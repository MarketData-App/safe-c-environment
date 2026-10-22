import inspect, math, struct, sys, unittest
from pathlib import Path
from optionlab import cvectors
from optionlab import normal

def erf_branch(x):
    """The branch of normal.erf (QuantLib ErrorFunction, errorfunction.cpp:196-246) that x takes, with the sign where
    the branch result depends on it; the conditions copy normal.py:42-66."""
    if math.isnan(x):return 'nan'
    if not math.isfinite(x):return 'inf+' if x>0 else 'inf-'
    ax=math.fabs(x);sign='+' if x>=0 else '-'
    if ax<0.84375:
        if ax<3.7252902984e-09:return 'tiny' if ax<normal.DBL_MIN*16 else 'small'
        return 'pp-qq'
    if ax<1.25:return 'erx'+sign
    if ax>=6:return 'saturated'+sign
    return ('ra-sa' if ax<2.85714285714285 else 'rb-sb')+sign

ERF_BRANCHES={'nan','inf+','inf-','tiny','small','pp-qq','erx+','erx-','saturated+','saturated-','ra-sa+','ra-sa-','rb-sb+','rb-sb-'}

def erfc_interval(x):
    """The glibc (fdlibm s_erf.c) erfc interval of x, decided on the high word as the library does."""
    if math.isnan(x):return 'nan'
    hx=struct.unpack('<Q',struct.pack('<d',x))[0]>>32;ix=hx&0x7fffffff;neg=hx>>31==1
    if ix>=0x7ff00000:return 'inf-' if neg else 'inf+'
    if ix<0x3feb0000:                                 # |x| < 0.84375
        if ix<0x3c700000:return 'tiny'                # |x| < 2**-56
        return 'below-quarter' if neg or ix<0x3fd00000 else 'quarter-up'
    if ix<0x3ff40000:return 'erx-' if neg else 'erx+'  # |x| < 1.25
    if ix<0x403c0000:                                 # |x| < 28
        if ix<0x4006db6d:return 'ra-sa-' if neg else 'ra-sa+'     # |x| < 1/0.35
        if neg and ix>=0x40180000:return 'below-minus-6'
        return 'rb-sb-' if neg else 'rb-sb+'
    return 'large-' if neg else 'large+'

ERFC_INTERVALS={'nan','inf+','inf-','tiny','below-quarter','quarter-up','erx+','erx-','ra-sa+','ra-sa-','rb-sb+','rb-sb-',
                'below-minus-6','large+','large-'}

class CVectorTests(unittest.TestCase):
    def test_bits_and_literal(self):
        self.assertEqual(cvectors.bits(1.0),0x3ff0000000000000)
        self.assertEqual(cvectors.lit(-0.0),'UINT64_C(0x8000000000000000)')
        self.assertEqual(cvectors.bits(math.nan),0x7ff8000000000000)
    def test_render_is_a_pragma_once_header(self):
        text=cvectors.render('x',[('uint64_t','a'),('int','b')],[['UINT64_C(0x0000000000000000)','1']])
        self.assertIn('#pragma once',text);self.assertIn('#define PL_VEC_X_COUNT ((size_t)1)',text);self.assertNotIn('NAN',text)
        self.assertNotIn('#pragma once',cvectors.render('y',[('int','b')],[['1']],preamble=False))
    def test_normal_part_hits_every_erf_branch_and_both_cdf_and_pdf_paths(self):
        text,count=cvectors.PARTS['normal']()
        self.assertEqual(count,len(cvectors.NORMAL_X));self.assertIn('PL_VEC_NORMAL',text)
        self.assertEqual({erf_branch(x) for x in cvectors.NORMAL_X},ERF_BRANCHES)
        # Exact membership: each erf bound, its predecessor toward zero (one past) and both negatives are inputs.
        self.assertEqual(cvectors.ERF_BOUNDS,(normal.DBL_MIN*16,3.7252902984e-09,0.84375,1.25,2.85714285714285,6.0))
        self.assertEqual(cvectors.bits(2.85714285714285),0x4006db6db6db6da7)     # the QuantLib literal, not 1/0.35
        have={cvectors.bits(x) for x in cvectors.NORMAL_X}
        for b in cvectors.ERF_BOUNDS:
            below=math.nextafter(b,0.0)
            for x in (b,below,-b,-below):self.assertIn(cvectors.bits(x),have,x)
            self.assertNotEqual(erf_branch(b),erf_branch(below),b)     # b really separates two branches
        self.assertEqual(len(have),len(cvectors.NORMAL_X))
        band={cvectors.bits(x) for x in cvectors.ERF_RA_BAND_X}
        self.assertEqual(len(band),32);self.assertLessEqual(band,have)
        self.assertEqual(max(cvectors.ERF_RA_BAND_X),math.nextafter(2.857142857142857,0.0))
        # norm_cdf (normal.py:78-96): the erf form and the 26.2.12 series (result <= 1e-8) on both sides of the switch.
        series={0.5*(1.0+normal.erf(z*normal.M_SQRT_2))<=1e-8 for z in cvectors.NORMAL_X if not math.isnan(z)}
        self.assertEqual(series,{True,False})
        self.assertTrue(any(x==-5.6 for x in cvectors.NORMAL_X) and any(x==-5.7 for x in cvectors.NORMAL_X))
        # norm_pdf (normal.py:72-76): the cutoff exponent <= -690.0 on both sides (|x| = 37.1 and 37.2).
        cut={-(x*x)/normal.DENOMINATOR<=-690.0 for x in cvectors.NORMAL_X if not math.isnan(x)}
        self.assertEqual(cut,{True,False})
        self.assertTrue(-(37.1*37.1)/2.0>-690.0 and -(37.2*37.2)/2.0<=-690.0)
    def test_erfc_part_inputs_hit_every_glibc_erfc_interval(self):
        seen=set()
        for n,x in enumerate(cvectors.erfc_inputs()):
            seen.add(erfc_interval(x))
            if seen==ERFC_INTERVALS:break
        self.assertEqual(seen,ERFC_INTERVALS);self.assertLess(n,10000)
    def test_helpers_part_has_subnormal_inputs_and_results(self):
        from optionlab.models import _exp
        text,count=cvectors.PARTS['helpers']()
        self.assertEqual(count,len(cvectors.HELPER_X));self.assertIn('PL_VEC_HELPERS',text)
        sub=lambda v:v!=0.0 and math.fabs(v)<sys.float_info.min
        self.assertTrue(any(sub(x) and x>0 for x in cvectors.HELPER_X) and any(sub(x) and x<0 for x in cvectors.HELPER_X))
        self.assertTrue(any(sub(_exp(x)) for x in cvectors.HELPER_X))
        self.assertTrue(any(_exp(x)==0.0 for x in cvectors.HELPER_X) and any(_exp(x)==math.inf for x in cvectors.HELPER_X))
    def test_fdlibm_bound_mutant_is_equivalent_on_the_whole_band(self):
        bad=mutant_erf(*FDLIBM_BOUND)
        for x in cvectors.ERF_RA_BAND_X:
            self.assertNotEqual(erf_branch(x)[:5],'ra-sa');self.assertEqual(cvectors.bits(bad(x)),cvectors.bits(normal.erf(x)),x)
    def test_corpus_files_are_bytes(self):
        files=cvectors.corpus_files()
        self.assertIsInstance(files,dict)
        self.assertTrue(all(isinstance(k,str) and isinstance(v,bytes) for k,v in files.items()))

# Mutants of normal.erf at each bound (I1). '<' to '<=' (or '>=' to '>') moves only x = +-bound to the other branch,
# so such a mutant is detectable exactly when the two branches give other bits at +-bound; else no input detects it (an
# equivalent mutant). The fdlibm literal 2.857142857142857 in place of 2.85714285714285 moves ERF_RA_BAND_X. A detected
# mutant gives other erf bits on some NORMAL_X value; test_normal.c compares pl_erf with those bits, so the same change
# in C fails it.
DETECTED={'saturated-gt':('ax>=6','ax>6')}
# The fdlibm literal moves all 32 doubles of ERF_RA_BAND_X from RB/SB to RA/SA; both pieces give equal bits on every one of
# them, so this mutant is equivalent too (test_fdlibm_bound_mutant_is_equivalent_on_the_whole_band).
FDLIBM_BOUND=('ax<2.85714285714285','ax<2.857142857142857')
# Equivalent at the bound: the branches on both sides give equal bits at +-bound. DBL_MIN*16: EFX8 is 8*EFX exactly and
# the scalings by 8 and 0.125 are exact, so the tiny branches agree for every normal x. The others: the fdlibm pieces agree
# to the last bit at the bound (shown by the test below on the vectors' own bound inputs).
EQUIVALENT={'tiny-le':('ax<DBL_MIN*16','ax<=DBL_MIN*16',normal.DBL_MIN*16),
            'small-le':('ax<3.7252902984e-09','ax<=3.7252902984e-09',3.7252902984e-09),
            'pp-qq-le':('ax<0.84375','ax<=0.84375',0.84375),'erx-le':('ax<1.25','ax<=1.25',1.25),
            'ra-sa-le':('ax<2.85714285714285','ax<=2.85714285714285',2.85714285714285)}

def mutant_erf(old,new):
    src=inspect.getsource(normal.erf)
    if src.count(old)!=1:raise AssertionError('mutation site not unique: '+old)
    space=dict(vars(normal));exec(compile(src.replace(old,new),'<mutant>','exec'),space)
    return space['erf']

def _detects(name,old,new):
    def test(self):
        bad=mutant_erf(old,new)
        self.assertTrue(any(cvectors.bits(bad(x))!=cvectors.bits(normal.erf(x)) for x in cvectors.NORMAL_X if not math.isnan(x)),name)
    return test

def _equivalent(name,old,new,b):
    def test(self):
        bad=mutant_erf(old,new)
        self.assertEqual(erf_branch(b)!=erf_branch(math.nextafter(b,0.0)),True)
        for x in (b,-b):
            self.assertIn(cvectors.bits(x),{cvectors.bits(y) for y in cvectors.NORMAL_X})
            self.assertEqual(cvectors.bits(bad(x)),cvectors.bits(normal.erf(x)),(name,x))
    return test

for _name,(_old,_new) in DETECTED.items():
    setattr(CVectorTests,'test_vectors_detect_erf_mutant_'+_name.replace('-','_'),_detects(_name,_old,_new))
for _name,(_old,_new,_b) in EQUIVALENT.items():
    setattr(CVectorTests,'test_erf_mutant_is_equivalent_at_bound_'+_name.replace('-','_'),_equivalent(_name,_old,_new,_b))

# ---- part black (Task 8) ----
EPS=sys.float_info.epsilon

def _raises(fn):
    try:fn();return False
    except ZeroDivisionError:return True

def init_branch(K,F,s):
    """The branch of Black.__init__ (models.py:113-128) that (strike, forward, stdDev) takes."""
    from optionlab.models import close
    if s>=EPS:return 'strike-zero' if close(K,0.0) else 'log'
    if close(F,K):return 'flat-close'
    return 'flat-above' if F>K else 'flat-below'

def flat_branch(b):
    """The result of Black._flat (models.py:132-135) that a zero-volatility greek returns: (position, alpha >= 0)."""
    from optionlab.models import close
    pos='close' if close(b.forward,b.strike) else 'above' if b.forward>b.strike else 'below'
    return pos,b.alpha>=0

FLAT_BRANCHES={(p,a) for p in ('close','above','below') for a in (True,False)}
INIT_BRANCHES={'strike-zero','log','flat-close','flat-above','flat-below'}

def engine_blacks():
    """(row, Black) of every part-black row where mapped_inputs returns and the forward is finite (models.bsm_engine)."""
    from optionlab.models import mapped_inputs, Black
    out=[]
    for row in cvectors.black_inputs():
        side,S,K,T,r,q,s=row
        if _raises(lambda:mapped_inputs(T,r,q,s)):continue
        d_r,d_q,v=mapped_inputs(T,r,q,s)
        if d_r==0.0:continue
        out.append((row,Black(side,K,S*d_q/d_r,math.sqrt(v),d_r)))
    return out

def mutant_black(old,new):
    """models.Black with every occurrence of `old` replaced by `new`."""
    from optionlab import models
    src=inspect.getsource(models.Black)
    if old not in src:raise AssertionError('mutation site not found: '+old)
    space=dict(vars(models));exec(compile(src.replace(old,new),'<mutant>','exec'),space)
    return space['Black']

def calc_bits(cls):
    return [tuple(cvectors.bits(v) for v in cvectors.black_calc_values(cls,*row).values()) for row in cvectors.black_calc_inputs()]

