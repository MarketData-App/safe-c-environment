"""Amendment G8.4 with errata I14/I15 (Task 3): the vectorized B09 coverage simulation decides exactly as
tools/bench_units.py (order-statistic bounds, I15), the stdlib code that decides real runs, and its full run fits half the
selftest job deadline."""
import hashlib, importlib.util, json, math, shutil, tempfile, time, unittest
from fractions import Fraction
from pathlib import Path
import numpy as np
from benchlab import coverage
spec=importlib.util.spec_from_file_location('bench_units','/src/tools/bench_units.py');bu=importlib.util.module_from_spec(spec);spec.loader.exec_module(bu)

class CoverageTests(unittest.TestCase):
    def test_numpy_decisions_equal_the_deciding_code(self):
        for cfg in coverage.CONFIGS:
            for look in range(1,coverage.SPECS[cfg]['looks']+1):
                units=coverage.sample_units(cfg,sigma_log=0.10,n=50,seed=7)
                got=coverage.decide_units_np(units['pi'],units['gamma'],look=look)
                want=coverage.decide_units_reference(units,bu,look=look)
                for k in want:np.testing.assert_array_equal(got[k],want[k])
    def test_runtime_projection_fits_the_selftest_deadline(self):
        total=0.0
        for cfg in coverage.CONFIGS:
            for sl in (0.02,0.10):total+=coverage.run(cfg,sl,coverage.POLICY_FOR_TEST,units=200)['seconds']
        projected=total*10000/200
        self.assertLessEqual(projected,1500.0,f'projected coverage wall {projected:.0f} s')

