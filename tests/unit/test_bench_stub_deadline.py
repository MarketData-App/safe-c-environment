"""Task 6 (Amendment G2.3, G2.6; P3P-07), Task A5 (I9.4) and FR3: the test-only stub floor, the stub environment and the
selftest stub plan. FR3: the stubs come from the `stubs` of a project's protected protocol file (reason, check, variant)
and the one test variable is SAFE_C_TEST_STUB=<reason>; the fixture project declares stub-hang (selector m4) and
stub-overrun (selector m5). (Renamed from the earlier stub test module; every assertion is kept with the generic names.)"""
import sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import bench_deadline as bd, bench_model as bm
from evidence import GateError
FIXTURE='tests/fixtures/bench-project'
POL=bm.load_policy(ROOT,FIXTURE)
CASE={'call_deadline':{'selectors':['m4'],'reason':'stub-hang','factor':10,'floor_seconds':60}}
T={'variant':'py-library','selector':'m4','tier':'tiny'}
VAR='SAFE_C_TEST_STUB'

def fixture_stub(reason='stub-hang'):
    """(project, case, spec) of a protocol stub, found by declaration over the synthetic unit-test project only (FR1, FS1
    F3): the framework tree holds no project that declares a test stub."""
    import bench
    from unittest import mock
    with mock.patch.object(bench,'example_projects',lambda root:[FIXTURE]):return bd.stub_project(ROOT,reason)

class StubFloorTests(unittest.TestCase):
    def test_floor_is_60_s_outside_selftest(self):
        self.assertEqual(bd.trial_deadline(CASE,POL,T,1,1,None,10_000,plan={'mode':'smoke'}),60.0)
    def test_selftest_plan_uses_the_test_floor(self):
        self.assertEqual(bd.trial_deadline(CASE,POL,T,1,1,None,10_000,plan={'mode':'selftest','test_floor_seconds':2}),2.0)
    def test_test_floor_is_refused_in_other_modes(self):
        with self.assertRaises(GateError):bd.check_test_floor({'mode':'decision','test_floor_seconds':2})
    def test_stub_environment_only_in_selftest(self):
        src=(ROOT/'container/bench-coordinator.py').read_text();self.assertIn("SAFE_C_TEST_STUB",src);self.assertIn("plan.get('mode')=='selftest'",src)

class StubBoundaryTests(unittest.TestCase):
    """Added by the implementer: the bounds of the test-only floor, the stub environment and the selftest stub plan."""
    def test_key_outside_selftest_never_lowers_the_floor(self):
        for mode in ('smoke','decision',None):
            with self.subTest(mode=mode):
                self.assertEqual(bd.trial_deadline(CASE,POL,T,1,1,None,10_000,plan={'mode':mode,'test_floor_seconds':2}),60.0)
        self.assertEqual(bd.trial_deadline(CASE,POL,T,1,1,None,10_000),60.0)
        self.assertEqual(bd.trial_deadline(CASE,POL,T,1,1,None,1.5,plan={'mode':'selftest','test_floor_seconds':2}),1.5)   # session cap still binds
    def test_check_test_floor(self):
        self.assertIsNone(bd.check_test_floor({'mode':'selftest','test_floor_seconds':2}))
        self.assertIsNone(bd.check_test_floor({'mode':'smoke'}))
        self.assertIsNone(bd.check_test_floor({'mode':'selftest','test_env':{VAR:'stub-hang'}}))
        for bad in ({'mode':'smoke','test_floor_seconds':2},{'test_floor_seconds':2},{'mode':'selftest','test_floor_seconds':0},
                    {'mode':'selftest','test_floor_seconds':True},{'mode':'selftest','test_floor_seconds':'2'},{'mode':'selftest','test_floor_seconds':61},
                    {'mode':'smoke','test_env':{VAR:'stub-hang'}},{'mode':'selftest','test_env':{'OTHER':'stub-hang'}},
                    {'mode':'selftest','test_env':{VAR:'Stub Hang'}},{'mode':'selftest','test_env':{VAR:1}},{'mode':'selftest','test_env':[VAR]}):
            with self.subTest(plan=bad):
                with self.assertRaises(GateError):bd.check_test_floor(bad)
    def test_written_plans_never_carry_the_selftest_mode(self):
        import bench
        for plan in ({'mode':'selftest'},{'mode':'decision','test_floor_seconds':2}):
            with self.subTest(plan=plan):
                with self.assertRaises(GateError):bench.verify_written_plan({},POL,dict(plan,plan_id=bench.plan_digest(plan)),None,None,None)
    def test_child_env_passes_the_stub_only_in_selftest(self):
        import importlib.util, os
        spec=importlib.util.spec_from_file_location('bc_stub',ROOT/'container/bench-coordinator.py');bc=importlib.util.module_from_spec(spec);spec.loader.exec_module(bc)
        old=os.environ.get(VAR);os.environ[VAR]='stub-hang'
        try:
            bc.set_test_env({'mode':'smoke','test_env':{VAR:'stub-hang'}});self.assertNotIn(VAR,bc.child_env())   # inherited value dropped
            bc.set_test_env({'mode':'selftest','test_env':{VAR:'stub-hang'}});self.assertEqual(bc.child_env()[VAR],'stub-hang')
            for bad in ({'mode':'selftest','test_env':{VAR:'Bad Value'}},{'mode':'selftest','test_env':{'PATH':'/x'}},{'mode':'selftest','test_env':'x'},
                        {'mode':'selftest','test_env':{}},{'mode':'selftest','test_env':{VAR:3}}):
                with self.subTest(plan=bad):
                    with self.assertRaises(ValueError):bc.set_test_env(bad)
                    self.assertNotIn(VAR,bc.child_env())
            bc.set_test_env({'mode':'selftest'});self.assertNotIn(VAR,bc.child_env())
        finally:
            bc.set_test_env({})
            if old is None:os.environ.pop(VAR,None)
            else:os.environ[VAR]=old
    def test_stub_plan_is_checked_and_an_edit_is_refused(self):
        import bench, copy
        project,case,spec=fixture_stub();identity=bm.project_identity(ROOT,project,case);env={'cpus':4,'cpuset':[0,1,2,3],'smt_siblings':[],'reduced':False,'multicore':'PASS'}
        plan=bd.stub_plan(ROOT,case,POL,env,7,spec,project,identity)
        self.assertEqual(plan['mode'],'selftest');self.assertEqual(plan['test_floor_seconds'],2);self.assertEqual(plan['memory'],[])
        self.assertEqual(plan['test_env'],{VAR:'stub-hang'})
        (t,)=[t for s in plan['sessions'] for t in s['trials']]
        self.assertEqual((t['variant'],t['workers'],t['scope'],t['tier'],t['selector'],t['call_deadline_reason']),('py-library','direct','caller','tiny','m4','stub-hang'))
        self.assertEqual(t['call_deadline_seconds'],2.0)
        self.assertIs(bd.check_selftest_plan(plan,case,POL,env,bench.plan_digest(plan),project=project,identity=identity,root=ROOT),plan)
        for edit in (lambda p:p.update(test_floor_seconds=1),lambda p:p['sessions'][0]['trials'][0].update(variant='py-optimized'),
                     lambda p:p.update(test_env={VAR:'stub-overrun'}),lambda p:p.update(test_env={VAR:'not-declared'}),
                     lambda p:p['sessions'][0]['trials'].append(dict(t,trial_id='x'))):
            bad=copy.deepcopy(plan);edit(bad)
            with self.subTest(edit=edit),self.assertRaises(GateError):bd.check_selftest_plan(bad,case,POL,env,bench.plan_digest(bad),project=project,identity=identity,root=ROOT)
        with self.assertRaises(GateError):bd.check_selftest_plan(plan,case,POL,env,bench.plan_digest(plan),project=project,identity=identity)   # no root: no stub spec

