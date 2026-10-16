"""Task 15 (G9.3 orders 1, 1a and 2-9, G9.5, G9.6, I15): the unit verdicts of a unit-threshold policy.

FR3: a unit-threshold policy is project data; these tests use the framework's synthetic engine test policy
(safety/performance-fixtures.json decision_cases.unit_policy: selectors m1..m5, threshold T, library report on m4). The
example project's model names and its model report move with the example (FR3 handoff list); the assertions are kept with
the generic names (m3 for a model without a special report, m4 for the library-report selector, m5 for a second selector)."""
import copy, json, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import bench_units as bu, bench_model as bm, bench_stats as bs
sys.path.insert(0,str(ROOT/'tests/unit'));import test_bench_qualification as tq      # qualified project checks come from the truth table
POL=bm.engine_unit_policy(ROOT);T=POL['threshold_ns_per_request'];ST={'resamples':1000,'seed':20261007}
PC0=tq.qualified('Q06')                  # exit 0 at I: manifest
SAFE_LABEL='separate process; copied, bounded, validated frames over pipes (safest)'
CELLS=('g1-pos-near','g0-mid-near','g1-neg-near','g1-pos-far','g0-mid-far','g1-neg-far')     # FR5: the fixture protocol's cell names
def const(v,n=12):return {b:float(v) for b in range(n)}
def row(variant,lang,v,route=None,workers='direct',unit='m3/full-dataset',mode='warm',eligible=True,planned=True,records=None):
    return {'unit':unit,'mode':mode,'variant':variant,'workers':workers,'route':route,'route_label':SAFE_LABEL if route else None,'language':lang,
            'eligible':eligible,'planned':planned,'wall':const(v),'cpu':const(v),'peak':None,'records':records}
def uev(rows,**over):
    d={'status':'VALID','reasons':[],'rows':rows,'blocked_other':[],'envelope_not_planned':[],'looks':{},'extension_not_run':[],'window_mismatch':[],
       'reference_evals':{'m3':10**6},'panel_evals':{'m3':{c:100 for c in CELLS}},
       'project_check':PC0,'current_identity':'a'*64,'opportunity_state':'APPROVED','coverage_ok':True,'reference_admit_excluded':None,'library_overhead_ns_per_row':None}
    d.update(over);return d
def one(unit,ev):return bu.decide_unit(unit,ev,POL,ST)
PY=lambda v:[row('py-optimized','python',v),row('py-library','python-library',v*1.01)]
GUARD_ROWS=[row('py-reference','python',T*10,unit='m3/single-record',records={c:const(1e9) for c in CELLS})]

class OrderTests(unittest.TestCase):
    def test_order_1_invalid_run(self):self.assertEqual(one('m3/full-dataset',uev(PY(T*2),status='INVALID_EXPERIMENT'))['reason'],'run-invalid')
    def test_order_1_ineligible_row(self):
        self.assertEqual(one('m3/full-dataset',uev(PY(T*2)+[row('c-serial','c',T,route='stdio',eligible=False)]))['reason'],'ineligible-row')
    def test_threshold_is_strict_below_the_threshold(self):
        self.assertEqual(one('m3/full-dataset',uev(PY(T-1)))['verdict'],'KEEP_PYTHON')
        self.assertNotEqual(one('m3/full-dataset',uev(PY(T)))['reason'],'python-under-threshold')
    def test_order_3_near_threshold(self):
        noisy=row('py-optimized','python',T);noisy['wall']={b:T*(0.9 if b%2 else 1.1) for b in range(12)}
        r=one('m3/full-dataset',uev([noisy]));self.assertEqual((r['verdict'],r['reason']),('INCONCLUSIVE','python-near-threshold'));self.assertTrue(r['extension']['trigger'])
    def test_order_4_missing_python_row(self):
        r=one('m3/full-dataset',uev(PY(T*2)+GUARD_ROWS,blocked_other=[{'unit':'m3/full-dataset','label':'py-processes x4','reason':'multicore BLOCKED'}]))
        self.assertEqual(r['reason'],'python-evidence-missing')
    def test_order_5_guard(self):
        self.assertEqual(one('m3/full-dataset',uev(PY(T*2)))['reason'],'py-reference-not-measured')   # no py-reference panel row
    def test_order_6_prefer_c(self):
        r=one('m3/full-dataset',uev(PY(T*2)+GUARD_ROWS+[row('c-serial','c',T*0.5,route='stdio')]))
        self.assertEqual((r['verdict'],r['reason']),('PREFER_C','c-reliably-faster'));self.assertEqual(r['default_action'],'PREFER_C')
    def test_order_7_c_not_eligible_is_inconclusive_with_conditions(self):
        for ev,cond in ((uev(PY(T*2)+GUARD_ROWS+[row('c-serial','c',T*0.5,route='stdio')],project_check=tq.qualified('Q16')),'framework-unqualified'),
                        (uev(PY(T*2)+GUARD_ROWS+[row('c-serial','c',T*0.5,route='stdio')],opportunity_state='PENDING'),'opportunity-not-approved')):
            r=one('m3/full-dataset',ev);self.assertEqual((r['verdict'],r['reason'],r['default_action']),('INCONCLUSIVE','c-not-eligible','KEEP_PYTHON'))
            self.assertIn(cond,r['failed_conditions'])
    def test_project_check_shape(self):
        self.assertEqual(set(PC0),{'exit','report_path','report_sha256','identity','local'})

