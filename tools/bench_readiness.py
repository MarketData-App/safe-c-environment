"""Readiness axes of the owner's brief section 18 (spec 13, Amendment H9; Task 24): the `performance` key of `dev readiness`.

Each axis reads only evidence whose source identity equals the current one. Missing evidence is BLOCKED, NOT_EXECUTED or
INCONCLUSIVE, never a pass; a real failure (a FAIL gate or suite) is FAILED, never BLOCKED. Decisions are review
recommendations: the three false axes are constants. The existing live-agent axis stays a separate top-level axis; the
performance handoff trial (Task 33) and the owner-policy unit verdicts are details, never axes of this list.

The two demo axes read only the demo decision run of Task 35 (an example project case, synthetic large; is_demo_run),
never a framework control-case run. The demo_experiment_execution domain has no FAILED value: a B17 FAIL (an attempted
execution that failed) is PARTIAL, never NOT_EXECUTED (T24-APP-02); the failure itself shows in combined_local_checks."""
import json
from pathlib import Path
from evidence import GateError, file_hash, load_project_json, PROJECT_JSON_MAX_BYTES, read_json, read_jsonl
from schema_check import validate
from bench_phase3_cli import RULE_POLICIES

def _unit_policy_plan(plan):
    """FR3: True when a plan names a policy that is not a framework rule policy (a project unit-threshold policy)."""
    name=plan.get('policy');return name is not None and name not in RULE_POLICIES

AXES=('benchmark_tooling','measurement_qualification','multicore_qualification','demo_experiment_execution','demo_performance_evidence',
      'combined_local_checks','independent_enforcement','actual_django_workload_tested','native_adoption_authorized','production_authorized')
FALSE_AXES=('actual_django_workload_tested','native_adoption_authorized','production_authorized')
TOOLING_SUITES=('B01',);MEASUREMENT_SUITES=('B02','B03','B05','B09','B13','B15');MULTICORE_SUITES=('B04','B10','B11','B12');DEMO_SUITE='B17'
CI_COMMAND='./tools/safety ci'
VERDICTS=('KEEP_PYTHON','PREFER_C','INCONCLUSIVE','INVALID_EXPERIMENT')
NO_RECEIPT='NOT_EXECUTED (trial mechanism: no receipt)'
MATRIX_UNAVAILABLE='matrix check unavailable (bench_phase3.matrix_complete, Task 30)'
DEMO_DATASET=('synthetic','large')     # Task 35: the demo decision run uses --dataset synthetic:large
FRAMEWORK=Path(__file__).resolve().parents[1]      # the closed schemas are framework files (as bench_phase3_cli._write_records)

def _read(path):
    """The JSON object at path, or None (missing, unreadable, malformed or not an object)."""
    try:value=read_json(Path(path))
    except (OSError,ValueError,GateError):return None
    return value if isinstance(value,dict) else None

def _jsonl(path):
    try:rows=read_jsonl(Path(path),'readiness-jsonl')     # FR3-19: container-written rows, capped
    except (OSError,ValueError):return None
    return rows if all(isinstance(r,dict) for r in rows) else None

def current_report(root,identity):
    """artifacts/bootstrap-report.json when it names the current source identity and its last command is the full ci."""
    rep=_read(Path(root)/'artifacts/bootstrap-report.json')
    if not rep or rep.get('source_identity')!=identity or not isinstance(rep.get('commands'),list) or rep['commands'][-1:]!=[CI_COMMAND]:return None
    return rep

def _gate(report,name):
    gates=report.get('gates') if isinstance(report,dict) else None
    return next((g for g in gates if isinstance(g,dict) and g.get('name')==name),None) if isinstance(gates,list) else None

def _status(value):return value if value in ('PASS','FAIL','BLOCKED') else None

def suite_status(report,name):
    """The status of one suite in the bench-selftest gate details, or None when it is missing."""
    gate=_gate(report,'bench-selftest');details=gate.get('details') if gate else None
    return _status(details.get(name)) if isinstance(details,dict) else None

