"""Coordinator jobs of the Phase 2 bench cases (Phase 2 Task 23, framework part; task EX-13): `native-overlap` (B04),
`agreement-controls` (B06, P16) and `failure-controls` (B16).

Registered by one line in bench-coordinator.py; `g` is its globals(). Framework code, record-agnostic: the project's
declared trace program (bench.json native.trace) and its case adapter supply every project value; the failure controls
use only the framework stub worker and the framework client benchlab.native_worker. Every child is reaped before the job
returns; the job output is one JSON record per job, read on the host by tools/bench_phase2.py."""
import hashlib, json, os, re, selectors, signal, subprocess, sys, time
from pathlib import Path

NATIVE_DIR=Path('/work/bench/private/native')
PROGRAM_RE=re.compile(r'^[a-z][a-z0-9_-]{0,62}$');SHA256_RE=re.compile(r'^[0-9a-f]{64}$')
NAME_RE=re.compile(r'^[a-z][a-z0-9-]{2,40}$');ROUTE_RE=re.compile(r'^(stdio|shm|inproc|none)$')
TRACE_CAP=1048576;TRACE_SECONDS=120;TRACE_LINES=4096
STUB=Path('/src/benchmarks/performance/python/tests/stub_worker.py')
FAILURE_CASES=(('worker-error','error',5.0),('eof','exit',5.0),('partial-response','partial',5.0),('deadline','sleep',0.5),('crash','segv',5.0))
CRASH_TRIAL={'trial_id':'caller-crash-00','variant':'py-reference','workers':'direct','mode':'warm','scope':'caller','tier':'tiny','warmup':False,
             'block':0,'order':0,'point':'caller-crash','selector':'all','route':None}
AGREEMENT_ROWS_MAX=4096;MUTATIONS_MAX=16
_COORD={}

def _fail(reason,**extra):return {'status':'FAIL','reason':reason,'files':[],**extra}

def _children():
    """The pids of this process's direct children (/proc/self/task/*/children)."""
    out=set()
    for task in Path('/proc/self/task').iterdir():
        try:out|={int(x) for x in (task/'children').read_text().split()}
        except (OSError,ValueError):pass
    return out

def _capped_run(proc,deadline):
    """stdout of a started process, read until EOF, at most TRACE_CAP bytes (stderr is counted, not kept); kills and reaps
    the process at the deadline or above the cap. Returns (bytes, truncated, timed_out)."""
    out=bytearray();truncated=False;timed_out=False;end=time.monotonic()+deadline
    with selectors.DefaultSelector() as sel:
        for stream in (proc.stdout,proc.stderr):
            os.set_blocking(stream.fileno(),False);sel.register(stream.fileno(),selectors.EVENT_READ,stream)
        open_=2
        while open_:
            left=end-time.monotonic()
            if left<=0:timed_out=True;break
            for key,_ in sel.select(left):
                try:chunk=os.read(key.fd,65536)
                except BlockingIOError:continue
                if not chunk:sel.unregister(key.fd);open_-=1;continue
                if key.data is proc.stdout:
                    if len(out)+len(chunk)>TRACE_CAP:truncated=True
                    else:out+=chunk
            if truncated:break
    if truncated or timed_out:
        try:proc.kill()
        except ProcessLookupError:pass
    try:proc.wait(max(1.0,end-time.monotonic()))
    except subprocess.TimeoutExpired:
        proc.kill();proc.wait()
    for s in (proc.stdin,proc.stdout,proc.stderr):
        try:s.close()
        except (OSError,AttributeError):pass
    return bytes(out),truncated,timed_out

