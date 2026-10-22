import math, unittest
from pathlib import Path
ROOT=Path('/src')   # the bench container mounts the repository read-only at /src
from optionlab.normal import norm_cdf, norm_pdf, erf
from optionlab.models import bsm, bsm_price, bjs_price, crr_result, crr_price, sigma_lo, ModelDefect
from optionlab.params import CASE
from optionlab import protocol

class NormalTests(unittest.TestCase):
    """Task 7b: the QuantLib N(x) and n(x) (spec 3.4) replace lnPhi and the Genz bivariate normal (no longer in the definition)."""
    def test_norm_cdf_is_continuous_at_the_series_switch(self):
        from optionlab.normal import M_SQRT_2
        form=lambda x:0.5*(1.0+erf(x*M_SQRT_2));lo,hi=-6.0,-5.0          # bisection to the last x where the erf form is > 1e-8
        while math.nextafter(lo,hi)<hi:
            mid=(lo+hi)/2.0
            if mid in (lo,hi):break
            lo,hi=(mid,hi) if form(mid)<=1e-8 else (lo,mid)
        self.assertLessEqual(form(lo),1e-8);self.assertGreater(form(hi),1e-8)
        a=norm_cdf(hi);b=norm_cdf(lo)                                     # erf form at hi, series at lo
        self.assertLess(abs(a-b),1e-6*a);self.assertGreater(norm_cdf(-37.0),0.0)
        self.assertEqual(norm_cdf(-40.0),0.0);self.assertEqual(norm_cdf(-1e3),0.0)     # n(z) = 0 below the density cutoff, so the series gives 0
    def test_norm_cdf_symmetry_and_limits(self):
        for x in (0.0,0.3,1.0,2.0,3.5,5.0):
            self.assertLessEqual(abs(norm_cdf(x)+norm_cdf(-x)-1.0),4*2.220446049250313e-16)
        self.assertEqual(norm_cdf(0.0),0.5);self.assertEqual(norm_cdf(40.0),1.0-2.220446049250313e-16/2)
        self.assertEqual(erf(math.inf),1.0);self.assertEqual(erf(-math.inf),-1.0);self.assertTrue(math.isnan(erf(math.nan)))
    def test_norm_pdf_constant_and_cutoff(self):
        self.assertEqual(norm_pdf(0.0),float.fromhex('0x1.9884533d43651p-2'))
        self.assertEqual(norm_pdf(-math.sqrt(1380.0)-1e-9),0.0);self.assertGreater(norm_pdf(-37.14),0.0)

