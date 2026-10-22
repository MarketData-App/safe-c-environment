"""py-optimized: NumPy + SciPy, vectorized over contracts, on the QuantLib 1.43 definitions of py-reference (spec 3.3-3.7, 5;
Amendments B and D; QL_VERSION 1.43).

Transcribed from the retained QuantLib 1.43 source (benchmarks/project/third_party/sources/QuantLib-1.43.tar.gz, paths below ql/),
through the scalar transcriptions optionlab.normal, optionlab.models, optionlab.solver and optionlab.mapping, which carry
the line citations:
- math/errorfunction.cpp:196-246, math/distributions/normaldistribution.{hpp:262-299, cpp:33-53} -> `erf`, `norm_cdf`,
  `norm_pdf` (QuantLib's binary64 constants and operation order; no scipy.special.ndtr, spec 3.8);
- math/comparison.hpp:59-76 -> `close`; math/solver1d.hpp:162-211, math/solvers1d/brent.hpp:39-133 -> `brent` (masked:
  every row runs the scalar iteration; a finished row is frozen; N_MAX = 201);
- pricingengines/blackcalculator.cpp:65-428 -> `Black`; pricingengines/vanilla/analyticeuropeanengine.cpp:45-114 -> BSM;
- pricingengines/vanilla/bjerksundstenslandengine.cpp:37-506 -> `_phi*` (the text of optionlab.models; std::erfc is
  scipy.special.erfc), `_european_call`, `_immediate`, `_american_call`, `_american_formula`, `bjs_engine`;
- pricingengines/vanilla/binomialengine.hpp:74-172, methods/lattices/binomialtree.{hpp,cpp}, bsmlattice.hpp:71-87,
  processes/blackscholesprocess.cpp:74-129, discretizedvanillaoption.cpp:47-77, pricingengines/greeks.cpp:25-35 ->
  `crr_tree`, `crr_engine` (backward induction on (N+1) x rows arrays);
- the term-structure arithmetic of models.discount/implied_rate/zero_rate/forward_rate (flatforward.hpp:102-104,
  interestrate.cpp:53-54, 91-92, yieldtermstructure.cpp:30, 118-171).
- ALO (Task A5, Amendment I4.2): the QdFpAmericanEngine transcription of optionlab.alo (its QuantLib line citations apply:
  qdplusamericanengine.cpp, qdfpamericanengine.cpp, chebyshevinterpolation.cpp, lagrangeinterpolation.hpp,
  tanhsinhintegral.hpp, integral.cpp, comparison.hpp, brent.hpp, solver1d.hpp, blackcalculator.cpp) -> `alo_values`,
  `_qd_boundary`, `_fp_sweeps`, `_tanh_sinh`, `evaluate_alo`.
QuantLib notice: examples/option-pricing-benchmark/NOTICE-QuantLib.md. License review: LR-EX 2026-10-18
(agent engineering review).

Boost file-scope notice (spec Appendix I-ALO R1a.4 and ALO1-03; NOTICE-QuantLib.md section "Boost copyright notices"):
`_tanh_sinh` transcribes Boost 1.90.0 boost/math/quadrature/tanh_sinh.hpp and boost/math/quadrature/detail/tanh_sinh_detail.hpp
(through optionlab.alo.TanhSinhDetail and its rows) and uses boost/math/special_functions/next.hpp, boost/math/tools/precision.hpp,
boost/math/constants/constants.hpp, boost/math/policies/policy.hpp and boost/math/policies/error_handling.hpp. Copyright lines:
  tanh_sinh.hpp, tanh_sinh_detail.hpp: Copyright Nick Thompson, 2017.
  next.hpp: (C) Copyright John Maddock 2008.
  precision.hpp: Copyright John Maddock 2005-2006.
  constants.hpp: Copyright John Maddock 2005-2006, 2011. Copyright Paul A. Bristow 2006-2011. Copyright Matt Borland 2024.
  policy.hpp: Copyright John Maddock 2007. Copyright Matt Borland 2021.
  error_handling.hpp: Copyright John Maddock 2007. Copyright Paul A. Bristow 2007. Copyright Matt Borland 2024.
Distributed under the Boost Software License, Version 1.0 (the text is in examples/option-pricing-benchmark/NOTICE-QuantLib.md
and in the retained benchmarks/project/third_party/sources/boost-1.90.0/LICENSE_1_0.txt). License review: LR-EX 2026-10-18
(agent engineering review).

Arithmetic: IEEE-754 binary64 (C semantics: an overflow is inf, an invalid operation NaN; a non-finite engine value fails
the order-5 check). Elementary functions come from NumPy (exp, log, pow, sqrt) and SciPy (erfc); they can differ from
libm in the last bit (spec 3.7). No algorithm or precision change against py-reference: only the loop over contracts is
vectorized. Differences in form, none in result: the solver evaluates engine values only (QuantLib's NPV does not depend on
the engine greeks); the American CRR exercise uses np.maximum, equal to std::max for the non-NaN node values (pu in [0, 1]
is checked); the CRR lattice runs in row blocks of CRR_BLOCK rows.
"""
import math, os
import numpy as np
import scipy
from scipy.special import erfc as _erfc
from optionlab.contract import STATUSES, MODELS, ALL_MODELS, FIELDS, check_models, check_variant_models, rates as chain_rates
from optionlab import counters
from optionlab.normal import (QL_EPSILON, DBL_MIN, QL_MAX_REAL, M_SQRT_2, NORMALIZATION, DENOMINATOR, TINY, ONE, ERX, EFX, EFX8,
                              PP, QQ, PA, QA, RA, SA, RB, SB)
from optionlab.models import M_SQRT2, M_SQRTPI, M_PI, M_1_SQRTPI, DT_DAY, RATE_DT, QL_MIN_REAL
from optionlab.reference import FLAG_BELOW_INTRINSIC, FLAG_BOUNDARY_AMBIGUOUS, FLAG_FLAT_VEGA, FLAG_ROUNDING_BAND
from optionlab.solver import ACCURACY, MAX_EVALUATIONS

CODE={s:i for i,s in enumerate(STATUSES)}
OK,MD,BELOW,ABOVE,NC=CODE['OK'],CODE['MODEL_DOMAIN'],CODE['BELOW_MIN'],CODE['ABOVE_MAX'],CODE['NOT_CONVERGED']
EPS=QL_EPSILON
CRR_BLOCK=512
SIMD_LABEL=('CPU-specific path: NumPy runtime SIMD dispatch selected these CPU features on this host; '
            'the C build (no -march) does not get them')

# ---- C arithmetic helpers (IEEE results; models.py keeps the same names for its scalar forms) ----
_exp=np.exp
_log=np.log
_sqrt=np.sqrt
_pow=np.power
def _sq(x):return x*x
def _max(a,b):return np.where(a<b,b,a)        # std::max

# ---- normal distribution (QuantLib ErrorFunction, CumulativeNormalDistribution, NormalDistribution) ----
def erf(x):
    """ErrorFunction::operator() (errorfunction.cpp:196-246), region by region on the rows of each region."""
    x=np.asarray(x,dtype=np.float64);out=np.empty(x.shape);ax=np.fabs(x)
    with np.errstate(all='ignore'):
        nf=~np.isfinite(x)
        if nf.any():xn=x[nf];out[nf]=np.where(np.isnan(xn),xn,np.where(xn>0,1.0,-1.0))
        m=ax<0.84375
        if m.any():
            xm=x[m];am=ax[m];z=xm*xm
            r=PP[0]+z*(PP[1]+z*(PP[2]+z*(PP[3]+z*PP[4])))
            s=ONE+z*(QQ[0]+z*(QQ[1]+z*(QQ[2]+z*(QQ[3]+z*QQ[4]))))
            y=r/s
            o=xm+xm*y
            t=am<3.7252902984e-09
            if t.any():o=np.where(t,np.where(am<DBL_MIN*16,0.125*(8.0*xm+EFX8*xm),xm+EFX*xm),o)
            out[m]=o
        m=(ax>=0.84375)&(ax<1.25)
        if m.any():
            xm=x[m];s=ax[m]-ONE
            P=PA[0]+s*(PA[1]+s*(PA[2]+s*(PA[3]+s*(PA[4]+s*(PA[5]+s*PA[6])))))
            Q=ONE+s*(QA[0]+s*(QA[1]+s*(QA[2]+s*(QA[3]+s*(QA[4]+s*QA[5])))))
            out[m]=np.where(xm>=0,ERX+P/Q,-ERX-P/Q)
        m=(ax>=6)&~nf
        if m.any():out[m]=np.where(x[m]>=0,ONE-TINY,TINY-ONE)
        m=(ax>=1.25)&(ax<6)
        if m.any():
            xm=x[m];am=ax[m];s=ONE/(am*am);a=am<2.85714285714285
            R=np.where(a,RA[0]+s*(RA[1]+s*(RA[2]+s*(RA[3]+s*(RA[4]+s*(RA[5]+s*(RA[6]+s*RA[7])))))),
                       RB[0]+s*(RB[1]+s*(RB[2]+s*(RB[3]+s*(RB[4]+s*(RB[5]+s*RB[6]))))))
            S=np.where(a,ONE+s*(SA[0]+s*(SA[1]+s*(SA[2]+s*(SA[3]+s*(SA[4]+s*(SA[5]+s*(SA[6]+s*SA[7]))))))),
                       ONE+s*(SB[0]+s*(SB[1]+s*(SB[2]+s*(SB[3]+s*(SB[4]+s*(SB[5]+s*SB[6])))))))
            r=_exp(-am*am-0.5625+R/S)
            out[m]=np.where(xm>=0,ONE-r/am,r/am-ONE)
    return out

def norm_pdf(x):
    """NormalDistribution(0, 1)::operator() (normaldistribution.hpp:275-281)."""
    deltax=np.asarray(x,dtype=np.float64)-0.0
    exponent=-(deltax*deltax)/DENOMINATOR
    with np.errstate(all='ignore'):return np.where(exponent<=-690.0,0.0,NORMALIZATION*_exp(exponent))

def norm_cdf(z):
    """CumulativeNormalDistribution(0, 1)::operator() (normaldistribution.cpp:33-53): erf form, then the masked
    Abramowitz-Stegun 26.2.12 series on the rows whose result is <= 1e-8 (each row stops at its own test)."""
    z=(np.asarray(z,dtype=np.float64)-0.0)/1.0
    result=0.5*(1.0+erf(z*M_SQRT_2))
    m=result<=1e-8
    if m.any():
        with np.errstate(all='ignore'):
            zz=z[m];k=zz.size;sum_=np.ones(k);zsqr=zz*zz;i=1.0;g=np.ones(k);a=np.full(k,QL_MAX_REAL);act=np.arange(k)
            while act.size:
                lasta=a[act];zs=zsqr[act]
                x=(4.0*i-3.0)/zs
                y=x*((4.0*i-1)/zs)
                an=g[act]*(x-y)
                s=sum_[act]-an;sum_[act]=s
                g[act]=g[act]*y
                i+=1.0
                an=np.fabs(an);a[act]=an
                act=act[(lasta>an)&(an>=np.fabs(s*QL_EPSILON))]
            result[m]=-norm_pdf(zz)/zz*sum_
    return result

def close(x,y):
    """QuantLib close(x, y) (math/comparison.hpp:59-76), elementwise."""
    x=np.asarray(x,dtype=np.float64);y=np.asarray(y,dtype=np.float64)
    with np.errstate(all='ignore'):
        diff=np.fabs(x-y);tolerance=42*QL_EPSILON
        return (x==y)|np.where((x==0.0)|(y==0.0),diff<tolerance*tolerance,(diff<=tolerance*np.fabs(x))&(diff<=tolerance*np.fabs(y)))

# ---- Brent through Solver1D::solve, masked ----
def brent(fun,lo,hi,guess,accuracy=ACCURACY,max_evaluations=MAX_EVALUATIONS):
    """Masked transcription of optionlab.solver.brent: every row runs the scalar iteration on its own state; all live rows
    take their k-th evaluation in the same call, so evaluationNumber is common. fun(idx, x) -> (f, dead): f at x for the
    rows idx, and `dead` for the rows whose evaluation failed the order-5 check (the scalar fun raises there; the row
    stops as MODEL_DOMAIN). Returns (status codes, root, f(lo), f(hi), evaluations); root is NaN unless OK; f(hi) is NaN
    when not evaluated."""
    if not accuracy>0.0:raise ValueError('accuracy must be positive')
    accuracy=max(accuracy,QL_EPSILON)
    lo=np.asarray(lo,dtype=np.float64);hi=np.asarray(hi,dtype=np.float64);guess=np.asarray(guess,dtype=np.float64);n=lo.size
    if not np.all(lo<hi):raise ValueError('invalid range')
    status=np.full(n,NC,np.uint8);root_out=np.full(n,np.nan);f_lo=np.full(n,np.nan);f_hi=np.full(n,np.nan);nev=np.zeros(n,np.int64)
    if n==0:return status,root_out,f_lo,f_hi,nev
    with np.errstate(all='ignore'):
        idx=np.arange(n)
        fa,dead=fun(idx,lo);nev+=1;status[dead]=MD;f_lo[~dead]=fa[~dead]
        c=~dead&close(fa,0.0);status[c]=OK;root_out[c]=lo[c];idx=idx[~dead&~c]
        if idx.size:
            fb,dead=fun(idx,hi[idx]);nev[idx]+=1;status[idx[dead]]=MD;idx=idx[~dead];fb=fb[~dead];f_hi[idx]=fb
            c=close(fb,0.0);status[idx[c]]=OK;root_out[idx[c]]=hi[idx[c]];idx=idx[~c];fb=fb[~c]
            fa=f_lo[idx];br=fa*fb<0.0
            status[idx[~br]]=np.where(fa[~br]>0.0,BELOW,ABOVE);idx=idx[br];fxMin=fa[br];fxMax=fb[br]
        if not idx.size:return status,root_out,f_lo,f_hi,nev
        xMin=lo[idx];xMax=hi[idx];root=guess[idx]
        if not np.all((root>xMin)&(root<xMax)):raise ValueError('guess outside the bracket')
        froot,dead=fun(idx,root);nev[idx]+=1;evaluationNumber=3
        status[idx[dead]]=MD;k=~dead
        idx,xMin,xMax,fxMin,fxMax,root,froot=idx[k],xMin[k],xMax[k],fxMin[k],fxMax[k],root[k],froot[k]
        m=froot*fxMin<0                                   # if: xMax = xMin; else: xMin = xMax (both ends equal)
        xMin=xMax=np.where(m,xMin,xMax);fxMin=fxMax=np.where(m,fxMin,fxMax)
        d=root-xMax
        e=d
        while evaluationNumber<=max_evaluations and idx.size:
            c1=((froot>0.0)&(fxMax>0.0))|((froot<0.0)&(fxMax<0.0))
            if c1.any():
                t=root-xMin;xMax=np.where(c1,xMin,xMax);fxMax=np.where(c1,fxMin,fxMax);e=np.where(c1,t,e);d=np.where(c1,t,d)
            c2=np.fabs(fxMax)<np.fabs(froot)
            if c2.any():
                xMin,root,xMax=np.where(c2,root,xMin),np.where(c2,xMax,root),np.where(c2,root,xMax)
                fxMin,froot,fxMax=np.where(c2,froot,fxMin),np.where(c2,fxMax,froot),np.where(c2,froot,fxMax)
            xAcc1=2.0*QL_EPSILON*np.fabs(root)+0.5*accuracy
            xMid=(xMax-root)/2.0
            conv=(np.fabs(xMid)<=xAcc1)|close(froot,0.0)
            ip=(np.fabs(e)>=xAcc1)&(np.fabs(fxMin)>np.fabs(froot))
            s=froot/fxMin
            cl=close(xMin,xMax)
            q=fxMin/fxMax
            r=froot/fxMax
            p=np.where(cl,2.0*xMid*s,s*(2.0*xMid*q*(q-r)-(root-xMin)*(r-1.0)))
            q=np.where(cl,1.0-s,(q-1.0)*(r-1.0)*(s-1.0))
            q=np.where(p>0.0,-q,q)
            p=np.fabs(p)
            min1=3.0*xMid*q-np.fabs(xAcc1*q)
            min2=np.fabs(e*q)
            acc=ip&(2.0*p<np.where(min1<min2,min1,min2))
            e=np.where(acc,d,xMid)
            d=np.where(acc,p/q,xMid)
            step=np.where(np.fabs(d)>xAcc1,root+d,root+np.where(xMid>=0.0,np.fabs(xAcc1),-np.fabs(xAcc1)))
            fx,dead=fun(idx,np.where(conv,root,step));nev[idx]+=1    # a converged row: the final call f(root) counts
            evaluationNumber+=1
            status[idx[dead]]=MD
            fin=conv&~dead;status[idx[fin]]=OK;root_out[idx[fin]]=root[fin]
            k=~conv&~dead
            idx,xMin,fxMin,root,froot,xMax,fxMax,d,e=idx[k],root[k],froot[k],step[k],fx[k],xMax[k],fxMax[k],d[k],e[k]
    return status,root_out,f_lo,f_hi,nev

