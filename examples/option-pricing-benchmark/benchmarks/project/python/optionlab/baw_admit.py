"""The shared Barone-Adesi-Whaley pre-check `baw_admit` and the shared S* transcription `critical_price` (spec Amendment G
item G2.3; the approved source-verification record Appendix G-BAW, items R2-R5 and R12 F5, F6). QL_VERSION 1.43.

QuantLib attribution (Amendment B item 9): transcribed operation by operation from the retained QuantLib 1.43 release
benchmarks/project/third_party/sources/QuantLib-1.43.tar.gz (sha256 b41206ccc4ba39b5e86bdc940d51138222b352f79d2c6fc68649f9c9bbe58701,
tag v1.43), paths below ql/:
- pricingengines/vanilla/baroneadesiwhaleyengine.cpp:39-138 (criticalPrice: QL_REQUIRE 45-48, seed 50-74, map 79-96 and
  113-118, loops 97-110 and 119-131) -> `_seed`, `_kcoef`, `_qexp`, `_map`, `_update`, `critical_price`;
- pricingengines/blackformula.cpp:40-54, 59-98 (checkParameters, blackFormula with discount 1.0 and displacement 0.0,
  blackformula.hpp:46-51) -> `black_formula`;
- math/comparison.hpp:78-90 (close(x, y, n)) -> `close_n`;
- termstructures/yield/flatforward.hpp:102-105, interestrate.hpp:69-71, interestrate.cpp:53-54 (discount 1.0/exp(r t) at
  t = 1.0, record R5) -> `discounts`.
The certificate C(x_j) and the replay are the record's item R4 (items 3 and 4), built only from these formulas.

One scalar implementation on `math` (N1a): `py-reference`, `py-optimized` (per element) and `py-library` call these
functions; the C port is an operation-by-operation copy. Every quantity is binary64 and is evaluated in the order written
(the C++ expression order). IEEE-754 semantics: a division by zero, a log of zero or of a negative number, an exp
overflow and a pow without a real result give the C++ result (models._div, _log, _exp, _sqrt, _pow), never a Python
exception. N and n are the section 3.4 ports (optionlab.normal).

The cap: `baw_admit` reads its convergence-bound cap from the protected case parameter `baw_newton_max` (NEWTON_MAX,
loaded from the case manifest when this module loads). A test override of `CaseParams.baw_newton_max` changes only the
iteration cap that callers pass to `critical_price`, never the admitted region (P3P-15).
License: the QuantLib license (BSD-3-Clause); the copyright notices, conditions and disclaimer are in examples/option-pricing-benchmark/NOTICE-QuantLib.md."""
import math
from optionlab.normal import norm_cdf, norm_pdf, QL_EPSILON
from optionlab.models import ModelDefect, BawRunDefect, RunDefect, _div, _log, _exp, _sqrt, _max
from optionlab.params import MANIFEST_NEWTON_MAX

CALL,PUT=0,1
TOL=1e-6                            # baroneadesiwhaleyengine.cpp:198 (record R3: relative to the strike)
U=2.0**-53                          # unit roundoff (record R4 item 4)
NBAR=0.39894228040143273            # >= n(0)
NBAR1=0.24197072451914340           # >= n(1) = sup |d| n(d)
NEWTON_MAX=MANIFEST_NEWTON_MAX     # the protected case parameter baw_newton_max (record R3: 40), one validator: params.check_newton_max

def _finite(*xs):return all(math.isfinite(x) for x in xs)

def discounts(r1,q1):
    """(D_r, D_q) = (1.0/exp(r1*1.0), 1.0/exp(q1*1.0)): the engine's FlatForward discount at t = 1.0 (record R5)."""
    return _div(1.0,_exp(r1*1.0)),_div(1.0,_exp(q1*1.0))

def close_n(x,y,n):
    """QuantLib close(x, y, n) (math/comparison.hpp:78-90)."""
    if x==y:return True
    diff=math.fabs(x-y);tolerance=n*QL_EPSILON
    if x==0.0 or y==0.0:return diff<(tolerance*tolerance)
    return diff<=tolerance*math.fabs(x) and diff<=tolerance*math.fabs(y)

def _g(x):return '%g'%x             # C++ ostream default formatting (6 significant digits)

