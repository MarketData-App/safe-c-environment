"""Amendment G2.6: the per-trial call deadline of declared selectors (model-neutral: selectors and reasons are opaque).

The case manifest declares `call_deadline` = {selectors, reason, factor, floor_seconds} and, since Amendment I9.1 (Task
A2), optional further entries `call_deadlines` of the same shape; `entries` joins them in declaration order and no two
entries share a selector (bench_model.check_call_deadlines). For one trial or job of a covered selector the deadline of an
entry is d = max(floor_seconds, factor x e), capped by the remaining session deadline, where e is the expected wall of
the call (`expected_seconds`); a job covered by two entries takes the larger d and that entry's reason, ties in
declaration order (controller ruling R-A8). The coordinator arms it outside the child, kills and reaps the child's
process group at expiry and records FAIL with the declared reason (never BLOCKED, never TIMEOUT, never a row status).

The deadline mechanism is model-neutral. The test-only stub selftests at the end of this module (Task 6, Amendment G2.3;
Task A5, I9.4) take every stub from the `stubs` of a project's protected protocol file (FR3: reason, check, variant): a
stub run and a stub check per declared stub, with the one test variable SAFE_C_TEST_STUB=<reason> in a selftest plan only.
They find the project by declaration (declared_stubs), never by path, and no deciding code reads the names."""
import re, time
from pathlib import Path
from evidence import GateError
from bench_plan import family, rate

REASON_RE=re.compile(r'^[a-z0-9-]{1,32}$')
# The call-deadline selftest suite (Task 1): one tiny call of the control's test selector. These are the suite's declared
# deadline inputs (job table row "bench selftest container suites": rows and calls constants).
SUITE_ROWS=1;SUITE_CALLS=1
CONTROL_CASE='bench-control-spin';CONTROL_CHECK='control-call'

def _selectors(trial):
    """A panel job carries the selector mask as `selectors`; every other trial or job one `selector` (default `all`)."""
    return list(trial['selectors']) if trial.get('selectors') else [trial.get('selector','all')]

def unapproved_shares(policy,selectors):
    """The selectors of `selectors` that budgets.share_required lists and that have no estimate_share_per_selector value."""
    budgets=policy['budgets'];shares=budgets.get('estimate_share_per_selector',{})
    return [s for s in selectors if s in budgets.get('share_required',[]) and s not in shares]

def expected_seconds(policy,trial,rows,calls,calibration):
    """Planning estimate (or calibrated rate) x the selector share (absent selector: 1.0; a mask sums its shares) x rows x calls.
    A selector that budgets.share_required lists needs an approved share (Amendment I3 R14, I10.1): GateError without it."""
    shares=policy['budgets'].get('estimate_share_per_selector',{});selectors=_selectors(trial)
    missing=unapproved_shares(policy,selectors)
    if missing:raise GateError(f'{missing[0]}: planning share not approved (budgets.share_required)')
    share=sum(shares.get(s,1.0) for s in selectors)
    return rate(policy,family(trial['variant']),calibration)*share*rows*calls

def measured_seconds(policy,trial,rows,calls,calibration):
    """T6-R7 (design I9.3: after calibration the input is the calibrated per-call wall of the row): the expected wall of
    `calls` calls of `rows` rows each of a caller-scope timing trial (a session trial, a window control trial, a memory
    trial). A calibration that holds measured walls (bench_plan.has_walls: every calibration that bench_plan.calibration_inputs
    reads from a run) gives rows x calls x the measured wall of the trial's variant, selector (a mask: the sum over its
    selectors) and call class (bench_plan.call_class of rows), never rate x share; a missing wall refuses
    (bench_windows.PlanRefusal wall-not-measured, exit 1: the smoke plan of the case measures every class, so no value
    is extrapolated from another class, selector or variant). The approved-share rule of expected_seconds applies first.
    Without a calibration (a smoke plan: the planning estimate) or with a rate table without walls: expected_seconds."""
    import bench_plan as bp
    if not bp.has_walls(calibration):return expected_seconds(policy,trial,rows,calls,calibration)
    selectors=_selectors(trial);missing=unapproved_shares(policy,selectors)
    if missing:raise GateError(f'{missing[0]}: planning share not approved (budgets.share_required)')
    cls=bp.call_class(rows);by=(calibration['walls'].get(trial['variant']) or {});total=0.0
    for s in selectors:
        wall=(by.get(s) or {}).get(cls)
        if isinstance(wall,bool) or not isinstance(wall,(int,float)) or not wall>0:
            import bench_windows
            raise bench_windows.PlanRefusal('wall-not-measured',f"variant {trial['variant']}, selector {s}, {cls} calls: the calibration run holds no measured wall above 0 "
                                            '(the smoke run of the case measures every class of its plans)',[{'variant':trial['variant'],'selector':s,'class':cls}])
        total+=wall
    return total*rows*calls

