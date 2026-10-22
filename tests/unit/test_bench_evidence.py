import json, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import bench_evidence as be
from evidence import GateError, file_hash

def make_run(d):
    (d/'plan.json').write_text('{"plan_id":"p"}');(d/'observations.jsonl').write_text('{"trial_id":"t0","wall_ns":5}\n');(d/'s0').mkdir()
    (d/'s0'/'phases.jsonl').write_text('');run={'run_id':'0'*32,'evidence_digests':be.digest_files(d)};(d/'run.json').write_text(json.dumps(run));return run

class EvidenceTests(unittest.TestCase):
    def test_digests_skip_derived_files(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t);run=make_run(d);(d/'compare.json').write_text('{}');(d/'decision-demo.json').write_text('{}')
            self.assertEqual(sorted(run['evidence_digests']),['observations.jsonl','plan.json','s0/phases.jsonl']);self.assertEqual(be.verify(d,run),[])
    def test_rewritten_observation_is_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t);run=make_run(d);(d/'observations.jsonl').write_text('{"trial_id":"t0","wall_ns":1}\n')
            self.assertEqual(be.verify(d,run),['changed after the run: observations.jsonl'])
    def test_missing_and_unrecorded_files(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t);run=make_run(d);(d/'plan.json').unlink();(d/'extra.jsonl').write_text('x')
            self.assertEqual(sorted(be.verify(d,run)),['missing: plan.json','unrecorded file: extra.jsonl'])
    def test_unbound_run(self):
        with tempfile.TemporaryDirectory() as t:
            p=be.verify(Path(t),{'run_id':'0'*32});self.assertTrue(be.is_unbound(p))
    def test_symlink_is_refused(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t);(d/'a').write_text('x');(d/'b').symlink_to(d/'a')
            with self.assertRaises(GateError):be.digest_files(d)
    def test_stale_source_is_labeled_and_not_current(self):
        self.assertTrue(be.stale({'source_identity':'a'*64},'b'*64));self.assertFalse(be.stale({'source_identity':'a'*64},'a'*64))
    def test_policy_changed_after_the_run_fails(self):
        run={'policy_sha256':'0'*64,'image_id':json.loads((ROOT/'developer.lock.json').read_text())['image_id']}
        self.assertTrue(any(p.startswith('post-hoc-policy-change') for p in be.policy_runtime_problems(ROOT,run)))
    def test_runtime_downgrade_fails(self):
        run={'policy_sha256':file_hash(ROOT/'safety/performance-policy.json'),'image_id':'sha256:'+'0'*64}
        self.assertTrue(any(p.startswith('reused-runner-report') for p in be.policy_runtime_problems(ROOT,run)))
    def test_changed_bench_profile_is_another_runner(self):
        run={'policy_sha256':file_hash(ROOT/'safety/performance-policy.json'),'image_id':json.loads((ROOT/'developer.lock.json').read_text())['image_id'],'bench_profile_sha256':'0'*64}
        self.assertIn('reused-runner-report: bench profile digest differs',be.policy_runtime_problems(ROOT,run))
    def test_current_run_has_no_problem(self):
        run={'policy_sha256':file_hash(ROOT/'safety/performance-policy.json'),'image_id':json.loads((ROOT/'developer.lock.json').read_text())['image_id']}
        self.assertEqual(be.policy_runtime_problems(ROOT,run),[])
    def test_integrity_checks(self):
        plan={'run_id':'r','dataset':{'sha256':'a'*64},'sessions':[{'trials':[{'trial_id':'t0','scope':'caller','point':'p','warmup':False,'tier':'small'}]}],'memory':[]}
        run={'run_id':'r','dataset':{'sha256':'a'*64}}
        ok=[{'run_id':'r','trial_id':'t0','scope':'caller','point':'p','warmup':False,'work_units':256,'eligible':True,'verdict':{'failures':{}}}]
        pol={'sizes':{'small':256},'pyperf':{'agreement_abs_ns':1000000,'agreement_rel':0.02,'clock_tolerance_ns':1000}}
        self.assertEqual(be.check_integrity(plan,run,ok,pol),[])
        for mut,expect in ((ok+ok,'duplicate rows'),([dict(ok[0],run_id='x')],'cross-run metrics'),([],'missing failed attempt'),
                           ([dict(ok[0],work_units=255)],'wrong work count'),([dict(ok[0],scope='kernel')],'scope mismatch'),
                           ([dict(ok[0],pyperf_wall_ns=10**9,wall_ns=1)],'forged self-timing')):
            with self.subTest(expect):self.assertTrue(any(r.startswith(expect) for r in be.check_integrity(plan,run,mut,pol)))
        self.assertTrue(any(r.startswith('dataset mismatch') for r in be.check_integrity(plan,dict(run,dataset={'sha256':'b'*64}),ok,pol)))
    def test_compare_refuses_a_recorded_cgroup_mismatch_and_labels_an_unrecorded_run(self):
        import argparse, bench
        from unittest import mock
        base={'run_id':'0'*32,'mode':'smoke','status':'VALID','evidence_digests':{}}
        with mock.patch('bench._run_dir',return_value=Path('/nonexistent')),mock.patch('bench.read_json',return_value=dict(base,accounting=[{'session':'s0','launcher_cgroup_inode':5,'job_cgroup_inode':6}])),\
             mock.patch('bench_evidence.verify',return_value=[]):
            self.assertEqual(bench.compare_cmd(ROOT,argparse.Namespace(run_id='0'*32,format='json')),1)
    def test_compare_labels_an_unrecorded_run_and_does_not_refuse_it(self):
        import argparse, bench, shutil
        src=ROOT/'tests/unit/fixtures/decide/run'
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp)/('0'*32);shutil.copytree(src,d);run=json.loads((d/'run.json').read_text());run.pop('accounting',None);(d/'run.json').write_text(json.dumps(run))
            from unittest import mock
            with mock.patch('bench._run_dir',return_value=d):rc=bench.compare_cmd(ROOT,argparse.Namespace(run_id='0'*32,format='json'))
            rows=json.loads((d/'compare.json').read_text())['rows']
        self.assertEqual(rc,0);self.assertTrue(rows);self.assertTrue(all(r['evidence_quality'].startswith('unbound') and 'cgroup identity unrecorded' in r['evidence_quality'] for r in rows))
    def test_replay_copied_numbers(self):
        old=[{'run_id':'a'*32,'trial_id':'t','warmup':False,'scope':'caller','wall_ns':7,'cpu_usage_usec':3}]
        self.assertEqual(be.check_replay_fresh(old,[dict(old[0],run_id='b'*32)]),['replay copied the recorded numbers'])
        self.assertEqual(be.check_replay_fresh(old,[dict(old[0],run_id='b'*32,wall_ns=8)]),[])
        self.assertIn('replay reused the run identity',be.check_replay_fresh(old,[dict(old[0],wall_ns=9)]))
    def test_profile_digest_is_stable(self):self.assertEqual(be.bench_profile_sha256(ROOT),be.bench_profile_sha256(ROOT))
    def test_run_schema_accepts_the_keys(self):
        p=json.loads((ROOT/'schemas/bench-run.json').read_text())['properties'];self.assertIn('evidence_digests',p);self.assertIn('bench_profile_sha256',p)

