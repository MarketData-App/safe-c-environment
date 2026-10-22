"""BSM, Bjerksund-Stensland 1993 and CRR(N) as the QuantLib 1.43 engines compute them (spec 3.4; QL_VERSION 1.43).

Side 0 call, 1 put. Every price goes through the unit-maturity mapping of Amendment B item 3 (`mapping.unit`): T' = 1,
r' = r*T, q' = q*T, sigma' = sigma*sqrt(T). `price_original_T` evaluates the same algorithms with original-T arithmetic
(discounts exp(-r*T), variance sigma^2*T, CRR dt = T/N, drift r - q - sigma^2/2, no term-structure read-back); it is
only the equivalence witness of Amendment B item 3.

Transcribed from the retained QuantLib 1.43 source (paths below ql/):
- termstructures/yield/flatforward.hpp:102-104, interestrate.cpp:53-54, 91-92 (discount 1/exp(r t), implied rate
  log(compound)/t), termstructures/yieldtermstructure.cpp:30, 118-127, 154-171 (zero and forward rates, dt = 0.0001),
  termstructures/volatility/equityfx/blackvoltermstructure.hpp:304-308 (Black variance vol*vol*t);
- pricingengines/blackcalculator.cpp:65-195 (setup), 197-428 (value and greeks) -> `black`;
- pricingengines/vanilla/analyticeuropeanengine.cpp:45-114 -> `bsm_engine`;
- pricingengines/vanilla/bjerksundstenslandengine.cpp:37-48 (phi), 50-110 (analytic phi derivatives), 115-175
  (European and immediate results), 177-429 (americanCallApproximation), 432-506 (calculate) -> `bjs_engine`;
- pricingengines/vanilla/binomialengine.hpp:74-172, methods/lattices/binomialtree.{hpp:42-47,84-101, cpp:37-48},
  methods/lattices/bsmlattice.hpp:71-87, processes/blackscholesprocess.cpp:74-82, 108-129,
  pricingengines/vanilla/discretizedvanillaoption.cpp:47-77, pricingengines/greeks.cpp:25-35 -> `crr_engine`.
Barone-Adesi-Whaley (Amendment G2): optionlab.baw (engine) and optionlab.baw_admit (the shared baw_admit and S*
transcription); `baw_result`, `baw_price` and `sigma_lo('baw', ...)` here.

C arithmetic semantics (Task 11b review ruling, PL-T11B-DIV0-01): IEEE-754 binary64 is the definition, as in QuantLib
C++, which never raises on a division by zero or an overflow. Python raises where C gives inf or NaN (exp/pow overflow,
log or sqrt of a negative number, division by zero). The helpers _exp, _pow, _log and _sqrt return the IEEE-754 results
instead. A division by zero gives the IEEE result too: `_div` in the CRR engine, and `_guard`, which evaluates an engine
again in IEEE mode (the operands as `_IEEEFloat`) when a ZeroDivisionError occurs. A ZeroDivisionError never becomes a
status. The price functions evaluate the engine value only (no greek-only code inside the solve and the bumps); the
order-5 check then judges the value, and the final finiteness rule of reference._engine_greeks judges the greeks.
License: the QuantLib license (BSD-3-Clause); the copyright notices, conditions and disclaimer are in examples/option-pricing-benchmark/NOTICE-QuantLib.md."""
import math
from optionlab.normal import norm_cdf, norm_pdf, QL_EPSILON, QL_MAX_REAL
from optionlab.mapping import unit

EPS=QL_EPSILON
QL_MIN_REAL=-QL_MAX_REAL
M_SQRT2=1.41421356237309504880          # glibc math.h (QuantLib uses it when defined)
M_SQRTPI=1.77245385090551602792981      # ql/mathconstants.hpp (glibc has no M_SQRTPI)
M_PI=3.14159265358979323846             # glibc math.h
M_SQRT_2=0.7071067811865475244008443621048490392848359376887
M_1_SQRTPI=0.564189583547756286948
DT_DAY=1.0-364.0/365.0                  # Actual365Fixed yearFraction(d0, d0+365) - yearFraction(d0+1, d0+365)
RATE_DT=0.0001                          # yieldtermstructure.cpp:30

class ModelDefect(ArithmeticError):
    """An engine error: a QuantLib exception (for example CRR "negative probability"), or arithmetic that has no finite
    result in Python. The row status is MODEL_DOMAIN (spec 3.3 order 5)."""

class RunDefect(ArithmeticError):
    """A propagating run defect (Amendment H19; Appendix G-BAW R8, Appendix I-ALO R8; Amendment F item 8): never a row
    status and never a check result. It derives from ArithmeticError, not from ModelDefect (which maps to order 5), and
    every handler that maps an exception to a status or a check result re-raises it first, so the run fails as a whole."""

class BawRunDefect(RunDefect):
    """A BAW run defect (Amendment G2.3, Appendix G-BAW R8, Amendment F item 8): the stop test of the critical-price
    iteration still fails after baw_newton_max updates ('baw-cap'), or S* is not finite ('baw-nonfinite-sstar'), on an
    admitted point. Never a status: reference.evaluate re-raises it and the run fails as a whole. Since Amendment H19
    (Task A4) a subclass of RunDefect, no longer of ModelDefect: a handler of ModelDefect does not catch it."""

