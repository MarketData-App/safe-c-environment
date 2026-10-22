"""The QuantLib definitions through QuantLib-Python (QL_VERSION 1.43; spec Amendment B items 2, 3 and 5).

The unit-maturity problem of Amendment B item 3: evaluation date d0, maturity d0 + 365 days, Actual365Fixed, flat
continuous r' and q' curves and a BlackConstantVol on a SimpleQuote that holds sigma' = sigma*sqrt(T). Engines:
AnalyticEuropeanEngine (BSM, European exercise), BjerksundStenslandApproximationEngine and
BinomialVanillaEngine(process, 'crr', crr_steps) (American exercise from d0 to d0 + 365).

IV: ql.Brent() with setMaxEvaluations(200) and solve(f, 1e-10, (sigma_lo + 5.0)/2, sigma_lo, 5.0) on
f(sigma) = engine NPV after quote.setValue(sigma*sqrt(T)) - mid. The Python callback applies the order-5 evaluation check
of spec 3.3 to every NPV and raises before it returns to QuantLib, so the solve stops at the same evaluation as in every
transcription. Exception texts (spec 3.3): a text that starts with "root not bracketed: f[" is BELOW_MIN or ABOVE_MAX by
the sign of f(sigma_lo); exactly "maximum number of function evaluations (200) exceeded" is NOT_CONVERGED; any other
text is MODEL_DOMAIN. The pre-engine checks (sigma_lo >= 5.0, the CRR domain check) run in Python first.
Greeks: the spec 3.6 table; a greek that the engine does not supply (CRR vega and rho) is the declared bump in the
original variables, each bumped point through the mapping, the same bumps as py-reference.

Run-defect marker (controller ruling A4-C2, finding A4R-05): SWIG turns a Python exception raised inside a ql.Brent
callback into RuntimeError. Every ql.Brent solve therefore goes through `brent_solve`, whose callback wrapper records a
models.RunDefect raised inside the callback and re-raises that same object after solve returns or fails; the status
mapping never sees it. Finding A5R-05 (Task A6): a callback raises only its declared stops (CallbackStop: an order-5
value, a QuantLib engine error of the evaluation, a failed pre check or an admission exclusion, each recorded by the
callback before it raises); any other Python error inside the callback (a coding defect such as a TypeError) is recorded
too and leaves as models.CallbackDefect (a RunDefect) after the solve, never as a status.
"""
import math
import QuantLib as ql
from optionlab.contract import ALL_MODELS
from optionlab.mapping import unit, greeks_from_unit
from optionlab.models import sigma_lo, crr_domain_ok, RunDefect, CallbackDefect
from optionlab.reference import tau_v, Checker, EngineDomain
from optionlab import counters

QL_VERSION='1.43'
D0=ql.Date(2,ql.January,2001)
BRACKET_TEXT='root not bracketed: f['
MAX_EVAL_TEXT='maximum number of function evaluations (200) exceeded'

class CallbackStop(Exception):
    """A declared stop of a ql.Brent callback (an order-5 value, an engine error of the evaluation, a failed pre check, an
    admission exclusion), raised by the callback after it records the stop; the caller maps the failed solve to a status."""

def brent_solve(f,lo,hi,guess,accuracy=1e-10,max_evaluations=200):
    """ql.Brent() with setMaxEvaluations(max_evaluations) and solve(f, accuracy, guess, lo, hi), with the run-defect marker
    of ruling A4-C2: a RunDefect raised inside the callback is recorded and re-raised (the same object) after the solve
    returns or fails. A CallbackStop leaves as the solve's own error (the caller reads its record of the stop). Any other
    exception inside the callback (A5R-05: a coding defect) is recorded as models.CallbackDefect('callback-error', class
    name) and raised after the solve, so it never maps to a status. Any other exception of the solve itself propagates
    unchanged (QuantLib errors arrive as RuntimeError)."""
    marker=[]
    def marked(x):
        try:return f(x)
        except RunDefect as e:
            marker.append(e);raise
        except CallbackStop:raise
        except Exception as exc:
            marker.append(CallbackDefect('callback-error',type(exc).__name__));raise
    solver=ql.Brent();solver.setMaxEvaluations(max_evaluations)
    try:root=solver.solve(marked,accuracy,guess,lo,hi)
    except RunDefect:raise                                         # H19: raised by the solve itself
    except Exception:
        if marker:raise marker[0] from None
        raise
    if marker:raise marker[0]
    return root