# ---- term-structure arithmetic and the mapping ----
def discount(rate,t):return 1.0/_exp(rate*t)
def implied_rate(compound,t):
    with np.errstate(all='ignore'):return np.where(compound==1.0,0.0,_log(compound)/t)
def zero_rate(rate,t):
    if t==0.0:t=RATE_DT
    return implied_rate(1.0/discount(rate,t),t)
def forward_rate(rate,t1,t2):return implied_rate(discount(rate,t1)/discount(rate,t2),t2-t1)
def unit(T,r,q,sigma):
    """(r', q', sigma') = (r*T, q*T, sigma*sqrt(T)) in this binary64 order (Amendment B item 3)."""
    r1=r*T
    q1=q*T
    s1=sigma*_sqrt(T)
    return r1,q1,s1
def mapped_inputs(T,r,q,sigma):
    r1,q1,s1=unit(T,r,q,sigma)
    return discount(r1,1.0),discount(q1,1.0),s1*s1*1.0

def tau_v(S,K,T,r,q):
    """Rounding band ((4 eps) D_r) max(F, K) of the mapped problem (spec 3.3)."""
    r1,q1,_=unit(T,r,q,1.0)
    D_r=discount(r1,1.0);D_q=discount(q1,1.0);F=(S*D_q)/D_r
    return ((4.0*QL_EPSILON)*D_r)*np.where(K>F,K,F)

# ---- BlackCalculator ----
class Black:
    """BlackCalculator(optionType, strike, forward, stdDev, discount) (blackcalculator.cpp:65-195, 197-428), elementwise;
    `call` is a bool array or True."""
    def __init__(self,call,strike,forward,stdDev,disc):
        self.call=call;self.strike=strike;self.forward=forward;self.stdDev=stdDev;self.discount=disc;self.variance=stdDev*stdDev
        with np.errstate(all='ignore'):
            big=stdDev>=QL_EPSILON;ks0=close(strike,0.0)
            d1=_log(forward/strike)/stdDev+0.5*stdDev
            d2=d1-stdDev
            k=d1.size;cum=norm_cdf(np.concatenate((d1,d2)));cum_d1=cum[:k];cum_d2=cum[k:];n_d1=norm_pdf(d1);n_d2=norm_pdf(d2)
            if not (big&~ks0).all():
                fk=close(forward,strike);s1=big&ks0;s2=~big&fk;s3=~big&~fk&(forward>strike);s4=~big&~fk&~(forward>strike);top=s1|s3
                d1=np.where(top,QL_MAX_REAL,np.where(s4,QL_MIN_REAL,np.where(s2,0.0,d1)));d2=np.where(top,QL_MAX_REAL,np.where(s4,QL_MIN_REAL,np.where(s2,0.0,d2)))
                cum_d1=np.where(top,1.0,np.where(s4,0.0,np.where(s2,0.5,cum_d1)));cum_d2=np.where(top,1.0,np.where(s4,0.0,np.where(s2,0.5,cum_d2)))
                half=M_SQRT_2*M_1_SQRTPI
                n_d1=np.where(top|s4,0.0,np.where(s2,half,n_d1));n_d2=np.where(top|s4,0.0,np.where(s2,half,n_d2))
        self.d1=d1;self.d2=d2
        self.x=strike;self.DxDstrike=1.0;self.DxDs=0.0
        if call is True:
            self.alpha=cum_d1;self.DalphaDd1=n_d1;self.beta=-cum_d2;self.DbetaDd2=-n_d2
        else:
            self.alpha=np.where(call,cum_d1,-1.0+cum_d1);self.DalphaDd1=n_d1;self.beta=np.where(call,-cum_d2,1.0-cum_d2);self.DbetaDd2=-n_d2
        self.flat=stdDev<=QL_EPSILON;self.any_flat=bool(self.flat.any())
    def value(self):return self.discount*(self.forward*self.alpha+self.x*self.beta)
    def _flat(self,call_atm,call_itm,call_otm,put_atm,put_itm_put,put_otm):
        a=self.alpha>=0;fk=close(self.forward,self.strike)
        return np.where(fk,np.where(a,call_atm,put_atm),np.where(self.forward>self.strike,np.where(a,call_itm,put_itm_put),np.where(a,call_otm,put_otm)))
    def _pick(self,flat,general):
        return np.where(self.flat,flat(),general) if self.any_flat else general
    def delta(self,spot):
        DforwardDs=self.forward/spot;temp=self.stdDev*spot
        DalphaDs=self.DalphaDd1/temp;DbetaDs=self.DbetaDd2/temp
        temp2=DalphaDs*self.forward+self.alpha*DforwardDs+DbetaDs*self.x+self.beta*self.DxDs
        d=self.discount
        return self._pick(lambda:self._flat(d*0.5*DforwardDs,d*1.0*DforwardDs,0.0,d*(-0.5)*DforwardDs,0.0,d*(-1.0)*DforwardDs),self.discount*temp2)
    def deltaForward(self):
        temp=self.stdDev*self.forward;DalphaDforward=self.DalphaDd1/temp;DbetaDforward=self.DbetaDd2/temp
        temp2=DalphaDforward*self.forward+self.alpha+DbetaDforward*self.x
        d=self.discount
        return self._pick(lambda:self._flat(d*0.5,d*1.0,0.0,d*(-0.5),0.0,d*(-1.0)),self.discount*temp2)
    def gamma(self,spot):
        DforwardDs=self.forward/spot;temp=self.stdDev*spot
        DalphaDs=self.DalphaDd1/temp;DbetaDs=self.DbetaDd2/temp
        D2alphaDs2=-DalphaDs/spot*(1+self.d1/self.stdDev)
        D2betaDs2=-DbetaDs/spot*(1+self.d2/self.stdDev)
        temp2=D2alphaDs2*self.forward+2.0*DalphaDs*DforwardDs+D2betaDs2*self.x+2.0*DbetaDs*self.DxDs
        return self._pick(lambda:0.0,self.discount*temp2)
    def theta(self,spot,maturity):
        if close(maturity,0.0):return np.zeros(self.forward.shape)
        return -(_log(self.discount)*self.value()+_log(self.forward/spot)*spot*self.delta(spot)+0.5*self.variance*spot*spot*self.gamma(spot))/maturity
    def vega(self,maturity):
        temp=_log(self.strike/self.forward)/self.variance
        DalphaDsigma=self.DalphaDd1*(temp+0.5);DbetaDsigma=self.DbetaDd2*(temp-0.5)
        temp2=DalphaDsigma*self.forward+DbetaDsigma*self.x
        return self._pick(lambda:0.0,self.discount*_sqrt(maturity)*temp2)
    def rho(self,maturity):
        DalphaDr=self.DalphaDd1/self.stdDev;DbetaDr=self.DbetaDd2/self.stdDev
        temp=DalphaDr*self.forward+self.alpha*self.forward+DbetaDr*self.x
        return self._pick(lambda:maturity*(self.deltaForward()*self.forward-self.value()),maturity*(self.discount*temp-self.value()))
    def dividendRho(self,maturity):
        DalphaDq=-self.DalphaDd1/self.stdDev;DbetaDq=-self.DbetaDd2/self.stdDev
        temp=DalphaDq*self.forward-self.alpha*self.forward+DbetaDq*self.x
        return self._pick(lambda:-maturity*self.discount*(self.deltaForward()/self.discount)*self.forward,maturity*self.discount*temp)
    def strikeSensitivity(self):
        temp=self.stdDev*self.strike;DalphaDstrike=-self.DalphaDd1/temp;DbetaDstrike=-self.DbetaDd2/temp
        temp2=DalphaDstrike*self.forward+DbetaDstrike*self.x+self.beta*self.DxDstrike
        d=self.discount
        return self._pick(lambda:self._flat(-d*0.5,-d*1.0,-d*0.0,d*0.5,d*0.0,d*1.0),self.discount*temp2)

# ---- AnalyticEuropeanEngine ----
GREEK_KEYS=('value','delta','gamma','rho','dividendRho','vega','theta')
def bsm_engine(call,S,K,D_r,D_q,variance,greeks=True):
    """AnalyticEuropeanEngine::calculate at t = 1 (the mapped problem)."""
    forwardPrice=S*D_q/D_r
    with np.errstate(all='ignore'):
        black=Black(call,K,forwardPrice,_sqrt(variance),D_r)
        if not greeks:return {'value':black.value()}
        return {'value':black.value(),'delta':black.delta(S),'gamma':black.gamma(S),'rho':black.rho(1.0),
                'dividendRho':black.dividendRho(1.0),'vega':black.vega(1.0),'theta':black.theta(S,1.0)}

# ---- Bjerksund-Stensland 1993: the phi functions are the text of optionlab.models ----
def _phi(S,gamma,H,I,rT,bT,variance):
    lam=(-rT+gamma*bT+0.5*gamma*(gamma-1.0)*variance)
    d=-(_log(S/H)+(bT+(gamma-0.5)*variance))/_sqrt(variance)
    kappa=2.0*bT/variance+(2.0*gamma-1.0)
    return _exp(lam)*(norm_cdf(d)-_pow((I/S),kappa)*norm_cdf(d-2.0*_log(I/S)/_sqrt(variance)))

def _phi_S(S,gamma,H,I,rT,bT,v):
    lsh=_log(S/H);lis=_log(I/S);sv=_sqrt(v)
    return _exp(bT*gamma-rT+((-1+gamma)*gamma*v)/2.)*((-(_pow(I/S,2*(gamma+bT/v))/(_exp(_sq(2*bT-v+2*gamma*v+4*lis+2*lsh)/(8.*v))*I))-1/(_exp(_sq(2*bT-v+2*gamma*v+2*lsh)/(8.*v))*S))/(M_SQRT2*M_SQRTPI*sv)+(_pow(I/S,2*(gamma+bT/v))*(2*bT+(-1+2*gamma)*v)*_erfc((2*bT-v+2*gamma*v+4*lis+2*lsh)/(2.*M_SQRT2*sv)))/(2.*I*v))

def _phi_SS(S,gamma,H,I,rT,bT,v):
    lsh=_log(S/H);lis=_log(I/S);sv=_sqrt(v)
    ex=_exp(_sq(2*bT-v+2*gamma*v+4*lis+2*lsh)/(8.*v))
    ey=_exp(_sq(2*bT+(-1+2*gamma)*v+2*lsh)/(8.*v))
    return (_exp(bT*gamma-rT+((-1+gamma)*gamma*v)/2.)*((M_SQRT2*I*v*sv)/ey+(2*M_SQRT2*_pow(I/S,2*(gamma+bT/v))*S*sv*(2*bT+(-1+2*gamma)*v))/ex-2*_sqrt(M_PI)*_pow(I/S,2*(gamma+bT/v))*S*(bT+gamma*v)*(2*bT+(-1+2*gamma)*v)*_erfc((2*bT-v+2*gamma*v+4*lis+2*lsh)/(2.*M_SQRT2*sv))+(M_SQRT2*I*sv*(bT+(-0.5+gamma)*v+lsh))/ey-(_pow(I/S,2*(gamma+bT/v))*S*sv*(2*bT-3*v+2*gamma*v+4*lis+2*lsh))/(M_SQRT2*ex)))/(2.*I*M_SQRTPI*_sq(S*v))

def _phi_gamma(S,gamma,H,I,rT,bT,v):
    lsh=_log(S/H);lis=_log(I/S);sv=_sqrt(v)
    return _exp(bT*gamma-rT+((-1+gamma)*gamma*v)/2)*(((-_exp(-_sq(2*bT-v+2*gamma*v+2*lsh)/(8*v))+_pow(I/S,-1+2*gamma+(2*bT)/v)/_exp(_sq(2*bT-v+2*gamma*v+4*lis+2*lsh)/(8*v)))*sv)/(M_SQRT2*M_SQRTPI)+((2*bT+(-1+2*gamma)*v)*_erfc((2*bT+(-1+2*gamma)*v+2*lsh)/(2.*M_SQRT2*sv)))/4.-(_pow(I/S,-1+2*gamma+(2*bT)/v)*_erfc((2*bT-v+2*gamma*v+4*lis+2*lsh)/(2.*M_SQRT2*sv))*(2*bT+(-1+2*gamma)*v+4*lis))/4.)

def _phi_H(S,gamma,H,I,rT,bT,v):
    lsh=_log(S/H)
    return (_exp(bT*gamma-rT+((-1+gamma)*gamma*v)/2.)*(I/_exp(_sq(2*bT-v+2*gamma*v+2*lsh)/(8.*v))-(_pow(I/S,2*(gamma+bT/v))*S)/_exp(_sq(2*bT-v+2*gamma*v+4*_log(I/S)+2*lsh)/(8.*v))))/(H*I*_sqrt(2*M_PI)*_sqrt(v))

def _phi_I(S,gamma,H,I,rT,bT,v):
    lsh=_log(S/H);lis=_log(I/S);sv=_sqrt(v)
    return (_exp(bT*gamma-rT+((-1+gamma)*gamma*v)/2.)*_pow(I/S,2*(gamma+bT/v))*S*((2*_sqrt(2/M_PI))/(_exp(_sq(2*bT-v+2*gamma*v+4*lis+2*lsh)/(8.*v))*sv)+(1-2*gamma-(2*bT)/v)*_erfc((2*bT-v+2*gamma*v+4*lis+2*lsh)/(2.*M_SQRT2*sv))))/(2.*I*I)

def _phi_rt(S,gamma,H,I,rT,bT,v):
    lsh=_log(S/H)
    return (_exp(bT*gamma-rT+((-1+gamma)*gamma*v)/2.)*(-(I*_erfc((2*bT-v+2*gamma*v+2*lsh)/(2.*_sqrt(2*v))))+_pow(I/S,2*(gamma+bT/v))*S*_erfc((2*bT-v+2*gamma*v+4*_log(I/S)+2*lsh)/(2.*_sqrt(2*v)))))/(2.*I)

def _phi_bt(S,gamma,H,I,rT,bT,v):
    lsh=_log(S/H);lis=_log(I/S);sv=_sqrt(v)
    return (_exp(bT*gamma-rT+((-1+gamma)*gamma*v)/2.)*(M_SQRT2*(-(I/_exp(_sq(2*bT-v+2*gamma*v+2*lsh)/(8.*v)))+(_pow(I/S,2*(gamma+bT/v))*S)/_exp(_sq(2*bT-v+2*gamma*v+4*lis+2*lsh)/(8.*v)))*sv+gamma*I*_sqrt(M_PI)*v*_erfc((2*bT-v+2*gamma*v+2*lsh)/(2.*M_SQRT2*sv))-M_SQRTPI*_pow(I/S,2*(gamma+bT/v))*S*_erfc((2*bT-v+2*gamma*v+4*lis+2*lsh)/(2.*M_SQRT2*sv))*(gamma*v+2*lis)))/(2.*I*_sqrt(M_PI)*v)

