"""Agreement of a variant with py-reference (spec 3.7, 3.3); runs after the timed interval.

Order of the per-row rules in `compare` (first match decides the row):
1. boundary_ambiguous (bound-price) reference row: a neighbor status of py-reference's status passes (and MODEL_DOMAIN
   too when either side has the rounding_band flag); the NaN rule (non-OK status) or the finite rule (OK status) still
   applies; the row leaves the numeric comparison and the reduction (plan ruling 4).
1b. rounding_band row (the flag on either side; every variant sets it, Task 7a round-2 item M-A), Amendment D item 3:
   accepted statuses are py-reference's status or MODEL_DOMAIN; a differing pair must be exactly OK and MODEL_DOMAIN, in
   either direction (any other pair is a status failure). When the accepted statuses differ, each side's NaN or
   finite rule applies, the numeric comparison is skipped and `band_status_mismatch[m]` counts the row; when they are
   equal, the row continues with rules 3-7 at the normal tolerances. Reduction: the variant's status counts use
   py-reference's status for band rows; a band row enters the max-IV comparison only when both statuses are OK.
   `rounding_band[m]` counts the band rows, `rounding_band_variant_only[m]` those where only the variant has the flag
   (spec 3.3 L-A: reported and counted).
2. Status differs (also an unknown status text; the reduction is then MISMATCH): `status` failure.
3. Non-OK status: every numeric field must be NaN (`nan` failure).
4. OK status: every numeric field must be finite (`nonfinite` failure; -0.0 equals 0.0).
5. flat_vega reference row (nu_ref < flat_vega): the fit rule only (`fit` failure).
6. |iv - iv_ref| > tau_sigma: a variant IV outside [sigma_lo, 5.0] is an `iv` failure. Otherwise the multi_root test below.
   multi_root: the reference price at the variant IV must fit mid, with nu from `fit_slope` (a difference clipped to
   [sigma_lo, 5.0]) (`fit` failure); the row leaves the IV, greek and reduction max-IV comparison. Otherwise: `iv` failure.
   A ModelDefect (an engine error) raised at a grid, bracket or slope point is a `model_error` failure; `model_errors[m]`
   counts the exception class names (no row content). The row is never an uncaught exception (controller ruling).
7. Price (difference and both fit rules) and each greek.

multi_root precedence (spec 3.3; the L1 bracket sentence is a later amendment to the sentence "Without more than one sign
change, the difference stays an agreement failure"):
  (a) The 64-point log grid test runs first. More than one sign change of the reference f over [sigma_lo, 5.0]: multi_root.
  (b) Only when (a) finds at most one sign change does the L1 disjoint-bracket test run. A sign change of the reference f
      inside both brackets [s - w, s + w] (s = iv_ref and s = iv_var; w = min(1e-6, |delta|/4); clipped to [sigma_lo, 5.0]):
      multi_root.
  (c) Only when (a) and (b) both fail does the difference stay an agreement failure (`iv`).
"""
import math
from optionlab.contract import MODELS, FIELDS, STATUSES
from optionlab.models import sigma_lo, ModelDefect, RunDefect
from optionlab.reference import FLAG_BOUNDARY_AMBIGUOUS, FLAG_ROUNDING_BAND, price_function as default_price, reduction

from optionlab import protocol as _protocol
_SHARED=('iv_abs','iv_ulp_rel','price_rel','fit_nu','fit_rel','greek_abs','greek_rel','flat_vega')
TOLERANCES={k:_protocol.tolerances()[k] for k in _SHARED}   # EX-3: the shared fields of protocol/protocol.json tolerances
MULTI_ROOT_GRID=int(_protocol.solver()['multi_root_grid'])   # EX-3: protocol/protocol.json solver.multi_root_grid
NEIGHBORS={'BELOW_MIN':{'BELOW_MIN','OK'},'ABOVE_MAX':{'ABOVE_MAX','OK'},'OK':{'OK','BELOW_MIN','ABOVE_MAX'}}

def tau_sigma(price_ref,nu_ref,tol=TOLERANCES):return tol['iv_abs']+tol['iv_ulp_rel']*max(1.0,price_ref)/nu_ref

