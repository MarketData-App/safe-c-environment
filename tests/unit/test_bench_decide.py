import copy, json, sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import bench_decide as bd, bench_model as bm
POL=bm.load_policy(ROOT);STATS=bd.stats_of(POL);FIX=bm.load_fixtures(ROOT)['decision_cases']
TEST_POLICY=FIX['policy']
def case(name):return copy.deepcopy(next(c for c in FIX['cases'] if c['name']==name))
FIXTURE='tests/fixtures/bench-project'     # FR1 (FS1 F3): the synthetic unit-test project (a C variant and an approved opportunity record)
def projects():
    """The fixture project, then every example project (bench.example_projects, found by layout)."""
    import bench
    return [FIXTURE]+bench.example_projects(ROOT)
def run(name,policy=None):
    c=case(name);return bd.decide(bd.synthetic_evidence(c),policy or dict(TEST_POLICY,modes=c.get('policy_modes',TEST_POLICY['modes'])),c['opportunity'],STATS)

class LogicTests(unittest.TestCase):
    def test_kleene(self):
        self.assertIs(bd.t_and(True,None),None);self.assertIs(bd.t_and(False,None),False);self.assertIs(bd.t_or(True,None),True)
        self.assertIs(bd.t_or(False,None),None);self.assertIs(bd.t_not(None),None);self.assertIs(bd.t_or(),False);self.assertIs(bd.t_and(),True)
    def test_consistent(self):
        self.assertIs(bd.consistent([True,True]),True);self.assertIs(bd.consistent([False]),False)
        self.assertIs(bd.consistent([True,False]),None);self.assertIs(bd.consistent([]),None)

# Ruling T14-C1: every test that runs the engine's bootstraps (benefit, limit_ok and each decide call that reaches rule 3)
# runs in the container suite benchmarks/performance/python/tests/test_decide.py with unchanged assertions: about 600
# bootstraps of the policy's 10,000 resamples exceed the check-fast unit gate's 30 s timeout and the 0.5 s per-file budget.

class RuleTests(unittest.TestCase):
    def test_every_rule_has_a_case(self):
        self.assertEqual({c['expect']['rule'] for c in FIX['cases']},set(range(1,9)))
    def test_unit_threshold_policy_is_refused(self):
        c=case('keep')
        with self.assertRaises(ValueError):bd.decide(bd.synthetic_evidence(c),bm.engine_unit_policy(ROOT),c['opportunity'],STATS)
        with self.assertRaises(ValueError):bd.decide(bd.synthetic_evidence(c),bm.load_decision_policy(ROOT,'fixture-request-threshold','tests/fixtures/bench-project'),c['opportunity'],STATS)
    def test_case_rules_refuse_an_unknown_baseline_variant(self):
        from evidence import GateError
        # the synthetic fixture project first, then every example project found by layout; the framework names no example
        # (Amendment A, test_bench_framework_imports; FR1, FS1 F3)
        project,case=next((p,c) for p in projects() for c in (bm.load_case(ROOT,i,p) for i in bm.project_bench(ROOT,p)['cases'])
                          if c['opportunity_record'] and any(v['language']=='c' for v in c['variants']))
        opp=copy.deepcopy(bm.load_opportunity(ROOT,case,project));opp['approval']['baseline_variant']='py-nonexistent'
        with self.assertRaises(GateError):bm.check_baseline_variant(case,opp)
        opp['approval']['baseline_variant']='py-reference';bm.check_baseline_variant(case,opp)
    def test_unfilled_owner_policy_is_inconclusive(self):
        c=case('c-candidate');r=bd.decide(bd.synthetic_evidence(c),bm.load_decision_policy(ROOT,'owner'),c['opportunity'],STATS)
        self.assertEqual((r['outcome'],r['rule']),('INCONCLUSIVE',2));self.assertIn('objective missing',r['reasons'][0])

