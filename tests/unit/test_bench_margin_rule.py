"""EX-18a: the two-condition unit rule of a unit-threshold policy (`margin_rule`, project data) and finding EX17-A01.

A unit-threshold policy can declare a relative margin of the candidate rows over the base rows, with the base and the
candidate variant families and the routes. A route prefers the candidate only when both conditions are decided true:
(1) the warm wall per request of the base family is at or above the policy threshold, on its order-statistic bounds, and
(2) a candidate row on that route is faster than the base row by more than the margin, on the order-statistic interval
of the median of the per-block ratios (end to end: the caller-scope rows hold the transfer of the route). Every other
outcome keeps the base with a reason that names each failed or undecided condition. The framework names no value: these
tests declare their own margins on the synthetic engine test policy (selectors m1..m5).

EX17-A01: decide detects the candidate rows that a plan removed (`--matrix python`, or any plan without a row of the
declared case). A rule-policy decision then is INCONCLUSIVE (rule 2, required evidence missing); a unit without a measured
candidate row is never a plain KEEP_PYTHON (single-condition rule: INCONCLUSIVE c-evidence-missing; two-condition rule:
KEEP_PYTHON with the reason candidate-not-measured)."""
import argparse, copy, json, shutil, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import bench_units as bu, bench_model as bm, bench_plan as bp, bench_decide as bd
from evidence import GateError
from schema_check import validate
sys.path.insert(0,str(ROOT/'tests/unit'))
import test_bench_units as tu, test_bench_protocol_file as tp, test_bench_b17 as tb

POL=tu.POL;T=tu.T;ST=tu.ST;row=tu.row;uev=tu.uev;const=tu.const
U='m3/full-dataset';M=0.25;LIMIT=0.75        # the margin of these tests: the ratio bound 1 - 0.25 is exact in binary
RULE={'base_variants':['py-reference','py-optimized'],'candidate_variants':['c-serial','c-threads'],'routes':['stdio','shm','inproc'],'margin':M}
MPOL=dict(POL,margin_rule=RULE)
B=2*T                                         # a base row at twice the threshold
def rule(**over):return dict(POL,margin_rule=dict(RULE,**over))
def mone(ev,pol=MPOL,unit=U):return bu.decide_unit(unit,ev,pol,ST)
def base(v=B):return [row('py-optimized','python',v)]+tu.GUARD_ROWS      # the guard rows: py-reference is in the base family
def cand(v,route='stdio',variant='c-serial',workers='direct'):return row(variant,'c',v,route=route,workers=workers)
def route_of(r,name):return next(x for x in r['margin_rule']['routes'] if x['route']==name)
def pair(r):return (r['verdict'],r['reason'])
EXC={'unit':U,'label':'c-serial xdirect [stdio]','reason':'excluded by --matrix python'}

class BothConditionsTests(unittest.TestCase):
    def test_both_conditions_met_prefers_the_candidate(self):
        r=mone(uev(base()+[cand(T)]))
        self.assertEqual((r['verdict'],r['reason'],r['verdict_safe_route'],r['reason_safe_route'],r['default_action']),
                         ('PREFER_C','both-conditions-met','PREFER_C','both-conditions-met','PREFER_C'))
        m=r['margin_rule'];self.assertEqual((m['margin'],m['ratio_bound'],m['threshold_ms'],m['k']),(M,LIMIT,T/1e6,1))
        self.assertEqual((m['base_variants'],m['candidate_variants']),(RULE['base_variants'],RULE['candidate_variants']))
        self.assertEqual(m['base'],{'rows':['py-optimized xdirect'],'P':'py-optimized xdirect','low_ms':B/1e6,'high_ms':B/1e6,'decision':'met','reason':None,'detail':None})
        s=route_of(r,'stdio')
        self.assertEqual((s['candidate'],s['ratio'],s['ratio_low'],s['ratio_high'],s['decision'],s['verdict'],s['reasons'],s['safe']),
                         ('c-serial xdirect [stdio]',0.5,0.5,0.5,'met','PREFER_C',[],True))
        self.assertEqual(s['rows'],[{'label':'c-serial xdirect [stdio]','ratio':0.5,'ratio_low':0.5,'ratio_high':0.5,'decision':'met'}])
        for name in ('shm','inproc'):
            x=route_of(r,name)
            self.assertEqual((x['decision'],x['verdict'],x['reasons'],x['candidate']),('not-measured','KEEP_PYTHON',['candidate-not-measured'],None))
        self.assertFalse(route_of(r,'inproc')['safe'])
        self.assertEqual([x['route'] for x in r['margin_rule']['routes']],RULE['routes'])
    def test_the_margin_decides_and_not_the_plain_candidate_claim(self):
        ev=uev(base()+[cand(0.8*B)])                       # the candidate is 20 % faster: the ratio 0.8
        self.assertEqual(pair(mone(ev)),('KEEP_PYTHON','candidate-margin-not-met'))
        self.assertEqual(route_of(mone(ev),'stdio')['reasons'],['candidate-margin-not-met'])
        self.assertEqual(pair(bu.decide_unit(U,ev,POL,ST)),('PREFER_C','c-reliably-faster'))     # without the rule: ratio < 1 suffices
        self.assertEqual(pair(mone(ev,rule(margin=0.125))),('PREFER_C','both-conditions-met'))   # the margin is the policy's value
    def test_the_margin_is_strict(self):
        self.assertEqual(pair(mone(uev(base(4e8)+[cand(3e8)]))),('KEEP_PYTHON','candidate-margin-not-met'))   # ratio exactly 0.75
        self.assertEqual(route_of(mone(uev(base(4e8)+[cand(3e8)])),'stdio')['ratio'],LIMIT)
        self.assertEqual(pair(mone(uev(base(4e8)+[cand(3e8-1)]))),('PREFER_C','both-conditions-met'))    # one past the bound
    def test_a_ratio_interval_across_the_bound_is_undecided(self):
        x=cand(B);x['wall']={b:B*(0.5 if b%2 else 1.0) for b in range(12)}      # per-block ratios 0.5 and 1.0: [0.5, 1.0]
        r=mone(uev(base()+[x]));s=route_of(r,'stdio')
        self.assertEqual(pair(r),('KEEP_PYTHON','candidate-margin-undecided'))
        self.assertEqual((s['decision'],s['ratio_low'],s['ratio_high'],s['reasons']),('undecided',0.5,1.0,['candidate-margin-undecided']))

