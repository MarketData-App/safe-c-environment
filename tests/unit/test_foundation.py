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


if __name__ == '__main__':
    unittest.main()