class OrderTestsContinued(unittest.TestCase):          # orders 7-9
    def test_order_7_summary_line(self):
        r=one('m3/full-dataset',uev(PY(T*2)+GUARD_ROWS+[row('c-serial','c',T*0.5,route='stdio')],opportunity_state='PENDING'))
        self.assertEqual(r['summary_line'],'C is reliably faster but not eligible: opportunity-not-approved')
    def test_order_8_missing_c_row(self):
        r=one('m3/full-dataset',uev(PY(T*2)+GUARD_ROWS+[row('c-serial','c',T*2,route='stdio')],
              blocked_other=[{'unit':'m3/full-dataset','label':'c-threads x4 [shm]','reason':'route refused'}]))
        self.assertEqual(r['reason'],'c-evidence-missing')
    def test_order_9_c_not_reliably_faster(self):
        r=one('m3/full-dataset',uev(PY(T*2)+GUARD_ROWS+[row('c-serial','c',T*2,route='stdio')]))
        self.assertEqual((r['verdict'],r['reason']),('KEEP_PYTHON','c-not-reliably-faster'))

class RuleDetailTests(unittest.TestCase):
    def test_bonferroni_levels_per_set_size(self):
        rows=[row(f'py-threads','python',T-1,workers=w) for w in (1,2,4)]
        for r in rows:r['wall']={b:(T-1)*(1+0.001*b) for b in range(12)}
        h,_=bu.h_pi([(f'r{i}',r['wall']) for i,r in enumerate(rows)],1,ST)
        self.assertEqual(h,min(bs.order_stat_bounds(r['wall'],0.025/3)[1] for r in rows))
    def test_empty_sets(self):self.assertEqual(one('m3/full-dataset',uev([]))['reason'],'python-evidence-missing')
    def test_missing_python_row_blocks_prefer_c(self):
        r=one('m3/full-dataset',uev(PY(T*2)+GUARD_ROWS+[row('c-serial','c',T*0.5,route='stdio')],
              blocked_other=[{'unit':'m3/full-dataset','label':'py-processes x4','reason':'launch failed'}]))
        self.assertEqual(r['reason'],'python-evidence-missing')
    def test_missing_c_row_blocks_keep_c_not_faster(self):
        r=one('m3/full-dataset',uev(PY(T*2)+GUARD_ROWS+[row('c-serial','c',T*2,route='stdio')],
              blocked_other=[{'unit':'m3/full-dataset','label':'c-serial xdirect [shm]','reason':'launch failed'}]))
        self.assertEqual(r['reason'],'c-evidence-missing')
    def test_envelope_blocked_rows_not_planned(self):
        r=one('m3/full-dataset',uev(PY(T*2)+GUARD_ROWS+[row('c-serial','c',T*2,route='stdio')],envelope_not_planned=[{'unit':'m3/full-dataset','label':'c-threads x4 [stdio]'}]))
        self.assertEqual(r['reason'],'c-not-reliably-faster');self.assertIn('rows not run on this envelope',r['envelope_note'])
    def test_extension_not_run(self):
        noisy=row('py-optimized','python',T);noisy['wall']={b:T*(0.9 if b%2 else 1.1) for b in range(12)}
        r=one('m3/full-dataset',uev([noisy],extension_not_run=['m3/full-dataset']));self.assertIn('extension-not-run',r['extension']['note'])
    def test_extension_trigger_and_levels(self):
        noisy=row('py-optimized','python',T);noisy['wall']={b:T*(0.9 if b%2 else 1.1) for b in range(24)}
        r=one('m3/full-dataset',uev([noisy],looks={'m3/full-dataset':2}));self.assertEqual((r['look'],r['alpha'],r['reason']),(2,0.0125,'python-at-threshold'))
    def test_window_mismatch_invalidates_extension(self):
        r=one('m3/full-dataset',uev(PY(T*2),looks={'m3/full-dataset':2},window_mismatch=['m3/full-dataset']));self.assertEqual(r['verdict'],'INVALID_EXPERIMENT')
    def test_safe_route_verdict_separate(self):
        r=one('m3/full-dataset',uev(PY(T*2)+GUARD_ROWS+[row('c-serial','c',T*0.5,route='inproc'),row('c-serial','c',T*2,route='stdio')]))
        self.assertEqual((r['verdict'],r['verdict_safe_route']),('PREFER_C','KEEP_PYTHON'));self.assertIn('PREFER_C only on the in-process route (less safe)',r['summary_line'])
    def test_missing_coverage_record_blocks_every_verdict(self):
        r=one('m3/full-dataset',uev(PY(T-1),coverage_ok=False));self.assertEqual((r['verdict'],r['reason'],r['detail']),('INVALID_EXPERIMENT','run-invalid','coverage-unqualified'))
    def test_guard_compares_with_the_upper_bound_of_p(self):
        ev=uev(PY(T*2)+GUARD_ROWS);ev['reference_evals']['m3']=1
        self.assertEqual(one('m3/full-dataset',ev)['reason'],'py-reference-not-measured')
    def test_library_selector_reports_exclusions_and_the_library_label(self):
        # G2.3, FR3: the selectors and the label come from the policy's project protocol (library_report); was a model-specific unit test
        rows=[dict(x,unit='m4/full-dataset') for x in PY(T-1)]
        r=one('m4/full-dataset',uev(rows,reference_admit_excluded={'row':3,'brent':1,'bump':0},library_overhead_ns_per_row=1234.0))
        self.assertEqual(r['reference_admit_excluded'],{'row':3,'brent':1,'bump':0});self.assertEqual(r['library_label'],POL['library_report']['label'])
        self.assertEqual(r['library_overhead_ns_per_row'],1234.0)
        r=one('m3/full-dataset',uev(PY(T-1),reference_admit_excluded={'row':3,'brent':1,'bump':0},library_overhead_ns_per_row=1234.0))
        self.assertEqual((r['library_label'],r['reference_admit_excluded'],r['library_overhead_ns_per_row']),(None,None,None))
        r=bu.decide_unit('m4/full-dataset',uev(rows),dict(POL,library_report=None),ST);self.assertIsNone(r['library_label'])
    def test_py_reference_guard_uses_eval_counts(self):
        ev=uev(PY(T*2)+GUARD_ROWS);self.assertTrue(bu.py_reference_guard('m3/full-dataset',ev,T*2))
        ev['panel_evals']['m3']['g0-mid-far']=None;self.assertFalse(bu.py_reference_guard('m3/full-dataset',ev,T*2))
    def test_panel_uses_worst_record(self):
        c={'a':const(1.0),'b':const(3.0),'c':const(2.0)};self.assertEqual(bu.worst_record(c),const(3.0))
    def test_cold_rows_never_decide(self):
        rows=PY(T*2)+GUARD_ROWS+[row('c-serial','c',T*0.5,route='stdio',mode='cold')]
        self.assertEqual(one('m3/full-dataset',uev(rows))['reason'],'c-evidence-missing')
    def test_order_1a_bound_unattainable(self):                       # I15.4: n = 3 synthetic blocks
        rows=[dict(row('py-optimized','python',T*2),wall={b:T*2 for b in range(3)})]
        r=bu.decide_unit('m3/full-dataset',uev(rows,looks={}),dict(POL,primary_blocks=3),ST)
        self.assertEqual((r['verdict'],r['reason'],r['default_action']),('INCONCLUSIVE','bound-unattainable','KEEP_PYTHON'))
    def test_guard_uses_the_order_statistic_bound(self):
        ev=uev(PY(T*2)+GUARD_ROWS);r=one('m3/full-dataset',ev)
        self.assertEqual(r['ranks']['rows'][0]['k_upper'],bs.order_stat_rank(12,0.025/2))
    def test_panel_status_detail(self):
        bad=dict(row('c-serial','c',T*0.5,route='stdio',unit='m3/single-record'),eligible=False,detail='panel-status')
        r=one('m3/single-record',uev([dict(x,unit='m3/single-record') for x in PY(T*2)]+[bad]))
        self.assertEqual((r['verdict'],r['reason'],r['detail']),('INVALID_EXPERIMENT','ineligible-row','panel-status'))
    def test_sensitivity_fields(self):
        cov={'power':{'0.02':{'all_rows_fast':{'0.9':1.0},'one_row_fast':{'0.9':{'fast_row_rate':0.9,'some_row_rate':0.9}}},
                      '0.1':{'all_rows_fast':{'0.9':0.32},'one_row_fast':{'0.9':{'fast_row_rate':0.05,'some_row_rate':0.06}}}}}
        r=one('m3/full-dataset',uev(PY(T*2)+GUARD_ROWS+[row('c-serial','c',T*2,route='stdio')],coverage_power=cov))
        s=r['sensitivity'];self.assertEqual((s['k_gamma'],s['level']),(1,0.02))
        self.assertIn('can stay unrecognized',s['sentence']);self.assertIn('coverage configuration has k_Gamma = 12',s['caveat'])
    def test_trend_is_reported(self):
        r=one('m3/full-dataset',uev(PY(T*2)+GUARD_ROWS+[row('c-serial','c',T*2,route='stdio')]))
        self.assertEqual(set(r['trend']),{'tau','p_two_sided','n','label'});self.assertIn('never a verdict',r['trend']['label'])
    def test_project_report_of_a_selector(self):
        # FR3 (was the I8.3 model report of one model): the run's project-report.json entry of the unit's selector
        rows=[dict(x,unit='m5/full-dataset') for x in PY(T-1)]
        r=one('m5/full-dataset',uev(rows,project_report={'m5':{'equation_rows':{'a':10,'b':90}}}))
        self.assertEqual(r['project_report'],{'label':'documented metric, never a verdict','tables':{'equation_rows':{'a':10,'b':90}}})
        self.assertIsNone(one('m3/full-dataset',uev(PY(T-1),project_report={'m5':{'x':1}}))['project_report'])
        self.assertIsNone(one('m3/full-dataset',uev(PY(T-1)))['project_report'])
        self.assertIsNone(bu._report_tables({'m5':{str(k):k for k in range(17)}}));self.assertIsNone(bu._report_tables({'Bad Key':{}}))
        self.assertEqual(bu._report_tables({'m5':{'a':1}}),{'m5':{'a':1}})
    def test_ten_records(self):
        self.assertEqual([r['unit'] for r in bu.decide_units(uev(PY(T*2)),POL,ST)],POL['units']);self.assertEqual(len(POL['units']),10)