class BaseConditionTests(unittest.TestCase):
    def test_a_base_under_the_threshold_keeps_the_base(self):
        r=mone(uev(base(T/2)+[cand(T/20)]))
        self.assertEqual((r['verdict'],r['reason'],r['verdict_safe_route'],r['reason_safe_route']),
                         ('KEEP_PYTHON','base-under-threshold','KEEP_PYTHON','base-under-threshold'))
        self.assertEqual(r['margin_rule']['base']['decision'],'not-met');self.assertEqual(r['margin_rule']['base']['reason'],'base-under-threshold')
        s=route_of(r,'stdio');self.assertEqual((s['decision'],s['verdict'],s['reasons']),('met','KEEP_PYTHON',['base-under-threshold']))
    def test_a_base_interval_across_the_threshold_is_undecided(self):
        noisy=row('py-optimized','python',T);noisy['wall']={b:T*(0.9 if b%2 else 1.1) for b in range(12)}
        r=mone(uev([noisy]+tu.GUARD_ROWS+[cand(T/10)]))
        self.assertEqual(pair(r),('KEEP_PYTHON','base-threshold-undecided'));self.assertTrue(r['extension']['trigger'])
        b=r['margin_rule']['base'];self.assertEqual((b['decision'],b['low_ms'],b['high_ms']),('undecided',0.9*T/1e6,1.1*T/1e6))
        self.assertEqual(route_of(r,'stdio')['reasons'],['base-threshold-undecided'])
    def test_a_base_exactly_at_the_threshold_meets_it(self):
        self.assertEqual(pair(mone(uev(base(T)+[cand(T/2)]))),('PREFER_C','both-conditions-met'))
        self.assertEqual(pair(mone(uev(base(T-1)+[cand(T/2)]))),('KEEP_PYTHON','base-under-threshold'))
    def test_a_missing_base_row_is_not_measured(self):
        r=mone(uev(base()+[cand(T)],blocked_other=[{'unit':U,'label':'py-reference xdirect','reason':'launch failed'}]))
        self.assertEqual(pair(r),('KEEP_PYTHON','base-not-measured'));self.assertEqual(r['margin_rule']['base']['decision'],'not-measured')
    def test_the_full_dataset_guard_of_a_base_reference_row(self):
        ev=uev([row('py-optimized','python',B),cand(T)])     # no single-record py-reference row: the guard has no input
        r=mone(ev);self.assertEqual(pair(r),('KEEP_PYTHON','base-not-measured'))
        self.assertEqual(r['margin_rule']['base']['detail'],'py-reference-not-measured')
        self.assertEqual(pair(mone(ev,rule(base_variants=['py-optimized']))),('PREFER_C','both-conditions-met'))
    def test_a_unit_without_a_base_row(self):
        r=mone(uev([cand(T)]));self.assertEqual(pair(r),('KEEP_PYTHON','base-not-measured'))
        self.assertIsNone(r['margin_rule']['base']['P']);self.assertEqual(route_of(r,'stdio')['decision'],'not-measured')

class CandidateTests(unittest.TestCase):
    def test_a_run_without_a_candidate_row_names_the_candidate(self):      # EX17-A01 under the two-condition rule
        for ev,base_decision in ((uev(base()),'met'),(uev(base(T/2)),'not-met'),(uev(base(),blocked_other=[EXC]),'met')):
            with self.subTest(base=base_decision):
                r=mone(ev)
                self.assertEqual((r['verdict'],r['reason'],r['verdict_safe_route'],r['reason_safe_route']),
                                 ('KEEP_PYTHON','candidate-not-measured','KEEP_PYTHON','candidate-not-measured'))
                self.assertEqual(r['margin_rule']['base']['decision'],base_decision)
                for x in r['margin_rule']['routes']:
                    self.assertEqual(x['decision'],'not-measured');self.assertIn('candidate-not-measured',x['reasons'])
        r=mone(uev(base(T/2)));self.assertEqual(route_of(r,'stdio')['reasons'],['base-under-threshold','candidate-not-measured'])
        r=mone(uev(base(),blocked_other=[EXC]))
        self.assertIn({'label':'c-serial xdirect [stdio]','reason':'excluded by --matrix python'},r['missing_rows'])
    def test_each_route_is_judged_separately(self):
        r=mone(uev(base()+[cand(0.5*B,'stdio'),cand(0.9*B,'shm'),cand(0.4*B,'inproc')]))
        self.assertEqual((r['verdict'],r['reason'],r['verdict_safe_route'],r['reason_safe_route']),
                         ('PREFER_C','both-conditions-met','PREFER_C','both-conditions-met'))
        self.assertEqual([(x['route'],x['verdict'],x['reasons']) for x in r['margin_rule']['routes']],
                         [('stdio','PREFER_C',[]),('shm','KEEP_PYTHON',['candidate-margin-not-met']),('inproc','PREFER_C',[])])
        self.assertEqual((r['C']['route'],r['C_safe']['route'],r['margin_rule']['k']),('inproc','stdio',3))
        r=mone(uev(base()+[cand(0.9*B,'stdio'),cand(0.9*B,'shm'),cand(0.4*B,'inproc')]))
        self.assertEqual((r['verdict'],r['verdict_safe_route'],r['reason_safe_route']),('PREFER_C','KEEP_PYTHON','candidate-margin-not-met'))
        self.assertIn('safe routes: KEEP_PYTHON (candidate-margin-not-met)',r['summary_line'])
        self.assertEqual(r['less_safe_label'],bu.LESS_SAFE_LABEL)
    def test_the_bonferroni_level_counts_every_candidate_row(self):
        x=cand(B);x['wall']={b:B*(0.3+0.04*b) for b in range(12)}
        rows=base()+[x,cand(0.9*B,'shm',variant='c-threads',workers=2),cand(0.9*B,'inproc')]
        r=mone(uev(rows));s=route_of(r,'stdio');P=rows[0]
        self.assertEqual(r['margin_rule']['k'],3)
        lo,hi=bu.ratio_bounds(P['wall'],x['wall'],3,1)
        self.assertEqual((s['ratio_low'],s['ratio_high']),(lo,hi));self.assertNotEqual((lo,hi),bu.ratio_bounds(P['wall'],x['wall'],1,1))
    def test_a_missing_candidate_row_on_a_route(self):
        r=mone(uev(base()+[cand(T)],blocked_other=[{'unit':U,'label':'c-serial xdirect [shm]','reason':'route refused'}]))
        self.assertEqual(pair(r),('PREFER_C','both-conditions-met'));self.assertEqual(route_of(r,'shm')['decision'],'not-measured')
        r=mone(uev(base()+[cand(0.9*B,'shm')],blocked_other=[{'unit':U,'label':'c-threads x2 [shm]','reason':'route refused'}]))
        self.assertEqual(route_of(r,'shm')['decision'],'not-measured');self.assertEqual(pair(r),('KEEP_PYTHON','candidate-not-measured'))
        short=cand(T);short['wall']=const(T,11)                               # not measured in every block of this look
        r=mone(uev(base()+[short]));self.assertEqual(pair(r),('KEEP_PYTHON','candidate-not-measured'))
        self.assertIn({'label':'c-serial xdirect [stdio]','reason':'not measured in every block of this look'},r['missing_rows'])
    def test_an_undecided_route_comes_before_a_route_that_misses_the_margin(self):
        x=cand(B,'shm');x['wall']={b:B*(0.5 if b%2 else 1.0) for b in range(12)}
        self.assertEqual(pair(mone(uev(base()+[cand(0.9*B),x]))),('KEEP_PYTHON','candidate-margin-undecided'))
    def test_rows_outside_the_families_never_decide(self):
        rows=base()+[row('py-library','python-library',T/2),cand(T/10,'stdio',variant='c-threads',workers=2),cand(T/10,'inproc')]
        r=mone(uev(rows),rule(candidate_variants=['c-serial'],routes=['stdio','shm']))
        self.assertEqual(r['margin_rule']['base']['decision'],'met');self.assertEqual(pair(r),('KEEP_PYTHON','candidate-not-measured'))
        self.assertEqual([x['route'] for x in r['margin_rule']['routes']],['stdio','shm'])
        self.assertEqual(r['missing_rows'],[]);self.assertEqual(r['python_rows'][0]['label'],'py-optimized xdirect')
        self.assertEqual(pair(bu.decide_unit(U,uev(rows),POL,ST)),('KEEP_PYTHON','python-under-threshold'))    # the library row decides without the rule
    def test_a_candidate_that_is_not_eligible_keeps_the_base(self):
        r=mone(uev(base()+[cand(T)],opportunity_state='PENDING'))
        self.assertEqual((r['verdict'],r['reason'],r['failed_conditions']),('KEEP_PYTHON','candidate-not-eligible',['opportunity-not-approved']))
        s=route_of(r,'stdio');self.assertEqual((s['decision'],s['verdict'],s['reasons']),('met','KEEP_PYTHON',['candidate-not-eligible']))
        r=mone(uev(base()+[cand(T)],project_check=tq_check('Q01')))
        self.assertEqual((r['reason'],r['failed_conditions']),('candidate-not-eligible',['framework-unqualified']))
    def test_an_invalid_run_stays_invalid(self):
        r=mone(uev(base()+[cand(T)],status='INVALID_EXPERIMENT'))
        self.assertEqual(pair(r),('INVALID_EXPERIMENT','run-invalid'));self.assertIsNone(r['margin_rule'])
        r=mone(uev(base()+[row('c-serial','c',T,route='stdio',eligible=False)]))
        self.assertEqual(pair(r),('INVALID_EXPERIMENT','ineligible-row'));self.assertIsNone(r['margin_rule'])
    def test_a_policy_without_the_rule_has_no_margin_record(self):
        self.assertIsNone(bu.decide_unit(U,uev(base()+[cand(T)]),POL,ST)['margin_rule'])

