"""Project gate runner: the framework code gates applied to a project's own code.

Every native step runs in ONE protected `project` container from the SDK image;
the built program then starts once in a minimal runtime image. Compiler,
analyzer, sanitizer and fuzzer text stays in evidence files; the console gets
one line per gate and the verdict.
"""
from __future__ import annotations
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import io
import json
import posixpath
import re
import shlex
import shutil
import tarfile
import tempfile
import time
import uuid
from pathlib import Path
import policy
import project_model as pm
from foundation import analysis_flags
from evidence import GateError, RUNTIME_ENV, atomic_json, digest, environment_gate, file_hash, passed, read_json
from schema_check import validate

GATES = ('format', 'gcc-O0', 'gcc-O2', 'clang-O0', 'clang-O2', 'hardened', 'tidy', 'csa', 'gcc-analyzer', 'ast',
         'asan', 'ubsan', 'integer', 'msan', 'tsan', 'unit', 'integration', 'coverage', 'fuzz-replay',
         'fuzz-exploration', 'clusterfuzzlite', 'inventory', 'review-protocol')
# (gate, Safety.cmake profile, compiler, optimization), in execution order. Sanitizer
# profiles add -O1 in Safety.cmake. The asan profile is -fsanitize=address,undefined, a
# superset of ubsan, so ubsan and integer build and run before asan: an undefined-behavior
# defect then fails its own gate first. The report keeps the policy order (GATES).
BUILDS = (('gcc-O0', 'strict', 'gcc', 0), ('gcc-O2', 'strict', 'gcc', 2), ('clang-O0', 'strict', 'clang', 0),
          ('clang-O2', 'strict', 'clang', 2), ('hardened', 'hardened', 'clang', 2), ('ubsan', 'ubsan', 'clang', 0),
          ('integer', 'integer', 'clang', 0), ('asan', 'asan', 'clang', 0), ('msan', 'msan', 'clang', 0),
          ('tsan', 'tsan', 'clang', 0), ('coverage', 'coverage', 'clang', 0))
# Test failures in these builds belong to `unit`/`integration`; a test failure in a
# sanitizer or coverage build belongs to that build's gate, so one defect names one gate.
TEST_BUILDS = ('gcc-O0', 'gcc-O2', 'clang-O0', 'clang-O2', 'hardened')
ANALYZERS = ('tidy', 'csa', 'gcc-analyzer', 'ast')
# The order in which gates are decided. `unit` and `integration` are decided after the
# last TEST_BUILDS build, or right after the first test build whose tests fail.
EXECUTION_ORDER = ('inventory', 'review-protocol', 'format',
                   *(b[0] for b in BUILDS if b[0] in TEST_BUILDS), 'unit', 'integration',
                   *(b[0] for b in BUILDS if b[0] not in TEST_BUILDS), *ANALYZERS,
                   'clusterfuzzlite', 'fuzz-replay', 'fuzz-exploration')
HARDENED_FLAGS = ('-fstack-protector-strong', '-fstack-clash-protection', '-D_FORTIFY_SOURCE=3', '-fPIE')
FUZZ_ENV = {'CC': 'clang', 'CXX': 'clang++',
            'CFLAGS': '-O1 -g -fno-omit-frame-pointer -fsanitize=fuzzer-no-link,address,undefined -fno-sanitize-recover=all',
            'LIB_FUZZING_ENGINE': '-fsanitize=fuzzer'}
BLOCKING_STATES = {'OPEN', 'UNRESOLVED', 'BLOCKED'}
MIN_FUZZ_SECONDS = 30
# Launcher.create's default command sleeps 1800 s; the container ends then.
CONTAINER_SECONDS = 1800
CONTAINER_RESERVE = 60
NO_FUZZ = {'targets': 0, 'reason': 'no module reads external input'}
RUNTIME_BYTES = 8*1024*1024
CHUNK = 2*1024*1024
SANITIZERS = ('AddressSanitizer', 'LeakSanitizer', 'MemorySanitizer', 'ThreadSanitizer',
              'UndefinedBehaviorSanitizer', 'runtime error')
class InfrastructureError(GateError):
    """The container, Docker or its lifetime failed; the gate is BLOCKED, never a project FAIL."""


VERDICT_EXIT = {'PASS': 0, 'FAIL': 1, 'BLOCKED': 2, 'PASS_UNQUALIFIED_FRAMEWORK': 3}


# ---------------------------------------------------------------- pure helpers

def gate_plan(project_policy):
    """The 23 mandatory gates in policy order. A dropped, added or renamed gate stops the run."""
    gates = list(project_policy.get('gates', []))
    if gates != list(GATES):
        raise GateError('project policy gate list differs from the 23 mandatory project gates')
    seconds = project_policy.get('fuzz_seconds')
    if type(seconds) is not int or seconds < MIN_FUZZ_SECONDS:
        raise GateError('project fuzz exploration budget is below 30 seconds')
    return gates


def coverage_thresholds(root):
    value = read_json(Path(root)/'safety/contract.json')['coverage']
    line, branch = value.get('line'), value.get('branch')
    if type(line) is not int or type(branch) is not int or line < 90 or branch < 85:
        raise GateError('contract coverage thresholds are below 90% lines / 85% branches')
    return line, branch


def coverage_ok(summary, files, line, branch):
    """Check an `llvm-cov export -summary-only` value over the project files (paths relative to /src)."""
    wanted = set(files)
    details = {'thresholds': {'line': line, 'branch': branch}, 'files': {}, 'missing': [], 'totals': {}}
    found = {}
    try:
        for package in summary['data']:
            for item in package['files']:
                source = item['filename'].removeprefix('/src/')
                if source not in wanted:
                    continue
                if source in found:
                    raise ValueError('duplicate coverage file')
                found[source] = {k: {'count': int(item['summary'][k]['count']),
                                     'covered': int(item['summary'][k]['covered'])} for k in ('lines', 'branches')}
    except (KeyError, TypeError, ValueError, AttributeError):
        details['reason'] = 'malformed coverage summary'
        return False, details
    details['files'] = found
    details['missing'] = sorted(wanted - set(found))
    ok = not details['missing']
    for category, threshold in (('lines', line), ('branches', branch)):
        count = sum(v[category]['count'] for v in found.values())
        covered = sum(v[category]['covered'] for v in found.values())
        details['totals'][category] = {'count': count, 'covered': covered,
                                       'percent': round(100*covered/count, 2) if count else 0.0}
        ok = ok and count > 0 and 0 <= covered <= count and covered*100 >= threshold*count
    return ok, details