class ErrataTests(unittest.TestCase):
    def test_both_c_configurations_have_one_python_row(self):          # I14
        self.assertEqual(coverage.SPECS['c-one-look']['pi'],[2*coverage.T_NS]);self.assertEqual(coverage.SPECS['c-two-looks']['pi'],[1.02*coverage.T_NS])
        for cfg in ('c-one-look','c-two-looks'):self.assertEqual(coverage.SPECS[cfg]['gamma'],[coverage.SPECS[cfg]['pi'][0]]*12)
    def test_mixed_units_compare_both_outcomes_of_every_event(self):
        for look in (1,2):
            units=coverage.mixed_units(n=48,look=look,seed=21)
            got=coverage.decide_units_np(units['pi'],units['gamma'],look=look)
            want=coverage.decide_units_reference(units,bu,look=look)
            for k in coverage.EVENTS:
                np.testing.assert_array_equal(got[k],want[k])
                self.assertTrue(want[k].any() and not want[k].all(),f'look {look}: event {k} has one outcome only')
    def test_unattainable_bounds_decide_as_the_deciding_code(self):
        rng=np.random.default_rng(5);pi=2e8*np.exp(0.1*rng.standard_normal((6,2,3)));gamma=pi[:,:1,:]*0.5
        got=coverage.decide_units_np(pi,gamma,look=1,blocks=3);want=coverage.decide_units_reference({'pi':pi,'gamma':gamma},bu,look=1)
        for k in coverage.EVENTS:np.testing.assert_array_equal(got[k],want[k])
        self.assertTrue(got['near'].all())                                    # L = -inf: no claim "every row >= T"
    def test_unattainable_c_bound_on_the_c_path_decides_as_the_deciding_code(self):    # Task 3 re-review Minor 2
        # 6 blocks: U(alpha/1) and L(alpha) are attainable (2^-6 <= 0.025), so the units reach orders 5-9; the C bound at
        # alpha/4 is not (2^-6 > 0.025/4): k_c = None on the C path, and no row qualifies although every ratio is 0.5.
        self.assertIsNotNone(coverage.rank(6,bu.alpha(1)));self.assertIsNone(coverage.rank(6,bu.alpha(1)/4))
        rng=np.random.default_rng(9);f=np.array([0.5,2.0,2.0,3.0,2.0,0.5])[:,None,None]
        pi=f*2e8*np.exp(0.02*rng.standard_normal((6,1,6)));gamma=np.repeat(pi*0.5,4,axis=1)
        got=coverage.decide_units_np(pi,gamma,look=1,blocks=6);want=coverage.decide_units_reference({'pi':pi,'gamma':gamma},bu,look=1,blocks=6)
        for k in coverage.EVENTS:np.testing.assert_array_equal(got[k],want[k])
        self.assertTrue(want['reached'].any() and want['keep'].any(),'the C path and the keep path both run')
        self.assertFalse(want['c'].any())
        rows=coverage.decide_units_np(pi,gamma,look=1,blocks=6,rows=True)['c_rows'];self.assertEqual(rows.shape,(6,4));self.assertFalse(rows.any())
    def test_ranks_are_the_deciding_ranks(self):                        # Task 3 re-review Minor 3: independent exact tails
        def exact_rank(n,a):
            num,den=Fraction(a).numerator,Fraction(a).denominator
            for k in range(n+1):
                if k>n//2 and sum(math.comb(n,j) for j in range(k,n+1))*den<=num*2**n:return k
            return None
        for n in range(1,25):
            for look in (1,2):
                for m in range(1,13):
                    a=bu.alpha(look)/m;self.assertEqual(coverage.rank(n,a),exact_rank(n,a),(n,look,m))
                    self.assertEqual(coverage.rank(n,a),bu.bs.order_stat_rank(n,a),(n,look,m))
        self.assertEqual([exact_rank(12,0.025/m) for m in (1,2,7,8,12)],[10,11,11,12,12])           # I15.3
        self.assertEqual([exact_rank(24,0.0125/m) for m in (1,2,3,4,12)],[18,19,19,20,20])
    def test_bench_stats_loads_from_the_digested_source(self):            # Task 3 re-review Minor 1
        with tempfile.TemporaryDirectory() as tmp:
            src=Path(tmp)/'src';out=Path(tmp)/'out';out.mkdir()
            for rel in ('tools/bench_units.py','tools/bench_stats.py','safety/performance-policy.json'):
                (src/rel).parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(Path('/src')/rel,src/rel)
            with open(src/'tools/bench_stats.py','a') as fh:fh.write('\ndef order_stat_rank(n,a):\n    return n\n')
            coverage.job(None,out,src=src);record=json.loads((out/'coverage.json').read_text())
            self.assertEqual(record['bench_stats_sha256'],hashlib.sha256((src/'tools/bench_stats.py').read_bytes()).hexdigest())
            self.assertEqual((record['ranks']['look1']['1'],record['ranks']['look2']['1']),(12,24))    # the ranks of the copy
        self.assertEqual(coverage.rank(12,bu.alpha(1)),10)                    # /src again after the job
    def test_threshold_checks_every_unit_threshold_policy(self):
        self.assertEqual(coverage.threshold({}),coverage.T_NS)
        self.assertEqual(coverage.threshold({'decision_policies':{'some-unit-policy':{'kind':'unit-threshold','threshold_ns_per_request':200000000}}}),200000000)
        with self.assertRaises(ValueError):coverage.threshold({'decision_policies':{'some-unit-policy':{'kind':'unit-threshold','threshold_ns_per_request':100}}})
        self.assertEqual(coverage.threshold({'decision_policies':{'owner':{'threshold_ns_per_request':100}}}),coverage.T_NS)   # a rule policy has no T
        self.assertEqual(coverage.threshold(json.loads(open('/src/safety/performance-policy.json').read())),coverage.T_NS)
    def test_policy_for_test_is_the_policy_entry(self):
        policy=json.loads(open('/src/safety/performance-policy.json').read())
        self.assertEqual({k:v for k,v in coverage.POLICY_FOR_TEST.items() if k in policy['coverage']},policy['coverage'])
        self.assertEqual(sorted(policy['coverage']),['bounds','seed','sigma_log','units']);self.assertEqual(tuple(coverage.POLICY_FOR_TEST['alpha']),bu.ALPHA)
    def test_power_report_and_look2(self):
        out=coverage.run('keep',0.10,coverage.POLICY_FOR_TEST,units=40)
        self.assertEqual(out['units'],40);self.assertTrue(0.0<=out['rate']<=1.0 and 0.0<=out['look2_rate']<=1.0)
        self.assertEqual(coverage.run('c-one-look',0.02,coverage.POLICY_FOR_TEST,units=5)['look2_rate'],0.0)
        power=coverage.power(0.10,coverage.POLICY_FOR_TEST,units=200)
        self.assertEqual(sorted(power),['0.7','0.8','0.9']);self.assertGreater(power['0.7'],power['0.9'])
    def test_power_reports_both_configurations(self):                  # H16.2
        report=coverage.power_report([0.02,0.10],coverage.POLICY_FOR_TEST,units=200)
        self.assertEqual(sorted(report),['0.02','0.1'])
        for sl in ('0.02','0.1'):
            self.assertEqual(sorted(report[sl]),['all_rows_fast','one_row_fast'])
            self.assertEqual(sorted(report[sl]['all_rows_fast']),['0.7','0.8','0.9']);self.assertEqual(sorted(report[sl]['one_row_fast']),['0.7','0.8','0.9'])
            for ratio,row in report[sl]['one_row_fast'].items():
                self.assertEqual(sorted(row),['fast_row_rate','some_row_rate'])
                self.assertTrue(0.0<=row['fast_row_rate']<=row['some_row_rate']<=1.0,(sl,ratio,row))
        self.assertEqual(report['0.1']['all_rows_fast'],coverage.power(0.10,coverage.POLICY_FOR_TEST,units=200))    # (a) unchanged
        self.assertGreater(report['0.1']['one_row_fast']['0.7']['fast_row_rate'],report['0.1']['one_row_fast']['0.9']['fast_row_rate'])
    def test_one_row_fast_rows_are_the_c_rows(self):                   # H16.2 (b): fast row 0, 11 rows at ratio 1.0
        units=coverage.mixed_units(n=48,look=1,seed=4);d=coverage.decide_units_np(units['pi'],units['gamma'],look=1,rows=True)
        self.assertEqual(d['c_rows'].shape,(48,4));np.testing.assert_array_equal(d['c_rows'].any(axis=1),d['c'])
        self.assertFalse((d['c_rows']&~d['reached'][:,None]).any())
        spec=coverage.one_row_fast_spec(0.8);self.assertEqual(spec['pi'],[2*coverage.T_NS]);self.assertEqual(spec['gamma'],[0.8*2*coverage.T_NS]+[2*coverage.T_NS]*11)

if __name__=='__main__':unittest.main()
