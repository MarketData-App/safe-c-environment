"""Panel candidate inputs of the synthetic large chain (spec Amendment G3.3, G3.7; Task 7, P3P-08; Amendment I7.2 and
the H21 cell rule, Task A6).

`inputs(chain, params, workers, part=None)` computes, outside every timed interval (the coordinator job `panel`):
- the py-reference result of the chain for the five models (MODELS5, digest form ocg-v1m, mask 31), per row status,
  flags and engine_evals per model (optionlab.reference.run on contiguous parts of the rows, one part per spawned worker
  process, joined in row order: each row is evaluated alone, so the joined columns equal one sequential run);
- per model the grid test `grid_ok` (at most one sign change of the reference f of the model on the 64 log-spaced sigma
  values over [sigma_lo, 5.0], optionlab.agreement.grid_sign_changes) for every row whose five statuses are OK and that
  carries none of the listed flags below_intrinsic, boundary_ambiguous, flat_vega (H21.4: rounding_band rows included);
  None on every other row. A ModelDefect at a grid point gives False (the row is not certified); a RunDefect propagates
  (run defect);
- side, K/S, T and x = ln(K/F) per row (`row_x`; H21.2).
With `part` = (k, K) only row part k of K is computed (the five-model inputs outlast one container); the part document
also holds the part's reference columns in the canonical value encoding, and `join(parts)` joins the K parts in row order
and computes the ocg-v1m digest of the joined result. The host (tools/bench_panel.py) applies the cell rule to the stored
values only; `selection` is the example's copy of the one selection rule of H21.5 for the pre-flight check (H21.7)."""
import math, multiprocessing, struct
from concurrent.futures import ProcessPoolExecutor
from optionlab import reference as ref_mod, protocol
from optionlab.agreement import MULTI_ROOT_GRID, grid_sign_changes
from optionlab.contract import MODELS5, FIELDS, rows as chain_rows
from optionlab.models import RunDefect, ModelDefect, discount

LISTED_FLAGS=ref_mod.FLAG_BELOW_INTRINSIC|ref_mod.FLAG_BOUNDARY_AMBIGUOUS|ref_mod.FLAG_FLAT_VEGA    # H21.4: rounding_band no longer excludes
PANEL_MODELS=MODELS5     # Amendment I7.2: the five-model panel, mask 31 (the MODELS5 bit order)
NO_SCALE=5e-324     # the scale column t must hold a finite number > 0 on every row (bench_panel.column_problems, FR5); a row with T <= 0
                    # (status EXPIRED, never a candidate) stores the smallest positive double in the panel column t

def rule():
    """FR5: the cell rule of the protocol (`panel.cell_rule`: category, position and scale columns, level ratios, grid, report,
    cells in cell order). The cells (H21.3: name, category, band, position target, scale target) are protocol data; the framework
    and this module read the same rule."""
    return protocol.protocol()['panel']['cell_rule']

def cell_names():
    """The panel cell names in cell order (the keys of the plan and the observations)."""
    return [c['name'] for c in rule()['cells']]

def grid():
    """The grid test settings of the protocol cell rule: {'upper': ..., 'points': ...}; the panel inputs carry them as `grid`."""
    return dict(rule()['grid'])

def scale_value(T):
    """The panel column t of a row with the time T: T, or NO_SCALE when T <= 0."""
    return T if T>0.0 else NO_SCALE

class PanelCellEmpty(Exception):
    """H21.5: a cell without a row (reason panel-cell-empty); args[0] is the cell name."""

def row_x(row,params=None):
    """H21.2: x = ln(K/F) with F = (S D_q)/D_r of the row's own r, q and T, the forward of tau_V (reference.tau_v: r' = r T,
    q' = q T, D = 1/exp(r' 1.0)), in this binary64 order. None when K/F is not a positive finite number (K = 0 on an
    INVALID_INPUT row): log is undefined there."""
    side,S,K,T,bid,ask,r,q=row
    r1=r*T;q1=q*T
    D_r=discount(r1,1.0);D_q=discount(q1,1.0);F=(S*D_q)/D_r
    v=K/F if F!=0.0 and math.isfinite(F) else math.nan
    return math.log(v) if math.isfinite(v) and v>0.0 else None

def grid_ok(row,model,params):
    """G3.3 grid test of one row and model: True when the py-reference f of the model changes sign at most once on the
    MULTI_ROOT_GRID log-spaced sigma values over [sigma_lo, 5.0]; False when it changes sign more than once or when an
    engine error (ModelDefect) occurs at a grid point. A RunDefect propagates."""
    mid=(row[4]+row[5])/2.0
    try:return grid_sign_changes(ref_mod.price_function(model,params),row,model,params,mid,MULTI_ROOT_GRID)<=1
    except RunDefect:raise
    except ModelDefect:return False

