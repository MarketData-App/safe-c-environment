"""EX-19 (Phase 3 Task 31, framework part; spec 12, Amendment H10, H15.2): local decision runs on a private dataset
(`--dataset local:PATH`, closed aggregates only) and their window attempts.

A local decision run uses one redacted container per timing session (a job). Each job runs the session's trials on the
local dataset and computes its own reference and the project summary inside the container, with the adapter of its one
reference selector (the selector of every trial of the job, else `all`: the single-selector local run). The only file
that leaves a job is its closed aggregate (schemas/bench-local-aggregate.json), which the host accepts with the Phase 1
gate (bench_privacy.accept_aggregate). The host then requires every timing row of the aggregate to be a planned row of
its job (row_problems: the planned key, trial count, blocks and panel cells, so no free value can enter through a row
key), checks the cgroup identity of each job (local_accounting) and merges the aggregates and its own records into the
closed `bench-local-merged` document (merge_aggregates), the only input of a local decision. The per-block values of the
merged document give the observations of the decision code (observations_from_merged), so a local run decides with the
same functions as a synthetic run; no row of the dataset and no per-trial output digest leaves a container.

Window attempts (H15.2 for local runs; ledger EX18b-A08): `bench run --plan PATH --window ID` and `bench run --extend
RUN_ID` on a local dataset run their attempts here; the run record and the merged document carry the window, the attempt,
`extends` and the attempt outcome from the control pairs of the merged document; bench_windows reads the observations of
a local window attempt through run_observations.

Memory and capacity trials of a local decision plan are not run: they are listed in the merged `not_run` and decide
nothing (a missing memory peak is missing evidence, never false). The project is the run plan's explicit project; this
module never selects a project by layout (amendment E rule S).

T5-R1 (EX-19 approver findings). T5-A01 (spec 12, Round-4 L4: "Digest fields name whole-run outputs only (the complete
result and the complete reference of the run); a digest of one row or of a subset of rows is not a field"): a job whose
rows are fewer than the run's rows (run_rows: the largest job rows of the plan), or every job of a run of one row, is a
partial job. It still computes its reference over its own rows inside its container, so the agreement check of every
trial is unchanged, but its aggregate holds `partial: true`, rows 0, no summary, the zero digests and no reference count
block; only a whole-run job exports the digests, the summary and the counts. The host refuses and deletes an aggregate
that breaks this (slice_problems; problem `partial-slice`). T5-A02: every decision job applies the synthetic run rule set
to its own trials inside the container and reports the count of trials that break each rule (`rules`, the closed rule
names of the coordinator's LOCAL_RULES); a count above zero makes the job and the run INVALID_EXPERIMENT (problem
`rules-failed`). T5-A06: each job's artifact-directory check has its own record (label local-check-<job>). T5-A07:
reference_admit_excluded is compared only between whole-run jobs of one selector."""
import datetime, json
from pathlib import Path
from evidence import GateError, atomic_json, file_hash, read_json, passed
from schema_check import validate
import bench_model as bm

MERGED='local-merged.json'
AGGREGATE_PREFIX='aggregate-'
ROW_KEY=('point','scope','mode','variant','workers','tier','route','selector','unit')
PROBLEMS=('doctor-blocked','guardrail-rejected','guardrail-blocked','before-run-failed','native-failed','job-missing','job-failed','job-invalid',
          'rows-unplanned','rows-missing','dataset-differs','case-differs','counts-differ','overhead-repeated','cgroup-identity','children-not-isolated',
          'image-changed','partial-slice','rules-failed')
HOST_PROBLEMS=('doctor-blocked','guardrail-rejected','guardrail-blocked','before-run-failed','native-failed','job-failed','image-changed','partial-slice')
BLOCKING=('doctor-blocked','guardrail-blocked')
MERGED_ROW=('job',)+ROW_KEY+('trials','eligible','wall_ns_per_unit','cpu_ns_per_unit','block_ids','block_eligible','blocks','cpu_blocks','pressure_blocks',
                             'request_records','panel_passes','panel_status','call_blocks','cells')
ZERO='0'*64                    # the digest of no output (a partial job, or a job without a summary)
COUNT_KEYS=('reference_evals','reference_admit_excluded','reference_overhead')
WHOLE_RUN_MIN_ROWS=2           # spec 12 L4: "a digest of one row ... is not a field": a run of one row exports no digest
SLICE_KINDS=('partial-flag','rows','summary','digest','counts')

# ---- the jobs of a local decision plan ----
def job_selector(trials):
    """The reference selector of one job: the one selector of all its trials, else `all` (single-selector local run)."""
    sels={t.get('selector','all') for t in trials}
    return sels.pop() if len(sels)==1 else 'all'