# ---- Task 16 approval follow-ups (T16-APP-01 to -04, -06), carried into Task 17 ----
FIXTURE=ROOT/'tests/unit/fixtures/decide/run'
PLAN1={'run_id':'r','dataset':{'kind':'synthetic','size':'small','seed':20261007,'sha256':None,'rows':256},
       'sessions':[{'trials':[{'trial_id':'t0','scope':'caller','point':'p','warmup':False,'tier':'small'}]}],'memory':[]}
ROW1={'run_id':'r','trial_id':'t0','scope':'caller','point':'p','warmup':False,'work_units':256,'eligible':True,'verdict':{'failures':{}}}
POL1={'sizes':{'small':256},'pyperf':{'agreement_abs_ns':1000000,'agreement_rel':0.02,'clock_tolerance_ns':1000}}
NAMED='synthetic:large#panel'
NAMED1={'kind':'synthetic','size':'large','seed':20261007,'sha256':None,'rows':6,'indices':[1,2,3,4,5,6]}

def fixture_copy(tmp,observations=None,run=None,drop=None,rebind=True):
    """The recorded fixture with edited raw files and recomputed digests (a consistent bound run); run.json last."""
    import shutil
    d=Path(tmp)/('0'*32);shutil.copytree(FIXTURE,d)
    if observations is not None:
        rows=[json.loads(x) for x in (d/'observations.jsonl').read_text().splitlines() if x.strip()]
        (d/'observations.jsonl').write_text(''.join(json.dumps(r,sort_keys=True)+'\n' for r in observations(rows)))
    if drop is not None:(d/drop).unlink()
    r=json.loads((d/'run.json').read_text())
    if rebind:r['evidence_digests']=be.digest_files(d)
    if run is not None:r=run(r)
    (d/'run.json').write_text(json.dumps(r));return d

