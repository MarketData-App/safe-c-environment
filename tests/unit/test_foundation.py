"""Evaluator regression tests; executed only through the protected runner."""
import copy
from pathlib import Path
import sys
import shutil
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from evidence import GateError, read_json
from foundation import fixture_inventory, validate_report, ordinary_gate, functional_gate, sdk_gate, input_gate
from policy import export_inventory
from evidence import atomic_json

ROOT = Path(__file__).resolve().parents[2]


def blocked_report():
    spec = fixture_inventory(ROOT)
    return {'schema_version': 1, 'status': 'BLOCKED', 'binding': {'source': 'a' * 64},
            'allocation_profile': 'glib-fail-stop', 'cases': [
                {'id': r['id'], 'status': 'BLOCKED', 'detector': r['detector'],
                 'bad': 'BLOCKED', 'control': 'BLOCKED', 'evidence_paths': [], 'observations': {},
                 'subchecks': [{'name': s, 'status': 'BLOCKED', 'control': 'BLOCKED', 'evidence_paths': []}
                              for s in r['subchecks']]} for r in spec['cases']],
            'profiles': [], 'coverage': {'status': 'BLOCKED'}, 'fuzz': {'status': 'BLOCKED'},
            'runtime': {'status': 'BLOCKED'}, 'sabotage': [
                {'parent': r['parent'], 'name': r['name'] + '/' + variant,
                 'status': 'BLOCKED', 'control': 'BLOCKED', 'evidence_paths': []}
                for r in spec['pipeline_subcases'] for variant in r['variants']],
            'application_release_ready': False, 'application_coverage': 'NOT_APPLICABLE',
            'independent_enforcement': 'UNSEALED'}


class FoundationReportTests(unittest.TestCase):
    def reject(self, change):
        report = blocked_report()
        change(report)
        with self.assertRaises(GateError):
            validate_report(ROOT, report, {'source': 'a' * 64})

    def test_scoped_report_records_unexecuted_requirements(self):
        report = blocked_report()
        self.assertTrue(validate_report(ROOT, report, report['binding']))

    def test_missing_and_duplicate_F_rows(self):
        self.reject(lambda r: r['cases'].pop())
        self.reject(lambda r: r['cases'].__setitem__(1, copy.deepcopy(r['cases'][0])))

    def test_missing_duplicate_subchecks_and_controls(self):
        self.reject(lambda r: r['cases'][0]['subchecks'].pop())
        self.reject(lambda r: r['cases'][0]['subchecks'].__setitem__(1, copy.deepcopy(r['cases'][0]['subchecks'][0])))
        self.reject(lambda r: r['cases'][0].pop('control'))

    def test_status_types_are_strict(self):
        self.reject(lambda r: r['cases'][0].update(status=True))
        self.reject(lambda r: r['cases'][0]['subchecks'][0].update(control=1))
        self.reject(lambda r: r['sabotage'][0].update(status='NOT_APPLICABLE'))

    def test_pass_requires_executed_controls_and_evidence(self):
        self.reject(lambda r: r['cases'][0].update(status='PASS', bad='PASS', control='PASS'))
        self.reject(lambda r: r['sabotage'][0].update(status='PASS', control='PASS'))
        self.reject(lambda r: r.update(status='PASS'))

    def test_dependency_runner_and_instance_binding_is_exact(self):
        for key in ['source', 'dependency', 'runner', 'instance', 'image']:
            self.reject(lambda r, k=key: r['binding'].update({k: 'b' * 64}))

    def test_pipeline_inventory_and_profile_duplicates(self):
        self.reject(lambda r: r['sabotage'].pop())
        self.reject(lambda r: r['sabotage'].__setitem__(1, copy.deepcopy(r['sabotage'][0])))
        self.reject(lambda r: r.update(profiles=[{'name': 'asan', 'status': 'BLOCKED'}] * 2))

    def test_declared_coverage_does_not_replace_denominator(self):
        self.reject(lambda r: r.update(coverage={'status': 'PASS', 'denominator': [],
            'totals': {'lines': {'count': 1, 'covered': 1}, 'branches': {'count': 1, 'covered': 1}}}))