class AloRunDefect(RunDefect):
    """An ALO run defect (Amendment I3 R7-R8, H19; Appendix I-ALO R7, R8): a failed check of the shared NaN check on an
    admitted point (args ('alo-nan',), `site` the check site) or a loop count above its QuantLib or Boost cap (args
    ('alo-cap',), `site` the loop). Never a status."""
    def __init__(self,kind,site=''):
        self.site=site;super().__init__(kind)

class CallbackDefect(RunDefect):
    """A Python error other than RunDefect and the callback's declared stops, raised inside a ql.Brent callback of
    py-library (finding A5R-05, Task A6): SWIG turns it into RuntimeError, so without the marker a coding defect (for
    example a TypeError) would map to a row status. optionlab.library.brent_solve records it and raises this run defect
    after the solve; args ('callback-error', <exception class name>). Never a status."""

class AdmitExcluded(ModelDefect):
    """baw_admit is false before an American-branch BAW evaluation (Appendix G-BAW R4 item 9): order 5 (MODEL_DOMAIN) with
    flag bit 64 admit_excluded. `reason` is the py-reference exclusion reason: 'row', 'brent' or 'bump'."""
    def __init__(self,reason):
        self.reason=reason;super().__init__(reason)

def _div(a,b):
    """IEEE-754 a/b: a nonzero finite or infinite a over a zero b is inf with the product of the signs; 0/0 and NaN/0 are NaN."""
    a=float(a);b=float(b)
    if b!=0.0 or b!=b:return a/b
    if a==0.0 or a!=a:return math.nan
    return math.copysign(math.inf,a)*math.copysign(1.0,b)

class _IEEEFloat(float):
    """A binary64 value whose division by zero gives the IEEE-754 result (`_div`) instead of raising. Every other operation
    is float's (identical binary64 results); the type propagates through mixed float operations and the helpers below."""
    def __add__(a,b):return _IEEEFloat(float(a)+b)
    def __radd__(a,b):return _IEEEFloat(b+float(a))
    def __sub__(a,b):return _IEEEFloat(float(a)-b)
    def __rsub__(a,b):return _IEEEFloat(b-float(a))
    def __mul__(a,b):return _IEEEFloat(float(a)*b)
    def __rmul__(a,b):return _IEEEFloat(b*float(a))
    def __truediv__(a,b):return _IEEEFloat(_div(a,b))
    def __rtruediv__(a,b):return _IEEEFloat(_div(b,a))
    def __neg__(a):return _IEEEFloat(-float(a))
    def __pos__(a):return a
    def __abs__(a):return _IEEEFloat(abs(float(a)))

def _keep(v,*args):return _IEEEFloat(v) if any(type(a) is _IEEEFloat for a in args) else v

def _exp(x):
    try:return _keep(math.exp(x),x)
    except OverflowError:return _keep(math.inf,x)
def _pow(a,b):
    try:return _keep(math.pow(a,b),a,b)
    except OverflowError:return _keep(math.inf if a>0.0 or float(b).is_integer() and b%2==0 else -math.inf,a,b)
    except (ValueError,ZeroDivisionError):
        if a==0.0 and b<0.0:return _keep(math.inf,a,b)
        return _keep(math.nan,a,b)
def _log(x):
    if x>0.0:return _keep(math.log(x),x)
    if x==0.0:return _keep(-math.inf,x)
    return _keep(math.nan,x)
def _sqrt(x):
    if x>=0.0:return _keep(math.sqrt(x),x)
    return _keep(math.nan,x)
def _sq(x):return x*x
def _max(a,b):return b if a<b else a        # std::max
def close(x,y):
    """QuantLib close(x, y) (math/comparison.hpp:59-76)."""
    if x==y:return True
    diff=math.fabs(x-y);tolerance=42*QL_EPSILON
    if x==0.0 or y==0.0:return diff<tolerance*tolerance
    return diff<=tolerance*math.fabs(x) and diff<=tolerance*math.fabs(y)

# ---- term-structure arithmetic (flat continuous curves, Actual365Fixed) ----
def discount(rate,t):return 1.0/_exp(rate*t)
def implied_rate(compound,t):
    if compound==1.0:return 0.0
    return _log(compound)/t
def zero_rate(rate,t):
    """YieldTermStructure::zeroRate(Time t, Continuous): t = 0 is replaced by dt = 0.0001."""
    if t==0.0:t=RATE_DT
    return implied_rate(1.0/discount(rate,t),t)
def forward_rate(rate,t1,t2):
    return implied_rate(discount(rate,t1)/discount(rate,t2),t2-t1)

