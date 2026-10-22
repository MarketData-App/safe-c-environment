"""Bench plans: rows, randomized blocks, budget and session caps (spec 8.3). Never shrinks a dataset, trial count or row."""
import hashlib, json, math, random, re
from pathlib import Path
from evidence import GateError, CAPPED_JSON_MAX_BYTES, loads_capped, read_capped
import bench_stats as bs

# T5R1-A01: the planned work of a trial (P07, B15, B10), defined once in container/bench_trial_work.py for the host rules
# and the rules inside a local decision job (the coordinator imports the same file). The host loads it by its path.
import importlib.util as _importlib_util
_work_spec=_importlib_util.spec_from_file_location('bench_trial_work_host',Path(__file__).resolve().parents[1]/'container/bench_trial_work.py')
trial_work=_importlib_util.module_from_spec(_work_spec);_work_spec.loader.exec_module(trial_work)
PANEL_ROWS_PER_CALL=trial_work.PANEL_ROWS_PER_CALL
planned_work_units=trial_work.planned_work_units

PYTHON_LANGUAGES=('python','python-library')   # Task 9b: py-library (an existing compiled library called from Python) is a Python row

def python_rows(case,envelope):
    rows=[];blocked=[]
    for v in case['variants']:
        if v['language'] not in PYTHON_LANGUAGES or v['status'] not in ('implemented',):
            if v['status']=='planned-phase-2':blocked+=[{'variant':v['id'],'workers':w,'reason':'C variant lands in Phase 2'} for w in v['workers']]
            continue
        for w in v['workers']:
            if w!='direct' and w>envelope['cpus']:blocked.append({'variant':v['id'],'workers':w,'reason':f"beyond the {envelope['cpus']}-CPU envelope"})
            else:rows.append({'variant':v['id'],'workers':w})
    return rows,blocked

ROUTES=('stdio','shm','inproc');DEFAULT_ROUTES=('stdio',)
INPROC_COLD='inproc cold: not-applicable (library load is the startup phase)'

def c_variant(variant):return isinstance(variant,str) and variant.startswith('c-')

def case_rows(case,envelope):
    """Phase 2 Task 19 (FR6 N4): (rows, blocked) with one row per (variant, workers, route). Python rows are those of
    python_rows with route None. An implemented C variant gives one row per route of its `routes` (default stdio); a pool
    row (workers above the envelope CPUs) is blocked per route. A planned-phase-2 C variant stays blocked as in Phase 1."""
    rows,blocked=python_rows(case,envelope)
    rows=[dict(r,route=None) for r in rows]
    for v in case['variants']:
        if v['language']!='c' or v['status']!='implemented':continue
        for w in v['workers']:
            for route in v.get('routes',list(DEFAULT_ROUTES)):
                if w!='direct' and w>envelope['cpus']:blocked.append({'variant':v['id'],'workers':w,'route':route,'reason':f"beyond the {envelope['cpus']}-CPU envelope"})
                else:rows.append({'variant':v['id'],'workers':w,'route':route})
    return rows,blocked

def _plan_row(r):
    """A plan row: a Python row (route None) keeps its Phase 1 form, so a plan without C rows keeps its plan id."""
    return {k:v for k,v in r.items() if not (k=='route' and v is None)}

def _point_specs(point,rows,mode_list):
    """(variant, workers, mode, route) of a point: a kernel point has one row per C variant and workers (no transfer route);
    a caller point keeps every route of its C rows, narrowed by the point's `routes`; inproc never runs cold (it is blocked)."""
    specs=[];blocked=[];seen=set()
    for r in rows:
        route=r.get('route')
        if point['scope']=='kernel':
            if route is not None:
                if (r['variant'],r['workers']) in seen:continue
                seen.add((r['variant'],r['workers']));route=None
        elif route is not None and 'routes' in point and route not in point['routes']:continue
        for m in mode_list:
            if route=='inproc' and m=='cold':
                blocked.append({'variant':r['variant'],'workers':r['workers'],'route':'inproc','mode':'cold','reason':INPROC_COLD});continue
            specs.append((r['variant'],r['workers'],m,route))
    return specs,blocked

def _route_keys(route,policy):
    """The trial keys of a C caller row: its route and the policy label of the route; none for a Python or kernel row."""
    return {} if route is None else {'route':route,'route_label':policy['routes'][route]}

def _route_id(row):return '' if row.get('route') is None else '-'+row['route']

def route_share(policy,selector):
    """G10.3: the estimate share of a selector (policy budgets.estimate_share_per_selector, from the project protocol; 1.0
    for `all` and for a selector without a share)."""
    return 1.0 if selector=='all' else float(policy['budgets'].get('estimate_share_per_selector',{}).get(selector,1.0))

def route_budget(plan,policy,calibration=None):
    """{route: {selector: seconds}}: the planned seconds of the C caller trials of each route and selector (trial_estimate
    times the selector share; T6-R7: with measured walls, the measured estimate of each trial, measured_trial_seconds).
    Empty without a C caller trial."""
    out={}
    for s in plan['sessions']:
        for t in s['trials']:
            if t.get('route') is None:continue
            sel=t.get('selector','all')
            est=(measured_trial_seconds(policy,t,calibration) if has_walls(calibration)
                 else trial_estimate(policy,t['variant'],policy['sizes'][t['tier']],t.get('loops',1),calibration)*route_share(policy,sel))
            bucket=out.setdefault(t['route'],{});bucket[sel]=round(bucket.get(sel,0.0)+est,6)
    return out

DATASET_KEYS=('kind','size','seed','sha256','rows')     # F-11: the only dataset keys a plan may hold
CLASSES=('primary','secondary','exploratory');MODES=('warm','cold','direct')

def family(variant):return variant if variant in ('py-reference','py-library') else 'c' if variant.startswith('c-') else 'py-optimized'

def rate(policy,family_name,calibration=None):
    table=calibration or policy['budgets']['estimate_seconds_per_record']
    if family_name not in table:raise GateError(f'the calibration has no rate for the {family_name} family')
    return table[family_name]

def trial_estimate(policy,variant,size,loops=1,calibration=None):
    """Pool rows are estimated as one worker (plan ruling 9); the calibration therefore uses direct and 1-worker rows only.
    A later per-worker-count calibration may refine pool rows, but must never lower the single-worker rate."""
    if not bs._count(loops):raise ValueError('loops must be a positive integer')
    return size*rate(policy,family(variant),calibration)*loops+policy['budgets']['trial_overhead_seconds']