def _grid(params):
    """FR5A-01: the grid settings of the panel inputs and part files: the upper sigma bound of the case and the point count of
    the grid test. `bench panel` refuses inputs whose grid differs from the protocol cell rule."""
    return {'upper':params.sigma_hi,'points':MULTI_ROOT_GRID}

def _reference_part(part,params):return ref_mod.run(part,params,models=PANEL_MODELS)

def _grid_part(items,params):return [(i,[grid_ok(row,m,params) for m in PANEL_MODELS]) for i,row in items]

def _parts(seq,k):
    n=len(seq);k=max(1,min(k,n));size=-(-n//k) if n else 1
    return [seq[i:i+size] for i in range(0,n,size)]

def candidate_before_grid(result,i):
    """Status OK for every panel model and none of the listed flags (the part of the H21.4 rule before the grid test)."""
    return all(result['models'][m]['status'][i]=='OK' and not result['models'][m]['flags'][i]&LISTED_FLAGS for m in PANEL_MODELS)

def _encode(v):
    """The canonical value encoding of reference.canonical_result (NaN -> None, -0.0 -> 0.0, else the big-endian bits)."""
    return ref_mod._digest_float(v)

def _decode(h):return math.nan if h is None else struct.unpack('>d',bytes.fromhex(h))[0]

def _below_intrinsic(rws,col):
    """Amendment I4.5: the count of OK alo rows whose price is below intrinsic (the engine has no intrinsic floor)."""
    return sum(1 for row,s,p in zip(rws,col['status'],col['price']) if s=='OK' and p<max((row[1]-row[2]) if row[0]==0 else (row[2]-row[1]),0.0))

def _compute(rws,params,workers):
    n=len(rws);ctx=multiprocessing.get_context('spawn')
    with ProcessPoolExecutor(max_workers=workers,mp_context=ctx) as ex:
        parts=list(ex.map(_reference_part,_parts(rws,workers),[params]*workers))
        result={'n':n,'models':{m:{k:[v for p in parts for v in p['models'][m][k]] for k in parts[0]['models'][m]} for m in PANEL_MODELS}}
        if any(len(col[k])!=n for col in result['models'].values() for k in col):raise ValueError('panel: joined reference columns differ from n')
        items=[(i,rws[i]) for i in range(n) if candidate_before_grid(result,i)]
        grid={m:[None]*n for m in PANEL_MODELS}
        for done in ex.map(_grid_part,_parts(items,workers*4),[params]*(workers*4)):
            for i,oks in done:
                for m,ok in zip(PANEL_MODELS,oks):grid[m][i]=ok
    return result,grid,len(items)

def _columns(rws,result,grid):
    return {'side':[r[0] for r in rws],'k_over_s':[r[2]/r[1] for r in rws],'t':[scale_value(r[3]) for r in rws],'x':[row_x(r) for r in rws],
            'per_model':{m:{'status':list(result['models'][m]['status']),'flags':list(result['models'][m]['flags']),
                            'engine_evals':list(result['models'][m]['engine_evals']),'grid_ok':grid[m]} for m in PANEL_MODELS}}

def _counts(grid_rows,grid,rws,result):
    return {'grid_rows':grid_rows,'grid_false':{m:sum(1 for v in grid[m] if v is False) for m in PANEL_MODELS},
            'alo_ok_below_intrinsic':_below_intrinsic(rws,result['models']['alo'])}

def inputs(chain,params,workers,part=None):
    if isinstance(workers,bool) or not isinstance(workers,int) or workers<1:raise ValueError('workers: a positive integer')
    rws=chain_rows(chain);n=len(rws)
    if n==0:raise ValueError('panel: the chain has no rows')
    if part is None:
        result,grid,grid_rows=_compute(rws,params,workers)
        return {'n':n,'models':list(PANEL_MODELS),'mask':sum(1<<MODELS5.index(m) for m in PANEL_MODELS),'digest_form':ref_mod.DIGEST_FORM_MASK,
                'reference_sha256':ref_mod.result_digest(result),'grid':_grid(params),
                **_columns(rws,result,grid),'counts':_counts(grid_rows,grid,rws,result)}
    k,K=part
    if isinstance(k,bool) or isinstance(K,bool) or not (isinstance(k,int) and isinstance(K,int) and 0<=k<K):raise ValueError('panel part: (k, K) with 0 <= k < K')
    a,b=k*n//K,(k+1)*n//K
    if b<=a:raise ValueError('panel part: an empty part')
    sub=rws[a:b];result,grid,grid_rows=_compute(sub,params,workers)
    ref={m:{'status':list(result['models'][m]['status']),'flags':list(result['models'][m]['flags']),**{f:[_encode(v) for v in result['models'][m][f]] for f in FIELDS}}
         for m in PANEL_MODELS}
    return {'part':[k,K],'start':a,'stop':b,'n_total':n,'grid':_grid(params),
            **_columns(sub,result,grid),'reference_columns':ref,'counts':_counts(grid_rows,grid,sub,result)}

def join(parts):
    """The panel inputs of the K part documents, joined in row order (they must be the contiguous parts 0..K-1 of one
    chain), with the ocg-v1m digest of the joined py-reference result (decoded from the canonical value encoding, so the
    digest bytes equal one sequential run's) and the summed counts."""
    K=len(parts);at=0
    if K<1:raise ValueError('panel join: no parts')
    n=parts[0]['n_total'];cols={c:[] for c in ('side','k_over_s','t','x')}
    per={m:{c:[] for c in ('status','flags','engine_evals','grid_ok')} for m in PANEL_MODELS}
    ref={m:{c:[] for c in ('status','flags',*FIELDS)} for m in PANEL_MODELS}
    counts={'grid_rows':0,'grid_false':{m:0 for m in PANEL_MODELS},'alo_ok_below_intrinsic':0}
    for k,p in enumerate(parts):
        if p['part']!=[k,K] or p['start']!=at or p['n_total']!=n or p['stop']<=at:raise ValueError('panel join: parts are not contiguous')
        if p['grid']!=parts[0]['grid']:raise ValueError('panel join: parts differ in grid')   # A6P-01, FR5A-01
        for c in cols:cols[c]+=p[c]
        for m in PANEL_MODELS:
            for c in per[m]:per[m][c]+=p['per_model'][m][c]
            for c in ref[m]:ref[m][c]+=p['reference_columns'][m][c]
        counts['grid_rows']+=p['counts']['grid_rows'];counts['alo_ok_below_intrinsic']+=p['counts']['alo_ok_below_intrinsic']
        for m in PANEL_MODELS:counts['grid_false'][m]+=p['counts']['grid_false'][m]
        at=p['stop']
    if at!=n or any(len(v)!=n for v in cols.values()):raise ValueError('panel join: the parts do not cover the chain')
    result={'n':n,'models':{m:{'status':ref[m]['status'],'flags':ref[m]['flags'],**{f:[_decode(h) for h in ref[m][f]] for f in FIELDS}} for m in PANEL_MODELS}}
    return {'n':n,'models':list(PANEL_MODELS),'mask':sum(1<<MODELS5.index(m) for m in PANEL_MODELS),'digest_form':ref_mod.DIGEST_FORM_MASK,
            'reference_sha256':ref_mod.result_digest(result),'grid':parts[0]['grid'],
            **cols,'per_model':per,'counts':counts}

# ---- the one selection rule of H21.5 (the pre-flight replacement, H21.7; the host bench_panel holds the same rule) ----
def _level(t,tt,ratios):
    a=math.fabs(math.log(t/tt));return 0 if a<=math.log(ratios[0]) else 1 if a<=math.log(ratios[1]) else 2

def _in_band(p,band):
    op,b=band['op'],band['bound']
    return p>b if op=='gt' else p<b if op=='lt' else abs(p)<=b

def _candidate(doc,i):
    per=doc['per_model']
    return all(per[m]['status'][i]=='OK' and not per[m]['flags'][i]&LISTED_FLAGS and per[m]['grid_ok'][i] is True for m in PANEL_MODELS)

def candidate_order(doc,cell,cell_rule=None):
    """The H21.5 candidate order of one cell (an entry of the protocol cell rule) over a stored panel reference:
    [{'row', 'level', 'd'}] in (level, d, row) order."""
    r=cell_rule or rule();c=doc['rows_columns'];cat=c[r['category']['column']];pos=c[r['position']];sc=c[r['scale']]
    value=r['category']['labels'][cell['category']];out=[]
    for i in range(doc['rows']):
        if cat[i]!=value or pos[i] is None or not _in_band(pos[i],cell['band']) or not _candidate(doc,i):continue
        out.append((_level(sc[i],cell['scale_target'],r['level_ratios']),abs(pos[i]-cell['position_target'])+abs(math.log(sc[i]/cell['scale_target'])),i))
    out.sort();return [{'row':i,'level':lv,'d':d} for lv,d,i in out]

def selection(doc,rejected,cell_rule=None):
    """The one selection rule (H21.5) with the rejected set R: cells in cell order, the first row of each candidate order
    not in R and not held by an earlier cell. Returns {'indices', 'cells': [{'order' (up to the selected row), 'selected'}]};
    PanelCellEmpty(cell name) when a cell has no such row."""
    r=cell_rule or rule();held=set();cells=[];R=set(rejected)
    for cell in r['cells']:
        order=candidate_order(doc,cell,r)
        k=next((n for n,e in enumerate(order) if e['row'] not in R and e['row'] not in held),None)
        if k is None:raise PanelCellEmpty(cell['name'])
        sel=order[k];held.add(sel['row']);cells.append({'order':order[:k+1],'selected':{'row':sel['row'],'level':sel['level']}})
    return {'indices':[c['selected']['row'] for c in cells],'cells':cells}
