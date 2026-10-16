"""Trusted, bounded host orchestration. Candidate processes receive no credentials."""
from __future__ import annotations
import hashlib
import json
import math
import os
from pathlib import Path
import selectors
import shutil
import signal
import stat
import subprocess
import time
import uuid

class GateError(RuntimeError):
    pass

def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def file_hash(path: Path) -> str:
    return digest(path.read_bytes())

# FR3-17 (ruling FR3-R7) and FR3-19 (ruling FR3-R9): one fail-closed boundary for every host parse of JSON that a project
# or a container can write. load_project_json reads project-controlled files (the protocol file, its approval record, its
# aggregate schema and oracle files, the local aggregate, bench.json, project case manifests and opportunity records,
# panel pre-flight and reference records, project.json, review/ledger.json and the owner confirmation). read_json,
# read_jsonl and loads_capped are capped readers built on the same code for every other JSON file, JSON-lines file and
# container output. Malformed data gives ProjectDataError (a GateError and a ValueError, exit 2), never another Python
# exception. Order: a size cap on the bytes, strict UTF-8, a nesting-depth cap checked on the raw text by an iterative
# scan before any parse (so json.loads can never reach RecursionError), then the parse, then the caller's validation
# inside the same boundary.
PROJECT_JSON_MAX_BYTES = 4194304          # 4 MiB: bench.json, case manifests, opportunity, pre-flight, project.json, owner confirmation
PROJECT_JSON_LARGE_BYTES = 16777216       # 16 MiB: protocol data files, panel references, review ledgers
PROJECT_JSON_MAX_DEPTH = 64               # nesting levels of arrays and objects; the deepest valid project file holds about 20
CAPPED_JSON_MAX_BYTES = 67108864          # 64 MiB: read_json, JSON-lines files and container output (twice the 32 MiB artifact cap)
CAPPED_JSON_MAX_DEPTH = 64                # the deepest tracked or recorded JSON document holds 14 levels
AST_JSON_MAX_DEPTH = 400                  # a clang JSON AST nests two levels per AST node

class ProjectDataError(GateError, ValueError):
    """A refusal of project-controlled or container-written JSON. `problem` is the stable name
    project-data-invalid:<kind>:<reason>; `original` is the type name of the exception that caused it (or None). The text
    holds no data of the document. It is also a ValueError, so a caller that handled a malformed document keeps doing so."""
    def __init__(self, kind, reason, label, original=None):
        self.problem = f'project-data-invalid:{kind}:{reason}'
        self.original = original
        super().__init__(f'{self.problem} ({label}{"; " + original if original else ""})')

