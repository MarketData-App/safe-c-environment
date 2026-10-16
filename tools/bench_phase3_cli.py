"""Phase 3 operations of `./tools/safety bench`, registered by one line in tools/bench.py before `configure_parser`
(`import bench_phase3_cli;bench_phase3_cli.register(HANDLERS,ARGUMENTS)`), so that Phase 3 adds no other hunk there.
Task 7: `panel` (Amendment G3.3, G3.7; Task A6 adds `--rejected-from`, H21). Task 17: `decide` (replay in Task 20;
privacy-pattern in Task 27)."""
import argparse, json
from pathlib import Path
from evidence import GateError, atomic_json, read_json

def _panel(root,args):
    import bench_panel
    return bench_panel.panel_cmd(root,args)

def decide_cmd(root,args):
    import bench_evidence as be
    with be.run_lock(args.run_id):return _decide_locked(root,args)      # T16-APP-06 (c): one compare, report or decide per run

def _refuse(bench,args,reasons,text):
    bench.emit(args,{'status':'FAIL','reasons':reasons[:20]},'decide refused: '+text);return 1

def _decide_locked(root,args):
    import bench, bench_decide as bd, bench_evidence as be, bench_model as bm
    run_dir=bench._run_dir(root,args.run_id);run=bench.read_json(run_dir/'run.json')
    record=be.verify_record(run)                 # T17-APP-01: run.json itself is bound; unbound or stripped is refused. T17-RR-01: before
    if record:return _refuse(bench,args,record,record[0])     # any field of run.json is used, so an edited mode is FAIL, not BLOCKED
    if run.get('mode')=='profile':
        bench.emit(args,{'status':'BLOCKED','reason':'profiled runs never decide'},'BLOCKED: profiled runs never decide');return 2
    if be.unbindable_blocked(run):                # T17-APP-03: bench run could not bind the evidence; nothing to decide
        bench.emit(args,{'status':'BLOCKED','reasons':run['reasons'][:1]},'BLOCKED: '+run['reasons'][0]);return 2
    problems=be.verify(run_dir,run)              # T16-APP-01: an unbound run (no evidence digests) is refused as well
    if problems:return _refuse(bench,args,problems,'; '.join(problems[:5]))
    from policy import source_identity
    if be.stale(run,source_identity(root)[0]):                      # P10 reused-source-report: another source's report is refused
        return _refuse(bench,args,['reused-source-report: the run belongs to another source identity'],'reused-source-report')
    p15=be.policy_runtime_problems(root,run)        # P10 post-hoc-policy-change and reused-runner-report
    if p15:return _refuse(bench,args,p15,'; '.join(p15))
    import bench_accounting
    acc=bench_accounting.recheck(run,run_dir)        # B15 cgroup identity (P3R4-01, P3R5-01)
    if acc==[bench_accounting.UNRECORDED]:           # T16-APP-01: run.json is not digest-bound; no identity rows is an unbound run
        return _refuse(bench,args,['unbound: cgroup identity unrecorded (run.json holds no accounting rows)'],'unbound: cgroup identity unrecorded')
    if acc:return _refuse(bench,args,acc,'; '.join(acc[:3]))
    args.cgroup_unrecorded=False
    try:plan=read_json(run_dir/'plan.json')
    except FileNotFoundError:return _refuse(bench,args,['missing: plan.json'],'missing: plan.json')     # T16-APP-06 (a)
    facts=be.plan_fact_problems(run,plan)        # T17-APP-01 (d): case, mode, project_dir and envelope come from plan.json
    if facts:return _refuse(bench,args,facts,'; '.join(facts))
    run=dict(run,case=plan.get('case'),mode=plan.get('mode'),envelope=plan.get('envelope'),plan=dict(run.get('plan') or {},project_dir=plan.get('project_dir')))
    # the digest-bound plan says whether the run is local; a run.json dataset that differs from it is a dataset mismatch below
    if (plan.get('dataset') or {}).get('kind')=='local':raise GateError('a local run decides only from its merged aggregate (Task 31)')
    policy_doc=bm.load_policy(root);obs=bench.read_jsonl(run_dir/'observations.jsonl');phases=bench.read_jsonl(run_dir/'phases.jsonl')
    blocked=run.get('status')=='BLOCKED' and not be.has_timed_rows(obs)
    integrity=[] if blocked else be.check_integrity(plan,run,obs+phases,policy_doc)     # B15, P10 on the recorded files (Task 16 hook)
    if integrity:return _refuse(bench,args,integrity,'; '.join(integrity[:5]))
    status,reasons=be.recorded_status(plan,run,obs,phases,policy_doc)     # T16-APP-01: never the status field of run.json
    if status=='BLOCKED':
        bench.emit(args,{'status':'BLOCKED','reasons':reasons[:20]},'BLOCKED: the run measured nothing; nothing decided');return 2
    names=policies_for(plan,args.policy);project=plan.get('project_dir')
    owner=[n for n in names if bm.load_decision_policy(root,n,project).get('kind')=='unit-threshold']
    if owner:                                    # Task 18: the unit-threshold branch, after every shared check above (P3R3-04)
        if names!=owner or len(owner)!=1:raise GateError('a unit-threshold decision is never mixed with another policy')
        return decide_owner(root,args,owner[0])
    run,plan,case,opp=_load_run(root,args.run_id)
    ev=bd.evidence_from_run(root,run_dir,run,plan,case);stats=bd.stats_of(policy_doc);records=[]
    for n in names:
        pol=bm.load_decision_policy(root,n)
        records.append(bd.decision_record(root,run,plan,case,n,bd.decide(ev,pol,opp,stats),ev,opp,cgroup_unrecorded=args.cgroup_unrecorded,stats=stats))
    _write_records(run_dir,records)
    worst='FAIL' if any(r['outcome']=='INVALID_EXPERIMENT' or any(u['verdict']=='INVALID_EXPERIMENT' for u in r.get('units') or []) for r in records) else 'PASS'
    bench.emit(args,{'status':worst,'decisions':{r['policy']['name']:[r['outcome'],r['adoption_outcome']] for r in records},'report':str(run_dir/'decision.md')},
               '; '.join(f"{r['policy']['name']}: rule {r['rule']} {r['outcome']} / adoption {r['adoption_outcome']}" for r in records))
    return 0 if worst=='PASS' else 1

