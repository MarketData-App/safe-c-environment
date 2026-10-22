"""Task 7b: py-reference agrees with QuantLib-Python 1.43 (spec Amendment B; sections 3.3-3.6).

Adaptations of the brief's draft (no check is weaker): `reference.evaluate` takes the 8-field row (side, S, K, T, bid, ask,
r, q) and returns (status, values, flags), so the IV test unpacks it; QuantLib exception texts, the normal functions and
the oracle edge rows are additional checks. The agreement statistics go to stderr as one `ALIGNMENT-STATS` JSON line
(numbers only)."""
import json, math, sys, unittest
import QuantLib as ql
from optionlab import library, mapping, models, reference, solver
from optionlab.normal import norm_cdf, norm_pdf
from optionlab.params import CASE, CaseParams
HOUR=3600/31536000
TS=(HOUR,6*HOUR,1.5/365,30.25/365,1.0,3.0)               # sub-day, same-day and non-integer-day rows included (H2)
GRID=[(side,S,K,T,s) for side in (0,1) for S in (80.0,100.0,125.0) for K in (90.0,100.0,110.0) for T in TS for s in (0.08,0.25,0.9)]
from optionlab.checks import ALIGN_TOL as TOL          # one tolerance table (review Minor 6)
from optionlab import protocol
R,Q=CASE.rate,CASE.dividend_yield

class MappingTests(unittest.TestCase):
    def test_theta_precedence(self):
        T,s=30.25/365,0.3
        self.assertEqual(mapping.greeks_from_unit(T,R,Q,s,{'delta_U':0.5,'gamma_U':0.01,'theta_U':-2.0})['theta'],-2.0/T/365)
        d={'delta_U':0.5,'gamma_U':0.01,'vega_U':10.0,'rho_U':20.0,'div_rho_U':-25.0}
        self.assertAlmostEqual(mapping.greeks_from_unit(T,R,Q,s,d)['theta'],-(R*20.0+Q*(-25.0)+s/(2*math.sqrt(T))*10.0)/365,places=15)
        self.assertEqual(mapping.greeks_from_unit(T,R,Q,s,{'delta_U':0.5,'gamma_U':0.01},theta_bump=-3.0)['theta'],-3.0/365)
        with self.assertRaises(ValueError):mapping.greeks_from_unit(T,R,Q,s,{'delta_U':0.5,'gamma_U':0.01})
    def test_mapping_arithmetic_is_fixed(self):
        T=30.25/365;self.assertEqual(mapping.unit(T,R,Q,0.3),(R*T,Q*T,0.3*math.sqrt(T)))
    def test_original_T_and_mapped_prices_agree(self):
        for model in ('bsm','bjs','crr'):
            for side,S,K,T,s in GRID:
                with self.subTest(model=model,row=(side,S,K,T,s)):
                    a=models.price_original_T(model,side,S,K,T,R,Q,s,CASE);b=models.price(model,side,S,K,T,R,Q,s,CASE)
                    # Amendment D item 1: BSM and BjS 1e-12 relative; CRR compares like with like (the original-T witness takes
                    # QuantLib's forward-difference drift) within max(S, K)(1 + T) 4 eps / h_fd + 1e-12 max(1, |V|).
                    bound=models.crr_witness_bound(S,K,T,a) if model=='crr' else 1e-12*max(1.0,abs(a))
                    self.assertLessEqual(abs(a-b),bound)
    def test_crr_exact_drift_witness(self):
        # Amendment D item 1: with the exact drift on both sides the mapping is exact to 1e-12 relative.
        for side,S,K,T,s in GRID:
            with self.subTest(row=(side,S,K,T,s)):
                a=models.crr_price_exact_drift(side,S,K,T,R,Q,s,CASE.crr_steps,mapped=False);b=models.crr_price_exact_drift(side,S,K,T,R,Q,s,CASE.crr_steps,mapped=True)
                self.assertLessEqual(abs(a-b),1e-12*max(1.0,abs(a)))
    def test_chain_rule_greeks_match_original_variable_differences(self):
        for side,S,K,T,s in GRID[::7]:
            g=reference.price_and_greeks('bsm',side,S,K,T,R,Q,s,CASE);h=1e-5
            P=lambda **k:models.price('bsm',side,k.get('S',S),K,k.get('T',T),k.get('r',R),Q,k.get('s',s),CASE)
            with self.subTest(row=(side,S,K,T,s)):
                self.assertLessEqual(abs(g['vega']-(P(s=s+h)-P(s=s-h))/(2*h)/100),1e-6*max(1,abs(g['vega'])))
                self.assertLessEqual(abs(g['rho']-(P(r=R+h)-P(r=R-h))/(2*h)/100),1e-6*max(1,abs(g['rho'])))
                # Richardson-extrapolated central difference: the brief's plain central difference with d = min(1e-5, T/4) has a
                # truncation error of about d^2/(8 T^2) relative at sub-day T (2.7e-5 at T = 6 h), above the 1e-5 rule; the
                # tolerance is unchanged, only the reference is more accurate (error O(d^4)).
                d=min(h,T/4);D=lambda e:(P(T=T-e)-P(T=T+e))/(2*e)
                self.assertLessEqual(abs(g['theta']-(4*D(d/2)-D(d))/3/365),1e-5*max(1,abs(g['theta'])))