class _Refused(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason

def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _Refused('duplicate-key')
        result[key] = value
    return result

def _no_constant(name):
    raise _Refused('non-finite-literal')

def _finite_float(text):
    """FR3-20: a number literal that parses to inf or -inf (for example 1e400) is a non-finite literal too."""
    value = float(text)
    if value in (math.inf, -math.inf):
        raise _Refused('non-finite-literal')
    return value

# One token: a complete string (possessive, so no backtracking), a bracket, or a quote that starts an unterminated string.
import re as _re
_JSON_TOKEN = _re.compile(r'"[^"\\]*+(?:\\.[^"\\]*+)*+"|[\[\]{}]|"', _re.S)

def json_too_deep(text, max_depth):
    """True when the arrays and objects of `text` nest deeper than `max_depth` levels. An iterative scan of the raw text
    in linear time: brackets inside strings (with backslash escapes) do not count, and the scan stops at an unterminated
    string (the parse fails there). It never recurses and never parses."""
    if text.count('[') + text.count('{') <= max_depth:
        return False              # FR3-R10: fewer openers than the cap can never nest past it
    depth = 0
    for match in _JSON_TOKEN.finditer(text):
        start = match.start()
        c = text[start]
        if c == '"':
            if match.end() - start == 1:
                break
        elif c == '[' or c == '{':
            depth += 1
            if depth > max_depth:
                return True
        else:
            depth -= 1
    return False

def _parse(data, kind, label, max_bytes, max_depth, unique_keys, finite):
    """The capped parse of bytes or text (a text is measured in characters, never more than its UTF-8 bytes)."""
    original = None
    try:
        if len(data) > max_bytes:
            raise _Refused('too-large')
        if isinstance(data, str):
            text = data
        else:
            try:
                text = bytes(data).decode('utf-8')
            except UnicodeDecodeError:
                original = 'UnicodeDecodeError'
                raise _Refused('not-utf-8') from None
        if json_too_deep(text, max_depth):
            raise _Refused('too-deep')
        try:
            hook = _unique_pairs if unique_keys is True else unique_keys if callable(unique_keys) else None
            return (json.loads(text, object_pairs_hook=hook, parse_constant=_no_constant, parse_float=_finite_float) if finite
                    else json.loads(text, object_pairs_hook=hook))
        except _Refused:
            raise
        except (ValueError, RecursionError, MemoryError) as exc:
            original = type(exc).__name__
            raise _Refused('not-json') from None
    except _Refused as refusal:
        raise ProjectDataError(kind, refusal.reason, label, original) from None

def read_capped(path, max_bytes, kind='json-file', label='JSON file'):
    """At most max_bytes bytes of a file; ProjectDataError too-large past it. An OSError passes unchanged."""
    with open(path, 'rb') as handle:
        data = handle.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ProjectDataError(kind, 'too-large', label)
    return data

def load_project_json(source, kind, max_bytes, max_depth=PROJECT_JSON_MAX_DEPTH, check=None, label=None,
                      unique_keys=True, finite=True, oserror=False):
    """The parsed value of project-controlled JSON. `source` is a path (read here, at most max_bytes + 1 bytes) or the
    bytes that the caller has already read under its own rules. `check(value)` runs inside the boundary: its GateError
    passes unchanged; any other exception becomes ProjectDataError with reason `exception` and the exception type name only.
    Refusals (each a ProjectDataError): too-large, unreadable, not-utf-8, too-deep, not-json, duplicate-key,
    non-finite-literal (NaN, Infinity, -Infinity and a number that parses to inf or -inf, FR3-20; only when `finite`). With `oserror`, an OSError of the read passes
    unchanged instead of `unreadable`."""
    label = label or kind
    if isinstance(source, (bytes, bytearray, str)):
        data = source
    else:
        try:
            data = read_capped(source, max_bytes, kind, label)
        except OSError as exc:
            if oserror:
                raise
            raise ProjectDataError(kind, 'unreadable', label, type(exc).__name__) from None
    value = _parse(data, kind, label, max_bytes, max_depth, unique_keys, finite)
    if check is not None:
        try:
            check(value)
        except GateError:
            raise
        except Exception as exc:
            raise ProjectDataError(kind, 'exception', label, type(exc).__name__) from None
    return value

def read_json(path: Path, max_bytes=CAPPED_JSON_MAX_BYTES, max_depth=CAPPED_JSON_MAX_DEPTH):
    """A JSON file through the boundary (FR3-19): at most 64 MiB and 64 levels, strict UTF-8, no duplicate key. NaN and
    Infinity stay allowed (atomic_json may write them). A missing or unreadable file raises its OSError as before."""
    return load_project_json(path, 'json-file', max_bytes, max_depth, label='JSON file', finite=False, oserror=True)

def loads_capped(data, kind='json-text', max_bytes=CAPPED_JSON_MAX_BYTES, max_depth=CAPPED_JSON_MAX_DEPTH, label=None,
                 object_pairs_hook=None):
    """json.loads of container output or of bytes read from a container-written file, through the boundary (FR3-19):
    the size and depth caps and strict UTF-8. Duplicate keys and NaN keep the json.loads behavior (or the caller's
    object_pairs_hook decides; its own exception passes unchanged)."""
    return _parse(data, kind, label or kind, max_bytes, max_depth, object_pairs_hook or False, False)

def read_jsonl(path, kind='jsonl-file', max_bytes=CAPPED_JSON_MAX_BYTES, max_depth=CAPPED_JSON_MAX_DEPTH):
    """The rows of a JSON-lines file through the boundary (FR3-19): the whole file at most max_bytes, each line capped like
    loads_capped. A missing or unreadable file raises its OSError."""
    data = read_capped(path, max_bytes, kind, 'JSON-lines file')
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        raise ProjectDataError(kind, 'not-utf-8', 'JSON-lines file', 'UnicodeDecodeError') from None
    return [loads_capped(line, kind, max_bytes, max_depth, 'JSON-lines file') for line in text.splitlines() if line.strip()]

def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp-' + uuid.uuid4().hex)
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    os.replace(tmp, path)

def bounded(argv, timeout=30, limit=4*1024*1024, env=None, cwd=None):
    """Kill/reap process groups; never confuse timeout/truncated output with success."""
    started = time.monotonic()
    process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               start_new_session=True, env=env, cwd=cwd)
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    output = bytearray()
    cause = None
    while selector.get_map():
        if time.monotonic() - started > timeout:
            cause = 'TIMEOUT'
            break
        for key, _ in selector.select(.05):
            data = os.read(key.fileobj.fileno(), 65536)
            if not data:
                selector.unregister(key.fileobj)
            else:
                output.extend(data)
                if len(output) > limit:
                    cause = 'OUTPUT_LIMIT'
                    break
        if cause:
            break
    if cause:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        code = process.wait(timeout=max(.1, timeout - (time.monotonic()-started)))
    except subprocess.TimeoutExpired:
        cause = 'TIMEOUT'
        os.killpg(process.pid, signal.SIGKILL)
        code = process.wait()
    selector.close()
    process.stdout.close()
    return {'argv': list(argv), 'exit_code': code, 'failure': cause,
            'seconds': round(time.monotonic()-started, 4),
            'evidence_complete':cause is None,
            'output': bytes(output[:limit]).decode('utf-8', errors='replace')}