def command(fn,d):
    import argparse, bench, contextlib, io
    from unittest import mock
    out=io.StringIO()
    with mock.patch('bench._run_dir',return_value=d),contextlib.redirect_stdout(out):rc=fn(ROOT,argparse.Namespace(run_id='0'*32,format='json'))
    return rc,json.loads(out.getvalue().strip().splitlines()[-1])

class IntegrityFollowUpTests(unittest.TestCase):
    def test_unplanned_row_is_a_reason(self):                          # T16-APP-02
        self.assertEqual(be.check_integrity(PLAN1,{'run_id':'r','dataset':PLAN1['dataset']},[ROW1],POL1),[])
        got=be.check_integrity(PLAN1,{'run_id':'r','dataset':PLAN1['dataset']},[ROW1,dict(ROW1,trial_id='t9')],POL1)
        self.assertEqual(got,['unplanned row: t9'])
    def test_primary_dataset_identity(self):                           # T16-APP-03: kind, size, seed, rows (and sha256 when planned)
        ok=dict(PLAN1['dataset'])
        self.assertEqual(be.check_integrity(PLAN1,{'run_id':'r','dataset':ok},[ROW1],POL1),[])
        for key,value in (('kind','local'),('size','large'),('seed',7),('rows',255),('rows',None)):
            with self.subTest(key=key,value=value):
                self.assertIn('dataset mismatch: primary dataset',be.check_integrity(PLAN1,{'run_id':'r','dataset':dict(ok,**{key:value})},[ROW1],POL1))
        self.assertIn('dataset mismatch: primary dataset',be.check_integrity(PLAN1,{'run_id':'r'},[ROW1],POL1))
    def test_values_the_run_fills(self):                               # a local plan has no row count; G6.6 fills named digests
        local=dict(PLAN1,dataset={'kind':'local','size':None,'seed':None,'sha256':'a'*64,'rows':None})
        self.assertEqual(be.check_integrity(local,{'run_id':'r','dataset':dict(local['dataset'],rows=100)},[ROW1],POL1),[])
        self.assertIn('dataset mismatch: primary dataset',be.check_integrity(local,{'run_id':'r','dataset':dict(local['dataset'],sha256='b'*64,rows=100)},[ROW1],POL1))
    def test_named_dataset_identity(self):                             # T16-APP-03: plan.datasets against run.json datasets
        plan=dict(PLAN1,datasets={NAMED:NAMED1});run={'run_id':'r','dataset':PLAN1['dataset']}
        check=lambda named:be.check_integrity(plan,dict(run,datasets=named),[ROW1],POL1)
        self.assertEqual(check({NAMED:dict(NAMED1)}),[])
        self.assertEqual(check({NAMED:dict(NAMED1,sha256='c'*64)}),[])                     # a filled digest of an unfilled plan entry
        for key,value in (('kind','local'),('size','small'),('seed',7),('rows',5),('indices',[1,2,3,4,5,7])):
            with self.subTest(key=key):self.assertIn('dataset mismatch: '+NAMED,check({NAMED:dict(NAMED1,**{key:value})}))
        self.assertIn('dataset mismatch: '+NAMED,check({}))
        self.assertIn('dataset mismatch: '+NAMED,check({NAMED:{k:v for k,v in NAMED1.items() if k!='indices'}}))
        self.assertIn('dataset mismatch: synthetic:small',check({NAMED:dict(NAMED1),'synthetic:small':dict(NAMED1,size='small')}))   # not planned
        filled=dict(plan,datasets={NAMED:dict(NAMED1,sha256='a'*64)})
        self.assertEqual(be.check_integrity(filled,dict(run,datasets={NAMED:dict(NAMED1,sha256='a'*64)}),[ROW1],POL1),[])
        self.assertIn('dataset mismatch: '+NAMED,be.check_integrity(filled,dict(run,datasets={NAMED:dict(NAMED1,sha256='b'*64)}),[ROW1],POL1))
    def test_run_schema_accepts_named_datasets(self):
        from schema_check import validate
        run=json.loads((FIXTURE/'run.json').read_text());validate(ROOT,'bench-run',dict(run,datasets={NAMED:NAMED1}))
        with self.assertRaises(GateError):validate(ROOT,'bench-run',dict(run,datasets={NAMED:dict(NAMED1,path='x')}))

