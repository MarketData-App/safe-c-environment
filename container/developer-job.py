"""Finite developer build/discovery job; launched only by the protected runner.

Selected native tests are returned to the outer controller for their own bounded
test-profile container. No test is executed in this build container.
"""
from pathlib import Path
import json
import re
import shlex
import sys
import time

sys.path.insert(0, '/src/tools')
from evidence import bounded, atomic_json, GateError, passed, file_hash

BUILD = Path('/work/developer-build')
OUTPUT = Path('/work/developer-job')


class Job:
    def __init__(self, request):
        self.request = request
        self.policy = json.loads(Path('/src/safety/developer-policy.json').read_text())
        self.profile = self.policy['profiles'][request['profile']]
        self.lock = json.loads(Path('/src/toolchain.lock.json').read_text())
        self.started = time.monotonic()
        self.records = []
        self.artifacts = []
        OUTPUT.mkdir()

    def run(self, argv, name, timeout=30):
        remaining = self.policy['limits']['job_wall_seconds'] - (time.monotonic() - self.started) - 3
        if remaining <= 0:
            raise GateError('developer job overall deadline exhausted')
        record = bounded(argv, timeout=min(timeout, remaining), limit=4194304)
        path = OUTPUT / (str(len(self.records)) + '-' + name + '.json')
        atomic_json(path, record)
        self.artifacts.append(str(path.relative_to('/work')))
        self.records.append({'name': name, 'exit_code': record['exit_code'],
                             'failure': record['failure'], 'seconds': record['seconds'],
                             'complete_capture': record['evidence_complete']})
        return record

    def configure(self):
        query = BUILD / '.cmake/api/v1/query'
        query.mkdir(parents=True, exist_ok=True)
        (query / 'codemodel-v2').write_text('')
        (query / 'toolchains-v1').write_text('')
        compiler = self.lock['tools'][self.profile['compiler']]['path']
        configured = self.run(['cmake', '-S', '/src', '-B', str(BUILD), '-G', 'Ninja',
                              '-DCMAKE_C_COMPILER=' + compiler,
                              '-DSAFETY_PROFILE=' + self.profile['safety_profile'],
                              '-DCMAKE_C_FLAGS=' + self.profile['flags'],
                              '-DSC_DEVELOPER_CONTEXT=ON'], 'configure')
        if not passed(configured):
            raise GateError('developer CMake configuration failed')
        indexes = sorted((BUILD / '.cmake/api/v1/reply').glob('index-*.json'))
        if len(indexes) != 1:
            raise GateError('ambiguous or missing actual CMake reply')
        index = json.loads(indexes[0].read_text())
        reply = BUILD / '.cmake/api/v1/reply'
        model = json.loads((reply / index['reply']['codemodel-v2']['jsonFile']).read_text())
        if len(model['configurations']) != 1:
            raise GateError('developer configuration must select one actual build graph')
        declared = json.loads(Path('/src/safety/source-inventory.json').read_text())['files']
        targets = []
        for target in model['configurations'][0]['targets']:
            actual = json.loads((reply / target['jsonFile']).read_text())
            sources = [p['path'].removeprefix('/src/') for p in actual.get('sources', [])
                       if p['path'].endswith('.c')]
            if (not sources or any(p not in declared or declared[p]['role'] == 'qualification-only'
                                   for p in sources) or re.match(r'^[CF]\d\d_', actual['name'])):
                continue
            targets.append({'id': actual['name'], 'type': actual['type'],
                            'sources': sources, 'source_association': 'CMake File API',
                            'artifacts': [p['path'] for p in actual.get('artifacts', [])]})
        if not targets or len({t['id'] for t in targets}) != len(targets):
            raise GateError('empty or duplicate developer target discovery')
        self.targets = targets
        self.database = json.loads((BUILD / 'compile_commands.json').read_text())
        known_sources = {'/src/' + source for t in targets for source in t['sources']}
        seen = set()
        for row in self.database:
            if row['file'] not in known_sources or row['directory'] != str(BUILD):
                raise GateError('compilation database includes an unregistered development entry')
            argv = row.get('arguments') or shlex.split(row['command'])
            if (not argv or argv[0] != compiler or '-std=c17' not in argv or
                    any(x.startswith(('-fplugin', '-ivfsoverlay', '-include-pch')) or
                        x in {'-load', '-plugin'} for x in argv)):
                raise GateError('developer compiler/standard/plugin context rejected')
            # Multiple actual commands for the same shared source are retained;
            # a position query must explicitly select its including target/TU.
            seen.add(row['file'])
        if seen != known_sources:
            raise GateError('actual development compilation context incomplete')
        discovered = self.run(['ctest', '--test-dir', str(BUILD), '--show-only=json-v1'], 'test-discovery')
        if not passed(discovered):
            raise GateError('actual developer CTest discovery failed')
        tests = []
        for test in json.loads(discovered['output'])['tests']:
            command = test.get('command', [])
            if not command:
                # CTest omits the executable from discovery until its target is
                # built. Do not invent a mapping or claim an executable test.
                continue
            target = Path(command[0]).name
            if target not in {t['id'] for t in targets}:
                raise GateError('developer CTest command references an unregistered target')
            tests.append({'id': test['name'], 'target': target, 'command': command,
                          'labels': next((p['value'] for p in test.get('properties', [])
                                          if p['name'] == 'LABELS'), []),
                          'association': 'actual CTest executable command'})
        self.tests = tests

    def build(self, targets):
        if not targets or any(t not in {r['id'] for r in self.targets} for t in targets):
            raise GateError('unknown or empty developer target selection')
        built = self.run(['cmake', '--build', str(BUILD), '--target', *targets, '--parallel', '2'], 'build')
        if not passed(built):
            raise GateError('selected developer target build failed')
        return built

    def complete(self):
        self.configure()
        operation = self.request['operation']
        result = {'status': 'PASS', 'scope': 'partial_feedback', 'acceptance': False,
                  'profile': self.request['profile'], 'targets': self.targets,
                  'tests': self.tests, 'compile_commands_sha256': file_hash(BUILD / 'compile_commands.json')}
        if operation in {'doctor', 'prepare', 'tests', 'test'}:
            self.build([t['id'] for t in self.targets if t['type'] == 'EXECUTABLE'])
            # Re-discovery observes actual executable commands after build.
            self.configure()
            result.update(targets=self.targets, tests=self.tests)
        if operation == 'build':
            self.build([self.request['target']])
        elif operation == 'test':
            selected = [t for t in self.tests if t['id'] == self.request['test_id']]
            if len(selected) != 1:
                raise GateError('unknown, empty or ambiguous developer test selection')
            result['selected_test'] = selected[0]
        elif operation == 'doctor':
            observed = self.run(['python3', '/src/container/developer-probe.py'], 'tool-capability-probe')
            if not passed(observed):
                raise GateError('actual confined developer tool capability probe failed')
            result['capabilities'] = json.loads(Path('/work/developer-probe/summary.json').read_text())
            # Keep the detailed debugger record opaque in the collector.
            for name in ['summary.json', 'gdb.opaque.log', 'clangd-check.opaque.log']:
                target = OUTPUT / ('prerequisite-' + name)
                target.write_bytes((Path('/work/developer-probe') / name).read_bytes())
                self.artifacts.append(str(target.relative_to('/work')))
        elif operation == 'nav':
            from developer_lsp import navigate
            if self.request.get('file', '').endswith('.h'):
                including = '/src/' + self.request.get('tu', '')
                commands = [row for row in self.database if row['file'] == including]
                if len(commands) != 1:
                    raise GateError('header including TU context missing or ambiguous')
                actual = commands[0].get('arguments') or shlex.split(commands[0]['command'])
                preprocessing, cursor = [], 0
                while cursor < len(actual):
                    if actual[cursor] == '-o':
                        cursor += 2
                    elif actual[cursor] == '-c':
                        cursor += 1
                    else:
                        preprocessing.append(actual[cursor])
                        cursor += 1
                dependency_file = OUTPUT / 'header-context.d'
                dependencies = self.run([*preprocessing, '-M', '-MT', 'SC_DEVELOPER_DEPENDENCIES',
                                         '-MF', str(dependency_file)], 'header-context')
                if not passed(dependencies):
                    raise GateError('actual including TU dependency observation failed')
                headers = shlex.split(dependency_file.read_text().replace('\\\n', ' ').split(':', 1)[1])
                if '/src/' + self.request['file'] not in headers:
                    raise GateError('requested header is not included by the selected actual TU')
                self.artifacts.append(str(dependency_file.relative_to('/work')))
            try:
                result['navigation'] = navigate(self.request, self.database, self.targets, self.policy)
            finally:
                for name in ['clangd.opaque.log', 'lsp-transport.opaque.jsonl']:
                    if (OUTPUT / name).is_file():
                        self.artifacts.append(str((OUTPUT / name).relative_to('/work')))
        return result


if __name__ == '__main__':
    job = None
    try:
        selected = json.loads(sys.argv[1])
        job = Job(selected)
        result = job.complete()
        result.update(steps=job.records, artifacts=job.artifacts)
        print(json.dumps(result, ensure_ascii=True))
    except Exception as error:
        print(json.dumps({'status': 'FAIL', 'error_type': type(error).__name__,
                          'property': str(error) if isinstance(error, GateError) else None,
                          'steps': job.records if job else [],
                          'artifacts': job.artifacts if job else []}))
        raise SystemExit(1)
