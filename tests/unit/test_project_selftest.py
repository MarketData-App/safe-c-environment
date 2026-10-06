import fnmatch, hashlib, io, json, shutil, subprocess, sys, tempfile, unittest
from contextlib import redirect_stdout
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'tools'))
from evidence import GateError
import project_check as pc
import project_model as pm
import project_selftest as ps
ROOT = Path(__file__).resolve().parents[2]


def mini_root(base):
    """Fixture set, schemas and the example in a small framework tree."""
    for rel in ('schemas', ps.FIXTURES, 'examples/hello-world'):
        shutil.copytree(ROOT/rel, base/rel)
    (base/'safety/project-policy.json').write_bytes((ROOT/'safety/project-policy.json').read_bytes())
    return base


def rehash(root):
    manifest = json.loads((root/ps.MANIFEST).read_text())
    manifest['files'] = {rel: digest for rel, digest in ps.fixture_files(root).items()}
    (root/ps.MANIFEST).write_text(json.dumps(manifest))


def report(failed=None, *, verdict=None, blockers=(), stopped=None):
    rows = {}
    for name in pc.GATES:
        if failed and name in failed:
            rows[name] = pc.gate_row(name, 'FAIL')
        elif failed:
            rows[name] = pc.gate_row(name, 'BLOCKED', {'reason': 'not run: gate '+failed[0]+' failed'})
        else:
            rows[name] = pc.gate_row(name, 'PASS')
    if failed:
        # Gates that ran before the first failure passed.
        for name in pc.EXECUTION_ORDER[:pc.EXECUTION_ORDER.index(failed[0])]:
            rows[name] = pc.gate_row(name, 'PASS')
    return {'gates': [rows[n] for n in pc.GATES], 'verdict': verdict or ('FAIL' if failed else 'PASS_UNQUALIFIED_FRAMEWORK'),
            'stopped_after': stopped if stopped is not None else (failed[0] if failed else None), 'blockers': list(blockers)}


