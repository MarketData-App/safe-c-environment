import json, sys, unittest
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import bench_units as bu, bench_plan as bp, bench_model as bm
sys.path.insert(0,str(ROOT/'tests/unit'));import test_bench_qualification as tq
POL=bm.load_policy(ROOT);FIX=ROOT/'tests/unit/fixtures/units/panel-observations.jsonl'
PPOL=bm.load_policy(ROOT,'tests/fixtures/bench-project')   # FR5: the plan takes the panel cell names from the project protocol
# FR3: a unit-threshold policy is project data. UPOL is the synthetic engine test policy (selectors m1..m5); the decide
# branch loads NAME from the protocol of the run's project (the fixture project).
UPOL=bm.engine_unit_policy(ROOT);NAME='fixture-request-threshold';PROJECT='tests/fixtures/bench-project'
def loaded_run(mode='decision',case='fixture-case'):
    """(run, plan, case, opportunity) of a run of the fixture project; FR3-08: `case` is the run's case (the policy's case)."""
    return ({'run_id':'0'*32,'status':'VALID','mode':mode,'case':case,'dataset':{'kind':'synthetic'},'plan':{'project_dir':PROJECT}},
            {'policy':NAME,'case':case},{'case_id':case,'variants':[]},{})
# Base Task 18 Step 2 (with addendum E-T18-8 to E-T18-12). SensitivityConfirmationTests is in tests/unit/test_bench_units.py,
# where Amendment H16.1 and addendum E-T18-12 name it. The brief's case name of the example project is replaced by the
# framework case record-scan (input data only): test_bench_framework_imports forbids the example name in framework tests.

class PanelTrialTests(unittest.TestCase):
    def test_l_rule(self):
        self.assertEqual(bp.panel_passes(per_call_seconds=0.001,mode='warm'),84)      # smallest L >= 5 with 6 * L * 0.001 >= 0.5
        self.assertEqual(bp.panel_passes(per_call_seconds=0.5,mode='warm'),5)
        self.assertEqual(bp.panel_passes(per_call_seconds=0.001,mode='cold'),1)
    def test_unit_evidence_from_recorded_observations(self):
        obs=[json.loads(x) for x in FIX.read_text().splitlines()]
        rows=bu.rows_from_observations(obs,cells=CELLS)
        one=[r for r in rows if r['unit']=='m3/single-record' and r['variant']=='py-optimized'][0]
        self.assertEqual(set(one['records']),set(CELLS))
        self.assertTrue(one['eligible'])
        unknown=[r for r in bu.rows_from_observations(obs) if r['unit']=='m3/single-record']      # FR5: no known cells, no value
        self.assertTrue(unknown and all(r['eligible'] is False and r['wall']=={} for r in unknown))
        self.assertEqual(one['wall'],bu.worst_record(one['records']))
    def test_full_dataset_row_is_per_request(self):
        obs=[{'trial_id':f't{b}','block':b,'warmup':False,'eligible':True,'work_units':13230,'loops':1,'wall_ns':13230*15000,'unit':'m3/full-dataset','scope':'caller','mode':'warm',
              'variant':'py-optimized','workers':'direct','point':'unit-m3-full'} for b in range(12)]
        pr=bu.per_request(obs)
        self.assertEqual(set(pr),set(range(12)));self.assertAlmostEqual(pr[0],13230*15000.0)           # 15 us per record -> 198.45 ms per request
        T=UPOL['threshold_ns_per_request'];self.assertLess(pr[0],T)
        obs2=[dict(o,wall_ns=13230*16000) for o in obs];self.assertGreaterEqual(bu.per_request(obs2)[0],T)   # 16 us per record -> 211.68 ms: at or above T
    def test_owner_policy_goes_to_the_unit_branch_and_adopts_the_unit_verdicts(self):
        import bench_phase3_cli as cli, argparse
        units=[{'unit':u,'verdict':'KEEP_PYTHON','reason':'python-under-threshold'} for u in UPOL['units']]
        with mock.patch('bench_phase3_cli._load_run',return_value=loaded_run()),\
             mock.patch('bench_units.unit_evidence_from_run',return_value={}),mock.patch('bench_units.decide_units',return_value=units) as du,\
             mock.patch('bench_units.unit_decision_record',side_effect=lambda *a,**k:{'units':a[5],'outcome':None,'adoption_outcome':None}) as rec,\
             mock.patch('bench_decide.decide',side_effect=AssertionError('rules 1-8 called')),mock.patch('bench_phase3_cli._write_records',return_value=None),mock.patch('bench_phase3_cli._sensitivity',return_value={'owner_confirmation':{'ledger_id':'P3-OWNER-SENS-01','coverage_sha256':'0'*64}}):
            self.assertEqual(cli.decide_owner(ROOT,argparse.Namespace(run_id='0'*32,policy='all',format='json',ci_run_id=None,approval=[],sensitivity_confirmation=None,cgroup_unrecorded=False),NAME),0)
        r=rec.call_args[0];self.assertEqual(len(r[5]),10)          # G9.9 with I8.2: the adoption outcome is the set of the policy's unit verdicts
        self.assertEqual((r[4]['name'],r[4]['origin'],r[4]['sha256']),(NAME,'project',bm.protocol_digest(ROOT,PROJECT)))   # FR3: the record binds the protocol
    def test_owner_policy_refuses_an_unrecorded_cgroup_identity(self):
        import bench_phase3_cli as cli, argparse
        with mock.patch('bench_phase3_cli._load_run',return_value=loaded_run()),mock.patch('bench_phase3_cli._sensitivity',return_value={'owner_confirmation':{'ledger_id':'P3-OWNER-SENS-01','coverage_sha256':'0'*64}}):
            self.assertEqual(cli.decide_owner(ROOT,argparse.Namespace(run_id='0'*32,policy='all',format='json',ci_run_id=None,approval=[],sensitivity_confirmation=None,cgroup_unrecorded=True),NAME),1)
    def test_real_unit_decision_record_validates(self):
        from schema_check import validate
        import json as _j
        pol=UPOL
        ev={'status':'VALID','reasons':[],'rows':[],'blocked_other':[],'envelope_not_planned':[],'looks':{},'extension_not_run':[],'window_mismatch':[],
            'reference_evals':{},'panel_evals':{},'project_check':tq.qualified('Q06'),'current_identity':'a'*64,'opportunity_state':'APPROVED','coverage_ok':True,
            'reference_admit_excluded':None,'library_overhead_ns_per_row':None}
        units=bu.decide_units(ev,pol,{'resamples':200,'seed':20261007})       # ten INCONCLUSIVE (python-evidence-missing) records
        run={'run_id':'0'*32,'case':'record-scan','mode':'decision','source_identity':'a'*64,'image_id':'sha256:'+'1'*64,'policy_sha256':'2'*64,'dataset':{'kind':'synthetic'}}
        with mock.patch('bench_decide._current_identity',return_value='a'*64):
            rec=bu.unit_decision_record(ROOT,run,{},{'case_id':'record-scan','variants':[]},pol,units,ev,{})
        validate(ROOT,'bench-decision',rec);self.assertIs(rec['cgroup_identity_unrecorded'],False);self.assertEqual(len(rec['units']),10)
    def test_coverage_record_binding(self):
        with mock.patch('bench_units._newest_coverage',return_value={'status':'PASS','bench_units_sha256':'0'*64,'coverage_sha256':'0'*64,'policy_sha256':'0'*64}):
            self.assertFalse(bu.coverage_record_ok(ROOT))
        with mock.patch('bench_units._newest_coverage',return_value=None):self.assertFalse(bu.coverage_record_ok(ROOT))
    def test_panel_status_difference_makes_the_row_ineligible(self):          # H21.4
        obs=[json.loads(x) for x in FIX.read_text().splitlines()]
        obs[0]=dict(obs[0],panel_status_diff=[{'cell':'g1-neg-near','model':'m3','status':'MODEL_DOMAIN','reference_status':'OK','band_difference':True}],detail='panel-status')
        rows=bu.rows_from_observations(obs,cells=CELLS);bad=[r for r in rows if r.get('detail')=='panel-status']
        self.assertTrue(bad and all(r['eligible'] is False for r in bad))
    def test_coverage_record_checks_bench_stats_and_the_method(self):
        rec={'status':'PASS','rates':{},'units':0,'interval_method':'bootstrap'}
        self.assertTrue(any('interval method' in p for p in bu.coverage_problems(rec,bm.load_policy(ROOT),bu.file_digests(ROOT))))

