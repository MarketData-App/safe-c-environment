"""Sealed memfd regions for the `shm` route (Phase 2 Task 18; Amendment F item 10; plan amendment FR6 N3, ruling FR6-R3
item 1). Record-agnostic: the workload codec supplies the input and output region sizes (its largest request and its
largest response payload); the framework refuses a size outside 1 to MAX_FRAME (4 MiB) and makes each region exactly
the given size, sealed against shrinking, growing and later seal changes.

snapshot()/leftover() are the job-end check of Amendment F item 10 (d): the open memfd descriptors of this process and
its descendants, and the /dev/shm entry names."""
import fcntl, mmap, os, struct
from benchlab.native_worker import MAX_FRAME

SEALS=fcntl.F_SEAL_SHRINK|fcntl.F_SEAL_GROW|fcntl.F_SEAL_SEAL
DESCRIPTOR=struct.Struct('<4Q')
NAME='safe-c-bench-region'

def _size(value,what):
    if isinstance(value,bool) or not isinstance(value,int) or not 1<=value<=MAX_FRAME:
        raise ValueError(f'{what} region size must be an integer from 1 to {MAX_FRAME}')
    return value

class Regions:
    """Two sealed memfd regions (input, output) of the exact sizes given, mapped read-write. close() releases the
    views, the maps and both descriptors; it is idempotent and runs on every path of the context manager."""
    def __init__(self,input_bytes,output_bytes):
        sizes=(_size(input_bytes,'input'),_size(output_bytes,'output'))
        self.input_fd=self.output_fd=None;self.input=self.output=None;self._maps=[];self._fds=[]
        try:
            for size in sizes:
                fd=os.memfd_create(NAME,os.MFD_CLOEXEC|os.MFD_ALLOW_SEALING);self._fds.append(fd)
                os.ftruncate(fd,size);fcntl.fcntl(fd,fcntl.F_ADD_SEALS,SEALS)
                self._maps.append(mmap.mmap(fd,size))
            self.input_fd,self.output_fd=self._fds
            self.input,self.output=memoryview(self._maps[0]),memoryview(self._maps[1])
        except BaseException:
            self.close();raise
    @property
    def input_bytes(self):return len(self._maps[0]) if self._maps else 0
    @property
    def output_bytes(self):return len(self._maps[1]) if len(self._maps)>1 else 0
    def pass_fds(self):return (self.input_fd,self.output_fd)
    def __enter__(self):return self
    def __exit__(self,*exc):self.close();return False
    def close(self):
        for view in (self.input,self.output):
            if view is not None:view.release()
        self.input=self.output=None
        while self._maps:self._maps.pop().close()
        while self._fds:os.close(self._fds.pop())
        self.input_fd=self.output_fd=None

def encode_descriptor(in_offset,in_length,out_offset,out_capacity):
    """The 32-byte SHM_REQUEST payload `<4Q`."""
    for v in (in_offset,in_length,out_offset,out_capacity):
        if isinstance(v,bool) or not isinstance(v,int) or not 0<=v<2**64:raise ValueError('descriptor field out of range')
    return DESCRIPTOR.pack(in_offset,in_length,out_offset,out_capacity)

def check_descriptor(regions,in_offset,in_length,out_offset,out_capacity):
    """ValueError unless both ranges lie inside their regions (the client side of the Amendment F item 10 checks)."""
    if in_offset+in_length>regions.input_bytes or out_offset+out_capacity>regions.output_bytes:
        raise ValueError('descriptor range outside its region')

def _descendants():
    me=os.getpid();parent={}
    for entry in os.listdir('/proc'):
        if not entry.isdigit():continue
        try:
            with open(f'/proc/{entry}/stat','rb') as f:stat=f.read()
        except OSError:continue
        try:parent[int(entry)]=int(stat[stat.rindex(b')')+2:].split()[1])
        except (ValueError,IndexError):continue
    found={me};grew=True
    while grew:
        grew=False
        for pid,ppid in parent.items():
            if ppid in found and pid not in found:found.add(pid);grew=True
    return sorted(found)

def snapshot():
    """{'memfd': sorted '<pid>:<fd>:<link>' of open memfd descriptors of this process and its descendants,
    'shm': sorted /dev/shm names}."""
    memfd=[]
    for pid in _descendants():
        try:fds=os.listdir(f'/proc/{pid}/fd')
        except OSError:continue
        for fd in fds:
            try:link=os.readlink(f'/proc/{pid}/fd/{fd}')
            except OSError:continue
            if link.startswith('/memfd:'):memfd.append(f'{pid}:{fd}:{link}')
    try:shm=sorted(os.listdir('/dev/shm'))
    except OSError:shm=[]
    return {'memfd':sorted(memfd),'shm':shm}

def leftover(before):
    """New memfd descriptors or /dev/shm entries since `before` (a snapshot()); [] when nothing was left."""
    now=snapshot()
    return sorted(set(now['memfd'])-set(before['memfd']))+['/dev/shm/'+n for n in sorted(set(now['shm'])-set(before['shm']))]
