"""Generic SCPL v2 frame transport and native worker lifecycle (Phase 2 Task 18; Amendment F items 4, 5, 10, Amendment G
items G4.4, G4.5, Amendment I item I5; plan amendment FR6 N3, ruling FR6-R3 item 1).

Record-agnostic: a payload is opaque bytes, and `selector_mask` is an opaque u16 (1-31 on types 1, 2, 5, 6; 0 on types 3,
4). The record layout, the payload length of a REQUEST or RESPONSE and the meaning of the mask belong to the workload
codec, which passes `expect(header) -> int` to `exchange`. The framework enforces the header rules, the 4 MiB frame bound,
the deadline, the stderr cap and the reaping of the worker on every failure path.

Header `<4sHHQIHHI` (28 bytes): magic, version, type, request ID, record count, worker threads, selector mask, payload
length. decode_header checks in the Amendment G order magic, version, type, record count, threads, selector mask, frame
size, payload length."""
import errno, hashlib, json, os, re, selectors, stat, struct, subprocess, threading, time
from pathlib import Path

HEADER=struct.Struct('<4sHHQIHHI');MAGIC=b'SCPL';VERSION=2
REQUEST,RESPONSE,ERROR,SHUTDOWN,SHM_REQUEST,SHM_RESPONSE=1,2,3,4,5,6
ERROR_NAMES={1:'BAD_MAGIC',2:'BAD_VERSION',3:'BAD_TYPE',4:'RECORD_LIMIT',5:'FRAME_LIMIT',6:'LENGTH_MISMATCH',7:'PROTOCOL_TRUNCATED',
             8:'BAD_THREADS',9:'KERNEL_FAILURE',10:'IO_ERROR',11:'RESERVED_NONZERO',12:'BAD_SELECTOR'}
MAX_RECORDS=14336;MAX_FRAME=4194304;MAX_THREADS=4;STDERR_CAP=65536;SHUTDOWN_WAIT=2.0
SELECTOR_MAX=31;ERROR_PAYLOAD=4
SELECTED=(REQUEST,RESPONSE,SHM_REQUEST,SHM_RESPONSE);UNSELECTED=(ERROR,SHUTDOWN)
ANSWER={REQUEST:RESPONSE,SHM_REQUEST:SHM_RESPONSE}
# The last call's pool and transport evidence, set by a workload codec (chunk_rule, chunks, chunk_sizes, chunk_wall_ns,
# transport_ns, copied_bytes, load_process). benchlab.trial resets it before every timed call.
LAST_STATS={}

SHA256_RE=re.compile(r'[0-9a-f]{64}')
UNKNOWN_ERROR='UNKNOWN_ERROR'      # N3-A02: an ERROR frame whose code is outside ERROR_NAMES

NATIVE_NAME=re.compile(r'^(?:[a-z][a-z0-9_-]{0,62}|lib[a-z][a-z0-9_]{0,62}\.so)$')

def native_path(name):
    """The restored native binary `name` under SAFE_C_BENCH_NATIVE (set only after the coordinator verified it)."""
    base=os.environ.get('SAFE_C_BENCH_NATIVE')
    if not base:raise ValueError('no restored native binaries (SAFE_C_BENCH_NATIVE is not set)')
    if not isinstance(name,str) or not NATIVE_NAME.fullmatch(name):raise ValueError('native binary name rejected')
    return Path(base)/name

def native_sha256(name):
    """The sha256 restored with the binaries (SAFE_C_BENCH_NATIVE/sha256.json, written by the coordinator native_env).
    No environment variable can override it (M7)."""
    path=native_path(name)
    with open(path.parent/'sha256.json') as f:index=json.load(f)
    digest=index.get(name) if isinstance(index,dict) else None
    if not isinstance(digest,str) or not SHA256_RE.fullmatch(digest):raise ValueError('no restored sha256 for the native binary')
    return digest

def restored(name):
    """N3b-A02: (path, sha256) of the restored binary `name`; both come from the one SAFE_C_BENCH_NATIVE directory."""
    return native_path(name),native_sha256(name)

def same_directory(native_dir):
    """N3b-A02: native_dir must be the SAFE_C_BENCH_NATIVE restore directory (ValueError otherwise), so that a codec takes
    the file and its digest from one directory."""
    base=os.environ.get('SAFE_C_BENCH_NATIVE')
    if not base or os.path.realpath(str(native_dir))!=os.path.realpath(base):raise ValueError('native directory is not the restore directory')

