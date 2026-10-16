"""Verified in-process loader for the `inproc` route (Phase 2 Task 18; plan amendment FR6 N3, ruling FR6-R3 item 1).

Record-agnostic: the workload codec names the ABI function, the entry, its ctypes argument types and its buffers. The
framework refuses a load outside a bench caller child (SAFE_C_BENCH_ROLE=caller and /work/bench a directory), opens the
library once (O_RDONLY | O_CLOEXEC | O_NOFOLLOW, a regular file only), verifies its sha256 through that descriptor and loads
/proc/self/fd/N of the same descriptor with ctypes.CDLL; after the load the file behind the descriptor must still have the
verified bytes, and the descriptor is closed (N3-A01). A refusal after the ctypes.CDLL call (changed bytes, ABI mismatch,
missing symbol) taints the process: every later load in it is refused (N3b-A01). It then checks that the ABI function returns ABI and sets the
entry's argtypes and restype. The check guards against an accidental change of the restored file and a swap of the path;
it does not guard against same-user code that runs in the caller child itself.
There is no environment override of the expected digest anywhere (M7). call() checks the framework request values (threads
in {0, 1, 2, 4}, 1 <= n <= MAX_RECORDS, 1 <= selector_mask <= 31) before it touches the entry, holds a reference to every
buffer until the call returns and takes time.monotonic_ns() immediately before and after the foreign call (ctypes.CDLL
releases the GIL during the call)."""
import ctypes, os, time
from pathlib import Path
from benchlab import native_worker as nw
from benchlab.native_worker import MAX_RECORDS, SELECTOR_MAX

ABI=2
THREADS=(0,1,2,4)
BENCH_DIR=Path('/work/bench')
LOAD_PROCESS={}
# /proc/self/fd/N -> sha256 of every library loaded in this process. The dynamic loader matches an earlier load by its
# name, so a later load of another library through a reused descriptor number would return the earlier library.
_LOADED={}
# N3b-A01: set after any refusal that follows a ctypes.CDLL call (the library stays mapped in this process, and the dynamic
# loader may return that object to a later load of the same name or file). Every later load in this process is refused.
_TAINTED=[]
REFUSED={'unverified':'library file has no restored digest','digest':'library digest mismatch','missing':'library file is missing','symlink':'library file is a symlink',
         'not a regular file':'library file is not a regular file','unreadable':'library file is unreadable',
         'changed':'library changed after the digest check'}

class InprocRefused(RuntimeError):
    """The library was not loaded: wrong process role, no bench directory, missing file, digest or ABI mismatch."""

def load(path,sha256,*,abi_symbol,entry,argtypes,restype=ctypes.c_int):
    """The verified ctypes.CDLL of path, with `entry` typed; InprocRefused otherwise."""
    role=os.environ.get('SAFE_C_BENCH_ROLE')
    if role!='caller':raise InprocRefused('in-process load refused: process role is not caller')
    if not BENCH_DIR.is_dir():raise InprocRefused('in-process load refused: no bench directory')
    if _TAINTED:raise InprocRefused('in-process load refused: an earlier library of this process was refused after its load')
    try:fd,identity=nw.open_verified(str(path),sha256)
    except nw.BinaryRefused as exc:raise InprocRefused('in-process load refused: '+REFUSED[exc.reason]) from None
    try:
        name=nw.fd_path(fd)
        if _LOADED.get(name,sha256)!=sha256:raise InprocRefused('in-process load refused: another library was loaded through this descriptor number')
        lib=ctypes.CDLL(name)
        try:nw.confirm_verified(fd,sha256,identity,str(path))
        except nw.BinaryRefused:
            _TAINTED.append(name);raise InprocRefused('in-process load refused: '+REFUSED['changed']) from None
    finally:os.close(fd)
    try:
        abi=getattr(lib,abi_symbol);abi.argtypes=[];abi.restype=ctypes.c_uint32
        if abi()!=ABI:raise InprocRefused('in-process load refused: ABI version mismatch')
        fn=getattr(lib,entry);fn.argtypes=list(argtypes);fn.restype=restype
    except BaseException:
        _TAINTED.append(name);raise
    _LOADED[name]=sha256           # N3b-A01: only a load that passed every check is recorded
    LOAD_PROCESS.clear();LOAD_PROCESS.update(pid=os.getpid(),role=role)
    return lib

def check_column(array,n):
    """The address of a C-contiguous little-endian float64 NumPy array of exactly n items, 8-byte aligned; ValueError naming
    the failed check otherwise."""
    import numpy as np
    if not isinstance(array,np.ndarray):raise ValueError('column is not a NumPy array')
    if array.dtype!=np.dtype('<f8'):raise ValueError('column dtype is not <f8')
    if not array.flags['C_CONTIGUOUS']:raise ValueError('column is not C-contiguous')
    if array.shape!=(n,):raise ValueError('column length differs from n')
    address=array.ctypes.data
    if address%8:raise ValueError('column address is not 8-byte aligned')
    return address

def check_bytes(buffer,length):
    """The address of a writable bytearray of exactly length bytes; ValueError otherwise."""
    if not isinstance(buffer,bytearray):raise ValueError('buffer is not a writable bytearray')
    if len(buffer)!=length:raise ValueError('buffer length differs')
    return ctypes.addressof(ctypes.c_char.from_buffer(buffer)) if length else 0

def _int(value,what,low,high):
    if isinstance(value,bool) or not isinstance(value,int) or not low<=value<=high:raise ValueError(f'{what} out of range')
    return value

def call(entry,n,threads,selector_mask,args,*,keep=(),scratch=None,echo_words=0):
    """Calls entry(*args) once: {'rc', 't0_ns', 't1_ns', 'echo'}; echo is the echo_words u64 values (little-endian) that the
    entry wrote into the last 8 * echo_words bytes of scratch."""
    if isinstance(threads,bool) or threads not in THREADS:raise ValueError('threads must be 0, 1, 2 or 4')
    _int(n,'records',1,MAX_RECORDS);_int(selector_mask,'selector_mask',1,SELECTOR_MAX)
    _int(echo_words,'echo_words',0,64)
    if echo_words and (not isinstance(scratch,bytearray) or len(scratch)<8*echo_words):raise ValueError('scratch is too small for the echo')
    held=(tuple(keep),tuple(args),scratch)
    t0=time.monotonic_ns();rc=entry(*args);t1=time.monotonic_ns()
    echo=[int.from_bytes(scratch[len(scratch)-8*(echo_words-k):len(scratch)-8*(echo_words-k-1)],'little') for k in range(echo_words)]
    del held
    return {'rc':rc,'t0_ns':t0,'t1_ns':t1,'echo':echo}
