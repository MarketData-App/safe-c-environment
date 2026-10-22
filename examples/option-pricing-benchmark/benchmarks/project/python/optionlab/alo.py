"""Andersen-Lake-Offengenden (ALO) as QuantLib 1.43 QdFpAmericanEngine computes it with accurateScheme =
QdFpLegendreTanhSinhScheme(25, 5, 13, 1e-8) and the fixed-point equation Auto (spec Amendment I items I2, I3, I4.1;
the approved source-verification record Appendix I-ALO, items R2-R10 and the errata R12 E-ALO-1..5). QL_VERSION 1.43.

QuantLib attribution (Amendment B item 9): transcribed statement by statement from the retained QuantLib 1.43 release
benchmarks/project/third_party/sources/QuantLib-1.43.tar.gz (sha256 b41206ccc4ba39b5e86bdc940d51138222b352f79d2c6fc68649f9c9bbe58701,
tag v1.43), paths below ql/:
- pricingengines/vanilla/qdplusamericanengine.cpp:41-122 (QdPlusBoundaryEvaluator) -> `QdPlusEval`; :132-158
  (QdPlusAddOnValue) -> the add-on integrand in `calculate_put`; :167-196 (QdPutCallParityEngine::calculate) -> `engine`;
  :198-228 (calculatePutWithEdgeCases) -> `put_with_edge_cases`; :231-251 (xMax) -> `xmax_fn`; :267-289 (buildInSolver
  with QuantLib Brent) -> `_qd_brent`; :291-344 (putExerciseBoundaryAtTau, Halley, eps 1e-8, maxIter 10) ->
  `qd_boundary_at_tau`; :346-362 (getPutExerciseBoundary, 14 interpolation points) -> `qd_boundary_interp`;
- pricingengines/vanilla/qdfpamericanengine.cpp:37-58, 103-116 (the scheme: GaussLegendreIntegrator(25), 1 Jacobi-Newton
  and 4 naive steps, a new TanhSinhIntegral(1e-8) per evaluation), :119-158 (DqFpEquation, d), :198-309 (FP-A f and NDd,
  Legendre path), :311-400 (FP-B f and NDd, Legendre path), :429-516 (calculatePut) -> `FpEquation`, `calculate_put`;
- math/interpolations/chebyshevinterpolation.cpp:33-81 (second kind, nodes -cos(i M_PI / 13), updateY) and
  lagrangeinterpolation.hpp:42-134 (barycentric weights and value with the exact-node branch), interpolation.hpp:122-125
  (operator()(x, true): no range check) -> `Cheb`;
- math/integrals/gaussianquadratures.{hpp,cpp} (GaussLegendreIntegration(25)): the frozen table GL_X/GL_W (record R5, a
  protected fixture `alo_gauss_legendre`, equal to the wheel bit for bit; the TqrEigenDecomposition loop is not run);
- math/integrals/tanhsinhintegral.hpp:41-70 and integral.cpp:76-86 (TanhSinhIntegral and Integrator::operator()) ->
  `tanh_sinh_integrate`; math/solvers1d/brent.hpp, math/solver1d.hpp (the inner Brent: optionlab.solver.brent);
  pricingengines/blackcalculator.cpp (optionlab.models.Black; checks optionlab.baw._black_checks); math/comparison.hpp
  (close, close_enough); math/distributions/normaldistribution.{hpp,cpp} (optionlab.normal).

Boost file-scope notice (spec Appendix I-ALO R1a.4 and ALO1-03; NOTICE-QuantLib.md section "Boost tanh-sinh
transcription reference"): the tanh-sinh integrator below (`TanhSinhDetail`, `tanh_sinh_integrate`) transcribes Boost
1.90.0 (BOOST_VERSION 109000) boost/math/quadrature/tanh_sinh.hpp:60-223 and boost/math/quadrature/detail/tanh_sinh_detail.hpp
:27-188, 190-558, 695-744, 855-875, and uses boost/math/special_functions/next.hpp (float_next, float_prior),
boost/math/tools/precision.hpp (epsilon, min_value, root_epsilon), boost/math/constants/constants.hpp (pi, half_pi
literals), boost/math/policies/policy.hpp and boost/math/policies/error_handling.hpp (evaluation_error throws). The
tabulated rows 0-7 are optionlab.alo_tables. Copyright lines of those files:
  tanh_sinh.hpp, tanh_sinh_detail.hpp: Copyright Nick Thompson, 2017.
  next.hpp: (C) Copyright John Maddock 2008.
  precision.hpp: Copyright John Maddock 2005-2006.
  constants.hpp: Copyright John Maddock 2005-2006, 2011. Copyright Paul A. Bristow 2006-2011. Copyright Matt Borland 2024.
  policy.hpp: Copyright John Maddock 2007. Copyright Matt Borland 2021.
  error_handling.hpp: Copyright John Maddock 2007. Copyright Paul A. Bristow 2007. Copyright Matt Borland 2024.
Distributed under the Boost Software License, Version 1.0 (the text is in examples/option-pricing-benchmark/NOTICE-QuantLib.md
and in the retained benchmarks/project/third_party/sources/boost-1.90.0/LICENSE_1_0.txt). License review: LR-EX 2026-10-18
(agent engineering review).

Arithmetic: IEEE-754 binary64 in the C++ expression order; std::max(a, b) is `b if a < b else a` and std::min(a, b) is
`b if b < a else a` (record R7: a NaN operand can vanish); a division by zero, an exp overflow, a log or sqrt outside the
domain give the C++ result (models._div, _exp, _log, _sqrt), never a Python exception. The default MXCSR (DAZ and FTZ off)
is assumed (record R1a.3).

The shared NaN check (Amendment I3 R7 item 3, record R7 item 3, E-ALO-4; `nan_check`): pre (before the engine call: S,
K, r_e, q_e, sigma' and T' finite, S > 0, K > 0, sigma' > 0; a failure is order 5, `AloPreCheck`), QD+ solver (each Halley
step: fx, f', f'', lf, step; the Brent fallback: f(xmin), each f(xmax) of the doubling loop, each Brent value),
post-boundary (the 14 node values after the QD+ interpolation and after each updateY; each interpolated value and B(tau)
used by a sweep, checked before std::max and the comparisons), post-sweep (N, D, fv after each f; Nd, Dd after each NDd),
integrand (t, v, b_t, dr, dq, the interpolated q and the integrand value, before the branches of qdplus:142-155 and before
the value reaches Boost), post-integral (addOn and the European value before cpp:515) and post-european (the Black value of
the r <= 0 edge branch before qdplus:208). A failure on an admitted point raises models.AloRunDefect('alo-nan') with its
site; a loop count above its QuantLib or Boost cap raises AloRunDefect('alo-cap') (record R3, R8). Every exception of an
engine evaluation (QuantLib and Boost texts, the inner QD+ Brent texts as `AloInnerSolverError`) is a models.ModelDefect,
so it is order 5 (record R8); only the outer IV Brent gives orders 6-8.
"""
import contextlib, hashlib, json, math, os, struct, threading
from optionlab.normal import norm_cdf as Phi, norm_pdf as phi, QL_EPSILON, QL_MAX_REAL
from optionlab.models import Black, close, ModelDefect, AloRunDefect, RunDefect, _div as dv, _log as lg, _exp as ex, _sqrt as sqt
from optionlab.mapping import unit
from optionlab.alo_equation import read_back, alo_equation, side_index, FP_A, FP_B
from optionlab.solver import brent
from optionlab import alo_tables

