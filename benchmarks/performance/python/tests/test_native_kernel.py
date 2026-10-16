import sys, time, unittest
from benchlab import native_kernel as nk
from benchlab import native_worker as nw
LINE='PLK1 status=OK records=4 loops=1 threads=0 mono_ns=10 cpu_ns=9 chunks=0 chunk_sizes= chunk_wall_ns= copied_bytes=256 red=x'
KERNEL=('import os,sys\n'
        'def get(b):\n'
        '    got=os.read(0,1)\n'
        '    if got!=b:sys.exit(5)\n'
        'os.write(1,b"B");get(b"G");os.write(1,b"E");get(b"F")\n'
        'os.write(1,(%r+"\\n").encode())\n')%LINE
NO_E=('import os,sys,time\nos.write(1,b"B");os.read(0,1);time.sleep(3600)\n')

def kernel(program):return [sys.executable,'-I','-c',program]

class KernelHandshakeTests(unittest.TestCase):
    def test_callbacks_run_in_order_between_the_bytes(self):
        events=[]
        got=nk.run_kernel(kernel(KERNEL),env={},deadline=5.0,on_begin=lambda:events.append('begin'),on_end=lambda:events.append('end'))
        self.assertEqual(events,['begin','end']);self.assertEqual(got['exit'],0);self.assertEqual(got['stderr_bytes'],0)
        s=got['summary']
        self.assertEqual((s['status'],s['records'],s['loops'],s['threads'],s['mono_ns'],s['cpu_ns'],s['chunks'],s['copied_bytes']),('OK',4,1,0,10,9,0,256))
        self.assertEqual((s['chunk_sizes'],s['chunk_wall_ns'],s['extra']),([],[],{'red':'x'}))
        self.assertEqual(nk.HANDSHAKE,(b'B',b'G',b'E',b'F'))
    def test_parse_summary_keys_and_types(self):
        s=nk.parse_summary('PLK1 status=OK records=2 loops=3 threads=2 mono_ns=5 cpu_ns=4 chunks=2 chunk_sizes=1,1 chunk_wall_ns=7,8 copied_bytes=24 digest=ab case=x')
        self.assertEqual((s['chunk_sizes'],s['chunk_wall_ns'],s['extra']),([1,1],[7,8],{'digest':'ab','case':'x'}))
        self.assertEqual(nk.parse_summary('PLK1 status=FAIL reason=usage'),{'status':'FAIL','extra':{'reason':'usage'}})
        for bad in ('PLK2 status=OK','PLK1 records=1','PLK1 status=OK records=x','PLK1 status=OK chunk_sizes=1,,2','PLK1 status=OK noequals',
                    'PLK1 status=OK records=1 records=2','PLK1 status=OK records=-1'):
            with self.subTest(bad=bad),self.assertRaises(ValueError):nk.parse_summary(bad)
    def test_a_kernel_that_never_writes_e_is_killed_within_the_deadline(self):
        t=time.monotonic();events=[]
        with self.assertRaises(nw.FrameError) as c:nk.run_kernel(kernel(NO_E),env={},deadline=0.5,on_begin=lambda:events.append('b'),on_end=lambda:events.append('e'))
        self.assertEqual(c.exception.name,'HANDSHAKE');self.assertLess(time.monotonic()-t,0.5+nw.SHUTDOWN_WAIT+1.0);self.assertEqual(events,['b'])
    def test_a_wrong_or_missing_first_byte_is_a_handshake_failure(self):
        for program in ('import os;os.write(1,b"X")','pass'):
            with self.subTest(program=program),self.assertRaises(nw.FrameError) as c:
                nk.run_kernel(kernel(program),env={},deadline=2.0,on_begin=lambda:None,on_end=lambda:None)
            self.assertEqual(c.exception.name,'HANDSHAKE')
    def test_output_after_the_handshake_is_capped(self):
        program=KERNEL+'os.write(1,b"z"*200000)\n'
        got=nk.run_kernel(kernel(program),env={},deadline=5.0,on_begin=lambda:None,on_end=lambda:None)
        self.assertIsNone(got['summary']);self.assertEqual(got['exit'],0)
    def test_no_summary_line_gives_none(self):
        program=KERNEL.replace('PLK1','XLK1')
        self.assertIsNone(nk.run_kernel(kernel(program),env={},deadline=5.0,on_begin=lambda:None,on_end=lambda:None)['summary'])