def tq_check(row_id):return tu.tq.qualified(row_id)

# EX18a-A01: the plan blocks the inproc cold cell by design (not-applicable: the library load is the startup phase). A
# blocked row that names another mode than the verdict mode is no missing candidate row of the verdict; a blocked row of
# the verdict mode, and a blocked row without a mode (it applies to every mode), still is.
COLD={'unit':U,'label':'c-serial xdirect [inproc]','reason':bp.INPROC_COLD,'mode':'cold'}

class VerdictModeBlockedRowTests(unittest.TestCase):
    def test_an_inproc_cold_cell_blocked_by_design_is_no_missing_candidate_row(self):
        r=mone(uev(base()+[cand(0.5*B,'inproc')],blocked_other=[COLD]));x=route_of(r,'inproc')
        self.assertEqual((x['decision'],x['verdict'],x['reasons']),('met','PREFER_C',[]))
        self.assertEqual(pair(r),('PREFER_C','both-conditions-met'))
        r=mone(uev(base()+[cand(0.9*B,'inproc')],blocked_other=[COLD]));x=route_of(r,'inproc')
        self.assertEqual((x['decision'],x['detail'],x['reasons']),('not-met',None,['candidate-margin-not-met']))
        self.assertEqual(pair(r),('KEEP_PYTHON','candidate-margin-not-met'))
        self.assertNotIn(COLD['label'],[m['label'] for m in r['missing_rows']])
        self.assertEqual(bu._owner_summary([r],uev([]),{},MPOL)['missing_evidence'],'none')      # the owner summary names no missing evidence
    def test_a_blocked_row_of_the_verdict_mode_or_without_a_mode_still_counts(self):
        for blocked in (dict(COLD,mode='warm',reason='launch failed'),{k:v for k,v in COLD.items() if k!='mode'}):
            with self.subTest(mode=blocked.get('mode')):
                r=mone(uev(base()+[cand(0.9*B,'inproc')],blocked_other=[blocked]))
                self.assertEqual((route_of(r,'inproc')['decision'],route_of(r,'inproc')['detail']),('not-measured','a planned candidate row of the route is missing'))
                self.assertEqual(pair(r),('KEEP_PYTHON','candidate-not-measured'))
                self.assertIn(blocked['label'],[m['label'] for m in r['missing_rows']])
    def test_a_base_row_blocked_in_another_mode_is_no_missing_base_row(self):
        cold_base={'unit':U,'label':'py-optimized xdirect','reason':'cold start refused','mode':'cold'}
        self.assertEqual(mone(uev(base()+[cand(T)],blocked_other=[cold_base]))['margin_rule']['base']['decision'],'met')
        self.assertEqual(mone(uev(base()+[cand(T)],blocked_other=[dict(cold_base,mode='warm')]))['margin_rule']['base']['decision'],'not-measured')
    def test_the_single_condition_rule_reads_the_verdict_mode_too(self):
        r=bu.decide_unit(U,uev(base()+[cand(1.5*B,'inproc')],blocked_other=[COLD]),POL,ST)
        self.assertEqual(pair(r),('KEEP_PYTHON','c-not-reliably-faster'))
        r=bu.decide_unit(U,uev(base()+[cand(1.5*B,'inproc')],blocked_other=[dict(COLD,mode='warm')]),POL,ST)
        self.assertEqual(pair(r),('INCONCLUSIVE','c-evidence-missing'))
    def test_the_blocked_rows_of_a_plan_keep_their_mode(self):
        plan={'blocked_rows':[{'variant':'c-serial','workers':'direct','route':'inproc','mode':'cold','reason':bp.INPROC_COLD},
                              {'variant':'c-threads','workers':2,'route':'shm','reason':'route refused'}]}
        env,other=bu._blocked(plan,[U])
        self.assertEqual(env,[])
        self.assertEqual(other,[{'unit':U,'label':'c-serial xdirect [inproc]','reason':bp.INPROC_COLD,'mode':'cold'},
                                {'unit':U,'label':'c-threads x2 [shm]','reason':'route refused'}])
    def test_a_real_plan_blocks_the_inproc_cold_cell_and_the_unit_decides_the_route(self):
        plan=tb.smoke_plan(tb.direct_case());cold=[b for b in plan['blocked_rows'] if b.get('mode')=='cold']
        self.assertEqual([(b['variant'],b['route'],b['reason']) for b in cold],[('c-serial','inproc',bp.INPROC_COLD)])
        env,other=bu._blocked(plan,[U])
        r=mone(uev(base()+[cand(0.5*B,'stdio'),cand(0.5*B,'shm'),cand(0.9*B,'inproc')],blocked_other=other))
        self.assertEqual([(x['route'],x['decision']) for x in r['margin_rule']['routes']],[('stdio','met'),('shm','met'),('inproc','not-met')])

