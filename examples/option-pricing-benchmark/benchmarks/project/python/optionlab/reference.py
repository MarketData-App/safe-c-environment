"""py-reference: clear scalar Python, math only, one contract at a time (spec 3.3-3.6; QuantLib 1.43 definitions).

Status order of spec 3.3. Brent (optionlab.solver, a transcription of QuantLib Solver1D/Brent, QL_VERSION 1.43) solves
f(sigma) = mapped engine value at sigma - mid on [sigma_lo, 5.0], accuracy 1e-10, guess (sigma_lo + 5.0)/2, 200
evaluations. Every engine value V of the row (solver evaluations, the price at the IV, the CRR bumps) passes the order-5
check: V not finite, or V < -tau_V, is MODEL_DOMAIN; -tau_V <= V < 0 is used as computed and marks the row with the
rounding_band flag (controller ruling on the Task 7a verdict, H1; round-2 item M-A). Since Amendment D item 3 a band row
is not boundary_ambiguous: the agreement compares it (see agreement.compare). A non-finite
engine greek is also MODEL_DOMAIN (spec 3.3 order 5 "during the solve or the greeks").
Greeks (spec 3.6 table): BSM and BjS from the engine (theta case (a) theta_U / T); CRR delta, gamma and theta from the
lattice, vega and rho by the declared bumps in the original variables, each bumped point through the mapping.

BAW (Amendment G2; the approved record Appendix G-BAW): `baw_admit` (optionlab.baw_admit) runs before every American-branch
evaluation: the pre-engine row check (its volatility-free checks, reason `row`), each Brent evaluation (reason `brent`) and
the row point and each greek point (reason `bump`); false is MODEL_DOMAIN with flag bit 64 `admit_excluded` and the reason
in the per-row `admit_reason` column (outside the digest). Greeks: the record's R6 table and R7 stencil rule
(`baw_greeks`); flag bits 16 `stencil_unresolved` and 32 `stencil_switched`. The run defects of record R8
(models.BawRunDefect: cap hit, non-finite S*) are never a status: `evaluate` re-raises them and the run fails.

ALO (Amendment I2, I4.1, H17, H19; the approved record Appendix I-ALO): the engine is optionlab.alo (QuantLib
QdFpAmericanEngine with accurateScheme), alo_equation is called immediately before every engine evaluation, the
pre check of the shared NaN check runs before each engine call (order 5 before the engine; such a point is not counted),
sigma_lo is the E-ALO-1 closed form, V(sigma*) is the value of the last Brent call (no separate call at the IV), and the
greeks follow I2.6 (`alo_greeks`). engine_evals = Brent f-calls + the stencil points (H17; IV_CALL_TERM 0). Every
models.RunDefect (BAW and ALO, H19) propagates. Per-row `alo_equation` and `alo_nan_guarded` columns stay outside the
digest; `alo_aggregate` gives the I8.3 counts.
"""
import hashlib, json, math, struct
from optionlab.contract import STATUSES, ALL_MODELS, MODELS5, FIELDS, check_models
from optionlab import counters
from optionlab.mapping import unit, greeks_from_unit
from optionlab.models import (bsm_result, bjs_result, crr_result, baw_result, price as model_price, sigma_lo, crr_domain_ok, discount,
                              mapped_inputs, ModelDefect, BawRunDefect, RunDefect, AloRunDefect, AdmitExcluded, QL_EPSILON)
from optionlab.baw_admit import baw_admit, baw_admit_rates, sstar
from optionlab.solver import brent

FLAG_BELOW_INTRINSIC=1;FLAG_BOUNDARY_AMBIGUOUS=2;FLAG_FLAT_VEGA=4;FLAG_ROUNDING_BAND=8
FLAG_STENCIL_UNRESOLVED=16;FLAG_STENCIL_SWITCHED=32;FLAG_ADMIT_EXCLUDED=64      # BAW, Appendix G-BAW R4 item 9, R7
ADMIT_REASONS=('row','brent','bump')
NAN7=(math.nan,)*7

class StencilUnresolved(ArithmeticError):
    """BAW record R7: no stencil on the row side after 4 halvings (order 5 with flag bit 16)."""

class EngineDomain(ArithmeticError):
    """An engine value or greek outside the order-5 domain: not finite, or below the rounding band."""

def tau_v(S,K,T,r,q):
    """Rounding band of a negative engine value: ((4 eps) D_r) max(F, K) of the mapped problem (spec 3.3)."""
    r1,q1,_=unit(T,r,q,1.0)
    D_r=discount(r1,1.0);D_q=discount(q1,1.0);F=(S*D_q)/D_r
    return ((4.0*QL_EPSILON)*D_r)*max(F,K)