class ModelTests(unittest.TestCase):
    def test_hull_known_answer(self):
        self.assertEqual(round(bsm_price(0,42,40,0.5,0.10,0.0,0.20),2),4.76);self.assertEqual(round(bsm_price(1,42,40,0.5,0.10,0.0,0.20),2),0.81)
    def test_bsm_parity_and_units(self):
        c=bsm(0,100,95,0.5,0.04,0.012,0.3);p=bsm(1,100,95,0.5,0.04,0.012,0.3)
        self.assertLess(abs(c[0]-p[0]-(100*math.exp(-0.006)-95*math.exp(-0.02))),1e-12)
        self.assertAlmostEqual(c[4],p[4],places=15);self.assertGreater(c[4],0)
    def test_bsm_greeks_hull_known_answer_in_output_units(self):
        # Hull, S=49 K=50 r=0.05 sigma=0.20 T=20/52 q=0: delta 0.522, gamma 0.066, theta -4.31/yr, vega 12.1, rho 8.91 per unit.
        _,delta,gamma,theta,vega,rho=bsm(0,49,50,20/52,0.05,0.0,0.20)
        self.assertAlmostEqual(delta,0.522,delta=5e-4);self.assertAlmostEqual(gamma,0.0655,delta=1e-4)
        self.assertAlmostEqual(theta,-4.31/365,delta=0.01/365);self.assertAlmostEqual(vega,0.121,delta=1e-3)
        self.assertAlmostEqual(rho,0.0891,delta=1e-4)
    def test_bjs_call_with_carry_at_least_rate_equals_bsm(self):
        self.assertAlmostEqual(bjs_price(0,100,100,1.0,0.04,0.0,0.3),bsm_price(0,100,100,1.0,0.04,0.0,0.3),places=12)
    def test_bjs_is_above_european_and_intrinsic(self):
        for side,S in ((0,120),(1,80),(1,100)):
            v=bjs_price(side,S,100,1.0,0.04,0.012,0.25)
            self.assertGreaterEqual(v,bsm_price(side,S,100,1.0,0.04,0.012,0.25)-1e-12);self.assertGreaterEqual(v,max((S-100) if side==0 else (100-S),0))
    def test_bjs_small_sigma_at_sigma_lo_is_finite(self):
        for side in (0,1):
            for T in (1/365/24,1.0,3.0):
                s=sigma_lo('bjs',side,T,0.04,0.012,CASE);self.assertTrue(math.isfinite(bjs_price(side,100,100,T,0.04,0.012,s)))
    def test_bjs_1993_values(self):
        # Task 7b: the definition is the 1993 one-step engine (spec 3.4). The BjS 1993 values that the Task 6 test cited
        # (Haug: 5.2704 call, 4.4531 put) to their 4 decimals, and below American CRR(N=200).
        for side,S,K,T,r,q,s,bjs93 in ((0,42,40,0.75,0.04,0.08,0.35,5.2704),(1,36,40,1.0,0.06,0.0,0.20,4.4531)):
            v=bjs_price(side,S,K,T,r,q,s)
            self.assertAlmostEqual(v,bjs93,delta=5e-5);self.assertLess(v,crr_price(side,S,K,T,r,q,s,200))
    def test_sigma_lo_values_from_the_spec(self):
        self.assertAlmostEqual(sigma_lo('bjs',1,1.0,0.04,0.012,CASE),math.sqrt(2*0.0281/50),places=12)
        self.assertAlmostEqual(1.001*0.0281*1.0/2,0.01406,places=5)
        self.assertAlmostEqual(sigma_lo('crr',0,1.0,0.04,0.012,CASE),1.001*0.0281*0.1,places=12)
        self.assertEqual(sigma_lo('bsm',0,1.0,0.04,0.012,CASE),1e-4)
    def test_sigma_lo_trigger_branch_dominates_at_long_tenor(self):
        s=sigma_lo('bjs',1,9.0,0.04,0.012,CASE)
        self.assertAlmostEqual(s,1.001*0.0281*3.0/2.0,places=12);self.assertAlmostEqual(s,0.04219215,delta=1e-12)
    def test_crr_lattice_greeks_and_american_bound(self):
        res=crr_result(1,100,100,1.0,0.04,0.012,0.3,100);e=crr_price(1,100,100,1.0,0.04,0.012,0.3,100,american=False)
        self.assertEqual(sorted(res),['delta','gamma','theta','value']);self.assertGreaterEqual(res['value'],e)
        self.assertLess(res['delta'],0.0);self.assertGreater(res['gamma'],0.0)
    def test_crr_european_agrees_with_bsm(self):
        e=crr_price(0,100,95,0.5,0.04,0.012,0.3,100,american=False);b=bsm_price(0,100,95,0.5,0.04,0.012,0.3)
        self.assertLess(abs(e-b),5e-4*b)
    def test_crr_probability_outside_unit_interval_is_a_defect(self):
        with self.assertRaises(ModelDefect) as ctx:crr_price(0,100,100,1.0,0.04,0.012,1e-4,100)
        self.assertEqual(str(ctx.exception),'negative probability')     # QuantLib binomialtree.cpp:46-47