# ---- Step 4: the synthetic unit_cases of safety/performance-fixtures.json (G12 B14, I12 B14, I15.4, H21.4) ----
UNIT_CASES=bm.load_fixtures(ROOT)['decision_cases']['unit_cases']
REASONS=('run-invalid','ineligible-row','bound-unattainable','python-under-threshold','python-near-threshold','python-at-threshold',
         'python-evidence-missing','py-reference-not-measured','c-reliably-faster','c-not-eligible','c-evidence-missing','c-not-reliably-faster')
ORDERS_1_TO_5=('run-invalid','ineligible-row','python-under-threshold','python-near-threshold','python-at-threshold','python-evidence-missing','py-reference-not-measured')

def case_policy(c):return dict(POL,primary_blocks=c['primary_blocks']) if 'primary_blocks' in c else POL
def case_uev(c):
    """The unit evidence of one fixture case; its project_check comes from the named truth-table row (never repeated here)."""
    rows=[]
    for s in c['rows']:
        wall={b:float(v) for b,v in enumerate(s['wall'])} if isinstance(s['wall'],list) else const(s['wall'],s.get('blocks',12))
        r={'unit':s.get('unit',c['unit']),'mode':s.get('mode','warm'),'variant':s['variant'],'workers':s['workers'],'route':s['route'],
           'route_label':SAFE_LABEL if s['route'] else None,'language':s['language'],'eligible':s.get('eligible',True),'planned':s.get('planned',True),
           'wall':wall,'cpu':dict(wall),'peak':None,'records':{x:const(s['record_wall']) for x in CELLS} if 'record_wall' in s else None}
        if s.get('detail'):r['detail']=s['detail']
        rows.append(r)
    return uev(rows,project_check=tq.qualified(c.get('qualification_row','Q06')),**copy.deepcopy(c.get('evidence',{})))

