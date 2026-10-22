"""Caller-scope trial child (spec 7, 8.3): the interval starts with the decoded dataset in memory and ends with Python
result objects; validation runs after the interval; a cold pool starts inside the interval and is torn down outside it.
Workload-generic: the case manifest names the adapter (benchlab.workload); this module never imports a case by name.

Session infrastructure stays outside every interval: the multiprocessing resource tracker starts once at session setup
(benchlab.pools.ensure_tracker) and the session end check (verify_session_end) runs after the last teardown."""
import argparse, gc, json, os, re, sys, sysconfig, time
from benchlab.markers import Marker
from benchlab.workload import load_case_adapter
from benchlab import pools, native_worker
POOLED=('py-threads','py-processes')
NATIVE_POOL_KEYS=('chunk_rule','chunks','chunk_sizes','chunk_wall_ns')
POOL_KEYS=('max_pending','chunks','window','pids_distinct','caller_pid_included','threads','start_method','tracker_session_setup','chunk_rule','chunk_sizes','chunk_wall_ns')

def _count(value,what):
    """A verdict count: a non-negative int, or the sum of a {name: int} or {model: {name: int}} mapping. Anything else is a
    malformed verdict (ValueError); the trial is then ineligible, never counted as 0."""
    if isinstance(value,dict):return sum(_count(v,what) for v in value.values())
    if type(value) is not int or value<0:raise ValueError(f'malformed verdict count: {what}')
    return value

VERDICT_COUNTS_MAX=16
COUNT_NAME=re.compile(r'[a-z][a-z0-9_]{0,31}')

def _counts(value):
    """FR5 (ruling FR5-R1 item 2): the project's own verdict counts, `counts` of the verdict ({name: count or mapping});
    each becomes one integer count. At most VERDICT_COUNTS_MAX names, each matching COUNT_NAME; the host refuses a name
    that the project protocol does not declare (`verdict_counts`). ValueError when malformed."""
    if not isinstance(value,dict) or len(value)>VERDICT_COUNTS_MAX or not all(isinstance(k,str) and COUNT_NAME.fullmatch(k) for k in value):
        raise ValueError('malformed verdict count: counts')
    return {k:_count(n,'counts') for k,n in sorted(value.items())}

def verdict_fields(v):
    """The note fields of one validation verdict. Explicit map (Task 10): `model_errors` ({model: {class name: count}})
    becomes one integer count; FR5 and FR5A-03: every other count is a project count, named in `counts` and reported as
    `verdict_counts` {name: int} (the protocol declares the names); every other verdict key is dropped. No row content
    leaves the child."""
    failures=v.get('failures') or {}
    if not isinstance(failures,dict):raise ValueError('malformed verdict count: failures')
    return {'eligible':bool(v.get('eligible')),'failures':{str(k):_count(n,'failures') for k,n in failures.items()},
            'reduction':v.get('reduction','NOT_RUN'),'model_errors':_count(v.get('model_errors',{}),'model_errors'),
            **({'verdict_counts':_counts(v['counts'])} if 'counts' in v else {})}

def malformed_verdict(error):
    return {'eligible':False,'failures':{'verdict':1},'reduction':'NOT_RUN','verdict_error':type(error).__name__}

def phase_split(t0,t1,t2,t3,t4,fresh):
    """Caller-interval split. A phase that did not run (an exception before its end) is None, never a negative span."""
    span=lambda a,b:b-a if a is not None and b is not None else None
    return {'prepare':span(t0,t1),'pool_start':span(t1,t2) if fresh else None,'work':span(t2,t3),'materialize':span(t3,t4)}

def pool_identity(variant):
    """B10: the benchlab.pools.LAST_STATS identity of the last pool run, or None for a direct variant."""
    if variant not in POOLED or not pools.LAST_STATS:return None
    return {k:pools.LAST_STATS.get(k) for k in POOL_KEYS}

def runtime_identity():
    """B10: process identity and GIL state after the adapter imports."""
    probe=getattr(sys,'_is_gil_enabled',None)
    return {'pid':os.getpid(),'free_threaded_build':bool(sysconfig.get_config_var('Py_GIL_DISABLED')),'gil_enabled':probe() if callable(probe) else None,
            'gil_label':'reported by sys._is_gil_enabled() after imports' if callable(probe) else 'not exposed by this runtime','isolated':bool(sys.flags.isolated)}