class ReviewFixTests(unittest.TestCase):
    """Task 6 review fix round: the stub selftests run in the cases suite; the control uses the same test floor; the
    overhead needs the case seed (no example seed in framework code) and sizes.small >= 256."""
    def test_cases_suite_runs_the_stub_selftests(self):
        import ast
        src=(ROOT/'tools/bench_deadline.py').read_text();tree=ast.parse(src)
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='stub_suites')
        called={c.func.id for c in ast.walk(fn) if isinstance(c,ast.Call) and isinstance(c.func,ast.Name)}
        self.assertTrue({'_stub_run_selftest','_stub_check_selftest'}<=called)
        self.assertIn('bench_deadline.stub_suites(root,run_dir)',(ROOT/'tools/bench.py').read_text())
    def test_control_check_uses_the_same_test_floor(self):
        src=(ROOT/'tools/bench_deadline.py').read_text()
        self.assertIn("control=one({'mode':'selftest','test_floor_seconds':TEST_FLOOR}",src)
    def test_reference_code_requires_the_case_seed_and_256_rows(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('bc_rf',ROOT/'container/bench-coordinator.py');bc=importlib.util.module_from_spec(spec);spec.loader.exec_module(bc)
        self.assertNotIn('20261007',bc.REFERENCE_CODE);self.assertEqual(bc.OVERHEAD_ROWS,256)
        self.assertIn('sizes.small >=',(ROOT/'container/bench-coordinator.py').read_text())

class DeclaredStubTests(unittest.TestCase):
    """FR1 (FS1 F2), FR3: bench selftest runs a stub suite only for a stub that a project protocol declares; a malformed
    declaration raises (selftest_cases then records one BLOCKED suite: tests/unit/test_bench_stub_suites.py)."""
    def test_declared_reasons_follow_the_project_protocols(self):
        import bench
        from unittest import mock
        with mock.patch.object(bench,'example_projects',lambda root:[]):self.assertEqual(bd.declared_stub_reasons(ROOT),[])
        with mock.patch.object(bench,'example_projects',lambda root:[FIXTURE]):self.assertEqual(bd.declared_stub_reasons(ROOT),['stub-hang','stub-overrun'])
    def test_a_malformed_project_declaration_raises(self):
        import bench
        from unittest import mock
        with mock.patch.object(bench,'example_projects',lambda root:['tests/fixtures/no-such-project']),self.assertRaises(GateError):bd.declared_stub_reasons(ROOT)
    def test_a_stub_without_a_matching_case_raises(self):
        import bench, copy
        from unittest import mock
        proto=copy.deepcopy(bm.load_protocol(ROOT,FIXTURE));proto['stubs'][0]['variant']='c-threads'     # no case of the project has this variant
        with mock.patch.object(bench,'example_projects',lambda root:[FIXTURE]),mock.patch.object(bm,'load_protocol',lambda root,p:proto),\
             self.assertRaisesRegex(GateError,'no case'):bd.declared_stub_reasons(ROOT)
    def test_the_cases_suite_runs_the_control_and_records_the_stub_suites(self):
        import ast
        src=(ROOT/'tools/bench.py').read_text();tree=ast.parse(src)
        body=ast.get_source_segment(src,next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='selftest_cases'))
        self.assertIn('stub,not_run=bench_deadline.stub_suites(root,run_dir);suites.update(stub)',body)
        self.assertIn("suites['call-deadline']=bench_deadline.selftest_suite(root,run_dir)",body)    # the framework control suite always runs

if __name__=='__main__':unittest.main()
