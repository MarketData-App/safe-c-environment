import json, sys, unittest, copy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from evidence import GateError
from schema_check import validate
import bench_model as bm

def load(rel):return json.loads((ROOT/rel).read_text())

class BenchSchemaTests(unittest.TestCase):
    def test_tracked_bench_files_validate(self):
        for kind,rel in [('bench-policy','safety/performance-policy.json'),('bench-fixtures','safety/performance-fixtures.json'),
                         ('bench-case','benchmarks/performance/cases/bench-control-spin.json'),('bench-case','benchmarks/performance/cases/record-scan.json'),
                         ('bench-case','tests/unit/data/bench-plan-case.json'),('bench-opportunity','tests/unit/data/bench-plan-case.opportunity.json')]:
            with self.subTest(rel=rel):validate(ROOT,kind,load(rel))
    def test_policy_holds_no_project_tolerance(self):
        # FR3: the example project's provisional tolerance values move with the example (FR3 handoff list)
        self.assertNotIn('tolerances',json.loads((ROOT/'safety/performance-policy.json').read_text()))
    def test_policy_limits_cannot_be_loosened(self):
        for path,value in [(('protocol','max_request_records'),20000),(('job_deadlines','long_check'),20000),(('budgets','decision_cap_seconds'),36000),(('envelope','cpus'),8)]:
            v=json.loads((ROOT/'safety/performance-policy.json').read_text());v[path[0]][path[1]]=value
            with self.subTest(path=path),self.assertRaises(GateError):validate(ROOT,'bench-policy',v)
        v=json.loads((ROOT/'safety/performance-policy.json').read_text())
        for key in ('tolerances','solver','before_run_required'):
            with self.subTest(key=key),self.assertRaises(GateError):validate(ROOT,'bench-policy',dict(v,**{key:{}}))
    def aggregate(self):
        return {'schema_version':2,'run_id':'0'*32,'case':'fixture-case','dataset_sha256':'a'*64,'rows':13230,
                'summary':{'crosscheck':{'s1':{'f1':{'count':0,'median':None,'p90':None}}}},
                'timings':[],'counters':{'cpu_usage_usec':0,'memory_peak_bytes':None},'exceptions':[],
                'output_digests':{'result_sha256':'b'*64,'reference_sha256':'c'*64},'status':'VALID'}
    def test_local_aggregate_accepts_the_closed_document(self):
        validate(ROOT,'bench-local-aggregate',self.aggregate())
        validate(ROOT,'bench-local-aggregate',dict(self.aggregate(),summary=None,status='INVALID_EXPERIMENT'))
    def test_local_aggregate_rejects_free_strings_and_row_digests(self):
        for mutate in [lambda a:a.update(note='value 412.35'),lambda a:a['output_digests'].update(row_0_sha256='d'*64),
                       lambda a:a.update(row_digests=['d'*64]),lambda a:a['exceptions'].append({'type':'free text','row_index':3}),
                       lambda a:a.update(case='free text'),lambda a:a.update(summary='value 412.35'),lambda a:a.update(summary=None),
                       lambda a:a.update(extra=None),lambda a:a.update(schema_version=1)]:
            a=self.aggregate();mutate(a)
            with self.assertRaises(GateError):validate(ROOT,'bench-local-aggregate',a)
    def observation(self):
        return {'schema_version':1,'run_id':'0'*32,'trial_id':'b00-r00','block':0,'order':0,'point':'smoke-caller','scope':'caller','mode':'warm',
                'variant':'py-optimized','workers':'direct','tier':'small','phase':'caller','warmup':False,'runner':'safe-c-trial-runner',
                'wall_ns':1,'cpu_usage_usec':1,'cpu_user_usec':1,'cpu_system_usec':0,'nr_throttled':0,'throttled_usec':0,
                'pids_start':1,'pids_end':1,'threads_start':1,'threads_end':1,'loops':1,'work_units':256,'phases':{},
                'result_sha256':'e'*64,'eligible':True,'verdict':{'failures':{}},'memory':None,'unavailable':{}}
    def test_observation_has_no_field_for_forbidden_memory_metrics(self):
        validate(ROOT,'bench-observation',self.observation())
        for key in ['tracemalloc_bytes','summed_rss_peak_bytes','phase_peak_bytes','vms_bytes']:
            o=self.observation();o[key]=1
            with self.subTest(key=key),self.assertRaises(GateError):validate(ROOT,'bench-observation',o)
    def test_pool_records_the_chunk_rule_sizes_and_times(self):
        """Amendment E item 5: the closed pool object holds chunk_rule, chunk_sizes (1-8 items, each >= 1) and chunk_wall_ns."""
        pool={'max_pending':4,'chunks':2,'window':4,'pids_distinct':2,'caller_pid_included':False,'threads':2,'start_method':'spawn','tracker_session_setup':True,
              'chunk_rule':'one-per-worker','chunk_sizes':[128,128],'chunk_wall_ns':[1000,1200]}
        ok=dict(self.observation(),variant='py-processes',workers=2,pool=pool);validate(ROOT,'bench-observation',ok)
        for mutate in [lambda p:p.pop('chunk_sizes'),lambda p:p.update(chunk_sizes=[1]*9),lambda p:p.update(chunk_sizes=[0,256]),
                       lambda p:p.update(chunk_rule='other'),lambda p:p.update(chunk_wall_ns=[-1,5]),lambda p:p.update(chunk_wall_ns=[1]*9)]:
            o=copy.deepcopy(ok);mutate(o['pool'])
            with self.subTest(),self.assertRaises(GateError):validate(ROOT,'bench-observation',o)
    NATIVE_POOL={'chunk_rule':'one-per-worker','chunks':2,'chunk_sizes':[128,128],'chunk_wall_ns':[1000,1200]}
    PY_POOL={'max_pending':4,'chunks':2,'window':4,'pids_distinct':1,'caller_pid_included':True,'threads':3,'start_method':'thread','tracker_session_setup':None,
             'chunk_rule':'one-per-worker','chunk_sizes':[128,128],'chunk_wall_ns':[1000,1200]}
    def test_the_native_pool_shape_belongs_to_c_rows(self):
        """N4-A03: only a C row (c-serial, c-threads) may record the native pool shape. A Python or control row with it is
        refused, so check_concurrency_identity never reads a native pool as a Python pool. C1: the Python pool shape (and
        null) stays valid for every variant, as before Task 19; only the shape that Task 19 opened to every variant closes."""
        for variant,workers in (('c-threads',2),('c-serial','direct')):
            with self.subTest(variant=variant):validate(ROOT,'bench-observation',dict(self.observation(),variant=variant,workers=workers,pool=dict(self.NATIVE_POOL)))
        for variant,workers in (('py-threads',2),('py-processes',2),('py-reference','direct'),('py-optimized','direct'),('py-library','direct'),('control','direct')):
            with self.subTest(variant=variant),self.assertRaises(GateError):
                validate(ROOT,'bench-observation',dict(self.observation(),variant=variant,workers=workers,pool=dict(self.NATIVE_POOL)))
        for variant in ('py-threads','c-threads','c-serial','py-reference','control'):
            with self.subTest(variant=variant,shape='python'):
                validate(ROOT,'bench-observation',dict(self.observation(),variant=variant,workers=2,pool=dict(self.PY_POOL)))
                validate(ROOT,'bench-observation',dict(self.observation(),variant=variant,workers=2,pool=None))
    def test_the_identity_check_never_crashes_on_a_pool(self):
        """N4-A03: check_concurrency_identity returns problems (never raises) for every pool shape on every pooled variant,
        also for a shape that the schema refuses."""
        import bench
        plan={'dataset':{'kind':'synthetic'}};policy=bm.load_policy(ROOT)
        for variant in ('py-threads','py-processes','c-threads'):
            for pool in (dict(self.NATIVE_POOL),dict(self.PY_POOL),None,{},{'chunk_rule':'one-per-worker'},{'max_pending':1}):
                o=dict(self.observation(),variant=variant,workers=2,pool=pool)
                with self.subTest(variant=variant,pool=pool):self.assertIsInstance(bench.check_concurrency_identity([o],plan,policy),list)
        o=dict(self.observation(),variant='py-threads',workers=2,pool=dict(self.NATIVE_POOL))
        self.assertIn('b00-r00: pool identity not recorded in the Python pool shape',bench.check_concurrency_identity([o],plan,policy))
    def test_c_row_needs_an_approved_opportunity_record(self):
        case=copy.deepcopy(load('tests/unit/data/bench-plan-case.json'))
        bm.case_rules(ROOT,case)
        for row in case['variants']:
            if row['id']=='c-serial':row['status']='implemented'
        with self.assertRaises(GateError):bm.case_rules(ROOT,case)
    def test_c_row_record_must_be_approved(self):
        """Review Important 1: a live C row with a PENDING record is refused; the same row with an APPROVED record passes."""
        import shutil, tempfile
        d=Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,d,True)
        shutil.copytree(ROOT/'schemas',d/'schemas');(d/bm.CASES).mkdir(parents=True)
        record=load('tests/unit/data/bench-plan-case.opportunity.json');self.assertEqual(record['approval']['state'],'PENDING')
        case=copy.deepcopy(load('tests/unit/data/bench-plan-case.json'));case['opportunity_record']=f'{bm.CASES}/plan-fixture.opportunity.json'
        for row in case['variants']:
            if row['id']=='c-serial':row['status']='implemented'
        (d/bm.CASES/'plan-fixture.opportunity.json').write_text(json.dumps(record))
        with self.assertRaises(GateError):bm.case_rules(d,case)
        approved=dict(record,approval=dict(record['approval'],state='APPROVED'))
        (d/bm.CASES/'plan-fixture.opportunity.json').write_text(json.dumps(approved))
        self.assertTrue(bm.case_rules(d,case))
    def test_py_library_row_validates_and_is_direct_only(self):
        """Task 9b: a py-library row (language python-library) validates; workers [1] or language python fail case_rules."""
        case=copy.deepcopy(load('tests/unit/data/bench-plan-case.json'))
        case['variants'].append({'id':'py-library','language':'python-library','workers':['direct'],'status':'implemented',
                                 'reason':'a compiled library through a Python binding; per-evaluation Python callback cost included'})
        validate(ROOT,'bench-case',case);self.assertTrue(bm.case_rules(ROOT,case))
        for change in ({'workers':[1]},{'language':'python'}):
            bad=copy.deepcopy(case);bad['variants'][-1].update(change)
            with self.subTest(change=change),self.assertRaises(GateError):validate(ROOT,'bench-case',bad);bm.case_rules(ROOT,bad)
        wrong=copy.deepcopy(case);wrong['variants'][1]['language']='python-library'
        with self.assertRaises(GateError):bm.case_rules(ROOT,wrong)
    def test_case_parameters_are_labeled(self):
        p=load('tests/unit/data/bench-plan-case.json')['parameters']
        self.assertEqual((p['p1']['value'],p['p1']['label'],p['p2']['value'],p['p3']['value']),(0.04,'assumption',0.012,100))   # FR3-03: neutral names
