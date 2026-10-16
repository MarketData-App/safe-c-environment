import os, struct, sys, time, unittest
from unittest import mock
from pathlib import Path
from benchlab import native_worker as nw
STUB=[sys.executable,'-I',str(Path(__file__).with_name('stub_worker.py'))]

def worker(mode,deadline=5.0):return nw.NativeWorker(STUB+[mode],env={},deadline=deadline)

class NativeWorkerTests(unittest.TestCase):
    def test_header_round_trip_and_checks(self):
        h=nw.encode_header(nw.REQUEST,nw.request_id(7,1),2,4,7,128)
        self.assertEqual(len(h),28);d=nw.decode_header(h);self.assertEqual((d['request_id'],d['selector_mask']),((7<<32)|1,7))
        for data,name in ((b'XCPL'+h[4:],'BAD_MAGIC'),(h[:4]+struct.pack('<H',1)+h[6:],'BAD_VERSION'),(h[:27],'PROTOCOL_TRUNCATED'),
                          (h[:4]+struct.pack('<H',1)+h[6:26],'PROTOCOL_TRUNCATED'),                     # a 26-byte version-1 frame at EOF
                          (nw.encode_header(nw.REQUEST,1,14337,0,7,14337*64),'RECORD_LIMIT'),(nw.encode_header(nw.REQUEST,1,1,5,7,64),'BAD_THREADS'),
                          (nw.encode_header(nw.REQUEST,1,1,0,0,64),'BAD_SELECTOR'),(nw.encode_header(nw.REQUEST,1,1,0,32,64),'BAD_SELECTOR'),
                          (nw.encode_header(nw.RESPONSE,1,0,0,0,4),'BAD_SELECTOR'),(nw.encode_header(nw.ERROR,1,0,0,7,4),'RESERVED_NONZERO'),
                          (nw.encode_header(nw.SHUTDOWN,1,0,0,7,0),'RESERVED_NONZERO'),
                          (nw.encode_header(9,1,0,0,7,0),'BAD_TYPE'),(nw.encode_header(nw.REQUEST,1,1,0,7,2**32-1),'FRAME_LIMIT')):
            with self.subTest(name=name):
                with self.assertRaises(nw.FrameError) as c:nw.decode_header(data)
                self.assertEqual(c.exception.name,name)
    def test_framework_values(self):
        self.assertEqual((nw.MAGIC,nw.VERSION,nw.HEADER.format,nw.HEADER.size),(b'SCPL',2,'<4sHHQIHHI',28))
        self.assertEqual((nw.REQUEST,nw.RESPONSE,nw.ERROR,nw.SHUTDOWN,nw.SHM_REQUEST,nw.SHM_RESPONSE),(1,2,3,4,5,6))
        self.assertEqual(nw.ERROR_NAMES,{1:'BAD_MAGIC',2:'BAD_VERSION',3:'BAD_TYPE',4:'RECORD_LIMIT',5:'FRAME_LIMIT',6:'LENGTH_MISMATCH',
                                         7:'PROTOCOL_TRUNCATED',8:'BAD_THREADS',9:'KERNEL_FAILURE',10:'IO_ERROR',11:'RESERVED_NONZERO',12:'BAD_SELECTOR'})
        self.assertEqual((nw.MAX_RECORDS,nw.MAX_FRAME,nw.MAX_THREADS,nw.STDERR_CAP,nw.SHUTDOWN_WAIT),(14336,4194304,4,65536,2.0))
        self.assertEqual(nw.LAST_STATS,{})
    def test_exact_bounds_and_the_check_order(self):
        for data in (nw.encode_header(nw.REQUEST,1,14336,4,31,64),nw.encode_header(nw.SHM_REQUEST,1,0,0,1,32),
                     nw.encode_header(nw.REQUEST,1,1,0,1,nw.MAX_FRAME-28),nw.encode_header(nw.SHUTDOWN,1,0,0,0,0),nw.encode_header(nw.ERROR,1,0,0,0,4)):
            with self.subTest(data=data[:8]):nw.decode_header(data)
        for data,name in ((nw.encode_header(nw.REQUEST,1,1,0,1,nw.MAX_FRAME-27),'FRAME_LIMIT'),(nw.encode_header(nw.ERROR,1,0,0,0,5),'LENGTH_MISMATCH'),
                          (nw.encode_header(nw.SHUTDOWN,1,0,0,0,1),'LENGTH_MISMATCH'),(nw.encode_header(nw.SHUTDOWN,1,1,0,0,0),'LENGTH_MISMATCH'),
                          (nw.encode_header(0,1,0,0,0,0),'BAD_TYPE'),(nw.encode_header(nw.SHM_RESPONSE,1,0,0,32,8),'BAD_SELECTOR'),
                          (nw.encode_header(nw.REQUEST,1,14337,5,0,2**32-1),'RECORD_LIMIT'),(nw.encode_header(nw.REQUEST,1,1,5,0,2**32-1),'BAD_THREADS'),
                          (nw.encode_header(nw.REQUEST,1,1,0,0,2**32-1),'BAD_SELECTOR'),(b'XCPL'+struct.pack('<H',1)+bytes(22),'BAD_MAGIC')):
            with self.subTest(name=name):
                with self.assertRaises(nw.FrameError) as c:nw.decode_header(data)
                self.assertEqual(c.exception.name,name)
        with self.assertRaises(ValueError):nw.encode_header(nw.REQUEST,2**64,0,0,1,0)
        with self.assertRaises(ValueError):nw.request_id(2**32,0)
        self.assertEqual(nw.request_id(2**32-1,2**32-1),2**64-1)
    def test_exchange_and_shutdown(self):
        with worker('echo') as w:
            w.start();head,payload=w.exchange(nw.REQUEST,nw.request_id(1,0),1,0,8,b'x'*64,lambda h:64)
            self.assertEqual((head['type'],head['request_id'],head['selector_mask'],payload),(nw.RESPONSE,1<<32,8,b'x'*64))
            self.assertEqual(w.shutdown(),0);self.assertFalse(w.alive())
            self.assertGreaterEqual(w.copied_bytes,2*(28+64))
    def test_a_large_opaque_payload_round_trips(self):
        data=bytes(range(256))*4096                                                       # 1 MiB: more than one pipe buffer
        with worker('echo') as w:
            w.start();head,payload=w.exchange(nw.REQUEST,1,2,0,31,data,lambda h:len(data))
            self.assertEqual((head['count'],payload),(2,data));self.assertEqual(w.shutdown(),0)
    def test_expected_length_must_match(self):
        w=worker('echo');w.start()
        with self.assertRaises(nw.FrameError) as c:w.exchange(nw.REQUEST,1,1,0,1,b'abc',lambda h:4)
        self.assertEqual(c.exception.name,'LENGTH_MISMATCH');self.assertFalse(w.alive())
    def test_response_mask_must_match(self):
        w=worker('mask');w.start()
        with self.assertRaises(nw.FrameError) as c:w.exchange(nw.REQUEST,1,0,0,1,b'',lambda h:0)
        self.assertEqual(c.exception.name,'SELECTOR_MISMATCH');w.kill();self.assertFalse(w.alive())
    def test_deadline_kills_and_reaps(self):
        w=worker('sleep',deadline=0.5);w.start();t=time.monotonic()
        with self.assertRaises(nw.FrameError) as c:w.exchange(nw.REQUEST,1,0,0,7,b'',lambda h:0)
        self.assertEqual(c.exception.name,'DEADLINE');self.assertLess(time.monotonic()-t,0.5+nw.SHUTDOWN_WAIT+1.0);self.assertFalse(w.alive())
    def test_truncated_frame(self):
        w=worker('truncate');w.start()
        with self.assertRaises(nw.FrameError) as c:w.exchange(nw.REQUEST,1,0,0,7,b'',lambda h:0)
        self.assertEqual(c.exception.name,'PROTOCOL_TRUNCATED');self.assertFalse(w.alive())
    def test_garbage_exit_and_error_frames(self):
        for mode,name in (('garbage','BAD_MAGIC'),('exit','WORKER_EXITED'),('error','KERNEL_FAILURE')):
            with self.subTest(mode=mode):
                w=worker(mode);w.start()
                with self.assertRaises(nw.FrameError) as c:w.exchange(nw.REQUEST,1,0,0,7,b'',lambda h:0)
                self.assertEqual(c.exception.name,name);w.kill();self.assertFalse(w.alive())
    def test_an_unknown_error_code_has_its_own_name(self):         # N3-A02: not BAD_TYPE
        for mode in ('error-unknown','error-zero'):
            with self.subTest(mode=mode):
                w=worker(mode);w.start()
                with self.assertRaises(nw.FrameError) as c:w.exchange(nw.REQUEST,1,0,0,7,b'',lambda h:0)
                self.assertEqual(c.exception.name,'UNKNOWN_ERROR');self.assertFalse(w.alive())
    def test_an_expect_that_raises_kills_and_reaps_the_worker(self):   # N3-A02
        def expect(head):raise RuntimeError('codec')
        w=worker('echo');self.addCleanup(w.kill);w.start()
        with self.assertRaisesRegex(RuntimeError,'codec'):w.exchange(nw.REQUEST,1,1,0,1,b'x'*8,expect)
        self.assertFalse(w.alive());self.assertIsNotNone(w.proc.returncode)
        self.assertTrue(w.proc.stdin.closed and w.proc.stdout.closed)
    def test_exchange_refuses_a_bad_request_before_writing(self):
        with worker('echo') as w:
            w.start()
            for args in ((nw.RESPONSE,1,0,0,1,b''),(nw.REQUEST,1,0,0,0,b''),(nw.REQUEST,1,14337,0,1,b''),(nw.SHUTDOWN,1,0,0,0,b'')):
                with self.subTest(args=args[:5]),self.assertRaises(ValueError):w.exchange(*args,lambda h:0)
            self.assertEqual(w.copied_bytes,0);self.assertEqual(w.shutdown(),0)
    def test_not_started_and_kill_are_safe(self):
        w=worker('echo');self.assertFalse(w.alive())
        with self.assertRaises(nw.FrameError) as c:w.exchange(nw.REQUEST,1,0,0,1,b'',lambda h:0)
        self.assertEqual(c.exception.name,'WORKER_EXITED');w.kill();w.kill()
        self.assertIsNone(w.shutdown())
    def test_stderr_is_capped(self):
        w=nw.NativeWorker([sys.executable,'-I','-c','import sys;sys.stderr.write("e"*200000);sys.stdin.read()'],env={},deadline=2.0)
        w.start();w.shutdown();self.assertEqual(w.stderr_bytes,200000);self.assertLessEqual(len(w.stderr_head),nw.STDERR_CAP)
    def test_a_worker_that_ignores_shutdown_is_killed_after_the_wait(self):
        w=nw.NativeWorker([sys.executable,'-I','-c','import time;time.sleep(3600)'],env={},deadline=2.0)
        w.start();t=time.monotonic();code=w.shutdown()
        self.assertLess(code,0);self.assertLess(time.monotonic()-t,nw.SHUTDOWN_WAIT+1.5);self.assertFalse(w.alive())