class Checker:
    """The order-5 evaluation check of one row; `band` records a value in -tau_V <= V < 0."""
    def __init__(self,tau):self.tau=tau;self.band=False
    def __call__(self,V):
        if not math.isfinite(V) or V<-self.tau:raise EngineDomain()
        if V<0.0:self.band=True
        return V

def price_function(model,params):
    """Engine value of `model` through the mapping, as f(side, S, K, T, r, q, sigma) (agreement and oracle use it). For `baw`
    each American-branch point passes baw_admit first; false raises models.AdmitExcluded (a ModelDefect, order 5)."""
    if model=='baw':
        def f(side,S,K,T,r,q,s):
            baw_admitted(side,S,K,T,r,q,s,'bump');return model_price('baw',side,S,K,T,r,q,s,params)
        return f
    return lambda side,S,K,T,r,q,s:model_price(model,side,S,K,T,r,q,s,params)

def baw_admitted(side,S,K,T,r,q,s,reason):
    """baw_admit before one BAW evaluation, in the original variables (mapped as the engine maps them). Returns in_scope
    (False: QuantLib's European branch); raises AdmitExcluded(reason) when the point is in scope and not admitted."""
    r1,q1,s1=unit(T,r,q,s)
    ins,adm=baw_admit(side,S,K,r1,q1,s1*s1*1.0)
    if ins and not adm:raise AdmitExcluded(reason)
    return ins

def baw_point_side(side,S,K,T,r,q,s,params,reason):
    """Side of one BAW evaluation point (record R7): 'european' for a European-branch point (always admitted; no S*);
    else baw_admit first (false raises AdmitExcluded(reason)), then the shared S* transcription: 'continuation' when
    call S < S* or put S > S* (the strict tests of lines 214 and 225), else 'exercise'. The S* call carries the case cap
    and the test-only planted NaN of `params`, so a cap hit or a non-finite S* raises BawRunDefect here too."""
    if not baw_admitted(side,S,K,T,r,q,s,reason):return 'european'
    D_r,D_q,v=mapped_inputs(T,r,q,s)
    Sk=sstar(side,K,D_r,D_q,v,params.baw_newton_max,params.baw_plant_nan_sstar)
    return 'continuation' if ((S<Sk) if side==0 else (S>Sk)) else 'exercise'

HALVINGS=4      # record R7: at most 4 halvings of a stencil step

