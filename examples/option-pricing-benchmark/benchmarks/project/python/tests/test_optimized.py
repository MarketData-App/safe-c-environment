"""Task 11b: py-optimized (NumPy + SciPy) computes the QuantLib 1.43 definitions of py-reference (spec 3.3-3.7, 5;
Amendments B and D).

Adaptations of the brief's draft (no check is weaker): the brief tested `ln_ndtr` and a bivariate normal `bvn_cdf`, which
spec 3.4 and 3.8 removed from the definition (the pinned Bjerksund-Stensland engine is the 1993 method without a
bivariate normal; QuantLib's N(x) replaces the lnPhi asymptote). The primitive tests check the vectorized ports of
QuantLib's ErrorFunction, N(x) and n(x), close() and Brent against the scalar transcriptions instead. The agreement tests of
the brief stay (edge rows, seeds 1-3, prepared input); QuantLib-Python agreement and transcription-identity tests are added.
"""
import inspect, json, math, unittest
from pathlib import Path
import numpy as np
from optionlab import optimized as opt, normal, models, reference, solver, library
from optionlab.agreement import compare
from optionlab.checks import ALIGN_TOL, ALIGN_GRID
from optionlab.contract import load_chain, rows, STATUSES
from optionlab.reference import run as ref_run
from optionlab.synthetic import generate
from optionlab.params import CASE, CaseParams
from optionlab import protocol

def core(result):
    """A py-reference result without the optional columns (Amendment G3.7, G5.3: engine_evals and admit_reason are
    outside the digest and only py-reference produces engine_evals); every other column is compared exactly."""
    return {'n':result['n'],'models':{m:{k:v for k,v in c.items() if k not in reference.OPTIONAL_COLUMNS} for m,c in result['models'].items()}}
FIX=protocol.oracle()
EPS=2.0**-52
R,Q=CASE.rate,CASE.dividend_yield

def near(a,b,rel):
    return a==b or (math.isnan(a) and math.isnan(b)) or abs(a-b)<=rel*max(abs(a),abs(b))

def prep_rows(rws):
    return {'n':len(rws),'side':np.array([r[0] if r[0] in (0,1) else 255 for r in rws],np.uint8),
            **{k:np.array([r[i] for r in rws],float) for k,i in (('S',1),('K',2),('T',3),('bid',4),('ask',5),('r',6),('q',7))}}

