"""The compiler-based project source policy of the ast gate: the plan (project_check),
the in-container evaluation (container/project-source-policy.py) and the host
dependency findings. The compilers themselves run only in the live project check."""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
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
        for flag in ('-std=c17', '-I/src/foundation/include', '-I/src/foundation/tests', '-I/src/fuzz',
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


class HostFindingTests(unittest.TestCase):
    def framework(self, d):
        (d/'starter-export.json').write_text(json.dumps({'files': ['fuzz/parser.h', 'tools/x.py', 'examples/app/include/greeting.h',
                                                                   'starter-export.json']}))
        return d

    def result(self, deps, failed=()):
        return {'status': 'FAIL' if failed else 'PASS', 'failed_checks': list(failed), 'configurations': ['gcc-O0'],
                'units': ['examples/app/src/greeting.c'], 'runs': 1, 'preprocess_errors': [], 'pragmas': [],
                'markers': [], 'differences': [], 'dependencies': {'examples/app/src/greeting.c': deps}}

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