# ---- Task 18 implementer additions (behavior of the Interfaces bullets that the brief's tests do not reach) ----
CELLS=tuple(c['name'] for c in bm.protocol_value(ROOT,PROJECT,'panel')['cell_rule']['cells'])   # FR5: the fixture protocol's cells in cell order
ENV={'cpus':4,'cpuset':[0,1,2,3],'smt_siblings':[],'reduced':False,'multicore':'PASS'}

class PanelPlanTests(unittest.TestCase):
    def test_build_plan_sets_the_panel_passes(self):
        import bench_deadline
        case={'case_id':'panel-plan-test','version':1,'scopes':['caller'],'sizes':['tiny'],
              'variants':[{'id':'py-reference','language':'python','status':'implemented','workers':['direct']},{'id':'py-optimized','language':'python','status':'implemented','workers':['direct']}],
              'points':[{'name':'unit-one','scope':'caller','size':'tiny','modes':['warm','cold'],'variants':['py-reference','py-optimized'],'class':'primary','panel':[11,12,13,14,15,16]}]}
        plan=bp.build_plan(case,PPOL,mode='decision',dataset={'kind':'synthetic','size':'large','seed':20261007,'sha256':None,'rows':13230},seed=7,envelope=ENV)
        trials=[t for s in plan['sessions'] for t in s['trials']];self.assertTrue(trials)
        for t in trials:
            with self.subTest(trial=t['trial_id']):
                per_call=bench_deadline.expected_seconds(PPOL,t,1,1,None)
                self.assertEqual(t['panel'],[11,12,13,14,15,16]);self.assertEqual(t['panel_cells'],list(CELLS))
                self.assertEqual(t['panel_passes'],bp.panel_passes(per_call_seconds=per_call,mode=t['mode']))
                self.assertEqual(t['panel_passes']==1,t['mode']=='cold')
                self.assertEqual(bench_deadline.job_inputs('timing',dict(plan,sizes=POL['sizes']),t),(1,6*t['panel_passes'] if t['mode']=='warm' else 6))   # the deadline inputs of bench_plan.trial_selector
                if t['mode']=='warm':        # the smallest L >= 5 with an estimated warm trial wall 6 x L x per-call >= 0.5 s
                    L=t['panel_passes'];self.assertGreaterEqual(L,5);self.assertGreaterEqual(6*L*per_call,0.5)
                    self.assertTrue(L==5 or 6*(L-1)*per_call<0.5)
        self.assertEqual({t['panel_passes'] for t in trials if t['mode']=='cold'},{1})
        self.assertGreater(max(t['panel_passes'] for t in trials),5)       # the py-optimized rate needs more than five passes
    def test_l_rule_refuses_a_bad_input(self):
        for bad in (0,-1.0,float('nan'),float('inf'),True,'0.1'):
            with self.subTest(bad=bad),self.assertRaises(ValueError):bp.panel_passes(per_call_seconds=bad,mode='warm')
        with self.assertRaises(ValueError):bp.panel_passes(per_call_seconds=0.1,mode='direct')