def b17_not_run(report):
    """EX17-A02: the open B17 entries ('B17 <dimension>') of the cases.json `not_run` list that the bench-selftest gate
    details carry (bench.cases_not_run); [] when none is open; None when the list is missing or malformed (unknown)."""
    gate=_gate(report,'bench-selftest');details=gate.get('details') if gate else None
    rows=details.get('not_run') if isinstance(details,dict) else None
    if not isinstance(rows,list) or not all(isinstance(r,str) for r in rows):return None
    return [r for r in rows if r.startswith(DEMO_SUITE+' ')]

def _combine(statuses):
    """FAILED when any status is FAIL (a real failure); PASSED only when every status is PASS; else BLOCKED (missing or blocked)."""
    if 'FAIL' in statuses:return 'FAILED'
    return 'PASSED' if statuses and all(s=='PASS' for s in statuses) else 'BLOCKED'

def _multicore(report):
    gate=_gate(report,'bench-doctor');details=gate.get('details') if gate else None
    envelope=details.get('envelope') if isinstance(details,dict) else None
    return 'PASS' if isinstance(envelope,dict) and envelope.get('multicore')=='PASS' else None     # a missing multicore envelope is BLOCKED

def _runs(root,identity,mode):
    """(run_dir, run) of every run.json of that mode and the current source identity, newest first (created_at, run id)."""
    base=Path(root)/'artifacts/bench';out=[]
    if not base.is_dir():return out
    for p in base.glob('*/run.json'):
        if p.is_symlink() or not p.is_file():continue
        run=_read(p)
        if run and run.get('mode')==mode and run.get('source_identity')==identity:out.append((str(run.get('created_at') or ''),p.parent.name,p.parent,run))
    return [(d,run) for _,_,d,run in sorted(out,key=lambda x:(x[0],x[1]),reverse=True)]

def _bound(run_dir,run):
    """[] when run.json matches its record digest and every evidence file its digest (bench_evidence, H8, T17-APP-01)."""
    import bench_evidence as be
    problems=be.verify_record(run)
    if problems:return problems
    try:return be.verify(run_dir,run)
    except (GateError,OSError) as exc:return [type(exc).__name__]

def decision_records(root,identity,run_dir):
    """The current rule-policy decision records of a demo decision run (one per RULE_POLICIES entry), or None when any is
    missing, invalid, stale, of another run or identity, not of decision quality, or INVALID_EXPERIMENT. An INCONCLUSIVE
    outcome is an honest decision record."""
    out=[]
    for name in RULE_POLICIES:
        rec=_read(Path(run_dir)/f'decision-{name}.json')
        if not rec:return None
        try:validate(FRAMEWORK,'bench-decision',rec)
        except GateError:return None
        if (rec.get('run_id')!=Path(run_dir).name or (rec.get('policy') or {}).get('name')!=name or rec.get('stale') is not False or rec.get('source_identity_run')!=identity
            or rec.get('source_identity_decision')!=identity or rec.get('evidence_quality')!='decision' or rec.get('outcome')=='INVALID_EXPERIMENT'):return None
        out.append(rec)
    return out

def primary_missing(plan,observations):
    """One entry per measured trial of a primary point without eligible observations; a plan without a primary point is incomplete."""
    if observations is None:return ['observations unreadable']
    seen={}
    for o in observations:seen.setdefault(o.get('trial_id'),[]).append(o)
    sessions=[s for s in plan.get('sessions') or [] if isinstance(s,dict) and s.get('class')=='primary']
    if not sessions:return ['no primary point in the plan']
    return [t.get('trial_id') for s in sessions for t in s.get('trials') or [] if isinstance(t,dict) and not t.get('warmup')
            and not (seen.get(t.get('trial_id')) and all(o.get('eligible') is True for o in seen[t.get('trial_id')]))]