class ManifestTests(unittest.TestCase):
    def test_repository_fixture_set_covers_every_project_gate(self):
        manifest, fixtures = ps.load_manifest(ROOT)
        self.assertEqual(manifest['gates'], list(pc.GATES))
        self.assertEqual(list(fixtures), list(pc.GATES))
        self.assertTrue(all(fixtures[g] and all(f['gate'] == g for _, f in fixtures[g]) for g in pc.GATES))
        # The ast gate proves its AST API scan, attribute scan and build identity check live.
        self.assertEqual([(d, f.get('check')) for d, f in fixtures['ast']],
                         [('ast', 'api'), ('ast-attribute', 'attributes'), ('ast-identity', 'identity')])
        runs = ps.fixture_runs(fixtures)
        self.assertEqual(len(runs), 25)
        self.assertEqual([g for g, _, _ in ps.fixture_runs(fixtures, ['ast', 'tsan'])], ['ast', 'ast', 'ast', 'tsan'])

    def test_fixture_c_sources_are_in_the_source_inventory(self):
        inventory = json.loads((ROOT/'safety/source-inventory.json').read_text())['files']
        for rel in ps.fixture_files(ROOT):
            if rel.endswith('.c'):
                row = inventory[ps.FIXTURES+'/'+rel]
                self.assertEqual(row['role'], 'qualification-only')
                self.assertEqual(row['sha256'], hashlib.sha256((ROOT/ps.FIXTURES/rel).read_bytes()).hexdigest())

    def test_fixture_files_are_exported_but_not_formatted(self):
        exported = set(json.loads((ROOT/'starter-export.json').read_text())['files'])
        formatted = set(json.loads((ROOT/'safety/source-inventory.json').read_text())['format_files'])
        for rel in list(ps.fixture_files(ROOT)) + ['manifest.json']:
            self.assertIn(ps.FIXTURES+'/'+rel, exported)
            self.assertNotIn(ps.FIXTURES+'/'+rel, formatted)
        for rel in ('tools/project_selftest.py', 'schemas/project-gate-fixtures.json', 'tests/unit/test_project_selftest.py'):
            self.assertIn(rel, exported)

    def test_contract_requires_the_project_gates_row(self):
        self.assertIn('project-gates', json.loads((ROOT/'safety/contract.json').read_text())['required_gates'])

    def check_rejected(self, mutate, text):
        with tempfile.TemporaryDirectory() as d:
            root = mini_root(Path(d))
            mutate(root)
            with self.assertRaises(GateError) as caught:
                ps.load_manifest(root)
            self.assertIn(text, str(caught.exception))

    def test_missing_gate_fixture_is_rejected(self):
        def mutate(root):
            shutil.rmtree(root/ps.FIXTURES/'tsan');rehash(root)
        self.check_rejected(mutate, 'directories differ')

    def test_dropped_gate_in_manifest_is_rejected(self):
        def mutate(root):
            value = json.loads((root/ps.MANIFEST).read_text());value['gates'] = value['gates'][:-1]+['format']
            (root/ps.MANIFEST).write_text(json.dumps(value))
        self.check_rejected(mutate, 'schema')

    def test_reordered_gates_are_rejected(self):
        def mutate(root):
            value = json.loads((root/ps.MANIFEST).read_text());value['gates'][0], value['gates'][1] = value['gates'][1], value['gates'][0]
            (root/ps.MANIFEST).write_text(json.dumps(value))
        self.check_rejected(mutate, '23 project gates')

    def test_changed_fixture_file_is_rejected(self):
        def mutate(root):
            path = root/ps.FIXTURES/'asan/test_seeded.c';path.write_bytes(path.read_bytes()+b'\n')
        self.check_rejected(mutate, 'hash mismatch: asan/test_seeded.c')

    def test_unlisted_fixture_file_is_rejected(self):
        self.check_rejected(lambda root: (root/ps.FIXTURES/'asan/extra.txt').write_text('x'), 'unlisted project gate fixture file')

    def test_missing_pinned_file_is_rejected(self):
        self.check_rejected(lambda root: (root/ps.FIXTURES/'asan/test_seeded.c').unlink(), 'fixture file is missing')

    def test_unused_fixture_file_is_rejected(self):
        def mutate(root):
            (root/ps.FIXTURES/'asan/extra.txt').write_text('x');rehash(root)
        self.check_rejected(mutate, 'not used by its fixture')

    def test_fixture_for_another_gate_is_rejected(self):
        def mutate(root):
            path = root/ps.FIXTURES/'ubsan/fixture.json';value = json.loads(path.read_text());value['gate'] = 'asan'
            path.write_text(json.dumps(value));rehash(root)
        self.check_rejected(mutate, 'names another gate')

    def test_unpinned_operation_source_is_rejected(self):
        def mutate(root):
            path = root/ps.FIXTURES/'ubsan/fixture.json';value = json.loads(path.read_text())
            value['operations'][0]['source'] = 'missing.c';path.write_text(json.dumps(value));rehash(root)
        self.check_rejected(mutate, 'not a pinned file')

    def test_escaping_operation_path_is_rejected(self):
        def mutate(root):
            path = root/ps.FIXTURES/'ubsan/fixture.json';value = json.loads(path.read_text())
            value['operations'][0]['path'] = 'src/../../escape.c';path.write_text(json.dumps(value));rehash(root)
        # The schema pattern rejects it first; apply_fixture repeats the check (ApplyTests).
        self.check_rejected(mutate, 'schema')

    def test_unknown_operation_is_rejected_by_schema(self):
        def mutate(root):
            path = root/ps.FIXTURES/'ubsan/fixture.json';value = json.loads(path.read_text())
            value['operations'][0]['op'] = 'chmod';path.write_text(json.dumps(value));rehash(root)
        self.check_rejected(mutate, 'schema')

    def test_dot_dot_path_is_rejected_by_schema(self):
        for bad in ('src/../escape.c', '../escape.c', 'src/./x.c', 'src//x.c', '.hidden'):
            def mutate(root, bad=bad):
                path = root/ps.FIXTURES/'ubsan/fixture.json';value = json.loads(path.read_text())
                value['operations'][0]['path'] = bad;path.write_text(json.dumps(value));rehash(root)
            with self.subTest(path=bad):
                self.check_rejected(mutate, 'schema')

    def test_fixture_directory_listed_twice_or_unlisted_is_rejected(self):
        def twice(root):
            value = json.loads((root/ps.MANIFEST).read_text());value['fixtures']['tsan'].append('asan')
            (root/ps.MANIFEST).write_text(json.dumps(value))
        self.check_rejected(twice, 'listed twice')
        def unlisted(root):
            value = json.loads((root/ps.MANIFEST).read_text());value['fixtures']['ast'].remove('ast-identity')
            (root/ps.MANIFEST).write_text(json.dumps(value))
        self.check_rejected(unlisted, 'directories differ')
        def missing_gate(root):
            value = json.loads((root/ps.MANIFEST).read_text());del value['fixtures']['tsan']
            (root/ps.MANIFEST).write_text(json.dumps(value))
        self.check_rejected(missing_gate, 'schema')

    def test_second_fixture_for_another_gate_is_rejected(self):
        def mutate(root):
            path = root/ps.FIXTURES/'ast-identity/fixture.json';value = json.loads(path.read_text());value['gate'] = 'tidy'
            path.write_text(json.dumps(value));rehash(root)
        self.check_rejected(mutate, 'names another gate')

    def test_symlinked_fixture_file_is_rejected(self):
        def mutate(root):
            (root/ps.FIXTURES/'asan/link.c').symlink_to(root/ps.FIXTURES/'asan/test_seeded.c')
        self.check_rejected(mutate, 'symlink')


