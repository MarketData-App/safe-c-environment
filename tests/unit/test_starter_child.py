"""Fresh child ci budget and child-container cleanup after a child TIMEOUT."""
import hashlib
import json
import sys
import tempfile
import unittest
from unittest import mock
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
    def test_child_ci_budget_covers_the_bench_gates(self):
        # Phase 1 adds bench-doctor and bench-selftest to the fresh child ci. The
        # child of the laboratory branch (run 86b4c062, 2026-10-08) took 1243 s for the core gates,
        # 1025 s for the bench gates and was still in the project-gates self-test
        # (about 650 s) when the 3000 s budget expired: about 3050 s in total. The
        # budget keeps the earlier margin ratio (3000 s for about 1860 s, x1.6).
        measured_phase_one_child_seconds = 3050
        self.assertGreaterEqual(starter.CHILD_CI_SECONDS, int(1.5*measured_phase_one_child_seconds))
        # Controller ruling D1-R3 (P3-T15-CHILD-BUDGET-01): the Phase 3 child ci with every bench gate took 5216 s
        # (starter verify run c41876a5 at 632e697, Task DD); the budget is at least 1.5 times that.
        measured_phase_three_child_seconds = 5216
        self.assertGreaterEqual(starter.CHILD_CI_SECONDS, int(1.5*measured_phase_three_child_seconds))
        self.assertEqual(starter.CHILD_CI_SECONDS, 8000)
        text = (ROOT/'tools/starter.py').read_text()
        self.assertIn('result=run_child(root,args,CHILD_CI_SECONDS,', text)
        self.assertNotIn('result=run_child(root,args,1200', text)

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

    def test_child_ci_time_is_recorded(self):
        # Task 26 (behavior): verify_starter measures the fresh child ci with time.monotonic around its run_child call,
        # records the integer child_ci_seconds, passes the child's bench runs from before that ci to
        # bench_b18.child_checks, records its result as bench_b18, and a failed child check fails the starter gate.
        import bench_b18
        for b18, want in (('PASS', 'PASS'), ('FAIL', 'FAIL')):
            with self.subTest(bench_b18=b18), tempfile.TemporaryDirectory() as d:
                root, run_dir = Path(d)/'root', Path(d)/'run'
                (root/'safety').mkdir(parents=True)
                run_dir.mkdir()
                (root/'starter.json').write_text(json.dumps({'version': '0'}))
                (root/'safety/fixtures.json').write_text(json.dumps({'cases': []}))
                (root/'safety/contract.json').write_text('{}')
                first = root/'artifacts/instances'/run_dir.name/'first project with space'
                second = root/'artifacts/instances'/run_dir.name/'second-project'

                def instantiate(parent, destination, name, maintenance):
                    if name == 'refused-project':
                        raise GateError('destination must be absent or empty')
                    (Path(destination)/'cmake').mkdir(parents=True)
                    (Path(destination)/'cmake/Safety.cmake').write_text('-Werror')
                    return {'name': name}

                def gate(candidate, parent, identity):
                    if '-Wno-error' in (Path(candidate)/'cmake/Safety.cmake').read_text():
                        raise GateError('protected policy changed')
                    return 'bound'
                calls = []

                def run_child(parent, args, timeout, child, directory, lock, record, what):
                    calls.append((what, timeout))
                    if what == 'fresh child developer selftest':
                        q = first/'artifacts/developer/runs/r1'
                        q.mkdir(parents=True)
                        (q/'qualification.json').write_text('{}')
                        pre = first/'artifacts/bench'/('9'*32)
                        pre.mkdir(parents=True)
                        (pre/'run.json').write_text(json.dumps({'source_identity': 'c'*64}))
                        return {'output': json.dumps({'run_id': 'r1', 'status': 'BLOCKED'}), 'failure': None, 'exit_code': 2}
                    (first/'artifacts/bootstrap-report.json').write_text(json.dumps({'local_state': 'PASS', 'source_identity': 'c'*64}))
                    return {'exit_code': 0, 'failure': None}
                clock = mock.Mock()
                clock.monotonic.side_effect = [1000.0, 4900.9]
                qualifier = mock.Mock()
                qualifier.return_value.qualify_case.return_value = {'status': 'PASS'}
                checked = {'status': b18, 'checks': {}}
                # T26-B18-02: each root has its own source identity (parent, designated child, second child); an unknown
                # root raises, so a swap of parent_identity and child_identity in the child_checks call is detected.
                identities = {root: 'a'*64, first: 'c'*64, second: 'd'*64}
                with mock.patch.multiple(starter, baseline_identity=mock.Mock(return_value='i'*64), package_candidate=mock.Mock(return_value={}),
                                         instantiate=instantiate, instance_files=mock.Mock(return_value=set()),
                                         source_identity=mock.Mock(side_effect=lambda r: (identities[Path(r)], {})), baseline_gate=gate, run_child=run_child,
                                         validate_fresh_report=mock.Mock(side_effect=GateError('copied report')), time=clock), \
                     mock.patch('developer_acceptance.load'), mock.patch('evidence.Runner'), mock.patch('qualification.Qualifier', qualifier), \
                     mock.patch('cli.initial_report', return_value={}), mock.patch.object(bench_b18, 'child_checks', return_value=checked) as cc:
                    got = starter.verify_starter(root, {'image_id': 'x'}, run_dir)
                self.assertEqual(calls, [('fresh child developer selftest', 1200), ('fresh child ci', starter.CHILD_CI_SECONDS)])
                self.assertEqual(got['child_ci_seconds'], 3900)
                self.assertIs(type(got['child_ci_seconds']), int)
                self.assertEqual((got['bench_b18'], got['status']), (checked, want))
                cc.assert_called_once()
                self.assertEqual(cc.call_args.args, (root, first))
                kw = cc.call_args.kwargs
                self.assertEqual((kw['instances'], kw['parent_identity'], kw['child_identity']), ([second], 'a'*64, 'c'*64))
                self.assertEqual([r['run_id'] for r in kw['before_runs']], ['9'*32])