DBL_MIN=2.2250738585072014e-308
M_PI=3.14159265358979323846                                       # glibc math.h (the same double as mathconstants.hpp:54)
M_SQRT2=1.41421356237309504880                                     # mathconstants.hpp:94
M_SQRTPI=1.77245385090551602792981                                 # mathconstants.hpp:74
M_1_SQRTPI=0.564189583547756286948                                 # mathconstants.hpp:86
M_SQRT_2=0.7071067811865475244008443621048490392848359376887       # mathconstants.hpp:98
HALF_PI=1.570796326794896619231321691639751442e+00                 # boost constants.hpp:274
PI_B=3.141592653589793238462643383279502884e+00                    # boost constants.hpp:273
ROOT_EPS=0.1490116119384765625e-7                                  # boost precision.hpp:276-279 (root_epsilon<double>)
BOOST_EPS=2.0**-52                                                 # boost tools::epsilon<double>
SCHEME_L,SCHEME_M,SCHEME_N,SCHEME_EPS=25,5,13,1e-8                 # accurateScheme (qdfpamericanengine.cpp:417-421; Amendment I2.2)
QDPLUS_EPS,QDPLUS_MAX_ITER=1e-8,10                                 # QdPlusAmericanEngine(process, n + 1, Halley, 1e-8), maxIter 10

# record R3: the QuantLib and Boost caps per engine evaluation (a count above a cap is a run defect, R8)
CAPS={'halley':10,'doubling':1,'brent':101,'sweep_f':65,'sweep_ndd':13,'levels':15,'integrand':196695,'qd_calls':1469}

# ---- the frozen 25-point Gauss-Legendre table (record R5; x() order, descending nodes) ----
GL_X_BITS=('3fefdb9a4a51c2f5','3fef40d4b23b417a','3fee2cd9020c6b11','3feca3c642223462','3feaab8fe033d77e','3fe84bda14fdc6bf',
           '3fe58ddb0e88edd4','3fe27c36f82fec33','3fde45ad3f9e97d5','3fd71d72726b05d7','3fcf3707b1145cb5','3fbf740f7c9899b8',
           'bc8fb94f498a5702','bfbf740f7c9899a9','bfcf3707b1145cc4','bfd71d72726b05e5','bfde45ad3f9e97d8','bfe27c36f82fec2e',
           'bfe58ddb0e88eddd','bfe84bda14fdc6c2','bfeaab8fe033d776','bfeca3c642223466','bfee2cd9020c6afd','bfef40d4b23b417c',
           'bfefdb9a4a51c2fc')
GL_W_BITS=('3f8755a1bf835128','3f9afccd36646ec7','3fa4f5fa2650dc7b','3fac1c77e339dfc9','3fb16af5d29930e6','3fb48419d7047207',
           '3fb74da0d03a821d','3fb9bcb95550b81f','3fbbc7f12e17560c','3fbd6759d2b4d178','3fbe94a725b474d8','3fbf4b47ded39780',
           '3fbf88774268159e','3fbf4b47ded3970e','3fbe94a725b474da','3fbd6759d2b4d196','3fbbc7f12e17568d','3fb9bcb95550b818',
           '3fb74da0d03a8207','3fb48419d7047218','3fb16af5d2993136','3fac1c77e339e021','3fa4f5fa2650dbd4','3f9afccd36646f05',
           '3f8755a1bf83525b')
GL_X=tuple(struct.unpack('>d',bytes.fromhex(h))[0] for h in GL_X_BITS)
GL_W=tuple(struct.unpack('>d',bytes.fromhex(h))[0] for h in GL_W_BITS)
GL_DIGEST=hashlib.sha256(json.dumps({'w':list(GL_W_BITS),'x':list(GL_X_BITS)},sort_keys=True,separators=(',',':')).encode()).hexdigest()
GL_REV=tuple(range(SCHEME_L-1,-1,-1))       # cpp:221, 337: for (i = x_i.size()-1; i >= 0; --i) (record R2, ALO1-07)

class AloEngineError(ModelDefect):
    """A QuantLib QL_REQUIRE/QL_FAIL or a Boost evaluation_error inside an ALO engine evaluation (order 5, record R8)."""

class AloInnerSolverError(ModelDefect):
    """An error of the inner QD+ Brent ("root not bracketed: f[...", "maximum number of function evaluations (100)
    exceeded"): order 5 in every variant, never orders 6-7 (Amendment I3 R8; record R8)."""

class AloPreCheck(ModelDefect):
    """The pre check of the shared NaN check failed: order 5 (MODEL_DOMAIN) before the engine call (I3 R7 item 3)."""

# ---- per-evaluation counters (passive; py-reference reads them through last_stats or price_stats) ----
# A4R-06 (Task A5): the statistics are per call. Each engine evaluation creates its own Stats object and keeps it in a
# thread-local slot, so a thread reads the statistics of its own last evaluation (last_stats), never those of another
# thread; price_stats returns the object of one call, which no later call changes.
class Stats:
    __slots__=('qd_calls','halley_max','fallback_nodes','fallback_max','levels','integrand','guarded','equation','fired')
    def __init__(self):
        self.qd_calls=0;self.halley_max=0;self.fallback_nodes=0;self.fallback_max=0;self.levels=0;self.integrand=0;self.guarded=0;self.equation=None
        self.fired=False                    # test-only: the planted NaN of this evaluation has fired (_m)

_TLS=threading.local()
def _st():
    """The Stats object of the calling thread's current (or last) engine evaluation."""
    s=getattr(_TLS,'st',None)
    if s is None:s=_TLS.st=Stats()
    return s
def last_stats():
    """The statistics of the calling thread's last engine evaluation (per thread; see price_stats for one call)."""
    return _st()

# ---- test-only state (I4.1 planted defects; act only with SAFE_C_TEST_COUNTERS=1 or the test-only CaseParams fields) ----
_PLANT=None;_PERSIST=False;_HALLEY=None;_BRACKET=False;_CAPFORCE=None

def _m(site,x):
    """A planted NaN at `site` (the first occurrence per engine evaluation, or every occurrence when persistent)."""
    st=_st()
    if _PLANT==site and (_PERSIST or not st.fired):
        st.fired=True;return math.nan
    return x

def nan_check(site,*xs):
    """The shared NaN check at `site`: every value finite, else models.AloRunDefect('alo-nan') (a run defect, R8)."""
    for x in xs:
        if not math.isfinite(x):raise AloRunDefect('alo-nan',site)

def _guard(site,*xs):
    """A NaN at a guard operation (record R7 guards): counted (aggregate alo_nan_guarded), not a defect by itself."""
    for x in xs:
        if x!=x:_st().guarded+=1

def _cap(name,count):
    """A loop count against its QuantLib or Boost cap (record R3): a count above it is AloRunDefect('alo-cap')."""
    if count>(0 if _CAPFORCE==name else CAPS[name]):raise AloRunDefect('alo-cap',name)

def smax(a,b):return b if a<b else a        # std::max
def smin(a,b):return b if b<a else a        # std::min

def close_enough(x,y):
    """QuantLib close_enough(x, y) (math/comparison.hpp:92-107)."""
    if x==y:return True
    diff=math.fabs(x-y);tolerance=42*QL_EPSILON
    if x==0.0 or y==0.0:return diff<(tolerance*tolerance)
    return diff<=tolerance*math.fabs(x) or diff<=tolerance*math.fabs(y)

# ---- Boost 1.90.0 tanh_sinh<double> (record R2) ----
_ROWS_A=tuple(tuple(float(t) for t in r) for r in alo_tables.ABSCISSAS_TEXT)
_ROWS_W=tuple(tuple(float(t) for t in r) for r in alo_tables.WEIGHTS_TEXT)
TS_ERROR='Error in function tanh_sinh<double>::integrate: The tanh_sinh quadrature '

