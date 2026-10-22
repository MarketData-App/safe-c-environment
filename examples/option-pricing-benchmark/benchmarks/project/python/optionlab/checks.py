"""Declared checks of the option-pricing example (Amendment A). The framework `check` job runs
`python -m optionlab.checks NAME OUT_DIR [ARGS...]` as a bounded subprocess; the last stdout line is the JSON result.

The bodies are the former coordinator jobs oracle-generate, oracle-calibrate and oracle-check (Task 9). They keep their
output files and keys. The framework check filter passes only `status`, `files`, `counts` and `label` to the host, so
every value the host tool needs is also in a listed output file: oracle-<part>.json, generator.json (the digest of
oracle_gen.py), calibration.json and oracle-check.json."""
import hashlib, json, math, sys
from pathlib import Path
CHECKS={}
from optionlab.protocol import ORACLE_FILE as FIXTURES   # EX-3: the oracle set, calibration and ALO table are protocol data (protocol/oracle.json)

def check(name):
    def register(fn):CHECKS[name]=fn;return fn
    return register

def _oracle_generate_body(out_dir,args):
    """Former coordinator job oracle-generate: one oracle part into oracle-<part>.json."""
    from optionlab import oracle_gen
    if len(args)!=1 or args[0] not in oracle_gen.PARTS:return {'status':'FAIL','reason':'one oracle part is required','files':[]}
    part=args[0];target=Path(out_dir)/f'oracle-{part}.json'
    rows=oracle_gen.generate(part)
    with open(target,'w') as f:json.dump(rows,f,separators=(',',':'),allow_nan=False)
    return {'status':'PASS' if target.is_file() else 'FAIL','part':part,'exit_code':0,'file':target.name,'files':[target.name]}

def _stdlib_body(out_dir,name,row):
    """Former coordinator helper _stdlib_job: the result row is also written to the named file."""
    (Path(out_dir)/name).write_text(json.dumps(row)+'\n');return dict(row,files=[name])

def _no_arguments(args):
    """Review Minor 6: a check that takes no argument refuses every extra argument."""
    return {'status':'FAIL','reason':'this check takes no arguments','files':[]} if args else None

def _rel(x,ref):
    """|x - ref| / max(1, |ref|); 0.0 when x == ref or both are NaN; inf when the difference is NaN (one side NaN, or inf
    against a different value). Finding PL-T9B-NAN-MAX-01: every deciding maximum goes through this, so a NaN fails."""
    return _frac(x,ref,max(1.0,abs(ref)) if ref==ref else 1.0)

def _frac(x,ref,den):
    """|x - ref| / den with the _rel rules (0.0 when equal or both NaN; inf when the quotient is NaN)."""
    if x==ref or (x!=x and ref!=ref):return 0.0
    d=abs(x-ref)/den
    return d if d==d else math.inf

def _count(value):return len(value) if isinstance(value,(list,tuple,dict)) else int(value)

def _oracle_calibrate_body(out_dir,args):
    """Former coordinator job oracle-calibrate: calibration.json holds {'status','calibration'}."""
    if _no_arguments(args):return _no_arguments(args)
    from optionlab import oracle
    from optionlab.params import CASE
    fx=json.loads(FIXTURES.read_text());c=oracle.calibrate(fx,CASE)
    return _stdlib_body(out_dir,'calibration.json',{'status':'PASS','calibration':c})

def _edge_erf_saturated(fx,params):
    """Amendment D item 3: erf_saturated per model over the oracle edge rows (a count, not a failure)."""
    from optionlab import reference
    from optionlab.params import CaseParams
    from optionlab.contract import FIELDS
    out={}
    for e in fx['oracle']['edge_rows']:
        pp=CaseParams(**{**params.__dict__,**e.get('params',{})});st,vals,fl=reference.evaluate3(tuple(e['row']),e['model'],pp)
        res={'models':{e['model']:{'status':[st],'flags':[fl],**{f:[v] for f,v in zip(FIELDS,vals)}}}}
        for m,c in reference.erf_saturated([tuple(e['row'])],res,pp).items():out[m]=out.get(m,0)+c
    return out

ORACLE_COUNT_FIELDS=('checked','failures')

def oracle_count_keys(items=tuple(str(k) for k in range(1,10))):
    """R1B-02: the count keys of the oracle check in their natural order: item<k>_checked and item<k>_failures for each
    oracle item, then `incomplete_items` (the number of INCOMPLETE items)."""
    return tuple(f'item{k}_{x}' for k in items for x in ORACLE_COUNT_FIELDS)+('incomplete_items',)

def _oracle_check_body(out_dir,args):
    """Former coordinator job oracle-check: every Task 9 oracle item; oracle-check.json holds the row. The framework filter
    passes only `counts` to the host, so `counts` repeats the per-item checked and failure numbers and holds
    `incomplete_items` (9 items x 2 + 1 = 19 keys, oracle_count_keys; item 9 is the QuantLib agreement of Task 9b). All of
    them reach the host (ruling T28-C2: the coordinator bound is 32 keys, and more keys FAIL the row)."""
    if _no_arguments(args):return _no_arguments(args)
    from optionlab import oracle
    from optionlab.params import CASE
    fx=json.loads(FIXTURES.read_text());r=oracle.run_all(fx,CASE);ev={}
    r['9']=quantlib_agreement_item(fx,CASE,evidence=ev)   # Task 9b: item 9; Task DD: ev keeps the QuantLib parts for quantlib-alignment
    status,incomplete=oracle.summary_status(r)
    row={'status':status,'incomplete':incomplete,
         'items':{k:{x:v[x] for x in ('status','checked','failures')} for k,v in r.items()},
         'model_accuracy':{'bjs_vs_lattice':r['5'].get('bjs_vs_lattice'),'crr_accuracy':r['5'].get('crr_accuracy'),
                           'erf_saturated':_edge_erf_saturated(fx,CASE)},
         'counts':dict(zip(oracle_count_keys(tuple(r)),[_count(v[x]) for v in r.values() for x in ORACLE_COUNT_FIELDS]+[len(incomplete)])),
         'alo_item7':r['7'].get('alo_item7')}            # controller ruling A4-C1: label "measured, not proven" and its reason
    result=_stdlib_body(out_dir,'oracle-check.json',row)
    if set(ev)==set(QL_EVIDENCE_PARTS):result['files']=result['files']+[write_quantlib_evidence(out_dir,fx,CASE,ev)]   # Task DD (DD1)
    return result

@check('oracle-generate')
def oracle_generate(out_dir,args):
    """Former coordinator job oracle-generate (Task 9), unchanged; adds the generator digest for bench_oracle."""
    result=_oracle_generate_body(out_dir,args)
    if result['status']!='PASS':return result
    from optionlab import oracle_gen
    digest=hashlib.sha256(Path(oracle_gen.__file__).read_bytes()).hexdigest()
    (Path(out_dir)/'generator.json').write_text(json.dumps({'script_sha256':digest})+'\n')
    return dict(result,script_sha256=digest,files=result['files']+['generator.json'])

@check('oracle-calibrate')
def oracle_calibrate(out_dir,args):return _oracle_calibrate_body(out_dir,args)

@check('b06-prerequisite-oracle')
def oracle_check(out_dir,args):return _oracle_check_body(out_dir,args)

ALIGN_TS=(3600/31536000,6*3600/31536000,1.5/365,30.25/365,1.0,3.0)
ALIGN_GRID=[(side,S,K,T,s) for side in (0,1) for S in (80.0,100.0,125.0) for K in (90.0,100.0,110.0) for T in ALIGN_TS for s in (0.08,0.25,0.9)]
ALIGN_TOL={'price':1e-10,'delta':1e-9,'gamma':1e-8,'theta':1e-9,'vega':1e-9,'rho':1e-9}
ALIGN_SEED=20261007

def _alignment_grid(params):
    """py-reference against QuantLib-Python on the Task 7b grid: price and greeks at a fixed sigma (relative difference
    |d| / max(1, |QuantLib|), as a fraction of the test tolerance) and the IV status, root and evaluation count."""
    from optionlab import library, reference
    r,q=params.rate,params.dividend_yield;out={}
    for m in ('bsm','bjs','crr'):
        f={k:0.0 for k in ALIGN_TOL};st={'rows':0,'equal':0,'ok':0,'max_iv_abs':0.0,'max_evaluations':0}
        for side,S,K,T,s in ALIGN_GRID:
            ours=reference.price_and_greeks(m,side,S,K,T,r,q,s,params);lib=library.price_and_greeks(m,side,S,K,T,r,q,s,params)
            for k in ALIGN_TOL:f[k]=max(f[k],_rel(ours[k],lib[k]))
            if lib['price']<0.01:continue
            ls,liv,n=library.implied_vol(m,side,S,K,T,r,q,lib['price'],params)
            rs,vals,_=reference.evaluate3((side,S,K,T,lib['price'],lib['price'],r,q),m,params)
            st['rows']+=1;st['equal']+=rs==ls;st['max_evaluations']=max(st['max_evaluations'],n)
            if rs==ls=='OK':st['ok']+=1;st['max_iv_abs']=max(st['max_iv_abs'],_frac(vals[0],liv,1.0))
        out[m]={'max_rel':f,'fraction_of_tolerance':{k:f[k]/ALIGN_TOL[k] for k in f},'iv':st}
    return out

def _alignment_chain(params):
    """py-reference against QuantLib-Python (library.run) on the seeded synthetic small chain, judged by agreement.compare
    (section 3.7 tolerances); also the largest |difference| / tolerance per field over the compared OK rows."""
    import math
    from optionlab import agreement, library, reference, synthetic
    from optionlab.contract import load_chain, rows as chain_rows
    rows=chain_rows(load_chain(synthetic.generate(synthetic.SIZES['small'],ALIGN_SEED,params)),params)
    ref=reference.run(rows,params);lib=library.run(rows,params);v=agreement.compare(rows,lib,ref,params)
    worst={}
    for m in ref['models']:
        a,b=ref['models'][m],lib['models'][m];w={k:0.0 for k in ('iv','price','delta','gamma','theta','vega','rho')}
        for i in range(len(rows)):
            if a['status'][i]!='OK' or b['status'][i]!='OK' or a['flags'][i]&(reference.FLAG_BOUNDARY_AMBIGUOUS|reference.FLAG_FLAT_VEGA):continue
            nu=a['vega'][i]*100.0;ts=agreement.tau_sigma(a['price'][i],nu)
            w['iv']=max(w['iv'],_frac(b['iv'][i],a['iv'][i],ts))
            w['price']=max(w['price'],_frac(b['price'][i],a['price'][i],nu*ts+1e-12*max(1.0,abs(a['price'][i]))))
            for k in ('delta','gamma','theta','vega','rho'):
                w[k]=max(w[k],_frac(b[k][i],a[k][i],1e-9+(1e-6+ts/a['iv'][i])*abs(a[k][i])))
        worst[m]={'fraction_of_tolerance':w,'status_counts':{s:a['status'].count(s) for s in sorted(set(a['status']))},
                  'status_equal':sum(x==y for x,y in zip(a['status'],b['status']))}
    keep=('eligible','failures','multi_root','boundary_ambiguous','flat_vega','model_errors','rounding_band','rounding_band_variant_only',
          'band_status_mismatch','reduction')
    return {'rows':len(rows),'seed':ALIGN_SEED,'compare':{k:v[k] for k in keep},'models':worst,
            'otm_put_share':synthetic.otm_put_share(synthetic.generate(synthetic.SIZES['small'],ALIGN_SEED,params),params),
            'dataset_digests':{t:synthetic.dataset_digest(synthetic.generate(synthetic.SIZES[t],ALIGN_SEED,params)) for t in ('tiny','small','medium')},
            'erf_saturated':reference.erf_saturated(rows,ref,params)}

def lattice_agreement(fx,params,on_point=None):
    """Amendment D item 0(a) (section 4 item 9 on the lattice): every lattice oracle point against QuantLib-Python at
    ALIGN_TOL['price']: py-reference CRR(100) American; the fixture's European values and the live py-reference European
    values at every N; for calls,
    py-reference's q = 0 American and q = 0 European values, each against QuantLib's value of the same exercise.
    Returns (band -> all equal, largest |d| / max(1, |QuantLib|), compared value count)."""
    from optionlab import library, models
    from optionlab.oracle import SIGMA_BANDS, T_BANDS, _band
    r,q=params.rate,params.dividend_yield;tol=ALIGN_TOL['price'];bands={};worst=0.0;n=0
    for p in fx['oracle']['lattice']:
        side,S,K,T,s=p['side'],p['S'],p['K'],p['T'],p['sigma'];key=_band(s,SIGMA_BANDS)+'|'+_band(T,T_BANDS)
        pairs=[('american',100,models.crr_price(side,S,K,T,r,q,s,100),library.crr_price(side,S,K,T,r,q,s,100,params))]
        for N in (100,200,400,800):          # the stored fixture values and the live py-reference values (review Minor 3)
            lib=library.crr_price(side,S,K,T,r,q,s,N,params,american=False)
            pairs+=[('european-fixture',N,p['euro'][str(N)],lib),('european-live',N,models.crr_price(side,S,K,T,r,q,s,N,american=False),lib)]
        if side==0:
            pairs+=[('q0-american',100,models.crr_price(0,S,K,T,r,0.0,s,100),library.crr_price(0,S,K,T,r,0.0,s,100,params)),
                    ('q0-european',100,models.crr_price(0,S,K,T,r,0.0,s,100,american=False),library.crr_price(0,S,K,T,r,0.0,s,100,params,american=False))]
        ok=bands.get(key,True)
        for kind,N,ours,lib in pairs:
            d=_rel(ours,lib);worst=max(worst,d);n+=1;ok=ok and d<=tol
            if on_point:on_point(p,kind,N,ours,lib)
        bands[key]=ok
    return bands,worst,n

# ---- Barone-Adesi-Whaley against QuantLib-Python (Amendment G2.4, G2.5; Appendix G-BAW R13; section 4 item 9) ----
BAW_RECORD_SK=(0.3,0.6,0.9,1.0,1.1,1.5,3.0)          # the record's oracle grid (Appendix G-BAW R13): 7 S/K x 6 T x 10 sigma x call/put
BAW_RECORD_T=(1/365/24,1/365,7/365,0.25,1.0,3.0)
BAW_RECORD_SIGMA=(1e-4,1.5e-4,1e-3,0.01,0.03,0.1,0.3,1.0,2.5,5.0)
BAW_RECORD_GRID=[(side,100.0*sk,100.0,T,s) for side in (0,1) for sk in BAW_RECORD_SK for T in BAW_RECORD_T for s in BAW_RECORD_SIGMA]

def ql_baw_option(side,S,K,T,r,q,sigma):
    """QuantLib-Python 1.43 BaroneAdesiWhaleyApproximationEngine on the unit-maturity problem of Amendment B item 3 (the
    optionlab.library construction: d0, maturity d0 + 365, Actual365Fixed, flat continuous r' and q', sigma' quote).
    Returns (option, vol quote). Used by the alignment checks (an independent construction; py-library is optionlab.library)."""
    import QuantLib as ql
    from optionlab.library import D0
    from optionlab.mapping import unit
    ql.Settings.instance().evaluationDate=D0
    r1,q1,s1=unit(T,r,q,sigma);dc=ql.Actual365Fixed();vol=ql.SimpleQuote(s1)
    rts=ql.YieldTermStructureHandle(ql.FlatForward(D0,r1,dc,ql.Continuous,ql.Annual))
    qts=ql.YieldTermStructureHandle(ql.FlatForward(D0,q1,dc,ql.Continuous,ql.Annual))
    vts=ql.BlackVolTermStructureHandle(ql.BlackConstantVol(D0,ql.NullCalendar(),ql.QuoteHandle(vol),dc))
    process=ql.BlackScholesMertonProcess(ql.QuoteHandle(ql.SimpleQuote(S)),qts,rts,vts)
    option=ql.VanillaOption(ql.PlainVanillaPayoff(ql.Option.Call if side==0 else ql.Option.Put,K),ql.AmericanExercise(D0,D0+365))
    option.setPricingEngine(ql.BaroneAdesiWhaleyApproximationEngine(process))
    return option,vol

def ql_baw_result(side,S,K,T,r,q,sigma,greeks=True):
    """The QuantLib engine in the form of models.baw_result: 'value'; with greeks=True also 'branch' and, in the European
    branch (every greek supplied), the engine greeks. A QuantLib exception raises models.ModelDefect with its text."""
    from optionlab.models import ModelDefect, RunDefect
    o,_=ql_baw_option(side,S,K,T,r,q,sigma)
    try:v=o.NPV()
    except RunDefect:raise                                                # H19
    except RuntimeError as exc:raise ModelDefect(str(exc)[:300]) from None
    out={'value':v}
    if not greeks:return out
    try:d=o.delta()
    except RuntimeError:return dict(out,branch='american')               # the American branch sets only the value (record R6)
    return dict(out,branch='european',delta=d,gamma=o.gamma(),theta=o.theta(),vega=o.vega(),rho=o.rho(),dividendRho=o.dividendRho())

QL_BAW_ENGINE=(lambda side,K,q:(lambda S_,T_,r_,s_:ql_baw_result(side,S_,K,T_,r_,q,s_,False)['value']),
               lambda side,K,q:(lambda S_,T_,r_,s_:ql_baw_result(side,S_,K,T_,r_,q,s_,True)))

