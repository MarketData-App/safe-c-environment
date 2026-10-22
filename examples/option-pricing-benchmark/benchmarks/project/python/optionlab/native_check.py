"""EX-10 container checks of the C routes (ruling R43 items b, c, d, h, i; R44 items 5, 6): `native-routes` (the real-worker
route tests of Phase 2 Task 20 test_native_routes.py, adapted to c-serial) and `c-call-deadline` (R43 item i part 2: the
coordinator's kill_group removes a C caller child and its pl-worker). EX-12 (R50 item c): this module also registers
`native-agreement` (optionlab.native_agreement), the native agreement check of bench.json `native`. EX-16 (R68): it also
registers `native-spread` (optionlab.native_spread), the section 3.7 spread of every variant (no gate, no tolerance change).

The framework runs `python -m optionlab.native_check <check> OUT_DIR` in the bench container with `bench check --native`,
and `bench run` runs native-agreement (the declared agreement check) with the restored binaries before any timing of a case
with a C row. SAFE_C_BENCH_NATIVE holds the restored, digest-verified pl-kernel, pl-worker and libpl_inproc.so; without it
each check FAILS (it never skips). The checks act as a bench caller child: they set SAFE_C_BENCH_ROLE=caller (the coordinator
sets it for its caller children; its check job does not), so benchlab.native_inproc loads the library. Each item records
its result and counts in the check file; an exception in an item is that item's FAIL with the exception type only (no
traceback, no row value). REQUIRE-style: named conditions, never an assert statement.

native-routes items (256 synthetic rows of the case seed unless named):
- routes: the c-serial result digest is the same on stdio (warm, cold), shm (warm, cold) and inproc (warm) for the mask 7
  and each one-model mask 1, 2, 4, 8, 16; an inproc cold call is refused (not-applicable).
- limits: at 14,336, 14,337, 16,384 and 20,000 rows (mask 1) each route gives the bytes of py-reference of the same rows: one
  request up to the request limit of benchlab.workload.request_limit(), then two. T19-A01: the rows are LIMIT_PERIOD (257)
  generated rows tiled, a period that does not divide the limit, so request 2 reads other rows than request 1 and a wrong
  offset of request 2 changes the result.
- reference: on every route the C result has the canonical bytes of py-reference (mask 7, 64 rows: bit for bit), and the
  adapter's agreement verdict is eligible.
- sides: a call row and a put row (side codes 0 and 1 of optionlab.contract; codec side values 0.0 and 1.0), each priced at
  sigma 0.3 by the BSM formula of its own side: on every route the C result equals py-reference bit for bit (three models),
  both BSM statuses are OK, and the BSM IV of each row is 0.3 (R44 item 6: the real side mapping end to end).
- kernel: pl-kernel with the bench.json native template (handshake, 64 rows): PLK1 digest= equals
  native_reference_digest(py-reference) and the canonical digest of unpack_native(output); the verdict is eligible.
- panel: the six panel rows of each model on every route have the stored statuses of option-chain-greeks.panel.json (the
  H21.7 pre-flight of the C row; optionlab.checks.preflight_variants lists the C row as native).
- zero-copy: inproc receives the caller's own column memory (argument echo) and copies only the output and scratch bytes.
- gil: a Python thread runs inside the window of the foreign call (ctypes releases the GIL).
- crash: an inproc call with invalid column addresses ends its own interpreter process (SIGSEGV); this process goes on.
- shm: 20 shm calls with a concurrent writer of the input region: the worker stays alive, every answer decodes, and no memfd
  or /dev/shm entry is left after the close.
- refusal: a restored directory with one changed byte in the library (or in pl-worker) refuses the start (InprocRefused,
  BinaryRefused); no process starts and no other route replaces it.
- echo: the echo-control rows on stdio and shm (warm, cold) are eligible echo results; the inproc echo row is refused.

R58 (T21-A01): native-routes stays declared as its own check, and it stays a per-run gate: the run gate native-agreement
runs the route-mechanics items MECHANICS (sides, kernel, panel, zero-copy, gil, crash, shm, refusal, echo) as its item
route_mechanics through route_mechanics(), with these item functions and the same input; its own items cover routes, limits
and reference.

c-call-deadline: for each route, a caller child (its own process group, as the coordinator starts every caller child) runs the
c-serial row of the covered selector baw in an endless loop of C calls; after TEST_FLOOR seconds the check calls the
coordinator's own kill_group (container/bench-coordinator.py, loaded read-only) and requires: no member of the group left, no
foreign orphan, the child killed by SIGKILL, its pl-worker gone, no memfd or /dev/shm entry left; and the coordinator's
deadline_reason of the call-deadline fields that the plan gives this C row (bench_deadline.deadline_fields) is the declared
reason baw-hang."""
import hashlib, importlib.util, json, os, re, select, shutil, signal, subprocess, sys, tempfile, threading, time
from pathlib import Path
from optionlab.models import RunDefect