def entries(case):
    """The call-deadline entries of a case in declaration order: [call_deadline] (when present) + call_deadlines."""
    return ([case['call_deadline']] if case.get('call_deadline') else [])+list(case.get('call_deadlines') or [])

def entry_for(case,selector):
    """The entry that covers `selector`, or None (entries never overlap: bench_model.check_call_deadlines)."""
    return next((e for e in entries(case) if selector in e['selectors']),None)

def covering_deadline(case,policy,trial,rows,calls,calibration,session_remaining,plan=None,measured=False):
    """None when no entry covers a selector of the trial; else (seconds, reason). Per covering entry the deadline is
    min(max(floor, factor x e), session_remaining) with the entry's floor_seconds (only a plan of mode `selftest`, built by
    bench selftest code, P3P-07, replaces it by its test_floor_seconds; every other mode ignores the key here, and
    bench_plan refuses it: check_test_floor) and factor. The job takes the largest value and that entry's reason; ties
    follow the declaration order (controller ruling R-A8). e is expected_seconds; with `measured` (a caller-scope timing
    trial, deadline_fields; T6-R7) it is measured_seconds, the measured wall of the trial's calls after calibration."""
    selectors=_selectors(trial);best=None
    for cd in entries(case):
        if not any(s in cd['selectors'] for s in selectors):continue
        floor=float(cd['floor_seconds'])
        if isinstance(plan,dict) and plan.get('mode')=='selftest' and 'test_floor_seconds' in plan:floor=float(plan['test_floor_seconds'])
        e=(measured_seconds if measured else expected_seconds)(policy,trial,rows,calls,calibration)
        d=min(max(floor,float(cd['factor'])*e),float(session_remaining))
        if best is None or d>best[0]:best=(d,cd['reason'])
    return best

def trial_deadline(case,policy,trial,rows,calls,calibration,session_remaining,plan=None,measured=False):
    """None for a selector the case does not cover; else the seconds of covering_deadline."""
    c=covering_deadline(case,policy,trial,rows,calls,calibration,session_remaining,plan=plan,measured=measured)
    return None if c is None else c[0]

TEST_FLOOR_MAX=60.0        # a test floor only lowers the floor of a selftest plan: 0 < test_floor_seconds <= 60
STUB_VAR='SAFE_C_TEST_STUB'
TEST_ENV={STUB_VAR:REASON_RE}   # the one test-only stub variable a selftest plan may carry, with a reason value (the coordinator's allowlist)

def check_test_floor(plan):
    """P3P-07: `test_floor_seconds` and `test_env` belong to a plan of mode `selftest` only (bench selftest code builds it;
    bench run and bench plan from the command line never accept the mode). Refuses the keys in every other mode and a
    malformed value (GateError)."""
    keys=[k for k in ('test_floor_seconds','test_env') if k in plan]
    if keys and plan.get('mode')!='selftest':raise GateError(f"{', '.join(keys)}: only a selftest plan may carry them")
    if 'test_floor_seconds' in plan:
        v=plan['test_floor_seconds']
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not 0<v<=TEST_FLOOR_MAX:raise GateError('test_floor_seconds must be a number in (0, 60]')
    if 'test_env' in plan:
        env=plan['test_env']
        if not isinstance(env,dict) or not env or any(k not in TEST_ENV or not isinstance(v,str) or not TEST_ENV[k].fullmatch(v) for k,v in env.items()):raise GateError('test_env holds a variable or value outside the test-stub allowlist')
    return None

def reference_tiers(plan):
    """The tiers of every trial that the once-per-run reference of a run of `plan` covers: its session, memory and capacity
    trials. bench.run_cmd computes the reference over the largest of them (Task 22: the capacity tier too), and the call
    deadline of the reference job takes the rows of the same tier (_planned_rows; FW-CASES-STUBREF-01: a stub plan keeps
    the capacity trials of the case's smoke plan, above its tiny session tier)."""
    return ([s['tier'] for s in plan.get('sessions') or []]+[m['tier'] for m in plan.get('memory') or []]
            +[c['tier'] for c in plan.get('capacity') or []])