class FoundationClassifierTests(unittest.TestCase):
    def test_export_preflight_requires_the_foundation_build_helper(self):
        manifest = read_json(ROOT / 'starter-export.json')
        manifest['files'] = sorted(set(manifest['files']) | {'cmake/Foundation.cmake'})
        # Copy the complete retained developer payload within bounded build
        # scratch; /tmp remains the separate fixed 64 MiB no-exec area.
        with tempfile.TemporaryDirectory(dir='/work') as temporary:
            candidate = Path(temporary)
            for relative in manifest['files']:
                target = candidate / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, target)
            atomic_json(candidate / 'starter-export.json', manifest)
            self.assertIn('cmake/Foundation.cmake', export_inventory(candidate))
            manifest['files'].remove('cmake/Foundation.cmake')
            atomic_json(candidate / 'starter-export.json', manifest)
            with self.assertRaisesRegex(GateError, 'foundation .* export missing'):
                export_inventory(candidate)

    def test_missing_locked_notice_is_an_explicit_preflight_rejection(self):
        lock = read_json(ROOT / 'foundation.lock.json')
        adaptation = read_json(ROOT / 'container/glib-test-compat.json')
        files = {'foundation.lock.json', 'safety/foundation-api-policy.json',
                 'schemas/foundation-lock.json', 'schemas/foundation-api-policy.json',
                 lock['recipe'], 'container/glib-test-compat.json', adaptation['adapter'], adaptation['patch']}
        files.update(row['path'] for row in lock['inputs'])
        files.update(lock['notices'])
        with tempfile.TemporaryDirectory() as temporary:
            candidate = Path(temporary)
            for relative in files:
                target = candidate / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, target)
            self.assertEqual(input_gate(candidate, artifacts=False)['status'], 'PASS')
            (candidate / next(iter(lock['notices']))).unlink()
            with self.assertRaisesRegex(GateError, 'foundation required input unavailable'):
                input_gate(candidate, artifacts=False)

    def result(self, **changes):
        value = {'exit_code': 0, 'failure': None, 'evidence_complete': True,
                 'binary_unchanged': True, 'output': ''}
        value.update(changes)
        return value

    def test_normal_success_does_not_mask_diagnostics(self):
        ordinary_gate(self.result())
        for changes in [{'exit_code': 134}, {'failure': 'CONTAINER_OOM'},
                        {'failure': 'TIMEOUT'}, {'evidence_complete': False},
                        {'binary_unchanged': False}, {'output': 'GLib-CRITICAL: test diagnostic'},
                        {'output': 'CONTRACT_FAILED F05/empty-index\n'}]:
            with self.assertRaises(GateError):
                ordinary_gate(self.result(**changes))

    def test_functional_failure_requires_the_exact_property(self):
        result = self.result(exit_code=1, output='CONTRACT_FAILED F05/empty-index\n')
        functional_gate(result, 'F05/empty-index')
        with self.assertRaises(GateError):
            functional_gate(result, 'F05/one-past-logical')
        with self.assertRaises(GateError):
            functional_gate(self.result(exit_code=1), 'F05/empty-index')

    def test_sdk_same_version_does_not_replace_exact_bytes(self):
        observed = {name: copy.deepcopy(row['files']) for name, row in
                    read_json(ROOT / 'foundation.lock.json')['profiles'].items()}
        sdk_gate(ROOT, observed)
        changed = copy.deepcopy(observed)
        changed['msan']['lib/libglib-2.0.so.0'] = '0' * 64
        with self.assertRaises(GateError):
            sdk_gate(ROOT, changed)
        changed = copy.deepcopy(observed)
        changed['msan'].pop('lib/glib-2.0/include/glibconfig.h')
        with self.assertRaises(GateError):
            sdk_gate(ROOT, changed)


