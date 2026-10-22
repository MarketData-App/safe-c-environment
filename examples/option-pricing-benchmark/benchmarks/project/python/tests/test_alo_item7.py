"""ALO oracle item 7 by erratum E-ALO-6 (Task A4 fix round 2; finding A4R-01): a measured check, not a proven bound.
Per greek: (1) stencil identity - the oracle derives form and step from the I2.6 rules on its own, the variant must report
the same and its greek must equal that stencil bit for bit; (2) truncation - D_R from D_{h/2} and D_{h/4} only,
tol = 2 eps_sch max|V over the h/4 points| / h_eff(h/4) + c |D_{h/2} - D_{h/4}| (c = 32/3 central, 8 one-sided);
(3) error/tol and tol/|greek| reported; resolved only when tol < |greek|/2 (controller amendment A4-C6).

Detection criteria (A4R-07): first fixed before any run as |candidate - greek| > tol; CHANGED after the fix round 2
iteration result (107 of 108 doubled greeks caught) by controller ruling A4-C6 to |candidate - greek| > 2 tol, the
guaranteed-detection bound (a correct greek that passes lies within tol of D_R, so a perturbation above 2 tol must fail
test (2)). Every counted candidate must fail test (2)."""
import math, unittest
from optionlab import oracle, alo
from optionlab.reference import price_and_greeks
from optionlab.params import CASE

H_R=CASE.h_r