def _planned_rows(plan):
    """The rows of the deadline estimate of the reference job: the largest tier of reference_tiers, the large tier when the
    plan holds no trial (an upper bound)."""
    sizes=plan['sizes'];tiers=reference_tiers(plan)
    return max(sizes[t] for t in tiers) if tiers else sizes['large']

def job_inputs(job,plan,trial):
    """(rows, calls) of the deadline estimate per job type (Task 1 table; G2.6)."""
    sizes=plan['sizes']
    if job=='timing':
        if 'panel' in trial:return 1,(6 if trial.get('mode')=='cold' else 6*trial['panel_passes'])
        rows=plan['dataset'].get('rows') if plan['dataset']['kind']=='local' else None
        # EX-19: a local plan records no row count of the private dataset (F-11: rows null), so its trials take the rows of
        # their tier, the rows that the coordinator slices for each trial of a local job; a recorded count still wins
        return (rows if type(rows) is int else sizes[trial['tier']]),trial.get('loops',1)
    if job=='memory':return sizes[trial['tier']],1
    if job=='reference':return _planned_rows(plan),1
    if job=='validate':return sizes['small']+int(trial.get('oracle_edge_rows',0)),1
    if job in ('check','panel'):return sizes['large'],1
    if job=='selftest-suite':return trial['rows'],trial['calls']
    raise GateError(f'no call-deadline inputs for job {job!r}')

def deadline_fields(case,policy,job,plan,trial,calibration,session_remaining):
    """The plan keys of one trial or job: {} for an uncovered selector, else call_deadline_seconds and call_deadline_reason.
    `plan` also selects the floor (trial_deadline: a selftest plan's test_floor_seconds). T6-R7: the input of a timing trial
    outside the kernel scope is its measured wall after calibration (measured_seconds); a job (reference, panel, check,
    validate, memory, selftest-suite) and a kernel trial keep expected_seconds (job table, G2.6)."""
    rows,calls=job_inputs(job,plan,trial)
    c=covering_deadline(case,policy,trial,rows,calls,calibration,session_remaining,plan=plan,measured=job=='timing' and trial.get('scope')!='kernel')
    return {} if c is None else {'call_deadline_seconds':c[0],'call_deadline_reason':c[1]}

def job_reason(row):
    """The declared reason of a coordinator job row killed at its call deadline, or None (a malformed reason counts as `call-deadline`)."""
    if not isinstance(row,dict) or 'failure_reason' not in row:return None
    reason=row['failure_reason'];return reason if isinstance(reason,str) and REASON_RE.fullmatch(reason) else 'call-deadline'

def check_selftest_plan(plan,case,policy,envelope,digest,project=None,identity=None,root=None):
    """`bench run` accepts a plan object only from selftest code (never from the command line). It must be unedited
    (plan_id), made for this envelope, and equal to the smoke plan that case, policy, dataset and seed produce, plus only
    trials of a covered selector whose shape and call-deadline fields hang_plan gives (one tiny direct warm caller trial).
    A plan of mode `selftest` (Task 6, Task A5: a stub run) must equal exactly the plan that the stub of its test_env
    reason (a stub of the project's protocol, FR3) builds from the same case, policy, envelope, seed, project and identity."""
    import bench_plan as bp
    bad=GateError('the selftest plan is malformed or edited')
    if isinstance(plan,dict) and plan.get('mode')=='selftest':
        if plan.get('envelope')!=envelope or plan.get('plan_id')!=digest:raise bad
        check_test_floor(plan)
        reason=(plan.get('test_env') or {}).get(STUB_VAR)
        spec=next((s for p,c,s in (declared_project_stubs(root,project) if root is not None and project is not None else []) if s['reason']==reason),None)
        if spec is None:raise bad
        try:want=_stub_plan(None,case,policy,envelope,plan['seed'],project,identity,spec)
        except (KeyError,TypeError,ValueError):raise bad from None
        if {k:v for k,v in plan.items() if k!='project_dir'}!={k:v for k,v in want.items() if k!='project_dir'}:raise bad
        return plan
    if not isinstance(plan,dict) or plan.get('envelope')!=envelope or plan.get('plan_id')!=digest or plan.get('mode')!='smoke':raise bad
    try:base=bp.build_plan(case,policy,mode='smoke',dataset=plan['dataset'],seed=plan['seed'],envelope=envelope)
    except (KeyError,TypeError,ValueError):raise bad from None
    covered={s for e in entries(case) for s in e['selectors']};extra=[];stripped=dict(plan,sessions=[])
    for sess in plan.get('sessions',[]):
        keep=[t for t in sess['trials'] if t.get('selector','all')=='all'];extra+=[(sess,t) for t in sess['trials'] if t.get('selector','all')!='all']
        stripped['sessions'].append(dict(sess,trials=keep))
    if len(extra)!=1 or {k:v for k,v in stripped.items() if k!='plan_id'}!={k:v for k,v in base.items() if k!='plan_id'}:raise bad
    sess,t=extra[0]
    want={'trial_id':sess['session']+'-hang','block':None,'order':None,'scope':'caller','mode':'warm','variant':'py-reference','workers':'direct','tier':'tiny',
          'loops':1,'warmup':False,'selector':t.get('selector')}
    want.update(point=t.get('point'),**deadline_fields(case,policy,'timing',{'sizes':policy['sizes'],'dataset':plan['dataset']},want,None,sess['deadline_seconds']))
    if t.get('selector') not in covered or t!=want or sess['scope']!='caller':raise bad
    return plan

