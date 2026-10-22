"""EX-8 container check `worker-routes`: the framework NativeWorker drives the real pl-worker (no stub) over both routes.

The framework runs `python -m optionlab.worker_check worker-routes OUT_DIR` in the bench container with `bench check
--native`, so that SAFE_C_BENCH_NATIVE holds the restored, digest-verified pl-worker. The request records are plain
64-byte rows (eight little-endian binary64 values) and the response is read as raw 290-byte records: the check needs no
option codec. It sends a ping, then eight rows with threads 0, 1, 2 and 4 on one persistent worker for each route
(stdio frames; shm through the framework's sealed memfd regions), and requires: the response header repeats the request
ID and mask (the framework client raises otherwise), the record bytes are identical across threads and across the two
routes, the trailer holds k = min(threads, n) entries whose sizes sum to n, and SHUTDOWN ends the worker with exit 0.
A last shm session sends a descriptor that disagrees with the request and requires the framework to raise
FrameError('LENGTH_MISMATCH') from the worker's ERROR frame."""
import json, struct, sys
from pathlib import Path
from benchlab import native_shm as ns, native_worker as nw

WORKER='pl-worker';RECORD_IN=64;RECORD_OUT=290;MASK=7;DEADLINE=120.0;ROWS=8;THREADS=(0,1,2,4)
INPUT_REGION=917504;OUTPUT_REGION=4157508;FILE='worker-routes.json'

class WorkerCheckError(Exception):
    """A worker-routes expectation that does not hold (a named exception; never a Python assert)."""

def need(condition,message):
    if not condition:raise WorkerCheckError(message)

def rows(n):
    """n valid option rows as request records."""
    out=bytearray()
    for i in range(n):
        k=80.0+5.0*i;mid=100.0-k+4.0 if 100.0-k>0.0 else 4.0
        out+=struct.pack('<8d',float(i&1),100.0,k,0.5,mid-0.1,mid+0.1,0.04,0.012)
    return bytes(out)

def trailer_length(n,threads):
    return 4+16*(min(threads,n) if threads else 0)

def split(payload,n,threads):
    """(records, chunk sizes) of a response payload; WorkerCheckError when the trailer disagrees with the request."""
    records=payload[:n*RECORD_OUT];tail=payload[n*RECORD_OUT:];k=struct.unpack_from('<I',tail)[0]
    need(k==(min(threads,n) if threads else 0),'trailer count')
    need(len(tail)==4+16*k,'trailer length')
    sizes=[struct.unpack_from('<I',tail,4+16*i)[0] for i in range(k)]
    need(k==0 or sum(sizes)==n,'chunk sizes')
    return records,sizes

def stdio_session(path,digest):
    """One persistent worker on stdio: a ping, then the rows at every thread count; the records of each, the exit code."""
    request=rows(ROWS);got=[]
    with nw.NativeWorker([str(path)],env={},deadline=DEADLINE,sha256=digest) as w:
        w.start()
        _,payload=w.exchange(nw.REQUEST,nw.request_id(1,0),0,0,MASK,b'',lambda h:4)
        need(struct.unpack('<I',payload)[0]==0,'ping trailer')
        for call,threads in enumerate(THREADS,start=2):
            n=ROWS;_,payload=w.exchange(nw.REQUEST,nw.request_id(call,0),n,threads,MASK,request,lambda h:n*RECORD_OUT+trailer_length(n,threads))
            got.append(split(payload,n,threads))
        return got,w.shutdown()

def shm_session(path,digest):
    """The same on shm through sealed memfd regions."""
    request=rows(ROWS);got=[]
    with ns.Regions(INPUT_REGION,OUTPUT_REGION) as regions:
        argv=[str(path),'--shm-in',str(regions.input_fd),'--shm-out',str(regions.output_fd)]
        with nw.NativeWorker(argv,env={},deadline=DEADLINE,pass_fds=regions.pass_fds(),sha256=digest) as w:
            w.start()
            _,payload=w.exchange(nw.SHM_REQUEST,nw.request_id(1,0),0,0,MASK,ns.encode_descriptor(0,0,0,4),lambda h:8)
            need(struct.unpack('<Q',payload)[0]==4,'ping written')
            for call,threads in enumerate(THREADS,start=2):
                n=ROWS;capacity=n*RECORD_OUT+trailer_length(n,threads);regions.input[:len(request)]=request
                _,payload=w.exchange(nw.SHM_REQUEST,nw.request_id(call,0),n,threads,MASK,
                                     ns.encode_descriptor(0,len(request),0,capacity),lambda h:8)
                need(struct.unpack('<Q',payload)[0]==capacity,'written count')
                got.append(split(bytes(regions.output[:capacity]),n,threads))
            return got,w.shutdown()

def hostile_session(path,digest):
    """A descriptor whose input length is not count * 64: the worker answers ERROR LENGTH_MISMATCH before any region read."""
    with ns.Regions(INPUT_REGION,OUTPUT_REGION) as regions:
        argv=[str(path),'--shm-in',str(regions.input_fd),'--shm-out',str(regions.output_fd)]
        with nw.NativeWorker(argv,env={},deadline=DEADLINE,pass_fds=regions.pass_fds(),sha256=digest) as w:
            w.start()
            try:w.exchange(nw.SHM_REQUEST,nw.request_id(1,0),ROWS,2,MASK,ns.encode_descriptor(0,ROWS*RECORD_IN-1,0,4096),lambda h:8)
            except nw.FrameError as exc:return exc.name
            return None

def worker_routes(out_dir,args):
    """worker-routes: see the module text."""
    if args:return {'status':'FAIL','reason':'worker-routes takes no arguments'}
    import os
    native_dir=os.environ.get('SAFE_C_BENCH_NATIVE')
    if not native_dir:return {'status':'FAIL','reason':'worker-routes needs bench check --native'}
    nw.same_directory(native_dir);path,digest=nw.restored(WORKER)
    stdio,stdio_exit=stdio_session(path,digest);shm,shm_exit=shm_session(path,digest);hostile=hostile_session(path,digest)
    first=stdio[0][0]
    same_threads=all(r==first for session in (stdio,shm) for r,_ in session)
    same_routes=[r for r,_ in stdio]==[r for r,_ in shm]
    chunks={'stdio':[s for _,s in stdio],'shm':[s for _,s in shm]}
    good=same_threads and same_routes and stdio_exit==0 and shm_exit==0 and hostile=='LENGTH_MISMATCH'
    counts={'requests_per_route':1+len(THREADS),'records_per_request':ROWS,'same_across_threads':int(same_threads),'same_across_routes':int(same_routes),
            'stdio_exit':stdio_exit,'shm_exit':shm_exit,'hostile_error':hostile}
    Path(out_dir).mkdir(parents=True,exist_ok=True)
    (Path(out_dir)/FILE).write_text(json.dumps({'counts':counts,'chunks':chunks},sort_keys=True,indent=1)+'\n')
    return {'status':'PASS' if good else 'FAIL','counts':{k:v for k,v in counts.items() if isinstance(v,int)},'files':[FILE],'hostile_error':hostile}

CHECKS={'worker-routes':worker_routes}

def main(argv):
    if len(argv)<3 or argv[1] not in CHECKS:print(json.dumps({'status':'FAIL','reason':'unknown check'}));return 2
    print(json.dumps(CHECKS[argv[1]](Path(argv[2]),argv[3:])));return 0

if __name__=='__main__':sys.exit(main(sys.argv))
