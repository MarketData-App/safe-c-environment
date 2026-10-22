"""A record-agnostic SCPL v2 peer for the framework transport tests (Phase 2 Task 18). It reads frames on stdin and
answers by its mode argument; the payload is opaque bytes. It imports nothing from benchlab, so the wire layout here is
an independent statement of the header `<4sHHQIHHI`.

Modes: echo (RESPONSE with the request payload and the request's selector mask, until SHUTDOWN or EOF), sleep (reads the
request, never answers), truncate (half a header, then exit), garbage (28 bytes that are no SCPL header), exit (exits
after the request header), error (ERROR code 9 with selector mask 0), error-unknown and error-zero (ERROR codes 99
and 0, outside 1-12), mask (RESPONSE whose selector mask differs). EX-13 (B16 failure controls): partial (a RESPONSE
header with the request's length, half of the payload, then exit) and segv (reads the request, then ends by SIGSEGV
with no core file)."""
import os, signal, struct, sys, time
HEADER=struct.Struct('<4sHHQIHHI');REQUEST,RESPONSE,ERROR,SHUTDOWN=1,2,3,4
ERROR_CODES={'error':9,'error-unknown':99,'error-zero':0}      # N3-A02: codes outside 1-12

def read_exact(fd,n):
    data=b''
    while len(data)<n:
        chunk=os.read(fd,n-len(data))
        if not chunk:return None
        data+=chunk
    return data

def write_all(fd,data):
    view=memoryview(data)
    while view:view=view[os.write(fd,view):]

def main(mode):
    while True:
        head=read_exact(0,HEADER.size)
        if head is None:return 0
        magic,version,kind,rid,count,threads,mask,length=HEADER.unpack(head)
        if kind==SHUTDOWN:return 0
        if mode=='exit':return 3
        payload=read_exact(0,length) if length else b''
        if payload is None:return 4
        if mode=='sleep':time.sleep(3600)
        elif mode=='truncate':write_all(1,head[:HEADER.size//2]);return 0
        elif mode=='garbage':write_all(1,b'XCPL'+bytes(range(24)));return 0
        elif mode in ERROR_CODES:write_all(1,HEADER.pack(b'SCPL',2,ERROR,rid,0,0,0,4)+struct.pack('<I',ERROR_CODES[mode]));return 1
        elif mode=='partial':write_all(1,HEADER.pack(b'SCPL',2,RESPONSE,rid,count,threads,mask,len(payload))+payload[:len(payload)//2]);return 0
        elif mode=='segv':
            import resource
            resource.setrlimit(resource.RLIMIT_CORE,(0,0));os.kill(os.getpid(),signal.SIGSEGV);time.sleep(60);return 5
        elif mode=='mask':write_all(1,HEADER.pack(b'SCPL',2,RESPONSE,rid,count,threads,mask%31+1,len(payload))+payload)
        else:write_all(1,HEADER.pack(b'SCPL',2,RESPONSE,rid,count,threads,mask,len(payload))+payload)

if __name__=='__main__':sys.exit(main(sys.argv[1]))
