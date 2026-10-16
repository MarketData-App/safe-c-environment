import argparse, contextlib, copy, io, json, os, shutil, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import bench, bench_decide as bd, bench_model as bm, bench_phase3_cli as cli
from schema_check import validate
POL=bm.load_policy(ROOT);FIX=bm.load_fixtures(ROOT)['decision_cases']
FIXTURE=ROOT/'tests/unit/fixtures/decide/run'
# Ruling T14-C1: the RecordTests of the Task 17 brief run the engine's bootstraps (rules 3-8 on the c-candidate and keep
# cases, 10,000 resamples each); they run in the container suite benchmarks/performance/python/tests/test_decide_records.py
# with the brief's assertions unchanged. policy.source_identity hashes the whole source tree, so every test that reaches
# the staleness check mocks it (the run's identity is 'a'*64). The brief's case name of the example project is replaced by
# the framework case record-scan (input data only): test_bench_framework_imports forbids the example name in framework tests.

class RegistrationTests(unittest.TestCase):
    def test_decide_is_registered(self):
        self.assertIn('decide',bench.HANDLERS);self.assertEqual(bench.ARGUMENTS['decide'][0][0],'--run-id')
        # FR3: a unit-threshold policy is a project policy name, loaded from the run's project protocol; --policy checks the form
        self.assertIs(dict(bench.ARGUMENTS['decide'])['--policy']['type'],cli.policy_name)
        for name in ('all','owner','demo-latency-2x','demo-cpu-40','fixture-request-threshold'):self.assertEqual(cli.policy_name(name),name)
        for bad in ('Owner','x','a b','../x','a'*42):
            with self.subTest(bad=bad),self.assertRaises(argparse.ArgumentTypeError):cli.policy_name(bad)
    def test_long_approval_path_is_refused(self):                       # P3R12-02: verdicts[].path stays within the schema's 300
        self.assertIs(dict(bench.ARGUMENTS['decide'])['--approval']['type'],cli.approval_path)
        self.assertEqual(cli.approval_path('a'*300),'a'*300)
        with self.assertRaises(argparse.ArgumentTypeError):cli.approval_path('a'*301)
    def test_all_means_the_policies_of_the_run(self):
        self.assertEqual(cli.policies_for({'policy':'fixture-request-threshold'},'all'),['fixture-request-threshold'])
        self.assertEqual(cli.policies_for({'policy':'owner'},'all'),['owner','demo-latency-2x','demo-cpu-40'])
        self.assertEqual(cli.policies_for({},'all'),['owner','demo-latency-2x','demo-cpu-40'])
        self.assertEqual(cli.policies_for({},'demo-cpu-40'),['demo-cpu-40'])
    def test_panel_stays_registered(self):                              # the Task 7 operation keeps its registration
        self.assertIn('panel',bench.HANDLERS);self.assertIn('--rejected-from',dict(bench.ARGUMENTS['panel']))