class BlackVectorTests(unittest.TestCase):
    def test_black_part_has_both_tables_with_plain_literals(self):
        self.assertEqual(cvectors.lit_plain(math.nan),'0x7ff8000000000000U');self.assertEqual(cvectors.lit_plain(-0.0),'0x8000000000000000U')
        text,count=cvectors.PARTS['black']()
        self.assertEqual(count,len(cvectors.black_inputs())+len(cvectors.black_calc_inputs()))
        self.assertIn('PL_VEC_BLACK_COUNT ((size_t)%d)'%len(cvectors.black_inputs()),text)
        self.assertIn('PL_VEC_BLACK_CALC_COUNT ((size_t)%d)'%len(cvectors.black_calc_inputs()),text)
        self.assertNotIn('UINT64_C',text);self.assertEqual(text.count('#pragma once'),1)
    def test_exp_bounds_are_exact(self):
        from optionlab.models import _exp
        zero_at,inf_at=cvectors.exp_bounds()
        self.assertEqual(_exp(zero_at),0.0);self.assertEqual(_exp(math.nextafter(zero_at,0.0)),5e-324)
        self.assertEqual(_exp(inf_at),math.inf);self.assertLess(_exp(math.nextafter(inf_at,0.0)),math.inf)
    def test_black_rows_hold_each_raise_bound_and_its_one_past_value_as_r_and_as_q(self):
        from optionlab.models import mapped_inputs
        zero_at,inf_at=cvectors.exp_bounds();rows=cvectors.black_inputs()
        expect=((zero_at,True),(math.nextafter(zero_at,0.0),False),(inf_at,False),(math.nextafter(inf_at,0.0),False))
        for x,raises in expect:
            for k in (4,5):
                hit=[r for r in rows if r[3]==1.0 and cvectors.bits(r[k])==cvectors.bits(x)]
                self.assertTrue(hit,(x,k))
                for r in hit:self.assertEqual(_raises(lambda:mapped_inputs(*r[3:])),raises,(x,k))
        # The brief's raising rows (r = -800, q = -800, r = -inf) and the non-raising r = inf row stay.
        self.assertTrue(_raises(lambda:mapped_inputs(1.0,-800.0,0.012,0.2)) and _raises(lambda:mapped_inputs(1.0,0.04,-800.0,0.2)))
        self.assertTrue(_raises(lambda:mapped_inputs(1.0,-math.inf,0.012,0.2)))
        self.assertFalse(_raises(lambda:mapped_inputs(1.0,math.inf,0.012,0.2)))
        # D of the one-past and inf rows: inf (1.0/5e-324), 0.0 and a subnormal value.
        self.assertEqual(mapped_inputs(1.0,math.nextafter(zero_at,0.0),0.0,0.2)[0],math.inf)
        self.assertEqual(mapped_inputs(1.0,inf_at,0.0,0.2)[0],0.0)
        self.assertTrue(0.0<mapped_inputs(1.0,math.nextafter(inf_at,0.0),0.0,0.2)[0]<sys.float_info.min)
    def test_black_rows_have_std_dev_at_and_next_to_ql_epsilon(self):
        stds={cvectors.bits(b.stdDev) for _,b in engine_blacks()}
        for s in (EPS,math.nextafter(EPS,0.0),math.nextafter(EPS,1.0)):self.assertIn(cvectors.bits(s),stds,s)
    def test_black_rows_reach_every_init_and_flat_branch(self):
        blacks=engine_blacks()
        self.assertEqual({init_branch(b.strike,b.forward,b.stdDev) for _,b in blacks},INIT_BRANCHES)
        self.assertEqual({flat_branch(b) for _,b in blacks if b.stdDev<=EPS},FLAT_BRANCHES)
    def test_black_rows_reach_both_outcomes_of_each_helper(self):
        from optionlab.models import discount, zero_rate, forward_rate, mapped_inputs
        rows=[r for r in cvectors.black_inputs() if not _raises(lambda:mapped_inputs(*r[3:]))]
        for fn in (lambda a:zero_rate(a,0.0),lambda a:forward_rate(a,0.0,0.0001)):
            self.assertEqual({_raises(lambda:fn(r[4]*r[3])) for r in rows},{True,False})
        # implied_rate: compound == 1.0 (rate*T*1e-4 too small to move exp) and != 1.0.
        self.assertEqual({1.0/discount(r[4]*r[3],0.0001)==1.0 for r in rows if math.isfinite(r[4])},{True,False})
        self.assertFalse(any(_raises(lambda:discount(r[4]*r[3],1.0)) for r in rows))
    def test_black_calc_rows_reach_every_branch_and_bound(self):
        from optionlab.models import Black, close
        rows=cvectors.black_calc_inputs()
        blacks=[Black(*row[:5]) for row in rows]
        self.assertEqual({init_branch(b.strike,b.forward,b.stdDev) for b in blacks},INIT_BRANCHES)
        self.assertEqual({flat_branch(b) for b in blacks if b.stdDev<=EPS},FLAT_BRANCHES)
        stds={cvectors.bits(row[3]) for row in rows}
        for s in (0.0,EPS,math.nextafter(EPS,0.0),math.nextafter(EPS,1.0)):self.assertIn(cvectors.bits(s),stds)
        self.assertEqual({close(row[6],0.0) for row in rows},{True,False})
        self.assertEqual({close(row[1],0.0) for row in rows},{True,False})
        self.assertTrue(close(1e-29,0.0) and not close(1e-28,0.0) and close(100.0,100.0+4e-13) and not close(100.0,100.0+1e-11))
    def test_vectors_detect_black_bound_mutants(self):
        from optionlab.models import Black
        good=calc_bits(Black)
        for old,new in BLACK_DETECTED:
            self.assertNotEqual(calc_bits(mutant_black(old,new)),good,(old,new))
    def test_black_forward_bound_mutants_are_equivalent(self):
        from optionlab.models import Black
        good=calc_bits(Black)
        for old,new in BLACK_EQUIVALENT:
            self.assertEqual(calc_bits(mutant_black(old,new)),good,(old,new))

# Bound mutants of models.Black (Task 8; the Task 7 lesson). Detected: stdDev == QL_EPSILON moves Black.__init__ to the flat
# branch ('>'), or the greeks to the full formulas ('<'); alpha == 0.0 (a zero-volatility put with the forward above the
# strike) moves _flat to the put result ('>'). Equivalent: forward == strike is close(forward, strike), which the code
# tests first, so '>=' for '>' at the forward/strike test changes no result for any input (NaN compares false both ways).
BLACK_DETECTED=(('if stdDev>=QL_EPSILON:','if stdDev>QL_EPSILON:'),('self.stdDev<=QL_EPSILON','self.stdDev<QL_EPSILON'),
                ('self.alpha>=0','self.alpha>0'))
BLACK_EQUIVALENT=(('elif forward>strike:','elif forward>=strike:'),('if self.forward>self.strike:','if self.forward>=self.strike:'))

# ---- part bjs (Task 9) ----
def bjs_branch(row):
    """The branch of models.bjs_engine and models._american_call that a row takes; the conditions copy models.py:345-346 and
    274-275: 'defect' (mapped_inputs raises), 'ql-error', 'european', 'immediate' (S >= I), 'european-q' (q_I > 12.5) or
    'formula'."""
    try:spot,X,rfD,dD,v=cvectors.call_inputs(*row)
    except ZeroDivisionError:return 'defect'
    if dD>1.0 and rfD>dD:return 'ql-error'
    if dD>=1.0 and dD>=rfD:return 'european'
    st=cvectors.american_state(spot,X,rfD,dD,v)
    if spot>=st['I']:return 'immediate'
    if st['q']>12.5:return 'european-q'
    return 'formula'

def bjs_bits(m,rows):
    """Status and bits of every row through models.bjs_result of m, then the bits of every direct _immediate row."""
    out=[]
    for row in rows:
        status,p,e=cvectors.bjs_outcome(m,row)
        out.append((status,cvectors.bits(p))+tuple(cvectors.bits(e[f]) for f in cvectors.BLACK_FIELDS))
    out+=[tuple(cvectors.bits(m._immediate(S,X)[f]) for f in cvectors.IMMEDIATE_FIELDS) for S,X in cvectors.IMMEDIATE_SX]
    return out

def bjs_mutant_rows():
    return cvectors.bjs_inputs()[-len(cvectors.bjs_edge_rows())-6:]

class BjsVectorTests(unittest.TestCase):
    def test_bjs_part_has_three_tables_with_plain_literals(self):
        text,count=cvectors.PARTS['bjs']()
        self.assertEqual(text.count('#pragma once'),1)
        n=len(cvectors.bjs_inputs());self.assertEqual(count,n+len(cvectors.PHI_GRID)+len(cvectors.IMMEDIATE_SX))
        self.assertIn('PL_VEC_BJS_COUNT ((size_t)%d)'%n,text);self.assertIn('PL_VEC_BJS_PHI_COUNT ((size_t)72)',text)
        self.assertIn('PL_VEC_BJS_IMMEDIATE_COUNT ((size_t)%d)'%len(cvectors.IMMEDIATE_SX),text);self.assertNotIn('UINT64_C',text)
    def test_bjs_rows_start_with_the_brief_rows(self):
        rows=cvectors.bjs_inputs();base=[r for r in cvectors.black_inputs() if r[6]>=0.01]
        self.assertEqual(rows[:len(base)],base);self.assertEqual(len(base),447)
        self.assertEqual(rows[len(base)+5],(1,100.0,100.0,2.0,0.04,0.012,0.0199))
    def test_bjs_statuses(self):
        from optionlab import models
        rows=cvectors.bjs_inputs();st=[cvectors.bjs_outcome(models,r)[0] for r in rows]
        self.assertEqual(set(st),{0,1,2})
        for row,want in (((0,100.0,100.0,1.0,-800.0,0.012,0.2),2),((0,100.0,100.0,1.0,-math.inf,0.012,0.2),2),
                         ((0,100.0,100.0,1.0,-0.05,-0.03,0.2),1),((0,100.0,100.0,1.0,math.inf,0.012,0.2),0)):
            self.assertIn(row,rows);self.assertEqual(cvectors.bjs_outcome(models,row)[0],want,row)
        # the status follows the branch: 2 exactly at 'defect', 1 exactly at 'ql-error'
        for row,s in zip(rows,st):self.assertEqual(s,{'defect':2,'ql-error':1}.get(bjs_branch(row),0),row)
    def test_bjs_bounds_are_exact_adjacent_pairs(self):
        from optionlab.models import discount
        b=cvectors.bjs_bounds()
        for k in ('dq_gt_one','dq_lt_one','dr_gt_dq','dd_gt_rfd','q_trigger','immediate','eu_fallback'):
            a,c=b[k];self.assertEqual(c,math.nextafter(a,math.inf),k)
        a,c=b['dq_gt_one'];self.assertEqual((discount(-a,1.0),discount(-c,1.0)>1.0),(1.0,True))
        a,c=b['dq_lt_one'];self.assertEqual((discount(a,1.0),discount(c,1.0)<1.0),(1.0,True))
        a,c=b['dr_gt_dq'];d=discount(-0.03,1.0);self.assertTrue(discount(-a,1.0)<=d<discount(-c,1.0))
        a,c=b['dd_gt_rfd'];d=discount(0.04,1.0);self.assertTrue(discount(a,1.0)>d>=discount(c,1.0))
    def test_bjs_rows_hold_each_engine_bound_with_its_outcome(self):
        # The engine conditions (models.py:345-346) at each bound pair: 'american' is any branch of _american_call.
        b=cvectors.bjs_bounds();rows=set(cvectors.bjs_inputs())
        cls=lambda r:'american' if bjs_branch(r) in ('formula','immediate','european-q') else bjs_branch(r)
        a,c=b['dq_gt_one'];a2,c2=b['dq_lt_one'];a3,c3=b['dr_gt_dq']
        expect=[((0,S,100.0,1.0,-0.5,q,0.2),w) for S in (100.0,50.0) for q,w in ((-a,'american'),(-c,'ql-error'))]
        expect+=[((0,100.0,100.0,1.0,0.04,q,0.2),'european') for q in (-a,-c)]
        expect+=[((0,100.0,100.0,1.0,r,0.0,0.2),w) for r,w in ((0.0,'european'),(-a,'european'),(-c,'american'))]
        expect+=[((0,100.0,100.0,1.0,0.04,a2,0.2),'european'),((0,100.0,100.0,1.0,0.04,c2,0.2),'american')]
        expect+=[((0,100.0,100.0,1.0,r,-0.03,0.2),w) for r,w in ((-0.03,'european'),(-a3,'european'),(-c3,'ql-error'))]
        for row,want in expect:
            side,S,K,T,r,q,s=row;put=(1,K,S,T,q,r,s)
            for x in (row,put):
                self.assertIn(x,rows,x);self.assertEqual(cls(x),want,x)
    def test_bjs_rows_hold_the_trigger_bounds(self):
        # S >= I (models.py:274) at S = I and one double below; q_I > 12.5 (models.py:275) at its adjacent S pair.
        b=cvectors.bjs_bounds();rows=set(cvectors.bjs_inputs());I=b['I'];qa,qc=b['q_trigger']
        expect=[((0,I,100.0,1.0,0.04,0.08,0.2),'immediate'),((0,math.nextafter(I,0.0),100.0,1.0,0.04,0.08,0.2),'formula'),
                ((0,qa,100.0,1.0,0.04,0.08,0.2),'european-q'),((0,qc,100.0,1.0,0.04,0.08,0.2),'formula')]
        for row,want in expect:
            side,S,K,T,r,q,s=row;put=(1,K,S,T,q,r,s)
            for x in (row,put):
                self.assertIn(x,rows,x);self.assertEqual(bjs_branch(x),want,x)
        # S == I below X with a zero European value (the row that detects '>' for '>=' at S >= I)
        s,I=b['I_low'];self.assertTrue(0.0<I<100.0)
        for S,want in ((I,'immediate'),(math.nextafter(I,0.0),None)):
            row=(0,S,100.0,1.0,0.012,0.04,s);put=(1,100.0,S,1.0,0.04,0.012,s)
            for x in (row,put):
                self.assertIn(x,rows,x)
                if want:self.assertEqual(bjs_branch(x),want,x)
        self.assertEqual(cvectors.american_fallback(*cvectors.call_inputs(0,I,100.0,1.0,0.012,0.04,s))[1],0.0)
    def test_bjs_rows_hold_the_exact_equality_points(self):
        # approver finding I1: q_I == 12.5 exactly with the formula above the European value, and the engine value equal to
        # (S - X)(1 + 10 eps) exactly; each row and its put form
        b=cvectors.bjs_bounds();rows=set(cvectors.bjs_inputs())
        rq=(0,b['q_equal'],100.0,1.0,0.3,0.01,0.3);ri=(0,b['immediate_equal'],100.0,1.0,0.04,0.08,0.2)
        for row in (rq,ri):
            side,S,K,T,r,q,s=row
            for x in (row,(1,K,S,T,q,r,s)):self.assertIn(x,rows,x)
        st=cvectors.american_state(*cvectors.call_inputs(*rq));self.assertEqual(st['q'],12.5)
        am,eu=cvectors.american_fallback(*cvectors.call_inputs(*rq));self.assertGreater(am,eu)
        value,bound=cvectors.engine_pre_immediate(ri);self.assertEqual(value,bound)
    def test_bjs_rows_reach_both_outcomes_of_each_inner_condition(self):
        from optionlab.models import mapped_inputs
        b=cvectors.bjs_bounds();rows=cvectors.bjs_inputs()
        formula=[r for r in rows if bjs_branch(r)=='formula'];american=[r for r in rows if bjs_branch(r) in ('formula','immediate','european-q')]
        self.assertEqual({bjs_branch(r) for r in rows},{'defect','ql-error','european','immediate','european-q','formula'})
        state=lambda r:cvectors.american_state(*cvectors.call_inputs(*r))
        # B0 = X when bT == rT (models.py:270), and B0Dq = 0.0, B0Dr = 0 when dD <= rfD (models.py:290, 307), in the greeks branch
        self.assertEqual({state(r)['bT']==state(r)['rT'] for r in formula},{True,False})
        self.assertEqual({cvectors.call_inputs(*r)[3]<=cvectors.call_inputs(*r)[2] for r in formula},{True,False})
        a,c=b['dd_gt_rfd']
        for q,le in ((0.04,True),(a,False),(c,True)):
            row=(0,100.0,100.0,1.0,0.04,q,0.2);self.assertIn(row,rows);self.assertEqual(bjs_branch(row),'formula')
            _,_,rfD,dD,_=cvectors.call_inputs(*row);self.assertEqual(dD<=rfD,le,q)
        # the European fallback (models.py:339) and the engine's immediate-exercise test (models.py:349): both outcomes, and the
        # exact adjacent pairs are rows
        fb=lambda r:(lambda am,eu:am<eu)(*cvectors.american_fallback(*cvectors.call_inputs(*r)))
        self.assertEqual({fb(r) for r in american},{True,False})
        fa,fc=[(1,100.0,100.0,1.0,0.04,0.012,s) for s in b['eu_fallback']]
        self.assertIn(fa,rows);self.assertIn(fc,rows);self.assertNotEqual(fb(fa),fb(fc))
        im=lambda r:(lambda v,bound:v<bound)(*cvectors.engine_pre_immediate(r))
        ok=[r for r in rows if bjs_branch(r) not in ('defect','ql-error')]
        self.assertEqual({im(r) for r in ok},{True,False})
        x,y=b['immediate'];rx=(0,x,100.0,1.0,0.04,0.08,0.2);ry=(0,y,100.0,1.0,0.04,0.08,0.2)
        self.assertIn(rx,rows);self.assertIn(ry,rows);self.assertNotEqual(im(rx),im(ry))
    def test_bjs_phi_grid_and_immediate_rows(self):
        self.assertEqual(len(cvectors.PHI_GRID),72)
        from optionlab.models import _immediate
        self.assertEqual({_immediate(S,X)['delta'] for S,X in cvectors.IMMEDIATE_SX},{0.0,1.0})
        self.assertEqual(_immediate(100.0,100.0)['delta'],1.0);self.assertEqual(_immediate(math.nextafter(100.0,0.0),100.0)['delta'],0.0)