def _t_from_abscissa_complement(x):         # tanh_sinh_detail.hpp:167-174
    l=math.log(2-x)-math.log(x)
    return math.log((math.sqrt(l*l+PI_B*PI_B)+l)/PI_B)

T_CROSSOVER=_t_from_abscissa_complement(0.5)

class TanhSinhDetail:
    """tanh_sinh_detail<double>(max_refinements 15, min_complement 4*DBL_MIN): init selector 2 (tsd:695-744; the rows
    0-7 are the tabulated literals), prune_to_min_complement removes nothing (tsd:855-875), rows 8-15 computed on first
    use (tsd:55-67, 103-141). A new object per engine evaluation (E-ALO-3: a new TanhSinhIntegral per call)."""
    def __init__(self,max_refinements=15):
        self.m_max_refinements=max_refinements;self.m_inital_row_length=alo_tables.INITIAL_ROW_LENGTH
        self.m_abscissas=list(_ROWS_A);self.m_weights=list(_ROWS_W);self.m_first_complements=list(alo_tables.FIRST_COMPLEMENTS)
        self.m_committed_refinements=len(self.m_abscissas)-1
        if self.m_max_refinements>=len(self.m_abscissas):
            n=self.m_max_refinements+1
            self.m_abscissas+=[()]*(n-len(self.m_abscissas));self.m_weights+=[()]*(n-len(self.m_weights))
            self.m_first_complements+=[0]*(n-len(self.m_first_complements))
        else:self.m_max_refinements=len(self.m_abscissas)-1
        self.m_t_max=float(self.m_inital_row_length);self.m_t_crossover=T_CROSSOVER
    def extend_refinements(self):           # tsd:103-141
        if self.m_committed_refinements>=self.m_max_refinements:return
        self.m_committed_refinements+=1;row=self.m_committed_refinements
        h=math.ldexp(1.0,-row);first_complement=0;pos=h;ab=[]
        while pos<self.m_t_max:
            if pos<self.m_t_crossover:first_complement+=1
            if pos<self.m_t_crossover:ab.append(math.tanh(HALF_PI*math.sinh(pos)))
            else:
                u2=HALF_PI*math.sinh(pos);ab.append(-(1/(math.exp(u2)*math.cosh(u2))))
            pos+=2*h
        self.m_abscissas[row]=tuple(ab);self.m_first_complements[row]=first_complement
        w=[];pos=h
        while pos<self.m_t_max:
            cs=math.cosh(HALF_PI*math.sinh(pos));w.append(HALF_PI*math.cosh(pos)/(cs*cs));pos+=2*h
        self.m_weights[row]=tuple(w)
    def _row(self,n):
        if self.m_committed_refinements<n:self.extend_refinements()
        return self.m_abscissas[n],self.m_weights[n],self.m_first_complements[n]
    def integrate(self,f,left_min_complement,right_min_complement,tolerance):
        """tsd:190-558. Returns (I1, err, L1_I1, k). A non-finite integrand value is checked by the caller's integrand
        check before it reaches here (E-ALO-4), so the end retreats on a non-finite value never run on an admitted point."""
        fabs=math.fabs;fin=math.isfinite
        h=self.m_t_max/self.m_inital_row_length
        I0=HALF_PI*f(0.0,1.0);L1_I0=abs(I0)
        A0=self.m_abscissas[0];W0=self.m_weights[0]
        max_left_position=len(A0)-1;max_right_position=max_left_position
        while max_left_position>1 and fabs(A0[max_left_position])<left_min_complement:max_left_position-=1
        while max_right_position>1 and fabs(A0[max_right_position])<right_min_complement:max_right_position-=1
        yp=f(-1-A0[max_left_position],A0[max_left_position]);ym=f(1+A0[max_right_position],-A0[max_right_position])
        tail_tolerance=smax(BOOST_EPS,tolerance*tolerance)
        while max_left_position:
            if fin(yp):break
            max_left_position-=1;yp=f(-1-A0[max_left_position],A0[max_left_position])
        while max_left_position>1:
            if abs(yp*W0[max_left_position])>abs(L1_I0*tail_tolerance):break
            max_left_position-=1;yp=f(-1-A0[max_left_position],A0[max_left_position])
        while max_right_position:
            if fin(ym):break
            max_right_position-=1;ym=f(1+A0[max_right_position],-A0[max_right_position])
        while max_right_position>1:
            if abs(ym*W0[max_right_position])>abs(L1_I0*tail_tolerance):break
            max_right_position-=1;ym=f(1+A0[max_right_position],-A0[max_right_position])
        if max_left_position==0 or max_right_position==0:
            raise AloEngineError(TS_ERROR+'found your function to be non-finite everywhere! Please check your function for singularities.')
        I0+=yp*W0[max_left_position]+ym*W0[max_right_position]
        L1_I0+=abs(yp*W0[max_left_position])+abs(ym*W0[max_right_position])
        for i in range(1,len(A0)):
            if i>=max_right_position and i>=max_left_position:break
            x=A0[i];xc=x;w=W0[i]
            if math.copysign(1.0,x)<0:x=1+xc
            else:xc=x-1
            yp=f(x,-xc) if i<max_right_position else 0.0
            ym=f(-x,xc) if i<max_left_position else 0.0
            I0+=(yp+ym)*w;L1_I0+=(abs(yp)+abs(ym))*w
        k=1;I1=I0;L1_I1=L1_I0;err=0.0;thrash_count=0;nrows=len(self.m_weights)
        while k<4 or (k<nrows and k<self.m_max_refinements):
            I0=I1;L1_I0=L1_I1;I1=0.5*I0;L1_I1=0.5*L1_I0;h*=0.5;s=0.0;absum=0.0
            abscissa_row,weight_row,first_complement_index=self._row(k)
            max_left_index=max_left_position-1;max_left_position*=2
            max_right_index=max_right_position-1;max_right_position*=2
            if len(abscissa_row)>max_left_index+1 and fabs(abscissa_row[max_left_index+1])>left_min_complement:
                max_left_position+=1;max_left_index+=1
            if len(abscissa_row)>max_right_index+1 and fabs(abscissa_row[max_right_index+1])>right_min_complement:
                max_right_position+=1;max_right_index+=1
            while True:
                yp=f(-1-abscissa_row[max_left_index],abscissa_row[max_left_index])
                if fin(yp):break
                if max_left_position<=2:raise AloEngineError(TS_ERROR+'found your function to be non-finite everywhere! Please check your function for singularities.')
                max_left_position-=2;max_left_index-=1
                if not abscissa_row[max_left_index]<0:break
            truncate_left=abs(L1_I1*tail_tolerance)>abs(yp*weight_row[max_left_index])
            while True:
                ym=f(1+abscissa_row[max_right_index],-abscissa_row[max_right_index])
                if fin(ym):break
                if max_right_position<=2:raise AloEngineError(TS_ERROR+'found your function to be non-finite everywhere! Please check your function for singularities.')
                max_right_index-=1;max_right_position-=2
                if not abscissa_row[max_right_index]<0:break
            truncate_right=abs(L1_I1*tail_tolerance)>abs(ym*weight_row[max_right_index])
            s+=yp*weight_row[max_left_index]+ym*weight_row[max_right_index]
            absum+=abs(yp*weight_row[max_left_index])+abs(ym*weight_row[max_right_index])
            endpoint_error=absum
            for j in range(len(weight_row)):
                if j>=max_left_index and j>=max_right_index:break
                x=abscissa_row[j];xc=x;w=weight_row[j]
                if j>=first_complement_index:x=1+xc
                else:xc=x-1
                yp=0.0 if j>=max_right_index else f(x,-xc)
                ym=0.0 if j>=max_left_index else f(-x,xc)
                s+=(yp+ym)*w;absum+=(abs(yp)+abs(ym))*w
            I1+=s*h;L1_I1+=absum*h;k+=1;last_err=err;err=abs(I0-I1)
            if not fin(I1):
                raise AloEngineError(TS_ERROR+'evaluated your function at a singular point and got %1%. Please narrow the bounds of integration or check your function for singularities.')
            if err*1.5>last_err and k>4:
                terminate=False;thrash_count+=1
                if thrash_count>1 and last_err<1e-3:terminate=True
                elif thrash_count>2:terminate=True
                elif last_err<ROOT_EPS:terminate=True
                elif abs(dv(endpoint_error,s))>err:terminate=True
                if terminate:
                    I1=I0;L1_I1=L1_I0;k-=1;err=last_err+endpoint_error;break
            if err<=abs(tolerance*L1_I1) and k>=4:
                if max_left_index and max_left_index<len(abscissa_row)-1 and abs(abscissa_row[max_left_index+1])>left_min_complement:
                    yp=f(-1-abscissa_row[max_left_index],abscissa_row[max_left_index])*weight_row[max_left_index]
                    ym=f(-1-abscissa_row[max_left_index-1],abscissa_row[max_left_index-1])*weight_row[max_left_index-1]
                    if abs(yp)>abs(ym):raise AloEngineError(TS_ERROR+'evaluated your function at a singular point and got %1%. Integration bounds were automatically narrowed, but the integral was found to be increasing at the new endpoint.')
                if max_right_index and max_right_index<len(abscissa_row)-1 and abs(abscissa_row[max_right_index+1])>right_min_complement:
                    yp=f(1+abscissa_row[max_right_index],-abscissa_row[max_right_index])*weight_row[max_right_index]
                    ym=f(1+abscissa_row[max_right_index-1],-abscissa_row[max_right_index-1])*weight_row[max_right_index-1]
                    if abs(yp)>abs(ym):raise AloEngineError(TS_ERROR+'evaluated your function at a singular point and got %1%. Integration bounds were automatically narrowed, but the integral was found to be increasing at the new endpoint.')
                err+=endpoint_error;break
            if truncate_left and max_left_position>1:max_left_position-=1
            if truncate_right and max_right_position>1:max_right_position-=1
        return I1,err,L1_I1,k