class _Problem:
    """One option of the mapped problem; `set_sigma` moves the volatility quote to sigma' = sigma*sqrt(T)."""
    def __init__(self,model,side,S,K,T,r,q,sigma,params,steps=None,european=False):
        ql.Settings.instance().evaluationDate=D0
        r1,q1,s1=unit(T,r,q,sigma);dc=ql.Actual365Fixed();self.T=T
        self.vol=ql.SimpleQuote(s1)
        rts=ql.YieldTermStructureHandle(ql.FlatForward(D0,r1,dc,ql.Continuous,ql.Annual))
        qts=ql.YieldTermStructureHandle(ql.FlatForward(D0,q1,dc,ql.Continuous,ql.Annual))
        vts=ql.BlackVolTermStructureHandle(ql.BlackConstantVol(D0,ql.NullCalendar(),ql.QuoteHandle(self.vol),dc))
        self.spot=ql.SimpleQuote(S);process=ql.BlackScholesMertonProcess(ql.QuoteHandle(self.spot),qts,rts,vts);self.process=process   # Task A6: alo-accuracy rebinds the engine scheme
        payoff=ql.PlainVanillaPayoff(ql.Option.Call if side==0 else ql.Option.Put,K)
        if model=='bsm':
            self.option=ql.VanillaOption(payoff,ql.EuropeanExercise(D0+365));engine=ql.AnalyticEuropeanEngine(process)
        elif model=='bjs':
            self.option=ql.VanillaOption(payoff,ql.AmericanExercise(D0,D0+365));engine=ql.BjerksundStenslandApproximationEngine(process)
        elif model=='crr':
            exercise=ql.EuropeanExercise(D0+365) if european else ql.AmericanExercise(D0,D0+365)
            self.option=ql.VanillaOption(payoff,exercise);engine=ql.BinomialVanillaEngine(process,'crr',steps or params.crr_steps)
        elif model=='baw':        # G-BAW2 part B: BaroneAdesiWhaleyApproximationEngine, American exercise d0 to d0 + 365 (record R5, R11)
            self.option=ql.VanillaOption(payoff,ql.AmericanExercise(D0,D0+365));engine=ql.BaroneAdesiWhaleyApproximationEngine(process)
        elif model=='alo':        # G-ALO2 part B (Amendment I4.2): QdFpAmericanEngine(process, accurateScheme(), Auto), d0 to d0 + 365
            self.option=ql.VanillaOption(payoff,ql.AmericanExercise(D0,D0+365))
            engine=ql.QdFpAmericanEngine(process,ql.QdFpAmericanEngine.accurateScheme(),ql.QdFpAmericanEngine.Auto)
        else:raise ValueError('unknown model')
        self.option.setPricingEngine(engine)
    def set_sigma(self,sigma):self.vol.setValue(sigma*math.sqrt(self.T))
    def npv(self):return self.option.NPV()

def price(model,side,S,K,T,r,q,sigma,params):
    counters.bump(model)                # test-only counters (Amendment G4.8): one engine call
    return _Problem(model,side,S,K,T,r,q,sigma,params).npv()

def crr_price(side,S,K,T,r,q,sigma,steps,params,american=True):
    """QuantLib BinomialVanillaEngine('crr', steps) on an American (d0 to d0 + 365) or European exercise (Amendment D item 0(a))."""
    return _Problem('crr',side,S,K,T,r,q,sigma,params,steps=steps,european=not american).npv()