# ---- T6-R7 (design I9.3: after calibration, the deadline input is "the calibrated per-call wall of the row"): measured walls ----
# A per-family rate of multi-row `all` calls times a selector share cannot size a one-row call: a variant with a fixed
# per-call cost (for example a vectorized engine) pays it on every one-row call. A calibration run therefore records a
# measured wall per variant, selector and call class (measured_walls), and every caller-scope timing trial of a calibrated
# plan (its passes L, its expected wall, its call-deadline input and its session, group and window estimates) uses that
# wall (bench_deadline.measured_seconds). The smoke plan measures every class that a decision plan of the case can hold
# (wall_probes). A missing wall refuses the plan (wall-not-measured); nothing is extrapolated from another class,
# selector or variant. The kernel scope keeps the family rate: its timed loops call the kernel without the caller path.
# Ruling R87: a probe measures a steady wall (an untimed warmup trial of the same shape in the same trial child takes the
# one-time cost of a new child), and a smoke plan that holds probe points keeps every session within the smoke job deadline
# and may take up to PROBE_SMOKE_CAP_SECONDS in all.
CALL_CLASSES=('one-row','multi-row')
PROBE_PREFIX='probe-'
PROBE_SMOKE_CAP_SECONDS=1200       # R87: the bound of a whole smoke plan with probe points (twice the 600 s smoke job deadline)

def call_class(rows):
    """The call class of a call of `rows` rows: one-row for a call of one row (a single-record panel call, or a call of a
    one-row tier), else multi-row (the fixed per-call cost is shared over the rows of the call)."""
    return 'one-row' if rows==1 else 'multi-row'

def point_class(point,policy):
    """The call class of the calls of a caller point: one-row for a panel point or a point whose tier has one row."""
    return 'one-row' if 'panel' in point else call_class(policy['sizes'][point['size']])

def has_walls(calibration):
    """True for a calibration that holds measured walls (every calibration that calibration_inputs reads from a run). A
    rate table without the key (the planning form of a unit test) keeps the rate rules."""
    return isinstance(calibration,dict) and isinstance(calibration.get('walls'),dict)

def measured_walls(observations,policy):
    """T6-R7: {variant: {selector: {call class: seconds}}} of a calibration run: per variant, selector and call class, the
    median over trials of each trial's per-unit wall (the rule of calibration_from_observations: eligible, non-warmup,
    direct and 1-worker rows of the phases caller and work), from the timed caller-scope rows only (no kernel, memory or
    capacity row). A one-row wall is the seconds of one one-row call (a panel trial: its wall / (6 x L)); a multi-row wall
    is the seconds per record of the calls of the smallest multi-row tier that the run measured for that variant and
    selector (a larger call shares its fixed per-call cost over more rows, so the wall is an upper bound of its cost per
    record). Pool rows are planned with the wall of their variant (plan ruling 9)."""
    sizes=policy['sizes']
    try:
        rows=[o for o in observations if o.get('scope')=='caller' and not o['warmup'] and o['eligible'] and o['work_units'] and o['phase'] in ('caller','work')
              and o['workers'] in ('direct',1)]
        groups={}
        for o in rows:
            n=1 if 'panel_passes' in o else sizes[o['tier']]
            groups.setdefault((o['variant'],o.get('selector','all'),call_class(n)),{}).setdefault(n,[]).append(o)
        out={}
        for (variant,sel,cls),by in sorted(groups.items()):
            out.setdefault(variant,{}).setdefault(sel,{})[cls]=bs.median(bs.per_trial_values(by[min(by)],'wall_ns').values())/1e9
        return out
    except ValueError as exc:raise GateError(f'calibration run is inconsistent: {exc}') from None
    except (KeyError,TypeError,AttributeError,ZeroDivisionError):raise GateError('calibration observations are malformed') from None

def caller_trial_estimate(policy,variant,selector,size,calibration,loops=1):
    """T6-R7: the estimate of one caller trial that is not a panel trial (a session trial or a memory trial): with measured
    walls, size x loops x the measured wall of its variant, selector and call class (bench_deadline.measured_seconds) plus
    the trial overhead; else trial_estimate (the planning form of the rule policies: size x rate, no share)."""
    if not has_walls(calibration):return trial_estimate(policy,variant,size,loops,calibration)
    if not bs._count(loops):raise ValueError('loops must be a positive integer')
    import bench_deadline
    return bench_deadline.measured_seconds(policy,{'variant':variant,'selector':selector},size,loops,calibration)+policy['budgets']['trial_overhead_seconds']

def measured_trial_seconds(policy,trial,calibration):
    """T6-R7: the measured estimate of one planned caller trial: a panel trial 6 x L one-row calls (L = 1 cold), any other
    trial the rows of its tier x loops; each at the measured wall of its class, plus the trial overhead."""
    if 'panel' in trial:
        import bench_deadline
        calls=PANEL_REQUESTS if trial.get('mode')=='cold' else PANEL_REQUESTS*trial['panel_passes']
        return bench_deadline.measured_seconds(policy,trial,1,calls,calibration)+policy['budgets']['trial_overhead_seconds']
    return caller_trial_estimate(policy,trial['variant'],trial.get('selector','all'),policy['sizes'][trial['tier']],calibration,trial.get('loops',1))

def wall_probes(case,policy):
    """T6-R7 (item 1(d); design choice: measure in the smoke, never extrapolate): the probe points of the smoke plan of
    `case`. The smoke-caller point measures selector `all` on multi-row calls of every caller row. For every other
    (selector, call class) of the caller points of the case, one probe point probe-<selector>-<class> measures one short
    trial of each variant that those points list (py-reference never at a large point): mode warm (cold when no such point
    is warm), 1 block after the warmup set of the session (R87: one untimed warmup trial of the same shape per variant, in
    the same trial child, so the timed trial measures the steady wall without the one-time cost of a new child; build_plan
    and the smoke bound PROBE_SMOKE_CAP_SECONDS), on the first direct or 1-worker row of the variant and the first route
    of a C variant that the points allow (_probe_rows). A multi-row probe runs at the small tier (the smallest multi-row
    tier: its per-record wall is an upper bound for the larger calls); a one-row probe on the panel and dataset_ref of the
    first such point (L = 1 pass of 6 one-row calls, panel_fields) or at its one-row tier. Points in the order of the first
    case point of each pair. A selector that no plan may hold yet gets no probe: an unlocked tolerance block
    (bench_model.require_locked_selectors) or a required share without its approved value (budgets.share_required); every
    plan of it refuses for that reason first. GateError for a case point with a probe name."""
    import bench_model, bench_deadline
    def ready(sel):
        if bench_deadline.unapproved_shares(policy,[sel]):return False
        try:bench_model.require_locked_selectors(policy,[sel])
        except GateError:return False
        return True
    variants=[v.get('id') for v in case.get('variants') or [] if isinstance(v,dict)]
    names={p.get('name') for p in case.get('points') or [] if isinstance(p,dict)};groups={}
    for p in case.get('points') or []:
        if not isinstance(p,dict) or p.get('scope')!='caller':continue
        key=(p.get('selector','all'),point_class(p,policy))
        if key!=('all','multi-row') and ready(key[0]):groups.setdefault(key,[]).append(p)
    out=[]
    for (sel,cls),pts in groups.items():
        name=f'{PROBE_PREFIX}{sel}-{cls}'
        if name in names:raise GateError(f'case point {name} has the name of a smoke probe point')
        listed=set()
        for p in pts:listed|={v for v in (p['variants'] if p.get('variants') is not None else variants) if not (v=='py-reference' and p['size']=='large')}
        first=pts[0];warm=any('warm' in (p.get('modes') or []) for p in pts)
        q={'name':name,'scope':'caller','size':first['size'] if cls=='one-row' else 'small','modes':['warm' if warm else 'cold'],
           'variants':[v for v in variants if v in listed],'class':'exploratory','blocks':1,'selector':sel,'probe':True}
        if all('routes' in p for p in pts):q['routes']=[r for r in ROUTES if any(r in p['routes'] for p in pts)]
        if cls=='one-row' and 'panel' in first:
            q['panel']=list(first['panel'])
            if 'dataset_ref' in first:q['dataset_ref']=first['dataset_ref']
        out.append(q)
    return out

