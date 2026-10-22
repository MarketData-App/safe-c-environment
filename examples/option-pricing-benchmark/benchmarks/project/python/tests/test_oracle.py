import json, unittest
from pathlib import Path
from optionlab import oracle
from optionlab.params import CASE
from optionlab import protocol
FIX=protocol.oracle()

class OracleTests(unittest.TestCase):
    def test_fixtures_are_generated(self):
        for key in ('bsm','bjs','lattice','greeks','monotonicity','edge_rows','lnphi'):self.assertTrue(FIX['oracle'][key],key)
        self.assertEqual(FIX['oracle']['bvn'],[])   # Task 7b: section 4 item 4 removed (no bivariate normal); the schema keeps the key
        self.assertIn('bsm-rounding-band',[e['name'] for e in FIX['oracle']['edge_rows']])
    def test_py_reference_passes_items_1_to_8(self):
        # Approval P1-R1-02: item 3 is INCOMPLETE (not PASS) while no BjS-1993 published row is transcribed.
        result=oracle.run_all(FIX,CASE)
        self.assertEqual({k:v['status'] for k,v in result.items()},{**{str(i):'PASS' for i in range(1,9)},'3':'INCOMPLETE'})
        self.assertEqual(result['3']['bjs_transcription'],'BLOCKED')

class KnownAnswerTests(unittest.TestCase):
    """Approval perf-lab-phase1-r1-f16cf65 P1-R1-02: item 3 reports INCOMPLETE, never PASS, while bjs_transcription is
    BLOCKED; a wrong transcribed row is a FAIL in either state; the summary keeps the gate status and names item 3."""
    BSM=[r for r in FIX['oracle']['known_answers'] if r['model']=='bsm']
    def fx(self,rows):return {'oracle':{'known_answers':rows}}
    def test_bsm_rows_alone_are_incomplete(self):
        r=oracle.check_known_answers(self.fx(self.BSM),CASE)
        self.assertEqual((r['status'],r['bjs_transcription'],r['failures']),('INCOMPLETE','BLOCKED',0))
    def test_a_wrong_row_fails_while_blocked(self):
        bad=dict(self.BSM[0],value=self.BSM[0]['value']+0.01)
        self.assertEqual(oracle.check_known_answers(self.fx([bad]+self.BSM[1:]),CASE)['status'],'FAIL')
    def test_a_transcribed_bjs_row_completes_item_3(self):
        from optionlab.models import bjs_price
        v=round(bjs_price(0,42.0,40.0,0.5,0.1,0.0,0.2),2)
        row=dict(self.BSM[0],model='bjs',value=v,source='test row')
        r=oracle.check_known_answers(self.fx(self.BSM+[row]),CASE);self.assertEqual((r['status'],r['bjs_transcription']),('PASS','PRESENT'))
        r=oracle.check_known_answers(self.fx(self.BSM+[dict(row,value=v+0.01)]),CASE);self.assertEqual(r['status'],'FAIL')
    def test_summary_reports_item_3_incomplete(self):
        items={str(i):{'status':'PASS'} for i in range(1,10)};items['3']={'status':'INCOMPLETE'}
        self.assertEqual(oracle.summary_status(items),('PASS',['3']))
        self.assertEqual(oracle.summary_status({**items,'5':{'status':'FAIL'}}),('FAIL',['3']))
        self.assertEqual(oracle.summary_status({**items,'3':{'status':'PASS'}}),('PASS',[]))
        self.assertEqual(oracle.summary_status({**items,'1':{'status':'INCOMPLETE'}}),('FAIL',['1','3']))   # only item 3 may be incomplete

    def test_crr_accuracy_is_a_metric_not_a_gate(self):
        # Amendment D item 2: the q = 0 call equality, the discretization band, the convergence rule and C_crr are metrics.
        r=oracle.check_properties(FIX,CASE);self.assertEqual(r['status'],'PASS')
        acc=r['crr_accuracy'];pts={(d['sigma'],round(d['T'],6)) for d in acc['q0_deviations']}
        self.assertIn((5.0,3.0),pts);self.assertIn((5.0,round(7/365,6)),pts)
        self.assertGreater(acc['bands']['sigma>1|T>1y']['q0_deviation_count'],0);self.assertGreater(acc['bands']['sigma>1|T<=7d']['q0_max_abs'],0.0)
        self.assertEqual(sum(b['points'] for b in acc['bands'].values()),len(FIX['oracle']['lattice']))
        for b in acc['bands'].values():self.assertEqual(sorted(b['euro_max_error']),['100','200','400','800'])
        self.assertNotEqual(oracle.calibrate(FIX,CASE)['decision'],'OWNER_ESCALATION')

class GeneratorTests(unittest.TestCase):
    def test_mpmath_1993_formula_matches_the_engine(self):
        # Task 7b: item 2 is the BjS 1993 closed form in mpmath (spec 3.8); the binary64 engine meets it within the item 2 rule
        # on calls and puts, inside the American branch and at the one-day sigma_lo row of the former quadrature regression.
        from optionlab import oracle_gen
        from optionlab.models import sigma_lo, bjs_price
        r,q=CASE.rate,CASE.dividend_yield
        for side,S,T,s in ((0,110.0,1/365,sigma_lo('bjs',0,1/365,r,q,CASE)),(0,130.0,1.0,0.3),(1,80.0,1.0,0.3),(1,100.0,3.0,0.9),(0,100.0,0.25,2.5)):
            with self.subTest(side=side,S=S,T=T):
                v=float(oracle_gen.bjs_mp(side,S,100.0,T,r,q,s));self.assertLessEqual(abs(bjs_price(side,S,100.0,T,r,q,s)-v),max(1e-10*abs(v),1e-12*100.0))
    def test_pool_workers_run_at_fifty_digits(self):
        # Task 9 review: the bjs part runs in spawn workers; each worker must evaluate at mp.dps = 50.
        import multiprocessing
        from optionlab import oracle_gen
        pool=multiprocessing.get_context('spawn').Pool(2)
        try:dps=pool.map(oracle_gen._worker_dps,[0,1])
        finally:pool.close();pool.join()
        self.assertEqual(dps,[50,50])