def parse_ctest_names(json_text):
    """Test names from `ctest --show-only=json-v1`, in CTest order."""
    try:
        value = json.loads(json_text)
    except ValueError as exc:
        raise GateError('CTest inventory is not JSON') from exc
    if not isinstance(value, dict) or not isinstance(value.get('tests'), list):
        raise GateError('CTest inventory has no test list')
    names = []
    for test in value['tests']:
        if not isinstance(test, dict) or not isinstance(test.get('name'), str) or not test['name']:
            raise GateError('CTest inventory entry has no name')
        names.append(test['name'])
    return names


def parse_failed_tests(output):
    """Names and reasons from the CTest 'The following tests FAILED' block."""
    block = output.split('The following tests FAILED:', 1)
    if len(block) != 2:
        return []
    return [{'name': m.group(1), 'reason': m.group(2)}
            for m in re.finditer(r'^\s*\d+ - (\S+) \(([^)\n]*)\)', block[1], re.M)][:50]


def detectors(output):
    return sorted({name for name in SANITIZERS if name in output})


_DIAGNOSTIC = re.compile(r'^(?P<file>[^:\n]+):(?P<line>\d+):(?:\d+:)? (?P<kind>error|warning): (?P<text>.*?)(?: \[(?P<check>[^\]\s]+)\])?$', re.M)


def diagnostics(output, limit=20):
    """File, line and check of compiler/analyzer diagnostics; no source excerpts."""
    rows = []
    for m in _DIAGNOSTIC.finditer(output):
        rows.append({'file': m.group('file').removeprefix('/src/'), 'line': int(m.group('line')),
                     'kind': m.group('kind'), 'check': m.group('check') or m.group('text')[:160]})
        if len(rows) >= limit:
            break
    return rows


def elf_hardened(text):
    """Structural hardening of one linked program from `readelf --wide -h -l -d -s`."""
    checks = {'pie': bool(re.search(r'Type:\s+DYN\b', text)), 'relro': 'GNU_RELRO' in text,
              'bind_now': 'BIND_NOW' in text, 'non_executable_stack': bool(re.search(r'GNU_STACK[^\n]*\bRW\b', text))}
    details = dict(checks, stack_protector_symbol='__stack_chk_fail' in text,
                   fortified_symbols=sorted(set(re.findall(r'\b__\w+_chk\b', text)) - {'__stack_chk_fail'}))
    return all(checks.values()), details


def fuzz_stats(output):
    """libFuzzer end-of-run counters: `-print_final_stats=1` stat lines and the final DONE line, both anchored."""
    executions = re.findall(r'^stat::number_of_executed_units: (\d+)$', output, re.M)
    done = re.findall(r'^#(\d+)\s+DONE\s+cov: (\d+) ft: (\d+)\b', output, re.M)
    return {'executions': int(executions[-1]) if executions else 0,
            'coverage_edges': int(done[-1][1]) if done else 0,
            'features': int(done[-1][2]) if done else 0}


def capped_timeout(requested, wall, deadline, now, reserve=CONTAINER_RESERVE):
    """Step timeout limited by the profile wall time and the container's remaining lifetime.

    Returns (timeout, capped_by_lifetime). Raises GateError when the lifetime is exhausted."""
    remaining = deadline - now - reserve
    if remaining < 1:
        raise InfrastructureError('project container lifetime exhausted before the step could run')
    timeout = min(requested, wall, remaining)
    return timeout, timeout == remaining and remaining < min(requested, wall)


def exec_infrastructure_error(result):
    """True when `docker exec` itself failed (daemon/runtime error), not the workload."""
    return result['exit_code'] in (125, 126, 127) and any(
        marker in result['output'] for marker in ('Error response from daemon', 'OCI runtime exec failed', 'is not running'))


def ctest_inventory_problems(names, expected):
    """Missing and extra CTest names against project.json; empty lists mean an exact match."""
    if names is None:
        return {'missing': sorted(expected['unit']+expected['integration']), 'extra': [], 'reason': 'CTest inventory unavailable'}
    wanted = set(expected['unit']+expected['integration'])
    duplicates = {n for n in names if names.count(n) > 1}
    return {'missing': sorted(wanted-set(names)), 'extra': sorted((set(names)-wanted) | duplicates)}


def verdict(rows, runtime_status, differences, development):
    statuses = [row['status'] for row in rows] + [runtime_status]
    if 'FAIL' in statuses:
        return 'FAIL', 1
    if any(s != 'PASS' for s in statuses):
        return 'BLOCKED', 2
    if differences:
        return ('PASS_UNQUALIFIED_FRAMEWORK', 3) if development else ('BLOCKED', 2)
    return 'PASS', 0


def _rel(project_dir, path):
    return posixpath.normpath(posixpath.join(project_dir, path))


def container_dir(project_dir):
    return posixpath.normpath('/src/'+project_dir)


def include_dir(project_dir):
    return posixpath.normpath('/src/'+project_dir+'/include')


def build_plan(project_dir):
    """Configure and build argv for every gate build; the root CMakeLists selects project mode."""
    rows = []
    for gate, profile, cc, opt in BUILDS:
        directory = f'project/{profile}-{cc}-O{opt}'
        rows.append({'gate': gate, 'profile': profile, 'compiler': cc, 'opt': opt, 'directory': directory,
                     'configure': ['cmake', '-S', '/src', '-B', '/work/'+directory, '-G', 'Ninja',
                                   '-DSAFE_C_PROJECT_DIR='+container_dir(project_dir), '-DCMAKE_C_COMPILER='+cc,
                                   '-DSAFETY_PROFILE='+profile, '-DSAFETY_CASE=NONE', '-DSAFETY_VARIANT=both',
                                   '-DCMAKE_C_FLAGS=-O'+str(opt), '-DFOUNDATION_CASE=NONE',
                                   '-DFOUNDATION_MUTANT=NONE', '-DFOUNDATION_DISABLED_GUARDS='],
                     'build': ['cmake', '--build', '/work/'+directory, '--parallel', '2', '--verbose']})
    return rows