def black_formula(side,strike,forward,stdDev):
    """blackFormula(optionType, strike, forward, stdDev) with discount = 1.0 and displacement = 0.0 (blackformula.cpp:59-98,
    blackformula.hpp:46-51). A failed QL_REQUIRE / QL_ENSURE raises ModelDefect with QuantLib's text (order 5)."""
    displacement=0.0;discount=1.0
    if not displacement>=0.0:raise ModelDefect('displacement ('+_g(displacement)+') must be non-negative')
    if not strike+displacement>=0.0:raise ModelDefect('strike + displacement ('+_g(strike)+' + '+_g(displacement)+') must be non-negative')
    if not forward+displacement>0.0:raise ModelDefect('forward + displacement ('+_g(forward)+' + '+_g(displacement)+') must be positive')
    if not stdDev>=0.0:raise ModelDefect('stdDev ('+_g(stdDev)+') must be non-negative')
    if not discount>0.0:raise ModelDefect('discount ('+_g(discount)+') must be positive')
    sign=1 if side==CALL else -1
    if stdDev==0.0:return _max((forward-strike)*sign,0.0)*discount
    forward=forward+displacement
    strike=strike+displacement
    if strike==0.0:return forward*discount if side==CALL else 0.0
    d1=_div(_log(_div(forward,strike)),stdDev)+0.5*stdDev
    d2=d1-stdDev
    nd1=norm_cdf(sign*d1)
    nd2=norm_cdf(sign*d2)
    result=(discount*sign)*(forward*nd1-strike*nd2)
    if not result>=0.0:raise ModelDefect('negative value ('+_g(result)+') for '+_g(stdDev)+' stdDev, '+('Call' if side==CALL else 'Put')+' option, '+_g(strike)+' strike , '+_g(forward)+' forward')
    return result

def _seed(side,K,D_r,D_q,variance):
    """(n, m, bT, qu, Su, h, Si) of baroneadesiwhaleyengine.cpp:51-70."""
    n=_div(2.0*_log(_div(D_q,D_r)),variance)
    m=_div(-2.0*_log(D_r),variance)
    bT=_log(_div(D_q,D_r))
    if side==CALL:
        qu=(-(n-1.0)+_sqrt(((n-1.0)*(n-1.0))+4.0*m))/2.0
        Su=_div(K,1.0-_div(1.0,qu))
        h=_div(-(bT+2.0*_sqrt(variance))*K,Su-K)
        Si=K+(Su-K)*(1.0-_exp(h))
    else:
        qu=(-(n-1.0)-_sqrt(((n-1.0)*(n-1.0))+4.0*m))/2.0
        Su=_div(K,1.0-_div(1.0,qu))
        h=_div((bT-2.0*_sqrt(variance))*K,K-Su)
        Si=Su+(K-Su)*_exp(h)
    return n,m,bT,qu,Su,h,Si

def _kcoef(D_r,variance):
    """The coefficient K of lines 83-86 (and 205-208): -2 ln(D_r)/(v (1 - D_r)) unless close(D_r, 1.0, 1000), else 2/v."""
    if not close_n(D_r,1.0,1000):return _div(-2.0*_log(D_r),variance*(1.0-D_r))
    return _div(2.0,variance)

def _qexp(side,n,Kc):
    """Q of line 91 (call) or 113 (put); `4 * K` and `/ 2` are exact conversions of the integer literals."""
    if side==CALL:return (-(n-1.0)+_sqrt(((n-1.0)*(n-1.0))+4.0*Kc))/2.0
    return (-(n-1.0)-_sqrt(((n-1.0)*(n-1.0))+4.0*Kc))/2.0

def _map(side,Si,K,D_r,D_q,variance,Q):
    """(LHS, RHS, bi) at Si: lines 79-96 (call) / 79-88 and 113-118 (put), the same expressions as the loop bodies
    (99-109, 121-130). The blackFormula checks raise ModelDefect (record R2: before the loop test)."""
    forwardSi=_div(Si*D_q,D_r)
    d1=_div(_log(_div(forwardSi,K))+0.5*variance,_sqrt(variance))
    temp=black_formula(side,K,forwardSi,_sqrt(variance))*D_r
    if side==CALL:
        LHS=Si-K
        RHS=temp+_div((1.0-D_q*norm_cdf(d1))*Si,Q)
        bi=D_q*norm_cdf(d1)*(1.0-_div(1.0,Q))+_div(1.0-_div(D_q*norm_pdf(d1),_sqrt(variance)),Q)
    else:
        LHS=K-Si
        RHS=temp-_div((1.0-D_q*norm_cdf(-d1))*Si,Q)
        bi=(-D_q)*norm_cdf(-d1)*(1.0-_div(1.0,Q))-_div(1.0+_div(D_q*norm_pdf(-d1),_sqrt(variance)),Q)
    return LHS,RHS,bi

def _stop(LHS,RHS,K):
    """True when the loop of lines 97 / 119 ends: not (|LHS - RHS|/K > tolerance) (a NaN residual ends it)."""
    return not (_div(math.fabs(LHS-RHS),K)>TOL)