class UnitCaseTests(unittest.TestCase):
    def test_every_unit_case_gives_its_expected_verdicts(self):
        for c in UNIT_CASES:
            with self.subTest(case=c['name']):
                r=bu.decide_unit(c['unit'],case_uev(c),case_policy(c),ST);e=c['expect']
                self.assertEqual((r['verdict'],r['reason'],r['verdict_safe_route']),(e['verdict'],e['reason'],e['verdict_safe_route']))
                self.assertEqual(r['failed_conditions'],e.get('failed_conditions',[]))
    def test_every_order_and_qualification_row_has_a_case(self):
        self.assertEqual({c['expect']['reason'] for c in UNIT_CASES},set(REASONS))
        self.assertLessEqual({'Q06','Q20','Q16','Q19','Q10','Q07','Q08','Q01'},{c.get('qualification_row') for c in UNIT_CASES})
        self.assertTrue(any(c['unit'].startswith('m5/') for c in UNIT_CASES))           # a second selector (was a model-specific unit case)
    def test_boundary_cases_of_the_t15_approval_are_present(self):    # T15-APP-01 (exactly T), T15-APP-02 (k_Gamma, k_safe, look-2 level)
        names={c['name'] for c in UNIT_CASES}
        self.assertLessEqual({'threshold-rule-python-exactly-at-threshold-prefer-c','threshold-rule-python-exactly-at-threshold-c-ratio-one',
                              'threshold-rule-lower-bound-one-past-below-threshold','c-claim-rank-boundary-one-row','c-claim-bonferroni-two-rows',
                              'c-claim-safe-route-rank','c-claim-look-2-level'},names)