class CompareFollowUpTests(unittest.TestCase):
    def test_compare_and_report_refuse_a_stripped_run(self):           # T16-APP-01: digests removed from a run recorded with them
        strip=lambda r:{k:v for k,v in r.items() if k!='evidence_digests'}
        cases={'profile digest kept':strip,
               'recorded after Task 16':lambda r:dict({k:v for k,v in strip(r).items() if k!='bench_profile_sha256'},created_at='2026-10-12T00:00:00+00:00')}
        import bench
        for name,edit in cases.items():
            with self.subTest(name),tempfile.TemporaryDirectory() as tmp:
                d=fixture_copy(tmp,run=edit)
                rc,out=command(bench.compare_cmd,d);self.assertEqual((rc,out['status']),(1,'FAIL'));self.assertTrue(out['reasons'][0].startswith('stripped'),out['reasons'])
                self.assertFalse((d/'compare.json').exists())
                rc,out=command(bench.report_cmd,d);self.assertEqual(rc,1);self.assertFalse((d/'summary.json').exists())
    def test_an_older_unbound_run_stays_readable(self):                 # R-8: recorded before evidence digests existed
        import bench
        with tempfile.TemporaryDirectory() as tmp:
            d=fixture_copy(tmp,run=lambda r:dict({k:v for k,v in r.items() if k not in ('evidence_digests','bench_profile_sha256')},created_at='2026-10-01T00:00:00+00:00'))
            rc,out=command(bench.compare_cmd,d);self.assertEqual(rc,0)
            self.assertTrue(all(r['evidence_quality'].startswith('unbound (recorded before evidence digests') for r in json.loads((d/'compare.json').read_text())['rows']))
    def test_compare_records_the_best_python_rule(self):                # N4-A02: the decide rule with the strictest framework guard
        import bench, bench_model as bm
        with tempfile.TemporaryDirectory() as tmp:
            d=fixture_copy(tmp);rc,out=command(bench.compare_cmd,d);self.assertEqual(rc,0)
            rule=json.loads((d/'compare.json').read_text())['best_python_rule']
            self.assertEqual((rule['metric'],rule['pool_cpu_guard']),('wall_ns_per_unit',bench.compare_pool_cpu_guard(bm.load_policy(ROOT))))
            self.assertIn('bench_decide.best_python_of',rule['rule'])
    def test_compare_of_a_blocked_run_without_rows(self):              # T16-APP-04
        import bench
        with tempfile.TemporaryDirectory() as tmp:
            d=fixture_copy(tmp,observations=lambda rows:[],run=lambda r:dict(r,status='BLOCKED',reasons=['bench doctor: BLOCKED']))
            rc,out=command(bench.compare_cmd,d);data=json.loads((d/'compare.json').read_text())
            self.assertEqual((rc,out['status'],data['status'],data['rows']),(2,'BLOCKED','BLOCKED',[]))
        for status in ('VALID','INVALID_EXPERIMENT'):                   # these keep the refusal
            with self.subTest(status),tempfile.TemporaryDirectory() as tmp:
                d=fixture_copy(tmp,observations=lambda rows:[],run=lambda r:dict(r,status=status))
                rc,out=command(bench.compare_cmd,d)
                self.assertEqual(rc,1);self.assertTrue(any(x.startswith('missing failed attempt') for x in out['reasons']));self.assertFalse((d/'compare.json').exists())
    def test_compare_without_a_plan_is_a_structured_refusal(self):     # T16-APP-06 (a)
        import bench
        with tempfile.TemporaryDirectory() as tmp:                     # an older unbound run that never had a plan
            d=fixture_copy(tmp,drop='plan.json',run=lambda r:dict({k:v for k,v in r.items() if k not in ('evidence_digests','bench_profile_sha256')},created_at='2026-10-01T00:00:00+00:00'))
            rc,out=command(bench.compare_cmd,d);self.assertEqual((rc,out['status'],out['reasons']),(1,'FAIL',['missing: plan.json']))
        with tempfile.TemporaryDirectory() as tmp:                     # a bound run whose plan disappeared
            d=fixture_copy(tmp);(d/'plan.json').unlink()
            rc,out=command(bench.compare_cmd,d);self.assertEqual(rc,1);self.assertIn('missing: plan.json',out['reasons'])
    def test_compare_and_report_take_the_run_lock(self):              # T16-APP-06 (c)
        import bench, fcntl, os
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            d=fixture_copy(tmp);fd=os.open(be.run_lock_path('0'*32),os.O_CREAT|os.O_RDWR,0o600)
            try:
                fcntl.flock(fd,fcntl.LOCK_EX)
                with mock.patch('bench_evidence.RUN_LOCK_SECONDS',0):
                    for fn in (bench.compare_cmd,bench.report_cmd):
                        with self.subTest(fn.__name__),self.assertRaises(GateError):command(fn,d)
            finally:os.close(fd)
            self.assertFalse((d/'compare.json').exists())
            with mock.patch('bench_evidence.RUN_LOCK_SECONDS',0):rc,out=command(bench.report_cmd,d)   # report holds the lock and calls compare
            self.assertEqual(rc,0);self.assertTrue((d/'compare.json').is_file());self.assertTrue((d/'summary.md').is_file())
    def test_run_lock_refuses_a_bad_run_id(self):
        with self.assertRaises(GateError):be.run_lock_path('../'+'0'*29)
    def test_run_lock_that_cannot_be_opened_is_blocked(self):         # T17-APP-04: a structured BLOCKED, never a Python error
        import os
        path=be.run_lock_path('f'*32);os.symlink('/nonexistent-lock-target',path)
        try:
            with self.assertRaises(GateError) as cm:
                with be.run_lock('f'*32):pass
            self.assertIn(path,str(cm.exception))
        finally:os.unlink(path)

