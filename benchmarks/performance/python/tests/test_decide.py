"""Task 14 (spec 10, Amendment H2-H5, B14): the fixture-driven decision engine tests. Ruling T14-C1: they moved here from
tests/unit/test_bench_decide.py because each `decide` call runs up to 36 paired bootstraps of the policy's 10,000 resamples;
the module needs about 600 of them, which exceeds the check-fast unit gate's 30 s timeout and the plan's 0.5 s per-file
budget for tests/unit. Assertions are unchanged; the resample count stays the policy value.

The host tools are loaded by path from /src/tools (the container has no host tool imports). They are registered in
sys.modules only while this module runs (setUpModule/tearDownModule), so later container tests that load a modified
copy of a tool (test_coverage) never receive these modules."""
import copy, importlib.util, sys, unittest
from pathlib import Path
ROOT=Path('/src')
TOOLS=('evidence','schema_check','bench_stats','bench_model','bench_decide')   # dependency order of bench_decide
_SAVED={}
bd=bm=POL=STATS=FIX=TEST_POLICY=None

def setUpModule():
    global bd,bm,POL,STATS,FIX,TEST_POLICY
    for name in TOOLS:_SAVED[name]=sys.modules.get(name)
    for name in TOOLS:
        spec=importlib.util.spec_from_file_location(name,ROOT/'tools'/f'{name}.py');mod=importlib.util.module_from_spec(spec)
        sys.modules[name]=mod;spec.loader.exec_module(mod)
    bd=sys.modules['bench_decide'];bm=sys.modules['bench_model']
    POL=bm.load_policy(ROOT);STATS=bd.stats_of(POL);FIX=bm.load_fixtures(ROOT)['decision_cases']
    TEST_POLICY=FIX['policy']

def tearDownModule():
    for name in TOOLS:
        if _SAVED.get(name) is None:sys.modules.pop(name,None)
        else:sys.modules[name]=_SAVED[name]

def case(name):return copy.deepcopy(next(c for c in FIX['cases'] if c['name']==name))
def run(name,policy=None):
    c=case(name);return bd.decide(bd.synthetic_evidence(c),policy or dict(TEST_POLICY,modes=c.get('policy_modes',TEST_POLICY['modes'])),c['opportunity'],STATS)

class LogicTests(unittest.TestCase):
    def test_benefit_three_values(self):
        base={b:100.0+b%3 for b in range(12)};fast={b:40.0+b%3 for b in range(12)};same={b:100.0+(b+1)%3 for b in range(12)}
        self.assertIs(bd.benefit(base,fast,relative=0.2,min_abs=0,stats=STATS)[0],True)
        self.assertIs(bd.benefit(base,same,relative=0.2,min_abs=0,stats=STATS)[0],False)
        self.assertIs(bd.benefit(base,fast,relative=0.2,min_abs=1000,stats=STATS)[0],False)      # saving too small
        self.assertIs(bd.benefit(base,{b:v for b,v in fast.items() if b<5},relative=0.2,min_abs=0,stats=STATS)[0],None)   # unpaired
    def test_limit(self):
        base={b:100.0 for b in range(12)}
        self.assertIs(bd.limit_ok(base,{b:103.0 for b in range(12)},0.05,STATS)[0],True)
        self.assertIs(bd.limit_ok(base,{b:110.0 for b in range(12)},0.05,STATS)[0],False)
        self.assertIs(bd.limit_ok(base,{b:110.0 for b in range(12)},None,STATS)[0],True)

