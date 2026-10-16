import hashlib, json, tempfile, unittest
from pathlib import Path
from benchlab.workload import load_adapter, load_case_adapter, OfflineJob
CASES=Path('/src/benchmarks/performance/cases')
ROWS=(('py-reference','direct'),('py-optimized','direct'),('py-threads',2),('py-processes',2))

def dataset(adapter,n,seed=11):
    data=adapter.synthesize(n,seed);p=Path(tempfile.mkdtemp())/'data.bin';p.write_bytes(data)
    return {'path':str(p),'sha256':hashlib.sha256(data).hexdigest()}

class WorkloadTests(unittest.TestCase):
    def test_control_adapters_round_trip_every_variant(self):
        for name in ('bench-control-spin','bench-control-wait','bench-control-touch'):
            a=load_case_adapter(json.loads((CASES/f'{name}.json').read_text()));data=a.load(dataset(a,40));ref=a.reference(data)
            for variant,workers in ROWS:
                w=1 if workers=='direct' else workers;res=a.materialize(a.run(a.prepare(data,variant,w),variant,w))
                with self.subTest(case=name,variant=variant):self.assertEqual(a.work_units(res),40);self.assertTrue(a.validate(res,ref,data)['eligible'])
    def test_record_scan_adapter_round_trip(self):
        a=load_case_adapter(json.loads((CASES/'record-scan.json').read_text()));data=a.load(dataset(a,300));ref=a.reference(data)
        for variant in ('py-reference','py-optimized'):
            res=a.materialize(a.run(a.prepare(data,variant),variant,1))
            with self.subTest(variant=variant):self.assertEqual(a.work_units(res),300);self.assertTrue(a.validate(res,ref,data)['eligible'])
    def test_dataset_digest_is_checked(self):
        a=load_case_adapter(json.loads((CASES/'bench-control-spin.json').read_text()));d=dataset(a,2);d['sha256']='0'*64
        with self.assertRaises(ValueError):a.load(d)
    def test_dropped_rows_give_fewer_work_units(self):
        a=load_case_adapter(json.loads((CASES/'bench-control-spin.json').read_text()));data=a.load(dataset(a,10))
        res=a.materialize(a.run(a.prepare(data,'py-optimized'),'py-optimized',1));res['values']=res['values'][:9]
        self.assertEqual(a.work_units(res),9);v=a.validate(res,a.reference(data),data);self.assertFalse(v['eligible']);self.assertEqual(v['reduction'],'ROW_COUNT')
    def test_offline_job_kind_is_bounded(self):
        job=OfflineJob(['python3','-c','print(7)'],timeout=5);self.assertEqual(job.work_units(job.run(None,'py-reference',1)),1)
        with self.assertRaises(TimeoutError):OfflineJob(['python3','-c','import time;time.sleep(5)'],timeout=0.5).run(None,'py-reference',1)
    def test_adapter_contract_is_enforced(self):
        import sys, types
        from benchlab.controlcase import Spin
        stub=types.ModuleType('stub_adapter_case')
        class NoValidate(Spin):validate=None
        class NoRunChunk(Spin):run_chunk=None
        stub.NoValidate=NoValidate;stub.NoRunChunk=NoRunChunk;sys.modules['stub_adapter_case']=stub
        with self.assertRaises(TypeError) as ctx:load_adapter('stub_adapter_case:NoValidate',{'rounds':1})
        self.assertIn('validate',str(ctx.exception))
        load_adapter('stub_adapter_case:NoRunChunk',{'rounds':1})                     # direct-only case: pool methods not needed
        with self.assertRaises(TypeError) as ctx:load_adapter('stub_adapter_case:NoRunChunk',{'rounds':1},pooled=True)
        self.assertIn('run_chunk',str(ctx.exception))
    def test_stdlib_list_matches_the_image(self):
        """plan L7: tools/bench_model.py STDLIB_313 is the container interpreter's list (read by path; no host import)."""
        import ast, sys
        tree=ast.parse(Path('/src/tools/bench_model.py').read_text());found={}
        for node in tree.body:
            if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name) and node.targets[0].id in ('STDLIB_313','WHEEL_MODULES'):
                found[node.targets[0].id]=ast.literal_eval(node.value.args[0])
        self.assertEqual(set(found['STDLIB_313']),set(sys.stdlib_module_names))
        self.assertTrue(any(n.startswith('_') for n in found['STDLIB_313']))
        tops={p.stem if p.suffix in ('.py','.so') else p.name for p in Path('/opt/bench-python').iterdir()
              if (p.is_dir() and (p/'__init__.py').is_file()) or p.suffix=='.py' or p.suffix=='.so'}
        tops={t.split('.')[0] for t in tops}
        self.assertEqual(tops-set(found['WHEEL_MODULES']),set())       # every importable bench wheel module is reserved
    def test_coordinator_reserves_the_same_names(self):
        import importlib.util, sys
        spec=importlib.util.spec_from_file_location('bc_container','/src/container/bench-coordinator.py');bc=importlib.util.module_from_spec(spec);spec.loader.exec_module(bc)
        self.assertTrue(set(sys.stdlib_module_names)<=bc.reserved_modules());self.assertIn('benchlab',bc.reserved_modules())
    def test_framework_packages_and_startup_hooks_are_reserved(self):
        """Review fix: every top-level framework package and both startup hooks are reserved on the host and in the coordinator."""
        import ast, importlib.util
        tree=ast.parse(Path('/src/tools/bench_model.py').read_text())
        found={n.targets[0].id:ast.literal_eval(n.value.args[0]) for n in tree.body if isinstance(n,ast.Assign) and len(n.targets)==1
               and isinstance(n.targets[0],ast.Name) and n.targets[0].id in ('FRAMEWORK_PACKAGES','STARTUP_HOOKS')}
        tops={p.name.split('.')[0] for p in Path('/src/benchmarks/performance/python').iterdir() if not p.name.startswith(('.','__'))}
        self.assertEqual(tops-set(found['FRAMEWORK_PACKAGES']),set());self.assertEqual(set(found['STARTUP_HOOKS']),{'sitecustomize','usercustomize'})
        spec=importlib.util.spec_from_file_location('bc_reserved','/src/container/bench-coordinator.py');bc=importlib.util.module_from_spec(spec);spec.loader.exec_module(bc)
        self.assertTrue(tops|{'sitecustomize','usercustomize'}<=bc.reserved_modules())