# ---- BlackCalculator (plain vanilla payoff) ----
class Black:
    """BlackCalculator(optionType, strike, forward, stdDev, discount) (blackcalculator.cpp:65-195, 197-428)."""
    def __init__(self,side,strike,forward,stdDev,disc):
        self.side=side;self.strike=strike;self.forward=forward;self.stdDev=stdDev;self.discount=disc;self.variance=stdDev*stdDev
        if stdDev>=QL_EPSILON:
            if close(strike,0.0):
                self.d1=QL_MAX_REAL;self.d2=QL_MAX_REAL;cum_d1=1.0;cum_d2=1.0;n_d1=0.0;n_d2=0.0
            else:
                self.d1=_log(forward/strike)/stdDev+0.5*stdDev
                self.d2=self.d1-stdDev
                cum_d1=norm_cdf(self.d1);cum_d2=norm_cdf(self.d2);n_d1=norm_pdf(self.d1);n_d2=norm_pdf(self.d2)
        else:
            if close(forward,strike):
                self.d1=0;self.d2=0;cum_d1=0.5;cum_d2=0.5;n_d1=M_SQRT_2*M_1_SQRTPI;n_d2=M_SQRT_2*M_1_SQRTPI
            elif forward>strike:
                self.d1=QL_MAX_REAL;self.d2=QL_MAX_REAL;cum_d1=1.0;cum_d2=1.0;n_d1=0.0;n_d2=0.0
            else:
                self.d1=QL_MIN_REAL;self.d2=QL_MIN_REAL;cum_d1=0.0;cum_d2=0.0;n_d1=0.0;n_d2=0.0
        self.x=strike;self.DxDstrike=1.0;self.DxDs=0.0
        if side==0:
            self.alpha=cum_d1;self.DalphaDd1=n_d1;self.beta=-cum_d2;self.DbetaDd2=-n_d2
        else:
            self.alpha=-1.0+cum_d1;self.DalphaDd1=n_d1;self.beta=1.0-cum_d2;self.DbetaDd2=-n_d2
    def value(self):return self.discount*(self.forward*self.alpha+self.x*self.beta)
    def _flat(self,call_atm,call_itm,call_otm,put_atm,put_itm_put,put_otm):
        if close(self.forward,self.strike):return call_atm if self.alpha>=0 else put_atm
        if self.forward>self.strike:return call_itm if self.alpha>=0 else put_itm_put
        return call_otm if self.alpha>=0 else put_otm
    def delta(self,spot):
        if self.stdDev<=QL_EPSILON:
            DforwardDs=self.forward/spot;d=self.discount
            return self._flat(d*0.5*DforwardDs,d*1.0*DforwardDs,0.0,d*(-0.5)*DforwardDs,0.0,d*(-1.0)*DforwardDs)
        DforwardDs=self.forward/spot;temp=self.stdDev*spot
        DalphaDs=self.DalphaDd1/temp;DbetaDs=self.DbetaDd2/temp
        temp2=DalphaDs*self.forward+self.alpha*DforwardDs+DbetaDs*self.x+self.beta*self.DxDs
        return self.discount*temp2
    def deltaForward(self):
        if self.stdDev<=QL_EPSILON:
            d=self.discount;return self._flat(d*0.5,d*1.0,0.0,d*(-0.5),0.0,d*(-1.0))
        temp=self.stdDev*self.forward;DalphaDforward=self.DalphaDd1/temp;DbetaDforward=self.DbetaDd2/temp
        temp2=DalphaDforward*self.forward+self.alpha+DbetaDforward*self.x
        return self.discount*temp2
    def gamma(self,spot):
        if self.stdDev<=QL_EPSILON:return 0.0
        DforwardDs=self.forward/spot;temp=self.stdDev*spot
        DalphaDs=self.DalphaDd1/temp;DbetaDs=self.DbetaDd2/temp
        D2alphaDs2=-DalphaDs/spot*(1+self.d1/self.stdDev)
        D2betaDs2=-DbetaDs/spot*(1+self.d2/self.stdDev)
        temp2=D2alphaDs2*self.forward+2.0*DalphaDs*DforwardDs+D2betaDs2*self.x+2.0*DbetaDs*self.DxDs
        return self.discount*temp2
    def theta(self,spot,maturity):
        if close(maturity,0.0):return 0.0
        return -(_log(self.discount)*self.value()+_log(self.forward/spot)*spot*self.delta(spot)+0.5*self.variance*spot*spot*self.gamma(spot))/maturity
    def vega(self,maturity):
        if self.stdDev<=QL_EPSILON:return 0.0
        temp=_log(self.strike/self.forward)/self.variance
        DalphaDsigma=self.DalphaDd1*(temp+0.5);DbetaDsigma=self.DbetaDd2*(temp-0.5)
        temp2=DalphaDsigma*self.forward+DbetaDsigma*self.x
        return self.discount*_sqrt(maturity)*temp2
    def rho(self,maturity):
        if self.stdDev<=QL_EPSILON:
            deltaFwd=self.deltaForward();return maturity*(deltaFwd*self.forward-self.value())
        DalphaDr=self.DalphaDd1/self.stdDev;DbetaDr=self.DbetaDd2/self.stdDev
        temp=DalphaDr*self.forward+self.alpha*self.forward+DbetaDr*self.x
        return maturity*(self.discount*temp-self.value())
    def dividendRho(self,maturity):
        if self.stdDev<=QL_EPSILON:
            deltaFwd=self.deltaForward()/self.discount;return -maturity*self.discount*deltaFwd*self.forward
        DalphaDq=-self.DalphaDd1/self.stdDev;DbetaDq=-self.DbetaDd2/self.stdDev
        temp=DalphaDq*self.forward-self.alpha*self.forward+DbetaDq*self.x
        return maturity*self.discount*temp
    def strikeSensitivity(self):
        if self.stdDev<=QL_EPSILON:
            d=self.discount;return self._flat(-d*0.5,-d*1.0,-d*0.0,d*0.5,d*0.0,d*1.0)
        temp=self.stdDev*self.strike;DalphaDstrike=-self.DalphaDd1/temp;DbetaDstrike=-self.DbetaDd2/temp
        temp2=DalphaDstrike*self.forward+DbetaDstrike*self.x+self.beta*self.DxDstrike
        return self.discount*temp2