def _probe_rows(rows,point):
    """The rows of a probe point: per variant its first direct or 1-worker row whose route the point allows (a C row:
    the point's routes; inproc only in the warm mode)."""
    out=[];seen=set()
    for r in rows:
        route=r.get('route')
        if r['variant'] in seen or r['workers'] not in ('direct',1):continue
        if route is not None and (('routes' in point and route not in point['routes']) or (route=='inproc' and 'warm' not in point['modes'])):continue
        seen.add(r['variant']);out.append(r)
    return out

PANEL_MIN_PASSES=5;PANEL_TRIAL_SECONDS=0.5;PANEL_REQUESTS=6     # Amendment G7.3: L >= 5 passes, warm trial wall >= 0.5 s, six requests
PANEL_MAX_PASSES=8192              # T18-C1b: the finite L bound (L_max 4167 of the fastest policy rate, the C rate at the cheapest selector of the reference example; margin 1.97)

def panel_passes(per_call_seconds,mode):
    """G7.3 (base Task 18): the passes L of a single-record panel trial. Cold cells use L = 1. Warm: the smallest L >= 5 with
    an estimated trial wall 6 x L x per_call_seconds >= 0.5 s (per_call_seconds: the calibrated or planned wall of one
    one-row call). ValueError for a per-call wall that is not a finite number > 0 or a mode other than warm or cold."""
    if mode not in ('warm','cold'):raise ValueError('a panel trial mode is warm or cold')
    if isinstance(per_call_seconds,bool) or not isinstance(per_call_seconds,(int,float)) or not math.isfinite(per_call_seconds) or per_call_seconds<=0:
        raise ValueError('per_call_seconds must be a finite number > 0')
    if mode=='cold':return 1
    wall=lambda n:PANEL_REQUESTS*n*per_call_seconds
    passes=max(PANEL_MIN_PASSES,math.ceil(PANEL_TRIAL_SECONDS/(PANEL_REQUESTS*per_call_seconds)))
    while passes>PANEL_MIN_PASSES and wall(passes-1)>=PANEL_TRIAL_SECONDS:passes-=1    # the exact predicate decides, never the rounding
    while wall(passes)<PANEL_TRIAL_SECONDS:passes+=1
    return passes

def panel_cells(policy):
    """The panel cell names in the cell order of the project's cell rule (FR5: `panel_cells` of bench_model.load_policy,
    from the protocol's panel.cell_rule), as the single-record observations name them (`panel_walls` keys). GateError when
    the policy holds no six cells (no project, or a project protocol without a cell rule)."""
    cells=list(policy.get('panel_cells') or [])
    if len(cells)!=PANEL_REQUESTS:raise GateError(f'a single-record panel needs the {PANEL_REQUESTS} panel cells of the project protocol cell rule')
    return cells

def panel_fields(trial,point,policy,calibration):
    """G7.3 plan keys of a trial of a point with a `panel`: the panel indices (cell order), L passes, the cell labels and
    the panel reference status of each panel row. H21.4: a selected panel row is a candidate row, status OK for every
    model of the panel mask (bench_panel.candidate; bench_panel.check refuses a stored reference whose selection differs),
    so the reference status of every panel row is OK. The per-call wall is the planning estimate of one one-row call with
    the selector share before calibration, and the measured one-row wall of the variant and selector after it (T6-R7,
    bench_deadline.measured_seconds). A probe point of a smoke plan (wall_probes) makes L = 1 pass in either mode."""
    import bench_deadline
    panel=list(point['panel']);cells=panel_cells(policy)
    if len(panel)!=len(cells):raise GateError(f"{point.get('name','?')}: a single-record panel holds the {len(cells)} panel cells")
    per_call=bench_deadline.measured_seconds(policy,{'variant':trial['variant'],'selector':point.get('selector','all')},1,1,calibration)
    passes=1 if point.get('probe') else panel_passes(per_call_seconds=per_call,mode=trial['mode'])
    if passes>PANEL_MAX_PASSES:      # T18-C1b: refused at plan time, never a run-time INVALID row
        raise GateError(f"l-pass-over-bound: {point.get('name','?')} {trial['variant']} {trial['mode']} needs L = {passes} passes, above the bound {PANEL_MAX_PASSES}")
    return {'panel':panel,'panel_passes':passes,'panel_cells':cells,'panel_reference_status':['OK']*len(panel)}

# T18-C1b: the observations.jsonl of one session is one fetched file under common.artifact_bytes
# (safety/container-policy.json, never changed here); bench plan refuses a session whose estimate exceeds 75 % of it.
SESSION_FILE_SHARE=(3,4)
OBS_ROW_BYTES=4096                 # one observation line without panel fields: the largest rows (pool identity) stay near 1.5 KB
PANEL_WALL_BYTES=21                # one wall: up to 19 digits and the ", " separator
PANEL_RECORD_BYTES=256           # per record: its key and the median, min and max object
PANEL_AUDIT_WALLS=64               # the audit sample bound of the coordinator (container/bench-coordinator.py PANEL_AUDIT_WALLS)
KERNEL_ROWS=4                      # pyperf rows per kernel trial in a decision run (bench run: 3 values + 1 warmup)

def artifact_bytes():
    """common.artifact_bytes of the protected container policy of this repository."""
    return json.loads((Path(__file__).resolve().parents[1]/'safety/container-policy.json').read_text())['common']['artifact_bytes']