def matrix_missing(root,plan,observations):
    """bench_phase3.matrix_complete (Task 30) of the run; without that check the matrix is never complete."""
    try:import bench_phase3
    except ModuleNotFoundError as exc:
        if exc.name!='bench_phase3':raise
        return [MATRIX_UNAVAILABLE]
    check=getattr(bench_phase3,'matrix_complete',None)
    if check is None:return [MATRIX_UNAVAILABLE]
    if observations is None:return ['observations unreadable']
    try:
        import bench_model as bm
        return list(check(plan,observations,bm.load_case(Path(root),plan['case'],plan.get('project_dir'))))
    except (GateError,OSError,ValueError,KeyError,TypeError) as exc:return [f'matrix check failed: {type(exc).__name__}']

def demo_cases(root,project=None):
    """(project_dir, case_id) of every case of every framework example project (bench.example_projects, found by layout;
    the framework names no example, Amendment A), or of the explicit `project` (dev readiness --project DIR, amendment E
    1.2 item 3). The demo decision run of Task 35 is a run of one of these cases."""
    import bench, bench_model as bm
    out=set()
    for example in bench.example_projects(root,project):
        try:doc=load_project_json(Path(root)/example/bm.PROJECT_AREA/'bench.json','bench-json',PROJECT_JSON_MAX_BYTES,
                                  label='benchmarks/project/bench.json')      # FR3-17: a malformed example is skipped
        except GateError:doc=None
        cases=doc.get('cases') if isinstance(doc,dict) else None
        out|={(example,c) for c in (cases if isinstance(cases,list) else []) if isinstance(c,str)}
    return out

def is_demo_run(run,plan,cases):
    """T24-APP-01: the demo decision run of spec 13 and Task 35 (`bench run --project <example> --case <its case> --mode
    decision --dataset synthetic:large`): run.json (bound by its record digest) names an example project case, the
    dataset is synthetic large, plan.json agrees on case and project, and the plan is not the owner policy. A framework
    control-case run (every ci writes one) is never the demo run."""
    project=(run.get('plan') or {}).get('project_dir') if isinstance(run.get('plan'),dict) else None
    data=run.get('dataset') if isinstance(run.get('dataset'),dict) else {}
    return ((project,run.get('case')) in cases and (data.get('kind'),data.get('size'))==DEMO_DATASET
            and plan.get('case')==run.get('case') and plan.get('project_dir')==project and not _unit_policy_plan(plan))

def demo_run(root,identity,project=None):
    """The newest current demo decision run (is_demo_run; other decision runs are skipped, never a stop) or None:
    {run_id, valid, primary_missing, matrix}. valid needs the bound run record and evidence, status VALID and the current
    decision records of every rule policy. `project`: the example scope (demo_cases)."""
    cases=demo_cases(root,project)
    for run_dir,run in _runs(root,identity,'decision'):
        plan=_read(run_dir/'plan.json') or {}
        if not is_demo_run(run,plan,cases):continue
        valid=not _bound(run_dir,run) and run.get('status')=='VALID' and bool(plan) and decision_records(root,identity,run_dir) is not None
        obs=_jsonl(run_dir/'observations.jsonl') if valid else None
        return {'run_id':run_dir.name,'valid':valid,'primary_missing':primary_missing(plan,obs) if valid else None,
                'matrix':matrix_missing(root,plan,obs) if valid else None}
    return None

def _smoke_evidence(root,identity,project=None):
    """A current VALID bound smoke run of an example project case of the scope `project` (exploratory demo evidence; a
    control-case smoke run is none)."""
    cases=demo_cases(root,project)
    return any(((run.get('plan') or {}).get('project_dir') if isinstance(run.get('plan'),dict) else None,run.get('case')) in cases
               and run.get('status')=='VALID' and not _bound(d,run) for d,run in _runs(root,identity,'smoke'))