# Bound mutants of the Bjerksund-Stensland engine (Task 9; the Task 7 lesson): each replaces one comparison of models.py at
# a branch bound. Detected: each changes a status or a value bit on the edge rows or the direct _immediate rows, so the same
# change in C fails test_bjs.c. '>' for '>=' at S >= I and '<=' for '<' at the European fallback are detected only by the
# I_low rows (S == I < X with a European value of exactly 0.0): at S == I > X every phi term is 0.0, the formula value is
# exactly I - X and the engine's immediate-exercise test gives the immediate results either way. '>=' for '>' at q_I > 12.5
# and '<=' for '<' at the immediate-exercise test are detected only by the exact-equality rows (q_equal, immediate_equal).
BJS_DETECTED={'dq_gt_one':('if dividendDiscount>1.0 and riskFreeDiscount>dividendDiscount:','if dividendDiscount>=1.0 and riskFreeDiscount>dividendDiscount:'),
              'dr_gt_dq':('and riskFreeDiscount>dividendDiscount:raise','and riskFreeDiscount>=dividendDiscount:raise'),
              'dq_ge_one':('if dividendDiscount>=1.0 and dividendDiscount>=riskFreeDiscount:','if dividendDiscount>1.0 and dividendDiscount>=riskFreeDiscount:'),
              'dq_ge_dr':('and dividendDiscount>=riskFreeDiscount:res=','and dividendDiscount>riskFreeDiscount:res='),
              's_ge_i':('    if S>=I:results=_immediate(S,X)','    if S>I:results=_immediate(S,X)'),
              'b0dq':('B0Dq=0.0 if dD<=rfD else','B0Dq=0.0 if dD<rfD else'),
              'b0dr':('B0Dr=0 if dD<=rfD else','B0Dr=0 if dD<rfD else'),
              's_ge_x':('delta=1.0 if S>=X else 0.0','delta=1.0 if S>X else 0.0'),
              'eu_fallback':("if results['value']<europeanResults['value']:","if results['value']<=europeanResults['value']:"),
              'q_trigger':('    elif q>12.5:','    elif q>=12.5:'),
              'immediate':("if res['value']<(spot-strike)*(1+10*QL_EPSILON):","if res['value']<=(spot-strike)*(1+10*QL_EPSILON):")}
_BJS_GOOD=[]
def _bjs_good(rows):
    from optionlab import models
    if not _BJS_GOOD:_BJS_GOOD.append(bjs_bits(models,rows))
    return _BJS_GOOD[0]

def _bjs_mutant_test(old,new):
    def test(self):
        rows=bjs_mutant_rows();self.assertNotEqual(bjs_bits(cvectors.models_variant(old,new),rows),_bjs_good(rows),(old,new))
    return test

for _name,(_old,_new) in BJS_DETECTED.items():
    setattr(BjsVectorTests,'test_vectors_detect_bjs_mutant_'+_name,_bjs_mutant_test(_old,_new))

# ---- part crr (Task 10) ----
def crr_bits(m):
    """Status, defect and bits of every edge row of table crr (both exercise styles), every crr_engine row and every crr_lo
    row through m (optionlab.models or a variant)."""
    out=[]
    for row in cvectors.crr_edge_rows():
        for american in (1,0):
            status,defect,tree,e=cvectors.crr_outcome(m,row,american)
            out.append((status,defect)+tuple(cvectors.bits(x) for x in (tree[0],tree[1],tree[2])+tuple(tree[3]))
                       +tuple(cvectors.bits(e[f]) for f in cvectors.CRR_FIELDS))
    for row in cvectors.crr_engine_inputs():
        status,e=cvectors.crr_engine_outcome(m,row);out.append((status,)+tuple(cvectors.bits(e[f]) for f in cvectors.CRR_FIELDS))
    for row in cvectors.crr_lo_inputs():
        v,ok=cvectors.crr_lo_outcome(m,row);out.append((cvectors.bits(v),ok))
    for row in cvectors.crr_tree_inputs():
        d,vals=cvectors.crr_tree_outcome(m,row);out.append((d,)+tuple(cvectors.bits(x) for x in vals))
    return out

_CRR_GOOD=[]
def _crr_good():
    from optionlab import models
    if not _CRR_GOOD:_CRR_GOOD.append(crr_bits(models))
    return _CRR_GOOD[0]