def overlap(plan,out,g):
    """native-overlap: the declared trace program from its verified restored binary, once; the record holds its exit
    code, its stdout lines, the affinity size of this job, the cgroup CPU delta and the wall time of the run."""
    nb=g['_bench_native'];nw=nb._benchlab('native_worker')
    trace=plan.get('trace');native=plan.get('native') or {}
    program=trace.get('program') if isinstance(trace,dict) and set(trace)=={'program'} else None
    if not isinstance(program,str) or not PROGRAM_RE.fullmatch(program) or program not in native:return _fail('trace program rejected')
    try:nb.native_env(plan)
    except ValueError:return _fail(nb.MISMATCH)
    digest=native[program];affinity=len(os.sched_getaffinity(0));before=g['read_counters']();t0=time.perf_counter_ns()
    path=str(NATIVE_DIR/program)
    try:fd,identity=nw.open_verified(path,digest)
    except nw.BinaryRefused:return _fail('trace program refused')
    try:
        proc=subprocess.Popen([program],executable=nw.fd_path(fd),stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                              env={},close_fds=True,pass_fds=(fd,),cwd='/work/bench/private')
        # FR7b-IDENTITY-RULE-01: the path must still name the verified file after the start (a replaced file is refused)
        try:nw.confirm_verified(fd,digest,identity,path)
        except nw.BinaryRefused:
            proc.kill();proc.wait();return _fail('trace program refused')
    finally:os.close(fd)
    data,truncated,timed_out=_capped_run(proc,min(TRACE_SECONDS,float(plan['deadline_seconds'])/2))
    wall=time.perf_counter_ns()-t0;after=g['read_counters']()
    cb=(before.get('cpu') or {}).get('usage_usec');ca=(after.get('cpu') or {}).get('usage_usec')
    lines=data.decode('ascii','replace').splitlines()
    doc={'program':program,'sha256':digest,'exit':proc.returncode,'lines':lines[:TRACE_LINES],'line_count':len(lines),'stdout_bytes':len(data),
         'truncated':truncated or len(lines)>TRACE_LINES,'timed_out':timed_out,'affinity':affinity,
         'cgroup_cpu_usec':ca-cb if isinstance(ca,int) and isinstance(cb,int) else None,'wall_ns':wall}
    (out/'overlap.json').write_text(json.dumps(doc,sort_keys=True))
    ok=proc.returncode==0 and not doc['truncated'] and not timed_out
    return {'status':'PASS' if ok else 'FAIL','files':['overlap.json'],'exit':proc.returncode}

AGREEMENT_CODE=r'''
import hashlib,json,os,sys,tempfile
from benchlab.workload import load_case_adapter
from benchlab import agreement
case=json.load(open(sys.argv[1]));a=load_case_adapter(case)
variant=sys.argv[2];workers='direct' if sys.argv[3]=='direct' else int(sys.argv[3]);route=None if sys.argv[4]=='none' else sys.argv[4]
rows=int(sys.argv[5]);seed=int(sys.argv[6]);extra=json.loads(sys.argv[7]);out=sys.argv[8]
def data_of(s):
    d=a.synthesize(rows,s);p=os.path.join(tempfile.mkdtemp(),'d');open(p,'wb').write(d)
    return a.load({'path':p,'sha256':hashlib.sha256(d).hexdigest()})
def c_result(d):
    a.route=route
    try:return a.materialize(a.run(a.prepare(d,variant,workers),variant,workers))
    finally:
        stop=getattr(a,'native_stop',None)
        if callable(stop):stop(variant,workers)
def eligible(r,ref,d):
    v=a.validate(r,ref,d)
    return bool(v.get('eligible')) if isinstance(v,dict) else False
d1=data_of(seed);d2=data_of(seed+1);ref=a.reference(d1);c1=c_result(d1);c2=c_result(d2);base=a.digest(c1)
doc={'variant':variant,'route':route,'rows':rows,'reference_sha256':a.digest(ref),'control':{'eligible':eligible(c1,ref,d1),'result_sha256':base},
     'seeds':[{'seed':seed,'result_sha256':base},{'seed':seed+1,'result_sha256':a.digest(c2)}],'mutations':{}}
for name in agreement.GENERIC:
    m=agreement.apply(name,c1,units=a.work_units(c1),slice_result=a.slice_result,data=d1,other=c2)
    doc['mutations'][name]={'changed':m is not None and a.digest(m)!=base,'eligible':None if m is None else eligible(m,ref,d1)}
hook=getattr(a,'agreement_mutation',None)
for name in extra:
    m=hook(name,c1,d1) if callable(hook) else None
    doc['mutations'][name]={'changed':m is not None and a.digest(m)!=base,'eligible':None if m is None else eligible(m,ref,d1),'realized':callable(hook)}
json.dump(doc,open(out,'w'),sort_keys=True)
'''

