"""EX-16 (T23; Phase 2 Task 24 example part, ruling R68): the check `native-spread`, the tolerance calibration evidence of spec
section 3.7 for every variant, C included. optionlab.native_check registers it; `bench check --check native-spread --native`
runs it with the restored, digest-verified pl-worker and libpl_inproc.so (SAFE_C_BENCH_NATIVE). It never changes a tolerance:
the framework CLI `bench tolerance --spread spread.json --project DIR` makes the proposal (tools/bench_tolerance.py).

Variants (single-thread rule R3: no py-threads, py-processes or pool rows): py-optimized, py-library, and c-serial on each
route cell that exists (stdio warm and cold, shm warm and cold, inproc warm; workers direct). Calls: the all-models call (mask
31, the five models) and each one-model call (masks 1, 2, 4, 8, 16). Sets: the tiers tiny (1 row), small (256) and medium
(1,024) of the case seed (prefixes of one prefix-stable chain; each tier is its own call) and the oracle edge rows of the
protocol that use the case parameters (optionlab.native_agreement.edge_inputs): for mask 31 the rows on which py-reference
evaluates all five models, for a one-model mask the rows on which it evaluates that model (a model that raises on a row is the
G4.8 trap class, a run defect and no spread). Reference: py-reference, one five-model run per set (reference.run evaluates
each row and model alone; native-agreement checks the per-model part against a per-model run).

Per row and model (compare_part) the row rules of optionlab.agreement.compare decide which rows enter the numeric comparison
(boundary_ambiguous and rounding-band rows by their status rules, equal statuses, OK, finite values; a flat_vega row the fit
rule only; a multi_root row (agreement.multi_root) the fit rule at the variant IV only); a status that the rules refuse, a
non-finite value of an OK row and a model error at a multi_root point are status failures. For each compared row the fraction
of each section 3.7 rule at the values of the model's tolerance block (`tolerances` for bsm, bjs, crr; `tolerances.baw`,
`tolerances.alo`) is recorded: iv |d iv| / tau_sigma; price |d price| / (nu tau_sigma + price_rel max(1, |price_ref|));
fit |price - mid| / (|nu_variant| fit_nu + fit_rel max(1, mid)) of the variant; greeks |d g| / (greek_abs + (greek_rel +
tau_sigma / iv_ref) |g_ref|) (+ sstar_k K for baw), and the largest |delta| of every quantity.

Fields (FIELD_BASIS): the measured spread of a tolerance field, in the unit of the field, is its current value times the
largest fraction of the rule it scales (iv_abs and iv_ulp_rel: iv; price_rel: price; fit_nu and fit_rel: fit; greek_abs and
greek_rel: the largest greek fraction): the value at which that rule, scaled as a whole, would exactly admit the largest
measured difference. So measured < current exactly when every compared difference is inside the rule (the baw-spread and
alo-spread basis, measured_fraction). NO_SPREAD names the fields without a spread (classification thresholds and the sstar_k
allowance term).

Oracle error per field (spec 3.7: each locked value above the measured spread and below the oracle error of section 4), in the
unit of the field, from the protocol oracle (protocol/oracle.json):
- iv_abs, iv_ulp_rel: the item 6 IV round-trip bound, tau = 1e-8 + 1e-13 max(1, price) / nu (optionlab.oracle.check_iv_roundtrip;
  item 6 covers the five models): ITEM6.
- price_rel (bsm, bjs, crr): the item 1 (BSM: max(1e-12 |v|, 1e-14 max(1, S))) and item 2 (BjS: max(1e-10 |v|, 1e-12 max(1, K)))
  bounds as a coefficient of max(1, |v|): the smallest bound / max(1, |v|) over the oracle points.
- greek_abs, greek_rel: the item 7 bounds as for the measured spread: the current value times the smallest bound / allowance
  over the item 7 points (bsm, bjs, crr: the CRR bump points on BSM, optionlab.oracle.item7_point; baw: the stencil points,
  optionlab.checks._sstar_oracle; alo: the E-ALO-6 measured item 7, optionlab.checks.alo_item7_margins), the allowance being
  the greek rule at the current values. The two checks functions use the general values, so a block whose greek and iv values
  differ from them gets no oracle error (a problem).
- Section 4 gives no bound for the fit rule and no price bound for baw and alo: those fields get no oracle error and stay out
  of spread.json (the framework spread form needs an oracle error for every field); spread-detail.json records them.

Files: spread.json (schemas/bench-tolerance-spread.json: per field the oracle error and per variant of the form
<variant>-all or <variant>-one the measured spread and its sample count) and spread-detail.json (per field: measured, the
variant, call, set, model and row that gave it, the oracle error and its basis, the current value; per variant, call, set and
model the counts and the largest |delta| of every quantity; the fields without a spread and why; seconds).

FAIL when a variant, call or set has no result, when a compared set is empty (a part without a row, a field without a sample),
when a status failure exists, or when a measured spread is not below the current value (never a widening, never a tolerance
change). The work runs in the spawned pool of optionlab.native_agreement (single-threaded tasks, MAX_WORKERS). REQUIRE-style:
named problems, never an assert statement; H19: a RunDefect ends the check."""
import hashlib, json, math, multiprocessing, tempfile, time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from optionlab import native_agreement as na
from optionlab.contract import FIELDS, MODELS5
from optionlab.models import RunDefect