class CrrVectorTests(unittest.TestCase):
    def test_crr_part_has_three_tables_with_plain_literals(self):
        text,count=cvectors.PARTS['crr']()
        self.assertEqual(text.count('#pragma once'),1);self.assertNotIn('UINT64_C',text)
        n=2*len(cvectors.crr_inputs());lo=len(cvectors.crr_lo_inputs());eng=len(cvectors.crr_engine_inputs())
        tree=len(cvectors.crr_tree_inputs());self.assertEqual(count,n+lo+eng+tree)
        for name,k in (('CRR',n),('CRR_LO',lo),('CRR_ENGINE',eng),('CRR_TREE',tree)):
            self.assertIn('PL_VEC_%s_COUNT ((size_t)%d)'%(name,k),text)
    def test_crr_tree_rows_hold_every_step_outcome(self):
        from optionlab import models
        out={row[4]:cvectors.crr_tree_outcome(models,row) for row in cvectors.crr_tree_inputs() if row[0]==1.0}
        self.assertEqual({n:d for n,(d,_) in out.items()},{-1:0,0:1,1:0,2:0,3:0,100:0})
        self.assertTrue(math.isnan(out[-1][1][0]));self.assertTrue(all(math.isnan(x) for x in out[0][1]))
    def test_crr_rows_start_with_the_brief_rows(self):
        rows=cvectors.crr_inputs();base=[r for r in cvectors.black_inputs() if r[6]>=0.01]
        self.assertEqual(rows[:len(base)],base);self.assertEqual(len(base),447)
        self.assertEqual(rows[len(base)+5],(0,100.0,100.0,1.0,-720.0,-720.0,0.3))
        self.assertEqual(rows[len(base)+6:],cvectors.crr_edge_rows())
        grid=[(m,side,T,r,q) for m in range(3) for side in (0,1) for T in cvectors.CRR_LO_TS
              for (r,q) in cvectors.RATES+((math.nan,0.012),(math.inf,0.012))]
        self.assertEqual(len(grid),180);self.assertEqual(cvectors.crr_lo_inputs()[:180],grid)
    def test_crr_statuses_and_brief_outcomes(self):
        from optionlab import models
        rows=cvectors.crr_inputs();seen=set()
        for row in rows:
            status,defect,_,_=cvectors.crr_outcome(models,row,1);seen.add((status,defect))
        self.assertEqual(seen,{(0,0),(1,0),(0,1)})
        for row,want in (((0,100.0,100.0,60.0,0.04,0.012,4.99),(1,0)),((1,100.0,100.0,1/365/24,0.04,0.012,0.5),(0,0)),
                         ((0,100.0,100.0,20.0,0.04,0.012,0.01),(1,0)),((1,100.0,90.0,1.0,0.1,-0.02,0.3),(0,0)),
                         ((0,100.0,100.0,1.0,709.77,709.79,0.3),(0,1)),((0,100.0,100.0,1.0,-720.0,-720.0,0.3),(0,1)),
                         ((0,100.0,100.0,-1.0,0.04,0.012,0.2),(0,1)),((0,100.0,100.0,-5e-324,0.04,0.012,0.2),(0,1)),
                         ((0,100.0,100.0,-0.0,0.04,0.012,0.2),(1,0)),((0,100.0,100.0,math.inf,0.04,0.012,0.2),(0,1)),
                         ((0,100.0,100.0,1.0,math.inf,0.012,0.2),(0,1)),((1,100.0,100.0,1.0,0.04,math.nan,0.2),(1,0))):
            self.assertIn(row,rows,row);self.assertEqual(cvectors.crr_outcome(models,row,1)[:2],want,row)
    def test_crr_raise_bounds_are_exact_adjacent_pairs_held_as_r_and_as_q(self):
        b=cvectors.crr_bounds();rows=set(cvectors.crr_inputs())
        for key in ('r_hi','r_lo','q_hi','q_lo'):
            a,c=b[key];self.assertEqual(c,math.nextafter(a,math.copysign(math.inf,a)),key);self.assertGreater(abs(a),709.0)
        for key in ('r_hi','r_lo'):
            a,c=b[key];self.assertEqual((cvectors.crr_tree_raises(1.0,a,0.012,0.3),cvectors.crr_tree_raises(1.0,c,0.012,0.3)),(False,True))
            for x in (a,c):
                for y in (0.012,a):self.assertIn((0,100.0,100.0,1.0,x,y,0.3),rows)
        for key in ('q_hi','q_lo'):
            a,c=b[key];self.assertEqual((cvectors.crr_tree_raises(1.0,0.04,a,0.3),cvectors.crr_tree_raises(1.0,0.04,c,0.3)),(False,True))
            for x in (a,c):
                for y in (0.04,a):self.assertIn((1,100.0,100.0,1.0,y,x,0.3),rows)
        # the zero-carry row on the no-raise side reaches the engine (status 0)
        from optionlab import models
        for key in ('r_hi','r_lo'):
            a,_=b[key];self.assertEqual(cvectors.crr_outcome(models,(0,100.0,100.0,1.0,a,a,0.3),1)[:2],(0,0),key)
    def test_crr_probability_bounds_are_exact(self):
        from optionlab import models
        b=cvectors.crr_bounds();rows=set(cvectors.crr_inputs())
        a,c=b['pu_ge_zero'];self.assertEqual(c,math.nextafter(a,math.inf))
        self.assertEqual(cvectors.crr_pu(60.0,0.04,0.012,a),0.0);self.assertLess(cvectors.crr_pu(60.0,0.04,0.012,c),0.0)
        a2,c2=b['pu_le_one'];self.assertEqual(c2,math.nextafter(a2,math.inf))
        self.assertGreater(cvectors.crr_pu(20.0,0.04,0.012,a2),1.0);self.assertEqual(cvectors.crr_pu(20.0,0.04,0.012,c2),1.0)
        for side in (0,1):
            for T,s,want in ((60.0,a,0),(60.0,c,1),(20.0,a2,1),(20.0,c2,0)):
                row=(side,100.0,100.0,T,0.04,0.012,s);self.assertIn(row,rows)
                for am in (1,0):self.assertEqual(cvectors.crr_outcome(models,row,am)[:2],(want,0),row)
        # direct engine rows: pu == 1.0 and pu == 0.0 exactly, and each adjacent pair
        e1,f1=b['eng_pu_le_one'];e0,f0=b['eng_pu_ge_zero']
        self.assertEqual((f1,f0),(math.nextafter(e1,1.0),math.nextafter(e0,1.0)))
        self.assertEqual((cvectors.crr_engine_pu(0.1,0.1),cvectors.crr_engine_pu(0.1,-0.1)),(1.0,0.0))
        self.assertLessEqual(cvectors.crr_engine_pu(0.1,e1),1.0);self.assertGreater(cvectors.crr_engine_pu(0.1,f1),1.0)
        self.assertGreaterEqual(cvectors.crr_engine_pu(0.1,-e0),0.0);self.assertLess(cvectors.crr_engine_pu(0.1,-f0),0.0)
        eng={(r[0],r[4],r[7],r[8]):cvectors.crr_engine_outcome(models,r)[0] for r in cvectors.crr_engine_inputs() if r[9]==0.999}
        for d,want in ((0.1,0),(e1,0),(f1,1),(-0.1,0),(-e0,0),(-f0,1)):
            for n in (3,100):
                for side in (0,1):self.assertEqual(eng[(side,n,0.1,d)],want,(d,n,side))
    def test_crr_engine_rows_reach_every_status_and_nan_path(self):
        from optionlab import models
        rows=cvectors.crr_engine_inputs();st=[cvectors.crr_engine_outcome(models,r)[0] for r in rows]
        self.assertEqual(set(st),{0,1,2})
        k=12*len(cvectors.CRR_ENGINE_STEPS)
        # the step sweep: ModelDefect below 2 steps; TypeError at 2 steps with greeks only
        for r,s in zip(rows[:k],st[:k]):
            n,g=r[4],r[3];self.assertEqual(s,1 if n<2 else (2 if n==2 and g else 0),r)
        self.assertEqual({r[4] for r in rows[:k]},set(cvectors.CRR_ENGINE_STEPS))
        # dx == 0.0 or NaN: pu is NaN or +-inf (QuantLib error); dx < 0.0 and the NaN-path rows price (status 0)
        self.assertEqual({s for r,s in zip(rows[k:],st[k:]) if r[7]==0.0 or r[7]!=r[7]},{1})
        self.assertEqual(len([r for r in rows[k:] if r[7]==0.0 or r[7]!=r[7]]),16)
        self.assertEqual({s for r,s in zip(rows[k:],st[k:]) if r[7]==-0.1 or r[9]!=0.999 or r[5]!=100.0 or r[6]!=100.0},{0})
        # K NaN: the payoff is NaN; the initial maximum gives 0.0 and the node maximum keeps the rolled-back value
        kn=[r for r in rows if r[6]!=r[6]];self.assertEqual(len(kn),4)
        for r in kn:self.assertEqual(cvectors.crr_engine_outcome(models,r)[1]['value'],0.0)
        dn=[r for r in rows if r[9]==math.inf];self.assertTrue(all(math.isnan(cvectors.crr_engine_outcome(models,r)[1]['value']) for r in dn))
        s0=[r for r in rows if r[5]==0.0];self.assertTrue(all(math.isnan(cvectors.crr_engine_outcome(models,r)[1]['delta']) for r in s0))
    def test_crr_lo_rows_hold_the_domain_bounds_and_the_zero_carry(self):
        from optionlab import models
        from optionlab.params import CASE
        b=cvectors.crr_bounds();rows=set(cvectors.crr_lo_inputs())
        pairs=[(0,rq,ac) for rq,ac in zip(cvectors.RATES,b['g_lo'])]+[(1,rq,ac) for rq,ac in zip(cvectors.CRR_HI_RATES,b['g_hi'])]
        flips=set()
        for k,(r,q),(a,c) in pairs:
            self.assertEqual(c,math.nextafter(a,math.inf))
            self.assertEqual(cvectors.crr_domain_g(a,r,q)[k],0.0);self.assertLess(cvectors.crr_domain_g(c,r,q)[k],0.0)
            self.assertFalse(models.crr_domain_ok(c,r,q,CASE))
            if models.crr_domain_ok(a,r,q,CASE):flips.add((k,r,q))
            for m in range(3):
                for side in (0,1):
                    for T in (a,c):self.assertIn((m,side,T,r,q),rows)
        # every g_lo pair flips crr_domain_ok; the g_hi pairs flip it where g(sigma_lo) >= 0.0 at T near 16 (small carry)
        self.assertEqual({x for x in flips if x[0]==0},{(0,r,q) for r,q in cvectors.RATES})
        self.assertEqual({x for x in flips if x[0]==1},{(1,0.04,0.04),(1,0.03,0.02)})
        # b == 0 (r == q) at T = 2000: sigma_trig at b = 0 would exceed sigma_carry, so '<=' for '<' changes sigma_lo(BjS)
        q1=math.nextafter(0.04,1.0)
        self.assertEqual(models.sigma_lo('bjs',0,2000.0,0.04,0.04,CASE),math.sqrt(2.0*(0.0+CASE.h_r)/CASE.kappa_cap))
        self.assertGreater(1.001*(0.0+CASE.h_r)*math.sqrt(2000.0)/2.0,math.sqrt(2.0*(0.0+CASE.h_r)/CASE.kappa_cap))
        self.assertGreater(models.sigma_lo('bjs',0,2000.0,0.04,q1,CASE),models.sigma_lo('bjs',1,2000.0,0.04,q1,CASE))
        for m in range(3):
            for side in (0,1):
                for r,q in ((0.04,0.04),(0.04,q1)):self.assertIn((m,side,2000.0,r,q),rows)
        self.assertEqual({cvectors.crr_lo_outcome(models,r)[1] for r in rows},{0,1})

# Bound mutants of the CRR path (Task 10; the Task 7 and Task 9 lessons): each replaces one comparison of models.py at a branch
# bound, or the argument order of one maximum (the tie and NaN rule). Every one changes a status or a value bit of the vectors,
# so the same change in C fails test_crr.c. The mutation runs in memory only (cvectors.models_variant).
CRR_DETECTED={'steps':("    if steps<2:raise ModelDefect","    if steps<=2:raise ModelDefect"),
              'pu_le_one':('    if not pu<=1.0:','    if not pu<1.0:'),
              'pu_ge_zero':('    if not pu>=0.0:','    if not pu>0.0:'),
              'node_max':('new=[_max(new[j],payoff(growth[2*j-i]))','new=[_max(payoff(growth[2*j-i]),new[j])'),
              'initial_max':('values=[_max(0.0,payoff(growth[2*j-steps]))','values=[_max(payoff(growth[2*j-steps]),0.0)'),
              'b_lt_zero':('trig=1.001*(abs(b)+hr)*math.sqrt(T)/2.0 if b<0.0 else 0.0','trig=1.001*(abs(b)+hr)*math.sqrt(T)/2.0 if b<=0.0 else 0.0'),
              'g_lo':("    return g(sigma_lo('crr',0,T,r,q,params))>=0.0 and","    return g(sigma_lo('crr',0,T,r,q,params))>0.0 and"),
              'g_hi':('and g(params.sigma_hi+params.h_sigma)>=0.0','and g(params.sigma_hi+params.h_sigma)>0.0')}

def _crr_mutant_test(old,new):
    def test(self):
        self.assertNotEqual(crr_bits(cvectors.models_variant(old,new)),_crr_good(),(old,new))
    return test

for _name,(_old,_new) in CRR_DETECTED.items():
    setattr(CrrVectorTests,'test_vectors_detect_crr_mutant_'+_name,_crr_mutant_test(_old,_new))

# ---- part solver (Task 11 part A) ----
def solver_rows():
    """(c, lo, hi, guess, accuracy, max_evaluations) of every row of tables solver and solver_edge, in table order."""
    from optionlab.solver import ACCURACY
    return [(c,lo,hi,(lo+hi)/2.0,ACCURACY,m) for c,lo,hi in cvectors.CUBICS for m in (200,4)]+cvectors.solver_edge_rows()

def solver_bits(brent):
    out=[]
    for row in solver_rows():
        st,n,root,fl,fh=cvectors.brent_outcome(brent,*row);out.append((st,n,cvectors.bits(root),cvectors.bits(fl),cvectors.bits(fh)))
    return out

_SOLVER_GOOD=[]
def _solver_good():
    from optionlab.solver import brent
    if not _SOLVER_GOOD:_SOLVER_GOOD.append(solver_bits(brent))
    return _SOLVER_GOOD[0]

def edge_outcome(c,lo,hi,guess,acc,me):
    from optionlab.solver import brent
    return cvectors.brent_outcome(brent,c,lo,hi,guess,acc,me)