def grid_sign_changes(price,row,model,params,mid,grid=MULTI_ROOT_GRID):
    """The section 3.3 grid test: the count of sign changes of f = price - mid on `grid` log-spaced sigma values over
    [sigma_lo, 5.0] (zero values skipped). Rule (a) of multi_root and the G3.3 panel candidate test (Task 7) both use it."""
    side,S,K,T,bid,ask,r,q=row;f=lambda s:price(side,S,K,T,r,q,s)-mid
    lo=sigma_lo(model,side,T,r,q,params);hi=params.sigma_hi
    signs=[v>0 for v in (f(lo*(hi/lo)**(j/(grid-1))) for j in range(grid)) if v!=0.0]
    return sum(1 for a,b in zip(signs,signs[1:]) if a!=b)

def multi_root(price,row,model,params,iv_ref,iv_var,mid,grid=MULTI_ROOT_GRID):
    """True when the row has several roots of f = price - mid; precedence (a) grid, (b) L1 brackets, see the module text."""
    side,S,K,T,bid,ask,r,q=row;f=lambda s:price(side,S,K,T,r,q,s)-mid
    lo=sigma_lo(model,side,T,r,q,params);hi=params.sigma_hi
    if grid_sign_changes(price,row,model,params,mid,grid)>1:return True        # (a) grid rule first
    w=min(1e-6,abs(iv_var-iv_ref)/4.0)          # (b) L1: disjoint brackets around both IVs
    def changes(s):
        a,b=max(lo,s-w),min(hi,s+w);fa,fb=f(a),f(b);return fa==0.0 or fb==0.0 or (fa>0)!=(fb>0)
    return w>0 and changes(iv_ref) and changes(iv_var)

def fit_slope(price,row,model,params,s,h=1e-6):
    """|d price / d sigma| at s by a difference clipped to [sigma_lo, 5.0]; s must lie inside that domain."""
    side,S,K,T,bid,ask,r,q=row;lo=sigma_lo(model,side,T,r,q,params);a,b=max(lo,s-h),min(params.sigma_hi,s+h)
    return abs(price(side,S,K,T,r,q,b)-price(side,S,K,T,r,q,a))/(b-a)