def hang_plan(root,case,policy,envelope,seed):
    """A smoke plan of the control case plus one caller trial of the covered test selector. It goes just before the first
    trial whose row already ran in the same session (the placement is unchanged; since P3-T15-REAPED-FLAKY-01 the reap is
    judged from the killed group's deadline_kills row, not from the next trial's process count)."""
    import bench_plan as bp
    from bench import plan_digest
    plan=bp.build_plan(case,policy,mode='smoke',dataset=bp.parse_dataset(root,'synthetic:small',policy),seed=seed,envelope=envelope)
    selector=entries(case)[0]['selectors'][0]
    for sess in plan['sessions']:
        if sess['scope']!='caller':continue
        seen=set()
        for i,t in enumerate(sess['trials']):
            key=(t['variant'],t['workers'],t['mode'])
            if not t['warmup'] and key in seen:
                hang={'trial_id':sess['session']+'-hang','block':None,'order':None,'point':t['point'],'scope':'caller','mode':'warm','variant':'py-reference',
                      'workers':'direct','tier':'tiny','loops':1,'warmup':False,'selector':selector}
                hang.update(deadline_fields(case,policy,'timing',{'sizes':policy['sizes'],'dataset':plan['dataset']},hang,None,sess['deadline_seconds']))
                sess['trials'].insert(i,hang);plan['plan_id']=plan_digest(plan);return plan,hang['trial_id'],t['trial_id']
            if not t['warmup']:seen.add(key)
    raise GateError('the smoke plan has no repeated caller row for the call-deadline trial')

def session_of(plan,trial_id):
    """The session id of the plan session that holds `trial_id`, or None."""
    return next((s['session'] for s in plan['sessions'] for t in s['trials'] if t['trial_id']==trial_id),None)

def reaped(run,observations,trial_id,session):
    """Every process of the killed group is gone, judged from the killed group itself (P3-T15-REAPED-FLAKY-01, ruling
    D1-R2(a)): the trial has an observation, no timing session is reported incomplete, and the coordinator's deadline_kills
    of the timing job of `session` hold exactly one row, this trial with left 0 (no group member, zombies included, in /proc
    after the reap) and foreign_orphans 0, both of type int (F1-REAP-TYPE-01: False or 0.0 never count). The process count
    of a later trial is never used: a pool row changes it without any kill (worker teardown timing).
    Known gap (F1-REAP-GAP-01, inside ruling D1-R2(a), the same trust as the production B12 rule): the rule trusts only the
    coordinator's own kill record. A process that left the group (setsid) and was orphaned to the container init before
    the subreaper window is in neither `left` nor `foreign_orphans`. A later independent check robust to pool rows (for
    example the cgroup pids_current at the end of the timing session against a no-hang baseline) would close it."""
    reasons=run.get('reasons',[]);kills=_deadline_kills(run,session)
    return (any(o.get('trial_id')==trial_id for o in observations) and not any(isinstance(r,str) and r.startswith('timing session') for r in reasons)
            and all(type(k.get('left')) is int and type(k.get('foreign_orphans')) is int for k in kills)
            and [(k.get('trial_id'),k.get('left'),k.get('foreign_orphans')) for k in kills]==[(trial_id,0,0)])