def price_and_greeks(model,side,S,K,T,r,q,sigma,params):
    """Price and greeks in output units (spec 3.6) from the QuantLib engine of `model`."""
    pb=_Problem(model,side,S,K,T,r,q,sigma,params);o=pb.option;check=Checker(tau_v(S,K,T,r,q))   # order-5 check (review Minor 1)
    counters.bump(model)                # the engine greek call (the CRR bumps count in `price`)
    p=check(o.NPV());dU={'delta_U':o.delta(),'gamma_U':o.gamma(),'theta_U':o.theta()}
    if model in ('bsm','bjs'):dU.update(vega_U=o.vega(),rho_U=o.rho(),div_rho_U=o.dividendRho())
    else:
        lo=sigma_lo('crr',side,T,r,q,params);h=params.h_sigma;hr=params.h_r
        V=lambda s,rr:check(price('crr',side,S,K,T,rr,q,s,params))
        dU['vega_bump']=(V(sigma+h,r)-p)/h if sigma-h<lo else (V(sigma+h,r)-V(sigma-h,r))/(2.0*h)
        dU['rho_bump']=(V(sigma,r+hr)-V(sigma,r-hr))/(2.0*hr)
    g=greeks_from_unit(T,r,q,sigma,dU)
    return {'iv':sigma,'price':p,**g,'rounding_band':check.band}

class _Domain(CallbackStop):
    """Raised by the callback on a non-finite NPV or an NPV below the rounding band (spec 3.3 order 5)."""

def _solve(model,side,S,K,T,r,q,mid,params,lo):
    """QuantLib Brent on the row's engine. Returns (status, root, evaluations, f values seen, band hit)."""
    pb=_Problem(model,side,S,K,T,r,q,lo,params);tau=tau_v(S,K,T,r,q);seen=[];domain=[];band=[];engine=[]
    def f(sigma):
        pb.set_sigma(sigma)
        try:v=pb.npv()
        except RuntimeError:engine.append(sigma);raise CallbackStop('engine error') from None   # a QuantLib error: order 5 (not counted, as before)
        if not math.isfinite(v) or v<-tau:
            domain.append(sigma);raise _Domain()
        if v<0.0:band.append(sigma)
        seen.append(v-mid);return v-mid
    try:
        try:root=brent_solve(f,lo,params.sigma_hi,(lo+params.sigma_hi)/2.0)
        finally:counters.bump(model,len(seen)+len(domain))     # test-only counters (G4.8): every Brent evaluation of the engine
    except RunDefect:raise                                         # H19: a run defect propagates, also from inside the callback (A4-C2)
    except Exception as exc:                                       # QuantLib errors arrive as RuntimeError
        n=len(seen)+len(domain)
        if domain or engine:return 'MODEL_DOMAIN',math.nan,n,seen,bool(band)
        text=str(exc)
        if text.startswith(BRACKET_TEXT):return ('BELOW_MIN' if seen[0]>0.0 else 'ABOVE_MAX'),math.nan,n,seen,bool(band)
        if text==MAX_EVAL_TEXT:return 'NOT_CONVERGED',math.nan,n,seen,bool(band)
        return 'MODEL_DOMAIN',math.nan,n,seen,bool(band)
    return 'OK',root,len(seen),seen,bool(band)

def implied_vol(model,side,S,K,T,r,q,mid,params):
    """(status, sigma, evaluations) by QuantLib Brent on the row's own engine; never VanillaOption implied volatility."""
    if side not in (0,1) or not all(math.isfinite(v) for v in (S,K,T,mid)) or S<=0.0 or K<=0.0:return 'INVALID_INPUT',math.nan,0
    if T<=0.0:return 'EXPIRED',math.nan,0
    lo=sigma_lo(model,side,T,r,q,params)
    if lo>=params.sigma_hi:return 'MODEL_DOMAIN',math.nan,0
    if model=='crr' and not crr_domain_ok(T,r,q,params):return 'MODEL_DOMAIN',math.nan,0
    st,root,n,_,_=_solve(model,side,S,K,T,r,q,mid,params,lo)
    return st,root,n

NAN7=(math.nan,)*7