def agreement_controls(plan,out,g):
    """agreement-controls: in a caller child with the verified binaries, the generic mutations of benchlab.agreement and
    the project mutations of the plan (protocol agreement_mutations, through the adapter hook agreement_mutation) on the C
    result of `rows` synthetic rows, each re-validated with the adapter's validate; the C result of a second seed too."""
    nb=g['_bench_native']
    variant=plan.get('variant');workers=plan.get('workers');route=plan.get('route');rows=plan.get('rows');seed=plan.get('seed');extra=plan.get('mutations',[])
    if (not isinstance(variant,str) or not variant.startswith('c-') or not isinstance(workers,str) or not re.fullmatch(r'direct|[1-9][0-9]?',workers)
            or not isinstance(route,str) or not ROUTE_RE.fullmatch(route) or isinstance(rows,bool) or not isinstance(rows,int) or not 2<=rows<=AGREEMENT_ROWS_MAX
            or isinstance(seed,bool) or not isinstance(seed,int) or not 0<=seed<2**62
            or not isinstance(extra,list) or len(extra)>MUTATIONS_MAX or not all(isinstance(m,str) and NAME_RE.fullmatch(m) for m in extra)):
        return _fail('agreement-controls plan rejected')
    try:env=nb.caller_env(plan)
    except ValueError:return _fail(nb.MISMATCH)
    before=nb.native_shm_snapshot();target=Path('/work/bench/private/agreement-controls.json');target.unlink(missing_ok=True)
    try:
        run=subprocess.run(g['python_argv'](g['PYTHONPATH'],'-c',AGREEMENT_CODE,g['_manifest'](plan),variant,workers,route,str(rows),str(seed),json.dumps(extra),str(target)),
                           env=g['child_env'](extra=env),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                           timeout=float(plan['deadline_seconds'])-30)
    except subprocess.TimeoutExpired:return _fail('agreement-controls exceeded its deadline')
    except ValueError:return _fail('case manifest path rejected')
    if run.returncode!=0 or not target.is_file():return _fail('agreement-controls child failed',exit=run.returncode)
    doc=json.loads(target.read_text())
    if plan.get('native_kernel') is not None:
        try:doc['kernel']=kernel_controls(plan,g)
        except (ValueError,OSError,subprocess.SubprocessError) as exc:      # BinaryRefused is a ValueError; FrameError is caught below
            doc['kernel']={'error':type(exc).__name__}
    (out/'agreement-controls.json').write_text(json.dumps(doc,sort_keys=True))
    if nb.job_end_check(before):return _fail(nb.SHM_LEFT)
    return {'status':'PASS','files':['agreement-controls.json']}