def tanh_sinh_integrate(f,a,b,tolerance):
    """Integrator::operator() (integral.cpp:76-86: 0 for a == b), TanhSinhIntegral::integrate (tanhsinhintegral.hpp:53-65:
    the error is stored and never checked) and tanh_sinh::integrate for finite a < b (ts:155-220). Returns (value,
    levels, evaluations)."""
    n=[0]
    def g(x):
        n[0]+=1;return f(x)
    if a==b:return 0.0,0,0
    if b<a:
        v,k,m=tanh_sinh_integrate(f,b,a,tolerance);return -v,k,m
    avg=(a+b)*0.5;diff=(b-a)*0.5;avg_over_diff_m1=a/diff;avg_over_diff_p1=b/diff
    have_small_left=math.fabs(a)<0.5;have_small_right=math.fabs(b)<0.5
    left_min_complement=math.nextafter(avg_over_diff_m1,math.inf)-avg_over_diff_m1
    min_complement_limit=smax(DBL_MIN,math.nextafter(DBL_MIN/diff,math.inf))
    if left_min_complement<min_complement_limit:left_min_complement=min_complement_limit
    right_min_complement=avg_over_diff_p1-math.nextafter(avg_over_diff_p1,-math.inf)
    if right_min_complement<min_complement_limit:right_min_complement=min_complement_limit
    def u(z,zc):
        if z<-0.5:
            if have_small_left:return g(diff*(avg_over_diff_m1-zc))
            position=a-diff*zc
        elif z>0.5:
            if have_small_right:return g(diff*(avg_over_diff_p1-zc))
            position=b-diff*zc
        else:position=avg+diff*z
        return g(position)
    I1,err,L1,k=TanhSinhDetail().integrate(u,left_min_complement,right_min_complement,tolerance)
    return diff*I1,k,n[0]

# ---- Chebyshev (second kind) over the barycentric Lagrange interpolation ----
class Cheb:
    """ChebyshevInterpolation(n, f, SecondKind) (chebyshevinterpolation.cpp:33-81) over LagrangeInterpolationImpl
    (lagrangeinterpolation.hpp:42-134); operator()(x, true) skips the range check (interpolation.hpp:122-125)."""
    def __init__(self,n,f):
        self.x=[-math.cos(i*M_PI/(n-1)) for i in range(n)];self.n=n
        self.y=[f(z) for z in self.x]
        cM1=4.0/(self.x[n-1]-self.x[0]);lam=[]
        for i in range(n):
            li=1.0;xi=self.x[i]
            for j in range(n):
                if i!=j:li*=cM1*(xi-self.x[j])
            lam.append(1.0/li)
        self.lam=lam
    def update_y(self,y):self.y=list(y)
    def __call__(self,x):
        xs=self.x;eps=10*QL_EPSILON*math.fabs(x);t=x-eps
        _guard('lagrange:116',t)
        lo=0
        while lo<self.n and xs[lo]<t:lo+=1               # std::lower_bound
        if lo!=self.n and xs[lo]-x<eps:return self.y[lo]
        n=0.0;d=0.0;y=self.y;lam=self.lam
        for i in range(self.n):
            alpha=dv(lam[i],(x-xs[i]));n+=alpha*y[i];d+=alpha
        return dv(n,d)

# ---- QD+ ----
def xmax_fn(K,r,q):
    """QdPlusAmericanEngine::xMax (qdplusamericanengine.cpp:231-251)."""
    if r>0.0 and q>0.0:return K*smin(1.0,r/q)
    elif r>0.0 and q<=0.0:return K
    elif r==0.0 and q<0.0:return K
    elif r==0.0 and q>=0.0:return 0.0
    elif r<0.0 and q>=0.0:return 0.0
    elif r<0.0 and q<r:return K
    elif r<0.0 and r<=q and q<0.0:return 0.0
    raise AloEngineError('internal error')