class BinaryRefused(ValueError):
    """A restored binary was not used (N3-A01). `.reason`: digest (malformed expectation or other bytes), missing,
    symlink, not a regular file, unreadable, changed (the file behind the descriptor changed after the hash), or
    unverified (N3b-A02: a start by path of a file in the SAFE_C_BENCH_NATIVE restore directory without its sha256)."""
    def __init__(self,reason):super().__init__('restored native binary refused: '+reason);self.reason=reason

def refuse_unverified(path):
    """N3b-A02: a start by path (no sha256) is refused when path, with every link resolved, lies inside the
    SAFE_C_BENCH_NATIVE restore directory: BinaryRefused('unverified'). Other paths (framework test peers) are unchanged."""
    base=os.environ.get('SAFE_C_BENCH_NATIVE')
    if not base:return
    top=os.path.realpath(base);real=os.path.realpath(str(path))
    if real==top or real.startswith(top.rstrip('/')+'/'):raise BinaryRefused('unverified')

def _identity(st):return (st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns)

def _fd_sha256(fd):
    """(sha256 hex, byte count) of the file behind fd, read with pread from offset 0."""
    h=hashlib.sha256();offset=0
    while True:
        chunk=os.pread(fd,1<<20,offset)
        if not chunk:return h.hexdigest(),offset
        h.update(chunk);offset+=len(chunk)

def open_verified(path,sha256):
    """N3-A01: opens path once (O_RDONLY | O_CLOEXEC | O_NOFOLLOW; O_NONBLOCK so that a FIFO cannot block the open),
    refuses a symlink and a non-regular file, and hashes the file through that descriptor: (fd, identity). The caller
    uses the file only through fd_path(fd), calls confirm_verified(fd, sha256, identity, path) after the use and closes fd.
    BinaryRefused otherwise (no descriptor stays open)."""
    if not (isinstance(sha256,str) and SHA256_RE.fullmatch(sha256)):raise BinaryRefused('digest')
    try:fd=os.open(path,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW|os.O_NONBLOCK)
    except FileNotFoundError:raise BinaryRefused('missing') from None
    except OSError as exc:raise BinaryRefused('symlink' if exc.errno==errno.ELOOP else 'unreadable') from None
    try:
        st=os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):raise BinaryRefused('not a regular file')
        try:got,size=_fd_sha256(fd)
        except OSError:raise BinaryRefused('unreadable') from None
        if got!=sha256:raise BinaryRefused('digest')
        if size!=st.st_size or _identity(os.fstat(fd))!=_identity(st):raise BinaryRefused('changed')
    except BaseException:
        os.close(fd);raise
    return fd,_identity(st)

def confirm_verified(fd,sha256,identity,path):
    """N3-A01: after the use (load or exec), the file behind fd still has the verified bytes and the identity of the
    hash (device, inode, size, mtime, ctime); BinaryRefused('changed') otherwise. FR7b-IDENTITY-RULE-01 (owner rule: a
    replaced file is always refused): path, not followed when it is a symlink, must still name the verified file (st_dev
    and st_ino of lstat(path) equal those of fstat(fd)), with no clock involved. The ctime stays an extra signal (a write
    followed by an mtime reset); it is never the only one."""
    try:got,size=_fd_sha256(fd);st=os.fstat(fd);at=os.lstat(path)
    except OSError:raise BinaryRefused('changed') from None
    if (at.st_dev,at.st_ino)!=(st.st_dev,st.st_ino):raise BinaryRefused('changed')
    if got!=sha256 or size!=st.st_size or _identity(st)!=identity:raise BinaryRefused('changed')

def fd_path(fd):
    """The /proc/self/fd path of a descriptor of this process: the open file itself, whatever its path names now."""
    return f'/proc/self/fd/{fd}'

class FrameError(Exception):
    """A protocol, transport or lifecycle failure; `.name` is an ERROR_NAMES value or UNKNOWN_ERROR (an ERROR code outside
    ERROR_NAMES), DEADLINE, WORKER_EXITED, SELECTOR_MISMATCH, REQUEST_ID_MISMATCH, HANDSHAKE."""
    def __init__(self,name):super().__init__(name);self.name=name

def encode_header(kind,request_id,count,threads,selector_mask,payload_length):
    """The 28 header bytes. Field ranges only (ValueError); the protocol rules are decode_header's."""
    try:return HEADER.pack(MAGIC,VERSION,kind,request_id,count,threads,selector_mask,payload_length)
    except struct.error as exc:raise ValueError('header field out of range') from exc