def evaluate(row,model,params):
    """(status, values, flags) of one row through QuantLib-Python, with the status order and flags of reference.evaluate."""
    from optionlab.reference import FLAG_BELOW_INTRINSIC, FLAG_BOUNDARY_AMBIGUOUS, FLAG_FLAT_VEGA, FLAG_ROUNDING_BAND
    side,S,K,T,bid,ask,r,q=row
    if side not in (0,1) or not all(math.isfinite(v) for v in (S,K,T,bid,ask)) or S<=0.0 or K<=0.0:return 'INVALID_INPUT',NAN7,0
    if T<=0.0:return 'EXPIRED',NAN7,0
    if bid<=0.0:return 'NO_BID',NAN7,0
    if ask<bid:return 'CROSSED',NAN7,0
    mid=(bid+ask)/2.0;lo=sigma_lo(model,side,T,r,q,params)
    if lo>=params.sigma_hi:return 'MODEL_DOMAIN',NAN7,0
    if model=='crr' and not crr_domain_ok(T,r,q,params):return 'MODEL_DOMAIN',NAN7,0
    st,iv,_,seen,band=_solve(model,side,S,K,T,r,q,mid,params,lo)
    flags=FLAG_ROUNDING_BAND if band else 0;width=1e-9*max(1.0,mid)          # Amendment D item 3
    if any(abs(v)<=width for v in seen[:2]):flags|=FLAG_BOUNDARY_AMBIGUOUS
    if st!='OK':
        if st=='BELOW_MIN' and mid<max((S-K) if side==0 else (K-S),0.0):flags|=FLAG_BELOW_INTRINSIC
        return st,NAN7,flags
    try:g=price_and_greeks(model,side,S,K,T,r,q,iv,params)
    except EngineDomain:return 'MODEL_DOMAIN',NAN7,flags
    vals=(iv,g['price'],g['delta'],g['gamma'],g['theta'],g['vega'],g['rho'])
    if not all(math.isfinite(v) for v in vals):return 'MODEL_DOMAIN',NAN7,flags
    if g['rounding_band']:flags|=FLAG_ROUNDING_BAND
    if vals[5]*100.0<1e-12:flags|=FLAG_FLAT_VEGA
    return 'OK',vals,flags

# ---- Barone-Adesi-Whaley (spec Amendment G2.3; the approved record Appendix G-BAW, R3-R8, R12 F5) ----
# QuantLib's BaroneAdesiWhaleyApproximationEngine prices every point. Before every in-scope evaluation the shared scalar
# baw_admit runs (optionlab.reference.baw_admitted -> optionlab.baw_admit.baw_admit): the row check (volatility-free part,
# MODEL_DOMAIN with bit 64), each Brent evaluation and each greek point. The stencil side test uses the shared S*
# transcription (optionlab.baw_admit.sstar), which QuantLib computes again inside the engine: this is the py-library S*
# side-test overhead that `reference_overhead` measures (G2.3, P3R2-04). The greeks follow the record's rule in
# optionlab.reference.baw_greeks with QuantLib's values. No timer runs inside the child: a hang is caught by the G2.6 call
# deadline outside it (reason baw-hang).
STUB_ENV='SAFE_C_TEST_STUB'   # test-only (G2.3; EX-3): the one stub variable of the framework; exactly BAW_STUB_REASON blocks the BAW path
BAW_STUB_REASON='baw-hang'    # the reason of the protocol stub (protocol.json stubs); the coordinator passes it only to selftest plans

def _baw_stub():
    """The blocking stub engine of the baw-hang tests: an Event wait without timeout (never set)."""
    import threading
    threading.Event().wait()

def _baw_engine(side,K,q,params,cache):
    """(value, result) of QuantLib's engine for reference.baw_greeks at a point (S, T, r, sigma). One problem per (T, r) of
    the row; S and sigma move through their quotes (the same inputs as a fresh construction). A QuantLib error raises
    models.ModelDefect with its text (order 5). Each engine call counts once (test-only counters, G4.8)."""
    from optionlab.models import ModelDefect
    def problem(S_,T_,r_,s_):
        pb=cache.get((T_,r_))
        if pb is None:pb=cache[(T_,r_)]=_Problem('baw',side,S_,K,T_,r_,q,s_,params)
        pb.spot.setValue(S_);pb.set_sigma(s_);return pb
    def value(S_,T_,r_,s_):
        pb=problem(S_,T_,r_,s_);counters.bump('baw')
        try:return pb.option.NPV()
        except RunDefect:raise                                  # H19
        except RuntimeError as exc:raise ModelDefect(str(exc)[:300]) from None
    def result(S_,T_,r_,s_):
        o=problem(S_,T_,r_,s_).option;counters.bump('baw')
        try:v=o.NPV()
        except RunDefect:raise                                  # H19
        except RuntimeError as exc:raise ModelDefect(str(exc)[:300]) from None
        try:d=o.delta()
        except RuntimeError:return {'value':v}                  # American branch: only the value is set (record R6)
        return {'value':v,'delta':d,'gamma':o.gamma(),'theta':o.theta(),'vega':o.vega(),'rho':o.rho(),'dividendRho':o.dividendRho()}
    return value,result

