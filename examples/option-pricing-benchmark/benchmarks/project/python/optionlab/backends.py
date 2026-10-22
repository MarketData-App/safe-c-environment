"""The C routes of the option example (task EX-10; Phase 2 Task 20 adapted by ruling R43): c-serial on stdio, shm and inproc.

Every backend runs the variant c-serial only (threads 0, workers direct; R43 item a; start_backend refuses any other row with
ValueError before a process or a library starts). Every backend takes the models mask and sends it with every request (the
SCPL header `selector_mask`, or the ABI 2 `models` argument); the framework client refuses a response whose mask differs
(FrameError SELECTOR_MISMATCH), and the codec checks the record count, the threads, the trailer and the reserved content of
every record (optionlab.native_codec.materialize). A chain above the request limit (benchlab.workload.request_limit(),
14,336 under the current policy; never a literal, R43 item e) is split into the requests r = 0, 1 of native_codec.requests,
each with native_worker.request_id(call sequence, r).

- StdioBackend: pl-worker (restored and verified: native_worker.restored) with no route flag; frames on its stdin and stdout.
- ShmBackend: two sealed memfd regions (benchlab.native_shm.Regions) sized for one full request: the input region holds the
  64-byte records (copied in by the caller), the output region the response payload WITH the trailer
  (n x 290 + 4 + 16 k, T16-A08); pl-worker gets --shm-in and --shm-out; the frames carry the control messages.
- InprocBackend: libpl_inproc.so through benchlab.native_inproc.load with the restored sha256 (no override); each request
  passes the eight caller columns in place; the output and scratch bytearrays are made per call; the argument echo (the
  eight addresses that the library received) must equal the caller's column addresses (no copy behind the call).

No backend falls back to another route: a refused start or a failed call raises and the row fails. A codec refusal of an
answer (trailer, written count) kills and reaps the worker before it propagates, as the framework client does.

Each price() resets and fills benchlab.native_worker.LAST_STATS: transport_ns, copied_bytes (stdio: the frame bytes both
ways; shm: the region bytes written and read plus the control frames; inproc: no input bytes, the output and scratch
bytes), the trailer keys, requests, and for inproc load_process, call_window (t0_ns, t1_ns of the foreign calls) and
argument_echo. transport_ns counts the codec's own transport work: the packing of the request records (measured in
prepare), the region writes and reads, the buffer checks and the result copies. NativeWorker.exchange writes the frame,
waits for the worker and reads the answer in one call, so the codec cannot separate the frame I/O time of stdio and shm
from the worker's work; that time stays in the work phase (a framework limit, ruling R46 decision 6; T7 backlog).

NativeRows is the mixin of the case adapters (optionlab.adapter, optionlab.echo_adapter): a warm row starts one backend in
native_start (outside every interval); a cold row starts its backend inside the timed call and keeps it until native_stop
(the trial's teardown phase), so the startup is inside the interval and the teardown outside, as for the Python pools. A
single-record (panel) trial has no teardown hook between its one-row calls (benchlab.trial run_panel; a framework limit,
T7 backlog): the adapter's take() stops the cold backend of the previous call before the next call starts, outside the
call wall and inside the caller interval, where benchlab.trial stops a cold Python pool."""
import ctypes, struct, time
from benchlab import native_inproc as ni, native_shm as ns, native_worker as nw
from optionlab import native_codec as nc

ROUTES=('stdio','shm','inproc')
VARIANTS=('c-serial',)
WORKER='pl-worker';LIBRARY='libpl_inproc.so'
EXCHANGE_SECONDS=1800.0         # the deadline of one frame exchange; the coordinator's call and job deadlines come first
ECHO_WORDS=8                    # libpl_inproc.so stores the eight column addresses in the last 64 bytes of scratch
INPROC_ARGTYPES=[ctypes.c_void_p]*8+[ctypes.c_size_t,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_size_t]
SHM_RESPONSE=struct.Struct('<Q')

def native_sha256(name):
    """The sha256 restored with the binaries (SAFE_C_BENCH_NATIVE/sha256.json); no environment override (M7)."""
    return nw.native_sha256(name)

def check_row(variant,workers,route):
    """ValueError unless the row is c-serial on direct workers (benchlab.trial passes 1 for direct) on one of ROUTES."""
    if variant not in VARIANTS:raise ValueError(f'C variant {variant!r} is not a row of this example (c-serial only)')
    if not (workers=='direct' or (type(workers) is int and workers==1)):raise ValueError('c-serial runs with workers direct')
    if route not in ROUTES:raise ValueError('a C row needs its route (stdio, shm or inproc)')