def session_file_estimate(trials):
    """An upper estimate of the observations.jsonl bytes of one session: OBS_ROW_BYTES per row (KERNEL_ROWS per kernel
    trial) and, per panel trial, its records with min(L, 64) audit walls each and the median, min and max."""
    total=0
    for t in trials:
        rows=KERNEL_ROWS if t.get('scope')=='kernel' else 1;total+=rows*OBS_ROW_BYTES
        if 'panel' in t:total+=len(t['panel'])*(min(t.get('panel_passes',1),PANEL_AUDIT_WALLS)*PANEL_WALL_BYTES+PANEL_RECORD_BYTES)
    return total

def check_session_file(estimate,limit,name):
    """session-file-over-bound when the estimate exceeds 75 % of the artifact limit (integer comparison)."""
    if estimate*SESSION_FILE_SHARE[1]>limit*SESSION_FILE_SHARE[0]:
        raise GateError(f'session-file-over-bound: session {name} observations.jsonl estimate {estimate} bytes exceeds 75 % of common.artifact_bytes ({limit})')

def panel_trial_estimate(policy,point,variant,mode,calibration):
    """The estimate of one panel trial: calls = 6 x L (L = 1 cold) of one one-row request each, plus the trial overhead
    (T6-R7: each call at the measured one-row wall after calibration)."""
    import bench_deadline
    f=panel_fields({'variant':variant,'mode':mode},point,policy,calibration)
    per_call=bench_deadline.measured_seconds(policy,{'variant':variant,'selector':point.get('selector','all')},1,1,calibration)
    return PANEL_REQUESTS*f['panel_passes']*per_call+policy['budgets']['trial_overhead_seconds']

def point_problems(case,policy):
    """Task 2 review: every case point names declared variants, a declared scope and a declared size (case and policy)."""
    variants={v['id'] for v in case['variants']};problems=[]
    for point in case['points']:
        name=point.get('name','?')
        if point['scope'] not in case['scopes']:problems.append(f'{name}: scope {point["scope"]} is not declared by the case')
        if point['size'] not in case['sizes'] or point['size'] not in policy['sizes']:problems.append(f'{name}: size {point["size"]} is not declared')
        problems+=[f'{name}: variant {v} is not declared by the case' for v in point['variants'] if v not in variants]
        if point.get('class') not in CLASSES:problems.append(f'{name}: unknown class')
        modes=point.get('modes')
        if not modes or any(m not in MODES for m in modes):problems.append(f'{name}: modes must be a non-empty list of warm, cold, direct')
        elif (point['scope']=='kernel')!=(list(modes)==['direct']) or (point['scope']!='kernel' and 'direct' in modes):
            problems.append(f'{name}: kernel points use mode direct only; other scopes use warm or cold')
    return problems

def _points(case,mode,policy=None):
    """The points of a plan of `mode`: a smoke plan holds smoke-caller, smoke-kernel and (T6-R7, with the policy) the probe
    points of wall_probes after them, so the session ids of the first two stay; any other mode the case points."""
    if mode=='smoke':
        return [{'name':'smoke-caller','scope':'caller','size':'small','modes':['warm','cold'],'variants':None,'class':'exploratory','blocks':'smoke'},
                {'name':'smoke-kernel','scope':'kernel','size':'small','modes':['direct'],'variants':['py-reference','py-optimized','c-serial'],'class':'exploratory','blocks':1}   # Task 19: the C kernel row
                ]+(wall_probes(case,policy) if policy is not None else [])
    return [dict(p,blocks=None) for p in case['points']]

# Amendment E: the pool chunk rule as the plan records it (benchlab.pools holds the same constants; a test pins them).
CHUNK_RULE='one-per-worker';PARTITION='splitmix64-fisher-yates';PARTITION_SEED='0x5AFEC0DE20261007'

