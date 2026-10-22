import dataclasses, math, unittest
from optionlab.baw_admit import baw_admit, critical_price
from optionlab import reference as ref
from optionlab.params import CASE
from optionlab import protocol
CALL,PUT=0,1

class AdmitTests(unittest.TestCase):
    def test_european_call_branch_is_always_admitted(self):
        for q1 in (0.0,-1e-300,-5e-324):
            self.assertEqual(baw_admit(CALL,100.0,100.0,0.04,q1,0.04),(False,True))
    def test_negative_rate_is_not_admitted_in_scope(self):
        self.assertEqual(baw_admit(PUT,100.0,100.0,-0.01,0.0,0.04),(True,False))
    def test_branch_gate_at_the_rounding_edge(self):
        e=2.0**-53
        for q1 in (math.nextafter(e,0.0),math.nextafter(e,1.0),-math.nextafter(e,0.0),-math.nextafter(e,1.0)):
            ins,_=baw_admit(CALL,100.0,100.0,0.04,q1,0.04);self.assertEqual(ins,not (1.0/math.exp(q1*1.0)>=1.0))
    def test_cap_hit_on_an_admitted_point_is_a_run_defect(self):
        from optionlab.models import RunDefect          # H19 (Task A4): a run defect is a RunDefect, not a ModelDefect
        p=dataclasses.replace(CASE,baw_newton_max=1)
        with self.assertRaises(RunDefect):ref.evaluate((PUT,100.0,110.0,1.0,12.0,12.2,0.04,0.012),'baw',p)
    def test_admit_excluded_flag_and_reason(self):
        st,vals,flags,_=ref.evaluate((PUT,100.0,100.0,0.25,4.9,5.1,-0.05,0.0),'baw',CASE)
        self.assertEqual(st,'MODEL_DOMAIN');self.assertTrue(flags&64)


