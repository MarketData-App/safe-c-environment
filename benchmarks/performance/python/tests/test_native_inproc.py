import ctypes, os, unittest
from pathlib import Path
from unittest import mock
import numpy as np
from benchlab import native_inproc as ni

def reset_loader():
    """The per-process loader state (N3b-A01): every test starts with an untainted process and no recorded load."""
    for name in ('_LOADED','_TAINTED'):
        state=getattr(ni,name,None)
        if state is not None:state.clear()

class InprocChecks(unittest.TestCase):
    def setUp(self):reset_loader();self.addCleanup(reset_loader)
    def test_load_refused_outside_the_caller_child(self):
        self.assertFalse(hasattr(ni,'SHA_OVERRIDE'))
        old=os.environ.pop('SAFE_C_BENCH_ROLE',None)
        try:
            with self.assertRaises(ni.InprocRefused):ni.load('/nonexistent.so','0'*64,abi_symbol='x_abi',entry='x',argtypes=[])
            os.environ['SAFE_C_BENCH_ROLE']='coordinator'
            with self.assertRaisesRegex(ni.InprocRefused,'role'):ni.load('/nonexistent.so','0'*64,abi_symbol='x_abi',entry='x',argtypes=[])
        finally:
            os.environ.pop('SAFE_C_BENCH_ROLE',None)
            if old is not None:os.environ['SAFE_C_BENCH_ROLE']=old
    def test_buffer_checks_refuse_before_the_call(self):
        good=np.zeros(8,dtype='<f8')
        self.assertEqual(ni.check_column(good,8),good.ctypes.data)
        for bad,msg in ((good[::2],'contiguous'),(good.astype('<f4'),'dtype'),(np.zeros(8,dtype='>f8'),'dtype'),(good,'length'),([0.0]*8,'NumPy')):
            with self.subTest(msg=msg):
                with self.assertRaisesRegex(ValueError,msg):ni.check_column(bad,8 if msg!='length' else 9)
        raw=np.zeros(9*8+1,dtype=np.uint8);mis=raw[1:1+64].view('<f8')      # NumPy allocations are at least 16-byte aligned
        self.assertEqual(mis.ctypes.data%8,1)
        with self.assertRaisesRegex(ValueError,'aligned'):ni.check_column(mis,8)
        with self.assertRaisesRegex(ValueError,'bytearray'):ni.check_bytes(bytes(10),10)
        with self.assertRaisesRegex(ValueError,'length'):ni.check_bytes(bytearray(9),10)
        buf=bytearray(10);self.assertEqual(ni.check_bytes(buf,10),ctypes.addressof(ctypes.c_char.from_buffer(buf)))
    def test_call_checks_threads_records_and_selector_before_touching_the_entry(self):
        for kwargs,msg in (({'threads':3},'threads'),({'n':0},'records'),({'n':14337},'records'),({'selector_mask':0},'selector'),
                           ({'selector_mask':32},'selector'),({'threads':True},'threads'),({'n':1.0},'records')):
            args=dict({'n':8,'threads':0,'selector_mask':7},**kwargs)
            with self.subTest(msg=msg,kwargs=kwargs):
                with self.assertRaisesRegex(ValueError,msg):ni.call(None,args=(),**args)
    def test_call_times_the_foreign_function_and_reads_the_echo(self):
        seen=[]
        def entry(*args):
            seen.append(args);scratch=args[0];scratch[-16:]=(5).to_bytes(8,'little')+(9).to_bytes(8,'little');return 0
        scratch=bytearray(32)
        got=ni.call(entry,8,0,1,(scratch,),keep=(scratch,),scratch=scratch,echo_words=2)
        self.assertEqual((got['rc'],got['echo']),(0,[5,9]));self.assertLessEqual(got['t0_ns'],got['t1_ns']);self.assertEqual(len(seen),1)
        self.assertEqual(ni.call(lambda:3,1,4,31,())['echo'],[])
        with self.assertRaisesRegex(ValueError,'scratch'):ni.call(lambda:0,1,0,1,(),scratch=bytearray(8),echo_words=2)
    def test_inproc_abi(self):
        self.assertEqual(ni.ABI,2)
    def test_corrupted_library_is_refused(self):
        import hashlib, tempfile
        with tempfile.TemporaryDirectory() as d:
            lib=Path(d)/'libx.so';lib.write_bytes(b'\x7fELF'+bytes(60));good=hashlib.sha256(lib.read_bytes()).hexdigest()
            data=bytearray(lib.read_bytes());data[10]^=1;lib.write_bytes(bytes(data))
            os.environ['SAFE_C_BENCH_ROLE']='caller'
            try:
                with mock.patch.object(ni,'BENCH_DIR',Path(d)),mock.patch.object(ni.ctypes,'CDLL',side_effect=AssertionError('loaded')):
                    with self.assertRaisesRegex(ni.InprocRefused,'digest'):ni.load(str(lib),good,abi_symbol='x_abi',entry='x',argtypes=[])      # checked before ctypes.CDLL
                    with self.assertRaisesRegex(ni.InprocRefused,'digest'):ni.load(str(lib),'A'*64,abi_symbol='x_abi',entry='x',argtypes=[])
                    with self.assertRaisesRegex(ni.InprocRefused,'library'):ni.load(str(Path(d)/'absent.so'),good,abi_symbol='x_abi',entry='x',argtypes=[])
                with mock.patch.object(ni,'BENCH_DIR',Path(d)/'absent'):
                    with self.assertRaisesRegex(ni.InprocRefused,'bench'):ni.load(str(lib),good,abi_symbol='x_abi',entry='x',argtypes=[])
            finally:os.environ.pop('SAFE_C_BENCH_ROLE',None)
    def test_a_verified_library_gets_its_abi_checked_and_its_argtypes(self):
        import hashlib, tempfile
        class Fn:
            def __init__(self,value):self.value=value;self.argtypes=None;self.restype=None
            def __call__(self):return self.value
        class Lib:
            def __init__(self,abi):self.x_abi=Fn(abi);self.x=Fn(0)
        with tempfile.TemporaryDirectory() as d:
            lib=Path(d)/'libx.so';lib.write_bytes(b'\x7fELF'+bytes(60));good=hashlib.sha256(lib.read_bytes()).hexdigest()
            os.environ['SAFE_C_BENCH_ROLE']='caller'
            try:
                with mock.patch.object(ni,'BENCH_DIR',Path(d)):
                    with mock.patch.object(ni.ctypes,'CDLL',return_value=Lib(2)) as cdll:
                        got=ni.load(str(lib),good,abi_symbol='x_abi',entry='x',argtypes=[ctypes.c_size_t])
                    cdll.assert_called_once();(name,),_=cdll.call_args                  # N3-A01: loaded through the verified descriptor
                    self.assertRegex(name,r'^/proc/self/fd/[0-9]+$')
                    self.assertEqual((got.x.argtypes,got.x.restype,got.x_abi.restype),([ctypes.c_size_t],ctypes.c_int,ctypes.c_uint32))
                    self.assertEqual(ni.LOAD_PROCESS,{'pid':os.getpid(),'role':'caller'})
                    with mock.patch.object(ni.ctypes,'CDLL',return_value=Lib(1)):
                        with self.assertRaisesRegex(ni.InprocRefused,'ABI'):ni.load(str(lib),good,abi_symbol='x_abi',entry='x',argtypes=[])
            finally:os.environ.pop('SAFE_C_BENCH_ROLE',None)

