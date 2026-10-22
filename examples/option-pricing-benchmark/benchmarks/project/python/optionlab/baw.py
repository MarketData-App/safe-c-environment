"""Barone-Adesi-Whaley as QuantLib 1.43 BaroneAdesiWhaleyApproximationEngine computes it (spec Amendment G item G2; the
approved source-verification record Appendix G-BAW, items R2, R6, R8 and R12 F1, F6). QL_VERSION 1.43.

QuantLib attribution (Amendment B item 9): transcribed operation by operation from the retained QuantLib 1.43 release
benchmarks/project/third_party/sources/QuantLib-1.43.tar.gz (sha256 b41206ccc4ba39b5e86bdc940d51138222b352f79d2c6fc68649f9c9bbe58701,
tag v1.43), paths below ql/:
- pricingengines/vanilla/baroneadesiwhaleyengine.cpp:140-236 (calculate: checks 142-153 and 162, forward 163,
  BlackCalculator 164-165, branch 167, European results 169-191, American branch 195-235) -> `engine`;
- pricingengines/blackcalculator.cpp:65-75 (the BlackCalculator checks) -> `_black_checks`; the BlackCalculator value
  and greeks are optionlab.models.Black (blackcalculator.cpp:65-428, the BSM transcription);
- criticalPrice (lines 39-138) is the shared transcription optionlab.baw_admit.critical_price (record R2, R3).

The engine reads the inputs only through D_r, D_q and the variance v (record R2, R11), so it takes the mapped inputs of
the unit-maturity problem (optionlab.models.mapped_inputs). Callers run `baw_admit` before every American-branch
evaluation (record R4 item 9, G2.3); the engine itself does not.
License: the QuantLib license (BSD-3-Clause); the copyright notices, conditions and disclaimer are in examples/option-pricing-benchmark/NOTICE-QuantLib.md."""
import math
from optionlab.models import Black, ModelDefect, _div, _log, _sqrt, _pow
from optionlab.normal import norm_cdf
from optionlab.baw_admit import CALL, NEWTON_MAX, sstar, _kcoef, _g

def _black_checks(strike,forward,stdDev,disc):
    """BlackCalculator::initialize checks (blackcalculator.cpp:66-75), QuantLib's texts (order 5)."""
    if not strike>=0.0:raise ModelDefect('strike ('+_g(strike)+') must be non-negative')
    if not forward>0.0:raise ModelDefect('forward ('+_g(forward)+') must be positive')
    if not stdDev>=0.0:raise ModelDefect('stdDev ('+_g(stdDev)+') must be non-negative')
    if not disc>0.0:raise ModelDefect('discount ('+_g(disc)+') must be positive')

def engine(side,S,K,D_r,D_q,variance,greeks=True,newton_max=NEWTON_MAX,plant_nan=False):
    """BaroneAdesiWhaleyApproximationEngine::calculate at t = 1 (the mapped problem). Returns a dict:
    - European branch (line 167 true: D_q >= 1 and a call): 'branch': 'european', 'value' and, with greeks=True, every
      engine greek (delta 170, gamma 173, rho 181, dividendRho 185, vega 189, theta 190; the year fractions are 1.0);
    - American branch: 'branch': 'american', 'value', 'sstar' (S*), 'side' ('continuation' when call S < S* or put
      S > S*, the strict tests of lines 214 and 225, else 'exercise'); the engine sets only the value (record R6).
    Raises ModelDefect with QuantLib's text for a QuantLib check (order 5), and BawRunDefect('baw-cap') or
    BawRunDefect('baw-nonfinite-sstar') for the run defects of record R8 (checked after the iteration, before the value
    arithmetic of lines 213 and 223). `newton_max` is the case parameter baw_newton_max; `plant_nan` is the test-only
    planted non-finite S* (G2.3)."""
    if not S>0.0:raise ModelDefect('negative or null underlying given')            # line 162
    forwardPrice=_div(S*D_q,D_r)                                                     # line 163
    sd=_sqrt(variance)
    _black_checks(K,forwardPrice,sd,D_r)
    black=Black(side,K,forwardPrice,sd,D_r)                                          # lines 164-165
    if D_q>=1.0 and side==CALL:                                                      # line 167
        if not greeks:return {'branch':'european','value':black.value()}
        return {'branch':'european','value':black.value(),'delta':black.delta(S),'gamma':black.gamma(S),'rho':black.rho(1.0),
                'dividendRho':black.dividendRho(1.0),'vega':black.vega(1.0),'theta':black.theta(S,1.0)}
    Sk=sstar(side,K,D_r,D_q,variance,newton_max,plant_nan)                           # lines 198-200 (R8 checks inside)
    forwardSk=_div(Sk*D_q,D_r)                                                       # line 201
    d1=_div(_log(_div(forwardSk,K))+0.5*variance,_sqrt(variance))                    # lines 202-203
    n=_div(2.0*_log(_div(D_q,D_r)),variance)                                         # line 204
    Kc=_kcoef(D_r,variance)                                                          # lines 205-208
    if side==CALL:
        Q=(-(n-1.0)+_sqrt(((n-1.0)*(n-1.0))+4.0*Kc))/2.0                              # line 212
        a=_div(Sk,Q)*(1.0-D_q*norm_cdf(d1))                                          # line 213
        if S<Sk:value=black.value()+a*_pow(_div(S,Sk),Q);where='continuation'        # lines 214-216
        else:value=S-K;where='exercise'                                              # line 218
    else:
        Q=(-(n-1.0)-_sqrt(((n-1.0)*(n-1.0))+4.0*Kc))/2.0                              # line 222
        a=-_div(Sk,Q)*(1.0-D_q*norm_cdf(-d1))                                        # lines 223-224
        if S>Sk:value=black.value()+a*_pow(_div(S,Sk),Q);where='continuation'        # lines 225-227
        else:value=K-S;where='exercise'                                              # line 229
    return {'branch':'american','value':value,'sstar':Sk,'side':where}