def _phi_v(S,gamma,H,I,rT,bT,v):
    lsh=_log(S/H);lis=_log(I/S);sv=_sqrt(v)
    er=_erfc((2*bT-v+2*gamma*v+4*lis+2*lsh)/(2.*M_SQRT2*sv))
    return (_exp(bT*gamma-rT+((-1+gamma)*gamma*v)/2.)*(((-1+gamma)*gamma*(I*_erfc((2*bT-v+2*gamma*v+2*lsh)/(2.*M_SQRT2*sv))-_pow(I/S,2*(gamma+bT/v))*S*er))/(2.*I)+(2*bT*_pow(I/S,-1+2*gamma+(2*bT)/v)*er*lis)/(v*v)+(2*bT+v-2*gamma*v+2*lsh)/(2.*_exp(_pow(2*bT+(-1+2*gamma)*v+2*lsh,2.0)/(8.*v))*M_SQRT2*M_SQRTPI*v*sv)-(_pow(I/S,-1+2*gamma+(2*bT)/v)*(2*bT+v-2*gamma*v+4*lis+2*lsh))/(2.*_exp(_sq(2*bT-v+2*gamma*v+4*lis+2*lsh)/(8.*v))*M_SQRT2*M_SQRTPI*v*sv)))/2.

BJS_KEYS=('value','delta','gamma','rho','dividendRho','vega','theta','strikeSensitivity','strikeGamma')

def _european_call(S,X,rfD,dD,variance,greeks):
    """europeanCallResults (lines 115-149) at t = 1."""
    forwardPrice=S*dD/rfD
    black=Black(True,X,forwardPrice,_sqrt(variance),rfD)
    if not greeks:return {'value':black.value()}
    res={'value':black.value(),'delta':black.delta(S),'gamma':black.gamma(S),'rho':black.rho(1.0),'dividendRho':black.dividendRho(1.0),
         'vega':black.vega(1.0),'theta':black.theta(S,1.0),'strikeSensitivity':black.strikeSensitivity()}
    res['strikeGamma']=res['gamma']*_sq(S/X)
    return res

def _immediate(S,X,greeks):
    """immediateExercise (lines 152-175)."""
    value=_max(0.0,S-X)
    if not greeks:return {'value':value}
    delta=np.where(S>=X,1.0,0.0);zero=np.zeros(S.shape)
    return {'value':value,'delta':delta,'gamma':zero,'rho':zero,'dividendRho':zero,'vega':zero,'theta':zero,'strikeSensitivity':-delta,'strikeGamma':zero}

def _american_formula(S,X,rfD,dD,variance,bT,rT,beta,BInfinity,B0,ht,I,greeks):
    """The 1993 price (lines 210-221) and, with greeks, the analytic greeks (lines 223-418), on the rows of that branch:
    the text of optionlab.models._american_call (B0Dq and B0Dr as np.where)."""
    tq=tr=tv=1.0;dtq=dtr=dtv=DT_DAY
    results={}
    pSb=_phi(S,beta,I,I,rT,bT,variance);pS1II=_phi(S,1.0,I,I,rT,bT,variance);pS1XI=_phi(S,1.0,X,I,rT,bT,variance)
    powb=_pow(S/I,beta)
    results['value']=((I-X)*powb*(1-pSb)+S*pS1II-S*pS1XI-X*_phi(S,0.0,I,I,rT,bT,variance)+X*_phi(S,0.0,X,I,rT,bT,variance))
    if not greeks:return results
    sSb=_phi_S(S,beta,I,I,rT,bT,variance);sS1II=_phi_S(S,1.0,I,I,rT,bT,variance);sS1XI=_phi_S(S,1.0,X,I,rT,bT,variance)
    results['delta']=((I-X)*_pow(S/I,beta-1)*beta/I*(1-pSb)-(I-X)*powb*sSb+pS1II+S*sS1II-pS1XI-S*sS1XI
                      -X*_phi_S(S,0.0,I,I,rT,bT,variance)+X*_phi_S(S,0.0,X,I,rT,bT,variance))
    root=_sqrt(_sq(bT/variance-0.5)+2.0*rT/variance)
    betaDq=tq*(1/variance-1/(2*root)*2*(bT/variance-0.5)/variance)
    BInfinityDq=-X/_sq(beta-1.0)*betaDq
    B0Dq=np.where(dD<=rfD,0.0,X*_log(rfD)/_sq(_log(dD))*tq)
    htDq=tq*B0/(BInfinity-B0)-(bT+2.0*_sqrt(variance))*(B0Dq*(BInfinity-B0)-B0*(BInfinityDq-B0Dq))/_sq(BInfinity-B0)
    IDq=B0Dq+(BInfinityDq-B0Dq)*(1-_exp(ht))-(BInfinity-B0)*_exp(ht)*htDq
    hb=_phi_H(S,beta,I,I,rT,bT,variance);ib=_phi_I(S,beta,I,I,rT,bT,variance);gb=_phi_gamma(S,beta,I,I,rT,bT,variance)
    btb=_phi_bt(S,beta,I,I,rT,bT,variance)
    h1=_phi_H(S,1.0,I,I,rT,bT,variance);i1=_phi_I(S,1.0,I,I,rT,bT,variance);bt1=_phi_bt(S,1.0,I,I,rT,bT,variance)
    i1x=_phi_I(S,1.0,X,I,rT,bT,variance);bt1x=_phi_bt(S,1.0,X,I,rT,bT,variance)
    h0=_phi_H(S,0.0,I,I,rT,bT,variance);i0=_phi_I(S,0.0,I,I,rT,bT,variance);bt0=_phi_bt(S,0.0,I,I,rT,bT,variance)
    i0x=_phi_I(S,0.0,X,I,rT,bT,variance);bt0x=_phi_bt(S,0.0,X,I,rT,bT,variance)
    results['dividendRho']=((IDq*powb+(I-X)*powb*(betaDq*_log(S/I)-beta*1/I*IDq))*(1-pSb)
                            -(I-X)*powb*(hb*IDq+ib*IDq+gb*betaDq-btb*tq)
                            +S*(h1*IDq+i1*IDq-bt1*tq)
                            -S*(i1x*IDq-bt1x*tq)
                            -X*(h0*IDq+i0*IDq-bt0*tq)
                            +X*(i0x*IDq-bt0x*tq))
    betaDr=tr*(-1/variance+1/(2*root)*2*((bT/variance-0.5)/variance+1/variance))
    BInfinityDr=-X/_sq(beta-1.0)*betaDr
    B0Dr=np.where(dD<=rfD,0,-X*tr/_log(dD))
    htDr=-tr*B0/(BInfinity-B0)-(bT+2.0*_sqrt(variance))*(B0Dr*(BInfinity-B0)-B0*(BInfinityDr-B0Dr))/_sq(BInfinity-B0)
    IDr=B0Dr+(BInfinityDr-B0Dr)*(1-_exp(ht))-(BInfinity-B0)*_exp(ht)*htDr
    results['rho']=((IDr*powb+(I-X)*powb*(betaDr*_log(S/I)-beta/I*IDr))*(1-pSb)
                    -(I-X)*powb*(hb*IDr+ib*IDr+gb*betaDr+_phi_rt(S,beta,I,I,rT,bT,variance)*tr+btb*tr)
                    +S*(h1*IDr+i1*IDr+_phi_rt(S,1.0,I,I,rT,bT,variance)*tr+bt1*tr)
                    -S*(i1x*IDr+_phi_rt(S,1.0,X,I,rT,bT,variance)*tr+bt1x*tr)
                    -X*(h0*IDr+i0*IDr+_phi_rt(S,0.0,I,I,rT,bT,variance)*tr+bt0*tr)
                    +X*(i0x*IDr+_phi_rt(S,0.0,X,I,rT,bT,variance)*tr+bt0x*tr))
    beta=(0.5-bT/variance)+_sqrt(_sq(bT/variance-0.5)+2.0*rT/variance)
    varianceDv=2*_sqrt(variance*tv)
    betaDv=bT/_sq(variance)*varianceDv+-1/(2*_sqrt(_sq(bT/variance-0.5)+2.0*rT/variance))*(2*(bT/variance-0.5)*bT*varianceDv/_sq(variance)+2*rT/_sq(variance)*varianceDv)
    BInfinityDv=-X/_sq(beta-1.0)*betaDv
    htDv=-1/_sqrt(variance)*varianceDv*B0/(BInfinity-B0)+(bT+2*_sqrt(variance))*B0/_sq(BInfinity-B0)*BInfinityDv
    IDv=BInfinityDv*(1-_exp(ht))-(BInfinity-B0)*_exp(ht)*htDv
    results['vega']=((IDv*powb+(I-X)*powb*(betaDv*_log(S/I)-beta/I*IDv))*(1-pSb)
                     -(I-X)*powb*(hb*IDv+ib*IDv+gb*betaDv+_phi_v(S,beta,I,I,rT,bT,variance)*varianceDv)
                     +S*(h1*IDv+i1*IDv+_phi_v(S,1.0,I,I,rT,bT,variance)*varianceDv)
                     -S*(i1x*IDv+_phi_v(S,1.0,X,I,rT,bT,variance)*varianceDv)
                     -X*(h0*IDv+i0*IDv+_phi_v(S,0.0,I,I,rT,bT,variance)*varianceDv)
                     +X*(i0x*IDv+_phi_v(S,0.0,X,I,rT,bT,variance)*varianceDv))
    results['gamma']=((I-X)*_pow(S/I,beta-2)*beta*(beta-1)/_sq(I)*(1-pSb)
                      -2*(I-X)*_pow(S/I,beta-1)*beta/I*sSb
                      -(I-X)*powb*_phi_SS(S,beta,I,I,rT,bT,variance)
                      +2*sS1II+S*_phi_SS(S,1.0,I,I,rT,bT,variance)
                      -2*sS1XI-S*_phi_SS(S,1.0,X,I,rT,bT,variance)
                      -X*_phi_SS(S,0.0,I,I,rT,bT,variance)+X*_phi_SS(S,0.0,X,I,rT,bT,variance))
    vol=_sqrt(variance/tv)
    thetaPerDay=-(0.5*results['vega']*vol/tv*dtv+results['rho']*rT/(tr*tr)*dtr+results['dividendRho']*(rT-bT)/(tq*tq)*dtq)
    results['theta']=365*thetaPerDay
    results['strikeSensitivity']=results['value']/X-S/X*results['delta']
    results['strikeGamma']=results['gamma']*_sq(S/X)
    return results

def _american_call(S,X,rfD,dD,variance,euro,greeks):
    """americanCallApproximation (lines 177-429) with tq = tr = tv = 1; `euro` holds europeanResults of the same rows."""
    bT=_log(dD/rfD);rT=_log(1.0/rfD)
    beta=(0.5-bT/variance)+_sqrt(_sq(bT/variance-0.5)+2.0*rT/variance)
    BInfinity=beta/(beta-1.0)*X
    B0=np.where(bT==rT,X,_max(X,rT/(rT-bT)*X))
    ht=-(bT+2.0*_sqrt(variance))*B0/(BInfinity-B0)
    I=B0+(BInfinity-B0)*(1-_exp(ht))
    fwd=S*dD/rfD
    q=_log(I/fwd)/_sqrt(variance)
    imm=S>=I;eu=~imm&(q>12.5);am=~imm&~eu
    keys=BJS_KEYS if greeks else ('value',)
    results={k:np.array(euro[k],dtype=np.float64) for k in keys}         # q > 12.5: the European results
    if imm.any():
        r=_immediate(S[imm],X[imm],greeks)
        for k in keys:results[k][imm]=r[k]
    if am.any():
        r=_american_formula(*(a[am] for a in (S,X,rfD,dD,variance,bT,rT,beta,BInfinity,B0,ht,I)),greeks)
        for k in keys:results[k][am]=r[k]
    low=results['value']<euro['value']
    if low.any():
        for k in keys:results[k]=np.where(low,euro[k],results[k])
    return results

def bjs_engine(call,S,K,D_r,D_q,variance,greeks=True):
    """BjerksundStenslandApproximationEngine::calculate (lines 432-506) for the mapped problem (tr = tq = 1).
    Returns (results, defect); `defect` marks the QL_FAIL "double-boundary case r<q<0 for a call given" rows."""
    with np.errstate(all='ignore'):
        spot=np.where(call,S,K);strike=np.where(call,K,S);riskFreeDiscount=np.where(call,D_r,D_q);dividendDiscount=np.where(call,D_q,D_r)
        defect=(dividendDiscount>1.0)&(riskFreeDiscount>dividendDiscount)
        keys=BJS_KEYS if greeks else ('value',)
        euro=_european_call(spot,strike,riskFreeDiscount,dividendDiscount,variance,greeks)
        res={k:np.array(euro[k],dtype=np.float64) for k in keys}
        am=~((dividendDiscount>=1.0)&(dividendDiscount>=riskFreeDiscount))
        if am.any():
            sub=_american_call(*(a[am] for a in (spot,strike,riskFreeDiscount,dividendDiscount,variance)),{k:euro[k][am] for k in keys},greeks)
            for k in keys:res[k][am]=sub[k]
        ex=res['value']<(spot-strike)*(1+10*QL_EPSILON)
        if ex.any():
            r=_immediate(spot[ex],strike[ex],greeks)
            for k in keys:res[k][ex]=r[k]
        if greeks:
            put=~np.asarray(call,dtype=bool)
            if put.any():
                sw=lambda a,b:(np.where(put,res[b],res[a]),np.where(put,res[a],res[b]))
                res['delta'],res['strikeSensitivity']=sw('delta','strikeSensitivity')
                res['gamma'],res['strikeGamma']=sw('gamma','strikeGamma')
                res['rho'],res['dividendRho']=sw('rho','dividendRho')
                tr=tq=1.0;res['rho']=np.where(put,res['rho']*(tr/tq),res['rho']);res['dividendRho']=np.where(put,res['dividendRho']*(tq/tr),res['dividendRho'])
    return res,defect

# ---- CRR binomial engine ----
def crr_tree(T,r,q,sigma,steps):
    """Tree constants of BinomialVanillaEngine<CoxRossRubinstein> for the mapped problem (models.crr_mapped_tree)."""
    with np.errstate(all='ignore'):
        r1,q1,s1=unit(T,r,q,sigma)
        v=s1
        rz=implied_rate(1.0/discount(r1,1.0),1.0)
        qz=implied_rate(1.0/discount(q1,1.0),1.0)
        maturity=1.0;dt=maturity/steps
        drift=forward_rate(rz,0.0,0.0+RATE_DT)-forward_rate(qz,0.0,0.0+RATE_DT)-0.5*v*v
        driftPerStep=drift*dt
        dx=_sqrt(v*v*(0.0+dt)-v*v*0.0)
        disc=_exp(-rz*dt)
        theta_rates=(zero_rate(r1,0.0),zero_rate(q1,0.0),s1)
    return dx,driftPerStep,disc,theta_rates