FILE='spread.json';DETAIL='spread-detail.json'
SETS=na.TIERS+('edges',)
CALLS=(na.ALL_MASK,)+na.PER_MODEL_MASKS
PY_VARIANTS=('py-optimized','py-library')
C_VARIANTS=tuple(f'c-serial-{cell}' for cell in na.ROUTE_CELLS)
VARIANTS=PY_VARIANTS+C_VARIANTS
GREEKS=('delta','gamma','theta','vega','rho')
QUANTITIES=('iv','price','fit')+GREEKS
BASES=('iv','price','fit','greeks')
FIELD_BASIS={'iv_abs':'iv','iv_ulp_rel':'iv','price_rel':'price','fit_nu':'fit','fit_rel':'fit','greek_abs':'greeks','greek_rel':'greeks'}
RULE_KEYS=tuple(FIELD_BASIS)+('flat_vega',)                 # the values that compare_part reads from a tolerance block
BLOCKS=('','baw','alo')                                     # '' = the top-level fields (bsm, bjs, crr)
NO_SPREAD={'flat_vega':'a classification threshold of nu_ref (spec 3.7: a flat_vega row compares status and the fit rule only), not a spread',
           'ambiguity_rel':'a classification threshold of the boundary_ambiguous rows (spec 3.3), not a spread',
           'provider_mid_diff':'a classification threshold of the provider mid difference, not a spread',
           'sstar_k':'an allowance term per BAW greek (G-BAW2 Proposal B: 0), not a spread; spread-detail.json records need_sstar_k'}
ITEM6={'iv_abs':1e-8,'iv_ulp_rel':1e-13}                    # spec 4 item 6: optionlab.oracle.check_iv_roundtrip tau
ITEM1=(1e-12,1e-14);ITEM2=(1e-10,1e-12)                     # spec 4 items 1 and 2: optionlab.oracle.check_bsm, check_bjs
SOURCE='optionlab.native_spread'
MAX_WORKERS=na.MAX_WORKERS

class NativeSpreadError(Exception):
    """A precondition of the check that does not hold (a named exception; never a Python assert)."""

def block_of(model):return model if model in ('baw','alo') else ''

def field_name(block,field):return f'{block}.{field}' if block else field

def call_name(mask):return 'all' if mask==na.ALL_MASK else 'one'

def spread_variant(variant,mask):return f'{variant}-{call_name(mask)}'

def block_values(tolerances,block):
    """The RULE_KEYS values of a tolerance block (block '' = the top-level fields) and its sstar_k (baw), as floats.
    NativeSpreadError when a value is missing or not a number."""
    t=tolerances if not block else tolerances.get(block)
    if not isinstance(t,dict):raise NativeSpreadError(f'tolerances.{block} is not a block')
    out={}
    for k in RULE_KEYS:
        v=t.get(k)
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v):raise NativeSpreadError(f'tolerances {field_name(block,k)} is not a number')
        out[k]=float(v)
    sk=t.get('sstar_k')
    if block=='baw':
        if not isinstance(sk,dict) or set(sk)!=set(GREEKS):raise NativeSpreadError('tolerances.baw.sstar_k needs one value per greek')
        out['sstar_k']={g:float(sk[g]) for g in GREEKS}
    return out

