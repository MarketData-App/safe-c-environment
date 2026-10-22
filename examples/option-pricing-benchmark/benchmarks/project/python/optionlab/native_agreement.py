"""EX-12 (T21; Phase 2 Task 22 adapted by ruling R50): the C agreement check `native-agreement`, the native agreement check of
bench.json (`native.agreement`). The framework runs it with the restored, digest-verified pl-kernel, pl-worker and
libpl_inproc.so after the native build and before any timing of a bench run with C rows (tools/bench.py run_native_build; a
FAIL gates the run); `bench check --check native-agreement --native` runs it alone. optionlab.native_check registers it.

C = py-reference byte for byte: each comparison takes the ocg-v1 / ocg-v1m canonical bytes (optionlab.reference.canonical_result)
of the C result and of the py-reference result of the same rows and models. A difference is a defect of the C transliteration,
never a tolerance (R50 item e). Variant c-serial only (threads 0, workers direct; R50 item a) on the cells stdio warm and cold,
shm warm and cold and inproc warm (an inproc cold call is not applicable), and where named the kernel cell (pl-kernel, option
case, threads 0; its own --canonical bytes). Rows: the synthetic chain of the case seed (the tiers tiny 1, small 256, medium
1,024 and large 13,230 rows are prefixes of one prefix-stable chain, optionlab.synthetic), the oracle edge rows of the
protocol that use the case parameters, and the trap row.

Items (run_all keys; each records its compared count, which must be nonzero, and the seconds of its tasks):
- py_reference: the tiers tiny, small, medium with mask 7 (ocg-v1): every cell equals py-reference.
- large_sample: the full large tier with mask 7 on every cell; the rows j with j mod 26 = 0 (509 rows) of each C result equal
  py-reference of those rows (count: the 509 sample rows of every cell).
- baw_alo_reference (EX-16, T21-A05): baw (mask 8) on the medium tier and on the sample rows of the large tier, and alo (mask
  16) on the medium tier, on every cell: each C result equals py-reference of the same rows (equal_problems, the code of
  py_reference and large_sample); the reference of the small-tier rows is the per_model one; each part counts its rows.
- routes: for each tier and the large tier, every cell gives the bytes (large: the SHA-256) of the C result on stdio warm.
- limits (T19-A01 carry): mask 1 at 14,336, 14,337, 16,384 and 20,000 rows, the large rows tiled with period 13,230 (which
  does not divide the request limit), on every cell: each result equals py-reference of the same rows; the routes send one
  request up to the limit of benchlab.workload.request_limit(), then two.
- edge_rows: every oracle edge row of the protocol (oracle.json edge_rows and the kind 'edge' rows of the baw and alo parts)
  under the case parameters. The models for which py-reference evaluates the row give C = py-reference on every cell (the
  rows grouped by that mask); a model for which py-reference raises (the G4.8 trap class) ends the C call as a run defect on
  every cell. A row with its own (test-only) parameters is covered by the Task 11 C vectors (covered_by_vectors).
- per_model (G5.4): the masks 1, 2, 4, 8, 16 on tiny and small: the C ocg-v1m bytes on every cell equal the per-model
  py-reference bytes. The per-model reference is the model's part of one five-model py-reference run (reference.run evaluates
  each row and model alone); the item also compares a per-model run of the first rows with that part.
- projection (G1.6): every mask 1-31 on the oracle set (the edge rows on which no model raises), tiny and small. On every
  route cell each part of the mask's C result is bit-identical (status, flags, binary64 bits of every field) to the same part
  of the mask-31 C result of the same cell, and the mask-31 C result equals py-reference.
- trap (G4.8): the trap row optionlab.cvectors.RAISE_ROWS[5] (Task 11 census: py-reference raises for crr only). The masks
  1, 2, 8, 16 succeed and equal py-reference on every cell; the masks 4, 7, 31 end as a run defect (stdio and shm
  KERNEL_FAILURE, inproc return code 2, pl-kernel exit 3 reason kernel).
- counters (G4.8): the small tier with the masks 1, 2, 4, 8, 16, 31. pl-kernel evals= lists exactly the selected models,
  each with the sum of the py-reference engine_evals; pl-worker --counters on stdio and shm gives calls 0 and evals 0 for every
  unselected model and calls n and that sum for every selected model. The inproc counters are a test hook of the library
  (pl_inproc_price_stats, not exported; tests/project/test_inproc.c): no route of this check can read them.
- quantlib: the tiers tiny, small, medium with mask 7: agreement.compare(rows, C result, library.run result, params) at the
  section 3.7 fields of the protocol tolerances, zero failures and reduction MATCH (EX-16, ruling R74, T21-A08: the item FAILS
  unless the top-level state is calibrated-phase-2 and the values are those of the calibration proposal, calibration_problems);
  and the ALIGN_GRID probe (pl-kernel --case
  probe, models bsm, bjs, crr) against library.price_and_greeks within ALIGN_TOL for every field (C gives PL_GREEKS_DOMAIN
  exactly where QuantLib raises).
- baw_quantlib, alo_quantlib: the same on the baw (mask 8) and alo (mask 16) part at the block that the protocol locks
  (locked-g-baw2 with sstar_k 0; locked-g-alo2; an unlocked block FAILS the item, N6), and the probe of model 3 and model 4
  against reference.price_and_greeks on QuantLib's engine values (optionlab.checks.QL_BAW_ENGINE, QL_ALO_ENGINE).
- route_mechanics (R58, T21-A01: native-routes stays a per-run gate): the route-mechanics items of native-routes
  (optionlab.native_check.MECHANICS: sides, kernel, panel, zero-copy, gil, crash, shm, refusal, echo) through
  native_check.route_mechanics, the same functions on the same input, in this process after the pool work. Each item must
  PASS; the count is the passed items. The other native-routes items are covered here by routes, limits and py_reference.

Time (R50 item d: the check runs before every bench run with C rows, under the framework's smoke job deadline): the work runs
in a pool of spawned processes (at most MAX_WORKERS, the CPU limit of the check container; the panel job uses the same
pattern). Each task is single-threaded and every C row stays c-serial. The file records the task seconds of each item and the
wall seconds of each phase. REQUIRE-style: named problems, never an assert statement; an exception in a task is a problem of
its item with the exception type only (no traceback, no row value). H19 (A4R-03): a RunDefect is never an item result; every
broad handler re-raises it first, so a run defect of a Python model ends the check (FAIL), as in optionlab.native_check. The
models that raise on an edge row or the trap row are optionlab.cvectors.raising_models (the census record site)."""
import hashlib, json, multiprocessing, os, re, struct, subprocess, tempfile, time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from optionlab.contract import ALL_MODELS, FIELDS, MODELS5
from optionlab.models import RunDefect
from optionlab.synthetic import SIZES

PROJECT=Path(__file__).resolve().parents[2]                 # <project dir>/benchmarks/project
EXAMPLE=PROJECT.parents[1]                                  # <project dir>
CASE_FILE=PROJECT/'cases'/'option-chain-greeks.json'
WIRED_HEADER=EXAMPLE/'include'/'pl_evaluate.h'
WIRED_LINE='#define PL_MASK_WIRED PL_MASK_MODELS5'
FILE='native-agreement.json'
TIERS=('tiny','small','medium')
LARGE_ROWS=SIZES['large']
LARGE_SAMPLE_STEP=26
ROUTE_CELLS=('stdio-warm','stdio-cold','shm-warm','shm-cold','inproc-warm')
KERNEL_CELL='kernel'
ALL_CELLS=ROUTE_CELLS+(KERNEL_CELL,)
BASE_CELL='stdio-warm'                                      # the C serial result that `routes` compares the other cells with
CASE_MASK=7;ALL_MASK=31
PER_MODEL_MASKS=(1,2,4,8,16)
PROJECTION_SETS=('oracle','tiny','small')
LIMIT_SIZES=(14336,14337,16384,20000);LIMIT_MASK=1
TRAP_PASS_MASKS=(1,2,8,16);TRAP_FAIL_MASKS=(4,7,31)
COUNTER_MASKS=(1,2,4,8,16,31);COUNTER_TIER='small';COUNTER_ROUTES=('stdio','shm')
INDEPENDENCE_ROWS=4
QL_ITEMS={7:'quantlib',8:'baw_quantlib',16:'alo_quantlib'}  # the mask of each QuantLib item
QL_MODELS={'quantlib':('bsm','bjs','crr'),'baw_quantlib':('baw',),'alo_quantlib':('alo',)}
ITEMS=('py_reference','large_sample','baw_alo_reference','routes','limits','edge_rows','per_model','projection','trap','counters',
       'quantlib','baw_quantlib','alo_quantlib','route_mechanics')
