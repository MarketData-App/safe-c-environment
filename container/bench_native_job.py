"""Coordinator job `native-build` and the restored-binary check (Phase 2 Task 17, plan amendment FR6 N2).

Registered by one line in bench-coordinator.py; `g` is its globals(). Framework code, record-agnostic: it builds the declared
targets of the configured project with the hardened clang -O2 profile, runs the project's `run` entry once from the build
directory as a smoke and copies the targets to the job output. Build and smoke output go to a private log that is never
fetched. native_env verifies every restored binary and the locked GLib runtime before a child sees SAFE_C_BENCH_NATIVE.
(Not bench_native: tools/bench_native.py has that name, and the framework unit tests import both into one process.)"""
import hashlib, json, os, posixpath, re, shlex, shutil, stat, subprocess, time
from pathlib import Path

NATIVE_DIR=Path('/work/bench/private/native')
GLIB=Path('/opt/foundation/clang-O2/lib/libglib-2.0.so.0')
GLIB_NAME='libglib-2.0.so.0'
BUILD=Path('/work/native')
LOG=Path('/work/bench/private/native-build.log')
PROGRAM_RE=re.compile(r'^[a-z][a-z0-9_-]{0,62}$');LIBRARY_RE=re.compile(r'^lib([a-z][a-z0-9_]{0,62})\.so$')
SHA256_RE=re.compile(r'^[0-9a-f]{64}$')
MAX_TARGETS=32;MAX_COMMANDS=512;MAX_ARGS=400;MAX_ARG_CHARS=4096;MAX_JSON_BYTES=16*1024*1024;SMOKE_SECONDS=120
MISMATCH='restored native binary digest mismatch'
SHA256_INDEX='sha256.json'

def cmake_target(name):
    """The CMake target of a native target name (ValueError for any other name)."""
    m=LIBRARY_RE.fullmatch(name) if isinstance(name,str) else None
    if m:return 'project-library-'+m.group(1)
    if isinstance(name,str) and PROGRAM_RE.fullmatch(name):return name
    raise ValueError('native target name rejected')

def _sha256(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for chunk in iter(lambda:f.read(1<<20),b''):h.update(chunk)
    return h.hexdigest()

def _fd_sha256(fd):
    h=hashlib.sha256();offset=0
    while True:
        chunk=os.pread(fd,1<<20,offset)
        if not chunk:return h.hexdigest()
        h.update(chunk);offset+=len(chunk)

def _open_verified(path,digest):
    """N3-A01: path opened once (O_RDONLY | O_CLOEXEC | O_NOFOLLOW; O_NONBLOCK so that a FIFO cannot block the open), a
    regular file whose bytes read through that descriptor have digest: the descriptor. ValueError(MISMATCH) otherwise."""
    try:fd=os.open(path,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW|os.O_NONBLOCK)
    except OSError:raise ValueError(MISMATCH) from None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode) or _fd_sha256(fd)!=digest:raise ValueError(MISMATCH)
    except BaseException:
        os.close(fd);raise
    return fd

def _still_verified(path,fd,digest):
    """N3-A01: path still names the file behind fd (device and inode, no symlink) and that file still has digest."""
    try:now=os.stat(path,follow_symlinks=False)
    except OSError:return False
    held=os.fstat(fd)
    return (now.st_dev,now.st_ino)==(held.st_dev,held.st_ino) and _fd_sha256(fd)==digest

