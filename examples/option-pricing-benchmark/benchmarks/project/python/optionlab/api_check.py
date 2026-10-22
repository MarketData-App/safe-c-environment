"""EX-11 (T20) container check `api-native`: the native API tests of Phase 2 Task 21 (test_native_api.py), adapted by ruling R49
(single-threaded backends only; ALO wired). The framework runs `python -m optionlab.api_check api-native OUT_DIR` in the bench
container with `bench check --native` (the unit suite has no --native). SAFE_C_BENCH_NATIVE holds the restored, digest-verified
pl-worker; without it the check FAILS (it never skips). Each item records its result and counts in the check file; an exception
in an item is that item's FAIL with the exception type only. REQUIRE-style named conditions, never an assert statement.

Items (256 synthetic rows of the case seed unless named; the model subsets are ('bsm',), ('baw',), ('alo',), ('bjs','crr') and
all five):
- subsets: for each subset, price_chain(backend='c-worker') equals price_chain(backend='python') in result_digest and equals
  the projection of the all-five (mask 31) c-worker result onto the subset; a c-worker call leaves no child process.
- limit: request_limit() + 1 tiled rows (mask 1) through c-worker equal the python result (two requests of one call).
- counters (G4.8): with SAFE_C_TEST_COUNTERS=1 the python backend counts zero evaluations of every unselected model and the
  py-reference engine_evals of every selected one; the c-worker backend (pl-worker --counters) reports calls 0 and evals 0 for
  every unselected model, calls n and the same engine_evals sum for every selected one, one request and exit 0.
- values (T20b-A01, A06): a side code outside {0, 1} (-1, 2, an int beyond binary64) and an int beyond binary64 in S, K, T, bid or ask
  give the INVALID_INPUT row for that row on c-worker, equal to python in result_digest.
- refusals: each refused argument of a list of 27 cases (the arguments, the malformed chains and the bad values) raises ValueError, calls
  no backend entry point (a recording spy with a positive control) and starts no process.
Before the items a positive control (scan_control) requires that the child scan sees a live child (T20-A03).

The checks act as a bench caller child (SAFE_C_BENCH_ROLE=caller, as optionlab.native_check)."""
import json, os, sys, tempfile, time
from pathlib import Path
from optionlab import native_check as nck
from optionlab.contract import MODELS5

SUBSETS=(('bsm',),('baw',),('alo',),('bjs','crr'),MODELS5)
FILES={'api-native':'api-native.json'}

def _children():
    """The pids of the live child processes of this process (every thread; /proc/<pid>/task/<tid>/children)."""
    out=[]
    for task in sorted(Path('/proc/self/task').iterdir()):
        try:out+=[int(x) for x in (task/'children').read_text().split()]
        except OSError:pass
    return sorted(out)

def scan_control():
    """Positive control of _children (T20-A03): a live child process of this process must be listed, and gone after it is
    reaped. On a kernel without /proc/<pid>/task/<tid>/children the scan sees nothing and the control raises."""
    import subprocess
    proc=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
    try:seen=proc.pid in _children()
    finally:proc.kill();proc.wait()
    nck.need(seen,'the child scan does not see a live child process (positive control)')
    nck.need(proc.pid not in _children(),'the child scan still lists a reaped child process')

def _project(result,models):
    return {'n':result['n'],'models':{m:result['models'][m] for m in models}}

def _call(chain,models,backend):
    """price_chain, requiring that no child process is left (the cold worker is reaped inside the call)."""
    from optionlab import api
    before=_children();out=api.price_chain(chain,models=models,backend=backend)
    nck.need(_children()==before,f'{backend} {",".join(models)}: a child process is left after the call')
    return out

def item_subsets(tmp,state):
    from optionlab.reference import result_digest
    chain=state['chain'];counts={'rows':chain['n']};full=_call(chain,MODELS5,'c-worker')
    nck.need(list(full['models'])==list(MODELS5),'the five-model result does not list the models in MODELS5 order')
    for models in SUBSETS:
        tag='+'.join(models);py=_call(chain,models,'python');c=_call(chain,models,'c-worker')
        nck.need(list(c['models'])==list(models) and list(py['models'])==list(models),f'{tag}: the result models differ from the selection')
        nck.need(result_digest(c)==result_digest(py),f'{tag}: c-worker differs from python')
        nck.need(result_digest(c)==result_digest(_project(full,models)),f'{tag}: c-worker differs from the projection of the mask-31 result')
        counts['subset_'+tag.replace('+','_')]=len(models)
    return counts