HEAVY_PARTS=(('baw_medium',('tier',8,'medium'),'bytes','n'),('baw_large_sample',('large',8,'large'),'sample_bytes','sample_n'),
             ('alo_medium',('tier',16,'medium'),'bytes','n'))     # EX-16 (T21-A05): (part, C outcome key, field, count key)
MAX_WORKERS=4                                               # the cpu.max of a bench check container (4 CPUs)
GEN_CHUNK=512;REF_CHUNK=64;ALO_CHUNK=8;BSM_CHUNK=4096;EDGE_CHUNK=4
KERNEL_SECONDS=600.0
PROBE_IN=struct.Struct('<9d');PROBE_OUT=struct.Struct('<II7d')
PROBE_FIELDS=('price','delta','gamma','theta','vega','rho')
RUN_DEFECTS={'stdio':('FrameError','KERNEL_FAILURE'),'shm':('FrameError','KERNEL_FAILURE'),
             'inproc':('RuntimeError','libpl_inproc.so returned 2'),KERNEL_CELL:('KernelExit','exit 3 reason kernel')}
COMPARE_KEYS=('eligible','failures','reduction','multi_root','boundary_ambiguous','flat_vega','model_errors','rounding_band',
              'band_status_mismatch')
LABEL_BAD=re.compile(r'[^A-Za-z0-9 ._:,()=+-]')
_REASON=re.compile(r'^[a-z_]{1,24}$')

class NativeAgreementError(Exception):
    """A precondition of the check that does not hold (a named exception; never a Python assert)."""

# ---- the case, the rows and the result helpers -----------------------------------------------------------------------
_CASE=None
def _case():
    """(case parameters, case seed) of cases/option-chain-greeks.json (cached per process)."""
    global _CASE
    if _CASE is None:
        from optionlab.params import params_from_manifest
        manifest=json.loads(CASE_FILE.read_text());seed=manifest['parameters']['seed']['value']
        if isinstance(seed,bool) or not isinstance(seed,int):raise NativeAgreementError('the case seed is not an integer')
        _CASE=(params_from_manifest(manifest),seed)
    return _CASE

def case_params():return _case()[0]

def models_of(mask):
    from optionlab.native_codec import models_of as of
    return of(mask)

def mask_of(models):
    from optionlab.native_codec import mask_of as of
    return of(tuple(models))

def mask_wired():
    """Plan Step 1 (approver finding L1): include/pl_evaluate.h holds exactly one line `#define PL_MASK_WIRED PL_MASK_MODELS5`
    (all five models wired; the ALO stub is gone)."""
    try:text=WIRED_HEADER.read_text()
    except OSError:return False
    return sum(1 for line in text.splitlines() if line.strip()==WIRED_LINE)==1

def sample_indices(n=LARGE_ROWS):
    """The rows j with j mod LARGE_SAMPLE_STEP = 0 of the large tier (509 rows)."""
    return list(range(0,n,LARGE_SAMPLE_STEP))

def chain_of(rows):
    """The request columns of row tuples (side, S, K, T, bid, ask, r, q), the chain form of optionlab.native_codec."""
    return {'n':len(rows),**{k:[r[j] for r in rows] for j,k in enumerate(('side','S','K','T','bid','ask','r','q'))}}

def tile(rows,n):
    """n rows: row i is rows[i mod len(rows)]."""
    return [rows[i%len(rows)] for i in range(n)]

def select(result,models,rows=None):
    """The part of a result for `models` (each part must be present), restricted to the row indices `rows` (None: all rows);
    every column, the optional ones too."""
    if any(m not in result['models'] for m in models):raise ValueError('select: a model part is missing')
    if rows is None:return {'n':result['n'],'models':{m:{k:list(v) for k,v in result['models'][m].items()} for m in models}}
    rows=list(rows)
    return {'n':len(rows),'models':{m:{k:[v[i] for i in rows] for k,v in result['models'][m].items()} for m in models}}

def concat(results):
    """The rows of results with the same model parts, in order (every column of each part)."""
    first=results[0]['models']
    if any(set(r['models'])!=set(first) for r in results):raise ValueError('concat: the model parts differ')
    return {'n':sum(r['n'] for r in results),'models':{m:{k:[v for r in results for v in r['models'][m][k]] for k in first[m]} for m in first}}

def merge(*results):
    """The model parts of results of the same rows in one result."""
    if len({r['n'] for r in results})!=1:raise ValueError('merge: the row counts differ')
    out={'n':results[0]['n'],'models':{}}
    for r in results:out['models'].update(r['models'])
    return out

def tile_result(result,n):
    """The result of tile(rows, n) from the result of rows (every row is evaluated alone)."""
    N=result['n']
    return {'n':n,'models':{m:{k:[v[i%N] for i in range(n)] for k,v in col.items()} for m,col in result['models'].items()}}

def digest_rows(result,indices):
    """SHA-256 (hex) of the canonical bytes of the result restricted to the listed rows."""
    from optionlab.reference import canonical_result
    return hashlib.sha256(canonical_result(select(result,tuple(result['models']),indices))).hexdigest()

def _bits(v):return struct.pack('<d',float(v))

def projection_problems(full,part,mask):
    """G1.6: `part` must hold exactly the models of `mask`, the row count of `full`, and for each model the status, the flags
    and the binary64 bits of every field of the same part of `full` (the mask-31 result). One problem per differing part."""
    want=models_of(mask);got=tuple((part.get('models') or {}));problems=[]
    if set(got)!=set(want):problems.append(f'mask {mask}: parts {",".join(sorted(got))} are not the models {",".join(want)}')
    if part.get('n')!=full.get('n'):return problems+[f'mask {mask}: the row count differs']
    for m in want:
        if m not in got:continue
        if m not in full.get('models',{}):problems.append(f'mask {mask}: the mask-31 result has no {m} part');continue
        a=full['models'][m];b=part['models'][m];bad=[]
        if list(a['status'])!=list(b['status']):bad.append('status')
        if list(a['flags'])!=list(b['flags']):bad.append('flags')
        bad+=[f for f in FIELDS if len(a[f])!=len(b[f]) or any(_bits(x)!=_bits(y) for x,y in zip(a[f],b[f]))]
        if bad:problems.append(f'mask {mask} {m}: {",".join(bad)} differ from the mask-31 part')
    return problems

# ---- judging (pure functions of the outcomes; the light tests mutate their inputs) --------------------------------------
# An outcome is a dict: {'n', 'bytes' (canonical bytes), 'result', 'sha256', 'sample_bytes', 'requests'} of a C result, or
# {'raised': exception type, 'detail': fixed text} of a C call that failed. `c` maps (cell,) + key to an outcome.
def _key(key):return ' '.join(str(x) for x in key)

def _why(o):
    if not isinstance(o,dict):return 'missing'
    if 'raised' in o:return f"{o['raised']} {o.get('detail','')}".strip()
    return 'no such field'

def equal_problems(c,want,cells,field='bytes',count_key='n'):
    """Byte identity with py-reference: for each key of `want` and each cell, c[(cell,) + key][field] == want[key].
    (problems, compared rows: the outcome's `count_key`, 'sample_n' for the sample of the large tier)."""
    problems=[];count=0
    for key,value in want.items():
        for cell in cells:
            o=c.get((cell,)+tuple(key))
            if not isinstance(o,dict) or field not in o:problems.append(f'{cell} {_key(key)}: no C result ({_why(o)})');continue
            count+=int(o.get(count_key,0))
            if o[field]!=value:problems.append(f'{cell} {_key(key)}: C differs from py-reference')
    return problems,count