def exec_dir():
    """A directory whose files may be executed: the job work directory in the bench container (its /tmp is noexec)."""
    import os
    return '/work' if os.path.isdir('/work') and os.access('/work',os.W_OK|os.X_OK) else None

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

class VerifiedStartTests(unittest.TestCase):
    """N3-A01: with the restored sha256, start() opens the binary once, hashes it through that descriptor and starts the
    worker from /proc/self/fd/N of the same descriptor, so a file swapped between the hash and the start is not run."""
    def setUp(self):
        import hashlib, shutil, stat, tempfile
        d=Path(tempfile.mkdtemp(dir=exec_dir()));self.addCleanup(shutil.rmtree,d,True);self.dir=d
        self.exe=d/'peer';text=Path(__file__).with_name('stub_worker.py').read_text()
        self.exe.write_text('#!'+sys.executable+' -I\n'+text);self.exe.chmod(0o755)
        self.good=hashlib.sha256(self.exe.read_bytes()).hexdigest()
    def popen_after(self,change):
        """subprocess.Popen of native_worker, with a hook that changes the file at the binary path just before the start."""
        real=nw.subprocess.Popen
        def popen(*args,**kwargs):change();return real(*args,**kwargs)
        return mock.patch.object(nw.subprocess,'Popen',side_effect=popen)
    def swap(self):
        tmp=self.dir/'swap.tmp';tmp.write_text('#!/bin/sh\nexit 7\n');tmp.chmod(0o755);os.replace(tmp,self.exe)
    def rewrite(self):
        with open(self.exe,'a') as f:f.write('\n# changed\n')
    def test_a_binary_swapped_after_the_hash_is_not_started(self):
        """FR7b-IDENTITY-RULE-01 (owner rule: a replaced file is always refused): the swap renames the directory that holds
        the file and puts another file at the same path. The verified inode is not touched, but at the check point the path
        names another file, so start() refuses ('changed') and reaps the started process. FR12-A01: the swapped file never
        runs: the process that Popen started (exec is complete when Popen returns) runs the interpreter of the verified peer,
        not /bin/sh of the swapped file, and the swapped file writes no marker."""
        sub=self.dir/'sub';sub.mkdir();exe=sub/'peer';exe.write_text(self.exe.read_text());exe.chmod(0o755)
        def swap():
            os.rename(sub,self.dir/'old');sub.mkdir();tmp=sub/'peer'
            tmp.write_text('#!/bin/sh\n: > '+str(self.dir/'swapped-ran')+'\nexit 7\n');tmp.chmod(0o755)
        real=nw.subprocess.Popen;images=[]
        def popen(*args,**kwargs):
            swap();proc=real(*args,**kwargs)
            try:images.append(os.readlink(f'/proc/{proc.pid}/exe'))
            except OSError as exc:images.append(type(exc).__name__)
            return proc
        w=nw.NativeWorker([str(exe),'echo'],env={},deadline=5.0,sha256=self.good);self.addCleanup(w.kill)
        with mock.patch.object(nw.subprocess,'Popen',side_effect=popen),self.assertRaises(nw.BinaryRefused) as c:w.start()
        self.assertEqual(c.exception.reason,'changed');self.assertFalse(w.alive())
        self.assertTrue(exe.read_text().startswith('#!/bin/sh'))                   # the swap did happen
        self.assertEqual(images,[os.path.realpath(sys.executable)])                # the verified peer started, not the swapped file
        self.assertFalse((self.dir/'swapped-ran').exists())
    def test_an_unchanged_binary_starts_and_answers(self):
        """FR7b-IDENTITY-RULE-01: the unchanged binary passes the path identity check; the verified peer answers."""
        with nw.NativeWorker([str(self.exe),'echo'],env={},deadline=5.0,sha256=self.good) as w:
            w.start()
            _,payload=w.exchange(nw.REQUEST,1,1,0,1,b'y'*16,lambda h:16)
            self.assertEqual(payload,b'y'*16);self.assertEqual(w.shutdown(),0)
    def test_a_binary_renamed_over_is_refused_with_no_clock_wait(self):
        """FR7b-IDENTITY-RULE-01 (owner rule): a rename over the binary right after the hash, with no wait for a timestamp
        tick, is refused ('changed') on the first try, and the started process is reaped."""
        w=nw.NativeWorker([str(self.exe),'echo'],env={},deadline=5.0,sha256=self.good);self.addCleanup(w.kill)
        with self.popen_after(self.swap),self.assertRaises(nw.BinaryRefused) as c:w.start()
        self.assertEqual(c.exception.reason,'changed');self.assertFalse(w.alive())
        self.assertTrue(self.exe.read_text().startswith('#!/bin/sh'))
    def test_a_binary_renamed_over_is_refused_when_the_ctime_gives_no_signal(self):
        """FR7b-IDENTITY-RULE-01: the no-tick case made deterministic. The identity without ctime stands for a rename over in
        the same timestamp tick (the ctime of the verified inode does not change); the path identity alone refuses it."""
        w=nw.NativeWorker([str(self.exe),'echo'],env={},deadline=5.0,sha256=self.good);self.addCleanup(w.kill)
        with mock.patch.object(nw,'_identity',lambda st:(st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns)):
            with self.popen_after(self.swap),self.assertRaises(nw.BinaryRefused) as c:w.start()
        self.assertEqual(c.exception.reason,'changed');self.assertFalse(w.alive())
        self.assertTrue(self.exe.read_text().startswith('#!/bin/sh'))
    def test_a_binary_renamed_over_after_a_timestamp_tick_is_refused_and_reaped(self):
        """FR7b-R3: a rename over the binary after the timestamp clock passed its ctime changes the ctime of the verified
        inode, so start() refuses ('changed') and reaps the started process."""
        def swap_after_tick():
            wait_for_timestamp_tick(self.exe);self.swap()
        w=nw.NativeWorker([str(self.exe),'echo'],env={},deadline=5.0,sha256=self.good)
        with self.popen_after(swap_after_tick),self.assertRaises(nw.BinaryRefused) as c:w.start()
        self.assertEqual(c.exception.reason,'changed');self.assertFalse(w.alive())
        self.assertTrue(self.exe.read_text().startswith('#!/bin/sh'))
    def test_a_start_by_path_runs_the_swapped_file(self):
        """The pre-N3-A01 behaviour, kept for an unverified start (sha256=None): the path is resolved at exec time, so the
        swapped file runs (here it exits at once)."""
        with self.popen_after(self.swap),nw.NativeWorker([str(self.exe),'echo'],env={},deadline=5.0) as w:
            w.start()
            with self.assertRaises(nw.FrameError) as c:w.exchange(nw.REQUEST,1,1,0,1,b'y'*16,lambda h:16)
            self.assertEqual(c.exception.name,'WORKER_EXITED')       # the verified peer would echo
    def test_a_binary_changed_in_place_after_the_hash_is_refused_and_reaped(self):
        w=nw.NativeWorker([str(self.exe),'echo'],env={},deadline=5.0,sha256=self.good)
        with self.popen_after(self.rewrite),self.assertRaises(nw.BinaryRefused) as c:w.start()
        self.assertEqual(c.exception.reason,'changed');self.assertFalse(w.alive())
    def test_a_wrong_digest_a_symlink_or_a_non_regular_file_starts_nothing(self):
        link=self.dir/'link';link.symlink_to(self.exe);fifo=self.dir/'fifo';os.mkfifo(fifo)
        for path,digest,reason in ((self.exe,'0'*64,'digest'),(self.exe,'A'*64,'digest'),(link,self.good,'symlink'),(fifo,self.good,'not a regular file'),
                                   (self.dir,self.good,'not a regular file'),(self.dir/'absent',self.good,'missing')):
            with self.subTest(path=path.name,reason=reason):
                w=nw.NativeWorker([str(path),'echo'],env={},deadline=5.0,sha256=digest)
                with mock.patch.object(nw.subprocess,'Popen',side_effect=AssertionError('started')),self.assertRaises(nw.BinaryRefused) as c:w.start()
                self.assertEqual(c.exception.reason,reason);self.assertIsNone(w.proc)
    def test_a_restored_binary_without_its_digest_is_refused(self):
        """N3b-A02: under SAFE_C_BENCH_NATIVE, a start by path (sha256=None) of a file in the restore directory is refused
        before any process starts; a path outside it keeps the unverified start (framework tests with Python peers)."""
        link=self.dir/'alias';link.symlink_to(self.exe)
        with mock.patch.dict(os.environ,{'SAFE_C_BENCH_NATIVE':str(self.dir)}):
            for path in (self.exe,link):
                with self.subTest(path=path.name):
                    w=nw.NativeWorker([str(path),'echo'],env={},deadline=5.0)
                    with mock.patch.object(nw.subprocess,'Popen',side_effect=AssertionError('started')),self.assertRaises(nw.BinaryRefused) as c:w.start()
                    self.assertEqual(c.exception.reason,'unverified');self.assertIsNone(w.proc)
            with worker('echo') as w:                     # the stub peer lies outside the restore directory
                w.start();self.assertEqual(w.shutdown(),0)
    def test_restored_gives_the_path_and_the_digest_of_one_directory(self):
        """N3b-A02: the path and the digest of a restored binary come from the same SAFE_C_BENCH_NATIVE directory."""
        import json
        (self.dir/'sha256.json').write_text(json.dumps({'peer':self.good}))
        with mock.patch.dict(os.environ,{'SAFE_C_BENCH_NATIVE':str(self.dir)}):
            path,digest=nw.restored('peer')
        self.assertEqual((path,digest),(self.dir/'peer',self.good))
    def test_the_descriptor_is_closed_in_the_caller_after_the_start(self):
        seen=[]
        real=nw.subprocess.Popen
        def popen(*args,**kwargs):seen.append(kwargs);return real(*args,**kwargs)
        with mock.patch.object(nw.subprocess,'Popen',side_effect=popen),nw.NativeWorker([str(self.exe),'echo'],env={},deadline=5.0,sha256=self.good) as w:
            w.start();self.assertEqual(w.shutdown(),0)
        exe=seen[0]['executable'];self.assertRegex(exe,r'^/proc/self/fd/[0-9]+$')
        self.assertIn(int(exe.rsplit('/',1)[1]),seen[0]['pass_fds'])
        with self.assertRaises(OSError):os.fstat(int(exe.rsplit('/',1)[1]))