def item_limit(tmp,state):
    from optionlab.reference import result_digest
    from benchlab.native_worker import LAST_STATS
    from benchlab.workload import request_limit
    limit=request_limit();n=limit+1;chain=nck._tile(state['chain'],n)
    py=_call(chain,('bsm',),'python');c=_call(chain,('bsm',),'c-worker')
    nck.need(LAST_STATS.get('requests')==2,'the call was not split into two requests')
    nck.need(result_digest(c)==result_digest(py),f'{n} rows: c-worker differs from python')
    return {'rows':n,'requests':2}

def item_counters(tmp,state):
    from optionlab import api, backends, counters
    from optionlab.native_agreement import _pairs
    chain=state['chain'];n=chain['n'];counts={}
    if os.environ.get(counters.ENV)!='1':raise nck.NativeCheckError('SAFE_C_TEST_COUNTERS is not 1')
    for models in SUBSETS:
        tag='+'.join(models);counters.reset();py=api.price_chain(chain,models=models,backend='python');snap=counters.snapshot()
        want={m:sum(py['models'][m]['engine_evals']) for m in models}
        nck.need({m:snap.get(m,0) for m in MODELS5}=={m:want.get(m,0) for m in MODELS5},f'{tag}: python counters differ from engine_evals')
        nck.need(all(snap.get(m,0)==0 for m in MODELS5 if m not in models),f'{tag}: python evaluated an unselected model')
        seen=[]
        class Counted(backends.StdioBackend):
            def _argv(self,path):return super()._argv(path)+['--counters']
            def __init__(self,*a,**k):super().__init__(*a,**k);seen.append(self)
        original=backends.BACKENDS['stdio'];backends.BACKENDS['stdio']=Counted
        try:
            before=_children();api.price_chain(chain,models=models,backend='c-worker')
        finally:backends.BACKENDS['stdio']=original
        nck.need(len(seen)==1 and _children()==before,f'{tag}: c-worker backend count or a child process left')
        lines=[x for x in seen[0].worker.stderr_head.decode('ascii','replace').splitlines() if x.startswith('PLW1 ')]
        nck.need(bool(lines),f'{tag}: no PLW1 line');fields=dict(p.split('=',1) for p in lines[-1].split()[1:] if '=' in p)
        calls=_pairs(fields.get('calls',''));evals=_pairs(fields.get('evals',''))
        nck.need(set(calls)==set(MODELS5) and set(evals)==set(MODELS5),f'{tag}: the worker counters do not list the five models')
        for m in MODELS5:
            if m in models:nck.need(calls[m]==n and evals[m]==want[m],f'{tag}: {m} calls or evals differ (calls n, evals engine_evals)')
            else:nck.need(calls[m]==0 and evals[m]==0,f'{tag}: the unselected model {m} has a nonzero worker count')
        nck.need(fields.get('requests')=='1' and seen[0].exit_code==0,f'{tag}: requests or exit code')
        counts['counted_'+tag.replace('+','_')]=len(models)
    return counts

def item_values(tmp,state):
    from optionlab.reference import result_digest
    chain=state['chain'];big=10**400;counts={'cases':0};models=('bsm',)
    cases=[('side',-1),('side',2),('side',-big)]+[(key,sign*big) for key in ('S','K','T','bid','ask') for sign in (1,-1)]
    for key,value in cases:
        col=list(chain[key]);col[3]=value;bad={**chain,key:col};tag=f'{key} {"big" if abs(value)>9 else value}'
        py=_call(bad,models,'python');c=_call(bad,models,'c-worker')
        nck.need(py['models']['bsm']['status'][3]=='INVALID_INPUT' and c['models']['bsm']['status'][3]=='INVALID_INPUT',f'{tag}: row 3 is not INVALID_INPUT')
        nck.need(result_digest(c)==result_digest(py),f'{tag}: c-worker differs from python');counts['cases']+=1
    return counts