class QdPlusEval:
    """QdPlusBoundaryEvaluator (qdplusamericanengine.cpp:41-122)."""
    def __init__(self,S,strike,rf,dy,vol,t,T):
        self.tau=tau=t;self.K=strike;self.sigma=sigma=vol;self.sigma2=sigma2=sigma*sigma;self.v=sigma*sqt(tau)
        self.r=r=rf;self.q=q=dy;self.dr=dr=ex(-r*tau);self.dq=ex(-q*tau)
        _guard('qdplus:47',r*tau)
        if math.fabs(r*tau)>1e-5:ddr=dv(r,(1-dr))
        else:ddr=dv(1,(tau*(1-0.5*r*tau*(1-r*tau/3))))
        self.ddr=ddr
        omega=dv(2*(r-q),sigma2);self.omega=omega
        root=sqt((omega-1)*(omega-1)+dv(8*ddr,sigma2))
        self.lam=lam=0.5*(-(omega-1)-root)
        lp=dv(2*ddr*ddr,(sigma2*root))
        self.alpha=alpha=dv(2*dr,(sigma2*(2*lam+omega-1)))
        self.beta=alpha*(ddr+dv(lp,(2*lam+omega-1)))-lam
        self.xMax=xmax_fn(strike,r,q)
        a=0.5*(strike+S);_guard('qdplus:56',a,self.xMax)
        self.xMin=QL_EPSILON*1e4*smin(a,self.xMax)
        self.sc=None;self.n=0;self.st=_st()
    def pre(self,S):
        _guard('qdplus:98',S)
        S=smax(QL_EPSILON,S);self.sc=S;v=self.v;K=self.K;dq=self.dq;dr=self.dr
        self.dp=dp=lg(dv(S*dq,(K*dr)))/v+0.5*v;self.dm=dm=dp-v
        self.Phi_dp=Phi(-dp);self.Phi_dm=Phi(-dm);self.phi_dp=phi(dp)
        self.npv=dr*K*self.Phi_dm-S*dq*self.Phi_dp
        self.theta=self.r*K*dr*self.Phi_dm-self.q*S*dq*self.Phi_dp-dv(self.sigma2*S,(2*v))*dq*self.phi_dp
        self.charm=-dq*(self.phi_dp*(dv((self.r-self.q),v)-dv(dm,(2*self.tau)))+self.q*self.Phi_dp)
    def __call__(self,S):
        self.n+=1;self.st.qd_calls+=1
        _guard('qdplus:63',S)
        if S!=self.sc:self.pre(S)
        npv=self.npv
        if _PLANT is not None:npv=_m('qdplus:66',npv)
        if close_enough(self.K-S,npv):return (1-self.dq*self.Phi_dp)*S+dv(self.alpha*self.theta,self.dr)
        c0=-self.beta-self.lam+dv(self.alpha*self.theta,(self.dr*(self.K-S-npv)))
        return (1-self.dq*self.Phi_dp)*S+(self.lam+c0)*(self.K-S-npv)
    def derivative(self,S):
        if S!=self.sc:self.pre(S)
        dq=self.dq
        return 1-dq*self.Phi_dp+dv(dq,self.v)*self.phi_dp+self.beta*(1-dq*self.Phi_dp)+dv(self.alpha,self.dr)*self.charm
    def fprime2(self,S):
        if S!=self.sc:self.pre(S)
        v=self.v;dq=self.dq;dp=self.dp
        gamma=dv(self.phi_dp*dq,(v*S))
        colour=gamma*(self.q+dv((self.r-self.q)*dp,v)+dv((1-dp*self.dm),(2*self.tau)))
        return dq*(dv(self.phi_dp,(S*v))-dv(self.phi_dp*dp,(S*v*v)))+self.beta*gamma+dv(self.alpha,self.dr)*colour

def qd_boundary_at_tau(S,K,r,q,vol,T,tau):
    """putExerciseBoundaryAtTau with Halley, eps 1e-8, maxIter_ 10 (qdplusamericanengine.cpp:291-344), with the QD+ solver
    check of the shared NaN check at each Halley step (record R7 item 3, AI3-02)."""
    if tau<QL_EPSILON:return xmax_fn(K,r,q)
    ev=QdPlusEval(S,K,r,q,vol,tau,T);eps=QDPLUS_EPS;max_iter=QDPLUS_MAX_ITER
    x=ev.xMax;xmin=ev.xMin
    while True:
        if _HALLEY is not None:_HALLEY.value+=1
        xOld=x;fx=ev(x);fPrime=ev.derivative(x);f2=ev.fprime2(x)
        lf=dv(fx*f2,(fPrime*fPrime))
        step=dv(dv(1,(1-0.5*lf))*fx,fPrime)
        if _PLANT is not None:step=_m('qdplus:329',step)
        nan_check('qdplus-solver',fx,fPrime,f2,lf,step)
        x=smax(xmin,x-step)
        close_ok=math.fabs(x-xOld)<0.5*eps
        if close_ok or not ev.n<max_iter:break
    _cap('halley',ev.n)
    if (not close_ok and not close(math.fabs(fx),0.0)) or _BRACKET:
        n0=ev.n;x=_qd_brent(ev,S,K,10*max_iter,x,max_iter,eps)
        ev.st.fallback_nodes+=1;ev.st.fallback_max=max(ev.st.fallback_max,ev.n-n0)
    else:ev.st.halley_max=max(ev.st.halley_max,ev.n)
    return x

def _qd_brent(ev,S,strike,max_evals,guess,max_iter_member,eps):
    """buildInSolver with QuantLib::Brent (qdplusamericanengine.cpp:267-289): lower bound xMin, f(xMin), the doubling loop
    (its count test uses the member maxIter_ = 10, so it never doubles after the Halley calls), the guess clamps, then
    Brent with accuracy eps and maxEvaluations 10*maxIter_ = 100 (N_MAX = 101). Its errors are AloInnerSolverError."""
    xmin=ev.xMin;fxmin=ev(xmin);nan_check('qdplus-solver',fxmin)
    a=0.5*(ev.xMax+S);_guard('qdplus:276',a)
    xmax=smax(a,ev.xMax);nd=0
    while True:
        fx=ev(xmax);nd+=1
        if _PLANT is not None:fx=_m('qdplus:277',fx)
        nan_check('qdplus-solver',fx)
        if fx*fxmin>0.0 and ev.n<max_iter_member:xmax*=2
        else:break
    _cap('doubling',nd)
    _guard('qdplus:283',guess)
    if guess>=xmax:guess=math.nextafter(xmax,-1.0)
    elif guess<=xmin:guess=math.nextafter(xmin,QL_MAX_REAL)
    if _BRACKET:raise AloInnerSolverError('root not bracketed: f[%g,%g] -> [%g,%g] (test-only forced bracket error)'%(xmin,xmax,fxmin,fx))
    def f(x):
        v=ev(x)
        if _PLANT is not None:v=_m('qdplus:brent',v)
        nan_check('qdplus-solver',v);return v
    try:st,root,_,_,n=brent(f,xmin,xmax,guess,accuracy=eps,max_evaluations=max_evals)
    except ValueError as e:raise AloInnerSolverError(str(e)[:120]) from None
    _cap('brent',n)
    if st=='OK':return root
    if st=='NOT_CONVERGED':raise AloInnerSolverError('maximum number of function evaluations (%d) exceeded'%max_evals)
    raise AloInnerSolverError('root not bracketed: f[%g,%g] -> [%g,%g]'%(xmin,xmax,fxmin,fx))

def qd_boundary_interp(S,K,r,q,vol,T,n_points=SCHEME_N+1):
    """getPutExerciseBoundary (qdplusamericanengine.cpp:346-362) with interpolationPoints = n + 1 = 14."""
    xmax=xmax_fn(K,r,q)
    def f(z):
        x_sq=0.25*T*((1+z)*(1+z))
        b=qd_boundary_at_tau(S,K,r,q,vol,T,x_sq);l=lg(dv(b,xmax));y=l*l
        if _PLANT is not None and x_sq>=QL_EPSILON:y=_m('cpp:441',y)
        return y
    return Cheb(n_points,f)