def scratch_length(n):
    """The inproc scratch length of n records (include/pl_inproc.h: 9 n + 64)."""
    return 9*n+64

def shm_region_sizes(limit):
    """(input, output) bytes of the shm regions for requests of at most `limit` records: limit x 64, and the response payload
    of `limit` records with the largest trailer of the worker (MAX_THREADS chunks; T16-A08: the capacity includes the trailer).
    At the policy limit 14,336: 917,504 and 4,157,508 bytes, the worker's region bounds (specs/project/serve.md)."""
    return limit*nc.RECORD_IN,nc.response_length(limit,nw.MAX_THREADS)

class Backend:
    """One route of one c-serial row (not started until start())."""
    route=None
    def __init__(self,variant,workers,*,models,echo):
        from benchlab.workload import request_limit
        self.variant=variant;self.threads=0;self.models=nc.check_mask(models);self.echo=bool(echo)
        self.limit=request_limit()
        if not 1<=self.limit<=nw.MAX_RECORDS:raise ValueError('the request limit is outside the worker record limit')
        self.sequence=0;self.started=False;self.closed=False
    def _next_sequence(self):
        if self.sequence>=2**32-1:raise ValueError('call sequence exhausted')
        self.sequence+=1;return self.sequence
    def price(self,prepared):
        """One call: the raw C result {'records', 'n', 'mask', 'echo'} of prepared['n'] rows; LAST_STATS filled."""
        if not self.started or self.closed:raise ValueError('the backend is not running')
        if prepared.get('route')!=self.route:raise ValueError('prepared input of another route')
        n=prepared['n'];seq=self._next_sequence()
        stats={'transport_ns':int(prepared.get('pack_ns') or 0),'copied_bytes':0,'requests':0}
        parts=[];sizes=[];walls=[];chunks=0;rule='direct'
        for r,(a,b) in enumerate(nc.requests(n,self.limit)):
            records,tr=self._request(prepared,seq,r,a,b,stats);parts.append(records);stats['requests']+=1
            rule=tr['chunk_rule'];chunks+=tr['chunks'];sizes+=tr['chunk_sizes'];walls+=tr['chunk_wall_ns']
        t=time.monotonic_ns();raw={'records':b''.join(parts),'n':n,'mask':self.models,'echo':self.echo};stats['transport_ns']+=time.monotonic_ns()-t
        nw.LAST_STATS.clear();nw.LAST_STATS.update(stats,chunk_rule=rule,chunks=chunks,chunk_sizes=sizes,chunk_wall_ns=walls,**self._extra_stats())
        return raw
    def _extra_stats(self):return {'load_process':None}
    def _expect(self,count,length):
        """The payload length rule of one answer for the framework client: the answer repeats the count and the threads."""
        def expect(head):
            if head['count']!=count or head['threads']!=self.threads:raise nw.FrameError('LENGTH_MISMATCH')
            return length
        return expect

class StdioBackend(Backend):
    route='stdio'
    def __init__(self,variant,workers,*,models,echo):
        super().__init__(variant,workers,models=models,echo=echo);self.worker=None;self.exit_code=None
    def _argv(self,path):return [str(path)]+(['--echo'] if self.echo else [])
    def start(self):
        """Starts the verified pl-worker (BinaryRefused for any other file); returns the spawn time in ns."""
        path,digest=nw.restored(WORKER)
        self.worker=nw.NativeWorker(self._argv(path),env={},deadline=EXCHANGE_SECONDS,sha256=digest)
        spawn=self.worker.start();self.started=True;return spawn
    def _request(self,prepared,seq,r,a,b,stats):
        m=b-a;payload=memoryview(prepared['wire'])[a*nc.RECORD_IN:b*nc.RECORD_IN];before=self.worker.copied_bytes
        _,resp=self.worker.exchange(nw.REQUEST,nw.request_id(seq,r),m,self.threads,self.models,payload,self._expect(m,nc.response_length(m,self.threads)))
        stats['copied_bytes']+=self.worker.copied_bytes-before
        t=time.monotonic_ns()
        try:tr=nc.trailer(resp,m,self.threads)
        except ValueError:
            self.worker.kill();raise
        records=resp[:m*nc.RECORD_OUT];stats['transport_ns']+=time.monotonic_ns()-t
        return records,tr
    def close(self):
        """SHUTDOWN, wait, reap (idempotent); the exit code (None when never started)."""
        if self.worker is not None and not self.closed:self.exit_code=self.worker.shutdown()
        self.closed=True;return self.exit_code

