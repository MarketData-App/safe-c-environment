"""EX-18b (Phase 3 addendum Tasks A8 and A9, generic; Amendment H15.1 to H15.4, G10.3, I10): the window plan, the window
attempts, the control pairs, the extension windows and the window chain of a unit-threshold policy that declares
`windows` in its project protocol (schemas/bench-protocol.json).

The project protocol declares per policy the window sizing values (`window_seconds`: the longest window, at most the
86,400 s of the H15.1 safety rule; `cap_headroom` and `cap_step_seconds` of the proposed caps, H15.3; optional
`caps_seconds` {synthetic, local}, H15.4) and the two control pairs (`controls.base`: the base A/A pair, two identical
Python rows; `controls.candidate`: the candidate control pair, two identical C rows on one route), each a row of a caller
point of the policy's case. The units come from the policy, the selector shares from the protocol budgets, the statistics
and the pressure test from the framework policy. The framework names no policy, unit, model, control case or field.

Plan (A8): `bench plan --policy NAME --mode decision --calibrate SMOKE_RUN_ID` keeps the unit points and the slow-row
diagnostic points (`unit-<selector>-slowest`), sizes every session and reference batch with the calibrated rate and the
approved share, splits the plan into windows by the deterministic 24-hour rule (split_windows, H15.1) and records the
windows, the look-2 worst cases, E_ctrl, the proposed cap and the smoke calibration report. A plan never shrinks a block
count, a row or a dataset; a refusal names its reason and its estimates (PlanRefusal).

Runs (A9): `bench run --plan PATH --window ID` runs one attempt of one look-1 window (window_run_plan: the window's sessions
with the control trials interleaved); `bench run --extend RUN_ID` runs one attempt of the extension window of a PASS
look-1 window run, with the triggered units of its bound look-1 decision record (extension_run_plan). Each attempt records
its window, attempt number, `extends`, attempt outcome (PASS, BLOCKED window-pressure or window-control-noise, or FAIL
run-invalid for a run that is not valid) and envelope identity. `bench decide` reads the chain of the plan version
(chain_for_decide): the chain checks of H15.2, the recorded checks of every chain run, the pooled evidence of the PASS
positions and the window outcomes of the units.

EX-18c (the EX-18b approver findings): the sessions of a window plan are packed by the share-weighted estimate that every
session check reads, with room for the control trials of one session (A01); the reference batch and the reference panel
row use the walls that the smoke calibration measured (measured_reference; A03); a smoke calibration above the smoke job
deadline needs the stated deadline windows.calibration_deadline_seconds (A04); the calibration report holds the spread
of each control pair and is part of the plan id (A06); the first extension attempt pins the look-1 record, and the chain
digest leaves out the decision digests of a later decide (record_digest, look1_for_extension; A07)."""
import copy, hashlib, json, math, random, re, statistics
from pathlib import Path
from evidence import GateError, read_json

DAY=86400                      # H15.1: the longest window, E_ctrl included (the protocol may declare a shorter one)
MAX_WINDOWS=16                 # look-1 windows of one plan version (the decision record holds 32 positions: 16 look-1, 16 extensions)
EXTENSION_OFFSET=12            # G10.3: the extension blocks of a look-1 block b are b + 12 (primary_blocks, a schema const)
PAIRS=('base','candidate');SIDES=('a','b');FINAL=('PASS','FAIL')
WINDOW_ID=re.compile(r'^[12][a-p]$')
DIAGNOSTIC=re.compile(r'^unit-([a-z0-9-]{1,16})-slowest$')     # G3.6: the slow-row diagnostic point of a selector
CALIBRATION_SEED=20261007
RUN_JSON_MAX=4194304
METHOD=('per control pair: 1,000 sets (draws) of 12 paired per-block log-ratios drawn from a normal distribution with mean 0 and the '
        'standard deviation of the pair\'s per-block log-ratios in the smoke calibration run (seed 20261007), each set classified by the B13 '
        'classifier bench_stats.classify with the bench compare arguments; reported, never a pass condition')
LOOK1_RECORD='look1-decision.json';PLAN_VERSION='window-plan.json'

class PlanRefusal(GateError):
    """A refused window plan (exit 1, no container): the stable reason, a detail and the estimates that the refusal prints."""
    def __init__(self,reason,detail,estimates=None):
        self.reason=reason;self.detail=detail;self.estimates=list(estimates or [])
        super().__init__(f'{reason}: {detail}')

class NotAWindowRun(GateError):
    """decide was given a run that is not a window attempt of a window plan."""