class AdmitBoundaryTests(unittest.TestCase):
    """Added by the implementer: the record's R4 order, R3 cap rule (F6), R8 defects, R6/R7 greeks and the reason column."""
    def test_newton_max_is_the_protected_case_value(self):
        import json, pathlib
        from optionlab import baw_admit as ba
        m=json.loads((pathlib.Path(__file__).resolve().parents[2]/'cases/option-chain-greeks.json').read_text())['parameters']['baw_newton_max']
        self.assertEqual((m['value'],m['label']),(40,'protocol'));self.assertEqual(ba.NEWTON_MAX,40);self.assertEqual(CASE.baw_newton_max,40)
        from optionlab.params import params_from_manifest
        self.assertEqual(params_from_manifest({'parameters':json.loads((pathlib.Path(__file__).resolve().parents[2]/'cases/option-chain-greeks.json').read_text())['parameters']}).baw_newton_max,40)
    def test_override_changes_the_cap_never_the_admitted_region(self):
        from optionlab import baw_admit as ba
        from optionlab.mapping import unit
        r1,q1,s1=unit(1.0,0.04,0.012,0.3);v=s1*s1*1.0
        a=ba.baw_admit(PUT,100.0,110.0,r1,q1,v)
        p=dataclasses.replace(CASE,baw_newton_max=1)
        ref.evaluate((PUT,100.0,100.0,0.25,4.9,5.1,-0.05,0.0),'baw',p)            # stopped at the row check, no engine
        self.assertEqual(ba.baw_admit(PUT,100.0,110.0,r1,q1,v),a);self.assertEqual(ba.NEWTON_MAX,40)
    def test_cap_rule_counts_updates(self):
        from optionlab.models import BawRunDefect
        from optionlab.baw_admit import discounts
        from optionlab.mapping import unit
        r1,q1,s1=unit(1.0,0.04,0.012,0.3);D_r,D_q=discounts(r1,q1);v=s1*s1*1.0
        S,n=critical_price(PUT,110.0,D_r,D_q,v,40)
        self.assertTrue(math.isfinite(S) and 1<=n<=9)
        self.assertEqual(critical_price(PUT,110.0,D_r,D_q,v,n),(S,n))          # exactly n updates then a passing stop test: legal
        with self.assertRaises(BawRunDefect) as cm:critical_price(PUT,110.0,D_r,D_q,v,n-1)
        self.assertEqual(cm.exception.args,('baw-cap',))
    def test_planted_nonfinite_sstar_is_a_run_defect(self):
        from optionlab.models import BawRunDefect
        p=dataclasses.replace(CASE,baw_plant_nan_sstar=True)
        with self.assertRaises(BawRunDefect) as cm:ref.evaluate((PUT,100.0,110.0,1.0,12.0,12.2,0.04,0.012),'baw',p)
        self.assertEqual(cm.exception.args,('baw-nonfinite-sstar',))
    def test_run_defects_are_never_a_status(self):
        from optionlab.models import BawRunDefect
        for p in (dataclasses.replace(CASE,baw_newton_max=1),dataclasses.replace(CASE,baw_plant_nan_sstar=True)):
            with self.subTest(params=p),self.assertRaises(BawRunDefect):ref.run([(PUT,100.0,110.0,1.0,12.0,12.2,0.04,0.012)],p,models=('baw',))
    def test_order_of_the_checks(self):
        from optionlab import baw_admit as ba
        self.assertEqual(ba.baw_admit(PUT,100.0,100.0,0.04,0.0,0.0),(True,False))           # 2a: v = 0
        self.assertEqual(ba.baw_admit(PUT,100.0,100.0,0.04,0.0,math.nan),(True,False))      # 2a: v NaN
        self.assertEqual(ba.baw_admit(PUT,100.0,100.0,0.0,0.0,0.09),(True,False))           # D_r = 1 passes 2b (D_r <= 1); the put seed then fails 2d (S_u = -0)
        self.assertEqual(ba.baw_admit(PUT,100.0,100.0,-5e-324,0.0,0.09)[0],True)
        self.assertEqual(ba.baw_admit_rates(PUT,-0.01,0.0),(True,False));self.assertEqual(ba.baw_admit_rates(CALL,-0.01,0.0),(False,True))
        self.assertEqual(ba.baw_admit_rates(PUT,0.0,0.0),(True,True))
    def test_european_branch_row_has_every_engine_greek(self):
        from optionlab.models import bsm_result
        row=(CALL,100.0,100.0,0.5,7.0,7.2,0.04,0.0)
        st,vals,flags,ev=ref.evaluate(row,'baw',CASE);self.assertEqual(st,'OK');self.assertEqual(flags&(16|32|64),0)
        b=ref.evaluate(row,'bsm',CASE);self.assertEqual(b[0],'OK')
        for x,y in zip(vals,b[1]):self.assertEqual(x,y)                         # q = 0 call: BAW's European branch is BSM
    def test_exercise_side_greeks_are_exact(self):
        g=ref.price_and_greeks('baw',PUT,60.0,100.0,1.0,0.04,0.012,0.2,CASE)
        self.assertEqual((g['delta'],g['gamma'],g['theta'],g['vega'],g['rho']),(-1.0,0.0,0.0,0.0,0.0));self.assertEqual(g['price'],40.0)
        g=ref.price_and_greeks('baw',CALL,200.0,100.0,1.0,0.04,0.1,0.2,CASE)
        self.assertEqual((g['delta'],g['gamma'],g['theta'],g['vega'],g['rho']),(1.0,0.0,0.0,0.0,0.0));self.assertEqual(g['price'],100.0)
    def test_continuation_greeks_against_central_differences(self):
        side,S,K,T,r,q,s=PUT,100.0,100.0,1.0,0.04,0.012,0.3
        g=ref.price_and_greeks('baw',side,S,K,T,r,q,s,CASE);self.assertEqual(g['stencils']['S'][0],'central');self.assertEqual(g['flags']&32,0)
        V=lambda **k:ref.price_function('baw',CASE)(side,k.get('S',S),K,k.get('T',T),k.get('r',r),q,k.get('s',s))
        self.assertAlmostEqual(g['delta'],(V(S=S+0.05)-V(S=S-0.05))/0.1,places=5)
        self.assertAlmostEqual(g['vega'],(V(s=s+1e-3)-V(s=s-1e-3))/2e-3/100,places=5)
        self.assertLess(g['delta'],0.0);self.assertGreater(g['gamma'],0.0);self.assertGreater(g['vega'],0.0)
    def test_one_sided_stencil_near_sstar_sets_the_switched_flag(self):
        from optionlab.baw_admit import discounts, sstar
        from optionlab.mapping import unit
        T,r,q,s=1.0,0.04,0.012,0.3;r1,q1,s1=unit(T,r,q,s);D_r,D_q=discounts(r1,q1);Sk=sstar(PUT,100.0,D_r,D_q,s1*s1*1.0,40)
        S=Sk*(1.0+5e-4)                                                         # h_S = 0.03 S > S - S*: the central stencil crosses S*
        g=ref.price_and_greeks('baw',PUT,S,100.0,T,r,q,s,CASE)
        self.assertEqual(g['stencils']['S'][0],'one-sided');self.assertTrue(g['flags']&32)
    def test_stencil_unresolved_and_reason_column(self):
        from unittest import mock
        real=ref.baw_point_side;first=[]
        def fake(side,S,K,T,r,q,s,params,reason):
            got=real(side,S,K,T,r,q,s,params,reason)
            if not first:first.append(s)                                        # the row point at the IV
            return got if s==first[0] else 'exercise'                           # every sigma bump point leaves the row side
        row=(PUT,100.0,100.0,1.0,0.0,0.0,0.04,0.012)
        p=ref.price_function('baw',CASE)(PUT,100.0,100.0,1.0,0.04,0.012,0.3);row=row[:4]+(p,p)+row[6:]
        with mock.patch.object(ref,'baw_point_side',fake):
            info={};st,_,flags,_=ref.evaluate(row,'baw',CASE,info=info)
        self.assertEqual(st,'MODEL_DOMAIN');self.assertTrue(flags&16)
        r=ref.run([(PUT,100.0,100.0,0.25,4.9,5.1,-0.05,0.0),row],CASE,models=('baw',))
        self.assertEqual(r['models']['baw']['admit_reason'],['row',None]);self.assertNotIn(b'admit_reason',ref.canonical_result(r))
    def test_brent_exclusion_reason(self):
        info={};e=2.0**-53                                                      # q*T just above 2^-53: an American call where QuantLib raises
        st,_,flags,ev=ref.evaluate((CALL,100.0,100.0,1.0,12.0,12.2,0.04,math.nextafter(e,1.0)),'baw',CASE,info=info)
        self.assertEqual((st,bool(flags&64),info.get('admit_reason'),ev),('MODEL_DOMAIN',True,'brent',0))
    def test_count_rule(self):
        from unittest import mock
        calls=[]
        real=ref.model_price
        def counting(*a,**k):calls.append(1);return real(*a,**k)
        with mock.patch('optionlab.reference.model_price',counting):st,_,_,ev=ref.evaluate((PUT,100.0,110.0,1.0,12.0,12.2,0.04,0.012),'baw',CASE)
        self.assertEqual(st,'OK');self.assertEqual(ev,len(calls)+1)          # every engine value call plus 1 for the greeks of an OK row
    def test_sigma_lo(self):
        from optionlab.models import sigma_lo
        self.assertEqual(sigma_lo('baw',PUT,1.0,0.04,0.012,CASE),1.001*(0.028+1e-4)*1.0/2.0)
        self.assertEqual(sigma_lo('baw',CALL,1.0,0.04,0.012,CASE),1e-4)
        self.assertEqual(sigma_lo('baw',PUT,1e-6,0.04,0.012,CASE),1e-4)
    def test_selector_baw_in_every_variant(self):
        import json, pathlib
        from optionlab import contract
        from optionlab.adapter import OptionChainGreeks
        self.assertEqual(contract.selector_models('baw'),('baw',))
        raw={k:v['value'] for k,v in json.loads((pathlib.Path(__file__).resolve().parents[2]/'cases/option-chain-greeks.json').read_text())['parameters'].items()}
        a=OptionChainGreeks(raw,selector='baw')
        chain={'n':1,'side':[1],'S':[100.0],'K':[110.0],'T':[1.0],'bid':[12.0],'ask':[12.2],'r':[0.04],'q':[0.012]}
        for v in ('py-optimized','py-library'):        # G-BAW2 part B (Task 6): no variant refuses baw
            with self.subTest(variant=v):
                res=a.materialize(a.run(a.prepare(chain,v,1),v,1));self.assertEqual(set(res['models']),{'baw'});self.assertEqual(res['models']['baw']['status'],['OK'])
        rows=[(PUT,100.0,100.0,0.25,4.9,5.1,-0.05,0.0),(PUT,100.0,110.0,1.0,12.0,12.2,0.04,0.012)]
        res=a.run(rows,'py-reference',1)
        self.assertEqual(a.reference_exclusions(res),{'row':1,'brent':0,'bump':0})
        self.assertIsNone(OptionChainGreeks(raw,selector='bsm').reference_exclusions(ref.run(rows,CASE,models=('bsm',))))