class ShmBackend(StdioBackend):
    route='shm'
    def __init__(self,variant,workers,*,models,echo):
        super().__init__(variant,workers,models=models,echo=echo);self.regions=None
    def start(self):
        """Makes the two sealed regions of one full request and starts the verified pl-worker on them."""
        path,digest=nw.restored(WORKER)
        self.regions=ns.Regions(*shm_region_sizes(self.limit));started=False
        try:
            argv=self._argv(path)+['--shm-in',str(self.regions.input_fd),'--shm-out',str(self.regions.output_fd)]
            self.worker=nw.NativeWorker(argv,env={},deadline=EXCHANGE_SECONDS,pass_fds=self.regions.pass_fds(),sha256=digest)
            spawn=self.worker.start();started=True
        finally:
            if not started:self.regions.close()      # a refused or failed start leaves no region
        self.started=True;return spawn
    def _request(self,prepared,seq,r,a,b,stats):
        m=b-a;length=m*nc.RECORD_IN;cap=nc.response_length(m,self.threads)
        ns.check_descriptor(self.regions,0,length,0,cap)
        t=time.monotonic_ns();self.regions.input[0:length]=memoryview(prepared['wire'])[a*nc.RECORD_IN:b*nc.RECORD_IN];stats['transport_ns']+=time.monotonic_ns()-t
        before=self.worker.copied_bytes
        _,resp=self.worker.exchange(nw.SHM_REQUEST,nw.request_id(seq,r),m,self.threads,self.models,ns.encode_descriptor(0,length,0,cap),self._expect(m,SHM_RESPONSE.size))
        frames=self.worker.copied_bytes-before
        t=time.monotonic_ns()
        try:
            if SHM_RESPONSE.unpack(resp)[0]!=cap:raise ValueError('LENGTH_MISMATCH')
            payload=bytes(self.regions.output[0:cap]);tr=nc.trailer(payload,m,self.threads)
        except ValueError:
            self.worker.kill();raise
        records=payload[:m*nc.RECORD_OUT]
        stats['transport_ns']+=time.monotonic_ns()-t;stats['copied_bytes']+=length+frames+cap
        return records,tr
    def close(self):
        code=super().close()
        if self.regions is not None:self.regions.close()
        return code

class InprocBackend(Backend):
    route='inproc'
    def __init__(self,variant,workers,*,models,echo):
        if echo:raise ValueError('libpl_inproc.so has no echo mode (the echo rows run on stdio and shm)')
        super().__init__(variant,workers,models=models,echo=False);self.entry=None;self.window=None;self.echo_addresses=None
    def start(self):
        """Loads the verified library (InprocRefused otherwise); returns the load time in ns."""
        path,digest=nw.restored(LIBRARY)
        t=time.monotonic_ns()
        lib=ni.load(str(path),digest,abi_symbol='pl_inproc_abi_version',entry='pl_inproc_price',argtypes=INPROC_ARGTYPES)
        self.entry=getattr(lib,'pl_inproc_price');self.started=True;return time.monotonic_ns()-t
    def price(self,prepared):
        self.window=None;self.echo_addresses=None
        return super().price(prepared)
    def _request(self,prepared,seq,r,a,b,stats):
        m=b-a;t=time.monotonic_ns()
        cols=[c[a:b] for c in prepared['columns']];addresses=[ni.check_column(c,m) for c in cols]
        out_len=nc.response_length(m,self.threads);scratch_len=scratch_length(m)
        out=bytearray(out_len);scratch=bytearray(scratch_len)
        args=addresses+[m,self.threads,r,self.models,ni.check_bytes(out,out_len),out_len,ni.check_bytes(scratch,scratch_len),scratch_len]
        stats['transport_ns']+=time.monotonic_ns()-t
        got=ni.call(self.entry,m,self.threads,self.models,args,keep=(cols,out),scratch=scratch,echo_words=ECHO_WORDS)
        t=time.monotonic_ns()
        if got['rc']!=0:raise RuntimeError(f"libpl_inproc.so returned {got['rc']}")
        if got['echo']!=addresses:raise RuntimeError('the argument echo differs from the caller columns')
        tr=nc.trailer(out,m,self.threads);records=bytes(memoryview(out)[:m*nc.RECORD_OUT])
        stats['transport_ns']+=time.monotonic_ns()-t;stats['copied_bytes']+=out_len+scratch_len
        self.window=(got['t0_ns'] if self.window is None else self.window[0],got['t1_ns'])
        if self.echo_addresses is None:self.echo_addresses=list(got['echo'])
        return records,tr
    def _extra_stats(self):
        return {'load_process':dict(ni.LOAD_PROCESS) or None,'call_window':list(self.window) if self.window else None,'argument_echo':self.echo_addresses}
    def close(self):
        """The library stays mapped in the process (it cannot be unloaded); the backend takes no further call."""
        self.closed=True;return None

