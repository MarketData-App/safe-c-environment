import argparse, json, shutil, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from evidence import GateError
import bench, bench_model as bm
REQUIRED=('load','prepare','run','work_units','validate','synthesize','slice','slice_result','materialize','reference','digest')

def sandbox():
    d=Path(tempfile.mkdtemp());(d/'benchmarks/performance').mkdir(parents=True)
    shutil.copytree(ROOT/'benchmarks/performance/cases',d/'benchmarks/performance/cases');shutil.copytree(ROOT/'schemas',d/'schemas')
    (d/'benchmarks/performance/python/tests').mkdir(parents=True);return d

class BenchNewTests(unittest.TestCase):
    def test_scaffold_is_python_only_and_valid(self):
        d=sandbox();paths=bench.new_case(d,'order-book-replay')
        case=bm.load_case(d,'order-book-replay')
        self.assertEqual({v['id']:v['status'] for v in case['variants']},{'py-reference':'implemented','py-optimized':'same-as-reference'})
        self.assertTrue(all(Path(p).is_file() for p in paths.values()));bm.case_rules(d,case)
        self.assertEqual(sorted({p.suffix for p in d.rglob('*') if p.is_file() and 'schemas' not in p.parts and 'cases' not in p.parts}),['.py'])   # no C or header file anywhere
        text=Path(paths['adapter']).read_text();self.assertTrue(all(f'def {m}(' in text for m in REQUIRED))
    def test_project_scaffold_registers_the_case(self):
        d=sandbox();(d/'proj').mkdir();paths=bench.new_case(d,'order-book-replay',project_dir='proj')
        self.assertTrue(all(p.startswith(str(d/'proj/benchmarks/project')) for p in paths.values()))
        bench.new_case(d,'fill-simulator',project_dir='proj')
        self.assertEqual(bm.project_bench(d,'proj')['cases'],['fill-simulator','order-book-replay'])
        case=bm.load_case(d,'order-book-replay','proj');self.assertEqual(case['opportunity_record'],'benchmarks/project/cases/order-book-replay.opportunity.json')
        self.assertIsNotNone(bm.load_opportunity(d,case,'proj'))
    def test_scaffold_refuses_bad_ids_and_existing_cases(self):
        d=sandbox()
        for bad in ['Bad','ab','x'*50,'../escape','c-kernel_']:
            with self.subTest(bad=bad),self.assertRaises(GateError):bench.new_case(d,bad)
        with self.assertRaises(GateError):bench.new_case(d,'bench-control-spin')
        (d/'proj').mkdir()
        with self.assertRaises(GateError):bench.new_case(d,'bench-control-spin',project_dir='proj')   # framework id collision
        for bad in ('../x','/abs','a//b'):
            with self.subTest(project=bad),self.assertRaises(GateError):bench.new_case(d,'order-book-replay',project_dir=bad)
    def test_parser_has_new_validate_check_and_project(self):
        p=argparse.ArgumentParser();bench.configure_parser(p)
        self.assertEqual(p.parse_args(['new','--case','abc-def']).case,'abc-def');self.assertEqual(p.parse_args(['validate','--case','abc']).operation,'validate')
        a=p.parse_args(['check','--check','b06-prerequisite-oracle','--project','examples/x']);self.assertEqual((a.check,a.project),('b06-prerequisite-oracle','examples/x'))
        self.assertEqual(p.parse_args(['plan','--case','bench-control-spin','--project','p']).project,'p')
    def test_new_inside_a_project_root_writes_only_project_files(self):
        import contextlib, io
        d=sandbox();(d/'project.json').write_text('{}')
        with contextlib.redirect_stdout(io.StringIO()):code=bench.new(d,argparse.Namespace(case='order-book-replay',project=None,format='json'))
        self.assertEqual(code,0);self.assertEqual(bm.project_bench(d,'.')['cases'],['order-book-replay'])
        self.assertFalse((d/'benchmarks/performance/cases/order-book-replay.json').exists())
    def test_scaffold_name_is_neutral_not_the_directory_name(self):
        d=sandbox();(d/'jdoe').mkdir();bench.new_case(d,'order-book-replay',project_dir='jdoe')
        self.assertEqual(bm.project_bench(d,'jdoe')['name'],'project')       # owner privacy rule: no login-like name in a tracked file
    def test_half_declared_project_tree_is_refused(self):
        d=sandbox();cases=d/'proj/benchmarks/project/cases';cases.mkdir(parents=True)
        (cases/'other-case.json').write_text(json.dumps(bm.load_case(ROOT,'bench-control-spin')|{'case_id':'other-case'}))
        with self.assertRaises(GateError) as ctx:bench.new_case(d,'order-book-replay',project_dir='proj')
        self.assertIn('bench.json',str(ctx.exception));self.assertEqual([p.name for p in cases.iterdir()],['other-case.json'])
    def test_a_failed_scaffold_leaves_nothing_behind(self):
        from unittest import mock
        d=sandbox();(d/'proj').mkdir();calls=[]
        real=bench.atomic_json
        def flaky(path,value):
            calls.append(path)
            if len(calls)==2:raise OSError('disk full')
            return real(path,value)
        with mock.patch.object(bench,'atomic_json',flaky),self.assertRaises(OSError):bench.new_case(d,'order-book-replay',project_dir='proj')
        self.assertEqual([str(p.relative_to(d)) for p in (d/'proj').rglob('*')],[])
    def test_framework_package_names_are_refused(self):
        d=sandbox()
        for bad in ('tests','benchlab','sitecustomize','usercustomize'):
            with self.subTest(bad=bad),self.assertRaises(GateError):bench.new_case(d,bad,project_dir=None)