def _unique(items):
    return list(dict.fromkeys(items))


def audit_sources(project_dir, project):
    """Translation units the CMake project build must compile, relative to /src."""
    files = [p for m in project['modules'] for p in m['sources']+m['tests']] + [p['main'] for p in project['programs']]
    return [_rel(project_dir, p) for p in _unique(files)]


def project_c_files(project_dir, project):
    files = [p for m in project['modules'] for p in m['sources']+m['tests']+[f['harness'] for f in m['fuzz']]]
    files += [p['main'] for p in project['programs']]
    return [_rel(project_dir, p) for p in _unique(files)]


def format_files(project_dir, project):
    headers = [h for m in project['modules'] for h in m['headers']]
    return project_c_files(project_dir, project) + [_rel(project_dir, h) for h in _unique(headers)]


def coverage_files(project_dir, project):
    files = [p for m in project['modules'] for p in m['sources']] + [p['main'] for p in project['programs']]
    return [_rel(project_dir, p) for p in _unique(files)]


def expected_tests(project):
    unit = ['project.'+m['name']+'.'+posixpath.basename(t).split('.')[0] for m in project['modules'] for t in m['tests']]
    return {'unit': unit, 'integration': ['project.run.'+project['run']['program']]}


def test_binaries(project):
    names = ['project_test_'+m['name']+'_'+posixpath.basename(t).split('.')[0] for m in project['modules'] for t in m['tests']]
    return names + [p['name'] for p in project['programs']]


def analyzer_argv(name, rel, index, project_dir):
    flags = analysis_flags('gcc-O0' if name == 'gcc-analyzer' else 'clang-O0') + ['-I'+include_dir(project_dir)]
    if name == 'tidy':
        return ['clang-tidy', '--config-file=/src/.clang-tidy', '/src/'+rel, '--', *flags]
    if name == 'csa':
        return ['clang', '--analyze', *flags, '-Xanalyzer', '-analyzer-output=text', '/src/'+rel,
                '-o', f'/work/project/analysis/csa-{index}.plist']
    if name == 'gcc-analyzer':
        return ['gcc', *flags, '-O0', '-fanalyzer', '-Wanalyzer-too-complex', '-Wanalyzer-symbol-too-complex',
                '-Werror', '-c', '/src/'+rel, '-o', f'/work/project/analysis/gcc-{index}.o']
    if name == 'ast':
        return ['python3', '/src/container/foundation-policy.py', rel, 'clang-O0', f'project-{index}',
                '--include', include_dir(project_dir)]
    raise GateError('unknown analyzer: '+name)


def fuzz_build_argv(project_dir, fuzz, module):
    return ['bash', '/src/container/project-fuzz-build.sh', project_dir, fuzz['name'], fuzz['harness'], *module['sources']]


def gate_row(name, status, details=None, evidence=()):
    return {'name': name, 'status': status, 'details': details or {}, 'evidence_paths': list(evidence)}


def inventory_gate(root, project_dir, project, framework_root):
    try:
        pm.project_inventory(root, project_dir, project, framework_root=framework_root)
    except GateError as exc:
        return gate_row('inventory', 'FAIL', {'reason': str(exc)})
    return gate_row('inventory', 'PASS', {'files': len(pm.project_files(root, project_dir))})


def review_gate(root, project_dir, framework_root):
    path = Path(root)/project_dir/'review/ledger.json'
    if path.is_symlink() or not path.is_file():
        return gate_row('review-protocol', 'FAIL', {'reason': 'review/ledger.json is missing'})
    try:
        value = read_json(path)
        validate(Path(framework_root), 'ledger', value)
    except (GateError, ValueError) as exc:
        return gate_row('review-protocol', 'FAIL', {'reason': 'review/ledger.json is invalid: '+str(exc)[:300]})
    blocking = [f['id'] for f in value['findings'] if f['state'] in BLOCKING_STATES
                and re.match(r'\s*(high|critical)\b', f['severity'], re.I)]
    details = {'findings': len(value['findings']), 'review_records': len(value['review']), 'blocking_findings': blocking}
    if blocking:
        details['reason'] = 'high-severity findings are OPEN, UNRESOLVED or BLOCKED'
        return gate_row('review-protocol', 'FAIL', details)
    return gate_row('review-protocol', 'PASS', details)


def framework_differences(root, framework_root, image_id):
    root = Path(root)
    if not (root/pm.MANIFEST).is_file() or (root/pm.MANIFEST).is_symlink():
        return ['missing: '+pm.MANIFEST]
    try:
        lines = pm.check_manifest(root, framework_root)
        images = read_json(root/pm.MANIFEST)['images']
    except (GateError, ValueError, KeyError) as exc:
        return ['invalid: '+pm.MANIFEST+': '+str(exc)[:200]]
    if images.get('sdk') != image_id:
        lines.append('image: the SDK image differs from the manifest')
    return lines


def project_identity(root, project_dir):
    files = pm.project_files(root, project_dir)
    files[pm.PROJECT_FILE] = file_hash(Path(root)/project_dir/pm.PROJECT_FILE)
    return digest(json.dumps(files, sort_keys=True, separators=(',', ':')).encode())


# ------------------------------------------------------------ container steps

class Stop(Exception):
    """A gate failed; later gates do not run."""