def item_refusals(tmp,state):
    from optionlab import api, backends
    chain=state['chain'];before=_children();counts={'refused':0};calls=[]
    def spy(name):
        def record(*a,**k):calls.append(name);raise RuntimeError(name)
        return record
    keep={k:getattr(backends,k) for k in ('cold_price','start_backend','prepare')};keep_stdio=backends.BACKENDS['stdio']
    backends.cold_price=spy('cold_price');backends.start_backend=spy('start_backend');backends.prepare=spy('prepare')
    backends.BACKENDS['stdio']=spy('stdio')
    def column(key,value):
        col=list(chain[key]);col[0]=value;return {**chain,key:col}
    without=lambda *gone:{k:v for k,v in chain.items() if k not in gone}
    cases=({'backend':'c-shm'},{'backend':'c-inproc'},{'backend':7},{'backend':'python-processes','workers':2},{'backend':'python-processes','workers':3},
           {'models':()},{'models':('heston',)},{'models':('bsm','bsm')},{'models':('bsm','bsm2')},{'models':'bsm'},{'models':None},
           {'backend':'c-worker','workers':2},{'backend':'c-worker','workers':8},{'backend':'c-worker','workers':1},{'backend':'python','workers':0},
           {'backend':'python','workers':True},{'backend':'c-worker','chain':without('q')},{'backend':'c-worker','chain':without('r')},
           {'backend':'c-worker','chain':without('r','q')},{'backend':'c-worker','chain':{**chain,'q':list(chain['q'][:2])}},
           {'backend':'c-worker','chain':{**chain,'n':-1}},{'backend':'c-worker','chain':column('side',True)},
           {'backend':'c-worker','chain':column('r',float('nan'))},{'backend':'c-worker','chain':column('q',10**400)},
           {'backend':'c-worker','chain':column('S',None)},{'backend':'python','chain':column('bid','x')},{'backend':'python','chain':None})
    try:
        try:api.price_chain(chain,backend='c-worker');control=False       # positive control: a valid call reaches the spy (not a ValueError)
        except RuntimeError:control=bool(calls)
        calls.clear()
        nck.need(control,'the backend spy did not see a valid c-worker call (positive control)')
        for kw in cases:
            kw=dict(kw);use=kw.pop('chain',chain)
            try:api.price_chain(use,**kw);refused=False
            except ValueError:refused=True
            nck.need(refused,f'{sorted(kw)}: not refused');counts['refused']+=1
    finally:
        for k,v in keep.items():setattr(backends,k,v)
        backends.BACKENDS['stdio']=keep_stdio
    nck.need(not calls,f'a refusal reached a backend entry point: {calls}')
    nck.need(_children()==before,'a refusal started a process')
    counts['backend_calls']=len(calls)
    return counts

ITEMS=(('subsets',item_subsets),('limit',item_limit),('counters',item_counters),('values',item_values),('refusals',item_refusals))

def api_native(out_dir,args):
    """api-native: see the module text."""
    if args:return {'status':'FAIL','reason':'api-native takes no arguments','files':[]}
    if nck._env_ready() is None:return {'status':'FAIL','reason':'api-native needs bench check --native','files':[]}
    try:scan_control()
    except nck.NativeCheckError as exc:return {'status':'FAIL','reason':nck.LABEL_BAD.sub(' ',str(exc))[:120],'files':[]}
    os.environ['SAFE_C_TEST_COUNTERS']='1'
    started=time.monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        a=nck._adapter();state={'chain':nck._chain(a,nck.ROWS,tmp)}
        results=nck._run_items(ITEMS,tmp,state)
    seconds=round(time.monotonic()-started,1);out=Path(out_dir);out.mkdir(parents=True,exist_ok=True)
    (out/FILES['api-native']).write_text(json.dumps({'items':results,'seconds':seconds},sort_keys=True,indent=1)+'\n')
    good=bool(results) and all(r['status']=='PASS' for r in results.values())
    counts={'items':len(results),'passed':sum(r['status']=='PASS' for r in results.values()),'seconds':int(seconds)}
    counts.update({'ok_'+k.replace('-','_'):int(r['status']=='PASS') for k,r in results.items()})
    failed=', '.join(f"{k}: {r.get('reason','')}" for k,r in results.items() if r['status']!='PASS')
    return {'status':'PASS' if good else 'FAIL','files':[FILES['api-native']],'counts':counts,
            'label':nck.LABEL_BAD.sub(' ',('failed ' if failed else 'all items passed')+failed)[:120]}

CHECKS={'api-native':api_native}

def main(argv):
    if len(argv)<3 or argv[1] not in CHECKS:print(json.dumps({'status':'FAIL','reason':'unknown check'}));return 2
    print(json.dumps(CHECKS[argv[1]](Path(argv[2]),argv[3:])));return 0

if __name__=='__main__':sys.exit(main(sys.argv))