class TrialHookTests(unittest.TestCase):
    def test_native_fields_come_from_last_stats_and_python_rows_get_none(self):
        from benchlab import trial
        self.assertEqual(trial.native_fields('py-reference','stdio','x'),{})
        nw.LAST_STATS.clear();nw.LAST_STATS.update(copied_bytes=92,load_process={'pid':1,'role':'caller'},chunk_rule='r',chunks=2,chunk_sizes=[1,1],chunk_wall_ns=[3,4])
        try:
            self.assertEqual(trial.native_fields('c-serial','inproc','in-process'),{'route':'inproc','route_label':'in-process','copied_bytes':92,'load_process':{'pid':1,'role':'caller'}})
            self.assertEqual(trial.native_fields('c-threads','shm',None)['pool'],{'chunk_rule':'r','chunks':2,'chunk_sizes':[1,1],'chunk_wall_ns':[3,4]})
            nw.LAST_STATS.clear()
            self.assertEqual(trial.native_fields('c-serial','stdio',None),{'route':'stdio','route_label':None,'copied_bytes':None,'load_process':None})
        finally:nw.LAST_STATS.clear()
    def panel_notes(self,variant,panel):
        """The notes of one panel trial of trial.main, with a stand-in marker, adapter and run_panel."""
        import json, tempfile
        from benchlab import trial
        notes={}
        class Marker:
            def __init__(self,*a,**k):self.commands=[{'op':'call','trial':'t0','panel':{'indices':[0],'cells':['c0'],'reference_status':['OK'],'passes':1}},{'op':'shutdown'}]
            def hello(self,client):pass
            def begin(self,*a):pass
            def end(self,*a,**k):pass
            def note(self,name,**fields):notes[name]=fields
            def close(self):pass
            def command(self):return self.commands.pop(0)
        class Adapter:
            route=None
            def load(self,d):return 'data'
        with tempfile.NamedTemporaryFile('w',suffix='.json',delete=False) as f:json.dump({},f)
        self.addCleanup(os.unlink,f.name)
        with mock.patch.object(trial,'Marker',Marker),mock.patch.object(trial,'load_case_adapter',lambda case,selector:Adapter()),\
             mock.patch.object(trial,'run_panel',panel),mock.patch.object(trial.pools,'verify_session_end',lambda:None):
            code=trial.main(['--client','x','--case-manifest',f.name,'--variant',variant,'--mode','warm','--dataset','d','--sha256','0'*64,
                             '--reference','none','--panel','--route','stdio','--route-label','pipe'])
        self.assertEqual(code,0);return notes['t0']
    def native_events(self,variant,mode,with_hooks=True):
        """The marker events and adapter calls of one call and a shutdown of trial.main (Task 19 hooks)."""
        import json, tempfile
        from benchlab import trial
        events=[]
        class Marker:
            def __init__(self,*a,**k):self.commands=[{'op':'call','trial':'t0','size':1},{'op':'shutdown'}]
            def hello(self,client):pass
            def begin(self,phase,name):events.append(('begin',phase,name))
            def end(self,phase,name,**k):events.append(('end',phase,name))
            def note(self,name,**fields):events.append(('note',name))
            def close(self):pass
            def command(self):return self.commands.pop(0)
        class Adapter:
            route=None
            def load(self,d):return [1]
            def slice(self,c,n):return c
            def prepare(self,c,v,w):events.append(('prepare',));return c
            def run(self,p,v,w,pool=None):events.append(('run',));return p
            def materialize(self,raw):return raw
            def work_units(self,r):return 1
            def digest(self,r):return '0'*64
            def validate(self,r,ref,data):return {'eligible':True,'failures':{}}
        if with_hooks:
            Adapter.native_start=lambda self,v,w:events.append(('native_start',v,w))
            Adapter.native_stop=lambda self,v,w:events.append(('native_stop',v,w))
        with tempfile.NamedTemporaryFile('w',suffix='.json',delete=False) as f:json.dump({},f)
        self.addCleanup(os.unlink,f.name)
        with mock.patch.object(trial,'Marker',Marker),mock.patch.object(trial,'load_case_adapter',lambda case,selector:Adapter()),\
             mock.patch.object(trial.pools,'verify_session_end',lambda:None):
            code=trial.main(['--client','x','--case-manifest',f.name,'--variant',variant,'--mode',mode,'--dataset','d','--sha256','0'*64,
                             '--reference','none','--route','stdio','--route-label','pipe'])
        self.assertEqual(code,0);return [e for e in events if e!=('note','identity:x')]      # the identity note comes first
    def test_a_warm_c_row_starts_its_worker_before_the_first_interval(self):     # Task 19 hook
        ev=self.native_events('c-serial','warm')
        self.assertEqual(ev[:3],[('begin','pool_start','startup:x'),('native_start','c-serial',1),('end','pool_start','startup:x')])
        self.assertLess(ev.index(('native_start','c-serial',1)),ev.index(('begin','caller','t0')))
        self.assertEqual([e for e in ev if e[0]=='native_stop'],[('native_stop','c-serial',1)])           # once, at shutdown
        self.assertGreater(ev.index(('native_stop','c-serial',1)),ev.index(('begin','teardown','teardown:x')))
    def test_a_cold_c_row_stops_its_worker_after_each_call_outside_the_interval(self):   # Task 19 hook
        ev=self.native_events('c-serial','cold')
        self.assertNotIn(('begin','pool_start','startup:x'),ev)
        stop=ev.index(('native_stop','c-serial',1))
        self.assertEqual(ev[stop-1:stop+2],[('begin','teardown','t0:teardown'),('native_stop','c-serial',1),('end','teardown','t0:teardown')])
        self.assertGreater(stop,ev.index(('end','caller','t0')));self.assertLess(stop,ev.index(('note','t0')))
    def test_python_rows_and_adapters_without_hooks_are_unchanged(self):
        ev=self.native_events('py-reference','warm')
        self.assertFalse([e for e in ev if e[0].startswith('native') or e[1:2]==('pool_start',)])
        ev=self.native_events('c-serial','warm',with_hooks=False)
        self.assertEqual(ev[:2],[('begin','pool_start','startup:x'),('end','pool_start','startup:x')])     # the startup handshake still runs
    def test_a_panel_note_carries_the_native_fields(self):          # N3-A03: as in the non-panel path
        def panel(*args):
            nw.LAST_STATS.update(copied_bytes=56,load_process={'pid':7,'role':'caller'})
            return {'panel_walls':{'c0':[5]},'work_units':1,'result_sha256':'0'*64,'panel_status_diff':[],'detail':None,'eligible':True,'failures':{},'reduction':'NOT_RUN'}
        def failing(*args):
            nw.LAST_STATS.update(copied_bytes=12);raise RuntimeError('panel')
        try:
            note=self.panel_notes('c-serial',panel)
            self.assertEqual({k:note.get(k) for k in ('route','route_label','copied_bytes','load_process')},
                             {'route':'stdio','route_label':'pipe','copied_bytes':56,'load_process':{'pid':7,'role':'caller'}})
            self.assertEqual((note['work_units'],note['eligible']),(1,True))
            note=self.panel_notes('c-serial',failing)
            self.assertEqual((note['route'],note['route_label'],note['copied_bytes'],note['eligible']),('stdio','pipe',12,False))
            note=self.panel_notes('py-reference',panel)
            self.assertFalse({'route','route_label','copied_bytes','load_process'}&set(note))
        finally:nw.LAST_STATS.clear()

if __name__=='__main__':unittest.main()