PROJECT=Path(__file__).resolve().parents[2]            # <project dir>/benchmarks/project
CASE_FILE=PROJECT/'cases'/'option-chain-greeks.json';ECHO_FILE=PROJECT/'cases'/'echo-control.json';BENCH_FILE=PROJECT/'bench.json'
SRC=Path('/src');COORDINATOR=SRC/'container'/'bench-coordinator.py';TOOLS=SRC/'tools'
SEED=20261007;ROWS=256;AGREE_ROWS=64;LIMIT_SIZES=(14336,14337,16384,20000);MASKS={7:'all',1:'bsm',2:'bjs',4:'crr',8:'baw',16:'alo'}
DEADLINE=240.0;TEST_FLOOR=2.0;READY_SECONDS=180.0;SIGMA=0.3
FILES={'native-routes':'native-routes.json','c-call-deadline':'c-call-deadline.json'}

class NativeCheckError(Exception):
    """An expectation of a native check item that does not hold (a named exception; never a Python assert)."""

def need(condition,message):
    if not condition:raise NativeCheckError(message)

def _env_ready():
    native=os.environ.get('SAFE_C_BENCH_NATIVE')
    if not native:return None
    from benchlab import native_worker as nw
    nw.same_directory(native);os.environ['SAFE_C_BENCH_ROLE']='caller'
    return native

def _adapter(selector='all',case_file=CASE_FILE):
    from benchlab.workload import load_case_adapter
    return load_case_adapter(json.loads(case_file.read_text()),selector=selector)

def _chain(a,n,tmp):
    data=a.synthesize(n,SEED);p=Path(tmp)/f'chain-{n}.json';p.write_bytes(data)
    return a.load({'path':str(p),'sha256':hashlib.sha256(data).hexdigest()})

LIMIT_PERIOD=257          # T19-A01: the limit rows repeat with this period, which does not divide the request limit

def _tile(chain,n):
    """The eight request columns of chain repeated to n rows (route tests beyond the generated rows)."""
    reps=n//chain['n']+1
    return {'n':n,**{k:(chain[k]*reps)[:n] for k in ('side','S','K','T','bid','ask','r','q')}}

def _tile_result(result,n):
    """The result of _tile(chain, n) from the result of chain (py-reference evaluates every row alone)."""
    reps=n//result['n']+1
    return {'n':n,'models':{m:{k:(v*reps)[:n] for k,v in col.items()} for m,col in result['models'].items()}}

def _c_result(a,route,mode,chain):
    """One c-serial call through the adapter hooks (warm: native_start first; cold: a backend inside the call)."""
    a.route=route
    try:
        if mode=='warm':a.native_start('c-serial',1)
        return a.materialize(a.run(a.prepare(chain,'c-serial',1),'c-serial',1))
    finally:a.native_stop('c-serial',1)

def _cells():
    return [('stdio','warm'),('stdio','cold'),('shm','warm'),('shm','cold'),('inproc','warm')]

