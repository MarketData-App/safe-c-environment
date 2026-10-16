"""Kernel handshake for pure native timing (Phase 2 Task 18; plan amendment FR6 N3). Record-agnostic.

The kernel program writes `B` on stdout before its loops and waits for `G` on stdin; after the loops it writes `E` and
waits for `F`. run_kernel calls on_begin() between B and G and on_end() between E and F, so the caller takes its counters
outside any Python work inside the kernel's timed loops. After the handshake it reads the rest of stdout (at most 64 KiB)
and waits for the exit. The last stdout line `PLK1 status=... key=value ...` is the kernel's summary (parse_summary).

With sha256 (the restored digest), run_kernel opens argv[0] once, hashes it through that descriptor and starts the kernel
from /proc/self/fd/N of the same descriptor (N3-A01, as benchlab.native_worker.NativeWorker.start). Without sha256, a
kernel inside the SAFE_C_BENCH_NATIVE restore directory is refused (N3b-A02)."""
import os, selectors, subprocess, threading, time
from benchlab.native_worker import BinaryRefused, FrameError, SHUTDOWN_WAIT, confirm_verified, fd_path, open_verified, refuse_unverified

HANDSHAKE=(b'B',b'G',b'E',b'F')
OUTPUT_CAP=65536
INTEGER_KEYS=('records','loops','threads','mono_ns','cpu_ns','chunks','copied_bytes')
LIST_KEYS=('chunk_sizes','chunk_wall_ns')

def _uint(text):
    if not text.isdigit() or not text.isascii():raise ValueError('summary value is not an unsigned integer')
    return int(text)

def parse_summary(line):
    """The PLK1 line as a dict: status, integer keys, list keys, every other key=value as text under `extra`."""
    parts=line.strip().split(' ')
    if not parts or parts[0]!='PLK1':raise ValueError('summary line does not start with PLK1')
    out={};extra={}
    for part in parts[1:]:
        key,sep,value=part.partition('=')
        if not sep or not key:raise ValueError('summary part is not key=value')
        if key in out or key in extra:raise ValueError('summary key repeated')
        if key=='status':out[key]=value
        elif key in INTEGER_KEYS:out[key]=_uint(value)
        elif key in LIST_KEYS:out[key]=[_uint(v) for v in value.split(',')] if value else []
        else:extra[key]=value
    if 'status' not in out:raise ValueError('summary has no status')
    out['extra']=extra;return out

def _start(argv,env,sha256):
    """The kernel process: by path without sha256, else from the verified descriptor (BinaryRefused, the process reaped)."""
    if sha256 is None:
        refuse_unverified(argv[0])          # N3b-A02: a restored kernel never starts by path
        return subprocess.Popen(argv,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,close_fds=True)
    fd,identity=open_verified(argv[0],sha256)
    try:
        proc=subprocess.Popen(argv,executable=fd_path(fd),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,
                              close_fds=True,pass_fds=(fd,))
        try:confirm_verified(fd,sha256,identity,argv[0])
        except BinaryRefused:
            proc.kill();proc.wait()
            for s in (proc.stdin,proc.stdout,proc.stderr):s.close()
            raise
        return proc
    finally:os.close(fd)

def run_kernel(argv,*,env,deadline,on_begin,on_end,sha256=None):
    """Runs one kernel through the handshake; {'exit', 'summary' (None without a PLK1 line or above the cap),
    'stderr_bytes'}. A missing or wrong handshake byte or the deadline kills and reaps it: FrameError('HANDSHAKE').
    BinaryRefused when the verified start fails."""
    proc=_start(list(argv),dict(env),sha256)
    count=[0]
    def drain():
        while True:
            chunk=proc.stderr.read1(65536)
            if not chunk:return
            count[0]+=len(chunk)
    thread=threading.Thread(target=drain,daemon=True);thread.start()
    end=time.monotonic()+float(deadline);out=proc.stdout.fileno();os.set_blocking(out,False)
    def reap():
        if proc.poll() is None:proc.kill()
        proc.wait()
        for s in (proc.stdin,proc.stdout):
            try:s.close()
            except OSError:pass
        thread.join(SHUTDOWN_WAIT)
        try:proc.stderr.close()
        except OSError:pass
    def read_some(n):
        with selectors.DefaultSelector() as sel:
            sel.register(out,selectors.EVENT_READ)
            while True:
                left=end-time.monotonic()
                if left<=0:return None
                if sel.select(left):
                    try:return os.read(out,n)
                    except BlockingIOError:continue
    def expect(byte):
        if read_some(1)!=byte:reap();raise FrameError('HANDSHAKE')
    def send(byte):
        try:proc.stdin.write(byte);proc.stdin.flush()
        except (BrokenPipeError,OSError):reap();raise FrameError('HANDSHAKE')
    try:
        expect(HANDSHAKE[0]);on_begin();send(HANDSHAKE[1])
        expect(HANDSHAKE[2]);on_end();send(HANDSHAKE[3])
        rest=bytearray();over=False
        while True:
            chunk=read_some(65536)
            if chunk is None:reap();raise FrameError('HANDSHAKE')
            if not chunk:break
            if len(rest)+len(chunk)>OUTPUT_CAP:over=True
            if not over:rest+=chunk
        try:proc.stdin.close()
        except OSError:pass
        left=max(0.0,end-time.monotonic())
        try:proc.wait(left)
        except subprocess.TimeoutExpired:reap();raise FrameError('HANDSHAKE') from None
        reap()
    except BaseException:
        reap();raise
    summary=None
    if not over:
        lines=[l for l in bytes(rest).decode('ascii','replace').splitlines() if l.startswith('PLK1 ')]
        if lines:
            try:summary=parse_summary(lines[-1])
            except ValueError:summary=None
    return {'exit':proc.returncode,'summary':summary,'stderr_bytes':count[0]}