def performance_axes(root,identity,developer_axes,project=None):
    """The ten axes of brief section 18 in brief order (Amendment H9). `project` (dev readiness --project DIR): the demo
    axes read the cases of that project instead of the framework examples (amendment E 1.2 item 3)."""
    root=Path(root);rep=current_report(root,identity)
    if rep is None:tooling=measurement=multicore='BLOCKED'
    else:
        doctor=_gate(rep,'bench-doctor')
        tooling=_combine([_status(doctor.get('status')) if doctor else None]+[suite_status(rep,n) for n in TOOLING_SUITES])
        measurement=_combine([suite_status(rep,n) for n in MEASUREMENT_SUITES])
        multicore=_combine([suite_status(rep,n) for n in MULTICORE_SUITES]+[_multicore(rep)])
    run=demo_run(root,identity,project);b17=rep is not None and suite_status(rep,DEMO_SUITE)=='PASS';b17_failed=rep is not None and suite_status(rep,DEMO_SUITE)=='FAIL'
    # EX17-A02: a B17 dimension in cases.json not_run (or an unknown not_run list) keeps the axis below COMPLETE
    if b17 and run and run['valid'] and run['matrix']==[] and b17_not_run(rep)==[]:execution='COMPLETE'
    elif b17 or run or b17_failed:execution='PARTIAL'     # only one of them exists, the matrix has missing cells, or B17 ran and failed (T24-APP-02)
    else:execution='NOT_EXECUTED'
    if run:evidence='DECISION_GRADE' if run['valid'] and run['primary_missing']==[] else 'INCONCLUSIVE'
    else:evidence='EXPLORATORY' if _smoke_evidence(root,identity,project) else 'INCONCLUSIVE'
    return {'benchmark_tooling':tooling,'measurement_qualification':measurement,'multicore_qualification':multicore,
            'demo_experiment_execution':execution,'demo_performance_evidence':evidence,
            'combined_local_checks':developer_axes['combined_local_checks'],'independent_enforcement':developer_axes['independent_enforcement'],
            'actual_django_workload_tested':False,'native_adoption_authorized':False,'production_authorized':False}

def unit_verdicts(root,identity):
    """The unit-verdict counts of the newest current unit-threshold decision record (FR3: any decision-<name>.json whose
    name is not a framework rule policy), or None (no record, or the newest one is not current or not valid). Unit
    verdicts are decision records, never a readiness axis."""
    base=Path(root)/'artifacts/bench';found=[]
    if base.is_dir():
        for p in base.glob('*/decision-*.json'):
            if p.stem[len('decision-'):] in RULE_POLICIES:continue
            if p.is_file() and not p.is_symlink():found.append((p.stat().st_mtime,p.parent.name,p))
    if not found:return None
    path=max(found)[2];rec=_read(path)
    if not rec or rec.get('run_id')!=path.parent.name or rec.get('stale') is not False or rec.get('source_identity_run')!=identity or rec.get('source_identity_decision')!=identity:return None
    try:validate(FRAMEWORK,'bench-decision',rec)
    except GateError:return None
    units=rec.get('units') or []
    return {v:sum(1 for u in units if u.get('verdict')==v) for v in VERDICTS}

HANDOFF_RECEIPT='artifacts/bench/handoff-trial.json'

def _validate(root,doc):
    from schema_check import validate
    validate(root,'bench-handoff-trial',doc)

NO_RUN='NOT_EXECUTED (trial mechanism: receipt names no current decision run)'
OTHER_POLICIES='NOT_EXECUTED (trial mechanism: receipt decisions differ from the run policies)'