_CLOSURE = r'''
import json,os,re,subprocess,sys
dirs=['/lib/x86_64-linux-gnu','/usr/lib/x86_64-linux-gnu']
def dyn(path):
    out=subprocess.run(['readelf','--wide','-l','-d',path],capture_output=True,text=True,check=True).stdout
    return re.findall(r'Shared library: \[([^\]]+)\]',out),re.findall(r'Requesting program interpreter: ([^\]]+)\]',out)
needed,interp=dyn(sys.argv[1])
if len(interp)!=1 or interp[0]!='/lib64/ld-linux-x86-64.so.2':raise SystemExit(40)
libs={};queue=list(needed)
while queue:
    name=queue.pop(0)
    if name in libs:continue
    if '/' in name or not re.fullmatch(r'[A-Za-z0-9_.+-]+',name):raise SystemExit(41)
    found=[os.path.realpath(os.path.join(d,name)) for d in dirs if os.path.isfile(os.path.join(d,name))]
    if not found:raise SystemExit(42)
    libs[name]=found[0];queue+=dyn(found[0])[0]
print(json.dumps({'interpreter':interp[0],'interpreter_path':os.path.realpath(interp[0]),'libraries':libs}))
'''
_STAT = r'''
import hashlib,json,pathlib,stat,sys
p=pathlib.Path(sys.argv[1])
if any(x.is_symlink() for x in [p,*p.parents] if str(x).startswith('/work')):raise SystemExit(31)
m=p.stat()
if not stat.S_ISREG(m.st_mode) or m.st_size>int(sys.argv[2]):raise SystemExit(32)
print(json.dumps({'bytes':m.st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}))
'''
_CHUNK = 'import base64,pathlib,sys;d=pathlib.Path(sys.argv[1]).read_bytes()[int(sys.argv[2]):int(sys.argv[2])+int(sys.argv[3])];sys.stdout.write(base64.encodebytes(d).decode())'
_LIST = 'import json,pathlib,sys;print(json.dumps(sorted(str(p) for p in pathlib.Path(sys.argv[1]).iterdir())))'
_COPY = ('import pathlib,shutil,sys;s=pathlib.Path(sys.argv[1]);d=pathlib.Path(sys.argv[2]);d.mkdir(parents=True);'
         '[shutil.copyfile(x,d/("seed-%d"%i)) for i,x in enumerate(sorted(p for p in s.rglob("*") if p.is_file()))];'
         'pathlib.Path(sys.argv[3]).mkdir(parents=True)')