# ---- one part: the row rules of agreement.compare and the section 3.7 fractions -----------------------------------------
def empty_stats():
    return {'rows':0,'compared':0,'status_failures':0,'multi_root':0,'flat_vega':0,'ambiguous':0,'band':0,
            'frac':{b:0.0 for b in BASES},'frac_at':{b:None for b in BASES},'samples':{b:0 for b in BASES},
            'max_abs':{q:0.0 for q in QUANTITIES},'abs_at':{q:None for q in QUANTITIES},'need_sstar_k':{g:0.0 for g in GREEKS}}

def _put(s,basis,value,i):
    s['samples'][basis]+=1
    if s['frac_at'][basis] is None or value>s['frac'][basis]:s['frac'][basis]=value;s['frac_at'][basis]=i

def _abs(s,q,value,i):
    if s['abs_at'][q] is None or value>s['max_abs'][q]:s['max_abs'][q]=value;s['abs_at'][q]=i

def compare_part(rows,a,b,tol,model,params):
    """Stats of the variant part `b` against the py-reference part `a` of one model on `rows` at the block values `tol`
    (block_values). The row rules are those of agreement.compare (see the module text); the fraction of each rule at `tol`
    and the largest |delta| per quantity are kept with the row index that gave them."""
    from optionlab import agreement
    from optionlab.models import sigma_lo, ModelDefect
    from optionlab.reference import FLAG_BOUNDARY_AMBIGUOUS, FLAG_ROUNDING_BAND, price_function
    s=empty_stats();n=len(rows)
    if any(len(col.get(k,()))!=n for col in (a,b) for k in ('status','flags')+FIELDS):
        s['rows']=n;s['status_failures']=max(1,n);return s
    price=price_function(model,params);sk=tol.get('sstar_k') or {g:0.0 for g in GREEKS}
    for i,row in enumerate(rows):
        s['rows']+=1
        rs,gs=a['status'][i],b['status'][i];side,S,K,T,bid,ask,r,q=row
        rband=bool(a['flags'][i]&FLAG_ROUNDING_BAND);gband=bool(b['flags'][i]&FLAG_ROUNDING_BAND)
        if a['flags'][i]&FLAG_BOUNDARY_AMBIGUOUS:
            s['ambiguous']+=1;accepted=set(agreement.NEIGHBORS.get(rs,{rs}))
            if rband or gband:accepted|={rs,'MODEL_DOMAIN'}
            if gs not in accepted:s['status_failures']+=1
            continue
        if (rband or gband) and gs!=rs:
            s['band']+=1
            if {rs,gs}!={'OK','MODEL_DOMAIN'}:s['status_failures']+=1
            continue
        if rs!=gs:s['status_failures']+=1;continue
        if rs!='OK':continue
        if any(not math.isfinite(b[f][i]) for f in FIELDS):s['status_failures']+=1;continue
        mid=(bid+ask)/2.0                                   # an OK row has numeric quotes
        nu=a['vega'][i]*100.0;pr=a['price'][i]
        fit_d=abs(b['price'][i]-mid);fit_allow=abs(b['vega'][i])*100.0*tol['fit_nu']+tol['fit_rel']*max(1.0,mid)
        if nu<tol['flat_vega']:
            s['flat_vega']+=1;_put(s,'fit',fit_d/fit_allow,i);_abs(s,'fit',fit_d,i);continue
        ts=agreement.tau_sigma(pr,nu,tol);d_iv=abs(b['iv'][i]-a['iv'][i]);v_iv=b['iv'][i]
        if d_iv>ts and sigma_lo(model,side,T,r,q,params)<=v_iv<=params.sigma_hi:
            try:mr=agreement.multi_root(price,row,model,params,a['iv'][i],v_iv,mid)
            except RunDefect:raise
            except ModelDefect:s['status_failures']+=1;continue
            if mr:
                s['multi_root']+=1
                try:d=abs(price(side,S,K,T,r,q,v_iv)-mid);slope=agreement.fit_slope(price,row,model,params,v_iv)
                except RunDefect:raise
                except ModelDefect:s['status_failures']+=1;continue
                _put(s,'fit',d/(slope*tol['fit_nu']+tol['fit_rel']*max(1.0,mid)),i);_abs(s,'fit',d,i);continue
        s['compared']+=1
        _put(s,'iv',d_iv/ts,i);_abs(s,'iv',d_iv,i)
        d=abs(b['price'][i]-pr);_put(s,'price',d/(nu*ts+tol['price_rel']*max(1.0,abs(pr))),i);_abs(s,'price',d,i)
        _put(s,'fit',fit_d/fit_allow,i);_abs(s,'fit',fit_d,i)
        worst=0.0
        for g in GREEKS:
            d=abs(b[g][i]-a[g][i]);general=tol['greek_abs']+(tol['greek_rel']+ts/a['iv'][i])*abs(a[g][i])
            worst=max(worst,d/(general+sk[g]*K));_abs(s,g,d,i)
            if model=='baw':s['need_sstar_k'][g]=max(s['need_sstar_k'][g],max(0.0,d-general)/K)
        _put(s,'greeks',worst,i)
    return s