def job_reference_selectors(trials):
    """R48 (ruling R51): the sorted selectors of a job whose trials hold more than one (a window session: its unit trials and
    the control trials of the window), sent as the job plan's `reference_selectors`, so the job's reference covers each of
    them through the adapter's optional reference_cover hook (the coordinator refuses a trial outside the list); [] for a
    single-selector job, whose reference selector is that selector, as before."""
    sels=sorted({t.get('selector','all') for t in trials})
    return sels if len(sels)>1 else []

def job_rows(trials,sizes):
    """The rows of one job's reference and summary: the largest tier of its trials that read the run dataset (a panel
    trial reads synthetic panel rows, H10); a job of panel trials only takes the largest tier of its trials."""
    own=[sizes[t['tier']] for t in trials if 'panel' not in t]
    return max(own or [sizes[t['tier']] for t in trials] or [0])

def run_rows(jobs):
    """The rows of the run: the largest job rows of the plan (0 without a job). Plan data, never a count of the dataset."""
    return max([j['rows'] for j in jobs] or [0])

def is_partial(rows,run):
    """T5-A01 (spec 12 L4): a job is partial when its rows are fewer than the run's rows, and every job of a run of fewer
    than WHOLE_RUN_MIN_ROWS rows is partial (a whole-run digest of one row is a digest of one row)."""
    return rows<run or run<WHOLE_RUN_MIN_ROWS

def local_jobs(plan,policy):
    """One job per timing session of the plan, in plan order: {'name', 'kind': 'timing', 'trials', 'selector', 'rows',
    'partial'} (partial: is_partial of the job's rows against the run's rows; plan data)."""
    jobs=[{'name':s['session'],'kind':'timing','trials':list(s['trials']),'selector':job_selector(s['trials']),'rows':job_rows(s['trials'],policy['sizes'])}
          for s in plan.get('sessions') or []]
    run=run_rows(jobs)
    for j in jobs:j['partial']=is_partial(j['rows'],run)
    return jobs

def not_run(plan):
    """The trials of a local decision plan that no local job runs (memory and capacity trials), as {kind, trials}."""
    out=[{'kind':'memory','trials':len(plan.get('memory') or [])},{'kind':'capacity','trials':len(plan.get('capacity') or [])}]
    return [x for x in out if x['trials']]

def overhead_selectors(plan):
    """G2.3 (Task 6 hand-off): the planned selectors other than `all`; the first whole-run job (T5-A01: a partial job
    exports no count block) measures the overhead of those that report one, on synthetic rows of the case seed (never on
    local rows); the other jobs measure none."""
    return sorted({t.get('selector','all') for s in plan.get('sessions') or [] for t in s['trials']}-{'all'})

def overhead_job(jobs):
    """The index of the job that measures the overhead: the first whole-run job, or None."""
    return next((n for n,j in enumerate(jobs) if not j.get('partial')),None)

def slice_problems(doc,job):
    """T5-A01 (spec 12 L4): the problem kinds (SLICE_KINDS, never a value) of one job's aggregate against the job's
    plan-derived `partial`. A partial job's aggregate holds partial true, rows 0, no summary, the zero digests and no
    reference count block; a whole-run job's aggregate holds partial false. [] when the aggregate keeps the rule."""
    d=doc if isinstance(doc,dict) else {};out=[]
    partial=bool(job.get('partial'));dig=d.get('output_digests') if isinstance(d.get('output_digests'),dict) else {}
    if d.get('partial') is not partial:out.append('partial-flag')
    if partial:
        if d.get('rows')!=0:out.append('rows')
        if d.get('summary') is not None:out.append('summary')
        if dig.get('result_sha256')!=ZERO or dig.get('reference_sha256')!=ZERO:out.append('digest')
        if any(k in d for k in COUNT_KEYS):out.append('counts')
    return out

def rule_problems(doc):
    """T5-A02: [(rule, trials)] of the rules that a decision job's aggregate reports broken (`rules`: the count of trials
    that break each rule of the synthetic run rule set inside the container), or [('rules-missing', 0)] for an aggregate
    without the block. [] when every count is zero."""
    rules=(doc or {}).get('rules')
    if not isinstance(rules,dict) or not rules:return [('rules-missing',0)]
    return [(k,v) for k,v in sorted(rules.items()) if not (type(v) is int and v==0)]

# ---- the host checks of one aggregate ----
def _key(x):
    return (x.get('point'),x.get('scope'),x.get('mode'),x.get('variant'),x.get('workers'),x.get('tier'),x.get('route'),x.get('selector','all'),x.get('unit'))

def planned_rows(trials):
    """{row key: {'trials', 'blocks', 'cells', 'passes'}} of the non-warmup caller and kernel trials of one job."""
    out={}
    for t in trials:
        if t.get('warmup') or t.get('scope') not in ('caller','kernel'):continue
        r=out.setdefault(_key(t),{'trials':0,'blocks':[],'cells':None,'passes':None})
        r['trials']+=1;r['blocks'].append(t.get('block'))
        if 'panel' in t:r['cells']=sorted(t.get('panel_cells') or []);r['passes']=t.get('panel_passes')
    return out

