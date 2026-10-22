import math, unittest
from pathlib import Path
ROOT=Path('/src')   # the bench container mounts the repository read-only at /src
from optionlab import oracle
from optionlab.params import CASE
from optionlab import protocol
CAL={'safety_factor':2,'floor_eps_multiplier':4,'floor_abs':1e-14,'sup_points':9}

class OracleRuleTests(unittest.TestCase):
    def test_m1_bound_survives_a_zero_of_the_leading_derivative(self):
        # Verdict M1, on the vega bump that remains after Task 7b (spec 3.8 item 7; h_S left): at a zero of d3V/dsigma3 the
        # leading term vanishes and 0.01*h^4/120*V5 (h_sigma = 1e-3, V5 = 1.2e5) is 1e-11; the sup bound still covers it.
        h=1e-3;true_error=0.01*h**4/120*1.2e5
        leading_at_point=oracle.fd_bound('vega',h,0.0,0.0,10.0,CAL)
        m1=oracle.fd_bound('vega',h,sup_lead=3e-5,sup_next=1.2e5,value=10.0,cal=CAL)
        self.assertLess(leading_at_point,true_error);self.assertGreaterEqual(m1,true_error)
    def test_bound_coefficients(self):
        f=lambda kind,h,a,b:oracle.fd_bound(kind,h,a,b,0.0,dict(CAL,floor_eps_multiplier=4,floor_abs=1e-14))
        self.assertAlmostEqual(f('vega',1e-3,1.0,0.0)-oracle.floor(0.0,1e-3,1,CAL,scale=0.01),0.01*2*1e-6/6,places=18)
        self.assertAlmostEqual(f('rho',1e-4,1.0,0.0)-oracle.floor(0.0,1e-4,1,CAL,scale=0.01),0.01*2*1e-8/6,places=20)
        self.assertAlmostEqual(f('vega-forward',1e-3,1.0,0.0)-oracle.floor(0.0,1e-3,1,CAL,scale=0.01),0.01*2*0.0005,places=15)
    def test_kappa_decision_escalates_when_a_lower_cap_cannot_help(self):
        self.assertEqual(oracle.kappa_decision([],CASE),'PASS')
        self.assertEqual(oracle.kappa_decision([{'side':1,'T':1.0,'sigma':0.036}],CASE),'LOWER_KAPPA')
        self.assertEqual(oracle.kappa_decision([{'side':1,'T':1.0,'sigma':0.9}],CASE),'OWNER_ESCALATION')
    def test_bjs_lattice_gap_is_a_documented_metric_not_a_gate(self):
        # Owner decision (Task 9): BjS against the high-step lattice is a model-accuracy metric. A 15% gap and a point above
        # A_ref + eps_ref neither fail item 5 nor escalate the calibration; the gap distribution is reported per band.
        from optionlab.models import bjs_price
        def row(S,T,s,gap):
            bj=bjs_price(0,S,100.0,T,CASE.rate,CASE.dividend_yield,s);a=bj/(1.0-gap)
            return {'side':0,'S':S,'K':100.0,'T':T,'sigma':s,'a_ref':a,'eps_ref':1e-9,'bsm':0.0,'euro':{str(n):0.0 for n in (100,200,400,800)}}
        lat=[row(100.0,1.0,5.0,0.15),row(100.0,0.25,0.3,0.01),row(90.0,1.0,0.1,-1e-4)]
        fx={'oracle':{'lattice':lat,'bjs':[],'greeks':[],'bsm':[]},'calibration':{'c_crr':1e9,'rho_bjs':None,'item7':CAL}}
        c=oracle.calibrate(fx,CASE);self.assertEqual(c['decision'],'PASS');self.assertGreater(c['rho_bjs'],0.02)
        m=c['bjs_vs_lattice'];self.assertEqual(m['above_lattice'],1);self.assertEqual(m['count'],3)
        self.assertAlmostEqual(m['bands']['sigma>1|0.25y<T<=1y']['max'],0.15,places=9)
        self.assertEqual(m['bands']['sigma<=0.1|0.25y<T<=1y']['count'],1)
        p=oracle.check_properties(fx,CASE);self.assertEqual(p['status'],'PASS');self.assertEqual(p['bjs_vs_lattice'],m)
    def test_floor_multiplier_is_calibrated_from_rounding_excess_only(self):
        # Rounding-dominated rho point (T = 1 day, ATM): the truncation terms are zero, the error is all rounding.
        term={'kind':'rho','h':1e-4,'value':0.6,'error':8.2e-13,'bound':oracle.fd_bound('rho',1e-4,0.0,0.0,0.6,CAL)}
        need=oracle.floor_multiplier([term],CAL)
        self.assertAlmostEqual(need,(8.2e-13-1e-14)/(0.01*oracle.EPS/1e-4),places=9)
        m=oracle.calibrated_floor(need);self.assertEqual(m,math.ceil(2*need))
        self.assertGreaterEqual(oracle.fd_bound('rho',1e-4,0.0,0.0,0.6,dict(CAL,floor_eps_multiplier=m)),8.2e-13)
        # A point inside its truncation bound needs no floor; the spec minimum 4 stays.
        inside={'kind':'vega','h':1e-3,'value':10.0,'error':1e-12,'bound':oracle.fd_bound('vega',1e-3,1.0,0.0,10.0,CAL)}
        self.assertEqual(oracle.floor_multiplier([inside],CAL),0.0);self.assertEqual(oracle.calibrated_floor(0.0),4)
    def test_rho_bjs_counts_only_the_gap_beyond_the_reference_error(self):
        # A deep OTM point priced 1e-17 by the lattice and 0 by BjS lies inside eps_ref = 1e-9; it must not drive rho_bjs (it gave 2.0).
        row={'side':0,'S':30.0,'K':100.0,'T':0.25,'sigma':0.1,'a_ref':1e-17,'eps_ref':1e-9+1e-17,'bsm':0.0,'euro':{str(n):0.0 for n in (100,200,400,800)}}
        fx={'oracle':{'lattice':[row],'bjs':[],'greeks':[]},'calibration':{'item7':CAL}}
        self.assertEqual(oracle.calibrate(fx,CASE)['rho_bjs'],0.0)
    def test_vega_property_accepts_ieee_underflow_only_where_the_oracle_vega_underflows(self):
        # One-hour deep OTM call at sigma 0.01: the 50-digit vega is below the smallest normal double, double vega is 0.0.
        row={'side':0,'S':50.0,'K':100.0,'T':1/365/24,'r':0.0,'q':0.0,'sigma':0.01,'price':0.0,'delta':0.0,'gamma':0.0,'theta':0.0,'vega':0.0,'rho':0.0}
        fx={'oracle':{'bsm':[row],'lattice':[]},'calibration':{'c_crr':1.0,'rho_bjs':0.01,'item7':CAL}}
        self.assertEqual(oracle.check_properties(fx,CASE)['status'],'PASS')
        # The same zero double vega fails when the oracle vega is a normal double (strict monotonicity in sigma).
        fx['oracle']['bsm']=[dict(row,vega=1e-300)]
        self.assertEqual(oracle.check_properties(fx,CASE)['status'],'FAIL')