def baw_greeks(side,S,K,T,r,q,iv,params,value,result,check,ev=None,sideof=None):
    """BAW price and greeks at iv by the record's R6 table and R7 stencil rule. `result(S, T, r, sigma)` is the engine call
    at the row point (a dict of models.baw_result form, every engine greek in the European branch); `value(S, T, r, sigma)`
    is the engine value at a greek point. Each point passes `baw_point_side` (baw_admit, reason `bump`, and the side test
    by the shared S* transcription) before its evaluation. `ev` counts the engine calls (G3.7): 1 for the row point (the
    greek call) and 1 per greek point. `sideof(S, T, r, sigma)` (Task 6) replaces the side function of a point; it must
    give the result of `baw_point_side` (py-optimized keeps each point's S*, py-library times the S* call). Returns (values, flags, stencils): flags holds bit 32 when a stencil is one-sided,
    forward or backward where the record's default is another form, or halved; stencils maps 'S', 'sigma', 'r', 'T' to
    (form, step). No row-side stencil after 4 halvings raises StencilUnresolved.
    Forms: S central (S - h, S + h) or one-sided three-point on the row side (call S - h, S - 2h; put S + h, S + 2h),
    h_S = min(1e-3, 0.1 sigma sqrt T) S; sigma central, forward (also when sigma - h_sigma < sigma_lo) or backward; r
    central, forward (also when r - h_r < 0, N7) or backward, q fixed; T backward (theta case (c), (V(T - d) - V(T))/d,
    d = min(1/365, T/2)) or forward ((V(T) - V(T + d))/d). A European-branch point has no S* and is not on an American
    row side. Exercise side: delta +1 (call) or -1 (put), gamma = theta = vega = rho = 0 exactly, no greek point."""
    def E(S_,T_,r_,s_):
        if ev is not None:ev[0]+=1
        return check(value(S_,T_,r_,s_))
    if sideof is None:sideof=lambda S_,T_,r_,s_:baw_point_side(side,S_,K,T_,r_,q,s_,params,'bump')
    row=sideof(S,T,r,iv)
    if ev is not None:ev[0]+=1
    e=result(S,T,r,iv);p=check(e['value']);flags=0;stencils={}
    if row=='european':
        dU={'delta_U':e['delta'],'gamma_U':e['gamma'],'theta_U':e['theta'],'vega_U':e['vega'],'rho_U':e['rho'],'div_rho_U':e['dividendRho']}
        g=greeks_from_unit(T,r,q,iv,dU)
    elif row=='exercise':
        g=greeks_from_unit(T,r,q,iv,{'delta_U':1.0 if side==0 else -1.0,'gamma_U':0.0,'vega_bump':0.0,'rho_bump':0.0},theta_bump=0.0)
    else:
        h=min(1e-3,0.1*iv*math.sqrt(T))*S;sgn=-1.0 if side==0 else 1.0
        for k in range(HALVINGS+1):
            if sideof(S-h,T,r,iv)==row and sideof(S+h,T,r,iv)==row:
                a=E(S-h,T,r,iv);b=E(S+h,T,r,iv);delta=(b-a)/(2.0*h);gamma=(b-2.0*p+a)/(h*h);form='central';break
            s1=S+sgn*h;s2=S+sgn*(2.0*h)
            if sideof(s1,T,r,iv)==row and sideof(s2,T,r,iv)==row:
                v1=E(s1,T,r,iv);v2=E(s2,T,r,iv);num=3.0*p-4.0*v1+v2
                delta=num/(2.0*h) if side==0 else -(num/(2.0*h));gamma=(p-2.0*v1+v2)/(h*h);form='one-sided';break
            h=h*0.5
        else:raise StencilUnresolved()
        stencils['S']=(form,h);flags|=FLAG_STENCIL_SWITCHED if form!='central' or k>0 else 0
        def two_point(name,up,down,step,down_allowed):
            """Central, forward or backward difference in one variable (record R7, sigma and r)."""
            nonlocal flags
            for k in range(HALVINGS+1):
                u=sideof(*up(step))==row
                d=down_allowed(step) and sideof(*down(step))==row
                if u and d:out=(E(*up(step))-E(*down(step)))/(2.0*step);form='central'
                elif u:out=(E(*up(step))-p)/step;form='forward'
                elif d:out=(p-E(*down(step)))/step;form='backward'
                else:
                    step=step*0.5;continue
                stencils[name]=(form,step);flags|=FLAG_STENCIL_SWITCHED if form!='central' or k>0 else 0
                return out
            raise StencilUnresolved()
        lo=sigma_lo('baw',side,T,r,q,params)
        vega=two_point('sigma',lambda h_:(S,T,r,iv+h_),lambda h_:(S,T,r,iv-h_),params.h_sigma,lambda h_:iv-h_>=lo)
        rho=two_point('r',lambda h_:(S,T,r+h_,iv),lambda h_:(S,T,r-h_,iv),params.h_r,lambda h_:r-h_>=0.0)
        d=min(1.0/365.0,T/2.0)
        for k in range(HALVINGS+1):
            if sideof(S,T-d,r,iv)==row:theta=(E(S,T-d,r,iv)-p)/d;form='backward';break
            if sideof(S,T+d,r,iv)==row:theta=(p-E(S,T+d,r,iv))/d;form='forward';break
            d=d*0.5
        else:raise StencilUnresolved()
        stencils['T']=(form,d);flags|=FLAG_STENCIL_SWITCHED if form!='backward' or k>0 else 0
        g=greeks_from_unit(T,r,q,iv,{'delta_U':delta,'gamma_U':gamma,'vega_bump':vega,'rho_bump':rho},theta_bump=theta)
    vals=(iv,p,g['delta'],g['gamma'],g['theta'],g['vega'],g['rho'])
    if not all(math.isfinite(v) for v in vals):raise EngineDomain()
    return vals,flags,stencils

# ---- Andersen-Lake-Offengenden (Amendment I2, I4.1; the approved record Appendix I-ALO R6, R10, H17) ----
def alo_pre(side,S,K,T,r,q,s):
    """The pre check of the shared NaN check (optionlab.alo.pre_check) of one ALO point, before its engine call: a failure
    raises alo.AloPreCheck (order 5) and the point does not count as an engine evaluation."""
    from optionlab import alo
    _,_,_,s1,r_e,q_e,_=alo.mapped_point(side,S,K,T,r,q,s);alo.pre_check(S,K,r_e,q_e,s1)