def decode_header(data):
    """dict(type, request_id, count, threads, selector_mask, length) of the first 28 bytes; FrameError otherwise."""
    if len(data)<HEADER.size:raise FrameError('PROTOCOL_TRUNCATED')
    magic,version,kind,rid,count,threads,mask,length=HEADER.unpack_from(data)
    if magic!=MAGIC:raise FrameError('BAD_MAGIC')
    if version!=VERSION:raise FrameError('BAD_VERSION')
    if kind not in SELECTED+UNSELECTED:raise FrameError('BAD_TYPE')
    if count>MAX_RECORDS:raise FrameError('RECORD_LIMIT')
    if threads>MAX_THREADS:raise FrameError('BAD_THREADS')
    if kind in SELECTED and not 1<=mask<=SELECTOR_MAX:raise FrameError('BAD_SELECTOR')
    if kind in UNSELECTED and mask!=0:raise FrameError('RESERVED_NONZERO')
    if HEADER.size+length>MAX_FRAME:raise FrameError('FRAME_LIMIT')
    if kind==ERROR and (length!=ERROR_PAYLOAD or count or threads):raise FrameError('LENGTH_MISMATCH')
    if kind==SHUTDOWN and (length or count or threads):raise FrameError('LENGTH_MISMATCH')
    return {'type':kind,'request_id':rid,'count':count,'threads':threads,'selector_mask':mask,'length':length}

def request_id(call_sequence,request_index):
    """(call_sequence << 32) | request_index; both are u32 values."""
    for v in (call_sequence,request_index):
        if isinstance(v,bool) or not isinstance(v,int) or not 0<=v<2**32:raise ValueError('request ID part out of range')
    return (call_sequence<<32)|request_index