def _control_check(root,run_dir,case,policy,selector):
    """One coordinator `check` job of the framework control check with `selector`, judged by the `bench check` rule
    (bench.check_outcome). Returns (status, text, reason, evidence path)."""
    import bench
    import bench_model as bm
    from evidence import passed
    deadline=policy['job_deadlines']['control'];trial={'variant':'py-reference','selector':selector,'rows':SUITE_ROWS,'calls':SUITE_CALLS}
    job={'schema_version':1,'job':'check','run_id':run_dir.name,'project_dir':None,'check':CONTROL_CHECK,'check_args':[],'selector':selector,
         'case_manifest':bm.container_case_path(case['case_id']),'deadline_seconds':deadline,
         **deadline_fields(case,policy,'selftest-suite',{'sizes':policy['sizes']},trial,None,deadline)}
    s=bench.BenchSession(root,run_dir)
    try:r=s.job(job,f'check-{CONTROL_CHECK}-{selector}',deadline);row=bench.last_json(r['output'])
    finally:s.close()
    status='PASS' if passed(r) and row.get('status')=='PASS' else 'FAIL'
    return (*bench.check_outcome(CONTROL_CHECK,status,row),r['evidence_path'])

def selftest_suite(root,run_dir):
    """Suite `call-deadline` (G2.6 framework control): a smoke run of the spin control with one caller trial of the test
    selector `hang` must be INVALID_EXPERIMENT with failure_reasons [reason], that trial FAIL (call-deadline) and every
    process reaped; a `bench check` job with selector `hang` exits 1 with `FAIL <reason>`, and the same check with selector
    `all` passes (control). Framework code only."""
    import argparse, uuid
    import bench
    import bench_model as bm
    from evidence import read_json
    started=time.monotonic();out={'status':'FAIL','property':'case-declared call deadline: process-group kill, FAIL with the declared reason, never BLOCKED or TIMEOUT'}
    try:
        root=Path(root);policy=bm.load_policy(root);case=bm.load_case(root,CONTROL_CASE)
        selector=entries(case)[0]['selectors'][0];reason=entry_for(case,selector)['reason']
        from container_policy import choose_envelope, host_topology
        envelope=choose_envelope(*host_topology(),wanted=policy['envelope']['cpus'])
        plan,hang_id,next_id=hang_plan(root,case,policy,envelope,int(uuid.uuid4().int%2**31))
        rc,row=bench._quiet(bench.run_cmd,root,argparse.Namespace(case=CONTROL_CASE,project=None,mode='smoke',dataset='synthetic:small',calibrate=None,plan=None,
                                                                  format='json',selftest_plan=plan))
        run_id=row.get('run_id');run_dir_run=root/'artifacts/bench'/run_id if isinstance(run_id,str) and re.fullmatch(r'[0-9a-f]{32}',run_id) else None
        run=read_json(run_dir_run/'run.json') if run_dir_run and (run_dir_run/'run.json').is_file() else {}
        obs=bench.read_jsonl(run_dir_run/'observations.jsonl') if run_dir_run and (run_dir_run/'observations.jsonl').is_file() else []
        hang=next((o for o in obs if o['trial_id']==hang_id),None)
        trial_fail=hang is not None and hang.get('eligible') is False and hang['verdict'].get('failures')=={'call-deadline':1} and hang.get('failure_reason')==reason
        check=_control_check(root,run_dir,case,policy,selector);control=_control_check(root,run_dir,case,policy,'all')
        gone=reaped(run,obs,hang_id,session_of(plan,hang_id))     # from the killed group itself, not the next trial's count
        ok=(rc==1 and run.get('status')=='INVALID_EXPERIMENT' and run.get('failure_reasons')==[reason] and f'run-invalid: {reason}' in run.get('reasons',[])
            and trial_fail and gone and bench.EXIT[check[0]]==1 and check[1].endswith(f'FAIL {reason}') and control[0]=='PASS')
        out.update(status='PASS' if ok else 'BLOCKED' if rc==2 else 'FAIL',run_id=run_id,run_status=run.get('status'),failure_reasons=run.get('failure_reasons'),trial_failed=trial_fail,
                   reaped=gone,call_deadline_seconds=plan_deadline(plan,hang_id),check_exit=bench.EXIT[check[0]],check_text=check[1][-80:],
                   control_check=control[0],evidence_paths=[check[3],control[3]])
    except GateError as exc:out.update(status='BLOCKED',reason=str(exc)[:200])
    out['duration_seconds']=round(time.monotonic()-started,1);return out