class FoundationProjectionReadyTests(unittest.TestCase):
    def test_doctor_report_is_not_projected(self):
        from cli import foundation_projection_ready
        self.assertFalse(foundation_projection_ready({'cases': [], 'profiles': [], 'sabotage': [], 'doctor': {'status': 'PASS'}}))
        self.assertFalse(foundation_projection_ready({}))

    def test_checked_report_is_projected(self):
        from cli import foundation_projection_ready
        self.assertTrue(foundation_projection_ready({'cases': [], 'profiles': [], 'sabotage': [], 'doctor': {'status': 'PASS'},
                                                     'policy': {'status': 'PASS'}}))
        self.assertFalse(foundation_projection_ready({'policy': {'status': 'PASS'}}))



class ParallelCoverageTests(unittest.TestCase):
    def test_parallel_coverage_needs_both_files_and_thresholds(self):
        import foundation
        want=['foundation/parallel/sc-parallel.c','foundation/parallel/sc-parallel.h']
        data=[{'files':[{'filename':'/src/'+want[0],'summary':{'lines':{'count':100,'covered':95},'branches':{'count':40,'covered':35}}},
                        {'filename':'/src/'+want[1],'summary':{'lines':{'count':0,'covered':0},'branches':{'count':0,'covered':0}}}]}]
        files,totals,ok=foundation._coverage_totals(data,want)
        self.assertTrue(ok);self.assertEqual(len(files),2)
        data[0]['files'][0]['summary']['branches']['covered']=30
        self.assertFalse(foundation._coverage_totals(data,want)[2])
        data[0]['files'][0]['summary']['branches']['covered']=35
        self.assertFalse(foundation._coverage_totals([{'files':data[0]['files'][:1]}],want)[2])   # the header is missing
        self.assertEqual(foundation.PARALLEL_DENOMINATOR,want)

    def test_parallel_coverage_refuses_empty_data_and_zero_counts(self):
        import foundation
        want=foundation.PARALLEL_DENOMINATOR
        files,totals,ok=foundation._coverage_totals([],want)
        self.assertFalse(ok);self.assertEqual(files,[]);self.assertEqual(totals['lines']['percent'],0)
        zero={'lines':{'count':0,'covered':0},'branches':{'count':0,'covered':0}}
        data=[{'files':[{'filename':'/src/'+w,'summary':copy.deepcopy(zero)} for w in want]}]
        self.assertFalse(foundation._coverage_totals(data,want)[2])           # both files present, nothing counted
        data[0]['files'][0]['summary']['lines']={'count':10,'covered':10}
        self.assertFalse(foundation._coverage_totals(data,want)[2])           # lines only: zero branches still fail
        self.assertEqual(foundation.PARALLEL_GROUPS,{'config','execution','admission','errors','trace','nesting','race'})


