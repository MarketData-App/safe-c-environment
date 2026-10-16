#!/usr/bin/env python3
"""Protected in-container bench coordinator: cgroup counters, handshakes, trial runner.

Framework code, not candidate code. It prints one JSON result line for a non-local
job and nothing for a local job; it never prints dataset content."""
from pathlib import Path
import hashlib, importlib, json, math, os, platform, re, selectors, signal, socket, subprocess, sys, time

CG=Path('/sys/fs/cgroup');WORK=Path('/work')
PYTHONPATH='/opt/bench-python:/src/benchmarks/performance/python'
FRAMEWORK_PYTHONPATH=PYTHONPATH
THREAD_ENV=('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS')
MANDATORY=('cpu.stat','memory.current','memory.stat','pids.current','cgroup.procs')
CPU_KEYS=('usage_usec','user_usec','system_usec','nr_throttled','throttled_usec')
MEM_KEYS=('anon','file','shmem')
JOBS={}
SRC=Path('/src')
PROJECT_RE=re.compile(r'^(\.|[A-Za-z0-9_][A-Za-z0-9._-]*(/[A-Za-z0-9_][A-Za-z0-9._-]*)*)$');ARG_RE=re.compile(r'^[A-Za-z0-9._:/-]{1,128}$')
FILE_RE=re.compile(r'^[A-Za-z0-9._-]{1,80}$')
WHEEL_MODULES=frozenset({'numpy','pyperf','psutil'})
STARTUP_HOOKS=frozenset({'sitecustomize','usercustomize'})
FRAMEWORK_PACKAGES=frozenset({'benchlab','tests'})
FRAMEWORK_PY=Path('/src/benchmarks/performance/python')
PROJECT_PY=None;PROJECT_ROOT=None
POOLED=('py-threads','py-processes')
NAME_RE=re.compile(r'^[a-z][a-z0-9-]{2,40}$');MODULE_RE=re.compile(r'^[a-z_][a-z0-9_.]{0,80}$')
LABEL_RE=re.compile(r'^[A-Za-z0-9 ._:,()=+-]{0,120}$');COUNT_RE=re.compile(r'^[a-z][a-z0-9_]{0,40}$')
MAX_FILES=32;MAX_COUNTS=32     # ruling T28-C2: a row with more count keys FAILs (check_result), never truncated
MAX_PROJECT_CHECKS=32          # schemas/bench-project.json checks maxItems (9dcb0e8; a project with 19 declared checks motivated the bound)

def reserved_modules():
    """plan L7: this interpreter's stdlib names ('_' names included), the startup hooks, the bench wheel modules and
    every top-level framework package."""
    try:present={p.name.split('.')[0] for p in FRAMEWORK_PY.iterdir() if not p.name.startswith(('.','__'))}
    except OSError:present=set()
    return set(sys.stdlib_module_names)|WHEEL_MODULES|STARTUP_HOOKS|FRAMEWORK_PACKAGES|present

def inside(path,top):
    """The fully resolved path (every link on the way) lies inside the resolved directory `top`."""
    top=Path(top).resolve();real=Path(path).resolve()
    return real==top or top in real.parents

def inside_src(path):
    """Review fix: the fully resolved path (every link on the way) lies inside /src."""
    return inside(path,SRC)

def case_manifest_allowed(path):
    """Task 13a residual: a case manifest is a .json file (not a link) that resolves inside the framework cases directory or,
    with a configured project, inside that project's benchmarks/project/cases; never elsewhere in /src."""
    if not isinstance(path,str) or len(path)>400 or not path.endswith('.json') or Path(path).is_symlink():return False
    tops=[SRC/'benchmarks/performance/cases']+([PROJECT_PY.parent/'cases'] if PROJECT_PY is not None else [])
    return any(inside(path,top) and Path(path).resolve()!=Path(top).resolve() for top in tops)

# Review fix: every child that may import project code starts isolated (-I: no PYTHONPATH, no user site, no script
# directory), so no startup hook (sitecustomize, usercustomize, .pth) from a project path can run. The bootstrap then
# puts the explicit path list first and runs the module or code. Spawned pool workers inherit -I and this sys.path.
BOOT=('import sys;sys.dont_write_bytecode=True;sys.path[0:0]=[x for x in sys.argv[1].split(":") if x]\n'
      'mode,target=sys.argv[2],sys.argv[3];sys.argv=[target]+sys.argv[4:]\n'
      'if mode=="-m":\n import runpy;runpy.run_module(target,run_name="__main__",alter_sys=True)\n'
      'else:exec(compile(target,"<bench>","exec"),{"__name__":"__main__"})\n')

def python_argv(path,mode,target,*args):
    if mode not in ('-m','-c'):raise ValueError('mode is -m or -c')
    return [sys.executable,'-I','-c',BOOT,path,mode,target,*[str(a) for a in args]]

def configure_project(plan):
    """Amendment A: the project package goes after the framework package on the import path; the path is confined to /src."""
    global PYTHONPATH,PROJECT_PY,PROJECT_ROOT
    d=plan.get('project_dir')
    if d is None:return None
    if not isinstance(d,str) or len(d)>200 or not PROJECT_RE.fullmatch(d) or '..' in d.split('/'):raise ValueError('project_dir is not a safe relative path')
    base=SRC/('' if d=='.' else d)/'benchmarks/project/python'
    if not inside_src(SRC/('' if d=='.' else d)) or not inside_src(base):raise ValueError('project path resolves outside /src')
    project_real=(SRC/('' if d=='.' else d)).resolve();real=base.resolve()
    if project_real not in real.parents:raise ValueError('benchmarks/project/python resolves outside the project')
    if base.is_symlink() or not base.is_dir():raise ValueError('project has no benchmarks/project/python')
    tops={x.name.split('.')[0] for x in base.iterdir() if x.name not in ('tests','__pycache__') and not x.name.startswith('.')}
    if tops&reserved_modules():raise ValueError('project module shadows a container module')
    PYTHONPATH=PYTHONPATH+':'+str(base);sys.path.append(str(base));PROJECT_PY=base;PROJECT_ROOT=project_real;return str(base)

def job(name):
    def register(fn):
        JOBS[name]=fn;return fn
    return register

sys.path.insert(0,str(Path(__file__).resolve().parent))
import bench_capacity_job as _bench_capacity;_bench_capacity.register(job,globals())   # Task 22 (Amendment H6): job `capacity` (not bench_capacity: tools/bench_capacity.py has that name)
# Phase 2 Task 17 (FR6 N2): generic native support, job `native-build` (not bench_native: tools/bench_native.py has that name;
# globals(), not a dict of values: child_env and python_argv are defined below this line)
import bench_native_job as _bench_native;_bench_native.register(job,globals())

def _read(root,name,unavailable):
    try:return (root/name).read_text()
    except OSError as error:
        unavailable[name]=type(error).__name__;return None

class ParseError(ValueError):
    """A readable cgroup file whose content does not have the kernel format."""

def _pairs(text,keys):
    rows={p[0]:p[1] for p in (line.split() for line in text.splitlines()) if len(p)>=2}
    if not rows:raise ParseError('no key-value rows')
    return {k:int(rows[k]) if k in rows else None for k in keys}

def _pressure(text):
    out={}
    for line in text.splitlines():
        kind,*fields=line.split()
        if any('=' not in f for f in fields):raise ParseError('field without =')
        values=dict(f.split('=',1) for f in fields)
        if 'total' not in values:raise ParseError('pressure line without total=')
        out[kind]=int(values['total'])
    if 'some' not in out:raise ParseError('no some line')
    return out

def _scalar(text):
    fields=text.split()
    if not fields:raise ParseError('empty file')
    return int(fields[0])

def _parsed(root,name,parse,unavailable):
    """Read and parse one file. A missing or malformed file gives None plus a reason, never zero."""
    text=_read(root,name,unavailable)
    if text is None:return None
    try:return parse(text)
    except (ValueError,KeyError,IndexError):
        unavailable[name]='ParseError';return None

def read_counters(root=CG,proc=Path('/proc'),clock=time.perf_counter_ns):
    """One handshake read of the container cgroup. A missing file gives None plus a reason, never zero."""
    unavailable={};sample={'perf_counter_ns':clock()}
    sample['cpu']=_parsed(root,'cpu.stat',lambda text:_pairs(text,CPU_KEYS),unavailable)
    sample['memory_stat']=_parsed(root,'memory.stat',lambda text:_pairs(text,MEM_KEYS),unavailable)
    for key,name in (('memory_current','memory.current'),('memory_peak','memory.peak'),('pids_current','pids.current'),('pids_peak','pids.peak')):
        sample[key]=_parsed(root,name,_scalar,unavailable)
    sample['cpu_pressure']=_parsed(root,'cpu.pressure',_pressure,unavailable)
    sample['memory_pressure']=_parsed(root,'memory.pressure',_pressure,unavailable)
    procs=_read(root,'cgroup.procs',unavailable);threads={}
    for pid in (procs or '').split():
        try:threads[pid]=len(os.listdir(proc/pid/'task'))
        except OSError:pass
    sample['threads']=sum(threads.values()) if procs is not None else None
    sample['processes']=len(threads) if procs is not None else None
    sample['unavailable']=unavailable
    return sample

DELTA_NAMES={'usage_usec':'cpu_usage_usec','user_usec':'cpu_user_usec','system_usec':'cpu_system_usec','nr_throttled':'nr_throttled','throttled_usec':'throttled_usec'}

def delta(start,end):
    out={'wall_ns':end['perf_counter_ns']-start['perf_counter_ns'],'unavailable':{**start['unavailable'],**end['unavailable']}}
    for k in CPU_KEYS:
        a=(start.get('cpu') or {}).get(k);b=(end.get('cpu') or {}).get(k)
        out[DELTA_NAMES[k]]=None if a is None or b is None else b-a
    for name,key in (('cpu_pressure_total','cpu_pressure'),('memory_pressure_total','memory_pressure')):   # spec 8.3 pressure, when readable
        a=(start.get(key) or {}).get('some');b=(end.get(key) or {}).get('some');out[name]=None if a is None or b is None else b-a
    out['pids_peak']=end.get('pids_peak')
    out['pids_start']=start.get('pids_current');out['pids_end']=end.get('pids_current')
    out['threads_start']=start.get('threads');out['threads_end']=end.get('threads')
    return out

class ProtocolError(ValueError):
    """A marker message that is not a JSON object of the handshake protocol."""