class NativeWorker:
    """One native worker process speaking SCPL v2 over its stdin and stdout. Every read and write uses the time left of
    the exchange deadline; any deadline, short read, malformed header, ERROR frame or worker exit kills and reaps the
    worker and raises FrameError; an exception of the codec's expect() kills and reaps it too, then propagates. stderr is
    drained by a thread that counts every byte and keeps the first 64 KiB.

    With sha256 (the restored digest, native_sha256), start() opens argv[0] once, hashes it through that descriptor and
    starts the worker from /proc/self/fd/N of the same descriptor (N3-A01); argv[0] stays the display name. The descriptor
    is passed to the worker (exec needs it open there) and closed in the caller after the start. Without sha256 the
    worker starts by path, unverified (framework tests with Python peers only); a path inside the SAFE_C_BENCH_NATIVE
    restore directory is then refused (N3b-A02)."""
    def __init__(self,argv,*,env,deadline,pass_fds=(),sha256=None):
        self.argv=list(argv);self.env=dict(env);self.deadline=float(deadline);self.pass_fds=tuple(pass_fds);self.sha256=sha256
        self.proc=None;self._drain=None;self._head=bytearray();self._stderr_bytes=0;self.copied_bytes=0
    def __enter__(self):return self
    def __exit__(self,*exc):self.kill();return False
    @property
    def stderr_bytes(self):return self._stderr_bytes
    @property
    def stderr_head(self):return bytes(self._head)
    def start(self):
        """Starts the worker; returns the spawn time in ns. BinaryRefused when the verified start fails (the worker, if it
        was started, is killed and reaped)."""
        fd=None
        if self.sha256 is None:refuse_unverified(self.argv[0])       # N3b-A02
        else:fd,identity=open_verified(self.argv[0],self.sha256)
        try:
            extra={} if fd is None else {'executable':fd_path(fd)}
            t=time.monotonic_ns()
            self.proc=subprocess.Popen(self.argv,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=self.env,
                                       pass_fds=self.pass_fds+(() if fd is None else (fd,)),close_fds=True,start_new_session=False,**extra)
            spawn=time.monotonic_ns()-t
            if fd is not None:
                try:confirm_verified(fd,self.sha256,identity,self.argv[0])
                except BinaryRefused:
                    self.kill();raise
        finally:
            if fd is not None:os.close(fd)
        os.set_blocking(self.proc.stdin.fileno(),False);os.set_blocking(self.proc.stdout.fileno(),False)
        self._drain=threading.Thread(target=self._drain_stderr,args=(self.proc.stderr,),daemon=True);self._drain.start()
        return spawn
    def _drain_stderr(self,stream):
        while True:
            chunk=stream.read1(65536) if hasattr(stream,'read1') else stream.read(65536)
            if not chunk:return
            self._stderr_bytes+=len(chunk)
            room=STDERR_CAP-len(self._head)
            if room>0:self._head+=chunk[:room]
    def alive(self):return self.proc is not None and self.proc.poll() is None
    def kill(self):
        """Kills and reaps the worker (idempotent) and closes the pipes."""
        if self.proc is None:return
        if self.proc.poll() is None:
            try:self.proc.kill()
            except ProcessLookupError:pass
        self.proc.wait();self._close()
    def _close(self):
        for stream in (self.proc.stdin,self.proc.stdout):
            try:stream.close()
            except OSError:pass
        if self._drain is not None:self._drain.join(SHUTDOWN_WAIT)
        try:self.proc.stderr.close()
        except OSError:pass
    def _fail(self,name):
        self.kill();raise FrameError(name)
    def _write(self,data,end):
        view=memoryview(data);fd=self.proc.stdin.fileno()
        with selectors.DefaultSelector() as sel:
            sel.register(fd,selectors.EVENT_WRITE)
            while view:
                left=end-time.monotonic()
                if left<=0:self._fail('DEADLINE')
                if not sel.select(left):continue
                try:n=os.write(fd,view)
                except BlockingIOError:continue
                except (BrokenPipeError,ConnectionResetError):self._fail('WORKER_EXITED')
                view=view[n:];self.copied_bytes+=n
    def _read(self,n,end,first):
        """Exactly n bytes. EOF before any byte of a frame is WORKER_EXITED (first) or PROTOCOL_TRUNCATED."""
        data=bytearray();fd=self.proc.stdout.fileno()
        with selectors.DefaultSelector() as sel:
            sel.register(fd,selectors.EVENT_READ)
            while len(data)<n:
                left=end-time.monotonic()
                if left<=0:self._fail('DEADLINE')
                if not sel.select(left):continue
                try:chunk=os.read(fd,n-len(data))
                except BlockingIOError:continue
                if not chunk:self._fail('WORKER_EXITED' if first and not data else 'PROTOCOL_TRUNCATED')
                data+=chunk;self.copied_bytes+=len(chunk)
        return bytes(data)
    def exchange(self,kind,request_id,count,threads,selector_mask,payload,expect):
        """Writes one request frame and reads its answer: (header dict, payload bytes)."""
        if kind not in ANSWER:raise ValueError('exchange takes a REQUEST or SHM_REQUEST')
        frame=encode_header(kind,request_id,count,threads,selector_mask,len(payload))
        try:decode_header(frame)                   # the request itself keeps the header rules
        except FrameError as exc:raise ValueError('request header refused: '+exc.name) from None
        if HEADER.size+len(payload)>MAX_FRAME:raise ValueError('request frame above the frame limit')
        if not self.alive():
            if self.proc is not None:self.kill()
            raise FrameError('WORKER_EXITED')
        end=time.monotonic()+self.deadline
        self._write(frame+bytes(payload),end)
        raw=self._read(HEADER.size,end,True)
        try:head=decode_header(raw)
        except FrameError as exc:self._fail(exc.name)
        if head['type']==ERROR:
            code=struct.unpack('<I',self._read(ERROR_PAYLOAD,end,False))[0]
            self._fail(ERROR_NAMES.get(code,UNKNOWN_ERROR))
        if head['type']!=ANSWER[kind]:self._fail('BAD_TYPE')
        if head['request_id']!=request_id:self._fail('REQUEST_ID_MISMATCH')
        if head['selector_mask']!=selector_mask:self._fail('SELECTOR_MISMATCH')
        try:want=expect(head)
        except BaseException:
            self.kill();raise                      # N3-A02: a codec failure reaps the worker before it propagates
        if want!=head['length']:self._fail('LENGTH_MISMATCH')
        return head,self._read(head['length'],end,False) if head['length'] else b''
    def shutdown(self):
        """SHUTDOWN frame, close stdin, wait at most SHUTDOWN_WAIT, kill, reap; the exit code (None when never started)."""
        if self.proc is None:return None
        if self.proc.poll() is None:
            try:self._write(encode_header(SHUTDOWN,0,0,0,0,0),time.monotonic()+SHUTDOWN_WAIT)
            except FrameError:return self.proc.returncode
            try:self.proc.stdin.close()
            except OSError:pass
            try:self.proc.wait(SHUTDOWN_WAIT)
            except subprocess.TimeoutExpired:pass
        self.kill();return self.proc.returncode