def _baw_side(side,K,q,params,clock=None):
    """The side of a point (record R7; reference.baw_point_side): baw_admit (AdmitExcluded 'bump' when not admitted), then
    the shared S* transcription. `clock` (a one-item list) accumulates the ns of the S* calls (reference_overhead only)."""
    from time import perf_counter_ns
    from optionlab.reference import baw_admitted
    from optionlab.models import mapped_inputs
    from optionlab.baw_admit import sstar
    def sideof(S_,T_,r_,s_):
        if not baw_admitted(side,S_,K,T_,r_,q,s_,'bump'):return 'european'
        D_r,D_q,v=mapped_inputs(T_,r_,q,s_)
        if clock is None:Sk=sstar(side,K,D_r,D_q,v,params.baw_newton_max,params.baw_plant_nan_sstar)
        else:
            t0=perf_counter_ns();Sk=sstar(side,K,D_r,D_q,v,params.baw_newton_max,params.baw_plant_nan_sstar);clock[0]+=perf_counter_ns()-t0
        return 'continuation' if ((S_<Sk) if side==0 else (S_>Sk)) else 'exercise'
    return sideof

def _baw_solve(pb,side,S,K,T,r,q,mid,params,lo):
    """QuantLib Brent on the BAW NPV with baw_admit before each evaluation (reason `brent`). Returns (status, root, f values
    seen, band hit, stop) with stop None, 'excluded' (an evaluation not admitted) or 'domain' (an order-5 value or a QuantLib
    error during the solve)."""
    from optionlab.reference import baw_admitted
    from optionlab.models import AdmitExcluded
    tau=tau_v(S,K,T,r,q);seen=[];stop=[];band=[]
    def f(sigma):
        try:baw_admitted(side,S,K,T,r,q,sigma,'brent')
        except AdmitExcluded:stop.append('excluded');raise CallbackStop('excluded') from None
        pb.set_sigma(sigma);counters.bump('baw')
        try:v=pb.npv()
        except RuntimeError:stop.append('domain');raise CallbackStop('engine error') from None
        if not math.isfinite(v) or v<-tau:stop.append('domain');raise _Domain()
        if v<0.0:band.append(sigma)
        seen.append(v-mid);return v-mid
    try:root=brent_solve(f,lo,params.sigma_hi,(lo+params.sigma_hi)/2.0)
    except RunDefect:raise                                         # H19 (A4-C2: also from inside the callback)
    except Exception as exc:                                       # QuantLib errors arrive as RuntimeError
        if stop:return 'MODEL_DOMAIN',math.nan,seen,bool(band),stop[0]
        text=str(exc)
        if text.startswith(BRACKET_TEXT):return ('BELOW_MIN' if seen[0]>0.0 else 'ABOVE_MAX'),math.nan,seen,bool(band),None
        if text==MAX_EVAL_TEXT:return 'NOT_CONVERGED',math.nan,seen,bool(band),None
        return 'MODEL_DOMAIN',math.nan,seen,bool(band),'domain'
    return 'OK',root,seen,bool(band),None

