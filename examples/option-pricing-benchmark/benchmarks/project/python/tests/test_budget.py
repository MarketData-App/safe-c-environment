"""Amendment I10.2 (Task A2): the pure planning-budget formula of optionlab.budget (from tools/bench_budget.py at a722ed7) and the required-share rule
(budgets.share_required) of bench_deadline.expected_seconds. Values are the I10.2 illustration table (minutes)."""
import sys, unittest
from pathlib import Path
ROOT=Path('/src')                                           # the bench container mounts the repository read-only at /src
sys.path.insert(0,str(ROOT/'tools'))
from optionlab import budget as bb                          # tools/bench_budget.py of commit a722ed7, moved into this example (FR5B-04)
import bench_model as bm

class BudgetFormulaTests(unittest.TestCase):          # Amendment I10.2 table, four selectors (minutes)
    def minutes(self,s):return round(s/60,1)
    def test_share_one_synthetic_and_local(self):
        g=bb.full_dataset_group(1.0,13230,local=False)
        self.assertEqual((g['sessions'],self.minutes(g['timing']),self.minutes(g['warmups']),self.minutes(g['reference'])),(2,166.6,27.8,30.9))
        g=bb.full_dataset_group(1.0,20000,local=True)
        self.assertEqual((g['sessions'],self.minutes(g['timing']),self.minutes(g['warmups']),self.minutes(g['reference'])),(2,247.9,41.3,46.7))
    def test_single_record_and_diagnostics(self):
        self.assertEqual(self.minutes(bb.single_record_group([0.05,0.10,1.0,0.15])),75.7)
        self.assertEqual(self.minutes(bb.diagnostics(4)),12.0)
    def test_session_cap_feasibility(self):
        self.assertEqual(bb.sessions_for(5400),12)
        with self.assertRaises(bb.PlanRefusal) as e:bb.sessions_for(5400.5)
        self.assertEqual(e.exception.reason,'session-cap-infeasible')
    # FR3: the planning shares are project data (the protocol's budgets); the option example's approved values (Task A5,
    # controller ruling A4-C5) move with the example (FR3 handoff list). The fixture protocol holds m1..m5 shares and
    # share_required [m5]; the framework policy alone holds none.
    FIXTURE='tests/fixtures/bench-project'
    def test_the_required_share_is_the_protocol_value(self):
        pol=bm.load_policy(ROOT,self.FIXTURE)
        self.assertEqual(pol['budgets']['estimate_share_per_selector']['m5'],3.0);self.assertEqual(pol['budgets']['share_required'],['m5'])
        self.assertEqual(bb.share(pol,'m5'),3.0)
        self.assertAlmostEqual(bb.reference_batch(bb.share(pol,'m5'),13230),0.140*13230*3.0)
        self.assertEqual((bb.share(pol,'m3'),bb.share(pol,'all')),(1.0,1.0))
        self.assertEqual(bm.load_policy(ROOT)['budgets']['estimate_share_per_selector'],{})
    def test_no_required_share_refuses(self):
        # the refusal rule stays: a policy without the required share refuses the selector
        import copy
        pol=copy.deepcopy(bm.load_policy(ROOT,self.FIXTURE));del pol['budgets']['estimate_share_per_selector']['m5']
        with self.assertRaises(ValueError):bb.share(pol,'m5')
        with self.assertRaises(ValueError):bb.share(bm.load_policy(ROOT),'m5')
    def test_expected_seconds_refuses_a_required_share(self):
        import copy, bench_deadline as bd
        from evidence import GateError
        pol=copy.deepcopy(bm.load_policy(ROOT,self.FIXTURE));del pol['budgets']['estimate_share_per_selector']['m5']
        with self.assertRaises(GateError):bd.expected_seconds(pol,{'variant':'py-reference','selector':'m5'},13230,1,None)
        full=bm.load_policy(ROOT,self.FIXTURE)
        self.assertAlmostEqual(bd.expected_seconds(full,{'variant':'py-reference','selector':'m5'},10,1,None),
                               3.0*bd.expected_seconds(full,{'variant':'py-reference','selector':'m3'},10,1,None))
        self.assertGreater(bd.expected_seconds(pol,{'variant':'py-reference','selector':'other-test'},10,1,None),0)   # not listed: 1.0 as landed

class BudgetBoundaryTests(unittest.TestCase):
    """Added by the implementer: the bounds and refusals of the interface (b_max, blocks, the local block, the refusal fields)."""
    def test_block_formula(self):
        self.assertAlmostEqual(bb.full_dataset_block(1.0),833.0);self.assertAlmostEqual(bb.full_dataset_block(1.0,local=True),1239.5)
        self.assertAlmostEqual(bb.full_dataset_block(0.0),36.0);self.assertAlmostEqual(bb.reference_batch(0.15,13230),0.140*13230*0.15)
    def test_sessions_bounds(self):
        self.assertEqual(bb.sessions_for(3600),6)          # b_max = 2
        self.assertEqual(bb.sessions_for(1.0),1)           # b_max = 10,799 >= 12 blocks
        self.assertEqual(bb.sessions_for(833.0),2)         # b_max = 11
        self.assertEqual(bb.sessions_for(833.0,blocks=11),1)
        self.assertEqual(bb.sessions_for(100.0,blocks=12,cap=200),12)    # b_max = 1
        with self.assertRaises(bb.PlanRefusal) as e:bb.sessions_for(101.0,cap=200)
        self.assertEqual(e.exception.reason,'session-cap-infeasible');self.assertTrue(e.exception.detail)
    def test_group_total(self):
        g=bb.full_dataset_group(0.15,256,local=False)
        self.assertAlmostEqual(g['total'],g['timing']+g['warmups']+g['reference'])
        self.assertAlmostEqual(g['warmups'],g['sessions']*g['block']);self.assertAlmostEqual(g['timing'],12*g['block'])
    def test_share_refusal_names_the_selector(self):
        pol=bm.load_policy(ROOT,'tests/fixtures/bench-project')
        with self.assertRaises(ValueError) as e:bb.share(pol,'zz-unknown')
        self.assertIn('zz-unknown',str(e.exception));self.assertIn('R14',str(e.exception))
        self.assertEqual(bb.share(pol,'m4'),0.15)

if __name__=='__main__':unittest.main()