def gitignored(rel, lines):
    """Minimal .gitignore evaluation for the patterns of this repository: last match wins,
    `!` negates, a trailing `/` matches a directory (and so every path below it), a
    pattern with an inner `/` is anchored at the root, `**` matches any depth."""
    parts = rel.split('/')
    candidates = [('/'.join(parts[:i]), i < len(parts)) for i in range(1, len(parts)+1)]
    ignored = False
    for raw in lines:
        line = raw.rstrip('\n')
        if not line.strip() or line.startswith('#'):
            continue
        negate = line.startswith('!')
        pattern = line[1:] if negate else line
        directory = pattern.endswith('/')
        pattern = pattern.rstrip('/')
        anchored = '/' in pattern
        pattern = pattern.lstrip('/')
        for path, is_dir in candidates:
            if directory and not is_dir:
                continue
            name = path if anchored else path.rsplit('/', 1)[-1]
            if fnmatch.fnmatchcase(name, pattern) or (pattern.endswith('/**') and path.startswith(pattern[:-3]+'/')):
                ignored = not negate
                break
    return ignored


class TrackingTests(unittest.TestCase):
    """Every pinned fixture file must be committable: an ignored file is missing from a clean checkout."""

    def fixture_paths(self):
        manifest = json.loads((ROOT/ps.MANIFEST).read_text())
        return [ps.FIXTURES+'/'+rel for rel in manifest['files']] + [ps.MANIFEST]

    def test_no_fixture_file_is_gitignored(self):
        lines = (ROOT/'.gitignore').read_text().splitlines()
        ignored = [rel for rel in self.fixture_paths() if gitignored(rel, lines)]
        self.assertEqual(ignored, [])

    def test_ignore_evaluation_detects_a_directory_rule(self):
        # Without the negation rules, `coverage/` hides the coverage fixture.
        lines = [l for l in (ROOT/'.gitignore').read_text().splitlines() if 'project-gate-fixtures' not in l]
        self.assertTrue(gitignored(ps.FIXTURES+'/coverage/fixture.json', lines))
        self.assertFalse(gitignored(ps.FIXTURES+'/asan/fixture.json', lines))

    @unittest.skipUnless((ROOT/'.git').exists() and shutil.which('git'), 'git checkout unavailable')
    def test_git_does_not_ignore_fixture_files(self):
        result = subprocess.run(['git', '-C', str(ROOT), 'check-ignore', '--no-index', *self.fixture_paths()],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.stdout.split(), [])


class ApplyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.fixture = self.base/'fixture';self.fixture.mkdir()
        (self.fixture/'new.c').write_text('new')
        self.project = self.base/'project'
        shutil.copytree(ROOT/'examples/hello-world', self.project)

    def tearDown(self):
        self.tmp.cleanup()

    def apply(self, *operations):
        ps.apply_fixture(self.fixture, {'operations': list(operations)}, self.project)

    def test_add_replace_and_delete(self):
        self.apply({'op': 'add', 'path': 'tests/project/deep/new.c', 'source': 'new.c'})
        self.assertEqual((self.project/'tests/project/deep/new.c').read_text(), 'new')
        self.apply({'op': 'replace', 'path': 'src/main.c', 'source': 'new.c'})
        self.assertEqual((self.project/'src/main.c').read_text(), 'new')
        self.apply({'op': 'delete', 'path': 'src/main.c'})
        self.assertFalse((self.project/'src/main.c').exists())

    def test_json_operations(self):
        self.apply({'op': 'json_append', 'path': 'project.json', 'pointer': '/modules/0/tests', 'value': 'tests/project/x.c'},
                   {'op': 'json_set', 'path': 'project.json', 'pointer': '/run/args', 'value': []},
                   {'op': 'json_set', 'path': 'review/ledger.json', 'pointer': '/findings/0/state', 'value': 'OPEN'})
        project = json.loads((self.project/'project.json').read_text())
        self.assertEqual(project['modules'][0]['tests'][-1], 'tests/project/x.c')
        self.assertEqual(project['run']['args'], [])
        self.assertEqual(json.loads((self.project/'review/ledger.json').read_text())['findings'][0]['state'], 'OPEN')

    def test_invalid_operations_are_rejected(self):
        bad = [{'op': 'add', 'path': 'src/main.c', 'source': 'new.c'},
               {'op': 'replace', 'path': 'src/missing.c', 'source': 'new.c'},
               {'op': 'delete', 'path': 'src/missing.c'},
               {'op': 'add', 'path': '../escape.c', 'source': 'new.c'},
               {'op': 'add', 'path': 'src/x.c', 'source': '../new.c'},
               {'op': 'json_set', 'path': 'project.json', 'pointer': '/run/missing', 'value': 1},
               {'op': 'json_set', 'path': 'project.json', 'pointer': '/modules/7/name', 'value': 'x'},
               {'op': 'json_append', 'path': 'project.json', 'pointer': '/run/program', 'value': 'x'},
               {'op': 'json_set', 'path': 'project.json', 'pointer': 'run', 'value': 1},
               {'op': 'chmod', 'path': 'project.json'}]
        for operation in bad:
            with self.subTest(operation=operation), self.assertRaises(GateError):
                self.apply(operation)

    def test_symlinked_target_is_rejected(self):
        (self.project/'src/link.c').symlink_to(self.project/'src/main.c')
        with self.assertRaises(GateError):
            self.apply({'op': 'replace', 'path': 'src/link.c', 'source': 'new.c'})

    def test_every_repository_fixture_applies_to_the_example(self):
        _, fixtures = ps.load_manifest(ROOT)
        for gate, name, fixture in ps.fixture_runs(fixtures):
            with self.subTest(fixture=name), tempfile.TemporaryDirectory() as d:
                project = Path(d)/'p'
                shutil.copytree(ROOT/'examples/hello-world', project)
                ps.apply_fixture(ROOT/ps.FIXTURES/name, fixture, project)
                value = pm.load_project(Path(d), 'p', framework_root=ROOT)
                if gate == 'inventory':
                    with self.assertRaises(GateError):
                        pm.project_inventory(Path(d), 'p', value, framework_root=ROOT)
                else:
                    pm.project_inventory(Path(d), 'p', value, framework_root=ROOT)