def evaluate_baw(row,params,clock=None):
    """(status, values, flags) of one row for `baw` through QuantLib-Python with py-reference's status order and flags
    (reference._evaluate): pre-engine statuses, sigma_lo, the baw_admit row check, Brent, the record's greeks. A
    BawRunDefect of the shared S* transcription propagates (never a status). `clock`: see _baw_side."""
    from optionlab.reference import (FLAG_BELOW_INTRINSIC, FLAG_BOUNDARY_AMBIGUOUS, FLAG_FLAT_VEGA, FLAG_ROUNDING_BAND, FLAG_ADMIT_EXCLUDED,
                                     FLAG_STENCIL_UNRESOLVED, baw_greeks, StencilUnresolved)
    from optionlab.models import ModelDefect, BawRunDefect, RunDefect, AloRunDefect, AdmitExcluded
    from optionlab.baw_admit import baw_admit_rates
    side,S,K,T,bid,ask,r,q=row
    if side not in (0,1) or not all(math.isfinite(v) for v in (S,K,T,bid,ask)) or S<=0.0 or K<=0.0:return 'INVALID_INPUT',NAN7,0
    if T<=0.0:return 'EXPIRED',NAN7,0
    if bid<=0.0:return 'NO_BID',NAN7,0
    if ask<bid:return 'CROSSED',NAN7,0
    mid=(bid+ask)/2.0;lo=sigma_lo('baw',side,T,r,q,params)
    if lo>=params.sigma_hi:return 'MODEL_DOMAIN',NAN7,0
    r1,q1,_=unit(T,r,q,1.0);ins,adm=baw_admit_rates(side,r1,q1)
    if ins and not adm:return 'MODEL_DOMAIN',NAN7,FLAG_ADMIT_EXCLUDED
    cache={};pb=cache[(T,r)]=_Problem('baw',side,S,K,T,r,q,lo,params)
    st,iv,seen,band,stop=_baw_solve(pb,side,S,K,T,r,q,mid,params,lo)
    bf=FLAG_ROUNDING_BAND if band else 0
    if stop=='excluded':return 'MODEL_DOMAIN',NAN7,FLAG_ADMIT_EXCLUDED|bf
    if stop=='domain':return 'MODEL_DOMAIN',NAN7,bf
    flags=0;width=1e-9*max(1.0,mid)
    if any(abs(v)<=width for v in seen[:2]):flags|=FLAG_BOUNDARY_AMBIGUOUS
    if st!='OK':
        if st=='BELOW_MIN' and mid<max((S-K) if side==0 else (K-S),0.0):flags|=FLAG_BELOW_INTRINSIC
        return st,NAN7,flags|bf
    check=Checker(tau_v(S,K,T,r,q));check.band=band
    value,result=_baw_engine(side,K,q,params,cache)
    try:values,gflags,_=baw_greeks(side,S,K,T,r,q,iv,params,value,result,check,sideof=_baw_side(side,K,q,params,clock))
    except RunDefect:raise
    except AdmitExcluded:return 'MODEL_DOMAIN',NAN7,flags|FLAG_ADMIT_EXCLUDED|(FLAG_ROUNDING_BAND if check.band else 0)
    except StencilUnresolved:return 'MODEL_DOMAIN',NAN7,flags|FLAG_STENCIL_UNRESOLVED|(FLAG_ROUNDING_BAND if check.band else 0)
    except (EngineDomain,ModelDefect):return 'MODEL_DOMAIN',NAN7,flags|(FLAG_ROUNDING_BAND if check.band else 0)
    flags|=gflags|(FLAG_ROUNDING_BAND if check.band else 0)
    if values[5]*100.0<1e-12:flags|=FLAG_FLAT_VEGA
    return 'OK',values,flags

# ---- Andersen-Lake-Offengenden (spec Amendment I4.2; the approved record Appendix I-ALO R6, R8, R10) ----
# QuantLib's QdFpAmericanEngine(process, accurateScheme(), Auto) prices every point through the mapping (QuantLib chooses
# the equation itself; alo_segment and sigma_lo run in Python). Before every engine evaluation the shared pre check runs
# (optionlab.reference.alo_pre: order 5 before the engine; such a point is not counted). The IV is ql.Brent (record R10)
# with the order-5 marker of record R8: any exception of an engine evaluation inside the callback (every QuantLib text,
# the inner QD+ Brent texts "root not bracketed: f[..." and "maximum number of function evaluations (100) exceeded"
# included), a failed pre check or an order-5 value is recorded in `stop`, so the solve's own error text is never read
# and the row is MODEL_DOMAIN, never orders 6-7. V(sigma*) is the value of the last Brent call (record IV-call fact).
# The greeks follow I2.6 through optionlab.reference.alo_greeks with QuantLib's values. No timer runs inside the child:
# an overrun is caught by the I9 call deadline outside it (reason alo-overrun).
ALO_STUB_ENV=STUB_ENV   # test-only (I9.4; EX-3): the same variable; exactly ALO_STUB_REASON blocks the ALO path
ALO_STUB_REASON='alo-overrun'  # the reason of the protocol stub