def ql_baw_implied_vol(side,S,K,T,r,q,mid,params):
    """(status, sigma, evaluations) by ql.Brent (setMaxEvaluations 200, accuracy 1e-10, guess (sigma_lo + 5)/2) on the
    QuantLib BAW NPV, with baw_admit before each American-branch evaluation and the order-5 check (the optionlab.library
    `_solve` pattern): the independent IV of the alignment checks."""
    from optionlab.library import BRACKET_TEXT, MAX_EVAL_TEXT, brent_solve, CallbackStop
    from optionlab.models import sigma_lo, AdmitExcluded, RunDefect
    from optionlab.mapping import unit
    from optionlab.baw_admit import baw_admit_rates
    from optionlab.reference import tau_v, baw_admitted
    if side not in (0,1) or not all(math.isfinite(v) for v in (S,K,T,mid)) or S<=0.0 or K<=0.0:return 'INVALID_INPUT',math.nan,0
    if T<=0.0:return 'EXPIRED',math.nan,0
    lo=sigma_lo('baw',side,T,r,q,params)
    if lo>=params.sigma_hi:return 'MODEL_DOMAIN',math.nan,0
    r1,q1,_=unit(T,r,q,1.0);ins,adm=baw_admit_rates(side,r1,q1)
    if ins and not adm:return 'MODEL_DOMAIN',math.nan,0
    o,vol=ql_baw_option(side,S,K,T,r,q,lo);tau=tau_v(S,K,T,r,q);seen=[];stop=[];engine=[]
    def f(sigma):                                  # A5R-05 (Task A6): only declared stops (CallbackStop) leave the callback
        try:baw_admitted(side,S,K,T,r,q,sigma,'brent')
        except AdmitExcluded:stop.append(sigma);raise CallbackStop('excluded') from None
        vol.setValue(sigma*math.sqrt(T))
        try:v=o.NPV()
        except RuntimeError:engine.append(sigma);raise CallbackStop('engine error') from None    # order 5, not counted (as before)
        if not math.isfinite(v) or v<-tau:stop.append(sigma);raise CallbackStop('order 5')
        seen.append(v-mid);return v-mid
    try:root=brent_solve(f,lo,params.sigma_hi,(lo+params.sigma_hi)/2.0)     # A4-C2: the run-defect marker of the callback
    except RunDefect:raise                                               # H19
    except Exception as exc:
        n=len(seen)+len(stop);text=str(exc)
        if stop or engine:return 'MODEL_DOMAIN',math.nan,n
        if text.startswith(BRACKET_TEXT):return ('BELOW_MIN' if seen[0]>0.0 else 'ABOVE_MAX'),math.nan,n
        if text==MAX_EVAL_TEXT:return 'NOT_CONVERGED',math.nan,n
        return 'MODEL_DOMAIN',math.nan,n
    return 'OK',root,len(seen)

def _bits_equal(a,b):return a==b or (a!=a and b!=b)

def baw_record_grid(params,on_point=None):
    """Engine values of the record's oracle grid (840 points) and of their greek points (record R13 'greek points of the
    grid'): py-reference's transcription against QuantLib's NPV. An admitted point must give the same binary64 value or
    QuantLib must raise where the transcription raises; an excluded point (baw_admit false) must be a QuantLib exception
    (record R4 item 9, R13). Returns counts."""
    from optionlab import models
    from optionlab.models import ModelDefect, BawRunDefect, RunDefect, AloRunDefect
    from optionlab.mapping import unit
    from optionlab.baw_admit import baw_admit
    r,q=params.rate,params.dividend_yield;c={'points':0,'admitted':0,'excluded':0,'european':0,'bit_equal':0,'both_raise':0,'excluded_ql_raises':0,'mismatch':0}
    def point(side,S,K,T,rr,s):
        r1,q1,s1=unit(T,rr,q,s);ins,adm=baw_admit(side,S,K,r1,q1,s1*s1*1.0);c['points']+=1
        try:lib=('value',ql_baw_result(side,S,K,T,rr,q,s,False)['value'])
        except RunDefect:raise                                           # H19
        except ModelDefect:lib=('raise',None)
        if ins and not adm:
            c['excluded']+=1;ok=lib[0]=='raise';c['excluded_ql_raises']+=ok
        else:
            c['admitted' if ins else 'european']+=1
            try:ours=('value',models.baw_price(side,S,K,T,rr,q,s,params))
            except RunDefect:raise                                    # record R8: a run defect fails the check (review I-1)
            except ModelDefect:ours=('raise',None)
            ok=ours[0]==lib[0] and (ours[0]=='raise' or _bits_equal(ours[1],lib[1]))
            c['both_raise' if ours[0]=='raise' and ok else 'bit_equal']+=ok
        c['mismatch']+=not ok
        if on_point:on_point((side,S,K,T,rr,s),ok)
    for side,S,K,T,s in BAW_RECORD_GRID:
        point(side,S,K,T,r,s)
        hS=min(1e-3,0.1*s*math.sqrt(T))*S;d=min(1/365,T/2)
        for Sb,Tb,rb,sb in ((S+hS,T,r,s),(S-hS,T,r,s),(S-2*hS,T,r,s),(S+2*hS,T,r,s),(S,T,r,s+1e-3),(S,T,r,s-1e-3),(S,T,r+1e-4,s),(S,T,r-1e-4,s),(S,T-d,r,s),(S,T+d,r,s)):
            if Sb>0.0 and sb>0.0:point(side,Sb,K,Tb,rb,sb)
    return c

def baw_alignment(params,grid=ALIGN_GRID,on_field=None):
    """Section 4 item 9 for BAW on the alignment grid (sub-day rows included): py-reference's price and greeks at a fixed
    sigma against the same admission and stencil rule on QuantLib's engine values (QL_BAW_ENGINE), per field the largest
    |d| / max(1, |QuantLib|) and the bit-equal count, the flags and stencil forms; and the IV of each quotable price
    (>= 0.01) against ql.Brent on QuantLib's NPV (ql_baw_implied_vol): status, root within 1e-9, bit-equal roots."""
    from optionlab import reference
    from optionlab.models import BawRunDefect, RunDefect, AloRunDefect
    r,q=params.rate,params.dividend_yield;f={k:0.0 for k in ALIGN_TOL};eq=dict.fromkeys(ALIGN_TOL,0)
    st={'rows':0,'equal':0,'ok':0,'max_iv_abs':0.0,'root_bit_equal':0,'max_evaluations':0};n=0;raised=0;flags_differ=0;failures=[]
    for side,S,K,T,s in grid:
        try:ours=reference.price_and_greeks('baw',side,S,K,T,r,q,s,params)
        except RunDefect:raise                                        # record R8: a run defect fails the check (review I-1)
        except ArithmeticError as exc:ours=type(exc).__name__           # ModelDefect (incl. AdmitExcluded), EngineDomain, StencilUnresolved
        try:lib=reference.price_and_greeks('baw',side,S,K,T,r,q,s,params,engine=QL_BAW_ENGINE)
        except RunDefect:raise
        except ArithmeticError as exc:lib=type(exc).__name__
        n+=1
        if isinstance(ours,str) or isinstance(lib,str):
            raised+=1
            if ours!=lib:failures.append(f'baw grid {side},{S},{K},{T:.6g},{s}: raise {ours} vs {lib}')
            continue
        if ours['flags']!=lib['flags'] or ours['stencils']!=lib['stencils']:flags_differ+=1;failures.append(f'baw grid {side},{S},{K},{T:.6g},{s}: flags')
        bad=[]
        for k in ALIGN_TOL:
            d=_rel(ours[k],lib[k]);f[k]=max(f[k],d);eq[k]+=_bits_equal(ours[k],lib[k])
            if not d<=ALIGN_TOL[k]:bad.append(k)
            if on_field:on_field((side,S,K,T,s),k,ours[k],lib[k])
        if lib['price']>=0.01:
            ls,liv,ln=ql_baw_implied_vol(side,S,K,T,r,q,lib['price'],params)
            rs,vals,_=reference.evaluate3((side,S,K,T,lib['price'],lib['price'],r,q),'baw',params)
            st['rows']+=1;st['equal']+=rs==ls;st['max_evaluations']=max(st['max_evaluations'],ln)
            if rs!=ls:bad.append('iv_status')
            elif rs=='OK':
                st['ok']+=1;st['max_iv_abs']=max(st['max_iv_abs'],abs(vals[0]-liv));st['root_bit_equal']+=vals[0]==liv
                if not abs(vals[0]-liv)<=1e-9:bad.append('iv')
        if bad:failures.append(f'baw grid {side},{S},{K},{T:.6g},{s}: '+','.join(bad))
    return {'rows':n,'raised':raised,'flags_differ':flags_differ,'max_rel':f,'fraction_of_tolerance':{k:f[k]/ALIGN_TOL[k] for k in f},
            'bit_equal':eq,'iv':st,'failures':failures}

BAW_ROW_FIELDS=('iv','price','delta','gamma','theta','vega','rho')

def baw_edge_agreement(fx,params,on_row=None):
    """Section 4 item 9 for the BAW oracle edge rows (fixture part `baw`, kind `edge`, run-defect rows excluded): the whole
    row through reference.evaluate with py-reference's engine and with QuantLib's engine values (same admission, Brent and
    stencil rule): equal status, flags and admit_reason; IV within 1e-9 and every other field within ALIGN_TOL."""
    from optionlab import reference
    from optionlab.params import CaseParams
    failures=[];n=0;bit=0
    for e in (x for x in fx['oracle'].get('baw',[]) if x.get('kind')=='edge' and x['status']!='DEFECT'):
        pp=CaseParams(**{**params.__dict__,**e.get('params',{})});row=tuple(e['row']);n+=1
        ia={};ib={};a=reference.evaluate(row,'baw',pp,info=ia);b=reference.evaluate(row,'baw',pp,info=ib,engine=QL_BAW_ENGINE)
        bad=[] if (a[0],a[2],ia.get('admit_reason'))==(b[0],b[2],ib.get('admit_reason')) else ['status']
        for k,x,y in zip(BAW_ROW_FIELDS,a[1],b[1]):
            tol=1e-9 if k=='iv' else ALIGN_TOL[k]
            if not (_bits_equal(x,y) or (k=='iv' and abs(x-y)<=tol) or (k!='iv' and _rel(x,y)<=tol)):bad.append(k)
        bit+=all(_bits_equal(x,y) for x,y in zip(a[1],b[1]))
        if on_row:on_row(e,a,b)
        if bad:failures.append(f"baw edge {e['name']}: "+','.join(bad))
    return {'rows':n,'bit_equal_rows':bit,'failures':failures}

# ---- Andersen-Lake-Offengenden against QuantLib-Python (Amendment I4.1, I4.4; Appendix I-ALO R4, R13; section 4 item 9) ----
BAW_ORACLE_DIGEST_14747B4='6a532f0284c58ba8648e9480fb72ba617759430d5b05ebbc26ac452f76c35096'   # sha256 of the 42 canonical BAW rows at 14747b4

def baw_oracle_digest():
    """sha256 of the canonical BAW oracle rows of protocol/oracle.json (json, sorted keys, no spaces): the
    H19 evidence that the RunDefect base-class move leaves every BAW oracle row byte-identical to 14747b4."""
    rows=json.loads(FIXTURES.read_text())['oracle']['baw']
    return hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def ql_alo_option(side,S,K,T,r,q,sigma,fp='Auto'):
    """QuantLib-Python 1.43 QdFpAmericanEngine(process, accurateScheme(), fp) on the unit-maturity problem of Amendment B
    item 3 (the optionlab.library construction: d0, maturity d0 + 365, Actual365Fixed, flat continuous r' and q', sigma'
    quote). An independent construction for the alignment checks; py-library ALO is G-ALO2 part B."""
    import QuantLib as ql
    from optionlab.library import D0
    from optionlab.mapping import unit
    ql.Settings.instance().evaluationDate=D0
    r1,q1,s1=unit(T,r,q,sigma);return ql_alo_option_mapped(side,S,K,r1,q1,s1,fp)

def ql_alo_option_mapped(side,S,K,r1,q1,s1,fp='Auto'):
    import QuantLib as ql
    from optionlab.library import D0
    ql.Settings.instance().evaluationDate=D0
    dc=ql.Actual365Fixed();vol=ql.SimpleQuote(s1)
    rts=ql.YieldTermStructureHandle(ql.FlatForward(D0,r1,dc,ql.Continuous,ql.Annual))
    qts=ql.YieldTermStructureHandle(ql.FlatForward(D0,q1,dc,ql.Continuous,ql.Annual))
    vts=ql.BlackVolTermStructureHandle(ql.BlackConstantVol(D0,ql.NullCalendar(),ql.QuoteHandle(vol),dc))
    process=ql.BlackScholesMertonProcess(ql.QuoteHandle(ql.SimpleQuote(S)),qts,rts,vts)
    option=ql.VanillaOption(ql.PlainVanillaPayoff(ql.Option.Call if side==0 else ql.Option.Put,K),ql.AmericanExercise(D0,D0+365))
    eq={'Auto':ql.QdFpAmericanEngine.Auto,'FP_A':ql.QdFpAmericanEngine.FP_A,'FP_B':ql.QdFpAmericanEngine.FP_B}[fp]
    option.setPricingEngine(ql.QdFpAmericanEngine(process,ql.QdFpAmericanEngine.accurateScheme(),eq))
    return option,vol

def ql_alo_npv(side,S,K,T,r,q,sigma,fp='Auto'):
    """QuantLib's ALO NPV through the mapping; a QuantLib exception raises models.ModelDefect with its text (order 5)."""
    from optionlab.models import ModelDefect, RunDefect
    o,_=ql_alo_option(side,S,K,T,r,q,sigma,fp)
    try:return o.NPV()
    except RunDefect:raise                                                # H19
    except RuntimeError as exc:raise ModelDefect(str(exc)[:300]) from None

QL_ALO_ENGINE=lambda side,K,q:(lambda S_,T_,r_,s_:ql_alo_npv(side,S_,K,T_,r_,q,s_))

def ql_alo_implied_vol(side,S,K,T,r,q,mid,params):
    """(status, sigma, evaluations) by ql.Brent (setMaxEvaluations 200, accuracy 1e-10, guess (sigma_lo + 5)/2) on
    QuantLib's ALO NPV, with the ALO pre check and the order-5 check before each value returns to QuantLib (the
    optionlab.library `_solve` pattern): the independent IV of the ALO alignment checks."""
    from optionlab.library import BRACKET_TEXT, MAX_EVAL_TEXT, brent_solve, CallbackStop
    from optionlab.models import sigma_lo, RunDefect
    from optionlab.alo import AloPreCheck
    from optionlab.reference import tau_v, alo_pre
    if side not in (0,1) or not all(math.isfinite(v) for v in (S,K,T,mid)) or S<=0.0 or K<=0.0:return 'INVALID_INPUT',math.nan,0
    if T<=0.0:return 'EXPIRED',math.nan,0
    lo=sigma_lo('alo',side,T,r,q,params)
    if lo>=params.sigma_hi:return 'MODEL_DOMAIN',math.nan,0
    o,vol=ql_alo_option(side,S,K,T,r,q,lo);tau=tau_v(S,K,T,r,q);seen=[];stop=[]
    def f(sigma):                                  # A5R-05 (Task A6): only declared stops (CallbackStop) leave the callback
        try:alo_pre(side,S,K,T,r,q,sigma)
        except AloPreCheck:stop.append(sigma);raise CallbackStop('pre check') from None
        vol.setValue(sigma*math.sqrt(T))
        try:v=o.NPV()
        except RuntimeError:stop.append(sigma);raise CallbackStop('engine error') from None
        if not math.isfinite(v) or v<-tau:stop.append(sigma);raise CallbackStop('order 5')
        seen.append(v-mid);return v-mid
    try:root=brent_solve(f,lo,params.sigma_hi,(lo+params.sigma_hi)/2.0)     # A4-C2: the run-defect marker of the callback
    except RunDefect:raise                                               # H19
    except Exception as exc:
        n=len(seen)+len(stop);text=str(exc)
        if stop:return 'MODEL_DOMAIN',math.nan,n
        if text.startswith(BRACKET_TEXT):return ('BELOW_MIN' if seen[0]>0.0 else 'ABOVE_MAX'),math.nan,n
        if text==MAX_EVAL_TEXT:return 'NOT_CONVERGED',math.nan,n
        return 'MODEL_DOMAIN',math.nan,n
    return 'OK',root,len(seen)

ALO_SWITCH_T=(0.03571428571428818,0.03571428571428819)     # record R4: last double with FP-A, first with FP-B (case rates)
ALO_SWITCH_SECONDS=(1126285,1126286)

