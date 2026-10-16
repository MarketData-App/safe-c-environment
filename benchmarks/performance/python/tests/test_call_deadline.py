"""Amendment G2.6 (Task 1): the coordinator's call-deadline kill. The first version of this test (bare os.killpg, then
pgrep -g) failed in the bench unit suite: a killed child's descendants are orphaned to the container init, which never reaps
them, so they can stay in the group as zombies. The coordinator's kill_group kills the group and reaps the child and every
orphaned member (it is a child subreaper during the reap). The check reads /proc, zombies included."""
import importlib.util, os, signal, subprocess, sys, time, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4]
spec=importlib.util.spec_from_file_location('bench_coordinator_deadline',ROOT/'container/bench-coordinator.py')
bc=importlib.util.module_from_spec(spec);spec.loader.exec_module(bc)

class ProcessGroupKillTests(unittest.TestCase):
    def test_killpg_reaps_the_child_and_its_descendants(self):
        p=subprocess.Popen([sys.executable,'-c','import subprocess,sys,time;subprocess.Popen([sys.executable,"-c","import time;time.sleep(600)"]);time.sleep(600)'],start_new_session=True)
        deadline=time.monotonic()+10
        while len(bc.group_members(p.pid))<2 and time.monotonic()<deadline:time.sleep(0.05)
        self.assertEqual(len(bc.group_members(p.pid)),2)              # control: the child and its grandchild lead and share the group
        left=bc.kill_group(p)
        self.assertEqual(p.returncode,-signal.SIGKILL)
        self.assertEqual(left,0);self.assertEqual(bc.group_members(p.pid),[])          # zombies included: nothing of the group remains
    def test_run_deadline_raises_the_declared_reason(self):
        started=time.monotonic()
        with self.assertRaises(bc.DeadlineKilled) as caught:
            bc.run_deadline([sys.executable,'-c','import time;time.sleep(600)'],{'call_deadline_seconds':0.5,'call_deadline_reason':'control-hang'},60,dict(os.environ),capture=True)
        self.assertEqual(caught.exception.reason,'control-hang');self.assertLess(time.monotonic()-started,10)
    def test_run_deadline_without_a_deadline_is_a_plain_run(self):
        r=bc.run_deadline([sys.executable,'-c','print(7)'],{},60,dict(os.environ),capture=True)
        self.assertEqual((r.returncode,r.stdout.strip()),(0,'7'))

if __name__=='__main__':unittest.main()