# ---- the fixed-point equations (Legendre path: x_i is not empty, cpp:127-133) ----
class FpEquation:
    """DqFpEquation_A and _B (qdfpamericanengine.cpp:119-400) on the frozen Gauss-Legendre table, sums in reverse order."""
    def __init__(self,kind,K,r,q,vol,B):
        self.kind=kind;self.K=K;self.r=r;self.q=q;self.vol=vol;self.B=B;self.f_calls=0;self.ndd_calls=0
    def d(self,t,z):                        # cpp:142-147
        v=self.vol*sqt(t);m=dv((lg(z)+(self.r-self.q)*t),v)+0.5*v
        return m,m-v
    def f(self,tau,b):
        self.f_calls+=1;K=self.K;r=self.r;q=self.q
        if self.kind==FP_A:                 # cpp:198-284
            v=self.vol*sqt(tau)
            if tau<QL_EPSILON*QL_EPSILON:
                if close_enough(b,K):N=dv(1,(M_SQRT2*M_SQRTPI*v));D=N+0.5
                else:N=0.0;D=1.0 if b>K else 0.0
            else:
                stv=dv(sqt(tau),self.vol);K12=K3=0.0
                for i in GL_REV:
                    y=GL_X[i];m=0.25*tau*((1+y)*(1+y))
                    d1,d2=self.d(m,dv(b,self.B(tau-m)))
                    K12+=GL_W[i]*ex(q*tau-q*m)*(0.5*tau*(y+1)*Phi(d1)+stv*phi(d1))
                    K3+=GL_W[i]*stv*ex(r*tau-r*m)*phi(d2)
                d1,d2=self.d(tau,dv(b,K))
                N=dv(phi(d2),v)+r*K3;D=dv(phi(d1),v)+Phi(d1)+q*K12
            alpha=K*ex(-(r-q)*tau)
            if tau<QL_EPSILON*QL_EPSILON:
                if close_enough(b,K):fv=alpha
                elif b>K:fv=0.0
                elif close_enough(q,0.0):fv=dv(alpha*r*(-1.0 if q<0 else 1.0),QL_EPSILON)
                else:fv=dv(alpha*r,q)
            else:fv=dv(alpha*N,D)
        else:                               # cpp:311-392
            if tau<QL_EPSILON*QL_EPSILON:
                if close_enough(b,K):N=D=0.5
                elif b<K:N=D=0.0
                else:N=D=1.0
            else:
                c=0.5*tau;ni=di=0.0
                for i in GL_REV:
                    u=c*GL_X[i]+c
                    d1,d2=self.d(tau-u,dv(b,self.B(u)))
                    ni+=GL_W[i]*ex(r*u)*Phi(d2);di+=GL_W[i]*ex(q*u)*Phi(d1)
                ni*=c;di*=c
                d1,d2=self.d(tau,dv(b,K))
                N=Phi(d2)+r*ni;D=Phi(d1)+q*di
            alpha=K*ex(-(r-q)*tau)
            if tau<QL_EPSILON*QL_EPSILON:
                if close_enough(b,K) or b>K:fv=alpha
                elif close_enough(q,0.0):fv=dv(alpha*r*(-1.0 if q<0 else 1.0),QL_EPSILON)
                else:fv=dv(alpha*r,q)
            else:fv=dv(alpha*N,D)
        if _PLANT is not None:N=_m('cpp:N',N);D=_m('cpp:D',D);fv=_m('cpp:fv',fv)
        nan_check('post-sweep',N,D,fv)
        return N,D,fv
    def NDd(self,tau,b):
        self.ndd_calls+=1;K=self.K;vol=self.vol
        if self.kind==FP_A:                 # cpp:286-309
            if tau<QL_EPSILON*QL_EPSILON:
                if close_enough(b,K):
                    sqTau=sqt(tau);vol2=vol*vol
                    Dd=M_1_SQRTPI*M_SQRT_2*(dv(-(0.5*vol2+self.r-self.q),(b*vol*vol2*sqTau))+dv(1,(b*vol*sqTau)))
                    Nd=dv(M_1_SQRTPI*M_SQRT_2*(-0.5*vol2+self.r-self.q),(b*vol*vol2*sqTau))
                else:Dd=Nd=0.0
            else:
                d1,d2=self.d(tau,dv(b,K))
                Dd=dv(-phi(d1)*d1,(b*vol*vol*tau))+dv(phi(d1),(b*vol*sqt(tau)))
                Nd=dv(-phi(d2)*d2,(b*vol*vol*tau))
        else:                               # cpp:394-400
            d1,d2=self.d(tau,dv(b,K))
            Nd=dv(phi(d2),(b*vol*sqt(tau)));Dd=dv(phi(d1),(b*vol*sqt(tau)))
        if _PLANT is not None:Nd=_m('cpp:ndd',Nd)
        nan_check('post-sweep',Nd,Dd)
        return Nd,Dd

def _black(K,F,sd,disc):
    """BlackCalculator(Option::Put, K, F, sd, disc).value() with its checks (blackcalculator.cpp:66-75; order 5)."""
    from optionlab.baw import _black_checks
    try:_black_checks(K,F,sd,disc)
    except RunDefect:raise
    except ModelDefect as e:raise AloEngineError(str(e)) from None
    return Black(1,K,F,sd,disc).value()

def calculate_put(S,K,r,q,vol,T,kind):
    """QdFpAmericanEngine::calculatePut (qdfpamericanengine.cpp:429-516) with accurateScheme; `kind` is the equation that
    alo_equation names (py-reference uses it, Amendment I2.4; it equals QuantLib's Auto choice bit for bit)."""
    if r<0.0 and q<r:raise AloEngineError('double-boundary case q<r<0 for a put option is given')
    xmax=xmax_fn(K,r,q)
    interp=qd_boundary_interp(S,K,r,q,vol,T)
    nan_check('post-boundary',*interp.y)
    z=interp.x;sT=sqt(T);x=[0.5*sT*(1.0+zi) for zi in z]
    def B(tau):
        zz=2*sqt(dv(math.fabs(tau),T))-1;iv=interp(zz)
        if _PLANT is not None:iv=_m('cpp:448',iv)
        nan_check('post-boundary',iv)
        b=xmax*ex(-sqt(smax(0.0,iv)));nan_check('post-boundary',b)
        return b
    def h(fv):
        l=lg(dv(fv,xmax));return l*l
    eqn=FpEquation(kind,K,r,q,vol,B)
    y=[0.0]*len(x)
    for k in range(1):                      # SCHEME_M - 4 = 1 Jacobi-Newton step (cpp:465-493)
        for i in range(1,len(x)):
            tau=x[i]*x[i];b=B(tau)
            N,D,fv=eqn.f(tau,b)
            if tau<QL_EPSILON:y[i]=h(fv)
            else:
                Nd,Dd=eqn.NDd(tau,b)
                fd=K*ex(-(r-q)*tau)*(dv(Nd,D)-dv(Dd*N,(D*D)))
                y[i]=h(b-dv((fv-b),(fd-1)))
            if _PLANT is not None:y[i]=_m('cpp:492',y[i])
        interp.update_y(y)
        nan_check('post-boundary',*interp.y)
    for k in range(SCHEME_M-1):             # 4 naive steps (cpp:495-504)
        for i in range(1,len(x)):
            tau=x[i]*x[i];fv=eqn.f(tau,B(tau))[2];y[i]=h(fv)
            if _PLANT is not None:y[i]=_m('cpp:503',y[i])
        interp.update_y(y)
        nan_check('post-boundary',*interp.y)
    _cap('sweep_f',eqn.f_calls);_cap('sweep_ndd',eqn.ndd_calls)
    T_=T;S_=S;K_=K;r_=r;q_=q;vol_=vol
    def aov(zv):                            # QdPlusAddOnValue::operator() (qdplusamericanengine.cpp:132-158)
        t=zv*zv;a=T_-t;_guard('qdplus:134',a)
        qv=interp(2*sqt(dv(smax(0.0,a),T_))-1)
        if _PLANT is not None:qv=_m('qdplus:135',qv)
        b_t=xmax*ex(-sqt(smax(0.0,qv)))
        dr=ex(-r_*t);dq=ex(-q_*t);v=vol_*sqt(t)
        if _PLANT is not None:v=_m('qdplus:142',v);b_t=_m('qdplus:143',b_t)
        nan_check('integrand',t,v,b_t,dr,dq,qv)
        if v>=QL_EPSILON:
            if b_t>QL_EPSILON:
                dp=dv(lg(dv(S_*dq,(b_t*dr))),v)+0.5*v
                res=2*zv*(r_*K_*dr*Phi(-dp+v)-q_*S_*dq*Phi(-dp))
            else:res=0.0
        elif close_enough(S_*dq,b_t*dr):res=zv*(r_*K_*dr-q_*S_*dq)
        elif b_t*dr>S_*dq:res=2*zv*(r_*K_*dr-q_*S_*dq)
        else:res=0.0
        if _PLANT is not None:res=_m('qdplus:150',res)
        nan_check('integrand-value',res)    # E-ALO-4: guards the Boost value masks directly
        return res
    addOn,levels,nev=tanh_sinh_integrate(aov,0.0,sT,SCHEME_EPS)
    st=_st();st.levels=levels;st.integrand=nev
    _cap('levels',levels);_cap('integrand',nev);_cap('qd_calls',st.qd_calls)
    europeanValue=_black(K,S*ex((r-q)*T),vol*sT,ex(-r*T))
    if _PLANT is not None:addOn=_m('cpp:515',addOn);europeanValue=_m('cpp:euro',europeanValue)
    nan_check('post-integral',addOn,europeanValue)
    return smax(europeanValue,0.0)+smax(0.0,addOn)