def _alo_engine(params,info=None):
    """py-reference's ALO engine for alo_greeks: value(side, K, q) -> f(S, T, r, sigma), the engine value through the
    mapping with alo_equation immediately before the evaluation (optionlab.alo.price); the guard NaN count of each
    evaluation adds to info['alo_nan_guarded'] (aggregate, outside the digest)."""
    from optionlab import alo
    def value(side,K,q):
        def f(S_,T_,r_,s_):
            try:return alo.price(side,S_,K,T_,r_,q,s_,params)
            finally:
                if info is not None:info['alo_nan_guarded']=info.get('alo_nan_guarded',0)+alo.last_stats().guarded
        return f
    return value

def alo_greeks(side,S,K,T,r,q,iv,p,params,value,check,ev=None,pre=alo_pre):
    """ALO price and greeks at iv (Amendment I2.6, record R6): p = V(iv) (from the last Brent call, record IV-call fact);
    S central, h_S = min(1e-3, 0.1 sigma sqrt T) S; vega h_sigma central, forward when sigma - h_sigma < sigma_lo; rho
    h_r with q fixed and the segment rule (central when both points have the row's segment (alo_segment), else the
    one-sided difference whose point has it, else h_r halved, at most 4 times); theta case (c) (V(T - d) - V(T))/d,
    d = min(1/365, T/2), when T - d has the row's segment, else the forward (V(T) - V(T + d))/d, else d halved (at most 4
    times). No row-segment stencil after 4 halvings raises StencilUnresolved (flag 16); a switched or halved rho or theta
    stencil sets flag 32. `value(S, T, r, sigma)` is the engine value; `ev` counts each greek point (H17)."""
    from optionlab.alo_equation import alo_segment
    def E(S_,T_,r_,s_):
        pre(side,S_,K,T_,r_,q,s_)
        if ev is not None:ev[0]+=1
        return check(value(S_,T_,r_,s_))
    flags=0;stencils={}
    hS=min(1e-3,0.1*iv*math.sqrt(T))*S
    up=E(S+hS,T,r,iv);dn=E(S-hS,T,r,iv)
    delta=(up-dn)/(2*hS);gamma=(up-2*p+dn)/(hS*hS);stencils['S']=('central',hS)
    h=params.h_sigma;lo=sigma_lo('alo',side,T,r,q,params)
    if iv-h<lo:vega=(E(S,T,r,iv+h)-p)/h;stencils['sigma']=('forward',h)
    else:vega=(E(S,T,r,iv+h)-E(S,T,r,iv-h))/(2.0*h);stencils['sigma']=('central',h)
    seg=alo_segment(side,*unit(T,r,q,1.0)[:2]);hr=params.h_r
    for k in range(HALVINGS+1):
        sp=alo_segment(side,*unit(T,r+hr,q,1.0)[:2])==seg;sm=alo_segment(side,*unit(T,r-hr,q,1.0)[:2])==seg
        if sp and sm:rho=(E(S,T,r+hr,iv)-E(S,T,r-hr,iv))/(2.0*hr);form='central'
        elif sp:rho=(E(S,T,r+hr,iv)-p)/hr;form='forward'
        elif sm:rho=(p-E(S,T,r-hr,iv))/hr;form='backward'
        else:
            hr=hr/2;continue
        stencils['r']=(form,hr);flags|=FLAG_STENCIL_SWITCHED if form!='central' or k>0 else 0;break
    else:raise StencilUnresolved()
    d=min(1.0/365.0,T/2.0)
    for k in range(HALVINGS+1):
        if alo_segment(side,*unit(T-d,r,q,1.0)[:2])==seg:theta=(E(S,T-d,r,iv)-p)/d;form='backward';break
        if alo_segment(side,*unit(T+d,r,q,1.0)[:2])==seg:theta=(p-E(S,T+d,r,iv))/d;form='forward';break
        d=d/2
    else:raise StencilUnresolved()
    stencils['T']=(form,d);flags|=FLAG_STENCIL_SWITCHED if form!='backward' or k>0 else 0
    g=greeks_from_unit(T,r,q,iv,{'delta_U':delta,'gamma_U':gamma,'vega_bump':vega,'rho_bump':rho},theta_bump=theta)
    vals=(iv,p,g['delta'],g['gamma'],g['theta'],g['vega'],g['rho'])
    if not all(math.isfinite(v) for v in vals):raise EngineDomain()
    return vals,flags,stencils

