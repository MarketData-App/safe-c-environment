import unittest
from optionlab.synthetic import generate, SIZES
from optionlab.contract import load_chain, rows
from optionlab.reference import run, reduction, FLAG_BOUNDARY_AMBIGUOUS
from optionlab.params import CASE

class SyntheticHeavyTests(unittest.TestCase):
    def test_prefix_stability(self):
        a=generate(40,3,CASE);b=generate(60,3,CASE)
        self.assertEqual({k:v[:40] if isinstance(v,list) else v for k,v in b.items()},a)
    def test_small_tier_reaches_every_targeted_status_and_has_no_ambiguous_rows(self):
        c=load_chain(generate(SIZES['small'],20261007,CASE));res=run(rows(c,CASE),CASE);red=reduction(res)
        for status in ('INVALID_INPUT','EXPIRED','NO_BID','CROSSED','BELOW_MIN','ABOVE_MAX','OK'):
            self.assertGreater(red['bjs']['counts'][status],0,status)
        self.assertFalse(any(f&FLAG_BOUNDARY_AMBIGUOUS for m in res['models'].values() for f in m['flags']))
    def test_out_of_the_money_put_share(self):
        # Amendment D item 3: out-of-the-money puts (K < F) on at least 20 % of the rows of every tier from small up.
        from optionlab.synthetic import otm_put_share
        for tier in ('small','medium','large'):
            with self.subTest(tier=tier):self.assertGreaterEqual(otm_put_share(generate(SIZES[tier],20261007,CASE),CASE),0.20)