def kernel_controls(plan,g):
    """EX13-A02: the real C kernel (the declared kernel program, from its verified restored binary, through the kernel
    handshake) runs once on `rows` synthetic rows; the framework kernel verifier of the timing job (KERNEL_VERIFY_CODE:
    adapter unpack_native and validate against the reference, and native_reference_digest against the kernel's canonical
    digest) then checks three outputs: the real output with the kernel's digest (control), an output of the same length
    that no kernel computed (no-op) and the real output with its digest removed (removed-consumption). Each note keeps the
    verifier's verdict; eligible = validated and canonical_ok, as run_native_kernel decides."""
    nb=g['_bench_native'];nk=nb._benchlab('native_kernel');kernel=plan['native_kernel'];native=plan.get('native') or {}
    program=kernel.get('program') if isinstance(kernel,dict) else None
    if program not in native:raise ValueError('no kernel binary in the plan')
    priv=Path('/work/bench/private/kernel-controls');priv.mkdir(parents=True,exist_ok=True)
    rows=plan['rows'];manifest=g['_manifest'](plan);left=lambda:120.0
    data=priv/'dataset';ref=priv/'reference.json';src=priv/'kernel.in';dst=priv/'kernel.out';zero=priv/'zero.out'
    def child(code,*args,capture=False):
        streams={'capture_output':True,'text':True} if capture else {'stdout':subprocess.DEVNULL,'stderr':subprocess.DEVNULL}
        return subprocess.run(g['python_argv'](g['PYTHONPATH'],'-c',code,*[str(a) for a in args]),env=g['child_env'](),stdin=subprocess.DEVNULL,
                              timeout=left(),**streams)
    if child(g['SYNTH_CODE'],data,rows,plan['seed'],manifest).returncode!=0:raise ValueError('synthetic dataset failed')
    sha=hashlib.sha256(data.read_bytes()).hexdigest()
    if child(g['REFERENCE_CODE'],manifest,data,sha,ref,rows,'[]').returncode!=0:raise ValueError('reference failed')
    if child(nb.KERNEL_PACK_CODE,manifest,data,sha,rows,src).returncode!=0:raise ValueError('kernel pack failed')
    argv=nb.kernel_argv(kernel,{'input':str(src),'records':str(rows),'loops':'1','threads':'0','output':str(dst)})
    try:got=nk.run_kernel(argv,env={},deadline=left(),on_begin=lambda:None,on_end=lambda:None,sha256=native[program])
    except nb._benchlab('native_worker').FrameError:raise ValueError('kernel handshake failed') from None
    summary=got['summary'] or {}
    canonical=(summary.get('extra') or {}).get('digest','')
    canonical=canonical if isinstance(canonical,str) and nb.LITERAL_RE.fullmatch(canonical) else 'none'
    def verify(output,digest):
        run=child(nb.KERNEL_VERIFY_CODE,manifest,data,sha,rows,ref,output,digest,capture=True)
        try:row=json.loads(run.stdout.strip().splitlines()[-1]) if run.returncode==0 else None
        except (ValueError,IndexError):row=None
        if not isinstance(row,dict):return {'validated':False,'canonical_ok':None,'eligible':False,'records':None,'verifier':'refused'}
        validated=bool(row.get('eligible'));ok=row.get('canonical_ok') is True
        return {'validated':validated,'canonical_ok':ok,'eligible':validated and ok,'records':row.get('work_units'),'verifier':'row'}
    notes={'control':verify(dst,canonical)}
    zero.write_bytes(bytes(dst.stat().st_size) if dst.is_file() else b'')
    notes['no-op']=verify(zero,canonical);notes['removed-consumption']=verify(dst,'none')
    for f in (data,ref,src,dst,zero):f.unlink(missing_ok=True)
    return {'program':program,'exit':got['exit'],'status':summary.get('status'),'records':summary.get('records'),'planned_rows':rows,'notes':notes}

def failure_controls(plan,out,g):
    """failure-controls: each failure class of the framework transport against the framework stub worker (worker ERROR,
    EOF, partial response, deadline, a worker that ends by SIGSEGV), a caller child that ends by SIGSEGV, and a normal
    call with its shutdown; then the children and shared-memory segments left."""
    nb=g['_bench_native'];nw=nb._benchlab('native_worker')
    if not STUB.is_file():return _fail('the framework stub worker is missing')
    before=nb.native_shm_snapshot();kids=_children();cases=[];payload=bytes(range(32))
    for name,mode,deadline in FAILURE_CASES:
        w=nw.NativeWorker([sys.executable,'-I',str(STUB),mode],env={},deadline=deadline);cls=None
        try:
            w.start();w.exchange(nw.REQUEST,nw.request_id(1,0),1,0,1,payload,lambda h:len(payload));cls='COMPLETED'
        except nw.FrameError as exc:cls=exc.name
        finally:w.kill()
        cases.append({'case':name,'class':cls,'returncode':w.proc.returncode if w.proc is not None else None,
                      'reaped':w.proc is not None and w.proc.returncode is not None and not w.alive(),'eligible':False if cls!='COMPLETED' else True,
                      'work_units':0 if cls!='COMPLETED' else 1})
    try:cases.append(caller_crash(plan,g))
    except (ValueError,OSError,TimeoutError,subprocess.SubprocessError) as exc:     # the caller path did not run: recorded, never a pass
        cases.append({'case':'caller-crash','error':type(exc).__name__,'framework_row':None,'reaped':None,'observations':None})
    w=nw.NativeWorker([sys.executable,'-I',str(STUB),'echo'],env={},deadline=5.0);normal={'result_kept':False,'returncode':None}
    try:
        w.start();_,got=w.exchange(nw.REQUEST,nw.request_id(1,0),1,0,1,payload,lambda h:len(payload))
        normal={'result_kept':got==payload,'returncode':w.shutdown()}
    except nw.FrameError as exc:normal['class']=exc.name
    finally:w.kill()
    time.sleep(0.1)
    doc={'cases':cases,'normal':normal,'leftover_processes':sorted(_children()-kids),'leftover_shm':nb.job_end_problems(before,nb.native_shm_snapshot())}
    (out/'failure-controls.json').write_text(json.dumps(doc,sort_keys=True))
    return {'status':'PASS','files':['failure-controls.json']}