def native_env(plan):
    """{} for a plan without `native`. Otherwise every restored NATIVE_DIR/<name> must be a regular file with its planned
    sha256 (then mode 0o555), and the locked GLib runtime must have the planned digest: writes NATIVE_DIR/sha256.json (name ->
    sha256 of the restored binaries) and returns {'SAFE_C_BENCH_NATIVE': NATIVE_DIR}. ValueError('restored native binary digest mismatch') for anything else.
    N3-A01: each file is opened once, hashed and set to mode 0o555 through that descriptor; before sha256.json is written,
    each path must still name the verified file with the same bytes. This guards against an accidental change and a swap
    during the check, not against same-user code that changes a file later (each use verifies again, benchlab.native_worker
    open_verified)."""
    if 'native' not in plan:return {}
    value=plan['native']
    if (not isinstance(value,dict) or not 2<=len(value)<=MAX_TARGETS+1 or GLIB_NAME not in value
            or not all(isinstance(k,str) and isinstance(v,str) and SHA256_RE.fullmatch(v) for k,v in value.items())):raise ValueError(MISMATCH)
    held=[]
    try:
        for name,digest in value.items():
            if name==GLIB_NAME:continue
            try:cmake_target(name)
            except ValueError:raise ValueError(MISMATCH) from None
            path=NATIVE_DIR/name;fd=_open_verified(path,digest);held.append((path,fd,digest))
            os.fchmod(fd,0o555)
        real=GLIB.resolve();fd=_open_verified(real,value[GLIB_NAME]);held.append((real,fd,value[GLIB_NAME]))
        if not all(_still_verified(path,fd,digest) for path,fd,digest in held):raise ValueError(MISMATCH)
    finally:
        for _,fd,_ in held:os.close(fd)
    # Task 20 framework part (FR6-R3 item 4): name -> sha256 of the restored binaries, read by benchlab.native_worker.
    index=NATIVE_DIR/SHA256_INDEX;temporary=NATIVE_DIR/(SHA256_INDEX+'.tmp')
    temporary.write_text(json.dumps({k:v for k,v in sorted(value.items()) if k!=GLIB_NAME},sort_keys=True))
    os.chmod(temporary,0o444);os.replace(temporary,index)
    return {'SAFE_C_BENCH_NATIVE':str(NATIVE_DIR)}

def _fail(reason,**extra):return {'status':'FAIL','reason':reason,'files':[],**extra}

def _commands(project_src):
    """(argv of every project translation unit in the compile database, cut): bounded; `cut` is True when a unit, an
    argument or a character was dropped at a limit (N2-A02: the host then refuses the build). None without a database."""
    path=BUILD/'compile_commands.json'
    if path.is_symlink() or not path.is_file() or path.stat().st_size>MAX_JSON_BYTES:return None
    rows=[];cut=False
    for entry in json.loads(path.read_text()):
        source=entry.get('file') if isinstance(entry,dict) else None
        if not isinstance(source,str) or not posixpath.normpath(source).startswith(project_src+'/'):continue
        if len(rows)>=MAX_COMMANDS:cut=True;break
        argv=entry.get('arguments') if isinstance(entry.get('arguments'),list) else shlex.split(entry.get('command',''))
        cut=cut or len(argv)>MAX_ARGS or any(len(str(a))>MAX_ARG_CHARS for a in argv[:MAX_ARGS])
        rows.append([str(a)[:MAX_ARG_CHARS] for a in argv[:MAX_ARGS]])
    return rows,cut

def _compiler(env):
    try:run=subprocess.run(['clang','--version'],stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=30,env=env)
    except (OSError,subprocess.TimeoutExpired):return None
    lines=(run.stdout or '').splitlines()
    return lines[0][:200] if run.returncode==0 and lines else None