class FixRound1Tests(unittest.TestCase):
    """Task 5 review fix round 1: a run defect fails a check (I-1); one baw_newton_max validator and source; BAW_LEAD
    defined once; the fixture coverage that the record allows."""
    def test_alignment_check_reraises_run_defects(self):
        from unittest import mock
        from optionlab import checks
        from optionlab.models import BawRunDefect
        def defect(*a,**k):raise BawRunDefect('baw-cap')
        with mock.patch.object(ref,'sstar',defect),self.assertRaises(BawRunDefect):checks.baw_alignment(CASE,grid=[(PUT,100.0,100.0,1.0,0.3)])
    def test_lattice_metric_and_iv_roundtrip_reraise_run_defects(self):
        from unittest import mock
        from optionlab import oracle
        from optionlab.models import BawRunDefect
        def raiser(*a):raise BawRunDefect('baw-nonfinite-sstar')
        real=oracle.price_function
        pf=lambda m,p:raiser if m=='baw' else real(m,p)
        fx={'oracle':{'lattice':[{'side':1,'S':100.0,'K':100.0,'T':1.0,'sigma':0.3,'a_ref':10.0,'eps_ref':1e-6}]}}
        with mock.patch.object(oracle,'price_function',pf):
            with self.assertRaises(BawRunDefect):oracle.baw_lattice_metric(fx,CASE)
            with self.assertRaises(BawRunDefect):oracle.check_iv_roundtrip(fx,CASE)
    def test_one_newton_max_validator_and_source(self):
        import json, pathlib
        from optionlab import params, baw_admit as ba
        for good in (1,40,40.0):self.assertEqual(params.check_newton_max(good),int(good))
        for bad in (0,41,1.5,True,'40',None,float('nan'),float('inf')):
            with self.subTest(bad=bad),self.assertRaises(ValueError):params.check_newton_max(bad)
        m=json.loads((pathlib.Path(__file__).resolve().parents[2]/'cases/option-chain-greeks.json').read_text())
        m['parameters']['baw_newton_max']['value']=41
        with self.assertRaises(ValueError):params.params_from_manifest(m)
        with self.assertRaises(TypeError):params.CaseParams(0.04,0.012,100)                   # no code default: the manifest value is required
        self.assertEqual((params.CASE.baw_newton_max,ba.NEWTON_MAX),(40,40))
    def test_baw_lead_is_defined_once(self):
        from optionlab import oracle, oracle_gen
        self.assertIs(oracle_gen.BAW_LEAD,oracle.BAW_LEAD)
    def test_fixture_coverage(self):
        import json
        fx=protocol.oracle()['oracle']['baw']
        edges={e['name']:e for e in fx if e['kind']=='edge'}
        a=edges['baw-call-zero-rate-admitted'];self.assertEqual((a['row'][6],a['status'],a['reason']),(0.0,'OK',None))
        h=edges['baw-put-rate-stencil-halved'];self.assertEqual(h['status'],'OK');self.assertTrue(h['flags']&32)
        kinds={g['kind'] for p in fx if p['kind']=='stencil' for g in p['greeks'].values()}
        for k in ('rho-forward','rho-backward','theta-forward','delta-one-sided','vega-forward'):self.assertIn(k,kinds)

if __name__=='__main__':unittest.main()