def bound(r):return dict(r,run_record_sha256=be.run_record_sha256(r))

class RunRecordBindingTests(unittest.TestCase):                      # fix round 1, T17-APP-01: compare and report
    def test_compare_and_report_refuse_an_edited_run_record(self):
        import bench
        for name,edit in (('status',lambda r:dict(r,status='INVALID_EXPERIMENT')),('source identity',lambda r:dict(r,source_identity='b'*64)),('case',lambda r:dict(r,case='bench-control-spin'))):
            with self.subTest(name),tempfile.TemporaryDirectory() as tmp:
                d=fixture_copy(tmp,run=lambda r:edit(bound(r)))
                for fn in (bench.compare_cmd,bench.report_cmd):
                    rc,out=command(fn,d);self.assertEqual(rc,1);self.assertIn('changed after the run: run.json',out['reasons'])
                self.assertFalse((d/'compare.json').exists());self.assertFalse((d/'summary.json').exists())
    def test_an_unedited_bound_run_is_compared(self):
        import bench
        with tempfile.TemporaryDirectory() as tmp:
            d=fixture_copy(tmp,run=bound);rc,out=command(bench.report_cmd,d)
            self.assertEqual(rc,0);self.assertTrue(all(r['evidence_quality']=='exploratory (smoke)' for r in json.loads((d/'compare.json').read_text())['rows']))
    def test_a_run_without_its_record_digest(self):                    # before the change: a label; after it: stripped
        import bench
        with tempfile.TemporaryDirectory() as tmp:
            d=fixture_copy(tmp);rc,out=command(bench.compare_cmd,d)         # the Task 16 fixture: digests, no record digest
            self.assertEqual(rc,0);self.assertTrue(all(r['evidence_quality']=='unbound (run.json not bound)' for r in json.loads((d/'compare.json').read_text())['rows']))
        with tempfile.TemporaryDirectory() as tmp:
            d=fixture_copy(tmp,run=lambda r:dict(r,created_at='2026-10-12T01:00:00+00:00'))
            for fn in (bench.compare_cmd,bench.report_cmd):
                rc,out=command(fn,d);self.assertEqual(rc,1);self.assertTrue(out['reasons'][0].startswith('stripped'),out['reasons'])
    def test_unbindable_blocked_run_keeps_a_blocked_result(self):    # T17-APP-03
        import bench
        drop=lambda r:bound(dict({k:v for k,v in r.items() if k!='evidence_digests'},status='BLOCKED',reasons=['evidence digests unavailable: x']))
        with tempfile.TemporaryDirectory() as tmp:
            d=fixture_copy(tmp,run=drop)
            for fn in (bench.compare_cmd,bench.report_cmd):
                rc,out=command(fn,d);self.assertEqual((rc,out['status']),(2,'BLOCKED'))
    def test_overlong_evidence_path_is_refused(self):                 # T17-APP-03: the schema allows 512 characters
        with tempfile.TemporaryDirectory() as t:
            d=Path(t);deep=d/('a'*200)/('b'*200);deep.mkdir(parents=True);(deep/('c'*111)).write_text('x')    # 513 characters
            with self.assertRaises(GateError):be.digest_files(d)
            (deep/('c'*111)).unlink();(deep/('c'*109)).write_text('x')     # 511 characters: accepted
            self.assertEqual(len(next(iter(be.digest_files(d)))),511)

