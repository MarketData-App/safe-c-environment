"""The compiler-based project source policy of the ast gate: the plan (project_check),
the in-container evaluation (container/project-source-policy.py) and the host
dependency findings. The compilers themselves run only in the live project check."""
import contextlib
import gc
import importlib.util
import io
import json
import sys
import tempfile
import threading
import unittest
import weakref
from pathlib import Path
from unittest import mock
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
from evidence import GateError
import project_check as pc

PROJECT = {'schema_version': 1, 'name': 'demo-app', 'modules': [{
    'name': 'greeting', 'spec': 'specs/project/greeting.md', 'sources': ['src/greeting.c'],
    'headers': ['include/greeting.h'], 'tests': ['tests/project/test_greeting.c'], 'reads_external_input': True,
    'fuzz': [{'name': 'greeting', 'harness': 'fuzz/project/greeting_fuzz.c', 'corpus': 'fuzz/project/corpus/greeting',
              'regressions': 'fuzz/project/regressions/greeting'}]}],
    'programs': [{'name': 'hello', 'main': 'src/main.c', 'modules': ['greeting']}],
    'run': {'program': 'hello', 'args': [], 'expect_exit': 0}}


def container_module():
    spec = importlib.util.spec_from_file_location('project_source_policy', ROOT/'container/project-source-policy.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PlanTests(unittest.TestCase):
    def test_every_gate_configuration_is_planned(self):
        plan = pc.source_policy_plan('examples/app', PROJECT)
        names = [c['name'] for c in plan['configs']]
        self.assertEqual(names[:len(pc.BUILDS)], [b[0] for b in pc.BUILDS])
        self.assertEqual(names[len(pc.BUILDS):], ['fuzz', 'tidy', 'csa', 'gcc-analyzer', 'ast-scan'])
        self.assertEqual(plan['project_root'], '/src/examples/app')
        self.assertEqual(plan['units'], ['/src/examples/app/'+p for p in ('src/greeting.c', 'tests/project/test_greeting.c',
                                                                         'fuzz/project/greeting_fuzz.c', 'src/main.c')])
        databases = [c['database'] for c in plan['configs'] if 'database' in c]
        self.assertEqual(databases, ['/work/'+b['directory']+'/compile_commands.json' for b in pc.build_plan('examples/app')])
        fuzz = plan['configs'][len(pc.BUILDS)]['argv']
        self.assertEqual(fuzz[0], pc.FUZZ_ENV['CC'])
        self.assertEqual(fuzz[1:-2], pc.FUZZ_ENV['CFLAGS'].split())
        self.assertEqual(fuzz[-2:], ['-std=c17', '-I/src/examples/app/include'])
        by_name = {c['name']: c for c in plan['configs']}
        self.assertIn('-D__clang_analyzer__=1', by_name['csa']['argv'])
        self.assertIn('-fanalyzer', by_name['gcc-analyzer']['argv'])
        self.assertTrue(by_name['ast-scan']['gnu_source_probe'])
        self.assertIn('/src/foundation/include/sc-foundation.h', by_name['ast-scan']['argv'])

    def test_ast_scan_flags_match_the_policy_scanner(self):
        text = (ROOT/'container/foundation-policy.py').read_text()
        for flag in ('-std=c17', '-I/src/foundation/include', '-I/src/foundation/parallel', '-I/src/foundation/tests', '-I/src/fuzz',
                     '-ffp-contract=off',
                     '-DGLIB_VERSION_MIN_REQUIRED=GLIB_VERSION_2_70', '-DGLIB_VERSION_MAX_ALLOWED=GLIB_VERSION_2_70',
                     "'include/glib-2.0'", "'lib/glib-2.0/include'", "'-idirafter'", 'sc-foundation.h'):
            self.assertIn(flag, text)
        argv = pc._ast_scan_flags('p')
        self.assertEqual(argv[argv.index('-idirafter')+1], '/src/p/include')


class ContainerEvaluationTests(unittest.TestCase):
    plan = {'project_root': '/src/p', 'units': ['/src/p/src/a.c', '/src/p/fuzz/project/h.c'],
            'configs': [{'name': 'gcc-O0', 'database': 'x'}, {'name': 'clang-O0', 'database': 'y'}]}

    def run_row(self, config, unit, stream, directives=(), markers=(), deps=(), defines=(), macros=None, found=()):
        return {'config': config, 'unit': unit, 'stream': list(stream), 'directives': list(directives),
                'markers': list(markers), 'dependencies': list(deps), 'defines': list(defines),
                'macros': macros or {}, 'found': list(found)}

    def test_clean_runs_pass(self):
        module = container_module()
        stream = [('/src/p/src/a.c', 1, 'int'), ('/src/p/src/a.c', 1, 'x')]
        runs = [self.run_row(c, u, stream, deps=[u]) for u in self.plan['units'] for c in ('gcc-O0', 'clang-O0')]
        result = module.evaluate(self.plan, runs)
        self.assertEqual((result['status'], result['failed_checks']), ('PASS', []))
        self.assertEqual(result['dependencies'], {'p/fuzz/project/h.c': ['/src/p/fuzz/project/h.c'], 'p/src/a.c': ['/src/p/src/a.c']})

    def test_each_check_fails(self):
        module = container_module()
        a, h = self.plan['units']
        base = [('/src/p/src/a.c', 3, 'int')]
        define = [('/src/p/src/a.c', 1, '#'), ('/src/p/src/a.c', 1, 'define'), ('/src/p/src/a.c', 1, 'V')]
        uses = [('/src/p/src/a.c', 5, 'int'), ('/src/p/src/a.c', 5, 'BUILD_X')]
        runs = [self.run_row('gcc-O0', a, base + uses, directives=[('/src/p/src/a.c', 2, 'pragma')], defines=define + [('/src/p/src/a.c', 1, '1')],
                             macros={'BUILD_X': (None, '1'), 'SAME': (None, '0x10')}),
                self.run_row('clang-O0', a, base + [('/src/p/src/a.c', 4, 'y')] + uses, defines=define + [('/src/p/src/a.c', 1, '2')],
                             markers=[('/src/p/src/a.c', 1, 'project file marked as a system header')],
                             macros={'BUILD_X': (None, '2'), 'SAME': (None, '16')}),
                self.run_row('gcc-O0', h, base),
                {'config': 'clang-O0', 'unit': h, 'error': 'exit 1', 'log': '/work/l'}]
        result = module.evaluate(self.plan, runs)
        self.assertEqual(result['failed_checks'], ['preprocess', 'pragmas', 'markers', 'identity', 'build-macros'])
        self.assertEqual(result['pragmas'], [{'file': 'p/src/a.c', 'line': 2, 'directive': 'pragma', 'configs': ['gcc-O0']}])
        self.assertEqual(result['build_macros'], [{'file': 'p/src/a.c', 'line': 5, 'macro': 'BUILD_X', 'configs': ['gcc-O0', 'clang-O0']}])
        self.assertGreaterEqual(result['differing_macros'], 1)
        self.assertEqual(result['differences'], [
            {'unit': 'p/src/a.c', 'stream': 'code', 'file': 'p/src/a.c', 'line': 5, 'token': 'int', 'baseline': 'gcc-O0',
             'config': 'clang-O0', 'other_file': 'p/src/a.c', 'other_line': 4, 'other_token': 'y'},
            {'unit': 'p/src/a.c', 'stream': 'defines', 'file': 'p/src/a.c', 'line': 1, 'token': '1', 'baseline': 'gcc-O0',
             'config': 'clang-O0', 'other_file': 'p/src/a.c', 'other_line': 1, 'other_token': '2'}])
        self.assertEqual(result['preprocess_errors'], [{'unit': 'p/fuzz/project/h.c', 'config': 'clang-O0', 'error': 'exit 1', 'log': '/work/l'}])

    def test_missing_command_is_an_error(self):
        module = container_module()
        a = self.plan['units'][0]
        result = module.evaluate(dict(self.plan, units=[a]), [self.run_row('gcc-O0', a, [])])
        self.assertEqual(result['preprocess_errors'], [{'unit': 'p/src/a.c', 'config': 'clang-O0', 'error': 'no compile command'}])

    def test_commands_use_the_database_and_fall_back_for_harnesses(self):
        module = container_module()
        with tempfile.TemporaryDirectory() as t:
            database = Path(t)/'compile_commands.json'
            database.write_text(json.dumps([
                {'directory': '/work/b', 'command': 'clang -I/src/p/include -O2 -o x.o -c /src/p/src/a.c', 'file': '/src/p/src/a.c'},
                {'directory': '/work/b', 'arguments': ['clang', '-c', 'other.c'], 'file': 'other.c'}]))
            source = Path(t)/'u.c'
            source.write_text('#define _GNU_SOURCE\n#include <stdio.h>\n')
            plan = {'units': ['/src/p/src/a.c', '/src/p/fuzz/project/h.c'],
                    'configs': [{'name': 'clang-O2', 'database': str(database)}, {'name': 'fuzz', 'argv': ['clang', '-O1']}]}
            table = dict(module.commands(plan))
            self.assertEqual(table['clang-O2']['/src/p/src/a.c'],
                             (['clang', '-I/src/p/include', '-O2', '-o', 'x.o', '-c', '/src/p/src/a.c'], '/work/b', '/src/p/src/a.c', None))
            self.assertEqual(table['clang-O2']['/src/p/fuzz/project/h.c'][2:], ('/src/p/src/a.c', '/src/p/fuzz/project/h.c'))
            self.assertEqual(table['fuzz']['/src/p/src/a.c'][0], ['clang', '-O1', '/src/p/src/a.c'])
            probe = dict(module.commands({'units': [str(source)], 'configs': [{'name': 'ast-scan', 'argv': ['clang'], 'gnu_source_probe': True}]}))
            self.assertEqual(probe['ast-scan'][str(source)][0], ['clang', '-D_GNU_SOURCE=', str(source)])

    def test_plan_paths_must_stay_under_src(self):
        module = container_module()
        for plan in ({'project_root': '/etc', 'units': [], 'configs': []},
                     {'project_root': '/src/p', 'units': ['/src/../etc/x.c'], 'configs': []}):
            with self.subTest(plan=plan['project_root']), self.assertRaises(ValueError):
                module.main([json.dumps(plan)])


def _reference_add(rows, key, row):
    if key in rows:
        if row['configs'][0] not in rows[key]['configs']:
            rows[key]['configs'].append(row['configs'][0])
    else:
        rows[key] = row


def _reference_difference(rel, unit, kind, found):
    return {'unit': rel(unit), 'stream': kind, 'file': rel(found['file']), 'line': found['line'],
            'token': found['token'], 'baseline': found['baseline'], 'config': found['config'],
            'other_file': rel(found['other_file']), 'other_line': found['other_line'],
            'other_token': found['other_token']}


def reference_evaluate(module, plan, runs):
    """The evaluate() of container/project-source-policy.py before the bounded-memory repair
    (P2-B2-SRCPOL-MEM-01), kept unchanged as the identity reference: it holds every run at once."""
    ps, _rel, _add, LIMIT = module.ps, module._rel, _reference_add, module.LIMIT
    names = [c['name'] for c in plan['configs']]
    pragmas, markers, uses, dependencies, differences = {}, {}, {}, {}, []
    errors = []
    tables = {unit: [] for unit in plan['units']}
    scanned = {unit: [] for unit in plan['units']}
    code = {unit: [] for unit in plan['units']}
    defines = {unit: [] for unit in plan['units']}
    for run in runs:
        unit = run['unit']
        if 'error' in run:
            errors.append({'unit': _rel(unit), 'config': run['config'], 'error': run['error'], 'log': run['log']})
            continue
        for file, line, name in run['directives']:
            _add(pragmas, (file, line, name), {'file': _rel(file), 'line': line, 'directive': name or '#',
                                              'configs': [run['config']]})
        for file, line, problem in run['markers']:
            _add(markers, (file, line, problem), {'file': _rel(file), 'line': line, 'problem': problem,
                                                 'configs': [run['config']]})
        tables[unit].append(run['macros'])
        scanned[unit].append((run['config'], run['stream'], run['found']))
        dependencies.setdefault(_rel(unit), set()).update(run['dependencies'])
        code[unit].append((run['config'], run['stream']))
        defines[unit].append((run['config'], run.get('defines', [])))
    covered = {(r['config'], r['unit']) for r in runs}
    for name in names:
        for unit in plan['units']:
            if (name, unit) not in covered:
                errors.append({'unit': _rel(unit), 'config': name, 'error': 'no compile command'})
    differing_count = 0
    for unit in plan['units']:
        differing = ps.differing_macros(tables[unit]) if tables[unit] else set()
        differing_count = max(differing_count, len(differing))
        for config, stream, directives_found in scanned[unit]:
            for file, line, name in ps.build_macro_uses(stream, directives_found, differing):
                _add(uses, (file, line, name), {'file': _rel(file), 'line': line, 'macro': name, 'configs': [config]})
        for kind, streams in (('code', code[unit]), ('defines', defines[unit])):
            found = ps.first_difference(streams)
            if found is not None:
                differences.append(_reference_difference(_rel, unit, kind, found))
    failed = [check for check, rows in (('preprocess', errors), ('pragmas', pragmas), ('markers', markers),
                                         ('identity', differences), ('build-macros', uses)) if rows]
    return {'status': 'FAIL' if failed else 'PASS', 'failed_checks': failed, 'configurations': names,
            'units': [_rel(u) for u in plan['units']], 'runs': len(runs),
            'preprocess_errors': errors[:LIMIT], 'pragmas': list(pragmas.values())[:LIMIT],
            'markers': list(markers.values())[:LIMIT], 'differences': differences[:LIMIT],
            'build_macros': list(uses.values())[:LIMIT], 'differing_macros': differing_count,
            'dependencies': {unit: sorted(paths) for unit, paths in sorted(dependencies.items())}}


class _Tracked(list):
    """A list that a weak reference can watch (the per-unit run list and its streams)."""


class IncrementalIdentityTests(unittest.TestCase):
    """The per-unit fold (bounded memory, P2-B2-SRCPOL-MEM-01) gives the result of the old evaluate()."""
    configs = ['gcc-O0', 'clang-O0', 'fuzz']
    units = ['/src/p/src/a.c', '/src/p/src/b.c', '/src/p/fuzz/project/h.c', '/src/p/tests/project/m.c']
    header = '/src/p/include/x.h'

    def plan(self, units=None, configs=None):
        return {'project_root': '/src/p', 'units': list(units or self.units),
                'configs': [{'name': n, 'database': 'db-'+n} for n in (configs or self.configs)]}

    def run_row(self, config, unit, stream, directives=(), markers=(), deps=(), defines=(), macros=None, found=()):
        return {'config': config, 'unit': unit, 'stream': list(stream), 'directives': list(directives),
                'markers': list(markers), 'dependencies': list(deps), 'defines': list(defines),
                'macros': dict(macros or {}), 'found': list(found)}

    def unit_run(self, config, unit):
        """One synthetic run; None when the unit has no compile command in that configuration."""
        a, b, h, m = self.units
        ci = self.configs.index(config)
        x = self.header
        if unit == m and config == 'fuzz':
            return None
        if unit == h and config == 'clang-O0':
            return {'config': config, 'unit': unit, 'error': 'exit 1', 'log': '/work/project/source-policy/0007-*.log'}
        macros = {'BUILD_X': (None, str(ci+1)), 'SAME': (None, '0x10' if ci == 0 else '16'), 'K': (None, 'BUILD_X')}
        stream = [(unit, 1, 'int'), (unit, 1, 'v'), (unit, 2, 'BUILD_X')]
        found = [(unit, 4, 'define', ['LOCAL', 'K'])]
        defines = [(unit, 4, '#'), (unit, 4, 'define'), (unit, 4, 'LOCAL'), (unit, 4, 'K')]
        directives, markers = [], []
        deps = [unit, x, '/usr/include/stdio.h']
        if unit == a:
            if config == 'clang-O0':
                stream = stream[:1] + [(unit, 1, 'w')] + stream[2:]
            if config == 'fuzz':
                defines = defines[:-1] + [(unit, 4, 'K2')]
                # Shared rows with unit b: a reaches them only in the last configuration.
                directives = [(x, 9, 'pragma'), (x, 10, 'ident')] + [(unit, 50+k, 'pragma') for k in range(6)]
                markers = [(x, 1, 'project file marked as a system header')] + [(unit, 60+k, 'renamed by #line') for k in range(6)]
                stream = stream + [(x, 30, 'BUILD_X')]
        if unit == b:
            directives = [(unit, 70+k, 'pragma') for k in range(ci, ci+18)] + [(x, 9, 'pragma')]
            if config != 'gcc-O0':
                directives.append((x, 10, 'ident'))
            markers = [(unit, 80+k, 'entered without being a dependency') for k in range(18)] + [(x, 1, 'project file marked as a system header')]
            stream = stream + [(unit, 90+k, 'BUILD_X') for k in range(22)]
            if config == 'gcc-O0':
                stream = stream + [(x, 30, 'BUILD_X')]
            if config == 'clang-O0':
                directives.append((unit, 3, ''))
        return self.run_row(config, unit, stream, directives=directives, markers=markers, deps=deps, defines=defines,
                            macros=macros, found=found)

    def config_major_runs(self, plan):
        runs = []
        for config in [c['name'] for c in plan['configs']]:
            for unit in plan['units']:
                run = self.unit_run(config, unit)
                if run is not None:
                    runs.append(run)
        return runs

    def test_incremental_result_equals_the_reference(self):
        module = container_module()
        plan = self.plan()
        runs = self.config_major_runs(plan)
        expected = reference_evaluate(module, plan, runs)
        self.assertEqual(expected['failed_checks'], ['preprocess', 'pragmas', 'markers', 'identity', 'build-macros'])
        # The case covers every row kind, truncation and a differing macro with a project use.
        self.assertEqual(len(expected['pragmas']), module.LIMIT)
        self.assertEqual(len(expected['markers']), module.LIMIT)
        self.assertEqual(len(expected['build_macros']), module.LIMIT)
        self.assertEqual([(d['unit'], d['stream']) for d in expected['differences']],
                         [('p/src/a.c', 'code'), ('p/src/a.c', 'defines'), ('p/src/b.c', 'code')])
        self.assertEqual(expected['preprocess_errors'][-1]['error'], 'no compile command')
        self.assertIn({'file': 'p/include/x.h', 'line': 30, 'macro': 'BUILD_X', 'configs': ['fuzz', 'gcc-O0']},
                      expected['build_macros'])
        result = module.evaluate(plan, runs)
        self.assertEqual(result, expected)
        self.assertEqual(json.dumps(result, sort_keys=True), json.dumps(expected, sort_keys=True))
        accumulator = module.Accumulator(plan)
        positions = {id(run): k for k, run in enumerate(runs)}
        for unit in plan['units']:
            accumulator.fold(unit, [(positions[id(r)], r) for r in runs if r['unit'] == unit])
        self.assertEqual(accumulator.result(), expected)

    def test_errors_beyond_the_limit_keep_their_order(self):
        module = container_module()
        units = ['/src/p/src/u%d.c' % k for k in range(12)]
        plan = self.plan(units=units)
        runs = []
        for ci, config in enumerate(self.configs):
            for uj, unit in enumerate(units):
                if (ci + uj) % 3 == 0:
                    continue
                if (ci * 5 + uj) % 2:
                    runs.append({'config': config, 'unit': unit, 'error': 'timeout', 'log': 'l%d-%d' % (ci, uj)})
                else:
                    runs.append(self.run_row(config, unit, [(unit, 1, 'int')], deps=[unit]))
        expected = reference_evaluate(module, plan, runs)
        self.assertEqual(len(expected['preprocess_errors']), module.LIMIT)
        self.assertEqual(module.evaluate(plan, runs), expected)

    def test_clean_and_single_unit_cases_equal_the_reference(self):
        module = container_module()
        plan = self.plan(units=self.units[:1], configs=self.configs[:1])
        a = self.units[0]
        for runs in ([], [self.run_row('gcc-O0', a, [(a, 1, 'int')], deps=[a])],
                     [{'config': 'gcc-O0', 'unit': a, 'error': 'no dependency file', 'log': 'l'}]):
            with self.subTest(runs=len(runs)):
                self.assertEqual(module.evaluate(plan, runs), reference_evaluate(module, plan, runs))

    def test_a_folded_unit_keeps_no_stream(self):
        module = container_module()
        plan = self.plan()
        runs = self.config_major_runs(plan)
        accumulator = module.Accumulator(plan)
        watched = []
        for unit in plan['units']:
            unit_runs = _Tracked()
            for position, run in enumerate(runs):
                if run['unit'] == unit:
                    run = dict(run)
                    if 'stream' in run:
                        for key in ('stream', 'found', 'defines', 'directives', 'markers', 'dependencies'):
                            run[key] = _Tracked(run[key])
                            watched.append(weakref.ref(run[key]))
                        run['macros'] = _TrackedDict(run['macros'])
                        watched.append(weakref.ref(run['macros']))
                    unit_runs.append((position, run))
            watched.append(weakref.ref(unit_runs))
            accumulator.fold(unit, unit_runs)
            del unit_runs, run
            gc.collect()
            self.assertEqual([w for w in watched if w() is not None], [], unit)
        self.assertEqual(accumulator.result(), reference_evaluate(module, plan, runs))

    def test_main_folds_units_in_order_with_a_bounded_number_in_flight(self):
        module = container_module()
        plan = self.plan()
        by_job = {}
        table = []
        for config in self.configs:
            rows = {}
            for unit in self.units:
                run = self.unit_run(config, unit)
                if run is not None:
                    rows[unit] = (['cc'], '/work', unit, None)
                    by_job[(config, unit)] = run
            table.append((config, rows))
        expected = reference_evaluate(module, plan, self.config_major_runs(plan))
        events, lock = [], threading.Lock()

        def fake_run_one(job):
            index, name, unit = job[:3]
            with lock:
                events.append(('start', unit))
            return dict(by_job[(name, unit)])
        fold = module.Accumulator.fold

        def recording_fold(accumulator, unit, unit_runs):
            with lock:
                events.append(('fold', unit))
            return fold(accumulator, unit, unit_runs)
        with tempfile.TemporaryDirectory() as t:
            out = io.StringIO()
            with mock.patch.object(module, 'WORK', Path(t)), mock.patch.object(module, 'commands', lambda p: table), \
                    mock.patch.object(module, 'run_one', fake_run_one), \
                    mock.patch.object(module.Accumulator, 'fold', recording_fold), contextlib.redirect_stdout(out):
                code = module.main([json.dumps(plan)])
            written = json.loads((Path(t)/'result.json').read_text())
        self.assertEqual(code, 1)
        self.assertEqual(written, json.loads(json.dumps(module.wire(expected))))
        self.assertEqual(json.loads(out.getvalue().strip().splitlines()[-1]), written)
        self.assertEqual(pc.source_policy_dependencies(written), expected['dependencies'])
        self.assertEqual({k: v for k, v in written.items() if k not in ('dependencies', 'dependency_paths')},
                         json.loads(json.dumps({k: v for k, v in expected.items() if k != 'dependencies'})))
        self.assertEqual([u for kind, u in events if kind == 'fold'], self.units)
        folded = 0
        for kind, unit in events:
            if kind == 'fold':
                folded += 1
            else:
                self.assertLess(self.units.index(unit), folded + module.UNITS_IN_FLIGHT, unit)

    def test_the_printed_form_decodes_to_the_old_dependencies(self):
        module = container_module()
        plan = self.plan()
        expected = reference_evaluate(module, plan, self.config_major_runs(plan))
        printed = json.loads(json.dumps(module.wire(module.evaluate(plan, self.config_major_runs(plan))), sort_keys=True))
        self.assertEqual(printed['dependency_paths'], sorted(printed['dependency_paths']))
        self.assertEqual(pc.source_policy_dependencies(printed), expected['dependencies'])
        rest = {k: v for k, v in printed.items() if k not in ('dependencies', 'dependency_paths')}
        self.assertEqual(rest, json.loads(json.dumps({k: v for k, v in expected.items() if k != 'dependencies'})))
        self.assertEqual(pc.source_policy_dependencies(module.wire(dict(expected, dependencies={}))), {})

    def test_malformed_printed_dependencies_block(self):
        good = {'dependency_paths': ['/src/p/a.c', '/usr/include/stdio.h'], 'dependencies': {'p/a.c': [0, 1]}}
        self.assertEqual(pc.source_policy_dependencies(good), {'p/a.c': ['/src/p/a.c', '/usr/include/stdio.h']})
        for bad in ({'dependencies': {'p/a.c': ['/src/p/a.c']}}, dict(good, dependency_paths=['/x', '/x']),
                    dict(good, dependencies={'p/a.c': [2]}), dict(good, dependencies={'p/a.c': [-1]}),
                    dict(good, dependencies={'p/a.c': [True]}), dict(good, dependencies={'p/a.c': ['0']}),
                    dict(good, dependencies=[]), dict(good, dependency_paths=[1])):
            with self.subTest(bad=bad), self.assertRaises(GateError):
                pc.source_policy_dependencies(bad)

    def test_the_printed_line_stays_under_the_record_limit_with_shared_headers(self):
        module = container_module()
        limit = json.loads((ROOT/'safety/container-policy.json').read_text())['common']['capture_record_bytes']
        shared = ['/src/examples/demo-project/include/generated_header_number_%04d.h' % k for k in range(400)]
        units = {'examples/demo-project/tests/project/test_unit_%03d.c' % u: shared for u in range(120)}
        result = {'status': 'PASS', 'dependencies': units}
        self.assertGreater(len(json.dumps(result, sort_keys=True)), limit)
        printed = json.dumps(module.wire(result), sort_keys=True)
        self.assertLess(len(printed), limit)
        self.assertEqual(pc.source_policy_dependencies(json.loads(printed)), units)

    def test_duplicate_units_are_rejected(self):
        module = container_module()
        with self.assertRaises(ValueError):
            module.main([json.dumps({'project_root': '/src/p', 'units': ['/src/p/a.c', '/src/p/a.c'], 'configs': []})])


class _TrackedDict(dict):
    """A dict that a weak reference can watch (the per-run macro table)."""


class HostFindingTests(unittest.TestCase):
    def framework(self, d):
        (d/'starter-export.json').write_text(json.dumps({'files': ['fuzz/parser.h', 'tools/x.py', 'examples/app/include/greeting.h',
                                                                   'starter-export.json']}))
        return d

    def result(self, deps, failed=()):
        return {'status': 'FAIL' if failed else 'PASS', 'failed_checks': list(failed), 'configurations': ['gcc-O0'],
                'units': ['examples/app/src/greeting.c'], 'runs': 1, 'preprocess_errors': [], 'pragmas': [],
                'markers': [], 'differences': [], 'dependency_paths': list(dict.fromkeys(deps)),
                'dependencies': {'examples/app/src/greeting.c': [list(dict.fromkeys(deps)).index(d) for d in deps]}}

    def test_framework_headers(self):
        with tempfile.TemporaryDirectory() as t:
            d = self.framework(Path(t))
            self.assertEqual(pc.framework_headers(d, 'examples/app'), {'fuzz/parser.h'})
            self.assertEqual(pc.framework_headers(d, '.'), {'fuzz/parser.h', 'examples/app/include/greeting.h'})

    def test_dependencies_checked_on_the_host(self):
        with tempfile.TemporaryDirectory() as t:
            d = self.framework(Path(t))
            ok = ['/src/examples/app/src/greeting.c', '/src/examples/app/include/greeting.h', '/src/fuzz/parser.h', '/usr/include/stdio.h']
            self.assertEqual(pc.source_policy_findings(self.result(ok), 'examples/app', PROJECT, d)[0], [])
            failed, details = pc.source_policy_findings(self.result(ok+['/src/examples/app/review/x.txt']), 'examples/app', PROJECT, d)
            self.assertEqual(failed, ['dependencies'])
            self.assertEqual(details['dependency_problems'], [{'file': 'review/x.txt', 'problem': 'project dependency is not a declared header',
                                                               'unit': 'examples/app/src/greeting.c'}])
            failed, _ = pc.source_policy_findings(self.result(ok, ['identity']), 'examples/app', PROJECT, d)
            self.assertEqual(failed, ['identity'])

    def test_incomplete_result_blocks(self):
        for value in (None, {'status': 'BLOCKED', 'error_type': 'KeyError'}, []):
            with self.subTest(value=value), self.assertRaises(GateError):
                pc.source_policy_findings(value, 'examples/app', PROJECT, ROOT)


class SourcePolicyStepTests(unittest.TestCase):
    """ProjectCheck.source_policy honours the step state (P2-B2-STEPFAIL-01): a step failure
    BLOCKS the gate even when the printed result is complete."""

    def printed(self, status='PASS', failed=()):
        return json.dumps({'status': status, 'failed_checks': list(failed), 'configurations': ['gcc-O0'],
                           'units': ['examples/app/src/greeting.c'], 'runs': 1, 'preprocess_errors': [], 'pragmas': [],
                           'markers': [], 'differences': [], 'build_macros': [], 'differing_macros': 0,
                           'dependency_paths': ['/src/examples/app/src/greeting.c'],
                           'dependencies': {'examples/app/src/greeting.c': [0]}}, sort_keys=True)

    def source_policy(self, output, exit_code=0, failure=None):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            (root/'starter-export.json').write_text(json.dumps({'files': ['starter-export.json']}))
            check = pc.ProjectCheck.__new__(pc.ProjectCheck)
            check.project_dir, check.project, check.snapshot = 'examples/app', PROJECT, root
            steps = []

            def step(label, argv, *, timeout, env=None, keep_output=True):
                steps.append(label)
                return {'output': output+'\n', 'exit_code': exit_code, 'failure': failure, 'seconds': 1.0,
                        'evidence_complete': failure is None, 'evidence_path': '/e/0001-'+label+'.json'}
            check.step = step
            evidence = []
            try:
                return check.source_policy(evidence)
            finally:
                self.assertEqual((steps, evidence), (['ast-source-policy'], ['/e/0001-ast-source-policy.json']))

    def test_a_passing_step_passes(self):
        failed, details = self.source_policy(self.printed())
        self.assertEqual((failed, details['dependency_problems']), ([], []))

    def test_a_failing_policy_result_fails(self):
        failed, _details = self.source_policy(self.printed('FAIL', ['pragmas']), exit_code=1)
        self.assertEqual(failed, ['pragmas'])

    def test_a_step_failure_blocks_even_with_complete_data(self):
        for failure in ('RECORD_LIMIT', 'OUTPUT_LIMIT', 'TIMEOUT', 'CGROUP_OOM', 'STARTUP_FAILURE', 'SECCOMP_FAILURE', 'EXEC'):
            for exit_code in (0, 1, 137):
                with self.subTest(failure=failure, exit_code=exit_code), self.assertRaises(GateError):
                    self.source_policy(self.printed(), exit_code=exit_code, failure=failure)

    def test_an_exit_code_that_contradicts_the_result_blocks(self):
        for output, exit_code in ((self.printed(), 1), (self.printed(), 2), (self.printed(), 137),
                                  (self.printed('FAIL', ['pragmas']), 0), (self.printed('FAIL', ['pragmas']), 2)):
            with self.subTest(exit_code=exit_code), self.assertRaises(GateError):
                self.source_policy(output, exit_code=exit_code)


class AstRowTests(unittest.TestCase):
    def row(self, value, exit_code=0):
        checks, row = set(), {}
        clean = pc.ProjectCheck.ast_row({'output': json.dumps(value) if value is not None else 'x', 'exit_code': exit_code,
                                         'failure': None if exit_code == 0 else 'EXIT'}, row, checks)
        return clean, row, checks

    def test_rows(self):
        self.assertEqual(self.row({'status': 'PASS', 'findings': []})[0], True)
        clean, row, checks = self.row({'status': 'FAIL', 'findings': [{'rule': 'project-attribute', 'name': 'NakedAttr'}]}, 1)
        self.assertEqual((clean, row['attributes'], checks), (False, ['NakedAttr'], {'attributes'}))
        clean, row, checks = self.row({'status': 'FAIL', 'findings': [{'rule': 'raw-indexing', 'name': 'x'}]}, 1)
        self.assertEqual((clean, checks), (False, {'api'}))
        clean, row, checks = self.row({'status': 'FAIL', 'findings': [{'rule': 'runtime-interface', 'name': '__'+'asan_default_options'},
                                                                      {'rule': 'project-builtin', 'name': '__builtin_constant_p'}]}, 1)
        self.assertEqual((clean, checks), (False, {'runtime-interface', 'builtins'}))
        clean, row, checks = self.row({'status': 'FAIL', 'findings': [{'rule': 'reserved-declaration', 'name': '__'+'x'},
                                                                      {'rule': 'fuzzer-entry', 'name': 'LLVMFuzzerInitialize'},
                                                                      {'rule': 'banned-call', 'name': 'dlsym'}]}, 1)
        self.assertEqual((clean, checks), (False, {'reserved-identifier', 'fuzzer-entry', 'banned-call'}))
        self.assertEqual(self.row(None, 2)[2], {'ast-scan'})
        self.assertEqual(self.row({'status': 'BLOCKED'}, 2)[2], {'ast-scan'})


if __name__ == '__main__':
    unittest.main()