class CommandTests(unittest.TestCase):
    def test_refuses_rewritten_evidence(self):
        with mock.patch('bench._run_dir',return_value=Path('/nonexistent')),mock.patch('bench.read_json',return_value={'run_id':'0'*32,'mode':'decision','status':'VALID'}),\
             mock.patch('bench_evidence.verify',return_value=['changed after the run: observations.jsonl']):
            self.assertEqual(cli.decide_cmd(ROOT,argparse.Namespace(run_id='0'*32,policy='all',format='json')),1)
    def test_refuses_a_policy_changed_after_the_run(self):
        with mock.patch('bench._run_dir',return_value=Path('/nonexistent')),mock.patch('bench.read_json',return_value={'run_id':'0'*32,'mode':'decision','status':'VALID','dataset':{'kind':'synthetic'}}),\
             mock.patch('bench_evidence.verify',return_value=[]),mock.patch('bench_evidence.stale',return_value=False),mock.patch('bench_evidence.policy_runtime_problems',return_value=['unapproved-policy-digest: x']),\
             mock.patch('policy.source_identity',return_value=('a'*64,{})):
            self.assertEqual(cli.decide_cmd(ROOT,argparse.Namespace(run_id='0'*32,policy='all',format='json')),1)
    def test_reused_source_report_is_refused(self):
        with mock.patch('bench._run_dir',return_value=Path('/nonexistent')),mock.patch('bench.read_json',return_value={'run_id':'0'*32,'mode':'decision','status':'VALID','source_identity':'a'*64,'dataset':{'kind':'synthetic'}}),\
             mock.patch('bench_evidence.verify',return_value=[]),mock.patch('policy.source_identity',return_value=('b'*64,{})):
            self.assertEqual(cli.decide_cmd(ROOT,argparse.Namespace(run_id='0'*32,policy='all',format='json')),1)
    def test_owner_request_policy_is_not_a_rule_policy(self):
        self.assertNotIn('fixture-request-threshold',cli.RULE_POLICIES)
        with mock.patch('bench._run_dir',return_value=Path('/nonexistent')),mock.patch('bench.read_json',return_value={'run_id':'0'*32,'case':'record-scan','mode':'decision','status':'VALID','source_identity':'a'*64,'dataset':{'kind':'synthetic'},'plan':{},
                                                                                               'accounting':[{'session':'s0','launcher_cgroup_inode':5,'job_cgroup_inode':5}]}),\
             mock.patch('bench_evidence.verify',return_value=[]),mock.patch('bench_evidence.stale',return_value=False),mock.patch('bench_evidence.policy_runtime_problems',return_value=[]),\
             mock.patch('bench_evidence.check_integrity',return_value=[]),mock.patch('bench_evidence.recorded_status',return_value=('VALID',[])),mock.patch('policy.source_identity',return_value=('a'*64,{})),\
             mock.patch('bench_evidence.plan_fact_problems',return_value=[]),\
             mock.patch('bench_phase3_cli.read_json',return_value={'policy':'fixture-request-threshold','project_dir':'tests/fixtures/bench-project'}),mock.patch('bench_model.load_case',return_value={'variants':[]}),\
             mock.patch('bench_model.load_opportunity',return_value={}),mock.patch('bench_decide.evidence_from_run',return_value={}),mock.patch('bench_decide.decide',side_effect=AssertionError('rules 1-8 called')),\
             mock.patch('bench_phase3_cli.decide_owner',return_value=0):
            self.assertEqual(cli.decide_cmd(ROOT,argparse.Namespace(run_id='0'*32,policy='all',format='json',ci_run_id=None,approval=[])),0)   # Task 18: the unit branch (P3R3-03)
    def test_evidence_from_run_on_a_recorded_fixture(self):
        d=FIXTURE
        ev=bd.evidence_from_run(ROOT,d,json.loads((d/'run.json').read_text()),json.loads((d/'plan.json').read_text()),{'variants':[{'id':'py-reference','language':'python','status':'implemented'},{'id':'py-optimized','language':'python','status':'implemented'}]})
        self.assertEqual({r['variant'] for r in ev['rows']},{'py-reference','py-optimized'});self.assertIn('policy_bound',ev);self.assertIn('crossover_measured',ev)
    def test_decide_refuses_a_recorded_cgroup_mismatch(self):
        run={'run_id':'0'*32,'case':'record-scan','mode':'decision','status':'VALID','source_identity':'a'*64,'dataset':{'kind':'synthetic'},
             'accounting':[{'session':'s0','launcher_cgroup_inode':5,'job_cgroup_inode':6}]}
        with mock.patch('bench._run_dir',return_value=Path('/nonexistent')),mock.patch('bench.read_json',return_value=run),mock.patch('bench_evidence.verify',return_value=[]),\
             mock.patch('bench_evidence.stale',return_value=False),mock.patch('bench_evidence.policy_runtime_problems',return_value=[]),mock.patch('policy.source_identity',return_value=('a'*64,{})):
            self.assertEqual(cli.decide_cmd(ROOT,argparse.Namespace(run_id='0'*32,policy='all',format='json')),1)
    def test_decide_without_accounting_raises_no_key_error(self):
        import bench_accounting as ba
        self.assertEqual(ba.recheck({'run_id':'0'*32}),[ba.UNRECORDED])
    def test_decide_cmd_on_an_unrecorded_run(self):
        # T16-APP-01: run.json is not digest-bound, so a run without accounting rows (cgroup identity unrecorded) is an
        # unbound run; decide refuses it under every policy and writes no record.
        with tempfile.TemporaryDirectory() as tmp:          # fix round 1: a bound run record without accounting (input data)
            d=recorded_copy(tmp,run=lambda r:{k:v for k,v in r.items() if k!='accounting'})
            for policy in ('demo-cpu-40','fixture-request-threshold'):
                with self.subTest(policy=policy):
                    rc,out=decide(d,policy)
                    self.assertEqual(rc,1);self.assertEqual(out['status'],'FAIL');self.assertTrue(any('cgroup identity unrecorded' in r for r in out['reasons']))
                    self.assertFalse(any(p.name.startswith('decision') for p in d.iterdir()))
    def test_profile_runs_never_decide(self):
        with mock.patch('bench._run_dir',return_value=Path('/nonexistent')),mock.patch('bench.read_json',return_value={'run_id':'0'*32,'mode':'profile','status':'VALID'}):
            self.assertEqual(cli.decide_cmd(ROOT,argparse.Namespace(run_id='0'*32,policy='all',format='json')),2)
    def test_request_limit_mismatch_is_invalid(self):                  # E-T17-3 (G-ALO-CO part 1, Amendment I13.1 item 1)
        with tempfile.TemporaryDirectory() as tmp:
            d=recorded_copy(tmp,plan=lambda p:dict(p,request_limit=16384))
            rc,out=decide(d,'all')
            self.assertEqual(rc,1);self.assertEqual(out['status'],'FAIL')
            for n in cli.RULE_POLICIES:
                rec=json.loads((d/f'decision-{n}.json').read_text());validate(ROOT,'bench-decision',rec)
                self.assertEqual((rec['outcome'],rec['adoption_outcome']),('INVALID_EXPERIMENT','INVALID_EXPERIMENT'))
                self.assertTrue(any('request_limit' in r for r in rec['reasons']),rec['reasons'])
    def test_recorded_fixture_decides(self):                          # the control for the refusal tests below
        with tempfile.TemporaryDirectory() as tmp:
            d=recorded_copy(tmp);rc,out=decide(d,'demo-cpu-40')
            rec=json.loads((d/'decision-demo-cpu-40.json').read_text());validate(ROOT,'bench-decision',rec)
            self.assertEqual((rc,out['status']),(0,'PASS'));self.assertNotEqual(rec['outcome'],'INVALID_EXPERIMENT');self.assertIs(rec['cgroup_identity_unrecorded'],False)
            self.assertTrue((d/'decision.md').is_file())
    def test_status_edited_to_valid_is_classified_by_the_recorded_files(self):   # T16-APP-01
        with tempfile.TemporaryDirectory() as tmp:
            d=recorded_copy(tmp,observations=lambda rows:[dict(rows[0],eligible=False)]+rows[1:])     # run.json still says VALID
            rc,out=decide(d,'demo-cpu-40');rec=json.loads((d/'decision-demo-cpu-40.json').read_text());validate(ROOT,'bench-decision',rec)
            self.assertEqual(rc,1);self.assertEqual(rec['outcome'],'INVALID_EXPERIMENT');self.assertTrue(any('ineligible' in r for r in rec['reasons']),rec['reasons'])
    def test_recorded_invalid_status_never_upgrades(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=recorded_copy(tmp,run=lambda r:dict(r,status='INVALID_EXPERIMENT',reasons=['a trial child did not start isolated']))
            rc,out=decide(d,'demo-cpu-40');rec=json.loads((d/'decision-demo-cpu-40.json').read_text())
            self.assertEqual((rc,rec['outcome']),(1,'INVALID_EXPERIMENT'));self.assertIn('a trial child did not start isolated',rec['reasons'])
    def test_unbound_runs_are_refused(self):                          # T16-APP-01: also a run that looks older than Task 16
        cases={'digests removed':lambda r:{k:v for k,v in r.items() if k!='evidence_digests'},
               'digests and profile removed, old date':lambda r:dict({k:v for k,v in r.items() if k not in ('evidence_digests','bench_profile_sha256')},created_at='2026-10-01T00:00:00+00:00')}
        for name,edit in cases.items():
            with self.subTest(name),tempfile.TemporaryDirectory() as tmp:
                d=recorded_copy(tmp,run=edit);rc,out=decide(d,'demo-cpu-40')
                self.assertEqual((rc,out['status']),(1,'FAIL'));self.assertTrue(out['reasons'][0].startswith('unbound'),out['reasons'])
                self.assertFalse((d/'decision-demo-cpu-40.json').exists())
    def test_unplanned_row_is_refused(self):                          # T16-APP-02
        with tempfile.TemporaryDirectory() as tmp:
            d=recorded_copy(tmp,observations=lambda rows:rows+[dict(rows[0],trial_id='smoke-caller-s00-b00-09')])
            rc,out=decide(d,'demo-cpu-40')
            self.assertEqual(rc,1);self.assertIn('unplanned row: smoke-caller-s00-b00-09',out['reasons']);self.assertFalse((d/'decision-demo-cpu-40.json').exists())
    def test_changed_dataset_identity_is_refused(self):               # T16-APP-03: run.json against the digest-bound plan
        for key,value in (('kind','local'),('size','large'),('seed',7),('rows',255)):
            with self.subTest(key),tempfile.TemporaryDirectory() as tmp:
                d=recorded_copy(tmp,run=lambda r:dict(r,dataset=dict(r['dataset'],**{key:value})))
                rc,out=decide(d,'demo-cpu-40')
                self.assertEqual(rc,1);self.assertIn('dataset mismatch: primary dataset',out['reasons']);self.assertFalse((d/'decision-demo-cpu-40.json').exists())
    def test_missing_plan_is_a_structured_refusal(self):              # T16-APP-06 (a)
        with tempfile.TemporaryDirectory() as tmp:
            d=recorded_copy(tmp,drop='plan.json');rc,out=decide(d,'demo-cpu-40')
            self.assertEqual((rc,out['status'],out['reasons']),(1,'FAIL',['missing: plan.json']))
    def test_blocked_run_without_rows_decides_nothing(self):          # BLOCKED evidence is unknown: exit 2, no record
        with tempfile.TemporaryDirectory() as tmp:
            d=recorded_copy(tmp,observations=lambda rows:[],run=lambda r:dict(r,status='BLOCKED',reasons=['bench doctor: BLOCKED']))
            rc,out=decide(d,'demo-cpu-40')
            self.assertEqual((rc,out['status']),(2,'BLOCKED'));self.assertFalse((d/'decision-demo-cpu-40.json').exists())
    def test_valid_run_without_rows_is_refused(self):                 # a VALID run keeps the integrity refusal
        with tempfile.TemporaryDirectory() as tmp:
            d=recorded_copy(tmp,observations=lambda rows:[])
            rc,out=decide(d,'demo-cpu-40')
            self.assertEqual(rc,1);self.assertTrue(any(r.startswith('missing failed attempt') for r in out['reasons']))
    def test_decide_waits_for_the_run_lock(self):                     # T16-APP-06 (c)
        import bench_evidence as be, fcntl
        from evidence import GateError
        with tempfile.TemporaryDirectory() as tmp:
            d=recorded_copy(tmp);fd=os.open(be.run_lock_path('0'*32),os.O_CREAT|os.O_RDWR,0o600)
            try:
                fcntl.flock(fd,fcntl.LOCK_EX)
                with mock.patch('bench_evidence.RUN_LOCK_SECONDS',0),self.assertRaises(GateError):decide(d,'demo-cpu-40')
            finally:os.close(fd)
            self.assertFalse((d/'decision-demo-cpu-40.json').exists())
            self.assertEqual(decide(d,'demo-cpu-40')[0],0)        # released: the next command runs

    # ---- fix round 1: T17-APP-01 (run.json bound by run_record_sha256; plan facts), T17-APP-02, T17-APP-03 ----
    def assert_refused(self,d,text):
        rc,out=decide(d,'demo-cpu-40')
        self.assertEqual((rc,out['status']),(1,'FAIL'));self.assertTrue(any(text in r for r in out['reasons']),out['reasons'])
        self.assertFalse(any(p.name.startswith('decision') for p in d.iterdir()))
    def test_edited_run_record_is_refused(self):                     # T17-APP-01 (a)-(d): a plain edit of run.json
        edits={'status and reasons':lambda r:dict(r,status='VALID',reasons=[]),
               'source identity':lambda r:dict(r,source_identity='b'*64),
               'image id':lambda r:dict(r,image_id='sha256:'+'0'*64),
               'policy digest':lambda r:dict(r,policy_sha256='0'*64),
               'profile digest':lambda r:dict(r,bench_profile_sha256='0'*64),
               'accounting':lambda r:{k:v for k,v in r.items() if k!='accounting'},
               'case':lambda r:dict(r,case='bench-control-spin'),
               'mode':lambda r:dict(r,mode='decision'),
               'project dir':lambda r:dict(r,plan=dict(r['plan'],project_dir='examples/x')),
               'envelope':lambda r:dict(r,envelope=dict(r['envelope'],cpus=2))}
        for name,edit in edits.items():
            with self.subTest(name),tempfile.TemporaryDirectory() as tmp:
                genuine=(lambda r:dict(r,status='INVALID_EXPERIMENT',reasons=['a trial child did not start isolated'])) if name=='status and reasons' else None
                self.assert_refused(recorded_copy(tmp,run=genuine,tamper=edit),'changed after the run: run.json')
    def test_a_bound_run_with_mode_edited_to_profile_is_refused(self):  # T17-RR-01: tampering is FAIL, not the BLOCKED of a profiled run
        with tempfile.TemporaryDirectory() as tmp:
            self.assert_refused(recorded_copy(tmp,tamper=lambda r:dict(r,mode='profile')),'changed after the run: run.json')
    def test_run_facts_come_from_the_plan(self):                      # T17-APP-01 (d): a consistent run.json that differs from plan.json
        edits={'case':lambda r:dict(r,case='bench-control-spin'),'mode':lambda r:dict(r,mode='decision'),
               'project dir':lambda r:dict(r,plan=dict(r['plan'],project_dir='examples/x')),'envelope':lambda r:dict(r,envelope=dict(r['envelope'],cpus=2))}
        for name,edit in edits.items():
            with self.subTest(name),tempfile.TemporaryDirectory() as tmp:
                self.assert_refused(recorded_copy(tmp,run=edit),'run.json differs from plan.json: '+name.replace(' ','_'))
    def test_a_run_without_its_record_digest_is_refused(self):
        import bench_evidence as be
        for created,text in (('2026-10-11T12:00:00+00:00','unbound: run.json'),('2026-10-12T01:00:00+00:00','stripped')):
            with self.subTest(created),tempfile.TemporaryDirectory() as tmp:
                d=recorded_copy(tmp,tamper=lambda r:dict({k:v for k,v in r.items() if k!='run_record_sha256'},created_at=created))
                self.assert_refused(d,text)
    def test_record_digest_is_canonical(self):                        # the file layout of run.json never matters
        import bench_evidence as be
        r=json.loads((FIXTURE/'run.json').read_text());h=be.run_record_sha256(r)
        self.assertEqual(h,be.run_record_sha256(json.loads(json.dumps(dict(r,run_record_sha256='f'*64),indent=3))))
        self.assertNotEqual(h,be.run_record_sha256(dict(r,status='BLOCKED')))
    def test_best_rows_name_the_interval_against_the_baseline(self):  # T17-APP-02 (spec 10)
        with tempfile.TemporaryDirectory() as tmp:
            d=recorded_copy(tmp);self.assertEqual(decide(d,'demo-cpu-40')[0],0)
            s=json.loads((d/'decision-demo-cpu-40.json').read_text())['summary']
            self.assertRegex(s['best_python'],r'^py-optimized .*median [0-9.e+]+ ns/unit; ratio [0-9.]+ \[[0-9.]+, [0-9.]+\] \(95 % interval\) vs py-reference')
            self.assertEqual(s['best_c'],'none')
    def test_unbindable_run_is_blocked(self):                         # T17-APP-03: a BLOCKED run whose digests failed decides nothing
        drop=lambda r:dict({k:v for k,v in r.items() if k!='evidence_digests'},status='BLOCKED',reasons=['evidence digests unavailable: evidence directory holds too many files'])
        with tempfile.TemporaryDirectory() as tmp:
            rc,out=decide(recorded_copy(tmp,run=drop),'demo-cpu-40');self.assertEqual((rc,out['status']),(2,'BLOCKED'))
        with tempfile.TemporaryDirectory() as tmp:          # its record is bound too
            d=recorded_copy(tmp,run=drop,tamper=lambda r:dict(r,status='VALID'));rc,out=decide(d,'demo-cpu-40');self.assertEqual(rc,1)

def recorded_copy(tmp,observations=None,plan=None,run=None,drop=None,tamper=None):
    """A copy of the recorded fixture with edited raw files; the evidence digests are recomputed, `run` edits run.json as
    bench run would have written it, and the run record digest is recomputed (a consistent bound run). `tamper` edits
    run.json afterwards, without any hash recomputation (T17-APP-01)."""
    import bench_evidence as be
    d=Path(tmp)/('0'*32);shutil.copytree(FIXTURE,d)
    if observations is not None:
        rows=[json.loads(x) for x in (d/'observations.jsonl').read_text().splitlines() if x.strip()]
        (d/'observations.jsonl').write_text(''.join(json.dumps(r,sort_keys=True)+'\n' for r in observations(rows)))
    if plan is not None:(d/'plan.json').write_text(json.dumps(plan(json.loads((d/'plan.json').read_text()))))
    if drop is not None:(d/drop).unlink()
    r=json.loads((d/'run.json').read_text());r['evidence_digests']=be.digest_files(d)
    if run is not None:r=run(r)
    r['run_record_sha256']=be.run_record_sha256(r)
    if tamper is not None:r=tamper(r)
    (d/'run.json').write_text(json.dumps(r,indent=2,sort_keys=True));return d

def decide(d,policy):
    """decide_cmd on a recorded copy: the current source identity, the policy digest and the image equal the run's."""
    out=io.StringIO()
    with mock.patch('bench._run_dir',return_value=d),mock.patch('bench_evidence.policy_runtime_problems',return_value=[]),\
         mock.patch('policy.source_identity',return_value=('a'*64,{})),mock.patch('bench_decide._current_identity',return_value='a'*64),contextlib.redirect_stdout(out):
        rc=cli.decide_cmd(ROOT,argparse.Namespace(run_id='0'*32,policy=policy,format='json',ci_run_id=None,approval=[]))
    return rc,json.loads(out.getvalue().strip().splitlines()[-1])