class EvaluationTests(unittest.TestCase):
    def test_exact_target_failure_passes(self):
        for gate in pc.GATES:
            with self.subTest(gate=gate):
                result = ps.evaluate_fixture(gate, report([gate]))
                self.assertEqual(result['status'], 'PASS', result)
                self.assertEqual(result['first_fail'], gate)

    def test_other_gate_failure_fails(self):
        result = ps.evaluate_fixture('asan', report(['tidy']))
        self.assertEqual((result['status'], result['first_fail']), ('FAIL', 'tidy'))

    def test_two_failures_fail(self):
        value = report(['asan'])
        value['gates'][pc.GATES.index('tsan')] = pc.gate_row('tsan', 'FAIL')
        self.assertEqual(ps.evaluate_fixture('asan', value)['status'], 'FAIL')

    def test_no_failure_fails(self):
        self.assertEqual(ps.evaluate_fixture('asan', report())['status'], 'FAIL')

    def test_stop_at_another_gate_fails(self):
        self.assertEqual(ps.evaluate_fixture('asan', report(['asan'], stopped='tidy'))['status'], 'FAIL')

    def test_passing_gate_after_target_fails(self):
        # The run must stop at the target: a later gate that ran and passed is not a stop.
        value = report(['asan'])
        value['gates'][pc.GATES.index('tsan')] = pc.gate_row('tsan', 'BLOCKED', {'reason': 'not run: gate tidy failed'})
        value['gates'][pc.GATES.index('tidy')] = pc.gate_row('tidy', 'FAIL')
        self.assertEqual(ps.evaluate_fixture('asan', value)['status'], 'FAIL')

    def test_earlier_gate_not_run_fails(self):
        # ubsan runs before asan: an asan failure with ubsan not run is not the asan stop.
        value = report(['asan'])
        value['gates'][pc.GATES.index('ubsan')] = pc.gate_row('ubsan', 'BLOCKED', {'reason': 'not run: gate asan failed'})
        result = ps.evaluate_fixture('asan', value)
        self.assertEqual(result['status'], 'FAIL')
        self.assertEqual(result['not_passed_earlier'], ['ubsan'])

    def test_unit_failure_may_skip_remaining_test_builds(self):
        value = report(['unit'])
        for name in ('gcc-O2', 'clang-O0', 'clang-O2', 'hardened'):
            value['gates'][pc.GATES.index(name)] = pc.gate_row(name, 'BLOCKED', {'reason': 'not run: gate unit failed'})
        self.assertEqual(ps.evaluate_fixture('unit', value)['status'], 'PASS')
        self.assertEqual(ps.evaluate_fixture('integration', report(['integration']))['status'], 'PASS')
        # After the test builds, unit must have passed before a sanitizer gate fails.
        value = report(['ubsan'])
        value['gates'][pc.GATES.index('unit')] = pc.gate_row('unit', 'BLOCKED', {'reason': 'not run: gate ubsan failed'})
        self.assertEqual(ps.evaluate_fixture('ubsan', value)['status'], 'FAIL')

    def test_named_check_must_fail(self):
        value = report(['ast'])
        value['gates'][pc.GATES.index('ast')] = pc.gate_row('ast', 'FAIL', {'failed_checks': ['api']})
        self.assertEqual(ps.evaluate_fixture('ast', value, 'api')['status'], 'PASS')
        result = ps.evaluate_fixture('ast', value, 'identity')
        self.assertEqual((result['status'], result['failed_checks'], result['check']), ('FAIL', ['api'], 'identity'))
        self.assertEqual(ps.evaluate_fixture('ast', report(['ast']), 'identity')['status'], 'FAIL')

    def test_infrastructure_block_is_blocked(self):
        value = report(verdict='BLOCKED', blockers=['InfrastructureError: docker'])
        self.assertEqual(ps.evaluate_fixture('asan', value)['status'], 'BLOCKED')

    def test_clean_evaluation(self):
        self.assertEqual(ps.evaluate_clean(report())['status'], 'PASS')
        self.assertEqual(ps.evaluate_clean(report(verdict='PASS'))['status'], 'PASS')
        self.assertEqual(ps.evaluate_clean(report(['tidy']))['status'], 'FAIL')
        self.assertEqual(ps.evaluate_clean(report(verdict='BLOCKED', blockers=['x']))['status'], 'BLOCKED')
        # Every gate passed but container cleanup reported a blocker: BLOCKED, not FAIL.
        self.assertEqual(ps.evaluate_clean(dict(report(), blockers=['container cleanup: x']))['status'], 'BLOCKED')
        runtime = dict(report(), verdict='FAIL')
        self.assertEqual(ps.evaluate_clean(runtime)['status'], 'FAIL')

    def test_non_target_gate_blocked_by_infrastructure_is_blocked(self):
        value = report(['asan'])
        value['gates'][pc.GATES.index('format')] = pc.gate_row('format', 'BLOCKED', {'reason': 'infrastructure'})
        self.assertEqual(ps.evaluate_fixture('asan', value)['status'], 'BLOCKED')
        # A non-target gate that failed or was skipped for another gate stays FAIL.
        value['gates'][pc.GATES.index('tsan')] = pc.gate_row('tsan', 'FAIL')
        self.assertEqual(ps.evaluate_fixture('asan', value)['status'], 'FAIL')