def case_named(name):return next(c for c in UNIT_CASES if c['name']==name)
def decide_case(name):c=case_named(name);return bu.decide_unit(c['unit'],case_uev(c),case_policy(c),ST)

class OwnerRuleBoundaryTests(unittest.TestCase):                  # T15-APP-01: "T or more prefers C" at exactly T
    def test_python_exactly_at_threshold_is_on_the_c_side(self):
        r=decide_case('threshold-rule-python-exactly-at-threshold-prefer-c')
        self.assertEqual((r['L_pi']['value_ms'],r['H_pi']['value_ms']),(T/1e6,T/1e6))      # L = U = T
        self.assertEqual((r['verdict'],r['reason'],r['verdict_safe_route'],r['default_action']),('PREFER_C','c-reliably-faster','PREFER_C','PREFER_C'))
    def test_python_exactly_at_threshold_with_c_ratio_one_keeps_python(self):
        r=decide_case('threshold-rule-python-exactly-at-threshold-c-ratio-one')
        self.assertEqual((r['verdict'],r['reason'],r['verdict_safe_route']),('KEEP_PYTHON','c-not-reliably-faster','KEEP_PYTHON'))
    def test_lower_bound_one_past_below_threshold_is_near_threshold(self):
        r=decide_case('threshold-rule-lower-bound-one-past-below-threshold')
        self.assertEqual(r['L_pi']['value_ms'],(T-1)/1e6)                                   # x_(3) = T - 1
        self.assertEqual((r['verdict'],r['reason'],r['verdict_safe_route']),('INCONCLUSIVE','python-near-threshold','INCONCLUSIVE'))