SCENARIOS=lambda:[uev(base()+[cand(T)]),uev(base()+[cand(0.8*B)]),uev(base(T/2)+[cand(T/20)]),uev(base()),uev(base(),blocked_other=[EXC]),
                  uev(base()+[cand(0.5*B,'stdio'),cand(0.9*B,'shm'),cand(0.4*B,'inproc')]),uev(base()+[cand(T)],opportunity_state='PENDING'),
                  uev(base()+[cand(T)],status='INVALID_EXPERIMENT'),uev([cand(T)])]

class MarginRecordTests(unittest.TestCase):
    def test_every_margin_record_validates(self):
        v=tu.units_validator()
        for k,ev in enumerate(SCENARIOS()):
            with self.subTest(scenario=k):
                recs=bu.decide_units(ev,MPOL,ST);v.validate({'units':recs})
                with mock.patch('bench_decide._current_identity',return_value='a'*64):
                    rec=bu.unit_decision_record(ROOT,{'run_id':'0'*32,'case':'fixture-case','mode':'decision','source_identity':'a'*64,'image_id':'sha256:'+'1'*64,
                                                      'dataset':{'kind':'synthetic'}},{},{'case_id':'fixture-case','variants':[]},MPOL,recs,ev,{})
                validate(ROOT,'bench-decision',rec)
    def test_the_schema_keeps_the_outcomes_of_the_rule(self):
        v=tu.units_validator();i=POL['units'].index(U)
        recs=bu.decide_units(uev(base()+[cand(T)]),MPOL,ST);self.assertTrue(v.is_valid({'units':recs}))
        keep=bu.decide_units(uev(base()+[cand(0.8*B)]),MPOL,ST);self.assertTrue(v.is_valid({'units':keep}))
        def bad(recs,edit):
            out=copy.deepcopy(recs);edit(out[i]);return v.is_valid({'units':out})
        edits={'inconclusive':lambda u:u.update(verdict='INCONCLUSIVE',reason='c-evidence-missing',verdict_safe_route='INCONCLUSIVE',reason_safe_route='c-evidence-missing',default_action='KEEP_PYTHON',next_action=None),
               'reason-without-rule':lambda u:u.update(margin_rule=None),
               'route-prefers-with-a-reason':lambda u:u['margin_rule']['routes'][0].update(reasons=['candidate-margin-not-met']),
               'route-keeps-without-a-reason':lambda u:u['margin_rule']['routes'][1].update(reasons=[]),
               'route-prefers-unmet':lambda u:u['margin_rule']['routes'][0].update(decision='undecided'),
               'unknown-decision':lambda u:u['margin_rule']['base'].update(decision='unknown'),
               'unknown-key':lambda u:u['margin_rule'].update(score=1),
               'unknown-route':lambda u:u['margin_rule']['routes'][0].update(route='ftp'),
               'unqualified-prefer':lambda u:u.update(framework_label='framework unqualified')}
        for name,edit in edits.items():
            with self.subTest(edit=name):self.assertFalse(bad(recs,edit))
        with self.subTest(edit='old-reason-with-rule'):
            self.assertFalse(bad(keep,lambda u:u.update(reason='c-not-reliably-faster',reason_safe_route='c-not-reliably-faster')))
        with self.subTest(edit='rule-reason-without-rule'):
            plain=bu.decide_units(uev(base()+[cand(0.8*B)]),POL,ST)
            self.assertFalse(bad(plain,lambda u:u.update(verdict='KEEP_PYTHON',reason='candidate-margin-not-met',verdict_safe_route='KEEP_PYTHON',
                                                          reason_safe_route='candidate-margin-not-met',default_action='KEEP_PYTHON',next_action=None)))
    def test_a_preferred_unit_or_route_needs_the_base_met_and_a_preferred_route(self):     # EX18a-A03
        v=tu.units_validator();i=POL['units'].index(U)
        def valid(recs,edit):
            out=copy.deepcopy(recs);edit(out[i]);return v.is_valid({'units':out})
        def keep_routes(u,safe_only=False):
            for x in u['margin_rule']['routes']:
                if x['safe'] or not safe_only:x.update(verdict='KEEP_PYTHON',decision='not-met',reasons=['candidate-margin-not-met'])
        prefer=bu.decide_units(uev(base()+[cand(T)]),MPOL,ST);self.assertTrue(v.is_valid({'units':prefer}))
        both=bu.decide_units(uev(base()+[cand(0.5*B,'stdio'),cand(0.9*B,'shm'),cand(0.4*B,'inproc')]),MPOL,ST)
        self.assertTrue(v.is_valid({'units':both}))
        under=bu.decide_units(uev(base(T/2)+[cand(T/20)]),MPOL,ST);self.assertTrue(v.is_valid({'units':under}))
        bad={'unit-prefers-with-the-base-not-met':(prefer,lambda u:u['margin_rule']['base'].update(decision='not-met',reason='base-under-threshold')),
             'unit-prefers-with-the-base-undecided':(prefer,lambda u:u['margin_rule']['base'].update(decision='undecided',reason='base-threshold-undecided')),
             'unit-prefers-without-a-preferred-route':(prefer,keep_routes),
             'safe-route-prefers-without-a-preferred-safe-route':(both,lambda u:keep_routes(u,safe_only=True)),
             'route-prefers-with-the-base-not-met':(under,lambda u:route_of(u,'stdio').update(verdict='PREFER_C',decision='met',reasons=[]))}
        for name,(recs,edit) in bad.items():
            with self.subTest(edit=name):self.assertFalse(valid(recs,edit))
        with self.subTest(edit='control: the less safe route alone prefers'):
            self.assertTrue(valid(both,lambda u:u.update(verdict_safe_route='KEEP_PYTHON',reason_safe_route='candidate-margin-not-met') or keep_routes(u,safe_only=True)))
    def test_old_records_without_the_field_stay_valid(self):        # the schema change is additive
        v=tu.units_validator();recs=bu.decide_units(uev(base()+[cand(T)]),POL,ST)
        for u in recs:u.pop('margin_rule')
        self.assertTrue(v.is_valid({'units':recs}))
    def test_the_markdown_names_both_conditions_per_route(self):
        recs=bu.decide_units(uev(base()+[cand(T)]),MPOL,ST)
        with mock.patch('bench_decide._current_identity',return_value='a'*64):
            rec=bu.unit_decision_record(ROOT,{'run_id':'0'*32,'case':'fixture-case','mode':'decision','source_identity':'a'*64,'image_id':'sha256:'+'1'*64,
                                              'dataset':{'kind':'synthetic'}},{},{'case_id':'fixture-case','variants':[]},MPOL,recs,uev([]),{})
        md=bu.render_units_markdown(rec)
        self.assertIn('- Margin rule: margin 0.25 (ratio bound 0.75), threshold 200 ms, k 1; base py-optimized xdirect [400, 400] ms: met',md)
        self.assertIn('- Margin route stdio: c-serial xdirect [stdio] ratio 0.5 [0.5, 0.5]: met; PREFER_C',md)
        self.assertIn('- Margin route shm: none: not-measured; KEEP_PYTHON (candidate-not-measured)',md)
        self.assertIn('more than 25 % faster',rec['summary']['problem'])