def row_problems(doc,trials):
    """[(code, text)] for the timing rows of an aggregate against the planned rows of its job: an unplanned row key, a row
    whose trial count, block ids or panel cells and L differ from the plan (rows-unplanned), and a planned row without
    a timing row (rows-missing). The host check that keeps every string of a timing row a planned value."""
    want=planned_rows(trials);seen=set();out=[]
    for r in (doc or {}).get('timings') or []:
        k=_key(r);p=want.get(k)
        if p is None or k in seen:out.append(('rows-unplanned',f'{r.get("point")} {r.get("variant")}: not a planned row of the job'));continue
        seen.add(k)
        if r.get('trials')!=p['trials']:out.append(('rows-unplanned',f'{r.get("point")} {r.get("variant")}: {r.get("trials")} trials, {p["trials"]} planned'))
        if 'block_ids' in r and sorted(r['block_ids'])!=sorted(b for b in p['blocks'] if b is not None):
            out.append(('rows-unplanned',f'{r.get("point")} {r.get("variant")}: the blocks differ from the plan'))
        if p['cells'] is not None and (sorted(c.get('cell') for c in r.get('cells') or [])!=p['cells'] or r.get('panel_passes')!=p['passes']):
            out.append(('rows-unplanned',f'{r.get("point")} {r.get("variant")}: the panel cells or passes differ from the plan'))
    out+=[('rows-missing',f'{k[0]} {k[3]}: a planned row without a timing row') for k in want if k not in seen]
    return out

def require_local_fields(doc):
    """The job keys that code requires of every aggregate of a local decision job (the schema keeps them optional, so a
    Phase 1 document stays valid): the cgroup inode. [] when present."""
    return [] if type((doc or {}).get('cgroup_inode')) is int else ['aggregate lacks cgroup_inode']

def local_accounting(name,session_record,doc,trials=0):
    """(reasons, row) of the B15 cgroup identity of one local job (P3R5-01): the launcher's cgroup inode at create against
    the inode that the coordinator read (the aggregate's cgroup_inode). A redacted job reports no coordinator window, so
    window_usec is null and only the identity is checked; trial_sum_usec is the aggregate's CPU counter."""
    import bench_accounting
    launcher=((session_record or {}).get('effective') or {}).get('cgroup_inode');job=(doc or {}).get('cgroup_inode')
    reasons=bench_accounting.check_cgroup_identity(name,launcher,job)
    cpu=((doc or {}).get('counters') or {}).get('cpu_usage_usec')
    return reasons,{'session':name,'host_total_usec':bench_accounting.host_total_usec(session_record),'window_usec':None,
                    'trial_sum_usec':cpu if type(cpu) is int and cpu>=0 else 0,'trials':int(trials),'launcher_cgroup_inode':launcher,'job_cgroup_inode':job,
                    'status':'FAIL' if reasons else 'PASS'}

# ---- the merged document ----
def _merged_row(job,r):
    out={'job':job,**{k:r.get(k) for k in MERGED_ROW[1:]}}
    out['selector']=r.get('selector','all');out['panel_status']=bool(r.get('panel_status'))
    return out

def _admit_block(full):
    """T5-A07: (block, problems) of reference_admit_excluded over the whole-run documents [(selector, doc)]: the blocks of
    one selector must be equal (counts-differ otherwise); the blocks of different selectors may differ (each selector's
    adapter computes its own reference). The run's block is the block of selector `all` when an `all` job holds one,
    else of the first selector in sorted order that holds one (the synthetic run's reference is the `all` reference)."""
    by={}
    for sel,d in full:
        if d.get('reference_admit_excluded') is not None:by.setdefault(sel,[]).append(d['reference_admit_excluded'])
    problems=['counts-differ' for blocks in by.values() if any(b!=blocks[0] for b in blocks)]
    if not by:return None,problems
    sel='all' if 'all' in by else sorted(by)[0]
    return dict(by[sel][0]),problems