def routes_problems(c,keys,cells,field='bytes',base=BASE_CELL):
    """Route identity: for each key, every cell gives the field of the C serial result on `base`. (problems, compared rows)."""
    problems=[];count=0
    for key in keys:
        b=c.get((base,)+tuple(key))
        if not isinstance(b,dict) or field not in b:problems.append(f'{base} {_key(key)}: no C result ({_why(b)})');continue
        for cell in cells:
            if cell==base:continue
            o=c.get((cell,)+tuple(key))
            if not isinstance(o,dict) or field not in o:problems.append(f'{cell} {_key(key)}: no C result ({_why(o)})');continue
            count+=int(o.get('n',0))
            if o[field]!=b[field]:problems.append(f'{cell} {_key(key)}: differs from the C result on {base}')
    return problems,count

def is_run_defect(cell,o):
    """True when the outcome is the run defect of the cell: KERNEL_FAILURE (stdio, shm), return code 2 (inproc), exit 3 with
    reason kernel (pl-kernel)."""
    kind=KERNEL_CELL if cell==KERNEL_CELL else cell.split('-')[0]
    return isinstance(o,dict) and (o.get('raised'),o.get('detail'))==RUN_DEFECTS[kind]

def defect_problems(c,keys,cells):
    """Each key ends as a run defect on every cell. (problems, compared calls)."""
    problems=[];count=0
    for key in keys:
        for cell in cells:
            o=c.get((cell,)+tuple(key));count+=1
            if not is_run_defect(cell,o):problems.append(f'{cell} {_key(key)}: no run defect ({"a result" if isinstance(o,dict) and "bytes" in o else _why(o)})')
    return problems,count

def projection_set_problems(c,cells,sets,masks=range(1,ALL_MASK)):
    """G1.6 on every cell and set: each mask's C result against the mask-31 C result of the same cell (projection_problems).
    (problems, compared rows)."""
    problems=[];count=0
    for cell in cells:
        for s in sets:
            full=c.get((cell,'proj',ALL_MASK,s))
            if not isinstance(full,dict) or 'result' not in full:problems.append(f'{cell} {s}: no mask-31 C result ({_why(full)})');continue
            for mask in masks:
                o=c.get((cell,'proj',mask,s))
                if not isinstance(o,dict) or 'result' not in o:problems.append(f'{cell} {s} mask {mask}: no C result ({_why(o)})');continue
                count+=int(o['result']['n'])
                problems+=[f'{cell} {s} {p}' for p in projection_problems(full['result'],o['result'],mask)]
    return problems,count

def counter_problems(observed,want,n):
    """G4.8 counters. observed: {(source, mask): counts} with source 'kernel' ({'evals': {selected model: count}}) or a
    pl-worker route ({'calls', 'evals': {model: count} for all five models, 'requests', 'exit'}); want: {model: sum of the
    py-reference engine_evals}; n: the rows. (problems, compared counters)."""
    problems=[];count=0
    for (source,mask),o in sorted(observed.items()):
        sel=models_of(mask);tag=f'{source} mask {mask}'
        if not isinstance(o,dict) or not isinstance(o.get('evals'),dict):problems.append(f'{tag}: no counters ({_why(o)})');continue
        if source==KERNEL_CELL:
            count+=len(sel)
            if tuple(o['evals'])!=sel:problems.append(f'{tag}: evals= lists {",".join(o["evals"])}, not the selected models')
            elif any(o['evals'][m]!=want[m] for m in sel):problems.append(f'{tag}: evals= differs from the py-reference engine_evals')
            continue
        count+=len(MODELS5)
        if set(o['evals'])!=set(MODELS5) or set(o.get('calls') or {})!=set(MODELS5):problems.append(f'{tag}: the counters do not list the five models');continue
        for m in MODELS5:
            if m in sel and (o['calls'][m]!=n or o['evals'][m]!=want[m]):problems.append(f'{tag}: {m} calls or evals differ (calls n, evals py-reference)')
            if m not in sel and (o['calls'][m] or o['evals'][m]):problems.append(f'{tag}: the unselected model {m} has a nonzero count')
        if o.get('requests',1)!=1 or o.get('exit',0)!=0:problems.append(f'{tag}: requests or exit code')
    return problems,count

def probe_problems(model,points,c_rows,ql_rows):
    """The ALIGN_GRID probe of one model: C status 0 where QuantLib gives values (iv = sigma; every PROBE_FIELDS value within
    ALIGN_TOL by optionlab.checks._rel), 1 where QuantLib raises an ArithmeticError, 2 where it raises a run defect.
    (problems, compared points)."""
    from optionlab.checks import ALIGN_TOL, _rel
    problems=[];count=0
    if not isinstance(c_rows,list) or not isinstance(ql_rows,list) or len(c_rows)!=len(points) or len(ql_rows)!=len(points):
        return [f'probe {model}: no complete C or QuantLib probe'],0
    for k,(p,cr,q) in enumerate(zip(points,c_rows,ql_rows)):
        st,_,*vals=cr;count+=1;tag=f'probe {model} point {k}'
        if 'ok' in q:
            if st!=0:problems.append(f'{tag}: C status {st} where QuantLib gives values');continue
            if _bits(vals[0])!=_bits(p[-1]):problems.append(f'{tag}: iv is not sigma')
            bad=[f for j,f in enumerate(PROBE_FIELDS,1) if not _rel(vals[j],q['ok'][f])<=ALIGN_TOL[f]]
            if bad:problems.append(f'{tag}: {",".join(bad)} outside ALIGN_TOL')
        elif st!=(1 if 'domain' in q else 2):problems.append(f'{tag}: C status {st} where QuantLib raises')
    return problems,count

def item(problems,count,seconds,**extra):
    """One item result: PASS needs no problem and a nonzero compared count."""
    return {'status':'PASS' if not problems and count>0 else 'FAIL','count':int(count),'seconds':round(float(seconds),1),
            'problem_count':len(problems),'problems':list(problems[:40]),**extra}

def heavy_item(c,want,seconds,cells=ALL_CELLS,task_problems=()):
    """EX-16 (T23; T21-A05): the item baw_alo_reference. `want`: {part: the py-reference bytes of HEAVY_PARTS}. Each part is
    compared on every cell by equal_problems (the code of py_reference and large_sample); the count is the compared rows of
    all parts, `parts` the count of each part; a part without a py-reference result or without a compared row is a problem
    that names it, and so is each task problem of the item."""
    problems=list(task_problems);counts={}
    for name,key,field,count_key in HEAVY_PARTS:
        if name not in want:problems.append(f'{name}: no py-reference result');counts[name]=0;continue
        pr,n=equal_problems(c,{key:want[name]},cells,field=field,count_key=count_key);problems+=pr;counts[name]=n
        if not n:problems.append(f'{name}: no compared row')
    return item(problems,sum(counts.values()),seconds,parts=counts)

def mechanics_item(results,seconds):
    """R58 (T21-A01): the item route_mechanics from the results of optionlab.native_check.route_mechanics ({name: {status,
    reason}}). PASS needs every native_check.MECHANICS item present and PASS; the count is the passed items; each failed or
    missing item is a problem that names it."""
    from optionlab.native_check import MECHANICS
    got={k:r for k,r in results.items() if k in MECHANICS and isinstance(r,dict)}
    problems=[f"{k}: {str(got[k].get('reason') or 'FAIL')[:80]}" for k in MECHANICS if k in got and got[k].get('status')!='PASS']
    problems+=[f'{k}: not run' for k in MECHANICS if k not in got]
    return item(problems,sum(1 for r in got.values() if r.get('status')=='PASS'),seconds,results={k:got[k].get('status') for k in got})