class NoMarketHookTests(unittest.TestCase):
    """FR3: the market hook of the example project left the framework (FR3 handoff list: MarketHookTests and
    MarketInheritTests move with it). The framework loader never reads a market variable and pyperf workers inherit none."""
    def test_the_loader_ignores_a_market_variable(self):
        import os, sys, types
        mod=types.ModuleType('bench_fake_plain_adapter')
        class Fake:
            def __init__(self,params):self.params=params
            def with_market(self,rate,items):raise AssertionError('the framework must not call with_market')   # NEG: the example's former hook
        for m in ('load','prepare','run','work_units','validate','synthesize','slice','slice_result','materialize','reference','digest'):setattr(Fake,m,lambda self,*a:None)
        mod.Fake=Fake;sys.modules['bench_fake_plain_adapter']=mod;self.addCleanup(sys.modules.pop,'bench_fake_plain_adapter',None)
        saved=os.environ.get('SAFE_C_BENCH_MARKET');os.environ['SAFE_C_BENCH_MARKET']='/nonexistent/market.json'
        self.addCleanup(lambda:os.environ.update({'SAFE_C_BENCH_MARKET':saved}) if saved is not None else os.environ.pop('SAFE_C_BENCH_MARKET',None))
        a=load_adapter('bench_fake_plain_adapter:Fake',{'x':1});self.assertEqual(a.bench_ref,('bench_fake_plain_adapter:Fake',{'x':1}))
    def test_pyperf_workers_inherit_no_market_variable(self):
        from benchlab import kernel_trial
        self.assertNotIn('SAFE_C_BENCH_MARKET',kernel_trial.INHERIT.split(','))
        self.assertIn('SAFE_C_BENCH_SPEC',kernel_trial.INHERIT.split(','))