class Channel:
    """Unix-socket handshake server. A begin/end message is acknowledged only after the cgroup read."""
    def __init__(self,path,reader=read_counters):
        self.path=Path(path);self.reader=reader;self.sel=selectors.DefaultSelector();self.open={};self.conns={};self.events=[]
        if self.path.exists():self.path.unlink()
        self.server=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);self.server.bind(str(self.path));self.server.listen(32)
        self.server.setblocking(False);self.sel.register(self.server,selectors.EVENT_READ,None)
    def pump(self,until,deadline):
        while not until():
            remaining=deadline-time.monotonic()
            if remaining<=0:raise TimeoutError('handshake deadline')
            for key,_ in self.sel.select(timeout=min(remaining,1.0)):
                if key.fileobj is self.server:
                    conn,_=self.server.accept();conn.setblocking(True);stream=conn.makefile('rwb')
                    self.conns[conn]=stream;self.sel.register(conn,selectors.EVENT_READ,stream);continue
                conn=key.fileobj;stream=key.data
                try:line=stream.readline()
                except OSError:line=b''
                if not line:
                    self._drop(conn);continue
                try:msg=json.loads(line)
                except ValueError:raise ProtocolError('marker message is not JSON') from None
                if type(msg) is not dict:raise ProtocolError('marker message is not an object')
                if msg.get('m')=='hello' and (type(msg.get('client')) is not str or not msg['client']):
                    raise ProtocolError('hello requires a client name')
                sample=self.reader() if msg.get('m') in ('begin','end') else None
                self.events.append({'msg':msg,'sample':sample})
                if msg.get('m')=='hello':self.open[msg['client']]=stream
                try:stream.write(b'{"ack":true}\n');stream.flush()
                except OSError:self._drop(conn)
    def _drop(self,conn):
        """Forget a connection: unregister it, close its stream and socket, remove its open entry."""
        stream=self.conns.pop(conn,None)
        try:self.sel.unregister(conn)
        except (KeyError,ValueError):pass
        for client in [c for c,s in self.open.items() if s is stream]:del self.open[client]
        for handle in (stream,conn):
            if handle is None:continue
            try:handle.close()
            except OSError:pass
    def send(self,client,command):
        stream=self.open[client];stream.write((json.dumps(command)+'\n').encode());stream.flush()
    def close(self):
        for conn in list(self.conns):self._drop(conn)
        self.sel.close();self.server.close()
        if self.path.exists():self.path.unlink()

REQUEST_LIMIT={}   # G-ALO-CO (Amendment I item I13.1): SAFE_C_BENCH_REQUEST_LIMIT for every child (set by main before the job)
POLICY_FILE=SRC/'safety/performance-policy.json'

def set_request_limit(plan,policy_path=None):
    """The job plan's request_limit when it has one, else pools.request_limit of the protected policy file. A missing or
    malformed value raises ValueError; benchlab.workload.construct_adapter reads the variable in every child."""
    if 'request_limit' in plan:value=plan['request_limit']
    else:
        try:value=json.loads(Path(policy_path or POLICY_FILE).read_text())['pools']['request_limit']
        except (OSError,ValueError,KeyError,TypeError):raise ValueError('request_limit: no plan value and no policy pools.request_limit') from None
    if isinstance(value,bool) or not isinstance(value,int) or value<1:raise ValueError('request_limit must be a positive integer')
    REQUEST_LIMIT.clear();REQUEST_LIMIT['SAFE_C_BENCH_REQUEST_LIMIT']=str(value);return value

TEST_STUB_VAR='SAFE_C_TEST_STUB'    # the one test-only stub variable (Task 6, G2.3; Task A5, I9.4; FR3: the value is the stub's declared reason)
TEST_ENV_ALLOWED={TEST_STUB_VAR:re.compile(r'^[a-z0-9-]{1,32}$')}   # never inherited, only from a selftest plan
TEST_ENV={}        # set by set_test_env before the job

def set_test_env(plan):
    """The test-only stub environment of a job: only when plan.get('mode')=='selftest' (a plan that bench selftest code
    built and bench_deadline.check_selftest_plan verified) and only the allowlisted variable with a reason value; otherwise
    empty. A malformed test_env raises ValueError and leaves the environment empty."""
    TEST_ENV.clear()
    if plan.get('mode')=='selftest' and 'test_env' in plan:
        env=plan['test_env']
        if (not isinstance(env,dict) or not env or any(k not in TEST_ENV_ALLOWED or not isinstance(v,str) or not TEST_ENV_ALLOWED[k].fullmatch(v) for k,v in env.items())):
            raise ValueError('test_env rejected')
        TEST_ENV.update(env)

def child_env(marker=None,extra=None):
    env={k:v for k,v in os.environ.items() if k not in TEST_ENV_ALLOWED};env['PYTHONPATH']=PYTHONPATH;env.update(REQUEST_LIMIT);env.update(TEST_ENV)
    if marker:env['SAFE_C_BENCH_MARKER']=str(marker)
    env.update(extra or {});return env

def numpy_runtime():
    try:
        from numpy._core._multiarray_umath import __cpu_baseline__,__cpu_dispatch__,__cpu_features__
    except ImportError:return None
    return {'baseline':list(__cpu_baseline__),'found':sorted(k for k,v in __cpu_features__.items() if v and k in __cpu_dispatch__),
            'label':'CPU-specific NumPy dispatch; the C build (no -march) does not get it'}

def runtime_identity(sys_module=sys,gil_disabled_build=None):
    """B10: GIL state after imports where the runtime exposes it. A missing optional API gives None with a label; it never claims free-threaded execution."""
    import sysconfig
    build=bool(sysconfig.get_config_var('Py_GIL_DISABLED')) if gil_disabled_build is None else bool(gil_disabled_build)
    probe=getattr(sys_module,'_is_gil_enabled',None)
    if callable(probe):label='reported by sys._is_gil_enabled() after imports'
    elif build:label='free-threaded build; GIL state not exposed, unverified'
    else:label='standard build; sys._is_gil_enabled() not exposed'
    return {'python':platform.python_version(),'free_threaded_build':build,'gil_enabled':probe() if callable(probe) else None,'gil_label':label}

def selftest_mutation(plan):
    """Task 19a (P01): '' for an ordinary plan. A plan that names `selftest` or `mutation` must be a doctor plan with
    selftest=true and exactly one known mutation: hide-counter:<mandatory counter> or hide-module:<expected library>.
    Anything else raises ValueError, and main refuses the plan before any job runs."""
    if 'selftest' not in plan and 'mutation' not in plan:return ''
    mutation=plan.get('mutation')
    if plan.get('selftest') is not True or plan.get('job')!='doctor' or not isinstance(mutation,str):raise ValueError('selftest mutation rejected')
    kind,_,name=mutation.partition(':');expected=plan.get('expected')
    if not ((kind=='hide-counter' and name in MANDATORY) or (kind=='hide-module' and isinstance(expected,dict) and name in expected)):
        raise ValueError('selftest mutation rejected')
    return mutation

@job('doctor')
def job_doctor(plan,out):
    # Task 19a: selftest-only doctor mutations (P01). A plan without selftest=true never hides anything.
    root=CG;mutation=selftest_mutation(plan)
    if mutation.startswith('hide-counter:'):
        hidden=mutation.split(':',1)[1];root=WORK/'bench/private/cgroup';root.mkdir(parents=True,exist_ok=True)
        for p in CG.iterdir():
            if p.is_file() and p.name!=hidden:
                try:(root/p.name).write_bytes(p.read_bytes())
                except OSError:pass
    if mutation.startswith('hide-module:'):
        name=mutation.split(':',1)[1]
        class Hidden:
            def find_spec(self,fullname,path=None,target=None):
                if fullname==name or fullname.startswith(name+'.'):raise ImportError('hidden by a selftest mutation')
        for loaded in [m for m in sys.modules if m==name or m.startswith(name+'.')]:sys.modules.pop(loaded,None)   # an earlier import never unhides it
        sys.meta_path.insert(0,Hidden())
    sample=read_counters(root);missing=[k for k in MANDATORY if k in sample['unavailable']]
    libraries={}
    sys.path[:0]=[p for p in PYTHONPATH.split(':') if p not in sys.path]
    for name,version in sorted(plan['expected'].items()):
        try:libraries[name]='MATCH' if getattr(importlib.import_module(name),'__version__',None)==version else 'MISMATCH'
        except ImportError:libraries[name]='UNAVAILABLE'
    env={k:os.environ.get(k) for k in THREAD_ENV}
    runtime={**runtime_identity(),'simd':numpy_runtime() if libraries.get('numpy')=='MATCH' else None}   # after the library imports (B10)
    try:cpuset=(CG/'cpuset.cpus.effective').read_text().strip()
    except OSError:cpuset=None
    try:cpu_max=(CG/'cpu.max').read_text().strip()[:64]          # B12 (Task 12): the quota the host compares with the envelope
    except OSError as error:cpu_max=None;sample['unavailable']['cpu.max']=type(error).__name__
    ok=(not missing and bool(plan['expected']) and all(v=='MATCH' for v in libraries.values()) and all(v=='1' for v in env.values())
        and runtime['python'].startswith('3.13.') and cpuset)
    return {'status':'PASS' if ok else 'BLOCKED','missing_counters':missing,'libraries':libraries,'thread_environment':env,'runtime':runtime,
            'cpuset':cpuset,'cpu_max':cpu_max,'unavailable':sample['unavailable']}

UNIT_ROW=re.compile(r'^(?:ERROR|FAIL): (\S+) \(([A-Za-z0-9_.]{1,200})\)',re.M)

UNIT_MODULE_RE=re.compile(r'^test_[a-z0-9_]{1,60}$')
UNIT_CODE=r'''
import sys,unittest
sys.path.insert(0,sys.argv[1])
unittest.main(module=None,argv=['unittest']+['tests.'+m for m in sys.argv[2:]])
'''

def unit_modules(plan):
    """Ruling A6-C3 (Task A6 lock follow-up): None (discover every test module) or the plan's `unit_modules`, a list of 1 to
    64 test module names of one declared unit group. ValueError for any other form."""
    mods=plan.get('unit_modules')
    if mods is None:return None
    if not isinstance(mods,list) or not 1<=len(mods)<=64 or any(not isinstance(m,str) or not UNIT_MODULE_RE.fullmatch(m) for m in mods):
        raise ValueError('unit_modules rejected')
    return list(mods)

@job('unit')
def job_unit(plan,out):
    """The framework tests, or with plan['project_dir'] the project's tests. The result names failed test ids only. With
    `unit_modules` (a project unit group, ruling A6-C3) only those modules run, in one child."""
    try:mods=unit_modules(plan)
    except ValueError as exc:return {'status':'FAIL','reason':str(exc),'tests':0,'failed':[]}
    if mods is not None and PROJECT_PY is None:return {'status':'FAIL','reason':'unit_modules needs a project','tests':0,'failed':[]}
    top=PROJECT_PY if PROJECT_PY is not None else Path('/src/benchmarks/performance/python')
    # Both trees hold a top-level `tests` package. For the project run, unittest puts the project directory first on
    # sys.path (it is not on PYTHONPATH here), so `tests` is the project's; configure_project already refused every
    # project module name that could shadow the stdlib, a bench wheel or benchlab. Spawned pool workers get this sys.path.
    path=FRAMEWORK_PYTHONPATH if PROJECT_PY is not None else PYTHONPATH
    argv=python_argv(path,'-m','unittest','discover','-s',str(top/'tests'),'-t',str(top)) if mods is None else python_argv(path,'-c',UNIT_CODE,str(top),*mods)
    run=subprocess.run(argv,
                       env=child_env(),capture_output=True,text=True,timeout=plan['deadline_seconds']-30)
    tail=run.stderr.strip().splitlines()[-3:]
    ran=next((int(line.split()[1]) for line in tail if line.startswith('Ran ')),0)
    (out/'unit.log').write_text(run.stderr[-1048576:])
    failed=sorted({m.group(2) for m in UNIT_ROW.finditer(run.stderr)})[:50]
    return {'status':'PASS' if run.returncode==0 and ran>0 else 'FAIL','tests':ran,'exit_code':run.returncode,'failed':failed,
            'scope':'project' if PROJECT_PY is not None else 'framework'}