class CClaimLevelTests(unittest.TestCase):                        # T15-APP-02: non-constant per-block ratios at the rank boundaries
    def test_one_row_qualifies_at_rank_ten(self):
        r=decide_case('c-claim-rank-boundary-one-row')
        self.assertEqual((r['k_gamma'],r['ranks']['C']),(1,{'n':12,'k':10}))
        self.assertEqual((r['verdict'],r['reason'],r['verdict_safe_route']),('PREFER_C','c-reliably-faster','PREFER_C'))
    def test_a_second_row_moves_the_rank_to_eleven(self):
        r=decide_case('c-claim-bonferroni-two-rows')
        self.assertEqual((r['k_gamma'],r['k_safe'],r['ranks']['C']['k']),(2,2,11))
        self.assertEqual((r['verdict'],r['reason'],r['verdict_safe_route']),('KEEP_PYTHON','c-not-reliably-faster','KEEP_PYTHON'))
    def test_safe_route_uses_k_safe(self):
        r=decide_case('c-claim-safe-route-rank')
        self.assertEqual((r['k_gamma'],r['k_safe'],r['ranks']['C']['k'],r['ranks']['C_safe']['k']),(2,1,11,10))
        self.assertEqual((r['verdict'],r['reason'],r['verdict_safe_route'],r['reason_safe_route']),('KEEP_PYTHON','c-not-reliably-faster','PREFER_C','c-reliably-faster'))
    def test_look_2_uses_the_look_2_level(self):
        r=decide_case('c-claim-look-2-level')
        self.assertEqual((r['look'],r['k_gamma'],r['ranks']['C']),(2,2,{'n':24,'k':19}))
        self.assertEqual((r['verdict'],r['reason'],r['verdict_safe_route']),('KEEP_PYTHON','c-not-reliably-faster','KEEP_PYTHON'))

class SafeRouteSummaryTests(unittest.TestCase):                   # T15-APP-04
    def test_summary_names_a_differing_safe_route_verdict(self):
        r=decide_case('c-claim-safe-route-rank')
        self.assertTrue(r['summary_line'].startswith('C bound = x_(11) of 12 per-block ratios, k = 11; '),r['summary_line'])
        self.assertTrue(r['summary_line'].endswith('; safe routes: PREFER_C (c-reliably-faster)'),r['summary_line'])
        self.assertLessEqual(len(r['summary_line']),600)
    def test_summary_without_a_difference_has_no_safe_route_part(self):
        for name in ('c-claim-bonferroni-two-rows','c-claim-rank-boundary-one-row','order-3-python-near-threshold'):
            with self.subTest(name=name):self.assertNotIn('safe routes',decide_case(name)['summary_line'])
    def test_the_less_safe_summary_names_the_safe_routes_once(self):
        r=decide_case('order-6-inproc-only-prefer-c')
        self.assertEqual(r['summary_line'],bu.SUMMARY_LESS_SAFE.format(v='KEEP_PYTHON',r='c-not-reliably-faster'))

def units_validator():
    import jsonschema
    s=json.loads((ROOT/'schemas/bench-decision.json').read_text())
    return jsonschema.Draft202012Validator({'$schema':s['$schema'],'$defs':s['$defs'],'type':'object','additionalProperties':False,
                                            'required':['units'],'properties':{'units':s['properties']['units']}})

def record_of(recs):
    """bench_units.unit_decision_record of `recs` on a minimal run (FR3: the code checks the units and their order)."""
    from unittest import mock
    run={'run_id':'0'*32,'case':'fixture-case','mode':'decision','source_identity':'a'*64,'image_id':'sha256:'+'1'*64,'dataset':{'kind':'synthetic'}}
    with mock.patch('bench_decide._current_identity',return_value='a'*64):
        return bu.unit_decision_record(ROOT,run,{},{'case_id':'fixture-case','variants':[]},POL,recs,uev([],project_check=PC0),{})

