"""bench replay (spec 13): re-run the recorded plan only while its profile is authorized; a new run identity and new
observations; never copies old numbers (spec 13, brief section 14 `replay`, Amendment H8, P10; B18 verifies replay).

Rulings T20-C1 and T20-C2 (Task 20):
- bench run adds RUN_ADDED_PLAN_KEYS to a plan after build_plan computed plan_id, and writes that plan to plan.json. The
  plan identity is therefore the plan_digest of the recorded plan without exactly those keys (plan_body); the added keys
  stay bound by the evidence digest of plan.json. The replay gives bench run plan_body from a temporary file outside the
  old run directory, and bench run adds the keys again (pyperf by mode).
- run.json is checked by its record digest before any of its fields is used; the old run is read under its run lock;
  the replay uses the run id that bench run created (args.created_run_id), never "the latest run"; a local replay is
  refused in a project instance and, since Task 26, under CI (bench_privacy.refuse_local)."""
import argparse, json, tempfile
from pathlib import Path
from evidence import GateError, file_hash, read_json

RUN_ADDED_PLAN_KEYS=('pyperf',)     # T20-C1: the key tools/bench.py run_cmd adds after plan_id (plan['pyperf']; FR3: no market key)

def _read_plan(run_dir):return read_json(Path(run_dir)/'plan.json')

def plan_body(plan):
    """T20-C1: the recorded plan without exactly RUN_ADDED_PLAN_KEYS (the plan that build_plan or bench plan wrote)."""
    return {k:v for k,v in plan.items() if k not in RUN_ADDED_PLAN_KEYS}

def _project(run,plan):
    """project_dir of the run: the digest-bound plan.json (a local run.json does not hold it), else run.json."""
    if isinstance(plan,dict) and 'project_dir' in plan:return plan['project_dir']
    return (run.get('plan') or {}).get('project_dir')

def authorization(root,run_dir,run,plan):
    import bench, bench_evidence as be, bench_model as bm
    root=Path(root)
    record=be.verify_record(run)                 # T20-C2 (T17-APP-01): a tampered run.json is refused before its fields are used
    if record:return ['recorded evidence changed: '+'; '.join(record)]
    problems=[]
    ev=be.verify(run_dir,run)
    if be.is_unbound(ev):problems.append('unbound runs are never replayed')
    elif ev:problems.append('recorded evidence changed: '+'; '.join(ev[:3]))
    if not isinstance(plan,dict) or bench.plan_digest(plan_body(plan))!=plan.get('plan_id'):problems.append('recorded plan changed')
    if 'bench_profile_sha256' not in run:problems.append('the run predates the recorded bench profile')
    elif run['bench_profile_sha256']!=be.bench_profile_sha256(root):problems.append('bench profile changed since the run')
    if run.get('policy_sha256')!=file_hash(root/'safety/performance-policy.json'):problems.append('performance policy changed since the run')
    if be.protocol_problems(root,run):problems.append('project protocol changed since the run')     # FR3: the run's bound protocol digest
    if run.get('image_id')!=read_json(root/'developer.lock.json')['image_id']:problems.append('image changed since the run')
    project=_project(run,plan)
    try:case=bm.load_case(root,run['case'],project)
    except (GateError,KeyError):return problems+['case no longer registered']
    if case['version']!=run.get('case_version'):problems.append('case version changed since the run')
    ident=bm.project_identity(root,project,case) if project is not None and case['case_id'] in bm.project_bench(root,project)['cases'] else None
    rplan=run.get('plan') or {}
    recorded=rplan['project_identity'] if 'project_identity' in rplan else (plan or {}).get('project_identity')
    if ident!=recorded:problems.append('project identity changed since the run')
    return problems

def _fail(bench,args,reasons,text,**more):
    bench.emit(args,{'status':'FAIL','replay_of':args.run_id,'reasons':reasons,**more},f'replay {args.run_id} FAIL: {text}');return 1

def replay_cmd(root,args):
    import bench, bench_evidence as be, bench_privacy
    root=Path(root)
    with be.run_lock(args.run_id):               # T20-C2 (T16-APP-06 (c)): the old run is read and verified under its run lock
        run_dir=bench._run_dir(root,args.run_id);run=bench.read_json(run_dir/'run.json');plan=_read_plan(run_dir)
        problems=authorization(root,run_dir,run,plan)
        old=bench.read_jsonl(run_dir/'observations.jsonl') if not problems and (run_dir/'observations.jsonl').is_file() else []
    if problems:
        bench.emit(args,{'status':'BLOCKED','replay_of':args.run_id,'reasons':problems},'replay BLOCKED: '+'; '.join(problems));return 2
    local=(plan.get('dataset') or {}).get('kind')=='local'
    if local:                                    # spec 12 (Task 26): a local replay is refused under CI and in project instances
        try:bench_privacy.refuse_local(root,'local replay')
        except GateError as exc:
            reason=str(exc)
            bench.emit(args,{'status':'BLOCKED','replay_of':args.run_id,'reasons':[reason]},'replay BLOCKED: '+reason);return 2
    if local and not args.dataset:raise GateError('a local replay needs --dataset local:PATH with the recorded digest')
    with tempfile.TemporaryDirectory(prefix='safe-c-replay-') as tmp:     # T20-C1: never a file of the old run directory
        path=Path(tmp)/'plan.json';path.write_text(json.dumps(plan_body(plan),sort_keys=True))
        ns=argparse.Namespace(case=run['case'],project=_project(run,plan),mode=plan['mode'],
                              dataset=args.dataset if local else f"synthetic:{plan['dataset']['size']}",calibrate=None,plan=str(path),
                              format=getattr(args,'format','text'),replay_of=args.run_id)
        rc=bench.run_cmd(root,ns)
    created=getattr(ns,'created_run_id',None)    # T20-C2: the run that bench run created, never the newest run directory
    if created is None:return _fail(bench,args,['replay produced no new run'],'no new run')
    try:new_dir=bench._run_dir(root,created);new=bench.read_json(new_dir/'run.json')
    except (GateError,OSError,ValueError):return _fail(bench,args,['the new run has no readable run.json'],'no new run record',run_id=created)
    reasons=[]
    if created==args.run_id:reasons.append('replay reused the run identity')
    if new.get('replay_of')!=args.run_id:reasons.append('the new run does not name the replayed run (replay_of)')
    reasons+=be.verify_record(new)
    reasons+=be.check_replay_fresh(old,bench.read_jsonl(new_dir/'observations.jsonl') if (new_dir/'observations.jsonl').is_file() else [])
    status='FAIL' if reasons else {0:'PASS',1:'FAIL',2:'BLOCKED'}.get(rc,'FAIL')
    bench.emit(args,{'status':status,'replay_of':args.run_id,'run_id':created,'reasons':reasons},f'replay {args.run_id} -> {created}: {status}')
    return {'PASS':0,'FAIL':1,'BLOCKED':2}[status]