def _baw_engine(model_value,params):
    """(value, result) callables of py-reference's BAW engine for baw_greeks: values through models.price, the row point
    through models.baw_result with every engine greek."""
    def value(side,K,q):return lambda S_,T_,r_,s_:model_value('baw',side,S_,K,T_,r_,q,s_,params)
    def result(side,K,q):return lambda S_,T_,r_,s_:baw_result(side,S_,K,T_,r_,q,s_,params)
    return value,result

def _engine_greeks(model,side,S,K,T,r,q,iv,params,check,ev=None):
    """`ev` (a one-item list) counts the engine calls (G3.7): 1 for the engine greek call, 1 per CRR bump evaluation."""
    if ev is not None:ev[0]+=1
    if model=='bsm':e=bsm_result(side,S,K,T,r,q,iv)
    elif model=='bjs':e=bjs_result(side,S,K,T,r,q,iv)
    else:e=crr_result(side,S,K,T,r,q,iv,params.crr_steps)
    p=check(e['value'])
    dU={'delta_U':e['delta'],'gamma_U':e['gamma'],'theta_U':e['theta']}
    if model in ('bsm','bjs'):dU.update(vega_U=e['vega'],rho_U=e['rho'],div_rho_U=e['dividendRho'])
    else:
        lo=sigma_lo('crr',side,T,r,q,params);h=params.h_sigma;hr=params.h_r
        def V(s,rr):
            if ev is not None:ev[0]+=1
            return check(model_price('crr',side,S,K,T,rr,q,s,params))
        dU['vega_bump']=(V(iv+h,r)-p)/h if iv-h<lo else (V(iv+h,r)-V(iv-h,r))/(2.0*h)
        dU['rho_bump']=(V(iv,r+hr)-V(iv,r-hr))/(2.0*hr)
    g=greeks_from_unit(T,r,q,iv,dU)
    vals=(iv,p,g['delta'],g['gamma'],g['theta'],g['vega'],g['rho'])
    if not all(math.isfinite(v) for v in vals):raise EngineDomain()
    return vals

def price_and_greeks(model,side,S,K,T,r,q,sigma,params,engine=None):
    """Price and greeks in output units at sigma (spec 3.6), the per-model greek code of `evaluate`. For `baw` the result
    also holds `flags` (bits 16, 32 of the stencil rule) and `stencils`; `engine` = (value, result) factories replaces
    py-reference's BAW engine (the QuantLib alignment check passes QuantLib's), the admission and stencil rule unchanged."""
    check=Checker(tau_v(S,K,T,r,q))
    if model=='alo':                    # `engine` = value factory (the QuantLib alignment check passes QuantLib's)
        value=(engine or _alo_engine(params))(side,K,q);alo_pre(side,S,K,T,r,q,sigma)
        p=check(value(S,T,r,sigma))
        vals,flags,stencils=alo_greeks(side,S,K,T,r,q,sigma,p,params,value,check)
        return dict(zip(('iv','price','delta','gamma','theta','vega','rho'),vals),rounding_band=check.band,flags=flags,stencils=stencils)
    if model=='baw':
        value,result=engine or _baw_engine(model_price,params)
        vals,flags,stencils=baw_greeks(side,S,K,T,r,q,sigma,params,value(side,K,q),result(side,K,q),check)
        return dict(zip(('iv','price','delta','gamma','theta','vega','rho'),vals),rounding_band=check.band,flags=flags,stencils=stencils)
    vals=_engine_greeks(model,side,S,K,T,r,q,sigma,params,check)
    return dict(zip(('iv','price','delta','gamma','theta','vega','rho'),vals),rounding_band=check.band)

def evaluate(row,model,params,info=None,engine=None):
    """(status, (iv, price, delta, gamma, theta, vega, rho), flags, evals) of one row and model (spec 3.3). `evals` counts
    every engine call of the row (Amendment G3.7): each Brent evaluation, the engine greek call and each bump evaluation;
    0 for a row stopped before the engine. The test-only counters (optionlab.counters) receive the same count.
    BAW: `info` (a dict) receives 'admit_reason' ('row', 'brent' or 'bump') for a row excluded by baw_admit; an engine
    evaluation counts only when it runs (after admission). A BawRunDefect (record R8) propagates: never a status.
    `engine` (BAW only): (value, result) factories that replace py-reference's engine (the QuantLib alignment check)."""
    ev=[0]
    try:status,values,flags=_evaluate(row,model,params,ev,{} if info is None else info,engine)
    finally:counters.bump(model,ev[0])
    return status,values,flags,ev[0]

def evaluate3(row,model,params):
    """(status, values, flags) of `evaluate`, for callers that need no evaluation count (oracle, agreement, checks)."""
    return evaluate(row,model,params)[:3]

