"""cProfile runs (spec 8.5): synthetic data only; a profiled run never enters a comparison. Workload-generic (Amendment A).

Scope rules (B13):
- A profile is diagnostic only. It is a separate run from every timing run and is never compared with an unprofiled run.
- Only the adapter's `run` (or, for py-processes, each worker's `run_chunk`) is inside the profile; load, synthesize and
  prepare are outside it.
- cProfile sees only the process that enables it. A direct variant reports one process; py-processes collects one
  profile per worker chunk (dispatched by ProcessPoolExecutor.map, not the timed run_pool path) and states that the
  parent is not profiled; py-threads counts how many worker-thread chunks the in-process profile actually saw.
- On Python 3.12+ cProfile runs on sys.monitoring, which delivers the events of every thread to one profiler with one
  call stack. Call counts stay exact; tottime and cumtime of code in concurrent threads are approximate. The py-threads
  row records the run wall time and the run_chunk cumtime so a reader can see the distortion.
- `top` reads pstats rows as pstats reports them. Cumulative times are inclusive per function and are never summed
  across rows (nested calls would be counted more than once). For py-processes, pstats merges the worker files: each
  row is that function's total over all worker files (CPU of concurrent workers, may exceed the wall time).
- Each record holds the input identity (dataset and case manifest digests, adapter reference) and the runtime identity."""
import cProfile, hashlib, io, json, multiprocessing, os, pstats, sys, time
from pathlib import Path
from benchlab.workload import load_case_adapter
from benchlab import pools

WORKERS=2
LABEL='profiled run; diagnostic only, never compared with unprofiled runs'
TIMES='cProfile seconds per function (tottime exclusive, cumtime inclusive as pstats reports it); rows are never summed'
THREAD_TIMES=TIMES+('; call counts are exact; tottime and cumtime of code in concurrent threads share one profiler stack '
                    '(sys.monitoring, Python 3.12+) and are approximate')
def _process_times(files):return TIMES+f'; per-function totals across {files} worker files (CPU of concurrent workers; may exceed the wall time)'

def _profiled_chunk(chunk,out_dir,seq):
    """One worker chunk under its own profile; the file names the worker pid and the chunk sequence number."""
    error=pools._WORKER.get('error')
    if error is not None:raise error
    prof=cProfile.Profile();prof.enable()
    try:res=pools._WORKER['adapter'].run_chunk(chunk)
    finally:prof.disable()
    prof.dump_stats(os.path.join(out_dir,f'py-processes-worker-{os.getpid()}-{seq:04d}.pstats'));return res

def _where(filename):
    """Source location as a module path: relative to the longest sys.path entry that holds the file, else the basename."""
    if filename=='~':return filename
    best=None
    for entry in sys.path:
        if not entry:continue
        base=os.path.abspath(entry).rstrip('/')+'/'
        if filename.startswith(base) and (best is None or len(base)>len(best)):best=base
    return filename[len(best):] if best else Path(filename).name

def top(paths,limit=20):
    st=pstats.Stats(*[str(p) for p in paths],stream=io.StringIO())
    rows=sorted(st.stats.items(),key=lambda kv:(-kv[1][3],str(kv[0])))[:limit]
    return [{'function':f'{_where(f)}:{line}({fn})','calls':nc,'tottime_s':round(tt,6),'cumtime_s':round(ct,6)} for (f,line,fn),(cc,nc,tt,ct,_) in rows]

def _stats_of(paths,name):
    """(calls, cumtime) of every Python function named `name` in the profile."""
    st=pstats.Stats(*[str(p) for p in paths],stream=io.StringIO());rows=[v for (f,line,fn),v in st.stats.items() if fn==name and f!='~']
    return sum(v[1] for v in rows),(round(sum(v[3] for v in rows),6) if rows else None)

def _python_variants(case):return {v['id'] for v in case['variants'] if v['language'] in ('python','python-library')}   # Task 9b: py-library

def runtime_identity():
    mechanism='sys.monitoring' if sys.version_info>=(3,12) else 'sys.setprofile'
    return {'version':sys.version,'implementation':sys.implementation.name,'profiler':f'cProfile (_lsprof) on {mechanism}'}

def profile(case_manifest,variant,n,seed,out_dir):
    manifest_bytes=Path(case_manifest).read_bytes();case=json.loads(manifest_bytes)
    if variant not in _python_variants(case):raise ValueError('not a Python variant of this case')
    if isinstance(n,bool) or not isinstance(n,int) or n<1:raise ValueError('n must be a positive integer')
    a=load_case_adapter(case);out=Path(out_dir);out.mkdir(parents=True,exist_ok=True)
    raw=a.synthesize(n,seed);tmp=out/'dataset';digest=hashlib.sha256(raw).hexdigest()
    try:
        tmp.write_bytes(raw);data=a.load({'path':str(tmp),'sha256':digest})
    finally:tmp.unlink(missing_ok=True)
    base={'variant':variant,'rows':n,'seed':seed,'label':LABEL,'dataset_sha256':digest,'case_manifest_sha256':hashlib.sha256(manifest_bytes).hexdigest(),
          'bench_ref':[a.bench_ref[0],a.bench_ref[1]],'runtime':runtime_identity()}
    if variant=='py-processes':
        from concurrent.futures import ProcessPoolExecutor
        from benchlab import profiling as this      # workers resolve the function by its module name, never by __main__
        chunks=a.chunks(a.prepare(data,variant,WORKERS),WORKERS);start=time.perf_counter()
        with ProcessPoolExecutor(max_workers=WORKERS,mp_context=multiprocessing.get_context('spawn'),initializer=pools._init_worker,initargs=(a.bench_ref,)) as ex:
            list(ex.map(this._profiled_chunk,chunks,[str(out)]*len(chunks),range(len(chunks))))
        wall=time.perf_counter()-start;files=sorted(out.glob('py-processes-worker-*.pstats'))
        return {**base,'workers':WORKERS,'wall_s':round(wall,6),
                'scope':f'run_chunk in each spawned worker; dispatched by ProcessPoolExecutor.map, not run_pool (no 2 x workers window; pool start and the parent not profiled; {WORKERS} workers)',
                'coverage':f'{len(files)} of {len(chunks)} worker chunks profiled; the parent process is not profiled','times':_process_times(len(files)),
                'top':top(files),'files':[f.name for f in files]}
    workers=WORKERS if variant in pools.POOLED else 1
    prepared=a.prepare(data,variant,workers);prof=cProfile.Profile();start=time.perf_counter();prof.enable()
    try:a.run(prepared,variant,workers)
    finally:prof.disable();wall=time.perf_counter()-start
    path=out/f'{variant}.pstats';prof.dump_stats(str(path));row={**base,'workers':workers,'wall_s':round(wall,6),'scope':'adapter run','times':TIMES}
    if variant=='py-threads':
        seen,cum=_stats_of([path],'run_chunk');total=len(a.chunks(prepared,workers))
        row.update(coverage=f'adapter run, one process; {seen} of {total} worker-thread chunks appear in the in-process profile (counted, not assumed)',
                   times=THREAD_TIMES,run_chunk_cumtime_s=cum)
    else:row['coverage']='adapter run, one process; child processes and native code are not profiled'
    return {**row,'top':top([path]),'files':[path.name]}

if __name__=='__main__':print(json.dumps(profile(sys.argv[1],sys.argv[2],int(sys.argv[3]),int(sys.argv[4]),sys.argv[5])))
