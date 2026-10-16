"""Moved from tests/unit/test_bench_controls.py and tests/unit/test_bench_profile.py (Task 19a): these start real child processes
and wait 1 to 2 s, which is over the 0.5 s per-file budget of the toolchain unit gate. They run in the bench unit suite."""
import importlib.util, sys, tempfile, time, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4]
spec=importlib.util.spec_from_file_location('bench_coordinator_marked',ROOT/'container/bench-coordinator.py')
bc=importlib.util.module_from_spec(spec);spec.loader.exec_module(bc)
PYPATH={'PYTHONPATH':str(ROOT/'benchmarks/performance/python')}
CLIENT=("import sys;from benchlab.markers import Marker;m=Marker();m.hello('c1');m.begin('control','c1');"
        "m.end('control','c1',sampled=True,children=3) if sys.argv[1]=='end' else None;m.close();sys.exit(0 if sys.argv[1]=='end' else 4)")

def fake_reader():
    fake_reader.n+=1;n=fake_reader.n
    return {'perf_counter_ns':n*1000,'cpu':{'usage_usec':n*7,'user_usec':n,'system_usec':n,'nr_throttled':0,'throttled_usec':0},
            'memory_current':n*1048576,'unavailable':{}}
fake_reader.n=0

class MarkedRunTests(unittest.TestCase):
    def test_client_exit_without_end_fails_fast_not_at_the_deadline(self):
        d=tempfile.TemporaryDirectory();self.addCleanup(d.cleanup)
        ch=bc.Channel(Path(d.name)/'m.sock',reader=fake_reader);self.addCleanup(ch.close)
        started=time.monotonic();row=bc.run_marked(ch,[sys.executable,'-c',CLIENT,'noend'],'c1',time.monotonic()+20,env=PYPATH)
        self.assertLess(time.monotonic()-started,10)
        # the exact row that tests/unit/test_bench_controls.py evaluates as a control failure
        self.assertEqual(row,{'name':'c1','exit_code':4,'extra':{'errors':[]},'unavailable':{'handshake':'missing begin or end'}})

class RunGroupTests(unittest.TestCase):
    """Task 17 review fix (Minor 7): a child past its deadline is killed with its whole process group (spawned workers included)."""
    def test_timeout_kills_the_process_group(self):
        code=('import subprocess,sys,time;p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"]);'
              'print(p.pid,flush=True);time.sleep(60)')
        start=time.monotonic();r=bc.run_group([sys.executable,'-c',code],timeout=2)
        self.assertTrue(r.timed_out);self.assertLess(time.monotonic()-start,20)
        pid=int(r.stdout.split()[0]);deadline=time.monotonic()+5;state=None
        while time.monotonic()<deadline:
            try:state=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[0]
            except OSError:state=None
            if state in (None,'Z','X'):break
            time.sleep(0.05)
        self.assertIn(state,(None,'Z','X'))                                   # the grandchild did not survive

if __name__=='__main__':unittest.main()