# ---- the fields, the spread file and the problems (pure functions of the stats; the light tests mutate their inputs) -----
def field_table(stats,tolerances):
    """{field: entry} of every FIELD_BASIS field of every block from `stats` {(variant, mask, set, model): compare_part stats}:
    current, measured (current x the largest fraction of the basis over every model of the block), the variant, call, set,
    model and row that gave it, the samples, and per spread variant (<variant>-all, <variant>-one) the measured spread and its
    samples."""
    out={}
    for block in BLOCKS:
        cur=block_values(tolerances,block);models=[m for m in MODELS5 if block_of(m)==block]
        for field,basis in FIELD_BASIS.items():
            name=field_name(block,field);e={'block':block or None,'basis':basis,'current':cur[field],'measured':0.0,'at':None,'samples':0,'variants':{}}
            for (variant,mask,s,model),st in sorted(stats.items()):
                if model not in models:continue
                n=st['samples'][basis];f=st['frac'][basis];key=spread_variant(variant,mask);e['samples']+=n
                if n:
                    v=e['variants'].setdefault(key,{'max_abs':0.0,'samples':0})
                    v['max_abs']=max(v['max_abs'],cur[field]*f);v['samples']+=n
                if n and (e['at'] is None or cur[field]*f>e['measured']):
                    e['measured']=cur[field]*f;e['at']={'variant':variant,'call':mask,'set':s,'model':model,'row':st['frac_at'][basis],'fraction':f}
            out[name]=e
    return out

def spread_document(fields,oracle):
    """The framework spread file (schemas/bench-tolerance-spread.json) of the fields that have an oracle error and a sample."""
    doc={'schema_version':1,'source':SOURCE,'fields':{}}
    for name,e in sorted(fields.items()):
        bound=oracle.get(name)
        if bound is None or not e['variants']:continue
        doc['fields'][name]={'oracle_error':bound,'variants':{k:{'max_abs':v['max_abs'],'samples':v['samples']} for k,v in sorted(e['variants'].items())}}
    return doc

def problems_of(stats,fields,missing):
    """The FAIL reasons: `missing` (the variant, call and set keys without a result), a part without a row, a field without a
    sample, a status failure, a measured spread not below the current value."""
    out=[f'{v} mask {m} {s}: no result' for v,m,s in missing]
    out+=[f'{v} mask {m} {s} {model}: no compared row' for (v,m,s,model),st in sorted(stats.items()) if not st['rows']]
    out+=[f'{v} mask {m} {s} {model}: {st["status_failures"]} status failures' for (v,m,s,model),st in sorted(stats.items()) if st['status_failures']]
    for name,e in sorted(fields.items()):
        if not e['samples']:out.append(f'{name}: no sample')
        elif not e['measured']<e['current']:out.append(f'{name}: measured spread {e["measured"]:.3g} not below the current value {e["current"]:.3g}')
    return out

def expected_keys():
    """Every (variant, mask, set) of the check."""
    return [(v,m,s) for v in VARIANTS for m in CALLS for s in SETS]

def check_row(problems,doc,seconds,counts):
    """The check row (container/bench-coordinator.py check_result: at most 32 integer count keys, a label of at most 120
    characters of the label grammar)."""
    c={'fields':len(doc['fields']),'variants':len(VARIANTS),'calls':len(CALLS),'sets':len(SETS),'problems':len(problems),'seconds':int(seconds)}
    c.update({k:int(v) for k,v in counts.items()})
    text=('failed '+problems[0]) if problems else 'every set compared, every measured spread below the current value'
    return {'status':'FAIL' if problems else 'PASS','files':[FILE,DETAIL],'counts':c,'label':na.LABEL_BAD.sub(' ',text)[:120]}

