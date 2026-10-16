"""Workload-generic Python pools (spec 5, Amendment A). A pool runs workload chunks through the registered-workload
interface (chunks, run_chunk, combine); it never imports a project module by name.

The multiprocessing resource tracker is session infrastructure, not a pool cost: the spawn context's named semaphores
need it, and once started it lives as long as the caller. Start it with ensure_tracker() during session setup, before the
first measured interval; no trial starts or stops it. verify_session_end(), called after the last interval, checks that
no child other than the tracker remains."""
import functools, multiprocessing, os, threading, time
from multiprocessing import resource_tracker
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, wait, FIRST_COMPLETED
THREAD_ENV=('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS');POOLED=('py-threads','py-processes')
TRACKER_COMMAND='from multiprocessing.resource_tracker import main'
LAST_STATS={};_WORKER={};_SESSION={'tracker':False}

def _positive_int(value,what):
    if isinstance(value,bool) or not isinstance(value,int) or value<1:raise ValueError(f'{what} must be a positive integer')
    return value

# Amendment E: one chunk per worker per request over a fixed-seed permutation (SplitMix64 + Fisher-Yates, Durstenfeld
# order). The definition is exact so that every implementation (Python here, C in Phase 2) gives the same index sets.
CHUNK_RULE='one-per-worker';PARTITION='splitmix64-fisher-yates'
PARTITION_SEED=0x5AFEC0DE20261007;MASK=(1<<64)-1

class SplitMix64:
    """SplitMix64 on a 64-bit unsigned state; all arithmetic modulo 2**64."""
    def __init__(self,state):self.state=state&MASK
    def next(self):
        self.state=(self.state+0x9E3779B97F4A7C15)&MASK;z=self.state
        z=((z^(z>>30))*0xBF58476D1CE4E5B9)&MASK;z=((z^(z>>27))*0x94D049BB133111EB)&MASK
        return z^(z>>31)
    def bounded(self,t):
        """Unbiased draw in [0, t), Lemire's multiply-high with rejection (1 <= t <= 2**32)."""
        if isinstance(t,bool) or not isinstance(t,int) or not 1<=t<=1<<32:raise ValueError('bound outside [1, 2**32]')
        x=self.next();p=x*t;low=p&MASK
        if low<t:
            threshold=((1<<64)-t)%t
            while low<threshold:x=self.next();p=x*t;low=p&MASK
        return p>>64

def permutation(m,r):
    """Fisher-Yates (i from m - 1 down to 1, j = bounded(i + 1)) from state (PARTITION_SEED + r) mod 2**64."""
    g=SplitMix64(PARTITION_SEED+r);p=list(range(m))
    for i in range(m-1,0,-1):
        j=g.bounded(i+1);p[i],p[j]=p[j],p[i]
    return p