CALLER_PATH=('CallerChild','Channel','ChildExited','failure_row','materialize_dataset','reference_path','WORK','_events')

def process_state(pid):
    """EX13-A09: the process table state letter of `pid` (/proc/<pid>/stat), or None when no such process exists."""
    try:text=Path(f'/proc/{pid}/stat').read_text()
    except OSError:return None
    return text[text.rfind(')')+2:].split(' ',1)[0] or None

def process_gone(pid):
    """EX13-A09: True when `pid` has left the process table (reaped); an exited but unreaped child is a zombie (Z)."""
    return process_state(pid) is None

def call_notes(events,channel,start,trial_id):
    """EX13-A09: the coordinator's note events of the trial since `start` (the coordinator builds an observation from a
    note); a crashed call has none."""
    return len(events(channel,start,trial_id,'note'))

def caller_crash(plan,g):
    """EX13-A04: a crash in a caller child of the framework caller path. The coordinator CallerChild starts a
    benchlab.trial child (SAFE_C_BENCH_ROLE=caller) of the framework case of the plan; after its handshake the child gets
    SIGSEGV (the simulated crash; core files off), and the call goes through the coordinator: CallerChild.call (or, when
    the send meets the closed socket, its own wait) raises ChildExited, and failure_row classifies it. No observation is
    made of the call, so nothing can count. Without the caller path (a unit test) the case is not run."""
    if any(k not in g for k in CALLER_PATH) or not plan.get('case_manifest'):return {'case':'caller-crash','not_run':True}
    import resource
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    cp={'job':'failure-controls','case_manifest':plan['case_manifest'],'dataset':plan['dataset'],'rows':plan['rows'],'sizes':plan['sizes'],
        'deadline_seconds':plan['deadline_seconds'],'run_id':plan.get('run_id','0'*32)}
    dataset=g['materialize_dataset'](cp);reference=g['reference_path'](dict(cp,job='reference'),dataset)
    channel=g['Channel'](g['WORK']/'bench/marker.sock');deadline=time.monotonic()+60.0;c=None;row=None;probes={'observations':None,'reaped':None}
    try:
        c=g['CallerChild'](channel,cp,dict(CRASH_TRIAL),dataset,reference,deadline,extra={'SAFE_C_BENCH_ROLE':'caller'})
        os.kill(c.proc.pid,signal.SIGSEGV)
        end=time.monotonic()+30.0       # wait until the child has exited, without reaping it: the coordinator must reap it
        while time.monotonic()<end and process_state(c.proc.pid) not in ('Z',None):time.sleep(0.01)
        try:c.call(dict(CRASH_TRIAL),cp['sizes'][CRASH_TRIAL['tier']],deadline);row={'status':'COMPLETED'}
        except g['ChildExited'] as exc:row=g['failure_row'](exc)
        except OSError:
            try:c._pump(lambda:False,deadline);row={'status':'COMPLETED'}
            except g['ChildExited'] as exc:row=g['failure_row'](exc)
        # EX13-A09: real probes, before any cleanup below: the coordinator's note events of the call and the process table
        probes={'observations':call_notes(g['_events'],channel,c.last_start,CRASH_TRIAL['trial_id']),'reaped':process_gone(c.proc.pid)}
    finally:
        if c is not None and c.proc.poll() is None:c.proc.kill();c.proc.wait()
        channel.close()
    return {'case':'caller-crash','framework_row':row,**probes,'fault':'SIGSEGV to the caller child after its handshake (simulated crash)'}

def register(job,g):
    _COORD.clear();_COORD.update({'g':g})
    @job('native-overlap')
    def job_native_overlap(plan,out):
        """EX-13 (B04): plan keys project_dir, native, trace, deadline_seconds."""
        return overlap(plan,out,g)
    @job('agreement-controls')
    def job_agreement_controls(plan,out):
        """EX-13 (B06): plan keys project_dir, case_manifest, native, variant, workers, route, rows, seed, mutations."""
        return agreement_controls(plan,out,g)
    @job('failure-controls')
    def job_failure_controls(plan,out):
        """EX-13 (B16): plan keys deadline_seconds; case_manifest, dataset, rows and sizes of a framework case (caller crash)."""
        return failure_controls(plan,out,g)
    return job_native_overlap,job_agreement_controls,job_failure_controls