def protocol_doc():return json.loads((ROOT/tp.FIXTURE/bm.PROJECT_AREA/bm.PROTOCOL_FILE).read_text())
def with_rule(doc,value):
    out=copy.deepcopy(doc);out['decision_policies'][tp.POLICY]['margin_rule']=value;return out

class ProtocolDeclarationTests(unittest.TestCase):
    def test_a_protocol_declares_the_rule_and_the_policy_carries_it(self):
        t=tp.scratch(self);doc=with_rule(tp.protocol(t),RULE);tp.rebind(t,doc)
        pol=bm.load_decision_policy(t,tp.POLICY,tp.FIXTURE)
        self.assertEqual(pol['margin_rule'],RULE);self.assertTrue(bm.policy_filled(pol))
        self.assertNotIn('margin_rule',bm.load_decision_policy(ROOT,tp.POLICY,tp.FIXTURE))     # the rule is optional
    def test_the_schema_refuses_a_bad_declaration(self):
        import jsonschema
        v=jsonschema.Draft202012Validator(json.loads((ROOT/'schemas/bench-protocol.json').read_text()));doc=protocol_doc()
        self.assertTrue(v.is_valid(with_rule(doc,RULE)))
        bad={'margin-zero':dict(RULE,margin=0),'margin-one':dict(RULE,margin=1),'margin-negative':dict(RULE,margin=-0.25),'margin-above-one':dict(RULE,margin=1.5),
             'margin-text':dict(RULE,margin='0.25'),'margin-bool':dict(RULE,margin=True),'margin-null':dict(RULE,margin=None),
             'candidate-in-base':dict(RULE,base_variants=['c-serial']),'base-in-candidate':dict(RULE,candidate_variants=['py-optimized']),
             'empty-base':dict(RULE,base_variants=[]),'empty-candidate':dict(RULE,candidate_variants=[]),'empty-routes':dict(RULE,routes=[]),
             'repeated-base':dict(RULE,base_variants=['py-optimized','py-optimized']),'unknown-route':dict(RULE,routes=['ftp']),
             'unknown-key':dict(RULE,threshold_ns_per_request=1),'not-an-object':[RULE]}
        for key in RULE:bad[f'missing-{key}']={k:x for k,x in RULE.items() if k!=key}
        for name,value in bad.items():
            with self.subTest(case=name):self.assertFalse(v.is_valid(with_rule(doc,value)))
    def test_a_bad_declaration_is_refused_at_load(self):
        t=tp.scratch(self);tp.rebind(t,with_rule(tp.protocol(t),dict(RULE,margin=0)))
        with self.assertRaises(GateError):bm.load_protocol(t,tp.FIXTURE)

# EX18a-A04: at protocol load, every declared base variant must be planned at every point of a policy unit, or be a
# blocked row of the plan with a reason (a planned-phase-2 variant). The plan never measures py-reference at the large
# size (the G8.2 guard estimates it there), so py-reference may be absent from a large unit point. Otherwise the
# protocol, and so every plan of the project, is refused with the stable reason margin-base-not-planned.
UNIT_POINT={'name':'unit-four-full','scope':'caller','size':'small','modes':['warm','cold'],'variants':['py-reference','py-library','c-serial'],
            'class':'primary','selector':'m4','unit':'m4/full-dataset'}

def with_point(t,point,variants=None):
    """The fixture case of the scratch root `t` with one more point (and, optionally, other variants)."""
    p=tp.area(t)/'cases/fixture-case.json';case=json.loads(p.read_text());case['points'].append(point)
    if variants is not None:case['variants']=variants
    p.write_text(json.dumps(case))

class BaseDeclarationTests(unittest.TestCase):
    def load(self,rule_value,point=UNIT_POINT,variants=None):
        t=tp.scratch(self);with_point(t,point,variants);tp.rebind(t,with_rule(tp.protocol(t),rule_value));return bm.load_protocol(t,tp.FIXTURE)
    def test_every_base_variant_planned_at_every_unit_point_loads(self):
        self.assertEqual(self.load(dict(RULE,base_variants=['py-reference','py-library']))['decision_policies'][tp.POLICY]['margin_rule']['base_variants'],
                         ['py-reference','py-library'])
    def test_a_base_variant_without_a_row_or_a_blocked_row_is_refused(self):
        for name,value,point in (('same-as-reference',dict(RULE,base_variants=['py-reference','py-optimized']),UNIT_POINT),
                                 ('not-in-the-point',dict(RULE,base_variants=['py-reference','py-library']),dict(UNIT_POINT,variants=['py-reference','c-serial'])),
                                 ('not-declared',dict(RULE,base_variants=['py-reference','py-threads']),UNIT_POINT)):
            with self.subTest(case=name):
                with self.assertRaises(GateError) as e:self.load(value,point)
                self.assertIn('margin-base-not-planned',str(e.exception));self.assertIn('unit-four-full',str(e.exception))
    def test_a_planned_phase_2_base_variant_is_a_blocked_row_with_a_reason(self):
        case=json.loads((ROOT/tp.FIXTURE/bm.PROJECT_AREA/'cases/fixture-case.json').read_text())
        variants=[dict(v,status='planned-phase-2') if v['id']=='py-library' else v for v in case['variants']]
        self.load(dict(RULE,base_variants=['py-reference','py-library']),variants=variants)
    def test_py_reference_may_be_absent_at_the_large_size(self):
        large=dict(UNIT_POINT,size='large',variants=['py-library','c-serial'])
        self.load(dict(RULE,base_variants=['py-reference','py-library']),large)
        with self.assertRaises(GateError):self.load(dict(RULE,base_variants=['py-reference','py-library']),dict(large,size='medium'))
    def test_a_unit_without_a_point_and_a_policy_without_the_rule_load(self):
        self.load(dict(RULE,base_variants=['py-optimized']),{k:v for k,v in UNIT_POINT.items() if k!='unit'})     # no point of a policy unit
        t=tp.scratch(self);with_point(t,UNIT_POINT);self.assertIsNotNone(bm.load_protocol(t,tp.FIXTURE))       # a policy without the rule