class ProjectCheck:
    def __init__(self, root, project_dir, project, run_dir, launcher, record, project_policy, *, snapshot, deadline):
        self.root, self.project_dir, self.project = root, project_dir, project
        self.run_dir, self.launcher, self.record = run_dir, launcher, record
        self.project_policy = project_policy
        self.snapshot, self.deadline = snapshot, deadline
        self.counter = 0
        self.rows = {}
        self.tests = {'unit': [], 'integration': []}
        self.builds = {}
        self.wall = launcher.value['profiles']['project']['wall_seconds']
        self.test_timeout = read_json(root/'safety/contract.json')['budgets']['timeout_seconds']

    def running(self):
        if self.record['lifecycle'] is not None:
            return False
        try:
            state = self.launcher.json(['inspect', self.record['container_id']])[0]['State']
        except (GateError, ValueError, KeyError, IndexError) as exc:
            raise InfrastructureError('infrastructure: project container inspection failed') from exc
        return bool(state.get('Running'))

    # One protected `docker exec` in the project container; evidence on disk.
    # Container or exec failures raise GateError (BLOCKED), never a project FAIL.
    def step(self, label, argv, *, timeout, env=None, keep_output=True):
        if not self.running():
            raise InfrastructureError('infrastructure: project container is not running before step '+label)
        timeout, capped = capped_timeout(timeout, self.wall, self.deadline, time.monotonic())
        self.counter += 1
        try:
            result = self.launcher.execute(self.record, argv, timeout=timeout, env=env)
        except GateError as exc:
            raise InfrastructureError('infrastructure: protected exec refused step '+label+': '+str(exc)[:200]) from exc
        saved = {k: v for k, v in result.items() if k not in ('effective_settings', 'runner_identity')}
        saved.update(command=list(argv), environment=dict(env or {}), label=label, timeout=timeout,
                     capped_by_container_lifetime=capped)
        if not keep_output:
            saved['output'] = f'<{len(result["output"])} bytes of transferred file content omitted>'
        path = self.run_dir/'evidence'/(f'{self.counter:04d}-'+re.sub(r'[^A-Za-z0-9_.-]', '_', label)[:80]+'.json')
        atomic_json(path, saved)
        result['evidence_path'] = str(path)
        if not passed(result):
            if result['failure'] == 'TIMEOUT' and capped:
                raise InfrastructureError('infrastructure: project container lifetime ended during step '+label)
            if exec_infrastructure_error(result):
                raise InfrastructureError('infrastructure: docker exec failed during step '+label)
            if result['failure'] is None and not self.running():
                raise InfrastructureError('infrastructure: project container stopped during step '+label)
        return result

    def set(self, name, status, details=None, evidence=()):
        self.rows[name] = gate_row(name, status, details, evidence)
        print(f'project gate {name}: {status}', flush=True)
        if status == 'FAIL':
            raise Stop(name)

    def read_text(self, label, path):
        r = self.step(label, ['cat', path], timeout=30)
        if not passed(r):
            raise GateError('unable to read build output: '+path)
        return r['output'], r['evidence_path']

    def fetch(self, label, path):
        r = self.step(label+'-stat', ['python3', '-c', _STAT, path, str(RUNTIME_BYTES)], timeout=30)
        if not passed(r):
            raise GateError('runtime file is not a bounded regular file: '+path)
        meta = json.loads(r['output'])
        data = bytearray()
        for offset in range(0, meta['bytes'], CHUNK):
            chunk = self.step(label+'-chunk', ['python3', '-c', _CHUNK, path, str(offset), str(CHUNK)], timeout=60, keep_output=False)
            if not passed(chunk):
                raise GateError('runtime file transfer failed: '+path)
            data.extend(base64.b64decode(chunk['output'], validate=False))
        if len(data) != meta['bytes'] or hashlib.sha256(data).hexdigest() != meta['sha256']:
            raise GateError('runtime file transfer changed bytes: '+path)
        return bytes(data)

    # ------------------------------------------------------------ phases
    def run(self):
        setup = self.step('setup', ['mkdir', '-p', '/work/project/analysis', '/work/project/profiles', '/work/project/fuzz'], timeout=10)
        if not passed(setup):
            raise GateError('project scratch preparation failed')
        self.format()
        for build in build_plan(self.project_dir):
            self.build(build)
            if build['gate'] == TEST_BUILDS[-1]:
                self.test_gates()
        self.coverage()
        for name in ANALYZERS:
            self.analyzer(name)
        self.fuzz()

    def format(self):
        files = ['/src/'+p for p in format_files(self.project_dir, self.project)]
        r = self.step('format', ['clang-format', '--style=file:/src/.clang-format', '--dry-run', '--Werror', *files], timeout=120)
        details = {'files': len(files)}
        if not passed(r):
            details['findings'] = diagnostics(r['output'])
        self.set('format', 'PASS' if passed(r) else 'FAIL', details, [r['evidence_path']])

    def build(self, build):
        gate, profile, directory = build['gate'], build['profile'], build['directory']
        evidence = []
        details = {'profile': profile, 'compiler': build['compiler'], 'opt': build['opt'], 'directory': directory}
        configure = self.step(gate+'-configure', build['configure'], timeout=300)
        evidence.append(configure['evidence_path'])
        if not passed(configure):
            details.update(stage='configure', findings=diagnostics(configure['output']))
            self.set(gate, 'FAIL', details, evidence)
        compiled = self.step(gate+'-build', build['build'], timeout=900)
        evidence.append(compiled['evidence_path'])
        if not passed(compiled):
            details.update(stage='build', findings=diagnostics(compiled['output']))
            self.set(gate, 'FAIL', details, evidence)
        from qualification import PROFILE_FLAGS
        try:
            text, path = self.read_text(gate+'-compile-database', '/work/'+directory+'/compile_commands.json')
            evidence.append(path)
            database = json.loads(text)
            details['build_audit'] = policy.build_audit(database, audit_sources(self.project_dir, self.project), profile)
            if profile == 'hardened':
                for row in database:
                    argv = row.get('arguments') or shlex.split(row['command'])
                    missing = [f for f in HARDENED_FLAGS if f not in argv]
                    if missing:
                        raise GateError('hardening flags missing: '+row['file'].removeprefix('/src/')+' '+' '.join(missing))
            links = self.step(gate+'-link-audit', ['ninja', '-C', '/work/'+directory, '-t', 'commands'], timeout=60)
            evidence.append(links['evidence_path'])
            if not passed(links):
                raise GateError('link command inventory unavailable')
            actual = [shlex.split(line) for line in links['output'].splitlines() if ' -o ' in line and ' -c ' not in line]
            if not actual:
                raise GateError('no final link commands')
            if profile in PROFILE_FLAGS and any(PROFILE_FLAGS[profile] not in row for row in actual):
                raise GateError('final link instrumentation missing')
            if profile == 'hardened' and any('-pie' not in row or '-Wl,-z,relro,-z,now,-z,noexecstack' not in row for row in actual):
                raise GateError('final link hardening missing')
        except InfrastructureError:
            raise
        except (GateError, ValueError, KeyError) as exc:
            details.update(stage='audit', reason=str(exc)[:300])
            self.set(gate, 'FAIL', details, evidence)
        if profile == 'hardened':
            programs = {}
            for program in self.project['programs']:
                elf = self.step('hardened-elf-'+program['name'], ['readelf', '--wide', '-h', '-l', '-d', '-s', '/work/'+directory+'/'+program['name']], timeout=30)
                evidence.append(elf['evidence_path'])
                ok, programs[program['name']] = elf_hardened(elf['output']) if passed(elf) else (False, {'reason': 'readelf failed'})
                if not ok:
                    details.update(stage='elf', programs=programs)
                    self.set(gate, 'FAIL', details, evidence)
            details['programs'] = programs
        tests = self.run_tests(gate, directory, profile, evidence)
        details['tests'] = tests
        if gate in TEST_BUILDS:
            for label in ('unit', 'integration'):
                self.tests[label].append({'build': gate, **tests[label]})
            self.set(gate, 'PASS', details, evidence)
            if any(tests[label]['status'] != 'PASS' for label in ('unit', 'integration')):
                self.test_gates()
        else:
            failed = [label for label in ('unit', 'integration') if tests[label]['status'] != 'PASS']
            if failed:
                details.update(stage='tests', failed_labels=failed)
                self.set(gate, 'FAIL', details, evidence)
            if gate != 'coverage':
                self.set(gate, 'PASS', details, evidence)
            else:
                self.builds['coverage'] = {'details': details, 'evidence': evidence, 'directory': directory}

    def run_tests(self, gate, directory, profile, evidence):
        env = dict(RUNTIME_ENV)
        if profile == 'coverage':
            env['LLVM_PROFILE_FILE'] = '/work/project/profiles/%m-%p.profraw'
        result = {}
        listing = self.step(gate+'-ctest-inventory', ['ctest', '--test-dir', '/work/'+directory, '--show-only=json-v1'], timeout=60)
        evidence.append(listing['evidence_path'])
        expected = expected_tests(self.project)
        try:
            names = parse_ctest_names(listing['output']) if passed(listing) else None
        except InfrastructureError:
            raise
        except GateError:
            names = None
        problems = ctest_inventory_problems(names, expected)
        for label in ('unit', 'integration'):
            if problems['missing'] or problems['extra']:
                result[label] = {'status': 'FAIL', 'reason': 'CTest inventory differs from project.json',
                                 'expected': expected[label], 'actual': names, **problems}
                continue
            r = self.step(f'{gate}-ctest-{label}', ['ctest', '--test-dir', '/work/'+directory, '--no-tests=error',
                                                    '--output-on-failure', '--timeout', str(self.test_timeout),
                                                    '-L', '^'+label+'$'], timeout=900, env=env)
            evidence.append(r['evidence_path'])
            row = {'status': 'PASS' if passed(r) else 'FAIL', 'tests': expected[label]}
            if not passed(r):
                row.update(failed_tests=parse_failed_tests(r['output']), detectors=detectors(r['output']),
                           failure=r['failure'])
            result[label] = row
        return result

    def test_gates(self):
        for label in ('unit', 'integration'):
            if label in self.rows:
                continue
            runs = self.tests[label]
            failed = [r for r in runs if r['status'] != 'PASS']
            complete = len(runs) == len(TEST_BUILDS)
            if failed:
                self.set(label, 'FAIL', {'builds': runs, 'failed_builds': [r['build'] for r in failed]})
            elif complete:
                self.set(label, 'PASS', {'builds': runs})

    def coverage(self):
        build = self.builds['coverage']
        details, evidence, directory = build['details'], build['evidence'], build['directory']
        line, branch = coverage_thresholds(self.root)
        listing = self.step('coverage-profiles', ['python3', '-c', _LIST, '/work/project/profiles'], timeout=30)
        evidence.append(listing['evidence_path'])
        profiles = json.loads(listing['output']) if passed(listing) else []
        if not profiles or any(not re.fullmatch(r'/work/project/profiles/[A-Za-z0-9_-]+\.profraw', p) for p in profiles):
            details.update(stage='coverage', reason='no test coverage profiles were written')
            self.set('coverage', 'FAIL', details, evidence)
        merged = self.step('coverage-merge', ['llvm-profdata', 'merge', '-sparse', *profiles, '-o', '/work/project/coverage.profdata'], timeout=120)
        evidence.append(merged['evidence_path'])
        binaries = ['/work/'+directory+'/'+name for name in test_binaries(self.project)]
        objects = [x for b in binaries[1:] for x in ('-object', b)]
        exported = self.step('coverage-export', ['llvm-cov', 'export', '-summary-only', binaries[0], *objects,
                                                 '-instr-profile=/work/project/coverage.profdata'], timeout=120)
        evidence.append(exported['evidence_path'])
        try:
            summary = json.loads(exported['output']) if passed(merged) and passed(exported) else {}
        except ValueError:
            summary = {}
        ok, result = coverage_ok(summary, coverage_files(self.project_dir, self.project), line, branch)
        details['coverage'] = result
        self.set('coverage', 'PASS' if ok else 'FAIL', details, evidence)

    def analyzer(self, name):
        evidence, failures = [], []
        files = project_c_files(self.project_dir, self.project)
        for index, rel in enumerate(files):
            r = self.step(f'{name}-{index}', analyzer_argv(name, rel, index, self.project_dir), timeout=300)
            evidence.append(r['evidence_path'])
            clean = passed(r)
            row = {'file': rel}
            if name == 'csa' and 'warning:' in r['output']:
                clean = False
            if name == 'ast':
                try:
                    value = json.loads(r['output'])
                    row['status'] = value.get('status') if isinstance(value, dict) else None
                except ValueError:
                    row['status'] = None
                clean = clean and row['status'] == 'PASS'
            if not clean:
                row['findings'] = diagnostics(r['output'])
                failures.append(row)
        self.set(name, 'FAIL' if failures else 'PASS', {'files': files, 'failures': failures}, evidence)

    def fuzz(self):
        targets = [(m, f) for m in self.project['modules'] for f in m['fuzz']]
        if not targets:
            for name in ('clusterfuzzlite', 'fuzz-replay', 'fuzz-exploration'):
                self.set(name, 'PASS', dict(NO_FUZZ))
            return
        built, evidence = {}, []
        for module, fuzz in targets:
            out = '/work/project/fuzz/'+fuzz['name']
            env = dict(FUZZ_ENV, OUT=out, WORK=out)
            r = self.step('clusterfuzzlite-'+fuzz['name'], fuzz_build_argv(self.project_dir, fuzz, module), timeout=600, env=env)
            evidence.append(r['evidence_path'])
            row = {'target': fuzz['name'], 'build': 'PASS' if passed(r) else 'FAIL'}
            if passed(r):
                objects = [f'{out}/module-{i}.o' for i in range(len(module['sources']))] + [out+'/harness.o']
                symbols = self.step('clusterfuzzlite-symbols-'+fuzz['name'], ['llvm-nm', '--undefined-only', *objects], timeout=60)
                evidence.append(symbols['evidence_path'])
                row['instrumentation'] = passed(symbols) and '__asan_report' in symbols['output'] and '__sanitizer_cov' in symbols['output']
            else:
                row['findings'] = diagnostics(r['output'])
            built[fuzz['name']] = row
        failed = [n for n, row in built.items() if row['build'] != 'PASS' or not row.get('instrumentation')]
        self.set('clusterfuzzlite', 'FAIL' if failed else 'PASS',
                 {'targets': list(built.values()), 'environment': FUZZ_ENV, 'failed_targets': failed}, evidence)
        base = self.snapshot/self.project_dir
        evidence, replayed, failures = [], 0, []
        for module, fuzz in targets:
            binary = f'/work/project/fuzz/{fuzz["name"]}/{fuzz["name"]}_fuzzer'
            for folder in (fuzz['regressions'], fuzz['corpus']):
                for path in sorted(p for p in (base/folder).rglob('*') if p.is_file()):
                    rel = _rel(self.project_dir, str(path.relative_to(base)))
                    r = self.step('fuzz-replay-'+fuzz['name'], [binary, '/src/'+rel, '-runs=1'], timeout=120, env=dict(RUNTIME_ENV))
                    evidence.append(r['evidence_path'])
                    replayed += 1
                    if not passed(r):
                        failures.append({'target': fuzz['name'], 'input': rel, 'detectors': detectors(r['output']), 'failure': r['failure']})
        self.set('fuzz-replay', 'FAIL' if failures or not replayed else 'PASS', {'inputs': replayed, 'failures': failures}, evidence)
        seconds = self.project_policy['fuzz_seconds']
        evidence, rows = [], []
        for module, fuzz in targets:
            work = '/work/project/fuzz/'+fuzz['name']
            corpus, failures_dir = work+'-corpus', work+'-failures'
            setup = self.step('fuzz-corpus-'+fuzz['name'], ['python3', '-c', _COPY, '/src/'+_rel(self.project_dir, fuzz['corpus']), corpus, failures_dir], timeout=60)
            evidence.append(setup['evidence_path'])
            if not passed(setup):
                raise GateError('fuzz exploration scratch preparation failed')
            r = self.step('fuzz-exploration-'+fuzz['name'], [work+'/'+fuzz['name']+'_fuzzer', corpus, '-seed=12345', '-max_len=4096',
                          '-timeout=3', '-rss_limit_mb=1024', '-print_final_stats=1', f'-max_total_time={seconds}', '-artifact_prefix='+failures_dir+'/'],
                          timeout=seconds+300, env=dict(RUNTIME_ENV))
            evidence.append(r['evidence_path'])
            crashes = self.step('fuzz-failures-'+fuzz['name'], ['python3', '-c', _LIST, failures_dir], timeout=30)
            evidence.append(crashes['evidence_path'])
            crashed = json.loads(crashes['output']) if passed(crashes) else ['failure inventory unavailable']
            stats = fuzz_stats(r['output'])
            ok = passed(r) and not crashed and stats['executions'] > 0 and stats['coverage_edges'] > 1 and r['seconds'] >= seconds
            rows.append({'target': fuzz['name'], 'status': 'PASS' if ok else 'FAIL', **stats, 'seed': 12345, 'budget_seconds': seconds,
                         'wall_seconds': r['seconds'], 'failure_artifacts': [posixpath.basename(c) for c in crashed],
                         'detectors': detectors(r['output']), 'failure': r['failure']})
        failed = [row['target'] for row in rows if row['status'] != 'PASS']
        self.set('fuzz-exploration', 'FAIL' if failed or not rows else 'PASS', {'targets': rows, 'failed_targets': failed}, evidence)

    # ------------------------------------------------------------ runtime
    def collect_runtime(self):
        program = self.project['run']['program']
        binary = '/work/project/hardened-clang-O2/'+program
        closure = self.step('runtime-closure', ['python3', '-c', _CLOSURE, binary], timeout=60)
        if not passed(closure):
            raise GateError('runtime shared-library closure is not a supported system closure')
        value = json.loads(closure['output'])
        members = {'bin/'+program: self.fetch('runtime-program', binary)}
        interpreter = value['interpreter'].lstrip('/')
        members[interpreter] = self.fetch('runtime-interpreter', value['interpreter_path'])
        for name, path in sorted(value['libraries'].items()):
            if name == posixpath.basename(interpreter):
                continue
            members['lib/x86_64-linux-gnu/'+name] = self.fetch('runtime-library', path)
        return members, closure['evidence_path']