class QuantLibAlignmentTests(unittest.TestCase):
    def test_prices_and_greeks_match_quantlib(self):
        for model in ('bsm','bjs','crr'):
            for side,S,K,T,s in GRID:
                ours=reference.price_and_greeks(model,side,S,K,T,R,Q,s,CASE);lib=library.price_and_greeks(model,side,S,K,T,R,Q,s,CASE)
                for f,tol in TOL.items():
                    with self.subTest(model=model,row=(side,S,K,T,s),field=f):self.assertLessEqual(abs(ours[f]-lib[f]),tol*max(1.0,abs(lib[f])))
    def test_implied_vol_is_brent_on_the_model_engine(self):
        for model in ('bsm','bjs','crr'):
            for side,S,K,T,s in GRID:
                p=library.price_and_greeks(model,side,S,K,T,R,Q,s,CASE)['price']
                if p<0.01:continue                                  # spec 4 item 6: not a tradable quote
                st,iv,n=library.implied_vol(model,side,S,K,T,R,Q,p,CASE);ours_st,ours_vals,_=reference.evaluate3((side,S,K,T,p,p,R,Q),model,CASE)
                with self.subTest(model=model,row=(side,S,K,T,s)):
                    self.assertEqual(ours_st,st);self.assertLessEqual(n,solver.N_MAX)    # N_MAX: the Task 7a evaluation-count semantics
                    if st=='OK':self.assertLessEqual(abs(ours_vals[0]-iv),1e-9)
    def test_library_never_uses_vanilla_implied_volatility(self):
        import inspect;self.assertNotIn('impliedVolatility',inspect.getsource(library))
    def test_brent_is_the_quantlib_algorithm(self):
        f=lambda x:x**3-2.0*x-5.0
        st,x,_,_,n=solver.brent(f,2.0,3.0,2.5,accuracy=1e-12,max_evaluations=200)
        q=ql.Brent();q.setMaxEvaluations(200);self.assertEqual(st,'OK');self.assertEqual(x,q.solve(f,1e-12,2.5,2.0,3.0))
        self.assertIn(solver.brent(f,3.0,4.0,3.5)[0],('BELOW_MIN','ABOVE_MAX'))
        self.assertEqual(solver.brent(f,2.0,3.0,2.5,accuracy=1e-300,max_evaluations=3)[0],'NOT_CONVERGED')
    def test_version_is_pinned(self):
        # FR4 moved the QuantLib wheel out of the framework image (developer.lock.json bench_python has no QuantLib key); T14 (EX-5):
        # the pin is the version of the quantlib wheel row of this project's third-party lock, which bench.json binds by sha256
        lock=json.load(open('/src/examples/option-pricing-benchmark/benchmarks/project/third_party/lock.json'))
        self.assertEqual(ql.__version__,next(w['version'] for w in lock['wheels'] if w['name']=='quantlib'))

class LatticeAgreementTests(unittest.TestCase):
    def test_every_lattice_point_matches_quantlib(self):
        # Amendment D item 0(a) (section 4 item 9): every lattice oracle point (all sigma, all T, calls and puts) at
        # ALIGN_TOL: CRR(100) American, the fixture's European values at N 100-800, and the q = 0 call pair.
        from optionlab.checks import lattice_agreement
        fx=protocol.oracle();seen=[]
        kinds=set()
        def point(p,kind,N,ours,lib):
            seen.append(1);kinds.add(kind)
            with self.subTest(point=(p['side'],p['S'],p['K'],p['T'],p['sigma']),kind=kind,N=N):
                self.assertLessEqual(abs(ours-lib),TOL['price']*max(1.0,abs(lib)))
        bands,_,n=lattice_agreement(fx,CASE,point)
        # per point: American, 4 stored and 4 live European values (review Minor 3), and the q = 0 pair for calls
        self.assertEqual(n,len(seen));self.assertEqual(n,sum(11 if p['side']==0 else 9 for p in fx['oracle']['lattice']))
        self.assertEqual(sorted({k for k in kinds}),['american','european-fixture','european-live','q0-american','q0-european'])
        self.assertGreater(len(fx['oracle']['lattice']),0)