import json
from unittest import mock
FIX=protocol.oracle()

def _greek_fixture(rows=None):
    return {'oracle':{'lattice':[],'bjs':[],'greeks':rows if rows is not None else FIX['oracle']['greeks']},
            'calibration':{'item7':dict(FIX['calibration']['item7'],floor_eps_multiplier=4),'locked':False}}

class ReviewFixTests(unittest.TestCase):
    """Task 9 review: the item 7 floor calibration cannot absorb a real error; NaN fails; quotable edge rows."""
    def test_calibration_cannot_absorb_a_wrong_greek(self):
        real=oracle.bsm
        def wrong(*a):
            v=list(real(*a));v[4]*=1.001;return tuple(v)   # vega 0.1% off (item 7 checks vega and rho since Task 7b)
        with mock.patch.object(oracle,'bsm',wrong):
            c=oracle.calibrate(_greek_fixture(),CASE)
            self.assertGreater(c['item7_violations'],0);self.assertEqual(c['decision'],'OWNER_ESCALATION')
            fx=_greek_fixture();fx['calibration']['item7']['floor_eps_multiplier']=c['floor_eps_multiplier']
            self.assertEqual(oracle.check_greeks(fx,CASE)['status'],'FAIL')
    def test_calibration_cannot_absorb_a_wrong_rho(self):
        # Task 7b: h_S left the definition (spec 3.8 item 7); the other analytic greek that item 7 still checks is rho.
        real=oracle.bsm
        def wrong(*a):
            v=list(real(*a));v[5]*=1.001;return tuple(v)   # rho 0.1% off
        with mock.patch.object(oracle,'bsm',wrong):
            c=oracle.calibrate(_greek_fixture(),CASE)
            self.assertGreater(c['item7_violations'],0);self.assertEqual(c['decision'],'OWNER_ESCALATION')
    def test_floor_never_exceeds_the_input_scale_rounding_bound(self):
        cal=dict(CAL,floor_eps_multiplier=10**6)
        self.assertAlmostEqual(oracle.floor(2.0,0.1,1,cal,inputs=100.0)-1e-14,4*oracle.EPS*100.0/0.1,places=20)
        self.assertAlmostEqual(oracle.floor(2.0,0.1,1,dict(CAL,floor_eps_multiplier=73),inputs=100.0)-1e-14,73*oracle.EPS*2.0/0.1,places=20)
    def test_a_raised_unlocked_multiplier_is_pending_approval(self):
        c=oracle.calibrate(_greek_fixture(),CASE)
        self.assertGreater(c['floor_eps_multiplier'],4);self.assertEqual(c['item7_violations'],0);self.assertEqual(c['decision'],'PENDING_APPROVAL')
        fx=_greek_fixture();fx['calibration'].update(locked=True);fx['calibration']['item7']['floor_eps_multiplier']=c['floor_eps_multiplier']
        self.assertEqual(oracle.calibrate(fx,CASE)['decision'],'PASS')
    def test_nan_fails_items_1_2_4_and_7(self):
        nan=float('nan')
        fx={'oracle':{'bsm':FIX['oracle']['bsm'][:3],'bjs':FIX['oracle']['bjs'][:3],'lnphi':FIX['oracle']['lnphi'][:3],'greeks':FIX['oracle']['greeks'][:1]},
            'calibration':FIX['calibration']}
        with mock.patch.object(oracle,'bsm',lambda *a:(nan,)*6):self.assertEqual(oracle.check_bsm(fx,CASE)['status'],'FAIL')
        with mock.patch.object(oracle,'bjs_price',lambda *a:nan):self.assertEqual(oracle.check_bjs(fx,CASE)['status'],'FAIL')
        with mock.patch.object(oracle,'norm_cdf',lambda *a:nan):self.assertEqual(oracle.check_normal(fx,CASE)['status'],'FAIL')
        with mock.patch.object(oracle,'norm_pdf',lambda *a:nan):self.assertEqual(oracle.check_normal(fx,CASE)['status'],'FAIL')
        with mock.patch.object(oracle,'bsm_price',lambda *a:nan):self.assertEqual(oracle.check_greeks(fx,CASE)['status'],'FAIL')
    def test_ok_edge_rows_use_quotable_quotes(self):
        rows=[e for e in FIX['oracle']['edge_rows'] if e['status']=='OK']
        self.assertTrue(rows);self.assertEqual([e['name'] for e in rows if e['row'][4]<0.01],[])
