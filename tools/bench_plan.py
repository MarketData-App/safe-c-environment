"""Bench plans: rows, randomized blocks, budget and session caps (spec 8.3). Never shrinks a dataset, trial count or row."""
import hashlib, json, math, random, re
from pathlib import Path
from evidence import GateError, CAPPED_JSON_MAX_BYTES, loads_capped, read_capped
import bench_stats as bs

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
    times the selector share). Empty without a C caller trial."""
    out={}
    for s in plan['sessions']:
        for t in s['trials']:
            if t.get('route') is None:continue
            sel=t.get('selector','all');est=trial_estimate(policy,t['variant'],policy['sizes'][t['tier']],t.get('loops',1),calibration)*route_share(policy,sel)
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
    so the reference status of every panel row is OK. The per-call wall is the planning estimate (or the calibrated rate)
    of one one-row call with the selector share (bench_deadline.expected_seconds)."""
    import bench_deadline
    panel=list(point['panel']);cells=panel_cells(policy)
    if len(panel)!=len(cells):raise GateError(f"{point.get('name','?')}: a single-record panel holds the {len(cells)} panel cells")
    per_call=bench_deadline.expected_seconds(policy,{'variant':trial['variant'],'selector':point.get('selector','all')},1,1,calibration)
    passes=panel_passes(per_call_seconds=per_call,mode=trial['mode'])
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
    """The estimate of one panel trial: calls = 6 x L (L = 1 cold) of one one-row request each, plus the trial overhead."""
    import bench_deadline
    f=panel_fields({'variant':variant,'mode':mode},point,policy,calibration)
    per_call=bench_deadline.expected_seconds(policy,{'variant':variant,'selector':point.get('selector','all')},1,1,calibration)
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

def _points(case,mode):
    if mode=='smoke':
        return [{'name':'smoke-caller','scope':'caller','size':'small','modes':['warm','cold'],'variants':None,'class':'exploratory','blocks':'smoke'},
                {'name':'smoke-kernel','scope':'kernel','size':'small','modes':['direct'],'variants':['py-reference','py-optimized','c-serial'],'class':'exploratory','blocks':1}]   # Task 19: the C kernel row
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
    """Amendment E item 6: the rows of one pooled trial. A synthetic dataset uses the policy size of the trial's tier; a
    local dataset uses the planned prefix length plan['dataset']['rows']."""
    kind=plan['dataset']['kind']
    if kind=='synthetic':return policy['sizes'][trial['tier']]
    if kind=='local':return plan['dataset']['rows']
    raise GateError(f'unknown dataset kind {kind!r}')