# ---- oracle errors ------------------------------------------------------------------------------------------------------
def _min_ratio(values):
    v=[x for x in values if math.isfinite(x)]
    return min(v) if v else None

def _task_oracle(kind,tolerances):
    """(oracle errors {field: value}, basis texts {field: text}, problems) of one block: 'top' (bsm, bjs, crr), 'baw', 'alo'."""
    from optionlab import agreement, checks, oracle, protocol
    fx=protocol.oracle();p=na.case_params();block='' if kind=='top' else kind;tol=block_values(tolerances,block)
    out={};basis={};problems=[]
    for f,v in ITEM6.items():out[field_name(block,f)]=v;basis[field_name(block,f)]='spec 4 item 6 (IV round trip tau)'
    if kind=='top':
        ratios=[max(ITEM1[0]*abs(x['price']),ITEM1[1]*max(1.0,x['S']))/max(1.0,abs(x['price'])) for x in fx['oracle']['bsm']]
        ratios+=[max(ITEM2[0]*abs(x['value']),ITEM2[1]*max(1.0,x['K']))/max(1.0,abs(x['value'])) for x in fx['oracle']['bjs']]
        out['price_rel']=_min_ratio(ratios);basis['price_rel']=f'spec 4 items 1 and 2 ({len(ratios)} points)'
        cal=fx['calibration']['item7'];ratios=[]
        for x in fx['oracle']['greeks']:
            an=oracle.bsm(x['side'],x['S'],x['K'],x['T'],x['r'],x['q'],x['sigma']);nu=abs(an[4])*100.0
            ts=agreement.tau_sigma(an[0],nu,tol) if nu>=tol['flat_vega'] else tol['iv_abs']
            for k,v in oracle.item7_point(x,cal).items():
                g=an[4] if k.startswith('vega') else an[5]
                ratios.append(v['bound']/(tol['greek_abs']+(tol['greek_rel']+ts/x['sigma'])*abs(g)))
        m=_min_ratio(ratios);desc=f'spec 4 item 7 (CRR bumps on BSM, {len(ratios)} terms)'
    else:
        general={k:float(agreement.TOLERANCES[k]) for k in RULE_KEYS}
        if any(tol[k]!=general[k] for k in RULE_KEYS):
            problems.append(f'tolerances.{kind}: values differ from the general values that the item 7 margin functions use');m=None
        elif kind=='baw':
            r=checks._sstar_oracle(fx,p,tol['sstar_k']);m=_min_ratio(r[g]['min_margin_high'] for g in GREEKS)
        else:
            r=checks.alo_item7_margins(p);m=_min_ratio(r[g]['min_tol_over_allowance'] for g in r if r[g]['min_tol_over_allowance'] is not None)
        desc='spec 4 item 7 (G-BAW2 stencil points)' if kind=='baw' else 'spec 4 item 7 (E-ALO-6, measured, not proven)'
    for f in ('greek_abs','greek_rel'):
        out[field_name(block,f)]=None if m is None else tol[f]*m;basis[field_name(block,f)]=desc
    return out,basis,problems

# ---- the pool tasks ------------------------------------------------------------------------------------------------------
def _task_variant(variant,rows,models):
    """The result of a Python variant (py-optimized through optionlab.optimized, py-library through optionlab.library) on
    the rows for the models, as the checks optimized-agreement, baw-spread and alo-spread call them."""
    from optionlab import library, optimized as opt
    from optionlab.checks import _prep_rows
    p=na.case_params()
    if variant=='py-optimized':return opt.materialize(opt.run(_prep_rows(rows),p,models=tuple(models)))
    if variant=='py-library':return library.run(rows,p,models=tuple(models))
    raise NativeSpreadError('unknown Python variant')

def _task_compare(rows,ref,got,models,tolerances):
    """{model: compare_part stats} of one call."""
    p=na.case_params()
    for m in models:
        if m not in got.get('models',{}) or m not in ref.get('models',{}):raise NativeSpreadError('a model part is missing')
    return {m:compare_part(rows,ref['models'][m],got['models'][m],block_values(tolerances,block_of(m)),m,p) for m in models}

