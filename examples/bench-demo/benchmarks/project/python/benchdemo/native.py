"""The bench-demo native codec (plan amendment FR6 N3): the Python side of the C peers bd-worker (routes stdio and shm),
libbd_inproc.so (route inproc) and bd-kernel (the kernel handshake). It uses the record-agnostic framework modules
benchlab.native_worker, native_shm, native_inproc and native_kernel and supplies the bench-demo values: request records of
12 bytes, response records of 16 bytes, the one selector value 1 (the digest), threads 0 (no pool), and the shm region
sizes 172,032 (input) and 229,376 (output) bytes (ruling FR6-R3 item 1).

The binaries come from SAFE_C_BENCH_NATIVE, which the coordinator sets only after it verified every restored binary
(container native_env); the path and the digest of each binary come from that one directory (benchlab.native_worker
.restored; a native_dir argument other than it is refused, N3b-A02), and every route starts or loads its binary from the
descriptor that it verified (N3-A01). The in-process route loads the library only in a caller child process (SAFE_C_BENCH_ROLE=caller), never
in the process that runs this module's check."""
import ctypes, json, os, struct, subprocess, sys, tempfile, time
from pathlib import Path
from benchlab import native_inproc as ni, native_kernel as nk, native_shm as ns, native_worker as nw
from benchdemo import reference as r

RECORD_IN=r.RECORD_IN;RECORD_OUT=r.RECORD_OUT;SELECTOR=1;THREADS=0
INPUT_REGION=r.RECORDS_MAX*RECORD_IN;OUTPUT_REGION=r.RECORDS_MAX*RECORD_OUT
WORKER='bd-worker';KERNEL='bd-kernel';LIBRARY='libbd_inproc.so'
ABI_SYMBOL='bd_inproc_abi_version';ENTRY='bd_inproc_digest'
ARGTYPES=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_size_t,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_uint32,
          ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_size_t]
ECHO_WORDS=6;SCRATCH=64;DEADLINE=120.0
ROUTES=('stdio','shm','inproc','kernel')

def records(request):
    """The record count of a request the C peers accept (1 to 14,336 whole records); ValueError otherwise."""
    if not isinstance(request,(bytes,bytearray)) or len(request)%RECORD_IN or not 1<=len(request)//RECORD_IN<=r.RECORDS_MAX:
        raise ValueError('request must hold 1 to 14,336 whole records')
    return len(request)//RECORD_IN

def response_length(n):
    """expect() of a RESPONSE: exactly 16 bytes per request record."""
    def expect(header):
        if header['count']!=n:return -1
        return n*RECORD_OUT
    return expect

def stdio_digest(native_dir,request,deadline=DEADLINE):
    """The output bytes of one REQUEST frame exchanged with bd-worker --stdio."""
    n=records(request);nw.same_directory(native_dir);path,digest=nw.restored(WORKER)      # N3b-A02: one directory
    with nw.NativeWorker([str(path),'--stdio'],env={},deadline=deadline,sha256=digest) as w:
        w.start()
        _,payload=w.exchange(nw.REQUEST,nw.request_id(1,0),n,THREADS,SELECTOR,bytes(request),response_length(n))
        if w.shutdown()!=0:raise nw.FrameError('WORKER_EXITED')
    return payload

def shm_digest(native_dir,request,deadline=DEADLINE):
    """The output bytes of one SHM_REQUEST with sealed memfd regions, exchanged with bd-worker --shm-in --shm-out."""
    n=records(request);nw.same_directory(native_dir);path,digest=nw.restored(WORKER)      # N3b-A02: one directory
    with ns.Regions(INPUT_REGION,OUTPUT_REGION) as regions:
        regions.input[:len(request)]=bytes(request)
        ns.check_descriptor(regions,0,len(request),0,n*RECORD_OUT)
        argv=[str(path),'--shm-in',str(regions.input_fd),'--shm-out',str(regions.output_fd)]
        with nw.NativeWorker(argv,env={},deadline=deadline,pass_fds=regions.pass_fds(),sha256=digest) as w:
            w.start()
            _,payload=w.exchange(nw.SHM_REQUEST,nw.request_id(1,0),n,THREADS,SELECTOR,
                                 ns.encode_descriptor(0,len(request),0,n*RECORD_OUT),lambda h:8)
            if struct.unpack('<Q',payload)[0]!=n*RECORD_OUT:raise nw.FrameError('LENGTH_MISMATCH')
            if w.shutdown()!=0:raise nw.FrameError('WORKER_EXITED')
        return bytes(regions.output[:n*RECORD_OUT])