class CoverageArgumentTests(unittest.TestCase):                # EX18a-A02
    def test_the_docs_record_why_the_b09_coverage_holds_at_the_margin_bound(self):
        text=' '.join((ROOT/'docs/performance-laboratory.md').read_text().split())
        for phrase in ('scale invariance of the order statistic','U(r) < 1 - m holds exactly when U(r/(1 - m)) < 1',
                       'B09 does not run margin_unit, _base_condition or _route_condition'):
            with self.subTest(phrase=phrase):self.assertIn(phrase,text)
        self.assertIn('B09 does not run',' '.join(bu.__doc__.split()))        # the module text names the path that B09 does not run

class SingleConditionTests(unittest.TestCase):                 # EX17-A01 under the single-condition rule
    def test_no_measured_candidate_with_a_missing_candidate_row_is_never_a_plain_keep(self):
        r=bu.decide_unit(U,uev(tu.PY(T-1),blocked_other=[EXC]),POL,ST)
        self.assertEqual((r['verdict'],r['reason'],r['verdict_safe_route'],r['reason_safe_route']),
                         ('INCONCLUSIVE','c-evidence-missing','INCONCLUSIVE','c-evidence-missing'))
        self.assertIn({'label':'c-serial xdirect [stdio]','reason':'excluded by --matrix python'},r['missing_rows'])
        self.assertEqual((r['H_pi'] or {}).get('value_ms') is not None,True)           # the Python bounds stay in the record
        short=cand(T/2);short['wall']=const(T/2,11)
        self.assertEqual(pair(bu.decide_unit(U,uev(tu.PY(T-1)+[short]),POL,ST)),('INCONCLUSIVE','c-evidence-missing'))
        tu.units_validator().validate({'units':bu.decide_units(uev(tu.PY(T-1),blocked_other=[EXC]),POL,ST)})
    def test_controls_keep_python_under_the_threshold(self):
        self.assertEqual(pair(bu.decide_unit(U,uev(tu.PY(T-1)),POL,ST)),('KEEP_PYTHON','python-under-threshold'))       # no candidate is planned
        self.assertEqual(pair(bu.decide_unit(U,uev(tu.PY(T-1)+[cand(T/2)],blocked_other=[dict(EXC,label='c-threads x2 [stdio]')]),POL,ST)),
                         ('KEEP_PYTHON','python-under-threshold'))                                                     # a candidate row is measured
        self.assertEqual(pair(bu.decide_unit(U,uev(tu.PY(2*T)+tu.GUARD_ROWS,blocked_other=[EXC]),POL,ST)),('INCONCLUSIVE','c-evidence-missing'))

ENV2={'cpus':2,'cpuset':[0,1],'smt_siblings':[],'reduced':True,'multicore':'PASS'}

class ExcludedRowTests(unittest.TestCase):
    def test_a_python_plan_excludes_every_candidate_row(self):
        case=tb.full_case();plan=tb.smoke_plan(case,matrix='python');rows,blocked=bp.case_rows(case,tb.ENV4)
        ex=bp.excluded_rows(case,plan)
        self.assertEqual(sorted((e['variant'],str(e['workers']),e['route']) for e in ex),
                         sorted((r['variant'],str(r['workers']),r.get('route')) for r in rows+blocked if r['variant'].startswith('c-')))
        self.assertEqual(len(ex),9);self.assertEqual({e['reason'] for e in ex},{bp.EXCLUDED_PYTHON});self.assertEqual(bp.EXCLUDED_PYTHON,'excluded by --matrix python')
    def test_a_full_plan_excludes_nothing(self):
        case=tb.full_case();self.assertEqual(bp.excluded_rows(case,tb.smoke_plan(case)),[])
        wide=tb.full_case();wide['variants']=[dict(v,workers=[1,2,4]) if v['id']=='c-threads' else v for v in wide['variants']]
        self.assertEqual(bp.excluded_rows(wide,tb.smoke_plan(wide,envelope=ENV2)),[])      # a row beyond the envelope is a blocked row, not an excluded one
    def test_any_plan_without_a_declared_row(self):
        case=tb.full_case();plan=tb.smoke_plan(case)
        edited=dict(plan,rows=[r for r in plan['rows'] if (r['variant'],r['workers'],r.get('route'))!=('c-threads',2,'shm')])
        self.assertEqual(bp.excluded_rows(case,edited),[{'variant':'c-threads','workers':2,'route':'shm','reason':bp.EXCLUDED_PLAN}])
        self.assertEqual(bp.excluded_rows(case,{}),[]);self.assertEqual(bp.excluded_rows({'case_id':'x'},plan),[])
        phase2=dict(case,variants=[v for v in case['variants'] if v['language']!='c']+[{'id':'c-serial','language':'c','workers':['direct'],'status':'planned-phase-2'}],
                    points=[dict(case['points'][0],variants=['py-reference','py-threads','c-serial'])])
        self.assertEqual(bp.excluded_rows(phase2,tb.smoke_plan(phase2,matrix='python')),
                         [{'variant':'c-serial','workers':'direct','route':None,'reason':bp.EXCLUDED_PYTHON}])
    def test_the_unit_evidence_carries_the_excluded_rows(self):
        import test_bench_panel_trials as tpt
        case={'case_id':'record-scan','parameters':{},'variants':[{'id':'py-reference','language':'python','workers':['direct'],'status':'implemented'},
                                                                  {'id':'c-serial','language':'c','workers':['direct'],'status':'implemented','routes':['stdio','shm']}]}
        plan={'rows':[{'variant':'py-reference','workers':'direct'}],'blocked_rows':[],'matrix':'python'}
        with tempfile.TemporaryDirectory() as t:
            d=Path(t)/('0'*32);d.mkdir();shutil.copy(tpt.FIX,d/'observations.jsonl')
            run={'run_id':'0'*32,'status':'VALID','reasons':[],'mode':'decision','source_identity':'a'*64,'plan':{'project_dir':tpt.PROJECT},'envelope':tpt.ENV}
            args=argparse.Namespace(ci_run_id=None,approval=[],sensitivity_confirmation=None)
            with mock.patch('bench_decide._current_identity',return_value='a'*64),mock.patch('bench_units.coverage_record_ok',return_value=True),\
                 mock.patch('bench_units._newest_coverage_path',return_value=None):
                ev=bu.unit_evidence_from_run(ROOT,d,run,plan,case,tpt.UPOL,args)
        self.assertEqual(ev['blocked_other'],[{'unit':'m3/single-record','label':'c-serial xdirect [stdio]','reason':'excluded by --matrix python'},
                                              {'unit':'m3/single-record','label':'c-serial xdirect [shm]','reason':'excluded by --matrix python'}])
    def test_the_rule_policy_evidence_carries_the_excluded_rows(self):
        case=tb.full_case()
        for matrix,want in (('python',9),('full',0)):
            with self.subTest(matrix=matrix),tempfile.TemporaryDirectory() as t:
                plan=tb.smoke_plan(case,matrix=matrix);rd=tb.write_run(t,case,plan);run=json.loads((rd/'run.json').read_text())
                ev=bd.evidence_from_run(Path(t),rd,run,plan,case)
                self.assertEqual(len([b for b in ev['blocked'] if b['reason']==bp.EXCLUDED_PYTHON]),want)
    def test_a_rule_policy_decision_without_the_candidate_is_inconclusive(self):
        c=copy.deepcopy(next(x for x in bm.load_fixtures(ROOT)['decision_cases']['cases'] if x['name']=='keep'))
        pol=bm.load_fixtures(ROOT)['decision_cases']['policy'];pol=dict(pol,modes=c.get('policy_modes',pol['modes']))
        stats=dict(bd.stats_of(bm.load_policy(ROOT)),resamples=200)
        ev=bd.synthetic_evidence(c)
        self.assertEqual((lambda r:(r['outcome'],r['rule']))(bd.decide(copy.deepcopy(ev),pol,c['opportunity'],stats)),('KEEP_PYTHON',3))   # control
        case=tb.full_case();ev['blocked']=[{k:e[k] for k in ('variant','workers','route','reason')} for e in bp.excluded_rows(case,tb.smoke_plan(case,matrix='python'))]
        r=bd.decide(ev,pol,c['opportunity'],stats)
        self.assertEqual((r['outcome'],r['rule']),('INCONCLUSIVE',2))
        self.assertIn('required evidence missing: c-serial xdirect [stdio]: excluded by --matrix python',r['reasons'])