class AloItem7Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.points=oracle.alo_item7_points(CASE)
        cls.results=[oracle.alo_item7_point(p,CASE) for p in cls.points]
        cls.summary=oracle.alo_item7(CASE)
    def test_label_reason_and_counts(self):
        self.assertEqual(oracle.ALO_ITEM7_LABEL,'measured, not proven')
        self.assertIn('no closed form',oracle.ALO_ITEM7_REASON);self.assertIn('bit equality',oracle.ALO_ITEM7_REASON)
        self.assertEqual((oracle.EPS_SCH,oracle.C_CENTRAL,oracle.C_ONE_SIDED),(1e-8,32/3,8.0))
        out=oracle.check_greeks({'oracle':{'greeks':[]},'calibration':{'item7':{}}},CASE)['alo_item7']
        self.assertEqual(out['label'],'measured, not proven')
        self.assertEqual(set(out['per_greek']),{'delta','gamma','vega','rho','theta'})
        self.assertEqual(sum(v['resolved']+v['not_resolved'] for v in out['per_greek'].values()),out['terms'])
    # (c) the oracle's own I2.6 decisions
    def test_oracle_h_s_and_theta_step(self):
        st=oracle.alo_item7_stencils(0,100.0,100.0,0.5,CASE.rate,CASE.dividend_yield,0.25,CASE)
        hS=min(1e-3,0.1*0.25*math.sqrt(0.5))*100.0
        self.assertEqual((st['delta'],st['gamma']),(('central',hS),('central',hS)))
        self.assertEqual(st['theta'],('backward',1.0/365.0));self.assertEqual(st['vega'],('central',CASE.h_sigma))
        T=3600/31536000.0;st=oracle.alo_item7_stencils(1,100.0,100.0,T,CASE.rate,CASE.dividend_yield,0.3,CASE)
        self.assertEqual(st['theta'],('backward',T/2.0));self.assertEqual(st['delta'][1],min(1e-3,0.1*0.3*math.sqrt(T))*100.0)
    def test_oracle_vega_forward_rule(self):
        from optionlab.models import sigma_lo
        lo=sigma_lo('alo',1,1.0,CASE.rate,CASE.dividend_yield,CASE)
        self.assertEqual(oracle.alo_item7_stencils(1,100.0,100.0,1.0,CASE.rate,CASE.dividend_yield,lo+5e-4,CASE)['vega'],('forward',CASE.h_sigma))
        self.assertEqual(oracle.alo_item7_stencils(1,100.0,100.0,1.0,CASE.rate,CASE.dividend_yield,lo+CASE.h_sigma,CASE)['vega'],('central',CASE.h_sigma))
    def test_oracle_segment_rule_and_halving(self):
        r,q=CASE.rate,CASE.dividend_yield
        st=oracle.alo_item7_stencils(1,100.0,100.0,1126286/31536000.0,r,q,0.3,CASE)
        self.assertEqual((st['rho'],st['theta']),(('forward',H_R),('forward',1.0/365.0)))
        st=oracle.alo_item7_stencils(1,100.0,100.0,1126285/31536000.0,r,q,0.3,CASE)
        self.assertEqual(st['rho'],('backward',H_R))
        self.assertEqual(oracle.alo_item7_stencils(1,100.0,100.0,10.0,q+0.6*H_R,q,0.3,CASE)['rho'],('backward',H_R/2))
        self.assertIsNone(oracle.alo_item7_stencils(1,100.0,100.0,200.0,q,q,0.3,CASE)['rho'])      # unresolved after 4 halvings
        self.assertIsNone(oracle.alo_item7_stencils(1,100.0,100.0,0.5,0.0,q,0.3,CASE)['rho'])      # r = 0 put (ruling A4R-02)
        self.assertEqual(oracle.alo_item7_stencils(1,100.0,100.0,1.0,r,q,0.3,CASE)['rho'],('central',H_R))
    # (1) and (2) on the correct greeks of py-reference
    def test_every_form_is_covered(self):
        kinds={v['kind'] for r in self.results for v in r.values()}
        for k in ('delta-central','gamma-central','vega-central','vega-forward','rho-central','rho-forward','rho-backward','theta-backward','theta-forward'):
            self.assertIn(k,kinds)
    def test_stencil_identity_holds(self):
        for p,r in zip(self.points,self.results):
            for name,v in r.items():
                with self.subTest(p=p,greek=name):self.assertTrue(v['stencil_ok'])
    def test_truncation_check_passes_on_correct_greeks(self):
        for p,r in zip(self.points,self.results):
            for name,v in r.items():
                with self.subTest(p=p,greek=name):self.assertTrue(v['truncation_ok'],(v['error'],v['tol']))
    def test_not_resolved_terms_are_never_resolved_passes(self):
        for r in self.results:
            for v in r.values():
                self.assertEqual(v['resolved'],v['tol']<abs(v['greek'])/2)
        n=sum(1 for r in self.results for v in r.values() if not v['resolved'])
        self.assertEqual(n,sum(v['not_resolved'] for v in self.summary['per_greek'].values()))
        self.assertEqual(self.summary['failures'],0)
    def test_not_resolved_terms_are_identified(self):
        """A4R2-03 (carried to Task A5): the item 7 record names every not-resolved term by (point, greek, tol/|greek|), and
        counts resolved and not-resolved terms per stencil form (the forward-vega form has its own count)."""
        want=[{'point':i,'greek':name,'kind':v['kind'],'tol_over_greek':v['tol_over_greek']}
              for i,r in enumerate(self.results) for name,v in r.items() if not v['resolved']]
        self.assertEqual(self.summary['not_resolved'],want)
        self.assertEqual(len(want),sum(v['not_resolved'] for v in self.summary['per_greek'].values()))
        forms={}
        for r in self.results:
            for v in r.values():
                f=forms.setdefault(v['kind'],{'resolved':0,'not_resolved':0});f['resolved' if v['resolved'] else 'not_resolved']+=1
        self.assertEqual(self.summary['per_form'],forms);self.assertIn('vega-forward',forms)
        out=oracle.check_greeks({'oracle':{'greeks':[]},'calibration':{'item7':{}}},CASE)['alo_item7']
        self.assertEqual(out['not_resolved'],want);self.assertEqual(out['per_form'],forms)
    # (a) a changed reported stencil fails the gate
    def test_changed_reported_stencil_fails(self):
        p=(1,100.0,100.0,1.0,CASE.rate,CASE.dividend_yield,0.3)
        g=price_and_greeks('alo',*p,CASE)
        bad=dict(g,stencils=dict(g['stencils'],r=(g['stencils']['r'][0],g['stencils']['r'][1]/2)))
        out=oracle.alo_item7_point(p,CASE,variant=bad);self.assertFalse(out['rho']['stencil_ok']);self.assertFalse(out['rho']['ok'])
        bad=dict(g,stencils=dict(g['stencils'],sigma=('forward',g['stencils']['sigma'][1])))
        out=oracle.alo_item7_point(p,CASE,variant=bad);self.assertFalse(out['vega']['stencil_ok']);self.assertFalse(out['vega']['ok'])
        bad=dict(g,stencils=dict(g['stencils'],S=('central',g['stencils']['S'][1]*2)))
        out=oracle.alo_item7_point(p,CASE,variant=bad);self.assertFalse(out['delta']['ok']);self.assertFalse(out['gamma']['ok'])
        bad=dict(g,delta=math.nextafter(g['delta'],0.0))
        self.assertFalse(oracle.alo_item7_point(p,CASE,variant=bad)['delta']['stencil_ok'])
    # (b) the truncation check alone catches a doubled greek and a wrong-form delta above the tolerance
    def trunc_fails(self,p,name,v,candidate):
        form,h=oracle.alo_item7_stencils(*p,CASE)[name]
        t=oracle.alo_truncation(p,CASE,name,form,h)
        return abs(candidate-t['d_r'])>t['tol']
    def test_doubled_greek_fails_the_truncation_check(self):
        """Consistency test, not independent detection evidence (A4R2-02): with the > 2 tol criterion it follows from
        test_truncation_check_passes_on_correct_greeks by the triangle inequality. The detection power of item 7 is the
        resolved count (oracle.alo_item7 per_greek, per_form and not_resolved)."""
        counted=caught=0
        for p,r in zip(self.points,self.results):
            for name,v in r.items():
                c=2.0*v['greek']
                if not abs(c-v['greek'])>2*v['tol']:continue
                counted+=1;caught+=self.trunc_fails(p,name,v,c)
        self.assertGreater(counted,0);self.assertEqual(caught,counted)
    def test_wrong_form_delta_fails_the_truncation_check(self):
        """Consistency test, not independent detection evidence (A4R2-02): with the > 2 tol criterion it follows from
        test_truncation_check_passes_on_correct_greeks by the triangle inequality (see the doubled-greek test)."""
        counted=caught=0
        for p,r in zip(self.points,self.results):
            side,S,K,T,rr,q,s=p;v=r['delta'];h=v['h']
            c=(alo.price(side,S+h,K,T,rr,q,s,CASE)-alo.price(side,S,K,T,rr,q,s,CASE))/h
            if not abs(c-v['greek'])>2*v['tol']:continue
            counted+=1;caught+=self.trunc_fails(p,'delta',v,c)
        self.assertGreater(counted,0);self.assertEqual(caught,counted)

if __name__=='__main__':unittest.main()