def _evaluate(row,model,params,ev,info,engine=None):
    side,S,K,T,bid,ask,r,q=row
    if side not in (0,1) or not all(math.isfinite(v) for v in (S,K,T,bid,ask)) or S<=0.0 or K<=0.0:return 'INVALID_INPUT',NAN7,0
    if T<=0.0:return 'EXPIRED',NAN7,0
    if bid<=0.0:return 'NO_BID',NAN7,0
    if ask<bid:return 'CROSSED',NAN7,0
    mid=(bid+ask)/2.0;lo=sigma_lo(model,side,T,r,q,params);hi=params.sigma_hi
    if lo>=hi:return 'MODEL_DOMAIN',NAN7,0
    if model=='crr' and not crr_domain_ok(T,r,q,params):return 'MODEL_DOMAIN',NAN7,0
    if model=='baw':                                    # pre-engine row check: the volatility-free checks of baw_admit
        r1,q1,_=unit(T,r,q,1.0);ins,adm=baw_admit_rates(side,r1,q1)
        if ins and not adm:info['admit_reason']='row';return 'MODEL_DOMAIN',NAN7,FLAG_ADMIT_EXCLUDED
    check=Checker(tau_v(S,K,T,r,q));flags=0
    def band_flags():return FLAG_ROUNDING_BAND if check.band else 0        # Amendment D item 3: not boundary_ambiguous
    if model=='baw':
        bv,br=engine or _baw_engine(model_price,params);bvalue=bv(side,K,q);bresult=br(side,K,q)
    if model=='alo':                                    # record R4: the row's equation (aggregate, outside the digest)
        from optionlab.alo_equation import alo_equation
        r1,q1,_=unit(T,r,q,1.0);info['alo_equation']=alo_equation(r1,q1);info.setdefault('alo_nan_guarded',0)
        avalue=(engine or _alo_engine(params,info))(side,K,q);last=[None,None];bre=[0]
    try:
        def price(s):
            if model=='alo':                            # H17: each Brent f-call that reaches the engine counts once
                alo_pre(side,S,K,T,r,q,s);ev[0]+=1;bre[0]+=1;v=check(avalue(S,T,r,s));last[0]=s;last[1]=v;return v
            if model=='baw':
                baw_admitted(side,S,K,T,r,q,s,'brent');ev[0]+=1;return check(bvalue(S,T,r,s))
            ev[0]+=1;return check(model_price(model,side,S,K,T,r,q,s,params))
        status,iv,fa,fb,_=brent(lambda s:price(s)-mid,lo,hi,(lo+hi)/2.0)
        band=1e-9*max(1.0,mid)
        if abs(fa)<=band or abs(fb)<=band:flags|=FLAG_BOUNDARY_AMBIGUOUS
        if status!='OK':
            if status=='BELOW_MIN' and mid<max((S-K) if side==0 else (K-S),0.0):flags|=FLAG_BELOW_INTRINSIC
            return status,NAN7,flags|band_flags()
        if model=='baw':
            values,gflags,_=baw_greeks(side,S,K,T,r,q,iv,params,bvalue,bresult,check,ev);flags|=gflags
        elif model=='alo':
            if last[0]!=iv:raise AloRunDefect('alo-iv-call','reference')   # record IV-call fact: the last Brent call is at the root
            info['brent_evals']=bre[0]
            values,gflags,_=alo_greeks(side,S,K,T,r,q,iv,last[1],params,avalue,check,ev);flags|=gflags
            info['stencil_points']=ev[0]-bre[0]
        else:values=_engine_greeks(model,side,S,K,T,r,q,iv,params,check,ev)
    except RunDefect:raise                                                     # record R8: a run defect, never a status
    except AdmitExcluded as exc:
        info['admit_reason']=exc.reason;return 'MODEL_DOMAIN',NAN7,flags|FLAG_ADMIT_EXCLUDED|band_flags()
    except StencilUnresolved:return 'MODEL_DOMAIN',NAN7,flags|FLAG_STENCIL_UNRESOLVED|band_flags()
    except (EngineDomain,ModelDefect):return 'MODEL_DOMAIN',NAN7,flags|band_flags()
    flags|=band_flags()
    if values[5]*100.0<1e-12:flags|=FLAG_FLAT_VEGA
    return 'OK',values,flags

ERF_SATURATION=6.0*math.sqrt(2.0)      # ErrorFunction returns 1 - eps for |x| >= 6, x = d/sqrt 2