def _sha(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

# ---- the 24-hour split (H15.1, the source text with the protocol's window length) ----
def cut(group,L):
    """Greedy session cut: each part takes the most sessions from the first unassigned one that keep it <= L; every part
    of a full-dataset group holds its own reference batch. An indivisible part above L refuses (window-cap-infeasible)."""
    parts=[];i=0;s=group['sessions'];ref=group.get('reference',0.0)
    while i<len(s):
        j=i;est=ref
        while j<len(s) and est+s[j]['seconds']<=L:est+=s[j]['seconds'];j+=1
        if j==i:raise PlanRefusal('window-cap-infeasible',f"{group['id']} part {len(parts)} estimate {ref+s[i]['seconds']:.0f} s above the group limit {L:.0f} s",
                                  [{'group':group['id'],'part':len(parts),'estimate':ref+s[i]['seconds']}])
        parts.append(dict(group,part=len(parts),sessions=s[i:j],estimate=est));i=j
    return parts

def split_windows(groups,e_ctrl,day=DAY):
    """H15.1: the group limit L = day - E_ctrl; parts sorted largest first (ties: order, part); n from ceil(W / day) upward;
    each part to the least-loaded window (ties: the lowest index); every window, E_ctrl included, at most `day`."""
    L=day-e_ctrl;parts=[p for g in groups for p in cut(g,L)]
    parts.sort(key=lambda p:(-p['estimate'],p['order'],p['part']))
    W=e_ctrl+sum(p['estimate'] for p in parts);n=max(1,math.ceil(W/day))
    while True:
        wins=[{'estimate':e_ctrl,'parts':[]} for _ in range(n)]
        for p in parts:
            k=min(range(n),key=lambda i:(wins[i]['estimate'],i));wins[k]['parts'].append(p);wins[k]['estimate']+=p['estimate']
        if all(w['estimate']<=day for w in wins):return [dict(w,id='1'+chr(ord('a')+i)) for i,w in enumerate(wins)]
        n+=1

def check_sessions(groups,cap=10800):
    """I10.2 feasibility: a session above the session cap refuses (session-cap-infeasible) before the split."""
    for g in groups:
        for s in g['sessions']:
            if s['seconds']>cap:raise PlanRefusal('session-cap-infeasible',f"{g['id']} session {s['id']} estimate {s['seconds']:.0f} s above the {cap} s session cap",
                                                  [{'group':g['id'],'session':s['id'],'estimate':s['seconds']}])

def check_window_count(windows):
    if len(windows)>MAX_WINDOWS:
        raise PlanRefusal('window-cap-infeasible',f'{len(windows)} windows; one plan version holds at most {MAX_WINDOWS}',
                          [{'window':w['id'],'estimate':w['estimate']} for w in windows])
    return windows

def look2_worst_case(window,e_ctrl):
    """The extension window of `window` when every unit triggers: its unit blocks and reference batches, one warmup set
    per session and E_ctrl, no diagnostics (at most the look-1 window estimate; never split)."""
    return e_ctrl+sum(p['estimate'] for p in window['parts'] if p.get('kind')!='diagnostics')

def cap(max_w,headroom=1.2,step=600):
    """H15.3: step x ceil(headroom x max W / step) (the protocol's headroom and step)."""
    return int(step*math.ceil(headroom*max_w/step))

# ---- estimates (I10.2 with the calibrated rate and the approved share, H15.3) ----
# EX-18c (EX18b-A03; G-ALO1 ruling (a) and finding ALO2-03 of the spec): the smoke calibration measures the wall of the
# reference batch of each full-dataset unit and the wall of the reference variant's panel row, and the window plan uses
# those measured walls for the reference batch R and for the reference panel term, never rate x share. `measured` is the
# plan's measured_reference ({'batch': {selector: seconds per record}, 'panel': {point: seconds per one-row call}}); None
# gives the planning form (a smoke plan). T6-R7 (design I9.3): every other trial term (each variant, the reference variant's
# multi-row trials too, and the control rows) uses the measured wall of its variant, selector and call class of the
# calibration (bench_deadline.measured_seconds; a missing wall refuses: wall-not-measured), never rate x share.
REFERENCE_VARIANT='py-reference'

def _is_reference(variant):
    import bench_plan as bp
    return bp.family(str(variant))==REFERENCE_VARIANT

def trial_seconds(trial,policy_doc,calibration,dataset,measured=None):
    """The window estimate of one trial: n x the wall of one row + the trial overhead, with n the rows x loops of the trial
    (a panel trial: 6 x L one-row calls, L = 1 cold). The wall: rate(family) x share(selector) before calibration; after it
    (T6-R7) the measured wall of the trial's variant, selector and call class (bench_deadline.measured_seconds; PlanRefusal
    wall-not-measured without one); a kernel trial keeps rate x share. With `measured`, a panel trial of the reference
    variant takes the measured per-call wall of its point (PlanRefusal reference-not-measured when the calibration holds
    none). GateError for an unapproved share."""
    import bench_deadline
    if 'panel' in trial:rows,calls=1,(6 if trial.get('mode')=='cold' else 6*trial['panel_passes'])
    else:                                         # EX-19: a local plan records no row count (F-11: rows null): the tier rows that a local job slices
        local=(dataset or {}).get('rows') if (dataset or {}).get('kind')=='local' else None
        rows,calls=(local if type(local) is int else policy_doc['sizes'][trial['tier']]),trial.get('loops',1)
    over=policy_doc['budgets']['trial_overhead_seconds']
    if measured is not None and 'panel' in trial and _is_reference(trial.get('variant')):
        wall=(measured.get('panel') or {}).get(trial.get('point'))
        if wall is None:raise PlanRefusal('reference-not-measured',f"point {trial.get('point')}: the calibration run holds no measured {REFERENCE_VARIANT} panel wall "
                                          '(bench run --policy NAME --mode smoke measures it)',[{'point':trial.get('point'),'variant':trial.get('variant')}])
        return wall*rows*calls+over
    if trial.get('scope')=='kernel':return bench_deadline.expected_seconds(policy_doc,trial,rows,calls,calibration)+over
    return bench_deadline.measured_seconds(policy_doc,trial,rows,calls,calibration)+over

def session_seconds(session,policy_doc,calibration,dataset,measured=None):
    """The trials of one session (its warmup set included), each by trial_seconds; an exactly rounded sum (math.fsum), so a
    session gives the same value in any trial order (the packing of build_plan and the checks of window_plan read it)."""
    return math.fsum(trial_seconds(t,policy_doc,calibration,dataset,measured) for t in session['trials'])

def reference_seconds(unit,rows,policy_doc,calibration,measured=None):
    """I10.3: the reference batch of a full-dataset unit (0 for another unit): with `measured`, rows x the measured
    reference wall per record of the unit's selector (PlanRefusal reference-not-measured without one); else the planning
    form rows x rate(py-reference) x share(selector)."""
    if not str(unit).endswith('/full-dataset'):return 0.0
    sel=unit.partition('/')[0]
    if measured is not None:
        wall=(measured.get('batch') or {}).get(sel)
        if wall is None:raise PlanRefusal('reference-not-measured',f'selector {sel}: the calibration run holds no measured {REFERENCE_VARIANT} reference batch wall '
                                          '(bench run --policy NAME --mode smoke measures it)',[{'unit':unit}])
        return rows*wall
    import bench_deadline
    return bench_deadline.expected_seconds(policy_doc,{'variant':REFERENCE_VARIANT,'selector':sel},rows,1,calibration)

# EX19-LOCAL-ESTIMATE-01 (T5-A08): a reference never leaves a local container (spec 12), so a local window has no shared
# reference batch per group part: the local runner (bench_local_decision) runs one container per session, and each job
# computes its reference over its rows with its reference selector, and a whole-run job also its summary. The estimate of
# a local plan counts LOCAL_REFERENCE_BATCHES batches in every session (its reference and a summary of one reference batch,
# as the framework control's local_summary computes; counted for every job, an upper bound: a partial job, T5-A01, computes
# no summary) and no group reference.
LOCAL_REFERENCE_BATCHES=2

def is_local(dataset):return (dataset or {}).get('kind')=='local'

def local_job_trials(trials,case,policy):
    """The trials of the local job of one window session as the local runner sees them: the session's trials and the control
    rows that window_run_plan interleaves into every session (their tier and selector)."""
    return list(trials)+[{'tier':r['tier'],'selector':r['selector'],'scope':'caller'} for r in control_rows(case,policy) if r.get('tier')]

def local_batch_seconds(sel,rows,policy,policy_doc,calibration,measured=None):
    """One reference batch of the selector `sel` over `rows` rows: with `measured`, rows x the measured wall per record of
    `sel` (selector `all` without its own measured wall: the sum over the policy's selectors; PlanRefusal
    reference-not-measured without a wall); else the planning form rows x rate(py-reference) x share(sel)."""
    if measured is not None:
        batch=measured.get('batch') or {};names=[sel] if sel in batch or sel!='all' else sorted(_selectors(policy))
        missing=[s for s in names if s not in batch]
        if missing:raise PlanRefusal('reference-not-measured',f'selector {missing[0]}: the calibration run holds no measured {REFERENCE_VARIANT} reference batch wall '
                                     'of a local job (bench run --policy NAME --mode smoke measures it)',[{'selector':missing[0]}])
        return rows*math.fsum(batch[s] for s in names)
    import bench_deadline
    return bench_deadline.expected_seconds(policy_doc,{'variant':REFERENCE_VARIANT,'selector':sel},rows,1,calibration)

def local_reference_seconds(trials,case,policy,policy_doc,calibration,measured=None):
    """The reference work of the local job of one window session: LOCAL_REFERENCE_BATCHES batches (local_batch_seconds) over
    the job's rows (bench_local_decision.job_rows) with its reference selector (job_selector) of local_job_trials."""
    import bench_local_decision as bl
    tr=local_job_trials(trials,case,policy)
    return LOCAL_REFERENCE_BATCHES*local_batch_seconds(bl.job_selector(tr),bl.job_rows(tr,policy_doc['sizes']),policy,policy_doc,calibration,measured)

def reference_points(case,policy):
    """EX-18c: {selector: [point names]} of the smoke calibration points that measure the reference batch of each
    full-dataset unit of the policy: the unit's own points that list the reference variant (no panel, no dataset_ref), else
    the added point reference-<selector> of window_smoke_points."""
    out={}
    for u in policy.get('units') or []:
        if not str(u).endswith('/full-dataset'):continue
        sel=u.partition('/')[0]
        own=[p['name'] for p in case.get('points') or [] if isinstance(p,dict) and p.get('unit')==u and 'panel' not in p and 'dataset_ref' not in p
             and REFERENCE_VARIANT in (p.get('variants') or [])]
        out[sel]=own or [f'reference-{sel}']
    return out

def _panel_reference_points(case,policy):
    """The panel points of a window plan (the unit points and the slow-row diagnostics) that list the reference variant."""
    units=set(policy.get('units') or [])
    return sorted(p['name'] for p in case.get('points') or [] if isinstance(p,dict) and 'panel' in p and REFERENCE_VARIANT in (p.get('variants') or [])
                  and (p.get('unit') in units or _diagnostic(p,policy)))

def measured_reference(observations,case,policy):
    """EX-18c (EX18b-A03): the measured reference walls of a smoke calibration run, the input of a window plan:
    batch {selector: seconds per record}: the reference variant's rows at the points of reference_points (no panel row);
    panel {point: seconds per one-row call}: the reference variant's panel rows of each panel point. The per-trial median
    rule of calibration_from_observations (eligible, non-warmup, direct and 1-worker rows of the phases caller and work). A
    value without an eligible trial is absent (the window plan then refuses: reference-not-measured)."""
    import bench_plan as bp, bench_stats as bs
    pts=reference_points(case,policy);panel=_panel_reference_points(case,policy)
    try:
        rows=[o for o in observations or [] if not o['warmup'] and o['eligible'] and o['work_units'] and o['phase'] in ('caller','work')
              and o['workers'] in ('direct',1) and bp.family(o['variant'])==REFERENCE_VARIANT]
        batch={}
        for sel,names in sorted(pts.items()):
            obs=[o for o in rows if o.get('point') in names and o.get('selector','all')==sel and 'panel_passes' not in o]
            if obs:batch[sel]=bs.median(bs.per_trial_values(obs,'wall_ns').values())/1e9
        walls={}
        for name in panel:
            obs=[o for o in rows if o.get('point')==name and 'panel_passes' in o]
            if obs:walls[name]=bs.median(bs.per_trial_values(obs,'wall_ns').values())/1e9
    except ValueError as exc:raise GateError(f'calibration run is inconsistent: {exc}') from None
    except (KeyError,TypeError,AttributeError,ZeroDivisionError):raise GateError('calibration observations are malformed') from None
    return {'batch':batch,'panel':walls}

# ---- the control pairs (H15.2) ----
def _point(case,name):return next((p for p in case.get('points') or [] if isinstance(p,dict) and p.get('name')==name),None)

def control_rows(case,policy):
    """The four control rows of every window: per pair (base, candidate) two identical rows a and b of the declared
    variant at the declared point's size and selector, warm and direct (the candidate pair on its declared route)."""
    decl=((policy.get('windows') or {}).get('controls') or {}) if isinstance(policy,dict) else {};out=[]
    for pair in PAIRS:
        c=decl.get(pair) or {};p=_point(case,c.get('point')) or {}
        for side in SIDES:
            row={'pair':pair,'member':side,'point':f'control-{pair}-{side}','variant':c.get('variant'),'workers':'direct','tier':p.get('size'),
                 'selector':p.get('selector','all'),'source_point':c.get('point')}
            if c.get('route'):row['route']=c['route']
            out.append(row)
    return out

def control_tier(case,policy,pair):return next(r['tier'] for r in control_rows(case,policy) if r['pair']==pair)

def _control_seconds(row,policy_doc,calibration):
    """One control trial: its tier rows at the planning rate x share, or (T6-R7) at the measured wall after calibration."""
    import bench_deadline
    return (bench_deadline.measured_seconds(policy_doc,{'variant':row['variant'],'selector':row['selector']},policy_doc['sizes'][row['tier']],1,calibration)
            +policy_doc['budgets']['trial_overhead_seconds'])

def control_load(policy_doc,calibration,case,policy,trials):
    """The estimate of `trials` trials of each control row (an exactly rounded sum, math.fsum): the control trials of one
    session with its control blocks and its warmup trial, or of a whole window (e_ctrl)."""
    return math.fsum(c for c in (_control_seconds(r,policy_doc,calibration) for r in control_rows(case,policy)) for _ in range(trials))

def e_ctrl(policy_doc,calibration,case,policy,sessions):
    """H15.1 (PB-L2): the control cost of a window of `sessions` sessions: per control row 12 paired blocks plus one warmup
    trial per session. e_ctrl(..., 1) is also the most that the control trials of one session cost (all 12 blocks and one
    warmup), which build_plan keeps free in every session of a window plan (EX-18c, EX18b-A01)."""
    return control_load(policy_doc,calibration,case,policy,int(policy.get('primary_blocks',EXTENSION_OFFSET))+sessions)

def control_assignment(sessions,blocks=EXTENSION_OFFSET):
    """The control blocks of each session of a window: consecutive ranges with the bounds round(blocks x i / sessions)
    (half up), so every block is in exactly one session."""
    edges=[(2*blocks*i+sessions)//(2*sessions) for i in range(sessions+1)]
    return [list(range(edges[i],edges[i+1])) for i in range(sessions)]

def declaration_problems(case,policy):
    """The checks of a windows declaration against the policy's case (bench_model calls it at protocol load, build_plan
    before a window plan): each control row is an implemented direct variant listed at a caller point with the warm mode
    (not a panel point; py-reference never at the large size); the base pair is a Python row without a route; the candidate
    pair is a C row on one of its routes (and of the point's routes)."""
    decl=policy.get('windows') if isinstance(policy,dict) else None
    if not isinstance(decl,dict):return []
    import bench_plan as bp
    out=[];variants={v.get('id'):v for v in case.get('variants') or [] if isinstance(v,dict)}
    for pair in PAIRS:
        c=(decl.get('controls') or {}).get(pair) or {};label=f'windows.controls.{pair}'
        p=_point(case,c.get('point'))
        if p is None:out.append(f"{label}: {c.get('point')} is not a point of case {case.get('case_id')}");continue
        if p.get('scope')!='caller':out.append(f"{label}: point {p['name']} is no caller point")
        if 'warm' not in (p.get('modes') or []):out.append(f"{label}: point {p['name']} has no warm mode")
        if 'panel' in p:out.append(f"{label}: point {p['name']} is a panel point")
        v=variants.get(c.get('variant'))
        if v is None or v.get('status')!='implemented':out.append(f"{label}: variant {c.get('variant')} is not an implemented variant of the case");continue
        if c['variant'] not in (p.get('variants') or []):out.append(f"{label}: point {p['name']} does not list variant {c['variant']}")
        if c['variant']=='py-reference' and p.get('size')=='large':out.append(f"{label}: py-reference is never planned at the large size")
        if 'direct' not in (v.get('workers') or []):out.append(f"{label}: variant {c['variant']} has no direct row")
        if pair=='base':
            if v.get('language') not in ('python','python-library'):out.append(f"{label}: the base pair is a Python row")
            if c.get('route'):out.append(f"{label}: a Python row has no route")
        else:
            if v.get('language')!='c':out.append(f"{label}: the candidate pair is a C row")
            routes=list(v.get('routes') or bp.DEFAULT_ROUTES)
            if not c.get('route'):out.append(f"{label}: the candidate pair names its route")
            elif c['route'] not in routes or ('routes' in p and c['route'] not in p['routes']):out.append(f"{label}: route {c['route']} is no route of the row")
    return out

def require_window_policy(case,policy,mode,calibration,matrix='full',smoke_job=None):
    """build_plan with a unit policy: the policy declares windows (a G10.4 unit smoke job needs only the units), decides this
    case and its declaration holds; a window plan measures the full matrix; a decision plan needs a calibration (H15.3)."""
    name=policy.get('name')
    if policy.get('kind')!='unit-threshold':raise GateError(f'--policy {name}: a window plan needs a unit-threshold policy')
    if smoke_job is None and not isinstance(policy.get('windows'),dict):raise GateError(f'--policy {name}: the policy declares no windows')
    if policy.get('case')!=case.get('case_id'):raise GateError(f"policy-case-mismatch: policy {name} is for case {policy.get('case')}, not {case.get('case_id')}")
    if matrix!='full':raise GateError('a window plan measures the full matrix')
    if mode=='decision' and calibration is None:raise GateError('a window plan needs a calibration (--calibrate SMOKE_RUN_ID, H15.3)')
    problems=declaration_problems(case,policy)
    if problems:raise GateError('; '.join(problems[:3])[:600])

# ---- the points of a policy plan ----
def _selectors(policy):return {u.partition('/')[0] for u in policy.get('units') or []}

def _diagnostic(point,policy):
    m=DIAGNOSTIC.match(str(point.get('name')))
    return bool(m) and 'unit' not in point and m.group(1) in _selectors(policy)

def _smoke(point,blocks):
    q=dict(point,modes=['warm'],blocks=blocks)
    if 'panel' not in q:q['size']='small'
    return q

def decision_points(case,policy):
    """A8: the unit points of the policy's units and their slow-row diagnostic points (G3.6)."""
    units=set(policy['units'])
    return [dict(p,blocks=None) for p in case['points'] if p.get('unit') in units or _diagnostic(p,policy)]

def window_smoke_points(case,policy,policy_doc=None):
    """A8 (PB-01): the smoke calibration plan: (a) the smoke-caller point unchanged (every variant, warm and cold, the
    family rates), (b) the unit points (full-dataset points at the small tier, single-record points on their panel), 2
    smoke blocks, warm, (c) the slow-row diagnostics, 1 block; (d) the control pairs are the control session of build_plan.
    EX-18c (EX18b-A03): (e) for each full-dataset unit whose own points list no reference row (reference_points), the point
    reference-<selector>: the reference variant at the small tier and the unit's selector, warm, 1 block; it measures the
    unit's reference batch. A case point of that name is refused (GateError)."""
    import bench_plan as bp
    units=set(policy['units'])
    added=[]
    for sel,names in reference_points(case,policy).items():
        if names!=[f'reference-{sel}']:continue
        if _point(case,names[0]) is not None:raise GateError(f'case point {names[0]} has the name of the reference calibration point of selector {sel}')
        added.append({'name':names[0],'scope':'caller','size':'small','modes':['warm'],'variants':[REFERENCE_VARIANT],'class':'exploratory','blocks':1,'selector':sel})
    return ([bp._points(case,'smoke')[0]]+[_smoke(p,'smoke') for p in case['points'] if p.get('unit') in units]
            +[_smoke(p,1) for p in case['points'] if _diagnostic(p,policy)]+added)

def unit_smoke_points(case,policy):
    """G10.4: the unit points of the policy (the full-dataset points at the small tier, the single-record points on their
    panel), 2 smoke blocks, warm."""
    units=set(policy['units']);order={u:i for i,u in enumerate(policy['units'])}
    pts=[p for p in case['points'] if p.get('unit') in units]
    return [_smoke(p,'smoke') for p in sorted(pts,key=lambda p:order[p['unit']])]

def point_smoke_seconds(case,point,policy_doc,envelope):
    """The share-weighted smoke estimate of one smoke point: (smoke blocks + one warmup set) x its trials."""
    import bench_plan as bp
    rows,_=bp.case_rows(case,envelope);names=point['variants']
    prow=[r for r in rows if r['variant'] in names and not (r['variant']=='py-reference' and point['size']=='large')]
    specs,_=bp._point_specs(point,prow,point['modes']);total=0.0
    for v,w,m,route in specs:
        t={'variant':v,'workers':w,'mode':m,'tier':point['size'],'loops':1,'selector':point.get('selector','all')}
        if 'panel' in point:t.update(bp.panel_fields(t,point,policy_doc,None))
        total+=trial_seconds(t,policy_doc,None,None)
    return total*(policy_doc['trials']['smoke_blocks']+1)

def unit_smoke_jobs(case,policy,policy_doc,envelope):
    """G10.4 with I10.8: the unit smoke points packed in policy unit order into jobs of at most the smoke deadline each (a
    new job when the next point does not fit); a point alone above the deadline refuses (GateError)."""
    limit=policy_doc['job_deadlines']['smoke'];jobs=[];cur=[];used=0.0
    for p in unit_smoke_points(case,policy):
        s=point_smoke_seconds(case,p,policy_doc,envelope)
        if s>limit:raise GateError(f"unit smoke point {p['name']}: {s:.0f} s above the {limit} s smoke deadline")
        if cur and used+s>limit:jobs.append(cur);cur=[];used=0.0
        cur.append(p);used+=s
    if cur:jobs.append(cur)
    return jobs

def plan_points(case,policy,policy_doc,mode,smoke_job,envelope):
    if mode=='decision':
        if smoke_job is not None:raise GateError('a smoke job is a smoke plan')
        return decision_points(case,policy)
    if smoke_job is None:return window_smoke_points(case,policy,policy_doc)
    jobs=unit_smoke_jobs(case,policy,policy_doc,envelope)
    if isinstance(smoke_job,bool) or not isinstance(smoke_job,int) or not 0<=smoke_job<len(jobs):raise GateError(f'unit smoke job {smoke_job!r} does not exist')
    return jobs[smoke_job]

# ---- the control trials of a run plan ----
def _control_trial(row,trial_id,block,order,warmup,case,policy_doc,dataset,calibration,cap_seconds):
    import bench_plan as bp
    t={'trial_id':trial_id,'block':block,'order':order,'point':row['point'],'scope':'caller','mode':'warm','variant':row['variant'],'workers':'direct',
       'tier':row['tier'],'loops':1,'warmup':warmup,**bp._route_keys(row.get('route'),policy_doc)}
    bp.trial_selector(t,{'selector':row['selector']},case,policy_doc,policy_doc['sizes'],dataset,cap_seconds,calibration)
    return t

def control_session_trials(case,policy,policy_doc,prefix,index,blocks,seed,dataset,calibration):
    """(warmups, block groups) of the control trials of one session: one warmup trial per control row, and per control
    block one trial of each row in a seeded order."""
    rows=control_rows(case,policy);cap_s=policy_doc['budgets']['session_cap_seconds']
    warm=[_control_trial(r,f'ctl-{prefix}-s{index:02d}-w{n:02d}',None,None,True,case,policy_doc,dataset,calibration,cap_s) for n,r in enumerate(rows)]
    groups=[]
    for b in blocks:
        order=list(rows);random.Random(f'{seed}:control:{prefix}:{b}').shuffle(order)
        groups.append([_control_trial(r,f'ctl-{prefix}-b{b:02d}-{o:02d}',b,o,False,case,policy_doc,dataset,calibration,cap_s) for o,r in enumerate(order)])
    return warm,groups

def _interleave(trials,warm,groups):
    """A session's trials with the control warmups after its own warmups and each control block after one of its own blocks."""
    own_warm=[t for t in trials if t['warmup']];by=[]
    for t in trials:
        if t['warmup']:continue
        if by and by[-1][0]==t['block']:by[-1][1].append(t)
        else:by.append((t['block'],[t]))
    out=own_warm+warm;m=len(by);r=len(groups)
    for i,(_,g) in enumerate(by):
        out+=g
        out+=[t for j,c in enumerate(groups) if (j*m)//r==i for t in c] if r else []
    if not m:out+=[t for c in groups for t in c]
    return out

RUN_PLAN_KEYS=('schema_version','plan_version','seed','case','case_version','mode','dataset','envelope','rows','calibration','chunk_rule','partition',
               'partition_seed','request_limit','policy','project_identity','calibration_source','datasets','cap_seconds')

def _run_plan(version,wid,look,sessions,estimate,case,policy,policy_doc):
    blocks=int(policy.get('primary_blocks',EXTENSION_OFFSET));out=[]
    for i,(s,ctl) in enumerate(zip(sessions,control_assignment(len(sessions),blocks))):
        warm,groups=control_session_trials(case,policy,policy_doc,wid,i,ctl,version['seed'],version['dataset'],version.get('calibration'))
        out.append(dict(s,trials=_interleave(s['trials'],warm,groups)))
    body={k:copy.deepcopy(version[k]) for k in RUN_PLAN_KEYS if k in version}
    body.update(sessions=out,memory=[],estimate_seconds=estimate,window={'id':wid,'look':look,'plan_id':version['plan_id']},
                blocked_rows=[r for r in version.get('blocked_rows') or [] if not (isinstance(r,dict) and r.get('guardrail') is True)])
    body['plan_id']=hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()[:32]     # bench.plan_digest of the body
    if 'project_dir' in version:body['project_dir']=version['project_dir']
    return body

def _window(version,wid):
    win=next((w for w in version.get('windows') or [] if w.get('id')==wid),None)
    if win is None:raise GateError(f'{wid} is not a look-1 window of the plan version')
    return win

def window_run_plan(version,wid,case,policy,policy_doc):
    """A9: the run plan of one attempt of the look-1 window `wid`: its sessions in plan order, each with one warmup trial per
    control row and its control blocks (control_assignment) interleaved; no memory or capacity trial. Deterministic."""
    win=_window(version,wid);by={s['session']:s for s in version['sessions']}
    return _run_plan(version,wid,1,[copy.deepcopy(by[sid]) for sid in win['sessions']],win['estimate'],case,policy,policy_doc)

def _shifted(session,offset,seed):
    """An extension session: the same cells with each block b moved to b + offset (a new seeded order per block), its warmup
    set kept; every trial id starts with x."""
    sid=session['session'];warm=[dict(t,trial_id='x'+t['trial_id']) for t in session['trials'] if t['warmup']];by={}
    for t in session['trials']:
        if not t['warmup']:by.setdefault(t['block'],[]).append(t)
    trials=list(warm)
    for b in sorted(by):
        cells=sorted(by[b],key=lambda t:t['order']);random.Random(f"{seed}:{session['point']}:{b+offset}").shuffle(cells)
        trials+=[dict(t,trial_id=f'x{sid}-b{b+offset:02d}-{o:02d}',block=b+offset,order=o) for o,t in enumerate(cells)]
    return dict(session,session='x'+sid,trials=trials)

def extension_run_plan(version,base_wid,units,case,policy,policy_doc):
    """A9 (G10.3, PB-05): the run plan of one attempt of the extension window of the look-1 window `base_wid`: the sessions
    of the triggered `units` in that window with their extension blocks b + 12 of every cell, one warmup set per session,
    the reference batches of the units and the window's own control pairs; no diagnostics."""
    win=_window(version,base_wid);units=list(units or [])
    if not units:raise GateError(f'window {base_wid}: no triggered unit, so no extension window')
    outside=[u for u in units if u not in win['units']]
    if outside:raise GateError(f'window {base_wid} holds no unit '+', '.join(outside))
    by={s['session']:s for s in version['sessions']};sessions=[]
    for sid in win['sessions']:
        s=by[sid];su={t.get('unit') for t in s['trials'] if t.get('unit')}
        if su&set(units):sessions.append(_shifted(s,EXTENSION_OFFSET,version['seed']))
    m=version.get('measured_reference')         # EX-18c: the measured reference walls of the plan version
    estimate=e_ctrl(policy_doc,version.get('calibration'),case,policy,len(sessions))+sum(session_seconds(s,policy_doc,version.get('calibration'),version['dataset'],m) for s in sessions)
    if is_local(version['dataset']):            # T5-A08: every local session job computes its own reference (local_reference_seconds)
        estimate+=sum(local_reference_seconds(s['trials'],case,policy,policy_doc,version.get('calibration'),m) for s in sessions)
    else:estimate+=sum(reference_seconds(u,version['dataset'].get('rows') or policy_doc['sizes']['large'],policy_doc,version.get('calibration'),m) for u in units)
    return _run_plan(version,'2'+base_wid[1:],2,sessions,estimate,case,policy,policy_doc)

# ---- the window plan (A8) ----
def _session_kind(session,policy):
    full=[u for u in policy['units'] if u.endswith('/full-dataset')];one=[u for u in policy['units'] if u.endswith('/single-record')]
    units={t['unit'] for t in session['trials'] if t.get('unit')}
    if len(units)>1:raise GateError(f"session {session['session']} holds more than one unit")
    if units:
        u=units.pop()
        if u in full:return 'unit',u,[u]
        if u in one:return 'single-record','single-record',[u]
        return None,None,[]
    if DIAGNOSTIC.match(str(session.get('point'))):return 'diagnostics','diagnostics',[]
    return None,None,[]

def groups(plan,policy,policy_doc,calibration,case=None):
    """H15.1: each full-dataset unit with its reference batch is one group (order: its index among the policy's full-dataset
    units); the single-record units are one group, the slow-row diagnostics one group (the two last orders). The sessions
    and the reference batches use the plan's measured reference walls (EX-18c; measured_reference). A local plan (T5-A08)
    has no group reference batch: each session counts the reference work of its own local job (local_reference_seconds,
    with the control rows of `case`)."""
    full=[u for u in policy['units'] if u.endswith('/full-dataset')];measured=plan.get('measured_reference');local=is_local(plan.get('dataset'))
    rows=(plan.get('dataset') or {}).get('rows') or policy_doc['sizes']['large'];out={}
    if local and case is None:raise GateError('the estimate of a local window plan needs the case of its control rows')
    for s in plan['sessions']:
        kind,key,units=_session_kind(s,policy)
        if kind is None:continue
        g=out.get(key)
        if g is None:
            ref=reference_seconds(key,rows,policy_doc,calibration,measured) if kind=='unit' and not local else 0.0
            order=full.index(key) if kind=='unit' else len(full)+(0 if kind=='single-record' else 1)
            g=out[key]={'id':key,'kind':kind,'order':order,'reference':ref,'units':[],'sessions':[]}
        own=local_reference_seconds(s['trials'],case,policy,policy_doc,calibration,measured) if local else 0.0
        g['sessions'].append({'id':s['session'],'seconds':session_seconds(s,policy_doc,calibration,plan.get('dataset'),measured)+own})
        g['units']+=[u for u in units if u not in g['units']]
    return sorted(out.values(),key=lambda g:g['order'])

def window_plan(plan,case,policy,policy_doc,calibration):
    """A8: the window plan of a built decision plan: check_sessions, the E_ctrl iteration with split_windows (the session
    count of the largest window, until it no longer grows), every session with its control trials within the session cap,
    at most 16 windows, the look-2 worst cases, the proposed cap of the plan's dataset and the declared cap check. Returns
    {'windows', 'look2', 'e_ctrl', 'caps_proposed'}."""
    decl=policy['windows'];day=int(decl.get('window_seconds',DAY));cap_s=policy_doc['budgets']['session_cap_seconds']
    gs=groups(plan,policy,policy_doc,calibration,case);check_sessions(gs,cap_s)
    estimates=[{'group':g['id'],'estimate':g['reference']+sum(x['seconds'] for x in g['sessions'])} for g in gs]
    if not gs:raise PlanRefusal('window-cap-infeasible','the plan holds no unit session',estimates)
    s=1
    while True:
        E=e_ctrl(policy_doc,calibration,case,policy,s)
        try:wins=split_windows(gs,E,day)
        except PlanRefusal as exc:raise PlanRefusal(exc.reason,exc.detail,exc.estimates+estimates) from None
        m=max(sum(len(p['sessions']) for p in w['parts']) for w in wins)
        if m<=s:break
        s=m
    check_window_count(wins)
    order={x['session']:i for i,x in enumerate(plan['sessions'])};by={x['session']:x for x in plan['sessions']}
    blocks=int(policy.get('primary_blocks',EXTENSION_OFFSET));out=[]
    for w in wins:
        seconds={x['id']:x['seconds'] for p in w['parts'] for x in p['sessions']}
        sids=sorted(seconds,key=order.get)
        if e_ctrl(policy_doc,calibration,case,policy,len(sids))>E+1e-9:raise PlanRefusal('window-cap-infeasible',f"window {w['id']}: its control cost exceeds the E_ctrl of the split")
        for sid,ctl in zip(sids,control_assignment(len(sids),blocks)):
            total=seconds[sid]+control_load(policy_doc,calibration,case,policy,len(ctl)+1)     # its control blocks and one warmup per control row
            if total>cap_s:raise PlanRefusal('session-cap-infeasible',f"window {w['id']} session {sid}: {total:.0f} s with its control trials above the {cap_s} s session cap",
                                             [{'window':w['id'],'session':sid,'estimate':total}])
        units=[u for u in policy['units'] if any(u in p['units'] for p in w['parts'])]
        out.append({'id':w['id'],'estimate':w['estimate'],'e_ctrl':E,'sessions':sids,'units':units,
                    'blocks':{u:sorted({t['block'] for sid in sids for t in by[sid]['trials'] if t.get('unit')==u and not t['warmup']}) for u in units},
                    'parts':[{'group':p['id'],'kind':p['kind'],'part':p['part'],'sessions':[x['id'] for x in p['sessions']],'units':list(p['units']),
                              'reference':p['reference'],'estimate':p['estimate']} for p in w['parts']]})
    look2=[{'window':w['id'],'estimate':look2_worst_case(w,E)} for w in wins]
    kind=(plan.get('dataset') or {}).get('kind');proposed={kind:cap(max(w['estimate'] for w in out),decl['cap_headroom'],decl['cap_step_seconds'])}
    caps=decl.get('caps_seconds')
    if isinstance(caps,dict):
        over=[{'window':w['id'],'estimate':w['estimate'],'cap':caps.get(kind)} for w in out if w['estimate']>caps.get(kind,0)]
        if over:raise PlanRefusal('owner-cap-exceeded',f"a window estimate is above the declared {kind} cap {caps.get(kind)} s",over)
    return {'windows':out,'look2':look2,'e_ctrl':E,'caps_proposed':proposed}

# ---- the smoke calibration report (H15.2; reported, never a pass condition) ----
def _pressure(o):
    v=o.get('cpu_pressure_total')
    return v if isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) else None

def _timed_rows(observations):
    return [o for o in observations or [] if isinstance(o,dict) and not o.get('warmup') and o.get('scope')=='caller' and o.get('block') is not None]

def _wall_by_block(rows):
    import bench
    try:return bench.per_trial(rows,'wall_ns')
    except (ValueError,KeyError,TypeError,ZeroDivisionError):return {}

def _row_key(o):return (o.get('point'),o.get('variant'),o.get('workers'),o.get('mode'),o.get('route'))

def _row_label(key):
    point,variant,workers,mode,route=key
    return f'{point} {variant} x{workers}'+(f' [{route}]' if route else '')+f' {mode}'

def calibration_report(observations,policy_doc,calibration=None,draws=1000,pairs=PAIRS):
    """trip_rate per row (the share of its smoke blocks whose cpu_pressure_total is above factor x the row's median and
    above min_usec; null with the reason for fewer than 3 smoke blocks), control_non_equal per control pair (METHOD) and,
    with the calibration, share_check {selector: {family: measured / (rate x share)}}. EX-18c (EX18b-A06): the input of
    the prediction per control pair: control_blocks (the paired blocks), control_log_ratios (their per-block log-ratios in
    block order) and control_sd (their sample standard deviation; null below 2 paired blocks). The report is part of the
    plan id; bench run --plan re-derives it from the bound calibration run."""
    import bench_stats as bs, bench_plan as bp
    rule=policy_doc['controls']['aa_pressure'];rows=_timed_rows(observations);by={}
    for o in rows:by.setdefault(_row_key(o),[]).append(o)
    trip={};why={}
    for key,obs in sorted(by.items(),key=lambda kv:str(kv[0])):
        label=_row_label(key);vals=[v for v in (_pressure(o) for o in obs) if v is not None]
        if len({o['block'] for o in obs})<3:trip[label]=None;why[label]='fewer than 3 smoke blocks: test (b) cannot trip'
        elif not vals:trip[label]=None;why[label]='no readable pressure value'
        else:
            med=bs.median(vals);trip[label]=sum(1 for v in vals if v>rule['factor']*med and v>rule['min_usec'])/len(vals);why[label]=None
    eff=policy_doc['effects'];st=policy_doc['statistics'];non_equal={};reasons={};sds={};counts={};logs={}
    for pair in pairs:
        a=_wall_by_block([o for o in rows if o.get('point')==f'control-{pair}-a']);b=_wall_by_block([o for o in rows if o.get('point')==f'control-{pair}-b'])
        blocks=sorted(k for k in set(a)&set(b) if a[k]>0 and b[k]>0)
        logs[pair]=[math.log(b[k]/a[k]) for k in blocks];counts[pair]=len(blocks);sds[pair]=None
        if len(blocks)<2:non_equal[pair]=None;reasons[pair]='the calibration run holds no control pair with 2 or more paired blocks';continue
        sd=sds[pair]=statistics.stdev(logs[pair]);rng=random.Random(CALIBRATION_SEED);n=EXTENSION_OFFSET;count=0
        for _ in range(draws):
            other={j:math.exp(rng.gauss(0.0,sd)) for j in range(n)}
            out=bs.classify({j:1.0 for j in range(n)},other,relative=eff['relative'],min_abs=eff['min_abs_ns_per_unit'],min_blocks=eff['min_blocks'],
                            resamples=st['bootstrap_resamples'],seed=st['bootstrap_seed'],interval=st['interval'])['outcome']
            count+=out!='EQUAL'
        non_equal[pair]=count/draws;reasons[pair]=None
    report={'trip_rate':trip,'trip_reason':why,'control_non_equal':non_equal,'control_reason':reasons,'control_blocks':counts,'control_sd':sds,
            'control_log_ratios':logs,'method':METHOD,'draws':draws}
    if calibration is not None:
        shares=policy_doc['budgets'].get('estimate_share_per_selector',{})
        report['share_check']={sel:{fam:rate/(calibration[fam]*(1.0 if sel=='all' else float(shares.get(sel,1.0)))) for fam,rate in fams.items() if fam in calibration and calibration[fam]}
                               for sel,fams in bp.selector_calibration(observations,policy_doc).items()}
    return report

# ---- attempts (A9, H15.2) ----
def control_result(base,other,policy_doc):
    """The B13 classification of one control pair on the attempt's paired blocks (the bench compare arguments)."""
    import bench_stats as bs
    eff=policy_doc['effects'];st=policy_doc['statistics']
    return bs.classify(base,other,relative=eff['relative'],min_abs=eff['min_abs_ns_per_unit'],min_blocks=eff['min_blocks'],resamples=st['bootstrap_resamples'],
                       seed=st['bootstrap_seed'],interval=st['interval'])['outcome']

def _trips(values,rule):
    import bench_stats as bs
    known=[v for v in values if v is not None]
    if len(known)<2:return False                  # a row with one block cannot meet the per-row test
    med=bs.median(known)
    return any(v>rule['factor']*med and v>rule['min_usec'] for v in known)

def attempt_outcome(controls,rows_pressure,policy):
    """H15.2: BLOCKED window-pressure when a pressure value is unreadable, when a control pair is not EQUAL and the H12 test
    holds for one of its rows, or when any block of any other row meets the H12 test against that row's median; else BLOCKED
    window-control-noise when a control pair is not EQUAL; else PASS. rows_pressure: {pair: {row: [values]}, 'rows': {...}}."""
    rule=policy['controls']['aa_pressure']
    if any(v is None for g in rows_pressure.values() for vals in g.values() for v in vals):return 'BLOCKED','window-pressure'
    for pair,outcome in controls.items():
        if outcome!='EQUAL' and any(_trips(vals,rule) for vals in (rows_pressure.get(pair) or {}).values()):return 'BLOCKED','window-pressure'
    if any(_trips(vals,rule) for vals in (rows_pressure.get('rows') or {}).values()):return 'BLOCKED','window-pressure'
    if any(outcome!='EQUAL' for outcome in controls.values()):return 'BLOCKED','window-control-noise'
    return 'PASS',None

def pressure_rows(observations,pairs=PAIRS):
    """{pair: {'a': [...], 'b': [...]}, 'rows': {label: [...]}}: the per-block cpu_pressure_total (None: unreadable) of the
    timed caller rows of an attempt, in block order."""
    rows=_timed_rows(observations);out={p:{} for p in pairs};out['rows']={};by={}
    for o in rows:by.setdefault(_row_key(o),[]).append(o)
    for key,obs in sorted(by.items(),key=lambda kv:str(kv[0])):
        vals=[_pressure(o) for o in sorted(obs,key=lambda o:o['block'])]
        m=re.fullmatch(r'control-(.+)-([ab])',str(key[0]))
        if m and m.group(1) in pairs:out[m.group(1)][m.group(2)]=vals
        else:out['rows'][_row_label(key)]=vals
    return out

def run_attempt_outcome(run_status,observations,policy_doc,pairs=PAIRS):
    """The recorded outcome of one window attempt: FAIL run-invalid for a run that is INVALID_EXPERIMENT (a final position:
    its units are order 1 and the window is never run again); BLOCKED window-pressure for a run that measured nothing or
    lacks a control row (the pressure is unreadable); else attempt_outcome on the control pairs and the pressure rows."""
    none={p:None for p in pairs}
    if run_status=='INVALID_EXPERIMENT':return {'status':'FAIL','reason':'run-invalid','controls':none}
    rows=_timed_rows(observations)
    if run_status!='VALID' or not rows:return {'status':'BLOCKED','reason':'window-pressure','controls':none}
    controls={}
    for p in pairs:
        a=[o for o in rows if o.get('point')==f'control-{p}-a'];b=[o for o in rows if o.get('point')==f'control-{p}-b']
        controls[p]=control_result(_wall_by_block(a),_wall_by_block(b),policy_doc) if a and b else 'INCONCLUSIVE'
    pr=pressure_rows(observations,pairs)
    if any(set(pr[p])!=set(SIDES) for p in pairs):return {'status':'BLOCKED','reason':'window-pressure','controls':controls}
    status,reason=attempt_outcome(controls,pr,policy_doc)
    return {'status':status,'reason':reason,'controls':controls}

# ---- envelope identity and extensions (moved from base Task 19, G10.3, P3P-20) ----
def envelope_identity(run,root=None):
    """G10.3: the bench profile digest, cpuset size and SMT labeling, image id, framework policy and project protocol
    digests, case version, source identity, native build sha256 values and dataset identities of one run record."""
    env=run.get('envelope') if isinstance(run.get('envelope'),dict) else {}
    native=(run.get('native') or {}).get('binaries') if isinstance(run.get('native'),dict) else None
    ds=run.get('dataset') if isinstance(run.get('dataset'),dict) else {}
    datasets={'primary':_sha({k:ds.get(k) for k in ('kind','size','seed','sha256','rows')})}
    for name,value in sorted((run.get('datasets') or {}).items()):datasets[str(name)]=_sha(value)
    return {'bench_profile_sha256':run.get('bench_profile_sha256'),'cpuset_size':len(env.get('cpuset') or []),'smt_siblings':list(env.get('smt_siblings') or []),
            'image_id':run.get('image_id'),'policy_sha256':run.get('policy_sha256'),'protocol_sha256':run.get('protocol_sha256'),'case_version':run.get('case_version'),
            'source_identity':run.get('source_identity'),'native':dict(native or {}),'datasets':datasets}

def windows_match(id1,id2):
    """The keys whose values differ between two envelope identities ([] when the windows may pool their blocks)."""
    a=id1 if isinstance(id1,dict) else {};b=id2 if isinstance(id2,dict) else {}
    return sorted(k for k in set(a)|set(b) if a.get(k)!=b.get(k))

def _triggered(record):
    return [u['unit'] for u in (record or {}).get('units') or [] if isinstance(u,dict) and ((u.get('extension') or {}).get('trigger') is True)]

def extension_plan(look1_record,plan,look1_blocks=None):
    """The extension of a look-1 window: the triggered units of the recorded look-1 unit records only, with blocks b + 12
    for the unit's look-1 blocks in that window (default 0-11: one list 12-23; with look1_blocks: a dict per unit), and the
    cells of each unit; None when no unit triggers. No agent or person chooses a unit."""
    units=_triggered(look1_record)
    if not units:return None
    cells=(plan or {}).get('cells') or {}
    blocks=list(range(EXTENSION_OFFSET,2*EXTENSION_OFFSET)) if look1_blocks is None else {u:[b+EXTENSION_OFFSET for b in look1_blocks.get(u,[])] for u in units}
    return {'units':units,'blocks':blocks,'cells':{u:list(cells.get(u,[])) for u in units}}

def check_extension(look1_record,extension,id1,id2,look1_blocks=None):
    """The B09 extension refusals: `extension without trigger`, `discarded blocks` (blocks other than b + 12 of the unit's
    look-1 blocks in that window, or fewer observed blocks than planned) and `window envelope mismatch`."""
    problems=[];trig=set(_triggered(look1_record));units=list((extension or {}).get('units') or [])
    if not units or any(u not in trig for u in units):problems.append('extension without trigger')
    got=(extension or {}).get('blocks')
    for u in units:
        want=[b+EXTENSION_OFFSET for b in (look1_blocks.get(u,[]) if look1_blocks is not None else range(EXTENSION_OFFSET))]
        have=got.get(u) if isinstance(got,dict) else got
        if sorted(have or [])!=sorted(want):problems.append('discarded blocks');break
    if windows_match(id1,id2):problems.append('window envelope mismatch')
    return problems

# ---- the chain of a plan version (H15.2) ----
def plan_runs(root,plan_id):
    """(run directory, run record) of every recorded window attempt of the plan version (artifacts/bench/*/run.json)."""
    base=Path(root)/'artifacts/bench';out=[]
    if not base.is_dir() or base.is_symlink():return out
    for d in sorted(base.iterdir()):
        p=d/'run.json'
        try:
            if d.is_symlink() or p.is_symlink() or not p.is_file() or p.stat().st_size>RUN_JSON_MAX:continue
            run=read_json(p)
        except (OSError,ValueError,GateError):continue
        if isinstance(run,dict) and run.get('window_plan_id')==plan_id and WINDOW_ID.match(str(run.get('window'))):out.append((d,run))
    return out

def _wkey(w):return (int(w[0]),w[1:]) if WINDOW_ID.match(str(w)) else (9,str(w))

def _by_window(ch):
    by={}
    for a in sorted(ch.get('attempts') or [],key=lambda a:a.get('seq',0)):by.setdefault(a['window'],[]).append(a)
    return by

def record_digest(run):
    """EX-18c (EX18b-A07): the chain digest of a window attempt: the run record digest of run.json without the decision
    digests that a later bench decide binds into it (bench_evidence.bind_decisions). A decide therefore never changes a
    chain position, an `extends` link or the base digest of an extension. A run without decision digests keeps its recorded
    run_record_sha256 (the record as bench run wrote it; an altered run keeps the digest it was bound with, and chain()
    marks it not intact); the whole run.json stays bound by run_record_sha256."""
    import bench_evidence as be
    if be.DECISIONS_KEY not in run:return run.get(be.RECORD_KEY)
    return be.run_record_sha256({k:v for k,v in run.items() if k!=be.DECISIONS_KEY})

def chain(root,plan_id):
    """The window chain of a plan version from its run records: attempts (window, attempt, status and reason of the attempt
    outcome, record_sha256 (the chain digest, record_digest), extends, seq: the run-record order), superseded (the BLOCKED
    attempts), superseded_files ({record_sha256: the run record is present and its digest holds}), exhausted (3 BLOCKED
    attempts, not all window-control-noise) and positions ({window: the record_sha256 of its final attempt})."""
    import bench_evidence as be
    rows=[]
    for d,run in plan_runs(root,plan_id):
        out=run.get('attempt_outcome') if isinstance(run.get('attempt_outcome'),dict) else {}
        rows.append({'window':run['window'],'attempt':run.get('attempt'),'status':out.get('status'),'reason':out.get('reason'),
                     'record_sha256':record_digest(run) if be.RECORD_KEY in run else None,
                     'extends':run.get('extends'),'run_id':run.get('run_id'),'created_at':str(run.get('created_at')),'identity':run.get('envelope_identity'),
                     'extension_of':run.get('extension_of'),'intact':be.RECORD_KEY in run and be.verify_record(run)==[]})
    rows.sort(key=lambda a:(a['created_at'],str(a['run_id'])))
    for k,a in enumerate(rows):a['seq']=k
    ch={'plan_id':plan_id,'attempts':rows};by=_by_window(ch)
    ch['superseded']=[a for a in rows if a['status']=='BLOCKED']
    ch['superseded_files']={a['record_sha256']:a['intact'] for a in ch['superseded']}
    ch['exhausted']=sorted(w for w,lst in by.items() if [a['attempt'] for a in lst]==[1,2,3] and all(a['status']=='BLOCKED' for a in lst)
                           and not all(a['reason']=='window-control-noise' for a in lst))
    ch['positions']={w:lst[-1]['record_sha256'] for w,lst in by.items() if lst[-1]['status'] in FINAL}
    return ch

def chain_problems(ch,planned_look1,triggered):
    """Every H15.2 chain check ([] for a valid chain): every planned look-1 window once, in plan order, as a final position
    (its latest attempt PASS or FAIL, every earlier attempt BLOCKED and superseded) or an exhausted position (attempts 1-3,
    all BLOCKED, superseded, listed); extension ids only for a PASS look-1 window whose units triggered; superseded files
    present with equal digests; attempt numbers from 1 without a gap, none after a final attempt, at most 3; the windows in
    plan order; each `extends` names the nearest earlier final position."""
    P=[];by=_by_window(ch);planned=list(planned_look1);ext={'2'+w[1:]:w for w in planned}
    sup={a['record_sha256'] for a in ch.get('superseded') or []};ex=set(ch.get('exhausted') or []);files=ch.get('superseded_files') or {};final={}
    for w in sorted(by,key=_wkey):
        lst=by[w]
        if w not in planned and w not in ext:P.append(f'{w}: not a window of the plan version');continue
        if w in ext:
            if ext[w] not in triggered:P.append(f'{w}: an extension of window {ext[w]}, which has no triggered unit')
            if ext[w] in ex:P.append(f'{w}: an extension of the exhausted window {ext[w]}')
        nums=[a['attempt'] for a in lst]
        if nums!=list(range(1,len(nums)+1)):P.append(f'{w}: attempt numbers {nums} do not start at 1 without a gap')
        if len(lst)>3:P.append(f'{w}: {len(lst)} attempts (at most 3)')
        P+=[f"{w}: attempt {a['attempt']} has the status {a['status']}" for a in lst if a['status'] not in ('PASS','BLOCKED','FAIL')]
        done=[i for i,a in enumerate(lst) if a['status'] in FINAL]
        if done and done[0]!=len(lst)-1:P.append(f'{w}: an attempt after a final attempt')
        P+=[f"{w}: the BLOCKED attempt {a['attempt']} is not in superseded" for a in lst if a['status']=='BLOCKED' and a['record_sha256'] not in sup]
        last=lst[-1]
        if last['status'] in FINAL:
            if w in ex:P.append(f"{w}: listed as exhausted, but its last attempt is {last['status']}")
            if (ch.get('positions') or {}).get(w)!=last['record_sha256']:P.append(f'{w}: the chain position is not the latest attempt')
            final[w]=last
        elif w in ex:
            if not (nums==[1,2,3] and all(a['status']=='BLOCKED' for a in lst)):P.append(f'{w}: exhausted with fewer than 3 BLOCKED attempts')
        else:P.append(f'{w}: no final attempt and not exhausted')
    P+=[f'{w}: missing (no attempt)' for w in planned if w not in by]
    P+=[f'{w}: exhausted without an attempt' for w in sorted(ex) if w not in by]
    P+=[f'{w}: an extension of window {ext[w]}, whose run failed' for w in by if w in ext and ext[w] in final and final[ext[w]]['status']!='PASS']
    P+=[f'superseded record {str(sha)[:12]}: missing or altered' for sha,ok in files.items() if not ok]
    P+=[f"superseded record of {a['window']} attempt {a['attempt']}: not checked" for a in ch.get('superseded') or [] if a['record_sha256'] not in files]
    order=sorted(by,key=_wkey)
    for x,y in zip(order,order[1:]):
        if max(a.get('seq',0) for a in by[x])>min(a.get('seq',0) for a in by[y]):P.append(f'{y}: reordered window ids (an attempt of {y} ran before the last attempt of {x})')
    prev=None
    for w in order:
        if w not in final:continue
        want=None if prev is None else final[prev]['record_sha256']
        if final[w].get('extends')!=want:P.append(f"{w}: extends names {str(final[w].get('extends'))[:12]}, not the nearest earlier final position")
        prev=w
    return list(dict.fromkeys(P))

def chain_state(ch):
    """{'positions', 'superseded', 'exhausted', 'control_fail'}: control_fail is true when one window has 3 attempts, all
    BLOCKED window-control-noise (FAIL window-control-fail: decide refuses the plan version)."""
    by=_by_window(ch)
    fail=any(len(lst)==3 and all(a['status']=='BLOCKED' and a.get('reason')=='window-control-noise' for a in lst) for lst in by.values())
    return {'positions':dict(ch.get('positions') or {}),'superseded':[{k:a.get(k) for k in ('window','attempt','record_sha256','status','reason')} for a in ch.get('superseded') or []],
            'exhausted':list(ch.get('exhausted') or []),'control_fail':fail}

def _closed(lst):return bool(lst) and (lst[-1]['status'] in FINAL or (len(lst)==3 and all(a['status']=='BLOCKED' for a in lst)))

def window_refusal(ch,plan,wid,triggered=None):
    """None when `bench run` may run the next attempt of window `wid`; else the reason (exit 1): a control-fail plan
    version, an unknown window, an earlier window in plan order that has neither a final attempt nor an exhausted state, a
    final attempt of `wid` (never run again) or 3 attempts."""
    if chain_state(ch)['control_fail']:return 'window-control-fail: a window of this plan version ended with three window-control-noise attempts; bench decide refuses the plan version'
    planned=[w['id'] for w in plan.get('windows') or []]
    if not WINDOW_ID.match(str(wid)) or ('1'+str(wid)[1:]) not in planned:return f'{wid} is not a window of the plan version'
    by=_by_window(ch)
    if wid[0]=='1':earlier=planned[:planned.index(wid)]
    else:
        trig=list(triggered or [])
        earlier=planned+['2'+w[1:] for w in planned if w in trig and _wkey('2'+w[1:])<_wkey(wid)]
    for w in earlier:
        if not _closed(by.get(w)):return f'{wid} runs after window {w} has a final attempt or is exhausted'
    lst=by.get(wid,[])
    if lst and lst[-1]['status'] in FINAL:return f"{wid} has a final attempt ({lst[-1]['status']}); a final attempt is never run again"
    if len(lst)>=3:return f'{wid} has 3 attempts (exhausted)'
    return None

def next_attempt(ch,wid):return 1+len(_by_window(ch).get(wid,[]))

def extends_of(ch,plan,wid):
    """The record_sha256 of the nearest earlier final position in plan order (1a, 1b, ..., then 2a, 2b, ...), or None."""
    planned=[w['id'] for w in plan.get('windows') or []];by=_by_window(ch);prev=None
    for w in planned+['2'+x[1:] for x in planned]:
        if w==wid:return prev
        lst=by.get(w)
        if lst and lst[-1]['status'] in FINAL:prev=lst[-1]['record_sha256']
    return prev

def control_fail_versions(root,plan_ids):
    """The plan versions among `plan_ids` whose chain ended FAIL window-control-fail."""
    return sorted(p for p in set(plan_ids) if chain_state(chain(root,p))['control_fail'])

def previous_versions(root,case_id,policy_name,dataset):
    """The plan ids of recorded window attempts whose plan version has the same case, policy and dataset identity."""
    keys=('kind','size','seed','sha256','rows');want={k:(dataset or {}).get(k) for k in keys};out=set()
    base=Path(root)/'artifacts/bench'
    for d in (sorted(base.iterdir()) if base.is_dir() and not base.is_symlink() else []):
        p=d/PLAN_VERSION
        try:
            if d.is_symlink() or p.is_symlink() or not p.is_file():continue
            v=read_json(p)
        except (OSError,ValueError,GateError):continue
        if isinstance(v,dict) and v.get('case')==case_id and v.get('policy')==policy_name and {k:(v.get('dataset') or {}).get(k) for k in keys}==want:
            out.add(v.get('plan_id'))
    return out

def repair_record(root,project,text,failed):
    """H15.2: --repair LEDGER_ID:COMMIT for a new plan version after window-control-fail: the ledger finding (the framework
    ledger or the project's review ledger) is VERIFIED (closed) and the commit is a hex identity; otherwise PlanRefusal
    control-fail-unrepaired (bench plan: exit 1, no container)."""
    m=re.fullmatch(r'([A-Za-z0-9][A-Za-z0-9-]{1,63}):([0-9a-f]{7,64})',str(text or ''))
    if not m:raise PlanRefusal('control-fail-unrepaired','--repair needs LEDGER_ID:COMMIT',[{'plan_id':p} for p in sorted(failed)][:8])
    ledger_id,commit=m.groups();rows=[]
    for rel in ['safety/framework-ledger.json']+([f'{project}/review/ledger.json'] if project not in (None,'.') else ['review/ledger.json']):
        p=Path(root)/rel
        try:doc=read_json(p) if p.is_file() and not p.is_symlink() else {}
        except (OSError,ValueError,GateError):doc={}
        rows+=[r for r in (doc.get('findings') or []) if isinstance(r,dict)]
    row=next((r for r in rows if r.get('id')==ledger_id),None)
    if row is None or row.get('state')!='VERIFIED':raise PlanRefusal('control-fail-unrepaired',f'ledger finding {ledger_id} is not a closed (VERIFIED) finding',
                                                                        [{'plan_id':p} for p in sorted(failed)][:8])
    return {'ledger_id':ledger_id,'commit':commit,'plan_ids':sorted(failed)}

# ---- decide over the chain (A9) ----
CHAIN_FIXTURE_IDENTITY={'bench_profile_sha256':'a'*64,'cpuset_size':4,'smt_siblings':[],'image_id':'sha256:'+'b'*64,'policy_sha256':'c'*64,'protocol_sha256':None,
                        'case_version':1,'source_identity':'d'*64,'native':{},'datasets':{'primary':'f'*64}}
CHAIN_FIXTURE_STATE={'history':{'plan_id':'0'*32,'attempts':[{'window':'1a','attempt':1,'status':'PASS','reason':None,'record_sha256':'1'*64,'extends':None,
                                                               'seq':0,'run_id':'0'*32,'identity':CHAIN_FIXTURE_IDENTITY,'extension_of':None}],
                                'superseded':[],'superseded_files':{},'exhausted':[],'positions':{'1a':'1'*64}},
                     'problems':[],'state':{'positions':{'1a':'1'*64},'superseded':[],'exhausted':[],'control_fail':False},'pooled':[]}

UEV_FIXTURE={'status':'VALID','reasons':[],'rows':[],'blocked_other':[],'envelope_not_planned':[],'looks':{},'extension_not_run':[],'window_mismatch':[],
             'reference_evals':{},'panel_evals':{},'project_check':{'exit':None,'report_path':None,'report_sha256':None,'identity':None,'local':None},
             'current_identity':'a'*64,'opportunity_state':'APPROVED','coverage_ok':True,'coverage_power':None,'reference_admit_excluded':None,
             'library_overhead_ns_per_row':None}

def windows_record(cfd,plan_id):
    """The decision record `windows` object: plan_id, the final positions (window, attempt, run id, record digest, status,
    sha256 of the envelope identity), the superseded attempts and the exhausted windows."""
    ch=cfd['history'];by=_by_window(ch);pos=[]
    for w in sorted(by,key=_wkey):
        last=by[w][-1]
        if last['status'] in FINAL and (ch.get('positions') or {}).get(w)==last['record_sha256']:
            pos.append({'window':w,'attempt':last['attempt'],'run_id':last['run_id'],'record_sha256':last['record_sha256'],'status':last['status'],
                        'envelope_identity_sha256':_sha(last.get('identity'))})
    sup=[{'window':a['window'],'attempt':a['attempt'],'record_sha256':a['record_sha256'],'status':a['status'],'reason':str(a.get('reason'))[:300]} for a in ch.get('superseded') or []]
    return {'plan_id':str(plan_id)[:64],'positions':pos[:32],'superseded':sup[:96],'exhausted':list(ch.get('exhausted') or [])[:32]}

CHAIN_FIXTURE_RECORD=windows_record(CHAIN_FIXTURE_STATE,'0'*32)

def _strip(plan):return {k:v for k,v in plan.items() if k not in ('project_dir','pyperf')} if isinstance(plan,dict) else plan

def version_of(run_dir,plan_id):
    """The plan version that a window attempt binds (window-plan.json, an evidence file of the run): unedited (its plan id
    is its digest) and the plan version of the run's window_plan_id."""
    import bench
    v=read_json(Path(run_dir)/PLAN_VERSION)
    if not isinstance(v,dict) or v.get('plan_id')!=plan_id or bench.plan_digest(v)!=plan_id:raise GateError('the plan version of the window attempt is not the bound plan version')
    return v

def look1_copy(run_dir):
    """(record, sha256) of the look-1 decision record that an extension attempt copied, or (None, None)."""
    p=Path(run_dir)/LOOK1_RECORD
    try:data=p.read_bytes() if p.is_file() and not p.is_symlink() else None
    except OSError:data=None
    if data is None:return None,None
    from evidence import loads_capped
    try:rec=loads_capped(data,'look1-decision')
    except ValueError:return None,None
    return (rec if isinstance(rec,dict) else None),hashlib.sha256(data).hexdigest()

def look1_record_of(root,run_id,policy_name):
    """bench run --extend: the bound look-1 decision record of a look-1 window attempt: decision-<policy>.json of the run,
    whose sha256 equals the run record's decision_digests entry. (record, sha256, bytes); GateError otherwise."""
    import bench, bench_evidence as be
    d=bench._run_dir(root,run_id);run=read_json(d/'run.json')
    if be.verify_record(run) or be.RECORD_KEY not in run:raise GateError('the base run record is not bound (run_record_sha256)')
    want=(run.get(be.DECISIONS_KEY) or {}).get(policy_name);p=d/f'decision-{policy_name}.json'
    if want is None or not p.is_file():raise GateError(f'the base run has no look-1 decision record of policy {policy_name} (bench decide --run-id {run_id} --policy {policy_name} first)')
    data=p.read_bytes()
    if hashlib.sha256(data).hexdigest()!=want:raise GateError('the look-1 decision record differs from its bound digest')
    from evidence import loads_capped
    rec=loads_capped(data,'look1-decision')
    return rec,want,data

def look1_for_extension(root,ch,run_id,policy_name):
    """EX-18c (EX18b-A07): (record, sha256, bytes) of the look-1 decision record of the next extension attempt. The first
    extension attempt of the plan version (chain order) pins it: every later attempt takes that attempt's copy
    (look1-decision.json, an evidence file of its bound run, with the digest that its extension_of names), so a later
    bench decide never changes the record of an open extension window, and every extension attempt names one record
    (chain_for_decide). Without an extension attempt: the bound record of the base run (look1_record_of). GateError for a
    copy that is missing, altered or unbound."""
    import bench_evidence as be
    first=next((a for a in sorted(ch.get('attempts') or [],key=lambda a:a.get('seq',0)) if str(a.get('window'))[:1]=='2'),None)
    if first is None:return look1_record_of(root,run_id,policy_name)
    label=f"the look-1 record copy of the first extension attempt ({first['window']} attempt {first['attempt']})"
    d=Path(root)/'artifacts/bench'/str(first.get('run_id'))
    try:run=read_json(d/'run.json');data=(d/LOOK1_RECORD).read_bytes() if not (d/LOOK1_RECORD).is_symlink() else None
    except (OSError,ValueError,GateError):run,data=None,None
    if not isinstance(run,dict) or data is None or be.verify_record(run) or be.RECORD_KEY not in run or be.verify(d,run):raise GateError(f'{label} is not bound')
    sha=hashlib.sha256(data).hexdigest()
    if sha!=(run.get('extension_of') or {}).get('decision_sha256'):raise GateError(f'{label} differs from its recorded digest')
    from evidence import loads_capped
    return loads_capped(data,'look1-decision'),sha,data

def chain_for_decide(root,run_id):
    """A9: {'history', 'problems', 'state', 'pooled', 'evidence', 'plan_id'} of the plan version of a window attempt.
    problems: chain_problems, the recorded checks of every final position and extension run (bench_phase3_cli
    recorded_problems), each final run's plan (the run plan of the plan version), the extension checks (check_extension,
    the bound look-1 record copy, the extended position). evidence: the observations of the PASS positions (look-1 unit and
    diagnostic rows; the extension rows of a unit whose every look-1 window has a PASS extension: look 2), the merged plan,
    looks, window_pressure (the units of an exhausted look-1 window), extension_exhausted, window_invalid (the units of a
    FAIL position). pooled: [{unit, windows, identities}] of every unit with blocks in more than one window."""
    import bench, bench_model as bm, bench_phase3_cli as cli
    root=Path(root);d=bench._run_dir(root,run_id);run=read_json(d/'run.json')
    plan_id=run.get('window_plan_id') if isinstance(run,dict) else None
    if not isinstance(plan_id,str) or not WINDOW_ID.match(str(run.get('window'))):
        raise NotAWindowRun('the run is not a window attempt of a window plan (bench run --plan PATH --window ID)')
    version=version_of(d,plan_id);project=version.get('project_dir')
    pol=bm.load_decision_policy(root,version['policy'],project);case=bm.load_case(root,version['case'],project);doc=bm.load_policy(root,project)
    ch=chain(root,plan_id);by=_by_window(ch);planned=[w['id'] for w in version['windows']];units_of={w['id']:list(w['units']) for w in version['windows']}
    finals={w:lst[-1] for w,lst in by.items() if lst[-1]['status'] in FINAL};runs={w:root/'artifacts/bench'/a['run_id'] for w,a in finals.items()}
    problems=[];look1=None
    for a in ch['attempts']:
        if a['window'][0]!='2':continue
        rec,sha=look1_copy(root/'artifacts/bench'/a['run_id'])
        if rec is None:problems.append(f"{a['window']} attempt {a['attempt']}: no look-1 decision record copy");continue
        if (a.get('extension_of') or {}).get('decision_sha256')!=sha:problems.append(f"{a['window']} attempt {a['attempt']}: the look-1 record copy differs from its recorded digest")
        if look1 is None:look1=(rec,sha)
        elif sha!=look1[1]:problems.append('the extension attempts name different look-1 decision records')
    triggered=set()
    if look1 is not None:
        if (look1[0].get('windows') or {}).get('plan_id')!=plan_id:problems.append('the look-1 decision record names another plan version')
        trig=set(_triggered(look1[0]));triggered={w for w in planned if trig&set(units_of[w])}
    problems+=chain_problems(ch,planned,triggered)
    for w,a in sorted(finals.items(),key=lambda kv:_wkey(kv[0])):
        problems+=[f'{w}: {p}' for p in cli.recorded_problems(root,a['run_id'])]
        try:sub=read_json(runs[w]/'plan.json');ver=read_json(runs[w]/PLAN_VERSION)
        except (OSError,ValueError,GateError):problems.append(f'{w}: the run plan or the plan version of the run is unreadable');continue
        if ver!=version:problems.append(f'{w}: the run binds another plan version')
        try:want=(window_run_plan(version,w,case,pol,doc) if w[0]=='1' else
                  extension_run_plan(version,'1'+w[1:],list((a.get('extension_of') or {}).get('units') or []),case,pol,doc))
        except GateError as exc:problems.append(f'{w}: {str(exc)[:200]}');continue
        if _strip(sub)!=_strip(want):problems.append(f'{w}: the run plan differs from the run plan of the plan version')
    for w,a in sorted(finals.items(),key=lambda kv:_wkey(kv[0])):
        if w[0]!='2' or a['status']!='PASS':continue
        eo=a.get('extension_of') or {};base=finals.get('1'+w[1:])
        if base is None or eo.get('run_id')!=base['run_id'] or eo.get('record_sha256')!=base['record_sha256']:
            problems.append(f'{w}: it extends another run than the final position of window 1{w[1:]}')
        win=next((x for x in version['windows'] if x['id']=='1'+w[1:]),{'blocks':{}});obs=run_observations(runs[w])
        for u in list(eo.get('units') or []):
            seen=sorted({o['block'] for o in obs if o.get('unit')==u and not o.get('warmup') and o.get('scope')=='caller' and o.get('block') is not None})
            problems+=[f'{w} {u}: {p}' for p in check_extension(look1[0] if look1 else {},{'units':[u],'blocks':seen},(base or {}).get('identity'),a.get('identity'),
                                                               {u:(win.get('blocks') or {}).get(u,[])})]
    state=chain_state(ch);evidence,pooled=_evidence(version,pol,finals,runs,ch)
    return {'history':ch,'problems':list(dict.fromkeys(problems)),'state':state,'pooled':pooled,'evidence':evidence,'plan_id':plan_id}

def run_observations(run_dir):
    """EX-19 (H15.2 for local runs): the observations of a recorded window attempt: observations.jsonl of a synthetic run;
    for a local run (plan.json dataset kind local) the per-block rows of its merged document
    (bench_local_decision.run_observations; none when the document is missing or not closed: the recorded checks refuse it)."""
    import bench
    try:plan=read_json(Path(run_dir)/'plan.json')
    except (OSError,ValueError,GateError):plan={}
    if ((plan if isinstance(plan,dict) else {}).get('dataset') or {}).get('kind')=='local':
        import bench_local_decision as bl
        try:return bl.run_observations(run_dir,plan)
        except (GateError,OSError,ValueError):return []
    return bench.read_jsonl(Path(run_dir)/'observations.jsonl')

def _evidence(version,policy,finals,runs,ch):
    import bench
    units_of={w['id']:list(w['units']) for w in version['windows']};exhausted=set(ch.get('exhausted') or [])
    ext_units=lambda w,a:list(((a or {}).get('extension_of') or {}).get('units') or [])
    first_ext={}
    for a in sorted(ch.get('attempts') or [],key=lambda a:a.get('seq',0)):
        if a['window'][0]=='2':first_ext.setdefault(a['window'],a)
    window_pressure=sorted({u for w in exhausted if w[0]=='1' for u in units_of.get(w,[])})
    window_invalid=sorted({u for w,a in finals.items() if a['status']=='FAIL' for u in (units_of.get(w,[]) if w[0]=='1' else ext_units(w,a))})
    looks={};ext_exhausted=set()
    for u in policy['units']:
        homes=[w for w in units_of if u in units_of[w]];exts=['2'+w[1:] for w in homes]
        ok=[x for x in exts if x in finals and finals[x]['status']=='PASS' and u in ext_units(x,finals[x])]
        if homes and len(ok)==len(exts):looks[u]=2
        elif any(x in exhausted and u in ext_units(x,first_ext.get(x)) for x in exts):ext_exhausted.add(u)
    observations=[];sessions=[];pooled={}
    for w,a in sorted(finals.items(),key=lambda kv:_wkey(kv[0])):
        if a['status']!='PASS':continue
        obs=run_observations(runs[w])
        if w[0]=='1':keep=lambda o,w=w:o.get('unit') in units_of[w] or (not o.get('unit') and bool(DIAGNOSTIC.match(str(o.get('point')))))
        else:keep=lambda o,w=w,a=a:o.get('unit') in ext_units(w,a) and looks.get(o.get('unit'))==2
        observations+=[o for o in obs if keep(o)]
        try:sessions+=[dict(s,trials=[t for t in s['trials'] if not str(t.get('point','')).startswith('control-')]) for s in read_json(runs[w]/'plan.json').get('sessions') or []]
        except (OSError,ValueError,GateError):pass
        for u in {o.get('unit') for o in obs if keep(o) and o.get('unit')}:pooled.setdefault(u,[]).append((w,a.get('identity')))
    plan={'sessions':sessions,'blocked_rows':list(bench.without_guardrail_rows(version).get('blocked_rows') or []),'rows':list(version.get('rows') or []),'envelope':version.get('envelope'),
          'project_dir':version.get('project_dir'),'deployment_starts_worker_per_request':bool(version.get('deployment_starts_worker_per_request'))}
    if version.get('matrix'):plan['matrix']=version['matrix']
    ev={'observations':observations,'plan':plan,'looks':looks,'window_pressure':window_pressure,'extension_exhausted':sorted(ext_exhausted),'window_invalid':window_invalid}
    pool=[{'unit':u,'windows':[w for w,_ in v],'identities':[i for _,i in v]} for u,v in sorted(pooled.items()) if len(v)>1]
    return ev,pool