def _alo_stub():
    """The blocking stub engine of the alo-overrun tests: an Event wait without timeout (never set)."""
    import threading
    threading.Event().wait()

def _alo_value(side,K,q,params,cache):
    """value(S, T, r, sigma) of QuantLib's ALO engine for reference.alo_greeks: one problem per (T, r) of the row, S and
    sigma move through their quotes (the same inputs as a fresh construction). A QuantLib error raises models.ModelDefect
    with its text (order 5, record R8). Each engine call counts once (test-only counters, G4.8)."""
    from optionlab.models import ModelDefect
    def value(S_,T_,r_,s_):
        pb=cache.get((T_,r_))
        if pb is None:pb=cache[(T_,r_)]=_Problem('alo',side,S_,K,T_,r_,q,s_,params)
        pb.spot.setValue(S_);pb.set_sigma(s_);counters.bump('alo')
        try:return pb.npv()
        except RunDefect:raise                                  # H19
        except RuntimeError as exc:raise ModelDefect(str(exc)[:300]) from None
    return value

def _alo_solve(pb,side,S,K,T,r,q,mid,params,lo):
    """QuantLib Brent on the ALO NPV with the ALO pre check before each evaluation and the order-5 marker of record R8.
    Returns (status, root, f values seen, band hit, stop, last) with stop None or 'domain' (a failed pre check, an engine
    exception or an order-5 value inside the callback) and last = [sigma, value] of the last engine call."""
    from optionlab import reference as _ref
    from optionlab.models import ModelDefect
    tau=tau_v(S,K,T,r,q);seen=[];stop=[];band=[];last=[None,None]
    def f(sigma):
        try:_ref.alo_pre(side,S,K,T,r,q,sigma)
        except RunDefect:raise                                     # H19 (the marker of brent_solve carries it out)
        except ModelDefect:stop.append('domain');raise CallbackStop('pre check') from None
        pb.set_sigma(sigma);counters.bump('alo')
        try:v=pb.npv()
        except RuntimeError:stop.append('domain');raise CallbackStop('engine error') from None   # the order-5 marker (record R8): never the solve's text
        if not math.isfinite(v) or v<-tau:stop.append('domain');raise _Domain()
        if v<0.0:band.append(sigma)
        last[0]=sigma;last[1]=v;seen.append(v-mid);return v-mid
    try:root=brent_solve(f,lo,params.sigma_hi,(lo+params.sigma_hi)/2.0)
    except RunDefect:raise                                         # H19 (A4-C2: also from inside the callback)
    except Exception as exc:                                       # QuantLib errors arrive as RuntimeError
        if stop:return 'MODEL_DOMAIN',math.nan,seen,bool(band),'domain',last
        text=str(exc)
        if text.startswith(BRACKET_TEXT):return ('BELOW_MIN' if seen[0]>0.0 else 'ABOVE_MAX'),math.nan,seen,bool(band),None,last
        if text==MAX_EVAL_TEXT:return 'NOT_CONVERGED',math.nan,seen,bool(band),None,last
        return 'MODEL_DOMAIN',math.nan,seen,bool(band),'domain',last
    return 'OK',root,seen,bool(band),None,last