def alo_switch_vectors(params):
    """The record's R4 switch vectors (28): the last-A and first-B T as doubles and as chain seconds (calls and puts), the
    rate pair at T = 1 with q = 0 (the record's adjacent doubles and 0.001 with its neighbours), r = q at 2 y and 1 d, a rho
    pair and a theta pair that straddle the switch, Amendment C-like rates at 0.5 y and 2.5 y. Each holds the mapped rates
    r1, q1 and `quantlib_equation`, observed through QuantLib-Python: the explicit equation whose NPV equals the Auto NPV
    bit for bit (and the other one does not), plus the transcription's value bits check (`transcription_equal`). A call
    vector uses the exchanged rates (r <-> q): |r - q| and the equation are unchanged, and the call has an early-exercise
    premium, so the FP-A and FP-B values differ and QuantLib's branch is observable."""
    from optionlab import alo
    r,q=params.rate,params.dividend_yield;hr=params.h_r;spec=[]
    for T in ALO_SWITCH_T:
        for side in (0,1):spec.append((f't-{T!r}-{"call" if side==0 else "put"}',side,T,r,q))
    for sec in ALO_SWITCH_SECONDS:
        for side in (0,1):spec.append((f's-{sec}-{"call" if side==0 else "put"}',side,sec/31536000.0,r,q))
    for rr in (0.0009999999999999317,0.000999999999999932):
        for side in (0,1):spec.append((f'rate-{rr!r}-{"call" if side==0 else "put"}',side,1.0,rr,0.0))
    for rr in (math.nextafter(0.001,0.0),0.001,math.nextafter(0.001,1.0)):spec.append((f'rate-{rr!r}-put',1,1.0,rr,0.0))
    spec.append(('rate-0.001-call',0,1.0,0.001,0.0))
    for T in (2.0,1/365):
        for side in (0,1):spec.append((f'r-eq-q-{T!r}-{"call" if side==0 else "put"}',side,T,0.04,0.04))
    Ts=ALO_SWITCH_T[1]
    spec+=[('rho-plus',1,Ts,r+hr,q),('rho-minus',1,Ts,r-hr,q),('theta-t',1,Ts+0.5/365,r,q),('theta-t-minus-delta',1,Ts+0.5/365-1/365,r,q)]
    for T in (0.5,2.5):
        for side in (0,1):spec.append((f'c-like-{T!r}-{"call" if side==0 else "put"}',side,T,0.043,0.0425))
    out=[]
    for name,side,T,rr,qq in spec:
        from optionlab.mapping import unit
        if side==0:rr,qq=qq,rr          # a call is priced with exchanged rates (q > r) so that its exchanged put has an early-exercise premium and FP-A and FP-B differ
        r1,q1,s1=unit(T,rr,qq,0.3)
        vals={fp:ql_alo_option_mapped(side,100.0,100.0,r1,q1,s1,fp)[0].NPV() for fp in ('Auto','FP_A','FP_B')}
        a=_bits_equal(vals['Auto'],vals['FP_A']);b=_bits_equal(vals['Auto'],vals['FP_B'])
        eq='FP_A' if a and not b else 'FP_B' if b and not a else 'ambiguous'
        ours=alo.price(side,100.0,100.0,T,rr,qq,0.3,params)
        out.append({'name':name,'side':side,'T':T,'r':rr,'q':qq,'r1':r1,'q1':q1,'quantlib_equation':eq,'transcription_equal':_bits_equal(ours,vals['Auto'])})
    return out

ALO_FIELDS=('iv','price','delta','gamma','theta','vega','rho')

def alo_alignment(params,grid=ALIGN_GRID,on_field=None):
    """Section 4 item 9 for ALO on the alignment grid (sub-day rows included; Amendment I4.1): py-reference's price and
    greeks at a fixed sigma (optionlab.reference.price_and_greeks) against the same I2.6 stencil and segment rule on
    QuantLib's engine values (QL_ALO_ENGINE): flags and stencil forms equal, every field within ALIGN_TOL (`failures`);
    and the IV of each quotable price (>= 0.01) against ql.Brent on QuantLib's NPV (ql_alo_implied_vol): status equal and
    root within 1e-9. The expected result is bit equality: `mismatches` counts points with any field, flag or root that
    is not bit-equal. A run defect propagates (H19)."""
    from optionlab import reference
    from optionlab.models import RunDefect
    r,q=params.rate,params.dividend_yield;f={k:0.0 for k in ALIGN_TOL};eq=dict.fromkeys(ALIGN_TOL,0)
    st={'rows':0,'equal':0,'ok':0,'max_iv_abs':0.0,'root_bit_equal':0,'max_evaluations':0};n=0;raised=0;failures=[];mism=0
    for side,S,K,T,s in grid:
        try:ours=reference.price_and_greeks('alo',side,S,K,T,r,q,s,params)
        except RunDefect:raise
        except ArithmeticError as exc:ours=type(exc).__name__
        try:lib=reference.price_and_greeks('alo',side,S,K,T,r,q,s,params,engine=QL_ALO_ENGINE)
        except RunDefect:raise
        except ArithmeticError as exc:lib=type(exc).__name__
        n+=1;tag=f'alo grid {side},{S},{K},{T:.6g},{s}'
        if isinstance(ours,str) or isinstance(lib,str):
            raised+=1
            if ours!=lib:failures.append(tag+f': raise {ours} vs {lib}');mism+=1
            continue
        bad=[];bitbad=False
        if ours['flags']!=lib['flags'] or ours['stencils']!=lib['stencils']:bad.append('flags')
        for k in ALIGN_TOL:
            d=_rel(ours[k],lib[k]);f[k]=max(f[k],d);b=_bits_equal(ours[k],lib[k]);eq[k]+=b;bitbad=bitbad or not b
            if not d<=ALIGN_TOL[k]:bad.append(k)
            if on_field:on_field((side,S,K,T,s),k,ours[k],lib[k])
        if lib['price']>=0.01:
            ls,liv,ln=ql_alo_implied_vol(side,S,K,T,r,q,lib['price'],params)
            rs,vals,_=reference.evaluate3((side,S,K,T,lib['price'],lib['price'],r,q),'alo',params)
            st['rows']+=1;st['equal']+=rs==ls;st['max_evaluations']=max(st['max_evaluations'],ln)
            if rs!=ls:bad.append('iv_status')
            elif rs=='OK':
                st['ok']+=1;st['max_iv_abs']=max(st['max_iv_abs'],abs(vals[0]-liv));st['root_bit_equal']+=vals[0]==liv;bitbad=bitbad or vals[0]!=liv
                if not abs(vals[0]-liv)<=1e-9:bad.append('iv')
        mism+=bool(bad) or bitbad
        if bad:failures.append(tag+': '+','.join(bad))
    return {'status':'PASS' if not failures and n>0 else 'FAIL','rows':n,'raised':raised,'mismatches':mism,'max_rel':f,
            'fraction_of_tolerance':{k:f[k]/ALIGN_TOL[k] for k in f},'bit_equal':eq,'iv':st,'failures':failures}

ALO_RECORD_SK=(0.3,0.6,0.9,1.0,1.1,1.5,3.0)          # the record's oracle grid (Appendix I-ALO R13): 7 S/K x 6 T x 10 sigma x call/put
ALO_RECORD_T=(1/365/24,1/365,7/365,0.25,1.0,3.0)
ALO_RECORD_SIGMA=(1e-4,1.5e-4,1e-3,0.01,0.03,0.1,0.3,1.0,2.5,5.0)

def alo_record_grid(params):
    """Engine values of the record's oracle grid at sigma >= the R9 sigma_lo (777 of 840 points; below sigma_lo the FP-A
    value is not defined, record R9) and of their greek points (S +- h_S, sigma +- h_sigma, r +- h_r, T +- d): py-reference's
    transcription (optionlab.alo.price) against QuantLib's NPV with Auto, bit for bit, or both raising (order 5). A run
    defect propagates (H19). Returns counts."""
    from optionlab import alo
    from optionlab.models import ModelDefect, RunDefect, sigma_lo
    r,q=params.rate,params.dividend_yield;c={'points':0,'grid':0,'bit_equal':0,'both_raise':0,'mismatch':0}
    def point(side,S,K,T,rr,s):
        c['points']+=1
        try:lib=('value',ql_alo_npv(side,S,K,T,rr,q,s))
        except RunDefect:raise
        except ModelDefect:lib=('raise',None)
        try:ours=('value',alo.price(side,S,K,T,rr,q,s,params))
        except RunDefect:raise
        except ModelDefect:ours=('raise',None)
        ok=ours[0]==lib[0] and (ours[0]=='raise' or _bits_equal(ours[1],lib[1]))
        c['both_raise' if ok and ours[0]=='raise' else 'bit_equal']+=ok;c['mismatch']+=not ok
    for side in (0,1):
        for sk in ALO_RECORD_SK:
            for T in ALO_RECORD_T:
                lo=sigma_lo('alo',side,T,r,q,params)
                for s in ALO_RECORD_SIGMA:
                    if s<lo:continue
                    S=100.0*sk;K=100.0;c['grid']+=1;point(side,S,K,T,r,s)
                    hS=min(1e-3,0.1*s*math.sqrt(T))*S;d=min(1/365,T/2)
                    for Sb,Tb,rb,sb in ((S+hS,T,r,s),(S-hS,T,r,s),(S,T,r,s+1e-3),(S,T,r,s-1e-3),(S,T,r+1e-4,s),(S,T,r-1e-4,s),(S,T-d,r,s),(S,T+d,r,s)):
                        if sb>=lo:point(side,Sb,K,Tb,rb,sb)
    return c

def alo_edge_agreement(fx,params):
    """Section 4 item 9 for the ALO oracle edge rows (fixture part `alo`, kind `edge`, run-defect rows excluded): the
    whole row through reference.evaluate with py-reference's engine and with QuantLib's engine values (same pre check,
    Brent and stencil rule): equal status and flags, every field bit-equal (IV within 1e-9, others within ALIGN_TOL)."""
    from optionlab import reference
    from optionlab.params import CaseParams
    failures=[];n=0;bit=0
    for e in (x for x in fx['oracle'].get('alo',[]) if x.get('kind')=='edge' and x['status']!='DEFECT'):
        pp=CaseParams(**{**params.__dict__,**e.get('params',{})});row=tuple(e['row']);n+=1
        a=reference.evaluate(row,'alo',pp);b=reference.evaluate(row,'alo',pp,engine=QL_ALO_ENGINE)
        bad=[] if (a[0],a[2])==(b[0],b[2]) else ['status']
        for k,x,y in zip(ALO_FIELDS,a[1],b[1]):
            tol=1e-9 if k=='iv' else ALIGN_TOL[k]
            if not (_bits_equal(x,y) or (k=='iv' and abs(x-y)<=tol) or (k!='iv' and _rel(x,y)<=tol)):bad.append(k)
        bit+=all(_bits_equal(x,y) for x,y in zip(a[1],b[1]))
        if bad:failures.append(f"alo edge {e['name']}: "+','.join(bad))
    return {'rows':n,'bit_equal_rows':bit,'failures':failures}

def alo_quantlib_evidence(fx,params):
    """Every ALO part of section 4 item 9 (Amendment I4.1): the alignment grid, the record grid with greek points, the
    switch vectors and the oracle edge rows. Returns (ok, document)."""
    a=alo_alignment(params);g=alo_record_grid(params);sv=alo_switch_vectors(params);e=alo_edge_agreement(fx,params)
    from optionlab.alo_equation import alo_equation
    sw={'vectors':len(sv),'equation_equal':sum(1 for v in sv if alo_equation(v['r1'],v['q1'])==v['quantlib_equation']),
        'transcription_bit_equal':sum(1 for v in sv if v['transcription_equal'])}
    ok=(a['status']=='PASS' and g['mismatch']==0 and sw['equation_equal']==sw['vectors']==sw['transcription_bit_equal']
        and not e['failures'] and e['rows']>0)
    a['failures']=a['failures'][:20];e['failures']=e['failures'][:20]
    return ok,{'grid':a,'record_grid':g,'switch_vectors':sw,'edge_rows':e}

# ---- Task DD (finding P3-T15-CHILD-BUDGET-01, ruling D1-R2(b)): one producer of the shared QuantLib comparison per session ----
QL_EVIDENCE_PARTS=('lattice','baw_alignment','baw_record_grid','baw_edge_rows','alo')
QL_EVIDENCE_FILE='shared-quantlib-evidence.json'       # the framework hands a shared-* file of a PASS check to the later checks
QL_EVIDENCE_PRODUCER='b06-prerequisite-oracle'

def _quantlib_part(part,fx,params):
    """One part of the shared QuantLib comparison, in the form both checks read (a tuple result as a list)."""
    if part=='lattice':return list(lattice_agreement(fx,params))
    if part=='baw_alignment':return baw_alignment(params)
    if part=='baw_record_grid':return baw_record_grid(params)
    if part=='baw_edge_rows':return baw_edge_agreement(fx,params)
    if part=='alo':return list(alo_quantlib_evidence(fx,params))
    raise ValueError('unknown QuantLib evidence part')

def quantlib_evidence(fx,params,parts=QL_EVIDENCE_PARTS,doc=None):
    """The QuantLib comparison that b06-prerequisite-oracle (item 9) and quantlib-alignment both judge: lattice_agreement,
    baw_alignment, baw_record_grid, baw_edge_agreement and alo_quantlib_evidence on fixture `fx` and `params`. Each part
    of `parts` that `doc` does not hold yet is computed into `doc` (in `parts` order); returns `doc`."""
    doc={} if doc is None else doc
    for part in parts:
        if part not in doc:doc[part]=_quantlib_part(part,fx,params)
    return doc