def merge_aggregates(docs,jobs,host):
    """The closed bench-local-merged document of one local decision run. docs: {job name: accepted aggregate or None};
    jobs: local_jobs of the run plan; host: {'run_id', 'case', 'dataset_sha256', 'problems' (host codes), 'accounting',
    'not_run'} and optional 'window'. Problems: a planned job without a document (job-missing), a document that is not
    VALID (job-invalid) or of another run, case or dataset, a timing row outside the plan (row_problems), a missing cgroup
    inode or a FAIL accounting row (cgroup-identity), a child that did not start isolated, a partial job's document with a
    digest, a summary, a row count or a count block, or a document whose partial flag differs from the plan (T5-A01:
    partial-slice), a rule of the synthetic run rule set broken inside a job or a document without the rule block (T5-A02:
    rules-failed), unequal reference counts of the same key over the whole-run jobs or unequal admission blocks of one
    selector (counts-differ), and more than one overhead measurement. A partial job contributes no rows, digests or
    counts to the merged document (its jobs[] entry holds null). rows: the rows of the whole-run documents (equal, else
    counts-differ; 0 without one). reference_evals is the union over the whole-run jobs (equal values per key);
    reference_admit_excluded from _admit_block; reference_overhead from the one job that measured it. Status: BLOCKED for
    a doctor or guardrail block, INVALID_EXPERIMENT for any other problem, else VALID."""
    problems=[p for p in host.get('problems') or [] if p in PROBLEMS];present={n:d for n,d in docs.items() if isinstance(d,dict)}
    run=run_rows(jobs);job_rows=[];timings=[];full=[]
    if not jobs:problems.append('job-missing')          # a decision run without a timing session measures nothing
    for j in jobs:
        d=present.get(j['name']);partial=bool(j.get('partial',is_partial(j['rows'],run)))
        if d is None:
            problems.append('job-missing')
            job_rows.append({'name':j['name'],'kind':'timing','status':'MISSING','selector':j['selector'],'partial':partial,'rows':None,'reference_sha256':None,
                             'result_sha256':None,'cgroup_inode':None,'isolated':None})
            continue
        if d.get('status')!='VALID' or d.get('run_id')!=host['run_id']:problems.append('job-invalid')
        if d.get('case')!=host['case']:problems.append('case-differs')
        if d.get('dataset_sha256')!=host['dataset_sha256']:problems.append('dataset-differs')
        if require_local_fields(d):problems.append('cgroup-identity')
        if d.get('isolated') is not True:problems.append('children-not-isolated')
        if d.get('selector','all')!=j['selector']:problems.append('rows-unplanned')
        if slice_problems(d,dict(j,partial=partial)):problems.append('partial-slice')
        if rule_problems(d):problems.append('rules-failed')
        problems+=[c for c,_ in row_problems(d,j['trials'])]
        dig=d.get('output_digests') or {}
        if not partial:full.append((j['selector'],d))
        job_rows.append({'name':j['name'],'kind':'timing','status':d.get('status'),'selector':j['selector'],'partial':partial,
                         'rows':None if partial else d.get('rows'),'reference_sha256':None if partial else dig.get('reference_sha256'),
                         'result_sha256':None if partial else dig.get('result_sha256'),
                         'cgroup_inode':d.get('cgroup_inode') if type(d.get('cgroup_inode')) is int else None,'isolated':d.get('isolated') if isinstance(d.get('isolated'),bool) else None})
        timings+=[_merged_row(j['name'],r) for r in d.get('timings') or []]
    if any(a.get('status')!='PASS' for a in host.get('accounting') or []):problems.append('cgroup-identity')
    counted={d.get('rows') for _,d in full if d.get('status')=='VALID'}      # an invalid job's document keeps rows 0 (no summary)
    if len(counted)>1:problems.append('counts-differ')
    rows=sorted(counted)[0] if len(counted)==1 and type(sorted(counted)[0]) is int else 0
    evals={}
    for _,d in full:
        for k,v in (d.get('reference_evals') or {}).items():
            if k in evals and evals[k]!=v:problems.append('counts-differ')
            evals.setdefault(k,v)
    admit,more=_admit_block(full);problems+=more
    over=[d['reference_overhead'] for _,d in full if d.get('reference_overhead') is not None]
    if len(over)>1:problems.append('overhead-repeated')
    problems=sorted(set(problems),key=PROBLEMS.index)
    status='BLOCKED' if any(p in BLOCKING for p in problems) else 'INVALID_EXPERIMENT' if problems else 'VALID'
    out={'schema_version':1,'run_id':host['run_id'],'case':host['case'],'dataset_sha256':host['dataset_sha256'],'rows':rows,'status':status,'problems':problems,
         'jobs':job_rows,'timings':timings,'not_run':list(host.get('not_run') or []),'accounting':list(host.get('accounting') or [])}
    if evals:out['reference_evals']=dict(sorted(evals.items()))
    if admit is not None:out['reference_admit_excluded']=admit
    if len(over)==1:out['reference_overhead']=dict(over[0])
    if host.get('window') is not None:out['window']=dict(host['window'])
    return out

# ---- the observations of the decision code ----
def _at(row,key,i):
    v=row.get(key);return v[i] if isinstance(v,list) and i<len(v) else None

def plan_trial_ids(plan):
    """{(row key, block): trial id} of the non-warmup caller and kernel trials of a run plan."""
    return {(_key(t),t.get('block')):t['trial_id'] for s in (plan or {}).get('sessions') or [] for t in s.get('trials') or []
            if not t.get('warmup') and t.get('scope') in ('caller','kernel')}

