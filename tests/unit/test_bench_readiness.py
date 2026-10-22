import json, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import bench_readiness as br
KEYS=['benchmark_tooling','measurement_qualification','multicore_qualification','demo_experiment_execution','demo_performance_evidence',
      'combined_local_checks','independent_enforcement','actual_django_workload_tested','native_adoption_authorized','production_authorized']
DEV={'combined_local_checks':'PASSED','independent_enforcement':'PENDING'}
def report(identity,suites,doctor='PASS',multicore='PASS'):
    return {'source_identity':identity,'commands':['./tools/safety ci'],'gates':[{'name':'bench-doctor','status':doctor,'details':{'envelope':{'multicore':multicore}}},
            {'name':'bench-selftest','status':'PASS','details':suites}]}
ALL={**{k:'PASS' for k in ('B01','B02','B03','B04','B05','B09','B10','B11','B12','B13','B15','B17')},'not_run':[]}   # EX17-A02: the ci gate records not_run

class ReadinessTests(unittest.TestCase):
    def root(self,t,rep=None):
        r=Path(t);(r/'artifacts/bench').mkdir(parents=True)
        if rep:(r/'artifacts/bootstrap-report.json').write_text(json.dumps(rep))
        return r
    def test_exact_axes_in_brief_order(self):
        with tempfile.TemporaryDirectory() as t:self.assertEqual(list(br.performance_axes(self.root(t),'a'*64,DEV)),KEYS)
    def test_false_axes(self):
        with tempfile.TemporaryDirectory() as t:
            a=br.performance_axes(self.root(t),'a'*64,DEV)
            for k in br.FALSE_AXES:self.assertIs(a[k],False)
    def test_no_current_evidence(self):
        with tempfile.TemporaryDirectory() as t:
            a=br.performance_axes(self.root(t,report('b'*64,ALL)),'a'*64,DEV)
            self.assertEqual((a['benchmark_tooling'],a['measurement_qualification'],a['multicore_qualification'],a['demo_experiment_execution']),('BLOCKED','BLOCKED','BLOCKED','NOT_EXECUTED'))
    def test_current_suites(self):
        with tempfile.TemporaryDirectory() as t:
            a=br.performance_axes(self.root(t,report('a'*64,ALL)),'a'*64,DEV)
            self.assertEqual((a['benchmark_tooling'],a['measurement_qualification'],a['multicore_qualification']),('PASSED','PASSED','PASSED'))
            self.assertEqual(a['demo_experiment_execution'],'PARTIAL')       # B17 passed, no demo decision run yet
    def test_missing_multicore_is_blocked(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(br.performance_axes(self.root(t,report('a'*64,ALL,multicore='BLOCKED')),'a'*64,DEV)['multicore_qualification'],'BLOCKED')
    def test_failed_measurement_suite(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(br.performance_axes(self.root(t,report('a'*64,dict(ALL,B15='FAIL'))),'a'*64,DEV)['measurement_qualification'],'FAILED')
    def test_developer_axes_pass_through(self):
        with tempfile.TemporaryDirectory() as t:
            a=br.performance_axes(self.root(t),'a'*64,DEV);self.assertEqual((a['combined_local_checks'],a['independent_enforcement']),('PASSED','PENDING'))
    def test_readiness_wires_the_axes(self):self.assertIn("performance_axes(",(ROOT/'tools/developer_acceptance.py').read_text())

# ---- Beyond the brief's tests (Task 24 implementer): behavior of the demo axes, the details, the report line and the readiness result ----
import os, shutil
from unittest import mock
import bench_evidence as be
from schema_check import validate
from evidence import GateError
ID='a'*64;OTHER='b'*64
DEMO_PROJECT='examples/demo-project';DEMO_CASE='demo-case'      # a synthetic example project, found by layout (bench.example_projects)

def example_layout(root,cases=(DEMO_CASE,)):
    p=root/DEMO_PROJECT/'benchmarks/project';p.mkdir(parents=True,exist_ok=True)
    (p/'bench.json').write_text(json.dumps({'schema_version':1,'name':'demo-project','cases':list(cases)}))

def full_record(run_id,identity,name,outcome='INCONCLUSIVE'):
    """A bench-decision record of the closed schema for one rule policy (the shape bench_decide.decision_record writes)."""
    demo=name!='owner'
    return {'schema_version':1,'run_id':run_id,'case':DEMO_CASE,'local':False,
            'policy':{'name':name,'sha256':'a'*64,'demonstration_only':demo,'filled':demo},'adoption_authorized':False,'cgroup_identity_unrecorded':False,
            'qualification':None,'sensitivity':None,'windows':None,'source_identity_run':identity,'source_identity_decision':identity,'stale':False,
            'image_id':'sha256:'+'c'*64,'evidence_quality':'decision','outcome':outcome,'rule':8,'adoption_outcome':'INCONCLUSIVE',
            'demonstration_outcome':outcome if demo else None,'adoption_note':'Python retained pending evidence','reasons':[],'comparisons':[],'items':[],
            'summary':{k:'n/a' for k in ('problem','best_python','best_c','size_range','caller_latency','cpu','memory','uncertainty','missing_evidence',
                                         'complexity','next_action','cpu_tradeoff','assumptions','frequency')}|{'routes':[]}}

def demo_run(root,run_id='1'*32,identity=ID,status='VALID',mode='decision',eligible=True,created='2026-10-11T10:00:00+00:00',policy=None,
             records=True,quality='decision',outcome='INCONCLUSIVE',kind='synthetic',size='large',case=DEMO_CASE,project=DEMO_PROJECT,full=False):
    """A synthetic run directory: plan with one primary trial (and its warmup), observations, a run record bound by its
    evidence and record digests (bench_evidence), and one decision record per rule policy (full: schema-valid records).
    The defaults are the demo decision run of Task 35: an example project's case, synthetic large, mode decision."""
    d=root/'artifacts/bench'/run_id;d.mkdir(parents=True)
    plan={'case':case,'project_dir':project,'sessions':[{'class':'primary','point':'p','trials':[{'trial_id':'p-s00-w00','warmup':True},{'trial_id':'p-s00-b00-00','warmup':False}]},
                                                  {'class':'exploratory','point':'e','trials':[{'trial_id':'e-s01-b00-00','warmup':False}]}]}
    if policy:plan['policy']=policy
    (d/'plan.json').write_text(json.dumps(plan))
    (d/'observations.jsonl').write_text(json.dumps({'trial_id':'p-s00-b00-00','eligible':eligible})+'\n')
    run={'run_id':run_id,'created_at':created,'case':case,'mode':mode,'source_identity':identity,'status':status,'dataset':{'kind':kind,'size':size},
         'plan':{'project_dir':project},'evidence_digests':be.digest_files(d)}
    run[be.RECORD_KEY]=be.run_record_sha256(run);(d/'run.json').write_text(json.dumps(run))
    if records:
        for n in br.RULE_POLICIES:
            rec=full_record(run_id,identity,n,outcome) if full else {'run_id':run_id,'policy':{'name':n},'stale':False,'source_identity_run':identity,
                                                                     'source_identity_decision':identity,'evidence_quality':quality,'outcome':outcome}
            (d/f'decision-{n}.json').write_text(json.dumps(rec))
    return d

def control_run(root,run_id='9'*32,created='2026-10-11T23:00:00+00:00',**over):
    """A framework control-case decision run (as every ci writes: bench-control-spin, no project, synthetic small), decided with valid records."""
    return demo_run(root,run_id,case='bench-control-spin',project=None,size='small',created=created,**over)

def owner_record(root,run_id='2'*32,identity=ID,verdicts=('KEEP_PYTHON',)*7+('PREFER_C','INCONCLUSIVE','INVALID_EXPERIMENT'),stale=False):
    d=root/'artifacts/bench'/run_id;d.mkdir(parents=True,exist_ok=True)
    p=d/'decision-fixture-request-threshold.json'
    p.write_text(json.dumps({'run_id':run_id,'stale':stale,'source_identity_run':identity,'source_identity_decision':identity,'units':[{'verdict':v} for v in verdicts]}))
    return p

class DemoAxisTests(unittest.TestCase):
    def root(self,t,rep=None):
        r=ReadinessTests.root(self,t,rep);example_layout(r);return r
    def axes(self,root):return br.performance_axes(root,ID,DEV)
    def test_a_complete_valid_demo_run_is_complete_and_decision_grade(self):
        with tempfile.TemporaryDirectory() as t,mock.patch.object(br,'validate'),mock.patch.object(br,'matrix_missing',return_value=[]):
            r=self.root(t,report(ID,ALL));demo_run(r);a=self.axes(r)
            self.assertEqual((a['demo_experiment_execution'],a['demo_performance_evidence']),('COMPLETE','DECISION_GRADE'))   # honestly INCONCLUSIVE records
    def test_missing_matrix_cells_or_no_b17_are_partial(self):
        with tempfile.TemporaryDirectory() as t,mock.patch.object(br,'validate'),mock.patch.object(br,'matrix_missing',return_value=['cell c-threads x2 missing']):
            r=self.root(t,report(ID,ALL));demo_run(r);a=self.axes(r)
            self.assertEqual((a['demo_experiment_execution'],a['demo_performance_evidence']),('PARTIAL','DECISION_GRADE'))
        with tempfile.TemporaryDirectory() as t,mock.patch.object(br,'validate'),mock.patch.object(br,'matrix_missing',return_value=[]):
            r=self.root(t,report(ID,dict(ALL,B17='FAIL')));demo_run(r);self.assertEqual(self.axes(r)['demo_experiment_execution'],'PARTIAL')
            (r/'artifacts/bootstrap-report.json').unlink();self.assertEqual(self.axes(r)['demo_experiment_execution'],'PARTIAL')
    def test_without_the_task_30_matrix_check_the_matrix_is_never_complete(self):
        with mock.patch.dict(sys.modules,{'bench_phase3':None}):
            self.assertEqual(br.matrix_missing(ROOT,{'case':'bench-control-spin'},[]),[br.MATRIX_UNAVAILABLE])
    def test_an_invalid_or_incomplete_newest_decision_run_is_inconclusive(self):
        for over in ({'status':'INVALID_EXPERIMENT'},{'status':'BLOCKED'},{'records':False},{'quality':'stale'},{'outcome':'INVALID_EXPERIMENT'}):
            with self.subTest(over=over),tempfile.TemporaryDirectory() as t,mock.patch.object(br,'validate'),mock.patch.object(br,'matrix_missing',return_value=[]):
                r=self.root(t,report(ID,ALL));demo_run(r,**over);a=self.axes(r)
                self.assertEqual(a['demo_performance_evidence'],'INCONCLUSIVE')
                self.assertEqual(a['demo_experiment_execution'],'PARTIAL')       # B17 passed and a run exists, but it is not VALID
        with tempfile.TemporaryDirectory() as t,mock.patch.object(br,'validate'):     # an ineligible primary trial: incomplete evidence
            r=self.root(t,report(ID,ALL));demo_run(r,eligible=False);self.assertEqual(self.axes(r)['demo_performance_evidence'],'INCONCLUSIVE')
        self.assertEqual(br.primary_missing({'sessions':[{'class':'primary','trials':[{'trial_id':'x','warmup':False}]}]},[]),['x'])
        self.assertEqual(br.primary_missing({'sessions':[{'class':'secondary','trials':[]}]},[]),['no primary point in the plan'])
    def test_a_changed_run_record_or_evidence_file_is_not_valid(self):
        with tempfile.TemporaryDirectory() as t,mock.patch.object(br,'validate'),mock.patch.object(br,'matrix_missing',return_value=[]):
            r=self.root(t,report(ID,ALL));d=demo_run(r);run=json.loads((d/'run.json').read_text());run['created_at']='2026-10-11T11:00:00+00:00'
            (d/'run.json').write_text(json.dumps(run));self.assertEqual(self.axes(r)['demo_performance_evidence'],'INCONCLUSIVE')
        with tempfile.TemporaryDirectory() as t,mock.patch.object(br,'validate'),mock.patch.object(br,'matrix_missing',return_value=[]):
            r=self.root(t,report(ID,ALL));d=demo_run(r);(d/'observations.jsonl').write_text(json.dumps({'trial_id':'p-s00-b00-00','eligible':True,'x':1})+'\n')
            self.assertEqual(self.axes(r)['demo_performance_evidence'],'INCONCLUSIVE')
    def test_a_decision_record_that_fails_its_schema_is_not_valid(self):
        with tempfile.TemporaryDirectory() as t,mock.patch.object(br,'matrix_missing',return_value=[]):
            r=self.root(t,report(ID,ALL));demo_run(r);self.assertEqual(self.axes(r)['demo_performance_evidence'],'INCONCLUSIVE')
    def test_the_newest_current_decision_run_decides(self):
        with tempfile.TemporaryDirectory() as t,mock.patch.object(br,'validate'),mock.patch.object(br,'matrix_missing',return_value=[]):
            r=self.root(t);demo_run(r,'1'*32);demo_run(r,'3'*32,status='INVALID_EXPERIMENT',created='2026-10-11T12:00:00+00:00')
            self.assertEqual(self.axes(r)['demo_performance_evidence'],'INCONCLUSIVE')
        with tempfile.TemporaryDirectory() as t,mock.patch.object(br,'validate'),mock.patch.object(br,'matrix_missing',return_value=[]):
            r=self.root(t);demo_run(r,'1'*32,status='INVALID_EXPERIMENT');demo_run(r,'3'*32,created='2026-10-11T12:00:00+00:00')
            demo_run(r,'4'*32,identity=OTHER,status='INVALID_EXPERIMENT',created='2026-10-11T13:00:00+00:00')     # another source identity: never read
            self.assertEqual(self.axes(r)['demo_performance_evidence'],'DECISION_GRADE')
    def test_owner_policy_and_local_runs_are_not_demo_runs(self):
        for over in ({'policy':'fixture-request-threshold'},{'kind':'local'}):
            with self.subTest(over=over),tempfile.TemporaryDirectory() as t,mock.patch.object(br,'validate'),mock.patch.object(br,'matrix_missing',return_value=[]):
                r=self.root(t);demo_run(r,**over);a=self.axes(r)
                self.assertEqual((a['demo_experiment_execution'],a['demo_performance_evidence']),('NOT_EXECUTED','INCONCLUSIVE'))
    def test_smoke_evidence_only_is_exploratory_and_nothing_is_inconclusive(self):
        with tempfile.TemporaryDirectory() as t:
            r=self.root(t);self.assertEqual(self.axes(r)['demo_performance_evidence'],'INCONCLUSIVE')
            demo_run(r,'5'*32,identity=OTHER,mode='smoke',records=False);self.assertEqual(self.axes(r)['demo_performance_evidence'],'INCONCLUSIVE')
            demo_run(r,'6'*32,mode='smoke',status='INVALID_EXPERIMENT',records=False);self.assertEqual(self.axes(r)['demo_performance_evidence'],'INCONCLUSIVE')
            demo_run(r,'7'*32,mode='smoke',records=False);a=self.axes(r)
            self.assertEqual((a['demo_performance_evidence'],a['demo_experiment_execution']),('EXPLORATORY','NOT_EXECUTED'))
        with tempfile.TemporaryDirectory() as t:     # Fix round 1: a control-case smoke run (every ci writes one) is no demo evidence
            r=self.root(t);control_run(r,mode='smoke',records=False);self.assertEqual(self.axes(r)['demo_performance_evidence'],'INCONCLUSIVE')

class DemoRunSelectionTests(unittest.TestCase):          # Fix round 1, T24-APP-01: only the demo decision run of Task 35 counts
    def root(self,t,rep=None):return DemoAxisTests.root(self,t,rep)
    def axes(self,root):return br.performance_axes(root,ID,DEV)
    def test_a_decided_control_case_run_never_raises_the_demo_axes(self):
        with tempfile.TemporaryDirectory() as t,mock.patch.object(br,'validate'),mock.patch.object(br,'matrix_missing',return_value=[]):
            r=self.root(t,report(ID,ALL));control_run(r);a=self.axes(r)
            self.assertEqual((a['demo_experiment_execution'],a['demo_performance_evidence']),('PARTIAL','INCONCLUSIVE'))    # B17 PASS only; no demo run
        with tempfile.TemporaryDirectory() as t:          # with schema-valid records as well (the real schema check)
            r=self.root(t,report(ID,ALL));control_run(r,full=True)
            with mock.patch.object(br,'matrix_missing',return_value=[]):a=self.axes(r)
            self.assertEqual((a['demo_experiment_execution'],a['demo_performance_evidence']),('PARTIAL','INCONCLUSIVE'))
    def test_a_newer_control_case_run_does_not_hide_the_demo_run(self):
        with tempfile.TemporaryDirectory() as t,mock.patch.object(br,'validate'),mock.patch.object(br,'matrix_missing',return_value=[]):
            r=self.root(t,report(ID,ALL));demo_run(r);control_run(r,status='INVALID_EXPERIMENT');control_run(r,'8'*32,records=False)
            a=self.axes(r);self.assertEqual((a['demo_experiment_execution'],a['demo_performance_evidence']),('COMPLETE','DECISION_GRADE'))
    def test_a_run_of_the_demo_case_that_is_not_the_demo_run_is_not_taken(self):
        for over in ({'size':'small'},{'size':'medium'},{'kind':'local'},{'project':None},{'project':'examples/other-project'},{'case':'other-case'},
                     {'policy':'fixture-request-threshold'}):
            with self.subTest(over=over),tempfile.TemporaryDirectory() as t,mock.patch.object(br,'validate'),mock.patch.object(br,'matrix_missing',return_value=[]):
                r=self.root(t,report(ID,ALL));demo_run(r,created='2026-10-11T12:00:00+00:00',**over);a=self.axes(r)
                self.assertEqual((a['demo_experiment_execution'],a['demo_performance_evidence']),('PARTIAL','INCONCLUSIVE'))
                demo_run(r,'3'*32);a=self.axes(r)          # the older real demo run next to it is found
                self.assertEqual((a['demo_experiment_execution'],a['demo_performance_evidence']),('COMPLETE','DECISION_GRADE'))
    def test_a_real_schema_valid_demo_run_is_decision_grade(self):    # T24-APP-03: the real bench-decision schema check, no mock of validate
        with tempfile.TemporaryDirectory() as t:
            r=self.root(t,report(ID,ALL));d=demo_run(r,full=True)
            for n in br.RULE_POLICIES:validate(ROOT,'bench-decision',json.loads((d/f'decision-{n}.json').read_text()))
            with mock.patch.object(br,'matrix_missing',return_value=[]):a=self.axes(r)
            self.assertEqual((a['demo_experiment_execution'],a['demo_performance_evidence']),('COMPLETE','DECISION_GRADE'))

class B17MappingTests(unittest.TestCase):                # Fix round 1, T24-APP-02: an attempted execution that failed is PARTIAL
    def test_a_failed_b17_without_a_demo_run_is_partial(self):
        with tempfile.TemporaryDirectory() as t:
            r=DemoAxisTests.root(self,t,report(ID,dict(ALL,B17='FAIL')));self.assertEqual(br.performance_axes(r,ID,DEV)['demo_experiment_execution'],'PARTIAL')
        for b17 in ('BLOCKED',None):
            with self.subTest(b17=b17),tempfile.TemporaryDirectory() as t:
                suites=dict(ALL,B17=b17) if b17 else {k:v for k,v in ALL.items() if k!='B17'}
                r=DemoAxisTests.root(self,t,report(ID,suites));self.assertEqual(br.performance_axes(r,ID,DEV)['demo_experiment_execution'],'NOT_EXECUTED')

class NotRunTests(unittest.TestCase):                    # EX17-A02: a B17 dimension in cases.json not_run is never COMPLETE
    def test_a_not_run_b17_dimension_is_never_complete(self):
        for not_run,want in ((['B17 c-multiple-workers'],'PARTIAL'),(['stub-run','B17 c-multiple-workers'],'PARTIAL'),(None,'PARTIAL'),('B17',None),
                             ([],'COMPLETE'),(['stub-run','P16 bench-selector-evaluations/selector-no-op'],'COMPLETE')):
            details={k:v for k,v in ALL.items() if k!='not_run'}
            if not_run is not None:details['not_run']=not_run
            with self.subTest(not_run=not_run),tempfile.TemporaryDirectory() as t,mock.patch.object(br,'validate'),mock.patch.object(br,'matrix_missing',return_value=[]):
                r=DemoAxisTests.root(self,t,report(ID,details));demo_run(r)
                self.assertEqual(br.performance_axes(r,ID,DEV)['demo_experiment_execution'],want or 'PARTIAL')
    def test_the_open_b17_entries(self):
        self.assertEqual(br.b17_not_run(report(ID,dict(ALL,not_run=['stub-run','B17 c-multiple-workers']))),['B17 c-multiple-workers'])
        self.assertEqual(br.b17_not_run(report(ID,ALL)),[])
        for bad in ({k:v for k,v in ALL.items() if k!='not_run'},dict(ALL,not_run='B17 x'),dict(ALL,not_run=[1])):
            with self.subTest(details=bad):self.assertIsNone(br.b17_not_run(report(ID,bad)))
        self.assertIsNone(br.b17_not_run(None))
    def test_ci_records_the_not_run_entries_in_the_gate_details(self):
        import bench
        def cases(root,run_dir):
            (Path(run_dir)/'cases.json').write_text(json.dumps({'suites':{},'additions':[],'not_run':[{'suite':'B17 c-multiple-workers','reason':'r'},{'suite':'stub-run','reason':'r'}]}))
            return {'B17':{'status':'PASS','evidence_paths':[]}},[]
        def gate(fn):
            with tempfile.TemporaryDirectory() as t,mock.patch.object(bench,'doctor_probe',lambda root,run_dir:{'status':'PASS','evidence_paths':[]}),\
                 mock.patch.object(bench,'selftest_cases',fn),mock.patch.object(bench,'_quiet',lambda fn,root,args:(0,{'status':'PASS'})),\
                 mock.patch.object(bench,'project_suites',lambda root,run_dir:{}),mock.patch.object(bench,'_privacy_suite',lambda root,run_dir:{'status':'PASS','evidence_paths':[]}):
                (Path(t)/'artifacts').mkdir();gates,_=bench.ci_gates(Path(t))
            return next(g for g in gates if g['name']=='bench-selftest')['details']
        self.assertEqual(gate(cases)['not_run'],['B17 c-multiple-workers','stub-run'])
        self.assertIsNone(gate(lambda root,run_dir:({'B17':{'status':'PASS','evidence_paths':[]}},[]))['not_run'])      # no cases.json: unknown

class QualificationAxisTests(unittest.TestCase):
    def axes(self,t,rep):return br.performance_axes(ReadinessTests.root(self,t,rep),ID,DEV)
    def test_real_failures_are_failed_never_blocked(self):
        with tempfile.TemporaryDirectory() as t:self.assertEqual(self.axes(t,report(ID,ALL,doctor='FAIL'))['benchmark_tooling'],'FAILED')
        with tempfile.TemporaryDirectory() as t:self.assertEqual(self.axes(t,report(ID,dict(ALL,B01='FAIL')))['benchmark_tooling'],'FAILED')
        with tempfile.TemporaryDirectory() as t:
            a=self.axes(t,report(ID,{k:v for k,v in dict(ALL,B04='FAIL').items() if k!='B12'},multicore='BLOCKED'))
            self.assertEqual(a['multicore_qualification'],'FAILED')      # a failed suite stays FAILED on a missing envelope and a missing suite
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(self.axes(t,report(ID,{k:v for k,v in dict(ALL,B02='FAIL').items() if k!='B15'}))['measurement_qualification'],'FAILED')
    def test_missing_or_blocked_evidence_is_blocked_never_passed(self):
        for name,axis in (('B01','benchmark_tooling'),('B15','measurement_qualification'),('B02','measurement_qualification'),('B04','multicore_qualification'),('B12','multicore_qualification')):
            with self.subTest(name=name),tempfile.TemporaryDirectory() as t:
                self.assertEqual(self.axes(t,report(ID,{k:v for k,v in ALL.items() if k!=name}))[axis],'BLOCKED')
            with self.subTest(blocked=name),tempfile.TemporaryDirectory() as t:
                self.assertEqual(self.axes(t,report(ID,dict(ALL,**{name:'BLOCKED'})))[axis],'BLOCKED')
        with tempfile.TemporaryDirectory() as t:self.assertEqual(self.axes(t,report(ID,ALL,doctor='BLOCKED'))['benchmark_tooling'],'BLOCKED')
        rep=report(ID,ALL);rep['gates'][0]['details']={}
        with tempfile.TemporaryDirectory() as t:self.assertEqual(self.axes(t,rep)['multicore_qualification'],'BLOCKED')
        rep=report(ID,ALL);rep['gates']=rep['gates'][1:]
        with tempfile.TemporaryDirectory() as t:
            a=self.axes(t,rep);self.assertEqual((a['benchmark_tooling'],a['multicore_qualification'],a['measurement_qualification']),('BLOCKED','BLOCKED','PASSED'))
    def test_only_a_current_full_ci_report_counts(self):
        for rep in (dict(report(ID,ALL),commands=['./tools/safety check-fast']),dict(report(ID,ALL),commands=[]),dict(report(ID,ALL),commands='./tools/safety ci')):
            with self.subTest(commands=rep['commands']),tempfile.TemporaryDirectory() as t:
                a=self.axes(t,rep);self.assertEqual((a['benchmark_tooling'],a['measurement_qualification'],a['multicore_qualification']),('BLOCKED',)*3)
        with tempfile.TemporaryDirectory() as t:
            r=ReadinessTests.root(self,t);(r/'artifacts/bootstrap-report.json').write_text('{not json')
            self.assertEqual(br.performance_axes(r,ID,DEV)['benchmark_tooling'],'BLOCKED')

class DetailsAndReportLineTests(unittest.TestCase):
    def test_details_without_evidence(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(br.performance_details(ReadinessTests.root(self,t),ID),{'handoff_trial':'NOT_EXECUTED (trial mechanism: no receipt)','unit_verdicts':None})
    def test_unit_verdict_counts_of_the_newest_current_owner_record(self):
        with tempfile.TemporaryDirectory() as t,mock.patch.object(br,'validate'):
            r=ReadinessTests.root(self,t);owner_record(r)
            self.assertEqual(br.performance_details(r,ID)['unit_verdicts'],{'KEEP_PYTHON':7,'PREFER_C':1,'INCONCLUSIVE':1,'INVALID_EXPERIMENT':1})
            p=owner_record(r,'3'*32,verdicts=('INCONCLUSIVE',)*10);os.utime(p,(p.stat().st_mtime+10,)*2)
            self.assertEqual(br.unit_verdicts(r,ID),{'KEEP_PYTHON':0,'PREFER_C':0,'INCONCLUSIVE':10,'INVALID_EXPERIMENT':0})
            p=owner_record(r,'4'*32,stale=True);os.utime(p,(p.stat().st_mtime+20,)*2)
            self.assertIsNone(br.unit_verdicts(r,ID))                       # the newest record is stale: no current counts
            self.assertIsNone(br.unit_verdicts(r,OTHER))
    def test_an_owner_record_that_fails_its_schema_gives_no_counts(self):
        with tempfile.TemporaryDirectory() as t:
            r=ReadinessTests.root(self,t);owner_record(r);self.assertIsNone(br.unit_verdicts(r,ID))
    def test_report_line(self):
        line=br.report_line(report(ID,ALL,doctor='BLOCKED'))
        self.assertEqual(line,'Performance laboratory: bench-doctor BLOCKED, bench-selftest PASS. Decisions are review recommendations; readiness keeps '
                              'actual_django_workload_tested, native_adoption_authorized and production_authorized false.')
        self.assertTrue(br.report_line({'gates':[]}).startswith('Performance laboratory: bench-doctor NOT_EXECUTED, bench-selftest NOT_EXECUTED. '))

class ReadinessResultTests(unittest.TestCase):           # developer_acceptance.readiness returns the axes and the details; the schema closes them
    def result(self,t):
        import developer_acceptance as da
        r=ReadinessTests.root(self,t);(r/'safety').mkdir();shutil.copy(ROOT/'safety/developer-policy.json',r/'safety/developer-policy.json')
        with mock.patch.object(da,'source_identity',return_value=(ID,{})):return da.readiness(r,'ctx',{'worktree':'w'},{},ID)
    def doc(self,result):
        return {'schema_version':1,'operation':'readiness','status':'BLOCKED','run_id':'0'*32,'source_identity':ID,'profile':'p','context_namespace':'ctx',
                'scope':'partial_feedback','acceptance':False,'evidence_paths':[],'result':result,'limitations':[]}
    def test_the_result_holds_the_axes_and_details_and_validates(self):
        with tempfile.TemporaryDirectory() as t:res=self.result(t)
        self.assertEqual(list(res['performance']),KEYS);self.assertEqual(res['performance']['combined_local_checks'],res['combined_local_checks'])
        self.assertEqual(res['performance']['independent_enforcement'],res['independent_enforcement'])
        self.assertEqual(res['performance_details'],{'handoff_trial':br.NO_RECEIPT,'unit_verdicts':None});self.assertIn('live_agent_trial',res)
        self.assertTrue(validate(ROOT,'developer-feedback',self.doc(res)))
    def test_the_schema_is_closed(self):
        with tempfile.TemporaryDirectory() as t:res=self.result(t)
        bad=[dict(res,performance=dict(res['performance'],production_authorized=True)),dict(res,performance=dict(res['performance'],actual_django_workload_tested=True)),
             dict(res,performance=dict(res['performance'],benchmark_tooling='PASS')),dict(res,performance=dict(res['performance'],demo_performance_evidence='PASSED')),
             dict(res,performance=dict(res['performance'],extra=1)),dict(res,performance={k:v for k,v in res['performance'].items() if k!='multicore_qualification'}),
             dict(res,performance_details=dict(res['performance_details'],extra=1)),dict(res,performance_details=dict(res['performance_details'],handoff_trial='x'*201)),
             dict(res,performance_details=dict(res['performance_details'],unit_verdicts={'KEEP_PYTHON':1})),
             dict(res,performance_details=dict(res['performance_details'],unit_verdicts={'KEEP_PYTHON':-1,'PREFER_C':0,'INCONCLUSIVE':0,'INVALID_EXPERIMENT':0}))]
        for b in bad:
            with self.subTest(b=json.dumps({k:b[k] for k in ('performance','performance_details')})[:200]):
                with self.assertRaises(GateError):validate(ROOT,'developer-feedback',self.doc(b))
        ok=dict(res,performance_details=dict(res['performance_details'],unit_verdicts={'KEEP_PYTHON':7,'PREFER_C':1,'INCONCLUSIVE':1,'INVALID_EXPERIMENT':1}))
        self.assertTrue(validate(ROOT,'developer-feedback',self.doc(ok)))

if __name__=='__main__':unittest.main()