def runtime_start(launcher, run_dir, project, members):
    program = project['run']['program']
    directory = run_dir/'runtime'
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory/'rootfs.tar'
    with tarfile.open(archive, 'w') as tar:
        for name, data in sorted(members.items()):
            info = tarfile.TarInfo(name)
            info.mode, info.uid, info.gid, info.mtime, info.size = 0o555, 0, 0, 0, len(data)
            tar.addfile(info, io.BytesIO(data))
    if archive.stat().st_size > RUNTIME_BYTES:
        raise GateError('project runtime archive exceeds the fixed bound')
    hashes = {name: digest(data) for name, data in members.items()}
    payload = digest(json.dumps(hashes, sort_keys=True).encode())
    tag = 'safe-c-project-runtime:'+payload[:24]
    label = 'org.safe-c.project-runtime=1'
    inspection = launcher.docker(['image', 'inspect', tag])
    if passed(inspection):
        image = json.loads(inspection['output'])[0]['Id']
    else:
        # Remove only this project's own earlier runtime images; never prune others.
        old = launcher.docker(['image', 'ls', '--filter', 'label='+label, '--filter', 'label=org.safe-c.project-name='+project['name'], '--format', '{{.ID}}'])
        for image_id in sorted(set(old['output'].split())) if passed(old) else []:
            launcher.docker(['image', 'rm', image_id], timeout=30)
        listed = launcher.docker(['image', 'ls', '--filter', 'label='+label, '--format', '{{.ID}}'])
        if not passed(listed) or len(set(listed['output'].split())) >= launcher.value['aggregate']['max_owned_images']:
            raise GateError('owned project runtime-image budget exhausted; remove obsolete project runtime images')
        c = launcher.value['common']
        imported = launcher.docker(['import', '--change', f"USER {c['uid']}:{c['gid']}", '--change', 'WORKDIR /work',
                                    '--change', 'CMD []', '--change', 'LABEL '+label,
                                    '--change', 'LABEL org.safe-c.project-name='+project['name'], str(archive), tag], timeout=60)
        if not passed(imported):
            raise GateError('bounded project runtime image assembly failed')
        image = imported['output'].strip()
    obj = launcher.json(['image', 'inspect', image])[0]
    if obj['Config'].get('Entrypoint') or obj['Config'].get('Volumes') or obj['Config'].get('Healthcheck') or obj['Size'] > RUNTIME_BYTES:
        raise GateError('project runtime image metadata or size mismatch')
    launcher.approved_runtime_images.add(image)
    record = launcher.create('runtime-demo', {}, image=image, command=['/bin/'+program, *project['run']['args']])
    try:
        waited = launcher.docker(['wait', record['container_id']], timeout=15)
        logged = launcher.docker(['logs', record['container_id']], timeout=5, limit=65536)
        host = launcher.json(['inspect', record['container_id']])[0]['HostConfig']
        p = record['plan']['resources']
        confined = (host['ReadonlyRootfs'] and host['CapDrop'] == ['ALL'] and not host['Privileged'] and host['NetworkMode'] == 'none'
                    and host['Memory'] == p['memory_bytes'] and host['PidsLimit'] == p['pids'])
        code = int(waited['output'].strip()) if passed(waited) and waited['output'].strip().lstrip('-').isdigit() else None
        lifecycle = launcher.dispose(record)
    except Exception:
        launcher.dispose(record)
        raise
    if not confined:
        raise GateError('project runtime container confinement mismatch')
    expected = project['run']['expect_exit']
    evidence = directory/'runtime-start.json'
    result = {'status': 'PASS' if code == expected else 'FAIL', 'program': program, 'args': project['run']['args'],
              'exit_code': code, 'expected_exit': expected, 'image_id': image, 'tag': tag, 'members': hashes,
              'container_id': record['container_id'], 'profile': 'runtime-demo', 'evidence_paths': [str(evidence)]}
    atomic_json(evidence, dict(result, output=logged['output'] if passed(logged) else '', lifecycle=lifecycle,
                               wait_failure=waited['failure']))
    return result