class VectorPrimitiveTests(unittest.TestCase):
    XS=[x/16.0 for x in range(-640,161)]+[-5.6120012,-5.6119,-37.14835,-37.1484,-38.0,8.3,40.0,0.0,-0.0,1e-300,-1e-300,
        3.7e-9,-3.8e-9,0.84375,-0.84375,1.25,-1.25,2.857142857142,6.0,-6.0,math.inf,-math.inf,math.nan]
    def test_erf_and_normal_functions_match_the_scalar_quantlib_ports(self):
        # NumPy's exp may differ from libm in the last bit (spec 3.7); the polynomial regions are exact.
        xs=np.array(self.XS)
        for name,vec,sc in (('erf',opt.erf,normal.erf),('norm_cdf',opt.norm_cdf,normal.norm_cdf),('norm_pdf',opt.norm_pdf,normal.norm_pdf)):
            got=vec(xs)
            for x,v in zip(self.XS,got.tolist()):
                with self.subTest(f=name,x=x):self.assertTrue(near(v,sc(x),4*EPS),(v,sc(x)))
        poly=np.array([x for x in self.XS if math.isfinite(x) and abs(x)<1.25])
        self.assertEqual(opt.erf(poly).tolist(),[normal.erf(x) for x in poly.tolist()])
    def test_close_matches_the_scalar_close(self):
        pairs=[(0.0,0.0),(0.0,1e-29),(0.0,9e-29),(1.0,1.0+40*EPS),(1.0,1.0+50*EPS),(-1.0,1.0),(1e-300,0.0),(math.nan,1.0),(math.inf,math.inf)]
        got=opt.close(np.array([a for a,_ in pairs]),np.array([b for _,b in pairs]))
        self.assertEqual(got.tolist(),[models.close(a,b) for a,b in pairs])
    def test_brent_is_the_scalar_brent_elementwise(self):
        # Functions with only + - * / so NumPy and Python round identically: root, status and evaluation count must be equal.
        fs=[lambda x:x*x*x-2.0*x-5.0,lambda x:x-1e-4,lambda x:x-5.0,lambda x:(x-0.3)*1e-3,lambda x:x*x+1.0,lambda x:-x*x-1.0,
            lambda x:(x-1.234567)*(x-1.234567)*(x-1.234567),lambda x:1.0/(x-7.0)+0.5]
        lo,hi=1e-4,5.0
        for i,f in enumerate(fs):
            with self.subTest(f=i):
                st,x,fa,fb,n=solver.brent(f,lo,hi,(lo+hi)/2.0)
                vs,vx,vfa,vfb,vn=opt.brent(lambda idx,xx,f=f:(f(xx),np.zeros(xx.shape,bool)),np.array([lo]),np.array([hi]),np.array([(lo+hi)/2.0]))
                self.assertEqual(STATUSES[int(vs[0])],st);self.assertEqual(int(vn[0]),n)
                self.assertTrue(near(float(vx[0]),x,0.0));self.assertTrue(near(float(vfa[0]),fa,0.0));self.assertTrue(near(float(vfb[0]),fb,0.0))
        step=lambda x:np.where(x<1e-200,-1.0,1.0)
        for cap in (5,200):
            vs,_,_,_,vn=opt.brent(lambda idx,xx:(step(xx),np.zeros(xx.shape,bool)),np.array([-1e300]),np.array([1e300]),np.array([1.0]),max_evaluations=cap)
            st,_,_,_,n=solver.brent(lambda x:float(step(x)),-1e300,1e300,1.0,max_evaluations=cap)
            with self.subTest(cap=cap):self.assertEqual((STATUSES[int(vs[0])],int(vn[0])),(st,n));self.assertEqual(n,cap+1)
        self.assertLessEqual(n,solver.N_MAX)
    def test_brent_masks_rows_independently_and_stops_a_dead_row(self):
        # Several rows with different roots in one call; a row whose f reports an order-5 failure stops as MODEL_DOMAIN.
        roots=np.array([0.01,0.3,1.7,4.9,2.2]);lo=np.full(5,1e-4);hi=np.full(5,5.0)
        def fun(idx,x):return (x-roots[idx])*(1.0+x),(idx==4)&(x>2.0)
        vs,vx,_,_,vn=opt.brent(fun,lo,hi,(lo+hi)/2.0)
        for i in range(4):
            st,x,_,_,n=solver.brent(lambda s,i=i:(s-roots[i])*(1.0+s),1e-4,5.0,(1e-4+5.0)/2.0)
            with self.subTest(row=i):self.assertEqual((STATUSES[int(vs[i])],float(vx[i]),int(vn[i])),(st,x,n))
        self.assertEqual(STATUSES[int(vs[4])],'MODEL_DOMAIN');self.assertTrue(math.isnan(float(vx[4])))
    def test_sigma_lo_domain_check_and_tau_v_match_the_scalar_rules(self):
        Ts=np.array([3600/31536000,1.0/365,0.5,1.0,3.0,7.0,7.2,20.0]);P=CaseParams(**{**CASE.__dict__,'kappa_cap':1e6})
        for params in (CASE,P):
            for side in (0,1):
                for m in ('bsm','bjs','crr'):
                    got=opt.sigma_lo(m,np.full(Ts.shape,side,np.uint8),Ts,R,Q,params)
                    self.assertEqual(got.tolist(),[models.sigma_lo(m,side,T,R,Q,params) for T in Ts.tolist()])
            self.assertEqual(opt.crr_domain_ok(Ts,R,Q,params).tolist(),[models.crr_domain_ok(T,R,Q,params) for T in Ts.tolist()])
        S=np.array([100.0,50.0,600.0]);K=np.array([100.0,120.0,300.0]);T=np.array([0.5,2.0,1/365])
        for a,b in zip(opt.tau_v(S,K,T,R,Q).tolist(),[reference.tau_v(*x,R,Q) for x in zip(S.tolist(),K.tolist(),T.tolist())]):
            self.assertTrue(near(a,b,4*EPS))