class RunRecordFollowUpTests(unittest.TestCase):
    def test_unbindable_evidence_keeps_a_blocked_run_record(self):     # T16-APP-06 (b): the run is never lost
        import test_bench_accounting as tba
        from unittest import mock
        with mock.patch('bench_evidence.digest_files',side_effect=GateError('evidence directory holds too many files')):
            code,run=tba.run_with(lambda name,trials:tba.session_config(1,trials))
        self.assertEqual((code,run['status']),(2,'BLOCKED'));self.assertNotIn('evidence_digests',run)
        self.assertIn('evidence digests unavailable: evidence directory holds too many files',run['reasons'])
    def test_unreadable_evidence_keeps_a_blocked_run_record(self):     # T17-APP-03: OSError as well
        import test_bench_accounting as tba
        from unittest import mock
        with mock.patch('bench_evidence.digest_files',side_effect=PermissionError('denied')):
            code,run=tba.run_with(lambda name,trials:tba.session_config(1,trials))
        self.assertEqual((code,run['status']),(2,'BLOCKED'));self.assertTrue(any(r.startswith('evidence digests unavailable: PermissionError') for r in run['reasons']),run['reasons'])
    def test_run_record_digest_is_written(self):                     # T17-APP-01
        import test_bench_accounting as tba
        code,run=tba.run_with(lambda name,trials:tba.session_config(1,trials))
        self.assertEqual(code,0);self.assertEqual(run['run_record_sha256'],be.run_record_sha256(run));self.assertEqual(be.verify_record(run),[])
    def test_run_records_the_named_datasets(self):                    # T16-APP-03: additive run.json datasets
        import bench_plan, test_bench_accounting as tba
        from unittest import mock
        real=bench_plan.build_plan
        def with_named(*a,**k):
            p=real(*a,**k);p['datasets']={NAMED:dict(NAMED1)};return p
        with mock.patch('bench_plan.build_plan',with_named):code,run=tba.run_with(lambda name,trials:tba.session_config(1,trials))
        self.assertEqual((code,run['status']),(0,'VALID'));self.assertEqual(run['datasets'],{NAMED:NAMED1})