def _load_run(root,run_id):
    """(run, plan, case, opportunity) of a run that decide_cmd has checked: run.json with case, mode, envelope and project_dir
    from the digest-bound plan.json (T17-APP-01 (d)) and the status and reasons re-derived from the recorded files
    (T16-APP-01, bench_evidence.recorded_status; never the status field of run.json). Shared by both decide branches."""
    import bench, bench_evidence as be, bench_model as bm
    run_dir=bench._run_dir(root,run_id);run=bench.read_json(run_dir/'run.json');plan=read_json(run_dir/'plan.json')
    run=dict(run,case=plan.get('case'),mode=plan.get('mode'),envelope=plan.get('envelope'),plan=dict(run.get('plan') or {},project_dir=plan.get('project_dir')))
    policy_doc=bm.load_policy(root);obs=bench.read_jsonl(run_dir/'observations.jsonl');phases=bench.read_jsonl(run_dir/'phases.jsonl')
    status,reasons=be.recorded_status(plan,run,obs,phases,policy_doc);run=dict(run,status=status,reasons=reasons)
    project=run['plan'].get('project_dir');case=bm.load_case(root,run['case'],project)
    return run,plan,case,bm.load_opportunity(root,case,project) or {}

def _write_records(run_dir,records):
    """Validates every decision record against the closed schema first, then writes decision-<policy>.json for each and
    decision.md (rule-policy records through bench_decide.render_markdown, owner records through render_units_markdown).
    S3-03: run.json must match its run record digest before any record is written (bench_evidence.bindable_run); after the
    writes, run.json binds the sha256 of each written record (bench_evidence.bind_decisions), so the decided policy set of
    the run is bound data, not the set of files that are in the run directory. FR12-A04: the run record that the bind
    would write is checked against its schema before any record is written (bench_evidence.check_bind)."""
    import bench_decide as bd, bench_evidence as be, bench_units as bu
    from schema_check import validate
    root=Path(__file__).resolve().parents[1]
    for rec in records:validate(root,'bench-decision',rec)
    run=be.bindable_run(run_dir)
    be.check_bind(run,[rec['policy']['name'] for rec in records])
    for rec in records:atomic_json(Path(run_dir)/f"decision-{rec['policy']['name']}.json",rec)
    (Path(run_dir)/'decision.md').write_text(bd.render_markdown([r for r in records if not r.get('units')])+''.join(bu.render_units_markdown(r) for r in records if r.get('units')))
    be.bind_decisions(run_dir,run,[rec['policy']['name'] for rec in records])