def observations_from_merged(merged,plan=None,routes=None):
    """The observations of the decision code from the per-block values of a merged document: per timing row and block one
    timed, non-warmup row with the plan's trial id (plan_trial_ids; `local-r<row>-b<block>` without one), the block's
    eligibility, records (work_units), wall and CPU (per-unit value x records, loops 1, so bench.per_trial gives back the
    per-unit value), cpu_pressure_total, and for a panel row the per-cell medians (panel_stats), L and the trial wall. A
    row without per-block values gives none. Timings only: no result digest and no dataset value."""
    ids=plan_trial_ids(plan);out=[]
    for i,r in enumerate((merged or {}).get('timings') or []):
        blocks=r.get('block_ids')
        if not isinstance(blocks,list):continue
        key=_key(r)
        for j,b in enumerate(blocks):
            wall=_at(r,'blocks',j);cpu=_at(r,'cpu_blocks',j);units=_at(r,'request_records',j)
            o={'trial_id':ids.get((key,b),f'local-r{i:04d}-b{b:02d}'),'block':b,'order':None,'point':r['point'],'scope':r['scope'],'mode':r['mode'],
               'variant':r['variant'],'workers':r['workers'],'tier':r['tier'],'phase':'caller' if r['scope']=='caller' else 'work','warmup':False,
               'eligible':_at(r,'block_eligible',j) is True,'loops':1,'work_units':units,
               'wall_ns':wall*units if wall is not None and units else None,'cpu_usage_usec':cpu*units/1000.0 if cpu is not None and units else None,
               'cpu_pressure_total':_at(r,'pressure_blocks',j)}
            if r.get('route') is not None or str(r['variant']).startswith('c-'):o.update(route=r.get('route'),route_label=(routes or {}).get(r.get('route')))
            if r.get('selector','all')!='all':o['selector']=r['selector']
            if r.get('unit'):o['unit']=r['unit']
            if isinstance(r.get('cells'),list) and r['cells']:
                o.update(panel_stats={c['cell']:{'median_ns':_at(c,'blocks',j)} for c in r['cells']},panel_walls={c['cell']:[] for c in r['cells']},
                         panel_passes=r.get('panel_passes'))
                if _at(r,'call_blocks',j) is not None:o['panel_call_ns']=_at(r,'call_blocks',j)
            if r.get('panel_status'):o['detail']='panel-status'
            out.append(o)
    return out

def load_merged(root,run_dir):
    """The merged document of a local run (capped read, closed schema); GateError otherwise."""
    p=Path(run_dir)/MERGED
    if p.is_symlink() or not p.is_file():raise GateError('missing: '+MERGED)
    doc=read_json(p);validate(root,'bench-local-merged',doc);return doc

def run_observations(run_dir,plan=None,root=None):
    """The observations of the decision code of a recorded local run (observations_from_merged of its merged document,
    with the trial ids of its plan.json)."""
    root=Path(root) if root is not None else Path(__file__).resolve().parents[1]
    if plan is None:plan=read_json(Path(run_dir)/'plan.json')
    return observations_from_merged(load_merged(root,run_dir),plan,bm.load_policy(root).get('routes'))

def _aggregates(root,run_dir,jobs):
    out={}
    for j in jobs:
        p=Path(run_dir)/f"{AGGREGATE_PREFIX}{j['name']}.json"
        if p.is_symlink() or not p.is_file():out[j['name']]=None;continue
        doc=read_json(p);validate(root,'bench-local-aggregate',doc);out[j['name']]=doc
    return out

def remerge_problems(root,run_dir,plan,merged,policy):
    """decide (T16-APP-01 for a local run): the merge of the recorded aggregates of the run's jobs with the recorded host
    inputs of the merged document must give that document (the window object aside). [] when it does."""
    try:
        jobs=local_jobs(plan,policy);docs=_aggregates(root,run_dir,jobs)
        host={'run_id':merged['run_id'],'case':merged['case'],'dataset_sha256':(plan.get('dataset') or {}).get('sha256'),
              'problems':[p for p in merged['problems'] if p in HOST_PROBLEMS],'accounting':merged['accounting'],'not_run':not_run(plan)}
        again=merge_aggregates(docs,jobs,host)
    except (GateError,OSError,ValueError,KeyError,TypeError) as exc:return [f'the local aggregates of the run are not mergeable ({type(exc).__name__})']
    mine={k:v for k,v in merged.items() if k!='window'}
    return [] if again==mine else [f'{MERGED} differs from the merge of its recorded aggregates']

