import math, sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import bench_units as bu, bench_stats as bs
ST={'resamples':1000,'seed':20261007}
def series(m,n=12):return {b:m*(1.0+0.01*((b%5)-2)) for b in range(n)}

class CoreTests(unittest.TestCase):
    """Amendment I15: the owner policy decides with distribution-free order-statistic bounds; stats is accepted and unused."""
    def test_alpha_per_look(self):self.assertEqual((bu.alpha(1),bu.alpha(2)),(0.025,0.0125))
    def test_h_pi_uses_bonferroni(self):
        rows=[('a',series(100.0)),('b',series(150.0)),('c',series(300.0))]
        h,label=bu.h_pi(rows,1,ST);lo,hi=bs.order_stat_bounds(rows[0][1],0.025/3)
        self.assertEqual((h,label),(hi,'a'));self.assertEqual(hi,sorted(rows[0][1].values())[10])        # k(12, 0.025/3) = 11
    def test_l_pi_has_no_adjustment(self):
        rows=[('a',series(100.0)),('b',series(150.0))];l,label=bu.l_pi(rows,1,ST)
        self.assertEqual((l,label),(bs.order_stat_bounds(rows[0][1],0.025)[0],'a'));self.assertEqual(l,sorted(rows[0][1].values())[2])   # x_(3)
    def test_empty_sets(self):
        self.assertEqual(bu.h_pi([],1,ST)[0],math.inf);self.assertEqual(bu.l_pi([],1,ST)[0],math.inf)
    def test_qualifies(self):
        self.assertIs(bu.qualifies(series(100.0),series(40.0),12,1,ST),True)
        self.assertIs(bu.qualifies(series(100.0),series(100.0),12,1,ST),False)
        self.assertIsNone(bu.qualifies(series(100.0),series(40.0,n=11),12,1,ST))
    def test_coverage_bounds_are_the_spec_values(self):
        import bench_model as bm
        self.assertEqual(bm.load_policy(ROOT)['coverage']['bounds'],{'two_look':0.0432,'c_one_look':0.0297})
    def test_rejects_a_bad_look_or_count(self):
        for look in (0,3,True,1.0):
            with self.assertRaises(ValueError):bu.alpha(look)
        for k in (0,-1,True,2.0):
            with self.assertRaises(ValueError):bu.qualifies(series(1.0),series(1.0),k,1,ST)

class OrderStatisticTests(unittest.TestCase):
    """Amendment I15.3: the exact rank table for n = 12 (look 1) and n = 24 (look 2) at every level used."""
    TABLE={1:{1:10,2:11,3:11,4:11,5:11,6:11,7:11,8:12,9:12,10:12,11:12,12:12},
           2:{1:18,2:19,3:19,4:20,5:20,6:20,7:20,8:20,9:20,10:20,11:20,12:20}}
    def test_rank_table(self):
        for look,row in self.TABLE.items():
            for m,k in row.items():self.assertEqual(bs.order_stat_rank(12*look,bu.alpha(look)/m),k,(look,m))
    def test_exact_tails(self):
        self.assertEqual(bs.binomial_upper_tail(12,10),(79,4096));self.assertEqual(bs.binomial_upper_tail(24,18),(190051,16777216))
        self.assertEqual(bs.binomial_upper_tail(24,20),(12951,16777216));self.assertEqual(bs.binomial_upper_tail(12,12),(1,4096))
    def test_bounds_are_the_order_statistics(self):
        values={b:float((7*b)%12) for b in range(12)}                        # 0..11 in shuffled block order
        self.assertEqual(bs.order_stat_bounds(values,0.025),(2.0,9.0))        # x_(3), x_(10)
        self.assertEqual(bs.order_stat_bounds(values,0.025/12),(0.0,11.0))    # x_(1), x_(12)
    def test_ties_keep_the_order_statistics(self):
        values={b:(5.0 if b<8 else 9.0) for b in range(12)}
        self.assertEqual(bs.order_stat_bounds(values,0.025),(5.0,9.0))
    def test_unattainable_with_three_blocks(self):
        three={0:1.0,1:2.0,2:3.0}
        self.assertIsNone(bs.order_stat_rank(3,0.025));self.assertEqual(bs.order_stat_bounds(three,0.025),(-math.inf,math.inf))
        self.assertEqual(bs.order_stat_rank(3,0.2),3)                          # 2^-3 = 0.125 <= 0.2
        self.assertEqual(bu.h_pi([('a',three)],1,ST),(math.inf,'a'));self.assertEqual(bu.l_pi([('a',three)],1,ST),(-math.inf,'a'))
        self.assertIs(bu.qualifies(three,{b:v*0.1 for b,v in three.items()},1,1,ST),False)
        self.assertEqual(bu.unattainable([('a',three)],1,1),{'U_pi':True,'L_pi':True,'C':True})
        self.assertEqual(bu.unattainable([('a',series(1.0))],12,1),{'U_pi':False,'L_pi':False,'C':False})
        self.assertEqual(bu.unattainable([],12,1),{'U_pi':False,'L_pi':False,'C':False})
    def test_rejects_a_bad_level(self):
        for a in (0,0.5,-0.1,True):
            with self.assertRaises(ValueError):bs.order_stat_rank(12,a)
        with self.assertRaises(ValueError):bs.order_stat_rank(0,0.025)
    def test_qualifies_uses_the_per_block_ratios(self):
        p={b:100.0 for b in range(12)};x={b:(50.0 if b!=4 else 101.0) for b in range(12)}    # one ratio above 1
        self.assertIs(bu.qualifies(p,x,12,1,ST),False)                         # k = 12: the largest ratio decides
        self.assertIs(bu.qualifies(p,x,1,1,ST),True)                           # k = 10: x_(10) of the ratios = 0.5
        self.assertEqual(bu.ratio_bounds(p,x,1,1),(0.5,0.5))