def _update(side,Si,K,RHS,bi):
    """Line 98 (call) / 120 (put)."""
    if side==CALL:return _div(K+RHS-bi*Si,1.0-bi)
    return _div(K-RHS+bi*Si,1.0+bi)

NEG_RATE_TEXT='the Barone-Adesi-Whaley approximation is not applicable with negative interest rates (risk-free discount factor: '

def critical_price(side,K,D_r,D_q,v,newton_max):
    """criticalPrice (lines 39-138) with the record's cap (R3, F6): returns (S_star, iterations), the count of updates.
    QuantLib has no cap: when the stop test still fails after `newton_max` updates this raises BawRunDefect('baw-cap')
    (on an admitted point a run defect, Amendment F item 8); `newton_max` updates followed by a passing stop test are legal.
    A QuantLib check raises ModelDefect with its text (order 5)."""
    if not D_r<=1.0:raise ModelDefect(NEG_RATE_TEXT+_g(D_r)+')')
    n,m,bT,qu,Su,h,Si=_seed(side,K,D_r,D_q,v)
    Q=_qexp(side,n,_kcoef(D_r,v))
    LHS,RHS,bi=_map(side,Si,K,D_r,D_q,v,Q)
    count=0
    while not _stop(LHS,RHS,K):
        if count>=newton_max:raise BawRunDefect('baw-cap')
        Si=_update(side,Si,K,RHS,bi)
        count+=1
        LHS,RHS,bi=_map(side,Si,K,D_r,D_q,v,Q)
    return Si,count

def sstar(side,K,D_r,D_q,v,newton_max,plant_nan=False):
    """S* of an admitted American-branch point for the engine value and the stencil side test (record R7, R8): the
    `critical_price` result, checked after the iteration: a non-finite S* raises BawRunDefect('baw-nonfinite-sstar').
    `plant_nan` (test-only parameter set, never in a timed run; G2.3 planted defect) replaces S* by NaN before the check."""
    Sk,_=critical_price(side,K,D_r,D_q,v,newton_max)
    if plant_nan:Sk=math.nan
    if not math.isfinite(Sk):raise BawRunDefect('baw-nonfinite-sstar')
    return Sk

def _sups(dlo,dhi):
    """(s_n, s_dn) over [dlo, dhi] (record R4 item 4): sup n(d) = n_bar e^(-d_min^2/2)(1 + 2^-40), d_min the point nearest 0;
    sup |d| n(d) = n_bar1 when the range holds 1 or -1, else the larger end value (1 + 2^-40); both 1e-299 when d_min >= 37.5."""
    dmin=0.0 if dlo<=0.0<=dhi else min(math.fabs(dlo),math.fabs(dhi))
    if dmin>=37.5:return 1e-299,1e-299
    s_n=NBAR*math.exp(-(dmin*dmin)/2.0)*(1.0+2.0**-40)
    if dlo<=1.0<=dhi or dlo<=-1.0<=dhi:s_dn=NBAR1
    else:
        ends=[math.fabs(d)*(NBAR*math.exp(-(d*d)/2.0)) for d in (dlo,dhi)]
        s_dn=_max(ends[0],ends[1])*(1.0+2.0**-40)
    return s_n,s_dn

def certificate(side,x0,K,D_r,D_q,v,Q,LHS,RHS,bi,cap=None):
    """The closed-form certificate C(x0) of record R4 item 4 at an iterate x0 with the computed LHS, RHS and bi of the map
    there. Returns N_C (the proven number of further updates, 0..cap) or None when the certificate fails. Every check is
    evaluated in binary64 in the order the record writes it."""
    cap=NEWTON_MAX if cap is None else cap
    sig=_sqrt(v);aQ=math.fabs(Q);tol=TOL
    gh=LHS-RHS
    dh=(1.0-bi) if side==CALL else (-1.0-bi)
    if not _finite(gh,dh) or dh==0.0:return None
    bhat=math.fabs(gh/dh)
    w=2.0**-24*(x0+K)
    R=8.0*bhat+w
    xlo=x0-R;xhi=x0+R
    if not xlo>0.0 or not _finite(xhi):return None
    Sigb=D_q*math.fabs(1.0-1.0/Q)+(1.0+NBAR*D_q/sig)/aQ
    Gam=D_q*xhi+D_r*K+(1.0+D_q)*xhi/aQ
    nu=2.0*(1.0+1.5*v)/sig+6.0
    cr=8.0*U*(nu+4.0)
    dg=cr*(Gam+xhi+K)
    db=cr*Sigb+U*D_q*sig
    dlow=math.fabs(dh)*(1.0-U)-db
    if not dlow>0.0:return None
    beta=(math.fabs(gh)+dg)/dlow
    llo=_log(xlo*D_q/D_r/K);lhi=_log(xhi*D_q/D_r/K)
    dlo=(llo+v/2.0)/sig;dhi=(lhi+v/2.0)/sig
    Delta=math.fabs(v/sig-sig)/2.0+16.0*U*(1.0+math.fabs(llo)+math.fabs(lhi)+v)/sig+16.0*U*(math.fabs(dlo)+math.fabs(dhi))
    s_n,s_dn=_sups(dlo-Delta,dhi+Delta)
    L=D_q/(xlo*sig)*(s_n+s_n/aQ+s_dn/(sig*aQ))*(1.0+2.0**-30)
    M=math.fabs(dh)*(1.0+U)+db+L*R
    m=dlow-L*R
    if not m>0.0:return None
    if not db+U*(1.0+Sigb)<=m/2.0:return None
    eta=2.0*(cr*Gam+3.0*U*(K+Gam+Sigb*xhi)+2.0*xhi*db+U*xhi*(1.0+Sigb))/m+2.0*U*xhi
    if not (4.0*beta+2.0*eta+4.0*U*xhi<=R and 2.0*eta<=w):return None
    target=0.25*tol*K
    if not M*2.0*eta+dg<=target:return None
    rho=L*(beta+eta)/m
    if not rho<=0.5*(1.0-2.0**-20):return None
    if M*2.0*(beta+eta)<=target:return 0
    b=2.0*rho
    for k in range(1,cap+1):
        b=b*b
        if M*_max(_div(b*m,L),2.0*eta)<=target:return k
    return None