def chunk_bounds(m,workers,r=0):
    """Amendment E: w = min(workers, m) equal contiguous parts of the request's permutation; each part sorted ascending.
    Request-local indices; zero rows give no chunk."""
    _positive_int(workers,'workers')
    if m<=0:return []
    w=min(workers,m);p=permutation(m,r);return [sorted(p[k*m//w:(k+1)*m//w]) for k in range(w)]

def request_splits(n,limit):
    """L2: consecutive requests of at most `limit` records; responses keep the request order. G-ALO-CO (Amendment I item
    I13.1): `limit` is required (no default); adapters get it from benchlab.workload.construct_adapter."""
    _positive_int(limit,'limit')
    if n<0:raise ValueError('negative record count')
    return [(i,min(n,i+limit)) for i in range(0,n,limit)]

def request_chunks(n,workers,limit):
    """The L2 requests first, then one chunk per worker inside each request (request index r); absolute indices."""
    return [[[a+i for i in c] for c in chunk_bounds(b-a,workers,r)] for r,(a,b) in enumerate(request_splits(n,limit))]

def chunk_indices(n,workers,limit):
    """The chunks of request_chunks in submission order (request by request), as absolute index lists."""
    return [c for req in request_chunks(n,workers,limit) for c in req]

def chunk_sizes(n,workers,limit):return [len(c) for c in chunk_indices(n,workers,limit)]

def _chunk_size(chunk):
    """Rows of one chunk: a dict chunk must carry its gather index `index` (Amendment E, see benchlab.workload); any
    other chunk is a sequence of rows. Anything else is refused (ValueError)."""
    if isinstance(chunk,dict):
        if 'index' not in chunk:raise ValueError('a dict chunk must carry its gather index (key "index", ascending absolute positions)')
        return len(chunk['index'])
    try:return len(chunk)
    except TypeError:raise ValueError('a chunk must be a dict with "index" or a sequence of rows') from None

def verify_thread_environment():
    values={k:os.environ.get(k) for k in THREAD_ENV}
    if any(v!='1' for v in values.values()):raise RuntimeError('BLAS/OpenMP thread environment is not 1')
    return values

def is_tracker_cmdline(argv):
    """True for the command line of the multiprocessing resource tracker (its `-c` program starts with TRACKER_COMMAND)."""
    return any(isinstance(a,str) and a.startswith(TRACKER_COMMAND) for a in argv)

def _descendants():
    """(pid, argv) of every descendant of this process, read from /proc (Linux). Session setup and end only."""
    parent={};me=os.getpid()
    for entry in os.listdir('/proc'):
        if not entry.isdigit():continue
        try:
            with open(f'/proc/{entry}/stat','rb') as f:stat=f.read()
            parent[int(entry)]=int(stat[stat.rindex(b')')+2:].split()[1])
        except (OSError,ValueError,IndexError):continue
    found=[];frontier=[me]
    while frontier:
        pid=frontier.pop();kids=[c for c,p in parent.items() if p==pid];found+=kids;frontier+=kids
    rows=[]
    for pid in sorted(found):
        try:
            with open(f'/proc/{pid}/cmdline','rb') as f:argv=[a.decode('utf-8','replace') for a in f.read().split(b'\0') if a]
        except OSError:continue
        rows.append((pid,argv))
    return rows

def _tracker_pids():return [pid for pid,argv in _descendants() if is_tracker_cmdline(argv)]

TRACKER_SETTLE_SECONDS=5.0;TRACKER_POLL_SECONDS=0.01
_clock=time.monotonic;_sleep=time.sleep

def ensure_tracker():
    """Session setup (outside every measured interval): start the resource tracker once with the public API.
    ensure_running() returns after the fork, before the tracker child completes exec; until then /proc shows the parent's
    command line (PL-FLAKY-B13-01). While no tracker is visible, scan again every TRACKER_POLL_SECONDS, at most
    TRACKER_SETTLE_SECONDS; then exactly one tracker is required (two fail at once, none after the bound)."""
    resource_tracker.ensure_running();_SESSION['tracker']=True
    deadline=_clock()+TRACKER_SETTLE_SECONDS;pids=_tracker_pids()
    while not pids and _clock()<deadline:
        _sleep(TRACKER_POLL_SECONDS);pids=_tracker_pids()
    if len(pids)!=1:raise RuntimeError(f'expected one resource tracker child, found {len(pids)}')
    return {'label':'session-setup','pid':pids[0]}

def verify_session_end():
    """Session end (outside every measured interval): the tracker may remain; any other descendant is an error."""
    rows=_descendants();tracker=[p for p,a in rows if is_tracker_cmdline(a)];other=[p for p,a in rows if not is_tracker_cmdline(a)]
    if other:raise RuntimeError(f'{len(other)} child process(es) other than the resource tracker remain at session end')
    return {'tracker_pids':tracker,'other_pids':other}

def _resolve(ref):
    """The pool worker's adapter, built only by benchlab.workload.construct_adapter (G-ALO-CO, Amendment I item I13.1).
    bench_ref of a pooled adapter: (spec, params, selector, request_limit); the ref's limit must equal
    benchlab.workload.request_limit(). A workload that supplies its own chunks may pass (spec, params) or
    (spec, params, selector) (Amendment G4.2); it gets no limit keyword."""
    from benchlab import workload
    if len(ref) not in (2,3,4):raise ValueError('bench_ref holds 2, 3 or 4 items')
    selector=ref[2] if len(ref)>=3 else 'all'
    if len(ref)==4:
        limit=ref[3]
        if isinstance(limit,bool) or not isinstance(limit,int) or limit!=workload.request_limit():
            raise ValueError(f'request_limit: the bench_ref limit {limit!r} differs from this process; construct adapters through benchlab.workload.construct_adapter')
        return workload.construct_adapter(ref[0],ref[1],selector=selector,pooled=True,request_limit=limit)
    return workload.construct_adapter(ref[0],ref[1],selector=selector,pooled=False)

def _init_worker(ref):
    """spec 5: imports happen at pool start, inside the interval. A failure is kept and raised again by the first chunk,
    so the caller gets the original exception type and message and the worker prints no traceback."""
    try:verify_thread_environment();_WORKER['adapter']=_resolve(ref)
    except Exception as exc:_WORKER['error']=exc

def _timed(fn,chunk):
    """(pid, thread id, wall ns of fn(chunk) measured inside the worker, result)."""
    t0=time.perf_counter_ns();part=fn(chunk);return os.getpid(),threading.get_ident(),time.perf_counter_ns()-t0,part

def _worker_chunk(chunk):
    error=_WORKER.get('error')
    if error is not None:raise error
    return _timed(_WORKER['adapter'].run_chunk,chunk)

def start_pool(variant,workers,ref=None):
    if variant not in POOLED:raise ValueError('not a pool variant')
    _positive_int(workers,'workers')
    if variant=='py-threads':ex=ThreadPoolExecutor(max_workers=workers)
    else:
        if ref is None:raise ValueError('a process pool needs the workload reference (module:object, params)')
        ex=ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context('spawn'),initializer=_init_worker,initargs=(ref,))
    ex.bench_tracker_session_setup=_SESSION['tracker'] if variant=='py-processes' else None
    return ex

def run_pool(workload,prepared,workers,executor,stats=None,chunk_fn=None,timeout=None):
    """Rolling window of 2 x workers outstanding chunks (spec 5, B10). The first chunk error cancels the queue and
    propagates; no partial result. `chunk_fn` replaces run_chunk in thread pools only (tests). Amendment E: the workload's
    chunks follow request_chunks (one chunk per worker per request); each worker measures its own run_chunk wall time,
    recorded in chunk order as `chunk_wall_ns` with `chunk_rule` and `chunk_sizes`; the workload's combine scatters the
    parts back to their input positions.

    Cancel and timeout limits: Future.cancel() stops only chunks that have not started. A running chunk always runs to
    its end, and a process pool may already have moved up to max_workers + 1 further calls into its call queue; the
    executor's shutdown(wait=True) waits for all of them. `timeout` (seconds, whole run) raises TimeoutError and cancels
    the queued chunks; it does not interrupt a running or hung chunk, which only the launcher job deadline stops. Stats
    record outcome 'ok', 'error' (a chunk raised) or 'timeout' (the deadline passed), and the submitted and cancelled
    chunk counts."""
    verify_thread_environment()
    _positive_int(workers,'workers')
    size=getattr(executor,'_max_workers',None)
    if isinstance(size,bool) or not isinstance(size,int):raise ValueError('executor is not a pool from start_pool (no worker count)')
    if workers!=size:raise ValueError('workers differs from the pool worker count')
    if timeout is not None:
        if isinstance(timeout,bool) or not isinstance(timeout,(int,float)) or not timeout>0:raise ValueError('timeout must be a positive number of seconds')
        deadline=time.monotonic()+timeout
    processes=isinstance(executor,ProcessPoolExecutor)
    if processes:
        start_method=getattr(getattr(executor,'_mp_context',None),'get_start_method',None)
        if not callable(start_method):raise ValueError('process executor is not a pool from start_pool (no multiprocessing context)')
        start_method=start_method()
    else:start_method='thread'
    if processes and chunk_fn is not None:raise ValueError('chunk_fn applies to thread pools only')
    chunks=workload.chunks(prepared,workers)            # spec 5: pre-sliced in prepare, submitted as is
    sizes=[_chunk_size(c) for c in chunks]            # refused before any submission
    call=_worker_chunk if processes else functools.partial(_timed,chunk_fn or workload.run_chunk)
    pending={};results={};walls={};it=iter(enumerate(chunks));peak=0;pids=set();threads=set();count={'submitted':0,'cancelled':0};outcome='ok'
    def submit():
        nonlocal peak
        try:i,chunk=next(it)
        except StopIteration:return False
        pending[executor.submit(call,chunk)]=i;count['submitted']+=1;peak=max(peak,len(pending));return True
    try:
        for _ in range(2*workers):
            if not submit():break
        while pending:
            left=None if timeout is None else deadline-time.monotonic()
            if left is not None and left<=0:
                outcome='timeout';raise TimeoutError(f'pool deadline of {timeout} s passed with {len(pending)} chunks outstanding')
            done,_=wait(pending,timeout=left,return_when=FIRST_COMPLETED)
            for f in done:
                try:pid,tid,wall,part=f.result()
                except BaseException:
                    outcome='error';raise
                i=pending.pop(f);results[i]=part;walls[i]=wall;pids.add(pid);threads.add((pid,tid));submit()
    except BaseException:
        if outcome=='ok':outcome='error'
        count['cancelled']=sum(1 for f in pending if f.cancel())
        raise
    finally:
        s={'max_pending':peak,'chunks':len(chunks),'window':2*workers,'pids_distinct':len(pids),'caller_pid_included':os.getpid() in pids,
           'chunk_rule':CHUNK_RULE,'chunk_sizes':sizes,'chunk_wall_ns':[walls[i] for i in sorted(walls)],
           'threads':len(threads),'start_method':start_method,'outcome':outcome,
           'submitted':count['submitted'],'cancelled':count['cancelled'],'tracker_session_setup':getattr(executor,'bench_tracker_session_setup',None)}
        LAST_STATS.clear();LAST_STATS.update(s)
        if stats is not None:stats.update(s)
    return workload.combine([results[i] for i in range(len(chunks))])