def build(plan,out,g):
    project_dir=plan.get('project_dir');targets=plan.get('targets')
    if g['PROJECT_ROOT'] is None or not isinstance(project_dir,str):return _fail('a native build needs a project')
    if not isinstance(targets,list) or not 1<=len(targets)<=MAX_TARGETS or len(set(map(str,targets)))!=len(targets):return _fail('native targets rejected')
    try:names=[cmake_target(t) for t in targets]
    except ValueError:return _fail('native targets rejected')
    project_src=posixpath.normpath('/src/'+project_dir)
    deadline=time.monotonic()+float(plan['deadline_seconds'])-30;env=g['child_env']()
    configure=['cmake','-S','/src','-B',str(BUILD),'-G','Ninja','-DSAFE_C_PROJECT_DIR='+project_src,'-DCMAKE_C_COMPILER=clang',
               '-DSAFETY_PROFILE=hardened','-DSAFETY_CASE=NONE','-DSAFETY_VARIANT=both','-DCMAKE_C_FLAGS=-O2','-DFOUNDATION_CASE=NONE',
               '-DFOUNDATION_MUTANT=NONE','-DFOUNDATION_DISABLED_GUARDS=']
    compile_=['cmake','--build',str(BUILD),'--parallel','2','--target',*names]
    with LOG.open('wb') as log:
        def step(argv,limit=None,cwd=None):
            remaining=deadline-time.monotonic()
            if remaining<=1:return None,'deadline'
            try:return subprocess.run(argv,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,env=env,cwd=cwd,
                                      timeout=min(remaining,limit or remaining)).returncode,None
            except subprocess.TimeoutExpired:return None,'timeout'
            except OSError as error:return None,type(error).__name__
        code,error=step(configure)
        if code!=0:return _fail('native configure failed',step_exit=code,step_error=error)
        code,error=step(compile_)
        if code!=0:return _fail('native build failed',step_exit=code,step_error=error)
        database=_commands(project_src)
        if database is None:return _fail('native compile database is missing')
        commands,commands_cut=database
        pj=g['PROJECT_ROOT']/'project.json'
        run=json.loads(pj.read_text()).get('run') if pj.is_file() and not pj.is_symlink() and pj.stat().st_size<=MAX_JSON_BYTES else None
        if (not isinstance(run,dict) or run.get('program') not in targets or not isinstance(run.get('args'),list)
                or not all(isinstance(a,str) for a in run['args'])):return _fail('the run program is not a native target')
        smoke_exit,smoke_error=step([str(BUILD/run['program']),*run['args']],SMOKE_SECONDS,str(BUILD))
    files={}
    for name in targets:
        source=BUILD/name
        if source.is_symlink() or not source.is_file():return _fail('native target is missing after the build')
        shutil.copyfile(source,out/name);files[name]=_sha256(out/name)
    glib=_sha256(GLIB.resolve()) if GLIB.resolve().is_file() else None
    row={'status':'PASS','files':list(targets),'sha256':files,'glib_sha256':glib,'compiler':_compiler(env),'commands':commands,'commands_cut':commands_cut,
         'smoke_exit':smoke_exit if smoke_exit is not None else -1}
    if smoke_error is not None:row['smoke_error']=smoke_error
    return row

# ---- Phase 2 Task 19 (FR6 N4): caller environment, job-end shared-memory check and native kernel trials ----
FRAMEWORK_PY='/src/benchmarks/performance/python'
SHM_LEFT='shared-memory segment left after the job'
KERNEL_DEADLINE_SHARE=0.5          # a kernel trial uses at most half of the job time left
_COORD={}                          # the coordinator globals (register)

def caller_env(plan):
    """The extra environment of a caller child: SAFE_C_BENCH_ROLE=caller and, with restored binaries, SAFE_C_BENCH_NATIVE
    (native_env verifies them; ValueError on a mismatch). Call it once per job."""
    return {'SAFE_C_BENCH_ROLE':'caller',**native_env(plan)}

def _benchlab(name):
    import importlib, sys
    if FRAMEWORK_PY not in sys.path:sys.path.append(FRAMEWORK_PY)
    return importlib.import_module('benchlab.'+name)

def native_shm_snapshot():
    """{'memfd': open memfd descriptors of this process and its descendants, 'dev_shm': /dev/shm entry names}."""
    snap=_benchlab('native_shm').snapshot()
    return {'memfd':list(snap['memfd']),'dev_shm':list(snap['shm'])}

def job_end_problems(before,after):
    """The memfd descriptors and /dev/shm entries in `after` that were not in `before` (one string each); [] when none."""
    return sorted(set(after['memfd'])-set(before['memfd']))+['/dev/shm/'+n for n in sorted(set(after['dev_shm'])-set(before['dev_shm']))]

def job_end_check(before):
    """Amendment F item 10 (d): the leftover list at the end of a job (after every child is reaped)."""
    return job_end_problems(before,native_shm_snapshot())

