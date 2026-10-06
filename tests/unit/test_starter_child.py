"""Fresh child ci budget and child-container cleanup after a child TIMEOUT."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
from evidence import GateError
import container_policy
import starter


class FakeLauncher:
    def __init__(self, cleanup):
        self.cleanup, self.calls, self.closed = cleanup, [], False

    def reap_scope(self, scope, *, seconds):
        self.calls.append((scope, seconds))
        return self.cleanup

    def close(self):
        self.closed = True


class ChildTimeoutTests(unittest.TestCase):
    def test_child_ci_budget_is_3000_seconds(self):
        self.assertEqual(starter.CHILD_CI_SECONDS, 3000)
        text = (ROOT/'tools/starter.py').read_text()
        self.assertIn('result=bounded(args,timeout=CHILD_CI_SECONDS', text)
        self.assertNotIn('result=bounded(args,timeout=1200', text)

    def test_no_cleanup_without_timeout(self):
        for result in ({'failure': None, 'exit_code': 0}, {'failure': 'EXIT', 'exit_code': 1}):
            self.assertIsNone(starter.child_timeout_cleanup(ROOT, ROOT, {}, ROOT, result, 'x',
                                                            launcher_factory=lambda: self.fail('launcher used')))

    def test_timeout_reaps_child_containers_and_raises(self):
        with tempfile.TemporaryDirectory() as d:
            child = Path(d)/'child'
            child.mkdir()
            fake = FakeLauncher({'waited_seconds': 3.0, 'removed': ['c1'], 'remaining': []})
            with self.assertRaises(GateError) as caught:
                starter.child_timeout_cleanup(ROOT, Path(d), {}, child, {'failure': 'TIMEOUT'}, 'fresh child ci',
                                              launcher_factory=lambda: fake)
            self.assertIn('fresh child ci TIMEOUT', str(caught.exception))
            self.assertEqual(fake.calls, [(hashlib.sha256(str(child.resolve()).encode()).hexdigest(), 120)])
            self.assertTrue(fake.closed)
            saved = json.loads((Path(d)/'starter-child-timeout-cleanup.json').read_text())
            self.assertEqual((saved['command'], saved['removed']), ('fresh child ci', ['c1']))


class ReapScopeTests(unittest.TestCase):
    def launcher(self, inventories, removed_ok=True):
        launcher = object.__new__(container_policy.Launcher)
        launcher.commands = []

        def docker(args, **kw):
            launcher.commands.append(list(args))
            if args[0] == 'ps':
                ids = inventories.pop(0) if len(inventories) > 1 else inventories[0]
                return {'exit_code': 0, 'failure': None, 'output': '\n'.join(ids)}
            return {'exit_code': 0 if removed_ok else 1, 'failure': None, 'output': ''}
        launcher.docker = docker
        return launcher

    def clock(self):
        now = [0.0]
        return now, (lambda: now[0]), (lambda s: now.__setitem__(0, now[0]+s))

    def test_disposes_running_and_stopped_child_containers_at_once(self):
        launcher = self.launcher([['a', 'b'], [], [], []])
        now, clock, sleep = self.clock()
        result = launcher.reap_scope('f'*64, seconds=120, poll=5, clock=clock, sleep=sleep)
        self.assertEqual((result['removed'], result['remaining']), (['a', 'b'], []))
        self.assertEqual([c for c in launcher.commands if c[0] in ('kill', 'rm')],
                         [['kill', 'a'], ['rm', '--force', 'a'], ['kill', 'b'], ['rm', '--force', 'b']])
        self.assertIn('label=org.safe-c.worktree='+'f'*64, launcher.commands[0])
        self.assertIn('-aq', launcher.commands[0])
        self.assertLessEqual(now[0], 15)

    def test_a_restarted_container_is_removed_again(self):
        # A container that reappears after removal (an external restart) is removed again.
        launcher = self.launcher([['a'], ['a'], [], [], []])
        _now, clock, sleep = self.clock()
        result = launcher.reap_scope('e'*64, seconds=120, poll=5, clock=clock, sleep=sleep)
        self.assertEqual(result['removed'], ['a'])
        self.assertEqual(sum(1 for c in launcher.commands if c == ['rm', '--force', 'a']), 2)
        self.assertEqual(result['remaining'], [])

    def test_bounded_when_containers_keep_reappearing(self):
        launcher = self.launcher([['a']])
        now, clock, sleep = self.clock()
        result = launcher.reap_scope('d'*64, seconds=20, poll=5, clock=clock, sleep=sleep)
        self.assertEqual(result['remaining'], ['a'])
        self.assertLessEqual(now[0], 25)

    def test_scope_must_be_a_digest(self):
        with self.assertRaises(GateError):
            self.launcher([[]]).reap_scope('not-a-digest')


if __name__ == '__main__':
    unittest.main()