class LibraryBumpCheckTests(unittest.TestCase):
    """Review Minor 1: the library applies the order-5 check to the CRR bump prices too."""
    def test_bump_below_the_band_is_model_domain_and_a_band_bump_is_flagged(self):
        from unittest import mock
        from optionlab.reference import tau_v, FLAG_ROUNDING_BAND
        side,S,K,T,s=0,100.0,100.0,0.5,0.3;tau=tau_v(S,K,T,R,Q);real=library.price;p=library.price('crr',side,S,K,T,R,Q,s,CASE)
        for bump,expect in ((-1.0,'MODEL_DOMAIN'),(math.nan,'MODEL_DOMAIN'),(-0.5*tau,'OK')):
            fake=lambda model,side_,S_,K_,T_,r,q,sig,params,bump=bump:bump if sig>s else real(model,side_,S_,K_,T_,r,q,sig,params)
            with self.subTest(bump=bump),mock.patch.object(library,'price',fake):
                if expect=='MODEL_DOMAIN':
                    with self.assertRaises(library.EngineDomain):library.price_and_greeks('crr',side,S,K,T,R,Q,s,CASE)
                    self.assertEqual(library.evaluate((side,S,K,T,p,p,R,Q),'crr',CASE)[0],'MODEL_DOMAIN')
                else:
                    self.assertTrue(library.price_and_greeks('crr',side,S,K,T,R,Q,s,CASE)['rounding_band'])
                    st,_,fl=library.evaluate((side,S,K,T,p,p,R,Q),'crr',CASE);self.assertEqual(st,'OK');self.assertTrue(fl&FLAG_ROUNDING_BAND)

class QuantLibDetailTests(unittest.TestCase):
    """Additional checks: the exception texts of spec 3.3 arrive without a prefix; Brent call counts and roots equal
    QuantLib's; the normal functions are QuantLib's; every oracle edge row has QuantLib's status."""
    def test_exception_texts_arrive_without_prefix(self):
        b=ql.Brent();b.setMaxEvaluations(200)
        with self.assertRaises(RuntimeError) as ctx:b.solve(lambda x:x*x+1.0,1e-10,2.5,1e-4,5.0)
        self.assertTrue(str(ctx.exception).startswith(library.BRACKET_TEXT),'bracket text has a prefix')
        b=ql.Brent();b.setMaxEvaluations(200)
        with self.assertRaises(RuntimeError) as ctx:b.solve(lambda x:-1.0 if x<1e-200 else 1.0,1e-10,1.0,-1e300,1e300)
        self.assertEqual(str(ctx.exception),library.MAX_EVAL_TEXT)
    def test_brent_counts_and_roots_equal_quantlib(self):
        cases=[(lambda x:x**3-2.0*x-5.0,2.0,3.0),(lambda x:math.exp(x)-3.0,1e-4,5.0),(lambda x:-1.0 if x<1.234567 else 1000.0,1e-4,5.0),
               (lambda x:math.atan(x-0.3)*1e-3,1e-4,5.0),(lambda x:x-1e-4,1e-4,5.0),(lambda x:x-5.0,1e-4,5.0)]
        for i,(f,lo,hi) in enumerate(cases):
            calls=[];g=lambda x,f=f:(calls.append(x),f(x))[1]
            q=ql.Brent();q.setMaxEvaluations(200);root=q.solve(g,1e-10,(lo+hi)/2.0,lo,hi)
            st,x,_,_,n=solver.brent(f,lo,hi,(lo+hi)/2.0)
            with self.subTest(case=i):self.assertEqual((st,x,n),('OK',root,len(calls)))
        step=lambda x:-1.0 if x<1e-200 else 1.0
        for cap in (5,200):
            calls=[];g=lambda x:(calls.append(x),step(x))[1];q=ql.Brent();q.setMaxEvaluations(cap)
            with self.assertRaises(RuntimeError):q.solve(g,1e-10,1.0,-1e300,1e300)
            st,_,_,_,n=solver.brent(step,-1e300,1e300,1.0,max_evaluations=cap)
            with self.subTest(cap=cap):self.assertEqual((st,n),('NOT_CONVERGED',len(calls)));self.assertEqual(n,cap+1)
        self.assertEqual(solver.N_MAX,201)
    def test_normal_functions_are_quantlibs(self):
        N=ql.CumulativeNormalDistribution();n=ql.NormalDistribution()
        xs=[x/16.0 for x in range(-640,161)]+[-5.6120012,-5.6119,-37.14835,-37.1484,-38.0,8.3,40.0]
        for x in xs:
            with self.subTest(x=x):self.assertEqual(norm_cdf(x),N(x));self.assertEqual(norm_pdf(x),n(x))
    def test_oracle_edge_rows_have_quantlibs_status(self):
        fx=protocol.oracle()
        for e in fx['oracle']['edge_rows']:
            side,S,K,T,bid,ask,r,q=e['row']
            if bid<=0.0 or ask<bid or not all(math.isfinite(v) for v in (bid,ask)):continue   # NO_BID and CROSSED need two quotes
            pp=CaseParams(**{**CASE.__dict__,**e.get('params',{})})
            st=reference.evaluate(tuple(e['row']),e['model'],pp)[0];lib=library.implied_vol(e['model'],side,S,K,T,r,q,(bid+ask)/2.0,pp)[0]
            with self.subTest(row=e['name']):self.assertEqual(st,lib)

if __name__=='__main__':unittest.main()