class DecisionBindingTests(unittest.TestCase):                       # S4-01: bind_decisions validates run.json before the write
    def test_an_invalid_record_is_refused_and_the_old_file_stays(self):
        for name,(edit,policy) in (('policy name',(lambda r:r,'Bad_Name')),('unknown key',(lambda r:dict(r,unknown_key=1),'demo'))):
            with self.subTest(name),tempfile.TemporaryDirectory() as tmp:
                d=fixture_copy(tmp,run=bound);(d/f'decision-{policy}.json').write_text('{}')
                run=edit(be.bindable_run(d));old=(d/'run.json').read_bytes()
                with self.assertRaisesRegex(GateError,'^schema bench-run: '):be.bind_decisions(d,run,[policy])
                self.assertEqual((d/'run.json').read_bytes(),old)
                self.assertEqual(sorted(p.name for p in d.iterdir()),sorted(['observations.jsonl','phases.jsonl','plan.json','run.json',f'decision-{policy}.json']))
    def test_a_valid_record_is_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=fixture_copy(tmp,run=bound);(d/'decision-demo.json').write_text('{}')
            body=be.bind_decisions(d,be.bindable_run(d),['demo'])
            self.assertEqual(json.loads((d/'run.json').read_text()),body);self.assertEqual(body['decision_digests'],{'demo':file_hash(d/'decision-demo.json')})
            self.assertEqual(be.verify_record(body),[])

# T6 item 5 (finding T5-A05): the pyperf self-timing rule (B15 `forged self-timing`) is one-sided. Spec 8.2: the bracket
# nests the timed loops (the coordinator takes the begin sample before it acknowledges the begin marker, the worker starts
# its clock only after that acknowledgement and stops it before it sends the end marker; both read CLOCK_MONOTONIC in one
# container). So an honest self-timing never exceeds its bracket by more than the clock tolerance, and the bracket exceeds
# it only by the handshake overhead. The inputs are the real policy file, so the RED and GREEN runs read the same tests.
POLICY=json.loads((ROOT/'safety/performance-policy.json').read_text())
KPLAN={'run_id':'r','dataset':{'kind':'synthetic','size':'small','seed':20261007,'sha256':None,'rows':256},'memory':[],
       'sessions':[{'trials':[{'trial_id':'k0','scope':'kernel','point':'p','warmup':False,'tier':'small'}]}],'pyperf':{'values':1,'warmups':0}}

def kernel_row(wall,pyperf):
    return {'run_id':'r','trial_id':'k0','scope':'kernel','point':'p','warmup':False,'work_units':256,'eligible':True,
            'verdict':{'failures':{}},'wall_ns':wall,'pyperf_wall_ns':pyperf}

