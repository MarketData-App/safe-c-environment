"""Test-only per-model evaluation counters (Amendment G4.8): the detector for "only selected models are computed".

Active only when the environment variable SAFE_C_TEST_COUNTERS is exactly '1'. Only the example container test suite
sets it (tests/test_per_model.py); a timed run never does, and then `bump` returns at once without counting. The
variable is read at each call, so the module may be imported before the suite sets it.

Counts live in this process's memory (a lock guards them). The example runs single-threaded variants only.
"""
import multiprocessing, os, re, threading

ENV='SAFE_C_TEST_COUNTERS'
_KEY=re.compile(r'^[a-z0-9-]{1,16}$')
_LOCK=threading.Lock()
_COUNTS={}

def active():
    return os.environ.get(ENV)=='1'

def in_worker():
    """True in a multiprocessing child (a process-pool worker), whose counts must travel back with its chunk."""
    return multiprocessing.parent_process() is not None

def bump(model,n=1):
    """Count n engine calls of `model` (the optimized variant passes the element count of one vectorized call)."""
    if os.environ.get(ENV)!='1' or not n:return
    with _LOCK:_COUNTS[model]=_COUNTS.get(model,0)+int(n)

def snapshot():
    with _LOCK:return dict(_COUNTS)

def reset():
    with _LOCK:_COUNTS.clear()

def take():
    """The counts so far, then reset (one atomic step)."""
    with _LOCK:
        out=dict(_COUNTS);_COUNTS.clear();return out

def merge(counts):
    """Add a snapshot from a worker: {model name: integer >= 0}; anything else raises ValueError."""
    if not isinstance(counts,dict) or any(not isinstance(k,str) or not _KEY.fullmatch(k) or type(v) is not int or v<0 for k,v in counts.items()):
        raise ValueError('counters: a snapshot is {model: integer >= 0}')
    with _LOCK:
        for k,v in counts.items():_COUNTS[k]=_COUNTS.get(k,0)+v