# T6-R8 FW-DECIDE (FW-DECIDE-NAMODE-01): a plan blocked row counts as missing evidence only in the modes it belongs to. The
# plan blocks the inproc cold cell by design; a rule policy that decides warm only must not read it as missing evidence.
class RuleBlockedRowModeTests(unittest.TestCase):
    def setUp(self):
        self.c=copy.deepcopy(next(x for x in bm.load_fixtures(ROOT)['decision_cases']['cases'] if x['name']=='keep'))
        pol=bm.load_fixtures(ROOT)['decision_cases']['policy'];self.pol=dict(pol,modes=self.c.get('policy_modes',pol['modes']))
        self.stats=dict(bd.stats_of(bm.load_policy(ROOT)),resamples=200)
        self.row={'variant':'c-serial','workers':'direct','route':'inproc','reason':bp.INPROC_COLD}
        self.na=dict(self.row,not_applicable=True)          # evidence() marks the not-applicable cell by its reason code
    def decide(self,blocked,pol=None):
        ev=bd.synthetic_evidence(self.c);ev['blocked']=blocked
        return bd.decide(ev,pol or self.pol,self.c['opportunity'],self.stats)
    def test_a_cold_blocked_row_is_no_missing_evidence_of_a_warm_only_policy(self):
        self.assertEqual(self.pol['modes'],['warm'])
        r=self.decide([dict(self.na,mode='cold')])
        self.assertEqual((r['outcome'],r['rule']),('KEEP_PYTHON',3));self.assertEqual(r['reasons'],[])
    def test_a_blocked_row_of_a_decided_mode_or_without_a_mode_still_is_missing_evidence(self):
        other=dict(self.row,reason='launch failed')       # any reason but the not-applicable one
        for blocked,pol in ((dict(other,mode='warm'),self.pol),(dict(other),self.pol),(dict(other,mode='cold'),dict(self.pol,modes=['warm','cold']))):
            with self.subTest(mode=blocked.get('mode'),modes=pol['modes']):
                r=self.decide([blocked],pol)
                self.assertEqual((r['outcome'],r['rule']),('INCONCLUSIVE',2))
                self.assertIn('required evidence missing: c-serial xdirect [inproc]: '+blocked['reason'],r['reasons'])
    def test_a_not_applicable_cell_is_no_missing_evidence_in_any_mode(self):          # R94 (T6R8-A01): the policy decides warm and cold
        pol=dict(self.pol,modes=['warm','cold'])
        ev=bd.synthetic_evidence(self.c);ev['rows']+=[dict(r,mode='cold') for r in ev['rows']]
        ev['blocked']=[dict(self.na,mode='cold')]
        r=bd.decide(ev,pol,self.c['opportunity'],self.stats)
        self.assertEqual([x for x in r['reasons'] if 'inproc' in x],[])
        self.assertEqual((r['outcome'],r['rule']),(self.c['expect']['outcome'],self.c['expect']['rule']))     # T6R8-A08: the rule verdict of the keep case
        self.assertEqual((r['outcome'],r['rule'],r['reasons']),('KEEP_PYTHON',3,[]))                           # (KEEP_PYTHON, rule 3), not INCONCLUSIVE rule 2
        ev['blocked']=[dict(self.row,mode='cold',reason='launch failed')]            # the same row with another reason still counts
        r=bd.decide(ev,pol,self.c['opportunity'],self.stats)
        self.assertEqual((r['outcome'],r['rule']),('INCONCLUSIVE',2))
        self.assertIn('required evidence missing: c-serial xdirect [inproc]: launch failed',r['reasons'])
    def test_a_malformed_mode_never_hides_a_blocked_row(self):                       # T6R8-A06
        for mode in ('','Warm','COLD','hot'):
            with self.subTest(mode=mode):
                r=self.decide([dict(self.row,mode=mode,reason='launch failed')])
                self.assertEqual((r['outcome'],r['rule']),('INCONCLUSIVE',2))
                self.assertIn('required evidence missing: c-serial xdirect [inproc]: launch failed',r['reasons'])
    def test_a_malformed_mode_is_a_missing_row_of_the_unit_verdict_too(self):       # T6R8-A06: bench_units.blocked_of
        for mode in ('','Warm','hot'):
            with self.subTest(mode=mode):
                self.assertEqual(bu.blocked_of({'blocked_other':[dict(COLD,mode=mode,reason='launch failed')]},U,'warm'),[dict(COLD,mode=mode,reason='launch failed')])
        self.assertEqual(bu.blocked_of({'blocked_other':[COLD]},U,'warm'),[])
    def test_the_rule_policy_evidence_keeps_the_mode_of_a_blocked_row(self):
        case=tb.full_case()
        with tempfile.TemporaryDirectory() as t:
            plan=tb.smoke_plan(case);rd=tb.write_run(t,case,plan);run=json.loads((rd/'run.json').read_text())
            ev=bd.evidence_from_run(Path(t),rd,run,plan,case)
        self.assertEqual({(b['variant'],b['route'],b.get('mode')) for b in ev['blocked'] if b.get('mode')},{('c-serial','inproc','cold'),('c-threads','inproc','cold')})
        self.assertTrue(all(b.get('not_applicable') is True for b in ev['blocked'] if b.get('reason')==bp.INPROC_COLD))      # R94: marked by the reason code
        self.assertFalse(any(b.get('not_applicable') for b in ev['blocked'] if b.get('reason')!=bp.INPROC_COLD))
    def test_the_mark_needs_the_reason_on_the_inproc_cold_cell(self):              # T6R8-A10 (T6-R9): the cell as bench_phase3 matrix_cells defines it
        """evidence_from_run marks a blocked row not_applicable only for the reason code bench_plan.INPROC_COLD on route
        inproc in mode cold. The same reason on another route, in another mode or without a mode, and a not_applicable key
        that the plan supplies, never mark a row (such a row stays required evidence missing in its own mode)."""
        case=tb.full_case();cell={'variant':'c-serial','workers':'direct','route':'inproc','mode':'cold','reason':bp.INPROC_COLD}
        rows=[cell,dict(cell,route='stdio'),dict(cell,route='shm'),dict(cell,mode='warm'),{k:v for k,v in cell.items() if k!='mode'},
              dict(cell,route='stdio',not_applicable=True),dict(cell,reason='launch failed',not_applicable=True)]
        with tempfile.TemporaryDirectory() as t:
            plan=tb.smoke_plan(case);rd=tb.write_run(t,case,plan);run=json.loads((rd/'run.json').read_text())
            ev=bd.evidence_from_run(Path(t),rd,run,dict(plan,blocked_rows=rows),case)
        got=ev['blocked'][:len(rows)]          # the plan rows first, in plan order; excluded_rows follow and are never marked
        self.assertEqual([(b['route'],b.get('mode'),b['reason']) for b in got],[(r['route'],r.get('mode'),r['reason']) for r in rows])
        self.assertEqual([b.get('not_applicable') is True for b in got],[True,False,False,False,False,False,False])
        self.assertFalse(any(b.get('not_applicable') for b in ev['blocked'][len(rows):]))
        pol=dict(bm.load_fixtures(ROOT)['decision_cases']['policy'],modes=['warm','cold'])         # an unmarked row with the reason still counts
        dc=copy.deepcopy(next(x for x in bm.load_fixtures(ROOT)['decision_cases']['cases'] if x['name']=='keep'))
        sev=bd.synthetic_evidence(dc);sev['rows']+=[dict(r,mode='cold') for r in sev['rows']];sev['blocked']=got[1:2]
        r=bd.decide(sev,pol,dc['opportunity'],dict(bd.stats_of(bm.load_policy(ROOT)),resamples=200))
        self.assertEqual((r['outcome'],r['rule']),('INCONCLUSIVE',2))
        self.assertIn('required evidence missing: c-serial xdirect [stdio]: '+bp.INPROC_COLD,r['reasons'])