def run_policies(root,identity,run_id):
    """S2-01: the decision policies of decision run run_id, or None when run_id names no current decision run. The run is
    current when its run.json has mode decision and the current source identity (_runs) and matches its record and
    evidence digests (_bound). S3-03: its decision policies are the rule policies that run.json binds (decision_digests,
    written by bench decide and covered by the run record digest), never the decision files that are in the run directory
    now. Each bound record must exist as a regular file with the bound sha256 and be schema-valid, of this run and policy,
    not stale and of the current source identity; a rule-policy record that run.json does not bind is refused as well.
    Any of these failures is None, so a removed, edited or added record cannot change the required set. A run that binds
    no rule-policy record is None."""
    run=next((run for d,run in _runs(root,identity,'decision') if d.name==run_id),None)
    if run is None:return None
    run_dir=Path(root)/'artifacts/bench'/run_id
    if _bound(run_dir,run):return None
    import bench_evidence as be
    digests=run.get(be.DECISIONS_KEY) if isinstance(run.get(be.DECISIONS_KEY),dict) else {}
    names=[]
    for name in RULE_POLICIES:
        p=run_dir/f'decision-{name}.json'
        present=p.exists() or p.is_symlink()
        if name not in digests:
            if present:return None                  # a record that run.json does not bind
            continue
        if p.is_symlink() or not p.is_file() or file_hash(p)!=digests[name]:return None
        rec=_read(p)
        if not rec:return None
        try:validate(FRAMEWORK,'bench-decision',rec)
        except GateError:return None
        if (rec.get('run_id')!=run_id or (rec.get('policy') or {}).get('name')!=name or rec.get('stale') is not False
                or rec.get('source_identity_run')!=identity or rec.get('source_identity_decision')!=identity):return None
        names.append(name)
    return names or None

def handoff_trial_axis(root,identity,tooling):
    """Task 33 (Amendment H9): the status of the outer harness's handoff-trial receipt when it validates and names the
    current tooling identity and the readiness source identity; else NOT_EXECUTED with the reason. S2-01: a PASSED
    receipt also needs a run_id that names a current decision run (run_policies) and exactly one decision for each
    decision policy of that run, no more and no fewer."""
    p=Path(root)/HANDOFF_RECEIPT
    if not p.is_file():return 'NOT_EXECUTED (trial mechanism: no receipt)'
    try:
        doc=read_json(p);_validate(root,doc)
    except (GateError,ValueError,OSError):return 'NOT_EXECUTED (trial mechanism: invalid receipt)'
    policies=[x.get('policy') for x in doc.get('decisions') or [] if isinstance(x,dict)]
    if len(policies)!=len(set(policies)):return 'NOT_EXECUTED (trial mechanism: invalid receipt)'   # S1-01: one decision per policy, as the schema
    if doc['tooling_identity']!=tooling or doc['source_identity']!=identity:return 'NOT_EXECUTED (trial mechanism: receipt for another source)'
    if doc['status']=='PASSED':
        names=run_policies(root,identity,doc['run_id'])
        if names is None:return NO_RUN
        if len(policies)!=len(names) or set(policies)!=set(names):return OTHER_POLICIES
    return doc['status']

def performance_details(root,identity):
    """Reported next to the axes, never an axis: the handoff trial (Task 33 reads its receipt) and the owner-policy unit verdicts.
    The tooling identity is computed only when a receipt exists, as for the live-agent trial (developer_acceptance.readiness):
    a root without a receipt needs none of its input files."""
    from developer_acceptance import tooling_identity
    tooling=tooling_identity(Path(root)) if (Path(root)/HANDOFF_RECEIPT).is_file() else None
    return {'handoff_trial':handoff_trial_axis(root,identity,tooling),'unit_verdicts':unit_verdicts(root,identity)}

def report_line(report):
    """The bootstrap report line after the developer tooling section; a missing gate is NOT_EXECUTED."""
    def status(name):
        gate=_gate(report,name)
        return gate['status'] if gate and isinstance(gate.get('status'),str) else 'NOT_EXECUTED'
    return (f"Performance laboratory: bench-doctor {status('bench-doctor')}, bench-selftest {status('bench-selftest')}. Decisions are review "
            "recommendations; readiness keeps actual_django_workload_tested, native_adoption_authorized and production_authorized false.")