class SelftestTests(unittest.TestCase):
    def run_selftest(self, outcomes, **kw):
        calls = []

        def runner(framework, base, *, development):
            self.assertTrue(development)
            self.assertTrue((Path(framework)/base/'project.json').is_file())
            project = json.loads((Path(framework)/base/'project.json').read_text())
            calls.append(project)
            return outcomes(len(calls)-1)
        with tempfile.TemporaryDirectory() as d:
            root = mini_root(Path(d))
            with redirect_stdout(io.StringIO()):
                row = ps.project_selftest(root, runner=runner, **kw)
            self.assertTrue((root/ps.SELFTEST_ARTIFACTS/row['details']['run']/'project-gates.json').is_file())
        return row, calls

    def runs(self):
        return ps.fixture_runs(ps.load_manifest(ROOT)[1])

    def outcome(self, runs, i):
        """The report a correct project check gives for run i (0 is the clean example)."""
        if i == 0:
            return report()
        gate, _, fixture = runs[i-1]
        value = report([gate])
        if fixture.get('check'):
            value['gates'][pc.GATES.index(gate)] = pc.gate_row(gate, 'FAIL', {'failed_checks': [fixture['check']]})
        return value

    def test_all_fixtures_exact_passes(self):
        runs = self.runs()
        row, calls = self.run_selftest(lambda i: self.outcome(runs, i))
        self.assertEqual(row['name'], 'project-gates')
        self.assertEqual(row['status'], 'PASS', row)
        self.assertEqual(len(calls), 1+len(runs))
        self.assertEqual([(f['gate'], f['fixture']) for f in row['details']['fixtures']], [(g, n) for g, n, _ in runs])
        self.assertTrue(all(set(f) >= {'gate', 'fixture', 'status', 'first_fail', 'verdict'} for f in row['details']['fixtures']))
        self.assertEqual(row['details']['clean']['verdict'], 'PASS_UNQUALIFIED_FRAMEWORK')
        # The fixture was applied to the scratch copy: integration drops the run arguments.
        self.assertEqual(calls[1+[n for _, n, _ in runs].index('integration')]['run']['args'], [])
        self.assertEqual(calls[0]['run']['args'], ['world'])
        # Every ast fixture added its own test to the scratch project.
        ast_calls = [calls[1+k] for k, (g, _, _) in enumerate(runs) if g == 'ast']
        self.assertEqual(len({c['modules'][0]['tests'][-1] for c in ast_calls}), 3)

    def test_missing_named_check_fails(self):
        runs = self.runs()
        row, _ = self.run_selftest(lambda i: report() if i == 0 else report([runs[i-1][0]]))
        self.assertEqual(row['status'], 'FAIL')
        self.assertEqual(sorted(f['fixture'] for f in row['details']['fixtures'] if f['status'] == 'FAIL'),
                         ['ast', 'ast-attribute', 'ast-identity'])

    def test_aggregate_requires_every_fixture(self):
        clean = {'status': 'PASS'}
        rows = [{'gate': g, 'fixture': g, 'status': 'PASS'} for g in pc.GATES]
        self.assertEqual(ps.aggregate(clean, rows)['status'], 'PASS')
        expected = [(g, n) for g, n, _ in self.runs()]
        self.assertEqual(ps.aggregate(clean, rows, expected=expected)['status'], 'FAIL')

    def test_failing_clean_example_blocks_fixtures_and_fails(self):
        row, calls = self.run_selftest(lambda i: report(['tidy']))
        self.assertEqual(row['status'], 'FAIL')
        self.assertEqual(len(calls), 1)
        self.assertTrue(all(f['status'] == 'BLOCKED' for f in row['details']['fixtures']))

    def test_wrong_gate_fails(self):
        row, _ = self.run_selftest(lambda i: report() if i == 0 else report(['format']))
        self.assertEqual(row['status'], 'FAIL')
        self.assertEqual([f['gate'] for f in row['details']['fixtures'] if f['status'] == 'PASS'], ['format'])

    def test_partial_run_never_passes(self):
        row, calls = self.run_selftest(lambda i: report() if i == 0 else report(['asan']), gates=['asan'])
        self.assertEqual((row['status'], len(calls)), ('BLOCKED', 2))

    def test_runner_exception_is_blocked(self):
        def outcomes(i):
            if i == 0:
                return report()
            raise GateError('infrastructure')
        row, _ = self.run_selftest(outcomes)
        self.assertEqual(row['status'], 'BLOCKED')

    def test_invalid_manifest_fails_without_runs(self):
        with tempfile.TemporaryDirectory() as d:
            root = mini_root(Path(d))
            (root/ps.FIXTURES/'asan/test_seeded.c').write_text('changed')
            row = ps.project_selftest(root, runner=lambda *a, **k: self.fail('runner called'))
        self.assertEqual(row['status'], 'FAIL')
        self.assertIn('hash mismatch', row['details']['reason'])


if __name__ == '__main__':
    unittest.main()