# ---- Amendment G2.6: the call deadline of a covered selector (the host sets call_deadline_seconds and its reason) ----
REASON_RE=re.compile(r'^[a-z0-9-]{1,32}$');SELECTOR_RE=re.compile(r'^[a-z0-9-]{1,16}$');PR_SET_CHILD_SUBREAPER=36

class DeadlineKilled(RuntimeError):
    """A covered call ran past its call deadline; its process group was killed and reaped. FAIL with the reason, never
    BLOCKED, never TIMEOUT."""
    def __init__(self,reason):super().__init__(reason);self.reason=reason

def deadline_reason(spec):
    """The declared reason of a plan or trial (an opaque string of the case manifest); a malformed one is never echoed."""
    r=spec.get('call_deadline_reason');return r if isinstance(r,str) and REASON_RE.fullmatch(r) else 'call-deadline'

def _subreaper(on):
    """PR_SET_CHILD_SUBREAPER: while on, members orphaned by a group kill come to this process (the container init never reaps)."""
    try:
        import ctypes
        return ctypes.CDLL(None,use_errno=True).prctl(PR_SET_CHILD_SUBREAPER,1 if on else 0,0,0,0)==0
    except (OSError,AttributeError):return False

def group_members(pgid,proc=Path('/proc')):
    """(pid, ppid) of every process of the group, zombies included."""
    out=[]
    for d in proc.iterdir():
        if not d.name.isdigit():continue
        try:fields=(d/'stat').read_text().rsplit(')',1)[1].split()
        except (OSError,IndexError):continue
        if len(fields)>2 and fields[2]==str(pgid):out.append((int(d.name),int(fields[1])))
    return out

def _children(proc=Path('/proc')):
    """Pids whose parent is this process."""
    me=str(os.getpid());out=set()
    for d in proc.iterdir():
        if not d.name.isdigit():continue
        try:fields=(d/'stat').read_text().rsplit(')',1)[1].split()
        except (OSError,IndexError):continue
        if len(fields)>1 and fields[1]==me:out.add(int(d.name))
    return out

def _state(pid):
    try:return Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[0]
    except (OSError,IndexError):return None