def plan_deadline(plan,trial_id):
    return next((t.get('call_deadline_seconds') for s in plan['sessions'] for t in s['trials'] if t['trial_id']==trial_id),None)

# ---- Task 6 (Amendment G2.3, G2.6; P3P-07) and Task A5 (I9.4): the stub run and the stub check of each test stub that a
# project's protected protocol declares (FR3: reason, check, variant; the framework names no stub). Task 29 calls the
# first declared stub from B15. ----
TEST_FLOOR=2
NOT_DECLARED='no example project declares a test stub (protocol stubs)'

def stub_spec(stub):
    """The run and check inputs of one protocol stub: reason, check, variant, trial id, test environment and label."""
    reason=stub['reason']
    return {'reason':reason,'check':stub['check'],'variant':stub['variant'],'trial':f'selftest-{reason}'[:40],'env':{STUB_VAR:reason},
            'model':stub.get('label',reason)}

def _stub_entry(case,reason):
    """The call-deadline entry of the case with the stub reason (read through `entries`), or None."""
    return next((e for e in entries(case) if e['reason']==reason),None)

def declared_project_stubs(root,project):
    """[(project, case, spec)] for every stub of the project's protocol (in declaration order). The stub's case is the first
    protocol case that declares a call deadline with the stub reason and has the stub variant. GateError when no case
    matches (a stub that cannot run is BLOCKED, never skipped)."""
    import bench_model as bm
    proto=bm.load_protocol(root,project);out=[]
    for stub in (proto or {}).get('stubs',[]):
        spec=stub_spec(stub);case=None
        for cid in proto['cases']:
            c=bm.load_case(root,cid,project)
            if _stub_entry(c,spec['reason']) is not None and spec['variant'] in [v['id'] for v in c['variants']]:case=c;break
        if case is None:raise GateError(f"protocol stub {spec['reason']}: no case of the project declares that call deadline with the variant {spec['variant']}")
        out.append((project,case,spec))
    return out

def declared_stubs(root,project=None):
    """declared_project_stubs of every example project of the scope (bench.example_projects: the framework examples, found
    by layout, or the explicit `project`; the framework names no example)."""
    import bench
    return [x for p in bench.example_projects(root,project) for x in declared_project_stubs(root,p)]

def declared_stub_reasons(root):
    """The reasons of declared_stubs, in declaration order (GateError as there)."""
    return [s['reason'] for _,_,s in declared_stubs(root)]

def stub_project(root,reason):
    """(project directory, case, spec) of the first declared stub with `reason`; GateError when none."""
    hit=next((x for x in declared_stubs(root) if x[2]['reason']==reason),None)
    if hit is None:raise GateError(f'no example project declares the {reason} test stub')
    return hit

def stub_suites(root,run_dir,project=None):
    """(suites, not_run) of `bench selftest`: a stub run `stub-run-<reason>` and a stub check `stub-check-<reason>` per
    declared stub. FR1-01: when no example project declares a stub, no suite runs and not_run records both suite kinds
    with the reason (cases.json `not_run`, as B15 records its stub part). A malformed declaration gives one BLOCKED suite
    `stubs` with the reason, never a silent skip. `project`: the example scope (declared_stubs)."""
    try:stubs=declared_stubs(root,project)
    except GateError as exc:
        return {'stubs':{'status':'BLOCKED','reason':str(exc)[:200],'property':'project test stubs: declaration readable'}},[]
    if not stubs:return {},[{'suite':'stub-run','reason':NOT_DECLARED},{'suite':'stub-check','reason':NOT_DECLARED}]
    suites={}
    for project,case,spec in stubs:
        suites['stub-run-'+spec['reason']]=_stub_run_selftest(root,run_dir,spec,project,case)
        suites['stub-check-'+spec['reason']]=_stub_check_selftest(root,run_dir,spec,project,case)
    return suites,[]