class AdoptionTests(unittest.TestCase):
    def test_invalid_stays_invalid(self):
        r=run('invalid');self.assertEqual(bd.adoption(r,TEST_POLICY)[0],'INVALID_EXPERIMENT')

# Behavior tests added beside the brief's tests (Task 14 implementer). Each drives a public function with concrete data.

class InterfaceBehaviorTests(unittest.TestCase):
    def test_label_format(self):
        row={'variant':'c-threads','workers':4,'route':'stdio','point':'baseline','mode':'warm'}
        self.assertEqual(bd.label(row),'c-threads x4 [stdio] @baseline/warm')
        self.assertEqual(bd.label(dict(row,variant='py-optimized',workers='direct',route=None)),'py-optimized xdirect @baseline/warm')
        self.assertEqual(bd.label(None),'missing')
    def test_stats_of_reads_the_policy(self):
        self.assertEqual(STATS,{'resamples':POL['statistics']['bootstrap_resamples'],'seed':POL['statistics']['bootstrap_seed'],
                                'interval':POL['statistics']['interval'],'min_blocks':POL['effects']['min_blocks']})
    def test_invalid_run_status_is_invalid_experiment(self):
        c=case('keep');ev=bd.synthetic_evidence(c);ev['status']='FAIL'
        r=bd.decide(ev,TEST_POLICY,c['opportunity'],STATS);self.assertEqual((r['outcome'],r['rule']),('INVALID_EXPERIMENT',1))
        self.assertEqual(bd.adoption(r,TEST_POLICY),('INVALID_EXPERIMENT',None,'invalid experiment: nothing decided'))
    def test_unfilled_template_adoption_is_inconclusive(self):
        owner=bm.load_decision_policy(ROOT,'owner')
        self.assertEqual(bd.adoption({'outcome':'KEEP_PYTHON'},owner),('INCONCLUSIVE','KEEP_PYTHON','Python retained pending evidence'))
        self.assertEqual(bd.adoption({'outcome':'INCONCLUSIVE'},TEST_POLICY),('INCONCLUSIVE',None,'Python retained pending evidence'))
    def test_missing_approval_adoption_is_inconclusive_under_every_policy(self):
        # ruling T29-C4 (spec H1, H4 item 8, section 10): without the required approval (an APPROVED opportunity record that
        # names the baseline variant) the adoption outcome is INCONCLUSIVE under a filled and a demonstration policy; the
        # rule outcome stays visible as the labeled demonstration outcome; an invalid experiment stays INVALID_EXPERIMENT
        approved={'approval':{'state':'APPROVED','baseline_variant':'py-reference'}}
        missing=[None,{},{'approval':{'state':'PENDING'}},{'approval':{'state':'APPROVED'}},{'approval':{'state':'APPROVED','baseline_variant':'py-optimized'}},
                 {'approval':{'state':'approved','baseline_variant':'py-reference'}},{'approval':'APPROVED'}]
        policies=[TEST_POLICY]+[bm.load_decision_policy(ROOT,n) for n in ('demo-latency-2x','demo-cpu-40')]
        for pol in policies:
            for opp in missing:
                for outcome in ('KEEP_PYTHON','C_CANDIDATE_FOR_REVIEW','OPTIMIZE_PYTHON_FIRST'):
                    with self.subTest(policy=pol.get('name',pol['state']),opp=opp,outcome=outcome):
                        a=bd.adoption({'outcome':outcome},pol,opp)
                        self.assertEqual((a[0],a[1]),('INCONCLUSIVE',outcome))
                with self.subTest(policy=pol.get('name',pol['state']),opp=opp,outcome='INVALID_EXPERIMENT'):
                    self.assertEqual(bd.adoption({'outcome':'INVALID_EXPERIMENT'},pol,opp)[0],'INVALID_EXPERIMENT')
        self.assertEqual(bd.adoption({'outcome':'KEEP_PYTHON'},TEST_POLICY,approved),('KEEP_PYTHON',None,'policy decision'))      # control
        self.assertEqual(bd.adoption({'outcome':'KEEP_PYTHON'},policies[1],approved)[0],'INCONCLUSIVE')                          # demo stays
        self.assertEqual(bd.adoption({'outcome':'KEEP_PYTHON'},TEST_POLICY,dict(approved,approval=dict(approved['approval'],baseline_variant='py-library')),
                                     baseline='py-library'),('KEEP_PYTHON',None,'policy decision'))
    def test_decision_record_takes_the_opportunity_approval(self):
        # ruling T29-C4: decision_record gives adoption the run's opportunity record and the case baseline (every protected rule
        # policy is a demonstration or an unfilled template, so the record's outcome alone cannot show the wiring)
        import tempfile, bench_phase3
        from unittest import mock
        from schema_check import validate
        c=case('invalid');ev=bd.synthetic_evidence(c);opp={'approval':{'state':'PENDING'}}
        result={'outcome':'KEEP_PYTHON','rule':8,'reasons':[],'comparisons':[],'items':[],'best':{}}
        with tempfile.TemporaryDirectory() as t:
            m=bench_phase3._mini_root(ROOT,Path(t)/'m')
            from policy import source_identity
            run={'run_id':'0'*31+'1','case':'bench-control-spin','mode':'smoke','source_identity':source_identity(m)[0],'image_id':'sha256:'+'0'*64,'dataset':{'kind':'synthetic'}}
            with mock.patch.object(bd,'adoption',wraps=bd.adoption) as a:
                rec=bd.decision_record(m,run,{},bm.load_case(ROOT,'bench-control-spin'),'demo-latency-2x',result,ev,opp,stats=dict(STATS,resamples=50))
        self.assertIs(a.call_args.args[2],opp);self.assertEqual(a.call_args.kwargs.get('baseline'),'py-reference')
        self.assertEqual((rec['adoption_outcome'],rec['demonstration_outcome']),('INCONCLUSIVE','KEEP_PYTHON'));validate(ROOT,'bench-decision',rec)
    def test_example_record_names_the_baseline_and_every_operational_cost(self):
        recs=[bm.load_opportunity(ROOT,c,p) for p in projects() for c in (bm.load_case(ROOT,i,p) for i in bm.project_bench(ROOT,p)['cases'])
              if c['opportunity_record'] and any(v['language']=='c' for v in c['variants'])]
        self.assertTrue(recs)
        for r in recs:
            self.assertEqual(r['approval']['baseline_variant'],'py-reference');self.assertEqual(set(r['operational_costs']),set(bd.OPERATIONAL_COSTS))
    def test_opportunity_schema_refuses_an_empty_or_unknown_cost(self):
        from schema_check import validate
        from evidence import GateError
        p=FIXTURE;c=bm.load_case(ROOT,bm.project_bench(ROOT,p)['cases'][0],p);rec=bm.load_opportunity(ROOT,c,p)
        validate(ROOT,'bench-opportunity',rec)
        for mutate in (lambda r:r['operational_costs'].update(observability='  '),lambda r:r['operational_costs'].pop('transport'),
                       lambda r:r['operational_costs'].update(score='1'),lambda r:r['approval'].update(baseline_variant='Py Reference')):
            r=copy.deepcopy(rec);mutate(r)
            with self.assertRaises(GateError):validate(ROOT,'bench-opportunity',r)
    def test_synthetic_series_has_twelve_blocks_with_the_stated_median(self):
        ev=bd.synthetic_evidence(case('keep'))
        for r in ev['rows']:
            self.assertEqual(len(r['wall']),12);self.assertEqual(len(r['cpu']),12)
        ref=next(r for r in ev['rows'] if r['variant']=='py-reference')
        self.assertAlmostEqual(sorted(ref['wall'].values())[5]+sorted(ref['wall'].values())[6],200000.0)

if __name__=='__main__':unittest.main()