def crr_engine(call,S,K,dx,driftPerStep,disc,steps,american=True,theta_rates=None):
    """CoxRossRubinstein tree and BlackScholesLattice rollback on (N+1) x rows arrays, in blocks of CRR_BLOCK rows; with
    theta_rates also the engine greeks (binomialengine.hpp:115-171). Returns (results, defect); `defect` marks the
    QL_REQUIRE "negative probability" rows (pu outside [0, 1], NaN included)."""
    n=S.size;value=np.empty(n);greeks=theta_rates is not None
    if greeks:delta=np.empty(n);gamma=np.empty(n);theta=np.empty(n)
    with np.errstate(all='ignore'):
        if steps<2:return ({'value':np.full(n,np.nan)},np.ones(n,bool))
        pu=0.5+0.5*driftPerStep/dx
        pd=1.0-pu
        defect=~(pu<=1.0)|~(pu>=0.0)
        jj=np.arange(-steps,steps+1,dtype=np.float64)[:,None]
        for a in range(0,n,CRR_BLOCK):
            b=min(n,a+CRR_BLOCK);Sb=S[a:b];Kb=K[a:b]
            growth=Sb*_exp(jj*dx[a:b])                     # underlying(i, index) = x0*exp((2 index - i) dx); row j + steps
            pay=np.maximum(np.where(call[a:b],growth-Kb,Kb-growth),0.0)
            values=pay[0::2].copy()                         # reset at maturity: node 2j - steps
            pub=pu[a:b];pdb=pd[a:b];db=disc[a:b];va2=va1=None
            for i in range(steps-1,-1,-1):
                new=(pdb*values[:i+1]+pub*values[1:i+2])*db
                if american:np.maximum(new,pay[steps-i:steps+i+1:2],out=new)
                values=new
                if i==2:va2=values
                elif i==1:va1=values
            p0=values[0];value[a:b]=p0
            if greeks:
                p2u,p2m,p2d=va2[2],va2[1],va2[0];s2u,s2m,s2d=growth[steps+2],growth[steps],growth[steps-2]
                delta2u=(p2u-p2m)/(s2u-s2m);delta2d=(p2m-p2d)/(s2m-s2d)
                g=(delta2u-delta2d)/((s2u-s2d)/2)
                p1u,p1d=va1[1],va1[0];s1u,s1d=growth[steps+1],growth[steps-1]
                dl=(p1u-p1d)/(s1u-s1d)
                r,q,v=(x[a:b] for x in theta_rates);u=Sb
                delta[a:b]=dl;gamma[a:b]=g;theta[a:b]=r*p0-(r-q)*u*dl-0.5*v*v*u*u*g
    out={'value':value}
    if greeks:out.update(delta=delta,gamma=gamma,theta=theta)
    return out,defect

def crr_result(call,S,K,T,r,q,sigma,steps,american=True,greeks=False):
    dx,dps,disc,rates=crr_tree(T,r,q,sigma,steps)
    return crr_engine(call,S,K,dx,dps,disc,steps,american,rates if greeks else None)

def crr_price(side,S,K,T,r,q,sigma,steps,american=True):
    """CRR(steps) value through the mapping; (value, defect)."""
    side=np.asarray(side);res,defect=crr_result(side==0,*(np.asarray(a,dtype=np.float64) for a in (S,K,T)),r,q,np.asarray(sigma,dtype=np.float64),steps,american)
    return res['value'],defect

# ---- per-model price through the mapping ----
def model_value(model,call,S,K,T,r,q,sigma,params):
    """Engine value of `model` at sigma through the unit-maturity mapping: (value, defect). The test-only counters count
    the call with its element count (Amendment G4.8)."""
    counters.bump(model,np.size(S))
    if model=='crr':
        res,defect=crr_result(call,S,K,T,r,q,sigma,params.crr_steps);return res['value'],defect
    with np.errstate(all='ignore'):D_r,D_q,variance=mapped_inputs(T,r,q,sigma)
    if model=='bsm':return bsm_engine(call,S,K,D_r,D_q,variance,greeks=False)['value'],np.zeros(S.shape,bool)
    if model=='bjs':
        res,defect=bjs_engine(call,S,K,D_r,D_q,variance,greeks=False);return res['value'],defect
    raise ValueError('unknown model')

def sigma_lo(model,side,T,r,q,params):
    """Brent's lower end xMin (spec 3.4), elementwise (models.sigma_lo)."""
    hr=params.h_r;T=np.asarray(T,dtype=np.float64)
    if model=='bsm':return np.full(T.shape,1e-4)
    if model=='alo':                    # E-ALO-1: the shared scalar form per element (it calls alo_equation)
        from optionlab.models import sigma_lo as s_lo
        sd,Tb,rb,qb=np.broadcast_arrays(np.asarray(side),T,np.asarray(r,dtype=np.float64),np.asarray(q,dtype=np.float64))
        return np.array([s_lo('alo',int(a),b,c,d,params) for a,b,c,d in zip(sd.ravel().tolist(),Tb.ravel().tolist(),rb.ravel().tolist(),qb.ravel().tolist())],np.float64).reshape(Tb.shape)
    if model=='crr':return np.maximum(1e-4,1.001*(abs(r-q)+hr)*_sqrt(T/params.crr_steps))
    b=np.where(np.asarray(side)==0,r-q,q-r)
    if model=='baw':                    # Appendix G-BAW R9, R12 F3: max(1e-4, sigma_trig) (models.sigma_lo, same operation order)
        with np.errstate(invalid='ignore'):return np.maximum(1e-4,np.where(b<0.0,1.001*(np.fabs(b)+hr)*_sqrt(T)/2.0,0.0))
    trig=np.where(b<0.0,1.001*(np.fabs(b)+hr)*_sqrt(T)/2.0,0.0)
    return np.maximum(np.maximum(1e-4,trig),_sqrt(2.0*(np.fabs(b)+hr)/params.kappa_cap))

def crr_domain_ok(T,r,q,params):
    """CRR pre-engine domain check (spec 3.4), elementwise (models.crr_domain_ok)."""
    sdt=_sqrt(np.asarray(T,dtype=np.float64)/params.crr_steps);b=abs(r-q)+params.h_r
    g=lambda s:s-(s*s/2.0+b)*sdt
    return (g(sigma_lo('crr',0,T,r,q,params))>=0.0)&(g(params.sigma_hi+params.h_sigma)>=0.0)

# ---- price and greeks (spec 3.6) with the order-5 check ----
class Checker:
    """The order-5 evaluation check of reference.Checker on many rows: a row that failed (`dead`) records no later band
    hit, as the scalar check raises at its first failure."""
    def __init__(self,tau):self.tau=tau;self.dead=np.zeros(tau.shape,bool);self.band=np.zeros(tau.shape,bool)
    def __call__(self,V,defect=None):
        with np.errstate(invalid='ignore'):
            bad=~np.isfinite(V)|(V<-self.tau)
            if defect is not None:bad|=defect
            alive=~self.dead
            self.band|=alive&~bad&(V<0.0);self.dead|=alive&bad
        return V

def _at(x,sel):
    """Rows `sel` of a per-row array; a scalar (one r or q for every row) is returned as is."""
    return x[sel] if np.ndim(x) else x

def _greeks(model,call,S,K,T,r,q,iv,lo,params,check):
    """(iv, price, delta, gamma, theta, vega, rho) in output units (reference._engine_greeks); rows that fail the check are
    marked in `check.dead`."""
    counters.bump(model,np.size(S))          # the engine greek call (the CRR bumps count in model_value)
    with np.errstate(all='ignore'):
        if model in ('bsm','bjs'):
            D_r,D_q,variance=mapped_inputs(T,r,q,iv)
            if model=='bsm':e=bsm_engine(call,S,K,D_r,D_q,variance);defect=None
            else:e,defect=bjs_engine(call,S,K,D_r,D_q,variance)
            p=check(e['value'],defect)
            sq=_sqrt(T)
            vega=(sq*e['vega'])*0.01;rho=(T*e['rho'])*0.01
        else:
            e,defect=crr_result(call,S,K,T,r,q,iv,params.crr_steps,greeks=True);p=check(e['value'],defect)
            h=params.h_sigma;hr=params.h_r
            def V(s,rr,m=None):
                if m is None:v,dft=model_value('crr',call,S,K,T,rr,q,s,params);return check(v,dft)
                out=np.full(S.shape,np.nan);sel=np.nonzero(m)[0]
                if sel.size:
                    v,dft=model_value('crr',call[sel],S[sel],K[sel],T[sel],_at(rr,sel),_at(q,sel),s[sel],params);sub=Checker(check.tau[sel])
                    sub.dead=check.dead[sel].copy();sub(v,dft);check.band[sel]|=sub.band;check.dead[sel]|=sub.dead;out[sel]=v
                return out
            fwd=iv-h<lo
            up=V(iv+h,r);dn=V(iv-h,r,~fwd)
            vega_b=np.where(fwd,(up-p)/h,(up-dn)/(2.0*h))
            rho_b=(V(iv,r+hr)-V(iv,r-hr))/(2.0*hr)
            vega=vega_b*0.01;rho=rho_b*0.01
        theta=(e['theta']/T)/365.0
        vals=(iv,p,e['delta'],e['gamma'],theta,vega,rho)
    return vals

def price_and_greeks(model,side,S,K,T,r,q,sigma,params):
    """Price and greeks in output units at sigma (reference.price_and_greeks, elementwise): a dict of arrays with the
    FIELDS, `rounding_band` and `dead` (an order-5 failure)."""
    side=np.asarray(side);S,K,T,sigma=(np.asarray(a,dtype=np.float64) for a in (S,K,T,sigma))
    check=Checker(tau_v(S,K,T,r,q));vals=_greeks(model,side==0,S,K,T,r,q,sigma,sigma_lo(model,side,T,r,q,params),params,check)
    return {**dict(zip(FIELDS,vals)),'rounding_band':check.band,'dead':check.dead}

# ---- one model over the prepared rows (spec 3.3 status order) ----
def evaluate_model(model,prep,params):
    """r and q are the prepared per-row columns (spec 3.1; Amendment C item 3), never the scalar case parameters."""
    if model=='baw':return evaluate_baw(prep,params)
    if model=='alo':return evaluate_alo(prep,params)     # G-ALO2 part B (Task A5)
    n=prep['n'];side=prep['side'];S,K,T,bid,ask,r,q=(prep[k] for k in ('S','K','T','bid','ask','r','q'))
    hi=params.sigma_hi
    status=np.full(n,OK,np.uint8);flags=np.zeros(n,np.uint8);vals={f:np.full(n,np.nan) for f in FIELDS}
    with np.errstate(invalid='ignore'):
        finite=np.isfinite(S)&np.isfinite(K)&np.isfinite(T)&np.isfinite(bid)&np.isfinite(ask)
        bad=(side>1)|~finite|(S<=0.0)|(K<=0.0);status[bad]=CODE['INVALID_INPUT'];live=~bad
        for cond,name in ((T<=0.0,'EXPIRED'),(bid<=0.0,'NO_BID'),(ask<bid,'CROSSED')):
            m=live&cond;status[m]=CODE[name];live&=~m
    idx=np.nonzero(live)[0]
    if idx.size:
        lo=sigma_lo(model,side[idx],T[idx],r[idx],q[idx],params);dom=lo>=hi
        if model=='crr':dom|=~crr_domain_ok(T[idx],r[idx],q[idx],params)
        status[idx[dom]]=MD;idx=idx[~dom];lo=lo[~dom]
    if idx.size==0:return {'status':status,'flags':flags,**vals}
    call=side[idx]==0;S_,K_,T_,r_,q_=S[idx],K[idx],T[idx],r[idx],q[idx];mid=(bid[idx]+ask[idx])/2.0
    check=Checker(tau_v(S_,K_,T_,r_,q_))
    def fun(j,x):
        v,defect=model_value(model,call[j],S_[j],K_[j],T_[j],r_[j],q_[j],x,params)
        sub=Checker(check.tau[j]);sub(v,defect);check.band[j]|=sub.band;check.dead[j]|=sub.dead
        return v-mid[j],sub.dead
    st,iv,fa,fb,_=brent(fun,lo,np.full(idx.size,hi),(lo+hi)/2.0)
    fl=np.zeros(idx.size,np.uint8);solved=st!=MD
    with np.errstate(invalid='ignore'):
        width=1e-9*np.where(mid>1.0,mid,1.0)
        fl[solved&((np.fabs(fa)<=width)|(np.fabs(fb)<=width))]|=FLAG_BOUNDARY_AMBIGUOUS
        intrinsic=np.where(call,S_-K_,K_-S_);fl[(st==BELOW)&(mid<np.where(0.0>intrinsic,0.0,intrinsic))]|=FLAG_BELOW_INTRINSIC
    ok=np.nonzero(st==OK)[0]
    if ok.size:
        sub=Checker(check.tau[ok])
        g=_greeks(model,call[ok],S_[ok],K_[ok],T_[ok],r_[ok],q_[ok],iv[ok],lo[ok],params,sub)
        check.band[ok]|=sub.band
        good=~sub.dead
        for v in g:good&=np.isfinite(v)
        st[ok[~good]]=MD;keep=ok[good];rows=idx[keep]
        for f,v in zip(FIELDS,g):vals[f][rows]=v[good]
        fl[keep[g[5][good]*100.0<1e-12]]|=FLAG_FLAT_VEGA
    fl[check.band]|=FLAG_ROUNDING_BAND
    status[idx]=st;flags[idx]=fl
    return {'status':status,'flags':flags,**vals}

# ---- Barone-Adesi-Whaley (spec Amendment G2; the approved record Appendix G-BAW, R4 item 9, R6-R8, R12 F1-F7) ----
# The shared scalar functions on `math` run per element (N1a: no NumPy form exists): baw_admit before every in-scope
# evaluation (optionlab.reference.baw_admitted, which calls optionlab.baw_admit.baw_admit) and the S* transcription
# (optionlab.baw_admit.sstar, with the case cap and its run-defect checks). The engine value of
# baroneadesiwhaleyengine.cpp:162-229 given S* (the Black value plus a (S/S*)^Q, or the exercise value) and the European
# branch (lines 167-191) are vectorized over every evaluation point of the rows. The greek stencils use the record's rule in
# optionlab.reference.baw_greeks (the one stencil rule): a first pass per row records the points and side tests (each side
# test admits the point and computes its S* once), the values of all points of all rows are computed in one vectorized
# call, and a second pass replays the rule with those values and the memoized sides, so the order of the order-5 checks,
# the exclusions (bit 64), the unresolved stencils (bit 16) and the stencil flags (bit 32) is py-reference's.
# Count rule (test-only counters, G4.8): py-optimized counts the engine-value elements it computes, which is its own work:
# each admitted Brent evaluation that reaches the vectorized value (a point whose S* iteration raises a QuantLib check is
# not counted; py-reference counts it) and each distinct greek point of pass 1 (a repeated point counts once; points
# after the first order-5 value of a row also count, because pass 1 does not know the values). The exact count rule of
# G3.7 binds py-reference and C only (spec G4.8: for the other variants the counters show that only the selected model
# runs); py-reference's per-row `engine_evals` stays the reference count.
def close_n(x,y,n):
    """QuantLib close(x, y, n) (math/comparison.hpp:78-90), elementwise (baw_admit.close_n)."""
    x=np.asarray(x,dtype=np.float64);y=np.asarray(y,dtype=np.float64)
    with np.errstate(all='ignore'):
        diff=np.fabs(x-y);tolerance=n*QL_EPSILON
        return (x==y)|np.where((x==0.0)|(y==0.0),diff<tolerance*tolerance,(diff<=tolerance*np.fabs(x))&(diff<=tolerance*np.fabs(y)))