# ---- the run ------------------------------------------------------------------------------------------------------------
def _sets(medium,ref_medium,per_row,edge_rows):
    """{(mask, set): (rows, py-reference result of the mask's models)}."""
    from optionlab.synthetic import SIZES
    out={}
    for mask in CALLS:
        models=na.models_of(mask)
        for t in na.TIERS:
            n=SIZES[t];out[(mask,t)]=(medium[:n],na.select(ref_medium,models,range(n)))
        idx=[i for i,r in enumerate(per_row) if r is not None and all(r[m][0]=='ok' for m in models)]
        if idx:out[(mask,'edges')]=([edge_rows[i] for i in idx],na.concat([na.merge(*(per_row[i][m][1] for m in models)) for i in idx]))
    return out

def run_all(native_dir):
    """The document of spread-detail.json and the framework spread document (see the module text)."""
    from benchlab import native_worker as nw
    from optionlab import protocol
    from optionlab.contract import rows as chain_rows
    from optionlab.synthetic import SIZES
    nw.same_directory(native_dir)
    tolerances=protocol.tolerances();t0=time.monotonic();phases={}
    a=na._adapter();params,seed=na._case()
    with tempfile.TemporaryDirectory() as tmp:
        data=a.synthesize(SIZES['medium'],seed);path=Path(tmp)/'medium.json';path.write_bytes(data)
        medium=chain_rows(a.load({'path':str(path),'sha256':hashlib.sha256(data).hexdigest()}))
    edges,covered=na.edge_inputs();edge_rows=[r for _,r in edges];phases['generate']=round(time.monotonic()-t0,1)
    ex=ProcessPoolExecutor(max_workers=min(MAX_WORKERS,na.pool_workers()),mp_context=multiprocessing.get_context('spawn'));P=na._Pool(ex)
    try:
        # the longest tasks first (the pool takes them in order): the Python variants on the largest tier, the ALO reference
        h_py={}
        for t in reversed(na.TIERS):
            for v in PY_VARIANTS:
                for mask in CALLS:h_py[(v,mask,t)]=P.submit(v,_task_variant,v,medium[:SIZES[t]],na.models_of(mask))
        h_alo=[P.submit('py-reference',na._task_reference,part,('alo',)) for part in na._chunks(medium,na.ALO_CHUNK)]
        h_ref=[P.submit('py-reference',na._task_reference,part,('bsm','bjs','crr','baw')) for part in na._chunks(medium,na.REF_CHUNK)]
        h_edge=[P.submit('edges',na._task_edges,part) for part in na._chunks(edge_rows,na.EDGE_CHUNK)]
        h_oracle={k:P.submit('oracle',_task_oracle,k,tolerances) for k in ('alo','baw','top')}
        h_c={(cell,mask):P.submit('c-serial',na._task_c,cell,mask,[(('tier',mask,t),medium[:SIZES[t]],'result') for t in na.TIERS]) for cell in na.ROUTE_CELLS for mask in CALLS}
        per_row=[]
        for h in h_edge:
            got=P.get(h);per_row+=got if got is not None else [None]*na.EDGE_CHUNK
        per_row=per_row[:len(edge_rows)]
        parts=[P.get(h) for h in h_ref];alo=[P.get(h) for h in h_alo]
        if None in parts or None in alo:raise NativeSpreadError('no py-reference result of the medium tier')
        ref_medium=na.merge(na.concat(parts),na.concat(alo));ref_medium={'n':ref_medium['n'],'models':{m:ref_medium['models'][m] for m in MODELS5}}
        sets=_sets(medium,ref_medium,per_row,edge_rows)
        for v in PY_VARIANTS:
            for mask in CALLS:
                if (mask,'edges') in sets:h_py[(v,mask,'edges')]=P.submit(v,_task_variant,v,sets[(mask,'edges')][0],na.models_of(mask))
        h_ce={(cell,mask):P.submit('c-serial',na._task_c,cell,mask,[(('edges',mask,'edges'),sets[(mask,'edges')][0],'result')])
              for cell in na.ROUTE_CELLS for mask in CALLS if (mask,'edges') in sets}
        results={}
        for (v,mask,s),h in h_py.items():
            got=P.get(h)
            if got is not None:results[(v,mask,s)]=got
        for (cell,mask),h in list(h_c.items())+list(h_ce.items()):
            for key,o in (P.get(h) or {}).items():
                if isinstance(o,dict) and 'result' in o:results[(f'c-serial-{cell}',mask,key[2])]=o['result']
        phases['results']=round(time.monotonic()-t0,1)
        h_cmp={k:P.submit('compare',_task_compare,sets[(k[1],k[2])][0],sets[(k[1],k[2])][1],got,na.models_of(k[1]),tolerances)
               for k,got in results.items() if (k[1],k[2]) in sets}
        stats={}
        for (v,mask,s),h in h_cmp.items():
            got=P.get(h)
            if got is not None:
                for m,st in got.items():stats[(v,mask,s,m)]=st
        oracle={};basis={};oracle_problems=[]
        for k,h in h_oracle.items():
            got=P.get(h)
            if got is None:oracle_problems.append(f'oracle {k}: no result');continue
            o,b,pr=got;oracle.update(o);basis.update(b);oracle_problems+=pr
        phases['compare']=round(time.monotonic()-t0,1)
        missing=[k for k in expected_keys() if (k[1],k[2]) not in sets or k not in results or any((k[0],k[1],k[2],m) not in stats for m in na.models_of(k[1]))]
        task_problems=[p for name in sorted(P.tasks) for p in P.task_problems(name)]
        seconds={k:round(v,1) for k,v in sorted(P.seconds.items())};tasks=dict(sorted(P.tasks.items()))
    finally:ex.shutdown(wait=True,cancel_futures=True)
    fields=field_table(stats,tolerances)
    for name,e in fields.items():
        e['oracle_error']=oracle.get(name);e['oracle_basis']=basis.get(name) or ('section 4 has no bound for this field' if name.split('.')[-1] in ('fit_nu','fit_rel','price_rel') else None)
    doc=spread_document(fields,oracle)
    problems=task_problems+oracle_problems+problems_of(stats,fields,missing)
    no_spread={}
    for block in BLOCKS:
        t=tolerances if not block else tolerances[block]
        for k in t:
            if k in NO_SPREAD:no_spread[field_name(block,k)]=NO_SPREAD[k]
    detail={'label':'EX-16 native-spread (spec 3.7 calibration evidence; never a tolerance change)','variants':list(VARIANTS),'calls':list(CALLS),
            'sets':{s:(SIZES[s] if s in SIZES else len(edge_rows)) for s in SETS},'edge_rows':len(edge_rows),'edge_rows_covered_by_vectors':covered,
            'fields':fields,'no_spread':no_spread,'in_spread_file':sorted(doc['fields']),
            'need_sstar_k':{g:max((st['need_sstar_k'][g] for (_,_,_,model),st in stats.items() if model=='baw'),default=None) for g in GREEKS},
            'parts':{f'{v} {m} {s} {model}':st for (v,m,s,model),st in sorted(stats.items())},
            'problems':problems[:200],'problem_count':len(problems),'phases':phases,'task_seconds':seconds,'tasks':tasks}
    counts={'parts':len(stats),'compared_rows':sum(st['compared'] for st in stats.values()),'multi_root':sum(st['multi_root'] for st in stats.values()),
            'status_failures':sum(st['status_failures'] for st in stats.values()),'missing':len(missing),'edge_rows':len(edge_rows)}
    return detail,doc,problems,counts

def check(out_dir,native_dir):
    """The check native-spread: run_all, spread.json and spread-detail.json in out_dir, and the check row. An exception other
    than a RunDefect is a FAIL row with the exception type only (no traceback, no row value)."""
    started=time.monotonic()
    try:detail,doc,problems,counts=run_all(native_dir)
    except RunDefect:raise
    except Exception as exc:
        text=na.LABEL_BAD.sub(' ',f'failed exception {type(exc).__name__}')[:120]
        return {'status':'FAIL','reason':text,'label':text,'files':[]}
    seconds=time.monotonic()-started;detail['seconds']=round(seconds,1)
    Path(out_dir).mkdir(parents=True,exist_ok=True)
    (Path(out_dir)/FILE).write_text(json.dumps(doc,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n')
    (Path(out_dir)/DETAIL).write_text(json.dumps(detail,sort_keys=True,indent=1,allow_nan=False)+'\n')
    return check_row(problems,doc,seconds,counts)