def check_row(items,seconds):
    """The check row (container/bench-coordinator.py check_result keeps `counts` and `label` only): items, passed, seconds, the
    compared count of each item and ok_<item> 1 or 0 (31 keys, at most 32); the label names the failed items."""
    good=bool(items) and set(items)==set(ITEMS) and all(r['status']=='PASS' for r in items.values())
    counts={'items':len(items),'passed':sum(r['status']=='PASS' for r in items.values()),'seconds':int(seconds)}
    counts.update({k:int(r['count']) for k,r in items.items()})
    counts.update({'ok_'+k:int(r['status']=='PASS') for k,r in items.items()})
    failed=', '.join(f"{k}: {(r['problems'] or ['no compared row'])[0]}" for k,r in items.items() if r['status']!='PASS')
    return {'status':'PASS' if good else 'FAIL','files':[FILE],'counts':counts,
            'label':LABEL_BAD.sub(' ',('failed ' if failed else 'all items passed')+failed)[:120]}

# ---- pool tasks (top-level functions: a spawned worker imports this module) --------------------------------------------
def _timed(fn,*args):
    t=time.monotonic()
    try:value=fn(*args);error=None
    except RunDefect:raise                  # H19: a run defect is never an item result (it ends the check)
    except Exception as exc:value=None;error=type(exc).__name__
    return {'value':value,'error':error,'seconds':time.monotonic()-t}

def _task_records(j0,j1):
    """The synthetic records j0 .. j1 - 1 of the case seed (optionlab.synthetic.row; generate is these rows in order)."""
    from optionlab.synthetic import row
    p,seed=_case()
    return [row(j,seed,p) for j in range(j0,j1)]

def _task_reference(rows,models):
    from optionlab.reference import run
    return run(rows,case_params(),models=tuple(models))

def _task_edges(rows):
    """Per row, per model: ('ok', py-reference result of the row for that model) or ('raised', model) for a model of
    optionlab.cvectors.raising_models (the census record site: the G4.8 trap class, and a recorded BAW or ALO run defect; any
    other RunDefect ends the check, H19). The census evaluates under params.CASE, which must equal the case parameters."""
    from optionlab.cvectors import raising_models
    from optionlab.params import CASE
    from optionlab.reference import run
    p=case_params()
    if p!=CASE:raise NativeAgreementError('the case parameters differ from params.CASE (the census parameters)')
    out=[]
    for row in rows:
        raised=set(raising_models(row))
        out.append({m:('raised',m) if m in raised else ('ok',run([row],p,models=(m,))) for m in MODELS5})
    return out

def _cell(cell):
    route,mode=cell.split('-');return route,mode

def _c_calls(cell,mask,chains):
    """[(key, raw C result or the exception, requests)] of the chains [(key, rows)] on one route cell, c-serial: warm = one
    backend for the chains (a new one after a failed call); cold = a backend per call (backends.cold_price)."""
    from optionlab import backends
    from benchlab import native_worker as nw
    route,mode=_cell(cell);out=[];b=None
    try:
        for key,rows in chains:
            prepared=backends.prepare(chain_of(rows),route)
            try:
                if mode=='cold':raw=backends.cold_price('c-serial','direct',route,prepared,models=mask)
                else:
                    if b is None:
                        b=backends.start_backend('c-serial','direct',route,models=mask);b.start()
                    raw=b.price(prepared)
                out.append((key,raw,nw.LAST_STATS.get('requests')))
            except RunDefect:raise
            except Exception as exc:
                out.append((key,exc,None))
                if b is not None:b.close();b=None
    finally:
        if b is not None:b.close()
    return out

def _raised(exc):
    """The outcome of a failed C call: the exception type and a fixed detail (the frame error name, or the inproc return code)."""
    from benchlab import native_worker as nw
    detail=''
    if isinstance(exc,nw.FrameError):detail=str(exc.name)[:40]
    elif isinstance(exc,RuntimeError) and re.fullmatch(r'libpl_inproc\.so returned -?[0-9]{1,3}',str(exc)):detail=str(exc)
    return {'raised':type(exc).__name__,'detail':detail}

def _outcome(res,how):
    """The outcome of one C result: 'bytes' (canonical bytes), 'result' (bytes and the result), ('sample', rows) (SHA-256, and
    the canonical bytes and the count `sample_n` of the rows) or 'digest' (SHA-256)."""
    from optionlab.reference import canonical_result
    data=canonical_result(res);o={'n':res['n']};kind=how[0] if isinstance(how,tuple) else how
    if kind=='sample':
        o['sha256']=hashlib.sha256(data).hexdigest();o['sample_bytes']=canonical_result(select(res,tuple(res['models']),how[1]));o['sample_n']=len(how[1])
    elif kind=='digest':o['sha256']=hashlib.sha256(data).hexdigest()
    else:
        o['bytes']=data
        if kind=='result':o['result']=res
    return o

def _kernel(args):
    """(exit code, PLK1 summary or None) of pl-kernel with `args`, started from its verified descriptor (as
    benchlab.native_kernel starts it), without the handshake."""
    from benchlab import native_kernel as nk, native_worker as nw
    path,digest=nw.restored('pl-kernel')
    fd,identity=nw.open_verified(str(path),digest)
    try:
        proc=subprocess.Popen([str(path)]+list(args),executable=nw.fd_path(fd),stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL,close_fds=True,pass_fds=(fd,))
        try:nw.confirm_verified(fd,digest,identity,str(path))
        except nw.BinaryRefused:
            proc.kill();proc.communicate();raise
    finally:os.close(fd)
    try:out,_=proc.communicate(timeout=KERNEL_SECONDS)
    except subprocess.TimeoutExpired:
        proc.kill();proc.communicate();raise
    lines=[x for x in out[-65536:].decode('ascii','replace').splitlines() if x.startswith('PLK1 ')]
    try:summary=nk.parse_summary(lines[-1]) if lines else None
    except ValueError:summary=None
    return proc.returncode,summary

def _kernel_failure(code,summary):
    reason=(summary or {}).get('extra',{}).get('reason') if isinstance(summary,dict) else None
    return {'raised':'KernelExit','detail':f'exit {code} reason {reason if isinstance(reason,str) and _REASON.fullmatch(reason) else "none"}'}

def _kernel_outcome(mask,rows,how):
    """pl-kernel (option case, threads 0, --models mask) on the rows: the outcome of its --canonical bytes, which must equal the
    canonical bytes of its --output records, and whose FNV-1a 64 must be the PLK1 digest=."""
    from optionlab import native_codec as nc
    from optionlab.reference import canonical_result
    n=len(rows)
    with tempfile.TemporaryDirectory() as tmp:
        src=Path(tmp)/'input';dst=Path(tmp)/'output';can=Path(tmp)/'canonical'
        src.write_bytes(nc.pack_requests(chain_of(rows)))
        code,summary=_kernel(['--case','option-chain-greeks','--input',str(src),'--records',str(n),'--threads','0','--models',str(mask),
                              '--output',str(dst),'--canonical',str(can)])
        if code!=0 or summary is None or summary.get('status')!='OK':return _kernel_failure(code,summary)
        records=dst.read_bytes();canonical=can.read_bytes()
    try:res=nc.materialize(records,n,mask)
    except ValueError as exc:return {'raised':type(exc).__name__,'detail':'materialize refused'}
    if summary.get('records')!=n or canonical_result(res)!=canonical or summary['extra'].get('digest')!='%016x'%nc.fnv1a64(canonical):
        return {'raised':'KernelOutput','detail':'the canonical file, the output records and digest= differ'}
    return _outcome(res,how)

def _task_c(cell,mask,jobs):
    """{key: outcome} of jobs [(key, rows, how)] on one cell with one mask."""
    from optionlab import native_codec as nc
    nc.check_mask(mask)
    if cell==KERNEL_CELL:return {key:_kernel_outcome(mask,rows,how) for key,rows,how in jobs}
    hows={key:how for key,_,how in jobs};out={}
    for key,raw,requests in _c_calls(cell,mask,[(key,rows) for key,rows,_ in jobs]):
        if isinstance(raw,BaseException):out[key]=_raised(raw);continue
        try:out[key]=dict(_outcome(nc.materialize(raw['records'],raw['n'],raw['mask']),hows[key]),requests=requests)
        except ValueError as exc:out[key]={'raised':type(exc).__name__,'detail':'materialize refused'}
    return out