class TranscriptionTests(unittest.TestCase):
    def test_bjs_phi_functions_are_the_scalar_text(self):
        # The phi functions and their analytic derivatives are the text of optionlab.models (bjerksundstenslandengine.cpp
        # lines 37-110); only std::erfc is the vectorized platform erfc.
        for name in ('_phi','_phi_S','_phi_SS','_phi_gamma','_phi_H','_phi_I','_phi_rt','_phi_bt','_phi_v'):
            with self.subTest(f=name):
                self.assertEqual(inspect.getsource(getattr(opt,name)),inspect.getsource(getattr(models,name)).replace('math.erfc','_erfc'))
    def test_american_value_and_greek_block_is_the_scalar_text(self):
        def body(src,start,stop):
            lines=src.splitlines();a=next(i for i,l in enumerate(lines) if l.strip().startswith(start))
            b=next(i for i in range(a,len(lines)) if lines[i].strip().startswith(stop))
            return [l.strip() for l in lines[a:b+1]]
        ms=inspect.getsource(models._american_call);os_=inspect.getsource(opt._american_formula)
        self.assertEqual(body(os_,'pSb=','results[\'value\']='),body(ms,'pSb=','results[\'value\']='))
        a=body(os_,'sSb=','results[\'strikeGamma\']=');b=body(ms,'sSb=','results[\'strikeGamma\']=')
        self.assertEqual(len(a),len(b))
        diff=[(x,y) for x,y in zip(a,b) if x!=y]
        self.assertEqual([y for _,y in diff],['B0Dq=0.0 if dD<=rfD else X*_log(rfD)/_sq(_log(dD))*tq','B0Dr=0 if dD<=rfD else -X*tr/_log(dD)'])
        self.assertEqual([x for x,_ in diff],['B0Dq=np.where(dD<=rfD,0.0,X*_log(rfD)/_sq(_log(dD))*tq)','B0Dr=np.where(dD<=rfD,0,-X*tr/_log(dD))'])

GRID_TOL={'price':1e-12,'delta':1e-10,'gamma':1e-9,'theta':1e-10,'vega':1e-10,'rho':1e-10}

class ModelTests(unittest.TestCase):
    """Prices and greeks at a fixed sigma on the Task 7b grid (sub-day and non-integer-day T): against py-reference and
    against QuantLib-Python at ALIGN_TOL (the py-reference/QuantLib tolerance of the quantlib-alignment check)."""
    @classmethod
    def setUpClass(cls):
        g=ALIGN_GRID;cls.side=np.array([x[0] for x in g],np.uint8)
        cls.S,cls.K,cls.T,cls.s=(np.array([x[i] for x in g]) for i in (1,2,3,4))
    def test_prices_and_greeks_match_py_reference_and_quantlib(self):
        for m in ('bsm','bjs','crr'):
            got=opt.price_and_greeks(m,self.side,self.S,self.K,self.T,R,Q,self.s,CASE)
            self.assertFalse(got['dead'].any())
            for i,(side,S,K,T,s) in enumerate(ALIGN_GRID):
                ref=reference.price_and_greeks(m,side,S,K,T,R,Q,s,CASE);lib=library.price_and_greeks(m,side,S,K,T,R,Q,s,CASE)
                for f in ALIGN_TOL:
                    v=float(got[f][i])
                    with self.subTest(model=m,row=(side,S,K,T,s),field=f):
                        self.assertLessEqual(abs(v-ref[f]),GRID_TOL[f]*max(1.0,abs(ref[f])))
                        self.assertLessEqual(abs(v-lib[f]),ALIGN_TOL[f]*max(1.0,abs(lib[f])))
                self.assertEqual(bool(got['rounding_band'][i]),ref['rounding_band'])
    def test_crr_lattice_points_match_quantlib_at_every_N(self):
        # Amendment D item 0(a) on py-optimized: CRR(100) American and CRR(N) European, N in {100, 200, 400, 800}.
        pts=FIX['oracle']['lattice'];self.assertGreater(len(pts),0)
        side=np.array([p['side'] for p in pts],np.uint8);S,K,T,s=(np.array([p[k] for p in pts]) for k in ('S','K','T','sigma'))
        for N,american in ((100,True),(100,False),(200,False),(400,False),(800,False)):
            v,dead=opt.crr_price(side,S,K,T,R,Q,s,N,american=american);self.assertFalse(dead.any())
            for i,p in enumerate(pts):
                lib=library.crr_price(p['side'],p['S'],p['K'],p['T'],R,Q,p['sigma'],N,CASE,american=american)
                with self.subTest(N=N,american=american,point=i):self.assertLessEqual(abs(float(v[i])-lib),ALIGN_TOL['price']*max(1.0,abs(lib)))
            if not american:
                for i,p in enumerate(pts):
                    with self.subTest(N=N,fixture=i):self.assertLessEqual(abs(float(v[i])-p['euro'][str(N)]),ALIGN_TOL['price']*max(1.0,abs(p['euro'][str(N)])))