def _sensitivity(root,args,pol=None):
    """Amendment H16.1: the record's `sensitivity` object {owner_confirmation: {ledger_id, coverage_sha256}} from the owner's
    confirmation at --sensitivity-confirmation (schemas/bench-owner-confirmation.json), or None after printing the refusal
    `sensitivity-unconfirmed`: no confirmation, an unreadable or invalid one, a coverage_path file whose sha256 differs
    from coverage_sha256 (another coverage record), or a confirmed record that does not certify the current code (H14)."""
    import bench, bench_units as bu, hashlib
    from schema_check import validate
    def refuse(text):
        bench.emit(args,{'status':'FAIL','reasons':['sensitivity-unconfirmed: '+text]},'decide refused: sensitivity-unconfirmed ('+text+')');return None
    path=getattr(args,'sensitivity_confirmation',None)
    if path is None:return refuse('no owner confirmation (--sensitivity-confirmation)')
    p=Path(path) if Path(path).is_absolute() else Path(root)/path
    from evidence import PROJECT_JSON_MAX_BYTES, load_project_json
    try:doc=load_project_json(p,'owner-confirmation',PROJECT_JSON_MAX_BYTES,label='owner confirmation',
                              check=lambda d:validate(root,'bench-owner-confirmation',d))     # FR3-17: the one boundary
    except (OSError,ValueError,GateError):return refuse('the confirmation is unreadable or not a bench-owner-confirmation record')
    try:
        cov=Path(doc['coverage_path']) if Path(doc['coverage_path']).is_absolute() else Path(root)/doc['coverage_path']
        data=cov.read_bytes()
    except (OSError,ValueError):return refuse('the confirmed coverage record is unreadable')    # ValueError: a NUL in the path
    if hashlib.sha256(data).hexdigest()!=doc['coverage_sha256']:return refuse('the confirmation names another coverage record')
    if not bu.coverage_record_ok(root,cov,pol):return refuse('the confirmed coverage record does not certify the current code (H14)')
    return {'owner_confirmation':{'ledger_id':doc['ledger_id'],'coverage_sha256':doc['coverage_sha256']}}

def decide_owner(root,args,name):
    """The unit-threshold branch of decide (G9, base Task 18) for the policy `name` of the protocol of the run's project
    (FR3: project data). decide_cmd has made every shared check (evidence digests, the current source identity, policy,
    protocol and runner binding, the cgroup identity, dataset identities, check_integrity; P3R3-04): this function repeats
    none of them and never calls bench_decide.decide. Refusals (exit 1, no record): an unrecorded cgroup identity, a smoke
    run (G10.4), a run of another case than the policy's case (FR3-08), no valid sensitivity confirmation (H16.1). Otherwise the unit verdicts are the adoption outcome (G9.9):
    one decision record, exit 1 when a unit is INVALID_EXPERIMENT."""
    import bench, bench_decide as bd, bench_model as bm, bench_units as bu
    run,plan,case,opp=_load_run(root,args.run_id)
    if getattr(args,'cgroup_unrecorded',False):
        return _refuse(bench,args,['cgroup-identity-unrecorded: a unit-threshold verdict needs the recorded cgroup identity'],'cgroup-identity-unrecorded')
    if run.get('mode')=='smoke':return _refuse(bench,args,['smoke runs give no unit verdict (G10.4)'],'smoke runs give no unit verdict')
    pol=bm.load_decision_policy(root,name,(run.get('plan') or {}).get('project_dir'))
    if pol.get('case')!=run.get('case'):         # FR3-08: a unit-threshold policy decides only its own protocol case
        return _refuse(bench,args,[f'policy-case-mismatch: policy {name} is for case {str(pol.get("case"))[:41]}, the run is of case {str(run.get("case"))[:41]}'],'policy-case-mismatch')
    sensitivity=_sensitivity(root,args,pol)
    if sensitivity is None:return 1
    run_dir=Path(root)/'artifacts/bench'/args.run_id
    uev=bu.unit_evidence_from_run(root,run_dir,run,plan,case,pol,args)
    units=bu.decide_units(uev,pol,bd.stats_of(bm.load_policy(root)))
    rec=bu.unit_decision_record(root,run,plan,case,pol,units,uev,opp,sensitivity=sensitivity,windows=None)   # windows: Task A9
    _write_records(run_dir,[rec])
    got=rec.get('units') or [];invalid=any(u.get('verdict')=='INVALID_EXPERIMENT' for u in got)
    bench.emit(args,{'status':'FAIL' if invalid else 'PASS','decisions':{name:[[u.get('unit'),u.get('verdict'),u.get('reason')] for u in got]},'report':str(run_dir/'decision.md')},
               '; '.join(f"{u.get('unit')}: {u.get('verdict')} ({u.get('reason')})" for u in got) or f'{name}: no unit records')
    return 1 if invalid else 0