class RuleTests(unittest.TestCase):
    def test_every_fixture_case_gives_its_expected_outcome(self):
        for c in FIX['cases']:
            with self.subTest(c['name']):
                p=dict(TEST_POLICY,modes=c.get('policy_modes',TEST_POLICY['modes']))
                r=bd.decide(bd.synthetic_evidence(c),p,c['opportunity'],STATS)
                self.assertEqual((r['outcome'],r['rule']),(c['expect']['outcome'],c['expect']['rule']))
    def test_straddling_deciding_comparison_is_inconclusive(self):
        r=run('straddle');self.assertEqual(r['outcome'],'INCONCLUSIVE');self.assertTrue(any('unknown' in x for x in r['reasons']))
    def test_point_disagreement_is_inconclusive(self):
        self.assertEqual(run('point-disagreement')['outcome'],'INCONCLUSIVE')
        self.assertTrue(any('disagreement' in x and 'baseline/warm true' in x and 'full-dataset/warm false' in x for x in run('point-disagreement')['reasons']))   # T14-APP-04
    def test_mode_disagreement_is_inconclusive(self):
        self.assertEqual(run('mode-disagreement')['outcome'],'INCONCLUSIVE')
        self.assertTrue(any('disagreement' in x and 'baseline/warm true' in x and 'baseline/cold false' in x for x in run('mode-disagreement')['reasons']))   # T14-APP-04
    def test_kernel_only_win_never_changes_the_outcome(self):
        # T14-APP-02: the kernel row sits at the decision point `baseline`; the result and the record never name it.
        base=run('keep');c=case('keep');ev=bd.synthetic_evidence(c);injected=[]
        for r in list(ev['rows']):
            if r['variant']=='py-reference' and r['point']=='baseline':
                k=dict(copy.deepcopy(r),scope='kernel',point='baseline',variant='c-serial',language='c',route=None)
                k['wall']={b:v/100 for b,v in k['wall'].items()};k['cpu']={b:v/100 for b,v in k['cpu'].items()};k['peak']=1;ev['rows'].append(k);injected.append(bd.label(k))
        r=bd.decide(ev,TEST_POLICY,c['opportunity'],STATS);self.assertEqual((r['outcome'],r['rule']),(base['outcome'],base['rule']))
        self.assertEqual((r['outcome'],r['rule']),('KEEP_PYTHON',3));self.assertTrue(injected)
        names={x['base'] for x in r['comparisons']}|{x['other'] for x in r['comparisons']}|{x['row'] for x in r['items']}
        self.assertFalse(names&set(injected),names&set(injected))
    def test_capacity_rows_never_decide(self):
        c=case('keep');ev=bd.synthetic_evidence(c);injected=[]
        for r in list(ev['rows']):
            if r['point']=='baseline' and r['variant']=='py-reference':
                ev['rows'].append(dict(copy.deepcopy(r),scope='capacity',variant='c-threads',workers=4,language='c',wall={b:1.0 for b in r['wall']}));injected.append(bd.label(ev['rows'][-1]))
        self.assertEqual(bd.decide(ev,TEST_POLICY,c['opportunity'],STATS)['outcome'],'KEEP_PYTHON')
        r=bd.decide(ev,TEST_POLICY,c['opportunity'],STATS);self.assertEqual((r['outcome'],r['rule']),('KEEP_PYTHON',3));self.assertTrue(injected)   # T14-APP-02
        names={x['base'] for x in r['comparisons']}|{x['other'] for x in r['comparisons']}|{x['row'] for x in r['items']}
        self.assertFalse(names&set(injected),names&set(injected))
    def test_py_library_counts_as_best_python(self):
        r=run('library');self.assertEqual(r['outcome'],'USE_EXISTING_PYTHON_LIBRARY')
        self.assertIn('py-library',' '.join(r['best'].values()))
    def test_c_compared_with_py_library_when_it_is_strongest(self):
        r=run('c-loses-to-library');names={(x['name'],x['base'].split(' ')[0]) for x in r['comparisons']}
        self.assertIn(('C over best Python','py-library'),names);self.assertNotEqual(r['outcome'],'C_CANDIDATE_FOR_REVIEW')
    def test_item_7_needs_every_operational_cost(self):
        c=case('c-candidate');c['opportunity']['operational_costs'].pop('observability')
        self.assertNotEqual(bd.decide(bd.synthetic_evidence(c),TEST_POLICY,c['opportunity'],STATS)['outcome'],'C_CANDIDATE_FOR_REVIEW')
    def test_missing_approval_cannot_authorize_migration(self):
        c=case('c-candidate');c['opportunity']['approval']={'state':'PENDING'}
        r=bd.decide(bd.synthetic_evidence(c),TEST_POLICY,c['opportunity'],STATS);self.assertNotEqual(r['outcome'],'C_CANDIDATE_FOR_REVIEW')
    def test_approval_must_name_the_baseline(self):
        c=case('c-candidate');c['opportunity']['approval'].pop('baseline_variant')
        self.assertNotEqual(bd.decide(bd.synthetic_evidence(c),TEST_POLICY,c['opportunity'],STATS)['outcome'],'C_CANDIDATE_FOR_REVIEW')
    def test_unbound_policy_cannot_give_a_candidate(self):
        c=case('c-candidate');c['policy_bound']=False
        self.assertNotEqual(bd.decide(bd.synthetic_evidence(c),TEST_POLICY,c['opportunity'],STATS)['outcome'],'C_CANDIDATE_FOR_REVIEW')
    def test_threaded_row_needs_threaded_correctness(self):
        c=case('c-threads-candidate');c['threaded_correctness']=False
        self.assertNotEqual(bd.decide(bd.synthetic_evidence(c),TEST_POLICY,c['opportunity'],STATS)['outcome'],'C_CANDIDATE_FOR_REVIEW')
    def test_python_misses_target_path(self):
        c=case('target-path');r=bd.decide(bd.synthetic_evidence(c),dict(TEST_POLICY,absolute_target_ns_per_unit=50000,target_margin=0.05),c['opportunity'],STATS)
        self.assertEqual(r['outcome'],'C_CANDIDATE_FOR_REVIEW')