def evaluate_alo(row,params):
    """(status, values, flags) of one row for `alo` through QuantLib-Python with py-reference's status order and flags
    (reference._evaluate): pre-engine statuses, sigma_lo (E-ALO-1), ql.Brent with the pre check and the order-5 marker,
    the I2.6 greeks (reference.alo_greeks: flags 16 and 32). A models.RunDefect propagates (H19)."""
    from optionlab.reference import (FLAG_BELOW_INTRINSIC, FLAG_BOUNDARY_AMBIGUOUS, FLAG_FLAT_VEGA, FLAG_ROUNDING_BAND, FLAG_STENCIL_UNRESOLVED,
                                     alo_greeks, StencilUnresolved)
    from optionlab.models import ModelDefect, AloRunDefect
    side,S,K,T,bid,ask,r,q=row
    if side not in (0,1) or not all(math.isfinite(v) for v in (S,K,T,bid,ask)) or S<=0.0 or K<=0.0:return 'INVALID_INPUT',NAN7,0
    if T<=0.0:return 'EXPIRED',NAN7,0
    if bid<=0.0:return 'NO_BID',NAN7,0
    if ask<bid:return 'CROSSED',NAN7,0
    mid=(bid+ask)/2.0;lo=sigma_lo('alo',side,T,r,q,params)
    if lo>=params.sigma_hi:return 'MODEL_DOMAIN',NAN7,0
    cache={};pb=cache[(T,r)]=_Problem('alo',side,S,K,T,r,q,lo,params)
    st,iv,seen,band,stop,last=_alo_solve(pb,side,S,K,T,r,q,mid,params,lo)
    bf=FLAG_ROUNDING_BAND if band else 0
    if stop=='domain':return 'MODEL_DOMAIN',NAN7,bf
    flags=0;width=1e-9*max(1.0,mid)
    if any(abs(v)<=width for v in seen[:2]):flags|=FLAG_BOUNDARY_AMBIGUOUS
    if st!='OK':
        if st=='BELOW_MIN' and mid<max((S-K) if side==0 else (K-S),0.0):flags|=FLAG_BELOW_INTRINSIC
        return st,NAN7,flags|bf
    if last[0]!=iv:raise AloRunDefect('alo-iv-call','library')     # record IV-call fact: the last Brent call is at the root
    check=Checker(tau_v(S,K,T,r,q));check.band=band
    try:values,gflags,_=alo_greeks(side,S,K,T,r,q,iv,last[1],params,_alo_value(side,K,q,params,cache),check)
    except RunDefect:raise
    except StencilUnresolved:return 'MODEL_DOMAIN',NAN7,flags|FLAG_STENCIL_UNRESOLVED|(FLAG_ROUNDING_BAND if check.band else 0)
    except (EngineDomain,ModelDefect):return 'MODEL_DOMAIN',NAN7,flags|(FLAG_ROUNDING_BAND if check.band else 0)
    flags|=gflags|(FLAG_ROUNDING_BAND if check.band else 0)
    if values[5]*100.0<1e-12:flags|=FLAG_FLAT_VEGA
    return 'OK',values,flags

OVERHEAD_ROWS=256      # G2.3, P3R2-04: the first 256 rows of the synthetic large chain

def sstar_overhead(rows,params):
    """The py-library S* side-test overhead (G2.3; P3R2-04): per row, the ns of the shared S* transcription calls that the
    BAW evaluation adds (one per stencil point side test and one for the row side test); returns the median over the rows
    (rows that stop before the greeks count 0 ns). Measured outside every timed interval."""
    per=[]
    for row in rows[:OVERHEAD_ROWS]:
        clock=[0];evaluate_baw(row,params,clock);per.append(clock[0])
    if not per:return None
    per.sort();k=len(per)
    return float(per[k//2]) if k%2 else (per[k//2-1]+per[k//2])/2.0

def run(rows,params,models=ALL_MODELS):
    """Columnar result of the listed models only (Amendment G4.3; default ALL_MODELS), in the form of reference.run."""
    import os
    from optionlab.contract import FIELDS, check_variant_models
    models=check_variant_models(models)
    if 'baw' in models and rows and os.environ.get(STUB_ENV)==BAW_STUB_REASON:_baw_stub()     # test-only stub (G2.3)
    if 'alo' in models and rows and os.environ.get(ALO_STUB_ENV)==ALO_STUB_REASON:_alo_stub()     # test-only stub (I9.4)
    out={'n':len(rows),'models':{m:{'status':[],'flags':[],**{f:[] for f in FIELDS}} for m in models}}
    for row in rows:
        for m in models:
            status,values,flags=evaluate_baw(row,params) if m=='baw' else evaluate_alo(row,params) if m=='alo' else evaluate(row,m,params);col=out['models'][m]
            col['status'].append(status);col['flags'].append(flags)
            for f,v in zip(FIELDS,values):col[f].append(v)
    return out