def native_fields(variant,route,route_label):
    """Task 18 hook: the note keys of a C variant from benchlab.native_worker.LAST_STATS (set by the workload codec during
    the timed call; reset before it), or {} for a Python variant. c-threads also reports its pool evidence."""
    if not variant.startswith('c-'):return {}
    s=native_worker.LAST_STATS
    out={'route':route,'route_label':route_label,'copied_bytes':s.get('copied_bytes'),'load_process':s.get('load_process')}
    if variant=='c-threads':out['pool']={k:s.get(k) for k in NATIVE_POOL_KEYS}
    return out

def native_call(adapter,name,variant,workers):
    """Task 19 hook: the codec's optional native_start(variant, workers) (a warm worker or library, before the first
    interval) or native_stop(variant, workers) (after a cold call, or at shutdown). An adapter without it is unchanged."""
    fn=getattr(adapter,name,None)
    if callable(fn):fn(variant,workers)

def warm_start(variant,workers,ref):
    """Start every worker of a warm pool before the first interval: `workers` back-to-back submissions make the executor
    create its full worker set (it creates workers on demand)."""
    pool=pools.start_pool(variant,workers,ref)
    for f in [pool.submit(os.getpid) for _ in range(workers)]:f.result()
    return pool

PANEL_MAX_CELLS=6;STATUS_MAX=32

def panel_command(cmd):
    """The `panel` object of a call command (base Task 18, G7.3): indices (the panel rows, cell order), passes L, cell labels
    and the panel reference status of each row. ValueError when it is malformed."""
    p=cmd.get('panel')
    if not isinstance(p,dict):raise ValueError('a panel call needs its panel object')
    idx,cells,ref,passes=p.get('indices'),p.get('cells'),p.get('reference_status'),p.get('passes')
    if not isinstance(idx,list) or not 1<=len(idx)<=PANEL_MAX_CELLS or not all(type(i) is int and i>=0 for i in idx):raise ValueError('panel indices rejected')
    if not isinstance(cells,list) or len(cells)!=len(idx) or not all(isinstance(c,str) and 0<len(c)<=STATUS_MAX for c in cells) or len(set(cells))!=len(cells):raise ValueError('panel cells rejected')
    if not isinstance(ref,list) or len(ref)!=len(idx) or not all(isinstance(s,str) and 0<len(s)<=STATUS_MAX for s in ref):raise ValueError('panel reference status rejected')
    if type(passes) is not int or not 1<=passes:raise ValueError('panel passes rejected')
    return idx,cells,ref,passes