def item_routes(tmp,state):
    from optionlab.reference import result_digest
    from optionlab import backends
    counts={};chain=state['chain']
    for mask,selector in MASKS.items():
        a=_adapter(selector);ref=result_digest(_c_result(a,'stdio','warm',chain))
        for route,mode in _cells():need(result_digest(_c_result(a,route,mode,chain))==ref,f'mask {mask}: {route} {mode} digest differs')
        counts[f'mask_{mask}_cells']=len(_cells())
    try:backends.cold_price('c-serial','direct','inproc',{'n':0,'route':'inproc'},models=7);refused=False
    except ValueError:refused=True
    need(refused,'inproc cold was not refused');counts['inproc_cold_refused']=1
    return counts

def item_limits(tmp,state):
    from optionlab.reference import result_digest
    from optionlab import backends
    from benchlab import native_worker as nw
    from benchlab.workload import request_limit
    limit=request_limit();counts={'request_limit':limit,'period':LIMIT_PERIOD}
    need(limit%LIMIT_PERIOD!=0,'the limit row period divides the request limit')
    a=_adapter('bsm');base=state['limit_chain'];ref=a.reference(base)
    for n in LIMIT_SIZES:
        chain=_tile(base,n);want=result_digest(_tile_result(ref,n));reqs=[]
        for route in backends.ROUTES:
            got=result_digest(_c_result(a,route,'warm',chain));reqs.append(nw.LAST_STATS.get('requests'))
            need(got==want,f'{n} rows: {route} differs from py-reference of the same rows')
        need(reqs==[len(range(0,n,limit))]*3,f'{n} rows: request count')
        counts[f'requests_{n}']=reqs[0]
    return counts

def item_reference(tmp,state):
    from optionlab.reference import result_digest
    from optionlab import backends
    a=_adapter();chain=a.slice(state['chain'],AGREE_ROWS);ref=state['reference'];want=result_digest(ref);counts={'rows':AGREE_ROWS}
    for route in backends.ROUTES:
        got=_c_result(a,route,'warm',chain)
        need(result_digest(got)==want,f'{route}: C differs from py-reference')
        need(a.validate(got,ref,chain)['eligible'] is True,f'{route}: verdict not eligible')
        counts[f'{route}_bit_equal']=1
    return counts

def _side_chain(a):
    """A call row and a put row, each quoted at the BSM price of its own side at sigma SIGMA (spread 0.2 percent)."""
    from optionlab.reference import price_function
    S,K,T,r,q=600.0,600.0,0.25,a.params.rate,a.params.dividend_yield;price=price_function('bsm',a.params)
    cols={'side':[],'S':[],'K':[],'T':[],'bid':[],'ask':[],'r':[],'q':[]}
    for side in (0,1):
        p=price(side,S,K,T,r,q,SIGMA)
        for k,v in zip(('side','S','K','T','bid','ask','r','q'),(side,S,K,T,p*0.999,p*1.001,r,q)):cols[k].append(v)
    return {'n':2,**cols}

def item_sides(tmp,state):
    from optionlab.reference import result_digest
    from optionlab import backends
    a=_adapter();chain=_side_chain(a);ref=a.reference(chain);want=result_digest(ref);counts={}
    need(ref['models']['bsm']['status']==['OK','OK'],'py-reference: a BSM status is not OK')
    need(all(abs(v-SIGMA)<1e-6 for v in ref['models']['bsm']['iv']),'py-reference: the BSM IV of a side is not its own sigma')
    for route in backends.ROUTES:
        got=_c_result(a,route,'warm',chain)
        need(result_digest(got)==want,f'{route}: the call/put rows differ from py-reference')
        need(all(abs(v-SIGMA)<1e-6 for v in got['models']['bsm']['iv']),f'{route}: the BSM IV of a side is not its own sigma')
        counts[f'{route}_sides_equal']=1
    counts['call_put_price_ratio_x1000']=int(1000*ref['models']['bsm']['price'][0]/ref['models']['bsm']['price'][1])
    return counts