class RecordTests(unittest.TestCase):
    def test_coverage_record_binds_bench_stats(self):
        self.assertIn('tools/bench_stats.py',bu.COVERAGE_FILES);self.assertIn('bench_stats_sha256',bu.COVERAGE_KEYS)
        self.assertEqual(len(bu.COVERAGE_FILES),len(bu.COVERAGE_KEYS))
    def test_job_row_other_than_pass_or_fail_is_blocked(self):
        self.assertEqual(bu.coverage_status({'status':'BLOCKED'},[]),'BLOCKED');self.assertEqual(bu.coverage_status({},[]),'BLOCKED')
        self.assertEqual(bu.coverage_status({'status':'PASS'},[]),'PASS');self.assertEqual(bu.coverage_status({'status':'FAIL'},['x']),'FAIL')
        self.assertEqual(bu.coverage_status({'status':'PASS'},['x']),'FAIL')
    def test_policy_has_no_resample_keys(self):
        import bench_model as bm
        self.assertEqual(sorted(bm.load_policy(ROOT)['coverage']),['bounds','seed','sigma_log','units'])

class PowerRowsTests(unittest.TestCase):
    REC={'power':{'0.02':{'all_rows_fast':{'0.9':1.0,'0.8':1.0,'0.7':1.0},'one_row_fast':{'0.9':{'fast_row_rate':0.9,'some_row_rate':0.91},'0.8':{'fast_row_rate':1.0,'some_row_rate':1.0},'0.7':{'fast_row_rate':1.0,'some_row_rate':1.0}}},
                  '0.1':{'all_rows_fast':{'0.9':0.32,'0.8':0.98,'0.7':1.0},'one_row_fast':{'0.9':{'fast_row_rate':0.05,'some_row_rate':0.06},'0.8':{'fast_row_rate':0.49,'some_row_rate':0.5},'0.7':{'fast_row_rate':0.9,'some_row_rate':0.9}}}}}
    def test_level_at_or_above(self):
        self.assertEqual(bu.power_rows(self.REC,0.01)['level'],0.02);self.assertEqual(bu.power_rows(self.REC,0.05)['level'],0.10)
    def test_above_the_largest_level_has_the_caveat(self):
        r=bu.power_rows(self.REC,0.2);self.assertEqual(r['level'],0.10);self.assertIn('upper bound',r['caveat'])
    def test_fast_row_rates_are_used(self):
        self.assertEqual(bu.power_rows(self.REC,0.08)['one_row_fast']['0.8'],0.49)
    def test_exact_levels_zero_and_one_past(self):              # H16.3: at or above, never a lower level, no interpolation
        for sl,level in ((0.0,0.02),(0.02,0.02),(0.0200001,0.10),(0.10,0.10)):
            r=bu.power_rows(self.REC,sl);self.assertEqual(r['level'],level,sl);self.assertIsNone(r['caveat'],sl)
        r=bu.power_rows(self.REC,0.1000001);self.assertEqual(r['level'],0.10);self.assertEqual(r['caveat'],bu.POWER_CAVEAT)
        self.assertEqual(bu.POWER_CAVEAT,'measured noise above the largest computed level; the 0.10 power is an upper bound, the true power is lower')
        self.assertEqual(bu.power_rows(self.REC,0.0)['all_rows_fast'],{'0.9':1.0,'0.8':1.0,'0.7':1.0})
        self.assertEqual(bu.power_rows(self.REC,1e9)['all_rows_fast'],{'0.9':0.32,'0.8':0.98,'0.7':1.0})
    def test_rejects_a_bad_noise_or_record(self):
        for sl in (-0.01,float('nan'),float('inf'),True,'0.1',None):
            with self.assertRaises(ValueError):bu.power_rows(self.REC,sl)
        for rec in ({},{'power':{}},{'power':{'x':{}}},{'power':{'0.1':{'all_rows_fast':{'0.9':0.3}}}},None):
            with self.assertRaises(ValueError):bu.power_rows(rec,0.05)

if __name__=='__main__':unittest.main()