def put_with_edge_cases(S,K,r,q,vol,T,kind):
    """QdPutCallParityEngine::calculatePutWithEdgeCases (qdplusamericanengine.cpp:198-228). The close(S, 0) and
    close(vol, 0) branches (qdplus:205, 214, 222, 224: value masks by the default rule) are unreachable on an admitted
    point (record R7 item 1, ALO1-06); they are transcribed with the std semantics."""
    _guard('qdplus:201',S,K,r,q,vol)
    if close(K,0.0):return 0.0
    if close(S,0.0):return smax(K,K*ex(-r*T))
    if r<=0.0 and r<=q:
        bv=_black(K,S*ex((r-q)*T),vol*sqt(T),ex(-r*T))
        if _PLANT is not None:bv=_m('qdplus:208',bv)
        nan_check('post-european',bv)
        return smax(0.0,bv)
    if close(vol,0.0):
        def intrinsic(t):return smax(0.0,K*ex(-r*t)-S*ex(-q*t))
        npv0=intrinsic(0.0);npvT=intrinsic(T)
        extremT=QL_MAX_REAL if close_enough(r,q) else dv(lg(dv(r*K,(q*S))),(r-q))
        if extremT>0.0 and extremT<T:
            m=npv0
            for c in (npvT,intrinsic(extremT)):
                if m<c:m=c                  # std::max({...}): the first largest by operator<
            return m
        return smax(npv0,npvT)
    return calculate_put(S,K,r,q,vol,T,kind)

def engine(side,S,K,r_e,q_e,vol,T,kind):
    """QdPutCallParityEngine::calculate (qdplusamericanengine.cpp:167-196) on the read-back inputs of the mapped problem
    (T = 1.0): a put calls calculatePutWithEdgeCases(S, K, r, q, vol, T), a call (K, S, q, r, vol, T)."""
    st=_TLS.st=Stats();st.equation=kind
    if not S>=0.0:raise AloEngineError('negative underlying given')
    if not S>=0:raise AloEngineError('zero or positive underlying value is required')
    if not K>=0:raise AloEngineError('zero or positive strike is required')
    if not vol>=0:raise AloEngineError('zero or positive volatility is required')
    if side==1:return put_with_edge_cases(S,K,r_e,q_e,vol,T,kind)
    return put_with_edge_cases(K,S,q_e,r_e,vol,T,kind)

def pre_check(S,K,r_e,q_e,s1):
    """The pre check of the shared NaN check (I3 R7 item 3): S, K, r_e, q_e, sigma' and T' = 1.0 finite, S > 0, K > 0,
    sigma' > 0; a failure raises AloPreCheck (order 5, MODEL_DOMAIN, before the engine call; the same in every variant)."""
    if not all(math.isfinite(v) for v in (S,K,r_e,q_e,s1,1.0)) or not (S>0.0 and K>0.0 and s1>0.0):raise AloPreCheck('alo-pre')

def price_stats(side,S,K,T,r,q,sigma,params):
    """(value, Stats) of one engine evaluation through `price`: the Stats object belongs to this call only (A4R-06)."""
    v=price(side,S,K,T,r,q,sigma,params);return v,_st()

def mapped_point(side,S,K,T,r,q,sigma):
    """(side index, r1, q1, s1, r_e, q_e, equation) of one point through the unit-maturity mapping (Amendment B item 3,
    I2.5): the engine reads r_e and q_e back (alo_equation.read_back) and vol = sigma'."""
    s=side_index(side);r1,q1,s1=unit(T,r,q,sigma);r_e,q_e=read_back(r1,q1)
    return s,r1,q1,s1,r_e,q_e,alo_equation(r1,q1)

def price(side,S,K,T,r,q,sigma,params):
    """The ALO engine value through the mapping (no greeks): the pre check, alo_equation immediately before the engine
    evaluation, then the engine with that equation. `side` is 0/'call' or 1/'put'. The test-only CaseParams fields
    alo_plant_nan and alo_force_cap plant a NaN or force a cap excess for this evaluation (never in a manifest)."""
    s,r1,q1,s1,r_e,q_e,kind=mapped_point(side,S,K,T,r,q,sigma)
    pre_check(S,K,r_e,q_e,s1)
    plant=getattr(params,'alo_plant_nan','');force=getattr(params,'alo_force_cap','')
    if not plant and not force:return engine(s,S,K,r_e,q_e,s1,1.0,kind)
    global _PLANT,_PERSIST,_CAPFORCE
    saved=(_PLANT,_PERSIST,_CAPFORCE)
    if plant:
        if plant not in VALUE_MASK_SITES+EUROPEAN_MASK_SITES:raise ValueError('alo_plant_nan: unknown site (test-only)')
        _PLANT,_PERSIST=plant,False
    if force:
        if force not in CAPS:raise ValueError('alo_force_cap: unknown loop (test-only)')
        _CAPFORCE=force
    try:return engine(s,S,K,r_e,q_e,s1,1.0,kind)
    finally:_PLANT,_PERSIST,_CAPFORCE=saved

# ---- test-facing names (Task A4 Step 1); the helpers act only with SAFE_C_TEST_COUNTERS=1 ----
TEST_ROW=2              # ROWS[2] of the 32-row seeded chain: status OK, FP-A, 40 Brent-fallback node solves over its evaluations
IV_CALL_TERM=0          # record "IV-call fact (H17)": no separate engine call at the solved IV (brent.hpp:87-90)
VALUE_MASK_SITES=('qdplus:66','qdplus:329','qdplus:277','qdplus:brent','cpp:441','cpp:448','cpp:N','cpp:D','cpp:fv','cpp:ndd',
                  'cpp:492','cpp:503','qdplus:135','qdplus:142','qdplus:143','qdplus:150','cpp:515','cpp:euro')
EUROPEAN_MASK_SITES=('qdplus:208',)
HANDLER_SITES=('baw_admit.py:245','agreement.py:129','checks.py:203','checks.py:238','checks.py:261','checks.py:268','checks.py:728',
               'library.py:93','library.py:166','library.py:170','library.py:210')