class ReapScopeTests(unittest.TestCase):
    def launcher(self, inventories, removed_ok=True):
        launcher = object.__new__(container_policy.Launcher)
        launcher.commands = []

        def docker(args, **kw):
            launcher.commands.append(list(args))
            if args[0] == 'ps' and any(a.startswith('label='+container_policy.ANCESTOR_LABEL+'.') for a in args):
                return {'exit_code': 0, 'failure': None, 'output': ''}  # no nested-run containers here
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


class NestedRunCleanupTests(unittest.TestCase):
    """A timed-out fresh child leaves the containers of its nested runs (the
    project-gates self-test copies the framework to /tmp and labels its containers
    with that worktree). The child's ancestor label lets the parent reap them;
    another session's containers are never touched."""
    CHILD, NESTED, OTHER = 'a'*64, 'b'*64, 'c'*64

    def records(self):
        return [
            {'id': 'child1', 'labels': {container_policy.LABEL: '1', 'org.safe-c.worktree': self.CHILD}},
            {'id': 'nested1', 'labels': {container_policy.LABEL: '1', 'org.safe-c.worktree': self.NESTED,
                                         container_policy.ANCESTOR_LABEL+'.'+self.CHILD: '1'}},
            {'id': 'other1', 'labels': {container_policy.LABEL: '1', 'org.safe-c.worktree': self.OTHER}},
            {'id': 'other2', 'labels': {container_policy.LABEL: '1', 'org.safe-c.worktree': self.OTHER,
                                        container_policy.ANCESTOR_LABEL+'.'+self.NESTED: '1'}},
        ]

    def launcher(self, records):
        launcher = object.__new__(container_policy.Launcher)
        launcher.commands = []

        def matches(record, args):
            filters = [args[i+1] for i, a in enumerate(args) if a == '--filter']
            for f in filters:
                if not f.startswith('label='):
                    return False
                key, _, value = f[len('label='):].partition('=')
                if key not in record['labels'] or (value and record['labels'][key] != value):
                    return False
            return True

        def docker(args, **kw):
            launcher.commands.append(list(args))
            if args[0] == 'ps':
                return {'exit_code': 0, 'failure': None, 'output': '\n'.join(r['id'] for r in records if matches(r, args))}
            if args[0] == 'rm':
                records[:] = [r for r in records if r['id'] != args[-1]]
            return {'exit_code': 0, 'failure': None, 'output': ''}
        launcher.docker = docker
        return launcher

    def test_nested_run_containers_are_reaped_and_other_sessions_are_not(self):
        records = self.records()
        launcher = self.launcher(records)
        now = [0.0]
        result = launcher.reap_scope(self.CHILD, seconds=20, poll=5, clock=lambda: now[0],
                                     sleep=lambda s: now.__setitem__(0, now[0]+s))
        self.assertEqual(sorted(result['removed']), ['child1', 'nested1'])
        self.assertEqual(result['remaining'], [])
        self.assertEqual(sorted(r['id'] for r in records), ['other1', 'other2'])
        self.assertFalse([c for c in launcher.commands if c[0] in ('kill', 'rm') and c[-1].startswith('other')])

    def test_ancestor_labels_come_only_from_digests(self):
        self.assertEqual(container_policy.ancestor_labels({}), [])
        self.assertEqual(container_policy.ancestor_labels({container_policy.ANCESTOR_ENV: ''}), [])
        env = {container_policy.ANCESTOR_ENV: self.CHILD+','+self.NESTED}
        self.assertEqual(container_policy.ancestor_labels(env),
                         ['--label', container_policy.ANCESTOR_LABEL+'.'+self.CHILD+'=1',
                          '--label', container_policy.ANCESTOR_LABEL+'.'+self.NESTED+'=1'])
        for bad in ('x', self.CHILD+',not-a-digest', ','.join([self.CHILD]*9), self.CHILD.upper()):
            with self.assertRaises(GateError):
                container_policy.ancestor_labels({container_policy.ANCESTOR_ENV: bad})
        text = (ROOT/'tools/container_policy.py').read_text()
        self.assertIn('*ancestor_labels(os.environ)', text)

    def test_child_commands_carry_the_child_scope(self):
        with tempfile.TemporaryDirectory() as d:
            child = Path(d)/'child'
            child.mkdir()
            scope = starter.child_scope(child)
            env = starter.child_env(child, {'PATH': '/bin'})
            self.assertEqual(env[container_policy.ANCESTOR_ENV], scope)
            self.assertEqual(env['PATH'], '/bin')
            nested = starter.child_env(child, {container_policy.ANCESTOR_ENV: self.OTHER})
            self.assertEqual(nested[container_policy.ANCESTOR_ENV], self.OTHER+','+scope)
        text = (ROOT/'tools/starter.py').read_text()
        self.assertIn("developer_result=run_child(root,developer_args,1200,first,run_dir,lock,"
                      "'starter-child-developer-command.opaque.json','fresh child developer selftest')", text)
        self.assertIn("result=run_child(root,args,CHILD_CI_SECONDS,first,run_dir,lock,'starter-child-command.json','fresh child ci')", text)
        self.assertIn('result=bounded(args,timeout=timeout,limit=4*1024*1024,env=child_env(first,tmpdir=scratch))', text)