def baw_values(call,S,K,D_r,D_q,v,Sk,eur,greeks=False):
    """BaroneAdesiWhaleyApproximationEngine::calculate at t = 1 for many points (optionlab.baw.engine), given S* of each
    American-branch point (`eur`: the European branch, line 167). Returns (value, bad, engine greeks or None): `bad` marks
    a point where the engine raises before its value (line 162 S <= 0, the BlackCalculator checks of
    blackcalculator.cpp:66-75); the greeks (European branch only, as the engine supplies them) when `greeks`."""
    with np.errstate(all='ignore'):
        forwardPrice=S*D_q/D_r;sd=_sqrt(v)
        bad=~(S>0.0)|~(K>=0.0)|~(forwardPrice>0.0)|~(sd>=0.0)|~(D_r>0.0)
        black=Black(call,K,forwardPrice,sd,D_r);bv=black.value()
        forwardSk=Sk*D_q/D_r
        d1=(_log(forwardSk/K)+0.5*v)/_sqrt(v)
        n=2.0*_log(D_q/D_r)/v
        Kc=np.where(close_n(D_r,1.0,1000),2.0/v,-2.0*_log(D_r)/(v*(1.0-D_r)))
        root=_sqrt(((n-1.0)*(n-1.0))+4.0*Kc)
        Q=np.where(call,(-(n-1.0)+root)/2.0,(-(n-1.0)-root)/2.0)
        a=np.where(call,(Sk/Q)*(1.0-D_q*norm_cdf(d1)),(-(Sk/Q))*(1.0-D_q*norm_cdf(-d1)))
        cont=np.where(call,S<Sk,S>Sk)
        amer=np.where(cont,bv+a*_pow(S/Sk,Q),np.where(call,S-K,K-S))
        value=np.where(eur,bv,amer)
        g=None
        if greeks:g={'delta':black.delta(S),'gamma':black.gamma(S),'rho':black.rho(1.0),'dividendRho':black.dividendRho(1.0),'vega':black.vega(1.0),'theta':black.theta(S,1.0)}
    return value,bad,g

def _baw_point(side,S,K,T,r,q,s,params,reason):
    """One evaluation point through the shared scalar functions: baw_admit (AdmitExcluded(reason) when not admitted) and,
    for an American-branch point, the S* transcription. Returns (D_r, D_q, v, S* or None for the European branch); a
    QuantLib check inside the S* iteration raises ModelDefect, a run defect BawRunDefect."""
    from optionlab.reference import baw_admitted
    from optionlab.models import mapped_inputs as m_inputs
    from optionlab.baw_admit import sstar
    ins=baw_admitted(side,S,K,T,r,q,s,reason);D_r,D_q,v=m_inputs(T,r,q,s)
    if not ins:return D_r,D_q,v,None
    return D_r,D_q,v,sstar(side,K,D_r,D_q,v,params.baw_newton_max,params.baw_plant_nan_sstar)

class _Point:
    """A point of the record's stencil rule with its side-test outcome (side text, or the exception that the side test raised)."""
    __slots__=('key','D_r','D_q','v','Sk','side','error','index')

def _baw_plan(side,S,K,T,r,q,iv,params):
    """First pass of the stencil rule for one OK row: the side tests run (admission and S*, once per distinct point); the
    engine values are placeholders. Returns (points in evaluation order, memo of side tests)."""
    from optionlab.reference import baw_greeks, StencilUnresolved
    from optionlab.models import ModelDefect, BawRunDefect, RunDefect, AloRunDefect
    memo={};order=[]
    def sideof(S_,T_,r_,s_):
        k=(S_,T_,r_,s_);p=memo.get(k)
        if p is None:
            p=_Point();p.key=k;p.error=None;p.side=None;p.index=None;memo[k]=p
            try:
                p.D_r,p.D_q,p.v,p.Sk=_baw_point(side,S_,K,T_,r_,q,s_,params,'bump')
                p.side='european' if p.Sk is None else 'continuation' if ((S_<p.Sk) if side==0 else (S_>p.Sk)) else 'exercise'
            except RunDefect:raise
            except ModelDefect as exc:p.error=exc
        if p.error is not None:raise p.error
        return p.side
    def value(S_,T_,r_,s_):order.append(memo[(S_,T_,r_,s_)]);return 0.0
    def result(S_,T_,r_,s_):
        p=memo[(S_,T_,r_,s_)];order.append(p)
        return {'value':0.0} if p.side!='european' else dict.fromkeys(('value','delta','gamma','theta','vega','rho','dividendRho'),0.0)
    try:baw_greeks(side,S,K,T,r,q,iv,params,value,result,lambda V:V,sideof=sideof)
    except RunDefect:raise
    except (StencilUnresolved,ModelDefect):pass       # the second pass meets the same outcome at the same position
    return order,memo

def evaluate_baw(prep,params):
    """BAW over the prepared rows with py-reference's status order (reference._evaluate): pre-engine statuses, sigma_lo
    domain, the volatility-free baw_admit row check (MODEL_DOMAIN, bit 64), the masked Brent with baw_admit before each
    evaluation (an exclusion stops the row: MODEL_DOMAIN, bit 64), then the record's greeks. A BawRunDefect propagates."""
    from optionlab.reference import (baw_greeks, Checker as RChecker, tau_v as rtau, EngineDomain, StencilUnresolved, FLAG_ADMIT_EXCLUDED,
                                     FLAG_STENCIL_UNRESOLVED)
    from optionlab.models import ModelDefect, BawRunDefect, RunDefect, AloRunDefect, AdmitExcluded
    from optionlab.baw_admit import baw_admit_rates
    from optionlab.mapping import unit as m_unit
    n=prep['n'];side=prep['side'];S,K,T,bid,ask,r,q=(prep[k] for k in ('S','K','T','bid','ask','r','q'))
    hi=params.sigma_hi
    status=np.full(n,OK,np.uint8);flags=np.zeros(n,np.uint8);vals={f:np.full(n,np.nan) for f in FIELDS}
    with np.errstate(invalid='ignore'):
        finite=np.isfinite(S)&np.isfinite(K)&np.isfinite(T)&np.isfinite(bid)&np.isfinite(ask)
        bad=(side>1)|~finite|(S<=0.0)|(K<=0.0);status[bad]=CODE['INVALID_INPUT'];live=~bad
        for cond,name in ((T<=0.0,'EXPIRED'),(bid<=0.0,'NO_BID'),(ask<bid,'CROSSED')):
            m=live&cond;status[m]=CODE[name];live&=~m
    idx=np.nonzero(live)[0]
    if idx.size:
        lo=sigma_lo('baw',side[idx],T[idx],r[idx],q[idx],params);dom=lo>=hi
        status[idx[dom]]=MD;idx=idx[~dom];lo=lo[~dom]
    if idx.size:                                    # pre-engine row check (reason `row` in py-reference)
        excl=np.zeros(idx.size,bool)
        for k,(sd,Tk,rk,qk) in enumerate(zip(side[idx].tolist(),T[idx].tolist(),r[idx].tolist(),q[idx].tolist())):
            r1,q1,_=m_unit(Tk,rk,qk,1.0);ins,adm=baw_admit_rates(sd,r1,q1);excl[k]=ins and not adm
        status[idx[excl]]=MD;flags[idx[excl]]=FLAG_ADMIT_EXCLUDED;idx=idx[~excl];lo=lo[~excl]
    if idx.size==0:return {'status':status,'flags':flags,**vals}
    call=side[idx]==0;S_,K_,T_,r_,q_=S[idx],K[idx],T[idx],r[idx],q[idx];mid=(bid[idx]+ask[idx])/2.0
    rows=list(zip(side[idx].tolist(),S_.tolist(),K_.tolist(),T_.tolist(),r_.tolist(),q_.tolist()))
    check=Checker(tau_v(S_,K_,T_,r_,q_));excluded=np.zeros(idx.size,bool)
    def fun(j,x):
        m=j.size;Dr=np.ones(m);Dq=np.ones(m);v=np.ones(m);Sk=np.full(m,np.nan);eur=np.zeros(m,bool);out=np.zeros(m,bool)
        for k,(jj,s) in enumerate(zip(j.tolist(),x.tolist())):
            sd,Sv,Kv,Tv,rv,qv=rows[jj]
            try:Dr[k],Dq[k],v[k],p=_baw_point(sd,Sv,Kv,Tv,rv,qv,s,params,'brent')
            except AdmitExcluded:out[k]=True;excluded[jj]=True;continue
            except RunDefect:raise
            except ModelDefect:out[k]=True;continue
            if p is None:eur[k]=True
            else:Sk[k]=p
        live_=~out;counters.bump('baw',int(live_.sum()))
        val,bad_,_=baw_values(call[j],S_[j],K_[j],Dr,Dq,v,Sk,eur)
        val=np.where(live_,val,np.nan)
        sub=Checker(check.tau[j]);sub(val,bad_|out);check.band[j]|=sub.band;check.dead[j]|=sub.dead
        return val-mid[j],sub.dead
    st,iv,fa,fb,_=brent(fun,lo,np.full(idx.size,hi),(lo+hi)/2.0)
    fl=np.zeros(idx.size,np.uint8);solved=st!=MD
    with np.errstate(invalid='ignore'):
        width=1e-9*np.where(mid>1.0,mid,1.0)
        fl[solved&((np.fabs(fa)<=width)|(np.fabs(fb)<=width))]|=FLAG_BOUNDARY_AMBIGUOUS
        intrinsic=np.where(call,S_-K_,K_-S_);fl[(st==BELOW)&(mid<np.where(0.0>intrinsic,0.0,intrinsic))]|=FLAG_BELOW_INTRINSIC
    fl[excluded&(st==MD)]|=FLAG_ADMIT_EXCLUDED
    ok=np.nonzero(st==OK)[0]
    if ok.size:
        plans=[];pts=[]
        for k in ok.tolist():
            sd,Sv,Kv,Tv,rv,qv=rows[k];order,memo=_baw_plan(sd,Sv,Kv,Tv,rv,qv,float(iv[k]),params);plans.append(memo)
            for p in memo.values():
                if p.error is None and p.index is None:p.index=len(pts);pts.append((k,p))
        if pts:
            ks=np.array([k for k,_ in pts],np.int64);P=[p for _,p in pts];counters.bump('baw',len(P))
            arr=lambda f:np.array([f(p) for p in P],np.float64)
            eur=np.array([p.Sk is None for p in P],bool)
            V,BAD,G=baw_values(call[ks],arr(lambda p:p.key[0]),K_[ks],arr(lambda p:p.D_r),arr(lambda p:p.D_q),arr(lambda p:p.v),
                               arr(lambda p:np.nan if p.Sk is None else p.Sk),eur,greeks=bool(eur.any()))
            V=V.tolist();BAD=BAD.tolist();G={g:x.tolist() for g,x in G.items()} if G is not None else None
        for k,memo in zip(ok.tolist(),plans):
            sd,Sv,Kv,Tv,rv,qv=rows[k];ivk=float(iv[k]);rc=RChecker(rtau(Sv,Kv,Tv,rv,qv));rc.band=bool(check.band[k])
            def lookup(S_,T_,r_,s_,memo=memo):
                p=memo[(S_,T_,r_,s_)]
                if BAD[p.index]:raise ModelDefect('engine check')
                return p
            def value(S_,T_,r_,s_):return V[lookup(S_,T_,r_,s_).index]
            def result(S_,T_,r_,s_):
                p=lookup(S_,T_,r_,s_);i=p.index
                return {'value':V[i]} if p.Sk is not None else {'value':V[i],**{g:G[g][i] for g in G}}
            def sideof(S_,T_,r_,s_,memo=memo):
                p=memo[(S_,T_,r_,s_)]
                if p.error is not None:raise p.error
                return p.side
            try:
                values,gflags,_=baw_greeks(sd,Sv,Kv,Tv,rv,qv,ivk,params,value,result,rc,sideof=sideof)
            except RunDefect:raise
            except AdmitExcluded:st[k]=MD;fl[k]|=FLAG_ADMIT_EXCLUDED|(FLAG_ROUNDING_BAND if rc.band else 0);continue
            except StencilUnresolved:st[k]=MD;fl[k]|=FLAG_STENCIL_UNRESOLVED|(FLAG_ROUNDING_BAND if rc.band else 0);continue
            except (EngineDomain,ModelDefect):st[k]=MD;fl[k]|=FLAG_ROUNDING_BAND if rc.band else 0;continue
            fl[k]|=gflags|(FLAG_ROUNDING_BAND if rc.band else 0)
            if values[5]*100.0<1e-12:fl[k]|=FLAG_FLAT_VEGA
            for f,x in zip(FIELDS,values):vals[f][idx[k]]=x
    fl[check.band&(st!=OK)]|=FLAG_ROUNDING_BAND
    status[idx]=st;flags[idx]=fl
    return {'status':status,'flags':flags,**vals}

# ---- Andersen-Lake-Offengenden (spec Amendment I4.2; the approved record Appendix I-ALO R2-R10, R12 E-ALO-1..5) ----
# The engine of optionlab.alo (QuantLib 1.43 QdFpAmericanEngine with accurateScheme; the line citations and the Boost
# file-scope notice are in optionlab.alo) for many evaluation points at once, in the same binary64 operation order. The
# shared scalar functions run per element: alo_equation and read_back (optionlab.alo_equation), the E-ALO-1 sigma_lo
# (optionlab.models.sigma_lo), the pre check (optionlab.reference.alo_pre) and the I2.6 stencil rule
# (optionlab.reference.alo_greeks, replayed with the vectorized values as for BAW). Vectorized: the QD+ boundary (13 nodes
# per point; Halley with a per-pair mask, at most 10 evaluator calls, a finished pair frozen; the Brent fallback through the
# masked `brent` above with accuracy 1e-8 and 100 evaluations), the barycentric Chebyshev interpolation, the 1 + 4
# fixed-point sweeps (FP-A and FP-B groups, 25 Legendre points in the record's reverse order), the tanh-sinh integral (a
# per-element state: tail positions, levels, thrash count; a finished element frozen; each sum is accumulated in the
# scalar order with np.add.accumulate) and the European value. std::max(a, b) is np.where(a < b, b, a) (`_max`), never
# np.maximum or np.fmax (record R7: a NaN operand can vanish exactly as in C++).
# The shared NaN check (record R7 item 3) runs at the same sites on every live element of a batch: a failure raises
# models.AloRunDefect('alo-nan', site) and the run fails (H19); a loop count above its cap raises AloRunDefect('alo-cap').
# Deviation in scope, not in result: the batch checks every node and every point it computes, while py-reference stops an
# evaluation at its first order-5 exception (no such case is known: record R8 found no exception at any compared point).
# An engine exception of an element (record R8: the engine checks, the double-boundary case, the inner QD+ Brent errors,
# the Boost evaluation_error cases, the BlackCalculator checks) marks that element `bad` (order 5, MODEL_DOMAIN).
# Not computed here: the guard NaN counts (`alo_nan_guarded` is a py-reference aggregate, I8.3). The test-only planting
# helpers of optionlab.alo act on py-reference only.
from optionlab import alo as _alo
from optionlab.models import AloRunDefect, RunDefect, ModelDefect

_CHEB_N=_alo.SCHEME_N+1
_CHEB_X=[-math.cos(i*_alo.M_PI/(_CHEB_N-1)) for i in range(_CHEB_N)]          # chebyshevinterpolation.cpp (alo.Cheb)
def _cheb_weights():
    cM1=4.0/(_CHEB_X[_CHEB_N-1]-_CHEB_X[0]);out=[]
    for i in range(_CHEB_N):
        li=1.0;xi=_CHEB_X[i]
        for j in range(_CHEB_N):
            if i!=j:li*=cM1*(xi-_CHEB_X[j])
        out.append(1.0/li)
    return out
_CHEB_LAM=_cheb_weights();_CHEB_XA=np.array(_CHEB_X)
_SWEEP_TAU=[(0.5*1.0*(1.0+z))*(0.5*1.0*(1.0+z)) for z in _CHEB_X]                 # x_i = 0.5 sqrt(T) (1 + z_i), T = 1.0 (cpp:443-445)
_ALO_TRACE=None         # test-only (I4.2 divergence instrumentation, outside timing): a list receives (point, stats) per evaluation