# ---- inputs of the mapped problem and of the original-T witness ----
def mapped_inputs(T,r,q,sigma):
    """(D_r, D_q, variance) of the unit-maturity problem read back as QuantLib does (t = 1.0)."""
    r1,q1,s1=unit(T,r,q,sigma)
    return discount(r1,1.0),discount(q1,1.0),s1*s1*1.0
def original_inputs(T,r,q,sigma):
    return 1.0/math.exp(r*T),1.0/math.exp(q*T),sigma*sigma*T

# ---- AnalyticEuropeanEngine ----
def bsm_engine(side,S,K,D_r,D_q,variance,greeks=True):
    """AnalyticEuropeanEngine::calculate (analyticeuropeanengine.cpp:45-114) at t = 1 (the mapped problem). With greeks=False
    only the value (the value never depends on the greeks)."""
    forwardPrice=S*D_q/D_r
    black=Black(side,K,forwardPrice,_sqrt(variance),D_r)
    if not greeks:return {'value':black.value()}
    return {'value':black.value(),'delta':black.delta(S),'gamma':black.gamma(S),'rho':black.rho(1.0),
            'dividendRho':black.dividendRho(1.0),'vega':black.vega(1.0),'theta':black.theta(S,1.0)}

# ---- Bjerksund-Stensland 1993 (bjerksundstenslandengine.cpp) ----
def _phi(S,gamma,H,I,rT,bT,variance):
    lam=(-rT+gamma*bT+0.5*gamma*(gamma-1.0)*variance)
    d=-(_log(S/H)+(bT+(gamma-0.5)*variance))/_sqrt(variance)
    kappa=2.0*bT/variance+(2.0*gamma-1.0)
    return _exp(lam)*(norm_cdf(d)-_pow((I/S),kappa)*norm_cdf(d-2.0*_log(I/S)/_sqrt(variance)))

def _phi_S(S,gamma,H,I,rT,bT,v):
    lsh=_log(S/H);lis=_log(I/S);sv=_sqrt(v)
    return _exp(bT*gamma-rT+((-1+gamma)*gamma*v)/2.)*((-(_pow(I/S,2*(gamma+bT/v))/(_exp(_sq(2*bT-v+2*gamma*v+4*lis+2*lsh)/(8.*v))*I))-1/(_exp(_sq(2*bT-v+2*gamma*v+2*lsh)/(8.*v))*S))/(M_SQRT2*M_SQRTPI*sv)+(_pow(I/S,2*(gamma+bT/v))*(2*bT+(-1+2*gamma)*v)*math.erfc((2*bT-v+2*gamma*v+4*lis+2*lsh)/(2.*M_SQRT2*sv)))/(2.*I*v))

def _phi_SS(S,gamma,H,I,rT,bT,v):
    lsh=_log(S/H);lis=_log(I/S);sv=_sqrt(v)
    ex=_exp(_sq(2*bT-v+2*gamma*v+4*lis+2*lsh)/(8.*v))
    ey=_exp(_sq(2*bT+(-1+2*gamma)*v+2*lsh)/(8.*v))
    return (_exp(bT*gamma-rT+((-1+gamma)*gamma*v)/2.)*((M_SQRT2*I*v*sv)/ey+(2*M_SQRT2*_pow(I/S,2*(gamma+bT/v))*S*sv*(2*bT+(-1+2*gamma)*v))/ex-2*_sqrt(M_PI)*_pow(I/S,2*(gamma+bT/v))*S*(bT+gamma*v)*(2*bT+(-1+2*gamma)*v)*math.erfc((2*bT-v+2*gamma*v+4*lis+2*lsh)/(2.*M_SQRT2*sv))+(M_SQRT2*I*sv*(bT+(-0.5+gamma)*v+lsh))/ey-(_pow(I/S,2*(gamma+bT/v))*S*sv*(2*bT-3*v+2*gamma*v+4*lis+2*lsh))/(M_SQRT2*ex)))/(2.*I*M_SQRTPI*_sq(S*v))

def _phi_gamma(S,gamma,H,I,rT,bT,v):
    lsh=_log(S/H);lis=_log(I/S);sv=_sqrt(v)
    return _exp(bT*gamma-rT+((-1+gamma)*gamma*v)/2)*(((-_exp(-_sq(2*bT-v+2*gamma*v+2*lsh)/(8*v))+_pow(I/S,-1+2*gamma+(2*bT)/v)/_exp(_sq(2*bT-v+2*gamma*v+4*lis+2*lsh)/(8*v)))*sv)/(M_SQRT2*M_SQRTPI)+((2*bT+(-1+2*gamma)*v)*math.erfc((2*bT+(-1+2*gamma)*v+2*lsh)/(2.*M_SQRT2*sv)))/4.-(_pow(I/S,-1+2*gamma+(2*bT)/v)*math.erfc((2*bT-v+2*gamma*v+4*lis+2*lsh)/(2.*M_SQRT2*sv))*(2*bT+(-1+2*gamma)*v+4*lis))/4.)

def _phi_H(S,gamma,H,I,rT,bT,v):
    lsh=_log(S/H)
    return (_exp(bT*gamma-rT+((-1+gamma)*gamma*v)/2.)*(I/_exp(_sq(2*bT-v+2*gamma*v+2*lsh)/(8.*v))-(_pow(I/S,2*(gamma+bT/v))*S)/_exp(_sq(2*bT-v+2*gamma*v+4*_log(I/S)+2*lsh)/(8.*v))))/(H*I*_sqrt(2*M_PI)*_sqrt(v))