import importlib.util, statistics
_spec=importlib.util.spec_from_file_location('bc_panel_bounds',ROOT/'container/bench-coordinator.py');bc=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(bc)
PANEL_CASE={'case_id':'panel-plan-test','version':1,'scopes':['caller'],'sizes':['tiny'],
            'variants':[{'id':'py-reference','language':'python','status':'implemented','workers':['direct']},{'id':'py-optimized','language':'python','status':'implemented','workers':['direct']}],
            'points':[{'name':'unit-one','scope':'caller','size':'tiny','modes':['warm','cold'],'variants':['py-reference','py-optimized'],'class':'primary','panel':[11,12,13,14,15,16]}]}
SYN={'kind':'synthetic','size':'large','seed':20261007,'sha256':None,'rows':13230}
def walls_for(n,seed):return [100000+((seed*7919+i*104729)%50021) for i in range(n)]

class PanelBoundTests(unittest.TestCase):                              # fix round 1, ruling T18-C1b (G7.3 item 3: only the medians decide)
    def test_recorded_median_is_the_exact_median(self):
        for L in (5,6):
            with self.subTest(L=L):
                walls={c:walls_for(L,k) for k,c in enumerate(CELLS)};s=bc.panel_summary(walls)
                self.assertEqual(s['panel_passes'],L)
                for c,w in walls.items():self.assertEqual(s['panel_stats'][c],{'median_ns':statistics.median(w),'min_ns':min(w),'max_ns':max(w)})
    def test_audit_sample_is_bounded(self):
        walls={c:walls_for(100,k) for k,c in enumerate(CELLS)};s=bc.panel_summary(walls)
        self.assertEqual(s['panel_passes'],100);self.assertEqual(s['panel_walls'],{c:w[:64] for c,w in walls.items()})
    def plan_at(self,L):
        """build_plan with a one-row per-call wall that gives exactly L warm passes (the smallest L with 6 L p >= 0.5 s)."""
        p=0.5/(6*(L-0.5));self.assertEqual(bp.panel_passes(per_call_seconds=p,mode='warm'),L)
        with mock.patch('bench_deadline.expected_seconds',return_value=p):
            return bp.build_plan(PANEL_CASE,PPOL,mode='decision',dataset=SYN,seed=7,envelope=ENV)
    def test_l_pass_bound_refusal(self):
        self.assertEqual(bp.PANEL_MAX_PASSES,8192)
        plan=self.plan_at(8192);self.assertEqual(max(t['panel_passes'] for s in plan['sessions'] for t in s['trials']),8192)
        from evidence import GateError
        with self.assertRaisesRegex(GateError,'l-pass-over-bound'):self.plan_at(8193)
    def test_session_file_bound_refusal(self):
        from evidence import GateError
        ab=json.loads((ROOT/'safety/container-policy.json').read_text())['common']['artifact_bytes'];self.assertEqual(bp.artifact_bytes(),ab)
        bp.check_session_file(ab*3//4,ab,'s')                               # exactly 75 % of common.artifact_bytes
        with self.assertRaisesRegex(GateError,'session-file-over-bound'):bp.check_session_file(ab*3//4+1,ab,'s')
        with mock.patch('bench_plan.artifact_bytes',return_value=4096),self.assertRaisesRegex(GateError,'session-file-over-bound'):
            bp.build_plan(PANEL_CASE,PPOL,mode='decision',dataset=SYN,seed=7,envelope=ENV)
    def test_a_4167_pass_cell_validates_and_its_session_file_stays_small(self):
        from schema_check import validate
        base=json.loads((ROOT/'tests/unit/fixtures/decide/run/observations.jsonl').read_text().splitlines()[0])
        row=dict(base,work_units=6*4167,panel_status_diff=[],detail=None,**bc.panel_summary({c:walls_for(4167,k) for k,c in enumerate(CELLS)}))
        validate(ROOT,'bench-observation',row);self.assertEqual(row['panel_passes'],4167)
        size=len(json.dumps(row,sort_keys=True))+1;ab=bp.artifact_bytes()
        self.assertLess(494*size,ab//10)                                     # 494 trials of one single-record session: under 10 % of the limit
        trial={'scope':'caller','panel':[1]*6,'panel_passes':4167}
        self.assertGreaterEqual(bp.session_file_estimate([trial]),size)     # the plan estimate bounds the real row
    def test_the_decision_uses_the_medians(self):                      # the raw-wall mean and the median differ
        walls=[1000,1000,1000,1000,9000000]
        obs=[dict(json.loads(FIX.read_text().splitlines()[0]),trial_id=f'x{b}',block=b,**bc.panel_summary({c:[w+10*k for w in walls] for k,c in enumerate(CELLS)})) for b in range(2)]
        row=bu.rows_from_observations(obs,cells=CELLS)[0];med=max(statistics.median([w+10*k for w in walls]) for k in range(6))
        self.assertEqual(row['wall'],{0:med,1:med});self.assertEqual(bu.per_request(obs,cells=CELLS),{0:med,1:med})
        self.assertLess(row['wall'][0],statistics.mean(walls))

class OwnerBranchTests(unittest.TestCase):
    def test_a_policy_of_another_case_is_refused(self):                  # FR3-08: the policy decides only its own case
        import bench_phase3_cli as cli, argparse, io, contextlib
        out=io.StringIO()
        with mock.patch('bench_phase3_cli._load_run',return_value=loaded_run(case='record-scan')),mock.patch('bench_phase3_cli._write_records') as w,\
             mock.patch('bench_units.unit_evidence_from_run') as ev,contextlib.redirect_stdout(out),\
             mock.patch('bench_phase3_cli._sensitivity',return_value={'owner_confirmation':{'ledger_id':'P3-OWNER-SENS-01','coverage_sha256':'0'*64}}):
            rc=cli.decide_owner(ROOT,argparse.Namespace(run_id='0'*32,policy='all',format='json',ci_run_id=None,approval=[],sensitivity_confirmation=None,cgroup_unrecorded=False),NAME)
        self.assertEqual(rc,1);w.assert_not_called();ev.assert_not_called();self.assertIn('policy-case-mismatch',out.getvalue())
    def test_owner_policy_refuses_a_smoke_run(self):                     # G10.4: smoke runs give no unit verdict
        import bench_phase3_cli as cli, argparse
        loaded=loaded_run('smoke')
        with mock.patch('bench_phase3_cli._load_run',return_value=loaded),mock.patch('bench_phase3_cli._write_records') as w,\
             mock.patch('bench_phase3_cli._sensitivity',return_value={'owner_confirmation':{'ledger_id':'P3-OWNER-SENS-01','coverage_sha256':'0'*64}}):
            self.assertEqual(cli.decide_owner(ROOT,argparse.Namespace(run_id='0'*32,policy='all',format='json',ci_run_id=None,approval=[],sensitivity_confirmation=None,cgroup_unrecorded=False),NAME),1)
            w.assert_not_called()
    def test_a_confirmation_of_another_coverage_record_is_refused(self):   # H16.1: the sha256 check alone refuses (the record itself certifies)
        import bench_phase3_cli as cli, argparse, hashlib, tempfile, io, contextlib
        with tempfile.TemporaryDirectory() as t:
            cov=Path(t)/'coverage.json';cov.write_text('{"status":"PASS"}');conf=Path(t)/'c.json'
            def ask(sha):
                conf.write_text(json.dumps({'schema_version':1,'ledger_id':'P3-OWNER-SENS-02','coverage_sha256':sha,'coverage_path':str(cov),'owner_words':'20% is fine','date':'2026-10-10'}))
                out=io.StringIO()
                with mock.patch('bench_units.coverage_record_ok',return_value=True),contextlib.redirect_stdout(out):
                    got=cli._sensitivity(ROOT,argparse.Namespace(format='json',sensitivity_confirmation=str(conf)))
                return got,out.getvalue()
            got,text=ask(hashlib.sha256(cov.read_bytes()+b' ').hexdigest())
            self.assertIsNone(got);self.assertIn('sensitivity-unconfirmed',text)
            got,_=ask(hashlib.sha256(cov.read_bytes()).hexdigest())
            self.assertEqual(got,{'owner_confirmation':{'ledger_id':'P3-OWNER-SENS-02','coverage_sha256':hashlib.sha256(cov.read_bytes()).hexdigest()}})
    def test_unit_evidence_from_a_recorded_run(self):
        import argparse, shutil, tempfile
        with tempfile.TemporaryDirectory() as t:
            d=Path(t)/('0'*32);d.mkdir();shutil.copy(FIX,d/'observations.jsonl')
            run={'run_id':'0'*32,'status':'VALID','reasons':[],'mode':'decision','source_identity':'a'*64,'plan':{'project_dir':PROJECT},'envelope':ENV,'reference_evals':{'m3':1000},
                 'reference_overhead':{'library_overhead_ns_per_row':12.5}}
            plan={'blocked_rows':[{'variant':'py-threads','workers':4,'reason':'beyond the 2-CPU envelope'},{'variant':'c-serial','workers':'direct','reason':'C variant lands in Phase 2'}]}
            args=argparse.Namespace(ci_run_id=None,approval=[],sensitivity_confirmation=None)
            with mock.patch('bench_decide._current_identity',return_value='a'*64),mock.patch('bench_units.coverage_record_ok',return_value=True) as ok,\
                 mock.patch('bench_units._newest_coverage_path',return_value=None):
                ev=bu.unit_evidence_from_run(ROOT,d,run,plan,{'case_id':'record-scan','variants':[],'parameters':{}},UPOL,args)
        self.assertEqual(len(ev['rows']),8);self.assertEqual({r['unit'] for r in ev['rows']},{'m3/single-record'})
        self.assertEqual({r['language'] for r in ev['rows']},{'python','python-library','c'});self.assertEqual(ev['rows_per_request'],{'m3/single-record':1})
        self.assertEqual((ev['status'],ev['reference_evals'],ev['library_overhead_ns_per_row'],ev['coverage_ok']),('VALID',{'m3':1000},12.5,True))
        self.assertEqual(ev['envelope_not_planned'],[{'unit':'m3/single-record','label':'py-threads x4'}])
        self.assertEqual([b['label'] for b in ev['blocked_other']],['c-serial xdirect']);self.assertEqual(ev['envelope_cpus'],4)
        self.assertEqual(ev['project_check']['exit'],None);self.assertEqual(ev['current_identity'],'a'*64)
        self.assertIsNone(ev['project_report']);self.assertIsNone(ev['coverage_power'])     # no project report in the run; no coverage record
        self.assertEqual(ev['opportunity_state'],None);ok.assert_called_once_with(ROOT,None,UPOL)
    def test_markdown_names_every_unit_and_the_g96_fields(self):
        pol=UPOL
        rows=[{'cell':c,'category':'g1','values':{'r':1.1,'p':0.0953,'s':0.0822,'s_scaled':30.0},'level':0} for c in CELLS]
        ev={'status':'VALID','reasons':[],'rows':[],'blocked_other':[],'envelope_not_planned':[],'looks':{},'extension_not_run':[],'window_mismatch':[],
            'reference_evals':{},'panel_evals':{},'project_check':tq.qualified('Q06'),'current_identity':'a'*64,'opportunity_state':'APPROVED','coverage_ok':True,
            'reference_admit_excluded':None,'library_overhead_ns_per_row':None,'panel_rows':rows}
        run={'run_id':'0'*32,'case':'record-scan','mode':'decision','source_identity':'a'*64,'image_id':'sha256:'+'1'*64,'dataset':{'kind':'synthetic'}}
        with mock.patch('bench_decide._current_identity',return_value='a'*64):
            rec=bu.unit_decision_record(ROOT,run,{},{'case_id':'record-scan','variants':[]},pol,bu.decide_units(ev,pol,{}),ev,{})
        md=bu.render_units_markdown(rec)
        for u in pol['units']:self.assertIn(u,md)
        for text in ('python-evidence-missing','default action','sensitivity','trend','ranks','g1, r 1.1','s_scaled 30','level 0','manifest recorded','never a verdict'):
            self.assertIn(text,md)

# ---- T18-APP-01 (Task 18 approval, MEDIUM): the stale-coverage refusal of H16.1 and the binding to the confirmed record,
# with real coverage records (no stub of coverage_record_ok on these paths) ----
def coverage_record(**over):
    """A coverage record that certifies the current code (every rate 0, the policy units, the order-statistic method, the
    current file digests); keyword arguments replace fields (a stale digest makes it stale)."""
    cov=POL['coverage']
    rec={'status':'PASS','rates':{cfg:{str(sl):0.0 for sl in cov['sigma_log']} for cfg in bu.COVERAGE_BOUND},'units':cov['units'],
         'interval_method':'order-statistic','threshold_ns':UPOL['threshold_ns_per_request'],**bu.file_digests(ROOT)}   # FR3: the simulated T of the record
    rec.update(over);return rec
STALE={'bench_units_sha256':'0'*64}
def confirmation(path,cov):
    import hashlib
    path.write_text(json.dumps({'schema_version':1,'ledger_id':'P3-OWNER-SENS-03','coverage_sha256':hashlib.sha256(cov.read_bytes()).hexdigest(),
                                'coverage_path':str(cov),'owner_words':'20% is fine','date':'2026-10-11'}))

class StaleCoverageTests(unittest.TestCase):
    def test_a_stale_confirmed_coverage_record_is_refused(self):     # the sha256 matches; the record does not certify the code
        import bench_phase3_cli as cli, argparse, io, contextlib, tempfile
        loaded=loaded_run()
        with tempfile.TemporaryDirectory() as t:
            cov=Path(t)/'coverage.json';conf=Path(t)/'c.json'
            def ask(record):
                cov.write_text(json.dumps(record));confirmation(conf,cov);out=io.StringIO()
                with mock.patch('bench_phase3_cli._load_run',return_value=loaded),mock.patch('bench_phase3_cli._write_records') as w,\
                     mock.patch('bench_units.unit_evidence_from_run',return_value={}) as ev,mock.patch('bench_units.decide_units',return_value=[]),\
                     mock.patch('bench_units.unit_decision_record',return_value={'units':[],'outcome':None,'adoption_outcome':None}),contextlib.redirect_stdout(out):
                    rc=cli.decide_owner(ROOT,argparse.Namespace(run_id='0'*32,policy='all',format='json',ci_run_id=None,approval=[],sensitivity_confirmation=str(conf),cgroup_unrecorded=False),NAME)
                return rc,w.call_count,ev.call_count,out.getvalue()
            self.assertEqual(ask(coverage_record())[:3],(0,1,1))           # control: the real check accepts a record of the current code
            rc,writes,evidence,text=ask(coverage_record(**STALE))
            self.assertEqual((rc,writes,evidence),(1,0,0));self.assertIn('sensitivity-unconfirmed',text);self.assertIn('H14',text)
    def test_coverage_record_ok_reads_the_record_at_the_path(self):   # never the newest record when a path is given
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'coverage.json'
            p.write_text(json.dumps(coverage_record(**STALE)))
            with mock.patch('bench_units._newest_coverage',return_value=coverage_record()):
                self.assertTrue(bu.coverage_record_ok(ROOT));self.assertFalse(bu.coverage_record_ok(ROOT,p))
            p.write_text(json.dumps(coverage_record()))
            with mock.patch('bench_units._newest_coverage',return_value=coverage_record(**STALE)):
                self.assertFalse(bu.coverage_record_ok(ROOT));self.assertTrue(bu.coverage_record_ok(ROOT,p))
    def test_unit_evidence_uses_the_confirmed_coverage_record(self):  # coverage_ok and coverage_power come from the confirmed record
        import argparse, shutil, tempfile
        confirmed_power={'0.1':{'all_rows_fast':{'0.5':0.9},'one_row_fast':{}}};newest_power={'0.02':{'all_rows_fast':{'0.5':0.1},'one_row_fast':{}}}
        with tempfile.TemporaryDirectory() as t:
            d=Path(t)/('0'*32);d.mkdir();shutil.copy(FIX,d/'observations.jsonl')
            cov=Path(t)/'confirmed.json';cov.write_text(json.dumps(coverage_record(power=confirmed_power,**STALE)))
            newest=Path(t)/'newest.json';newest.write_text(json.dumps(coverage_record(power=newest_power)))
            conf=Path(t)/'c.json';confirmation(conf,cov)
            run={'run_id':'0'*32,'status':'VALID','reasons':[],'mode':'decision','source_identity':'a'*64,'plan':{'project_dir':PROJECT},'envelope':ENV}
            args=argparse.Namespace(ci_run_id=None,approval=[],sensitivity_confirmation=str(conf))
            with mock.patch('bench_decide._current_identity',return_value='a'*64),mock.patch('bench_units._newest_coverage_path',return_value=newest):
                ev=bu.unit_evidence_from_run(ROOT,d,run,{},{'case_id':'record-scan','variants':[],'parameters':{}},UPOL,args)
                self.assertIs(ev['coverage_ok'],False);self.assertEqual(ev['coverage_power'],{'power':confirmed_power})
                cov.write_text(json.dumps(coverage_record(power=confirmed_power)))      # the confirmed record certifies the code
                ev=bu.unit_evidence_from_run(ROOT,d,run,{},{'case_id':'record-scan','variants':[],'parameters':{}},UPOL,args)
                self.assertIs(ev['coverage_ok'],True)

# ---- T18-APP-04 (Task 18 approval, LOW): a panel row holds the six planned records and the planned L ----
def fixture():return [json.loads(x) for x in FIX.read_text().splitlines()]
def row_of(rows,o):return [r for r in rows if (r['mode'],r['variant'],r['workers'])==(o['mode'],o['variant'],o['workers'])][0]

class PanelRowCheckTests(unittest.TestCase):
    def assert_only_row_of_first_ineligible(self,rows,obs):
        bad=row_of(rows,obs[0]);self.assertIs(bad['eligible'],False);self.assertEqual(bad['wall'],{})
        self.assertTrue(all(r['eligible'] for r in rows if r is not bad))
    def test_a_panel_trial_without_the_six_panel_records_makes_its_row_ineligible(self):
        self.assertTrue(all(r['eligible'] for r in bu.rows_from_observations(fixture(),cells=CELLS)))          # control
        cell='g1-neg-far';five=lambda d:{c:v for c,v in d.items() if c!=cell};renamed=lambda d:{('g9-neg-far' if c==cell else c):v for c,v in d.items()}
        for name,change in (('five records',lambda o:dict(o,panel_stats=five(o['panel_stats']),panel_walls=five(o['panel_walls']))),
                            ('another record',lambda o:dict(o,panel_stats=renamed(o['panel_stats']),panel_walls=renamed(o['panel_walls']))),
                            ('medians and audit sample name different records',lambda o:dict(o,panel_walls=renamed(o['panel_walls'])))):
            with self.subTest(name):
                obs=fixture();obs[0]=change(obs[0]);self.assert_only_row_of_first_ineligible(bu.rows_from_observations(obs,cells=CELLS),obs)
    def test_a_panel_trial_with_another_l_than_planned_makes_its_row_ineligible(self):
        obs=fixture();planned={o['trial_id']:o['panel_passes'] for o in obs}
        self.assertTrue(all(r['eligible'] for r in bu.rows_from_observations(obs,planned=planned,cells=CELLS)))   # control: every L as planned
        for name,plan in (('another L',dict(planned,**{obs[0]['trial_id']:6})),('unplanned trial',{k:v for k,v in planned.items() if k!=obs[0]['trial_id']})):
            with self.subTest(name):self.assert_only_row_of_first_ineligible(bu.rows_from_observations(obs,planned=plan,cells=CELLS),obs)
    def test_unit_evidence_compares_l_with_the_plan(self):
        import argparse, shutil, tempfile
        obs=fixture()
        def plan(first_l):
            return {'sessions':[{'session':'s00','trials':[{'trial_id':o['trial_id'],'panel_passes':first_l if i==0 else o['panel_passes']} for i,o in enumerate(obs)]}]}
        with tempfile.TemporaryDirectory() as t:
            d=Path(t)/('0'*32);d.mkdir();shutil.copy(FIX,d/'observations.jsonl')
            run={'run_id':'0'*32,'status':'VALID','reasons':[],'mode':'decision','source_identity':'a'*64,'plan':{'project_dir':PROJECT},'envelope':ENV}
            args=argparse.Namespace(ci_run_id=None,approval=[],sensitivity_confirmation=None)
            with mock.patch('bench_decide._current_identity',return_value='a'*64),mock.patch('bench_units._newest_coverage_path',return_value=None):
                ev=lambda p:bu.unit_evidence_from_run(ROOT,d,run,p,{'case_id':'record-scan','variants':[],'parameters':{}},UPOL,args)
                self.assertTrue(all(r['eligible'] for r in ev(plan(obs[0]['panel_passes']))['rows']))
                self.assert_only_row_of_first_ineligible(ev(plan(obs[0]['panel_passes']+1))['rows'],obs)

# ---- T18-APP-03 (Task 18 approval, LOW): the achieved warm panel trial wall is recorded, and a wall below the 0.5 s target
# of G7.3 is flagged in the unit diagnostics (the planned C rate is never calibrated); the recorded medians still decide ----
class PanelTrialWallTests(unittest.TestCase):
    def test_the_coordinator_records_the_trial_wall(self):
        from schema_check import validate
        from evidence import GateError
        walls={c:walls_for(7,k) for k,c in enumerate(CELLS)};s=bc.panel_summary(walls)
        self.assertEqual(s['panel_call_ns'],sum(sum(w) for w in walls.values()))      # the sum of the 6 x L timed calls
        base=json.loads((ROOT/'tests/unit/fixtures/decide/run/observations.jsonl').read_text().splitlines()[0])
        row=dict(base,work_units=42,panel_status_diff=[],detail=None,**s);validate(ROOT,'bench-observation',row)
        with self.assertRaises(GateError):validate(ROOT,'bench-observation',{k:v for k,v in row.items() if k!='panel_call_ns'})
    def diagnostics(self,obs):
        import argparse, tempfile
        with tempfile.TemporaryDirectory() as t:
            d=Path(t)/('0'*32);d.mkdir();(d/'observations.jsonl').write_text(''.join(json.dumps(o)+'\n' for o in obs))
            run={'run_id':'0'*32,'status':'VALID','reasons':[],'mode':'decision','source_identity':'a'*64,'plan':{'project_dir':PROJECT},'envelope':ENV}
            with mock.patch('bench_decide._current_identity',return_value='a'*64),mock.patch('bench_units._newest_coverage_path',return_value=None):
                ev=bu.unit_evidence_from_run(ROOT,d,run,{},{'case_id':'record-scan','variants':[],'parameters':{}},UPOL,
                                             argparse.Namespace(ci_run_id=None,approval=[],sensitivity_confirmation=None))
        return ev['diagnostics']['m3/single-record']
    def test_a_warm_trial_wall_below_half_a_second_is_flagged(self):
        obs=[dict(o,panel_call_ns=600_000_000) for o in fixture()]
        self.assertFalse([x for x in self.diagnostics(obs) if 'trial wall' in x])          # every warm trial at or above 0.5 s
        obs[0]=dict(obs[0],panel_call_ns=400_000_000)
        flags=[x for x in self.diagnostics(obs) if 'trial wall' in x]
        self.assertEqual(len(flags),1);self.assertIn('below the 0.5 s',flags[0]);self.assertIn('py-reference xdirect',flags[0])
        self.assertIn('1 of 3 trials',flags[0]);self.assertIn('400 ms',flags[0])
        obs=[dict(o,mode='cold',panel_call_ns=1000) if o['variant']=='py-optimized' else o for o in obs]     # cold trials (L = 1) are never flagged
        self.assertEqual([x for x in self.diagnostics(obs) if 'trial wall' in x],flags)
    def test_a_warm_trial_without_a_recorded_wall_is_reported(self):
        obs=[dict(o,panel_call_ns=600_000_000) for o in fixture()];obs[1]={k:v for k,v in obs[1].items() if k!='panel_call_ns'}
        flags=[x for x in self.diagnostics(obs) if 'trial wall' in x]
        self.assertEqual(len(flags),1);self.assertIn('not recorded',flags[0]);self.assertIn('py-reference xdirect',flags[0]);self.assertIn('1 of 3 trials',flags[0])

# T6-R9 FW-CASES (FW-CASES-B08PROBE-01; B08, G7.1): a single-record (panel) trial reports the caller phases of its interval
# as every other caller trial does. prepare, work and materialize (and pool_start of a cold pool) are the sums over its
# 6 x L timed calls; the transport of a C trial is the sum of the codec's transport_ns of each call (benchlab.native_worker
# LAST_STATS, reset before each call, so a call without the value leaves the transport unknown). The one-row probe points
# of a smoke plan (T6-R7 wall_probes) are panel trials, so B08 reads their phases as those of every other C caller row.
class PanelPhaseTests(unittest.TestCase):
    PANEL={'indices':[0,1],'cells':['a','b'],'reference_status':['OK','OK'],'passes':3}       # 2 panel rows x L = 3: six timed calls
    def run_trial(self,variant,mode,workers='direct',transport=lambda n:7,route='stdio'):
        """(caller phases, note) of one panel trial of benchlab.trial.main with a stand-in marker, adapter and pool; the real
        run_panel times the calls. `transport(n)` is the codec's transport_ns of call n (None: the codec reports none)."""
        import os, tempfile
        path=str(ROOT/'benchmarks/performance/python')
        if path not in sys.path:sys.path.append(path)
        from benchlab import trial, native_worker as nw
        seen={'phases':[],'notes':{}};calls=[]
        class Marker:
            def __init__(self,*a,**k):self.commands=[{'op':'call','trial':'t0','panel':dict(PanelPhaseTests.PANEL)},{'op':'shutdown'}]
            def hello(self,client):pass
            def begin(self,*a):pass
            def end(self,phase,name,**k):
                if phase=='caller':seen['phases'].append(k.get('phases'))
            def note(self,name,**fields):seen['notes'][name]=fields
            def close(self):pass
            def command(self):return self.commands.pop(0)
        class Adapter:
            route=None;bench_ref=('benchlab.controlcase:Spin',{})
            def load(self,d):return 'data'
            def take(self,data,i):return [i]
            def prepare(self,sub,v,w):return list(sub)
            def run(self,p,v,w,pool=None):
                calls.append(p);t=transport(len(calls))
                if t is not None:nw.LAST_STATS.update(transport_ns=t,copied_bytes=8)
                return p
            def materialize(self,raw):return list(raw)
            def work_units(self,r):return 1
            def digest(self,r):return '0'*64
            def row_status(self,r):return 'OK'
        class Pool:
            def shutdown(self,wait=True):pass
        with tempfile.NamedTemporaryFile('w',suffix='.json',delete=False) as f:json.dump({},f)
        self.addCleanup(os.unlink,f.name);self.addCleanup(nw.LAST_STATS.clear)
        with mock.patch.object(trial,'Marker',Marker),mock.patch.object(trial,'load_case_adapter',lambda case,selector:Adapter()),\
             mock.patch.object(trial,'warm_start',lambda *a:Pool()),mock.patch.object(trial.pools,'verify_session_end',lambda:None):
            code=trial.main(['--client','x','--case-manifest',f.name,'--variant',variant,'--mode',mode,'--workers',str(workers),'--dataset','d',
                             '--sha256','0'*64,'--reference','none','--panel','--route',route,'--route-label','pipe'])
        self.assertEqual((code,len(calls),len(seen['phases'])),(0,6,1))
        return seen['phases'][0],seen['notes']['t0']
    def test_a_c_panel_trial_reports_the_four_phases_of_its_calls(self):
        ph,note=self.run_trial('c-serial','warm')
        for k in ('prepare','transport','work','materialize'):
            with self.subTest(phase=k):
                self.assertIs(type(ph.get(k)),int);self.assertGreaterEqual(ph[k],0)
        self.assertEqual(ph.get('transport'),6*7)             # the codec's transport_ns of each of the six calls
        self.assertIsNone(ph.get('pool_start'))           # a warm trial starts nothing inside its interval
        self.assertLessEqual(ph['prepare']+ph['work']+ph['materialize'],sum(sum(w) for w in note['panel_walls'].values()))   # inside the timed calls
    def test_a_cold_pooled_panel_trial_reports_its_pool_start(self):
        ph,_=self.run_trial('py-threads','cold',workers=2,transport=lambda n:None,route='none')
        for k in ('prepare','pool_start','work','materialize'):
            with self.subTest(phase=k):self.assertIs(type(ph.get(k)),int)
        self.assertIsNone(ph.get('transport'))            # a Python row reports no transport
    def test_a_call_without_its_transport_value_leaves_the_transport_unknown(self):
        ph,_=self.run_trial('c-serial','warm',transport=lambda n:7 if n==1 else None)
        self.assertIsNone(ph.get('transport'))            # never the stale value of an earlier call
        self.assertIs(type(ph.get('work')),int)
    def test_b08_accepts_the_row_of_a_one_row_probe(self):
        import bench_phase2 as b2
        ph,note=self.run_trial('c-serial','warm');labels=POL['routes']
        row={'trial_id':'probe-m1-one-row-s00-b00-00','point':'probe-m1-one-row','scope':'caller','warmup':False,'variant':'c-serial','workers':'direct',
             'mode':'warm','route':'stdio','route_label':labels['stdio'],'copied_bytes':note['copied_bytes'],'result_sha256':note['result_sha256'],
             'phases':{k:v for k,v in ph.items() if k in ('prepare','pool_start','work','materialize','transport')}}      # the coordinator's phase keys
        py={'trial_id':'py','scope':'caller','warmup':False,'variant':'py-reference','workers':'direct','mode':'warm'}
        start=[{'phase':'pool_start','mode':'warm','variant':'c-serial','workers':'direct','route':'stdio'}]
        self.assertEqual(b2.check_caller_scope([row,py],start,labels),[])
        self.assertEqual(b2.check_caller_scope([dict(row,phases=dict(row['phases'],transport=None)),py],start,labels),
                         ['probe-m1-one-row-s00-b00-00: the interval misses transport'])      # B08 keeps its rule for every C row

if __name__=='__main__':unittest.main()