BACKENDS={'stdio':StdioBackend,'shm':ShmBackend,'inproc':InprocBackend}

def start_backend(variant,workers,route,*,echo=False,models=7):
    """A backend of the row (not started): c-serial (threads 0) on `route` with the models mask; ValueError for any other
    variant, worker count, route, mask or an inproc echo."""
    check_row(variant,workers,route);nc.check_mask(models)
    return BACKENDS[route](variant,workers,models=models,echo=echo)

def cold_price(variant,workers,route,prepared,*,echo=False,models=7):
    """One cold call: start, price and close inside the call (tests and checks); inproc refuses cold (the library load is
    the startup phase; plan reason `inproc cold: not-applicable`)."""
    if route=='inproc':raise ValueError('inproc cold: not-applicable')
    b=start_backend(variant,workers,route,echo=echo,models=models)
    try:
        b.start();return b.price(prepared)
    finally:b.close()

def prepare(chain,route):
    """The prepared input of a C row: {'n', 'route', 'pack_ns', 'wire' (stdio, shm) or 'columns' (inproc)}."""
    if route not in ROUTES:raise ValueError('a C row needs its route (stdio, shm or inproc)')
    t=time.monotonic_ns();out={'n':chain['n'],'route':route}
    if route=='inproc':out['columns']=nc.columns(chain)
    else:out['wire']=nc.pack_requests(chain)
    out['pack_ns']=time.monotonic_ns()-t
    return out

class NativeRows:
    """The C rows of a case adapter. The adapter sets `models` (its selected model tuple); the trial sets `route`
    (benchlab.trial: None for a Python row) before any prepare. NATIVE_ECHO selects pl-worker --echo; ROUTES_ALLOWED narrows
    the routes (the echo case)."""
    NATIVE_ECHO=False;ROUTES_ALLOWED=ROUTES
    def _native_init(self):
        self.route=None;self._warm=None;self._cold=None
    def native_mask(self):return nc.mask_of(self.models)
    def _native_route(self):
        route=getattr(self,'route',None)
        if route not in self.ROUTES_ALLOWED:raise ValueError(f'a C row of this case needs one of the routes {", ".join(self.ROUTES_ALLOWED)}')
        return route
    def native_prepare(self,chain,variant,workers):
        """The prepared input of a C row on the adapter's route (ValueError without a declared route; no default route)."""
        route=self._native_route();check_row(variant,workers,route)
        return prepare(chain,route)
    def native_run(self,prepared,variant,workers):
        """The raw C result: the warm backend when native_start ran, else a cold backend started inside the call."""
        check_row(variant,workers,self._native_route())
        if self._warm is not None:return self._warm.price(prepared)
        self.native_retire_cold()            # a cold call never shares a worker with an earlier call
        b=self._new_backend(variant,workers);self._cold=b;b.start()
        return b.price(prepared)
    def pack_native(self,chain):
        """Kernel hook (container/bench_native_job.py): the 64-byte request records of the chain, the kernel input file."""
        return nc.pack_requests(chain)
    def native_materialize(self,raw):
        """The reference.run shape of a raw C result of this adapter (its mask and echo mode only)."""
        if raw.get('mask')!=self.native_mask() or raw.get('echo')!=self.NATIVE_ECHO:raise ValueError('a raw C result of another mask or echo mode')
        return nc.materialize(raw['records'],raw['n'],raw['mask'],echo=raw['echo'])
    def _new_backend(self,variant,workers):
        route=self._native_route();check_row(variant,workers,route)
        return start_backend(variant,workers,route,echo=self.NATIVE_ECHO,models=self.native_mask())
    def native_start(self,variant,workers):
        """benchlab.trial hook (warm C row): start the backend once, before the first interval."""
        if self._warm is None:
            b=self._new_backend(variant,workers);b.start();self._warm=b
    def native_stop(self,variant,workers):
        """benchlab.trial hook: after a cold call (teardown phase) and at shutdown; stops the cold and the warm backend."""
        self.native_retire_cold()
        if self._warm is not None:
            b,self._warm=self._warm,None;b.close()
    def native_retire_cold(self):
        """Stops the backend of the last cold call, if one is left."""
        if self._cold is not None:
            b,self._cold=self._cold,None;b.close()