class ParallelQualificationTests(unittest.TestCase):
    def test_parallel_mutant_inventory_is_bound_to_its_recipe(self):
        import hashlib, json
        d=json.loads((ROOT/'safety/parallel-mutants.json').read_text())
        self.assertEqual(hashlib.sha256((ROOT/d['recipe']).read_bytes()).hexdigest(),d['recipe_sha256'])
        self.assertEqual({m['lane'] for m in d['mutants'].values()},{'tsan','asan','functional'})

    def test_parallel_fault_names(self):
        import foundation
        self.assertEqual(foundation.PARALLEL_FAULTS,{'create','incomplete','push-after-queue'})
        self.assertEqual(foundation.MUTANT_RUNS,3)   # detection on every run, never by chance

    def test_parallel_report_key_is_optional_and_counted_only_when_present(self):
        from foundation_report import selftest_statuses
        report = blocked_report()
        self.assertNotIn('parallel', read_json(ROOT / 'schemas/foundation-report.json')['required'])
        self.assertTrue(validate_report(ROOT, report, report['binding']))   # a check run has no key
        self.assertEqual(selftest_statuses(report), [])
        report['parallel'] = {'status': 'FAIL', 'faults': {'status': 'FAIL'}, 'mutants': []}
        self.assertTrue(validate_report(ROOT, report, report['binding']))   # a selftest run has the key
        self.assertEqual(selftest_statuses(report), ['FAIL'])
        report['parallel'] = 'PASS'
        with self.assertRaises(GateError):
            validate_report(ROOT, report, report['binding'])

    def test_selftest_report_without_parallel_is_blocked(self):
        from foundation_report import selftest_statuses
        report = blocked_report()
        report['functional'] = {'status': 'PASS'}                         # a selftest or ci report
        self.assertEqual(selftest_statuses(report), ['BLOCKED'])
        report['parallel'] = {'status': 'PASS', 'faults': {'status': 'PASS'}, 'mutants': []}
        self.assertEqual(selftest_statuses(report), ['PASS'])

    def test_fault_variant_and_mutant_are_never_combined(self):
        from types import SimpleNamespace
        from qualification import Qualifier
        stub = SimpleNamespace(root=ROOT)
        with self.assertRaises(GateError):
            Qualifier.build(stub, 'ordinary', parallel_faults=True, parallel_mutant='plain-stop-read')
        with self.assertRaises(GateError):
            Qualifier.build(stub, 'strict', parallel_faults=True)            # ordinary static link only
        with self.assertRaises(GateError):
            Qualifier.build(stub, 'tsan', parallel_mutant='not-inventoried')

    def test_top_level_report_embeds_the_optional_parallel_key(self):
        import jsonschema
        branch = read_json(ROOT / 'schemas/report.json')['properties']['foundation']['anyOf'][0]
        self.assertNotIn('parallel', branch['required'])
        report = blocked_report()
        jsonschema.Draft202012Validator(branch).validate(report)            # a check run has no key
        report['parallel'] = {'status': 'PASS', 'faults': {'status': 'PASS'}, 'mutants': []}
        jsonschema.Draft202012Validator(branch).validate(report)            # a selftest or ci run has it
        report['parallel'] = 'PASS'
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.Draft202012Validator(branch).validate(report)


MUTEX_FATAL = 'g_mutex_clear() called on uninitialised or locked mutex\n'


class FakeParallelQualifier:
    """Drives foundation.parallel_checks without a container: every build succeeds except the fault variant (BLOCKED,
    not under test here); the negative runs of each mutant return the recorded outcomes of `runs`, the controls pass."""
    def __init__(self, runs):
        self.root = ROOT
        self.runs = runs

    def build(self, profile, compiler=None, parallel_faults=False, parallel_mutant=None):
        return {'configure': None, 'build': None, 'links': None, 'faults': parallel_faults,
                'parallel_mutation': parallel_mutant}

    def built(self, build):
        return not build['faults']

    def executable(self, build, name, label):
        import foundation
        prefix = 'foundation-parallel-mutant-'
        if label.startswith(prefix):
            mutant, run = label[len(prefix):].rsplit('-', 1)
            exit_code, output, failure = self.runs[mutant][int(run) - 1]
            return {'exit_code': exit_code, 'output': output, 'failure': failure, 'evidence_path': label}
        output = ''.join('PARALLEL_PASS ' + g + '\n' for g in sorted(foundation.PARALLEL_GROUPS))
        return {'exit_code': 0, 'output': output, 'failure': None, 'evidence_path': label}