def forged(wall,pyperf):
    return 'forged self-timing: k0' in be.check_integrity(KPLAN,{'run_id':'r','dataset':KPLAN['dataset']},[kernel_row(wall,pyperf)],POLICY)

class SelfTimingTests(unittest.TestCase):
    def test_the_policy_declares_the_one_sided_bounds(self):
        self.assertEqual(POLICY['pyperf'],{'agreement_abs_ns':5000000,'agreement_rel':0.02,'clock_tolerance_ns':1000})
    def test_honest_bracket_overhead_passes(self):
        # Recorded honest pairs: the T5 foundation child smoke trial (bracket 31,650,646 ns, self-timing 30,580,927 ns,
        # overhead 1,069,719 ns) and the largest honest overhead of the 212 distinct trials (424 recorded rows: each kernel
        # row is stored twice; 1,661,031 ns, recorded on a 274.8 ms wall; T6-A01) applied to the shortest recorded wall
        # (29,392,881 ns); then zero, one, the exact bounds and the representable maximum.
        for wall,pyperf in ((31650646,30580927),(29392881,29392881-1661031),(30000000,30000000),(30000000,29999999),
                            (30000000,25000000),(10**9,10**9-20000000),(0,0),(2**63-1,2**63-1)):
            with self.subTest(wall=wall,pyperf=pyperf):self.assertFalse(forged(wall,pyperf))
    def test_a_self_timing_above_its_bracket_is_forged(self):
        for wall,pyperf in ((30000000,30001001),(31650646,31650646+2000000),(1,10**9),(30000000,2*30000000+10**9),(0,1001),
                            (2**63-1-1001,2**63-1)):
            with self.subTest(wall=wall,pyperf=pyperf):self.assertTrue(forged(wall,pyperf))
        self.assertFalse(forged(30000000,30001000))                         # exactly the clock tolerance
    def test_a_self_timing_far_below_its_bracket_is_forged(self):
        for wall,pyperf in ((30000000,24999999),(30000000,15000000),(30000000,0),(10**9,10**9-20000001),(10**9,0)):
            with self.subTest(wall=wall,pyperf=pyperf):self.assertTrue(forged(wall,pyperf))
    def test_a_malformed_self_timing_or_bracket_is_forged(self):
        for wall,pyperf in ((0,-1),(30000000,-1),(30000000,True),(30000000,1.5e7),(30000000,'30000000'),(-1,0),(True,1),(3e7,30000000)):
            with self.subTest(wall=wall,pyperf=pyperf):self.assertTrue(forged(wall,pyperf))
    def test_a_row_without_a_self_timing_or_a_bracket_is_not_judged_here(self):
        self.assertFalse(forged(30000000,None));self.assertFalse(forged(None,30000000))
    def test_compare_takes_honest_overhead_and_refuses_a_self_timing_above_its_bracket(self):
        import bench
        at_bound=lambda rows:[dict(r,pyperf_wall_ns=r['wall_ns']-5000000) if k==1 else r for k,r in enumerate(rows)]   # the 121 ms row
        with tempfile.TemporaryDirectory() as tmp:
            d=fixture_copy(tmp,observations=at_bound);rc,out=command(bench.compare_cmd,d)
            self.assertEqual(rc,0,out);rows=json.loads((d/'compare.json').read_text())['rows']
            self.assertEqual(sum(r['pyperf_disagreements'] for r in rows),0)
            self.assertFalse(any(r['evidence_quality']=='pyperf-disagreement' for r in rows))
        above=lambda rows:[dict(r,pyperf_wall_ns=r['wall_ns']+1001) if k==1 else r for k,r in enumerate(rows)]
        with tempfile.TemporaryDirectory() as tmp:
            d=fixture_copy(tmp,observations=above);rc,out=command(bench.compare_cmd,d)
            self.assertEqual((rc,out['status']),(1,'FAIL'));self.assertTrue(any(x.startswith('forged self-timing') for x in out['reasons']),out)