class AgreementTests(unittest.TestCase):
    def check_rows(self,rws,params=CASE,against=None):
        got=opt.materialize(opt.run(prep_rows(rws),params));ref=(against or ref_run)(rws,params)
        return compare(rws,got,ref,params),got,ref
    def test_edge_rows_agree(self):
        self.assertTrue(FIX['oracle']['edge_rows'],'oracle fixtures must be generated (Task 9) before this test means anything')
        for e in FIX['oracle']['edge_rows']:
            p=CaseParams(**{**CASE.__dict__,**e.get('params',{})})
            v,got,ref=self.check_rows([tuple(e['row'])],p)
            with self.subTest(name=e['name']):
                self.assertTrue(v['eligible'],v['failures'])
                for m in ('bsm','bjs','crr'):self.assertEqual(got['models'][m]['status'],ref['models'][m]['status'])
                self.assertEqual(got['models'][e['model']]['status'][0],e['status'])
    def test_fixed_seed_chains_agree(self):
        for seed in (1,2,3):
            c=load_chain(generate(64,seed,CASE));v,got,ref=self.check_rows(rows(c,CASE))
            with self.subTest(seed=seed):
                self.assertTrue(v['eligible'],v['failures']);self.assertEqual(v['reduction'],'MATCH')
                for m in ('bsm','bjs','crr'):self.assertEqual(got['models'][m]['status'],ref['models'][m]['status'])
    def test_fixed_seed_chain_agrees_with_quantlib(self):
        c=load_chain(generate(64,4,CASE));v,_,_=self.check_rows(rows(c,CASE),against=library.run)
        self.assertTrue(v['eligible'],v['failures']);self.assertEqual(v['reduction'],'MATCH')
    def test_prepared_input_is_contiguous_float64(self):
        p=opt.prepare(load_chain(generate(8,1,CASE)),CASE)
        self.assertTrue(all(p[k].dtype==np.float64 and p[k].flags['C_CONTIGUOUS'] for k in ('S','K','T','bid','ask','r','q')));self.assertEqual(p['side'].dtype,np.uint8)
        self.assertEqual(p['n'],8)
    def test_unknown_side_zero_rows_and_one_row(self):
        rws=[(-1,100.0,100.0,0.5,1.0,1.1,R,Q)]
        got=opt.materialize(opt.run(prep_rows(rws),CASE))
        self.assertEqual({m:c['status'] for m,c in got['models'].items()},{m:['INVALID_INPUT'] for m in ('bsm','bjs','crr')})
        self.assertTrue(all(math.isnan(x) for c in got['models'].values() for f in ('iv','price','delta') for x in c[f]))
        empty=opt.materialize(opt.run(prep_rows([]),CASE));self.assertEqual(empty['n'],0)
        self.assertEqual(empty,core(ref_run([],CASE)))                         # G3.7: engine_evals is a py-reference column only
    def test_slices_concatenate_to_the_whole_run(self):
        p=opt.prepare(load_chain(generate(40,5,CASE)),CASE);whole=opt.materialize(opt.run(p,CASE))
        parts=[opt.run(opt.slice_prepared(p,a,b),CASE) for a,b in ((0,1),(1,17),(17,40))]
        joined=opt.materialize(opt.concat(parts))
        self.assertEqual(json.dumps(joined,sort_keys=True),json.dumps(whole,sort_keys=True))
        self.assertTrue(all(p2['S'].flags['C_CONTIGUOUS'] for p2 in [opt.slice_prepared(p,3,9)]))
    def test_materialized_result_has_the_reference_shape_and_digest_form(self):
        rws=rows(load_chain(generate(8,2,CASE)),CASE);got=opt.materialize(opt.run(prep_rows(rws),CASE));ref=ref_run(rws,CASE)
        self.assertEqual({m:sorted(c) for m,c in got['models'].items()},{m:sorted(core(ref)['models'][m]) for m in ref['models']})
        self.assertTrue(all(type(x) is int for c in got['models'].values() for x in c['flags']))
        self.assertEqual(len(reference.result_digest(got)),64)