def _nan_check(site,*xs):
    """The shared NaN check on arrays: every value finite, else models.AloRunDefect('alo-nan', site)."""
    for x in xs:
        if not np.all(np.isfinite(x)):raise AloRunDefect('alo-nan',site)

def _close_enough(x,y):
    """QuantLib close_enough(x, y) (math/comparison.hpp:92-107), elementwise (alo.close_enough)."""
    with np.errstate(all='ignore'):
        diff=np.fabs(x-y);tol=42*QL_EPSILON
        return (x==y)|np.where((x==0.0)|(y==0.0),diff<tol*tol,(diff<=tol*np.fabs(x))|(diff<=tol*np.fabs(y)))

def _xmax(K,r,q):
    """QdPlusAmericanEngine::xMax (alo.xmax_fn), elementwise; (value, internal-error mask)."""
    c1=(r>0.0)&(q>0.0);c2=(r>0.0)&(q<=0.0);c3=(r==0.0)&(q<0.0);c4=(r==0.0)&(q>=0.0);c5=(r<0.0)&(q>=0.0);c6=(r<0.0)&(q<r);c7=(r<0.0)&(r<=q)&(q<0.0)
    with np.errstate(all='ignore'):rq=r/q;mn=np.where(rq<1.0,rq,1.0)            # std::min(1.0, r/q)
    v=np.select([c1,c2,c3,c4,c5,c6,c7],[K*mn,K,K,0.0,0.0,K,0.0],np.nan)
    return v,~(c1|c2|c3|c4|c5|c6|c7)

def _cheb_value(y,x):
    """Cheb.__call__ (lagrangeinterpolation.hpp:97-134; the exact-node branch) for every element: y (k, 14) node values,
    x (k, j) points; returns (k, j)."""
    with np.errstate(all='ignore'):
        eps=10*QL_EPSILON*np.fabs(x);t=x-eps
        lo=np.where(np.isnan(t),0,np.searchsorted(_CHEB_XA,t,side='left'))     # std::lower_bound(x.begin(), x.end(), x - eps)
        lc=np.minimum(lo,_CHEB_N-1)
        exact=(lo!=_CHEB_N)&(_CHEB_XA[lc]-x<eps)
        n=np.zeros(x.shape);d=np.zeros(x.shape)
        for i in range(_CHEB_N):
            alpha=_CHEB_LAM[i]/(x-_CHEB_X[i]);n=n+alpha*y[:,i:i+1];d=d+alpha
        return np.where(exact,np.take_along_axis(y,lc,axis=1),n/d)

class _QdPlus:
    """QdPlusBoundaryEvaluator (alo.QdPlusEval) for many (point, node) pairs; `n` counts operator() calls per pair."""
    def __init__(self,S,K,r,q,vol,tau):
        with np.errstate(all='ignore'):
            self.S=S;self.K=K;self.r=r;self.q=q;self.tau=tau;self.sigma2=sigma2=vol*vol;self.v=vol*_sqrt(tau)
            self.dr=dr=_exp(-r*tau);self.dq=_exp(-q*tau)
            ddr=np.where(np.fabs(r*tau)>1e-5,r/(1-dr),1/(tau*(1-0.5*r*tau*(1-r*tau/3))))
            omega=2*(r-q)/sigma2
            root=_sqrt((omega-1)*(omega-1)+8*ddr/sigma2)
            self.lam=lam=0.5*(-(omega-1)-root)
            lp=2*ddr*ddr/(sigma2*root)
            self.alpha=alpha=2*dr/(sigma2*(2*lam+omega-1))
            self.beta=alpha*(ddr+lp/(2*lam+omega-1))-lam
            self.xMax,_=_xmax(K,r,q)
            self.xMin=QL_EPSILON*1e4*_min(0.5*(K+S),self.xMax)
        self.n=np.zeros(S.shape,np.int64)
    def _pre(self,i,S):
        S=_max(QL_EPSILON,S);v=self.v[i];K=self.K[i];dq=self.dq[i];dr=self.dr[i];r=self.r[i];q=self.q[i];tau=self.tau[i]
        dp=_log(S*dq/(K*dr))/v+0.5*v;dm=dp-v
        Phi_dp=norm_cdf(-dp);Phi_dm=norm_cdf(-dm);phi_dp=norm_pdf(dp)
        npv=dr*K*Phi_dm-S*dq*Phi_dp
        theta=r*K*dr*Phi_dm-q*S*dq*Phi_dp-(self.sigma2[i]*S/(2*v))*dq*phi_dp
        charm=-dq*(phi_dp*((r-q)/v-dm/(2*tau))+q*Phi_dp)
        return dp,dm,Phi_dp,phi_dp,npv,theta,charm
    def value(self,i,S,parts=None):
        """operator()(S) for the pairs i (counted); `parts` = _pre(i, S) when already computed."""
        self.n[i]+=1
        with np.errstate(all='ignore'):
            dp,dm,Phi_dp,phi_dp,npv,theta,charm=parts if parts is not None else self._pre(i,S)
            K=self.K[i];dq=self.dq[i];dr=self.dr[i];alpha=self.alpha[i];lam=self.lam[i]
            ce=_close_enough(K-S,npv)
            c0=-self.beta[i]-lam+alpha*theta/(dr*(K-S-npv))
            return np.where(ce,(1-dq*Phi_dp)*S+alpha*theta/dr,(1-dq*Phi_dp)*S+(lam+c0)*(K-S-npv))
    def halley_parts(self,i,S):
        """(f, f', f'') at S for the pairs i (one counted operator() call)."""
        with np.errstate(all='ignore'):
            parts=self._pre(i,S);dp,dm,Phi_dp,phi_dp,npv,theta,charm=parts
            fx=self.value(i,S,parts)
            dq=self.dq[i];v=self.v[i];beta=self.beta[i];alpha=self.alpha[i];dr=self.dr[i];r=self.r[i];q=self.q[i];tau=self.tau[i]
            fp=1-dq*Phi_dp+dq/v*phi_dp+beta*(1-dq*Phi_dp)+alpha/dr*charm
            gamma=phi_dp*dq/(v*S)
            colour=gamma*(q+(r-q)*dp/v+(1-dp*dm)/(2*tau))
            f2=dq*(phi_dp/(S*v)-phi_dp*dp/(S*v*v))+beta*gamma+alpha/dr*colour
        return fx,fp,f2

def _min(a,b):return np.where(b<a,b,a)        # std::min

def _qd_boundary(S,K,r,q,vol):
    """getPutExerciseBoundary with 14 interpolation points (alo.qd_boundary_interp) for m points: the node values y
    (m, 14) = log(b / xMax)^2, plus per point the stats (halley_max, fallback nodes, fallback max, evaluator calls) and the
    `bad` mask (an inner QD+ Brent error: AloInnerSolverError, order 5)."""
    m=S.size;nodes=_CHEB_N-1
    P=np.repeat(np.arange(m),nodes);tau=np.tile(np.array([0.25*1.0*((1+z)*(1+z)) for z in _CHEB_X[1:]]),m)   # x_sq, T = 1.0
    ev=_QdPlus(S[P],K[P],r[P],q[P],vol[P],tau);npair=P.size
    eps=_alo.QDPLUS_EPS;max_iter=_alo.QDPLUS_MAX_ITER
    x=ev.xMax.copy();xmin=ev.xMin;fx_last=np.zeros(npair);close_ok=np.zeros(npair,bool);act=np.arange(npair)
    with np.errstate(all='ignore'):
        while act.size:                                  # Halley (qdplus:312-338); every live pair takes one call per pass
            xOld=x[act];fx,fp,f2=ev.halley_parts(act,xOld)
            lf=fx*f2/(fp*fp)
            step=(1/(1-0.5*lf))*fx/fp
            _nan_check('qdplus-solver',fx,fp,f2,lf,step)
            xn=_max(xmin[act],xOld-step);x[act]=xn;fx_last[act]=fx
            ok=np.fabs(xn-xOld)<0.5*eps;close_ok[act]=ok
            act=act[~(ok|~(ev.n[act]<max_iter))]
    if np.any(ev.n>_alo.CAPS['halley']):raise AloRunDefect('alo-cap','halley')
    fb=~close_ok&~close(np.fabs(fx_last),0.0);bad_pair=np.zeros(npair,bool)
    halley_n=ev.n.copy()
    F=np.nonzero(fb)[0]
    if F.size:                                           # buildInSolver with QuantLib Brent (qdplus:267-289)
        with np.errstate(all='ignore'):
            fxmin=ev.value(F,xmin[F]);_nan_check('qdplus-solver',fxmin)
            a=0.5*(ev.xMax[F]+ev.S[F]);xmax_b=_max(a,ev.xMax[F])
            fxb=ev.value(F,xmax_b);_nan_check('qdplus-solver',fxb)
            if np.any((fxb*fxmin>0.0)&(ev.n[F]<max_iter)):raise AloRunDefect('alo-cap','doubling')   # the loop never doubles (record R3)
            g=x[F];g=np.where(g>=xmax_b,np.nextafter(xmax_b,-1.0),np.where(g<=xmin[F],np.nextafter(xmin[F],QL_MAX_REAL),g))
        # a pair without an interior bracket or guess is an inner solver error in py-reference too (ValueError there)
        inner=(xmin[F]<xmax_b)&(g>xmin[F])&(g<xmax_b);bad_pair[F[~inner]]=True;Fi=F[inner]
        if Fi.size:
            def fun(j,xx):
                v=ev.value(Fi[j],xx);_nan_check('qdplus-solver',v);return v,np.zeros(j.size,bool)
            st,root,_,_,nev=brent(fun,xmin[Fi],xmax_b[inner],g[inner],accuracy=eps,max_evaluations=10*max_iter)
            if np.any(nev>_alo.CAPS['brent']):raise AloRunDefect('alo-cap','brent')
            okb=st==OK;x[Fi[okb]]=root[okb];bad_pair[Fi[~okb]]=True
    with np.errstate(all='ignore'):
        xm,_=_xmax(K[P],r[P],q[P]);l=_log(x/xm);yv=l*l
    y=np.zeros((m,_CHEB_N));y[:,1:]=yv.reshape(m,nodes)
    with np.errstate(all='ignore'):l0=_log(_xmax(K,r,q)[0]/_xmax(K,r,q)[0]);y[:,0]=l0*l0     # node 0: tau = 0 < QL_EPSILON gives xMax
    fbm=fb.reshape(m,nodes);hn=np.where(fbm,0,halley_n.reshape(m,nodes));fn=np.where(fbm,ev.n.reshape(m,nodes)-halley_n.reshape(m,nodes),0)
    stats={'halley_max':hn.max(axis=1),'fallback_nodes':fbm.sum(axis=1),'fallback_max':fn.max(axis=1),'qd_calls':ev.n.reshape(m,nodes).sum(axis=1)}
    return y,stats,bad_pair.reshape(m,nodes).any(axis=1)

def _fp_sweeps(kindA,K,r,q,vol,xmax,y):
    """The 1 Jacobi-Newton and 4 naive fixed-point sweeps (alo.calculate_put, cpp:465-504) for one equation group; y is
    updated in place. T = 1.0, so every node has tau >= 2.1e-4 and the tau < QL_EPSILON branches are not taken."""
    tau=np.array(_SWEEP_TAU[1:])[None,:];K=K[:,None];r=r[:,None];q=q[:,None];vol=vol[:,None];xm=xmax[:,None]
    def B(t):
        zz=2*_sqrt(np.fabs(t)/1.0)-1;iv=_cheb_value(y,np.broadcast_to(zz,(y.shape[0],zz.shape[-1])) if zz.shape[0]==1 else zz)
        _nan_check('post-boundary',iv)
        b=xm*_exp(-_sqrt(_max(0.0,iv)));_nan_check('post-boundary',b);return b
    def d(t,z):
        v=vol*_sqrt(t);mm=(_log(z)+(r-q)*t)/v+0.5*v;return mm,mm-v
    def f(b):
        if kindA:
            v=vol*_sqrt(tau);stv=_sqrt(tau)/vol;K12=0.0;K3=0.0
            for i in _alo.GL_REV:
                yy=_alo.GL_X[i];mm=0.25*tau*((1+yy)*(1+yy))
                d1,d2=d(mm,b/B(tau-mm))
                K12=K12+_alo.GL_W[i]*_exp(q*tau-q*mm)*(0.5*tau*(yy+1)*norm_cdf(d1)+stv*norm_pdf(d1))
                K3=K3+_alo.GL_W[i]*stv*_exp(r*tau-r*mm)*norm_pdf(d2)
            d1,d2=d(tau,b/K)
            N=norm_pdf(d2)/v+r*K3;D=norm_pdf(d1)/v+norm_cdf(d1)+q*K12
        else:
            c=0.5*tau;ni=0.0;di=0.0
            for i in _alo.GL_REV:
                u=c*_alo.GL_X[i]+c
                d1,d2=d(tau-u,b/B(u))
                ni=ni+_alo.GL_W[i]*_exp(r*u)*norm_cdf(d2);di=di+_alo.GL_W[i]*_exp(q*u)*norm_cdf(d1)
            ni=ni*c;di=di*c
            d1,d2=d(tau,b/K)
            N=norm_cdf(d2)+r*ni;D=norm_cdf(d1)+q*di
        alpha=K*_exp(-(r-q)*tau);fv=alpha*N/D
        _nan_check('post-sweep',N,D,fv);return N,D,fv
    def NDd(b):
        d1,d2=d(tau,b/K)
        if kindA:
            Dd=-norm_pdf(d1)*d1/(b*vol*vol*tau)+norm_pdf(d1)/(b*vol*_sqrt(tau))
            Nd=-norm_pdf(d2)*d2/(b*vol*vol*tau)
        else:
            Nd=norm_pdf(d2)/(b*vol*_sqrt(tau));Dd=norm_pdf(d1)/(b*vol*_sqrt(tau))
        _nan_check('post-sweep',Nd,Dd);return Nd,Dd
    def h(fv):
        l=_log(fv/xm);return l*l
    with np.errstate(all='ignore'):
        b=B(tau);N,D,fv=f(b);Nd,Dd=NDd(b)                # the Jacobi-Newton step (cpp:465-493)
        fd=K*_exp(-(r-q)*tau)*(Nd/D-Dd*N/(D*D))
        y[:,1:]=h(b-(fv-b)/(fd-1));_nan_check('post-boundary',y)
        for _ in range(_alo.SCHEME_M-1):               # 4 naive steps (cpp:495-504)
            y[:,1:]=h(f(B(tau))[2]);_nan_check('post-boundary',y)
    return y

def _addon_integrand(S,K,r,q,vol,xmax,y,z):
    """QdPlusAddOnValue::operator() (alo.calculate_put `aov`, qdplus:132-158) at the points z (k,) of the elements whose
    columns are given (one element per point), with the integrand checks of the shared NaN check."""
    with np.errstate(all='ignore'):
        t=z*z;a=1.0-t
        qv=_cheb_value(y,(2*_sqrt(_max(0.0,a)/1.0)-1)[:,None])[:,0]
        b_t=xmax*_exp(-_sqrt(_max(0.0,qv)))
        dr=_exp(-r*t);dq=_exp(-q*t);v=vol*_sqrt(t)
        _nan_check('integrand',t,v,b_t,dr,dq,qv)
        dp=_log(S*dq/(b_t*dr))/v+0.5*v
        gen=np.where(b_t>QL_EPSILON,2*z*(r*K*dr*norm_cdf(-dp+v)-q*S*dq*norm_cdf(-dp)),0.0)
        small=np.where(_close_enough(S*dq,b_t*dr),z*(r*K*dr-q*S*dq),np.where(b_t*dr>S*dq,2*z*(r*K*dr-q*S*dq),0.0))
        res=np.where(v>=QL_EPSILON,gen,small)
    _nan_check('integrand-value',res);return res