def baw_admit_rates(side,r1,q1):
    """The checks of `baw_admit` that do not depend on the volatility (record R4 items 1, 2a for D_r and D_q, 2b), at the
    mapped rates r1 = r*T, q1 = q*T: the pre-engine row check of py-reference (exclusion reason `row`). Returns
    (in_scope, admitted). When it admits, `baw_admit` still decides each evaluation."""
    D_r,D_q=discounts(r1,q1)
    if D_q>=1.0 and side==CALL:return False,True
    if not (_finite(D_r,D_q) and D_r>0.0 and D_q>0.0):return True,False
    if not D_r<=1.0:return True,False
    return True,True

def baw_admit(side,S,K,r1,q1,v,*,cap=None):
    """(in_scope, admitted) of one BAW engine evaluation (record R4): mapped rates r1 = r*T, q1 = q*T and the engine
    variance v = sigma'*sigma'*1.0. in_scope is False exactly in QuantLib's European branch (line 167: D_q >= 1 and a call),
    which is always admitted. Otherwise admitted is False at the first failed check of R4 item 2, in its order, and True
    when the replay with certificate (item 3) proves that the engine's stop test passes within NEWTON_MAX updates.
    `cap` (keyword-only, TEST-ONLY): another replay cap for the tie-vector tests and the vector generator; None (every
    production call site; a guard test enforces it) is NEWTON_MAX, the manifest value baw_newton_max = 40."""
    if cap is None:cap=NEWTON_MAX
    elif isinstance(cap,bool) or not isinstance(cap,int) or cap<1:raise ValueError('cap: a positive integer required (test-only)')
    D_r,D_q=discounts(r1,q1)
    if D_q>=1.0 and side==CALL:return False,True                                       # 1. branch gate
    if not (_finite(D_r,D_q,v) and D_r>0.0 and D_q>0.0 and v>0.0):return True,False      # 2a
    if not D_r<=1.0:return True,False                                                   # 2b (lines 45-48)
    n,m,bT,qu,Su,h,Si=_seed(side,K,D_r,D_q,v)
    if not _finite(n,m,bT,qu,Su,h,Si):return True,False                                 # 2c
    if not ((Su>K) if side==CALL else (0.0<Su<K)):return True,False                     # 2d
    if not Si>0.0:return True,False                                                     # 2e
    Kc=_kcoef(D_r,v);Q=_qexp(side,n,Kc)
    if not _finite(Kc,Q) or Q==0.0:return True,False                                    # 2f
    x=Si                                                                                # 2g: replay with certificate (item 3)
    for j in range(cap+1):
        if not (_finite(x) and x>0.0):return True,False
        try:LHS,RHS,bi=_map(side,x,K,D_r,D_q,v,Q)
        except RunDefect:raise                          # H19: a run defect propagates (none reaches _map today)
        except ModelDefect:return True,False
        if not _finite(LHS,RHS,bi):return True,False
        if _stop(LHS,RHS,K):return True,True
        if j<cap:
            NC=certificate(side,x,K,D_r,D_q,v,Q,LHS,RHS,bi,cap)
            if NC is not None and j+NC<=cap:return True,True
            x=_update(side,x,K,RHS,bi)
    return True,False