def inproc_call(native_dir,request):
    """In a caller child: loads the verified library and calls the entry once; (rc, output bytes, echo)."""
    n=records(request)
    if os.environ.get('SAFE_C_BENCH_ROLE')!='caller':raise ni.InprocRefused('in-process load refused: process role is not caller')
    nw.same_directory(native_dir);path,digest=nw.restored(LIBRARY)      # N3b-A02: one directory
    lib=ni.load(str(path),digest,abi_symbol=ABI_SYMBOL,entry=ENTRY,argtypes=ARGTYPES)
    req=bytearray(request);out=bytearray(n*RECORD_OUT);scratch=bytearray(SCRATCH)
    args=(ni.check_bytes(req,len(req)),len(req),n,THREADS,1,SELECTOR,ni.check_bytes(out,len(out)),len(out),
          ni.check_bytes(scratch,SCRATCH),SCRATCH)
    got=ni.call(getattr(lib,ENTRY),n,THREADS,SELECTOR,args,keep=(req,out,scratch),scratch=scratch,echo_words=ECHO_WORDS)
    return got['rc'],bytes(out),got['echo']

def inproc_digest(native_dir,request,deadline=DEADLINE):
    """The output bytes of the in-process route, computed in a separate caller child process."""
    n=records(request)
    with tempfile.TemporaryDirectory() as t:
        src=Path(t)/'request.bin';dst=Path(t)/'output.bin';src.write_bytes(bytes(request))
        env=dict(os.environ,SAFE_C_BENCH_ROLE='caller')
        run=subprocess.run([sys.executable,'-m','benchdemo.native','inproc',str(native_dir),str(src),str(dst)],env=env,
                           stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=deadline)
        lines=run.stdout.strip().splitlines()
        row=json.loads(lines[-1]) if run.returncode==0 and lines else {}
        if row.get('rc')!=0 or row.get('echo')!=[n,len(request),THREADS,1,SELECTOR,n*RECORD_OUT]:
            raise RuntimeError('in-process call failed: '+str(row.get('rc',run.returncode))[:40])
        if row.get('load_process',{}).get('role')!='caller' or row['load_process'].get('pid')==os.getpid():
            raise RuntimeError('in-process load did not happen in a caller child')
        return dst.read_bytes()

def kernel_digest(native_dir,request,loops=1,deadline=DEADLINE):
    """The output bytes of bd-kernel through the kernel handshake, and its PLK1 summary."""
    n=records(request);marks=[];nw.same_directory(native_dir);path,digest=nw.restored(KERNEL)      # N3b-A02: one directory
    with tempfile.TemporaryDirectory() as t:
        src=Path(t)/'request.bin';dst=Path(t)/'output.bin';src.write_bytes(bytes(request))
        argv=[str(path),'--input',str(src),'--records',str(n),'--loops',str(loops),'--handshake','--output',str(dst)]
        got=nk.run_kernel(argv,env={},deadline=deadline,on_begin=lambda:marks.append('begin'),on_end=lambda:marks.append('end'),
                          sha256=digest)
        s=got['summary']
        if got['exit']!=0 or s is None or s['status']!='OK' or marks!=['begin','end']:raise RuntimeError('kernel run failed')
        if (s['records'],s['loops'],s['copied_bytes'])!=(n,loops,len(request)):raise RuntimeError('kernel summary differs')
        output=dst.read_bytes()
        if s['extra'].get('digest')!=format(r.fnv1a(output),'016x'):raise RuntimeError('kernel digest differs')
        return output