class ChildScratchTests(unittest.TestCase):
    """A killed fresh child cannot run its own cleanup, so its /tmp scratch (evidence and
    project copies) stayed behind and later BLOCKED disk admission. The child runs with
    TMPDIR set to one recorded directory, which the parent removes by its exact path."""

    def setUp(self):
        self.base = Path(tempfile.mkdtemp())
        patcher = mock.patch.object(tempfile, 'tempdir', str(self.base))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_child_env_sets_tmpdir_to_the_child_scratch(self):
        scratch = self.base/'safe-c-child-tmp-x'
        env = starter.child_env(self.base/'child', {'PATH': '/bin'}, tmpdir=scratch)
        self.assertEqual((env['TMPDIR'], env['PATH']), (str(scratch), '/bin'))
        self.assertNotIn('TMPDIR', starter.child_env(self.base/'child', {'PATH': '/bin'}))

    def test_timeout_removes_the_recorded_child_scratch_only(self):
        run_dir = self.base/'run'
        run_dir.mkdir()
        scratch = starter.child_scratch(run_dir)
        self.assertEqual(scratch.parent, self.base)
        self.assertEqual(json.loads((run_dir/'starter-child-scratch.json').read_text())['paths'], [str(scratch)])
        (scratch/'safe-c-evidence-abc').mkdir()
        (scratch/'safe-c-evidence-abc'/'big.bin').write_bytes(b'x'*1024)
        keep = self.base/'safe-c-evidence-other-session'
        keep.mkdir()
        (keep/'kept.txt').write_text('kept')
        fake = FakeLauncher({'waited_seconds': 0.0, 'removed': [], 'remaining': []})
        with self.assertRaises(GateError):
            starter.child_timeout_cleanup(ROOT, run_dir, {}, self.base/'child', {'failure': 'TIMEOUT'}, 'fresh child ci',
                                          launcher_factory=lambda: fake, scratch=scratch)
        self.assertFalse(scratch.exists())
        self.assertEqual((keep/'kept.txt').read_text(), 'kept')
        saved = json.loads((run_dir/'starter-child-timeout-cleanup.json').read_text())
        self.assertEqual(saved['scratch'], {'path': str(scratch), 'removed': True})

    def test_only_a_recorded_child_scratch_shape_is_removed(self):
        other = self.base/'safe-c-evidence-x'
        other.mkdir()
        nested = self.base/'deeper'/'safe-c-child-tmp-y'
        nested.mkdir(parents=True)
        target = self.base/'target'
        target.mkdir()
        (target/'t.txt').write_text('t')
        link = self.base/'safe-c-child-tmp-link'
        link.symlink_to(target)
        for path in (other, nested, link, Path('/tmp'), self.base):
            with self.subTest(path=str(path)), self.assertRaises(GateError):
                starter.remove_child_scratch(path)
        self.assertTrue(other.is_dir() and nested.is_dir() and (target/'t.txt').exists())
        gone = self.base/'safe-c-child-tmp-gone'
        self.assertEqual(starter.remove_child_scratch(gone), {'path': str(gone), 'removed': True})


if __name__ == '__main__':
    unittest.main()