def _phi_I(S,gamma,H,I,rT,bT,v):
    lsh=_log(S/H);lis=_log(I/S);sv=_sqrt(v)
    return (_exp(bT*gamma-rT+((-1+gamma)*gamma*v)/2.)*_pow(I/S,2*(gamma+bT/v))*S*((2*_sqrt(2/M_PI))/(_exp(_sq(2*bT-v+2*gamma*v+4*lis+2*lsh)/(8.*v))*sv)+(1-2*gamma-(2*bT)/v)*math.erfc((2*bT-v+2*gamma*v+4*lis+2*lsh)/(2.*M_SQRT2*sv))))/(2.*I*I)

def _phi_rt(S,gamma,H,I,rT,bT,v):
    lsh=_log(S/H)
    return (_exp(bT*gamma-rT+((-1+gamma)*gamma*v)/2.)*(-(I*math.erfc((2*bT-v+2*gamma*v+2*lsh)/(2.*_sqrt(2*v))))+_pow(I/S,2*(gamma+bT/v))*S*math.erfc((2*bT-v+2*gamma*v+4*_log(I/S)+2*lsh)/(2.*_sqrt(2*v)))))/(2.*I)

def _phi_bt(S,gamma,H,I,rT,bT,v):
    lsh=_log(S/H);lis=_log(I/S);sv=_sqrt(v)
    return (_exp(bT*gamma-rT+((-1+gamma)*gamma*v)/2.)*(M_SQRT2*(-(I/_exp(_sq(2*bT-v+2*gamma*v+2*lsh)/(8.*v)))+(_pow(I/S,2*(gamma+bT/v))*S)/_exp(_sq(2*bT-v+2*gamma*v+4*lis+2*lsh)/(8.*v)))*sv+gamma*I*_sqrt(M_PI)*v*math.erfc((2*bT-v+2*gamma*v+2*lsh)/(2.*M_SQRT2*sv))-M_SQRTPI*_pow(I/S,2*(gamma+bT/v))*S*math.erfc((2*bT-v+2*gamma*v+4*lis+2*lsh)/(2.*M_SQRT2*sv))*(gamma*v+2*lis)))/(2.*I*_sqrt(M_PI)*v)

def _phi_v(S,gamma,H,I,rT,bT,v):
    lsh=_log(S/H);lis=_log(I/S);sv=_sqrt(v)
    er=math.erfc((2*bT-v+2*gamma*v+4*lis+2*lsh)/(2.*M_SQRT2*sv))
    return (_exp(bT*gamma-rT+((-1+gamma)*gamma*v)/2.)*(((-1+gamma)*gamma*(I*math.erfc((2*bT-v+2*gamma*v+2*lsh)/(2.*M_SQRT2*sv))-_pow(I/S,2*(gamma+bT/v))*S*er))/(2.*I)+(2*bT*_pow(I/S,-1+2*gamma+(2*bT)/v)*er*lis)/(v*v)+(2*bT+v-2*gamma*v+2*lsh)/(2.*_exp(_pow(2*bT+(-1+2*gamma)*v+2*lsh,2.0)/(8.*v))*M_SQRT2*M_SQRTPI*v*sv)-(_pow(I/S,-1+2*gamma+(2*bT)/v)*(2*bT+v-2*gamma*v+4*lis+2*lsh))/(2.*_exp(_sq(2*bT-v+2*gamma*v+4*lis+2*lsh)/(8.*v))*M_SQRT2*M_SQRTPI*v*sv)))/2.

def _european_call(S,X,rfD,dD,variance,t=1.0):
    """europeanCallResults (lines 115-149); t = the year fraction of the mapped problem (1.0)."""
    forwardPrice=S*dD/rfD
    black=Black(0,X,forwardPrice,_sqrt(variance),rfD)
    res={'value':black.value(),'delta':black.delta(S),'gamma':black.gamma(S),'rho':black.rho(t),'dividendRho':black.dividendRho(t),
         'vega':black.vega(t),'theta':black.theta(S,t),'strikeSensitivity':black.strikeSensitivity()}
    res['strikeGamma']=res['gamma']*_sq(S/X)
    return res

def _immediate(S,X):
    """immediateExercise (lines 152-175)."""
    delta=1.0 if S>=X else 0.0
    return {'value':_max(0.0,S-X),'delta':delta,'gamma':0.0,'rho':0.0,'dividendRho':0.0,'vega':0.0,'theta':0.0,
            'strikeSensitivity':-delta,'strikeGamma':0.0}

