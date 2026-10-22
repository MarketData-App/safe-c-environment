"""FR1-01 (FR1 approval finding) and FR3: the test-stub selftest suites come from the `stubs` of a project's protected
protocol file. When no example project declares a stub, no stub suite runs and `bench selftest` records each suite kind
in cases.json `not_run` with the reason (as B15 records its stub part); a malformed declaration is one BLOCKED suite,
never a silent skip. No container runs here: the stub run and check are patched to record their calls."""
import ast, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import bench, bench_deadline as bd
from evidence import GateError

FIXTURE='tests/fixtures/bench-project'

def never(*a,**k):raise AssertionError('no stub suite may run')

class StubSuiteTests(unittest.TestCase):
    def test_no_declared_stub_records_not_run_with_the_reason(self):
        with mock.patch.object(bench,'example_projects',lambda root,project=None:[]),mock.patch.object(bd,'_stub_run_selftest',never),\
             mock.patch.object(bd,'_stub_check_selftest',never):
            suites,not_run=bd.stub_suites(ROOT,Path(tempfile.mkdtemp()))
        self.assertEqual(suites,{})
        self.assertEqual(not_run,[{'suite':'stub-run','reason':bd.NOT_DECLARED},{'suite':'stub-check','reason':bd.NOT_DECLARED}])

    def test_the_framework_example_declares_no_stub(self):
        self.assertEqual(bd.declared_stub_reasons(ROOT),[])          # examples/bench-demo: the framework names no stub

    def test_each_declared_stub_gives_a_run_and_a_check_suite(self):
        calls=[]
        def run(root,run_dir,spec,project,case):calls.append(('run',spec['reason'],project,case['case_id']));return {'status':'PASS'}
        def check(root,run_dir,spec,project,case):calls.append(('check',spec['reason'],project,spec['check']));return {'status':'PASS'}
        with mock.patch.object(bench,'example_projects',lambda root,project=None:[FIXTURE]),mock.patch.object(bd,'_stub_run_selftest',run),\
             mock.patch.object(bd,'_stub_check_selftest',check):
            suites,not_run=bd.stub_suites(ROOT,Path(tempfile.mkdtemp()))
        self.assertEqual(not_run,[])
        self.assertEqual(sorted(suites),['stub-check-stub-hang','stub-check-stub-overrun','stub-run-stub-hang','stub-run-stub-overrun'])
        self.assertIn(('run','stub-hang',FIXTURE,'fixture-case'),calls);self.assertIn(('check','stub-overrun',FIXTURE,'overrun-stub'),calls)

    def test_a_malformed_declaration_is_one_blocked_suite(self):
        def bad(root,project):raise GateError('protocol stub x: no case')
        with mock.patch.object(bench,'example_projects',lambda root,project=None:[FIXTURE]),mock.patch.object(bd,'declared_project_stubs',bad):
            suites,not_run=bd.stub_suites(ROOT,Path(tempfile.mkdtemp()))
        self.assertEqual((list(suites),suites['stubs']['status'],not_run),(['stubs'],'BLOCKED',[]))

    def test_a_stub_spec_uses_the_one_test_variable_with_its_reason(self):
        spec=bd.stub_spec({'reason':'stub-hang','check':'hang-stub','variant':'py-library'})
        self.assertEqual(spec['env'],{'SAFE_C_TEST_STUB':'stub-hang'})
        bd.check_test_floor({'mode':'selftest','test_floor_seconds':2,'test_env':spec['env']})
        for env in ({'SAFE_C_TEST_STUB':'Bad Reason'},{'SAFE_C_TEST_OTHER':'stub-hang'},{}):
            with self.subTest(env=env),self.assertRaises(GateError):bd.check_test_floor({'mode':'selftest','test_env':env})

    def test_selftest_cases_writes_not_run_into_cases_json(self):
        src=(ROOT/'tools/bench.py').read_text();tree=ast.parse(src)
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='selftest_cases');body=ast.get_source_segment(src,fn)
        self.assertIn('bench_deadline.stub_suites(root,run_dir,project)',body)
        self.assertIn("'not_run':not_run",body)

if __name__=='__main__':unittest.main()
