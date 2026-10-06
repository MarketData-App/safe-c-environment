"""Trusted, bounded host orchestration. Candidate processes receive no credentials."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import selectors
import shutil
import signal
import subprocess
import time
import uuid

class GateError(RuntimeError):
    pass

def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def file_hash(path: Path) -> str:
    return digest(path.read_bytes())

def read_json(path: Path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise GateError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(path.read_text(), object_pairs_hook=unique)

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

class Runner:
    def __init__(self, root: Path, run_dir: Path, lock, scratch: Path, *, build_profile="build", purpose="qualification", source_root=None, fixture_root=None):
        if build_profile not in {"build", "dependency-build"}:raise GateError("unapproved build adapter profile")
        self.build_profile=build_profile
        self.root, self.run_dir, self.lock, self.scratch = root.resolve(), run_dir, lock, scratch.resolve()
        self.source_root = Path(source_root).resolve() if source_root is not None else self.root
        self.fixture_root = Path(fixture_root) if fixture_root is not None else None
        scratch.mkdir(parents=True, exist_ok=True)
        run_dir.mkdir(parents=True, exist_ok=True)
        self.counter=0;self.records=[];self.alive=False;self.session=None
        self.collected_bytes=0;self.collected_files=0
        self.collection_sizes={}
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
        self.session=self.launcher.create(self.build_profile,mounts)
        self.name=self.session['container_id'];self.alive=True
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
        return destination

    def fetch(self,relative,destination=None):
        self.start()
        return self.collect(self.session,relative,destination or self.scratch/relative)

    def restore(self,relative,path):
        # Transfer finite chunks rather than one argv-sized base64 blob. Native
        # jobs and the builder keep the same mounts and resource ceilings.
        import base64
        p=Path(relative);path=Path(path).absolute()
        if p.is_absolute() or '..' in p.parts or not p.parts:
            raise GateError('unsafe artifact restore path')
        if (not any(path.is_relative_to(base.absolute()) for base in [self.scratch,self.run_dir]) or
                any(x.is_symlink() for x in [path,*path.parents]) or not path.is_file() or
                path.stat().st_size>self.launcher.value['common']['artifact_bytes']):
            raise GateError('unapproved artifact restore source')
        expected=file_hash(path);data=path.read_bytes()
        if digest(data)!=expected:raise GateError('artifact restore source changed')
        pending=relative+'.restore-'+uuid.uuid4().hex
        deadline=time.monotonic()+30
        receipt={'source_sha256':expected,'destination':relative,'bytes':len(data),
                 'input_binding':dict(self.input_binding),'steps':[],'status':'FAIL'}
        evidence=self.run_dir/'transfers'/(expected+'.json')
        def step(stage,args):
            remaining=deadline-time.monotonic()
            if remaining<=0:raise GateError('finite artifact transfer deadline exhausted')
            result=self.launcher.execute(self.session,args,timeout=remaining)
            receipt['steps'].append({'stage':stage,'exit_code':result['exit_code'],
                'failure':result['failure'],'evidence_complete':result['evidence_complete']})
            if not passed(result):
                atomic_json(evidence.with_name(expected+'-failed-stage.json'),result)
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
                    for relative in json.loads(listing['output']):
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