class UnitRecordSchemaTests(unittest.TestCase):
    def test_every_case_gives_ten_valid_records(self):
        v=units_validator()
        for c in UNIT_CASES:
            with self.subTest(case=c['name']):
                recs=bu.decide_units(case_uev(c),case_policy(c),ST);v.validate({'units':recs})
                self.assertEqual([r['unit'] for r in recs],POL['units'])
    def test_reports_with_every_optional_block_validate(self):
        cov={'power':{'0.02':{'all_rows_fast':{'0.9':1.0},'one_row_fast':{'0.9':{'fast_row_rate':0.9,'some_row_rate':0.9}}}}}
        rows=PY(T*2)+GUARD_ROWS+[row('c-serial','c',T*0.5,route='inproc'),row('c-serial','c',T*2,route='stdio'),row('c-serial','c',T*0.5,route='stdio',mode='cold')]
        rows+=[dict(x,unit='m5/full-dataset') for x in PY(T-1)]+[dict(x,unit='m4/single-record') for x in PY(T*2)]
        ev=uev(rows,coverage_power=cov,project_report={'m5':{'equation_rows':{'a':1,'b':2}}},reference_admit_excluded={'row':1,'brent':0,'bump':0},
               library_overhead_ns_per_row=10.0,envelope_not_planned=[{'unit':'m3/full-dataset','label':'c-threads x4 [stdio]'}],
               panel_rows=[{'cell':c,'category':'g1','values':{'r':1.1,'p':0.09,'s':0.1,'s_scaled':36.5},'level':0} for c in CELLS])
        recs=bu.decide_units(ev,POL,ST);units_validator().validate({'units':recs})
        m3=recs[POL['units'].index('m3/full-dataset')]
        self.assertEqual((m3['verdict'],m3['C']['route'],m3['C']['c_under_threshold']),('PREFER_C','inproc',True))
        self.assertIsNotNone(m3['less_safe_label']);self.assertEqual(m3['cold']['C'],None)        # no cold row of the inproc identity
        pc=recs[POL['units'].index('m4/single-record')]['panel_records'];self.assertEqual(len(pc),6)
        self.assertEqual(pc[0],{'cell':CELLS[0],'category':'g1','values':{'r':1.1,'p':0.09,'s':0.1,'s_scaled':36.5},'level':0})   # FR5: the rule's report values
        self.assertIsNotNone(recs[POL['units'].index('m5/full-dataset')]['project_report'])
    def test_the_schema_and_the_record_refuse_a_changed_record(self):
        v=units_validator();recs=bu.decide_units(uev(PY(T*2)),POL,ST)
        self.assertTrue(v.is_valid({'units':recs}))
        # FR3: the unit names are project data, so the count and the order are checked by unit_decision_record (was prefixItems)
        self.assertEqual([u['unit'] for u in record_of(recs)['units']],POL['units'])
        for changed in (recs[:9],list(reversed(recs))):
            with self.subTest(n=len(changed)),self.assertRaises(ValueError):record_of(changed)
        self.assertFalse(v.is_valid({'units':recs+[recs[0]]}));self.assertFalse(v.is_valid({'units':[]}))     # at most ten, at least one
        last=copy.deepcopy(recs);last[9]['score']=1;self.assertFalse(v.is_valid({'units':last}))      # every element is a closed record
        for key,value in (('score',1),('verdict','C_CANDIDATE_FOR_REVIEW'),('adoption_authorized',True),('default_action','PREFER_C'),('reason','faster'),
                          ('unit','Bad Unit'),('library_label',''),('project_report',{'label':'x','tables':{}})):
            with self.subTest(key=key):
                bad=copy.deepcopy(recs);bad[0][key]=value;self.assertFalse(v.is_valid({'units':bad}))
        bad=copy.deepcopy(recs);bad[0]['reference_admit_excluded']={'row':1,'brent':0,'bump':0};self.assertFalse(v.is_valid({'units':bad}))   # no library label
    def test_prefer_c_needs_a_qualified_framework_label(self):        # T15-APP-06 (a): a defective producer cannot write PREFER_C unqualified
        v=units_validator();i=POL['units'].index('m3/full-dataset')
        for name,field in (('order-6-prefer-c-manifest','verdict'),('order-6-prefer-c-exit-3-complete-local-evidence','verdict'),('c-claim-safe-route-rank','verdict_safe_route')):
            c=case_named(name);recs=bu.decide_units(case_uev(c),case_policy(c),ST)
            with self.subTest(case=name):
                self.assertEqual(recs[i][field],'PREFER_C');self.assertTrue(v.is_valid({'units':recs}))
                bad=copy.deepcopy(recs);bad[i]['framework_label']='framework unqualified';self.assertFalse(v.is_valid({'units':bad}))
    def test_orders_1_to_5_carry_the_shared_pair_on_the_safe_route(self):   # T15-APP-06 (b)
        v=units_validator();i=POL['units'].index('m3/full-dataset');seen=set()
        for c in UNIT_CASES:
            if c['unit']!='m3/full-dataset' or c['expect']['reason'] not in ORDERS_1_TO_5:continue
            recs=bu.decide_units(case_uev(c),case_policy(c),ST);seen.add(c['expect']['reason'])
            with self.subTest(case=c['name']):
                self.assertEqual((recs[i]['verdict_safe_route'],recs[i]['reason_safe_route']),(recs[i]['verdict'],recs[i]['reason']));self.assertTrue(v.is_valid({'units':recs}))
                for pair in (('KEEP_PYTHON','c-not-reliably-faster'),('PREFER_C','c-reliably-faster'),('INCONCLUSIVE','c-evidence-missing')):
                    bad=copy.deepcopy(recs);bad[i]['verdict_safe_route'],bad[i]['reason_safe_route']=pair;self.assertFalse(v.is_valid({'units':bad}),pair)
        self.assertEqual(seen,set(ORDERS_1_TO_5))