def _tanh_sinh(fe,m,tol):
    """Boost tanh_sinh<double>::integrate on [0, sqrt(T)] = [0, 1] (alo.tanh_sinh_integrate and TanhSinhDetail.integrate,
    tsd:190-558) for m integrands at once: fe(e, z) evaluates the integrands of the elements e at the points z. Every
    element keeps its own tail positions, sums, error, thrash count and level; a finished element is frozen. Returns
    (diff * I1, levels, evaluations, bad) per element; `bad` marks a Boost evaluation_error (order 5)."""
    det=_alo.TanhSinhDetail()                          # a new object per batch (E-ALO-3), rows 8-15 computed on use
    a,b=0.0,1.0;avg=(a+b)*0.5;diff=(b-a)*0.5;aodm1=a/diff;aodp1=b/diff
    small_l=math.fabs(a)<0.5;small_r=math.fabs(b)<0.5
    lmc=math.nextafter(aodm1,math.inf)-aodm1;lim=_alo.smax(_alo.DBL_MIN,math.nextafter(_alo.DBL_MIN/diff,math.inf))
    if lmc<lim:lmc=lim
    rmc=aodp1-math.nextafter(aodp1,-math.inf)
    if rmc<lim:rmc=lim
    def pos(zv,zc):
        """tanh_sinh::integrate's u(z, zc) (ts:177-197) as a position, elementwise."""
        return np.where(zv<-0.5,(diff*(aodm1-zc)) if small_l else (a-diff*zc),np.where(zv>0.5,(diff*(aodp1-zc)) if small_r else (b-diff*zc),avg+diff*zv))
    nev=np.zeros(m,np.int64);bad=np.zeros(m,bool)
    def F(e,zv,zc):
        e=np.asarray(e,np.int64)
        if not e.size:return np.zeros(0)
        np.add.at(nev,e,1);return fe(e,pos(np.asarray(zv,np.float64),np.asarray(zc,np.float64)))
    fabs=np.fabs;HP=_alo.HALF_PI;tail=_alo.smax(_alo.BOOST_EPS,tol*tol);E=np.arange(m)
    h=det.m_t_max/det.m_inital_row_length
    A0=det.m_abscissas[0];W0=det.m_weights[0];A0a=np.array(A0);W0a=np.array(W0)
    I0=HP*F(E,np.zeros(m),np.ones(m));L1_I0=np.abs(I0)
    ml=len(A0)-1;mr=ml
    while ml>1 and math.fabs(A0[ml])<lmc:ml-=1
    while mr>1 and math.fabs(A0[mr])<rmc:mr-=1
    mlp=np.full(m,ml,np.int64);mrp=np.full(m,mr,np.int64)
    yp=F(E,-1-A0a[mlp],A0a[mlp]);ym=F(E,1+A0a[mrp],-A0a[mrp])
    # the end retreats on a non-finite value (tsd:242-249) never run: the integrand check raised before
    act=np.nonzero(mlp>1)[0]
    while act.size:                                  # tsd:250-256: retreat the left end while its term is below the tail tolerance
        stop=fabs(yp[act]*W0a[mlp[act]])>fabs(L1_I0[act]*tail);act=act[~stop]
        if not act.size:break
        mlp[act]-=1;yp[act]=F(act,-1-A0a[mlp[act]],A0a[mlp[act]]);act=act[mlp[act]>1]
    act=np.nonzero(mrp>1)[0]
    while act.size:
        stop=fabs(ym[act]*W0a[mrp[act]])>fabs(L1_I0[act]*tail);act=act[~stop]
        if not act.size:break
        mrp[act]-=1;ym[act]=F(act,1+A0a[mrp[act]],-A0a[mrp[act]]);act=act[mrp[act]>1]
    I0=I0+(yp*W0a[mlp]+ym*W0a[mrp]);L1_I0=L1_I0+(np.abs(yp*W0a[mlp])+np.abs(ym*W0a[mrp]))
    def row_sums(e,row_a,row_w,lim_l,lim_r,complement_from,s0,a0):
        """The interior loop of one row for the elements e (tsd: the j loop): yp where j < lim_r, ym where j < lim_l, and
        the sums s0 + (yp + ym) w and a0 + (|yp| + |ym|) w accumulated in j order (padding -0.0 leaves a sum unchanged)."""
        L=len(row_w);jj=np.arange(L)
        top=np.maximum(lim_l,lim_r);need=jj[None,:]<top[:,None]
        if L==0 or not need.any():return s0,a0
        ra=np.array(row_a);x=ra.copy();xc=ra.copy()
        cm=jj>=complement_from if complement_from is not None else np.copysign(1.0,ra)<0
        x=np.where(cm,1+ra,ra);xc=np.where(cm,ra,ra-1)
        np_=need&(jj[None,:]<lim_r[:,None]);nm=need&(jj[None,:]<lim_l[:,None])
        Yp=np.zeros((e.size,L));Ym=np.zeros((e.size,L))
        ei,ji=np.nonzero(np_)
        if ei.size:Yp[ei,ji]=F(e[ei],x[ji],-xc[ji])
        ei,ji=np.nonzero(nm)
        if ei.size:Ym[ei,ji]=F(e[ei],-x[ji],xc[ji])
        w=np.array(row_w)[None,:]
        ts=np.where(need,(Yp+Ym)*w,-0.0);ta=np.where(need,(np.abs(Yp)+np.abs(Ym))*w,-0.0)
        s=np.add.accumulate(np.concatenate((s0[:,None],ts),axis=1),axis=1)[:,-1]
        ab=np.add.accumulate(np.concatenate((a0[:,None],ta),axis=1),axis=1)[:,-1]
        return s,ab
    # row 0 interior (tsd:263-276): i = 1 .. len(A0)-1 while i < max(ml, mr)
    lim_l=mlp-1;lim_r=mrp-1                         # i runs from 1: shift by one
    I0,L1_I0=row_sums(E,A0[1:],W0[1:],lim_l,lim_r,None,I0,L1_I0)
    k=1;I1=I0.copy();L1_I1=L1_I0.copy();err=np.zeros(m);last_err=np.zeros(m);thrash=np.zeros(m,np.int64)
    levels=np.zeros(m,np.int64);done=np.zeros(m,bool);nrows=len(det.m_weights)
    while k<4 or (k<nrows and k<det.m_max_refinements):
        act=np.nonzero(~done)[0]
        if not act.size:break
        I0[act]=I1[act];L1_I0[act]=L1_I1[act];I1[act]=0.5*I0[act];L1_I1[act]=0.5*L1_I0[act];h*=0.5
        ra,rw,fci=det._row(k);raa=np.array(ra);rwa=np.array(rw)
        mli=mlp[act]-1;mlp[act]*=2;mri=mrp[act]-1;mrp[act]*=2
        gl=(len(ra)>mli+1)&(fabs(raa[np.minimum(mli+1,len(ra)-1)])>lmc);mlp[act]+=gl;mli=mli+gl
        gr=(len(ra)>mri+1)&(fabs(raa[np.minimum(mri+1,len(ra)-1)])>rmc);mrp[act]+=gr;mri=mri+gr
        # the end retreats on a non-finite value (tsd:373-399) never run: the integrand check raised before
        ypa=F(act,-1-raa[mli],raa[mli]);trl=fabs(L1_I1[act]*tail)>fabs(ypa*rwa[mli])
        yma=F(act,1+raa[mri],-raa[mri]);trr=fabs(L1_I1[act]*tail)>fabs(yma*rwa[mri])
        s=0.0+(ypa*rwa[mli]+yma*rwa[mri]);absum=0.0+(np.abs(ypa*rwa[mli])+np.abs(yma*rwa[mri]))
        endpoint_error=absum
        s,absum=row_sums(act,ra,rw,mli,mri,fci,s,absum)
        I1[act]=I1[act]+s*h;L1_I1[act]=L1_I1[act]+absum*h;k+=1;last_err[act]=err[act];err[act]=np.abs(I0[act]-I1[act])
        nf=~np.isfinite(I1[act])
        if nf.any():bad[act[nf]]=True;done[act[nf]]=True
        keep=~nf;act,s,endpoint_error,trl,trr,mli,mri=act[keep],s[keep],endpoint_error[keep],trl[keep],trr[keep],mli[keep],mri[keep]
        th=(err[act]*1.5>last_err[act])&(k>4)
        thrash[act[th]]+=1
        with np.errstate(all='ignore'):
            le=last_err[act];term=th&(((thrash[act]>1)&(le<1e-3))|(thrash[act]>2)|(le<_alo.ROOT_EPS)|(np.abs(endpoint_error/s)>err[act]))
        t_=act[term]
        I1[t_]=I0[t_];L1_I1[t_]=L1_I0[t_];levels[t_]=k-1;err[t_]=last_err[t_]+endpoint_error[term];done[t_]=True
        rest=~term;act,endpoint_error,trl,trr,mli,mri=act[rest],endpoint_error[rest],trl[rest],trr[rest],mli[rest],mri[rest]
        conv=(err[act]<=np.abs(tol*L1_I1[act]))&(k>=4)
        if conv.any():
            c=act[conv];cl=mli[conv];cr=mri[conv];inc=np.zeros(c.size,bool)
            sel=(cl>0)&(cl<len(ra)-1)&(fabs(raa[np.minimum(cl+1,len(ra)-1)])>lmc)
            if sel.any():
                e=c[sel];i_=cl[sel]
                yp1=F(e,-1-raa[i_],raa[i_])*rwa[i_];ym1=F(e,-1-raa[i_-1],raa[i_-1])*rwa[i_-1];inc[np.nonzero(sel)[0][np.abs(yp1)>np.abs(ym1)]]=True
            sel=~inc&(cr>0)&(cr<len(ra)-1)&(fabs(raa[np.minimum(cr+1,len(ra)-1)])>rmc)
            if sel.any():
                e=c[sel];i_=cr[sel]
                yp1=F(e,1+raa[i_],-raa[i_])*rwa[i_];ym1=F(e,1+raa[i_-1],-raa[i_-1])*rwa[i_-1];inc[np.nonzero(sel)[0][np.abs(yp1)>np.abs(ym1)]]=True
            bad[c[inc]]=True
            err[c]=err[c]+endpoint_error[conv];levels[c]=k;done[c]=True
        rest=~conv;act,trl,trr=act[rest],trl[rest],trr[rest]
        dl=act[trl&(mlp[act]>1)];mlp[dl]-=1
        dr_=act[trr&(mrp[act]>1)];mrp[dr_]-=1
    levels[~done]=k
    return diff*I1,levels,nev,bad

def alo_values(call,S,K,r_e,q_e,vol,kindA):
    """QdPutCallParityEngine::calculate (alo.engine) for m points of the mapped problem (T = 1.0): call (bool), S, K, the
    read-back rates r_e and q_e, vol = sigma' and the equation (kindA: FP-A). Returns (value, bad, stats): `bad` marks
    an order-5 engine exception of the element (record R8); stats holds the per-point halley_max, fallback_nodes,
    fallback_max, levels, integrand and qd_calls (the counters of alo.Stats). A failed shared NaN check or a cap excess
    raises AloRunDefect for the batch."""
    m=S.size;val=np.full(m,np.nan);bad=np.zeros(m,bool)
    st={k:np.zeros(m,np.int64) for k in ('halley_max','fallback_nodes','fallback_max','levels','integrand','qd_calls')}
    if not m:return val,bad,st
    Sp=np.where(call,K,S);Kp=np.where(call,S,K);rp=np.where(call,q_e,r_e);qp=np.where(call,r_e,q_e)     # the exchanged put (qdplus:190-193)
    with np.errstate(all='ignore'):
        bad|=~(S>=0.0)|~(K>=0.0)|~(vol>=0.0)                                   # qdplus:168-180 engine checks
        g1=~bad&close(Kp,0.0);val[g1]=0.0
        g2=~bad&~g1&close(Sp,0.0);val[g2]=_max(Kp[g2],Kp[g2]*_exp(-rp[g2]*1.0))
        g3=~bad&~g1&~g2&(rp<=0.0)&(rp<=qp)                                     # the European edge branch (qdplus:207-210)
        if g3.any():
            F_=Sp[g3]*_exp((rp[g3]-qp[g3])*1.0);sd=vol[g3]*_sqrt(1.0);disc=_exp(-rp[g3]*1.0)
            chk=(Kp[g3]>=0.0)&(F_>0.0)&(sd>=0.0)&(disc>0.0)
            bv=Black(np.zeros(F_.size,bool),Kp[g3],F_,sd,disc).value()
            if np.any(chk):_nan_check('post-european',bv[chk])
            i3=np.nonzero(g3)[0];bad[i3[~chk]]=True;val[i3[chk]]=_max(0.0,bv[chk])
        g4=~bad&~g1&~g2&~g3&close(vol,0.0)                                    # close(vol, 0): unreachable on an admitted point
        for i in np.nonzero(g4)[0].tolist():
            val[i]=_alo.put_with_edge_cases(float(Sp[i]),float(Kp[i]),float(rp[i]),float(qp[i]),float(vol[i]),1.0,_alo.FP_A if kindA[i] else _alo.FP_B)
        g5=~bad&~g1&~g2&~g3&~g4
        db=g5&(rp<0.0)&(qp<rp);bad|=db;g5&=~db                                # double-boundary case (cpp:432)
        xm,ie=_xmax(Kp,rp,qp);bad|=g5&ie;g5&=~ie
    idx=np.nonzero(g5)[0]
    if not idx.size:return val,bad,st
    S5,K5,r5,q5,v5,x5=Sp[idx],Kp[idx],rp[idx],qp[idx],vol[idx],xm[idx]
    y,qs,qbad=_qd_boundary(S5,K5,r5,q5,v5)
    for k_ in ('halley_max','fallback_nodes','fallback_max','qd_calls'):st[k_][idx]=qs[k_]
    bad[idx[qbad]]=True;keep=~qbad
    idx,S5,K5,r5,q5,v5,x5,y=idx[keep],S5[keep],K5[keep],r5[keep],q5[keep],v5[keep],x5[keep],y[keep]
    if not idx.size:return val,bad,st
    _nan_check('post-boundary',y)
    kA=np.asarray(kindA)[idx]
    for grp in (kA,~kA):
        if grp.any():y[grp]=_fp_sweeps(bool(kA[grp][0]),K5[grp],r5[grp],q5[grp],v5[grp],x5[grp],y[grp])
    def fe(e,z):return _addon_integrand(S5[e],K5[e],r5[e],q5[e],v5[e],x5[e],y[e],z)
    addOn,levels,nev,tbad=_tanh_sinh(fe,idx.size,_alo.SCHEME_EPS)
    st['levels'][idx]=levels;st['integrand'][idx]=nev
    if np.any(levels>_alo.CAPS['levels']):raise AloRunDefect('alo-cap','levels')
    if np.any(nev>_alo.CAPS['integrand']):raise AloRunDefect('alo-cap','integrand')
    if np.any(st['qd_calls']>_alo.CAPS['qd_calls']):raise AloRunDefect('alo-cap','qd_calls')
    bad[idx[tbad]]=True;keep=~tbad;idx,S5,K5,r5,q5,v5,addOn=idx[keep],S5[keep],K5[keep],r5[keep],q5[keep],v5[keep],addOn[keep]
    if not idx.size:return val,bad,st
    with np.errstate(all='ignore'):
        F_=S5*_exp((r5-q5)*1.0);sd=v5*_sqrt(1.0);disc=_exp(-r5*1.0)
        chk=(K5>=0.0)&(F_>0.0)&(sd>=0.0)&(disc>0.0)                           # BlackCalculator checks (order 5)
        ev_=Black(np.zeros(F_.size,bool),K5,F_,sd,disc).value()
    bad[idx[~chk]]=True
    _nan_check('post-integral',addOn[chk],ev_[chk])
    val[idx[chk]]=_max(ev_[chk],0.0)+_max(0.0,addOn[chk])
    return val,bad,st