def quantlib_binding(fx,params):
    """Every input the shared QuantLib comparison depends on: the fixture (sha256 of its canonical JSON, so an edited
    in-memory fixture differs too), the case parameters (alo_scheme and the test-only plant fields included), the optionlab
    source (sha256 over every file of the package) and the QuantLib version, with the evidence schema and part names. A
    saved comparison is reused only when this whole document is equal."""
    import dataclasses
    import QuantLib as ql
    pkg=Path(__file__).resolve().parent;src=hashlib.sha256()
    for p in sorted(x for x in pkg.iterdir() if x.is_file()):src.update(p.name.encode()+b'\0'+hashlib.sha256(p.read_bytes()).digest())
    fixture=hashlib.sha256(json.dumps(fx,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return json.loads(json.dumps({'schema_version':1,'kind':'quantlib-evidence','parts':list(QL_EVIDENCE_PARTS),'fixture_sha256':fixture,
                                  'params':dataclasses.asdict(params),'source_sha256':src.hexdigest(),'quantlib_version':ql.__version__},sort_keys=True))

def write_quantlib_evidence(out_dir,fx,params,doc):
    """b06-prerequisite-oracle: save the complete comparison with its binding as QL_EVIDENCE_FILE; returns the file name."""
    target=Path(out_dir)/QL_EVIDENCE_FILE
    target.write_text(json.dumps({'binding':quantlib_binding(fx,params),'evidence':{p:doc[p] for p in QL_EVIDENCE_PARTS}},sort_keys=True)+'\n')
    return target.name

def shared_quantlib_evidence(out_dir,fx,params):
    """quantlib-alignment: the comparison b06-prerequisite-oracle saved in the same check session (the framework restores it
    to bench/shared/<producer>/ next to the check's output directory). Returns (evidence, reason): the evidence only when
    the file is present, readable, complete and its binding equals quantlib_binding(fx, params) exactly; otherwise None
    and the reason, and the caller recomputes."""
    path=Path(out_dir).parent/'shared'/QL_EVIDENCE_PRODUCER/QL_EVIDENCE_FILE
    if not path.is_file():return None,'absent'
    try:doc=json.loads(path.read_text())
    except (OSError,ValueError):return None,'unreadable'
    if not isinstance(doc,dict) or doc.get('binding')!=quantlib_binding(fx,params):return None,'binding mismatch'
    ev=doc.get('evidence')
    if not isinstance(ev,dict) or sorted(ev)!=sorted(QL_EVIDENCE_PARTS):return None,'incomplete'
    return ev,'reused'

ITEM9_PARTS=('grid','lattice','known_answers','edge_rows','baw_grid','baw_edge_rows','alo')

def _within(ours,lib,tol):
    """_rel(ours, lib) <= tol: a NaN on one side fails, NaN against NaN and inf against inf pass (finding PL-T9B-NAN-MAX-01)."""
    return _rel(ours,lib)<=tol

def quantlib_agreement_item(fx,params,parts=ITEM9_PARTS,evidence=None):
    """Section 4 item 9 "QuantLib agreement" (Amendment B item 7, Amendment D item 0(a)): py-reference against py-library
    (QuantLib-Python 1.43). Parts: `grid` - the Task 7b oracle grid (sub-day and non-integer-day T included), price and
    greeks at a fixed sigma within ALIGN_TOL and the IV status, root (1e-9) of every quotable grid price, for each model;
    `lattice` - every lattice oracle point by `lattice_agreement` (CRR(100) American, CRR(N) European for N 100-800, the
    q = 0 call pair) at ALIGN_TOL['price']; `known_answers` - the item 3 rows, price and greeks within ALIGN_TOL;
    `edge_rows` - every oracle edge row (with its parameters) through reference.run and library.run, judged by
    agreement.compare (section 3.7 tolerances) with reduction MATCH. Every comparison is NaN-safe; any failure fails
    b06-prerequisite-oracle. `checked` counts the compared grid rows x models, lattice values, item 3 rows and edge rows.
    Task DD: the lattice, BAW and ALO parts come from quantlib_evidence; `evidence` (a dict, optional) receives them and
    may already hold some (then they are not computed again)."""
    from optionlab import agreement, library, reference
    from optionlab.params import CaseParams
    failures=[];counted={};ev={} if evidence is None else evidence
    if 'grid' in parts:
        r,q=params.rate,params.dividend_yield;n=0
        for m in ('bsm','bjs','crr'):
            for side,S,K,T,s in ALIGN_GRID:
                n+=1;ours=reference.price_and_greeks(m,side,S,K,T,r,q,s,params);lib=library.price_and_greeks(m,side,S,K,T,r,q,s,params)
                bad=[k for k in ALIGN_TOL if not _within(ours[k],lib[k],ALIGN_TOL[k])]
                if lib['price']>=0.01:
                    ls,liv,_=library.implied_vol(m,side,S,K,T,r,q,lib['price'],params)
                    rs,vals,_=reference.evaluate3((side,S,K,T,lib['price'],lib['price'],r,q),m,params)
                    if rs!=ls:bad.append('iv_status')
                    elif rs=='OK' and not abs(vals[0]-liv)<=1e-9:bad.append('iv')
                if bad:failures.append(f'grid {m} {side},{S},{K},{T:.6g},{s}: '+','.join(bad))
        counted['grid']=n
    if 'lattice' in parts:
        bands,_,n=quantlib_evidence(fx,params,('lattice',),ev)['lattice'];counted['lattice']=n
        failures+=[f'lattice {b}' for b,ok in sorted(bands.items()) if not ok]
        if n==0:failures.append('lattice: no value compared')
    if 'known_answers' in parts:
        rows=fx['oracle']['known_answers']
        for k in rows:
            ours=reference.price_and_greeks(k['model'],k['side'],k['S'],k['K'],k['T'],k['r'],k['q'],k['sigma'],params)
            lib=library.price_and_greeks(k['model'],k['side'],k['S'],k['K'],k['T'],k['r'],k['q'],k['sigma'],params)
            bad=[f for f in ALIGN_TOL if not _within(ours[f],lib[f],ALIGN_TOL[f])]
            if bad:failures.append(f"known {k['model']} {k['side']}: "+','.join(bad))
        counted['known_answers']=len(rows)
    if 'edge_rows' in parts:
        rows=fx['oracle']['edge_rows']
        for e in rows:
            pp=CaseParams(**{**params.__dict__,**e.get('params',{})});rw=[tuple(e['row'])]
            v=agreement.compare(rw,library.run(rw,pp),reference.run(rw,pp),pp)
            if not v['eligible'] or v['reduction']!='MATCH':failures.append(f"edge {e['name']}: "+(','.join(sorted(v['failures'])) or v['reduction']))
        counted['edge_rows']=len(rows)
    if 'baw_grid' in parts:                  # Amendment G2.4: BAW at ALIGN_TOL (exact QuantLib agreement) on the grid, sub-day rows included
        quantlib_evidence(fx,params,('baw_alignment','baw_record_grid'),ev);a,g=ev['baw_alignment'],ev['baw_record_grid'];counted['baw_grid']=a['rows']+g['points']
        failures+=a['failures']+([f"baw record grid: {g['mismatch']} mismatches"] if g['mismatch'] else [])
    if 'baw_edge_rows' in parts:
        e=quantlib_evidence(fx,params,('baw_edge_rows',),ev)['baw_edge_rows'];counted['baw_edge_rows']=e['rows'];failures+=e['failures']
        if e['rows']==0:failures.append('baw edge rows: none in the fixture')
    if 'alo' in parts:                       # Amendment I4.1: ALO at ALIGN_TOL (expected bit equality), sub-day rows and switch vectors included
        ok,doc=quantlib_evidence(fx,params,('alo',),ev)['alo']
        counted['alo']=doc['grid']['rows']+doc['record_grid']['points']+doc['switch_vectors']['vectors']+doc['edge_rows']['rows']
        if not ok:failures+=doc['grid']['failures']+doc['edge_rows']['failures']+[f"alo record grid {doc['record_grid']['mismatch']} mismatches, switch vectors {doc['switch_vectors']}"]
    checked=sum(counted.values())
    return {'status':'PASS' if not failures and checked>0 else 'FAIL','checked':checked,'failures':failures,'parts':counted}

@check('quantlib-alignment')
def quantlib_alignment(out_dir,args):
    """Task 7b evidence: py-reference against QuantLib-Python 1.43 on the oracle grid of the alignment test and on the
    seeded synthetic small chain. alignment.json holds the statistics; PASS when every grid field is inside its tolerance,
    every grid IV status is equal, every grid IV is within 1e-9, and agreement.compare finds the chain eligible.
    Task DD (DD1): the lattice, BAW and ALO comparison is the one b06-prerequisite-oracle saved in the same check session
    when its binding matches exactly (shared_quantlib_evidence), and is recomputed otherwise; the grid and the chain are
    this check's own part. `quantlib_evidence` in alignment.json records which."""
    import copy
    if _no_arguments(args):return _no_arguments(args)
    from optionlab import oracle
    from optionlab.params import CASE
    grid=_alignment_grid(CASE);chain=_alignment_chain(CASE)
    fx=json.loads(FIXTURES.read_text());ev,reason=shared_quantlib_evidence(out_dir,fx,CASE)
    provenance={'source':'reused' if ev is not None else 'computed','reason':reason}
    ev=copy.deepcopy(ev if ev is not None else quantlib_evidence(fx,CASE))
    bands,worst,n=ev['lattice']
    lattice={'values':n,'max_rel':worst,'fraction_of_tolerance':worst/ALIGN_TOL['price'],'bands_equal':bands,
             'crr_accuracy':oracle.crr_accuracy(fx,CASE,agreement=bands)}
    baw=ev['baw_alignment'];baw['record_grid']=ev['baw_record_grid'];baw['edge_rows']=ev['baw_edge_rows']   # G2.4: BAW counted
    baw_ok=(not baw['failures'] and baw['record_grid']['mismatch']==0 and not baw['edge_rows']['failures'] and baw['iv']['equal']==baw['iv']['rows'])
    alo_ok,alo=ev['alo']                                                                                     # I4.1: ALO counted
    for k in ('failures',):baw[k]=baw[k][:20];baw['edge_rows'][k]=baw['edge_rows'][k][:20]
    ok=(all(v<=1.0 for m in grid.values() for v in m['fraction_of_tolerance'].values())
        and all(m['iv']['equal']==m['iv']['rows'] and m['iv']['max_iv_abs']<=1e-9 for m in grid.values()) and chain['compare']['eligible']
        and n>0 and all(bands.values()) and baw_ok and alo_ok)
    return _stdlib_body(out_dir,'alignment.json',{'status':'PASS' if ok else 'FAIL','grid':grid,'chain':chain,'lattice':lattice,'baw':baw,'alo':alo,
                        'quantlib_evidence':provenance,
                        'counts':{'grid_rows':len(ALIGN_GRID),'chain_rows':chain['rows'],'lattice_values':n,'baw_grid_rows':baw['rows'],
                                  'baw_record_points':baw['record_grid']['points'],'baw_edge_rows':baw['edge_rows']['rows'],
                                  'alo_grid_rows':alo['grid']['rows'],'alo_grid_mismatches':alo['grid']['mismatches'],'alo_record_points':alo['record_grid']['points'],
                                  'alo_record_mismatches':alo['record_grid']['mismatch'],'alo_switch_vectors':alo['switch_vectors']['vectors'],'alo_edge_rows':alo['edge_rows']['rows']}})

def _variant_stats(rows,base,got):
    """Per model, over the rows where both sides are OK and the base row is neither boundary_ambiguous nor flat_vega: the
    largest |difference| / section 3.7 tolerance per field (base = the tolerance basis), the count of bit-equal values per
    field, and the count of equal statuses (numbers only)."""
    from optionlab import agreement, reference
    out={}
    for m in base['models']:
        a,b=base['models'][m],got['models'][m];w={k:0.0 for k in ('iv','price','delta','gamma','theta','vega','rho')};eq=dict.fromkeys(w,0);k=0
        for i in range(len(rows)):
            if a['status'][i]!='OK' or b['status'][i]!='OK' or a['flags'][i]&(reference.FLAG_BOUNDARY_AMBIGUOUS|reference.FLAG_FLAT_VEGA):continue
            k+=1;nu=a['vega'][i]*100.0;ts=agreement.tau_sigma(a['price'][i],nu)
            w['iv']=max(w['iv'],_frac(b['iv'][i],a['iv'][i],ts))
            w['price']=max(w['price'],_frac(b['price'][i],a['price'][i],nu*ts+1e-12*max(1.0,abs(a['price'][i]))))
            for f in ('delta','gamma','theta','vega','rho'):w[f]=max(w[f],_frac(b[f][i],a[f][i],1e-9+(1e-6+ts/a['iv'][i])*abs(a[f][i])))
            for f in w:eq[f]+=a[f][i]==b[f][i]
        out[m]={'compared_ok_rows':k,'fraction_of_tolerance':w,'bit_equal':eq,'status_equal':sum(x==y for x,y in zip(a['status'],b['status'])),
                'status_counts':{s:b['status'].count(s) for s in sorted(set(b['status']))}}
    return out

COMPARE_KEYS=('eligible','failures','multi_root','boundary_ambiguous','flat_vega','model_errors','rounding_band','rounding_band_variant_only',
              'band_status_mismatch','reduction')

def _optimized_grid(params):
    """py-optimized on the Task 7b grid at a fixed sigma against py-reference and QuantLib-Python: per model the largest
    _rel / ALIGN_TOL per field (NaN difference -> inf, finding PL-T9B-NAN-MAX-01), dead lanes and bit-equal counts."""
    import numpy as np
    from optionlab import library, optimized as opt, reference
    r,q=params.rate,params.dividend_yield;grid={}
    side=np.array([x[0] for x in ALIGN_GRID],np.uint8);S,K,T,s=(np.array([x[i] for x in ALIGN_GRID]) for i in (1,2,3,4))
    for m in ('bsm','bjs','crr'):
        pg=opt.price_and_greeks(m,side,S,K,T,r,q,s,params);fr={k:0.0 for k in ALIGN_TOL};fl={k:0.0 for k in ALIGN_TOL};eq=dict.fromkeys(ALIGN_TOL,0)
        for i,(sd,S_,K_,T_,s_) in enumerate(ALIGN_GRID):
            a=reference.price_and_greeks(m,sd,S_,K_,T_,r,q,s_,params);b=library.price_and_greeks(m,sd,S_,K_,T_,r,q,s_,params)
            for k in ALIGN_TOL:
                x=float(pg[k][i]);fr[k]=max(fr[k],_rel(x,a[k])/ALIGN_TOL[k]);fl[k]=max(fl[k],_rel(x,b[k])/ALIGN_TOL[k]);eq[k]+=x==a[k]
        grid[m]={'rows':len(ALIGN_GRID),'dead':int(pg['dead'].sum()),'fraction_of_align_tol_vs_reference':fr,'fraction_of_align_tol_vs_quantlib':fl,'bit_equal_vs_reference':eq}
    return grid

def _prep_rows(rws):
    """The py-optimized prepared input of py-reference row tuples (side, S, K, T, bid, ask, r, q); side 255: unknown side."""
    import numpy as np
    return {'n':len(rws),'side':np.array([x[0] if x[0] in (0,1) else 255 for x in rws],np.uint8),
            **{k:np.array([x[i] for x in rws],float) for k,i in (('S',1),('K',2),('T',3),('bid',4),('ask',5),('r',6),('q',7))}}

@check('optimized-agreement')
def optimized_agreement(out_dir,args):
    """Task 11b evidence: py-optimized against py-reference and against QuantLib-Python 1.43. Seeded synthetic small chain
    (agreement.compare at the section 3.7 tolerances, both bases), every oracle edge row (with its parameters), the Task 7b
    grid at a fixed sigma (ALIGN_TOL) and every lattice oracle point (CRR(100) American, CRR(N) European for N 100-800 at
    ALIGN_TOL['price']). optimized-agreement.json holds the statistics and NumPy's SIMD dispatch record. PASS when every
    comparison is eligible with reduction MATCH and every grid and lattice value is inside its tolerance."""
    if _no_arguments(args):return _no_arguments(args)
    import math, time
    import numpy as np
    from optionlab import agreement, library, models, optimized as opt, reference, synthetic
    from optionlab.contract import load_chain, rows as chain_rows
    from optionlab.params import CASE, CaseParams
    params=CASE;r,q=params.rate,params.dividend_yield;fx=json.loads(FIXTURES.read_text());prep=_prep_rows
    rows=chain_rows(load_chain(synthetic.generate(synthetic.SIZES['small'],ALIGN_SEED,params)),params)
    t0=time.perf_counter();got=opt.materialize(opt.run(prep(rows),params));t_opt=time.perf_counter()-t0
    t0=time.perf_counter();ref=reference.run(rows,params);t_ref=time.perf_counter()-t0
    lib=library.run(rows,params)
    v_ref=agreement.compare(rows,got,ref,params);v_lib=agreement.compare(rows,got,lib,params)
    chain={'rows':len(rows),'seed':ALIGN_SEED,'compare_vs_reference':{k:v_ref[k] for k in COMPARE_KEYS},'compare_vs_quantlib':{k:v_lib[k] for k in COMPARE_KEYS},
           'vs_reference':_variant_stats(rows,ref,got),'vs_quantlib':_variant_stats(rows,lib,got),
           'seconds_informational':{'py-optimized':t_opt,'py-reference':t_ref}}
    edge={'rows':0,'eligible_vs_reference':0,'eligible_vs_quantlib':0,'status_equal_vs_reference':0}
    for e in fx['oracle']['edge_rows']:
        pp=CaseParams(**{**params.__dict__,**e.get('params',{})});rw=[tuple(e['row'])]
        g=opt.materialize(opt.run(prep(rw),pp));a=reference.run(rw,pp);b=library.run(rw,pp)
        edge['rows']+=1;edge['eligible_vs_reference']+=agreement.compare(rw,g,a,pp)['eligible'];edge['eligible_vs_quantlib']+=agreement.compare(rw,g,b,pp)['eligible']
        edge['status_equal_vs_reference']+=all(g['models'][m]['status']==a['models'][m]['status'] for m in a['models'])
    grid=_optimized_grid(params)
    pts=fx['oracle']['lattice'];ls=np.array([p['side'] for p in pts],np.uint8);LS,LK,LT,Ls=(np.array([p[k] for p in pts]) for k in ('S','K','T','sigma'))
    lattice={'points':len(pts),'values':0,'max_rel_vs_quantlib':0.0,'max_rel_vs_reference':0.0,'dead':0}
    for N,american in ((100,True),(100,False),(200,False),(400,False),(800,False)):
        val,dead=opt.crr_price(ls,LS,LK,LT,r,q,Ls,N,american=american);lattice['dead']+=int(dead.sum())
        for i,p in enumerate(pts):
            b=library.crr_price(p['side'],p['S'],p['K'],p['T'],r,q,p['sigma'],N,params,american=american)
            a=models.crr_price(p['side'],p['S'],p['K'],p['T'],r,q,p['sigma'],N,american=american)
            x=float(val[i]);lattice['values']+=1
            lattice['max_rel_vs_quantlib']=max(lattice['max_rel_vs_quantlib'],_rel(x,b))
            lattice['max_rel_vs_reference']=max(lattice['max_rel_vs_reference'],_rel(x,a))
    lattice['fraction_of_align_tol_vs_quantlib']=lattice['max_rel_vs_quantlib']/ALIGN_TOL['price']
    ok=(v_ref['eligible'] and v_lib['eligible'] and v_ref['reduction']==v_lib['reduction']=='MATCH'
        and edge['eligible_vs_reference']==edge['rows']==edge['eligible_vs_quantlib']==edge['status_equal_vs_reference'] and edge['rows']>0
        and all(x<=1.0 for g in grid.values() for k in ('fraction_of_align_tol_vs_reference','fraction_of_align_tol_vs_quantlib') for x in g[k].values())
        and all(g['dead']==0 for g in grid.values()) and lattice['dead']==0 and lattice['values']>0 and lattice['fraction_of_align_tol_vs_quantlib']<=1.0
        and all(math.isfinite(t) for t in (t_opt,t_ref)))
    return _stdlib_body(out_dir,'optimized-agreement.json',{'status':'PASS' if ok else 'FAIL','chain':chain,'edge_rows':edge,'grid':grid,'lattice':lattice,
                        'runtime':opt.runtime_record(),'counts':{'chain_rows':len(rows),'edge_rows':edge['rows'],'grid_rows':len(ALIGN_GRID),'lattice_values':lattice['values']}})

CASE_FILE=Path(__file__).resolve().parents[2]/'cases'/'option-chain-greeks.json'
AGREEMENT_VARIANTS=(('py-optimized','direct'),('py-library','direct'))
AGREEMENT_CHAINS=((1,64),(2,64),(3,64),(4,256))   # (seed, rows): seeds 1-3 as the brief; seed 4: 256 rows

def agreement_body(out_dir,chains=AGREEMENT_CHAINS,edge_names=None):
    """Body of b06-prerequisite-agreement (the former Task 12 coordinator job). Each variant of AGREEMENT_VARIANTS (single-threaded
    variants only; owner 2026-10-16) runs on the synthetic chains of `chains` ((seed, rows), the case parameters) and on each
    oracle edge row (all when `edge_names` is None) under its own parameters, as a one-row input. Every row is judged against
    py-reference by agreement.compare (section 3.7 tolerances; never widened). The check passes when every row is
    `eligible`, and `eligible` is the compare() result: compare() accepts a status difference inside the rounding band, so
    an exact status match is not required for the pass. Each row also records `status_equal_reference` (the exact match
    of every model's statuses) as evidence only. agreement.json holds one row per (input, variant)."""
    from optionlab import library, optimized as opt
    from optionlab.agreement import compare
    from optionlab.contract import load_chain, rows as chain_rows
    from optionlab.reference import run as ref_run
    from optionlab.synthetic import generate
    from optionlab.params import CASE, CaseParams, params_from_manifest
    manifest=json.loads(CASE_FILE.read_text());base={k:v['value'] for k,v in manifest['parameters'].items()}
    if params_from_manifest(manifest)!=CASE:return {'status':'FAIL','reason':'case manifest parameters differ from CASE','files':[]}
    inputs=[]              # (key, value, params, adapter parameters, rows)
    for seed,n in chains:
        inputs.append(('seed',seed,CASE,base,chain_rows(load_chain(generate(n,seed,CASE)),CASE)))
    edges=json.loads(FIXTURES.read_text())['oracle']['edge_rows']
    for e in edges:
        if edge_names is not None and e['name'] not in edge_names:continue
        extra=e.get('params',{});p=CaseParams(**{**CASE.__dict__,**extra});raw={**base,**extra}
        if params_from_manifest({'parameters':{k:{'value':v} for k,v in raw.items()}})!=p:
            return {'status':'FAIL','reason':'edge row parameters do not map to the adapter','files':[]}
        inputs.append(('edge_row',e['name'],p,raw,[tuple(e['row'])]))
    if edge_names is not None and len(inputs)-len(chains)!=len(set(edge_names)):return {'status':'FAIL','reason':'unknown edge row name','files':[]}
    table={}               # (input index, variant, workers) -> agreement row
    for i,(key,value,p,raw,rw) in enumerate(inputs):
        ref=ref_run(rw,p);direct=opt.run(_prep_rows(rw),p)
        for variant,workers in AGREEMENT_VARIANTS:
            got=opt.materialize(direct) if variant=='py-optimized' else library.run(rw,p)
            v=compare(rw,got,ref,p);same=all(got['models'][m]['status']==ref['models'][m]['status'] for m in ref['models'])
            table[i,variant,workers]={key:value,'rows':len(rw),'variant':variant,'workers':workers,'eligible':v['eligible'],'compare_eligible':v['eligible'],'failures':v['failures'],
                                      'reduction':v['reduction'],'status_equal_reference':same}
    out=[table[i,variant,workers] for i in range(len(inputs)) for variant,workers in AGREEMENT_VARIANTS]
    with open(Path(out_dir)/'agreement.json','w') as f:json.dump(out,f,separators=(',',':'),allow_nan=False)
    eligible=sum(1 for r in out if r['eligible'])
    return {'status':'PASS' if out and eligible==len(out) else 'FAIL','files':['agreement.json'],
            'counts':{'rows':len(out),'eligible':eligible,'chains':len(chains),'edge_rows':len(inputs)-len(chains),'variants':len(AGREEMENT_VARIANTS)}}

@check('b06-prerequisite-agreement')
def agreement(out_dir,args):
    """B06 prerequisite (B06 itself is a Phase 2 case): every Python variant agrees with py-reference; see agreement_body."""
    if _no_arguments(args):return _no_arguments(args)
    return agreement_body(out_dir)

COST_SIZES=(1,32,64,256,1024);COST_REPS=20;COST_SEED=20261007

def _median_seconds(fn,reps):
    import time
    fn();ts=[]                     # one warm-up call, then `reps` timed calls
    for _ in range(reps):
        t0=time.perf_counter_ns();fn();ts.append((time.perf_counter_ns()-t0)/1e9)
    ts.sort();return {'median_s':ts[len(ts)//2] if len(ts)%2 else (ts[len(ts)//2-1]+ts[len(ts)//2])/2.0,'min_s':ts[0],'max_s':ts[-1],'reps':reps}

def call_cost_body(out_dir,sizes=COST_SIZES,reps=COST_REPS):
    """EXPLORATORY (Task 12b review, Important 1): the median warm wall time of one py-optimized `optimized.run` call per
    synthetic size (and per model at each size). The fixed cost per call is the intercept of a
    least-squares line over the sizes. Not decision evidence: one container session, no isolation from host load."""
    from optionlab import optimized as opt
    from optionlab.contract import load_chain
    from optionlab.synthetic import generate
    from optionlab.params import CASE
    chain=load_chain(generate(max(sizes),COST_SEED,CASE));whole=opt.prepare(chain,CASE);run_rows=[]
    for n in sizes:
        prep=opt.slice_prepared(whole,0,n);row={'rows':n,'run':_median_seconds(lambda:opt.run(prep,CASE),reps)}
        row['models']={m:_median_seconds(lambda m=m:opt.evaluate_model(m,prep,CASE),reps)['median_s'] for m in opt.MODELS}
        run_rows.append(row)
    xs=[r['rows'] for r in run_rows];ys=[r['run']['median_s'] for r in run_rows];k=len(xs);mx=sum(xs)/k;my=sum(ys)/k
    slope=sum((x-mx)*(y-my) for x,y in zip(xs,ys))/sum((x-mx)**2 for x in xs);fit={'fixed_s_per_call':my-slope*mx,'s_per_row':slope}
    doc={'label':'exploratory, not decision evidence','reps':reps,'opt_run':run_rows,'fit':fit,'runtime':opt.runtime_record()}
    with open(Path(out_dir)/'call-cost.json','w') as f:json.dump(doc,f,separators=(',',':'),allow_nan=False)
    return {'status':'PASS','label':'exploratory','files':['call-cost.json'],'counts':{'sizes':len(run_rows),'reps':reps}}

@check('call-cost-exploratory')
def call_cost(out_dir,args):
    """Exploratory measurement of the py-optimized fixed cost per call; see call_cost_body."""
    if _no_arguments(args):return _no_arguments(args)
    return call_cost_body(out_dir)

@check('c-vectors')
def c_vectors(out_dir,args):
    """C test vectors (Phase 2 Task 7): pl_vec_<part>.h for each named part, every part when none is named; on every run
    (controller ruling A35: `bench check` passes no arguments) the corpus_files() entries as one file corpus.json
    ({name: lowercase hex of the bytes}, sorted keys; the host splits it into fuzz/project/corpus/protocol/<name>, and an inproc-<name> entry into fuzz/project/corpus/inproc/<name>). One file,
    because the host fetches at most 32 files of a check (tools/bench.py check_files; Task 13 finding P2-T13-FETCH-01)."""
    from optionlab import cvectors
    names=list(args) or sorted(cvectors.PARTS)
    if not all(n in cvectors.PARTS for n in names):return {'status':'FAIL','reason':'unknown vector part','files':[]}
    files,counts=cvectors.write_parts(out_dir,names)   # write_parts writes a part whose text starts with '{' as <part>.json
    if 'corpus' in cvectors.PARTS:return {'status':'FAIL','reason':'a vector part named corpus would collide with corpus.json','files':[]}
    corpus={name:data.hex() for name,data in cvectors.corpus_files().items()}
    target=Path(out_dir)/'corpus.json';target.write_text(json.dumps(corpus,sort_keys=True,indent=1)+'\n',encoding='ascii');files.append(target.name)
    counts['corpus']=len(corpus)
    return {'status':'PASS','files':files,'counts':counts}

def _census_files(out_dir):
    """Writes census.json and census-rows.json of cvectors.census_documents(); returns (names, census doc, rows text)."""
    from optionlab import cvectors
    census_text,rows_text=cvectors.census_documents()
    names=['census.json','census-rows.json']
    for name,text in zip(names,(census_text,rows_text)):(Path(out_dir)/name).write_text(text,encoding='ascii')
    return names,json.loads(census_text),rows_text

def census_gate(out_dir,tracked):
    """The c-census result against the tracked rows file `tracked`. FAIL (controller ruling N9) when `tracked` is absent,
    not a regular file, unreadable, or differs from the regenerated census-rows.json; when a raise location is outside
    the resolved cvectors.CENSUS_ANCHORS (a new raise point); when an anchor does not resolve to exactly one location (a lost
    raise point or an ambiguous anchor, Task CA); or when the trap row does not raise for crr only among bsm and crr."""
    names,doc,rows_text=_census_files(out_dir)
    try:same=Path(tracked).is_file() and Path(tracked).read_text(encoding='ascii')==rows_text
    except (OSError,UnicodeDecodeError):same=False
    ok=same and not doc['unexpected'] and not doc['anchor_errors'] and doc['trap_ok']
    return {'status':'PASS' if ok else 'FAIL','files':names,'counts':{'rows':doc['rows'],'locations':len(doc['raises']),
            'raising_rows':doc['raising_rows'],'unexpected':len(doc['unexpected']),'anchor_errors':len(doc['anchor_errors']),
            'tracked_rows_differ':0 if same else 1}}

@check('c-census')
def c_census(out_dir,args):
    """The raise census of Phase 2 Task 11 (1,000 hostile rows, models of ALL_MODELS) as a gate: census.json (raise counts
    by type and file:line, the raising-row count, the G4.8 trap-row models, the locations outside the audit table) and
    census-rows.json (the distinct raising rows, NaN and infinities as "nan", "inf", "-inf"); see census_gate."""
    if _no_arguments(args):return _no_arguments(args)
    from optionlab import cvectors
    return census_gate(out_dir,Path(cvectors.__file__).with_name(cvectors.CENSUS_ROWS_FILE))

@check('c-census-generate')
def c_census_generate(out_dir,args):
    """Regeneration of the census files (before_run false): writes census.json and census-rows.json and always passes, so
    the framework fetches them; the host copies census-rows.json to optionlab/census_rows.json and then runs c-census.
    It compares nothing and is never a gate."""
    if _no_arguments(args):return _no_arguments(args)
    names,doc,_=_census_files(out_dir)
    return {'status':'PASS','files':names,'counts':{'rows':doc['rows'],'locations':len(doc['raises']),'raising_rows':doc['raising_rows']}}

@check('baw-hang-stub')
def baw_hang_stub(out_dir,args):
    """Test-only (G2.3, G2.6; `before_run: false`): one py-library call of selector `baw` on a one-row synthetic chain (the
    case seed). Without the stub it passes. With SAFE_C_TEST_STUB=baw-hang (passed by the coordinator only to a selftest
    plan) the py-library BAW path blocks; the coordinator's call deadline kills the check child: FAIL with reason
    baw-hang (tools/bench_deadline.baw_hang_check_selftest). No timer runs in this process."""
    if _no_arguments(args):return _no_arguments(args)
    import tempfile
    from benchlab.workload import load_case_adapter
    case=json.loads(CASE_FILE.read_text());a=load_case_adapter(case,selector='baw')
    data=a.synthesize(1,int(case['parameters']['seed']['value']));p=Path(tempfile.mkdtemp())/'chain.json';p.write_bytes(data)
    chain=a.load({'path':str(p),'sha256':hashlib.sha256(data).hexdigest()})
    res=a.materialize(a.run(a.prepare(chain,'py-library',1),'py-library',1))
    return {'status':'PASS' if a.work_units(res)==1 else 'FAIL','files':[],'counts':{'rows':1}}

# ---- G2.4 (Task 7): the BAW variant spread against py-reference and the tolerance proposal (measurement only, no gate) ----
SPREAD_CHAINS=((ALIGN_SEED,1024),(1,512),(2,512),(3,512))   # (seed, rows): the first 1,024 rows of the synthetic large chain and three fixed seeds
SPREAD_VARIANTS=(('py-optimized',1),('py-library',1))
SPREAD_DIRECT=('py-optimized','py-library')                # the oracle-set rows carry their own parameters: direct variants only
BAW_GREEK_FIELDS=('delta','gamma','theta','vega','rho')
SSTAR_MARGIN=1.0       # proposed sstar_k = this x the largest measured S* term per unit K, rounded up to one significant digit
SSTAR_CANDIDATES=(0.0,1.0,2.0)   # margins reported against the item 7 bound (0: no S* term, the R4/G2.4 shared-S* reading)

def ceil_1sig(x):
    """x rounded up to one significant decimal digit (None for x <= 0)."""
    if not x>0:return None
    e=math.floor(math.log10(x));m=math.ceil(round(x/10.0**e,12))
    if m>=10:m,e=1,e+1
    return float(f'{m}e{e}')

def _empty_spread():
    return {'rows':0,'compared_ok_rows':0,'status_equal':0,'flags_equal':0,'max_abs':{f:0.0 for f in BAW_ROW_FIELDS},
            'max_fraction_of_general':{f:0.0 for f in BAW_ROW_FIELDS+('fit',)},'bit_equal':{f:0 for f in BAW_ROW_FIELDS},
            'need_sstar_k':{g:0.0 for g in BAW_GREEK_FIELDS},'compare_failures':{},'compare_ineligible':0}

def _merge_spread(acc,rows,a,b,params,compare_v):
    """Add one comparison of a variant column `b` with the py-reference column `a` (BAW only) to `acc`. Fractions use the
    section 3.7 rules at the general (provisional) values; `need_sstar_k` is the smallest sstar_k[g] that would admit
    the greek difference beyond the general greek rule, per unit K."""
    from optionlab import agreement, reference
    tol=agreement.TOLERANCES;acc['rows']+=len(rows)
    for k,v in compare_v['failures'].items():acc['compare_failures'][k]=acc['compare_failures'].get(k,0)+v
    acc['compare_ineligible']+=not compare_v['eligible']
    for i,row in enumerate(rows):
        acc['status_equal']+=a['status'][i]==b['status'][i];acc['flags_equal']+=a['flags'][i]==b['flags'][i]
        if a['status'][i]!='OK' or b['status'][i]!='OK' or a['flags'][i]&(reference.FLAG_BOUNDARY_AMBIGUOUS|reference.FLAG_FLAT_VEGA):continue
        acc['compared_ok_rows']+=1;K=row[2];mid=(row[4]+row[5])/2.0
        nu=a['vega'][i]*100.0;ts=agreement.tau_sigma(a['price'][i],nu);pr=a['price'][i]
        allow={'iv':ts,'price':nu*ts+tol['price_rel']*max(1.0,abs(pr))}
        for g in BAW_GREEK_FIELDS:allow[g]=tol['greek_abs']+(tol['greek_rel']+ts/a['iv'][i])*abs(a[g][i])
        for f in BAW_ROW_FIELDS:
            d=abs(b[f][i]-a[f][i]);acc['max_abs'][f]=max(acc['max_abs'][f],d);acc['bit_equal'][f]+=b[f][i]==a[f][i]
            acc['max_fraction_of_general'][f]=max(acc['max_fraction_of_general'][f],_frac(b[f][i],a[f][i],allow[f]))
            if f in BAW_GREEK_FIELDS:acc['need_sstar_k'][f]=max(acc['need_sstar_k'][f],max(0.0,d-allow[f])/K)
        fit=abs(b['vega'][i])*100.0*tol['fit_nu']+tol['fit_rel']*max(1.0,mid)
        acc['max_fraction_of_general']['fit']=max(acc['max_fraction_of_general']['fit'],abs(b['price'][i]-mid)/fit)

def _oracle_quote_rows(fx,params):
    """The BAW oracle set as quote rows: every fixture BAW edge row except the planted run-defect rows (with its own
    parameters), the item 7 stencil points quoted at their stored value, and the record's oracle grid (BAW_RECORD_GRID,
    case rates) quoted at py-reference's price where the engine prices the point. Returns [(name, params, row)] and counts."""
    from optionlab.params import CaseParams
    from optionlab.reference import price_function
    from optionlab.models import ModelDefect, RunDefect
    out=[];skipped=0;r,q=params.rate,params.dividend_yield
    for e in fx['oracle']['baw']:
        if e['kind']=='edge':
            if e['status']=='DEFECT':continue
            out.append((e['name'],CaseParams(**{**params.__dict__,**e.get('params',{})}),tuple(e['row'])))
        elif e['kind']=='stencil':
            out.append(('stencil',params,(e['side'],e['S'],e['K'],e['T'],e['value'],e['value'],e['r'],e['q'])))
    price=price_function('baw',params)
    for side,S,K,T,s in BAW_RECORD_GRID:
        try:v=price(side,S,K,T,r,q,s)
        except RunDefect:raise                                           # H19
        except ModelDefect:skipped+=1;continue
        out.append(('grid',params,(side,S,K,T,v,v,r,q)))
    return out,{'edge_and_stencil':sum(1 for n,_,_ in out if n!='grid'),'grid':sum(1 for n,_,_ in out if n=='grid'),'grid_engine_error':skipped}

def _sstar_oracle(fx,params,sstar_k):
    """Per BAW greek: the largest stored F7 S* term per unit K over the item 7 stencil points, and the margin of the
    proposed allowance under the item 7 bound at every point (bound / (general greek rule + sstar_k K))."""
    from optionlab import oracle, agreement
    tol=agreement.TOLERANCES;pts=[p for p in fx['oracle']['baw'] if p.get('kind')=='stencil'];out={}
    terms={g:max(p['greeks'][g]['sstar_term']/p['K'] for p in pts) for g in BAW_GREEK_FIELDS}
    margins={g:[] for g in BAW_GREEK_FIELDS}
    for p in pts:
        b=oracle.baw_item7_point(p,fx['calibration']['item7'],params);ref=p['greeks']
        for g in BAW_GREEK_FIELDS:
            nu=abs(ref['vega']['exact'])*100.0          # T7-05: tau_sigma of the point; a flat-vega point (no greek rule in agreement) uses iv_abs
            ts=agreement.tau_sigma(p['value'],nu) if nu>=tol['flat_vega'] else tol['iv_abs']
            allow=tol['greek_abs']+(tol['greek_rel']+ts/p['sigma'])*abs(ref[g]['exact'])+(sstar_k[g] or 0.0)*p['K']
            margins[g].append({'bound':b[g]['bound'],'allowance':allow,'sstar_term':ref[g]['sstar_term'],'ok':b[g]['ok']})
    for g in BAW_GREEK_FIELDS:
        m=margins[g];worst=max(m,key=lambda x:x['sstar_term'])
        out[g]={'points':len(m),'max_sstar_term_per_k':terms[g],'max_bound':max(x['bound'] for x in m),
                'min_margin_high':min(x['bound']/x['allowance'] for x in m),'margin_high_at_largest_term':worst['bound']/worst['allowance'],
                'points_allowance_above_bound':sum(1 for x in m if x['allowance']>x['bound']),'oracle_ok':sum(1 for x in m if x['ok'])}
    return out

def baw_spread_body(out_dir,chains=SPREAD_CHAINS):
    """G2.4 calibration evidence for the BAW agreement tolerances (Task 7; spec 3.7, Appendix G-BAW R12 F7). Every Python
    variant (py-optimized, py-library) runs `baw` on the fixed-seed synthetic chains; the
    direct variants also run every BAW oracle-set row with its own parameters. Against py-reference: the largest |delta|
    per field, the largest fraction of the section 3.7 rule at the general values, bit-equal counts, status and full-flag
    equality, agreement.compare at the general values (reported, not a gate) and the smallest sstar_k per greek that a
    greek difference beyond the general rule would need. The proposal (bench_tolerance style): per section 3.7 field the
    provisional value when the measured fraction is below 1 (never a widening); per greek sstar_k = SSTAR_MARGIN x the
    largest of the F7 term per unit K at the oracle stencil points and the measured need, rounded up to one significant
    digit, with its margins against the item 7 bound. PASS when every comparison ran, every status and bit 64 equal
    py-reference (G2.3) and no run defect occurred; the value spread itself never decides (N6: no BAW value gate before the lock)."""
    import time
    from optionlab import agreement, library, optimized as opt, reference
    from optionlab.contract import load_chain, rows as chain_rows
    from optionlab.synthetic import generate
    from optionlab.params import CASE, params_from_manifest
    manifest=json.loads(CASE_FILE.read_text());raw={k:v['value'] for k,v in manifest['parameters'].items()}
    if params_from_manifest(manifest)!=CASE:return {'status':'FAIL','reason':'case manifest parameters differ from CASE','files':[]}
    fx=json.loads(FIXTURES.read_text());M=('baw',);t0=time.perf_counter();seconds={}
    spread={f'{v}/{w}':_empty_spread() for v,w in SPREAD_VARIANTS};bit64_equal=True
    def add(key,rows,ref,got,p):
        nonlocal bit64_equal
        a,b=ref['models']['baw'],got['models']['baw']
        bit64_equal=bit64_equal and [(s,f&64) for s,f in zip(a['status'],a['flags'])]==[(s,f&64) for s,f in zip(b['status'],b['flags'])]
        _merge_spread(spread[key],rows,a,b,p,agreement.compare(rows,got,ref,p,models=M))
    chain_rows_list=[chain_rows(load_chain(generate(n,seed,CASE)),CASE) for seed,n in chains];seconds['generate']=time.perf_counter()-t0
    refs=[reference.run(rw,CASE,models=M) for rw in chain_rows_list];seconds['py-reference chains']=time.perf_counter()-t0
    for variant,workers in SPREAD_VARIANTS:
        key=f'{variant}/{workers}'
        if variant=='py-optimized':
            for rw,ref in zip(chain_rows_list,refs):add(key,rw,ref,opt.materialize(opt.run(_prep_rows(rw),CASE,models=M)),CASE)
        else:
            for rw,ref in zip(chain_rows_list,refs):add(key,rw,ref,library.run(rw,CASE,models=M),CASE)
        seconds[key+' chains']=time.perf_counter()-t0
    oracle_rows,oracle_counts=_oracle_quote_rows(fx,CASE);oracle_spread={f'{v}/1':_empty_spread() for v in SPREAD_DIRECT}
    groups={}
    for name,p,row in oracle_rows:groups.setdefault(p,[]).append(row)
    for p,rw in groups.items():
        ref=reference.run(rw,p,models=M)
        for variant in SPREAD_DIRECT:
            got=opt.materialize(opt.run(_prep_rows(rw),p,models=M)) if variant=='py-optimized' else library.run(rw,p,models=M)
            a,b=ref['models']['baw'],got['models']['baw']
            bit64_equal=bit64_equal and [(s,f&64) for s,f in zip(a['status'],a['flags'])]==[(s,f&64) for s,f in zip(b['status'],b['flags'])]
            _merge_spread(oracle_spread[f'{variant}/1'],rw,a,b,p,agreement.compare(rw,got,ref,p,models=M))
    seconds['oracle set']=time.perf_counter()-t0
    every=list(spread.values())+list(oracle_spread.values())
    frac={f:max(s['max_fraction_of_general'][f] for s in every) for f in BAW_ROW_FIELDS+('fit',)}
    need={g:max(s['need_sstar_k'][g] for s in every) for g in BAW_GREEK_FIELDS}
    f7=_sstar_oracle(fx,CASE,{g:None for g in BAW_GREEK_FIELDS})
    sstar_k={g:ceil_1sig(SSTAR_MARGIN*max(f7[g]['max_sstar_term_per_k'],need[g])) for g in BAW_GREEK_FIELDS}
    candidates={str(c):_sstar_oracle(fx,CASE,{g:ceil_1sig(c*max(f7[g]['max_sstar_term_per_k'],need[g])) or 0.0 for g in BAW_GREEK_FIELDS}) for c in SSTAR_CANDIDATES}
    candidates={c:{'sstar_k':{g:ceil_1sig(float(c)*max(f7[g]['max_sstar_term_per_k'],need[g])) or 0.0 for g in BAW_GREEK_FIELDS},'oracle':v} for c,v in candidates.items()}
    f7=_sstar_oracle(fx,CASE,sstar_k)
    tol=agreement.TOLERANCES;fields={}
    for key,basis in (('iv_abs','iv'),('iv_ulp_rel','iv'),('price_rel','price'),('fit_nu','fit'),('fit_rel','fit'),('greek_abs','greeks'),('greek_rel','greeks')):
        m=max(frac[g] for g in BAW_GREEK_FIELDS) if basis=='greeks' else frac[basis]
        fields[key]={'basis':basis,'measured_fraction':m,'current':tol[key],'proposed':tol[key] if m<1.0 else None,
                     'margin_low':(1.0/m if m>0 else None),'reason':None if m<1.0 else 'the measured spread exceeds the general rule; a widening is never proposed automatically'}
    fields['flat_vega']={'basis':'threshold','current':tol['flat_vega'],'proposed':tol['flat_vega'],'reason':'a classification threshold, not a spread'}
    for g in BAW_GREEK_FIELDS:
        fields[f'sstar_k.{g}']={'basis':'F7 S* term','f7_max_term_per_k':f7[g]['max_sstar_term_per_k'],'measured_need_per_k':need[g],'proposed':sstar_k[g],
                                 'margin_low':sstar_k[g]/max(f7[g]['max_sstar_term_per_k'],need[g]) if sstar_k[g] else None,
                                 'oracle_max_bound':f7[g]['max_bound'],'min_margin_high':f7[g]['min_margin_high'],
                                 'margin_high_at_largest_term':f7[g]['margin_high_at_largest_term'],'points_allowance_above_bound':f7[g]['points_allowance_above_bound']}
    doc={'label':'G2.4 calibration evidence (Task 7); measurement only, never a gate before the approver lock','chains':[list(c) for c in chains],
         'variants':[f'{v}/{w}' for v,w in SPREAD_VARIANTS],'chain_spread':spread,'oracle_counts':oracle_counts,'oracle_spread':oracle_spread,
         'max_fraction_of_general':frac,'need_sstar_k':need,'f7':f7,'sstar_candidates':candidates,'proposal':{'state':'provisional-g-baw2','sstar_margin':SSTAR_MARGIN,'fields':fields},
         'seconds_informational':seconds}
    with open(Path(out_dir)/'baw-spread.json','w') as f:json.dump(doc,f,separators=(',',':'),allow_nan=False)
    ran=all(s['rows']>0 for s in every) and oracle_counts['grid']>0
    ok=ran and bit64_equal
    return {'status':'PASS' if ok else 'FAIL','label':'calibration evidence','files':['baw-spread.json'],
            'counts':{'chain_rows':sum(n for _,n in chains),'oracle_rows':len(oracle_rows),'variants':len(SPREAD_VARIANTS),'bit64_equal':int(bit64_equal)}}

@check('baw-spread')
def baw_spread(out_dir,args):
    """G2.4 (Task 7): the BAW variant spread and the tolerance proposal; see baw_spread_body. Not a gate (before_run false)."""
    if _no_arguments(args):return _no_arguments(args)
    return baw_spread_body(out_dir)

# ---- G-ALO2 part B (Task A5; Amendment I4.2, I9.4): the alo-overrun stub check and the ALO variant spread (no gate) ----
@check('alo-overrun-stub')
def alo_overrun_stub(out_dir,args):
    """Test-only (I9.4; `before_run: false`): one py-library call of selector `alo` on a one-row synthetic chain (the case
    seed). Without the stub it passes. With SAFE_C_TEST_STUB=alo-overrun (passed by the coordinator only to a selftest plan)
    the py-library ALO path blocks; the coordinator's call deadline kills the check child: FAIL with reason alo-overrun
    (tools/bench_deadline.alo_overrun_check_selftest). No timer runs in this process."""
    if _no_arguments(args):return _no_arguments(args)
    import tempfile
    from benchlab.workload import load_case_adapter
    case=json.loads(CASE_FILE.read_text());a=load_case_adapter(case,selector='alo')
    data=a.synthesize(1,int(case['parameters']['seed']['value']));p=Path(tempfile.mkdtemp())/'chain.json';p.write_bytes(data)
    chain=a.load({'path':str(p),'sha256':hashlib.sha256(data).hexdigest()})
    res=a.materialize(a.run(a.prepare(chain,'py-library',1),'py-library',1))
    return {'status':'PASS' if a.work_units(res)==1 else 'FAIL','files':[],'counts':{'rows':1}}

ALO_SPREAD_CHAINS=((ALIGN_SEED,256),)      # the first 256 rows of the synthetic large chain (the I4.2 sample)
ALO_SPREAD_SIGMAS=(0.01,0.1,0.3,1.0,2.5)   # Task A6: the record grid sigmas of the oracle-set rows (half of ALO_RECORD_SIGMA: the 600 s check limit)
ALO_RECORD_GRID=[(side,100.0*sk,100.0,T,s) for side in (0,1) for sk in ALO_RECORD_SK for T in ALO_RECORD_T for s in ALO_RECORD_SIGMA]

def alo_switch_quote_rows(params):
    """The 28 record R4 switch vectors (alo_switch_vectors) as quote rows: S = K = 100, sigma 0.3, bid = ask = the
    py-reference price (a call vector carries the exchanged rates)."""
    from optionlab import alo
    out=[]
    for v in alo_switch_vectors(params):
        p=alo.price(v['side'],100.0,100.0,v['T'],v['r'],v['q'],0.3,params);out.append((v['side'],100.0,100.0,v['T'],p,p,v['r'],v['q']))
    return out

def alo_oracle_quote_rows(fx,params,sigmas=ALO_SPREAD_SIGMAS,edges=True,item7_points=None,grid_limit=None):
    """Task A6 (I4.3: calibrated on the synthetic chain and the oracle set): the ALO oracle set as quote rows. Every fixture
    ALO edge row except the planted run-defect rows (its row carries its own r and q), the item 7 points
    (oracle.alo_item7_points, the first `item7_points`) quoted at the py-reference price, and the record's oracle grid
    (ALO_RECORD_GRID at the `sigmas`, sigma >= sigma_lo(ALO, row), case rates, the first `grid_limit`) quoted at the
    py-reference price. Returns ([(kind, row)], counts)."""
    from optionlab import alo, oracle
    from optionlab.models import sigma_lo
    out=[];r,q=params.rate,params.dividend_yield
    if edges:out+=[('edge',tuple(e['row'])) for e in fx['oracle']['alo'] if e['kind']=='edge' and e['status']!='DEFECT' and not e.get('params')]
    for side,S,K,T,rr,qq,s in oracle.alo_item7_points(params)[:item7_points]:
        v=alo.price(side,S,K,T,rr,qq,s,params);out.append(('item7',(side,S,K,T,v,v,rr,qq)))
    grid=[g for g in ALO_RECORD_GRID if g[4] in sigmas and g[4]>=sigma_lo('alo',g[0],g[3],r,q,params)][:grid_limit]
    for side,S,K,T,s in grid:
        v=alo.price(side,S,K,T,r,q,s,params);out.append(('grid',(side,S,K,T,v,v,r,q)))
    return out,{k:sum(1 for n,_ in out if n==k) for k in ('edge','item7','grid')}

def alo_item7_margins(params,points=None):
    """Per greek, the margin of the section 3.7 greek allowance at the general values (greek_abs + (greek_rel +
    tau_sigma/sigma) |greek|, py-reference's price and vega) below the E-ALO-6 item 7 tolerance (the oracle error) at every
    item 7 point: the smallest tol/allowance (all terms and resolved terms only) and the count of points whose allowance is
    above tol. Evidence for the approver; it decides nothing."""
    from optionlab import agreement, oracle
    from optionlab.reference import price_and_greeks
    tol=agreement.TOLERANCES;pts=oracle.alo_item7_points(params)[:points];out={g:[] for g in oracle.ALO_GREEKS}
    for p in pts:
        side,S,K,T,r,q,s=p;g=price_and_greeks('alo',side,S,K,T,r,q,s,params)
        res=oracle.alo_item7_point(p,params,variant=g);nu=abs(g['vega'])*100.0
        ts=agreement.tau_sigma(g['price'],nu) if nu>=tol['flat_vega'] else tol['iv_abs']
        for name,v in res.items():
            allow=tol['greek_abs']+(tol['greek_rel']+ts/s)*abs(g[name])
            out[name].append({'tol':v['tol'],'allowance':allow,'resolved':v['resolved']})
    def summary(m):
        res=[x for x in m if x['resolved'] and math.isfinite(x['tol'])]
        return {'points':len(m),'min_tol_over_allowance':min((x['tol']/x['allowance'] for x in m if math.isfinite(x['tol'])),default=None),
                'min_tol_over_allowance_resolved':min((x['tol']/x['allowance'] for x in res),default=None),
                'points_allowance_above_tol':sum(1 for x in m if x['allowance']>x['tol']),'resolved':len(res)}
    return {g:summary(m) for g,m in out.items()}

def alo_spread_body(out_dir,chains=ALO_SPREAD_CHAINS,switch=True,oracle_sigmas=ALO_SPREAD_SIGMAS,oracle_edges=True,item7_points=None,oracle_grid_limit=None):
    """G-ALO2 part B evidence (Task A5; Amendment I4.2) and the Task A6 tolerance proposal (I4.3). Every Python variant
    (py-optimized, py-library) runs `alo` on the fixed-seed synthetic chain rows (and, with
    `switch`, the 28 switch vectors) against py-reference: per variant status_equal, flags_equal (the full flag byte),
    bits_16_32_equal, bit-equal counts per field, the largest |delta|, the fraction of the section 3.7 rule at the general
    (provisional) values and agreement.compare at those values (reported, never a gate: N6, no ALO tolerance before the
    Task A6 lock), and the adaptive-path divergence of py-optimized (optimized.alo_divergence; test-only instrumentation
    outside timing; QuantLib exposes no counts). Task A6: the direct variants also run the ALO oracle set
    (alo_oracle_quote_rows) against py-reference, and the proposal (the bench_tolerance and baw-spread style) gives per
    section 3.7 field the general value when the largest measured fraction (chain and oracle set) is below 1 (never a
    widening: a fraction >= 1 proposes nothing and names the reason), its margin, and per greek the item 7 margins
    (alo_item7_margins). PASS when every comparison ran, every status and bits 16/32 equal py-reference (the I4.2
    identity) and no run defect occurred. `ruling_needed` is true when a divergent evaluation exists and a py-optimized
    field exceeds the general rule (I4.2: such a divergence stops G-ALO2 for a ruling; no tolerance widens to admit it).
    The oracle arguments shorten the oracle set for tests only."""
    import time
    from optionlab import agreement, library, optimized as opt, reference
    from optionlab.contract import load_chain, rows as chain_rows
    from optionlab.synthetic import generate
    from optionlab.params import CASE, params_from_manifest
    manifest=json.loads(CASE_FILE.read_text());raw={k:v['value'] for k,v in manifest['parameters'].items()}
    if params_from_manifest(manifest)!=CASE:return {'status':'FAIL','reason':'case manifest parameters differ from CASE','files':[]}
    M=('alo',);t0=time.perf_counter();seconds={}
    spread={f'{v}/{w}':dict(_empty_spread(),bits_16_32_equal=0) for v,w in SPREAD_VARIANTS};identity=True
    sets=[chain_rows(load_chain(generate(n,seed,CASE)),CASE) for seed,n in chains]+([alo_switch_quote_rows(CASE)] if switch else [])
    refs=[reference.run(rw,CASE,models=M) for rw in sets];seconds['py-reference']=time.perf_counter()-t0
    def add(acc,rows,ref,got):
        nonlocal identity
        a,b=ref['models']['alo'],got['models']['alo']
        eq=[(s,f&48) for s,f in zip(a['status'],a['flags'])]==[(s,f&48) for s,f in zip(b['status'],b['flags'])];identity=identity and eq
        acc['bits_16_32_equal']+=sum(1 for x,y in zip(a['flags'],b['flags']) if x&48==y&48)
        _merge_spread(acc,rows,a,b,CASE,agreement.compare(rows,got,ref,CASE,models=M))
    for variant,workers in SPREAD_VARIANTS:
        key=f'{variant}/{workers}'
        if variant=='py-optimized':
            for rw,ref in zip(sets,refs):add(spread[key],rw,ref,opt.materialize(opt.run(_prep_rows(rw),CASE,models=M)))
        else:
            for rw,ref in zip(sets,refs):add(spread[key],rw,ref,library.run(rw,CASE,models=M))
        seconds[key]=time.perf_counter()-t0
    fx=json.loads(FIXTURES.read_text())
    orows,ocounts=alo_oracle_quote_rows(fx,CASE,sigmas=oracle_sigmas,edges=oracle_edges,item7_points=item7_points,grid_limit=oracle_grid_limit)
    oracle_spread={f'{v}/1':dict(_empty_spread(),bits_16_32_equal=0) for v in SPREAD_DIRECT}
    rw=[row for _,row in orows]
    if rw:
        oref=reference.run(rw,CASE,models=M)
        add(oracle_spread['py-optimized/1'],rw,oref,opt.materialize(opt.run(_prep_rows(rw),CASE,models=M)))
        add(oracle_spread['py-library/1'],rw,oref,library.run(rw,CASE,models=M))
    seconds['oracle set']=time.perf_counter()-t0
    margins=alo_item7_margins(CASE,item7_points);seconds['item7 margins']=time.perf_counter()-t0
    div=opt.alo_divergence([r for rw_ in sets for r in rw_],CASE);seconds['divergence']=time.perf_counter()-t0
    worst=max(spread['py-optimized/1']['max_fraction_of_general'].values())
    every=list(spread.values())+[s for s in oracle_spread.values() if s['rows']]
    frac={f:max(s['max_fraction_of_general'][f] for s in every) for f in BAW_ROW_FIELDS+('fit',)}
    tol=agreement.TOLERANCES;fields={}
    for key,basis in (('iv_abs','iv'),('iv_ulp_rel','iv'),('price_rel','price'),('fit_nu','fit'),('fit_rel','fit'),('greek_abs','greeks'),('greek_rel','greeks')):
        m=max(frac[g] for g in BAW_GREEK_FIELDS) if basis=='greeks' else frac[basis]
        fields[key]={'basis':basis,'measured_fraction':m,'current':tol[key],'proposed':tol[key] if m<1.0 else None,
                     'margin_low':(1.0/m if m>0 else None),'reason':None if m<1.0 else 'the measured spread exceeds the general rule; a widening is never proposed automatically'}
    fields['flat_vega']={'basis':'threshold','current':tol['flat_vega'],'proposed':tol['flat_vega'],'reason':'a classification threshold, not a spread'}
    doc={'label':'G-ALO2 part B spread (Task A5); measurement only, never a gate before the Task A6 lock (N6); Task A6 adds the oracle set and the tolerance proposal',
         'chains':[list(c) for c in chains],'switch_vectors':28 if switch else 0,'variants':[f'{v}/{w}' for v,w in SPREAD_VARIANTS],'chain_spread':spread,
         'oracle_counts':ocounts,'oracle_spread':oracle_spread,'max_fraction_of_general':frac,'divergence':div,
         'divergence_note':'py-optimized only; py-library runs QuantLib, which exposes no Halley, fallback or tanh-sinh counts',
         'ruling_needed':bool(div['any'] and worst>=1.0),'py_optimized_max_fraction_of_general':worst,
         'proposal':{'state':'provisional-g-alo2','fields':fields,'item7_margins':margins,
                     'basis':'section 3.7: each locked value above the measured variant spread and below the oracle error; no tolerance of another model changes'},
         'seconds_informational':seconds}
    with open(Path(out_dir)/'alo-spread.json','w') as f:json.dump(doc,f,separators=(',',':'),allow_nan=False)
    ran=all(s['rows']>0 for s in spread.values()) and (not orows or all(s['rows']>0 for s in oracle_spread.values()))
    ok=ran and identity
    return {'status':'PASS' if ok else 'FAIL','label':'measurement evidence','files':['alo-spread.json'],
            'counts':{'rows':sum(len(rw_) for rw_ in sets),'oracle_rows':len(orows),'variants':len(SPREAD_VARIANTS),'identity':int(identity),
                      'divergent_evaluations':div['any'],'evaluations':div['evaluations'],'ruling_needed':int(doc['ruling_needed'])}}

@check('alo-spread')
def alo_spread(out_dir,args):
    """G-ALO2 part B (Task A5): the ALO variant spread, flags and divergence; see alo_spread_body. Not a gate (before_run false)."""
    if _no_arguments(args):return _no_arguments(args)
    return alo_spread_body(out_dir)

# ---- G2.4 (Task A1, base Task 7 Step 5): BAW value agreement at the locked tolerances (before-run gate) ----
POLICY=Path('/src/safety/performance-policy.json')   # the framework policy: the envelope only; tolerances come from the protocol (EX-3)
BAW_LOCK_STATE='locked-g-baw2'      # approval artifacts/approvals/perf-lab-t7-baw-lock (Proposal B: sstar_k = 0)
BAW_AGREEMENT_VARIANTS=(('py-optimized','direct'),('py-library','direct'))

def _baw_tolerances():
    """The `tolerances.baw` block of the protocol (protocol/protocol.json, EX-3)."""
    from optionlab import protocol
    return protocol.tolerances()['baw']

def _baw_fractions(rows,a,b,tol):
    """Largest |variant - py-reference| / allowance per field at `tol` (the section 3.7 rules; the fit rule on the variant
    price), over the rows where both sides are OK with finite values and the reference row is neither boundary_ambiguous
    nor flat_vega. Evidence only: agreement.compare decides."""
    from optionlab import agreement, reference
    w={f:0.0 for f in BAW_ROW_FIELDS+('fit',)};k=0
    for i,row in enumerate(rows):
        if a['status'][i]!='OK' or b['status'][i]!='OK' or a['flags'][i]&(reference.FLAG_BOUNDARY_AMBIGUOUS|reference.FLAG_FLAT_VEGA):continue
        if not all(math.isfinite(c[f][i]) for c in (a,b) for f in BAW_ROW_FIELDS):continue
        nu=a['vega'][i]*100.0
        if nu<tol['flat_vega']:continue
        k+=1;ts=agreement.tau_sigma(a['price'][i],nu,tol);pr=a['price'][i];mid=(row[4]+row[5])/2.0
        allow={'iv':ts,'price':nu*ts+tol['price_rel']*max(1.0,abs(pr))}
        for g in BAW_GREEK_FIELDS:allow[g]=tol['greek_abs']+(tol['greek_rel']+ts/a['iv'][i])*abs(a[g][i])
        for f in BAW_ROW_FIELDS:w[f]=max(w[f],_frac(b[f][i],a[f][i],allow[f]))
        w['fit']=max(w['fit'],abs(b['price'][i]-mid)/(abs(b['vega'][i])*100.0*tol['fit_nu']+tol['fit_rel']*max(1.0,mid)))
    return k,w

def _baw_refusal(reason,state):
    return {'status':'FAIL','reason':reason,'label':reason,'tolerance_state':state,'rows':[],'files':[]}

def _tolerance_block(model):
    """The `tolerances.<model>` block of the protocol (protocol/protocol.json, EX-3), or None."""
    from optionlab import protocol
    t=protocol.tolerances().get(model)
    return t if isinstance(t,dict) else None

# Per-model settings of the locked value agreement (G2.4 for baw, Task A1; I4.3 for alo, Task A6). The block function is
# looked up at call time, so a test can patch _baw_tolerances or _tolerance_block.
AGREEMENT_SPECS={
    'baw':{'block':lambda:_baw_tolerances(),'lock':'locked-g-baw2','flag_mask':64,'flag_key':'bit64_equal','edge_key':'baw_edge_row',
           'label':'G2.4 BAW value agreement at the locked tolerances (Task A1)','file':'baw-agreement.json','variants':'BAW_AGREEMENT_VARIANTS'},
    'alo':{'block':lambda:_tolerance_block('alo'),'lock':'locked-g-alo2','flag_mask':48,'flag_key':'bits_16_32_equal','edge_key':'alo_edge_row',
           'label':'I4.3 ALO value agreement at the locked tolerances (Task A6)','file':'alo-agreement.json','variants':'ALO_AGREEMENT_VARIANTS'}}

def _locked_agreement_body(model,out_dir,chains,edge_names):
    """The value agreement of one model at its locked tolerance block (the Task A1 pattern): refused (FAIL
    'tolerances.<model> not locked') unless the block has its lock state; the block must hold every section 3.7 key (baw:
    and sstar_k 0 for every greek, Proposal B). Inputs: the synthetic chains of `chains` ((seed, rows), case parameters)
    and each oracle edge row under its own parameters as a one-row input: the general edge rows and the model's edge rows
    (fixture part `<model>`, kind `edge`, the planted run-defect rows excluded); `edge_names` (None: all) selects by name.
    Each variant of the model's variant table against py-reference through agreement.compare at the locked tolerances;
    the status column and the model's identity flag bits (baw: 64; alo: 16 and 32, I4.2) must equal py-reference on every
    row (the full flag byte is reported as `flags_equal`, a count). Single-threaded variants only (owner 2026-10-16).
    <model>-agreement.json holds one row per (input, variant)."""
    spec=AGREEMENT_SPECS[model];variants=globals()[spec['variants']]
    t=spec['block']();state=t.get('state') if isinstance(t,dict) else None
    if state!=spec['lock']:return _baw_refusal(f'tolerances.{model} not locked',state)
    from optionlab import agreement, library, optimized as opt
    from optionlab.contract import load_chain, rows as chain_rows
    from optionlab.reference import run as ref_run
    from optionlab.synthetic import generate
    from optionlab.params import CASE, CaseParams, params_from_manifest
    sk=t.get('sstar_k')
    if model=='baw':
        if any(k not in t for k in agreement.TOLERANCES) or not isinstance(sk,dict) or set(sk)!=set(BAW_GREEK_FIELDS):
            return _baw_refusal('tolerances.baw incomplete',state)
        if any(v!=0 for v in sk.values()):return _baw_refusal('tolerances.baw sstar_k nonzero: no S* comparator',state)
    elif any(k not in t for k in agreement.TOLERANCES) or sk is not None:return _baw_refusal(f'tolerances.{model} incomplete',state)
    tol={k:float(t[k]) for k in agreement.TOLERANCES};M=(model,);mask=spec['flag_mask']
    manifest=json.loads(CASE_FILE.read_text());base={k:v['value'] for k,v in manifest['parameters'].items()}
    if params_from_manifest(manifest)!=CASE:return _baw_refusal('case manifest parameters differ from CASE',state)
    inputs=[]              # (key, value, params, adapter parameters, rows)
    for seed,n in chains:inputs.append(('seed',seed,CASE,base,chain_rows(load_chain(generate(n,seed,CASE)),CASE)))
    fx=json.loads(FIXTURES.read_text())['oracle']
    edges=[('edge_row',e) for e in fx['edge_rows']]+[(spec['edge_key'],e) for e in fx[model] if e['kind']=='edge' and e['status']!='DEFECT']
    for key,e in edges:
        if edge_names is not None and e['name'] not in edge_names:continue
        extra=e.get('params',{});p=CaseParams(**{**CASE.__dict__,**extra});raw={**base,**extra}
        if params_from_manifest({'parameters':{k:{'value':v} for k,v in raw.items()}})!=p:
            return _baw_refusal('edge row parameters do not map to the adapter',state)
        inputs.append((key,e['name'],p,raw,[tuple(e['row'])]))
    if edge_names is not None and len(inputs)-len(chains)!=len(set(edge_names)):return _baw_refusal('unknown edge row name',state)
    table={}
    for i,(key,value,p,raw,rw) in enumerate(inputs):
        ra_full=ref_run(rw,p,models=M);direct=opt.run(_prep_rows(rw),p,models=M);ra=ra_full['models'][model]
        for variant,workers in variants:
            got=opt.materialize(direct) if variant=='py-optimized' else library.run(rw,p,models=M);gb=got['models'][model]
            v=agreement.compare(rw,got,ra_full,p,tol=tol,models=M)
            same=gb['status']==ra['status'];ident=[f&mask for f in gb['flags']]==[f&mask for f in ra['flags']]
            compared,frac=_baw_fractions(rw,ra,gb,tol)
            row={key:value,'rows':len(rw),'variant':variant,'workers':workers,'compare_eligible':v['eligible'],'failures':v['failures'],
                 'reduction':v['reduction'],'status_equal':same,spec['flag_key']:ident,'flags_equal':sum(x==y for x,y in zip(gb['flags'],ra['flags'])),
                 'compared_ok_rows':compared,'max_fraction_of_tolerance':frac}
            row['eligible']=bool(v['eligible'] and same and ident);table[i,variant,workers]=row
    out=[table[i,variant,workers] for i in range(len(inputs)) for variant,workers in variants]
    worst={f:max([r['max_fraction_of_tolerance'][f] for r in out] or [0.0]) for f in BAW_ROW_FIELDS+('fit',)}
    doc={'label':spec['label'],'tolerance_state':state,'approval':t.get('approval'),'tolerances':tol,
         **({'sstar_k':sk} if model=='baw' else {}),'chains':[list(c) for c in chains],'variants':[f'{v}/{w}' for v,w in variants],
         'max_fraction_of_tolerance':worst,'rows':out}
    with open(Path(out_dir)/spec['file'],'w') as f:json.dump(doc,f,separators=(',',':'),allow_nan=False)
    eligible=sum(1 for r in out if r['eligible'])
    status='PASS' if out and eligible==len(out) else 'FAIL'
    return {'status':status,'tolerance_state':state,'rows':out,'files':[spec['file']],'label':f'tolerances.{model} '+state,
            'counts':{'rows':len(out),'eligible':eligible,'status_equal':sum(r['status_equal'] for r in out),spec['flag_key']:sum(r[spec['flag_key']] for r in out),
                      'chains':len(chains),'edge_rows':sum(1 for x in inputs if x[0]=='edge_row'),spec['edge_key']+'s':sum(1 for x in inputs if x[0]==spec['edge_key']),
                      'variants':len(variants)}}

def baw_agreement_body(out_dir,chains=AGREEMENT_CHAINS,edge_names=None):
    """G2.4 BAW value agreement (base Task 7 Step 5; Task A1): _locked_agreement_body for `baw` (state locked-g-baw2,
    sstar_k 0 for every greek; status and flag bit 64 equal to py-reference; baw-agreement.json)."""
    return _locked_agreement_body('baw',out_dir,chains,edge_names)

ALO_LOCK_STATE='locked-g-alo2'      # set by the approver's lock follow-up of Task A6 (I4.3; N6: no ALO value gate before it)
ALO_AGREEMENT_VARIANTS=BAW_AGREEMENT_VARIANTS

def alo_agreement_body(out_dir,chains=AGREEMENT_CHAINS,edge_names=None):
    """I4.3 ALO value agreement (Task A6, the Task A1 pattern): _locked_agreement_body for `alo` (refused with FAIL
    'tolerances.alo not locked' before the approver lock; the block holds the section 3.7 keys and no sstar_k; status
    and flag bits 16 and 32 equal to py-reference, I4.2; alo-agreement.json)."""
    return _locked_agreement_body('alo',out_dir,chains,edge_names)

@check('baw-agreement')
def baw_agreement(out_dir,args):
    """G2.4 before-run gate (Task A1): the BAW value agreement of every Python variant with py-reference at the locked
    `tolerances.baw`; see baw_agreement_body. The per-row table stays in baw-agreement.json (the stdout row is bounded)."""
    if _no_arguments(args):return _no_arguments(args)
    return {k:v for k,v in baw_agreement_body(out_dir).items() if k!='rows'}

@check('alo-agreement')
def alo_agreement(out_dir,args):
    """I4.3 before-run gate (Task A6 lock follow-up): the ALO value agreement of every Python variant with py-reference at
    the locked `tolerances.alo` (state locked-g-alo2, approval perf-lab-alo-panel, H23) on the AGREEMENT_CHAINS inputs;
    see alo_agreement_body. The edge-row inputs run in alo-agreement-edges: one job over both input sets takes about
    610 s, above the 600 s check limit (chains 313 s, edges 295 s measured), so the gate is two declared before-run
    checks that together hold every input of alo_agreement_body. The per-row table stays in alo-agreement.json."""
    if _no_arguments(args):return _no_arguments(args)
    return {k:v for k,v in alo_agreement_body(out_dir,chains=AGREEMENT_CHAINS,edge_names=()).items() if k!='rows'}

@check('alo-agreement-edges')
def alo_agreement_edges(out_dir,args):
    """I4.3 before-run gate, second part (Task A6 lock follow-up): the ALO value agreement on every general and ALO
    oracle edge row under its own parameters (no chain); see alo_agreement."""
    if _no_arguments(args):return _no_arguments(args)
    return {k:v for k,v in alo_agreement_body(out_dir,chains=(),edge_names=None).items() if k!='rows'}

# ---- H21.7 (Task A6): the panel pre-flight check (outside timing, under the call deadline; never a panel reference) ----
PANEL_FILE=CASE_FILE.parent/'option-chain-greeks.panel.json'
PREFLIGHT_FILE='panel-preflight.json'
FLAG_ROUNDING_BAND_BIT=8

def preflight_variants(manifest=None,policy=None):
    """The rows that the case manifest and the policy plan for the single-record unit points (G6.3, H21.7): every
    implemented variant with each declared worker count, warm; a worker count above the policy envelope's CPUs is
    envelope-blocked and not planned (G6.3). Variants that are not implemented are listed in `not_implemented`. An
    implemented C variant (EX-10: c-serial) is listed in `native`: this Python check has no restored binaries, so the
    native check native-routes (optionlab.native_check, item panel) runs the six panel rows of every model on each route of
    the C row against the same stored statuses."""
    manifest=manifest or json.loads(CASE_FILE.read_text());policy=policy or json.loads(POLICY.read_text())
    cpus=policy['envelope']['cpus'];run=[];blocked=[];missing=[];native=[]
    for v in manifest['variants']:
        if v['status']!='implemented':missing.append(v['id']);continue
        if v['language']=='c':native.append(v['id']);continue
        for w in v['workers']:
            (run if w=='direct' or w<=cpus else blocked).append((v['id'],w))
    return {'run':run,'envelope_blocked':blocked,'not_implemented':missing,'native':native}

def _panel_rows(indices,seed):
    """The py-reference row tuples of the synthetic large chain rows `indices` (synthetic.row is prefix-stable)."""
    from optionlab import synthetic
    from optionlab.contract import load_chain, rows as chain_rows, with_rates
    from optionlab.params import CASE
    recs=[synthetic.row(j,seed,CASE) for j in indices]
    chain=with_rates(load_chain({'s':'ok',**{k:[r[k] for r in recs] for k in synthetic.KEYS}}),CASE.rate,CASE.dividend_yield)
    return chain_rows(chain)

def _preflight_runner(seed):
    """The real variant runner of the pre-flight check: runner(variant, workers, model, indices) -> [(status, flags)] of the
    regenerated panel rows, through the same paths as a unit trial (py-reference, py-optimized and py-library direct)."""
    from optionlab import library, optimized as opt, reference
    from optionlab.params import CASE
    def run(variant,workers,model,indices):
        rws=_panel_rows(indices,seed);M=(model,)
        if variant=='py-reference':res=reference.run(rws,CASE,models=M)
        elif variant=='py-optimized':res=opt.materialize(opt.run(_prep_rows(rws),CASE,models=M))
        elif variant=='py-library':res=library.run(rws,CASE,models=M)
        else:raise ValueError('unknown variant')
        col=res['models'][model];return list(zip(col['status'],col['flags']))
    return run

def panel_preflight_body(out_dir,runner=None,panel_doc=None):
    """H21.7: every planned single-record variant (preflight_variants) runs on the six panel rows for each model; each
    status is compared with py-reference's stored status of the panel reference. Any difference (an Amendment D
    rounding-band difference included) adds the row to R; the selection is computed again by the one rule of H21.5
    (optionlab.panel.selection, in cell order) and the check repeats for every changed row until all six rows pass. A
    difference of py-reference itself means a stale reference: FAIL. A cell without a passing row: FAIL panel-cell-empty.
    panel-preflight.json records every replacement (cell, old index, variant, workers, model, both statuses, band
    difference yes or no, agreement finding for a non-band difference, new index and its level) and the carried
    rejections of the reference; the check writes no panel reference (a replacement needs `bench panel --rejected-from`
    and a new case version through approval). `runner` (test-only injection) replaces the real variant runner."""
    from optionlab import panel
    from optionlab.contract import MODELS5
    doc=panel_doc if panel_doc is not None else json.loads(PANEL_FILE.read_text())
    plan=preflight_variants();per=doc['per_model']
    carried=[{'cell':k,**e} for k,c in enumerate(doc['cells']) for e in c['rejected']]
    R={e['row'] for e in carried}
    def fail(reason,**extra):
        rec={'label':'panel pre-flight (H21.7)','status':'FAIL','reason':reason,'panel_sha256':doc['sha256'],**extra}
        with open(Path(out_dir)/PREFLIGHT_FILE,'w') as f:json.dump(rec,f,separators=(',',':'),allow_nan=False)
        return {'status':'FAIL','reason':reason,'files':[PREFLIGHT_FILE],'counts':{k:v for k,v in extra.items() if isinstance(v,int)}}
    try:sel=panel.selection(doc,R)
    except panel.PanelCellEmpty as exc:return fail('panel-cell-empty',cell=exc.args[0])
    if sel['indices']!=doc['indices']:return fail('the stored panel indices differ from the one selection rule')
    runner=runner or _preflight_runner(doc['seed'])
    replacements=[];passed=set();runs=0;before=list(sel['indices'])
    while True:
        todo=[i for i in sel['indices'] if i not in passed]
        if not todo:break
        diffs={}
        for model in MODELS5:
            for variant,workers in plan['run']:
                got=runner(variant,workers,model,todo);runs+=1
                for i,(st,fl) in zip(todo,got):
                    rs,rf=per[model]['status'][i],per[model]['flags'][i]
                    if st==rs:continue
                    if variant=='py-reference':return fail('py-reference differs from the stored panel reference',row=i)
                    band={st,rs}=={'OK','MODEL_DOMAIN'} and bool((fl|rf)&FLAG_ROUNDING_BAND_BIT)
                    diffs.setdefault(i,[]).append({'variant':variant,'workers':workers,'model':model,'status':st,'reference_status':rs,'band_difference':band})
        passed|={i for i in todo if i not in diffs}
        if not diffs:continue
        R|=set(diffs)
        try:new=panel.selection(doc,R)
        except panel.PanelCellEmpty as exc:return fail('panel-cell-empty',cell=exc.args[0],replacements=len(replacements))
        for i in sorted(diffs,key=sel['indices'].index):
            k=sel['indices'].index(i)
            for d in diffs[i]:
                replacements.append({'cell':k,'cell_name':panel.cell_names()[k],'old_index':i,**d,'agreement_finding':not d['band_difference'],
                                     'new_index':new['indices'][k],'level':new['cells'][k]['selected']['level']})
        sel=new
    rec={'label':'panel pre-flight (H21.7); a replacement needs bench panel --rejected-from and a new case version','status':'PASS',
         'schema_version':1,'panel_sha256':doc['sha256'],'variants':[[v,w] for v,w in plan['run']],'envelope_blocked':[[v,w] for v,w in plan['envelope_blocked']],
         'not_implemented':plan['not_implemented'],'native':plan['native'],'models':list(MODELS5),'carried':carried,'replacements':replacements,
         'indices_before':before,'indices_after':sel['indices'],'levels_after':[c['selected']['level'] for c in sel['cells']],
         'passed_rows':sorted(passed),'variant_runs':runs}
    with open(Path(out_dir)/PREFLIGHT_FILE,'w') as f:json.dump(rec,f,separators=(',',':'),allow_nan=False)
    return {'status':'PASS','label':'panel pre-flight','files':[PREFLIGHT_FILE],
            'counts':{'replacements':len(replacements),'agreement_findings':sum(1 for r in replacements if r['agreement_finding']),
                      'variant_runs':runs,'variants':len(plan['run']),'not_implemented':len(plan['not_implemented'])}}

@check('panel-preflight')
def panel_preflight(out_dir,args):
    """H21.7 (Task A6): the panel pre-flight check; see panel_preflight_body. Not a gate before every run (before_run
    false): it runs once before the smoke calibration and the window plan (H15.5)."""
    if _no_arguments(args):return _no_arguments(args)
    return panel_preflight_body(out_dir)

# ---- I4.5 (Task A6): ALO model-accuracy metrics (documented metrics, never gates) ----
ALO_MAPPING_DAYS=(1,7,30,91,365,730,1095)               # record R11 (a)
ALO_MAPPING_SIGMAS=(0.05,0.1,0.3,1.0,2.5)
ALO_ACCURACY_CHAIN_ROWS=256
HIGH_PRECISION={'scheme':'QdFpTanhSinhIterationScheme','m':10,'n':30,'eps':1e-10,'fp_equation':'Auto'}   # qdfpamericanengine.cpp:423-427

def _stats(xs):
    from optionlab.numeric import median, quantile
    return {'count':len(xs),'median':median(xs),'p90':quantile(xs,0.9),'max':max(xs)}

def _banded(pairs):
    """{'all', 'bands'} statistics of (band key, value) pairs per SIGMA_BANDS x T_BANDS."""
    groups={}
    for k,v in pairs:groups.setdefault(k,[]).append(v)
    xs=[v for _,v in pairs]
    return {'all':_stats(xs) if xs else None,'bands':{k:_stats(v) for k,v in sorted(groups.items())}}

def ql_alo_npv_scheme(side,S,K,T,r,q,sigma,scheme):
    """QuantLib QdFpAmericanEngine NPV on the mapped problem with the named iteration scheme ('accurate' or 'high') and Auto."""
    import QuantLib as ql
    from optionlab.library import _Problem
    pb=_Problem('alo',side,S,K,T,r,q,sigma,None)
    if scheme=='high':
        hp=getattr(ql.QdFpAmericanEngine,'highPrecisionScheme',None)
        sch=hp() if hp is not None else ql.QdFpTanhSinhIterationScheme(HIGH_PRECISION['m'],HIGH_PRECISION['n'],HIGH_PRECISION['eps'])
        pb.option.setPricingEngine(ql.QdFpAmericanEngine(pb.process,sch,ql.QdFpAmericanEngine.Auto))
    return pb.npv()

def ql_alo_npv_dated(side,S,K,days,r,q,sigma):
    """QuantLib QdFpAmericanEngine(accurateScheme, Auto) with day-granular dates and the real r, q and sigma (record R11 (a)):
    evaluation date d0, American exercise d0 to d0 + days, Actual365Fixed, flat continuous curves."""
    import QuantLib as ql
    from optionlab.library import D0
    ql.Settings.instance().evaluationDate=D0;dc=ql.Actual365Fixed()
    rts=ql.YieldTermStructureHandle(ql.FlatForward(D0,r,dc,ql.Continuous,ql.Annual));qts=ql.YieldTermStructureHandle(ql.FlatForward(D0,q,dc,ql.Continuous,ql.Annual))
    vts=ql.BlackVolTermStructureHandle(ql.BlackConstantVol(D0,ql.NullCalendar(),ql.QuoteHandle(ql.SimpleQuote(sigma)),dc))
    process=ql.BlackScholesMertonProcess(ql.QuoteHandle(ql.SimpleQuote(S)),qts,rts,vts)
    o=ql.VanillaOption(ql.PlainVanillaPayoff(ql.Option.Call if side==0 else ql.Option.Put,K),ql.AmericanExercise(D0,D0+days))
    o.setPricingEngine(ql.QdFpAmericanEngine(process,ql.QdFpAmericanEngine.accurateScheme(),ql.QdFpAmericanEngine.Auto));return o.NPV()

def alo_accuracy_body(out_dir,lattice_limit=None,grid_limit=None,switch_sigmas=None,mapping_days=ALO_MAPPING_DAYS,chain_rows=ALO_ACCURACY_CHAIN_ROWS):
    """Amendment I4.5 (documented metrics, never gates; written to alo-accuracy.json): (1) ALO (py-reference) against the
    converged CRR lattice reference A_ref of section 4 item 5 per SIGMA_BANDS x T_BANDS: count, median, p90 and maximum of
    (A_ref - ALO)/A_ref for A_ref >= 0.01 and the counts above and below A_ref +- eps_ref (ALO is not a bound); (2) ALO
    against BAW: the same statistics of (ALO - BAW)/ALO where both price the point (BAW admitted, ALO >= 0.01); (3) the
    scheme truncation |ALO(accurateScheme) - ALO(highPrecisionScheme)| (QuantLib-Python, Auto) on the record's oracle grid
    at sigma >= sigma_lo(ALO, row), absolute and relative to the accurate value (>= 0.01), information only; (4) the
    equation-switch jump of R4: |V(last FP-A T) - V(first FP-B T)| on the record S/K and sigma grid at sigma >= the R9
    sigma_lo of both equations, absolute and per unit K (K = 100); (5) the mapping consequence of R11: day-granular
    QuantLib (real r, q, sigma) against the mapped engine, both Auto, per T band; (6) the count of OK rows whose ALO price
    is below intrinsic: lattice points and grid points priced below intrinsic, and the OK rows of the first `chain_rows`
    rows of the synthetic large chain (the full-dataset count is in the bench panel counts). The `*_limit` arguments
    shorten the inputs for tests only."""
    from optionlab import oracle, reference
    from optionlab.models import sigma_lo, RunDefect, ModelDefect
    from optionlab.oracle import SIGMA_BANDS, T_BANDS, _band
    from optionlab.params import CASE
    from optionlab.contract import load_chain, rows as rows_of
    from optionlab.synthetic import generate
    fx=json.loads(FIXTURES.read_text());r,q=CASE.rate,CASE.dividend_yield
    alo_price=reference.price_function('alo',CASE);baw_price=reference.price_function('baw',CASE)
    intrinsic=lambda side,S,K:max((S-K) if side==0 else (K-S),0.0)
    key=lambda s,T:_band(s,SIGMA_BANDS)+'|'+_band(T,T_BANDS)
    lat=fx['oracle']['lattice'][:lattice_limit];gaps=[];above=below=skipped=0;vs_baw=[];both=0;lat_below=0;not_priced=0
    for p in lat:
        side,S,K,T,s=p['side'],p['S'],p['K'],p['T'],p['sigma']
        if s<sigma_lo('alo',side,T,r,q,CASE):not_priced+=1;continue           # below the R9 sigma_lo the ALO value is not defined
        try:v=alo_price(side,S,K,T,r,q,s)
        except RunDefect:raise                                     # H19: a run defect fails the check
        except ModelDefect:not_priced+=1;continue                  # order 5 (an inner-solver error): not priced
        lat_below+=v<intrinsic(side,S,K);above+=v>p['a_ref']+p['eps_ref'];below+=v<p['a_ref']-p['eps_ref']
        if p['a_ref']<0.01:skipped+=1
        else:gaps.append((key(s,T),(p['a_ref']-v)/p['a_ref']))
        try:b=baw_price(side,S,K,T,r,q,s)
        except RunDefect:raise
        except ArithmeticError:continue                       # BAW not admitted (AdmitExcluded) or a QuantLib error: not priced
        both+=1
        if v>=0.01:vs_baw.append((key(s,T),(v-b)/v))
    out={'label':'documented metric, never a gate (Amendment I4.5, Amendment D)'}
    out['alo_vs_lattice']={'points':len(lat),'count':len(gaps),'skipped_below_0.01':skipped,'not_priced':not_priced,'above_lattice':above,'below_lattice':below,**_banded(gaps)}
    out['alo_vs_baw']={'points':len(lat),'both_admitted':both,'count':len(vs_baw),**_banded(vs_baw)}
    grid=[g for g in ALO_RECORD_GRID if g[4]>=sigma_lo('alo',g[0],g[3],r,q,CASE)][:grid_limit];absd=[];reld=[];grid_below=0
    for side,S,K,T,s in grid:
        a=ql_alo_npv_scheme(side,S,K,T,r,q,s,'accurate');h=ql_alo_npv_scheme(side,S,K,T,r,q,s,'high')
        grid_below+=a<intrinsic(side,S,K);absd.append((key(s,T),abs(a-h)))
        if a>=0.01:reld.append((key(s,T),abs(a-h)/a))
    out['scheme_truncation']={'label':'information only; it defines nothing','points':len(grid),'high_precision':dict(HIGH_PRECISION),
                              'absolute':_banded(absd),'relative_value_ge_0.01':_banded(reld)}
    tA,tB=ALO_SWITCH_T;sw=[];swr=[]
    for side in (0,1):
        for sk in ALO_RECORD_SK:
            for s in (switch_sigmas if switch_sigmas is not None else ALO_RECORD_SIGMA):
                if s<max(sigma_lo('alo',side,tA,r,q,CASE),sigma_lo('alo',side,tB,r,q,CASE)):continue
                va=alo_price(side,100.0*sk,100.0,tA,r,q,s);vb=alo_price(side,100.0*sk,100.0,tB,r,q,s);sw.append(abs(va-vb))
                big=max(abs(va),abs(vb))
                if big>0.0:swr.append(abs(va-vb)/big)
    out['equation_switch_jump']={'t_fp_a':tA,'t_fp_b':tB,'points':len(sw),'max_abs':max(sw) if sw else None,
                                 'max_abs_per_k':max(sw)/100.0 if sw else None,'max_abs_per_k_label':'max_abs divided by K = 100 (not the R4 relative measure)',
                                 'max_rel_to_value':max(swr) if swr else None,
                                 'max_rel_to_value_label':'|V_FP-A - V_FP-B| relative to the larger of the two values (the R4 relative measure, A6P-03)'}
    mc={}
    for days in mapping_days:
        T=days/365.0
        for side in (0,1):
            for sk in ALO_RECORD_SK:
                for s in ALO_MAPPING_SIGMAS:
                    d=ql_alo_npv_dated(side,100.0*sk,100.0,days,r,q,s);m=ql_alo_npv(side,100.0*sk,100.0,T,r,q,s)
                    b=mc.setdefault(_band(T,T_BANDS),{'points':0,'max_abs':0.0,'max_rel':0.0});b['points']+=1;b['max_abs']=max(b['max_abs'],abs(d-m))
                    if abs(d)>=1e-8*100.0:b['max_rel']=max(b['max_rel'],abs(d-m)/abs(d))
    out['mapping_consequence']={'days':list(mapping_days),'sigmas':list(ALO_MAPPING_SIGMAS),'points':sum(b['points'] for b in mc.values()),'bands':mc}
    rws=rows_of(load_chain(generate(chain_rows,ALIGN_SEED,CASE)),CASE) if chain_rows else [];res=reference.run(rws,CASE,models=('alo',)) if rws else None
    ok=[(row,p) for row,st,p in zip(rws,res['models']['alo']['status'],res['models']['alo']['price']) if st=='OK'] if res else []
    out['ok_below_intrinsic']={'lattice':lat_below,'record_grid':grid_below,'chain_rows':len(rws),'chain_ok_rows':len(ok),
                               'chain_ok_below_intrinsic':sum(1 for row,p in ok if p<intrinsic(row[0],row[1],row[2]))}
    with open(Path(out_dir)/'alo-accuracy.json','w') as f:json.dump(out,f,separators=(',',':'),allow_nan=False)
    return {'status':'PASS','label':'documented metric, never a gate','files':['alo-accuracy.json'],
            'counts':{'lattice':len(lat),'grid':len(grid),'switch':len(sw),'mapping':out['mapping_consequence']['points'],'chain_rows':len(rws)}}

@check('alo-accuracy')
def alo_accuracy(out_dir,args):
    """I4.5 (Task A6): the documented ALO model-accuracy metrics; see alo_accuracy_body. Never a gate (before_run false)."""
    if _no_arguments(args):return _no_arguments(args)
    return alo_accuracy_body(out_dir)

def main(argv):
    if len(argv)<3 or argv[1] not in CHECKS:print(json.dumps({'status':'FAIL','reason':'unknown check'}));return 2
    print(json.dumps(CHECKS[argv[1]](Path(argv[2]),argv[3:])));return 0

if __name__=='__main__':sys.exit(main(sys.argv))