def exec_dir():
    """A directory whose files may be executed: the job work directory in the bench container (its /tmp is noexec)."""
    import os
    return '/work' if os.path.isdir('/work') and os.access('/work',os.W_OK|os.X_OK) else None

CLOCK_REALTIME_COARSE=getattr(time,'CLOCK_REALTIME_COARSE',5)     # Linux: the clock of file timestamps

def wait_for_timestamp_tick(path):
    """Returns once the coarse real-time clock is past the ctime of path, so a later change of the inode gets a new
    ctime (an explicit condition, bounded to 2 s)."""
    import os
    ctime=os.stat(path).st_ctime_ns;limit=time.monotonic()+2.0
    while time.clock_gettime_ns(CLOCK_REALTIME_COARSE)<=ctime:
        if time.monotonic()>limit:raise AssertionError('the timestamp clock did not advance')
        time.sleep(0.001)

class VerifiedKernelStartTests(unittest.TestCase):
    """N3-A01: with the restored sha256, run_kernel opens the kernel once, hashes it through that descriptor and starts it
    from /proc/self/fd/N of the same descriptor."""
    def setUp(self):
        import hashlib, shutil, tempfile
        from pathlib import Path
        d=Path(tempfile.mkdtemp(dir=exec_dir()));self.addCleanup(shutil.rmtree,d,True);self.dir=d
        self.exe=d/'kernel';self.exe.write_text('#!'+sys.executable+' -I\n'+KERNEL);self.exe.chmod(0o755)
        self.good=hashlib.sha256(self.exe.read_bytes()).hexdigest()
    def run_after(self,change,digest=None,path=None):
        from unittest import mock
        real=nk.subprocess.Popen
        def popen(*args,**kwargs):change();return real(*args,**kwargs)
        with mock.patch.object(nk.subprocess,'Popen',side_effect=popen):
            return nk.run_kernel([str(path or self.exe)],env={},deadline=5.0,on_begin=lambda:None,on_end=lambda:None,sha256=digest or self.good)
    def swapped_text(self):
        return '#!/bin/sh\n: > '+str(self.dir/'swapped-ran')+'\nexit 7\n'     # marks that the swapped file ran
    def swap(self):
        import os
        tmp=self.dir/'swap.tmp';tmp.write_text(self.swapped_text());tmp.chmod(0o755);os.replace(tmp,self.exe)
    def test_a_kernel_swapped_after_the_hash_is_not_started(self):
        """FR7b-IDENTITY-RULE-01 (owner rule: a replaced file is always refused): the swap renames the directory that holds
        the file and puts another file at the same path. The verified inode is not touched, but at the check point the path
        names another file, so the start is refused ('changed'); the swapped file never runs."""
        import os
        sub=self.dir/'sub';sub.mkdir();exe=sub/'kernel';exe.write_text(self.exe.read_text());exe.chmod(0o755)
        def swap():
            os.rename(sub,self.dir/'old');sub.mkdir();tmp=sub/'kernel';tmp.write_text(self.swapped_text());tmp.chmod(0o755)
        with self.assertRaises(nw.BinaryRefused) as c:self.run_after(swap,path=exe)
        self.assertEqual(c.exception.reason,'changed')
        self.assertTrue(exe.read_text().startswith('#!/bin/sh'))                              # the swap did happen
        self.assertFalse((self.dir/'swapped-ran').exists())
    def test_an_unchanged_kernel_runs_from_its_descriptor(self):
        """FR7b-IDENTITY-RULE-01: the unchanged kernel passes the path identity check and runs from /proc/self/fd/N."""
        from unittest import mock
        real=nk.subprocess.Popen;seen=[]
        def popen(*args,**kwargs):seen.append(kwargs.get('executable'));return real(*args,**kwargs)
        with mock.patch.object(nk.subprocess,'Popen',side_effect=popen):
            got=nk.run_kernel([str(self.exe)],env={},deadline=5.0,on_begin=lambda:None,on_end=lambda:None,sha256=self.good)
        self.assertEqual(got['exit'],0);self.assertEqual(got['summary']['records'],4)
        self.assertEqual(len(seen),1);self.assertRegex(seen[0],r'^/proc/self/fd/[0-9]+$')
    def test_a_kernel_renamed_over_is_refused_with_no_clock_wait(self):
        """FR7b-IDENTITY-RULE-01 (owner rule): a rename over the kernel right after the hash, with no wait for a timestamp
        tick, is refused ('changed') on the first try; the swapped file never runs."""
        with self.assertRaises(nw.BinaryRefused) as c:self.run_after(self.swap)
        self.assertEqual(c.exception.reason,'changed')
        self.assertTrue(self.exe.read_text().startswith('#!/bin/sh'));self.assertFalse((self.dir/'swapped-ran').exists())
    def test_a_kernel_renamed_over_is_refused_when_the_ctime_gives_no_signal(self):
        """FR7b-IDENTITY-RULE-01: the no-tick case made deterministic. The identity without ctime stands for a rename over in
        the same timestamp tick (the ctime of the verified inode does not change); the path identity alone refuses it."""
        from unittest import mock
        with mock.patch.object(nw,'_identity',lambda st:(st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns)):
            with self.assertRaises(nw.BinaryRefused) as c:self.run_after(self.swap)
        self.assertEqual(c.exception.reason,'changed')
        self.assertTrue(self.exe.read_text().startswith('#!/bin/sh'));self.assertFalse((self.dir/'swapped-ran').exists())
    def test_a_kernel_renamed_over_after_a_timestamp_tick_is_refused(self):
        """FR7b-R3 (the bench unit failure of run 471b2b02): a rename over the kernel after the timestamp clock passed its
        ctime changes the ctime of the verified inode, so the start is refused ('changed'); the swapped file never runs."""
        def swap_after_tick():
            wait_for_timestamp_tick(self.exe);self.swap()
        with self.assertRaises(nw.BinaryRefused) as c:self.run_after(swap_after_tick)
        self.assertEqual(c.exception.reason,'changed')
        self.assertTrue(self.exe.read_text().startswith('#!/bin/sh'));self.assertFalse((self.dir/'swapped-ran').exists())
    def test_a_restored_kernel_without_its_digest_is_refused(self):
        """N3b-A02: under SAFE_C_BENCH_NATIVE, a kernel in the restore directory never starts by path."""
        import os
        from unittest import mock
        with mock.patch.dict(os.environ,{'SAFE_C_BENCH_NATIVE':str(self.dir)}),mock.patch.object(nk.subprocess,'Popen',side_effect=AssertionError('started')):
            with self.assertRaises(nw.BinaryRefused) as c:
                nk.run_kernel([str(self.exe)],env={},deadline=5.0,on_begin=lambda:None,on_end=lambda:None)
        self.assertEqual(c.exception.reason,'unverified')
    def test_a_kernel_changed_in_place_or_with_a_wrong_digest_is_refused(self):
        def rewrite():
            with open(self.exe,'a') as f:f.write('\n# changed\n')
        with self.assertRaises(nw.BinaryRefused) as c:self.run_after(rewrite)
        self.assertEqual(c.exception.reason,'changed')
        with self.assertRaises(nw.BinaryRefused) as c:self.run_after(lambda:None,'0'*64)
        self.assertEqual(c.exception.reason,'digest')

if __name__=='__main__':unittest.main()