def _alo_points(points,params):
    """Engine values of ALO evaluation points (side, S, K, T, r, q, sigma) through the mapping, after the pre check
    (optionlab.reference.alo_pre; a failure is order 5 and the point is not counted). Returns (value, bad) arrays: `bad`
    marks a failed pre check or an engine exception. alo_equation and read_back run per point (shared scalar functions).
    The test-only counters count the evaluated points (G4.8); the divergence trace (test-only) records each point."""
    from optionlab.reference import alo_pre
    from optionlab.alo_equation import read_back, alo_equation
    n=len(points);val=np.full(n,np.nan);bad=np.zeros(n,bool);live=[]
    for i,(sd,S_,K_,T_,r_,q_,s_) in enumerate(points):
        try:alo_pre(sd,S_,K_,T_,r_,q_,s_)
        except RunDefect:raise
        except ModelDefect:bad[i]=True;continue
        live.append(i)
    if not live:return val,bad
    L=np.array(live,np.int64);rows=[points[i] for i in live]
    call=np.array([p[0]==0 for p in rows]);S=np.array([p[1] for p in rows]);K=np.array([p[2] for p in rows])
    rb=[read_back(p[4]*p[3],p[5]*p[3]) for p in rows];eq=[alo_equation(p[4]*p[3],p[5]*p[3]) for p in rows]
    r_e=np.array([x[0] for x in rb]);q_e=np.array([x[1] for x in rb]);vol=np.array([p[6]*math.sqrt(p[3]) for p in rows])
    counters.bump('alo',len(rows))
    v,b,st=alo_values(call,S,K,r_e,q_e,vol,np.array([e==_alo.FP_A for e in eq]))
    val[L]=v;bad[L]=b
    if _ALO_TRACE is not None:
        for j,p in enumerate(rows):_ALO_TRACE.append((p,(int(st['halley_max'][j]),int(st['fallback_nodes'][j]),int(st['levels'][j])),bool(b[j])))
    return val,bad

def evaluate_alo(prep,params):
    """ALO over the prepared rows with py-reference's status order and flags (reference._evaluate): pre-engine statuses,
    the E-ALO-1 sigma_lo domain, the masked Brent with the pre check and the order-5 check before each evaluation, the
    record IV-call fact (V(sigma*) is the last Brent value), then the I2.6 greeks by the one stencil rule
    (reference.alo_greeks): a first pass per row records the stencil points (the rule depends on alo_segment and sigma_lo
    only, never on a value), the values of all points of all rows come from one vectorized batch, and a second pass
    replays the rule with those values, so the order of the order-5 checks, the unresolved stencils (bit 16) and the
    stencil flags (bit 32) is py-reference's. A RunDefect propagates (H19)."""
    from optionlab.reference import (alo_greeks, Checker as RChecker, tau_v as rtau, EngineDomain, StencilUnresolved, FLAG_STENCIL_UNRESOLVED)
    from optionlab.models import sigma_lo as s_lo
    n=prep['n'];side=prep['side'];S,K,T,bid,ask,r,q=(prep[k] for k in ('S','K','T','bid','ask','r','q'))
    hi=params.sigma_hi
    status=np.full(n,OK,np.uint8);flags=np.zeros(n,np.uint8);vals={f:np.full(n,np.nan) for f in FIELDS}
    with np.errstate(invalid='ignore'):
        finite=np.isfinite(S)&np.isfinite(K)&np.isfinite(T)&np.isfinite(bid)&np.isfinite(ask)
        bad=(side>1)|~finite|(S<=0.0)|(K<=0.0);status[bad]=CODE['INVALID_INPUT'];live=~bad
        for cond,name in ((T<=0.0,'EXPIRED'),(bid<=0.0,'NO_BID'),(ask<bid,'CROSSED')):
            m=live&cond;status[m]=CODE[name];live&=~m
    idx=np.nonzero(live)[0]
    if idx.size:
        lo=np.array([s_lo('alo',int(sd),Tk,rk,qk,params) for sd,Tk,rk,qk in zip(side[idx].tolist(),T[idx].tolist(),r[idx].tolist(),q[idx].tolist())],np.float64)
        dom=lo>=hi;status[idx[dom]]=MD;idx=idx[~dom];lo=lo[~dom]
    if idx.size==0:return {'status':status,'flags':flags,**vals}
    call=side[idx]==0;S_,K_,T_,r_,q_=S[idx],K[idx],T[idx],r[idx],q[idx];mid=(bid[idx]+ask[idx])/2.0
    rows=list(zip(side[idx].tolist(),S_.tolist(),K_.tolist(),T_.tolist(),r_.tolist(),q_.tolist()))
    check=Checker(tau_v(S_,K_,T_,r_,q_));last_x=np.full(idx.size,np.nan);last_v=np.full(idx.size,np.nan)
    def fun(j,x):
        pts=[(rows[k][0],rows[k][1],rows[k][2],rows[k][3],rows[k][4],rows[k][5],s) for k,s in zip(j.tolist(),x.tolist())]
        v,b=_alo_points(pts,params)
        sub=Checker(check.tau[j]);sub(v,b);check.band[j]|=sub.band;check.dead[j]|=sub.dead
        last_x[j]=x;last_v[j]=v
        return v-mid[j],sub.dead
    st,iv,fa,fb,_=brent(fun,lo,np.full(idx.size,hi),(lo+hi)/2.0)
    fl=np.zeros(idx.size,np.uint8);solved=st!=MD
    with np.errstate(invalid='ignore'):
        width=1e-9*np.where(mid>1.0,mid,1.0)
        fl[solved&((np.fabs(fa)<=width)|(np.fabs(fb)<=width))]|=FLAG_BOUNDARY_AMBIGUOUS
        intrinsic=np.where(call,S_-K_,K_-S_);fl[(st==BELOW)&(mid<np.where(0.0>intrinsic,0.0,intrinsic))]|=FLAG_BELOW_INTRINSIC
    ok=np.nonzero(st==OK)[0]
    if ok.size:
        if np.any(last_x[ok]!=iv[ok]):raise AloRunDefect('alo-iv-call','optimized')    # record IV-call fact
        plans=[];pts=[]
        for k in ok.tolist():
            sd,Sv,Kv,Tv,rv,qv=rows[k];rec=[]
            def value(S2,T2,r2,s2,rec=rec):rec.append((S2,T2,r2,s2));return 0.0
            try:alo_greeks(sd,Sv,Kv,Tv,rv,qv,float(iv[k]),0.0,params,value,lambda V:V)
            except RunDefect:raise
            except (StencilUnresolved,ModelDefect,EngineDomain):pass      # the second pass meets the same outcome at the same position
            memo={}
            for p in rec:
                if p not in memo:memo[p]=len(pts);pts.append((sd,p[0],Kv,p[1],p[2],qv,p[3]))
            plans.append(memo)
        V,BAD=_alo_points(pts,params) if pts else (np.zeros(0),np.zeros(0,bool))
        V=V.tolist();BAD=BAD.tolist()
        for k,memo in zip(ok.tolist(),plans):
            sd,Sv,Kv,Tv,rv,qv=rows[k];rc=RChecker(rtau(Sv,Kv,Tv,rv,qv));rc.band=bool(check.band[k])
            def value(S2,T2,r2,s2,memo=memo):
                i=memo[(S2,T2,r2,s2)]
                if BAD[i]:raise ModelDefect('alo engine exception (order 5)')
                return V[i]
            try:values,gflags,_=alo_greeks(sd,Sv,Kv,Tv,rv,qv,float(iv[k]),float(last_v[k]),params,value,rc)
            except RunDefect:raise
            except StencilUnresolved:st[k]=MD;fl[k]|=FLAG_STENCIL_UNRESOLVED|(FLAG_ROUNDING_BAND if rc.band else 0);continue
            except (EngineDomain,ModelDefect):st[k]=MD;fl[k]|=FLAG_ROUNDING_BAND if rc.band else 0;continue
            fl[k]|=gflags|(FLAG_ROUNDING_BAND if rc.band else 0)
            if values[5]*100.0<1e-12:fl[k]|=FLAG_FLAT_VEGA
            for f,x in zip(FIELDS,values):vals[f][idx[k]]=x
    fl[check.band&(st!=OK)]|=FLAG_ROUNDING_BAND
    status[idx]=st;flags[idx]=fl
    return {'status':status,'flags':flags,**vals}

def alo_divergence(rows,params):
    """Adaptive-path divergence (Amendment I4.2; test-only instrumentation, never in a timed interval): py-optimized ALO
    runs `rows` with the evaluation trace on; every traced engine evaluation is evaluated again by py-reference
    (optionlab.alo.price_stats, per-call statistics, A4R-06) and the counts of evaluations whose largest Halley count
    (`halley`), Brent-fallback node count (`fallback`) or tanh-sinh level (`levels`) differ are returned, with `any` (one
    of them or a different order-5 outcome), the evaluation count and the number of rows with a divergent evaluation.
    py-library is not instrumented: QuantLib does not expose these counts."""
    global _ALO_TRACE
    chain={'n':len(rows),**{k:[row[i] for row in rows] for i,k in enumerate(('side','S','K','T','bid','ask','r','q'))}}
    trace=[];saved=_ALO_TRACE;_ALO_TRACE=trace
    try:evaluate_alo(prepare(chain),params)
    finally:_ALO_TRACE=saved
    out={'rows':len(rows),'evaluations':len(trace),'halley':0,'fallback':0,'levels':0,'any':0,'rows_with_divergence':0};rows_div=set()
    for p,(hm,fbn,lev),b in trace:
        try:_,s=_alo.price_stats(*p,params);ref=(s.halley_max,s.fallback_nodes,s.levels);rb=False
        except RunDefect:raise
        except ModelDefect:ref=None;rb=True
        d=[False,False,False] if ref is None else [hm!=ref[0],fbn!=ref[1],lev!=ref[2]]
        if b or rb:d=[False,False,False]
        out['halley']+=d[0];out['fallback']+=d[1];out['levels']+=d[2]
        anyd=any(d) or (b!=rb);out['any']+=anyd
        if anyd:rows_div.add(p[:6])
    out['rows_with_divergence']=len(rows_div)
    return out

# ---- the variant's interface ----
PREPARED=('side','S','K','T','bid','ask','r','q')

def empty_prepared():
    """A prepared input with zero rows and every PREPARED column (side uint8, the others float64)."""
    return {'n':0,**{k:np.zeros(0,np.uint8 if k=='side' else np.float64) for k in PREPARED}}

def prepare(chain,params=None,market=None):
    """Kernel-scope prepared input (spec 5): contiguous float64 S, K, T, bid, ask, the per-row r and q columns of the chain
    (contract.rates: `market` gives r and the q of each row's expiry, Amendment C; the case parameters fill them only for a
    chain without columns) and a uint8 side (255: unknown side)."""
    r,q=chain_rates(chain,params,market)
    return {'n':chain['n'],'side':np.array([s if s in (0,1) else 255 for s in chain['side']],np.uint8),
            **{k:np.ascontiguousarray(chain[k],dtype=np.float64) for k in ('S','K','T','bid','ask')},
            'r':np.ascontiguousarray(r,dtype=np.float64),'q':np.ascontiguousarray(q,dtype=np.float64)}

def slice_prepared(prep,start,stop):
    """Rows start..stop of a prepared input as views; 0 <= start <= stop <= n, else ValueError."""
    import operator
    try:start=operator.index(start);stop=operator.index(stop)
    except TypeError:raise ValueError('slice bounds are not integers') from None
    if not 0<=start<=stop<=prep['n']:raise ValueError('slice outside the prepared input')
    return {'n':stop-start,**{k:prep[k][start:stop] for k in PREPARED}}

def gather_prepared(prep,index):
    """Rows `index` (ascending absolute positions, Amendment E) of a prepared input as contiguous copies (arr[idx]), with
    the index itself (int64) for the scatter back."""
    idx=np.asarray(index,dtype=np.int64)
    if idx.ndim!=1 or (idx.size and (idx[0]<0 or idx[-1]>=prep['n'] or np.any(np.diff(idx)<=0))):raise ValueError('gather index is not ascending inside the prepared input')
    return {'n':int(idx.size),**{k:np.ascontiguousarray(prep[k][idx]) for k in PREPARED},'index':idx}

def scatter(results):
    """The inverse of the gathers: each result row goes back to its input position (out[idx] = part); every position of
    0 .. n-1 must be covered exactly once."""
    n=sum(r['n'] for r in results);seen=np.zeros(n,dtype=bool);out={}
    for r in results:
        idx=np.asarray(r['index'],dtype=np.int64)
        if idx.size!=r['n'] or (idx.size and (idx.min()<0 or idx.max()>=n)) or seen[idx].any():raise ValueError('scatter index does not partition the rows')
        seen[idx]=True
    if not seen.all():raise ValueError('scatter index does not cover every row')
    _same_models(results)
    for m in results[0]['models']:           # the models present in the parts (Amendment G4.3)
        out[m]={}
        for k in ('status','flags')+FIELDS:
            first=results[0]['models'][m][k];col=np.empty(n,dtype=first.dtype)
            for r in results:col[np.asarray(r['index'],dtype=np.int64)]=r['models'][m][k]
            out[m][k]=col
    return {'n':n,'models':out}

def run(prep,params,models=ALL_MODELS):
    """The listed models only (Amendment G4.3; default ALL_MODELS, mask 7)."""
    return {'n':prep['n'],'models':{m:evaluate_model(m,prep,params) for m in check_variant_models(models)}}

def _same_models(results):
    if any(set(r['models'])!=set(results[0]['models']) for r in results):raise ValueError('parts hold different models')

def concat(results):
    """Rows of several `run` results in order. An empty list is out of contract (the adapter runs an empty input)."""
    _same_models(results)
    return {'n':sum(r['n'] for r in results),'models':{m:{k:np.concatenate([r['models'][m][k] for r in results]) for k in ('status','flags')+FIELDS} for m in results[0]['models']}}

def materialize(result):
    """Python columnar lists in the form of reference.run (statuses as text, flags as int, NaN for non-OK fields)."""
    return {'n':result['n'],'models':{m:{'status':[STATUSES[c] for c in col['status'].tolist()],'flags':col['flags'].tolist(),**{f:col[f].tolist() for f in FIELDS}}
                                      for m,col in result['models'].items()}}

def runtime_record(cpu_module='numpy._core._multiarray_umath'):
    """NumPy runtime SIMD dispatch (the simd_extensions part of np.show_runtime()), labeled as a CPU-specific path (spec 5),
    and the BLAS thread variables as the process sees them (the bench profile sets them; a worker records them).
    The CPU tables live in a private NumPy module (the one np.show_runtime() reads under the pinned NumPy 2.3.3). If a NumPy
    lacks them, the record fails closed: simd status "unknown" with the reason, never a crash and never an empty list
    presented as a measurement."""
    import importlib
    try:
        mod=importlib.import_module(cpu_module)
        baseline,dispatch,features=list(mod.__cpu_baseline__),list(mod.__cpu_dispatch__),dict(mod.__cpu_features__)
        simd={'status':'recorded','baseline':baseline,'found':[f for f in dispatch if features.get(f)],'not_found':[f for f in dispatch if not features.get(f)]}
    except (ImportError,AttributeError,TypeError) as exc:
        simd={'status':'unknown','reason':'NumPy CPU dispatch tables unavailable: '+type(exc).__name__,'baseline':None,'found':None,'not_found':None}
    return {'numpy':np.__version__,'scipy':scipy.__version__,'simd':simd,
            'label':SIMD_LABEL,'blas_threads_env':{k:os.environ.get(k) for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS')}}