# T6-R8 FW-DECIDE (FW-WINDOWS-GUARDRAIL-01): plan-time guardrail rows are warnings, not decision evidence. The window
# evidence of a unit-threshold decision must not carry them, so a measured base row is never base-not-measured.
class WindowEvidenceGuardrailRowTests(unittest.TestCase):
    GUARD=[{'variant':v,'workers':'direct','reason':'blocked: doctor not run','guardrail':True} for v in ('py-optimized','py-reference','c-serial')]
    def finals(self,blocked):
        import test_bench_windows as tw
        case=tw.wcase();case['points']=[p for p in case['points'] if 'panel' not in p];pol=dict(tw.WPOL,units=['ma/full-dataset','mb/full-dataset'])
        version=dict(tw.decision_plan(case=case,policy=pol),blocked_rows=blocked)
        version['plan_id']=tw.bench.plan_digest(version)
        sub=tw.bw.window_run_plan(version,'1a',case,pol,tw.pdoc())
        with tempfile.TemporaryDirectory() as t:
            tw.write_window_run(t,'a'*32,sub,tw.unit_obs(sub),'1a',1,version=version)
            with mock.patch('bench_phase3_cli.recorded_problems',return_value=[]),mock.patch('bench_model.load_decision_policy',return_value=pol),\
                 mock.patch('bench_model.load_case',return_value=case),mock.patch('bench_model.load_policy',return_value=tw.pdoc()):
                return tw.bw.chain_for_decide(Path(t),'a'*32)['evidence']['plan']
    def verdict(self,plan):
        env,other=bu._blocked(plan,[U])
        return pair(mone(uev(base()+[cand(0.5*B,'inproc')],blocked_other=other)))
    def test_guardrail_rows_of_the_plan_version_keep_the_unit_verdicts(self):
        self.assertEqual(self.verdict(self.finals([])),('PREFER_C','both-conditions-met'))        # control
        plan=self.finals(self.GUARD+[dict(COLD)])
        self.assertEqual([b for b in plan['blocked_rows'] if b.get('guardrail')],[])
        self.assertEqual(self.verdict(plan),('PREFER_C','both-conditions-met'))
    def test_a_real_blocked_row_of_the_verdict_mode_still_makes_the_base_not_measured(self):
        real={'variant':'py-optimized','workers':'direct','reason':'launch failed'}
        plan=self.finals(self.GUARD+[real])
        self.assertIn(real,plan['blocked_rows'])
        self.assertEqual(self.verdict(plan),('KEEP_PYTHON','base-not-measured'))

if __name__=='__main__':unittest.main()
