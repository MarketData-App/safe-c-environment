import json, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import bench_readiness as br, bench_evidence as be
from schema_check import validate
from evidence import GateError, file_hash
R={'schema_version':1,'status':'PASSED','tooling_identity':'a'*64,'source_identity':'b'*64,'run_id':'0'*32,
   'decisions':[{'policy':'demo-cpu-40','outcome':'KEEP_PYTHON','adoption_outcome':'INCONCLUSIVE'}],'commands':3,'edits':0,'harness':'outer'}

def _readiness_fixtures():
    """The decision-run fixtures of test_bench_readiness (demo_run: a run bound by its evidence and record digests, with
    schema-valid decision records), loaded under another module name so that its tests do not run twice."""
    import importlib.util
    spec=importlib.util.spec_from_file_location('handoff_readiness_fixtures',ROOT/'tests/unit/test_bench_readiness.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
FX=_readiness_fixtures()

def schema_valid_run(d,edit=None):
    """S4-01: the demo run of d with the required run fields that bench run writes (a schema-valid run record), then
    `edit` (FR12-A04), bound again by its record digest."""
    run=json.loads((d/'run.json').read_text());run.pop(be.RECORD_KEY)
    run.update(schema_version=1,case_version=1,dataset=dict(run['dataset'],seed=1,sha256=None,rows=6),envelope=None,image_id='sha256:'+'c'*64,
               policy_sha256='a'*64,fixtures_sha256='a'*64,runtime=None,admission={'lock_held_ns':0,'active_at_handshake':[]},evidence={},reasons=[])
    if edit is not None:run=edit(run)
    run[be.RECORD_KEY]=be.run_record_sha256(run);(d/'run.json').write_text(json.dumps(run));return d

def decision_run(root,policies,run_id='0'*32,identity='b'*64,**over):
    """S2-01: a bound decision run of that source identity with one schema-valid decision record for each policy in
    policies (the other rule-policy records removed; the evidence digests do not cover the decision records). S3-03:
    run.json binds the records it keeps, as bench decide writes it: decision_digests holds the sha256 of each kept
    record, and the run record digest is recomputed over it."""
    d=FX.demo_run(Path(root),run_id,identity=identity,full=True,**over)
    for name in br.RULE_POLICIES:
        if name not in policies:(d/f'decision-{name}.json').unlink()
    run=json.loads((d/'run.json').read_text())
    run['decision_digests']={n:file_hash(d/f'decision-{n}.json') for n in br.RULE_POLICIES if n in policies}
    run[be.RECORD_KEY]=be.run_record_sha256(run);(d/'run.json').write_text(json.dumps(run))
    return d

class HandoffTrialTests(unittest.TestCase):
    def test_schema(self):
        validate(ROOT,'bench-handoff-trial',R)
        for bad in ({'edits':1},{'harness':'inner'},{'commands':9}):
            with self.assertRaises(GateError):validate(ROOT,'bench-handoff-trial',dict(R,**bad))
    def test_axis(self):
        with tempfile.TemporaryDirectory() as t:
            r=Path(t);(r/'artifacts/bench').mkdir(parents=True)
            self.assertEqual(br.handoff_trial_axis(r,'b'*64,'a'*64),'NOT_EXECUTED (trial mechanism: no receipt)')
            (r/'artifacts/bench/handoff-trial.json').write_text(json.dumps(R));decision_run(r,['demo-cpu-40'])
            with mock.patch('bench_readiness._validate',return_value=None):self.assertEqual(br.handoff_trial_axis(r,'b'*64,'a'*64),'PASSED')
            with mock.patch('bench_readiness._validate',return_value=None):self.assertTrue(br.handoff_trial_axis(r,'c'*64,'a'*64).startswith('NOT_EXECUTED'))
    def test_prompt(self):
        p=(ROOT/'prompts/performance-handoff-trial.md').read_text()
        for s in ('bench run --case bench-control-spin --mode smoke','bench compare --run-id','bench decide --run-id','Python retained pending evidence','at most 8','zero edits'):
            self.assertIn(s,p)

# Behavior tests beside the brief's tests (Task 33 implementer).
class HandoffTrialBehaviorTests(unittest.TestCase):
    def test_the_schema_is_closed(self):
        bad=[{k:v for k,v in R.items() if k!='run_id'},dict(R,extra=1),dict(R,status='PASS'),dict(R,tooling_identity='A'*64),dict(R,source_identity='b'*63),
             dict(R,run_id='0'*31),dict(R,commands=-1),dict(R,commands=True),dict(R,edits=False),
             dict(R,decisions=R['decisions']*2),dict(R,decisions=[dict(R['decisions'][0],policy='fixture-request-threshold')]),
             dict(R,decisions=[dict(R['decisions'][0],outcome='PREFER_C')]),dict(R,decisions=[dict(R['decisions'][0],deploy=True)]),
             dict(R,decisions=[{'policy':p,'outcome':'KEEP_PYTHON','adoption_outcome':'INCONCLUSIVE'} for p in ('owner','demo-latency-2x','demo-cpu-40','owner')])]
        for b in bad:
            with self.subTest(b=json.dumps(b)[:160]),self.assertRaises(GateError):validate(ROOT,'bench-handoff-trial',b)
        self.assertTrue(validate(ROOT,'bench-handoff-trial',dict(R,status='NOT_EXECUTED',run_id=None,decisions=[],commands=0)))

    def test_axis_with_the_real_schema_check(self):
        with tempfile.TemporaryDirectory() as t:
            r=Path(t);(r/'artifacts/bench').mkdir(parents=True);(r/'schemas').mkdir()
            (r/'schemas/bench-handoff-trial.json').write_text((ROOT/'schemas/bench-handoff-trial.json').read_text())
            p=r/'artifacts/bench/handoff-trial.json';decision_run(r,['demo-cpu-40'])
            for status in ('PASSED','FAILED','NOT_EXECUTED'):
                p.write_text(json.dumps(dict(R,status=status)))
                with self.subTest(status=status):self.assertEqual(br.handoff_trial_axis(r,'b'*64,'a'*64),status)
            p.write_text(json.dumps(R))
            self.assertEqual(br.handoff_trial_axis(r,'b'*64,'f'*64),'NOT_EXECUTED (trial mechanism: receipt for another source)')   # other tooling
            self.assertEqual(br.handoff_trial_axis(r,'c'*64,'a'*64),'NOT_EXECUTED (trial mechanism: receipt for another source)')   # other source
            for text in (json.dumps(dict(R,edits=2)),json.dumps(dict(R,harness='inner')),'{not json',json.dumps([R])):
                p.write_text(text)
                with self.subTest(text=text[:40]):self.assertEqual(br.handoff_trial_axis(r,'b'*64,'a'*64),'NOT_EXECUTED (trial mechanism: invalid receipt)')

    def test_details_read_the_receipt_with_the_current_tooling_identity(self):
        with tempfile.TemporaryDirectory() as t:
            r=Path(t);(r/'artifacts/bench').mkdir(parents=True)
            self.assertEqual(br.performance_details(r,'b'*64)['handoff_trial'],br.NO_RECEIPT)
            (r/'artifacts/bench/handoff-trial.json').write_text(json.dumps(R));decision_run(r,['demo-cpu-40'])
            with mock.patch('bench_readiness._validate',return_value=None),mock.patch('developer_acceptance.tooling_identity',return_value='a'*64):
                self.assertEqual(br.performance_details(r,'b'*64)['handoff_trial'],'PASSED')
            with mock.patch('bench_readiness._validate',return_value=None),mock.patch('developer_acceptance.tooling_identity',return_value='e'*64):
                self.assertTrue(br.performance_details(r,'b'*64)['handoff_trial'].startswith('NOT_EXECUTED'))      # the tooling changed since the trial

    def test_a_failed_trial_with_edits_or_many_commands_reads_as_failed(self):
        # T33-APP-01: a trial that failed because the agent edited a file or used more than 8 commands has a valid
        # receipt, and readiness shows FAILED; the same counts on a PASSED (or NOT_EXECUTED) receipt are refused.
        with tempfile.TemporaryDirectory() as t:
            r=Path(t);(r/'artifacts/bench').mkdir(parents=True);(r/'schemas').mkdir()
            (r/'schemas/bench-handoff-trial.json').write_text((ROOT/'schemas/bench-handoff-trial.json').read_text())
            p=r/'artifacts/bench/handoff-trial.json'
            failed=dict(R,status='FAILED')
            for counts in ({'edits':1},{'commands':9},{'edits':1,'commands':9},{'edits':1000,'commands':1000},
                           {'edits':2,'commands':12,'run_id':None,'decisions':[]}):
                with self.subTest(counts=counts):
                    self.assertTrue(validate(ROOT,'bench-handoff-trial',dict(failed,**counts)))
                    p.write_text(json.dumps(dict(failed,**counts)))
                    self.assertEqual(br.handoff_trial_axis(r,'b'*64,'a'*64),'FAILED')
            for status in ('PASSED','NOT_EXECUTED'):
                for counts in ({'edits':1},{'commands':9}):
                    with self.subTest(status=status,counts=counts):
                        with self.assertRaises(GateError):validate(ROOT,'bench-handoff-trial',dict(R,status=status,**counts))
                        p.write_text(json.dumps(dict(R,status=status,**counts)))
                        self.assertEqual(br.handoff_trial_axis(r,'b'*64,'a'*64),'NOT_EXECUTED (trial mechanism: invalid receipt)')
            for counts in ({'edits':-1},{'commands':-1},{'edits':1001},{'commands':1001},{'edits':True}):
                with self.subTest(failed_bound=counts),self.assertRaises(GateError):validate(ROOT,'bench-handoff-trial',dict(failed,**counts))

    def test_a_passed_trial_carries_a_run_and_decisions(self):
        # T33-APP-02: PASSED needs a run id, at least one decision and at least the three public commands.
        for bad in ({'run_id':None},{'decisions':[]},{'commands':0},{'commands':2},{'run_id':None,'decisions':[],'commands':0}):
            with self.subTest(bad=bad),self.assertRaises(GateError):validate(ROOT,'bench-handoff-trial',dict(R,**bad))
        for good in ({'commands':3},{'commands':8},
                     {'decisions':[{'policy':p,'outcome':'KEEP_PYTHON','adoption_outcome':'INCONCLUSIVE'} for p in ('owner','demo-latency-2x','demo-cpu-40')]}):
            with self.subTest(good=good):self.assertTrue(validate(ROOT,'bench-handoff-trial',dict(R,**good)))
        with tempfile.TemporaryDirectory() as t:
            r=Path(t);(r/'artifacts/bench').mkdir(parents=True);(r/'schemas').mkdir()
            (r/'schemas/bench-handoff-trial.json').write_text((ROOT/'schemas/bench-handoff-trial.json').read_text())
            (r/'artifacts/bench/handoff-trial.json').write_text(json.dumps(dict(R,run_id=None,decisions=[],commands=0)))
            self.assertEqual(br.handoff_trial_axis(r,'b'*64,'a'*64),'NOT_EXECUTED (trial mechanism: invalid receipt)')

    def test_a_receipt_holds_one_decision_per_policy(self):
        # S1-01: uniqueItems compares whole objects, so two decisions of one policy with different outcomes passed.
        # The schema (contains + maxContains 1 per policy) and handoff_trial_axis both refuse a repeated policy.
        def d(policy,outcome='KEEP_PYTHON',adoption='INCONCLUSIVE'):return {'policy':policy,'outcome':outcome,'adoption_outcome':adoption}
        repeated=[[d('owner'),d('owner','C_CANDIDATE_FOR_REVIEW')],[d('demo-latency-2x'),d('demo-latency-2x',adoption='KEEP_PYTHON')],
                  [d('demo-cpu-40','INCONCLUSIVE'),d('owner'),d('demo-cpu-40')]]
        with tempfile.TemporaryDirectory() as t:
            r=Path(t);(r/'artifacts/bench').mkdir(parents=True);(r/'schemas').mkdir()
            (r/'schemas/bench-handoff-trial.json').write_text((ROOT/'schemas/bench-handoff-trial.json').read_text())
            p=r/'artifacts/bench/handoff-trial.json'
            for status in ('PASSED','FAILED'):
                for decisions in repeated:
                    doc=dict(R,status=status,decisions=decisions)
                    with self.subTest(status=status,decisions=[x['policy'] for x in decisions]):
                        with self.assertRaises(GateError):validate(ROOT,'bench-handoff-trial',doc)
                        p.write_text(json.dumps(doc))
                        self.assertEqual(br.handoff_trial_axis(r,'b'*64,'a'*64),'NOT_EXECUTED (trial mechanism: invalid receipt)')
                        with mock.patch('bench_readiness._validate',return_value=None):   # the axis code refuses it without the schema
                            self.assertEqual(br.handoff_trial_axis(r,'b'*64,'a'*64),'NOT_EXECUTED (trial mechanism: invalid receipt)')
            for i,decisions in enumerate(([d('owner')],[d('owner'),d('demo-cpu-40','C_CANDIDATE_FOR_REVIEW')],[d('owner'),d('demo-latency-2x'),d('demo-cpu-40')])):
                run_id=str(i+1)*32;decision_run(r,[x['policy'] for x in decisions],run_id)
                doc=dict(R,decisions=decisions,run_id=run_id)
                with self.subTest(good=[x['policy'] for x in decisions]):
                    self.assertTrue(validate(ROOT,'bench-handoff-trial',doc))
                    p.write_text(json.dumps(doc))
                    self.assertEqual(br.handoff_trial_axis(r,'b'*64,'a'*64),'PASSED')

    def test_a_passed_receipt_names_a_current_decision_run_with_its_policies(self):
        # S2-01: a PASSED receipt reads PASSED only when its run_id names a bound decision run of the current source
        # identity and its decisions hold exactly one decision per decision policy of that run (the rule-policy decision
        # records in the run directory). A foreign, stale or other-mode run, a run whose record digest no longer matches,
        # a missing policy and an extra policy read NOT_EXECUTED with the reason; a FAILED receipt keeps its status.
        def d(policy):return {'policy':policy,'outcome':'KEEP_PYTHON','adoption_outcome':'INCONCLUSIVE'}
        two=[d('owner'),d('demo-cpu-40')]
        NO_RUN='NOT_EXECUTED (trial mechanism: receipt names no current decision run)'
        OTHER_POLICIES='NOT_EXECUTED (trial mechanism: receipt decisions differ from the run policies)'
        with tempfile.TemporaryDirectory() as t:
            r=Path(t);(r/'artifacts/bench').mkdir(parents=True);(r/'schemas').mkdir()
            (r/'schemas/bench-handoff-trial.json').write_text((ROOT/'schemas/bench-handoff-trial.json').read_text())
            p=r/'artifacts/bench/handoff-trial.json'
            decision_run(r,['owner','demo-cpu-40'],'1'*32)                                        # the current run of two policies
            decision_run(r,['owner','demo-cpu-40'],'2'*32,identity='c'*64)                        # stale: another source identity
            decision_run(r,['owner','demo-cpu-40'],'3'*32,mode='smoke')                           # not a decision run
            tampered=decision_run(r,['owner','demo-cpu-40'],'4'*32)
            run=json.loads((tampered/'run.json').read_text());run['status']='INVALID_EXPERIMENT';(tampered/'run.json').write_text(json.dumps(run))
            decision_run(r,['owner','demo-latency-2x','demo-cpu-40'],'5'*32)                      # three policies
            decision_run(r,['demo-cpu-40'],'6'*32)                                                # one policy
            stale_record=decision_run(r,['owner','demo-cpu-40'],'7'*32)
            rec=json.loads((stale_record/'decision-owner.json').read_text());rec['stale']=True;(stale_record/'decision-owner.json').write_text(json.dumps(rec))
            p.write_text(json.dumps(dict(R,run_id='1'*32,decisions=two)))
            self.assertEqual(br.handoff_trial_axis(r,'b'*64,'a'*64),'PASSED')
            cases={'foreign run id':('8'*32,two,NO_RUN),'stale run':('2'*32,two,NO_RUN),'smoke run':('3'*32,two,NO_RUN),
                   'record digest mismatch':('4'*32,two,NO_RUN),'stale decision record':('7'*32,two,NO_RUN),
                   'missing policy':('5'*32,two,OTHER_POLICIES),'extra policy':('6'*32,two,OTHER_POLICIES),
                   'one of two':('1'*32,[d('owner')],OTHER_POLICIES),'another pair':('1'*32,[d('owner'),d('demo-latency-2x')],OTHER_POLICIES)}
            for name,(run_id,decisions,reason) in cases.items():
                with self.subTest(case=name):
                    p.write_text(json.dumps(dict(R,run_id=run_id,decisions=decisions)))
                    self.assertEqual(br.handoff_trial_axis(r,'b'*64,'a'*64),reason)
                    p.write_text(json.dumps(dict(R,status='FAILED',run_id=run_id,decisions=decisions)))
                    self.assertEqual(br.handoff_trial_axis(r,'b'*64,'a'*64),'FAILED')

    def test_a_removed_edited_or_unbound_decision_record_never_reads_passed(self):
        # S3-03: the decision policies of a run come from run.json (decision_digests, bound by the run record digest), not
        # from the decision files that are in the run directory now. A removed record (the required set would shrink), an
        # edited record (other bytes), a record that run.json does not bind and a run.json without decision_digests read
        # NOT_EXECUTED (no current decision run); a FAILED receipt keeps its status.
        def d(policy):return {'policy':policy,'outcome':'KEEP_PYTHON','adoption_outcome':'INCONCLUSIVE'}
        NO_RUN='NOT_EXECUTED (trial mechanism: receipt names no current decision run)'
        three=[d(n) for n in br.RULE_POLICIES];two=[d('owner'),d('demo-cpu-40')]
        with tempfile.TemporaryDirectory() as t:
            r=Path(t);(r/'artifacts/bench').mkdir(parents=True);(r/'schemas').mkdir()
            (r/'schemas/bench-handoff-trial.json').write_text((ROOT/'schemas/bench-handoff-trial.json').read_text())
            p=r/'artifacts/bench/handoff-trial.json'
            decision_run(r,list(br.RULE_POLICIES),'1'*32)                                        # the control: all three bound
            removed=decision_run(r,list(br.RULE_POLICIES),'2'*32);(removed/'decision-demo-latency-2x.json').unlink()
            edited=decision_run(r,['owner','demo-cpu-40'],'3'*32)
            rec=json.loads((edited/'decision-owner.json').read_text());(edited/'decision-owner.json').write_text(json.dumps(rec,indent=2))
            unbound=decision_run(r,['owner'],'4'*32)
            (unbound/'decision-demo-cpu-40.json').write_text(json.dumps(FX.full_record('4'*32,'b'*64,'demo-cpu-40')))
            FX.demo_run(r,'5'*32,identity='b'*64,full=True)                                      # records, no decision_digests
            p.write_text(json.dumps(dict(R,run_id='1'*32,decisions=three)))
            self.assertEqual(br.handoff_trial_axis(r,'b'*64,'a'*64),'PASSED')
            cases={'removed record, the shrunken set':('2'*32,two),'removed record, the bound set':('2'*32,three),
                   'edited record':('3'*32,two),'unbound record':('4'*32,two),'no decision_digests':('5'*32,three)}
            for name,(run_id,decisions) in cases.items():
                with self.subTest(case=name):
                    p.write_text(json.dumps(dict(R,run_id=run_id,decisions=decisions)))
                    self.assertEqual(br.handoff_trial_axis(r,'b'*64,'a'*64),NO_RUN)
                    p.write_text(json.dumps(dict(R,status='FAILED',run_id=run_id,decisions=decisions)))
                    self.assertEqual(br.handoff_trial_axis(r,'b'*64,'a'*64),'FAILED')

    def test_decide_binds_the_records_it_writes_into_run_json(self):
        # S3-03: bench decide (_write_records) records the sha256 of each decision record it writes in run.json under
        # decision_digests, merged with the records of an earlier decide of that run, and recomputes the run record digest,
        # so the run stays bound and run_policies reads exactly the decided policies. A run.json that no longer matches its
        # record digest is refused before any record is written.
        # S4-01: bind_decisions validates run.json against schemas/bench-run.json before the write, so the demo runs here
        # carry the required run fields that bench run writes (schema-valid run records), bound again by the record digest.
        import bench_phase3_cli as p3
        schema_valid=schema_valid_run
        with tempfile.TemporaryDirectory() as t:
            r=Path(t);d=schema_valid(FX.demo_run(r,'1'*32,identity='b'*64,full=True,records=False))
            validate(ROOT,'bench-run',json.loads((d/'run.json').read_text()))
            with mock.patch('bench_decide.render_markdown',return_value=''):
                p3._write_records(d,[FX.full_record('1'*32,'b'*64,'owner')])
                p3._write_records(d,[FX.full_record('1'*32,'b'*64,'demo-cpu-40')])
            run=json.loads((d/'run.json').read_text())
            self.assertEqual(run['decision_digests'],{n:file_hash(d/f'decision-{n}.json') for n in ('owner','demo-cpu-40')})
            self.assertEqual((be.verify_record(run),be.verify(d,run)),([],[]))
            self.assertEqual(br.run_policies(r,'b'*64,'1'*32),['owner','demo-cpu-40'])
            bad=schema_valid(FX.demo_run(r,'2'*32,identity='b'*64,full=True,records=False))
            doc=json.loads((bad/'run.json').read_text());doc['status']='INVALID_EXPERIMENT';(bad/'run.json').write_text(json.dumps(doc))
            with mock.patch('bench_decide.render_markdown',return_value=''),self.assertRaises(GateError):
                p3._write_records(bad,[FX.full_record('2'*32,'b'*64,'owner')])
            self.assertFalse((bad/'decision-owner.json').exists())

    def test_a_bind_that_the_run_schema_refuses_writes_no_decision_file(self):
        # FR12-A04: _write_records checks the run record that the bind would write against schemas/bench-run.json before
        # any decision file is written, so a schema refusal leaves no partial decision-<policy>.json or decision.md, and
        # run.json stays unchanged. Cases: a run record with an unknown key, and a ninth bound policy (decision_digests
        # holds at most 8 names).
        import bench_phase3_cli as p3
        eight={f'policy-{i}':'a'*64 for i in range(8)}
        for name,edit in (('unknown key',lambda run:dict(run,unknown_key=1)),('ninth policy',lambda run:dict(run,decision_digests=eight))):
            with self.subTest(name),tempfile.TemporaryDirectory() as t:
                d=schema_valid_run(FX.demo_run(Path(t),'1'*32,identity='b'*64,full=True,records=False),edit)
                old=(d/'run.json').read_bytes();before=sorted(p.name for p in d.iterdir())
                with mock.patch('bench_decide.render_markdown',return_value=''),self.assertRaisesRegex(GateError,'^schema bench-run: '):
                    p3._write_records(d,[FX.full_record('1'*32,'b'*64,'owner')])
                self.assertEqual(sorted(p.name for p in d.iterdir()),before);self.assertEqual((d/'run.json').read_bytes(),old)

    def test_the_run_schema_accepts_decision_digests(self):
        # S3-03: decision_digests is a closed field of schemas/bench-run.json: policy names to 64-hex sha256 values.
        run=json.loads((ROOT/'tests/unit/fixtures/decide/run/run.json').read_text())
        self.assertTrue(validate(ROOT,'bench-run',dict(run,decision_digests={'owner':'a'*64,'fixture-request-threshold':'b'*64})))
        for bad in ({'owner':'A'*64},{'owner':'a'*63},{'Owner':'a'*64},{'owner':1},[]):
            with self.subTest(bad=bad),self.assertRaises(GateError):validate(ROOT,'bench-run',dict(run,decision_digests=bad))

    def test_the_new_files_are_exported(self):
        files=set(json.loads((ROOT/'starter-export.json').read_text())['files'])
        self.assertTrue({'prompts/performance-handoff-trial.md','schemas/bench-handoff-trial.json','tests/unit/test_bench_handoff_trial.py'}<=files)

if __name__=='__main__':unittest.main()