def compare(rows,result,reference,params,tol=TOLERANCES,price_function=None,models=None):
    """`models` None (Amendment G4.3): the models are the result's keys, and the reference must hold exactly the same keys
    (a variant that drops or adds a model part is MISSING_ROWS). An explicit `models` compares only those models."""
    v={'eligible':True,'failures':{},'multi_root':{},'boundary_ambiguous':{},'flat_vega':{},'model_errors':{},'rounding_band':{},
       'rounding_band_variant_only':{},'band_status_mismatch':{},'reduction':'MATCH'}
    n=reference['n']
    if result.get('n')!=n:return dict(v,eligible=False,reduction='ROW_COUNT')
    if models is None:
        got_models=result.get('models')
        if not isinstance(got_models,dict) or not got_models or set(got_models)!=set(reference['models']):return dict(v,eligible=False,reduction='MISSING_ROWS')
        models=tuple(got_models)
    for m in models:
        got=result['models'].get(m)
        if got is None or any(len(got.get(k,()))!=n for k in ('status',)+FIELDS) or ('flags' in got and len(got['flags'])!=n):
            return dict(v,eligible=False,reduction='MISSING_ROWS')
    def fail(key):v['failures'][key]=v['failures'].get(key,0)+1
    exclude={};iv_exclude={};counted={}
    for m in models:
        ref=reference['models'][m];got=result['models'][m];price=price_function or default_price(m,params)
        mr=amb=flat=band=band_var=mismatch=0;exclude[m]=[];iv_exclude[m]=[];errors={};gflags=got.get('flags') or [0]*n
        counted[m]=list(got['status'])
        for i in range(n):
            rs,gs=ref['status'][i],got['status'][i];side,S,K,T,bid,ask,r,q=rows[i];mid=(bid+ask)/2.0
            rband=bool(ref['flags'][i]&FLAG_ROUNDING_BAND);gband=bool(gflags[i]&FLAG_ROUNDING_BAND)
            band+=rband or gband;band_var+=gband and not rband
            if ref['flags'][i]&FLAG_BOUNDARY_AMBIGUOUS:
                amb+=1;exclude[m].append(i)
                accepted=set(NEIGHBORS.get(rs,{rs}))
                if rband or gband:accepted|={rs,'MODEL_DOMAIN'}
                if gs not in accepted:fail(m+'.status')
                elif gs!='OK' and any(not math.isnan(got[f][i]) for f in FIELDS):fail(m+'.nan')
                elif gs=='OK' and any(not math.isfinite(got[f][i]) for f in FIELDS):fail(m+'.nonfinite')
                continue
            if (rband or gband) and gs!=rs:                  # Amendment D item 3
                if {rs,gs}!={'OK','MODEL_DOMAIN'}:fail(m+'.status');continue      # exactly OK <-> MODEL_DOMAIN (review Minor 2)
                mismatch+=1;iv_exclude[m].append(i);counted[m][i]=rs
                for st,col in ((rs,ref),(gs,got)):
                    if st!='OK' and any(not math.isnan(col[f][i]) for f in FIELDS):fail(m+'.nan')
                    elif st=='OK' and any(not math.isfinite(col[f][i]) for f in FIELDS):fail(m+'.nonfinite')
                continue
            if rs!=gs:fail(m+'.status');continue
            if rs!='OK':
                if any(not math.isnan(got[f][i]) for f in FIELDS):fail(m+'.nan')
                continue
            vals=[got[f][i] for f in FIELDS]
            if any(not math.isfinite(x) for x in vals):fail(m+'.nonfinite');continue
            nu=ref['vega'][i]*100.0;pr=ref['price'][i]
            fit=lambda p,nn:abs(p-mid)<=nn*tol['fit_nu']+tol['fit_rel']*max(1.0,mid)
            if nu<tol['flat_vega']:
                flat+=1      # variant-side fit only: the reference side is the oracle's responsibility (spec 4), not agreement
                if not fit(got['price'][i],abs(got['vega'][i])*100.0):fail(m+'.fit')
                continue
            ts=tau_sigma(pr,nu,tol)
            if abs(got['iv'][i]-ref['iv'][i])>ts:
                s=got['iv'][i]
                if not sigma_lo(m,side,T,r,q,params)<=s<=params.sigma_hi:fail(m+'.iv');continue   # outside the solver bracket: a defect
                try:
                    if multi_root(price,rows[i],m,params,ref['iv'][i],s,mid):
                        mr+=1;exclude[m].append(i)
                        if not fit(price(side,S,K,T,r,q,s),fit_slope(price,rows[i],m,params,s)):fail(m+'.fit')
                        continue
                except RunDefect:raise          # H19: a run defect fails the run (never an agreement failure)
                except ModelDefect as exc:      # a new sigma point meets a model error: agreement failure, cause recorded
                    fail(m+'.model_error');name=type(exc).__name__;errors[name]=errors.get(name,0)+1;continue
                fail(m+'.iv');continue
            if (abs(got['price'][i]-pr)>nu*ts+tol['price_rel']*max(1.0,abs(pr)) or not fit(got['price'][i],abs(got['vega'][i])*100.0) or not fit(pr,nu)):fail(m+'.price')
            for f in ('delta','gamma','theta','vega','rho'):
                if abs(got[f][i]-ref[f][i])>tol['greek_abs']+(tol['greek_rel']+ts/ref['iv'][i])*abs(ref[f][i]):fail(m+'.'+f)
        v['multi_root'][m]=mr;v['boundary_ambiguous'][m]=amb;v['flat_vega'][m]=flat;v['rounding_band'][m]=band;v['rounding_band_variant_only'][m]=band_var;v['band_status_mismatch'][m]=mismatch
        if errors:v['model_errors'][m]=errors
    if any(s not in STATUSES for m in models for s in result['models'][m]['status']):   # unknown status text: already a status failure
        v['reduction']='MISMATCH';v['eligible']=False;return v
    rr=reduction({'models':{m:reference['models'][m] for m in models}},exclude,iv_exclude)
    rg=reduction({'models':{m:dict(result['models'][m],status=counted[m]) for m in models}},exclude,iv_exclude)
    for m in models:
        if rr[m]['counts']!=rg[m]['counts']:v['reduction']='MISMATCH'
        elif rr[m]['max_iv'] is not None:
            i=rr[m]['max_iv_index'];ref=reference['models'][m]
            if rg[m]['max_iv'] is None or abs(rg[m]['max_iv']-rr[m]['max_iv'])>tau_sigma(ref['price'][i],max(ref['vega'][i]*100.0,1e-300),tol):v['reduction']='MISMATCH'
    v['eligible']=not v['failures'] and v['reduction']=='MATCH'
    return v