def expected_chunk_sizes(n,workers,limit):
    """Host copy of the Amendment E size rule: per L2 request of m rows, w = min(workers, m) chunks of
    floor((k+1)m/w) - floor(km/w) rows (k = 0 .. w-1); requests in order. No benchlab import (framework host tool)."""
    if isinstance(n,bool) or not isinstance(n,int) or n<0:raise ValueError('row count must be a non-negative integer')
    if isinstance(workers,bool) or not isinstance(workers,int) or workers<1:raise ValueError('workers must be a positive integer')
    out=[]
    for a in range(0,n,limit):
        m=min(n,a+limit)-a;w=min(workers,m);out+=[(k+1)*m//w-k*m//w for k in range(w)]
    return out

def b10_row_count(plan,trial,policy):
    """Amendment E item 6: the rows of one pooled request of a trial (pass the plan's trial). A synthetic dataset uses the
    policy size of the trial's tier; a local dataset uses the planned prefix length plan['dataset']['rows']. T5R1-A01: a
    single-record (panel) trial calls one-row requests, so each of its pooled calls holds one row (bench_trial_work
    request_rows; spec B10: a one-row request has one chunk)."""
    kind=plan['dataset']['kind']
    if kind=='synthetic':rows=policy['sizes'][trial['tier']]
    elif kind=='local':rows=plan['dataset']['rows']
    else:raise GateError(f'unknown dataset kind {kind!r}')
    return trial_work.request_rows(trial,rows)

MATRICES=('python','full')      # Task 30 (brief section 14): `--matrix python|full` of bench plan and bench run; default full

def matrix_case(case,matrix):
    """Task 30: the case that a plan of `matrix` measures. `full` is the case itself. `python` keeps only the Python rows:
    the variants of a Python language and the capacity configurations of such a variant (no C row, C memory trial, C
    capacity trial or C blocked row is planned, so no native build runs). GateError for another matrix."""
    if matrix not in MATRICES:raise GateError(f'unknown matrix {matrix!r}: python or full')
    if matrix=='full':return case
    py={v['id'] for v in case['variants'] if v['language'] in PYTHON_LANGUAGES}
    out=dict(case,variants=[v for v in case['variants'] if v['id'] in py])
    if isinstance(case.get('capacity'),dict):
        out['capacity']=dict(case['capacity'],configurations=[c for c in case['capacity'].get('configurations',[]) if c.get('variant') in py])
    return out

EXCLUDED_PYTHON='excluded by --matrix python';EXCLUDED_PLAN='not in the plan'

def _identity(r):return (r.get('variant'),r.get('workers'),r.get('route'))

def excluded_rows(case,plan):
    """EX17-A01: the rows of the declared case (case_rows: every row and every blocked row; an envelope moves a row only
    between the two, so the set does not depend on it) that `plan` neither plans nor blocks, in the order of case_rows,
    each {variant, workers, route, reason}. The reason is EXCLUDED_PYTHON for a `--matrix python` plan and EXCLUDED_PLAN
    for any other plan. A full plan of the case excludes nothing. [] for a plan without `rows` (no built plan) or a case
    without variants; a variant without its id, language, status and workers list declares no row. bench decide adds
    these rows to the missing evidence of both decision branches, so a decision never reads a removed candidate row as
    measured."""
    if not isinstance(plan,dict) or not isinstance(plan.get('rows'),list) or not isinstance(case,dict) or not isinstance(case.get('variants'),list):return []
    variants=[v for v in case['variants'] if isinstance(v,dict) and all(k in v for k in ('id','language','status')) and isinstance(v.get('workers'),list)]
    if not variants:return []
    widest=max([w for v in variants for w in v['workers'] if isinstance(w,int) and not isinstance(w,bool)]+[1])
    rows,blocked=case_rows(dict(case,variants=variants),{'cpus':widest})          # no row beyond this envelope: the declared order
    have={_identity(r) for r in list(plan['rows'])+list(plan.get('blocked_rows') or []) if isinstance(r,dict)}
    reason=EXCLUDED_PYTHON if plan.get('matrix')=='python' else EXCLUDED_PLAN;out=[];seen=set()
    for r in rows+blocked:
        key=_identity(r)
        if key in have or key in seen:continue
        seen.add(key);out.append({'variant':key[0],'workers':key[1],'route':key[2],'reason':reason})
    return out

def _window_estimates(bw,point,specs,warmed,policy,calibration,dataset,measured):
    """EX-18c (EX18b-A01): (block trial estimates, estimate(n)) of the sessions of one point of a window policy plan: the
    bench_windows.trial_seconds of each spec (the approved share of the point's selector; in a decision plan the measured
    reference walls), and estimate(n), the exactly rounded sum (math.fsum) of one warmup set (when warmed) and n blocks:
    the value that bench_windows.session_seconds gives for that session."""
    def one(v,w,m):
        t={'variant':v,'workers':w,'mode':m,'tier':point['size'],'loops':1,'selector':point.get('selector','all'),'point':point['name'],'scope':point['scope']}
        if 'panel' in point:t.update(panel_fields(t,point,policy,calibration))
        return bw.trial_seconds(t,policy,calibration,dataset,measured)
    block=[one(v,w,m) for v,w,m,_ in specs];warm=list(block) if warmed else []
    return block,lambda n:math.fsum(warm+block*n)

def build_plan(case,policy,*,mode,dataset,seed,envelope,calibration=None,project_dir=None,project_identity=None,calibration_source=None,matrix='full',
               unit_policy=None,smoke_job=None,repair=None,calibration_observations=None):
    """EX-18b: with `unit_policy` (a unit-threshold policy that declares windows, project data) a smoke plan is the window
    smoke calibration plan (the smoke-caller point, the unit points, the diagnostics and one control session; with
    `smoke_job` the G10.4 unit smoke job of that index), a decision plan the window plan version (the unit and diagnostic
    points, bench_windows.window_plan; a calibration is required); neither holds memory or capacity trials (they never
    decide under a unit policy), the estimates use the approved shares, and the window caps replace the 8 h decision cap of
    the rule policies. `repair` (H15.2) is bound in the plan id.
    EX-18c: a window decision plan needs `calibration_observations` (the rows of its bound calibration run): they give the
    measured reference walls (bench_windows.measured_reference, EX18b-A03) and the calibration report; both are part of
    the plan id (EX18b-A06), and bench run --plan re-derives them. The sessions of a window plan are packed by the
    share-weighted estimate of bench_windows.trial_seconds, the measure of every later session check (EX18b-A01): a
    decision session holds the most blocks that keep it, with the most control trials one session can hold (all 12
    control blocks and one warmup per control row, e_ctrl of one session), within the session cap; the block count never
    changes. A window smoke calibration plan keeps every session job within the smoke job deadline and the whole plan
    within that deadline or, when the policy states one, within windows.calibration_deadline_seconds (EX18b-A04)."""
    if mode=='selftest':raise GateError('the selftest mode is built only by bench selftest code (bench_deadline.stub_plan), never by build_plan')
    planned=matrix_case(case,matrix)            # Task 30: the point checks read the declared case; the rows come from the matrix case
    if calibration_source is not None and calibration is None:raise GateError('a calibration source needs its calibration')
    problems=point_problems(case,policy)
    if problems:raise GateError('case points reference undeclared entries: '+'; '.join(problems))
    bw=None
    if unit_policy is not None:
        import bench_windows as bw
        bw.require_window_policy(case,unit_policy,mode,calibration,matrix,smoke_job)
        points=bw.plan_points(case,unit_policy,policy,mode,smoke_job,envelope)
    else:
        if smoke_job is not None or repair is not None:raise GateError('a smoke job and a repair belong to a window policy plan (--policy)')
        points=_points(case,mode,policy)              # T6-R7: a smoke plan also holds the probe points (wall_probes)
    missing=[k for k in DATASET_KEYS if k not in dataset]
    if missing:raise GateError('dataset record lacks '+', '.join(missing))
    dataset={k:dataset[k] for k in DATASET_KEYS}     # F-11: allowlist; a plan never holds the owner-fixture path or a label
    measured=None;reserve=0.0
    if bw is not None and mode=='decision':          # EX-18c: the measured reference walls and the control trials of one session
        if calibration_observations is None:raise GateError('a window plan needs the observations of its calibration run (bench plan --calibrate SMOKE_RUN_ID)')
        measured=bw.measured_reference(calibration_observations,case,unit_policy)
        reserve=bw.e_ctrl(policy,calibration,case,unit_policy,1)
    sizes=policy['sizes'];trials=policy['trials'];rows,blocked=case_rows(planned,envelope)      # Task 19: (variant, workers, route) rows
    cap=policy['job_deadlines']['smoke'] if mode=='smoke' else policy['budgets']['session_cap_seconds'];sessions=[];version='v1';total=0.0;probed=False
    for point in points:
        if point['scope'] not in case['scopes']:continue
        size=sizes[point['size']];names=point['variants']
        prow=[r for r in rows if (names is None or r['variant'] in names) and not (r['variant']=='py-reference' and point['size']=='large')]
        if point['scope']=='kernel':prow=[r for r in prow if r['workers']=='direct']
        if point.get('probe'):prow=_probe_rows(prow,point)      # T6-R7: one row per variant
        if not prow:continue
        specs,cold=_point_specs(point,prow,point['modes'])
        blocked+=[b for b in cold if b not in blocked]
        nblocks=trials['smoke_blocks'] if point['blocks']=='smoke' else point['blocks'] if point['blocks'] else trials['primary'] if point['class']=='primary' else trials['secondary'] if point['class']=='secondary' else trials['exploratory'][0]
        warmed=not (mode=='decision' and point['class']=='exploratory')        # spec 8.3: exploratory decision rows get no warmup (R87: a smoke probe has its warmup)
        probed=probed or bool(point.get('probe'))                               # R87: the smoke plan holds a probe point
        if bw is None:
            # G7.3; T6-R7: a caller trial at the measured wall of its variant, selector and call class after calibration; a kernel trial keeps the family rate
            est=((lambda v,m,point=point:panel_trial_estimate(policy,point,v,m,calibration)) if 'panel' in point
                 else (lambda v,m,size=size:trial_estimate(policy,v,size,1,calibration)) if point['scope']=='kernel'
                 else (lambda v,m,size=size,point=point:caller_trial_estimate(policy,v,point.get('selector','all'),size,calibration)))
            warm=sum(est(v,m) for v,w,m,_ in specs) if warmed else 0.0
            block=sum(est(v,m) for v,w,m,_ in specs)
            if warm+block>cap:raise GateError(f"one block of {point['name']} exceeds the session cap; choose fallback A or C as a new plan version")
            per_session=max(1,int((cap-warm)//block));estimate=lambda n,warm=warm,block=block:warm+block*n
        else:                                         # EX-18c (EX18b-A01): the share-weighted estimate that every session check reads
            _,estimate=_window_estimates(bw,point,specs,warmed,policy,calibration,dataset,measured)
            # T5-A08 (EX19-LOCAL-ESTIMATE-01): a session of a local plan also holds the reference work of its own local job
            own=(bw.local_reference_seconds([{'tier':point['size'],'selector':point.get('selector','all'),**({'panel':True} if 'panel' in point else {})}],
                                            case,unit_policy,policy,calibration,measured) if mode=='decision' and bw.is_local(dataset) else 0.0)
            if estimate(1)+reserve+own>cap:
                if mode=='decision':raise bw.PlanRefusal('session-cap-infeasible',f"{point['name']}: one block with its warmup set ({estimate(1):.1f} s) and the control "
                                                        f"trials of one session ({reserve:.1f} s)"+(f" and the reference work of its local job ({own:.1f} s)" if own else '')
                                                        +f" above the {cap} s session cap (H15.6)",[{'point':point['name'],'estimate':estimate(1)+reserve+own}])
                raise GateError(f"one block of {point['name']} exceeds the session cap; choose fallback A or C as a new plan version")
            per_session=max(b for b in range(1,max(1,nblocks)+1) if estimate(b)+reserve+own<=cap)
        groups=[list(range(i,min(nblocks,i+per_session))) for i in range(0,nblocks,per_session)]
        if len(groups)>1:version='v1-split'
        for g in groups:
            sid=f"{point['name']}-s{len(sessions):02d}";tlist=[]
            for n,(v,w,m,rt) in enumerate(specs if warmed else []):tlist.append({'trial_id':f'{sid}-w{n:02d}','block':None,'order':None,'point':point['name'],'scope':point['scope'],'mode':m,'variant':v,'workers':w,'tier':point['size'],'loops':1,'warmup':True,**_route_keys(rt,policy)})
            for b in g:
                order=list(specs);random.Random(f"{seed}:{point['name']}:{b}").shuffle(order)
                for o,(v,w,m,rt) in enumerate(order):tlist.append({'trial_id':f'{sid}-b{b:02d}-{o:02d}','block':b,'order':o,'point':point['name'],'scope':point['scope'],'mode':m,'variant':v,'workers':w,'tier':point['size'],'loops':1,'warmup':False,**_route_keys(rt,policy)})
            for t in tlist:
                if 'panel' in point:t.update(panel_fields(t,point,policy,calibration))     # G7.3: before the call deadline (calls = 6 x L)
                trial_selector(t,point,case,policy,sizes,dataset,cap,calibration)
            check_session_file(session_file_estimate(tlist),artifact_bytes(),sid)      # T18-C1b
            sest=estimate(len(g));total+=sest
            sessions.append({'session':sid,'group':point['name'],'point':point['name'],'scope':point['scope'],'tier':point['size'],'class':point['class'],'deadline_seconds':cap,'estimate_seconds':sest,'trials':tlist})
    if bw is not None and mode=='smoke' and smoke_job is None:      # A8 (PB-01, PB-03): the control pairs with their window block count
        warm,groups=bw.control_session_trials(case,unit_policy,policy,'smoke',0,list(range(int(unit_policy.get('primary_blocks',12)))),seed,dataset,calibration)
        sid=f'control-s{len(sessions):02d}';tlist=warm+[t for g in groups for t in g]
        for t in tlist:t['trial_id']=t['trial_id'].replace('ctl-smoke-s00-','ctl-smoke-')
        check_session_file(session_file_estimate(tlist),artifact_bytes(),sid)
        ctl=bw.session_seconds({'trials':tlist},policy,calibration,dataset)      # EX-18c (EX18b-A04): one session job, the smoke job deadline
        if ctl>cap:raise GateError(f'the control session of the window smoke calibration ({ctl:.0f} s) is above the {cap} s smoke job deadline')
        sessions.append({'session':sid,'group':'control','point':'control','scope':'caller','tier':tlist[0]['tier'],'class':'exploratory','deadline_seconds':cap,
                         'estimate_seconds':ctl,'trials':tlist})
    mem_tier='small' if mode=='smoke' else 'medium';mem_n=trials['smoke_memory'] if mode=='smoke' else trials['memory_primary']
    memory=[{'trial_id':f"memory-{r['variant']}-{r['workers']}{_route_id(r)}-{k}",'point':'memory','tier':mem_tier,'variant':r['variant'],'workers':r['workers'],'mode':'warm','selector':'all',**_route_keys(r.get('route'),policy)} for r in rows for k in range(mem_n)]
    if 'caller' not in case['scopes'] or bw is not None:memory=[]          # memory trials use caller-scope containers (spec 8.4 row 9); a unit policy plan holds none
    if mode=='decision' and memory:
        memory+=[{'trial_id':f"memory-large-{r['variant']}-{r['workers']}{_route_id(r)}",'point':'memory-large','tier':'large','variant':r['variant'],'workers':r['workers'],'mode':'warm','selector':'all',**_route_keys(r.get('route'),policy)} for r in rows if r['variant']!='py-reference']
        total+=sizes[dataset['size'] or 'large']*rate(policy,'py-reference',calibration)   # reference output, outside timing
    for m in memory:
        est=caller_trial_estimate(policy,m['variant'],m['selector'],sizes[m['tier']],calibration)     # T6-R7: the measured wall after calibration
        if est>policy['job_deadlines']['memory']:raise GateError(f"memory trial {m['trial_id']} exceeds the {policy['job_deadlines']['memory']} s memory-trial limit; choose a fallback as a new plan version")
        total+=est
    if dataset['kind']=='local' and sessions:   # a local run computes its reference inside its single container
        total+=max(sizes[x['tier']] for x in sessions)*rate(policy,'py-reference',calibration)
    if bw is None:
        import bench_capacity;cap_trials,cap_blocked,cap_est=bench_capacity.capacity_trials(planned,policy,envelope,mode,seed);total+=cap_est   # Task 22 (H6)
    else:
        cap_trials,cap_blocked=[],[]                # EX-18b: a unit policy plan holds no capacity trial; its estimate uses the approved shares
        total=math.fsum(bw.session_seconds(s,policy,calibration,dataset,measured) for s in sessions)
    stated=(unit_policy.get('windows') or {}).get('calibration_deadline_seconds') if bw is not None and mode=='smoke' and smoke_job is None else None
    smoke_cap=policy['job_deadlines']['smoke'] if stated is None else int(stated)       # EX-18c (EX18b-A04): the stated deadline of a calibration
    if mode=='smoke' and probed:            # R87: each session stays within the smoke job deadline (cap, above); the whole plan within the probe bound
        smoke_cap=PROBE_SMOKE_CAP_SECONDS
        if total>smoke_cap:raise GateError(f"the smoke plan with probe points ({total:.0f} s) exceeds its {PROBE_SMOKE_CAP_SECONDS} s bound "
                                           f"(every session within the {policy['job_deadlines']['smoke']} s smoke job deadline)")
    if mode=='smoke' and stated is not None and total>smoke_cap:
        raise GateError(f'the window smoke calibration plan ({total:.0f} s) exceeds its stated deadline windows.calibration_deadline_seconds ({smoke_cap} s)')
    if mode=='smoke' and total>smoke_cap:
        raise GateError(f"smoke plan exceeds the {policy['job_deadlines']['smoke']} s smoke job deadline")
    if mode=='decision' and bw is None and total>policy['budgets']['decision_cap_seconds']:
        raise GateError('plan exceeds the 8 h decision cap; the owner or approver chooses fallback A, B or C as a new plan version')
    body={'schema_version':1,'plan_version':version,'seed':seed,'case':case['case_id'],'case_version':case['version'],'mode':mode,'dataset':dataset,'envelope':envelope,
          'rows':[_plan_row(r) for r in rows],'blocked_rows':blocked,'sessions':sessions,'memory':memory,'estimate_seconds':round(total,1),
          'cap_seconds':smoke_cap if mode=='smoke' else policy['budgets']['decision_cap_seconds'],'calibration':calibration,
          'chunk_rule':policy['pools']['chunk_rule'],'partition':PARTITION,'partition_seed':PARTITION_SEED,'request_limit':policy['pools']['request_limit']}
    if cap_trials or cap_blocked:body.update(capacity=cap_trials,capacity_blocked=cap_blocked)   # Task 22: a case without capacity keeps its plan id
    budget=route_budget(body,policy,calibration)
    if budget:body['route_budget']=budget          # Task 19: per route and selector; only with C caller rows (other plans keep their plan id)
    datasets=plan_datasets(points,policy)
    if datasets:body['datasets']=datasets          # G6.6: only with dataset_ref points, so other plans keep their plan id
    if matrix!='full':body['matrix']=matrix        # Task 30: only a python matrix plan names its matrix, so a full plan keeps its plan id
    if project_identity is not None:body['project_identity']=project_identity   # Task 13a: the plan id binds the project content
    if calibration_source is not None:body['calibration_source']=dict(calibration_source)   # Task 19a: the plan id binds the calibration run and its digest
    if bw is not None:                              # EX-18b: only a unit policy plan names its policy, so every other plan keeps its plan id
        body['policy']=unit_policy['name']
        if smoke_job is not None:body['smoke_job']=smoke_job
        if repair is not None:body['repair']=dict(repair)
        if mode=='decision':
            body['cap_seconds']=int(unit_policy['windows']['window_seconds'])
            body['measured_reference']=measured     # EX-18c (EX18b-A03): the measured walls of the reference terms
            body.update(bw.window_plan(body,case,unit_policy,policy,calibration))
            body['estimate_seconds']=round(sum(w['estimate'] for w in body['windows']),1)
            body['calibration_report']=bw.calibration_report(calibration_observations,policy,calibration)     # EX-18c (EX18b-A06): in the plan id
    from bench_deadline import check_test_floor
    check_test_floor(body)                          # P3P-07: a built plan never carries the selftest keys (Task 6)
    body['plan_id']=hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()[:32]
    if project_dir is not None:body['project_dir']=project_dir      # the locator only; outside the plan id
    return body

def trial_selector(trial,point,case,policy,sizes,dataset,cap,calibration):
    """Amendment G4.2, G2.6: a trial carries its point's selector (default `all`, an opaque string) and, for a selector the
    case's call_deadline covers, call_deadline_seconds (capped by the session cap) and call_deadline_reason."""
    import bench_deadline
    import bench_model;bench_model.require_locked_selectors(policy,[point.get('selector','all')])      # A6P-05: no row of an unlocked tolerance block
    trial['selector']=point.get('selector','all')
    if 'unit' in point:trial['unit']=point['unit']             # Task 19 (G-CO1 field): C and Python rows of the point carry it
    if 'dataset_ref' in point:trial['dataset_ref']=point['dataset_ref']
    trial.update(bench_deadline.deadline_fields(case,policy,'timing',{'sizes':sizes,'dataset':dataset},trial,calibration,cap))

def plan_datasets(points,policy):
    """G6.6: `plan.datasets` {name: {kind, size, seed, sha256, rows, indices?}} for each dataset_ref of the planned points
    (`<kind>:<size>[#...]`). The sha256 of the filtered packed rows is filled by the run that materializes them (None here)."""
    out={}
    for p in points:
        ref=p.get('dataset_ref')
        if not ref or ref in out:continue
        kind,_,rest=ref.partition(':');size,_,part=rest.partition('#')
        if kind!='synthetic' or size not in policy['sizes']:raise GateError(f"{p.get('name','?')}: dataset_ref {ref} is not synthetic:<size>[#...]")
        row=re.fullmatch(r'row:([0-9]{1,5})',part)
        indices=list(p['panel']) if 'panel' in p else [int(row.group(1))] if row else None
        out[ref]={'kind':kind,'size':size,'seed':20261007,'sha256':None,'rows':len(indices) if indices is not None else policy['sizes'][size],**({'indices':indices} if indices is not None else {})}
    return out

def check_trial_design(plan,observations):
    """B09: each planned trial observed exactly once (pyperf: warmups + values brackets), warmups flagged, no extra trials."""
    problems=[];seen={}
    for o in observations:seen.setdefault(o['trial_id'],[]).append(o)
    planned={t['trial_id']:(t,s) for s in plan['sessions'] for t in s['trials']}
    for tid,(t,s) in planned.items():
        got=seen.get(tid,[])
        want=(plan.get('pyperf',{}).get('values',1)+plan.get('pyperf',{}).get('warmups',0)) if t['scope']=='kernel' and not c_variant(t['variant']) else 1   # Task 19: one C kernel row
        if len(got)!=want:problems.append(f'{tid}: {len(got)} observations, {want} planned')
        if any(o['warmup']!=t['warmup'] for o in got if t['scope']!='kernel'):problems.append(f'{tid}: warmup label differs')
    problems+=[f'{tid}: not in the plan' for tid in seen if tid not in planned]
    return problems

def parse_dataset(root,spec,policy):
    kind,_,value=spec.partition(':')
    if kind=='synthetic' and value in policy['sizes']:return {'kind':'synthetic','size':value,'seed':20261007,'sha256':None,'rows':policy['sizes'][value]}
    if kind=='local':
        try:from bench_privacy import resolve_local_dataset
        except ModuleNotFoundError as exc:raise GateError('local datasets are not available before Task 18') from exc
        return resolve_local_dataset(root,value)
    raise GateError('dataset must be synthetic:tiny|small|medium|large or local:PATH')

def calibration_run_dir(root,run_id):
    if not isinstance(run_id,str) or not re.fullmatch(r'[0-9a-f]{32}',run_id):raise GateError('calibration run id must be 32 lowercase hex digits')
    path=Path(root)/'artifacts/bench'/run_id/'observations.jsonl'
    if not path.is_file():raise GateError('calibration run has no observations')
    return path

CALIBRATION_FAMILIES=('py-reference','py-optimized')

def calibration_families(case):
    """EX-18b: the Python families that a calibration of `case` must measure: py-reference, and py-optimized when the case
    implements a Python variant of that family (a case without one, such as an example without a separate optimized
    implementation, has no row that needs its rate). The default without a case keeps both."""
    if not isinstance(case,dict) or not isinstance(case.get('variants'),list):return CALIBRATION_FAMILIES
    fams={family(v.get('id','')) for v in case['variants'] if isinstance(v,dict) and v.get('status')=='implemented' and v.get('language')=='python'}
    return tuple(f for f in CALIBRATION_FAMILIES if f=='py-reference' or f in fams)

def selector_calibration(observations,policy):
    """A8 (H15.3): {selector: {family: seconds per record}} of the eligible direct and 1-worker caller rows of a calibration
    run (the per-trial median rule of calibration_from_observations, per selector); reported in calibration_report
    share_check, never used to size a window (the two reference terms of a window use bench_windows.measured_reference,
    EX-18c)."""
    try:
        eligible=[o for o in observations if isinstance(o,dict) and not o['warmup'] and o['eligible'] and o['work_units'] and o['phase'] in ('caller','work')
                  and o['workers'] in ('direct',1)]
        per={}
        for o in eligible:per.setdefault((o.get('selector','all'),family(o['variant'])),[]).append(o)
        out={}
        for (sel,fam),obs in sorted(per.items()):out.setdefault(sel,{})[fam]=bs.median(bs.per_trial_values(obs,'wall_ns').values())/1e9
        return out
    except ValueError as exc:raise GateError(f'calibration run is inconsistent: {exc}') from None
    except (KeyError,TypeError,AttributeError,ZeroDivisionError):raise GateError('calibration observations are malformed') from None

def calibration_from_observations(observations,policy,required=CALIBRATION_FAMILIES):
    """Seconds per record per family: median over trials of each trial's per-unit median (loops x records; ruling F-07).
    `required`: the Python families the calibration must hold (calibration_families of the case)."""
    try:
        # G2.6 (Task 1 review): only selector `all` rows; the deadline applies the selector share once, on top of this rate
        eligible=[o for o in observations if not o['warmup'] and o['eligible'] and o['work_units'] and o['phase'] in ('caller','work') and o['workers'] in ('direct',1)
                  and o.get('selector','all')=='all']
        per={}
        for o in eligible:per.setdefault(family(o['variant']),[]).append(o)
        cal={fam:bs.median(bs.per_trial_values(obs,'wall_ns').values())/1e9 for fam,obs in per.items() if fam!='c'}
    except ValueError as exc:raise GateError(f'calibration run is inconsistent: {exc}') from None
    except (KeyError,TypeError,AttributeError,ZeroDivisionError):raise GateError('calibration observations are malformed') from None
    cal['c']=policy['budgets']['estimate_seconds_per_record']['c']
    unknown=sorted(set(cal)-{'py-reference','py-optimized','py-library','c'})        # py-library: optional, when measured (Task 9b)
    if unknown:raise GateError('calibration run holds an unknown family '+', '.join(unknown))
    missing=[f for f in required if f not in cal]
    if missing:raise GateError('calibration run lacks eligible rows for the Python families '+', '.join(missing))
    return cal

def load_calibration(root,run_id,policy):
    """Reads one run's observations.jsonl; any malformed line or record is BLOCKED (GateError), never an exception."""
    return calibration_record(root,run_id,policy)[0]

def calibration_record(root,run_id,policy,required=CALIBRATION_FAMILIES):
    """(calibration, source): the source names the run and the sha256 of the exact observation bytes the calibration came from,
    read once. A written plan carries the source, so `bench run --plan` re-derives the calibration instead of trusting it."""
    calibration,source,_=calibration_inputs(root,run_id,policy,required)
    return calibration,source

def calibration_inputs(root,run_id,policy,required=CALIBRATION_FAMILIES):
    """EX-18c: (calibration, source, observations) of one read of a calibration run: the rates and the source of
    calibration_record and the observation rows of those same bytes (a window plan derives its measured reference walls
    and its calibration report from them). T6-R7: the calibration also holds `walls`, the measured walls of the same rows
    (measured_walls), so a written plan binds them and bench run --plan re-derives them like the rates."""
    observations=[]
    try:data=read_capped(calibration_run_dir(root,run_id),CAPPED_JSON_MAX_BYTES,'calibration-jsonl','calibration observations');text=data.decode('utf-8',errors='strict')
    except (OSError,UnicodeDecodeError):raise GateError('calibration observations are unreadable') from None
    for line in text.splitlines():
        if not line.strip():continue
        try:value=loads_capped(line,'calibration-jsonl')      # FR3-19: container-written rows, capped
        except ValueError:raise GateError('calibration observations are not valid JSON lines') from None
        if not isinstance(value,dict):raise GateError('calibration observations are malformed')
        observations.append(value)
    calibration=dict(calibration_from_observations(observations,policy,required),walls=measured_walls(observations,policy))
    return calibration,{'run_id':run_id,'observations_sha256':hashlib.sha256(data).hexdigest()},observations