class FixRound2Tests(unittest.TestCase):
    """T14-APP-01, 03, 04 (partly above), 05, 06: missing evidence is unknown; one c_items evaluation per identity; reasons."""
    def test_blocked_native_gates_are_unknown(self):
        r=run('gates-blocked');self.assertEqual((r['outcome'],r['rule']),('INCONCLUSIVE',2))
        self.assertTrue(any('item 1' in x and 'c-serial xdirect [stdio]' in x for x in r['reasons']),r['reasons'])
        c=case('gates-blocked');c['native_gates']=None
        self.assertEqual(bd.decide(bd.synthetic_evidence(c),TEST_POLICY,c['opportunity'],STATS)['outcome'],'INCONCLUSIVE')
    def test_failed_native_gates_are_false(self):
        r=run('gates-fail');self.assertEqual((r['outcome'],r['rule']),('USE_EXISTING_PYTHON_LIBRARY',6))
    def test_null_peak_is_inconclusive(self):
        for variant in ('c-serial','py-optimized'):
            with self.subTest(variant=variant):
                c=case('c-candidate');ev=bd.synthetic_evidence(c)
                for r in ev['rows']:
                    if r['point']=='baseline' and r['variant']==variant:r['peak']=None
                r=bd.decide(ev,TEST_POLICY,c['opportunity'],STATS);self.assertEqual((r['outcome'],r['rule']),('INCONCLUSIVE',2))
    def test_cold_only_policy_reads_the_cold_peak(self):
        c=case('c-candidate')
        for r in c['rows']:r['mode']='cold'
        r=bd.decide(bd.synthetic_evidence(c),dict(TEST_POLICY,modes=['cold']),c['opportunity'],STATS)
        self.assertEqual((r['outcome'],r['rule']),('C_CANDIDATE_FOR_REVIEW',4))
    def test_comparison_and_item_labels_are_unique(self):
        for name in ('optimize-first','library','rule-eight','gates-fail'):
            with self.subTest(name):
                r=run(name);keys=[(x['name'],x['base'],x['other'],x['point'],x['mode']) for x in r['comparisons']]
                self.assertEqual(len(keys),len(set(keys)));items=[(x['row'],x['item']) for x in r['items']];self.assertEqual(len(items),len(set(items)))
    def test_unknown_reasons_name_only_the_deciding_rule(self):
        r=run('straddle');self.assertTrue(r['reasons'][0].startswith('rule 3 '))
        named=[x for x in r['reasons'] if x.startswith('unknown deciding comparison')]
        self.assertTrue(named);self.assertTrue(all('benefit over baseline' in x for x in named))
    def test_rule_eight_reason_names_the_false_items(self):
        r=run('rule-eight');self.assertEqual((r['outcome'],r['rule']),('KEEP_PYTHON',8))
        self.assertTrue(any('c-serial xdirect [stdio]' in x and 'items 5 are false' in x for x in r['reasons']),r['reasons'])
        self.assertFalse(any('fails a limit, or the benefit is too small' in x for x in r['reasons']))
    def test_rule_eight_without_a_c_benefit_states_no_false_python_fact(self):      # T14-RR-01
        c=case('rule-eight');c['rows']=[x for x in c['rows'] if x['language']!='c']
        for x in c['rows']:
            if x['variant']=='py-optimized':x.update(wall=75000,cpu=75000)
            elif x['variant']=='py-processes' and x['workers']==4:x.update(wall=70000,cpu=90000)     # within the pool CPU guard
        r=bd.decide(bd.synthetic_evidence(c),TEST_POLICY,c['opportunity'],STATS)
        self.assertEqual((r['outcome'],r['rule']),('KEEP_PYTHON',8))
        self.assertTrue(any(x['name']=='benefit over baseline' and x['value'] is True for x in r['comparisons']))   # a Python row has one
        self.assertEqual(r['reasons'],['no earlier rule matched: no C row shows a benefit over best Python, and rules 6 and 7 did not match'])

class AdoptionTests(unittest.TestCase):
    def test_demo_policy_adoption_is_inconclusive_with_labeled_demo_outcome(self):
        r=run('c-candidate');a=bd.adoption(r,bm.load_decision_policy(ROOT,'demo-cpu-40'))
        self.assertEqual(a,('INCONCLUSIVE','C_CANDIDATE_FOR_REVIEW','Python retained pending evidence'))
    def test_filled_policy_adopts_the_rule_outcome(self):
        r=run('keep');self.assertEqual(bd.adoption(r,TEST_POLICY,case('keep')['opportunity']),('KEEP_PYTHON',None,'policy decision'))   # ruling T29-C4: the approved record

if __name__=='__main__':unittest.main()