def _american_call(S,X,rfD,dD,variance,greeks=True):
    """americanCallApproximation (lines 177-429) with tq = tr = tv = 1 (the mapped problem). With greeks=False only the value
    is computed (the value never depends on the greek terms)."""
    tq=tr=tv=1.0;dtq=dtr=dtv=DT_DAY
    europeanResults=_european_call(S,X,rfD,dD,variance)
    bT=_log(dD/rfD);rT=_log(1.0/rfD)
    beta=(0.5-bT/variance)+_sqrt(_sq(bT/variance-0.5)+2.0*rT/variance)
    BInfinity=beta/(beta-1.0)*X
    B0=X if bT==rT else _max(X,rT/(rT-bT)*X)
    ht=-(bT+2.0*_sqrt(variance))*B0/(BInfinity-B0)
    I=B0+(BInfinity-B0)*(1-_exp(ht))
    fwd=S*dD/rfD
    q=_log(I/fwd)/_sqrt(variance)
    if S>=I:results=_immediate(S,X)
    elif q>12.5:results=dict(europeanResults)
    else:
        results={}
        pSb=_phi(S,beta,I,I,rT,bT,variance);pS1II=_phi(S,1.0,I,I,rT,bT,variance);pS1XI=_phi(S,1.0,X,I,rT,bT,variance)
        powb=_pow(S/I,beta)
        results['value']=((I-X)*powb*(1-pSb)+S*pS1II-S*pS1XI-X*_phi(S,0.0,I,I,rT,bT,variance)+X*_phi(S,0.0,X,I,rT,bT,variance))
        if not greeks:
            for k in ('delta','gamma','rho','dividendRho','vega','theta','strikeSensitivity','strikeGamma'):results[k]=math.nan
        else:
            sSb=_phi_S(S,beta,I,I,rT,bT,variance);sS1II=_phi_S(S,1.0,I,I,rT,bT,variance);sS1XI=_phi_S(S,1.0,X,I,rT,bT,variance)
            results['delta']=((I-X)*_pow(S/I,beta-1)*beta/I*(1-pSb)-(I-X)*powb*sSb+pS1II+S*sS1II-pS1XI-S*sS1XI
                              -X*_phi_S(S,0.0,I,I,rT,bT,variance)+X*_phi_S(S,0.0,X,I,rT,bT,variance))
            root=_sqrt(_sq(bT/variance-0.5)+2.0*rT/variance)
            betaDq=tq*(1/variance-1/(2*root)*2*(bT/variance-0.5)/variance)
            BInfinityDq=-X/_sq(beta-1.0)*betaDq
            B0Dq=0.0 if dD<=rfD else X*_log(rfD)/_sq(_log(dD))*tq
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
            B0Dr=0 if dD<=rfD else -X*tr/_log(dD)
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
    if results['value']<europeanResults['value']:results=dict(europeanResults)
    return results

def bjs_engine(side,S,K,D_r,D_q,variance,greeks=True):
    """BjerksundStenslandApproximationEngine::calculate (lines 432-506) for the mapped problem (tr = tq = 1)."""
    spot,strike,riskFreeDiscount,dividendDiscount=S,K,D_r,D_q
    if side==1:spot,strike=strike,spot;riskFreeDiscount,dividendDiscount=dividendDiscount,riskFreeDiscount
    if dividendDiscount>1.0 and riskFreeDiscount>dividendDiscount:raise ModelDefect('double-boundary case r<q<0 for a call given')
    if dividendDiscount>=1.0 and dividendDiscount>=riskFreeDiscount:res=_european_call(spot,strike,riskFreeDiscount,dividendDiscount,variance)
    else:res=_american_call(spot,strike,riskFreeDiscount,dividendDiscount,variance,greeks)
    if res['value']<(spot-strike)*(1+10*QL_EPSILON):res=_immediate(spot,strike)
    if side==1:
        res=dict(res);res['delta'],res['strikeSensitivity']=res['strikeSensitivity'],res['delta']
        res['gamma'],res['strikeGamma']=res['strikeGamma'],res['gamma']
        res['rho'],res['dividendRho']=res['dividendRho'],res['rho']
        tr=tq=1.0;res['rho']*=tr/tq;res['dividendRho']*=tq/tr
    return res

# ---- CRR binomial engine ----
def crr_mapped_tree(T,r,q,sigma,steps):
    """Tree constants of BinomialVanillaEngine<CoxRossRubinstein> for the mapped problem: zero rates read back at T' = 1,
    flat curves built again from them, the process drift over [0, 0.0001], dx = sqrt(v*v*dt - v*v*0), discount exp(-r dt)."""
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

def crr_original_tree(T,r,q,sigma,steps):
    """Original-T CRR witness with QuantLib's drift arithmetic on the original-T curves (Amendment D item 1): zero rates read
    back at T, flat curves built again, the drift as forward-rate differences over [0, h_fd = 1e-4] years."""
    rz=implied_rate(1.0/discount(r,T),T);qz=implied_rate(1.0/discount(q,T),T)
    dt=T/steps
    drift=forward_rate(rz,0.0,0.0+RATE_DT)-forward_rate(qz,0.0,0.0+RATE_DT)-0.5*sigma*sigma
    dx=_sqrt(sigma*sigma*(0.0+dt)-sigma*sigma*0.0);disc=_exp(-rz*dt)
    return dx,drift*dt,disc,(r,q,sigma)

def crr_exact_drift_tree(T,r,q,sigma,steps,mapped):
    """CRR with the exact drift r - q - sigma^2/2 and no term-structure read-back, in the mapped (T' = 1) or the original-T
    variables: the second CRR witness of Amendment D item 1."""
    if mapped:r,q,sigma=unit(T,r,q,sigma);T=1.0
    dt=T/steps;return math.sqrt(sigma*sigma*dt),(r-q-0.5*sigma*sigma)*dt,math.exp(-r*dt)

def crr_price_exact_drift(side,S,K,T,r,q,sigma,steps,mapped):
    dx,dps,disc=crr_exact_drift_tree(T,r,q,sigma,steps,mapped)
    return _guard(crr_engine,side,S,K,dx,dps,disc,steps,greeks=False)['value']