KERNEL_PACK_CODE=r"""
import json,sys
from benchlab.workload import load_case_adapter
a=load_case_adapter(json.load(open(sys.argv[1])));f=getattr(a,'pack_native',None)
callable(f) or sys.exit(3)
c=a.slice(a.load({'path':sys.argv[2],'sha256':sys.argv[3]}),int(sys.argv[4]))
open(sys.argv[5],'wb').write(bytes(f(c)))
"""
KERNEL_VERIFY_CODE=r"""
import json,sys
from benchlab.workload import load_case_adapter
from benchlab.trial import malformed_verdict, verdict_fields
a=load_case_adapter(json.load(open(sys.argv[1])))
u=getattr(a,'unpack_native',None);d=getattr(a,'native_reference_digest',None)
(callable(u) and callable(d)) or sys.exit(3)
n=int(sys.argv[4]);c=a.slice(a.load({'path':sys.argv[2],'sha256':sys.argv[3]}),n)
ref=a.slice_result(json.load(open(sys.argv[5])),n,c);res=u(open(sys.argv[6],'rb').read())
try:v=verdict_fields(a.validate(res,ref,c))
except ValueError as e:v=malformed_verdict(e)
print(json.dumps({'work_units':a.work_units(res),'result_sha256':a.digest(res),'canonical_ok':d(ref)==sys.argv[7],**v}))
"""

def _kernel_failure(name):
    return {'eligible':False,'failures':{name:1},'work_units':0,'result_sha256':None,'reduction':'NOT_RUN'}

PLACEHOLDER_RE=re.compile(r'^\{(input|records|loops|threads|output)\}$');LITERAL_RE=re.compile(r'^[A-Za-z0-9._=-]{1,64}$')

def kernel_argv(kernel,values):
    """The argv of the declared kernel: NATIVE_DIR/<program>, then each template argument (a literal, or a placeholder
    replaced by values[name]). ValueError for a malformed declaration (the container re-checks what the host checked)."""
    if not isinstance(kernel,dict) or set(kernel)!={'program','args'} or not isinstance(kernel['program'],str) or not PROGRAM_RE.fullmatch(kernel['program']):
        raise ValueError('kernel declaration rejected')
    args=kernel['args']
    if not isinstance(args,list) or not 4<=len(args)<=24 or not all(isinstance(a,str) and (PLACEHOLDER_RE.fullmatch(a) or LITERAL_RE.fullmatch(a)) for a in args):
        raise ValueError('kernel declaration rejected')
    if any(args.count('{'+k+'}')!=1 for k in ('input','records','loops','output')) or args.count('{threads}')>1:raise ValueError('kernel declaration rejected')
    return [str(NATIVE_DIR/kernel['program'])]+[str(values[a[1:-1]]) if PLACEHOLDER_RE.fullmatch(a) else a for a in args]