def _stub_plan(root,case,policy,envelope,seed,project,identity,spec):
    """The selftest plan of one stub run (`spec` of stub_spec): the case's smoke plan with its sessions replaced by one
    session of one caller trial (the stub variant, direct, warm, tier tiny, the covered selector) and no memory trials;
    mode `selftest`, test_floor_seconds 2 and the stub's test_env (the coordinator passes it to the trial child only for
    this mode). The trial's call deadline is max(2 s, factor x e), min the session deadline. Deterministic in its inputs."""
    import bench_plan as bp
    from bench import plan_digest
    variant=spec['variant'];selector=_stub_entry(case,spec['reason'])['selectors'][0];cap=policy['job_deadlines']['smoke']
    point=next(p for p in case['points'] if p['scope']=='caller' and p['size']=='tiny' and (p['variants'] is None or variant in p['variants']))
    base=bp.build_plan(case,policy,mode='smoke',dataset=bp.parse_dataset(root,'synthetic:small',policy),seed=seed,envelope=envelope,
                       project_dir=project,project_identity=identity)
    trial={'trial_id':spec['trial'],'block':None,'order':None,'point':point['name'],'scope':'caller','mode':'warm','variant':variant,'workers':'direct',
           'tier':'tiny','loops':1,'warmup':False,'selector':selector}
    sess={'session':'selftest-s00','group':point['name'],'point':point['name'],'scope':'caller','tier':'tiny','class':'exploratory','deadline_seconds':cap,
          'estimate_seconds':0.0,'trials':[trial]}
    plan={k:v for k,v in base.items() if k not in ('plan_id','project_dir','datasets')}     # T6-R7: no named dataset of a smoke probe point
    plan.update(mode='selftest',sessions=[sess],memory=[],test_floor_seconds=TEST_FLOOR,test_env=dict(spec['env']))
    trial.update(deadline_fields(case,policy,'timing',dict(plan,sizes=policy['sizes']),trial,None,cap))
    plan['plan_id']=plan_digest(plan)
    if project is not None:plan['project_dir']=project
    return plan

def stub_plan(root,case,policy,envelope,seed,spec,project=None,identity=None):
    """The selftest plan of a stub run (_stub_plan)."""
    return _stub_plan(root,case,policy,envelope,seed,project,identity,spec)

def _deadline_kills(run,session='selftest-s00'):
    """The `deadline_kills` rows of the timing job of `session` (default: the stub session), read from its recorded
    evidence `NNNN-timing-<session>.json` (the job row: per killed trial, `left` = members of the killed process group still
    present in /proc after the reap, zombies included, and `foreign_orphans`). [] when the evidence or the row is missing."""
    import bench
    from evidence import read_json
    if not isinstance(session,str):return []
    for p in ((run.get('evidence') or {}).get('jobs') or []):
        if re.fullmatch(r'[0-9]{4,}-timing-'+re.escape(session)+r'\.json',Path(p).name) and Path(p).is_file():
            try:row=bench.last_json(read_json(Path(p)).get('output',''))
            except (GateError,ValueError,TypeError):return []
            kills=row.get('deadline_kills') if isinstance(row,dict) else None
            return [k for k in kills if isinstance(k,dict)] if isinstance(kills,list) else []
    return []

def _stub_run_selftest(root,run_dir,spec,project=None,case=None):
    """One stub run: bench.run_cmd with the selftest plan of _stub_plan. Expected: run INVALID_EXPERIMENT with
    failure_reasons [reason] and the reason `run-invalid: <reason>`, the trial FAIL (call-deadline, the reason), and the
    child process group reaped (the timing session completes only when no group member survived the kill)."""
    import argparse, uuid
    import bench
    import bench_model as bm
    from evidence import read_json
    reason=spec['reason'];trial_id=spec['trial']
    started=time.monotonic();out={'status':'FAIL','property':f"{spec['variant']} {spec['model']}: process-group kill, FAIL {reason}, run INVALID_EXPERIMENT, never BLOCKED or TIMEOUT"}
    try:
        root=Path(root)
        if project is None or case is None:project,case,spec=stub_project(root,reason)
        policy=bm.load_policy(root,project);identity=bm.project_identity(root,project,case)
        from container_policy import choose_envelope, host_topology
        envelope=choose_envelope(*host_topology(),wanted=policy['envelope']['cpus'])
        plan=_stub_plan(root,case,policy,envelope,int(uuid.uuid4().int%2**31),project,identity,spec)
        rc,row=bench._quiet(bench.run_cmd,root,argparse.Namespace(case=case['case_id'],project=project,mode='smoke',dataset='synthetic:small',calibrate=None,plan=None,
                                                                  format='json',selftest_plan=plan))
        run_id=row.get('run_id');run_dir_run=root/'artifacts/bench'/run_id if isinstance(run_id,str) and re.fullmatch(r'[0-9a-f]{32}',run_id) else None
        run=read_json(run_dir_run/'run.json') if run_dir_run and (run_dir_run/'run.json').is_file() else {}
        obs=bench.read_jsonl(run_dir_run/'observations.jsonl') if run_dir_run and (run_dir_run/'observations.jsonl').is_file() else []
        hang=next((o for o in obs if o['trial_id']==trial_id),None);reasons=run.get('reasons',[])
        trial_fail=hang is not None and hang.get('eligible') is False and hang['verdict'].get('failures')=={'call-deadline':1} and hang.get('failure_reason')==reason
        kills=_deadline_kills(run)            # the coordinator's own count of group members left after the kill (/proc)
        gone=reaped(run,obs,trial_id,'selftest-s00')
        ok=(rc==1 and run.get('status')=='INVALID_EXPERIMENT' and run.get('failure_reasons')==[reason] and f'run-invalid: {reason}' in reasons
            and trial_fail and gone)
        out.update(status='PASS' if ok else 'BLOCKED' if rc==2 else 'FAIL',run_id=run_id,run_status=run.get('status'),failure_reasons=run.get('failure_reasons'),
                   trial_failed=trial_fail,reaped=gone,group_left=[k.get('left') for k in kills],call_deadline_seconds=plan_deadline(plan,trial_id))
    except GateError as exc:out.update(status='BLOCKED',reason=str(exc)[:200])
    out['duration_seconds']=round(time.monotonic()-started,1);return out