PROHIBITED_ENV = ('LIT_OPTS', 'FILECHECK_OPTS', 'ASAN_OPTIONS', 'LSAN_OPTIONS',
                  'MSAN_OPTIONS', 'TSAN_OPTIONS', 'UBSAN_OPTIONS', 'LLVM_PROFILE_FILE',
                  'CFLAGS', 'CXXFLAGS', 'CPPFLAGS', 'LDFLAGS', 'CMAKE_ARGS',
                  'CTEST_TEST_ARGS', 'CTEST_PARALLEL_LEVEL', 'LD_PRELOAD', 'LD_LIBRARY_PATH',
                  'CPATH', 'C_INCLUDE_PATH', 'CPLUS_INCLUDE_PATH', 'LIBRARY_PATH',
                  'PKG_CONFIG_PATH', 'PKG_CONFIG_LIBDIR', 'G_DEBUG', 'G_SLICE')
# Every sanitizer value names a nonzero exit code: the environment overrides options
# that code compiled into a program (a *_default_options hook) may set.
RUNTIME_ENV = {'ASAN_OPTIONS': 'detect_leaks=1:detect_stack_use_after_return=1:halt_on_error=1:symbolize=1:exitcode=21',
               'LSAN_OPTIONS': 'exitcode=23',
               'UBSAN_OPTIONS': 'halt_on_error=1:print_stacktrace=1:exitcode=22',
               'MSAN_OPTIONS': 'halt_on_error=1:exit_code=24:exitcode=24:print_stats=1',
               'TSAN_OPTIONS': 'halt_on_error=1:exitcode=25',
               'ASAN_SYMBOLIZER_PATH': '/usr/lib/llvm-19/bin/llvm-symbolizer'}