def recorded_status(root,run_dir,run,plan,policy):
    """bench_evidence.recorded_status for a local run: the status comes from the digest-bound merged document, which
    remerge_problems re-derives from the recorded aggregates; a FAIL accounting row of run.json adds a reason; a
    recorded status never upgrades. Returns (status, reasons), the derived reasons first."""
    recorded=run.get('status');reasons=[str(r)[:300] for r in run.get('reasons') or [] if isinstance(r,str)][:200] if isinstance(run.get('reasons'),list) else []
    try:merged=load_merged(root,run_dir)
    except (GateError,OSError,ValueError) as exc:return 'INVALID_EXPERIMENT',[f'{MERGED} is unreadable or not a closed merged document ({type(exc).__name__})']+reasons
    derived=remerge_problems(root,run_dir,plan,merged,policy)
    if merged['status']=='BLOCKED' and recorded=='BLOCKED' and not derived:return 'BLOCKED',reasons
    if merged['status']!='VALID':derived+=[f'local merge: {p}' for p in merged['problems']] or [f"local merge status {merged['status']}"]
    derived+=[f"B15 accounting row {str(a.get('session','?'))[:80]}: {str(a.get('status'))[:20]}" if isinstance(a,dict) else 'B15 accounting row malformed'
              for a in (run.get('accounting') if isinstance(run.get('accounting'),list) else []) if not isinstance(a,dict) or a.get('status')!='PASS']
    if recorded not in ('VALID','INVALID_EXPERIMENT','BLOCKED'):derived.append(f'recorded status {str(recorded)[:40]!r} unknown')
    if not derived and recorded in ('VALID','BLOCKED'):return recorded,reasons
    return 'INVALID_EXPERIMENT',list(dict.fromkeys([str(x)[:300] for x in derived]+reasons))[:200]

def outcome_problems(root,run_dir,run,plan,policy):
    """A window attempt of a local run: the attempt outcome that its merged document gives (bench_windows
    run_attempt_outcome on observations_from_merged) must equal the recorded one of run.json and of the merged document."""
    import bench_windows as bwin
    if run.get('window') is None:return []
    try:merged=load_merged(root,run_dir)
    except (GateError,OSError,ValueError) as exc:return [f'{MERGED} is unreadable ({type(exc).__name__})']
    status,_=recorded_status(root,run_dir,run,plan,policy)
    want=bwin.run_attempt_outcome(status,observations_from_merged(merged,plan,policy.get('routes')),policy)
    got=[run.get('attempt_outcome'),(merged.get('window') or {}).get('outcome')]
    return [] if all(g==want for g in got) else ['the recorded attempt outcome differs from the outcome of the merged document']

# ---- the run ----
def local_run_record(root,run_dir,plan,case,merged,status,reasons,probe,held,admission,accounting,evidence,protocol_sha256,
                     native_record=None,project_images=(),window=None,replay_of=None):
    """The bench-run record of a local decision run: every required field as the Phase 1 local record, mode decision, the
    merged document and the job aggregates as evidence, the accounting rows, the reference count blocks of the merged
    document, the native build, the named datasets, the project image, the window fields of an attempt and, last,
    evidence_digests, bench_profile_sha256 and run_record_sha256. Validated against bench-run by the caller."""
    import bench, bench_evidence
    from policy import source_identity
    root=Path(root);run_dir=Path(run_dir)
    run={'schema_version':1,'run_id':run_dir.name,'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'case':case['case_id'],
         'case_version':case['version'],'mode':plan['mode'],'dataset':dict({k:plan['dataset'].get(k) for k in ('kind','size','seed','sha256')},rows=merged['rows'] or None),
         'plan':{'plan_id':plan['plan_id'],'plan_version':plan['plan_version'],'estimate_seconds':plan.get('estimate_seconds'),'seed':plan.get('seed'),
                 'project_dir':plan.get('project_dir'),'project_identity':plan.get('project_identity')},
         'envelope':probe.get('envelope'),'image_id':bench.BenchSession.image(root),'policy_sha256':file_hash(root/'safety/performance-policy.json'),
         'protocol_sha256':protocol_sha256,'fixtures_sha256':file_hash(root/'safety/performance-fixtures.json'),'source_identity':source_identity(root)[0],'runtime':None,
         'admission':{'lock_held_ns':sum(held),'active_at_handshake':list(admission)},
         'evidence':{'merged':MERGED,'aggregates':sorted(p.name for p in run_dir.glob(AGGREGATE_PREFIX+'*.json')),'guardrails':'guardrails.json','jobs':list(evidence)},
         'status':status,'reasons':[str(r)[:300] for r in reasons[:200]],'accounting':list(accounting)}
    for k in ('reference_evals','reference_admit_excluded','reference_overhead'):
        if k in merged:run[k]=json.loads(json.dumps(merged[k]))
    if native_record is not None:run['native']=native_record
    if plan.get('datasets'):run['datasets']=json.loads(json.dumps(plan['datasets']))
    if project_images:
        import project_image as pimg
        sel=pimg.selection(root,plan.get('project_dir'))
        run['project_image']={'image_ids':sorted(i for i,_ in project_images),'key':sorted(k for _,k in project_images)[0],'lock_sha256':sel['lock_sha256'] if sel else None}
        if len(project_images)!=1 or sel is None or sel['key']!=run['project_image']['key']:
            run['reasons']=(['project bench image changed during the run']+run['reasons'])[:200]
            if run['status']=='VALID':run['status']='INVALID_EXPERIMENT'
    if replay_of is not None:run['replay_of']=replay_of
    run['evidence_digests']=bench_evidence.digest_files(run_dir);run['bench_profile_sha256']=bench_evidence.bench_profile_sha256(root)
    if window is not None:
        import bench_windows as bwin
        run.update(window=window['window'],attempt=window['attempt'],window_plan_id=window['window_plan_id'],extends=window['extends'],
                   attempt_outcome=merged['window']['outcome'],envelope_identity=bwin.envelope_identity(run),extension_of=window['extension_of'])
    run[bench_evidence.RECORD_KEY]=bench_evidence.run_record_sha256(run)
    return run