import time
CLOCK_REALTIME_COARSE=getattr(time,'CLOCK_REALTIME_COARSE',5)     # Linux: the clock of file timestamps

def wait_for_timestamp_tick(path):
    """Returns once the coarse real-time clock is past the ctime of path, so a later change of the inode gets a new
    ctime (an explicit condition, bounded to 2 s)."""
    import os
    ctime=os.stat(path).st_ctime_ns;limit=time.monotonic()+2.0
    while time.clock_gettime_ns(CLOCK_REALTIME_COARSE)<=ctime:
        if time.monotonic()>limit:raise AssertionError('the timestamp clock did not advance')
        time.sleep(0.001)

class VerifiedDescriptorTests(unittest.TestCase):
    """N3-A01: load() opens the library once, hashes it through that descriptor and loads /proc/self/fd/N of the same
    descriptor, so a file swapped or changed between the hash and the load is never loaded as the verified bytes."""
    class Fn:
        def __init__(self,value):self.value=value;self.argtypes=None;self.restype=None
        def __call__(self):return self.value
    def setUp(self):
        import hashlib, shutil, tempfile
        d=Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,d,True);self.dir=d
        self.lib=d/'libx.so';self.verified=b'\x7fELF'+bytes(60);self.lib.write_bytes(self.verified)
        self.good=hashlib.sha256(self.verified).hexdigest();self.other=b'\x7fELF'+b'swapped'*9
        os.environ['SAFE_C_BENCH_ROLE']='caller';self.addCleanup(os.environ.pop,'SAFE_C_BENCH_ROLE',None)
        reset_loader();self.addCleanup(reset_loader)
    def cdll(self,change):
        """A ctypes.CDLL stand-in: it first changes the file at the library path (the hook between the hash and the load),
        then records the bytes behind the name it was given, as the dynamic loader would read them."""
        seen=[];test=self
        def load(name):
            change();seen.append(Path(name).read_bytes())
            lib=type('Lib',(),{})();lib.x_abi=test.Fn(2);lib.x=test.Fn(0);return lib
        return load,seen
    def swap(self):
        tmp=self.dir/'swap.tmp';tmp.write_bytes(self.other);os.replace(tmp,self.lib)
    def rewrite(self):
        with open(self.lib,'r+b') as f:f.seek(10);f.write(b'changed')
    def load(self):
        return ni.load(str(self.lib),self.good,abi_symbol='x_abi',entry='x',argtypes=[])
    def test_a_file_swapped_after_the_hash_is_not_loaded(self):
        """FR7b-IDENTITY-RULE-01 (owner rule: a replaced file is always refused): the swap renames the directory that holds
        the file and puts another file at the same path. The verified inode is not touched, but at the check point the path
        names another file, so load() refuses ('changed'); the loader saw only the verified bytes."""
        sub=self.dir/'sub';sub.mkdir();lib=sub/'libx.so';lib.write_bytes(self.verified)
        def swap():
            os.rename(sub,self.dir/'old');sub.mkdir();(sub/'libx.so').write_bytes(self.other)
        fake,seen=self.cdll(swap)
        with mock.patch.object(ni,'BENCH_DIR',self.dir),mock.patch.object(ni.ctypes,'CDLL',side_effect=fake):
            with self.assertRaisesRegex(ni.InprocRefused,'changed'):ni.load(str(lib),self.good,abi_symbol='x_abi',entry='x',argtypes=[])
        self.assertEqual(seen,[self.verified])                    # the verified bytes, not the swapped file
        self.assertEqual(lib.read_bytes(),self.other)             # the swap did happen
    def test_an_unchanged_file_is_loaded(self):
        """FR7b-IDENTITY-RULE-01: the unchanged library passes the path identity check and loads the verified bytes."""
        fake,seen=self.cdll(lambda:None)
        with mock.patch.object(ni,'BENCH_DIR',self.dir),mock.patch.object(ni.ctypes,'CDLL',side_effect=fake):self.load()
        self.assertEqual(seen,[self.verified])
    def test_a_file_renamed_over_is_refused_with_no_clock_wait(self):
        """FR7b-IDENTITY-RULE-01 (owner rule): a rename over the library right after the hash, with no wait for a
        timestamp tick, is refused ('changed') on the first try; the loader saw only the verified bytes."""
        fake,seen=self.cdll(self.swap)
        with mock.patch.object(ni,'BENCH_DIR',self.dir),mock.patch.object(ni.ctypes,'CDLL',side_effect=fake):
            with self.assertRaisesRegex(ni.InprocRefused,'changed'):self.load()
        self.assertEqual(seen,[self.verified]);self.assertEqual(self.lib.read_bytes(),self.other)
    def test_a_file_renamed_over_is_refused_when_the_ctime_gives_no_signal(self):
        """FR7b-IDENTITY-RULE-01: the no-tick case made deterministic. The identity without ctime stands for a rename over in
        the same timestamp tick (the ctime of the verified inode does not change); the path identity alone refuses it."""
        fake,seen=self.cdll(self.swap)
        with mock.patch.object(ni,'BENCH_DIR',self.dir),mock.patch.object(ni.ctypes,'CDLL',side_effect=fake):
            with mock.patch.object(ni.nw,'_identity',lambda st:(st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns)):
                with self.assertRaisesRegex(ni.InprocRefused,'changed'):self.load()
        self.assertEqual(seen,[self.verified]);self.assertEqual(self.lib.read_bytes(),self.other)
    def test_a_file_renamed_over_after_a_timestamp_tick_is_refused(self):
        """FR7b-R3: a rename over the library after the timestamp clock passed its ctime changes the ctime of the
        verified inode, so load() refuses ('changed'); the loader saw only the verified bytes."""
        def swap_after_tick():
            wait_for_timestamp_tick(self.lib);self.swap()
        fake,seen=self.cdll(swap_after_tick)
        with mock.patch.object(ni,'BENCH_DIR',self.dir),mock.patch.object(ni.ctypes,'CDLL',side_effect=fake):
            with self.assertRaisesRegex(ni.InprocRefused,'changed'):self.load()
        self.assertEqual(seen,[self.verified]);self.assertEqual(self.lib.read_bytes(),self.other)
    def test_a_file_changed_in_place_after_the_hash_is_refused(self):
        fake,seen=self.cdll(self.rewrite)
        with mock.patch.object(ni,'BENCH_DIR',self.dir),mock.patch.object(ni.ctypes,'CDLL',side_effect=fake):
            with self.assertRaisesRegex(ni.InprocRefused,'changed'):self.load()
        self.assertEqual(len(seen),1)
    def test_the_descriptor_is_closed_after_the_load(self):
        names=[]
        def fake(name):
            names.append(name);self.assertTrue(os.path.exists(name))
            lib=type('Lib',(),{})();lib.x_abi=self.Fn(2);lib.x=self.Fn(0);return lib
        with mock.patch.object(ni,'BENCH_DIR',self.dir),mock.patch.object(ni.ctypes,'CDLL',side_effect=fake):self.load()
        fd=int(names[0].rsplit('/',1)[1])
        with self.assertRaises(OSError):os.fstat(fd)
    def restore(self):
        with open(self.lib,'r+b') as f:f.write(self.verified)
    def test_a_load_after_a_refusal_that_followed_the_load_is_refused(self):
        """N3b-A01: change in place, refuse, restore the bytes, load again: refused (the refused object stays mapped)."""
        fake,seen=self.cdll(self.rewrite)
        with mock.patch.object(ni,'BENCH_DIR',self.dir),mock.patch.object(ni.ctypes,'CDLL',side_effect=fake):
            with self.assertRaisesRegex(ni.InprocRefused,'changed'):self.load()
        self.restore();self.assertEqual(self.lib.read_bytes(),self.verified)
        self.assertEqual(ni._LOADED,{})                              # a refused load is never recorded as loaded
        fake,seen=self.cdll(lambda:None)
        with mock.patch.object(ni,'BENCH_DIR',self.dir),mock.patch.object(ni.ctypes,'CDLL',side_effect=fake):
            with self.assertRaisesRegex(ni.InprocRefused,'earlier library'):self.load()
        self.assertEqual(seen,[])                                    # refused before any new ctypes.CDLL call
    def test_a_load_after_an_abi_refusal_is_refused(self):
        def wrong_abi(name):
            lib=type('Lib',(),{})();lib.x_abi=self.Fn(1);lib.x=self.Fn(0);return lib
        def right_abi(name):
            lib=type('Lib',(),{})();lib.x_abi=self.Fn(2);lib.x=self.Fn(0);return lib
        with mock.patch.object(ni,'BENCH_DIR',self.dir):
            with mock.patch.object(ni.ctypes,'CDLL',side_effect=wrong_abi),self.assertRaisesRegex(ni.InprocRefused,'ABI'):self.load()
            with mock.patch.object(ni.ctypes,'CDLL',side_effect=right_abi),self.assertRaisesRegex(ni.InprocRefused,'earlier library'):self.load()
        self.assertEqual(ni._LOADED,{})
    def test_a_symlink_and_a_non_regular_file_are_refused(self):
        link=self.dir/'liblink.so';link.symlink_to(self.lib);fifo=self.dir/'libfifo.so';os.mkfifo(fifo)
        with mock.patch.object(ni,'BENCH_DIR',self.dir),mock.patch.object(ni.ctypes,'CDLL',side_effect=AssertionError('loaded')):
            for path in (link,fifo,self.dir):
                with self.subTest(path=path.name),self.assertRaisesRegex(ni.InprocRefused,'library'):
                    ni.load(str(path),self.good,abi_symbol='x_abi',entry='x',argtypes=[])

if __name__=='__main__':unittest.main()