def run_native_kernel(channel,plan,trial,dataset,reference,deadline,out):
    """One C kernel trial (no Python in the timed loops): the adapter's pack_native(data) writes the packed input to the
    private tmpfs (an isolated child; the `prepare` phase), the declared kernel program runs through the kernel handshake
    from its verified descriptor, the cgroup counters are taken in on_begin and on_end (the bracket), and an isolated child
    checks the output: adapter.unpack_native and validate against the run reference (the reduction) and
    adapter.native_reference_digest of the reference against the kernel's canonical digest (PLK1 digest). Returns
    (observations, phases, files): one safe-c-trial-runner observation with self_timing and native_sha256. A kernel that
    cannot run (no declaration, refused binary, handshake failure) gives an ineligible row with a named failure; no other
    route replaces it."""
    g=_COORD['g'];nk=_benchlab('native_kernel');nw=_benchlab('native_worker')
    n=plan['sizes'][trial['tier']];loops=trial['loops'];tid=trial['trial_id']
    private=Path('/work/bench/private');private.mkdir(parents=True,exist_ok=True);src=private/f'{tid}.in';dst=private/f'{tid}.out'
    for f in (src,dst):f.unlink(missing_ok=True)
    kernel=plan.get('native_kernel');native=plan.get('native') or {};samples={};summary=None;note=None;prepare=None;digest=None
    left=lambda:max(1.0,(deadline-time.monotonic())*KERNEL_DEADLINE_SHARE)
    try:
        program=kernel.get('program') if isinstance(kernel,dict) else None
        if program not in native:raise ValueError('no kernel binary in the plan')
        digest=native[program]
        values={'input':str(src),'records':str(n),'loops':str(loops),'threads':'0' if trial['workers']=='direct' else str(trial['workers']),'output':str(dst)}
        argv=kernel_argv(kernel,values)
    except ValueError:note=_kernel_failure('native-declaration')
    if note is None:
        t0=time.perf_counter_ns()
        packed=subprocess.run(g['python_argv'](g['PYTHONPATH'],'-c',KERNEL_PACK_CODE,g['_manifest'](plan),dataset['path'],dataset['sha256'],str(n),str(src)),
                              env=g['child_env'](),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=left())
        prepare=time.perf_counter_ns()-t0
        if packed.returncode!=0 or not src.is_file():note=_kernel_failure('native-pack')
    if note is None:
        read=g['read_counters']
        try:
            got=nk.run_kernel(argv,env={},deadline=left(),on_begin=lambda:samples.__setitem__('b',read()),on_end=lambda:samples.__setitem__('e',read()),sha256=digest)
            summary=got['summary']
            ok=(got['exit']==0 and summary is not None and summary.get('status')=='OK' and summary.get('records')==n and summary.get('loops')==loops
                and type(summary.get('mono_ns')) is int and type(summary.get('cpu_ns')) is int and dst.is_file())
            if not ok:note=_kernel_failure('native-kernel')
        except nw.BinaryRefused:note=_kernel_failure('native-binary-refused')
        except nw.FrameError:note=_kernel_failure('native-handshake')
    if note is None:
        canonical=(summary.get('extra') or {}).get('digest','')
        canonical=canonical if isinstance(canonical,str) and LITERAL_RE.fullmatch(canonical) else 'none'
        check=subprocess.run(g['python_argv'](g['PYTHONPATH'],'-c',KERNEL_VERIFY_CODE,g['_manifest'](plan),dataset['path'],dataset['sha256'],str(n),reference,str(dst),canonical),
                             env=g['child_env'](),stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=left())
        try:row=json.loads(check.stdout.strip().splitlines()[-1]) if check.returncode==0 else None
        except (ValueError,IndexError):row=None
        if not isinstance(row,dict):note=_kernel_failure('native-verify')
        else:
            note={k:v for k,v in row.items() if k not in ('canonical_ok','eligible')}     # the verdict map of benchlab.trial.verdict_fields
            note['eligible']=bool(row.get('eligible')) and row.get('canonical_ok') is True
            if row.get('canonical_ok') is not True:note['failures']=dict(note.get('failures') or {},**{'canonical-digest':1})
    for f in (src,dst):f.unlink(missing_ok=True)
    now=g['read_counters']()
    b=samples.get('b',now);e=samples.get('e',now)
    note=dict(note,self_timing={'mono_ns':summary['mono_ns'],'cpu_ns':summary['cpu_ns']} if summary and type(summary.get('mono_ns')) is int and type(summary.get('cpu_ns')) is int else None,
              native_sha256=digest)
    obs=g['observation'](plan,trial,'work',{'sample':b,'msg':{}},{'sample':e,'msg':{'loops':loops,'phases':{'prepare':prepare}}},note,'safe-c-trial-runner',trial['warmup'])
    return [obs],[],[]

def register(job,g):
    _COORD.clear();_COORD.update({'g':g})
    @job('native-build')
    def job_native_build(plan,out):
        """Phase 2 Task 17: plan keys project_dir, targets, deadline_seconds."""
        return build(plan,out,g)
    return job_native_build
