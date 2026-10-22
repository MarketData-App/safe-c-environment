"""G-BAW2 part A (Amendment G2.4; Appendix G-BAW R5, R8, R11, R13): py-reference BAW equals QuantLib-Python 1.43
(BaroneAdesiWhaleyApproximationEngine through the unit-maturity mapping) at ALIGN_TOL on the oracle grid, the edge rows
and the sub-day rows, and bit for bit on the record's grid and its greek points. The statistics go to stderr as one
`BAW-ALIGNMENT-STATS` JSON line (counts and maxima only)."""
import dataclasses, json, math, struct, sys, unittest
import QuantLib as ql
from optionlab import checks, models, reference
from optionlab.baw_admit import baw_admit, discounts, NEWTON_MAX
from optionlab.mapping import unit
from optionlab.params import CASE
from optionlab.checks import ALIGN_TOL as TOL
from tests import quantlib_cache
from optionlab import protocol
FIX=protocol.oracle()
CALL,PUT=0,1
STATS={}

def bits(x):return struct.pack('>d',x).hex()

class BawQuantLibTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):print('BAW-ALIGNMENT-STATS '+json.dumps(STATS,sort_keys=True,default=float),file=sys.stderr)
    def test_record_grid_and_greek_points_are_bit_equal(self):
        c=quantlib_cache.part(FIX,CASE,'baw_record_grid');STATS['record_grid']=c     # Task DD (DD2): checks.baw_record_grid once per process
        self.assertEqual(c['mismatch'],0);self.assertEqual(c['excluded'],c['excluded_ql_raises'])
        self.assertEqual(c['points'],c['admitted']+c['excluded']+c['european']);self.assertGreater(c['bit_equal'],7000)
    def test_alignment_grid_at_align_tol_with_quantlib_iv(self):
        a=quantlib_cache.part(FIX,CASE,'baw_alignment');STATS['alignment']={k:v for k,v in a.items() if k!='failures'};STATS['alignment']['failures']=len(a['failures'])
        self.assertEqual(a['failures'],[]);self.assertEqual(a['rows'],len(checks.ALIGN_GRID))
        self.assertEqual(a['iv']['equal'],a['iv']['rows']);self.assertGreater(a['iv']['ok'],0);self.assertLessEqual(a['iv']['max_iv_abs'],1e-9)
        for k,t in TOL.items():self.assertLessEqual(a['max_rel'][k],t)
    def test_edge_rows_agree(self):
        e=quantlib_cache.part(FIX,CASE,'baw_edge_rows');STATS['edge_rows']={'rows':e['rows'],'bit_equal_rows':e['bit_equal_rows'],'failures':len(e['failures'])}
        self.assertEqual(e['failures'],[]);self.assertGreater(e['rows'],0)
    def test_planted_nonfinite_sstar_raises_the_defect(self):
        p=dataclasses.replace(CASE,baw_plant_nan_sstar=True)
        with self.assertRaises(models.BawRunDefect) as cm:reference.evaluate((PUT,100.0,110.0,1.0,12.0,12.2,0.04,0.012),'baw',p)
        self.assertEqual(cm.exception.args,('baw-nonfinite-sstar',))
        D_r,D_q,v=models.mapped_inputs(1.0,0.04,0.012,0.3)
        from optionlab import baw
        with self.assertRaises(models.BawRunDefect):baw.engine(PUT,100.0,110.0,D_r,D_q,v,plant_nan=True)
        self.assertEqual(baw.engine(CALL,100.0,110.0,*models.mapped_inputs(1.0,0.04,0.0,0.3),plant_nan=True)['branch'],'european')   # no S* there
    def test_forced_cap_raises_the_defect(self):
        p=dataclasses.replace(CASE,baw_newton_max=1)
        with self.assertRaises(models.BawRunDefect) as cm:reference.evaluate((PUT,100.0,110.0,1.0,12.0,12.2,0.04,0.012),'baw',p)
        self.assertEqual(cm.exception.args,('baw-cap',));self.assertEqual(NEWTON_MAX,40)
    def test_branch_gate_vectors_agree_with_quantlib_greek_availability(self):
        """Record R5 / F2: 17 values of q' (T = 1, so q' = q), call and put, S = K = 100, r = 0.04, sigma = 0.3: the Python D_q
        and D_r have the engine's bits, and in_scope equals the branch QuantLib takes (a greek request returns or raises)."""
        t53,t54=2.0**-53,2.0**-54;qs=[0.0,1e-300,-1e-300,5e-324,-5e-324]
        for base in (t53,t54):
            for sgn in (1.0,-1.0):b=sgn*base;qs+=[b,math.nextafter(b,math.inf),math.nextafter(b,-math.inf)]
        n=0
        for q in qs:
            for side in (CALL,PUT):
                r1,q1,s1=unit(1.0,0.04,q,0.3);D_r,D_q=discounts(r1,q1);ins,adm=baw_admit(side,100.0,100.0,r1,q1,s1*s1*1.0)
                o,_=checks.ql_baw_option(side,100.0,100.0,1.0,0.04,q,0.3)
                try:o.delta();branch='european'
                except RuntimeError:branch='american'
                with self.subTest(q=q,side=side):
                    self.assertEqual(not ins,branch=='european')
                    if not ins:self.assertTrue(adm)
                    self.assertEqual(bits(D_q),bits(1.0/math.exp(q1*1.0)))
                n+=1
        STATS['branch_vectors']=n;self.assertEqual(n,34)
    def test_engine_discounts_are_the_python_bits(self):
        D0=ql.Date(2,ql.January,2001);ql.Settings.instance().evaluationDate=D0;dc=ql.Actual365Fixed()
        for T in checks.ALIGN_TS+checks.BAW_RECORD_T:
            for rr in (0.04,0.012,-0.01,5e-324):
                r1,_,_=unit(T,rr,0.0,1.0);ts=ql.FlatForward(D0,r1,dc,ql.Continuous,ql.Annual)
                with self.subTest(T=T,r=rr):self.assertEqual(bits(ts.discount(D0+365)),bits(discounts(r1,0.0)[0]))
    def test_unit_maturity_mapping_witness(self):
        """Record R11: the transcribed engine with the original-T inputs (1/exp(r T), sigma^2 T) against the mapped inputs on
        the Amendment B item 3 maturities, 7 S/K, 5 sigma (>= sigma_lo), call and put: 1e-12 relative for prices >= 1e-8 K;
        a row whose iteration counts differ is reported (not seen in the record)."""
        worst=0.0;n=0;counts_differ=0
        for side in (CALL,PUT):
            for sk in (0.6,0.9,1.0,1.1,1.5,0.8,1.25):
                for T in checks.ALIGN_TS:
                    lo=models.sigma_lo('baw',side,T,CASE.rate,CASE.dividend_yield,CASE)
                    for s in (0.05,0.1,0.3,0.9,2.0):
                        if s<lo:continue
                        S,K=100.0*sk,100.0;r1,q1,s1=unit(T,CASE.rate,CASE.dividend_yield,s)
                        if not baw_admit(side,S,K,r1,q1,s1*s1*1.0)[1]:continue
                        a=models.price_original_T('baw',side,S,K,T,CASE.rate,CASE.dividend_yield,s,CASE);b=models.price('baw',side,S,K,T,CASE.rate,CASE.dividend_yield,s,CASE)
                        n+=1
                        from optionlab.baw_admit import critical_price
                        ca=critical_price(side,K,*models.original_inputs(T,CASE.rate,CASE.dividend_yield,s)[:2],models.original_inputs(T,CASE.rate,CASE.dividend_yield,s)[2],NEWTON_MAX)[1]
                        cb=critical_price(side,K,*models.mapped_inputs(T,CASE.rate,CASE.dividend_yield,s)[:2],models.mapped_inputs(T,CASE.rate,CASE.dividend_yield,s)[2],NEWTON_MAX)[1]
                        counts_differ+=ca!=cb
                        if b>=1e-8*K:
                            worst=max(worst,abs(a-b)/abs(b))
                            with self.subTest(row=(side,S,T,s)):self.assertLessEqual(abs(a-b),1e-12*abs(b))
        STATS['mapping_witness']={'points':n,'max_rel':worst,'iteration_counts_differ':counts_differ};self.assertGreater(n,300)

class FixRound1QuantLibTests(unittest.TestCase):
    def test_record_grid_reraises_run_defects(self):
        from unittest import mock
        def defect(*a,**k):raise models.BawRunDefect('baw-cap')
        with mock.patch.object(models,'baw_price',defect),self.assertRaises(models.BawRunDefect):checks.baw_record_grid(CASE)

if __name__=='__main__':unittest.main()