def _require_test():
    if os.environ.get('SAFE_C_TEST_COUNTERS')!='1':raise RuntimeError('test-only helper: SAFE_C_TEST_COUNTERS=1 required')

@contextlib.contextmanager
def plant_nan(site,persistent=False):
    """A NaN planted at `site` (VALUE_MASK_SITES or EUROPEAN_MASK_SITES): the first occurrence in each engine evaluation,
    or every occurrence when persistent."""
    _require_test()
    if site not in VALUE_MASK_SITES+EUROPEAN_MASK_SITES:raise ValueError('unknown planting site')
    global _PLANT,_PERSIST
    saved=(_PLANT,_PERSIST);_PLANT,_PERSIST=site,persistent
    try:yield
    finally:_PLANT,_PERSIST=saved

class _Count:
    def __init__(self):self.value=0

@contextlib.contextmanager
def count_halley():
    """The number of Halley steps started (every node solve) while the context is open, as `.value`."""
    _require_test()
    global _HALLEY
    saved=_HALLEY;_HALLEY=_Count()
    try:yield _HALLEY
    finally:_HALLEY=saved

@contextlib.contextmanager
def force_inner_bracket_error():
    """The first node solve takes the Brent fallback and its bracket check fails (AloInnerSolverError: order 5)."""
    _require_test()
    global _BRACKET
    saved=_BRACKET;_BRACKET=True
    try:yield
    finally:_BRACKET=saved

@contextlib.contextmanager
def force_cap_excess(name):
    """The cap of loop `name` (CAPS) is taken as 0, so its first count check is an excess (AloRunDefect('alo-cap'))."""
    _require_test()
    if name not in CAPS:raise ValueError('unknown loop')
    global _CAPFORCE
    saved=_CAPFORCE;_CAPFORCE=name
    try:yield
    finally:_CAPFORCE=saved

def _raise_run_defect(*a,**k):raise RunDefect('planted run defect (test-only)')

class _FakeBrent:
    def setMaxEvaluations(self,n):pass
    def solve(self,*a,**k):_raise_run_defect()

class _FakeOption:
    def NPV(self):_raise_run_defect()

class _FakeProblem:
    def __init__(self,*a,**k):self.option=_FakeOption();self.spot=self;self.vol=self
    def setValue(self,v):pass
    def set_sigma(self,s):pass
    def npv(self):_raise_run_defect()

@contextlib.contextmanager
def plant_run_defect(site):
    """A test-only RunDefect planted at the call inside the try of handler `site` (HANDLER_SITES; landed lines)."""
    _require_test()
    from unittest import mock
    from optionlab import baw_admit, agreement, checks, reference
    if site not in HANDLER_SITES:raise ValueError('unknown handler site')
    if site=='baw_admit.py:245':p=mock.patch.object(baw_admit,'_map',_raise_run_defect)
    elif site=='agreement.py:129':p=mock.patch.object(agreement,'multi_root',_raise_run_defect)
    elif site=='checks.py:203':p=mock.patch.object(checks,'ql_baw_option',lambda *a,**k:(_FakeOption(),None))
    elif site in ('checks.py:238','library.py:93','library.py:210'):p=mock.patch('QuantLib.Brent',_FakeBrent)
    elif site=='checks.py:261':p=mock.patch.object(checks,'ql_baw_result',_raise_run_defect)
    elif site=='checks.py:268':p=mock.patch('optionlab.models.baw_price',_raise_run_defect)
    elif site=='checks.py:728':p=mock.patch.object(reference,'price_function',lambda *a,**k:_raise_run_defect)
    else:
        from optionlab import library
        p=mock.patch.object(library,'_Problem',_FakeProblem)
    with p:yield

def call_through(site):
    """Call the function that holds handler `site` with inputs that reach the planted call."""
    _require_test()
    from optionlab.params import CASE
    from optionlab.mapping import unit as _unit
    r,q=CASE.rate,CASE.dividend_yield
    if site=='baw_admit.py:245':
        from optionlab.baw_admit import baw_admit
        r1,q1,s1=_unit(1.0,r,q,0.3);return baw_admit(1,100.0,100.0,r1,q1,s1*s1*1.0)
    if site=='agreement.py:129':
        import copy
        from optionlab import agreement, reference
        from optionlab.models import bsm_price
        p=bsm_price(1,100.0,100.0,1.0,r,q,0.3);rows=[(1,100.0,100.0,1.0,p,p,r,q)]
        ref=reference.run(rows,CASE,models=('bsm',));got=copy.deepcopy(ref);got['models']['bsm']['iv'][0]+=0.05
        return agreement.compare(rows,got,ref,CASE)
    from optionlab import checks, library
    if site=='checks.py:203':return checks.ql_baw_result(1,100.0,100.0,1.0,r,q,0.3)
    if site=='checks.py:238':return checks.ql_baw_implied_vol(1,100.0,100.0,1.0,r,q,10.0,CASE)
    if site in ('checks.py:261','checks.py:268'):return checks.baw_record_grid(CASE)
    if site=='checks.py:728':return checks._oracle_quote_rows({'oracle':{'baw':[]}},CASE)
    if site=='library.py:93':return library._solve('bsm',1,100.0,100.0,1.0,r,q,10.0,CASE,1e-4)
    if site=='library.py:166':return library._baw_engine(1,100.0,q,CASE,{})[0](100.0,1.0,r,0.3)
    if site=='library.py:170':return library._baw_engine(1,100.0,q,CASE,{})[1](100.0,1.0,r,0.3)
    if site=='library.py:210':return library._baw_solve(None,1,100.0,100.0,1.0,r,q,10.0,CASE,1e-4)
    raise ValueError('unknown handler site')

EDGE_SECONDS=(1,60,600,1800,3599)          # T in (0, 1 h) (record R9 validity, ALO1-02)

def edge_vectors(params):
    """ALO1-02 edge vectors: T in (0, 1 h); sigma = sigma_lo and sigma_lo (1 +- 1e-3); FP-A puts (case rates), FP-B calls
    (test-only carry: r = 0.002/T, q = 0, so |r' - q'| = 0.002 >= 0.001 and the FP-B class side r > q of a call) and
    r = q (FP-A at every T); S = 100, K in {90, 100, 110}. Each entry: the inputs, the equation, whether sigma >= sigma_lo
    (admitted), and the outcome of the engine evaluation with its post checks: 'value' (finite), 'nonfinite',
    'run-defect:<site>' or 'order5:<text>'."""
    from optionlab.models import sigma_lo
    out=[]
    for sec in EDGE_SECONDS:
        T=sec/31536000.0
        for label,side,r,q in (('fp-a-put',1,params.rate,params.dividend_yield),('fp-b-call',0,0.002/T,0.0),('r-eq-q-put',1,0.04,0.04)):
            lo=sigma_lo('alo',side,T,r,q,params)
            for tag,s in (('lo',lo),('lo-plus',lo*(1+1e-3)),('lo-minus',lo*(1-1e-3))):
                for K in (90.0,100.0,110.0):
                    eq=alo_equation(*unit(T,r,q,1.0)[:2])
                    try:
                        v=price(side,100.0,K,T,r,q,s,params);oc='value' if math.isfinite(v) else 'nonfinite'
                    except AloRunDefect as e:oc='run-defect:'+e.site
                    except ModelDefect as e:oc='order5:'+str(e)[:40]
                    out.append({'set':label,'seconds':sec,'side':side,'K':K,'r':r,'q':q,'sigma':s,'sigma_tag':tag,'equation':eq,
                                'admitted':s>=lo,'outcome':oc})
    return out