def erf_saturated(rows,result,params):
    """Amendment D item 3 (a count, not a failure), per model: the OK rows of py-reference where |d1| or |d2| of the BSM
    evaluation (mapped problem) at the row's implied volatility is >= 6 sqrt 2, plus the MODEL_DOMAIN rows that carry the
    rounding_band flag (the band reached at sigma_lo)."""
    from optionlab.models import mapped_inputs
    out={}
    for m,col in result['models'].items():
        n=0
        for i,row in enumerate(rows):
            st=col['status'][i]
            if st=='MODEL_DOMAIN' and col['flags'][i]&FLAG_ROUNDING_BAND:n+=1;continue
            if st!='OK':continue
            side,S,K,T=row[:4];r,q=row[6],row[7];D_r,D_q,v=mapped_inputs(T,r,q,col['iv'][i])
            sd=math.sqrt(v);d1=math.log((S*D_q/D_r)/K)/sd+0.5*sd;d2=d1-sd
            n+=abs(d1)>=ERF_SATURATION or abs(d2)>=ERF_SATURATION
        out[m]=n
    return out

def run(rows,params,models=ALL_MODELS):
    """Columnar result of the listed models only (Amendment G4.3; default ALL_MODELS). Each model also holds the per-row
    integer column `engine_evals` (G3.7), which stays outside the ocg-v1 and ocg-v1m bytes; `baw` also holds the per-row
    `admit_reason` column (G2.3: 'row', 'brent', 'bump' or None), outside the bytes too."""
    models=check_models(models)
    out={'n':len(rows),'models':{m:{'status':[],'flags':[],**{f:[] for f in FIELDS},'engine_evals':[],**({'admit_reason':[]} if m=='baw' else {}),
                                     **({'alo_equation':[],'alo_nan_guarded':[]} if m=='alo' else {})} for m in models}}
    for row in rows:
        for m in models:
            info={};status,values,flags,evals=evaluate(row,m,params,info);col=out['models'][m]
            col['status'].append(status);col['flags'].append(flags);col['engine_evals'].append(evals)
            if m=='baw':col['admit_reason'].append(info.get('admit_reason'))   # G2.3: outside the digest (OPTIONAL_COLUMNS)
            if m=='alo':                                                        # I8.3, H10: outside the digest (OPTIONAL_COLUMNS)
                col['alo_equation'].append(info.get('alo_equation'));col['alo_nan_guarded'].append(info.get('alo_nan_guarded',0))
            for f,v in zip(FIELDS,values):col[f].append(v)
    return out

def reduction(result,exclude=None,iv_exclude=None):
    """Per model: count of each status and the maximum IV over OK rows (spec 3.2). `exclude[m]` holds row indices left out (boundary_ambiguous; ruling 4);
    `iv_exclude[m]` holds rows that are counted but stay out of the maximum IV (Amendment D item 3: band rows whose statuses differ).

    Tie rule: when several OK rows share the maximum IV, `max_iv_index` is the lowest row index (a later row replaces the
    best only when its IV is strictly greater). The value `max_iv` is order independent; the C reduction uses the same index rule.
    """
    out={}
    for m,col in result['models'].items():
        skip=set((exclude or {}).get(m,()));noiv=set((iv_exclude or {}).get(m,()));counts={s:0 for s in STATUSES};best=None
        for i,(s,v) in enumerate(zip(col['status'],col['iv'])):
            if i in skip:continue
            counts[s]+=1
            if s=='OK' and i not in noiv and (best is None or v>col['iv'][best]):best=i
        out[m]={'counts':counts,'max_iv':None if best is None else col['iv'][best],'max_iv_index':best}
    return out

DIGEST_FORM='ocg-v1';DIGEST_FORM_MASK='ocg-v1m'
OPTIONAL_COLUMNS=('engine_evals','admit_reason','alo_equation','alo_nan_guarded')     # G5.3, I8.3: allowed in a result, never in the bytes

def alo_aggregate(result):
    """Amendment I8.3, H10 (aggregate, outside the digest): for the `alo` model of a py-reference result the row counts per
    equation {'FP_A', 'FP_B'} (rows that reach sigma_lo), the stencil_switched (flag 32) and stencil_unresolved (flag 16)
    row counts and the alo_nan_guarded total; None when the result holds no `alo`."""
    col=result['models'].get('alo')
    if col is None:return None
    eq=col.get('alo_equation',[]);fl=col['flags']
    return {'reference_alo_equation':{'FP_A':sum(1 for e in eq if e=='FP_A'),'FP_B':sum(1 for e in eq if e=='FP_B')},
            'stencil_switched':sum(1 for f in fl if f&FLAG_STENCIL_SWITCHED),'stencil_unresolved':sum(1 for f in fl if f&FLAG_STENCIL_UNRESOLVED),
            'alo_nan_guarded':sum(col.get('alo_nan_guarded',[]))}