def _task_limits(cell,rows,sizes):
    """{('limit', LIMIT_MASK, n): outcome with the SHA-256 and the request count} of tile(rows, n) for each n."""
    return {k:v for n in sizes for k,v in _task_c(cell,LIMIT_MASK,[(('limit',LIMIT_MASK,n),tile(rows,n),'digest')]).items()}

def _pairs(text):
    """{model: count} of `bsm:N,bjs:N,...` (ValueError for another form)."""
    out={}
    for part in text.split(','):
        m,_,v=part.partition(':')
        if m not in MODELS5 or m in out or not re.fullmatch(r'0|[1-9][0-9]{0,19}',v):raise ValueError('counter list')
        out[m]=int(v)
    return out

def _task_kernel_counts(mask,rows):
    """pl-kernel --models mask on the rows: {'evals': {model: count} of evals= in MODELS5 order, 'models': the printed mask}."""
    from optionlab import native_codec as nc
    with tempfile.TemporaryDirectory() as tmp:
        src=Path(tmp)/'input';src.write_bytes(nc.pack_requests(chain_of(rows)))
        code,summary=_kernel(['--case','option-chain-greeks','--input',str(src),'--records',str(len(rows)),'--threads','0','--models',str(mask)])
    if code!=0 or summary is None or summary.get('status')!='OK':return _kernel_failure(code,summary)
    extra=summary['extra'];evals=_pairs(extra.get('evals',''))
    if extra.get('models')!=str(mask):raise ValueError('models= differs from --models')
    return {'evals':evals}

def _task_worker_counts(route,mask,rows):
    """pl-worker --counters (G4.8 test option) on one route: one c-serial request of the rows, then SHUTDOWN; the totals of the
    PLW1 line {'calls', 'evals', 'requests', 'exit'}."""
    from optionlab import backends, native_codec as nc
    backends.check_row('c-serial','direct',route);nc.check_mask(mask)
    if route not in COUNTER_ROUTES:raise ValueError('the counters are a pl-worker option (stdio, shm)')
    class Counted(backends.BACKENDS[route]):
        def _argv(self,path):return super()._argv(path)+['--counters']
    b=Counted('c-serial','direct',models=mask,echo=False)
    try:
        b.start();raw=b.price(backends.prepare(chain_of(rows),route))
    finally:code=b.close()
    if raw['n']!=len(rows):raise ValueError('row count')
    lines=[x for x in b.worker.stderr_head.decode('ascii','replace').splitlines() if x.startswith('PLW1 ')]
    if not lines:raise ValueError('no PLW1 line')
    fields=dict(p.split('=',1) for p in lines[-1].split()[1:] if '=' in p)
    return {'calls':_pairs(fields.get('calls','')),'evals':_pairs(fields.get('evals','')),'requests':int(fields.get('requests','-1')),'exit':code}

def _task_probe(points):
    """pl-kernel --case probe on points [(model index, side, S, K, T, r, q, sigma)]: [(status, band, seven binary64)]."""
    with tempfile.TemporaryDirectory() as tmp:
        src=Path(tmp)/'input';dst=Path(tmp)/'output'
        src.write_bytes(b''.join(PROBE_IN.pack(*(float(x) for x in p),0.0) for p in points))
        code,summary=_kernel(['--case','probe','--input',str(src),'--records',str(len(points)),'--output',str(dst)])
        if code!=0 or summary is None or summary.get('status')!='OK':raise NativeAgreementError('the probe run failed')
        data=dst.read_bytes()
    if len(data)!=PROBE_OUT.size*len(points):raise NativeAgreementError('the probe output length')
    return [PROBE_OUT.unpack_from(data,PROBE_OUT.size*i) for i in range(len(points))]

def _task_ql_probe(model,grid):
    """QuantLib at the ALIGN_GRID points of one model: library.price_and_greeks (bsm, bjs, crr), or reference.price_and_greeks
    on QuantLib's engine values (baw: QL_BAW_ENGINE, alo: QL_ALO_ENGINE). Per point {'ok': values} or {'domain': type} (an
    ArithmeticError: an engine error, a refused point). A run defect ends the check (H19), as in the alignment checks."""
    from optionlab import library, reference
    from optionlab.checks import QL_ALO_ENGINE, QL_BAW_ENGINE
    p=case_params();r,q=p.rate,p.dividend_yield;out=[]
    for side,S,K,T,s in grid:
        try:
            if model in ('baw','alo'):g=reference.price_and_greeks(model,side,S,K,T,r,q,s,p,engine=QL_BAW_ENGINE if model=='baw' else QL_ALO_ENGINE)
            else:g=library.price_and_greeks(model,side,S,K,T,r,q,s,p)
            out.append({'ok':{f:float(g[f]) for f in PROBE_FIELDS}})
        except RunDefect:raise
        except ArithmeticError as exc:out.append({'domain':type(exc).__name__})
    return out

def _task_library(rows,models):
    from optionlab import library
    return library.run(rows,case_params(),models=tuple(models))

def _task_compare(rows,result,ref,tol,models):
    """agreement.compare(rows, C result, QuantLib result, params) at `tol` (None: agreement.TOLERANCES) for `models`."""
    from optionlab import agreement
    v=agreement.compare(rows,result,ref,case_params(),tol=tol if tol is not None else agreement.TOLERANCES,models=tuple(models))
    return {k:v[k] for k in COMPARE_KEYS}

# ---- the run ------------------------------------------------------------------------------------------------------------
def pool_workers():
    try:n=len(os.sched_getaffinity(0))
    except (AttributeError,OSError):n=1
    return max(1,min(MAX_WORKERS,n))

def _chunks(seq,size):return [seq[i:i+size] for i in range(0,len(seq),size)]

class _Pool:
    """The spawned process pool; the task seconds and the task errors are kept per item."""
    def __init__(self,ex):self.ex=ex;self.seconds={};self.errors={};self.tasks={}
    def submit(self,item_name,fn,*args):
        self.tasks[item_name]=self.tasks.get(item_name,0)+1
        return (item_name,self.ex.submit(_timed,fn,*args))
    def get(self,handle):
        name,future=handle
        try:r=future.result()
        except RunDefect:raise                                                                 # H19: a task's run defect ends the check
        except Exception as exc:r={'value':None,'error':type(exc).__name__,'seconds':0.0}     # a worker that died (BrokenProcessPool)
        self.seconds[name]=self.seconds.get(name,0.0)+r['seconds']
        if r['error'] is not None:self.errors.setdefault(name,[]).append(r['error']);return None
        return r['value']
    def task_problems(self,name):return [f'task error {e}' for e in self.errors.get(name,[])]

def _adapter():
    from benchlab.workload import load_case_adapter
    return load_case_adapter(json.loads(CASE_FILE.read_text()),selector='all')

def edge_inputs():
    """([(name, row)], covered_by_vectors names): the oracle edge rows of the protocol (oracle.json edge_rows and the kind
    'edge' rows of the baw and alo parts) under the case parameters; a row with its own parameters is test-only."""
    from optionlab import protocol
    fx=protocol.oracle()['oracle'];rows=[];covered=[]
    for part,e in [('edge_rows',e) for e in fx['edge_rows']]+[(m,e) for m in ('baw','alo') for e in fx[m] if e.get('kind')=='edge']:
        name=f"{part}:{e['name']}"
        if e.get('params'):covered.append(name)
        else:rows.append((name,tuple(e['row'])))
    return rows,covered

def _large_rows(P,a,seed,tmp):
    """The row tuples of the synthetic large tier of the case seed (the pool computes the records; the bytes equal
    adapter.synthesize, which the first 256 rows confirm), loaded through the adapter as a bench run loads them."""
    from optionlab.contract import rows as chain_rows
    from optionlab.synthetic import KEYS
    parts=[P.submit('generate',_task_records,j,min(LARGE_ROWS,j+GEN_CHUNK)) for j in range(0,LARGE_ROWS,GEN_CHUNK)]
    records=[]
    for h in parts:
        got=P.get(h)
        if got is None:raise NativeAgreementError('the synthetic rows')
        records+=got
    doc=lambda recs:json.dumps({'s':'ok',**{k:[r[k] for r in recs] for k in KEYS}}).encode()
    if doc(records[:SIZES['small']])!=a.synthesize(SIZES['small'],seed):raise NativeAgreementError('the pool rows differ from the generator')
    data=doc(records);path=Path(tmp)/'large.json';path.write_bytes(data)
    return chain_rows(a.load({'path':str(path),'sha256':hashlib.sha256(data).hexdigest()}))