class SolverVectorTests(unittest.TestCase):
    def test_solver_part_has_two_tables_with_plain_literals(self):
        text,count=cvectors.PARTS['solver']()
        self.assertEqual(text.count('#pragma once'),1);self.assertNotIn('UINT64_C',text)
        self.assertEqual(count,16+len(cvectors.solver_edge_rows()))
        self.assertIn('PL_VEC_SOLVER_COUNT ((size_t)16)',text)
        self.assertIn('PL_VEC_SOLVER_EDGE_COUNT ((size_t)%d)'%len(cvectors.solver_edge_rows()),text)
    def test_solver_brief_rows_and_statuses(self):
        from optionlab.solver import brent, N_MAX
        seen=set()
        for (c0,c1,c2,c3),lo,hi in cvectors.CUBICS:
            for m in (200,4):
                st,root,fl,fh,n=brent(lambda s:((c0*s+c1)*s+c2)*s+c3,lo,hi,(lo+hi)/2.0,max_evaluations=m)
                got=cvectors.brent_outcome(brent,(c0,c1,c2,c3),lo,hi,(lo+hi)/2.0,1e-10,m)
                self.assertEqual(cvectors.bits(got[2]),cvectors.bits(root));self.assertEqual(got[:2],(cvectors.SOLVER_STATUS.index(st),n))
                self.assertLessEqual(n,N_MAX);seen.add(st)
        self.assertEqual(seen,{'OK','BELOW_MIN','ABOVE_MAX','NOT_CONVERGED'})
        self.assertEqual({edge_outcome(*r)[0] for r in cvectors.solver_edge_rows()},{0,1,2,3,5})
    def test_solver_edge_rows_hold_the_argument_bounds(self):
        lin=(0.0,0.0,1.0,-1.5);up=math.nextafter(1.0,2.0);dn=math.nextafter(2.0,1.0)
        rows=cvectors.solver_edge_rows()
        for row,want in (((lin,1.0,2.0,1.25,0.0,200),(5,0)),((lin,1.0,2.0,1.25,-0.0,200),(5,0)),((lin,1.0,2.0,1.25,math.nan,200),(5,0)),
                         ((lin,1.0,2.0,1.25,5e-324,200),(0,5)),((lin,2.0,2.0,2.0,1e-10,200),(5,0)),((lin,dn,2.0,2.0,1e-10,200),(1,2)),
                         ((lin,3.0,2.0,2.5,1e-10,200),(5,0)),((lin,1.0,2.0,1.0,1e-10,200),(5,2)),((lin,1.0,2.0,up,1e-10,200),(0,5)),
                         ((lin,1.0,2.0,2.0,1e-10,200),(5,2)),((lin,1.0,2.0,dn,1e-10,200),(0,5)),((lin,1.0,2.0,math.nan,1e-10,200),(5,2))):
            self.assertTrue(any(repr(row)==repr(r) for r in rows),row);self.assertEqual(edge_outcome(*row)[:2],want,row)
        # accuracy below QL_EPSILON solves as QL_EPSILON itself (max(accuracy, QL_EPSILON)); the unclamped mutant differs
        a=edge_outcome((-2.0,2.0,-6.0,0.0),-2.0,4.0,1.0,1e-20,200);b=edge_outcome((-2.0,2.0,-6.0,0.0),-2.0,4.0,1.0,EPS,200)
        self.assertEqual((a[:2],cvectors.bits(a[2])),(b[:2],cvectors.bits(b[2])));self.assertEqual(a[0],0)
    def test_solver_edge_rows_hold_the_close_and_bracket_bounds(self):
        tol2=(42*EPS)*(42*EPS);dn=math.nextafter(tol2,0.0)
        for c3,want in ((0.0,(0,1)),(-0.0,(0,1)),(dn,(0,1)),(tol2,(1,2)),(-dn,(0,1)),(-tol2,(2,2))):
            got=edge_outcome((0.0,0.0,0.0,c3),1.0,2.0,1.5,1e-10,200);self.assertEqual(got[:2],want,c3)
            if want[0]==0:self.assertEqual(got[2],1.0)
        # root on an endpoint: f(lo) == 0.0 (1 call), f(hi) == 0.0 (2 calls), both (lo wins)
        self.assertEqual(edge_outcome((0.0,0.0,1.0,-1.0),1.0,2.0,1.5,1e-10,200)[:3],(0,1,1.0))
        self.assertEqual(edge_outcome((0.0,0.0,1.0,-2.0),1.0,2.0,1.5,1e-10,200)[:3],(0,2,2.0))
        self.assertEqual(edge_outcome((0.0,1.0,-3.0,2.0),1.0,2.0,1.5,1e-10,200)[:3],(0,1,1.0))
        self.assertEqual(edge_outcome((0.0,0.0,tol2,-2.0*tol2),1.0,2.0,1.5,1e-10,200)[:3],(0,2,2.0))
        # NaN ends: the product is NaN, not < 0.0, and fxMin > 0.0 is false: ABOVE_MAX
        self.assertEqual(edge_outcome((0.0,0.0,0.0,math.nan),1.0,2.0,1.5,1e-10,200)[:2],(2,2))
        self.assertEqual(edge_outcome((0.0,0.0,math.inf,-1.5),1.0,2.0,1.5,1e-10,200)[:2],(1,2))
        # f(guess) == 0.0 exactly: the solve stops at the first loop pass with the guess
        self.assertEqual(edge_outcome((0.0,0.0,1.0,-2.5),1.0,4.0,2.5,1e-10,200)[:3],(0,4,2.5))
    def test_solver_edge_rows_hold_the_evaluation_limit(self):
        from optionlab.solver import N_MAX, MAX_EVALUATIONS
        c=(1.0,0.0,0.0,-0.125);g=(0.0001+5.0)/2.0
        self.assertEqual(g,2.50005)
        for m,want in ((-1,(3,3)),(0,(3,3)),(2,(3,3)),(3,(3,4)),(13,(3,14)),(14,(0,15)),(15,(0,15))):
            self.assertEqual(edge_outcome(c,0.0001,5.0,g,1e-10,m)[:2],want,m)
        lo,hi=-2.0**63,2.0**62
        for m,want in ((199,(3,200)),(MAX_EVALUATIONS,(0,N_MAX)),(201,(0,N_MAX))):
            self.assertEqual(edge_outcome(c,lo,hi,(lo+hi)/2.0,1e-10,m)[:2],want,m)
        lo,hi=-1.25*2.0**63,1.25*2.0**64
        for m,want in ((MAX_EVALUATIONS,(3,N_MAX)),(201,(0,202)),(202,(0,202))):
            self.assertEqual(edge_outcome(c,lo,hi,(lo+hi)/2.0,1e-10,m)[:2],want,m)
    def test_solver_edge_rows_hold_the_iteration_ties(self):
        # |fxMax| == |froot| at the first pass: f(1) = -4.0, f(3) = 4.0
        f=cvectors.cubic_fun((0.0,1.0,0.0,-5.0));self.assertEqual((f(1.0),f(3.0)),(-4.0,4.0))
        # |xMid| == xAcc1 at the first pass: root 0.0, xMax 1e-10, xMid = 5e-11 = 0.5*1e-10
        self.assertEqual((1e-10-0.0)/2.0,2.0*EPS*0.0+0.5*1e-10)
        f=cvectors.cubic_fun((0.0,0.0,1.0,-2.5e-11));self.assertLess(f(0.0),0.0);self.assertGreater(math.fabs(f(1e-10)),math.fabs(f(0.0)))
        self.assertEqual(edge_outcome((0.0,0.0,1.0,-2.5e-11),-1.0,1e-10,0.0,1e-10,200)[:3],(0,4,0.0))
        # p == 0.0: f(hi) is -inf and becomes fxMin (f(guess) has the sign of f(lo)), so s = froot/fxMin is -0.0
        f=cvectors.cubic_fun((0.5,-1e200,-1e308,-1.0))
        self.assertEqual((f(-2.0),f(4.0)),(math.inf,-math.inf));self.assertTrue(0.0<f(-1.25)<math.inf)
        self.assertEqual(math.copysign(1.0,f(-1.25)/f(4.0)),-1.0);self.assertEqual(f(-1.25)/f(4.0),0.0)
    def test_solver_edge_rows_reach_e_below_xacc1(self):
        # the last row reaches |e| < xAcc1 with |fxMin| > |froot|: forcing the interpolation there changes the count
        row=cvectors.solver_edge_rows()[-1];v=cvectors.solver_variant('if math.fabs(e)>=xAcc1 and','if True and')
        self.assertEqual(edge_outcome(*row)[:2],(0,32));self.assertEqual(cvectors.brent_outcome(v.brent,*row)[:2],(0,31))

# Bound mutants of solver.py (Task 11 part A; the Task 7 and Task 9 lessons). DETECTED: each changes a status, a count or a
# value bit of the vectors, so the same change in C fails test_solver.c. EQUIVALENT: no input can tell them apart:
# - acc_max_order: a tie gives the same value; a NaN accuracy has raised at :23.
# - bracket (fxMin*fxMax <= 0.0) and below (fxMin >= 0.0): close() has returned for |f| < tol^2 = (42 QL_EPSILON)^2
#   (f == 0.0 included), and a product of two values with |f| >= tol^2 is at least tol^4 (about 7.6e-57), never 0.0.
# - side (froot*fxMin <= 0): the product is 0.0 only for froot == 0.0 (|froot| >= tol^2 and |fxMin| >= tol^2 otherwise);
#   then the first pass returns the guess through close(froot, 0.0) on either side, with the same calls.
# - same_pos and same_neg (>= for >): froot == 0.0 returns at the same pass with the same root and calls; fxMax is a value
#   that close() has already refused, so it is never 0.0.
# - interp_f (|fxMin| >= |froot|): at a tie s = froot/fxMin is +1 (q becomes 0.0, so 2p < min(.) fails) or -1 after a
#   reset (secant through xMin == xMax: 2p == min2 == 4|xMid|), so the step is the bisection of the original.
#   Searched: 17,819 ties in 200,000 random solves, none changed a result.
# - min (min1 <= min2): a tie gives the same value; a NaN min1 is false either way.
# - min_order (min2 if min2 < min1 else min1): differs only for a NaN min1 with 2p < min2, which needs a finite p with an
#   infinite or NaN q. Searched: 1,518 NaN min1 cases in 200,000 random solves, none changed a result.
# - step (|d| >= xAcc1): an accepted step has sign(d) == sign(xMid) (3 xMid q > 2p >= 0), so +-xAcc1 equals d at a
#   tie; a bisection step |xMid| == xAcc1 has converged at :55.
# - sign (b > 0.0 in _sign): xMid == 0.0 has converged at :55 before the step.
SOLVER_DETECTED={'accuracy_gt':('if not accuracy>0.0:','if not accuracy>=0.0:'),
                 'accuracy_max':('accuracy=max(accuracy,QL_EPSILON)','accuracy=accuracy'),
                 'range':('if not xMin<xMax:','if not xMin<=xMax:'),
                 'guess_lo':('if not guess>xMin','if not guess>=xMin'),
                 'guess_hi':('or not guess<xMax','or not guess<=xMax'),
                 'loop':('while evaluationNumber<=max_evaluations:','while evaluationNumber<max_evaluations:'),
                 'swap':('if math.fabs(fxMax)<math.fabs(froot):','if math.fabs(fxMax)<=math.fabs(froot):'),
                 'stop':('if math.fabs(xMid)<=xAcc1','if math.fabs(xMid)<xAcc1'),
                 'interp_e':('if math.fabs(e)>=xAcc1','if math.fabs(e)>xAcc1'),
                 'p_sign':('if p>0.0:q=-q','if p>=0.0:q=-q'),
                 'accept':('if 2.0*p<(min1','if 2.0*p<=(min1')}
SOLVER_EQUIVALENT={'acc_max_order':('accuracy=max(accuracy,QL_EPSILON)','accuracy=max(QL_EPSILON,accuracy)'),
                   'bracket':('if not fxMin*fxMax<0.0:','if not fxMin*fxMax<=0.0:'),
                   'below':("'BELOW_MIN' if fxMin>0.0","'BELOW_MIN' if fxMin>=0.0"),
                   'side':('if froot*fxMin<0:','if froot*fxMin<=0:'),
                   'same_pos':('(froot>0.0 and fxMax>0.0)','(froot>=0.0 and fxMax>=0.0)'),
                   'same_neg':('(froot<0.0 and fxMax<0.0)','(froot<=0.0 and fxMax<=0.0)'),
                   'interp_f':('math.fabs(fxMin)>math.fabs(froot):','math.fabs(fxMin)>=math.fabs(froot):'),
                   'min':('(min1 if min1<min2 else min2)','(min1 if min1<=min2 else min2)'),
                   'min_order':('(min1 if min1<min2 else min2)','(min2 if min2<min1 else min1)'),
                   'step':('if math.fabs(d)>xAcc1:','if math.fabs(d)>=xAcc1:'),
                   'sign':('return math.fabs(a) if b>=0.0','return math.fabs(a) if b>0.0')}

def _solver_mutant_test(old,new,detected):
    def test(self):
        got=solver_bits(cvectors.solver_variant(old,new).brent)
        if detected:self.assertNotEqual(got,_solver_good(),(old,new))
        else:self.assertEqual(got,_solver_good(),(old,new))
    return test

for _name,(_old,_new) in SOLVER_DETECTED.items():
    setattr(SolverVectorTests,'test_vectors_detect_solver_mutant_'+_name,_solver_mutant_test(_old,_new,True))
for _name,(_old,_new) in SOLVER_EQUIVALENT.items():
    setattr(SolverVectorTests,'test_solver_mutant_is_equivalent_'+_name,_solver_mutant_test(_old,_new,False))

# ---- Row evaluation (Task 11 part B) ----
MODELS3=('bsm','bjs','crr')

def eval_bits(evaluate,pairs):
    """(status, flags, defect, evals, value bits) of each (row, params) pair and model through `evaluate` (the module's or a
    variant's), as part evaluate records it."""
    from optionlab.contract import STATUSES
    out=[]
    for row,prm in pairs:
        for name in MODELS3:
            try:st,vals,flags,ev=evaluate(row,name,prm);out.append((STATUSES.index(st),flags,0,ev)+tuple(cvectors.bits(v) for v in vals))
            except (ZeroDivisionError,ValueError):out.append((0,0,1,0))
    return out

_BOUND=[]
def bound_pairs():
    if not _BOUND:
        from optionlab.params import CASE
        _BOUND.append(cvectors.evaluate_bound_rows()+[(r,CASE) for r in cvectors.EDGE_ROWS+cvectors.RAISE_ROWS])
    return _BOUND[0]

_EVAL_GOOD=[]
def _eval_good():
    from optionlab.reference import evaluate
    if not _EVAL_GOOD:_EVAL_GOOD.append(eval_bits(evaluate,bound_pairs()))
    return _EVAL_GOOD[0]

def outcome(row,name,prm=None):
    from optionlab.params import CASE
    return cvectors.evaluate_outcome(row,name,prm or CASE)