RULE_POLICIES=['owner','demo-latency-2x','demo-cpu-40']

def policies_for(plan,requested):
    """The policies to decide: the requested one, or for `all` the plan's named (project unit-threshold) policy when the
    plan names one, else the three framework rule policies."""
    if requested!='all':return [requested]
    named=plan.get('policy')
    return [named] if isinstance(named,str) and named not in RULE_POLICIES else list(RULE_POLICIES)

def policy_name(value):
    """--policy: all, a framework rule policy, or a project unit-threshold policy name (bench_model loads it from the
    protocol of the run's project; an unknown name is refused there)."""
    import re
    if value!='all' and not re.fullmatch(r'[a-z][a-z0-9-]{2,40}',value):raise argparse.ArgumentTypeError('--policy: a policy name')
    return value

def approval_path(value):
    if len(value)>300:raise argparse.ArgumentTypeError('--approval: at most 300 characters')
    return value

PATTERN_TEXT={True:'privacy path pattern installed',False:'privacy path pattern already present'}

def privacy_pattern_cmd(root,args):
    """Task 27 (S-06): `bench privacy-pattern --dataset local:PATH` appends the fixture file name pattern to the private path
    patterns of the hooks (bench_privacy.install_fixture_pattern). Prints one fixed line, never the name."""
    import bench, bench_privacy
    text=PATTERN_TEXT[bench_privacy.install_fixture_pattern(root,args.dataset)]
    bench.emit(args,{'status':'PASS','result':text},text);return 0

def register(handlers,arguments):
    """Adds the Phase 3 operations to the bench HANDLERS and ARGUMENTS tables (each name once)."""
    for name in ('panel','decide','replay','privacy-pattern'):
        if name in handlers:raise ValueError(f'bench operation {name} is already registered')
    handlers['privacy-pattern']=privacy_pattern_cmd;arguments['privacy-pattern']=[('--dataset',{'required':True})]
    import bench_replay                          # Task 20 (spec 13)
    handlers['replay']=bench_replay.replay_cmd;arguments['replay']=[('--run-id',{'required':True}),('--dataset',{})]
    handlers['panel']=_panel
    arguments['panel']=[('--case',{'required':True}),('--project',{}),('--dataset',{'default':'synthetic:large'}),
                        ('--rejected-from',{'default':None})]      # Task A6 (H21.6, H21.7): a tracked pre-flight record
    handlers['decide']=decide_cmd
    arguments['decide']=[('--run-id',{'required':True}),('--policy',{'type':policy_name,'default':'all'}),
                         ('--ci-run-id',{}),('--approval',{'action':'append','default':[],'type':approval_path}),
                         ('--sensitivity-confirmation',{'default':None,'type':approval_path})]     # Task 18 (H16.1): owner-sensitivity.json