def environment_gate(environment=None):
    inherited = os.environ if environment is None else environment
    bad = [key for key in PROHIBITED_ENV if inherited.get(key)]
    if bad:
        raise GateError('prohibited inherited options: ' + ', '.join(bad))

# A session older than HOLDER_SECONDS-SESSION_MARGIN_SECONDS is renewed at the next
# gate boundary, so no single step runs into the holder's end.
SESSION_MARGIN_SECONDS = 600

class Runner:
    def __init__(self, root: Path, run_dir: Path, lock, scratch: Path, *, build_profile="build", purpose="qualification", source_root=None, fixture_root=None, file_mounts=None, redacted=False, input_root=None):
        if build_profile not in {"build", "dependency-build", "bench"}:raise GateError("unapproved build adapter profile")
        self.build_profile=build_profile
        self.file_mounts=dict(file_mounts) if file_mounts else None
        self.redacted=bool(redacted)
        self.input_root=Path(input_root).resolve() if input_root is not None else None
        self.root, self.run_dir, self.lock, self.scratch = root.resolve(), run_dir, lock, scratch.resolve()
        self.source_root = Path(source_root).resolve() if source_root is not None else self.root
        self.fixture_root = Path(fixture_root) if fixture_root is not None else None
        scratch.mkdir(parents=True, exist_ok=True)
        run_dir.mkdir(parents=True, exist_ok=True)
        self.counter=0;self.records=[];self.alive=False;self.session=None
        self.session_started=None
        self.collected_bytes=0;self.collected_files=0
        self.collection_sizes={}
        self.collection_digests={}      # DD-01: destination -> sha256 of the bytes that collect fetched
        from container_policy import Launcher
        self.launcher=Launcher(self.root,self.run_dir,lock,purpose=purpose)

    def start(self):
        if self.alive:return
        from policy import source_files
        snapshot=self.scratch/'source-snapshot'
        if snapshot.exists():shutil.rmtree(snapshot)
        snapshot.mkdir()
        for relative in source_files(self.source_root):
            destination=snapshot/relative;destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(self.source_root/relative,destination)
        for directory in ['src','include']:(snapshot/directory).mkdir(exist_ok=True)
        from policy import write_tracked_manifest
        write_tracked_manifest(self.source_root,snapshot)     # T27-03: the host tracked set, outside the source identity
        self.snapshot=snapshot
        mounts={'/src':snapshot}
        if self.fixture_root is not None:
            from developer_workspace import descriptor
            _,fixture_files=descriptor(self.root,self.fixture_root)
            self.fixture_snapshot=self.scratch/'fixture-snapshot'
            self.fixture_snapshot.mkdir()
            for name in fixture_files:
                target=self.fixture_snapshot/name
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(self.fixture_root/name,target)
            if {name:file_hash(self.fixture_snapshot/name) for name in fixture_files}!=fixture_files:
                raise GateError('developer fixture changed during immutable snapshot creation')
            mounts['/fixture']=self.fixture_snapshot
        if self.input_root is not None:
            # Regular files only, copied into a private snapshot mounted read-only at /inputs.
            self.input_snapshot=self.scratch/'inputs-snapshot'
            if self.input_snapshot.exists():shutil.rmtree(self.input_snapshot)
            self.input_snapshot.mkdir()
            for source in sorted(self.input_root.rglob('*')):
                mode=source.lstat().st_mode
                if stat.S_ISDIR(mode):continue
                if not stat.S_ISREG(mode):raise GateError('input snapshot accepts regular files only')
                target=self.input_snapshot/source.relative_to(self.input_root)
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(source,target)
            mounts['/inputs']=self.input_snapshot
        self.session=self.launcher.create(self.build_profile,mounts,file_mounts=self.file_mounts,redacted=self.redacted)
        self.name=self.session['container_id'];self.alive=True;self.session_started=self.clock()
        from containment import expected_binding
        from policy import source_identity
        self.input_binding=expected_binding(self.root,self.launcher.runner_identity,
                                            self.lock['image_id'],self.launcher.value)
        if self.source_root != self.root:
            self.input_binding['source']=source_identity(self.source_root)[0]
        if self.fixture_root is not None:
            self.input_binding['developer_demo']=fixture_files
        if source_identity(snapshot)[0] != self.input_binding['source']:
            raise GateError('source changed during immutable job snapshot creation')
        for key,path in [('dependency','foundation.lock.json'),
                         ('api_policy','safety/foundation-api-policy.json'),
                         ('fixture_inventory','safety/foundation-fixtures.json')]:
            if (snapshot/path).is_file():self.input_binding[key]=file_hash(snapshot/path)

    def close(self):
        self.launcher.close();self.alive=False

    @staticmethod
    def clock():
        return time.monotonic()

    def release(self):
        """Dispose the idle session container through the launcher. The next run
        creates a fresh session; Qualifier builds from the old one are redone."""
        if self.session is not None and self.session.get('lifecycle') is None:
            self.launcher.dispose(self.session)
        self.alive=False;self.session=None;self.session_started=None

    def refresh(self, *, idle=False):
        """Gate boundary. `idle=True` before a step that leaves the session unused for
        a long time (developer suite, starter child ci); otherwise renew a session that
        is close to the holder lifetime. Returns True when the session was released."""
        from container_policy import HOLDER_SECONDS
        if not self.alive:return False
        if idle or self.session_started is None or self.clock()-self.session_started>=HOLDER_SECONDS-SESSION_MARGIN_SECONDS:
            self.release();return True
        return False

    def collect(self,session,relative,destination):
        import base64
        p=Path(relative)
        if p.is_absolute() or '..' in p.parts or not p.parts:raise GateError('unsafe scratch artifact path')
        c=self.launcher.value['common']
        # Validate every component, including parents. All bytes are capped before
        # reading; no symlink/special file may become a collected artifact.
        script="""import pathlib,base64,sys,stat
p=pathlib.Path('/work')
for part in pathlib.Path(sys.argv[1]).parts:
 p=p/part
 if p.is_symlink():raise SystemExit(31)
m=p.stat()
if not stat.S_ISREG(m.st_mode) or m.st_size>int(sys.argv[2]):raise SystemExit(32)
print(base64.b64encode(p.read_bytes()).decode())"""
        self.launcher.verify_session(session)
        result=self.launcher.docker(['exec',session['container_id'],'python3','-c',script,relative,str(c['artifact_bytes'])],timeout=30,limit=c['artifact_bytes']*2)
        if not passed(result):raise GateError('artifact collection refused or unavailable: '+relative)
        data=base64.b64decode(result['output'].strip(),validate=True)
        destination=Path(destination).absolute()
        previous=self.collection_sizes.get(str(destination),0)
        new_file=str(destination) not in self.collection_sizes
        if len(data)>c['artifact_bytes'] or self.collected_bytes-previous+len(data)>c['artifact_total_bytes'] or self.collected_files+int(new_file)>c['artifact_files']:raise GateError('artifact collector budget exceeded')
        if not any(destination.is_relative_to(base.absolute()) for base in [self.scratch,self.run_dir]):raise GateError('collector destination outside owned evidence')
        if any(x.is_symlink() for x in [destination,*destination.parents]):raise GateError('collector destination link rejected')
        destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(data)
        self.collected_bytes+=len(data)-previous;self.collected_files+=int(new_file)
        self.collection_sizes[str(destination)]=len(data)
        self.collection_digests[str(destination)]=digest(data)
        return destination

    def fetch(self,relative,destination=None):
        self.start()
        return self.collect(self.session,relative,destination or self.scratch/relative)

    def restore(self,relative,path,fetched=None,label=None):
        # Transfer finite chunks rather than one argv-sized base64 blob. Native
        # jobs and the builder keep the same mounts and resource ceilings.
        # DD-01: a collected file is handed on only when its bytes still have the
        # sha256 recorded when collect fetched them: `fetched` (passed on with a
        # shared file to the Runner of a later check) or this Runner's own
        # collection record. Only a host-made input (never collected, e.g. the
        # plan) takes its digest from the bytes read here.
        # DD-02: every restore writes its own receipt, transfers/<sha>[-<label>]
        # [-<n>].json, where label names the destination job (other characters
        # become '-', at most 96) and n counts the earlier receipts of the same
        # name, so no receipt overwrites another.
        import base64, re
        p=Path(relative);path=Path(path).absolute()
        if label is not None and type(label) is not str:raise GateError('transfer receipt label is not text')
        if fetched is None:fetched=self.collection_digests.get(str(path))
        if fetched is not None and not (type(fetched) is str and re.fullmatch(r'[0-9a-f]{64}',fetched)):
            raise GateError('malformed fetched artifact digest')
        if p.is_absolute() or '..' in p.parts or not p.parts:
            raise GateError('unsafe artifact restore path')
        if (not any(path.is_relative_to(base.absolute()) for base in [self.scratch,self.run_dir]) or
                any(x.is_symlink() for x in [path,*path.parents]) or not path.is_file() or
                path.stat().st_size>self.launcher.value['common']['artifact_bytes']):
            raise GateError('unapproved artifact restore source')
        data=path.read_bytes();expected=digest(data) if fetched is None else fetched
        if digest(data)!=expected:raise GateError('artifact restore source differs from the fetched bytes')
        pending=relative+'.restore-'+uuid.uuid4().hex
        deadline=time.monotonic()+30
        receipt={'source_sha256':expected,'destination':relative,'bytes':len(data),'label':label,
                 'input_binding':dict(self.input_binding),'steps':[],'status':'FAIL'}
        name=expected+('-'+re.sub(r'[^A-Za-z0-9._-]','-',label)[:96] if label else '');count=1
        while (self.run_dir/'transfers'/(name+('' if count==1 else f'-{count}')+'.json')).exists():count+=1
        evidence=self.run_dir/'transfers'/(name+('' if count==1 else f'-{count}')+'.json')
        def step(stage,args):
            remaining=deadline-time.monotonic()
            if remaining<=0:raise GateError('finite artifact transfer deadline exhausted')
            result=self.launcher.execute(self.session,args,timeout=remaining)
            receipt['steps'].append({'stage':stage,'exit_code':result['exit_code'],
                'failure':result['failure'],'evidence_complete':result['evidence_complete']})
            if not passed(result):
                atomic_json(evidence.with_name(evidence.stem+'-failed-stage.json'),result)
                raise GateError('collected artifact transfer failed')
        prepare="""import pathlib,sys
p=pathlib.Path('/work')
for part in pathlib.Path(sys.argv[1]).parts:
 p=p/part
 if p.is_symlink():raise SystemExit(31)
p.parent.mkdir(parents=True,exist_ok=True)
(pathlib.Path('/work')/sys.argv[2]).open('xb').close()
"""
        try:
            step('prepare',['python3','-c',prepare,relative,pending])
            for offset in range(0,len(data),65536):
                chunk=base64.b64encode(data[offset:offset+65536]).decode()
                step('chunk',['python3','-c',
                    'import pathlib,base64,sys;p=pathlib.Path("/work")/sys.argv[1];'
                    '\nif p.is_symlink() or p.stat().st_size!=int(sys.argv[2]):raise SystemExit(31)\n'
                    'p.open("ab").write(base64.b64decode(sys.argv[3],validate=True))',
                    pending,str(offset),chunk])
            finish="""import hashlib,pathlib,sys,os
p=pathlib.Path('/work')/sys.argv[1]
if p.is_symlink() or hashlib.sha256(p.read_bytes()).hexdigest()!=sys.argv[3]:raise SystemExit(32)
os.replace(p,pathlib.Path('/work')/sys.argv[2])
"""
            step('verify-and-publish',['python3','-c',finish,pending,relative,expected])
            if file_hash(path)!=expected:raise GateError('artifact transfer source changed')
            receipt['status']='PASS'
        finally:
            atomic_json(evidence,receipt)

    def native(self,args,timeout,settings):
        from container_policy import policy_hash
        binary=args[0][len('/work/'):]
        path=self.fetch(binary)
        inputs=self.scratch/('native-input-'+str(self.counter));inputs.mkdir()
        shutil.copy2(path,inputs/'target')
        (inputs/'target').chmod(0o555)
        profile='test-asan' if binary.startswith('benchmark') else 'fuzz' if binary.startswith('adapter/') or 'fuzz' in binary.split('/')[1] else 'test-'+binary.split('/')[1].split('-')[0] if binary.startswith('build/') else 'test-ordinary'
        if profile not in self.launcher.value['profiles']:profile='test-ordinary'
        session=self.launcher.create(profile,{'/src':self.snapshot,'/inputs':inputs})
        try:
            corpus_profiles={'/work/exploration-corpus':'/src/fuzz/corpus','/work/foundation-exploration-corpus':'/src/foundation/corpus'}
            active_corpora=[path for path in corpus_profiles if path in args]
            if len(active_corpora)>1:raise GateError('ambiguous fuzz corpus profile')
            active_corpus=active_corpora[0] if active_corpora else None
            if active_corpus:
                setup=self.launcher.execute(session,['python3','-c','import pathlib,shutil,sys;p=pathlib.Path(sys.argv[1]);p.mkdir();[shutil.copyfile(x,p/x.name) for x in pathlib.Path(sys.argv[2]).iterdir() if x.is_file()];pathlib.Path("/work/fuzz-failures").mkdir()',active_corpus,corpus_profiles[active_corpus]],timeout=10)
                if not passed(setup):raise GateError('fresh fuzz scratch preparation failed')
            before_events=self.launcher.counters(session['effective']['cgroup_path'])
            result=self.launcher.execute(session,['/inputs/target',*args[1:]],timeout=min(timeout,self.launcher.value['profiles'][profile]['wall_seconds']),env=settings)
            after_events=session['lifecycle']['counters_after'] if session['lifecycle'] else self.launcher.counters(session['effective']['cgroup_path'])
            from containment import counters
            if counters(after_events['memory.events'])['oom']>counters(before_events['memory.events'])['oom']:
                result['failure']='CGROUP_OOM';result['evidence_complete']=False
            if counters(after_events['pids.events'])['max']>counters(before_events['pids.events'])['max']:
                result['failure']='PID_LIMIT';result['evidence_complete']=False
            result['cgroup_events']={'before':before_events,'after':after_events}
            result['binary_sha256']=file_hash(inputs/'target');result['binary_unchanged']=file_hash(inputs/'target')==file_hash(path)
            if result['failure'] is None:
                if settings.get('LLVM_PROFILE_FILE'):
                    relative=settings['LLVM_PROFILE_FILE'].removeprefix('/work/')
                    collected=self.collect(session,relative,self.scratch/'native-output'/relative);self.restore(relative,collected)
                if active_corpus:
                    listing=self.launcher.execute(session,['python3','-c','import pathlib,json,sys;print(json.dumps([str(p.relative_to("/work")) for d in [sys.argv[1],"fuzz-failures"] for p in pathlib.Path("/work",d).iterdir()]))',active_corpus.removeprefix("/work/")],timeout=10)
                    if not passed(listing):raise GateError('live fuzz artifact inventory failed')
                    for relative in loads_capped(listing['output']):
                        if not __import__('re').fullmatch(r'(exploration-corpus|foundation-exploration-corpus|fuzz-failures)/[a-zA-Z0-9_-]+',relative):raise GateError('unsafe fuzz output name')
                        collected=self.collect(session,relative,self.scratch/'native-output'/relative);self.restore(relative,collected)
            result['lifecycle']=self.launcher.dispose(session)
            from container_policy import completion_gate
            completion_gate(result,result['lifecycle'])
            return result
        finally:
            self.launcher.dispose(session);shutil.rmtree(inputs,ignore_errors=True)

    def ctest(self,args,timeout,settings,*,targets=None,profile='test-strict'):
        directory=args[args.index('--test-dir')+1].removeprefix('/work/')
        inputs=self.scratch/('ctest-input-'+str(self.counter));inputs.mkdir()
        hashes={}
        targets=targets or ['infrastructure_demo','hardening_probe']
        if (not targets or len(set(targets))!=len(targets) or
                any(not __import__('re').fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}',t) for t in targets)):
            raise GateError('invalid selected CTest target inventory')
        if profile not in {'test-ordinary','test-strict','test-asan','test-ubsan','test-integer','test-msan','test-tsan','test-coverage','test-hardened'}:
            raise GateError('unapproved selected CTest runtime profile')
        for target in targets:
            p=self.fetch(directory+'/'+target);hashes[target]=file_hash(p)
            shutil.copy2(p,inputs/target);(inputs/target).chmod(0o555)
        config=self.fetch(directory+'/CTestTestfile.cmake')
        (inputs/'CTestTestfile.cmake').write_text(config.read_text().replace('/work/'+directory,'/inputs'))
        session=self.launcher.create(profile,{'/src':self.snapshot,'/inputs':inputs})
        argv=list(args);argv[argv.index('--test-dir')+1]='/work/ctest'
        try:
            setup=self.launcher.execute(session,['python3','-c','import pathlib,shutil;p=pathlib.Path("/work/ctest");p.mkdir();shutil.copyfile("/inputs/CTestTestfile.cmake",p/"CTestTestfile.cmake")'],timeout=5)
            if not passed(setup):raise GateError('fresh CTest scratch preparation failed')
            result=self.launcher.execute(session,argv,timeout=min(timeout,10),env=settings)
            if '--output-junit' in args and result['failure'] is None:
                relative=args[args.index('--output-junit')+1].removeprefix('/work/')
                self.collect(session,relative,self.run_dir/'selected-ctest.xml')
            if profile=='test-coverage' and result['failure'] is None:
                if settings.get('LLVM_PROFILE_FILE')!='/work/selected.profraw':
                    raise GateError('selected coverage output path not fixed')
                self.collect(session,'selected.profraw',self.run_dir/'selected.profraw')
            result['test_binary_hashes']=hashes;result['lifecycle']=self.launcher.dispose(session)
            from container_policy import completion_gate
            completion_gate(result,result['lifecycle'])
            return result
        finally:self.launcher.dispose(session);shutil.rmtree(inputs,ignore_errors=True)

    def run(self,args,*,timeout=30,env=None,label='process',ctest_targets=None,runtime_profile=None):
        self.start();self.counter+=1
        settings=dict(RUNTIME_ENV);settings.update(env or {})
        if args[0]=='ctest' and '--no-tests=error' in args:
            result=self.ctest(args,timeout,settings,targets=ctest_targets,profile=runtime_profile or 'test-strict')
        elif str(args[0]).startswith('/work/'):
            result=self.native(args,timeout,settings)
        else:
            result=self.launcher.execute(self.session,args,timeout=timeout,env=settings)
            if result['failure']:self.alive=False
        result['command']=list(args);result['image_id']=self.lock['image_id']
        result['environment']=settings
        result['input_binding']=dict(self.input_binding)
        filename=f'{self.counter:04d}-{label}.json'
        result['evidence_path']=str(self.run_dir/'evidence'/filename)
        atomic_json(Path(result['evidence_path']),result);self.records.append(result)
        return result

def passed(result):
    return result['exit_code'] == 0 and result['failure'] is None