class Session:
    """FR6 N4: one route of the bench run caller child (SAFE_C_BENCH_ROLE=caller, SAFE_C_BENCH_NATIVE set): a bd-worker
    (stdio, or shm with two sealed memfd regions) or the verified libbd_inproc.so, started once by start() and kept until
    stop(). digest(request) gives the output bytes of one request and adds its evidence to `stats`: transport_ns (the
    wall of the frame exchange or of the foreign call), copied_bytes (frame bytes on the pipes; for shm also the region
    copy-in and copy-out; for inproc the copy into and out of the call buffers) and load_process (inproc only)."""
    def __init__(self,route,deadline=DEADLINE):
        if route not in ('stdio','shm','inproc'):raise ValueError('route must be stdio, shm or inproc')
        self.route=route;self.deadline=deadline;self.worker=None;self.regions=None;self.entry=None;self.calls=0
        self.stats={'transport_ns':0,'copied_bytes':0,'load_process':None}
    @property
    def started(self):return self.worker is not None or self.entry is not None
    def start(self):
        if self.started:return
        if self.route=='inproc':
            if os.environ.get('SAFE_C_BENCH_ROLE')!='caller':raise ni.InprocRefused('in-process load refused: process role is not caller')
            path,digest=nw.restored(LIBRARY)
            lib=ni.load(str(path),digest,abi_symbol=ABI_SYMBOL,entry=ENTRY,argtypes=ARGTYPES);self.entry=getattr(lib,ENTRY)
            self.stats['load_process']=dict(ni.LOAD_PROCESS);return
        path,digest=nw.restored(WORKER)
        if self.route=='stdio':argv=[str(path),'--stdio'];fds=()
        else:
            self.regions=ns.Regions(INPUT_REGION,OUTPUT_REGION)
            argv=[str(path),'--shm-in',str(self.regions.input_fd),'--shm-out',str(self.regions.output_fd)];fds=self.regions.pass_fds()
        self.worker=nw.NativeWorker(argv,env={},deadline=self.deadline,pass_fds=fds,sha256=digest)
        try:self.worker.start()
        except BaseException:
            self.stop();raise
    def digest(self,request):
        n=records(request);self.start();self.calls+=1;rid=nw.request_id(self.calls,0)
        if self.route=='inproc':
            req=bytearray(request);out=bytearray(n*RECORD_OUT);scratch=bytearray(SCRATCH)
            args=(ni.check_bytes(req,len(req)),len(req),n,THREADS,1,SELECTOR,ni.check_bytes(out,len(out)),len(out),ni.check_bytes(scratch,SCRATCH),SCRATCH)
            got=ni.call(self.entry,n,THREADS,SELECTOR,args,keep=(req,out,scratch),scratch=scratch,echo_words=ECHO_WORDS)
            if got['rc']!=0 or got['echo']!=[n,len(request),THREADS,1,SELECTOR,n*RECORD_OUT]:raise RuntimeError('in-process call failed')
            self.stats['transport_ns']+=got['t1_ns']-got['t0_ns'];self.stats['copied_bytes']+=2*len(request)+2*len(out)
            return bytes(out)
        before=self.worker.copied_bytes;t0=time.monotonic_ns()
        if self.route=='stdio':
            _,payload=self.worker.exchange(nw.REQUEST,rid,n,THREADS,SELECTOR,bytes(request),response_length(n))
            self.stats['transport_ns']+=time.monotonic_ns()-t0;self.stats['copied_bytes']+=self.worker.copied_bytes-before
            return payload
        self.regions.input[:len(request)]=bytes(request)
        ns.check_descriptor(self.regions,0,len(request),0,n*RECORD_OUT)
        _,payload=self.worker.exchange(nw.SHM_REQUEST,rid,n,THREADS,SELECTOR,ns.encode_descriptor(0,len(request),0,n*RECORD_OUT),lambda h:8)
        if struct.unpack('<Q',payload)[0]!=n*RECORD_OUT:raise nw.FrameError('LENGTH_MISMATCH')
        out=bytes(self.regions.output[:n*RECORD_OUT])
        self.stats['transport_ns']+=time.monotonic_ns()-t0;self.stats['copied_bytes']+=self.worker.copied_bytes-before+len(request)+len(out)
        return out
    def stop(self):
        """Shuts the worker down (killed and reaped after the wait) and releases the regions; idempotent. The in-process
        library stays mapped (a shared library is not unloaded) and only its entry is dropped."""
        if self.worker is not None:
            try:self.worker.shutdown()
            finally:self.worker=None
        if self.regions is not None:
            self.regions.close();self.regions=None
        self.entry=None

def route_digest(route,native_dir,request):
    return {'stdio':stdio_digest,'shm':shm_digest,'inproc':inproc_digest,'kernel':kernel_digest}[route](native_dir,request)

def main(argv):
    """The caller child of the in-process route: inproc NATIVE_DIR REQUEST OUTPUT; prints one JSON row."""
    if len(argv)!=5 or argv[1]!='inproc':print(json.dumps({'rc':None}));return 2
    rc,output,echo=inproc_call(argv[2],Path(argv[3]).read_bytes())
    Path(argv[4]).write_bytes(output)
    print(json.dumps({'rc':rc,'echo':echo,'load_process':dict(ni.LOAD_PROCESS)}));return 0

if __name__=='__main__':sys.exit(main(sys.argv))
