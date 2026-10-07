"""Long-lived session containers: restart detection and renewal around long waits.

A host watchdog outside this repository may `docker start` every exited container.
A session holder that expired and came back has an empty /work and must never be
reused; the parent disposes idle sessions before long waits and rebuilds after.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
from evidence import GateError, Runner
import container_policy
import qualification

T0 = '2026-10-06T23:15:27.165863528Z'
RESTARTED = '2026-10-06T23:46:01.896247896Z'
MESSAGE = 'session container stopped or was restarted outside the launcher'


class FakeDocker:
    """Fake daemon: containers keyed by id with State and RestartCount."""
    def __init__(self, clock=None, lifetime=container_policy.HOLDER_SECONDS):
        self.containers, self.commands = {}, []
        self.clock, self.lifetime = clock, lifetime
        self.inspect_fails = False

    def add(self, cid, started=T0, running=True, restarts=0, born=0.0):
        self.containers[cid] = {'Id': cid, 'RestartCount': restarts, 'born': born,
                                'State': {'Running': running, 'Paused': False, 'Restarting': False,
                                          'StartedAt': started, 'Pid': 41 if running else 0}}

    def expire_and_watchdog(self):
        # The holder's sleep ends; the external watchdog starts it again.
        if self.clock is None:return
        for c in self.containers.values():
            if self.clock[0]-c['born'] >= self.lifetime and c['State']['StartedAt'] == T0:
                c['State'].update(StartedAt=RESTARTED, Pid=99, Running=True)

    def __call__(self, args, **kw):
        self.commands.append(list(args))
        self.expire_and_watchdog()
        if args[0] == 'inspect':
            if self.inspect_fails or any(a not in self.containers for a in args[1:]):
                return {'exit_code': 1, 'failure': None, 'output': 'no such container'}
            return {'exit_code': 0, 'failure': None,
                    'output': json.dumps([{k: v for k, v in self.containers[a].items() if k != 'born'} for a in args[1:]])}
        if args[0] == 'kill':
            c = self.containers.get(args[1])
            if c:c['State'].update(Running=False, Pid=0)
            return {'exit_code': 0, 'failure': None, 'output': ''}
        if args[0] == 'rm':
            self.containers.pop(args[-1], None)
            return {'exit_code': 0, 'failure': None, 'output': ''}
        if args[0] == 'exec':
            return {'exit_code': 0, 'failure': None, 'output': 'ok\n', 'evidence_complete': True}
        return {'exit_code': 0, 'failure': None, 'output': ''}


def make_launcher(run_dir, docker):
    launcher = object.__new__(container_policy.Launcher)
    launcher.value = container_policy.policy(ROOT)
    launcher.run_dir = Path(run_dir)
    launcher.runner_identity = None
    launcher.records = []
    launcher.docker = docker
    return launcher


def record(cid, started=T0):
    return {'execution_path': 'docker', 'container_id': cid, 'profile': 'build',
            'plan': {'profile': 'build', 'resources': {'wall_seconds': 900}}, 'policy_hash': 'p',
            'effective': {'inspect': {'state': {'Running': True, 'StartedAt': started, 'Pid': 41}},
                          'cgroup_path': '/nonexistent'},
            'lifecycle': None}


class SessionRestartDetectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.docker = FakeDocker()
        self.launcher = make_launcher(self.temp.name, self.docker)

    def tearDown(self):
        self.temp.cleanup()

    def execs(self):
        return [c for c in self.docker.commands if c[0] == 'exec']

    def test_holder_lifetime_stays_1800_seconds(self):
        self.assertEqual(container_policy.HOLDER_SECONDS, 1800)
        self.assertIn("'import time; time.sleep(1800)'", (ROOT/'tools/container_policy.py').read_text())

    def test_unchanged_running_session_is_reused(self):
        self.docker.add('c1')
        result = self.launcher.execute(record('c1'), ['true'], timeout=10)
        self.assertEqual(result['exit_code'], 0)
        self.assertEqual(len(self.execs()), 1)
        self.assertEqual(self.docker.commands[0][:2], ['inspect', 'c1'])

    def assert_refused(self, rec):
        with self.assertRaises(GateError) as caught:
            self.launcher.execute(rec, ['true'], timeout=10)
        self.assertEqual(str(caught.exception), MESSAGE)
        self.assertEqual(self.execs(), [])

    def test_restarted_session_is_refused(self):
        self.docker.add('c1', started=RESTARTED)
        self.assert_refused(record('c1'))

    def test_stopped_session_is_refused(self):
        self.docker.add('c1', running=False)
        self.assert_refused(record('c1'))

    def test_restart_count_is_refused(self):
        self.docker.add('c1', restarts=1)
        self.assert_refused(record('c1'))

    def test_missing_or_uninspectable_session_is_refused(self):
        self.assert_refused(record('gone'))
        self.docker.add('c2');self.docker.inspect_fails = True
        self.assert_refused(record('c2'))

    def test_session_without_recorded_start_is_refused(self):
        self.docker.add('c1')
        rec = record('c1');rec['effective']['inspect']['state'].pop('StartedAt')
        self.assert_refused(rec)

    def test_refused_session_is_disposed_and_never_reused(self):
        self.docker.add('c1', started=RESTARTED)
        rec = record('c1')
        self.assert_refused(rec)
        self.assertNotIn('c1', self.docker.containers)
        self.assertIsNotNone(rec['lifecycle'])
        with self.assertRaises(GateError):
            self.launcher.execute(rec, ['true'], timeout=10)
        self.assertEqual(self.execs(), [])


class StubRunner(Runner):
    """Real Runner session bookkeeping; start() skips the source snapshot."""
    def __init__(self, launcher, clock):
        self.launcher, self.clock_value = launcher, clock
        self.alive, self.session, self.session_started = False, None, None
        self.counter, self.records, self.input_binding = 0, [], {}
        self.lock = {'image_id': 'sha256:test'}
        self.run_dir = launcher.run_dir

    def clock(self):
        return self.clock_value[0]

    def start(self):
        if self.alive:return
        cid = 'c%d' % (len(self.launcher.docker.containers)+len(self.launcher.records)+1)
        self.launcher.docker.add(cid, born=self.clock_value[0])
        self.session = record(cid);self.launcher.records.append(self.session)
        self.name = cid;self.alive = True;self.session_started = self.clock()


class FakeQRunner:
    def __init__(self):
        self.alive, self.session, self.commands, self.count = False, None, [], 0

    def start(self):
        if self.alive:return
        self.count += 1;self.session = {'container_id': 's%d' % self.count};self.alive = True

    def run(self, args, **kw):
        self.start();self.commands.append(args[:2])
        return {'exit_code': 0, 'failure': None, 'output': ''}

    def fetch(self, relative):
        raise GateError('no compile database in fake')


class SessionRenewalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.now = [0.0]
        self.docker = FakeDocker(clock=self.now)
        self.launcher = make_launcher(self.temp.name, self.docker)
        self.runner = StubRunner(self.launcher, self.now)

    def tearDown(self):
        self.temp.cleanup()

    def exec_into(self):
        self.runner.start()
        return self.launcher.execute(self.runner.session, ['true'], timeout=10)

    def test_long_starter_without_renewal_is_detected(self):
        # Without disposal, a child run longer than the holder lifetime leaves a
        # restarted holder; the launcher refuses it instead of building in an empty /work.
        self.exec_into()
        self.now[0] += 3000
        with self.assertRaises(GateError) as caught:
            self.exec_into()
        self.assertEqual(str(caught.exception), MESSAGE)

    def test_parent_disposes_before_long_wait_and_recreates_after(self):
        self.exec_into()
        first = self.runner.session
        self.runner.refresh(idle=True)          # before the starter's child run
        self.assertFalse(self.runner.alive)
        self.assertIsNotNone(first['lifecycle'])
        self.assertNotIn(first['container_id'], self.docker.containers)
        self.now[0] += 3000                     # child ci longer than the holder lifetime
        result = self.exec_into()
        self.assertEqual(result['exit_code'], 0)
        self.assertNotEqual(self.runner.session['container_id'], first['container_id'])

    def test_aged_session_is_renewed_at_a_gate_boundary(self):
        self.exec_into();first = self.runner.session['container_id']
        self.now[0] += container_policy.HOLDER_SECONDS-700
        self.runner.refresh()
        self.assertTrue(self.runner.alive)
        self.assertEqual(self.runner.session['container_id'], first)
        self.now[0] += 200
        self.runner.refresh()
        self.assertFalse(self.runner.alive)
        self.exec_into()
        self.assertNotEqual(self.runner.session['container_id'], first)

    def test_release_without_session_is_harmless(self):
        self.runner.refresh(idle=True)
        self.assertFalse(self.runner.alive)


class BuildCacheTests(unittest.TestCase):
    def qualifier(self):
        return qualification.Qualifier(ROOT, FakeQRunner())

    def configures(self, q):
        return sum(1 for c in q.runner.commands if c == ['cmake', '-S'])

    def test_build_is_cached_within_one_session(self):
        q = self.qualifier()
        q.build('asan', case='C33');q.build('asan', case='C33')
        self.assertEqual(self.configures(q), 1)

    def test_build_is_redone_in_a_new_session(self):
        q = self.qualifier()
        first = q.build('asan', case='C33')
        q.runner.alive = False                  # session disposed before the starter
        second = q.build('asan', case='C33')
        self.assertEqual(self.configures(q), 2)
        self.assertEqual(first['directory'], second['directory'])
        self.assertEqual(q.build_sessions[second['directory']], 's2')

    def test_executable_refuses_a_build_from_a_disposed_session(self):
        q = self.qualifier()
        build = q.build('asan', case='C33')
        q.runner.alive = False;q.runner.start()
        with self.assertRaises(GateError):
            q.executable(build, 'C33_bad')


if __name__ == '__main__':
    unittest.main()