def run_panel(adapter,data,variant,workers,pool,cold,idx,cells,ref,passes,model):
    """G7.3: L passes over the one-row panel requests in cell order, one call per request (a warm pool or worker is reused;
    a cold pool starts inside its call). Each call is timed (perf_counter_ns) inside the caller interval. H21.4: the status
    of each result must equal the panel reference status of its row; no band acceptance. Returns the note fields:
    panel_walls {cell: [L walls in ns]}, work_units, result_sha256, panel_status_diff (at most 6 items), detail, eligible,
    and `phases`, the caller phases of the trial's interval (FW-CASES-B08PROBE-01; B08, G7.1): prepare, work and materialize
    (pool_start of a cold pool) are the sums of phase_split over the timed calls; a C variant's transport is the sum of the
    codec's transport_ns of each call (native_worker.LAST_STATS, reset before each call, outside its wall), None when a
    call reports none. main() passes `phases` with the end of the interval and keeps it out of the note."""
    import hashlib
    walls={c:[] for c in cells};units=0;digests={};diff={}
    phases={'prepare':0,'pool_start':0 if cold else None,'work':0,'materialize':0,'transport':0 if variant.startswith('c-') else None}
    status=getattr(adapter,'row_status',None);band=getattr(adapter,'band_difference',None)
    for _ in range(passes):
        for i,cell in zip(idx,cells):
            sub=adapter.take(data,i);fresh=None;native_worker.LAST_STATS.clear()      # benchlab.native_worker: reset before every timed call
            t0=time.perf_counter_ns()
            prepared=adapter.prepare(sub,variant,workers);t1=time.perf_counter_ns()
            if cold:fresh=warm_start(variant,workers,adapter.bench_ref)
            t2=time.perf_counter_ns()
            try:raw=adapter.run(prepared,variant,workers,pool=pool or fresh);t3=time.perf_counter_ns();result=adapter.materialize(raw)
            finally:
                t4=time.perf_counter_ns()
                if fresh is not None:fresh.shutdown(wait=True)       # outside the call wall, inside the caller interval
            walls[cell].append(t4-t0);units+=adapter.work_units(result);digests[cell]=adapter.digest(result)
            for k,v in phase_split(t0,t1,t2,t3,t4,cold).items():
                if phases[k] is not None:phases[k]+=v
            if phases['transport'] is not None:
                got=native_worker.LAST_STATS.get('transport_ns')
                phases['transport']=phases['transport']+got if type(got) is int and got>=0 else None
            got=status(result) if callable(status) else None
            if got!=ref[cells.index(cell)] and cell not in diff:
                diff[cell]={'cell':cell,'model':model,'status':got if isinstance(got,str) else None,'reference_status':ref[cells.index(cell)],
                            'band_difference':bool(band(result)) if callable(band) else None}
    items=[diff[c] for c in cells if c in diff][:PANEL_MAX_CELLS]
    digest=hashlib.sha256(json.dumps([digests[c] for c in cells],separators=(',',':')).encode()).hexdigest()
    return {'panel_walls':walls,'work_units':units,'result_sha256':digest,'panel_status_diff':items,'detail':'panel-status' if items else None,
            'eligible':not items,'failures':{'panel-status':len(items)} if items else {},'reduction':'NOT_RUN','phases':phases}