CALIBRATED_STATE='calibrated-phase-2'       # ruling R74: the top-level tolerances state after the EX-16 calibration
CALIBRATION_KEYS=('proposal','proposal_sha256','verdict')

def _values_digest(values):
    return hashlib.sha256(json.dumps(values,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def calibration_problems(tolerances,base=PROJECT):
    """Ruling R74 item 5 (T21-A08): the problems of the top-level tolerances that the quantlib item takes. The state must be
    CALIBRATED_STATE; `calibration` names the proposal file of the calibration (a relative path inside the protocol
    directory of `base`, a regular file), its sha256 and the verdict reference; the file must have that sha256, and the
    digest of the top-level tolerance values must equal the digest of the proposal's current values of its top-level fields
    (the same field set). Every other case is a named problem (never an exception)."""
    state=tolerances.get('state') if isinstance(tolerances,dict) else None
    if state!=CALIBRATED_STATE:return [f'tolerances not calibrated (state {str(state)[:40]})']
    rec=tolerances.get('calibration')
    if not isinstance(rec,dict) or set(rec)!=set(CALIBRATION_KEYS) or not all(isinstance(rec[k],str) for k in CALIBRATION_KEYS):
        return ['tolerances.calibration is not a record of proposal, proposal_sha256 and verdict']
    rel=rec['proposal'];parts=rel.split('/')
    if not re.fullmatch(r'protocol/[a-z0-9][a-z0-9._-]{0,80}\.json',rel) or '..' in parts:return ['tolerances.calibration.proposal is not a file of the protocol directory']
    path=Path(base)/rel
    if path.is_symlink() or not path.is_file():return ['the calibration proposal file is missing']
    data=path.read_bytes()
    if hashlib.sha256(data).hexdigest()!=rec['proposal_sha256']:return ['the calibration proposal file differs from its sha256']
    try:fields=json.loads(data)['fields']
    except (ValueError,KeyError,TypeError):return ['the calibration proposal file is not a proposal record']
    if not isinstance(fields,dict):return ['the calibration proposal file is not a proposal record']
    try:want={k:v['current'] for k,v in fields.items() if '.' not in k}
    except (KeyError,TypeError):return ['the calibration proposal file is not a proposal record']
    got={k:v for k,v in tolerances.items() if not isinstance(v,(dict,str))}
    if _values_digest(got)!=_values_digest(want):return ['the top-level tolerance values differ from the calibration proposal']
    return []

def _tolerance(name):
    """(tolerance dict or None for agreement.TOLERANCES, state, problems) of a QuantLib item: quantlib takes the section 3.7
    fields of the protocol tolerances and FAILS unless they are the calibrated values (calibration_problems, ruling R74, T21-A08);
    baw_quantlib and alo_quantlib take the locked block (the rules of optionlab.checks._locked_agreement_body: the lock state,
    every section 3.7 key, sstar_k 0 for every baw greek, none for alo)."""
    from optionlab import agreement, checks, protocol
    if name=='quantlib':
        t=protocol.tolerances();return None,t.get('state'),calibration_problems(t)
    model=QL_MODELS[name][0];spec=checks.AGREEMENT_SPECS[model];t=spec['block']()
    state=t.get('state') if isinstance(t,dict) else None
    if state!=spec['lock']:return None,state,[f'tolerances.{model} not locked']
    sk=t.get('sstar_k')
    if any(k not in t for k in agreement.TOLERANCES):return None,state,[f'tolerances.{model} incomplete']
    if model=='baw' and (not isinstance(sk,dict) or set(sk)!=set(checks.BAW_GREEK_FIELDS) or any(v!=0 for v in sk.values())):
        return None,state,['tolerances.baw sstar_k is not 0 for every greek']
    if model=='alo' and sk is not None:return None,state,['tolerances.alo has sstar_k']
    return {k:float(t[k]) for k in agreement.TOLERANCES},state,[]

def run_all(native_dir):
    """Every item (see the module text) with the restored binaries of native_dir (SAFE_C_BENCH_NATIVE). Returns the document of
    native-agreement.json: the items, `counts` (compared count per item), `status`, the phases and the task seconds."""
    from benchlab import native_worker as nw
    nw.same_directory(native_dir)
    doc={'wired':mask_wired(),'cells':list(ALL_CELLS),'pool_workers':pool_workers(),'phases':{}}
    if not doc['wired']:
        items={k:item(['WAITING: Task 10b (PL_MASK_WIRED is not PL_MASK_MODELS5)'],0,0.0) for k in ITEMS}
        return _finish(doc,items,None)
    ex=ProcessPoolExecutor(max_workers=doc['pool_workers'],mp_context=multiprocessing.get_context('spawn'));P=_Pool(ex)
    try:
        with tempfile.TemporaryDirectory() as tmp:items=_collect_and_judge(P,tmp,doc)
    except RunDefect:raise                  # H19: never an item result (native_check: a run defect ends the check)
    except Exception as exc:
        items={k:item([f'exception {type(exc).__name__}'],0,0.0) for k in ITEMS}
    finally:ex.shutdown(wait=True,cancel_futures=True)
    return _finish(doc,items,P)

def _finish(doc,items,P):
    doc.update({k:items[k] for k in ITEMS})
    doc['counts']={k:items[k]['count'] for k in ITEMS}
    doc['status']='PASS' if all(items[k]['status']=='PASS' for k in ITEMS) else 'FAIL'
    if P is not None:doc['task_seconds']={k:round(v,1) for k,v in sorted(P.seconds.items())};doc['tasks']=dict(sorted(P.tasks.items()))
    return doc

def _collect_and_judge(P,tmp,doc):
    from benchlab.workload import request_limit
    from optionlab.checks import ALIGN_GRID
    from optionlab.cvectors import RAISE_ROWS
    from optionlab.reference import canonical_result
    phases=doc['phases'];t0=time.monotonic()
    a=_adapter();params,seed=_case();limit=request_limit()
    rows=_large_rows(P,a,seed,tmp);phases['generate']=round(time.monotonic()-t0,1)
    n_t={t:SIZES[t] for t in TIERS};tiers={t:rows[:n_t[t]] for t in TIERS};sample=sample_indices()
    edges,covered=edge_inputs();edge_rows=[r for _,r in edges];trap_row=tuple(RAISE_ROWS[5])
    hi=[j for j in sample if j>=n_t['medium']];small=tiers['small']
    probe_points=[(k,side,S,K,T,params.rate,params.dividend_yield,s) for k in range(len(MODELS5)) for side,S,K,T,s in ALIGN_GRID]
    # wave 1: the edge classification first (the projection needs it), then the long tasks, then the rest
    h_edge=[P.submit('edge_rows',_task_edges,part) for part in _chunks(edge_rows,EDGE_CHUNK)]
    h_trap_ref=P.submit('trap',_task_edges,[trap_row])
    h_c=[(cell,P.submit('large_sample',_task_c,cell,CASE_MASK,[(('large',CASE_MASK,'large'),rows,('sample',sample))])) for cell in ALL_CELLS]
    h_refba=[P.submit('per_model',_task_reference,part,('baw','alo')) for part in _chunks(small,ALO_CHUNK)]
    h_c+=[(BASE_CELL,P.submit(QL_ITEMS[m],_task_c,BASE_CELL,m,[(('tier',m,'medium'),tiers['medium'],'result')])) for m in (8,16)]
    # EX-16 (T21-A05): baw and alo beyond the small tier; the medium C results of BASE_CELL come from the QuantLib items above
    rest=rows[n_t['small']:n_t['medium']];low=[j for j in sample if j<n_t['medium']]
    h_alohi=[P.submit('baw_alo_reference',_task_reference,part,('alo',)) for part in _chunks(rest,ALO_CHUNK)]
    h_bawhi=[P.submit('baw_alo_reference',_task_reference,part,('baw',)) for part in _chunks(rest,REF_CHUNK)]
    h_bawsample=[P.submit('baw_alo_reference',_task_reference,part,('baw',)) for part in _chunks([rows[j] for j in hi],REF_CHUNK)]
    h_c+=[(cell,P.submit('baw_alo_reference',_task_c,cell,8,([] if cell==BASE_CELL else [(('tier',8,'medium'),tiers['medium'],'bytes')])
                         +[(('large',8,'large'),rows,('sample',sample))])) for cell in ALL_CELLS]
    h_c+=[(cell,P.submit('baw_alo_reference',_task_c,cell,16,[(('tier',16,'medium'),tiers['medium'],'bytes')])) for cell in ALL_CELLS if cell!=BASE_CELL]
    h_lib={(t,name):P.submit(name,_task_library,tiers[t],QL_MODELS[name]) for t in TIERS for name in QL_MODELS}
    h_ref7=[P.submit('py_reference',_task_reference,part,ALL_MODELS) for part in _chunks(tiers['medium'],REF_CHUNK)]
    h_refhi=[P.submit('large_sample',_task_reference,part,ALL_MODELS) for part in _chunks([rows[j] for j in hi],REF_CHUNK)]
    h_refbsm=[P.submit('limits',_task_reference,part,('bsm',)) for part in _chunks(rows[n_t['medium']:],BSM_CHUNK)]
    h_indep={m:P.submit('per_model',_task_reference,small[:INDEPENDENCE_ROWS],(m,)) for m in MODELS5}
    h_c+=[(cell,P.submit('py_reference',_task_c,cell,CASE_MASK,[(('tier',CASE_MASK,t),tiers[t],'result' if cell==BASE_CELL else 'bytes') for t in TIERS]))
          for cell in ALL_CELLS]
    h_c+=[(cell,P.submit('limits',_task_limits,cell,rows,LIMIT_SIZES)) for cell in ALL_CELLS]
    h_c+=[(KERNEL_CELL,P.submit('per_model',_task_c,KERNEL_CELL,m,[(('proj',m,t),tiers[t],'bytes') for t in ('tiny','small')])) for m in PER_MODEL_MASKS]
    h_c+=[(cell,P.submit('trap',_task_c,cell,m,[(('trap',m,'trap'),[trap_row],'bytes')])) for cell in ALL_CELLS for m in TRAP_PASS_MASKS+TRAP_FAIL_MASKS]
    h_kc={(KERNEL_CELL,m):P.submit('counters',_task_kernel_counts,m,tiers[COUNTER_TIER]) for m in COUNTER_MASKS}
    h_wc={(route,m):P.submit('counters',_task_worker_counts,route,m,tiers[COUNTER_TIER]) for route in COUNTER_ROUTES for m in COUNTER_MASKS}
    h_probe=P.submit('quantlib',_task_probe,probe_points)
    h_qlp={m:P.submit({'baw':'baw_quantlib','alo':'alo_quantlib'}.get(m,'quantlib'),_task_ql_probe,m,ALIGN_GRID) for m in MODELS5}
    # the edge classification: the models that py-reference evaluates on each row, and the models that raise
    per_row=[]
    for h in h_edge:
        got=P.get(h);per_row+=got if got is not None else [None]*EDGE_CHUNK
    per_row=per_row[:len(edge_rows)]
    ok_mask=[mask_of([m for m in MODELS5 if r[m][0]=='ok']) if r is not None and any(r[m][0]=='ok' for m in MODELS5) else 0 for r in per_row]
    groups={}
    for i,m in enumerate(ok_mask):
        if m:groups.setdefault(m,[]).append(i)
    raising=[(i,1<<MODELS5.index(m)) for i,r in enumerate(per_row) if r is not None for m in MODELS5 if r[m][0]=='raised']
    proj_idx=groups.get(ALL_MASK,[])
    sets={'oracle':[edge_rows[i] for i in proj_idx],'tiny':tiers['tiny'],'small':small}
    h_c+=[(cell,P.submit('projection',_task_c,cell,m,[(('proj',m,s),sets[s],'result') for s in PROJECTION_SETS])) for cell in ROUTE_CELLS for m in range(1,ALL_MASK+1)]
    h_c+=[(cell,P.submit('edge_rows',_task_c,cell,m,[(('edge',m,'group'),[edge_rows[i] for i in idx],'bytes')])) for cell in ALL_CELLS for m,idx in sorted(groups.items())]
    h_c+=[(cell,P.submit('edge_rows',_task_c,cell,bit,[(('edge_raise',bit,f'row{i}'),[edge_rows[i]],'bytes')])) for cell in ALL_CELLS for i,bit in raising]
    # gather wave 1
    c={}
    for cell,h in h_c:
        got=P.get(h)
        for key,o in (got or {}).items():c[(cell,)+tuple(key)]=o
    join=lambda hs:[P.get(h) for h in hs]
    parts=join(h_ref7);ref7=concat(parts) if all(x is not None for x in parts) else None
    parts=join(h_refba);refba=concat(parts) if all(x is not None for x in parts) else None
    parts=join(h_refhi);refhi=concat(parts) if all(x is not None for x in parts) else None
    parts=join(h_refbsm);refbsm=concat(parts) if all(x is not None for x in parts) else None
    joined={}
    for name,hs in (('alo',h_alohi),('baw',h_bawhi),('baw_sample',h_bawsample)):
        parts=join(hs);joined[name]=concat(parts) if parts and all(x is not None for x in parts) else None
    indep={m:P.get(h) for m,h in h_indep.items()};trap_ref=P.get(h_trap_ref)
    counts_obs={k:P.get(h) for k,h in {**h_kc,**h_wc}.items()}
    lib={k:P.get(h) for k,h in h_lib.items()};probe=P.get(h_probe);qlp={m:P.get(h) for m,h in h_qlp.items()}
    phases['reference_and_c']=round(time.monotonic()-t0-phases['generate'],1)
    # wave 2: agreement.compare of the C results (stdio warm) with QuantLib
    t1=time.monotonic();tol={};h_cmp={}
    for name in QL_MODELS:
        tol[name]=_tolerance(name)
        if tol[name][2]:continue
        m=mask_of(QL_MODELS[name])
        for t in TIERS:
            o=c.get((BASE_CELL,'tier',m,t)) or c.get((BASE_CELL,'proj',m,t))
            if isinstance(o,dict) and 'result' in o and lib.get((t,name)) is not None:
                h_cmp[(t,name)]=P.submit(name,_task_compare,tiers[t],o['result'],lib[(t,name)],tol[name][0],QL_MODELS[name])
    cmp={k:P.get(h) for k,h in h_cmp.items()}
    phases['compare']=round(time.monotonic()-t1,1)
    # judge
    t2=time.monotonic();items={};canon=canonical_result
    ref_ok=ref7 is not None
    # py_reference and routes
    want={('tier',CASE_MASK,t):canon(select(ref7,ALL_MODELS,range(n_t[t]))) for t in TIERS} if ref_ok else {}
    pr,n=equal_problems(c,want,ALL_CELLS)
    items['py_reference']=item(P.task_problems('py_reference')+(['no py-reference result'] if not ref_ok else [])+pr,n,P.seconds.get('py_reference',0.0))
    rk=[('tier',CASE_MASK,t) for t in TIERS];pr,n=routes_problems(c,rk,ALL_CELLS);pr2,n2=routes_problems(c,[('large',CASE_MASK,'large')],ALL_CELLS,field='sha256')
    items['routes']=item(pr+pr2,n+n2,0.0,base=BASE_CELL)
    # large_sample
    if ref_ok and refhi is not None:
        low=[j for j in sample if j<n_t['medium']];ref_sample=concat([select(ref7,ALL_MODELS,low),select(refhi,ALL_MODELS)])
        pr,n=equal_problems(c,{('large',CASE_MASK,'large'):canon(ref_sample)},ALL_CELLS,field='sample_bytes',count_key='sample_n')
    else:pr,n=['no py-reference result of the sample'],0
    items['large_sample']=item(P.task_problems('large_sample')+pr,n,P.seconds.get('large_sample',0.0),sample_rows=len(sample))
    # baw_alo_reference (EX-16, T21-A05): the small-tier part of the per_model reference and the rest of the medium tier
    want_h={}
    if refba is not None and joined['baw'] is not None:
        baw_med=concat([select(refba,('baw',)),joined['baw']]);want_h['baw_medium']=canon(baw_med)
        if joined['baw_sample'] is not None:want_h['baw_large_sample']=canon(concat([select(baw_med,('baw',),low),joined['baw_sample']]))
    if refba is not None and joined['alo'] is not None:want_h['alo_medium']=canon(concat([select(refba,('alo',)),joined['alo']]))
    items['baw_alo_reference']=heavy_item(c,want_h,P.seconds.get('baw_alo_reference',0.0),task_problems=P.task_problems('baw_alo_reference'))
    # limits
    if ref_ok and refbsm is not None:
        ref_large=concat([select(ref7,('bsm',)),refbsm])
        want_l={('limit',LIMIT_MASK,s):hashlib.sha256(canon(tile_result(ref_large,s))).hexdigest() for s in LIMIT_SIZES}
        pr,n=equal_problems(c,want_l,ALL_CELLS,field='sha256')
        for s in LIMIT_SIZES:
            for cell in ROUTE_CELLS:
                o=c.get((cell,'limit',LIMIT_MASK,s))
                if isinstance(o,dict) and 'sha256' in o and o.get('requests')!=len(range(0,s,limit)):pr.append(f'{cell} {s} rows: request count')
    else:pr,n=['no py-reference result of the large rows'],0
    items['limits']=item(P.task_problems('limits')+pr,n,P.seconds.get('limits',0.0),request_limit=limit,period=LARGE_ROWS)
    # per_model (the C results of the per-model masks come from the projection jobs and the kernel jobs)
    pr=[];n=0
    if ref_ok and refba is not None:
        ref31=merge(select(ref7,ALL_MODELS,range(n_t['small'])),refba)
        want_p={('proj',m,t):canon(select(ref31,models_of(m),range(n_t[t]))) for m in PER_MODEL_MASKS for t in ('tiny','small')}
        pr,n=equal_problems(c,want_p,ALL_CELLS)
        for m,got in indep.items():
            if got is None or canon(got)!=canon(select(ref31,(m,),range(INDEPENDENCE_ROWS))):pr.append(f'the per-model py-reference run of {m} differs from its part of the five-model run')
    else:ref31=None;pr=['no py-reference result of the small tier']
    items['per_model']=item(P.task_problems('per_model')+pr,n,P.seconds.get('per_model',0.0),independence_rows=INDEPENDENCE_ROWS*len(MODELS5))
    # projection
    pr,n=projection_set_problems(c,ROUTE_CELLS,PROJECTION_SETS)
    if ref31 is not None and None not in per_row:
        anchors={('proj',ALL_MASK,t):canon(select(ref31,MODELS5,range(n_t[t]))) for t in ('tiny','small')}
        if proj_idx:anchors[('proj',ALL_MASK,'oracle')]=canon(concat([merge(*(per_row[i][m][1] for m in MODELS5)) for i in proj_idx]))
        pa,_=equal_problems(c,anchors,ROUTE_CELLS);pr+=pa
    else:pr.append('no py-reference anchor of the mask-31 results')
    if not proj_idx:pr.append('no oracle edge row without a raising model')
    items['projection']=item(P.task_problems('projection')+pr,n,P.seconds.get('projection',0.0),oracle_rows=len(proj_idx))
    # edge_rows
    pr=[];n=0
    if None in per_row:pr.append('an edge row has no py-reference classification')
    else:
        want_e={('edge',m,'group'):canon(concat([merge(*(per_row[i][x][1] for x in models_of(m))) for i in idx])) for m,idx in groups.items()}
        pe,n=equal_problems(c,want_e,ALL_CELLS);pd,nd=defect_problems(c,[('edge_raise',bit,f'row{i}') for i,bit in raising],ALL_CELLS);pr+=pe+pd;n+=nd
    items['edge_rows']=item(P.task_problems('edge_rows')+pr,n,P.seconds.get('edge_rows',0.0),rows=len(edge_rows),covered_by_vectors=covered,
                            groups={str(m):len(idx) for m,idx in sorted(groups.items())},raising=[[edges[i][0],models_of(bit)[0]] for i,bit in raising])
    # trap
    pr=[];n=0
    if trap_ref is None:pr.append('no py-reference classification of the trap row')
    else:
        r=trap_ref[0];raised=[m for m in MODELS5 if r[m][0]=='raised']
        if raised!=['crr']:pr.append('the trap row is not the crr-only class of the census')
        else:
            want_t={('trap',m,'trap'):canon(merge(*(r[x][1] for x in models_of(m)))) for m in TRAP_PASS_MASKS}
            pe,n=equal_problems(c,want_t,ALL_CELLS);pd,nd=defect_problems(c,[('trap',m,'trap') for m in TRAP_FAIL_MASKS],ALL_CELLS);pr+=pe+pd;n+=nd
    items['trap']=item(P.task_problems('trap')+pr,n,P.seconds.get('trap',0.0))
    # counters
    if ref31 is not None:
        want_c={m:sum(ref31['models'][m]['engine_evals']) for m in MODELS5}
        pr,n=counter_problems(counts_obs,want_c,n_t[COUNTER_TIER])
    else:pr,n=['no py-reference engine_evals'],0
    items['counters']=item(P.task_problems('counters')+pr,n,P.seconds.get('counters',0.0),
                           inproc='not readable: pl_inproc_price_stats is a test hook of the library, not exported (tests/project/test_inproc.c)')
    # QuantLib items
    for name in QL_MODELS:
        tl,state,pr=tol[name];n=0;summaries={}
        if not pr:
            for t in TIERS:
                v=cmp.get((t,name))
                if v is None:pr.append(f'{t}: no compare verdict');continue
                n+=n_t[t];summaries[t]={'eligible':v['eligible'],'failures':v['failures'],'reduction':v['reduction'],'multi_root':v['multi_root']}
                if not v['eligible']:pr.append(f'{t}: agreement.compare not eligible ({",".join(sorted(v["failures"])) or v["reduction"]})')
        for m in QL_MODELS[name]:
            k=MODELS5.index(m);pts=[p for p in probe_points if p[0]==k]
            c_rows=[x for p,x in zip(probe_points,probe) if p[0]==k] if isinstance(probe,list) else None
            pp,np_=probe_problems(m,pts,c_rows,qlp.get(m));pr+=pp;n+=np_
        items[name]=item(P.task_problems(name)+pr,n,P.seconds.get(name,0.0),tolerance_state=state,compare=summaries,
                         probe_points=len(ALIGN_GRID)*len(QL_MODELS[name]))
    phases['judge']=round(time.monotonic()-t2,1)
    phases['generate_task_seconds']=round(P.seconds.get('generate',0.0),1)
    # R58 (T21-A01): the route-mechanics items of native-routes, in this process after the pool work (no CPU contention for
    # the gil and crash items); the native_check functions with the input that native-routes gives them
    from optionlab import native_check
    t3=time.monotonic();items['route_mechanics']=mechanics_item(native_check.route_mechanics(tmp),time.monotonic()-t3)
    phases['route_mechanics']=round(time.monotonic()-t3,1)
    return items

def check(out_dir,native_dir):
    """The check native-agreement: run_all, native-agreement.json in out_dir, and the check row (check_row)."""
    started=time.monotonic();doc=run_all(native_dir);seconds=time.monotonic()-started;doc['seconds']=round(seconds,1)
    Path(out_dir).mkdir(parents=True,exist_ok=True)
    (Path(out_dir)/FILE).write_text(json.dumps(doc,sort_keys=True,indent=1)+'\n')
    return check_row({k:doc[k] for k in ITEMS},seconds)