class ParallelMutantDetectionTests(unittest.TestCase):
    """P2-MUTANT-TEARDOWN-FLAKY-01 (Task F1 ruling): a negative run of no-wait-teardown also counts as detected when the
    same defect ends it by the GLib fatal abort of g_mutex_clear (exit 134, the exact message) before AddressSanitizer
    reports. A passing run, an unrelated failure and the message under another status still count as not detected.
    Fix round 1 (F1-POLICY-01, F1-ASANLANE-01): the rule is the policy's `also_detected`; the row also needs at least
    `min_expected_runs` runs with the inventoried text; a malformed definition or an unknown key BLOCKS (GateError)."""
    ASAN = (22, '==1==ERROR: AddressSanitizer: stack-use-after-return\n', None)
    TSAN = (66, 'WARNING: ThreadSanitizer: data race\n', None)
    FUNC = (1, 'PARALLEL_FAIL errors\n', None)

    GLIB = (134, MUTEX_FATAL, None)

    def rows(self, teardown, stop=None, definitions=None):
        import contextlib, io, foundation
        from unittest import mock
        runs = {'plain-stop-read': stop or [self.TSAN] * 3, 'no-wait-teardown': teardown,
                'accounting-skip': [self.FUNC] * 3}
        real = read_json(ROOT / 'safety/parallel-mutants.json')
        policy = real if definitions is None else dict(real, mutants=definitions(copy.deepcopy(real['mutants'])))
        with contextlib.redirect_stdout(io.StringIO()), \
                mock.patch.object(foundation, 'read_json', side_effect=lambda p: policy if str(p).endswith('parallel-mutants.json') else read_json(p)):
            report = foundation.parallel_checks(FakeParallelQualifier(runs))
        return {r['id']: r for r in report['mutants']}

    def test_the_policy_declares_the_teardown_rule(self):
        # F1-POLICY-01: the alternate outcome lives in the protected inventory, not in a code constant
        import foundation
        d = read_json(ROOT / 'safety/parallel-mutants.json')
        self.assertEqual(d['mutants']['no-wait-teardown'], {
            'lane': 'asan', 'expected': 'AddressSanitizer',
            'also_detected': {'exit_code': 134, 'line': 'g_mutex_clear() called on uninitialised or locked mutex'},
            'min_expected_runs': 1})
        self.assertEqual({k for k, m in d['mutants'].items() if 'also_detected' in m or 'min_expected_runs' in m}, {'no-wait-teardown'})
        self.assertFalse(hasattr(foundation, 'PARALLEL_MUTANT_FATAL'))

    def test_recorded_glib_mutex_abort_counts_as_detected(self):
        # run 16401ba6, evidence 0389: exit 134, failure None, output exactly the GLib message, no AddressSanitizer text
        row = self.rows([self.ASAN, self.GLIB, self.ASAN])['no-wait-teardown']
        self.assertEqual((row['detected_runs'], row['bad'], row['control'], row['status']), (3, 'PASS', 'PASS', 'PASS'))
        row = self.rows([self.GLIB, self.ASAN, self.GLIB])['no-wait-teardown']      # 1 ASan + 2 GLib
        self.assertEqual((row['detected_runs'], row['bad'], row['status']), (3, 'PASS', 'PASS'))

    def test_the_asan_lane_needs_at_least_one_asan_report(self):
        # F1-ASANLANE-01: 3 of 3 GLib aborts prove nothing about the ASan profile
        row = self.rows([self.GLIB] * 3)['no-wait-teardown']
        self.assertEqual((row['detected_runs'], row['bad'], row['status']), (3, 'FAIL', 'FAIL'))
        row = self.rows([self.GLIB, self.ASAN, self.ASAN],
                        definitions=lambda m: (m['no-wait-teardown'].update(min_expected_runs=3), m)[1])['no-wait-teardown']
        self.assertEqual((row['detected_runs'], row['expected_runs'], row['bad']), (3, 2, 'FAIL'))
        row = self.rows([self.GLIB, self.ASAN, self.ASAN],
                        definitions=lambda m: (m['no-wait-teardown'].update(min_expected_runs=2), m)[1])['no-wait-teardown']
        self.assertEqual((row['detected_runs'], row['expected_runs'], row['bad']), (3, 2, 'PASS'))

    def test_a_mutant_without_also_detected_keeps_the_text_rule(self):
        def drop(m):
            m['no-wait-teardown'].pop('also_detected', None)
            m['no-wait-teardown'].pop('min_expected_runs', None)
            return m
        row = self.rows([self.ASAN, self.GLIB, self.ASAN], definitions=drop)['no-wait-teardown']
        self.assertEqual((row['detected_runs'], row['bad'], row['status']), (2, 'FAIL', 'FAIL'))
        row = self.rows([self.ASAN] * 3, definitions=drop)['no-wait-teardown']
        self.assertEqual((row['detected_runs'], row['bad']), (3, 'PASS'))

    def test_a_malformed_definition_blocks(self):
        line = MUTEX_FATAL.rstrip('\n')
        bad_also = [None, [], 'x', {}, {'exit_code': 134}, {'line': line}, {'exit_code': True, 'line': line},
                    {'exit_code': False, 'line': line}, {'exit_code': '134', 'line': line}, {'exit_code': 134.0, 'line': line},
                    {'exit_code': 134, 'line': ''}, {'exit_code': 134, 'line': 7}, {'exit_code': 134, 'line': line, 'extra': 1}]
        for also in bad_also:
            with self.subTest(also_detected=also):
                with self.assertRaises(GateError):
                    self.rows([self.ASAN] * 3, definitions=lambda m, a=also: (m['no-wait-teardown'].update(also_detected=a), m)[1])
        for runs in [0, -1, 4, True, '1', 1.0, None]:
            with self.subTest(min_expected_runs=runs):
                with self.assertRaises(GateError):
                    self.rows([self.ASAN] * 3, definitions=lambda m, r=runs: (m['no-wait-teardown'].update(min_expected_runs=r), m)[1])
        for name in ['plain-stop-read', 'no-wait-teardown']:
            with self.subTest(unknown_key=name):
                with self.assertRaises(GateError):
                    self.rows([self.ASAN] * 3, definitions=lambda m, n=name: (m[n].update(also_detect={'exit_code': 134, 'line': line}), m)[1])

    def test_asan_detection_and_the_other_mutants_are_unchanged(self):
        rows = self.rows([self.ASAN] * 3)
        self.assertEqual({k: (r['detected_runs'], r['status']) for k, r in rows.items()},
                         {'plain-stop-read': (3, 'PASS'), 'no-wait-teardown': (3, 'PASS'), 'accounting-skip': (3, 'PASS')})

    def test_a_pass_or_an_unrelated_failure_is_not_detected(self):
        for outcome in [(0, '', None),                                   # the run passed
                        (0, MUTEX_FATAL, None),                          # the message, but the run passed
                        (134, '', None),                                 # an abort without the message
                        (134, 'GLib:ERROR:other.c:1: assertion failed\n', None),
                        (1, MUTEX_FATAL, None),                          # the message under another status
                        (139, MUTEX_FATAL, None),
                        (134, 'xx' + MUTEX_FATAL, None),                 # the message not on its own line
                        (134, MUTEX_FATAL, 'timeout'),                   # a runner failure
                        (None, MUTEX_FATAL, 'timeout')]:
            with self.subTest(outcome=outcome):
                row = self.rows([self.ASAN, outcome, self.ASAN])['no-wait-teardown']
                self.assertEqual((row['detected_runs'], row['bad'], row['status']), (2, 'FAIL', 'FAIL'))

    def test_the_mutex_abort_detects_only_the_teardown_mutant(self):
        row = self.rows([self.ASAN] * 3, stop=[self.TSAN, (134, MUTEX_FATAL, None), self.TSAN])['plain-stop-read']
        self.assertEqual((row['detected_runs'], row['bad'], row['status']), (2, 'FAIL', 'FAIL'))


if __name__ == '__main__':
    unittest.main()