def _stub_check_selftest(root,run_dir,spec,project=None,case=None):
    """One stub check: one coordinator `check` job of the project check of `spec` with the selftest mode, the test floor
    and the stub variable, judged by bench.check_outcome (the bench check rule). Expected: FAIL, exit 1, the stub reason,
    never BLOCKED; the control (the same check, the same 2 s floor, no stub variable) must PASS."""
    import bench
    import bench_model as bm
    from evidence import passed
    reason=spec['reason'];check=spec['check']
    started=time.monotonic();out={'status':'FAIL','property':f"bench check of the {spec['variant']} stub {spec['model']}: FAIL {reason}, exit 1, never BLOCKED"}
    try:
        root=Path(root);run_dir=Path(run_dir)
        if project is None or case is None:project,case,spec=stub_project(root,reason)
        policy=bm.load_policy(root,project)
        selector=_stub_entry(case,reason)['selectors'][0];deadline=policy['job_deadlines']['smoke']
        test={'mode':'selftest','test_floor_seconds':TEST_FLOOR,'test_env':dict(spec['env'])};check_test_floor(test)
        trial={'variant':spec['variant'],'selector':selector,'rows':SUITE_ROWS,'calls':SUITE_CALLS}
        def one(extra,name):
            job={'schema_version':1,'job':'check','run_id':run_dir.name,'project_dir':project,'check':check,'check_args':[],'selector':selector,
                 'deadline_seconds':deadline,**extra,**deadline_fields(case,policy,'selftest-suite',dict(extra,sizes=policy['sizes']),trial,None,deadline)}
            s=bench.BenchSession(root,run_dir)
            try:r=s.job(job,name,deadline);row=bench.last_json(r['output'])
            finally:s.close()
            return (*bench.check_outcome(check,'PASS' if passed(r) and row.get('status')=='PASS' else 'FAIL',row),job.get('call_deadline_seconds'),r['evidence_path'])
        status,text,got,limit,ev=one(test,'check-'+check)
        control=one({'mode':'selftest','test_floor_seconds':TEST_FLOOR},'check-'+check+'-control')   # same 2 s floor, no stub: must PASS,
        # so the FAIL above comes from the stub, not from a slow child start (review Minor 2)
        code=bench.EXIT[status]
        out.update(status='PASS' if (status,code,got)==('FAIL',1,reason) and control[0]=='PASS' else 'FAIL',exit=code,reason=got,text=text[-80:],
                   call_deadline_seconds=limit,control_check=control[0],evidence_paths=[ev,control[4]])
    except GateError as exc:out.update(status='BLOCKED',reason=str(exc)[:200])
    out['duration_seconds']=round(time.monotonic()-started,1);return out

def first_stub_selftests(root,run_dir,project=None):
    """B15 (Task 29): the stub run and the stub check of the first declared stub of the example scope `project`
    (declared_stubs), or None when no project declares one (GateError as declared_stubs)."""
    stubs=declared_stubs(root,project)
    if not stubs:return None
    project,case,spec=stubs[0]
    return {'reason':spec['reason'],'run':_stub_run_selftest(root,run_dir,spec,project,case),'check':_stub_check_selftest(root,run_dir,spec,project,case)}