CRR_WITNESS_HFD=RATE_DT
def crr_witness_bound(S,K,T,V):
    """Amendment D item 1: max(S, K)(1 + T) 4 eps / h_fd + 1e-12 max(1, |V|)."""
    return max(S,K)*(1.0+T)*4*2.0**-52/CRR_WITNESS_HFD+1e-12*max(1.0,abs(V))

def crr_engine(side,S,K,dx,driftPerStep,disc,steps,american=True,theta_rates=None,greeks=True):
    """CoxRossRubinstein tree, BlackScholesLattice rollback and the engine greeks (binomialengine.hpp:115-171). Divisions are
    IEEE (`_div`): QuantLib computes the lattice greeks with no guard, a 0/0 delta is NaN and never decides the status of a
    solve evaluation. With greeks=False only the value."""
    if steps<2:raise ModelDefect('Expect 3 nodes in grid at second step')
    pu=0.5+_div(0.5*driftPerStep,dx)
    pd=1.0-pu
    if not pu<=1.0:raise ModelDefect('negative probability')
    if not pu>=0.0:raise ModelDefect('negative probability')
    growth={j:S*_exp(j*dx) for j in range(-steps,steps+1)}            # underlying(i, index) = x0*exp((2 index - i) dx)
    payoff=(lambda s:_max(s-K,0.0)) if side==0 else (lambda s:_max(K-s,0.0))
    values=[_max(0.0,payoff(growth[2*j-steps])) for j in range(steps+1)]   # reset: zeros, then the exercise condition
    va2=va1=None
    for i in range(steps-1,-1,-1):
        new=[(pd*values[j]+pu*values[j+1])*disc for j in range(i+1)]
        if american:                                                   # American: max(value, payoff) at every step, t = 0 included
            new=[_max(new[j],payoff(growth[2*j-i])) for j in range(i+1)]
        values=new
        if i==2:va2=list(values)
        elif i==1:va1=list(values)
    p0=values[0]
    if not greeks:return {'value':p0}
    p2u,p2m,p2d=va2[2],va2[1],va2[0];s2u,s2m,s2d=growth[2],growth[0],growth[-2]
    delta2u=_div(p2u-p2m,s2u-s2m);delta2d=_div(p2m-p2d,s2m-s2d)
    gamma=_div(delta2u-delta2d,(s2u-s2d)/2)
    p1u,p1d=va1[1],va1[0];s1u,s1d=growth[1],growth[-1]
    delta=_div(p1u-p1d,s1u-s1d)
    out={'value':p0,'delta':delta,'gamma':gamma}
    if theta_rates is not None:
        r,q,v=theta_rates;u=S
        out['theta']=r*p0-(r-q)*u*delta-0.5*v*v*u*u*gamma
    return out

def _ieee_arg(a):
    if type(a) is float:return _IEEEFloat(a)
    if type(a) is tuple:return tuple(_ieee_arg(x) for x in a)
    return a
def _plain(v):
    if isinstance(v,dict):return {k:_plain(x) for k,x in v.items()}
    return float(v) if type(v) is _IEEEFloat else v

def _guard(fn,*args,**kw):
    """An engine call with IEEE-754 division (PL-T11B-DIV0-01). The plain call runs first (no cost on the ordinary path);
    when it raises ZeroDivisionError, the same engine runs again with every float operand as `_IEEEFloat`, so each division
    by zero gives +-inf or NaN as in QuantLib C++, and the binary64 results of all other operations are unchanged. The
    result holds plain floats. A ZeroDivisionError in IEEE mode would be a transcription defect and propagates."""
    try:return fn(*args,**kw)
    except ZeroDivisionError:pass
    return _plain(fn(*(_ieee_arg(a) for a in args),**{k:_ieee_arg(v) for k,v in kw.items()}))

# ---- public price functions (mapped) ----
def bsm_result(side,S,K,T,r,q,sigma,greeks=True):return _guard(bsm_engine,side,S,K,*mapped_inputs(T,r,q,sigma),greeks=greeks)
def bjs_result(side,S,K,T,r,q,sigma,greeks=True):return _guard(bjs_engine,side,S,K,*mapped_inputs(T,r,q,sigma),greeks=greeks)
def crr_result(side,S,K,T,r,q,sigma,steps,american=True,greeks=True):
    dx,dps,disc,rates=crr_mapped_tree(T,r,q,sigma,steps)
    return _guard(crr_engine,side,S,K,dx,dps,disc,steps,american,rates,greeks=greeks)

def bsm_price(side,S,K,T,r,q,sigma):return bsm_result(side,S,K,T,r,q,sigma,greeks=False)['value']
def bjs_price(side,S,K,T,r,q,sigma):return bjs_result(side,S,K,T,r,q,sigma,greeks=False)['value']
def crr_price(side,S,K,T,r,q,sigma,steps,american=True):return crr_result(side,S,K,T,r,q,sigma,steps,american,greeks=False)['value']

def bsm(side,S,K,T,r,q,sigma):
    """BSM price and greeks in output units (price, delta, gamma, theta/365, vega/100, rho/100), mapped engine greeks."""
    from optionlab.mapping import greeks_from_unit
    e=bsm_result(side,S,K,T,r,q,sigma)
    g=greeks_from_unit(T,r,q,sigma,{'delta_U':e['delta'],'gamma_U':e['gamma'],'theta_U':e['theta'],'vega_U':e['vega'],'rho_U':e['rho'],'div_rho_U':e['dividendRho']})
    return e['value'],g['delta'],g['gamma'],g['theta'],g['vega'],g['rho']