class SensitivityConfirmationTests(unittest.TestCase):            # base Task 18 with addendum E-T18-12 (Amendment H16.1)
    def test_decide_refuses_unconfirmed_sensitivity(self):
        import bench_phase3_cli as cli, argparse, tempfile
        from unittest import mock
        ns=lambda p:argparse.Namespace(run_id='0'*32,policy='all',format='json',ci_run_id=None,approval=[],sensitivity_confirmation=p,cgroup_unrecorded=False)
        name='fixture-request-threshold'           # FR3: the unit-threshold policy of the fixture project's protocol
        loaded=({'run_id':'0'*32,'status':'VALID','mode':'decision','case':'fixture-case','dataset':{'kind':'synthetic'},'plan':{'project_dir':'tests/fixtures/bench-project'}},
                {'policy':name,'case':'fixture-case'},{'case_id':'fixture-case','variants':[]},{})     # FR3-08: a run of the policy's case
        with mock.patch('bench_phase3_cli._load_run',return_value=loaded),mock.patch('bench_phase3_cli._write_records') as w:
            self.assertEqual(cli.decide_owner(ROOT,ns(None),name),1);w.assert_not_called()
            with tempfile.TemporaryDirectory() as t:
                cov=Path(t)/'coverage.json';cov.write_text('{}')
                conf=Path(t)/'c.json';conf.write_text(json.dumps({'schema_version':1,'ledger_id':'P3-OWNER-SENS-01','coverage_sha256':'f'*64,'coverage_path':str(cov),'owner_words':'20% is fine','date':'2026-10-10'}))
                self.assertEqual(cli.decide_owner(ROOT,ns(str(conf)),name),1);w.assert_not_called()          # names another coverage record
                import hashlib
                conf.write_text(json.dumps({'schema_version':1,'ledger_id':'P3-OWNER-SENS-01','coverage_sha256':hashlib.sha256(cov.read_bytes()).hexdigest(),'coverage_path':str(cov),'owner_words':'20% is fine','date':'2026-10-10'}))
                self.assertEqual(cli.decide_owner(ROOT,ns(str(conf)),name),1);w.assert_not_called()          # the record has no threshold_ns of the policy
                with mock.patch('bench_units.coverage_record_ok',return_value=True),mock.patch('bench_units.unit_evidence_from_run',return_value={}),\
                     mock.patch('bench_units.decide_units',return_value=[]),mock.patch('bench_units.unit_decision_record',return_value={'units':[],'outcome':None,'adoption_outcome':None}):
                    self.assertEqual(cli.decide_owner(ROOT,ns(str(conf)),name),0);w.assert_called_once()
    def test_the_coverage_threshold_must_equal_the_policy_threshold(self):
        """FR3: the coverage job checked the owner policy T on the framework policy before the move; now decide checks the
        decided policy's T against the record's simulated threshold_ns (bench_units.coverage_record_ok)."""
        from unittest import mock
        rec={'threshold_ns':T}
        with mock.patch('bench_units._read_coverage',return_value=rec),mock.patch('bench_units._resolve',return_value=Path('/x')),\
             mock.patch('bench_units.coverage_problems',return_value=[]):
            self.assertTrue(bu.coverage_record_ok(ROOT,'x',POL));self.assertTrue(bu.coverage_record_ok(ROOT,'x'))
            self.assertFalse(bu.coverage_record_ok(ROOT,'x',dict(POL,threshold_ns_per_request=T-1)))

if __name__=='__main__':unittest.main()
