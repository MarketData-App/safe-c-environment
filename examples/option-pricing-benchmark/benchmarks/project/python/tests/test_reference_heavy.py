import math, unittest
from optionlab.reference import evaluate3 as evaluate
from optionlab.models import bjs_price, crr_price
from optionlab.params import CASE

class HeavyReferenceTests(unittest.TestCase):
    def test_american_round_trips(self):
        for model,price in (('bjs',lambda s:bjs_price(1,100,110,1.0,0.04,0.012,s)),('crr',lambda s:crr_price(1,100,110,1.0,0.04,0.012,s,100))):
            for sig in (0.15,0.35,1.5):   # above the early-exercise boundary, so the IV is identifiable
                p=price(sig);st,vals,_=evaluate((1,100.0,110.0,1.0,p,p,0.04,0.012),model,CASE)
                with self.subTest(model=model,sig=sig):self.assertEqual(st,'OK');self.assertLess(abs(vals[0]-sig),1e-8)
    def test_one_hour_rows_have_no_defect(self):
        for model in ('bsm','bjs','crr'):
            st,vals,_=evaluate((0,100.0,100.0,1/365/24,0.20,0.22,0.04,0.012),model,CASE)
            self.assertIn(st,('OK','BELOW_MIN','ABOVE_MAX'));self.assertTrue(st!='OK' or all(math.isfinite(v) for v in vals))

from optionlab.models import sigma_lo
from optionlab.reference import FLAG_BOUNDARY_AMBIGUOUS

class ForwardVegaTests(unittest.TestCase):
    def test_vega_is_forward_at_the_lower_bound(self):
        # mid equals the model price at sigma_lo, so the IV is sigma_lo and sigma - h_sigma < sigma_lo selects the forward difference.
        for model,price in (('bjs',lambda s:bjs_price(0,100.0,100.0,0.5,0.04,0.012,s)),('crr',lambda s:crr_price(0,100.0,100.0,0.5,0.04,0.012,s,CASE.crr_steps))):
            lo=sigma_lo(model,0,0.5,0.04,0.012,CASE);p=price(lo)
            st,vals,flags=evaluate((0,100.0,100.0,0.5,p,p,0.04,0.012),model,CASE)
            with self.subTest(model=model):
                self.assertEqual(st,'OK');self.assertEqual(vals[0],lo);self.assertTrue(flags&FLAG_BOUNDARY_AMBIGUOUS)
                if model=='crr':self.assertEqual(vals[5],(price(lo+CASE.h_sigma)-p)/CASE.h_sigma*0.01)   # BjS vega is the engine's (Task 7b)
                else:
                    from optionlab.models import bjs_result
                    self.assertEqual(vals[5],(math.sqrt(0.5)*bjs_result(0,100.0,100.0,0.5,0.04,0.012,lo)['vega'])*0.01)