class RuntimeRecordTests(unittest.TestCase):
    def test_simd_dispatch_is_recorded_and_labeled(self):
        rec=opt.runtime_record()
        self.assertEqual(rec['numpy'],json.load(open('/src/developer.lock.json'))['bench_python']['numpy'])
        self.assertTrue(rec['simd']['baseline']);self.assertIsInstance(rec['simd']['found'],list);self.assertIsInstance(rec['simd']['not_found'],list)
        self.assertIn('CPU-specific',rec['label'])
        self.assertEqual(set(rec['blas_threads_env']),{'OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'})
    def test_missing_private_cpu_module_gives_an_unknown_record(self):
        # review Minor 3: a NumPy without the private module records "unknown" (fail closed), never a crash or an empty list
        rec=opt.runtime_record(cpu_module='numpy._core._no_such_module')
        self.assertEqual(rec['simd']['status'],'unknown');self.assertIn('label',rec)
        self.assertEqual(opt.runtime_record()['simd']['status'],'recorded')

class SliceBoundTests(unittest.TestCase):
    def test_gather_and_scatter_refuse_a_bad_index(self):
        """Review Minor 4 (Amendment E): gather_prepared needs an ascending 1-D index inside the input; scatter needs the
        parts' indices to partition 0 .. n-1 exactly (no overlap, inside the range, one index value per row; with n = the
        sum of the part sizes these imply no gap)."""
        prep=opt.prepare(load_chain(generate(6,3,CASE)),CASE)
        g=opt.gather_prepared(prep,[0,2,5]);self.assertEqual((g['n'],g['index'].tolist()),(3,[0,2,5]));self.assertTrue(g['S'].flags['C_CONTIGUOUS'])
        self.assertEqual(opt.gather_prepared(prep,[])['n'],0)
        for bad in ([2,1],[0,0],[-1,2],[0,6],[[0,1]]):
            with self.subTest(index=bad),self.assertRaises(ValueError):opt.gather_prepared(prep,bad)
        part=lambda idx:dict(opt.run(opt.gather_prepared(prep,idx),CASE),index=np.asarray(idx,np.int64))
        whole=opt.run(prep,CASE);back=opt.scatter([part([1,3,5]),part([0,2,4])])
        self.assertTrue(all(back['models'][m][k].tobytes()==whole['models'][m][k].tobytes() for m in whole['models'] for k in whole['models'][m]))
        overlap=part([0,1,2]);overlap['index']=np.array([0,1,1],np.int64)
        outside=part([0,1,2]);outside['index']=np.array([0,1,9],np.int64)
        short=part([0,1,2]);short['index']=np.array([0,1],np.int64)
        for name,parts in (('overlap',[overlap,part([3,4,5])]),('outside',[outside,part([3,4,5])]),('size',[short,part([3,4,5])])):
            with self.subTest(case=name),self.assertRaises(ValueError):opt.scatter(parts)
    def test_slice_bounds_are_checked(self):
        p=opt.prepare(load_chain(generate(8,1,CASE)),CASE)
        self.assertEqual(opt.slice_prepared(p,0,8)['n'],8);self.assertEqual(opt.slice_prepared(p,8,8)['n'],0)
        for a,b in ((0,9),(-1,3),(5,4),(9,9)):
            with self.subTest(bounds=(a,b)),self.assertRaises(ValueError):opt.slice_prepared(p,a,b)

class CrossVariantDivisionTests(unittest.TestCase):
    """Task 11b review ruling (PL-T11B-DIV0-01): IEEE-754 division semantics in every variant. At T = 1e-24 the CRR lattice
    delta is 0/0 inside the solve; QuantLib ignores it (the NPV decides), so every variant gives ABOVE_MAX for CRR."""
    ROW=(0,100.0,100.0,1e-24,0.5,0.6,R,Q)
    def test_reference_optimized_and_library_give_equal_statuses(self):
        got=opt.materialize(opt.run(prep_rows([self.ROW]),CASE))
        for m in ('bsm','bjs','crr'):
            ref=reference.evaluate(self.ROW,m,CASE)[0];lib=library.evaluate(self.ROW,m,CASE)[0]
            with self.subTest(model=m):self.assertEqual((ref,got['models'][m]['status'][0]),(lib,lib))
        self.assertEqual(library.evaluate(self.ROW,'crr',CASE)[0],'ABOVE_MAX')

if __name__=='__main__':unittest.main()