class ManifestParameterTests(unittest.TestCase):
    """Amendment A: the option-case completeness rule left tools/bench_model.params_from_case for optionlab.params."""
    def manifest(self):
        import json
        return json.loads((Path(__file__).resolve().parents[2]/'cases/option-chain-greeks.json').read_text())   # benchmarks/project/cases
    def test_the_case_manifest_gives_the_case_parameters(self):
        from optionlab.params import params_from_manifest
        self.assertEqual(params_from_manifest(self.manifest()),CASE)
    def test_the_locked_fixture_kappa_cap_is_the_value_in_use(self):
        # Approval P1-R1-05: the locked calibration kappa_cap binds the CASE value and the case manifest value that the code
        # reads; h_s is a record only (Amendment B removed it from item 7), so no case parameter carries it.
        import json, dataclasses
        from optionlab.params import params_from_manifest
        cal=protocol.oracle()['calibration']
        self.assertEqual(cal['kappa_cap'],CASE.kappa_cap);self.assertEqual(cal['kappa_cap'],params_from_manifest(self.manifest()).kappa_cap)
        self.assertEqual(cal['kappa_cap'],self.manifest()['parameters']['kappa_cap']['value'])
        self.assertEqual(cal['h_s'],{'cap':0.001,'scale':0.1})
        self.assertFalse({f.name.lower() for f in dataclasses.fields(CASE)}&{'h_s'})
    def test_a_manifest_without_crr_steps_raises(self):
        from optionlab.params import params_from_manifest
        m=self.manifest();del m['parameters']['crr_steps']
        with self.assertRaises(ValueError):params_from_manifest(m)
    def test_every_pricing_parameter_is_required(self):
        from optionlab.params import params_from_manifest
        for key in ('rate','dividend_yield','crr_steps','sigma_hi','kappa_cap','h_r','h_sigma','seed'):
            m=self.manifest();del m['parameters'][key]
            with self.subTest(key=key),self.assertRaises(ValueError):params_from_manifest(m)

class IEEEDivisionTests(unittest.TestCase):
    """Task 11b review ruling (PL-T11B-DIV0-01): IEEE-754 binary64 is the definition. A division by zero gives +-inf or NaN,
    as in QuantLib C++; a Python ZeroDivisionError never becomes a status."""
    def test_crr_engine_gives_a_finite_value_and_a_non_finite_delta_at_tiny_dx(self):
        from optionlab.models import crr_mapped_tree, crr_engine
        dx,dps,disc,rates=crr_mapped_tree(1e-24,CASE.rate,CASE.dividend_yield,1e-4,CASE.crr_steps)
        self.assertTrue(0.9e-17<dx<1.1e-17 and math.exp(dx)==1.0)
        out=crr_engine(0,100.0,100.0,dx,dps,disc,CASE.crr_steps,True,rates)
        self.assertTrue(math.isfinite(out['value']));self.assertFalse(math.isfinite(out['delta']))
    def test_guard_gives_the_ieee_result_of_a_division_by_zero(self):
        from optionlab.models import _guard
        div=lambda a,b:a/b
        self.assertEqual(_guard(div,1.0,0.0),math.inf);self.assertEqual(_guard(div,-1.0,0.0),-math.inf)
        self.assertEqual(_guard(div,1.0,-0.0),-math.inf);self.assertTrue(math.isnan(_guard(div,0.0,0.0)))
        self.assertEqual(_guard(lambda a,b:{'v':1.0/(a/b)},1.0,0.0),{'v':0.0})      # the IEEE result continues: 1/inf = 0
    def test_value_path_does_not_evaluate_greek_only_code(self):
        # the reviewer's row at sigma_lo: the CRR lattice delta is 0/0, the value is finite; the price function returns it
        v=crr_price(0,100.0,100.0,1e-24,CASE.rate,CASE.dividend_yield,1e-4,CASE.crr_steps)
        self.assertTrue(math.isfinite(v));self.assertTrue(math.isfinite(bsm_price(0,100.0,100.0,1e-24,CASE.rate,CASE.dividend_yield,1e-4)))