def run_local_decision(root,args,plan,case,policy,path,envelope=None,window=None):
    """One local decision run (or one window attempt) on the fixture `path` (the plan no longer holds it, F-11): the
    privacy path pattern, the doctor probe and the B12 guardrails, the before-run checks (synthetic containers), the native
    build of a run with C rows (a synthetic build container), then one redacted container per timing session (job) with
    the session's trials, the job's reference selector and rows and, for the first job, the overhead selectors; the
    artifact-directory check and accept_aggregate exactly as Phase 1 (aggregate-<job>.json); local_accounting per job;
    merge_aggregates into local-merged.json; for a window attempt the attempt outcome of its control pairs; run.json
    through local_run_record. Every error whose text names the fixture is withheld. Exit 0 VALID, 1 INVALID_EXPERIMENT,
    2 BLOCKED (also a BLOCKED window attempt: run the window again)."""
    import bench, bench_native, bench_privacy as bp, bench_windows as bwin
    root=Path(root);project=plan.get('project_dir')
    try:
        protocol_sha256=bm.protocol_digest(root,project);proto=bm.load_protocol(root,project) if project is not None else None
        summary_schema=bm.protocol_data(root,project,'aggregate_schema',proto=proto) if project is not None else None
        names=tuple((proto or {}).get('local_exceptions',[]));kernel=bench.native_run_declaration(root,project,plan)
        bp.install_fixture_pattern(root,'local:'+path)      # Task 27 (S-06): before the first container
        run_dir=bench.new_run_dir(root,'run-local');atomic_json(run_dir/'plan.json',plan);args.created_run_id=run_dir.name
        if window is not None:
            atomic_json(run_dir/bwin.PLAN_VERSION,window['version'])
            if window['look1'] is not None:(run_dir/bwin.LOOK1_RECORD).write_bytes(window['look1'])
        held=[];admission=[];evidence=[];host=[];reasons=[]
        probe=bench.doctor_probe(root,run_dir);held.append(probe.pop('lock_held_ns',0) or 0);evidence+=list(probe.get('evidence_paths') or [])
        if probe['status']!='PASS':reasons.append('bench doctor: '+probe['status'])
        more,state=bench.guardrail_gate(root,run_dir,plan,policy,envelope if envelope is not None else plan.get('envelope'),probe);reasons+=more
        if state=='GATED':host.append('guardrail-rejected')
        elif state!='PASS':host.append('doctor-blocked' if probe['status']!='PASS' else 'guardrail-blocked')
        native=native_record=None
        if state=='PASS':
            pre,ev=bench.before_run_checks(root,run_dir,project);evidence+=ev
            if pre:reasons+=pre;host.append('before-run-failed');state='GATED'
        if state=='PASS' and kernel is not None:
            native,native_record,more,ev=bench.run_native_build(root,run_dir,project,kernel);evidence+=ev
            if more:reasons+=more;host.append('native-failed');state='GATED'
        jobs=local_jobs(plan,policy);docs={};accounting=[];images=set();deadline=policy['job_deadlines']['session']
        base={'schema_version':1,'job':'local','run_id':run_dir.name,'case':case['case_id'],'case_manifest':bm.container_case_path(case['case_id'],project,root),
              'project_dir':project,'project_identity':plan.get('project_identity'),'dataset':plan['dataset'],'sizes':policy['sizes'],'pyperf':plan['pyperf'],
              'local':True,'decision':True,'output':'bench/out','deadline_seconds':deadline,'local_exceptions':list(names),
              **({'request_limit':plan['request_limit']} if 'request_limit' in plan else {}),**({'datasets':plan['datasets']} if plan.get('datasets') else {})}
        restore=()
        if native is not None:
            base.update(native=bench_native.native_plan(native),native_kernel=dict(kernel['kernel']));restore=tuple(bench_native.native_restore(native))
        over=overhead_selectors(plan);first=overhead_job(jobs)
        for n,j in enumerate(jobs if state=='PASS' else []):
            s=bench.BenchSession(root,run_dir,fixture=path,redacted=True);doc=None;reason='not collected';code=0
            try:
                r=s.job(dict(base,trials=j['trials'],rows=j['rows'],partial=j['partial'],reference_selector=j['selector'],
                             **({'overhead_selectors':over} if n==first and over else {}),
                             **({'reference_selectors':cover} if (cover:=job_reference_selectors(j['trials'])) else {})),'local-'+j['name'],deadline,restore=restore)
                # T5-A06: each job's artifact-directory check keeps its own record (the label names the job)
                check=s.runner.run(['python3','/src/container/bench-coordinator.py','--local-check','bench/out'],timeout=30,label='local-check-'+j['name'])
                evidence+=[x for x in (r.get('evidence_path'),check.get('evidence_path')) if isinstance(x,str)]     # redacted launcher records (byte counts only)
                code=r['exit_code'] if not passed(r) and isinstance(r.get('exit_code'),int) and r.get('failure') is None else 0 if passed(r) else 1
                if passed(check):
                    target=run_dir/f"{AGGREGATE_PREFIX}{j['name']}.json"
                    doc,reason=bp.accept_aggregate(root,s.fetch('bench/out/aggregate.json',target),summary_schema=summary_schema,exceptions=names)
                    if doc is not None and not passed(r) and doc['status']=='VALID':target.unlink(missing_ok=True);doc,reason=None,'local job failed with a VALID aggregate'
                    kinds=slice_problems(doc,j) if doc is not None else []
                    if kinds:                    # T5-A01: a partial job's digest, summary, rows or counts never stay on disk
                        bp._remove(target);doc,reason=None,f"aggregate rejected (partial-slice: {', '.join(kinds)}); kept as a count only"
                        host.append('partial-slice')
                else:reason='local job or artifact-directory check failed'
            finally:
                s.close();held.append(bench.lock_held(s));admission.append(bench.active_before(s))
                used=getattr(s,'project_image',None)
                if used is not None:images.add((used['image_id'],used['key']))
            st,why=bp.local_run_status(doc,reason,code)
            if st!='VALID':reasons+=[f"job {j['name']}: {w}" for w in why]
            if doc is not None:reasons+=[f"job {j['name']}: rule {k} broken by {v} trials" if k!='rules-missing' else f"job {j['name']}: aggregate lacks the rule counts"
                                         for k,v in rule_problems(doc)]          # T5-A02
            if doc is None or reason!='valid' or code!=0:host.append('job-failed')
            docs[j['name']]=doc
            more,row=local_accounting(j['name'],s.runner.session,doc,len(j['trials']));reasons+=more;accounting.append(row)
    except Exception as exc:
        if bp._withheld(exc,path):raise GateError('local run failed; the error named the fixture and is withheld') from None
        raise
    if images:                                    # EX-1: every job ran in the one project bench image of the project's lock
        import project_image as pimg
        sel=pimg.selection(root,project)
        if len(images)!=1 or sel is None or sel['key']!=sorted(k for _,k in images)[0]:host.append('image-changed')
    hostrec={'run_id':run_dir.name,'case':case['case_id'],'dataset_sha256':plan['dataset']['sha256'],'problems':host,'accounting':accounting,'not_run':not_run(plan)}
    merged=merge_aggregates(docs,jobs,hostrec);status=merged['status']
    for p in merged['problems']:
        if p not in HOST_PROBLEMS:reasons.append(f'local merge: {p}')
    if window is not None:
        out=bwin.run_attempt_outcome(status,observations_from_merged(merged,plan,policy.get('routes')),policy)
        merged['window']={'id':window['window'],'attempt':window['attempt'],'plan_id':window['window_plan_id'],'extends':window['extends'],'outcome':out}
    validate(root,'bench-local-merged',merged);atomic_json(run_dir/MERGED,merged)
    run=local_run_record(root,run_dir,plan,case,merged,status,reasons,probe,held,admission,accounting,evidence,protocol_sha256,native_record,images,window,
                         getattr(args,'replay_of',None))
    validate(root,'bench-run',run);atomic_json(run_dir/'run.json',run);status=run['status']
    extra={'window':window['window'],'attempt':window['attempt'],'attempt_outcome':run['attempt_outcome']} if window is not None else {}
    tail=(f"; window {window['window']} attempt {window['attempt']}: {run['attempt_outcome']['status']}"
          +(f" ({run['attempt_outcome']['reason']})" if run['attempt_outcome']['reason'] else '')) if window is not None else ''
    bench.emit(args,{'status':status,'run_id':run_dir.name,'jobs':len(jobs),'reasons':len(run['reasons']),**extra},
               f'bench run (owner fixture, local, aggregate) {run_dir.name}: {status} ({len(jobs)} jobs, {len(run["reasons"])} reasons){tail}')
    if window is not None and run['attempt_outcome']['status']=='BLOCKED':return 2
    return {'VALID':0,'INVALID_EXPERIMENT':1,'BLOCKED':2}[status]