def baw_result(side,S,K,T,r,q,sigma,params,greeks=True):
    """BaroneAdesiWhaleyApproximationEngine (optionlab.baw.engine) through the unit-maturity mapping, with the case
    parameter baw_newton_max and the test-only planted non-finite S* of `params`. The caller runs baw_admit first."""
    from optionlab import baw
    return _guard(baw.engine,side,S,K,*mapped_inputs(T,r,q,sigma),greeks=greeks,newton_max=params.baw_newton_max,plant_nan=params.baw_plant_nan_sstar)
def baw_price(side,S,K,T,r,q,sigma,params):return baw_result(side,S,K,T,r,q,sigma,params,greeks=False)['value']

def price(model,side,S,K,T,r,q,sigma,params):
    """The engine value of `model` through the unit-maturity mapping (every variant's definition). For `baw` the caller runs
    baw_admit first (reference.price_function does)."""
    if model=='bsm':return bsm_price(side,S,K,T,r,q,sigma)
    if model=='bjs':return bjs_price(side,S,K,T,r,q,sigma)
    if model=='crr':return crr_price(side,S,K,T,r,q,sigma,params.crr_steps)
    if model=='baw':return baw_price(side,S,K,T,r,q,sigma,params)
    if model=='alo':
        from optionlab import alo
        return alo.price(side,S,K,T,r,q,sigma,params)
    raise ValueError('unknown model')

def price_original_T(model,side,S,K,T,r,q,sigma,params):
    """Equivalence witness (Amendment B item 3): the same algorithms with original-T arithmetic."""
    if model=='bsm':return _guard(bsm_engine,side,S,K,*original_inputs(T,r,q,sigma),greeks=False)['value']
    if model=='bjs':return _guard(bjs_engine,side,S,K,*original_inputs(T,r,q,sigma),greeks=False)['value']
    if model=='crr':
        dx,dps,disc,_=crr_original_tree(T,r,q,sigma,params.crr_steps)
        return _guard(crr_engine,side,S,K,dx,dps,disc,params.crr_steps,greeks=False)['value']
    if model=='baw':
        from optionlab import baw
        return _guard(baw.engine,side,S,K,*original_inputs(T,r,q,sigma),greeks=False,newton_max=params.baw_newton_max)['value']
    raise ValueError('unknown model')

def sigma_lo(model,side,T,r,q,params):
    """Brent's lower end xMin (spec 3.4): BSM 1e-4; CRR max(1e-4, 1.001(|b| + h_r) sqrt(T/N)); BjS max(1e-4, sigma_trig,
    sigma_carry) with b the carry of the evaluated call (b' = q - r for a transformed put); BAW max(1e-4, sigma_trig) with
    b = r - q for a call and q - r for a put (Appendix G-BAW R9, R12 F3); ALO max(1e-4, (C_e max(0, d_e + h_r)) sqrt(T))
    (Appendix I-ALO R9, R12 E-ALO-1: e = alo_equation(r T, q T) of the row; (rho, delta) = (r, q) for a put and (q, r) for
    a call; d_A = rho - delta, C_A = 0.75; d_B = delta - rho, C_B = 0.003; validity: T >= 1 h and |r' - q'| >= 1e-6)."""
    hr=params.h_r
    if model=='bsm':return 1e-4
    if model=='alo':                    # Appendix I-ALO R9, R12 E-ALO-1 (approved): the closed form, binary64 in this order
        from optionlab.alo_equation import alo_equation
        rho,dl=(r,q) if side==1 else (q,r)
        r1,q1,_=unit(T,r,q,1.0)
        if alo_equation(r1,q1)=='FP_A':C,d=0.75,rho-dl
        else:C,d=0.003,dl-rho
        return _max(1e-4,(C*_max(0.0,d+hr))*math.sqrt(T))
    if model=='baw':                    # Appendix G-BAW R9 and R12 F3: max(1e-4, sigma_trig), the BjS sigma_trig form
        b=(r-q) if side==0 else (q-r)
        return max(1e-4,1.001*(abs(b)+hr)*math.sqrt(T)/2.0 if b<0.0 else 0.0)
    if model=='crr':return max(1e-4,1.001*(abs(r-q)+hr)*math.sqrt(T/params.crr_steps))
    b=(r-q) if side==0 else (q-r)
    trig=1.001*(abs(b)+hr)*math.sqrt(T)/2.0 if b<0.0 else 0.0
    return max(1e-4,trig,math.sqrt(2.0*(abs(b)+hr)/params.kappa_cap))

def crr_domain_ok(T,r,q,params):
    """CRR pre-engine domain check (spec 3.4): g(sigma) = sigma - (sigma^2/2 + |b| + h_r) sqrt(dt) >= 0 at both ends of
    [sigma_lo(CRR, row), 5.0 + h_sigma] (g is concave, so it then holds on the whole evaluated range)."""
    sdt=math.sqrt(T/params.crr_steps);b=abs(r-q)+params.h_r
    g=lambda s:s-(s*s/2.0+b)*sdt
    return g(sigma_lo('crr',0,T,r,q,params))>=0.0 and g(params.sigma_hi+params.h_sigma)>=0.0