def kill_group(proc,grace=5.0,foreign=None):
    """SIGKILL to the process group that the child leads (start_new_session=True), then reap the child and every member the
    kill orphaned. Returns the number of group members still present after `grace` seconds (0: all reaped). A process of
    another group orphaned to this process during the subreaper window is reaped when it is a zombie, else its pid is
    appended to `foreign` (recorded, never waited for: no hang). Known children before the window are never touched."""
    own=_children();sub=_subreaper(True)
    try:
        try:os.killpg(proc.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        proc.wait();end=time.monotonic()+grace;me=os.getpid()
        while True:
            left=group_members(proc.pid)
            if not left or time.monotonic()>end:return len(left)
            for pid,ppid in left:
                if ppid!=me:continue
                try:os.waitpid(pid,os.WNOHANG)
                except ChildProcessError:pass
            time.sleep(0.01)
    finally:
        if sub:_subreaper(False)
        group={pid for pid,_ in group_members(proc.pid)}
        for pid in sorted(_children()-own-group-{proc.pid}):
            if _state(pid)=='Z':
                try:os.waitpid(pid,os.WNOHANG)
                except ChildProcessError:pass
            elif foreign is not None:foreign.append(pid)

def run_deadline(argv,plan,timeout,env,capture=False,check=False):
    """subprocess.run, and under the plan's call deadline when the host set one for this job: the child leads its own
    process group; at the deadline the group is killed and reaped and DeadlineKilled carries the declared reason."""
    limit=plan.get('call_deadline_seconds')
    io={'stdout':subprocess.PIPE,'stderr':subprocess.PIPE,'text':True} if capture else {'stdout':subprocess.DEVNULL,'stderr':subprocess.DEVNULL}
    if limit is None:return subprocess.run(argv,env=env,check=check,timeout=timeout,**io)
    p=subprocess.Popen(argv,env=env,start_new_session=True,**io)
    try:out,err=p.communicate(timeout=min(timeout,float(limit)))
    except subprocess.TimeoutExpired:
        kill_group(p);p.communicate()        # one rule with CallerChild.call: an armed call that expires is FAIL with the reason,
        raise DeadlineKilled(deadline_reason(plan)) from None     # whether its own limit or the job limit bound first
    if check and p.returncode:raise subprocess.CalledProcessError(p.returncode,argv,out,err)
    return subprocess.CompletedProcess(argv,p.returncode,out,err)

VALIDATE_CODE=r'''
import hashlib,json,sys,tempfile
from pathlib import Path
from benchlab.workload import load_case_adapter
case=json.load(open(sys.argv[1]));a=load_case_adapter(case);data=a.synthesize(1,int(case['parameters'].get('seed',{'value':20261007})['value']))
p=Path(tempfile.mkdtemp())/'tiny';p.write_bytes(data);d=a.load({'path':str(p),'sha256':hashlib.sha256(data).hexdigest()});ref=a.reference(d);rows=[]
for v in case['variants']:
    if v['language'] not in ('python','python-library') or v['status']!='implemented':continue
    res=a.materialize(a.run(a.prepare(d,v['id'],1),v['id'],1));rows.append({'variant':v['id'],'eligible':bool(a.validate(res,ref,d)['eligible']),'work_units':a.work_units(res)})
print(json.dumps({'status':'PASS' if rows and all(r['eligible'] and r['work_units']==1 for r in rows) else 'FAIL','adapter':'importable','variants':rows}))
'''

@job('validate')
def job_validate(plan,out):
    """bench validate: import the adapter, check its methods and round-trip a tiny dataset through every implemented
    Python variant with 1 worker against reference. Bounded by the plan deadline."""
    manifest=plan.get('case_manifest')
    if not case_manifest_allowed(manifest):return {'status':'FAIL','adapter':'case manifest path rejected'}
    try:run=run_deadline(python_argv(PYTHONPATH,'-c',VALIDATE_CODE,manifest),plan,plan['deadline_seconds']-10,child_env(),capture=True)
    except subprocess.TimeoutExpired:return {'status':'FAIL','adapter':'deadline'}
    except DeadlineKilled as killed:return {'status':'FAIL','adapter':'call-deadline','failure_reason':killed.reason}
    (out/'validate.log').write_text(run.stderr[-1048576:])
    if run.returncode==0 and run.stdout.strip():
        try:row=json.loads(run.stdout.splitlines()[-1])
        except ValueError:row=None
        if isinstance(row,dict):return row
    return {'status':'FAIL','adapter':'not-importable-or-failed','exit_code':run.returncode}

def project_checks():
    """Review fix: the container re-reads and re-checks bench.json (the host check may be stale); None when malformed."""
    path=PROJECT_PY.parent/'bench.json'
    try:
        if path.is_symlink() or not inside_src(path) or PROJECT_ROOT is None or not inside(path,PROJECT_ROOT):return None   # Task 13a residual
        decl=json.loads(path.read_text())
    except (OSError,ValueError):return None
    checks=decl.get('checks',[]) if isinstance(decl,dict) else None
    if not isinstance(checks,list) or len(checks)>MAX_PROJECT_CHECKS:return None
    for c in checks:
        if (not isinstance(c,dict) or set(c)-{'selectors'}!={'name','module','before_run'} or not isinstance(c['name'],str) or not NAME_RE.fullmatch(c['name'])
            or not isinstance(c['module'],str) or not MODULE_RE.fullmatch(c['module']) or not all(x.isidentifier() for x in c['module'].split('.'))
            or type(c['before_run']) is not bool):return None
        if 'selectors' in c and not check_selectors_ok(c['selectors']):return None
    return checks

def check_selectors_ok(value):
    """Post-approval ruling PC-01 (Task A2): the optional `selectors` of a check entry is a list of 1 to 8 distinct selector
    names (SELECTOR_RE). Every other extra key of an entry stays refused."""
    return (isinstance(value,list) and 1<=len(value)<=8 and len(set(map(str,value)))==len(value)
            and all(isinstance(s,str) and SELECTOR_RE.fullmatch(s) for s in value))

def check_result(name,returncode,stdout):
    """Review fix: a closed allowlist of the project check row. The status comes from the framework (exit code 0 and a
    JSON object row); the row may only report a failure, never a pass. Every other key is dropped and counted. A `counts`
    object with more than MAX_COUNTS keys FAILs the row with a named reason and no counts (ruling T28-C2: no truncation)."""
    row=None;lines=(stdout or '')[-65536:].strip().splitlines()
    if lines:
        try:row=json.loads(lines[-1])
        except ValueError:row=None
    ok=returncode==0 and isinstance(row,dict)
    row=row if isinstance(row,dict) else {}
    if row.get('status') not in (None,'PASS'):ok=False
    out={'status':'PASS' if ok else 'FAIL','check':name,'files':[]};dropped=0
    for key,value in row.items():
        if key=='status':continue
        if key=='files' and isinstance(value,list):
            out['files']=[f for f in value if isinstance(f,str) and FILE_RE.fullmatch(f) and f not in ('.','..')][:MAX_FILES]
        elif key=='counts' and isinstance(value,dict):
            if len(value)>MAX_COUNTS:ok=False;out['reason']='check row has more count keys than the bound';continue   # T28-C2
            out['counts']={k:v for k,v in value.items() if isinstance(k,str) and COUNT_RE.fullmatch(k) and type(v) is int and abs(v)<2**53}
        elif key=='label' and isinstance(value,str) and LABEL_RE.fullmatch(value):out['label']=value
        else:dropped+=1
    out['dropped_keys']=dropped
    if not ok:out['status']='FAIL'
    if returncode!=0:out['exit_code']=returncode if isinstance(returncode,int) else -1
    return out

@job('check')
def job_check(plan,out):
    """Amendment A: a check declared in the project's bench.json, run as a bounded isolated subprocess; its last stdout
    line is filtered through check_result."""
    if PROJECT_PY is None:return control_check(plan,out) if plan.get('check')==CONTROL_CHECK else {'status':'FAIL','reason':'a check needs a project'}
    checks=project_checks()
    if checks is None:return {'status':'FAIL','reason':'bench.json is missing or malformed'}
    entry=next((c for c in checks if c['name']==plan.get('check')),None)
    raw=plan.get('check_args',[]);args=[str(a) for a in raw] if isinstance(raw,list) else None
    if entry is None:return {'status':'FAIL','reason':'undeclared check'}
    if entry['module'].split('.')[0] in reserved_modules():return {'status':'FAIL','reason':'check module shadows a container module'}
    if args is None or len(args)>8 or not all(ARG_RE.fullmatch(a) for a in args):return {'status':'FAIL','reason':'check arguments rejected'}
    try:native=_bench_native.native_env(plan)          # Task 17 (FR6 N2): restored binaries are verified before the check starts
    except ValueError:return {'status':'FAIL','reason':'restored native binary digest mismatch','check':entry['name'],'files':[]}
    before=_bench_native.native_shm_snapshot()          # Task 19 (Amendment F item 10 (d))
    try:run=run_deadline(python_argv(PYTHONPATH,'-m',entry['module'],entry['name'],str(out),*args),plan,plan['deadline_seconds']-30,child_env(extra=native),capture=True)
    except subprocess.TimeoutExpired:return {'status':'FAIL','reason':'check exceeded its deadline','check':entry['name'],'files':[]}
    except DeadlineKilled as killed:return {'status':'FAIL','reason':'call deadline','check':entry['name'],'files':[],'failure_reason':killed.reason}
    (out/f"{entry['name']}.log").write_text((run.stderr or '')[-1048576:])
    row=check_result(entry['name'],run.returncode,run.stdout)
    if _bench_native.job_end_check(before):row.update(status='FAIL',reason=_bench_native.SHM_LEFT)      # Task 19
    return row

CONTROL_CHECK='control-call'      # G2.6 framework control check: one tiny py-reference call of a framework case with a selector
CONTROL_CODE=("import hashlib,json,os,sys,tempfile;from benchlab.workload import load_case_adapter;"
              "case=json.load(open(sys.argv[1]));a=load_case_adapter(case,selector=sys.argv[2]);data=a.synthesize(1,20261007);"
              "p=os.path.join(tempfile.mkdtemp(),'d');open(p,'wb').write(data);d=a.load({'path':p,'sha256':hashlib.sha256(data).hexdigest()});"
              "r=a.materialize(a.run(a.prepare(d,'py-reference',1),'py-reference',1));print(json.dumps({'status':'PASS' if a.work_units(r)==1 else 'FAIL'}))")

def control_check(plan,out):
    """The framework control check (no project): only a framework case manifest and a declared selector. A covered selector
    runs under the plan's call deadline (the call-deadline selftest suite)."""
    manifest=plan.get('case_manifest');selector=plan.get('selector','all')
    if not case_manifest_allowed(manifest) or not str(manifest).startswith(str(SRC/'benchmarks/performance/cases')+'/'):return {'status':'FAIL','reason':'case manifest path rejected'}
    if not isinstance(selector,str) or not SELECTOR_RE.fullmatch(selector):return {'status':'FAIL','reason':'selector rejected'}
    try:run=run_deadline(python_argv(PYTHONPATH,'-c',CONTROL_CODE,manifest,selector),plan,plan['deadline_seconds']-30,child_env(),capture=True)
    except subprocess.TimeoutExpired:return {'status':'FAIL','reason':'check exceeded its deadline','check':CONTROL_CHECK,'files':[]}
    except DeadlineKilled as killed:return {'status':'FAIL','reason':'call deadline','check':CONTROL_CHECK,'files':[],'failure_reason':killed.reason}
    return check_result(CONTROL_CHECK,run.returncode,run.stdout)

def run_marked(channel,argv,client,deadline,env=None):
    """Run one marked client to its end handshake. The row holds the begin/end delta, the end fields and the exit code."""
    p=subprocess.Popen(argv,env=child_env(channel.path,env),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    start=len(channel.events)
    ended=lambda:any(e['msg'].get('m')=='end' and e['msg'].get('trial')==client for e in channel.events[start:])
    try:channel.pump(lambda:ended() or p.poll() is not None,deadline)   # an end is acknowledged before the client can exit
    finally:
        try:p.wait(timeout=max(1.0,deadline-time.monotonic()))
        except subprocess.TimeoutExpired:p.kill();p.wait()
    ev=[e for e in channel.events[start:] if e['msg'].get('trial')==client]
    b=next((e for e in ev if e['msg'].get('m')=='begin'),None);e=next((x for x in ev if x['msg'].get('m')=='end'),None)
    errors=[x['msg']['error'] for x in ev if x['msg'].get('m')=='note' and 'error' in x['msg']]
    if b is None or e is None:return {'name':client,'exit_code':p.returncode if p.returncode else 1,'extra':{'errors':errors},'unavailable':{'handshake':'missing begin or end'}}
    row={'name':client,**delta(b['sample'],e['sample']),'ready_current':b['sample'].get('memory_current'),'post_current':e['sample'].get('memory_current'),
         'extra':{k:v for k,v in e['msg'].items() if k not in ('m','phase','trial')},'exit_code':p.returncode}
    if row['extra'].pop('sampled',False):
        seen=[x for x in (row['ready_current'],row['post_current']) if x is not None]
        row['extra']['sampled_max_bytes']=max(seen) if seen else None
        row['extra']['label']='lower bound: memory.current sampled at the begin/end handshakes; a spike between them is missed'
    return row

def _controls(plan,out,names,filename):
    channel=Channel(WORK/'bench/marker.sock');deadline=time.monotonic()+plan['deadline_seconds']-10;rows=[]
    try:
        sizes=[str(plan[k]) for k in ('short_children','touch_mib','untouched_mib')]
        for name in names:
            try:rows.append(run_marked(channel,python_argv(PYTHONPATH,'-m','benchlab.controls',name,str(plan['seconds']),str(plan['native_mib']),*sizes),name,deadline))
            except TimeoutError:   # keep the completed rows; the late control fails and the rest are missing (FAIL)
                rows.append({'name':name,'exit_code':1,'extra':{},'unavailable':{'handshake':'deadline'}});break
    finally:channel.close()
    (out/filename).write_text('\n'.join(json.dumps(r,sort_keys=True) for r in rows)+'\n')
    return {'status':'PASS' if rows and all(r['exit_code']==0 for r in rows) else 'FAIL','controls':len(rows)}

@job('controls-cpu')
def job_controls_cpu(plan,out):return _controls(plan,out,plan['controls'],'controls-cpu.jsonl')

@job('controls-memory')
def job_controls_memory(plan,out):return _controls(plan,out,[plan['control']],'controls-memory.jsonl')

# ---- Task 16a: workload-generic trial runner (timing, memory, reference) ----

def _manifest(plan):
    if not case_manifest_allowed(plan.get('case_manifest')):raise ValueError('case manifest path rejected')
    return plan['case_manifest']

SYNTH_CODE=("import json,sys;from benchlab.workload import load_case_adapter;a=load_case_adapter(json.load(open(sys.argv[4])));"
            "open(sys.argv[1],'wb').write(a.synthesize(int(sys.argv[2]),int(sys.argv[3])))")
REFERENCE_CODE=r'''
import hashlib,json,os,sys,tempfile
from benchlab.workload import load_case_adapter
case=json.load(open(sys.argv[1]));a=load_case_adapter(case)
c=a.slice(a.load({'path':sys.argv[2],'sha256':sys.argv[3]}),int(sys.argv[5]));r=a.reference(c);json.dump(r,open(sys.argv[4],'w'))
rc=getattr(a,'reference_counts',None);rc is None or json.dump(rc(r),open(sys.argv[4]+'.evals','w'))
rx=getattr(a,'reference_exclusions',None);x=None if rx is None else rx(r);x is None or json.dump(x,open(sys.argv[4]+'.admit','w'))
ov={}
for s in (json.loads(sys.argv[6]) if len(sys.argv)>6 else []):
    b=load_case_adapter(case,selector=s);f=getattr(b,'reference_overhead',None)
    if f is None:continue
    seed=(case.get('parameters') or {}).get('seed',{}).get('value')
    if isinstance(seed,bool) or not isinstance(seed,int):raise SystemExit('reference overhead: the case manifest declares no integer parameter seed (the synthetic dataset of the case seed)')
    d=b.synthesize(int(sys.argv[7]),seed);p=os.path.join(tempfile.mkdtemp(),'overhead')
    open(p,'wb').write(d);y=f(b.load({'path':p,'sha256':hashlib.sha256(d).hexdigest()}))
    if y:ov.update({k:v for k,v in y.items() if k not in ov})
ov and json.dump(ov,open(sys.argv[4]+'.overhead','w'))
'''
EVALS_KEY=re.compile(r'^[a-z0-9-]{1,16}$')
ADMIT_KEYS=('row','brent','bump')       # Amendment G2.3 (P3R2-04): the closed reason set of reference_admit_excluded

def reference_evals(path):
    """Amendment G3.7: the adapter's evaluation totals written beside the reference ({opaque key: integer >= 0}, 1 to 8
    keys). None when the file is absent (an adapter without reference_counts); a malformed file raises ValueError."""
    p=Path(path)
    if not p.is_file():return None
    try:d=json.loads(p.read_text())
    except ValueError:raise ValueError('reference evaluation counts are not JSON') from None
    if not isinstance(d,dict) or not 0<len(d)<=8 or any(not EVALS_KEY.fullmatch(k) or type(v) is not int or v<0 for k,v in d.items()):
        raise ValueError('reference evaluation counts are malformed')
    return d

def reference_admit_excluded(path):
    """Amendment G2.3 (P3R2-04): the adapter's exclusion counts written beside the reference (exactly the keys row, brent,
    bump; integers >= 0). None when the file is absent (no reference_exclusions, or no selected model reports reasons);
    a malformed file raises ValueError."""
    p=Path(path)
    if not p.is_file():return None
    try:d=json.loads(p.read_text())
    except ValueError:raise ValueError('reference exclusion counts are not JSON') from None
    if not isinstance(d,dict) or sorted(d)!=sorted(ADMIT_KEYS) or any(type(v) is not int or v<0 for v in d.values()):
        raise ValueError('reference exclusion counts are malformed')
    return d

OVERHEAD_KEY='library_overhead_ns_per_row'     # G2.3 (P3R2-04, Task 6): the closed key of reference_overhead
OVERHEAD_ROWS=256                               # G2.3 (P3R2-04): the rows of the overhead measurement (the synthetic small tier, seed of the case)

def reference_overhead(path):
    """G2.3 (P3R2-04): the adapter's S* side-test overhead written beside the reference (a closed object of one finite number
    >= 0). None when the file is absent (no planned selector reports one); a malformed file raises ValueError."""
    p=Path(path)
    if not p.is_file():return None
    try:d=json.loads(p.read_text(),parse_constant=lambda c:(_ for _ in ()).throw(ValueError(c)))
    except ValueError:raise ValueError('reference overhead is not JSON') from None
    v=d.get(OVERHEAD_KEY) if isinstance(d,dict) and list(d)==[OVERHEAD_KEY] else None
    if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<0:raise ValueError('reference overhead is malformed')
    return {OVERHEAD_KEY:v}

def materialize_dataset(plan):
    d=WORK/'bench/data';d.mkdir(parents=True,exist_ok=True);target=d/'dataset';ds=plan['dataset']
    if ds['kind']=='synthetic':           # Amendment A: the workload synthesizes its own seeded dataset (isolated child)
        subprocess.run(python_argv(PYTHONPATH,'-c',SYNTH_CODE,str(target),str(plan['rows']),str(ds['seed']),_manifest(plan)),env=child_env(),check=True,
                       stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=plan['deadline_seconds']//2)
    else:
        data=Path('/data/dataset.json').read_bytes()
        if hashlib.sha256(data).hexdigest()!=ds['sha256']:raise ValueError('owner fixture digest changed')
        target.write_bytes(data)          # private tmpfs copy: every variant is charged the same bytes (shmem)
    return {'path':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}

def reference_path(plan,dataset):
    """Spec 4: the reference output is computed once per run, outside timing, and bound by digest. A synthetic job verifies the copy the
    host restored; only the `reference` job and a local run (single container) compute it, over the largest planned tier."""
    target=WORK/'bench/private/reference.json';target.parent.mkdir(parents=True,exist_ok=True)
    if plan.get('reference_sha256'):
        if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest()!=plan['reference_sha256']:raise ValueError('restored reference digest mismatch')
        return str(target)
    if plan['dataset']['kind']=='synthetic' and plan.get('job')!='reference':raise ValueError('a synthetic job needs the run reference digest')
    sel=plan.get('overhead_selectors',[])      # G2.3 (Task 6): opaque selector strings; each adapter decides whether it reports an overhead
    if not isinstance(sel,list) or len(sel)>16 or not all(isinstance(s,str) and SELECTOR_RE.fullmatch(s) for s in sel):raise ValueError('overhead selectors rejected')
    if sel and not plan['sizes']['small']>=OVERHEAD_ROWS:   # G2.3 (P3R2-04): the overhead runs on the first 256 rows of the synthetic dataset
        raise ValueError(f"reference overhead needs sizes.small >= {OVERHEAD_ROWS} (the first {OVERHEAD_ROWS} rows of the synthetic dataset); the policy gives {plan['sizes']['small']}")
    run_deadline(python_argv(PYTHONPATH,'-c',REFERENCE_CODE,_manifest(plan),dataset['path'],dataset['sha256'],str(target),str(plan['rows']),json.dumps(sel),
                             str(plan['sizes']['small']) if sel else '0'),plan,plan['deadline_seconds'],child_env(),check=True)
    return str(target)

@job('reference')
def job_reference(plan,out):
    dataset=materialize_dataset(plan);evals=WORK/'bench/private/reference.json.evals';admit=WORK/'bench/private/reference.json.admit'
    over=WORK/'bench/private/reference.json.overhead'
    evals.unlink(missing_ok=True);admit.unlink(missing_ok=True);over.unlink(missing_ok=True)      # only the counts of this job's reference child count
    try:data=Path(reference_path(plan,dataset)).read_bytes()
    except DeadlineKilled as killed:return {'status':'FAIL','failure_reason':killed.reason}
    (out/'reference.json').write_bytes(data);counts=reference_evals(evals);excluded=reference_admit_excluded(admit);overhead=reference_overhead(over)
    return {'status':'PASS','files':['reference.json'],'reference_sha256':hashlib.sha256(data).hexdigest(),'dataset_sha256':dataset['sha256'],
            **({'reference_evals':counts} if counts is not None else {}),**({'reference_admit_excluded':excluded} if excluded is not None else {}),
            **({'reference_overhead':overhead} if overhead is not None else {})}

# ---- Amendment G3.3, G3.7 (Task 7): the panel candidate inputs of the synthetic large dataset ----
PANEL_CODE=r'''
import json,sys
from benchlab.workload import load_case_adapter
a=load_case_adapter(json.load(open(sys.argv[1])));f=getattr(a,'panel_inputs',None)
callable(f) or sys.exit(3)
k,K=int(sys.argv[6]),int(sys.argv[7])
d=f(a.load({'path':sys.argv[2],'sha256':sys.argv[3]}),int(sys.argv[5]),**({'part':(k,K)} if K>1 else {}))
with open(sys.argv[4],'w') as h:json.dump(d,h,separators=(',',':'),allow_nan=False)
'''
PANEL_JOIN_CODE=r'''
import json,sys
from benchlab.workload import load_case_adapter
a=load_case_adapter(json.load(open(sys.argv[1])));f=getattr(a,'panel_join',None)
callable(f) or sys.exit(3)
d=f([json.load(open(p)) for p in sys.argv[3:]])
with open(sys.argv[2],'w') as h:json.dump(d,h,separators=(',',':'),allow_nan=False)
'''
PANEL_WORKERS_MAX=8
PANEL_PARTS_MAX=64
PANEL_FILE='panel-inputs.json'

def panel_mode(plan):
    """Task A6 (I7.2, H21): ('whole', 0, 1) for one job over every row (Task 7), ('part', k, K) for row part k of K
    (`panel_part` [k, K], 2 <= K <= 64), ('join', 0, K) for the join of K restored part files (`panel_join` K). ValueError
    for any other form."""
    part,join=plan.get('panel_part'),plan.get('panel_join')
    if part is not None and join is not None:raise ValueError('panel: part and join together')
    if part is not None:
        if not isinstance(part,list) or len(part)!=2 or any(isinstance(v,bool) or not isinstance(v,int) for v in part):raise ValueError('panel_part rejected')
        k,K=part
        if not 2<=K<=PANEL_PARTS_MAX or not 0<=k<K:raise ValueError('panel_part rejected')
        return 'part',k,K
    if join is not None:
        if isinstance(join,bool) or not isinstance(join,int) or not 2<=join<=PANEL_PARTS_MAX:raise ValueError('panel_join rejected')
        return 'join',0,join
    return 'whole',0,1

@job('panel')
def job_panel(plan,out):
    """G3.3 (Task 7): synthetic datasets only (a local dataset is refused here and by the host). The adapter's optional
    panel_inputs runs in one child under the job deadline and the plan's call deadline (G2.6: a covered selector mask);
    `panel_workers` (1 to 8) spawned processes share the rows. Task A6: with `panel_part` [k, K] the child computes row
    part k of K (the five-model inputs outlast one container); with `panel_join` K the adapter's panel_join joins the K
    part files that the host restored into bench/data and computes the digest of the joined result. The host builds and
    checks the panel reference from the written file; this job only computes and reports its digest."""
    ds=plan.get('dataset');w=plan.get('panel_workers')
    try:mode,k,K=panel_mode(plan)
    except ValueError as exc:return {'status':'FAIL','reason':str(exc),'files':[]}
    name=PANEL_FILE if mode!='part' else f'panel-part-{k}.json'
    if plan.get('panel_file',PANEL_FILE)!=name:return {'status':'FAIL','reason':'panel_file rejected','files':[]}
    if not isinstance(ds,dict) or ds.get('kind')!='synthetic':return {'status':'FAIL','reason':'panel: synthetic datasets only','files':[]}
    if isinstance(w,bool) or not isinstance(w,int) or not 1<=w<=PANEL_WORKERS_MAX:return {'status':'FAIL','reason':'panel_workers rejected','files':[]}
    target=out/name;target.unlink(missing_ok=True)
    if mode=='join':
        parts=[WORK/'bench/data'/f'panel-part-{j}.json' for j in range(K)]
        if not all(p.is_file() and not p.is_symlink() for p in parts):return {'status':'FAIL','reason':'panel join: a part file is missing','files':[]}
        dataset=materialize_dataset(plan)          # the generator hash of the joined dataset (cheap; the host compares it with every part's)
        argv=python_argv(PYTHONPATH,'-c',PANEL_JOIN_CODE,_manifest(plan),str(target),*[str(p) for p in parts])
    else:
        dataset=materialize_dataset(plan)
        argv=python_argv(PYTHONPATH,'-c',PANEL_CODE,_manifest(plan),dataset['path'],dataset['sha256'],str(target),str(w),str(k),str(K))
    try:run=run_deadline(argv,plan,plan['deadline_seconds']-30,child_env())
    except subprocess.TimeoutExpired:return {'status':'FAIL','reason':'panel exceeded its deadline','files':[]}
    except DeadlineKilled as killed:return {'status':'FAIL','reason':'call deadline','files':[],'failure_reason':killed.reason}
    if run.returncode==3:return {'status':'REFUSED','reason':'the case adapter has no panel_inputs or panel_join','files':[]}
    if run.returncode!=0 or not target.is_file():return {'status':'FAIL','reason':'panel child failed','exit_code':run.returncode,'files':[]}
    return {'status':'PASS','files':[name],'inputs_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'dataset_sha256':dataset['sha256']}

VERDICT_KEYS=('model_errors','verdict_counts','reduction')   # the explicit verdict map (benchlab.trial.verdict_fields; FR5: the project's named counts)

def observation(plan,trial,phase,b,e,note,runner,warmup):
    d=delta(b['sample'],e['sample'])
    return {'schema_version':1,'run_id':plan['run_id'],'trial_id':trial['trial_id'],'block':trial['block'],'order':trial['order'],'point':trial['point'],'scope':trial['scope'],
            'mode':trial['mode'],'variant':trial['variant'],'workers':trial['workers'],'tier':trial['tier'],'phase':phase,'warmup':warmup,'runner':runner,'wall_ns':d['wall_ns'],
            **{k:d[k] for k in ('cpu_usage_usec','cpu_user_usec','cpu_system_usec','nr_throttled','throttled_usec','pids_start','pids_end','threads_start','threads_end','cpu_pressure_total','memory_pressure_total','pids_peak')},
            'loops':e['msg'].get('loops',1),'work_units':note.get('work_units'),'phases':{k:v for k,v in (e['msg'].get('phases') or {}).items() if k in ('prepare','pool_start','work','materialize','transport')},
            'result_sha256':note.get('result_sha256'),'eligible':note.get('eligible'),
            'verdict':{'failures':note.get('failures',{}),**{k:note[k] for k in VERDICT_KEYS if k in note}},'memory':None,'unavailable':d['unavailable'],'pool':note.get('pool'),
            **({'pyperf_wall_ns':int(note['pyperf_seconds']*1e9)} if 'pyperf_seconds' in note else {}),
            **({'selector':trial['selector']} if trial.get('selector','all')!='all' else {}),**({'dataset_ref':trial['dataset_ref']} if 'dataset_ref' in trial else {}),
            **({'unit':trial['unit']} if 'unit' in trial else {}),**native_observation_fields(trial,note),     # Task 19: the route dimension
            **{k:note[k] for k in PANEL_NOTE_KEYS if k in note},      # base Task 18 (G7.3, H21.4): the panel note of a single-record trial
            **(_panel_fields(note['panel_walls']) if isinstance(note.get('panel_walls'),dict) else {})}

def _panel_fields(walls):
    """panel_summary of a note; malformed walls make the observation ineligible, never a crash of the session."""
    try:return panel_summary(walls)
    except (ValueError,TypeError,AttributeError):return {'eligible':False}

PANEL_NOTE_KEYS=('panel_status_diff','detail')
NATIVE_NOTE_KEYS=('copied_bytes','load_process','self_timing','native_sha256')

def native_observation_fields(trial,note):
    """Task 19 (FR6 N4): the route and its label of a C caller row come from the plan trial; copied_bytes and load_process
    (caller child note) and self_timing and native_sha256 (kernel C trial) from the note. A Python row gets none of them."""
    out={k:note[k] for k in NATIVE_NOTE_KEYS if k in note}
    if trial.get('route') is not None:out.update(route=trial['route'],route_label=trial.get('route_label'))
    elif str(trial.get('variant','')).startswith('c-'):out['route']=None
    return out
PANEL_AUDIT_WALLS=64        # T18-C1b: the bounded audit sample per panel record (the first walls in call order)

def panel_summary(walls):
    """Task 18 fix round 1 (ruling T18-C1b; G7.3 item 3): from the child's per-call walls {record: [L walls in ns]}, the
    exact per-record median, min and max (only the medians decide: the trial value is the largest of the six), L, and
    an audit sample of at most PANEL_AUDIT_WALLS walls per record. ValueError when the records hold different L.
    T18-APP-03: panel_call_ns, the achieved trial wall (the sum of the 6 x L timed calls), so that the host can flag a warm
    trial below the 0.5 s target of G7.3 (a report only; the medians decide)."""
    counts={len(w) for w in walls.values()}
    if len(counts)!=1 or 0 in counts or not all(type(x) is int and x>=0 for w in walls.values() for x in w):raise ValueError('panel walls rejected')
    def median(w):
        s=sorted(w);n=len(s);return s[n//2] if n%2 else (s[n//2-1]+s[n//2])/2
    return {'panel_passes':counts.pop(),'panel_stats':{c:{'median_ns':median(w),'min_ns':min(w),'max_ns':max(w)} for c,w in walls.items()},
            'panel_walls':{c:list(w[:PANEL_AUDIT_WALLS]) for c,w in walls.items()},'panel_call_ns':sum(sum(w) for w in walls.values())}

def _events(channel,start,trial_id,kind=None,phase=None):
    return [e for e in channel.events[start:] if e['msg'].get('trial')==trial_id and (kind is None or e['msg'].get('m')==kind) and (phase is None or e['msg'].get('phase')==phase)]

EXC_LINE=re.compile(r'^([A-Za-z_][A-Za-z0-9_.]{0,80})(?::|$)')

def error_class(log):
    """The exception class name of the last traceback line in a child log (no message text, agent context rule)."""
    try:lines=[l for l in Path(log).read_text(errors='replace')[-65536:].splitlines() if l and not l.startswith(' ')]
    except OSError:return 'no log'
    for line in reversed(lines):
        m=EXC_LINE.match(line)
        if m and (m.group(1).endswith(('Error','Exception','Exit','Interrupt')) or '.' in m.group(1)):return m.group(1)
    return 'no exception line'

class ChildExited(RuntimeError):
    """A trial child ended before the handshake the coordinator waits for. Keeps the child exit code and the exception
    class of its log (error_class: a bounded identifier, no message text) for the failure row."""
    returncode=None;error_class=None

CHILD_CLASS=re.compile(r'[A-Za-z_][A-Za-z0-9_.]{0,80}')

def failure_row(error):
    """The coordinator's last line for an uncaught error: the error type; for ChildExited also the child exit code (int)
    and exception class (bounded identifier). Any other field or value is dropped (agent context rule: no raw output)."""
    row={'status':'FAILED','error_type':type(error).__name__}
    if isinstance(error,ChildExited):
        code=error.returncode;name=error.error_class
        row['child_exit_code']=code if type(code) is int and -512<=code<=512 else None
        row['child_error_class']=name if name in ('no log','no exception line') or (isinstance(name,str) and CHILD_CLASS.fullmatch(name)) else None
    return row

def fresh_log(directory,key):
    """The stderr log of a new trial child. A fresh child after a call-deadline kill gets a new file (key-2.log, ...), so
    the killed child's log stays as evidence."""
    base=key.replace(':','-');path=Path(directory)/(base+'.log');n=2
    while path.exists():path=Path(directory)/f'{base}-{n}.log';n+=1
    return path

def child_key(trial):
    """One trial child per variant, workers, mode and (Amendment G4.2) selector; `all` keeps the Phase 1 key."""
    key=f"{trial['variant']}:{trial['workers']}:{trial['mode']}";selector=trial.get('selector','all')
    route=trial.get('route')                       # Task 19: the route next to the selector; a Python row keeps its Phase 1 key
    if route is not None:
        if route not in ('stdio','shm','inproc'):raise ValueError('route rejected')
        key=f'{key}:{route}'
    if not isinstance(selector,str) or not SELECTOR_RE.fullmatch(selector):raise ValueError('selector rejected')
    return key if selector=='all' else f'{key}:{selector}'

WARM_START_FAILED='warm C start failed'

def blocked_start_row(trial,error):
    """N4-A10: the BLOCKED row of a warm C child that exited during its start (ChildExited): its variant, workers, route,
    mode and selector, and a reason with the bounded exit code and exception class of failure_row only."""
    f=failure_row(error)
    return {'variant':trial['variant'],'workers':trial['workers'],'route':trial.get('route'),'mode':trial['mode'],'selector':trial.get('selector','all'),
            'trials':[],'reason':f"{WARM_START_FAILED} (child exit {f.get('child_exit_code')}, {f.get('child_error_class')})"}

def deadline_row(plan,channel,child,trial,reason):
    """G2.6: the failed observation of a trial killed at its call deadline: no result and never a time that can count
    (eligible False, failures call-deadline 1, the declared reason). The interval ends at the reap."""
    begin=next(iter(_events(channel,child.last_start,trial['trial_id'],'begin','caller')),None);end={'sample':channel.reader(),'msg':{}}
    note={'eligible':False,'failures':{'call-deadline':1},'work_units':0,'result_sha256':None,'reduction':'NOT_RUN'}
    row=observation(plan,trial,'caller',begin or end,end,note,'safe-c-trial-runner',trial.get('warmup',False));row['failure_reason']=reason
    return row

class CallerChild:
    def __init__(self,channel,plan,trial,dataset,reference,deadline,memory=False,extra=None):
        self.channel=channel;self.trial=trial;self.key=child_key(trial);self.start=len(channel.events);self.last_start=self.start;self.left=None
        argv=python_argv(PYTHONPATH,'-m','benchlab.trial','--client',self.key,'--case-manifest',_manifest(plan),'--variant',trial['variant'],'--workers',str(trial['workers']),
                         '--mode',trial['mode'],'--dataset',dataset['path'],'--sha256',dataset['sha256'],'--reference',reference,*(['--memory'] if memory else []),
                         '--selector',trial.get('selector','all'),*(['--panel'] if 'panel' in trial else []),     # base Task 18: single-record panel trials (G7.3)
                         '--route',trial.get('route') or 'none',*(['--route-label',trial['route_label']] if trial.get('route') and isinstance(trial.get('route_label'),str) else []))   # Task 19
        self.log=fresh_log(WORK/'bench/private',self.key);self.foreign=[]
        with self.log.open('wb') as log:      # G2.6: each child leads its own process group, so a call deadline kills the whole group
            self.proc=subprocess.Popen(argv,env=child_env(channel.path,extra),stdout=subprocess.DEVNULL,stderr=log,start_new_session=True)   # Task 19: SAFE_C_BENCH_ROLE=caller (+ SAFE_C_BENCH_NATIVE)
        startup='startup:'+self.key if (trial['variant'] in POOLED or trial['variant'].startswith('c-')) and trial['mode']=='warm' else None   # Task 19: a warm C worker or library starts here
        # Wait for the child's last startup message (identity note, warm pool start, memory ready) before any command:
        # a command sent earlier would reach the child while it waits for an acknowledgement.
        self._pump(lambda:self.key in channel.open and _events(channel,self.start,'identity:'+self.key,'note') and (startup is None or _events(channel,self.start,startup,'end')) and (not memory or _events(channel,self.start,self.key,'end','ready')),deadline)
    def _pump(self,until,deadline):
        self.channel.pump(lambda:until() or self.proc.poll() is not None,deadline)
        if until():return
        if self.proc.poll() is None:raise TimeoutError(f'trial child {self.key}: handshake deadline')
        name=error_class(self.log);exc=ChildExited(f'trial child {self.key} exited with {self.proc.returncode} ({name})')
        exc.returncode=self.proc.returncode;exc.error_class=name;raise exc
    def identity(self):
        ev=_events(self.channel,self.start,'identity:'+self.key,'note')
        return {k:v for k,v in ev[0]['msg'].items() if k not in ('m','trial')} if ev else None
    def call(self,trial,size,deadline):
        start=len(self.channel.events);self.last_start=start;armed=trial.get('call_deadline_seconds') is not None
        limit=min(deadline,time.monotonic()+float(trial['call_deadline_seconds'])) if armed else deadline
        # base Task 18 (G7.3, H21.4): a panel trial names its rows (cell order), L passes, the cell labels and the panel
        # reference status of each row; the child times each one-row call and notes panel_walls, panel_status_diff and detail
        panel={'panel':{'indices':trial['panel'],'passes':trial['panel_passes'],'cells':trial['panel_cells'],'reference_status':trial['panel_reference_status']}} if 'panel' in trial else {}
        self.channel.send(self.key,{'op':'call','trial':trial['trial_id'],'size':size,**panel})
        try:self._pump(lambda:_events(self.channel,start,trial['trial_id'],'note'),limit)
        except TimeoutError:
            if not armed:raise
            self.left=kill_group(self.proc,foreign=self.foreign);raise DeadlineKilled(deadline_reason(trial)) from None    # G2.6: outside the child
        return start
    def shutdown(self,deadline):
        start=len(self.channel.events);self.channel.send(self.key,{'op':'shutdown'})
        self._pump(lambda:_events(self.channel,start,'teardown:'+self.key,'end'),deadline)
        try:self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:self.proc.kill();self.proc.wait()
        return start

def run_kernel(channel,plan,trial,dataset,reference,deadline,out):
    spec_path=WORK/f"bench/private/{trial['trial_id']}.json";target=out/'pyperf'/f"{trial['trial_id']}.json";target.parent.mkdir(exist_ok=True)
    spec={'trial_id':trial['trial_id'],'case_manifest':_manifest(plan),'dataset':dataset['path'],'sha256':dataset['sha256'],'reference':reference,'size':plan['sizes'][trial['tier']],
          'variant':trial['variant'],'workers':trial['workers'],'values':plan['pyperf']['values'],'warmups':plan['pyperf']['warmups'],'loops':trial['loops'],'output':str(target)}
    spec_path.write_text(json.dumps(spec));start=len(channel.events);want=spec['values']+spec['warmups']
    with (WORK/f"bench/private/{trial['trial_id']}.log").open('wb') as log:   # isolated master; pyperf starts its worker with the same interpreter arguments
        p=subprocess.Popen(python_argv(PYTHONPATH,'-m','benchlab.kernel_trial'),env=child_env(channel.path,{'SAFE_C_BENCH_SPEC':str(spec_path)}),stdout=subprocess.DEVNULL,stderr=log)
    try:channel.pump(lambda:len(_events(channel,start,trial['trial_id'],'note'))>=want or p.poll() is not None,deadline)
    finally:
        try:p.wait(timeout=max(1.0,deadline-time.monotonic()))
        except subprocess.TimeoutExpired:p.kill();p.wait()
    begins=_events(channel,start,trial['trial_id'],'begin','work');ends=_events(channel,start,trial['trial_id'],'end','work');notes=_events(channel,start,trial['trial_id'],'note')
    rows=[observation(plan,trial,'work',b,e,n['msg'],'pyperf',trial['warmup'] or i<spec['warmups']) for i,(b,e,n) in enumerate(zip(begins,ends,notes))]
    zb=_events(channel,start,trial['trial_id'],'begin','control-zero');ze=_events(channel,start,trial['trial_id'],'end','control-zero')
    zero=[observation(plan,trial,'control-zero',b,e,{},'pyperf',True) for b,e in zip(zb,ze)]
    ident=_events(channel,start,'identity:'+trial['trial_id'],'note')
    identity=dict({k:v for k,v in ident[0]['msg'].items() if k not in ('m','trial')},client=trial['trial_id']) if ident else {'client':trial['trial_id'],'isolated':None}
    return rows,zero,(target.name if target.is_file() else None),p.returncode,identity

def _pairs_of(channel,start,trial_id,phase):return list(zip(_events(channel,start,trial_id,'begin',phase),_events(channel,start,trial_id,'end',phase)))

@job('timing')
def job_timing(plan,out):
    try:extra=_bench_native.caller_env(plan)            # Task 19: verified restored binaries before any child starts
    except ValueError:return {'status':'FAIL','reason':'restored native binary digest mismatch','observations':0,'files':[]}
    before=_bench_native.native_shm_snapshot()          # Task 19 (Amendment F item 10 (d))
    channel=Channel(WORK/'bench/marker.sock');deadline=time.monotonic()+plan['deadline_seconds']-30;observations=[];phases=[];files=[];children={};exits=[];identities=[];killed=[]
    blocked={}         # N4-A10: child key -> the BLOCKED row of a warm C child that exited during its start
    (WORK/'bench/private').mkdir(parents=True,exist_ok=True)
    first=(read_counters().get('cpu') or {}).get('usage_usec')       # B15 (Amendment H7): the coordinator window starts here
    try:
        dataset=materialize_dataset(plan);reference=reference_path(plan,dataset)
        for trial in plan['trials']:
            if trial['scope']=='kernel' and trial['variant'].startswith('c-'):     # Task 19: native kernel trials, no Python in the timed loops
                rows,phases_k,files_k=_bench_native.run_native_kernel(channel,plan,trial,dataset,reference,deadline,out);observations+=rows;phases+=phases_k;files+=files_k
                continue
            if trial['scope']=='kernel':
                rows,zero,name,code,ident=run_kernel(channel,plan,trial,dataset,reference,deadline,out);observations+=rows;phases+=zero;exits.append(code);identities.append(ident)
                if name:files.append('pyperf/'+name)
                continue
            key=child_key(trial)
            if key in blocked:blocked[key]['trials'].append(trial['trial_id']);continue      # N4-A10: one start attempt per row
            if key not in children:
                try:children[key]=CallerChild(channel,plan,trial,dataset,reference,deadline,extra=extra)
                except ChildExited as error:     # N4-A10: a failed warm C start BLOCKS that row only; a Python start failure ends the job
                    if not (trial['variant'].startswith('c-') and trial['mode']=='warm'):raise
                    blocked[key]=blocked_start_row(trial,error);blocked[key]['trials'].append(trial['trial_id']);continue
                c=children[key];identities.append(dict(c.identity() or {},client=key))
                for b,e in _pairs_of(channel,c.start,'startup:'+key,'pool_start'):phases.append(observation(plan,trial,'pool_start',b,e,{},'safe-c-trial-runner',True))
            try:start=children[key].call(trial,plan['sizes'][trial['tier']],deadline);tid=trial['trial_id']
            except DeadlineKilled as error:     # G2.6: a failed observation with the reason; the next trial of this key starts a fresh child
                c=children.pop(key);observations.append(deadline_row(plan,channel,c,trial,error.reason));killed.append({'trial_id':trial['trial_id'],'left':c.left,'foreign_orphans':len(c.foreign)});continue
            b=_events(channel,start,tid,'begin','caller')[0];e=_events(channel,start,tid,'end','caller')[0];n=_events(channel,start,tid,'note')[0]['msg']
            observations.append(observation(plan,trial,'caller',b,e,n,'safe-c-trial-runner',trial['warmup']))
            for tb,te in _pairs_of(channel,start,tid+':teardown','teardown'):phases.append(observation(plan,trial,'teardown',tb,te,{},'safe-c-trial-runner',True))
        for key,c in children.items():
            start=c.shutdown(deadline);exits.append(c.proc.returncode)
            for tb,te in _pairs_of(channel,start,'teardown:'+key,'teardown'):phases.append(observation(plan,c.trial,'teardown',tb,te,{},'safe-c-trial-runner',True))
    finally:
        for c in children.values():
            if c.proc.poll() is None:c.proc.kill();c.proc.wait()
        channel.close()
    (out/'observations.jsonl').write_text(''.join(json.dumps(o,sort_keys=True)+'\n' for o in observations))
    (out/'phases.jsonl').write_text(''.join(json.dumps(o,sort_keys=True)+'\n' for o in phases))
    skipped=sum(len(b['trials']) for b in blocked.values())       # N4-A10: the trials of a BLOCKED row have no observation
    ok=len({o['trial_id'] for o in observations})+skipped==len(plan['trials']) and all(code==0 for code in exits)
    ok=ok and all(k['left']==0 for k in killed)       # a group member that survived its kill is never a clean session
    left=_bench_native.job_end_check(before)            # Task 19: FAIL when a shared-memory segment is left
    last=(read_counters().get('cpu') or {}).get('usage_usec')        # B15: the coordinator window ends here
    return {'status':'PASS' if ok and not left else 'FAIL','observations':len(observations),'files':['observations.jsonl','phases.jsonl']+files,'child_exit_codes':exits,
            **({'reason':_bench_native.SHM_LEFT,'shm_left':len(left)} if left else {}),
            'children':identities,'reference_sha256':hashlib.sha256(Path(reference).read_bytes()).hexdigest(),**({'deadline_kills':killed} if killed else {}),
            **({'blocked_rows':list(blocked.values())} if blocked else {}),
            'cgroup_window':{'first_usage_usec':first,'last_usage_usec':last},'cgroup_inode':os.stat(CG).st_ino}

@job('memory')
def job_memory(plan,out):
    try:extra=_bench_native.caller_env(plan)            # Task 19
    except ValueError:return {'status':'FAIL','reason':'restored native binary digest mismatch','files':[],'child_exit_codes':[],'children':[]}
    before=_bench_native.native_shm_snapshot()
    channel=Channel(WORK/'bench/marker.sock');deadline=time.monotonic()+plan['deadline_seconds']-30;t=dict(plan['trial'],block=None,order=None,scope='memory',loops=1,warmup=False)
    (WORK/'bench/private').mkdir(parents=True,exist_ok=True);c=None;reason=None
    try:
        dataset=materialize_dataset(plan)        # no reference in a memory trial: eligibility comes from the timing session (digest match)
        c=CallerChild(channel,plan,t,dataset,'none',deadline,memory=True,extra=extra);ready=_events(channel,c.start,c.key,'begin','ready')[0]['sample']
        try:start=c.call(t,plan['sizes'][t['tier']],deadline)
        except DeadlineKilled as error:   # G2.6: FAIL with the declared reason; the failed row is kept, never a memory figure
            reason=error.reason;row=deadline_row(plan,channel,c,t,reason);code=None;identity=c.identity()
        else:
            c._pump(lambda:_events(channel,start,c.key,'end','post-work'),deadline)
            post=_events(channel,start,c.key,'begin','post-work')[0]['sample'];tid=t['trial_id']
            row=observation(plan,t,'caller',_events(channel,start,tid,'begin','caller')[0],_events(channel,start,tid,'end','caller')[0],_events(channel,start,tid,'note')[0]['msg'],'safe-c-trial-runner',False)
            ms=lambda s,k:(s.get('memory_stat') or {}).get(k)
            row['memory']={'ready_current':ready.get('memory_current'),'ready_anon':ms(ready,'anon'),'ready_file':ms(ready,'file'),'ready_shmem':ms(ready,'shmem'),
                           'retained_current':post.get('memory_current'),'retained_anon':ms(post,'anon'),'retained_file':ms(post,'file'),'retained_shmem':ms(post,'shmem'),
                           'group_peak_bytes':None,'group_peak_source':'host memory.peak, trial container lifetime','sampled':None}
            c.shutdown(deadline);code=c.proc.returncode;identity=c.identity()
    finally:
        if c is not None and c.proc.poll() is None:c.proc.kill();c.proc.wait()
        channel.close()
    (out/'memory.jsonl').write_text(json.dumps(row,sort_keys=True)+'\n')
    left=_bench_native.job_end_check(before)            # Task 19
    if reason is not None:return {'status':'FAIL','failure_reason':reason,'files':['memory.jsonl'],'child_exit_codes':[],'children':[dict(identity or {},client=c.key)]}
    if left:return {'status':'FAIL','reason':_bench_native.SHM_LEFT,'files':['memory.jsonl'],'child_exit_codes':[code],'children':[dict(identity or {},client=c.key)]}
    return {'status':'PASS' if code==0 else 'FAIL','files':['memory.jsonl'],'child_exit_codes':[code],'children':[dict(identity or {},client=c.key)]}

# ---- Task 17: cProfile profiling (diagnostic only; never compared with unprofiled runs) ----
PROFILE_LABEL='profiled run; diagnostic only, never compared with unprofiled runs'
MAX_PROFILE_VARIANTS=8;MAX_PROFILE_ROWS=1<<20

def run_group(argv,timeout):
    """Review fix: run one child in its own process group. Past `timeout` the whole group (spawned pool workers included)
    is killed; after a normal exit any member left behind is killed too. Returns returncode, stdout, stderr, timed_out."""
    import signal, types
    p=subprocess.Popen(argv,env=child_env(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True);timed=False
    try:out,err=p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed=True
        try:os.killpg(p.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        out,err=p.communicate()
    try:os.killpg(p.pid,signal.SIGKILL)
    except (ProcessLookupError,PermissionError):pass
    return types.SimpleNamespace(returncode=p.returncode,stdout=out,stderr=err,timed_out=timed)

def _profile_row(variant,run):
    """The child's last JSON line, with its file names re-checked; any other output is a failed profile."""
    row=None
    if run.returncode==0 and run.stdout.strip():
        try:row=json.loads(run.stdout.splitlines()[-1])
        except ValueError:row=None
    if not isinstance(row,dict) or row.get('variant')!=variant or not isinstance(row.get('files'),list) or not row.get('top'):
        return {'variant':variant,'error':'profile failed','exit_code':run.returncode,'label':PROFILE_LABEL,'files':[]}
    row['files']=[f for f in row['files'] if isinstance(f,str) and FILE_RE.fullmatch(f) and f not in ('.','..')][:MAX_FILES]
    row['label']=PROFILE_LABEL;return row

@job('profile')
def job_profile(plan,out):
    """bench profile: one isolated child per variant runs benchlab.profiling on a seeded synthetic dataset. Writes
    profile.json and pstats/*.pstats. A profile is a separate run from every timing run."""
    manifest=plan.get('case_manifest');variants=plan.get('variants');rows=plan.get('rows');seed=(plan.get('dataset') or {}).get('seed')
    if not case_manifest_allowed(manifest):return {'status':'FAIL','reason':'case manifest path rejected'}
    if (not isinstance(variants,list) or not 1<=len(variants)<=MAX_PROFILE_VARIANTS or len(set(map(str,variants)))!=len(variants)
        or not all(isinstance(v,str) and NAME_RE.fullmatch(v) for v in variants)):return {'status':'FAIL','reason':'profile variants rejected'}
    if isinstance(rows,bool) or not isinstance(rows,int) or not 1<=rows<=MAX_PROFILE_ROWS or isinstance(seed,bool) or not isinstance(seed,int):
        return {'status':'FAIL','reason':'profile size or seed rejected'}
    if (plan.get('dataset') or {}).get('kind')!='synthetic':return {'status':'FAIL','reason':'profiling runs on synthetic data only'}
    target=out/'pstats';target.mkdir(parents=True,exist_ok=True);results=[];stop=time.monotonic()+plan['deadline_seconds']-30
    for variant in variants:
        left=stop-time.monotonic()
        if left<=1:results.append({'variant':variant,'error':'deadline','label':PROFILE_LABEL,'files':[]});continue
        run=run_group(python_argv(PYTHONPATH,'-m','benchlab.profiling',manifest,variant,rows,seed,str(target)),timeout=left)
        with open(out/'profile.log','a') as log:log.write((run.stderr or '')[-65536:])
        if run.timed_out:results.append({'variant':variant,'error':'deadline','label':PROFILE_LABEL,'files':[]});continue
        results.append(_profile_row(variant,run))
    (out/'profile.json').write_text(json.dumps(results,sort_keys=True))
    return {'status':'PASS' if all('error' not in r for r in results) else 'FAIL','label':PROFILE_LABEL,
            'files':['profile.json']+['pstats/'+f for r in results for f in r.get('files',[])]}

# ---- Task 18: owner-fixture local run (spec 12) ----

LOCAL_LIMIT=262144

def local_check(directory):
    """--local-check DIR: exit 0 only when DIR holds exactly one regular aggregate.json (not a link) of at most 256 KiB."""
    if not isinstance(directory,str) or not PROJECT_RE.fullmatch(directory) or '..' in directory.split('/'):return 3
    out=WORK/directory;a=out/'aggregate.json'
    try:names=sorted(p.name for p in out.iterdir())
    except OSError:return 3
    return 0 if names==['aggregate.json'] and not a.is_symlink() and a.is_file() and a.stat().st_size<=LOCAL_LIMIT else 3

@job('stderr-probe')
def job_stderr_probe(plan,out):
    sys.stderr.write('synthetic value 412.35\n');sys.stderr.flush();return {'status':'PASS'}

def _dist(xs):
    xs=sorted(xs)
    if not xs:return {'n':0,'median':None,'iqr':None,'min':None,'max':None}
    def q(p):
        h=(len(xs)-1)*p;i=int(h);return xs[i]+(h-i)*(xs[min(i+1,len(xs)-1)]-xs[i])
    return {'n':len(xs),'median':q(0.5),'iqr':q(0.75)-q(0.25),'min':xs[0],'max':xs[-1]}

LOCAL_EXC=('TimeoutError','MemoryError','OSError','ValueError')      # framework exception names; a plan adds the protocol's local_exceptions
AGGREGATE_SCHEMA=SRC/'schemas/bench-local-aggregate.json'
STATS_KEYS=('rows','result_sha256','reference_sha256')    # FR3: the framework keys of local_summary; every other key is the project summary
LOCAL_NAMES=[]     # the protocol's local_exceptions of the running local job (set by job_local)
LOCAL_HAS_SUMMARY=("import json,sys;from benchlab.workload import load_case_adapter;a=load_case_adapter(json.load(open(sys.argv[1])));"
                   "sys.exit(0 if callable(getattr(a,'local_summary',None)) else 3)")
LOCAL_SUMMARY=("import json,sys;from benchlab.workload import load_case_adapter;a=load_case_adapter(json.load(open(sys.argv[4])));"
               "n=int(sys.argv[2]);d=a.slice(a.load({'path':sys.argv[1],'sha256':sys.argv[5]}),n);ref=a.slice_result(json.load(open(sys.argv[3])),n,d);"
               "sys.stdout.write(json.dumps(a.local_summary(d,ref))+'\\n')")

def _exception_row(error):
    name=type(error).__name__;return {'type':name if name in LOCAL_EXC or name in LOCAL_NAMES else 'Other','row_index':None}

def _local_timings(obs):
    groups={}
    for o in obs:
        if not o['warmup'] and o['scope'] in ('caller','kernel'):groups.setdefault((o['point'],o['scope'],o['mode'],o['variant'],o['workers'],o['tier']),[]).append(o)
    def per_trial(v,field):   # F-07: per unit = loops x records; inner samples of one trial collapse to their median
        by={}
        for o in v:
            if o['work_units'] and o.get(field) is not None:by.setdefault(o['trial_id'],[]).append(o[field]/(o.get('loops',1)*o['work_units']))
        return [_dist(x)['median'] for x in by.values()]
    return [{'point':k[0],'scope':k[1],'mode':k[2],'variant':k[3],'workers':k[4],'tier':k[5],'trials':len({o['trial_id'] for o in v}),'eligible':all(o['eligible'] for o in v),
             'wall_ns_per_unit':_dist(per_trial(v,'wall_ns')),'cpu_ns_per_unit':_dist([x*1000.0 for x in per_trial(v,'cpu_usage_usec')])}
            for k,v in sorted(groups.items(),key=str)][:64]

def local_aggregate(plan,stats,timings,obs,exceptions,ok):
    """The closed aggregate (schemas/bench-local-aggregate.json): the framework envelope (rows, timings, counters, exceptions,
    whole-run digests) and `summary`, the project's case block: every key of the adapter's local_summary other than
    STATS_KEYS (FR3: its shape is project data, validated on the host with the protocol's aggregate schema). Without a
    summary it is null and the status is INVALID_EXPERIMENT."""
    summary={k:v for k,v in stats.items() if k not in STATS_KEYS} if stats else None
    return {'schema_version':2,'run_id':plan['run_id'],'case':plan['case'],'dataset_sha256':plan['dataset']['sha256'],'rows':stats['rows'] if stats else 0,
            'summary':summary,'timings':timings,'counters':{'cpu_usage_usec':sum(o['cpu_usage_usec'] or 0 for o in obs),'memory_peak_bytes':read_counters().get('memory_peak')},
            'exceptions':exceptions[:64],'output_digests':{'result_sha256':stats['result_sha256'] if stats else '0'*64,'reference_sha256':stats['reference_sha256'] if stats else '0'*64},
            'status':'VALID' if ok and summary is not None else 'INVALID_EXPERIMENT'}

def _write_aggregate(out,agg,plan=None):
    """One JSON document without NaN or infinity; a summary that holds one is replaced by the empty INVALID_EXPERIMENT block."""
    try:text=json.dumps(agg,sort_keys=True,separators=(',',':'),allow_nan=False)
    except ValueError:
        try:json.dumps(agg['timings'],allow_nan=False);timings=agg['timings']
        except ValueError:timings=[]
        empty=local_aggregate(plan,None,timings,[],agg['exceptions'][:63]+[{'type':'ValueError','row_index':None}],False)
        empty['counters']=agg['counters'];text=json.dumps(empty,sort_keys=True,separators=(',',':'),allow_nan=False)
    (out/'aggregate.json').write_text(text)

TIMING_RESERVE=30   # job_timing ends its own deadline 30 s before the job deadline

def set_local_names(plan):
    """FR3: the protocol's local_exceptions the host put in the plan (at most 16 class names); ValueError otherwise."""
    names=plan.get('local_exceptions',[])
    if not isinstance(names,list) or len(names)>16 or not all(isinstance(n,str) and re.fullmatch(r'[A-Z][A-Za-z0-9]{1,40}',n) for n in names):
        raise ValueError('local_exceptions rejected')
    LOCAL_NAMES[:]=names

@job('local')
def job_local(plan,out):
    """Owner fixture: trials run into a private directory; the only artifact is the closed aggregate document. A case whose
    adapter has no local_summary is refused before any trial (exit 3, aggregate status INVALID_EXPERIMENT; Amendment A).
    FR3: the market step of the example project left the framework (FR3 handoff list)."""
    private=WORK/'bench/private/out';private.mkdir(parents=True,exist_ok=True);exceptions=[];stats=None
    try:set_local_names(plan)
    except ValueError:_write_aggregate(out,local_aggregate(plan,None,[],[],[],False));return {'status':'FAIL'}
    has=subprocess.run(python_argv(PYTHONPATH,'-c',LOCAL_HAS_SUMMARY,_manifest(plan)),env=child_env(),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=120)
    if has.returncode!=0:
        _write_aggregate(out,local_aggregate(plan,None,[],[],[],False));return {'status':'REFUSED' if has.returncode==3 else 'FAIL'}
    return _local_trials(plan,out,private,exceptions,stats)

def _local_trials(plan,out,private,exceptions,stats):
    try:timing=job_timing(dict(plan,local=False),private)
    except Exception as error:timing={'status':'FAIL'};exceptions.append(_exception_row(error))
    obs=[json.loads(x) for x in (private/'observations.jsonl').read_text().splitlines()] if (private/'observations.jsonl').is_file() else []
    reference=WORK/'bench/private/reference.json'
    if reference.is_file():
        try:
            run=subprocess.run(python_argv(PYTHONPATH,'-c',LOCAL_SUMMARY,str(WORK/'bench/data/dataset'),plan['rows'],str(reference),_manifest(plan),plan['dataset']['sha256']),
                               env=child_env(),stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=600)
            stats=json.loads(run.stdout.splitlines()[-1]) if run.returncode==0 and run.stdout.strip() else None
            if stats is not None and not (isinstance(stats,dict) and all(k in stats for k in STATS_KEYS) and len(stats)<=32+len(STATS_KEYS)):stats=None
            if stats is None:exceptions.append({'type':'Other','row_index':None})
        except Exception as error:exceptions.append(_exception_row(error))
    timings=_local_timings(obs)
    ok=timing['status']=='PASS' and stats is not None and bool(timings) and all(t['eligible'] for t in timings)
    _write_aggregate(out,local_aggregate(plan,stats,timings,obs,exceptions,ok),plan)
    return {'status':'PASS' if ok else 'FAIL'}

JOBS['coverage']=lambda plan,out:importlib.import_module('benchlab.coverage').job(plan,out)    # Amendment G8.4 (Task 3): B09 coverage

def _configured_job(plan,out):
    """G-ALO-CO: the request limit is set before the project path and before any child starts."""
    try:set_request_limit(plan)
    except ValueError:return {'status':'FAIL','reason':'request_limit rejected'}
    try:set_test_env(plan)
    except ValueError:return {'status':'FAIL','reason':'test_env rejected'}
    try:configure_project(plan)
    except ValueError:return {'status':'FAIL','reason':'project_dir rejected'}
    return JOBS[plan['job']](plan,out)

def main(argv):
    if argv[1]=='--local-check':return local_check(argv[2])          # Task 18: the artifact directory of a local job
    plan=json.loads((WORK/argv[1]).read_text())
    out=WORK/plan.get('output','bench/out');out.mkdir(parents=True,exist_ok=True)
    try:selftest_mutation(plan)
    except ValueError:result={'status':'FAIL','reason':'selftest mutation rejected'}
    else:result=_configured_job(plan,out)
    if not plan.get('local'):
        (out/'result.json').write_text(json.dumps(result,sort_keys=True));print(json.dumps(result,sort_keys=True))
    return {'PASS':0,'BLOCKED':2,'REFUSED':3}.get(result.get('status'),1)

if __name__=='__main__':
    try:sys.exit(main(sys.argv))
    except Exception as error:
        print(json.dumps(failure_row(error)));sys.exit(1)