def main(argv=None):
    p=argparse.ArgumentParser()
    for name in ('--client','--case-manifest','--variant','--mode','--dataset','--sha256','--reference'):p.add_argument(name,required=True)
    p.add_argument('--workers',default='direct');p.add_argument('--memory',action='store_true');p.add_argument('--selector',default='all')
    p.add_argument('--panel',action='store_true')
    p.add_argument('--route',default='none');p.add_argument('--route-label',default=None);a=p.parse_args(argv)     # Task 18 hook       # base Task 18 (G7.3): single-record L-pass panel trials
    with open(a.case_manifest) as f:case=json.load(f)
    adapter=load_case_adapter(case,selector=a.selector)
    adapter.route=None if a.route=='none' else a.route             # Task 18 hook: before any prepare
    workers=1 if a.workers=='direct' else int(a.workers);data=adapter.load({'path':a.dataset,'sha256':a.sha256})
    reference=None
    if a.reference!='none':
        with open(a.reference) as f:reference=json.load(f)
    if a.variant=='py-processes':pools.ensure_tracker()          # session setup, before any interval
    m=Marker();m.hello(a.client);m.note('identity:'+a.client,**runtime_identity());pool=None
    if a.variant in POOLED and a.mode=='warm':
        m.begin('pool_start','startup:'+a.client);pool=warm_start(a.variant,workers,adapter.bench_ref);m.end('pool_start','startup:'+a.client)
    if a.variant.startswith('c-') and a.mode=='warm':     # Task 19 hook: a warm C worker or library starts once, outside every interval
        m.begin('pool_start','startup:'+a.client);native_call(adapter,'native_start',a.variant,workers);m.end('pool_start','startup:'+a.client)
    if a.memory:m.begin('ready',a.client);m.end('ready',a.client)
    while True:
        cmd=m.command()
        if cmd['op']=='shutdown':
            m.begin('teardown','teardown:'+a.client)
            if pool is not None:pool.shutdown(wait=True)
            if a.variant.startswith('c-'):native_call(adapter,'native_stop',a.variant,workers)     # Task 19 hook
            try:pools.verify_session_end();error=None
            except RuntimeError as exc:error=type(exc).__name__
            if error:m.note('teardown:'+a.client,session_end_error=error)    # before the end: the coordinator stops reading at the end
            m.end('teardown','teardown:'+a.client);m.close();return 1 if error else 0
        trial=cmd['trial']
        if a.panel:      # G7.3: one caller interval per trial; inside it, L passes of one-row calls, each call timed
            pools.LAST_STATS.clear();native_worker.LAST_STATS.clear();note=None;failed=None
            try:
                idx,cells,ref,passes=panel_command(cmd);m.begin('caller',trial)
                try:note=run_panel(adapter,data,a.variant,workers,pool,a.variant in POOLED and pool is None,idx,cells,ref,passes,a.selector)
                except Exception as error:failed=type(error).__name__
                spans=note.pop('phases',None) if isinstance(note,dict) else None      # FW-CASES-B08PROBE-01: the phases of the interval
                m.end('caller',trial,phases=spans if isinstance(spans,dict) else phase_split(None,None,None,None,None,False))
            except ValueError as error:      # a malformed command: no interval was opened
                m.begin('caller',trial);m.end('caller',trial,phases=phase_split(None,None,None,None,None,False));failed=type(error).__name__
            native=native_fields(a.variant,adapter.route,a.route_label)      # N3-A03: the native keys, as in the non-panel path
            pool_info=native.pop('pool') if 'pool' in native else pool_identity(a.variant)
            if note is None:
                m.note(trial,eligible=False,failures={'exception':1},error_type=failed,work_units=0,result_sha256=None,reduction='NOT_RUN',pool=pool_info,**native)
            else:m.note(trial,pool=pool_info,**native,**note)
            continue
        sub=adapter.slice(data,cmd['size']);ref=adapter.slice_result(reference,cmd['size'],sub) if reference is not None else None
        fresh=None;result=None;failed=None;pools.LAST_STATS.clear();native_worker.LAST_STATS.clear()
        m.begin('caller',trial);t0=time.perf_counter_ns();t1=t2=t3=t4=None;cold=a.variant in POOLED and pool is None
        try:
            prepared=adapter.prepare(sub,a.variant,workers);t1=time.perf_counter_ns()
            if cold:fresh=warm_start(a.variant,workers,adapter.bench_ref)    # a cold pool starts its full worker set inside the interval
            t2=time.perf_counter_ns();raw=adapter.run(prepared,a.variant,workers,pool=pool or fresh);t3=time.perf_counter_ns()
            result=adapter.materialize(raw);t4=time.perf_counter_ns()
        except Exception as error:failed=type(error).__name__
        phases=phase_split(t0,t1,t2,t3,t4,cold)
        phases['transport']=native_worker.LAST_STATS.get('transport_ns') if a.variant.startswith('c-') else None   # Task 18 hook
        m.end('caller',trial,phases=phases)
        pool_info=pool_identity(a.variant);native=native_fields(a.variant,adapter.route,a.route_label)
        if 'pool' in native:pool_info=native.pop('pool')
        if fresh is not None:
            m.begin('teardown',trial+':teardown');fresh.shutdown(wait=True);m.end('teardown',trial+':teardown')
        if a.variant.startswith('c-') and a.mode=='cold':   # Task 19 hook: a cold C worker started inside the interval stops outside it
            m.begin('teardown',trial+':teardown');native_call(adapter,'native_stop',a.variant,workers);m.end('teardown',trial+':teardown')
        if result is None:
            m.note(trial,eligible=False,failures={'exception':1},error_type=failed,work_units=0,result_sha256=None,reduction='NOT_RUN',pool=pool_info,**native);continue
        if a.memory:   # memory trial: digest only; the host takes eligibility from the timing session
            m.note(trial,eligible=None,failures={},work_units=adapter.work_units(result),result_sha256=adapter.digest(result),reduction='NOT_RUN',pool=pool_info,**native)
            del result;gc.collect();m.begin('post-work',a.client);m.end('post-work',a.client);continue
        try:v=verdict_fields(adapter.validate(result,ref,sub))
        except ValueError as error:v=malformed_verdict(error)
        m.note(trial,work_units=adapter.work_units(result),result_sha256=adapter.digest(result),pool=pool_info,**native,**v)

if __name__=='__main__':sys.exit(main())