class EvaluateVectorTests(unittest.TestCase):
    def test_evaluate_rows_hold_every_row_set(self):
        rows=cvectors.evaluate_rows();keys={tuple(cvectors.bits(x) for x in r) for r,_ in rows}
        self.assertGreater(len(rows),116)
        for r in cvectors.EDGE_ROWS+cvectors.RAISE_ROWS+cvectors.census_raising_rows()+cvectors.BRENT_STOP_ROWS:
            self.assertIn(tuple(cvectors.bits(x) for x in r),keys)
        self.assertGreater(len(cvectors.census_raising_rows()),8)
    def test_raise_rows_raise_where_the_audit_table_says(self):
        # r = +-inf and q = -inf: BjS and CRR stop first at sigma_lo >= sigma_hi (MODEL_DOMAIN); rows 5-7 are CRR-only
        # (Task 10a: raising_models covers EVALUATE_MODELS; the three-model expectation is unchanged, and the G4.8 trap row
        # RAISE_ROWS[5] raises for crr only, baw included)
        self.assertEqual([[m for m in cvectors.raising_models(r) if m not in ('baw','alo')] for r in cvectors.RAISE_ROWS],
                         [['bsm','bjs','crr'],['bsm','bjs','crr'],['bsm'],['bsm'],['bsm'],['crr'],['crr'],['crr']])
        # Task 10b: alo raises on rows 0, 3 and 4 in alo_equation.read_back (a zero exponential: sigma_lo reads the rates back)
        # and on row 1 in reference.tau_v; on row 2 sigma_lo(ALO) is inf (MODEL_DOMAIN); rows 5-7 read back infinite rates,
        # which the pre check refuses (MODEL_DOMAIN)
        self.assertEqual([int('alo' in cvectors.raising_models(r)) for r in cvectors.RAISE_ROWS],[1,1,0,1,1,0,0,0])
        self.assertEqual(cvectors.raising_models(cvectors.RAISE_ROWS[5]),['crr'])
    def test_brent_stop_rows_stop_with_model_domain_at_the_listed_call(self):
        for row,ev in zip(cvectors.BRENT_STOP_ROWS,cvectors.BRENT_STOP_EVALS):
            st,flags,defect,got,_=outcome(row,'bjs')
            self.assertEqual((st,defect,got),(4,0,ev),row)
    def test_status_bound_rows(self):
        # S 0.0, -0.0, 5e-324, -5e-324; K the same; S NaN; T -0.0, 5e-324, -5e-324, inf, NaN; bid -0.0, 5e-324, -5e-324;
        # ask NaN, inf; ask one double below bid, equal, one above (BSM; 5e-324 values are priced)
        self.assertEqual([outcome(r,'bsm')[0] for r in cvectors.status_bound_rows()],
                         [0,0,6,0,0,0,5,0,0,1,6,1,0,0,2,8,2,0,0,3,8,8])
    def test_boundary_band_rows_are_exact(self):
        rows=cvectors.boundary_band_rows()
        for i,name in enumerate(MODELS3):
            lo=[outcome(r,name)[1]&2 for r in rows[6*i:6*i+3]];hi=[outcome(r,name)[1]&2 for r in rows[6*i+3:6*i+6]]
            self.assertEqual((lo,hi),([0,2,2],[2,2,0]),name)
            self.assertEqual([outcome(r,name)[0] for r in rows[6*i:6*i+6]],[5,5,5,6,6,6],name)
    def test_intrinsic_rows(self):
        for name in MODELS3:
            got=[outcome(r,name)[:2] for r in cvectors.intrinsic_rows()]
            self.assertEqual(got,[(5,1),(5,1),(5,0),(5,0),(5,0),(5,0)],name)
    def test_sigma_hi_rows(self):
        from optionlab.models import sigma_lo
        from optionlab.params import CASE
        pairs=cvectors.sigma_hi_rows();(a,_),(b,_)=pairs[:2]
        self.assertEqual(sigma_lo('bjs',0,1.0,b[6],0.0,CASE),5.0)
        self.assertNotEqual(outcome(a,'bjs')[0],4);self.assertEqual(outcome(b,'bjs')[0],4)
        got=[outcome(r,'bjs',prm)[:3] for r,prm in pairs[2:]]
        self.assertEqual([g[0] for g in got[:2]],[4,4]);self.assertEqual(got[2][2],1);self.assertEqual(got[3][0],8)
    def test_greek_step_rows(self):
        rows=cvectors.greek_step_rows();got=[outcome(r,'crr') for r in rows]
        self.assertEqual(got[0][0],4);self.assertGreater(got[0][3],1)
        self.assertEqual([g[2] for g in got[1:4]],[1,0,1]);self.assertEqual(got[2][0],4)
        self.assertEqual(got[4][0],8)
        st,flags,_,_,_=outcome(rows[5],'bsm');self.assertEqual((st,flags&4),(8,4))
    def test_flat_vega_rows_hold_the_exact_bound(self):
        rows=cvectors.flat_vega_rows();got=[outcome(r,'bsm') for r in rows]
        self.assertEqual([(g[0],g[1]&4) for g in got],[(8,4),(8,0),(8,0)])
        self.assertEqual(got[2][4][5]*100.0,1e-12)
    def test_vega_bump_rows_hold_the_exact_bound(self):
        from optionlab.models import sigma_lo
        from optionlab.params import CASE
        rows=cvectors.vega_bump_rows();got=[outcome(r,'crr') for r in rows];lo=sigma_lo('crr',0,rows[2][3],0.04,0.012,CASE)
        self.assertEqual([g[0] for g in got],[8,8,8])
        self.assertLess(got[0][4][0]-CASE.h_sigma,lo);self.assertEqual(got[2][4][0]-CASE.h_sigma,lo)
    def test_checker_and_tau_tables(self):
        chk=[cvectors.checker_outcome(t,v) for t,v in cvectors.checker_rows()]
        self.assertEqual({c for c in chk},{(0,0),(0,1),(1,0)})
        tau=[cvectors.tau_outcome(*r) for r in cvectors.tau_rows()]
        self.assertEqual(sum(d for d,_ in tau),5);self.assertTrue(any(d==0 and v!=v for d,v in tau))
    def test_greeks_rows_reach_every_status(self):
        got=[cvectors.greeks_outcome(*x) for x in cvectors.greeks_rows()]
        self.assertEqual({g[0] for g in got},{0,1,2})
    def test_census_documents_hold_only_audit_locations(self):
        import json
        doc=json.loads(cvectors.census_documents()[0])
        self.assertEqual((doc['rows'],doc['unexpected'],doc['trap_ok']),(1000,[],True))
        self.assertIn('crr',doc['trap_row_models']);self.assertNotIn('bsm',doc['trap_row_models'])
        # Task CA: every anchor resolves once, and census.json lists the resolved audit locations
        self.assertEqual((doc['anchor_errors'],len(doc['expected'])),([],len(cvectors.CENSUS_ANCHORS)))

class CensusGateTests(unittest.TestCase):
    """Controller ruling N9 (fix round 1, I1): c-census compares the tracked rows file in every state."""
    def run_gate(self,make):
        import tempfile
        from optionlab import checks
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/'out';out.mkdir();tracked=Path(d)/'census_rows.json';make(tracked)
            return checks.census_gate(out,tracked)
    def test_absent_tracked_file_fails(self):
        r=self.run_gate(lambda p:None);self.assertEqual((r['status'],r['counts']['tracked_rows_differ']),('FAIL',1))
    def test_directory_in_place_of_the_tracked_file_fails(self):
        r=self.run_gate(lambda p:p.mkdir());self.assertEqual(r['status'],'FAIL')
    def test_different_tracked_file_fails(self):
        r=self.run_gate(lambda p:p.write_text('[]',encoding='ascii'));self.assertEqual(r['status'],'FAIL')
    def test_unreadable_tracked_file_fails(self):
        # Task 11 part B review M5: an OSError on the read (PermissionError here, through a patched read) and bytes that
        # are not ASCII (UnicodeDecodeError) both FAIL; the regenerated rows are never compared with a partial read
        from unittest import mock
        text=cvectors.census_documents()[1]
        def denied(self,*a,**k):raise PermissionError('denied')
        with mock.patch.object(Path,'read_text',denied):
            r=self.run_gate(lambda p:p.write_bytes(text.encode('ascii')))
        self.assertEqual((r['status'],r['counts']['tracked_rows_differ']),('FAIL',1))
        r=self.run_gate(lambda p:p.write_bytes(b'\xff\xfe'+text.encode('ascii')))
        self.assertEqual((r['status'],r['counts']['tracked_rows_differ']),('FAIL',1))
    def test_equal_tracked_file_passes(self):
        text=cvectors.census_documents()[1]
        r=self.run_gate(lambda p:p.write_text(text,encoding='ascii'));self.assertEqual(r['status'],'PASS')
    def test_tracked_rows_are_distinct(self):
        rows=cvectors.census_raising_rows();keys={tuple(cvectors.bits(x) for x in r) for r in rows}
        self.assertEqual(len(keys),len(rows))
    def test_generate_check_always_passes_and_writes_both_files(self):
        import tempfile
        from optionlab import checks
        with tempfile.TemporaryDirectory() as d:
            r=checks.c_census_generate(Path(d),[])
            self.assertEqual((r['status'],sorted(p.name for p in Path(d).iterdir())),('PASS',['census-rows.json','census.json']))