def item_kernel(tmp,state):
    from benchlab import native_kernel as nk, native_worker as nw
    from optionlab import native_codec as nc
    a=_adapter();chain=a.slice(state['chain'],AGREE_ROWS);ref=state['reference']
    src=Path(tmp)/'kernel.in';dst=Path(tmp)/'kernel.out';src.write_bytes(a.pack_native(chain))
    decl=json.loads(BENCH_FILE.read_text())['native']['kernel'];path,digest=nw.restored(decl['program'])
    values={'input':str(src),'records':str(AGREE_ROWS),'loops':'1','threads':'0','output':str(dst)}
    argv=[str(path)]+[values[x[1:-1]] if x.startswith('{') else x for x in decl['args']]
    got=nk.run_kernel(argv,env={},deadline=DEADLINE,on_begin=lambda:None,on_end=lambda:None,sha256=digest)
    summary=got['summary'] or {}
    need(got['exit']==0 and summary.get('status')=='OK' and summary.get('records')==AGREE_ROWS,'pl-kernel run')
    printed=(summary.get('extra') or {}).get('digest')
    res=a.unpack_native(dst.read_bytes())
    need(printed==a.native_reference_digest(ref),'PLK1 digest differs from native_reference_digest')
    need(printed==nc.canonical_digest(res),'PLK1 digest differs from the digest of the output records')
    need(a.validate(res,ref,chain)['eligible'] is True,'kernel verdict not eligible')
    return {'rows':AGREE_ROWS,'digest_equal':1}

def item_zero_copy(tmp,state):
    from optionlab import backends, native_codec as nc
    from benchlab import native_worker as nw
    chain=state['chain'];prepared=backends.prepare(chain,'inproc');b=backends.start_backend('c-serial','direct','inproc',models=7);b.start()
    try:b.price(prepared);echo=nw.LAST_STATS['argument_echo'];copied=nw.LAST_STATS['copied_bytes']
    finally:b.close()
    need(echo==[c.ctypes.data for c in prepared['columns']],'the library did not receive the caller columns')
    need(copied==nc.response_length(ROWS,0)+backends.scratch_length(ROWS),'copied bytes are not output plus scratch')
    return {'columns':8,'copied_bytes':copied}

