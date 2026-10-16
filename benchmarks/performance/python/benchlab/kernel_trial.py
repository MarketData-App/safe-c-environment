"""Kernel-scope trial under pyperf (spec 8.2): one pyperf worker process is one trial; values inside it are inner samples.
The time function brackets exactly its loops with coordinator handshakes; validation runs after the bracket.

Started isolated by the coordinator (python -I with an explicit path list). The pyperf worker is started with the same
interpreter arguments (sys.orig_argv), so it is isolated too and no startup hook from a project path runs in it."""
import gc, json, os, sys, time
import pyperf
from benchlab.markers import Marker
from benchlab.workload import load_case_adapter
from benchlab.trial import malformed_verdict, runtime_identity, verdict_fields
INHERIT='SAFE_C_BENCH_MARKER,SAFE_C_BENCH_SPEC,OPENBLAS_NUM_THREADS,OMP_NUM_THREADS,MKL_NUM_THREADS'
STATE={}

def load_spec():
    with open(os.environ['SAFE_C_BENCH_SPEC']) as f:return json.load(f)

def state():
    if STATE:return STATE
    spec=load_spec()
    with open(spec['case_manifest']) as f:case=json.load(f)
    adapter=load_case_adapter(case);data=adapter.slice(adapter.load({'path':spec['dataset'],'sha256':spec['sha256']}),spec['size'])
    workers=1 if spec['workers']=='direct' else int(spec['workers'])
    with open(spec['reference']) as f:ref=adapter.slice_result(json.load(f),spec['size'],data)
    m=Marker();m.hello(spec['trial_id']+':'+str(os.getpid()));m.note('identity:'+spec['trial_id'],**runtime_identity());m.begin('control-zero',spec['trial_id']);m.end('control-zero',spec['trial_id'])
    STATE.update(spec=spec,adapter=adapter,data=data,ref=ref,m=m,workers=workers,prepared=adapter.prepare(data,spec['variant'],workers));return STATE

def time_func(loops):
    st=state();spec=st['spec'];a=st['adapter'];m=st['m'];raw=None
    m.begin('work',spec['trial_id']);t0=time.perf_counter()
    for _ in range(loops):raw=a.run(st['prepared'],spec['variant'],st['workers'])
    dt=time.perf_counter()-t0
    m.end('work',spec['trial_id'],loops=loops,units=loops*spec['size'],gc_enabled=gc.isenabled())
    res=a.materialize(raw)
    try:v=verdict_fields(a.validate(res,st['ref'],st['data']))
    except ValueError as error:v=malformed_verdict(error)
    m.note(spec['trial_id'],work_units=a.work_units(res),result_sha256=a.digest(res),pyperf_seconds=dt,**v)
    return dt

def main():
    spec=load_spec()
    runner=pyperf.Runner(processes=1,values=spec['values'],warmups=spec['warmups'],loops=spec['loops'],program_args=tuple(sys.orig_argv[1:]))
    runner.parse_args(None if '--worker' in sys.argv else ['--inherit-environ',INHERIT,'--output',spec['output'],'--quiet'])
    runner.bench_time_func(spec['trial_id'],time_func)

if __name__=='__main__':main()