class CensusAnchorTests(unittest.TestCase):
    """Task CA (HANDOFF-P2 Next steps 4): the census audit table names each raise point by a source-text anchor (file,
    enclosing function, exact stripped line text, optional context lines below it), resolved to its line at check time."""
    PKG=Path(cvectors.__file__).resolve().parent
    def write(self,d,name,text):(Path(d)/name).write_text(text,encoding='utf-8')
    def resolve(self,d,*anchors):return cvectors.resolve_anchors(anchors,d)
    def shifted_copy(self,d,edits):
        """A copy of optionlab and of the case file that params reads, under d, with one comment line inserted above each
        line named by its stripped text in edits ((file, text) pairs); returns the python directory of the copy."""
        import shutil
        py=Path(d)/'project'/'python';shutil.copytree(self.PKG,py/'optionlab',ignore=shutil.ignore_patterns('__pycache__'))
        case=self.PKG.parents[1]/'cases'/'option-chain-greeks.json';(Path(d)/'project'/'cases').mkdir()
        shutil.copyfile(case,Path(d)/'project'/'cases'/case.name)
        for name,text in edits:
            p=py/'optionlab'/name;lines=p.read_text(encoding='utf-8').splitlines(keepends=True)
            at=[i for i,l in enumerate(lines) if l.strip()==text];self.assertEqual(len(at),1,text)
            lines.insert(at[0],'# census shift (Task CA test)\n');p.write_text(''.join(lines),encoding='utf-8')
        return py
    def test_a_line_shift_above_raise_points_keeps_the_census_passing(self):
        # RED before Task CA: the line pins name models.py:128 and reference.py:51, so the shifted raises are unexpected
        import json, os, subprocess, tempfile
        with tempfile.TemporaryDirectory() as d:
            py=self.shifted_copy(d,[('models.py','def discount(rate,t):return 1.0/_exp(rate*t)'),
                                    ('reference.py','D_r=discount(r1,1.0);D_q=discount(q1,1.0);F=(S*D_q)/D_r')])
            out=Path(d)/'out';out.mkdir()
            code=("import json,sys\nfrom pathlib import Path\nfrom optionlab import checks, cvectors\n"
                  "r=checks.census_gate(Path(sys.argv[1]),Path(cvectors.__file__).with_name(cvectors.CENSUS_ROWS_FILE))\n"
                  "doc=json.loads(Path(sys.argv[1],'census.json').read_text(encoding='ascii'))\n"
                  "print(json.dumps({'status':r['status'],'at':sorted({x['at'] for x in doc['raises']}),'unexpected':doc['unexpected'],"
                  "'anchor_errors':doc.get('anchor_errors'),'file':cvectors.__file__}))\n")
            env=dict(os.environ,PYTHONPATH=str(py))
            p=subprocess.run([sys.executable,'-c',code,str(out)],cwd=str(py),env=env,capture_output=True,text=True,timeout=900)
            self.assertEqual(p.returncode,0,'the census subprocess failed')
            got=json.loads(p.stdout.strip().splitlines()[-1])
            self.assertTrue(got['file'].startswith(str(py)))
            self.assertIn('models.py:129',got['at']);self.assertIn('reference.py:52',got['at'])     # the shift took effect
            self.assertEqual((got['unexpected'],got['anchor_errors'],got['status']),([],[],'PASS'))
    def test_an_anchor_resolves_to_its_current_line(self):
        import tempfile
        a=('ZeroDivisionError','m.py','f',('return 1.0/x',))
        with tempfile.TemporaryDirectory() as d:
            self.write(d,'m.py','def f(x):\n    y=1\n    return 1.0/x\n')
            self.assertEqual(self.resolve(d,a),(frozenset({('ZeroDivisionError','m.py:3')}),[]))
            self.write(d,'m.py','\n# shift\ndef f(x):\n\n    y=1\n    return 1.0/x\n')
            self.assertEqual(self.resolve(d,a),(frozenset({('ZeroDivisionError','m.py:6')}),[]))
    def test_a_missing_anchor_fails_with_a_named_reason(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            self.write(d,'m.py','def f(x):\n    return 1.0/x\n')
            self.assertEqual(self.resolve(d,('ZeroDivisionError','m.py','f',('return 2.0/x',))),
                             (frozenset(),['anchor-missing ZeroDivisionError m.py f: return 2.0/x']))
            self.assertEqual(self.resolve(d,('ZeroDivisionError','n.py','f',('return 1.0/x',))),
                             (frozenset(),['source-unreadable ZeroDivisionError n.py f: return 1.0/x']))
    def test_an_ambiguous_anchor_fails_with_a_named_reason(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            self.write(d,'m.py','def f(x):\n    a=1.0/x\n    a=1.0/x\n')
            self.assertEqual(self.resolve(d,('ZeroDivisionError','m.py','f',('a=1.0/x',))),
                             (frozenset(),['anchor-ambiguous ZeroDivisionError m.py f: a=1.0/x (lines 2, 3)']))
    def test_the_enclosing_function_bounds_the_anchor(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            self.write(d,'m.py','def f(x):\n    return 1.0/x\ndef g(x):\n    return 1.0/x\n')
            self.assertEqual(self.resolve(d,('ZeroDivisionError','m.py','g',('return 1.0/x',))),(frozenset({('ZeroDivisionError','m.py:4')}),[]))
            self.assertEqual(self.resolve(d,('ZeroDivisionError','m.py','h',('return 1.0/x',))),
                             (frozenset(),['scope-missing ZeroDivisionError m.py h: return 1.0/x']))
            self.write(d,'m.py','def f(x):\n    return 1.0/x\nclass C:\n    def f(self):\n        return 2.0\n')
            self.assertEqual(self.resolve(d,('ZeroDivisionError','m.py','f',('return 1.0/x',))),
                             (frozenset(),['scope-ambiguous ZeroDivisionError m.py f: return 1.0/x']))
    def test_context_lines_make_a_repeated_line_unique(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            self.write(d,'m.py','def f(x):\n    for k in r:\n        a=1\n    for k in r:\n        b=1/x\n')
            self.assertEqual(self.resolve(d,('ZeroDivisionError','m.py','f',('for k in r:','b=1/x'))),(frozenset({('ZeroDivisionError','m.py:4')}),[]))
            self.assertEqual(self.resolve(d,('ZeroDivisionError','m.py','f',('for k in r:',)))[1],
                             ['anchor-ambiguous ZeroDivisionError m.py f: for k in r: (lines 2, 4)'])
    def test_two_anchors_on_one_location_fail(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            self.write(d,'m.py','def f(x):\n    a=1\n    return 1.0/x\n')
            # the first anchor line is the pinned line: ('a=1', 'return 1.0/x') pins line 2
            self.assertEqual(self.resolve(d,('ZeroDivisionError','m.py','f',('return 1.0/x',)),('ZeroDivisionError','m.py','f',('a=1','return 1.0/x'))),
                             (frozenset({('ZeroDivisionError','m.py:2'),('ZeroDivisionError','m.py:3')}),[]))
            got=self.resolve(d,('ZeroDivisionError','m.py','f',('return 1.0/x',)),('ZeroDivisionError','m.py','f',('return 1.0/x',)))
            self.assertEqual(got,(frozenset({('ZeroDivisionError','m.py:3')}),['anchor-collision ZeroDivisionError m.py f: return 1.0/x (line 3)']))
    def test_every_census_anchor_resolves_once_at_this_head(self):
        expected,errors=cvectors.resolve_anchors()
        self.assertEqual((errors,len(expected),len(cvectors.CENSUS_ANCHORS)),([],39,39))   # Task 10b: 25 + the 14 ALO raise points
    def test_a_lost_raise_point_is_reported(self):
        import shutil, tempfile
        old="if not xMin<xMax:raise ValueError('invalid range')"
        with tempfile.TemporaryDirectory() as d:
            for name in ('models.py','reference.py','solver.py','baw_admit.py','alo_equation.py','alo.py'):shutil.copyfile(self.PKG/name,Path(d)/name)
            p=Path(d)/'solver.py';src=p.read_text(encoding='utf-8');self.assertEqual(src.count(old),1)
            p.write_text(src.replace(old,"if not xMin<xMax:raise ValueError('range')"),encoding='utf-8')
            expected,errors=cvectors.resolve_anchors(src_dir=d)
            self.assertEqual((errors,len(expected)),(['anchor-missing ValueError solver.py brent: '+old],38))
    def test_a_new_raise_point_is_reported(self):
        expected,_=cvectors.resolve_anchors();known=sorted(expected)[0]
        counts={known:3,('ZeroDivisionError','models.py:1'):1,('KeyError',known[1]):2}
        self.assertEqual(cvectors.census_unexpected(counts,expected),['KeyError '+known[1],'ZeroDivisionError models.py:1'])
        self.assertEqual(cvectors.census_unexpected({known:1},expected),[])
    def test_anchor_errors_fail_the_gate(self):
        import tempfile
        from unittest import mock
        from optionlab import checks
        expected,_=cvectors.resolve_anchors();tracked=Path(cvectors.__file__).with_name(cvectors.CENSUS_ROWS_FILE)
        with tempfile.TemporaryDirectory() as d:
            r=checks.census_gate(Path(d),tracked);self.assertEqual((r['status'],r['counts']['anchor_errors']),('PASS',0))
        with tempfile.TemporaryDirectory() as d, mock.patch.object(cvectors,'resolve_anchors',lambda *a,**k:(expected,['anchor-missing X'])):
            r=checks.census_gate(Path(d),tracked)
        self.assertEqual((r['status'],r['counts']['anchor_errors'],r['counts']['unexpected']),('FAIL',1,0))

class BumpStepTests(unittest.TestCase):
    """Fix round 1: I2 (reference.py:59/60 divide by h_sigma and h_r) and M2 (the stop position of each greek-step row)."""
    def test_zero_bump_steps_raise_for_crr_and_not_for_bsm(self):
        from optionlab.params import CASE
        row=(0,100.0,100.0,1.0,10.0,11.0,0.04,0.012)
        for kw in ({'h_r':0.0},{'h_sigma':0.0}):
            prm=cvectors._replace(CASE,**kw)
            self.assertEqual(cvectors.evaluate_outcome(row,'crr',prm)[2],1,kw)
            self.assertEqual(cvectors.evaluate_outcome(row,'bsm',prm)[:3],cvectors.evaluate_outcome(row,'bsm',CASE)[:3],kw)
    def test_greeks_rows_stop_at_the_greek_call_and_at_every_bump(self):
        # a CRR greek step that stops makes 1 + k engine calls: k = 0 the greek call, then iv+h, iv-h (central only),
        # r+h_r, r-h_r. A stop at bump 2 (iv-h) is reachable (Task 11 part B review carry): for b < 0 the pu >= 0 bound
        # has a sigma^2 term that sigma_lo(CRR) lacks, so iv-h >= sigma_lo(CRR) can still give pu < 0 (the T = 1403.98 row).
        got={(g[0],g[2]) for m,row,s,prm in cvectors.greeks_rows() if m==2 for g in (cvectors.greeks_outcome(m,row,s,prm),) if g[0]!=0}
        self.assertTrue({(1,1),(1,2),(1,3),(2,4),(2,5),(1,5)}<=got,got)

# Bound mutants of reference.py: each must change a vector result (part evaluate rows or the Checker or tau_v tables).
EVAL_DETECTED={'S':('or S<=0.0 or K<=0.0','or S<0.0 or K<=0.0'),'K':('or K<=0.0:return','or K<0.0:return'),
               'T':('if T<=0.0:','if T<0.0:'),'bid':('if bid<=0.0:','if bid<0.0:'),'ask':('if ask<bid:','if ask<=bid:'),
               'lo_hi':('if lo>=hi:','if lo>hi:'),'band_lo':('abs(fa)<=band','abs(fa)<band'),'band_hi':('abs(fb)<=band','abs(fb)<band'),
               'intrinsic':('mid<max(','mid<=max('),'vega_bump':('iv-h<lo else','iv-h<=lo else'),'flat':('values[5]*100.0<1e-12','values[5]*100.0<=1e-12')}
CHECK_DETECTED={'domain':('V<-self.tau','V<=-self.tau'),'band':('if V<0.0:self.band=True','if V<=0.0:self.band=True')}

def _eval_mutant_test(old,new):
    def test(self):
        self.assertNotEqual(eval_bits(cvectors.reference_variant(old,new).evaluate,bound_pairs()),_eval_good(),(old,new))
    return test

def _check_mutant_test(old,new):
    def test(self):
        v=cvectors.reference_variant(old,new)
        def run(t,x):
            c=v.Checker(t)
            try:c(x)
            except v.EngineDomain:return 1,int(c.band)
            return 0,int(c.band)
        self.assertNotEqual([run(t,x) for t,x in cvectors.checker_rows()],[cvectors.checker_outcome(t,x) for t,x in cvectors.checker_rows()])
    return test

for _name,(_old,_new) in EVAL_DETECTED.items():
    setattr(EvaluateVectorTests,'test_vectors_detect_evaluate_mutant_'+_name,_eval_mutant_test(_old,_new))
for _name,(_old,_new) in CHECK_DETECTED.items():
    setattr(EvaluateVectorTests,'test_vectors_detect_checker_mutant_'+_name,_check_mutant_test(_old,_new))

def test_tau_max_order(self):
    v=cvectors.reference_variant('max(F,K)','max(K,F)')
    def run(*row):
        try:return 0,cvectors.bits(v.tau_v(*row))
        except (ZeroDivisionError,ValueError):return 1,0
    self.assertNotEqual([run(*r) for r in cvectors.tau_rows()],[(d,cvectors.bits(x) if d==0 else 0) for d,x in (cvectors.tau_outcome(*r) for r in cvectors.tau_rows())])
EvaluateVectorTests.test_vectors_detect_tau_mutant_max_order=test_tau_max_order

def _baw_greeks_with(ref,row,prm):
    """(status, flags, count, value bits) of the BAW greek step at sigma through the module `ref` (reference or a variant)."""
    from optionlab import models
    side,S,K,T,r,q,s=row;ev=[0]
    try:
        check=ref.Checker(ref.tau_v(S,K,T,r,q));value,result=ref._baw_engine(models.price,prm)
        vals,flags,_=ref.baw_greeks(side,S,K,T,r,q,s,prm,value(side,K,q),result(side,K,q),check,ev)
    except models.BawRunDefect:return (2,0,0,())
    except models.AdmitExcluded:return (1,64,ev[0],())
    except ref.StencilUnresolved:return (1,16,ev[0],())
    except (ref.EngineDomain,models.ModelDefect):return (1,0,ev[0],())
    except (ZeroDivisionError,ValueError):return (3,0,ev[0],())
    return (0,flags,ev[0],tuple(cvectors.bits(v) for v in vals))

class BawVectorTests(unittest.TestCase):
    """Task 10a: the BAW vectors (parts baw_admit, baw_cert, baw, baw_greeks, evaluate_baw) hold their bound rows, and every
    BAW bound mutant changes a vector result (so the same change in C fails a C test)."""
    def test_traced_admit_matches_baw_admit_and_names_each_exit(self):
        from optionlab import baw_admit as ba
        rows=cvectors.baw_admit_inputs()+cvectors.baw_admit_boundary_inputs()
        exits=set()
        for row in rows:
            ins,adm,defect,vals,_=cvectors.baw_admit_detail(*row)
            if not defect:self.assertEqual((bool(ins),bool(adm)),ba.baw_admit(*row));exits.add(vals[-1])
        self.assertTrue({1.0,2.0,3.0,4.0,5.0,11.0,12.0}<=exits,exits)
    def test_certificate_rows_hold_the_crafted_divisions(self):
        defects=[a for a in cvectors.baw_cert_inputs(cvectors.baw_admit_boundary_inputs()) if cvectors.baw_cert_detail(a)[1]]
        self.assertGreaterEqual(len(defects),2)
    def test_greek_rows_reach_the_flags(self):
        from optionlab.params import CASE
        got=[cvectors.baw_greeks_outcome(r,CASE) for r in cvectors.baw_greek_rows()]
        self.assertTrue(any(g[0]==0 and g[2]&32 for g in got));self.assertTrue(any(g[2]&64 for g in got))
    def test_evaluate_rows_reach_each_reason_and_both_defects(self):
        got=[cvectors.evaluate_baw_outcome(r,p) for r,p in cvectors.evaluate_baw_rows()]
        self.assertTrue({1,2,3}<={g[4] for g in got});self.assertGreaterEqual(sum(g[2] for g in got),2)
    def test_mutant_r_stencil_forward_at_zero(self):
        # R(c): r - h_r >= 0.0; the put at r == h_r evaluates r = 0.0 (refused, bit 64); '>' takes the forward point
        from optionlab import reference
        from optionlab.params import CASE
        v=cvectors.reference_variant('lambda h_:r-h_>=0.0','lambda h_:r-h_>0.0')
        rows=cvectors.baw_greek_rows()
        self.assertNotEqual([_baw_greeks_with(v,r,CASE) for r in rows],[_baw_greeks_with(reference,r,CASE) for r in rows])
    def test_mutant_sigma_stencil_down_bound(self):
        from optionlab import reference
        from optionlab.params import CASE
        v=cvectors.reference_variant('lambda h_:iv-h_>=lo','lambda h_:iv-h_>lo')
        rows=cvectors.baw_greek_rows()
        self.assertNotEqual([_baw_greeks_with(v,r,CASE) for r in rows],[_baw_greeks_with(reference,r,CASE) for r in rows])
    def test_mutant_side_test_strictness(self):
        from optionlab import reference
        from optionlab.params import CASE
        v=cvectors.reference_variant("'continuation' if ((S<Sk) if side==0 else (S>Sk))","'continuation' if ((S<=Sk) if side==0 else (S>=Sk))")
        rows=cvectors.baw_sstar_rows()
        self.assertNotEqual([_baw_greeks_with(v,r,CASE) for r in rows],[_baw_greeks_with(reference,r,CASE) for r in rows])
    def test_mutant_engine_strictness(self):
        import inspect, types
        from optionlab import baw, models
        from optionlab.params import CASE
        for old,new in (('if S<Sk:value','if S<=Sk:value'),('if S>Sk:value','if S>=Sk:value'),('if D_q>=1.0 and side==CALL:   ','if D_q>1.0 and side==CALL:   ')):
            src=inspect.getsource(baw);self.assertEqual(src.count(old),1,old)
            space={'__name__':'optionlab_baw_variant'};exec(compile(src.replace(old,new),'<baw variant>','exec'),space)
            def run(eng,row):
                side,S,K,T,r,q,s=row
                try:return cvectors.bits(eng(side,S,K,*models.mapped_inputs(T,r,q,s),greeks=False)['value'])
                except (models.ModelDefect,models.RunDefect,ZeroDivisionError):return None   # H19: a BAW run defect is a RunDefect
            rows=cvectors.baw_inputs()
            self.assertNotEqual([run(space['engine'],r) for r in rows],[run(baw.engine,r) for r in rows],old)
    def test_mutant_sigma_lo_carry_sign(self):
        from optionlab import models
        from optionlab.params import CASE
        v=cvectors.models_variant('1.001*(abs(b)+hr)*math.sqrt(T)/2.0 if b<0.0 else 0.0)','1.001*(abs(b)+hr)*math.sqrt(T)/2.0 if b<=0.0 else 0.0)')
        rows=cvectors.baw_lo_inputs()
        f=lambda m:[cvectors.bits(m.sigma_lo('baw',s,T,r,q,CASE)) for _,s,T,r,q in rows]
        self.assertNotEqual(f(v),f(models))

def _baw_admit_variant(old,new):
    """(namespace, return lines of its certificate) of optionlab.baw_admit executed again with `old` (one occurrence)
    replaced by `new`."""
    import ast, inspect
    from optionlab import baw_admit as ba
    src=inspect.getsource(ba)
    if src.count(old)!=1:raise ValueError('variant site not unique: '+old)
    src=src.replace(old,new);space={'__name__':'optionlab_baw_admit_variant'}
    exec(compile(src,'<baw_admit variant>','exec'),space)
    fn=[n for n in ast.parse(src).body if isinstance(n,ast.FunctionDef) and n.name=='certificate'][0]
    lines=sorted(r.lineno for r in ast.walk(fn) if isinstance(r,ast.Return))
    return space,lines

def _cert_outcomes(fn,rows,lines=None):
    """(N_C or None or the exception type, exit, the CERT_FIELDS bits) of fn on every baw_cert row."""
    out=[]
    for args in rows:
        res,exc,loc,pos,_=cvectors._traced(fn,args,lines=lines)
        out.append((type(exc).__name__ if exc else res,pos,tuple(cvectors.bits(cvectors._field(loc,n,pos)) for n in cvectors.CERT_FIELDS)))
    return out

# Certificate bound mutants (fix round 1, I3): each must change a baw_cert vector result (return value, exit or intermediate).
CERT_DETECTED={'xlo':('if not xlo>0.0 or','if not xlo>=0.0 or'),'dlow':('if not dlow>0.0:return None','if not dlow>=0.0:return None'),
               'm':('if not m>0.0:return None','if not m>=0.0:return None'),'half':('<=m/2.0:return None','<m/2.0:return None'),
               'reach':('<=R and 2.0*eta<=w','<R and 2.0*eta<=w'),'eta_w':('and 2.0*eta<=w)','and 2.0*eta<w)'),
               'target7':('+dg<=target:return None','+dg<target:return None'),'rho':('if not rho<=0.5*','if not rho<0.5*'),
               'target9':('if M*2.0*(beta+eta)<=target:return 0','if M*2.0*(beta+eta)<target:return 0'),
               'rate':('2.0*eta)<=target:return k','2.0*eta)<target:return k')}

class BawCertMutantTests(unittest.TestCase):
    """Fix round 1: the stop test (I1) and the certificate thresholds (I3) at their exact bounds."""
    @classmethod
    def setUpClass(cls):
        from optionlab import baw_admit as ba
        cls.rows=cvectors.baw_cert_inputs(cvectors.baw_admit_inputs()+cvectors.baw_admit_boundary_inputs())
        cls.good=_cert_outcomes(ba.certificate,cls.rows)
    def test_tie_rows_sit_exactly_on_their_bounds(self):
        found={n for n in cvectors.CERT_CHECKS if any(cvectors._cert_tie(n,a) for a in self.rows)}
        self.assertTrue(set(CERT_DETECTED)<=found,found)
    def test_stop_tie_row_is_exact_and_the_mutant_changes_the_vectors(self):
        from optionlab import baw_admit as ba, models
        side,S,K,T,r,q,s=cvectors.STOP_TIE_ROW
        D_r,D_q,v=models.mapped_inputs(T,r,q,s)
        space,_=_baw_admit_variant('return not (_div(math.fabs(LHS-RHS),K)>TOL)','return not (_div(math.fabs(LHS-RHS),K)>=TOL)')
        self.assertNotEqual(space['critical_price'](side,K,D_r,D_q,v,40),ba.critical_price(side,K,D_r,D_q,v,40))
        def crit(cp):
            out=[]
            for row in cvectors.baw_inputs():
                side,S,K,T,r,q,s=row
                try:D_r,D_q,v=models.mapped_inputs(T,r,q,s)
                except ZeroDivisionError:continue
                if D_q>=1.0 and side==0:continue
                try:out.append(cp(side,K,D_r,D_q,v,40))
                except (models.ModelDefect,models.RunDefect) as e:out.append(type(e).__name__)   # H19: BawRunDefect (cap hit) is a RunDefect
            return out
        self.assertNotEqual(crit(space['critical_price']),crit(ba.critical_price))

def _cert_mutant_test(old,new):
    def test(self):
        space,lines=_baw_admit_variant(old,new)
        self.assertNotEqual(_cert_outcomes(space['certificate'],self.rows,lines),self.good,(old,new))
    return test

for _name,(_old,_new) in CERT_DETECTED.items():
    setattr(BawCertMutantTests,'test_vectors_detect_certificate_mutant_'+_name,_cert_mutant_test(_old,_new))

class ProtocolVectorTests(unittest.TestCase):
    """Task 13: the protocol corpus (Amendment G G4.4-G4.5, Amendment I I5, ruling 47) and the canonical vectors (G5, I6)."""
    NAMES={'request-1','request-threads','response-1','shutdown','error','truncated','shm-request','shm-hostile',
           'request-models-0','request-models-32','request-models-16','request-models-31','error-models-7','shutdown-models-7',
           'response-models-0','v1-eof','response-mask-1','unselected-status','unselected-flags','unselected-value',
           'unselected-alo','selected-254','alo-flags','request-limit','error-count-1','shutdown-count-1',
           'baw-flags','unselected-alo-flags','unselected-alo-nan-payload','unselected-alo-negative-nan','selected-alo-254'}
    MISPLACED=((0,16),(0,32),(0,64),(1,16),(1,32),(1,64),(2,16),(2,32),(2,64),(4,64),(0,128),(1,128),(2,128),(3,128),(4,128))
    def test_layout_constants(self):
        self.assertEqual((cvectors.HEADER.size,cvectors.REQUEST.size,cvectors.RESPONSE.size),(28,64,290))
        self.assertEqual(28+14336*290+4+16*4,4157536)
        self.assertGreater(28+14336*290+4+16*4,cvectors.FUZZ_MAX_LEN)   # ruling 47: the full response is a unit vector only
        rec=cvectors.RESPONSE.pack(0,1,2,3,4,5,6,7,8,9,*[float(i) for i in range(35)])
        for k in range(5):
            for j in range(7):
                self.assertEqual(struct.unpack_from('<d',rec,10+56*k+8*j)[0],float(7*k+j))
    def test_corpus_names_sizes_and_frames(self):
        files=cvectors.corpus_files()
        names=self.NAMES|{f'misplaced-flag-{k}-{b}' for k,b in self.MISPLACED}|{f'baw-boundary-{i}' for i in range(8)}
        names|={f'alo-switch-{i}' for i in range(12)}
        inproc={'inproc-valid-2','inproc-misaligned','inproc-overlap','inproc-short-out'}|{f'inproc-models-{m}' for m in (0,1,15,16,31,32)}   # Task 16 (EX-9), T17-A03
        inproc|={f'inproc-baw-boundary-{i}' for i in range(8)}|{f'inproc-alo-switch-{i}' for i in range(12)}
        self.assertEqual(len(inproc),30)
        self.assertEqual(set(files),names|inproc)
        self.assertTrue(all(isinstance(v,bytes) and 0<len(v)<=cvectors.FUZZ_MAX_LEN for v in files.values()))
        self.assertTrue(all(v[:4]==b'SCPL' for k,v in files.items() if not k.startswith('inproc-')))   # the inproc seeds are a different frame (T17-A03)
        hdr=lambda n:cvectors.HEADER.unpack_from(files[n])
        self.assertEqual(len(files['v1-eof']),26);self.assertEqual(hdr('request-limit')[4],14337)
        self.assertEqual([hdr(f'request-models-{m}')[6] for m in (0,32,16,31)],[0,32,16,31])
        self.assertEqual([hdr(n)[4] for n in ('error-count-1','shutdown-count-1')],[1,1])   # G4.4 count on ERROR, SHUTDOWN
        self.assertEqual(len(set(files[f'baw-boundary-{i}'][28:] for i in range(8))),8)
    def test_misplaced_flag_entries(self):
        files=cvectors.corpus_files()
        for k,bit in self.MISPLACED:
            rec=files[f'misplaced-flag-{k}-{bit}'][28:28+290]
            self.assertEqual(cvectors.HEADER.unpack_from(files[f'misplaced-flag-{k}-{bit}'])[6],31)
            self.assertEqual(list(rec[5:10]),[bit if i==k else 0 for i in range(5)])
        self.assertEqual(files['alo-flags'][28+9],48)
        rec=files['baw-flags'][28:28+290]   # I12: bits 16, 32, 64 accepted in the baw flag byte (review I1)
        self.assertEqual(cvectors.HEADER.unpack_from(files['baw-flags'])[6],31)
        self.assertEqual(list(rec[:10]),[8,8,8,8,8,0,0,0,112,0])
    def test_unselected_parts_are_exact(self):
        files=cvectors.corpus_files();nan_bits=b'\x00\x00\x00\x00\x00\x00\xf8\x7f'
        rec=files['response-mask-1'][28:28+290]
        self.assertEqual(list(rec[:10]),[8,254,254,254,254,0,0,0,0,0])
        self.assertTrue(all(rec[10+56*k+8*j:18+56*k+8*j]==nan_bits for k in range(1,5) for j in range(7)))
        self.assertEqual(files['unselected-alo'][28+4],8);self.assertEqual(files['unselected-value'][28+282:28+290],bytes(8))
        alo=lambda n:files[n][28:28+290]   # I13.3: every unselected-part defect of the alo block (review I1)
        self.assertEqual(list(alo('unselected-alo-flags')[:10]),[8,254,254,254,254,0,0,0,0,32])
        self.assertTrue(all(alo('unselected-alo-flags')[10+56*k+8*j:18+56*k+8*j]==nan_bits for k in range(1,5) for j in range(7)))
        self.assertEqual(alo('unselected-alo-nan-payload')[234:242],bytes.fromhex('010000000000f87f'))
        self.assertEqual(alo('unselected-alo-negative-nan')[234:242],bytes.fromhex('000000000000f8ff'))
        self.assertEqual(cvectors.HEADER.unpack_from(files['selected-alo-254'])[6],17)
        self.assertEqual(list(alo('selected-alo-254')[:10]),[8,254,254,254,254,0,0,0,0,0])
    def test_canonical_texts_follow_the_mask(self):
        import json
        from optionlab.reference import canonical_result
        from optionlab.contract import MODELS4
        text,count=cvectors.PARTS['canonical']()
        self.assertEqual(count,10);self.assertIn('PL_VEC_CANONICAL_TEXT',text)
        res=cvectors.canonical_case()
        for mask in cvectors.CANON_MASKS:
            got=canonical_result(cvectors.subset(res,mask)).decode('ascii')
            if mask==7:self.assertTrue(got.startswith('{"digest_form":"ocg-v1","models":{"bjs":'))
            else:self.assertTrue(got.startswith('{"digest_form":"ocg-v1m","mask":%d,"models":{'%mask))
            if mask<16:   # I6.3: an independent Amendment G (MODELS4) form gives the same bytes
                doc=json.loads(got);models=[m for i,m in enumerate(MODELS4) if mask>>i&1]
                self.assertEqual(sorted(doc['models']),sorted(models))
                if mask!=7:self.assertEqual(doc['mask'],sum(1<<MODELS4.index(m) for m in models))
            else:self.assertIn('"alo":',got)
    def test_masks_1_to_15_equal_an_independent_amendment_g_render(self):
        # Review M2 / I6.3: a stdlib render of the Amendment G form (MODELS4 bits, keys in sorted order, 16 hex digits of the
        # big-endian bits, -0.0 as 0.0, NaN as null), written without canonical_result, equals its bytes for every mask 1-15.
        import json
        from optionlab.reference import canonical_result
        from optionlab.contract import MODELS4,FIELDS
        res=cvectors.canonical_case()
        def num(v):return None if math.isnan(v) else struct.pack('>d',0.0 if v==0.0 else v).hex()
        for mask in range(1,16):
            sel=[m for i,m in enumerate(MODELS4) if mask>>i&1];col=res['models']
            models={m:{**{f:[num(v) for v in col[m][f]] for f in FIELDS},'flags':list(col[m]['flags']),'status':list(col[m]['status'])} for m in sel}
            head='{"digest_form":"ocg-v1","models":' if mask==7 else '{"digest_form":"ocg-v1m","mask":%d,"models":'%mask
            body=json.dumps(models,sort_keys=True,separators=(',',':'))
            self.assertEqual(canonical_result(cvectors.subset(res,mask)),(head+body+',"n":%d}'%res['n']).encode('ascii'),mask)

if __name__=='__main__':unittest.main()