def build_plan(case,policy,*,mode,dataset,seed,envelope,calibration=None,project_dir=None,project_identity=None,calibration_source=None):
    if mode=='selftest':raise GateError('the selftest mode is built only by bench selftest code (bench_deadline.stub_plan), never by build_plan')
    if calibration_source is not None and calibration is None:raise GateError('a calibration source needs its calibration')
    problems=point_problems(case,policy)
    if problems:raise GateError('case points reference undeclared entries: '+'; '.join(problems))
    missing=[k for k in DATASET_KEYS if k not in dataset]
    if missing:raise GateError('dataset record lacks '+', '.join(missing))
    dataset={k:dataset[k] for k in DATASET_KEYS}     # F-11: allowlist; a plan never holds the owner-fixture path or a label
    sizes=policy['sizes'];trials=policy['trials'];rows,blocked=case_rows(case,envelope)      # Task 19: (variant, workers, route) rows
    cap=policy['job_deadlines']['smoke'] if mode=='smoke' else policy['budgets']['session_cap_seconds'];sessions=[];version='v1';total=0.0
    for point in _points(case,mode):
        if point['scope'] not in case['scopes']:continue
        size=sizes[point['size']];names=point['variants']
        prow=[r for r in rows if (names is None or r['variant'] in names) and not (r['variant']=='py-reference' and point['size']=='large')]
        if point['scope']=='kernel':prow=[r for r in prow if r['workers']=='direct']
        if not prow:continue
        specs,cold=_point_specs(point,prow,point['modes'])
        blocked+=[b for b in cold if b not in blocked]
        nblocks=trials['smoke_blocks'] if point['blocks']=='smoke' else point['blocks'] if point['blocks'] else trials['primary'] if point['class']=='primary' else trials['secondary'] if point['class']=='secondary' else trials['exploratory'][0]
        warmed=not (mode=='decision' and point['class']=='exploratory')        # spec 8.3: exploratory decision rows get no warmup
        est=(lambda v,m,point=point:panel_trial_estimate(policy,point,v,m,calibration)) if 'panel' in point else (lambda v,m,size=size:trial_estimate(policy,v,size,1,calibration))   # G7.3
        warm=sum(est(v,m) for v,w,m,_ in specs) if warmed else 0.0
        block=sum(est(v,m) for v,w,m,_ in specs)
        if warm+block>cap:raise GateError(f"one block of {point['name']} exceeds the session cap; choose fallback A or C as a new plan version")
        per_session=max(1,int((cap-warm)//block));groups=[list(range(i,min(nblocks,i+per_session))) for i in range(0,nblocks,per_session)]
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
            sest=warm+block*len(g);total+=sest
            sessions.append({'session':sid,'group':point['name'],'point':point['name'],'scope':point['scope'],'tier':point['size'],'class':point['class'],'deadline_seconds':cap,'estimate_seconds':sest,'trials':tlist})
    mem_tier='small' if mode=='smoke' else 'medium';mem_n=trials['smoke_memory'] if mode=='smoke' else trials['memory_primary']
    memory=[{'trial_id':f"memory-{r['variant']}-{r['workers']}{_route_id(r)}-{k}",'point':'memory','tier':mem_tier,'variant':r['variant'],'workers':r['workers'],'mode':'warm','selector':'all',**_route_keys(r.get('route'),policy)} for r in rows for k in range(mem_n)]
    if 'caller' not in case['scopes']:memory=[]          # memory trials use caller-scope containers (spec 8.4 row 9)
    if mode=='decision' and memory:
        memory+=[{'trial_id':f"memory-large-{r['variant']}-{r['workers']}{_route_id(r)}",'point':'memory-large','tier':'large','variant':r['variant'],'workers':r['workers'],'mode':'warm','selector':'all',**_route_keys(r.get('route'),policy)} for r in rows if r['variant']!='py-reference']
        total+=sizes[dataset['size'] or 'large']*rate(policy,'py-reference',calibration)   # reference output, outside timing
    for m in memory:
        est=trial_estimate(policy,m['variant'],sizes[m['tier']],1,calibration)
        if est>policy['job_deadlines']['memory']:raise GateError(f"memory trial {m['trial_id']} exceeds the {policy['job_deadlines']['memory']} s memory-trial limit; choose a fallback as a new plan version")
        total+=est
    if dataset['kind']=='local' and sessions:   # a local run computes its reference inside its single container
        total+=max(sizes[x['tier']] for x in sessions)*rate(policy,'py-reference',calibration)
    import bench_capacity;cap_trials,cap_blocked,cap_est=bench_capacity.capacity_trials(case,policy,envelope,mode,seed);total+=cap_est   # Task 22 (H6)
    if mode=='smoke' and total>policy['job_deadlines']['smoke']:
        raise GateError(f"smoke plan exceeds the {policy['job_deadlines']['smoke']} s smoke job deadline")
    if mode=='decision' and total>policy['budgets']['decision_cap_seconds']:
        raise GateError('plan exceeds the 8 h decision cap; the owner or approver chooses fallback A, B or C as a new plan version')
    body={'schema_version':1,'plan_version':version,'seed':seed,'case':case['case_id'],'case_version':case['version'],'mode':mode,'dataset':dataset,'envelope':envelope,
          'rows':[_plan_row(r) for r in rows],'blocked_rows':blocked,'sessions':sessions,'memory':memory,'estimate_seconds':round(total,1),
          'cap_seconds':policy['job_deadlines']['smoke'] if mode=='smoke' else policy['budgets']['decision_cap_seconds'],'calibration':calibration,
          'chunk_rule':policy['pools']['chunk_rule'],'partition':PARTITION,'partition_seed':PARTITION_SEED,'request_limit':policy['pools']['request_limit']}
    if cap_trials or cap_blocked:body.update(capacity=cap_trials,capacity_blocked=cap_blocked)   # Task 22: a case without capacity keeps its plan id
    budget=route_budget(body,policy,calibration)
    if budget:body['route_budget']=budget          # Task 19: per route and selector; only with C caller rows (other plans keep their plan id)
    datasets=plan_datasets(_points(case,mode),policy)
    if datasets:body['datasets']=datasets          # G6.6: only with dataset_ref points, so other plans keep their plan id
    if project_identity is not None:body['project_identity']=project_identity   # Task 13a: the plan id binds the project content
    if calibration_source is not None:body['calibration_source']=dict(calibration_source)   # Task 19a: the plan id binds the calibration run and its digest
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

def calibration_from_observations(observations,policy):
    """Seconds per record per family: median over trials of each trial's per-unit median (loops x records; ruling F-07)."""
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
    missing=[f for f in ('py-reference','py-optimized') if f not in cal]
    if missing:raise GateError('calibration run lacks eligible rows for the Python families '+', '.join(missing))
    return cal

def load_calibration(root,run_id,policy):
    """Reads one run's observations.jsonl; any malformed line or record is BLOCKED (GateError), never an exception."""
    return calibration_record(root,run_id,policy)[0]

def calibration_record(root,run_id,policy):
    """(calibration, source): the source names the run and the sha256 of the exact observation bytes the calibration came from,
    read once. A written plan carries the source, so `bench run --plan` re-derives the calibration instead of trusting it."""
    observations=[]
    try:data=read_capped(calibration_run_dir(root,run_id),CAPPED_JSON_MAX_BYTES,'calibration-jsonl','calibration observations');text=data.decode('utf-8',errors='strict')
    except (OSError,UnicodeDecodeError):raise GateError('calibration observations are unreadable') from None
    for line in text.splitlines():
        if not line.strip():continue
        try:value=loads_capped(line,'calibration-jsonl')      # FR3-19: container-written rows, capped
        except ValueError:raise GateError('calibration observations are not valid JSON lines') from None
        if not isinstance(value,dict):raise GateError('calibration observations are malformed')
        observations.append(value)
    return calibration_from_observations(observations,policy),{'run_id':run_id,'observations_sha256':hashlib.sha256(data).hexdigest()}
