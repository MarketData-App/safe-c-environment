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
        from policy import source_files
        self.source_files=source_files(Path('/src'))
        if self.request.get('demo_workspace'):
            self.source_files['demo/candidate.c']=file_hash(Path('/fixture/candidate.c'))
        self.restored=False
        self.invalidated=[]
        if request.get('state_restored'):
            from developer_state import restore
            prior=restore(BUILD,Path('/work/developer-state-input'),request['context_namespace'],self.policy['limits'])
            self.restored=True
            changed={('/fixture/candidate.c' if p=='demo/candidate.c' else '/src/'+p) for p in set(prior['source_files'])|set(self.source_files)
                     if prior['source_files'].get(p)!=self.source_files.get(p)}
            if changed:
                dependencies=self.run(['ninja','-C',str(BUILD),'-t','deps'],'incremental-dependencies')
                if not passed(dependencies):raise GateError('retained Ninja dependency inventory unavailable')
                current=None
                for line in dependencies['output'].splitlines():
                    if not line.startswith(' ') and ': #deps ' in line:
                        current=line.split(': #deps ',1)[0]
                    elif line.startswith('    ') and line.strip() in changed and current:
                        object_path=BUILD/current
                        if not object_path.is_relative_to(BUILD) or '..' in Path(current).parts:
                            raise GateError('Ninja dependency object outside private build')
                        if object_path.is_file():
                            object_path.unlink()
                            self.invalidated.append(current)

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
                              '-DSC_DEVELOPER_DEMO=' + ('ON' if self.request.get('demo_workspace') else 'OFF'),
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
            demo=self.request.get('demo_workspace') and actual['name']=='developer_demo'
            if demo:
                if set(sources)!={'/fixture/candidate.c','safety/qualification/developer/control.c'}:
                    raise GateError('isolated demo build source inventory mismatch')
                sources=['demo/candidate.c' if p=='/fixture/candidate.c' else p for p in sources]
            excluded = not demo and any(p not in declared or declared[p]['role'] == 'qualification-only' for p in sources)
            if not sources or excluded or re.match(r'^[CF]\d\d_', actual['name']):
                continue
            targets.append({'id': actual['name'], 'type': actual['type'],
                            'sources': sources, 'source_association': 'CMake File API',
                            'artifacts': [p['path'] for p in actual.get('artifacts', [])]})
        if not targets or len({t['id'] for t in targets}) != len(targets):
            raise GateError('empty or duplicate developer target discovery')
        self.targets = targets
        self.database = json.loads((BUILD / 'compile_commands.json').read_text())
        known_sources = {('/fixture/candidate.c' if source=='demo/candidate.c' else '/src/'+source) for t in targets for source in t['sources']}
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
        before={str(p.relative_to(BUILD)):(file_hash(p),p.stat().st_mtime_ns) for p in BUILD.rglob('*.o') if p.is_file()}
        built = self.run(['cmake', '--build', str(BUILD), '--target', *targets, '--parallel', '2'], 'build')
        if not passed(built):
            raise GateError('selected developer target build failed')
        after={str(p.relative_to(BUILD)):(file_hash(p),p.stat().st_mtime_ns) for p in BUILD.rglob('*.o') if p.is_file()}
        self.records[-1]['rebuilt_objects']=[p for p in after if before.get(p)!=after[p]]
        self.records[-1]['object_sha256']={p:r[0] for p,r in after.items()}
        return built

    def complete(self):
        self.configure()
        operation = self.request['operation']
        result = {'status': 'PASS', 'scope': 'partial_feedback', 'acceptance': False,
                  'profile': self.request['profile'], 'targets': self.targets,
                  'tests': self.tests, 'compile_commands_sha256': file_hash(BUILD / 'compile_commands.json')}
        if operation in {'doctor', 'prepare', 'tests'} or (operation=='test' and not self.tests):
            self.build([t['id'] for t in self.targets if t['type'] == 'EXECUTABLE'])
            # Re-discovery observes actual executable commands after build.
            self.configure()
            result.update(targets=self.targets, tests=self.tests)
        if operation == 'build':
            self.build([self.request['target']])
        elif operation == 'debug':
            from developer_gdb import inspect
            target = self.request.get('target')
            if target not in {t['id'] for t in self.targets if t['type']=='EXECUTABLE'}:
                raise GateError('unknown debug executable target')
            if self.request['recipe']=='breakpoint':
                path=self.request['location'].rpartition(':')[0]
                declared=json.loads(Path('/src/safety/source-inventory.json').read_text())['files']
                if path=='demo/candidate.c' and self.request.get('demo_workspace'):
                    actual=Path('/fixture/candidate.c')
                elif path in declared and (declared[path]['role']!='qualification-only' or
                        (self.request.get('demo_workspace') and path=='safety/qualification/developer/control.c')):
                    actual=Path('/src')/path
                else:
                    raise GateError('unregistered debug source location')
                if int(self.request['location'].rpartition(':')[2])>len(actual.read_text().splitlines()):
                    raise GateError('debug source line outside actual snapshot')
            self.build([target])
            result['debugger']=inspect(self.request,target,self.policy,OUTPUT)
            result['status']=result['debugger']['debug_session_status']
            for name in ['gdb-mi.opaque.log','inferior.opaque.log']:
                if (OUTPUT/name).is_file():self.artifacts.append(str((OUTPUT/name).relative_to('/work')))
        elif operation == 'test':
            selected = [t for t in self.tests if t['id'] == self.request['test_id']]
            if len(selected) != 1:
                raise GateError('unknown, empty or ambiguous developer test selection')
            self.build([selected[0]['target']])
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
        from developer_state import pack
        result['state']=pack(BUILD,Path('/work/developer-state-output'),self.request['context_namespace'],
                             self.policy['limits'],self.source_files)
        result['incremental']={'restored':self.restored,'invalidated_objects':self.invalidated,
                               'compiler_cache':'ABSENT','acceptance_cache_reuse':False}
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