def item_gil(tmp,state):
    from optionlab import backends
    from benchlab import native_worker as nw
    prepared=backends.prepare(state['chain'],'inproc');b=backends.start_backend('c-serial','direct','inproc',models=7);b.start()
    stamps=[];stop=threading.Event()
    def spin():
        while not stop.is_set():stamps.append(time.monotonic_ns())
    t=threading.Thread(target=spin);t.start()
    try:b.price(prepared);t0,t1=nw.LAST_STATS['call_window']
    finally:
        stop.set();t.join();b.close()
    inside=sum(1 for s in stamps if t0<s<t1)
    need(t1-t0>10_000_000,'the foreign call is too short to observe (10 ms)')
    need(inside>1000,'no Python thread ran inside the foreign call')
    return {'call_ms':(t1-t0)//1_000_000,'samples_inside':min(inside,10**9)}

def _python(code,*args):
    """argv of a child interpreter with this process's import path (isolated mode, no bytecode files)."""
    boot='import sys;sys.dont_write_bytecode=True;sys.path[0:0]='+repr([p for p in sys.path if p])+'\n'
    return [sys.executable,'-I','-c',boot+code,*[str(x) for x in args]]

CRASH_CODE=('import resource,sys\n'
            'resource.setrlimit(resource.RLIMIT_CORE,(0,0))\n'
            'from benchlab import native_inproc as ni\n'
            'from optionlab import backends\n'
            'lib=ni.load(sys.argv[1],sys.argv[2],abi_symbol="pl_inproc_abi_version",entry="pl_inproc_price",argtypes=backends.INPROC_ARGTYPES)\n'
            'out=bytearray(294);scratch=bytearray(73)\n'
            'lib.pl_inproc_price(*[8*(k+1) for k in range(8)],1,0,0,7,ni.check_bytes(out,294),294,ni.check_bytes(scratch,73),73)\n'
            'print("returned")\n')

def item_crash(tmp,state):
    from benchlab import native_worker as nw
    path,digest=nw.restored('libpl_inproc.so')
    r=subprocess.run(_python(CRASH_CODE,path,digest),env=dict(os.environ),stdin=subprocess.DEVNULL,capture_output=True,timeout=DEADLINE)
    need(r.returncode==-signal.SIGSEGV,'the invalid in-process call did not end its own process with SIGSEGV')
    return {'child_signal':signal.SIGSEGV.value}

def item_shm(tmp,state):
    from optionlab import backends, native_codec as nc
    from benchlab import native_shm as ns
    before=ns.snapshot();prepared=backends.prepare(state['chain'],'shm')
    b=backends.start_backend('c-serial','direct','shm',models=7);b.start();stop=threading.Event();calls=0
    def scribble():
        while not stop.is_set():b.regions.input[0:8]=bytes(8)       # a hostile writer of the input region during the calls
    t=threading.Thread(target=scribble);t.start()
    try:
        for _ in range(20):
            raw=b.price(prepared);nc.materialize(raw['records'],raw['n'],raw['mask']);calls+=1
        alive=b.worker.alive()
    finally:
        stop.set();t.join();b.close()
    need(alive,'the worker did not survive the concurrent writer')
    left=ns.leftover(before);need(left==[],'a memfd or /dev/shm entry is left')
    return {'calls':calls,'left':len(left)}

def _children():
    me=str(os.getpid());out=[]
    for d in os.listdir('/proc'):
        if not d.isdigit():continue
        try:fields=Path(f'/proc/{d}/stat').read_text().rsplit(')',1)[1].split()
        except (OSError,IndexError):continue
        if len(fields)>1 and fields[1]==me:out.append(int(d))
    return out

def item_refusal(tmp,state):
    from optionlab import backends
    from benchlab import native_inproc as ni, native_shm as ns, native_worker as nw
    real=os.environ['SAFE_C_BENCH_NATIVE'];before=ns.snapshot();counts={}
    for name,route,error in (('libpl_inproc.so','inproc',ni.InprocRefused),('pl-worker','stdio',nw.BinaryRefused),('pl-worker','shm',nw.BinaryRefused)):
        d=Path(tempfile.mkdtemp(dir=tmp))
        for f in os.listdir(real):shutil.copyfile(os.path.join(real,f),d/f)    # writable copies (the restored files are 0555); sha256.json keeps the real digests
        data=bytearray((d/name).read_bytes());data[64]^=1;(d/name).write_bytes(bytes(data))
        os.environ['SAFE_C_BENCH_NATIVE']=str(d);kids=set(_children())
        try:
            try:backends.start_backend('c-serial','direct',route,models=7).start();refused=False
            except error:refused=True
        finally:os.environ['SAFE_C_BENCH_NATIVE']=real
        need(refused,f'{route}: a changed {name} was not refused')
        need(set(_children())<=kids,f'{route}: a process started after the refusal')
        counts[f'{route}_refused']=1
    need(ns.leftover(before)==[],'a memfd or /dev/shm entry is left after the refusals')
    return counts

def item_echo(tmp,state):
    e=_adapter(case_file=ECHO_FILE);chain=e.slice(state['chain'],ROWS);ref=e.reference(chain);counts={}
    for route,mode in (('stdio','warm'),('stdio','cold'),('shm','warm'),('shm','cold')):
        got=_c_result(e,route,mode,chain)
        need(e.validate(got,ref,chain)['eligible'] is True and e.work_units(got)==ROWS,f'{route} {mode}: not an echo result')
        counts[f'{route}_{mode}']=1
    e.route='inproc'
    try:e.prepare(chain,'c-serial',1);refused=False
    except ValueError:refused=True
    need(refused,'the inproc echo row was not refused');counts['inproc_refused']=1
    return counts

def item_panel(tmp,state):
    """The H21.7 pre-flight of the C row (optionlab.checks.preflight_variants lists it as native): the six panel rows of each
    model (adapter.take: the generated rows of synthetic:large) on every route; each status equals the stored panel status."""
    from optionlab import backends
    from optionlab.contract import MODELS5
    doc=json.loads((PROJECT/'cases'/'option-chain-greeks.panel.json').read_text());idx=doc['indices'];counts={}
    for m in MODELS5:
        a=_adapter(m);one=[a.take(state['chain'],i) for i in idx]
        chain={'n':len(idx),**{k:[r[k][0] for r in one] for k in ('side','S','K','T','bid','ask','r','q')}}
        want=[doc['per_model'][m]['status'][i] for i in idx]
        for route in backends.ROUTES:
            need(_c_result(a,route,'warm',chain)['models'][m]['status']==want,f'{m} {route}: a panel status differs from the stored panel reference')
        counts[f'{m}_rows']=len(idx)
    return counts

ITEMS=(('routes',item_routes),('limits',item_limits),('reference',item_reference),('sides',item_sides),('kernel',item_kernel),('panel',item_panel),
       ('zero-copy',item_zero_copy),('gil',item_gil),('crash',item_crash),('shm',item_shm),('refusal',item_refusal),('echo',item_echo))
# R58 (T21-A01): the route-mechanics items of native-routes. The declared run gate native-agreement runs them as its item
# route_mechanics (optionlab.native_agreement); its items routes, limits and py_reference cover routes, limits and reference.
MECHANICS=('sides','kernel','panel','zero-copy','gil','crash','shm','refusal','echo')

def mechanics_items():
    """[(name, item function)] of the MECHANICS items: the functions of ITEMS themselves (no copy), in ITEMS order."""
    return [(n,f) for n,f in ITEMS if n in MECHANICS]

def _state(a,tmp):
    """The shared input of the native-routes items: the ROWS-row chain of the case seed, the py-reference result of its first
    AGREE_ROWS rows (mask 7) and the LIMIT_PERIOD-row chain."""
    chain=_chain(a,ROWS,tmp)
    return {'chain':chain,'reference':a.reference(a.slice(chain,AGREE_ROWS)),'limit_chain':_chain(a,LIMIT_PERIOD,tmp)}

def route_mechanics(tmp):
    """R58: the MECHANICS items as native-routes runs them (_run_items on the same input); {item: result}. The caller has the
    restored binaries ready (_env_ready: SAFE_C_BENCH_NATIVE and SAFE_C_BENCH_ROLE=caller)."""
    return _run_items(mechanics_items(),tmp,_state(_adapter(),tmp))

def _write(out_dir,name,doc):
    Path(out_dir).mkdir(parents=True,exist_ok=True);(Path(out_dir)/FILES[name]).write_text(json.dumps(doc,sort_keys=True,indent=1)+'\n')

LABEL_BAD=re.compile(r'[^A-Za-z0-9 ._:,()=+-]')

def _row(name,results,seconds):
    """The check row: the framework keeps only counts and a label (container/bench-coordinator.py check_result) and fetches
    the check file only on a pass, so the row names each item (ok_<item> 1 or 0) and the label names the failed items with
    their reasons (the label grammar of check_result; at most 120 characters)."""
    good=bool(results) and all(r['status']=='PASS' for r in results.values())
    counts={'items':len(results),'passed':sum(r['status']=='PASS' for r in results.values()),'seconds':int(seconds)}
    counts.update({'ok_'+k.replace('-','_'):int(r['status']=='PASS') for k,r in results.items()})
    failed=', '.join(f"{k}: {r.get('reason','')}" for k,r in results.items() if r['status']!='PASS')
    return {'status':'PASS' if good else 'FAIL','files':[FILES[name]],'counts':counts,
            'label':LABEL_BAD.sub(' ',('failed ' if failed else 'all items passed')+failed)[:120]}

def _run_items(items,tmp,state):
    results={}
    for name,fn in items:
        t=time.monotonic()
        try:results[name]={'status':'PASS','counts':fn(tmp,state)}
        except NativeCheckError as exc:results[name]={'status':'FAIL','reason':str(exc)[:200]}
        except RunDefect:raise                  # a run defect of a model is never an item result (it ends the check)
        except Exception as exc:results[name]={'status':'FAIL','reason':'exception '+type(exc).__name__}
        results[name]['seconds']=round(time.monotonic()-t,1)
    return results

def native_routes(out_dir,args):
    """native-routes: see the module text."""
    if args:return {'status':'FAIL','reason':'native-routes takes no arguments','files':[]}
    if _env_ready() is None:return {'status':'FAIL','reason':'native-routes needs bench check --native','files':[]}
    started=time.monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        results=_run_items(ITEMS,tmp,_state(_adapter(),tmp))
    seconds=round(time.monotonic()-started,1)
    _write(out_dir,'native-routes',{'items':results,'seconds':seconds})
    return _row('native-routes',results,seconds)

def _coordinator():
    """The coordinator module, loaded read-only from its file (as the framework test test_marked_run loads it)."""
    spec=importlib.util.spec_from_file_location('optionlab_native_check_coordinator',COORDINATOR)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod

CALLER_CODE=('import hashlib,json,os,sys\n'
             'from benchlab.workload import load_case_adapter\n'
             'a=load_case_adapter(json.load(open(sys.argv[1])),selector=sys.argv[2]);a.route=sys.argv[3]\n'
             'c=a.load({"path":sys.argv[4],"sha256":sys.argv[5]})\n'
             'a.native_start("c-serial",1);p=a.prepare(c,"c-serial",1);r=a.materialize(a.run(p,"c-serial",1))\n'
             'w=getattr(a._warm,"worker",None)\n'
             'print(json.dumps({"pid":os.getpid(),"worker":w.proc.pid if w is not None else None,"units":a.work_units(r)}),flush=True)\n'
             'while True:a.run(p,"c-serial",1)\n')

def _ready_line(proc,seconds):
    end=time.monotonic()+seconds;buf=b''
    while b'\n' not in buf:
        left=end-time.monotonic()
        if left<=0 or proc.poll() is not None:return None
        r,_,_=select.select([proc.stdout],[],[],left)
        if r:
            chunk=os.read(proc.stdout.fileno(),4096)
            if not chunk:return None
            buf+=chunk
    return buf.split(b'\n',1)[0]

def _deadline_fields(route):
    """The call-deadline fields that the plan gives the c-serial caller trial of unit-baw-full on `route`."""
    if str(TOOLS) not in sys.path:sys.path.insert(0,str(TOOLS))
    import bench_deadline
    import bench_model as bm
    project_dir=str(PROJECT.parents[1].relative_to(SRC))
    case=bm.load_case(SRC,'option-chain-greeks',project_dir);policy=bm.load_policy(SRC,project_dir)
    pt=next(p for p in case['points'] if p.get('unit')=='baw/full-dataset')
    plan={'sizes':policy['sizes'],'dataset':{'kind':'synthetic','rows':None}};cap=float(policy['budgets']['session_cap_seconds'])
    trial={'variant':'c-serial','workers':'direct','mode':'warm','tier':pt['size'],'loops':1,'selector':'baw','route':route,'scope':'caller'}
    return bench_deadline.deadline_fields(case,policy,'timing',plan,trial,None,cap)

def _deadline_route(coord,route,data,tmp):
    from benchlab import native_shm as ns
    before=ns.snapshot();counts={}
    proc=subprocess.Popen(_python(CALLER_CODE,CASE_FILE,'baw',route,data['path'],data['sha256']),env=dict(os.environ),
                          stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,start_new_session=True)
    try:
        line=_ready_line(proc,READY_SECONDS)
        need(line is not None,f'{route}: the caller child did not start its C row')
        info=json.loads(line);need(info['units']==data['rows'],f'{route}: the first C call was not complete')
        need(route=='inproc' or isinstance(info['worker'],int),f'{route}: no pl-worker pid')
        time.sleep(TEST_FLOOR)                       # the call loop runs past its (test) deadline
        need(proc.poll() is None,f'{route}: the caller child ended before the deadline')
        foreign=[];left=coord.kill_group(proc,foreign=foreign)
    finally:
        if proc.poll() is None:proc.kill();proc.wait()
        proc.stdout.close()
    need(left==0 and foreign==[],f'{route}: group members left after the kill')
    need(proc.returncode==-signal.SIGKILL,f'{route}: the caller child did not end by SIGKILL')
    need(info['worker'] is None or not Path(f"/proc/{info['worker']}").exists(),f'{route}: the pl-worker is still present')
    need(ns.leftover(before)==[],f'{route}: a memfd or /dev/shm entry is left')
    fields=_deadline_fields(route)
    need(fields.get('call_deadline_reason')=='baw-hang' and coord.deadline_reason(fields)=='baw-hang',f'{route}: the declared reason is not baw-hang')
    counts.update(left=left,foreign=len(foreign),worker=int(info['worker'] is not None),planned_deadline_s=int(fields['call_deadline_seconds']))
    return counts

def c_call_deadline(out_dir,args):
    """c-call-deadline: see the module text."""
    if args:return {'status':'FAIL','reason':'c-call-deadline takes no arguments','files':[]}
    if _env_ready() is None:return {'status':'FAIL','reason':'c-call-deadline needs bench check --native','files':[]}
    started=time.monotonic();results={}
    try:coord=_coordinator()
    except RunDefect:raise
    except Exception as exc:coord=None;results['coordinator']={'status':'FAIL','reason':'exception '+type(exc).__name__}
    if coord is not None:
        with tempfile.TemporaryDirectory() as tmp:
            a=_adapter('baw');raw=a.synthesize(AGREE_ROWS,SEED);p=Path(tmp)/'chain.json';p.write_bytes(raw)
            data={'path':str(p),'sha256':hashlib.sha256(raw).hexdigest(),'rows':AGREE_ROWS}
            results=_run_items([(route,lambda t,s,route=route:_deadline_route(coord,route,data,t)) for route in ('stdio','shm','inproc')],tmp,{})
    seconds=round(time.monotonic()-started,1)
    _write(out_dir,'c-call-deadline',{'items':results,'seconds':seconds,'test_floor_seconds':TEST_FLOOR})
    return _row('c-call-deadline',results,seconds)

def native_agreement(out_dir,args):
    """native-agreement (EX-12): the C agreement check of optionlab.native_agreement, the run gate of every bench run with C rows."""
    if args:return {'status':'FAIL','reason':'native-agreement takes no arguments','files':[]}
    native=_env_ready()
    if native is None:return {'status':'FAIL','reason':'native-agreement needs bench check --native','files':[]}
    from optionlab import native_agreement as na
    return na.check(out_dir,native)

def native_spread(out_dir,args):
    """native-spread (EX-16): the section 3.7 spread of every variant, C included (optionlab.native_spread); never a gate of a run
    (before_run false) and never a tolerance change."""
    if args:return {'status':'FAIL','reason':'native-spread takes no arguments','files':[]}
    native=_env_ready()
    if native is None:return {'status':'FAIL','reason':'native-spread needs bench check --native','files':[]}
    from optionlab import native_spread as ns
    return ns.check(out_dir,native)

CHECKS={'native-routes':native_routes,'c-call-deadline':c_call_deadline,'native-agreement':native_agreement,'native-spread':native_spread}

def main(argv):
    if len(argv)<3 or argv[1] not in CHECKS:print(json.dumps({'status':'FAIL','reason':'unknown check'}));return 2
    print(json.dumps(CHECKS[argv[1]](Path(argv[2]),argv[3:])));return 0

if __name__=='__main__':sys.exit(main(sys.argv))