def _digest_int(v):
    if type(v) is not int:raise ValueError('digest: an integer field is not an int')
    return v

def _digest_float(v):
    if isinstance(v,bool) or not isinstance(v,(int,float)):raise ValueError('digest: a numeric field is not a number')
    v=float(v)
    if math.isnan(v):return None
    if math.isinf(v):raise ValueError('digest: infinity in a numeric field')
    if v==0.0:v=0.0
    return struct.pack('>d',v).hex()

def canonical_result(result):
    """Canonical byte form "ocg-v1" of a `run` result; `result_digest` is its SHA-256. The C path reproduces it byte for byte.

    Document: {"digest_form":"ocg-v1","models":{<model>:{<field>:[...],"flags":[...],"status":[...]}},"n":<int>}.
    - Keys: exactly `n` and `models` at the top, exactly `status`, `flags` and the seven FIELDS per model; any other key or a
      column whose length differs from n is rejected (ValueError), so nothing goes unhashed.
    - `n` and each flag: a JSON integer; the value must be a Python int (a bool or a float is rejected).
    - `status`: one of STATUSES, as a JSON string.
    - Each numeric field value (iv, price, delta, gamma, theta, vega, rho): NaN is null; infinity is rejected (a defect, spec
      3.7); -0.0 becomes 0.0; every other value is its IEEE-754 binary64 bit pattern, big-endian, as 16 lowercase hex digits
      (struct.pack('>d', x).hex(); in C memcpy to uint64_t and "%016" PRIx64). An int value is converted to binary64 first.
    - Serialization: keys sorted, separators ',' and ':' without spaces, ASCII only, no NaN/Infinity tokens, no trailing newline.
    The digest identifies one run's output; it is not a cross-variant agreement check (spec 3.7 allows ulp differences).

    Amendment G5: the model key set chooses the form. Exactly {bsm, bjs, crr} (mask 7) is "ocg-v1" above, byte for byte.
    Any other non-empty subset of MODELS5 is "ocg-v1m": {"digest_form":"ocg-v1m","mask":M,"models":{...},"n":N}, M = the
    sum of 1 << MODELS5.index(m), the same model objects and value rules (Amendment I6.3: MODELS5 extends MODELS4, so the
    bytes of every mask 1-15 are unchanged; alo is bit 16). Empty or unknown model keys raise ValueError.
    The optional columns OPTIONAL_COLUMNS (engine_evals, admit_reason) are allowed (length n) and never enter the bytes.
    """
    if set(result)!={'n','models'}:raise ValueError('digest: unexpected top-level keys')
    n=_digest_int(result['n']);models={}
    if not isinstance(result['models'],dict):raise ValueError('digest: models is not an object')
    keys=set(result['models'])
    if not keys or not keys<=set(MODELS5):raise ValueError('digest: empty or unknown model keys')
    required={'status','flags',*FIELDS}
    for m,col in result['models'].items():
        if not isinstance(col,dict) or not required<=set(col)<=required|set(OPTIONAL_COLUMNS):raise ValueError('digest: unexpected model keys')
        if any(not isinstance(col[k],(list,tuple)) for k in OPTIONAL_COLUMNS if k in col):raise ValueError('digest: an optional column is not a list')
        if 'engine_evals' in col and any(type(v) is not int or v<0 for v in col['engine_evals']):raise ValueError('digest: engine_evals holds a value that is not an integer >= 0')
        if any(len(col[k])!=n for k in col):raise ValueError('digest: column length differs from n')
        if any(not isinstance(s,str) or s not in STATUSES for s in col['status']):raise ValueError('digest: unknown status')
        out={'status':list(col['status']),'flags':[_digest_int(v) for v in col['flags']]}
        for f in FIELDS:out[f]=[_digest_float(v) for v in col[f]]
        models[m]=out
    if keys==set(ALL_MODELS):doc={'digest_form':DIGEST_FORM,'n':n,'models':models}
    else:doc={'digest_form':DIGEST_FORM_MASK,'mask':sum(1<<MODELS5.index(m) for m in keys),'n':n,'models':models}
    return json.dumps(doc,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')

def result_digest(result):
    return hashlib.sha256(canonical_result(result)).hexdigest()