def complete_rows(rows, stopped_after):
    """All 23 rows in policy order; a gate without a decided row is BLOCKED."""
    reason = f'not run: gate {stopped_after} failed' if stopped_after else 'not run: run blocked'
    result = []
    for name in GATES:
        if name not in rows:
            rows[name] = gate_row(name, 'BLOCKED', {'reason': reason})
            print(f'project gate {name}: BLOCKED', flush=True)
        result.append(rows[name])
    return result


def snapshot_sources(root, scratch):
    snapshot = scratch/'source-snapshot'
    snapshot.mkdir()
    for relative in policy.source_files(root):
        destination = snapshot/relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root/relative, destination)
    for directory in ('src', 'include'):
        (snapshot/directory).mkdir(exist_ok=True)
    return snapshot


# ------------------------------------------------------------ entry points

def run_project_check(framework_root, project_dir='.', *, development=False):
    started = time.monotonic()
    root = Path(framework_root).resolve()
    run_id = uuid.uuid4().hex
    run_dir = root/'artifacts/project-runs'/run_id
    latest = root/'artifacts/project-report.json'
    # A stale report from an earlier run must never stand in for this run.
    if latest.is_file() or latest.is_symlink():
        latest.unlink()
    run_dir.mkdir(parents=True)
    report = {'schema_version': 1, 'run_id': run_id, 'project': None, 'project_dir': project_dir,
              'started_at': datetime.now(timezone.utc).isoformat(), 'finished_at': '', 'elapsed_seconds': 0.0,
              'development': bool(development), 'verdict': 'BLOCKED', 'exit_code': 2,
              'framework_identity': None, 'framework_differences': [], 'project_identity': None,
              'source_identity': None, 'image_id': None, 'gates': [],
              'runtime': {'status': 'BLOCKED', 'reason': 'not run'}, 'blockers': [], 'stopped_after': None,
              'evidence_directory': str(run_dir)}
    rows = {}
    launcher = None
    scratch = None
    try:
        environment_gate()
        project_policy = pm.project_policy(root)
        gate_plan(project_policy)
        lock = read_json(root/'toolchain.lock.json')
        report['image_id'] = lock['image_id']
        report['framework_identity'] = digest(json.dumps(pm.framework_files(root), sort_keys=True).encode())
        differences = framework_differences(root, root, lock['image_id'])
        report['framework_differences'] = differences
        if differences and not development:
            raise GateError('framework files differ from framework-manifest.json; ./tools/safety ci is required')
        project = pm.load_project(root, project_dir, framework_root=root)
        report['project'] = project['name']
        report['project_identity'] = project_identity(root, project_dir)
        report['source_identity'] = policy.source_identity(root)[0]
        for row in (inventory_gate(root, project_dir, project, root), review_gate(root, project_dir, root)):
            rows[row['name']] = row
            print(f'project gate {row["name"]}: {row["status"]}', flush=True)
        if any(r['status'] == 'FAIL' for r in rows.values()):
            raise Stop(next(r['name'] for r in rows.values() if r['status'] == 'FAIL'))
        from container_policy import Launcher
        scratch = Path(tempfile.mkdtemp(prefix='safe-c-project-'))
        snapshot = snapshot_sources(root, scratch)
        if policy.source_identity(snapshot)[0] != report['source_identity']:
            raise GateError('source changed during the immutable project snapshot')
        launcher = Launcher(root, run_dir, lock, purpose='project')
        deadline = time.monotonic()+CONTAINER_SECONDS
        record = launcher.create('project', {'/src': snapshot})
        atomic_json(run_dir/'container.json', {k: record.get(k) for k in ('container_id', 'name', 'profile', 'plan', 'policy_hash', 'runner', 'reservation', 'effective')})
        check = ProjectCheck(root, project_dir, project, run_dir, launcher, record, project_policy,
                             snapshot=snapshot, deadline=deadline)
        try:
            check.run()
        finally:
            rows.update(check.rows)
        members, closure_evidence = check.collect_runtime()
        launcher.dispose(record)
        report['runtime'] = runtime_start(launcher, run_dir, project, members)
        report['runtime']['evidence_paths'].insert(0, closure_evidence)
        print(f'project runtime {project["run"]["program"]}: {report["runtime"]["status"]}', flush=True)
    except Stop as stop:
        report['stopped_after'] = str(stop)
        report['runtime'] = {'status': 'BLOCKED', 'reason': f'not run: gate {stop} failed'}
    except Exception as exc:  # every other failure is infrastructure: BLOCKED, never a traceback
        # Only first-party GateError text is reported; other exception text may quote tool output.
        report['blockers'].append(f'{type(exc).__name__}: {str(exc)[:500]}' if isinstance(exc, GateError) else type(exc).__name__)
        report['runtime'] = dict(report['runtime'], status='BLOCKED')
    finally:
        if launcher is not None:
            try:
                launcher.close()
            except Exception as exc:
                report['blockers'].append('container cleanup: '+(str(exc)[:300] if isinstance(exc, GateError) else type(exc).__name__))
        if scratch is not None:
            shutil.rmtree(scratch, ignore_errors=True)
    report['gates'] = complete_rows(rows, report['stopped_after'])
    report['verdict'], report['exit_code'] = verdict(report['gates'], report['runtime']['status'],
                                                     report['framework_differences'], development)
    report['finished_at'] = datetime.now(timezone.utc).isoformat()
    report['elapsed_seconds'] = round(time.monotonic()-started, 1)
    try:
        validate(root, 'project-report', report)
    except Exception as exc:
        report['blockers'].append('report schema: '+(str(exc)[:300] if isinstance(exc, GateError) else type(exc).__name__))
        report['verdict'], report['exit_code'] = 'BLOCKED', 2
    atomic_json(run_dir/'project-report.json', report)
    atomic_json(root/'artifacts/project-report.json', report)
    for line in report['blockers']:
        print('project blocker: '+line, flush=True)
    print(f'project check verdict: {report["verdict"]} ({report["elapsed_seconds"]} s)', flush=True)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(prog='safety project check')
    parser.add_argument('--project', default='.')
    parser.add_argument('--development', action='store_true')
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    return run_project_check(root, args.project, development=args.development)['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())
