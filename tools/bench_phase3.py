"""Phase 3 bench selftest cases (owner brief sections 15 and 16; spec Amendment H1; Task 29): the suites B12, B14, B15 and
B18 and the P10 (bench-stale-or-rewritten-evidence) and P15 (bench-policy-or-runtime-downgrade) subcases. B17 is Task 30.

`phase3_cases(root, run_dir, smoke_dir)` runs from bench.selftest_cases (one hook line) on the real bench-control-spin smoke
run of that selftest (`smoke_dir`). `host_additions(root)` gives the P10 and P15 variants that need no container
(HOST_VARIANTS); `rewritten-raw-samples` mutates a scratch copy of the real smoke run. Every addition has its unmutated
control: the same check must pass on the unmutated input, so a broken check or a broken control never gives PASS
(bench._sub). A check that raises gives FAIL with the exception type, never PASS or BLOCKED.

Framework code: it names no example. The example project is found by layout (bench.example_projects); mutated inputs
live in temporary directories or in memory, never in the tree. The host variants run each enforcement function that the
real command calls (decide: bench_evidence.stale, policy_runtime_problems, check_integrity; run --plan:
bench.verify_written_plan; validate and run: bm.dropped_before_run_checks through bench.refuse_dropped_checks; plan: bench_plan.build_plan; launch: container_policy.make_plan; package:
bench_b18.runtime_bench_files and runtime.inventory_gate; decision record: schemas/bench-decision.json; unit-threshold
policy: schemas/bench-protocol.json and the protocol digest binding (FR3); unit verdicts: bench_units.decide_unit)."""
import copy, json, shutil, tempfile
from pathlib import Path
from evidence import GateError, file_hash, loads_capped, read_json
import bench_model as bm

NAMES={'P10':'bench-stale-or-rewritten-evidence','P15':'bench-policy-or-runtime-downgrade'}
P10_VARIANTS=('reused-source-report','reused-runner-report','reused-dataset-report','reused-scope-report','rewritten-raw-samples',
              'post-hoc-policy-change','parent-results-in-child')
P15_VARIANTS=('lowered-threshold','removed-safety-check','exceeded-resource-budget','shipped-bench-assets','recommendation-deploys',
              'owner-threshold-altered','verdict-from-cold-row')
ALL_VARIANTS=[('P10',v) for v in P10_VARIANTS]+[('P15',v) for v in P15_VARIANTS]
REAL_VARIANTS=(('P10','rewritten-raw-samples'),)                 # needs the real smoke run of the selftest
HOST_VARIANTS=[x for x in ALL_VARIANTS if x not in REAL_VARIANTS]

CONTROL_CASE='bench-control-spin';SEED=20261007;RUN_ID='0'*31+'1'
ENV={'cpus':4,'cpuset':[0,1,2,3],'smt_siblings':[],'reduced':False,'multicore':'PASS'}    # a synthetic permitted envelope (host checks)
MINI_FILES=('safety/performance-policy.json','safety/container-policy.json','developer.lock.json','schemas/bench-policy.json')
P15_FIXTURES='tests/unit/fixtures/p15'
DEPLOY_WORDS=('deploy','adopt','rollout','release','apply','install','promote')
RECORD_RESAMPLES=200          # recommendation-deploys builds one record for its schema check only; no number of it is asserted

# B14 unit cases (G12 B14, I12, I15.4): the qualification truth-table rows that safety/performance-fixtures.json unit_cases
# name, each as (project exit, project report, ci evidence, approval) of tests/unit/test_bench_qualification.py, produced by
# the real chain (bench_units.project_check_from_report, load_local_evidence, qualify) in a temporary root.
QUALIFICATION_ROWS={'Q01':(None,'missing','absent','absent'),'Q06':(0,'present','absent','absent'),'Q07':(1,'present','absent','absent'),
                    'Q08':(2,'present','absent','absent'),'Q10':(3,'present','absent','absent'),'Q16':(3,'present','identity-mismatch','absent'),
                    'Q19':(3,'present','valid','mismatch'),'Q20':(3,'present','valid','valid')}
IDENTITY_I='a'*64;IDENTITY_J='f'*64;CI_RUN='c'*32;VERDICT='artifacts/approvals/t/verdict.md'
CELLS=('g1-pos-near','g0-mid-near','g1-neg-near','g1-pos-far','g0-mid-far','g1-neg-far')     # FR5: the synthetic cell names of the fixture project's cell rule
SAFE_LABEL='separate process; copied, bounded, validated frames over pipes (safest)'     # Amendment F item 10 (stdio), verbatim

PROPERTY={'B12':'plan-time guardrails reject or block hidden one-CPU availability, oversubscription, an unbounded queue, changed nested '
                'threads and a missing aggregate limit; the real control runs on the permitted envelope; no multicore is BLOCKED',
          'B14':'synthetic policies and data give every section 10 outcome; a kernel-only C win changes nothing; a missing objective or '
                'approval never authorizes migration; every owner-policy unit case gives its verdict',
          'B15':'the real smoke run is traceable (accounting PASS, integrity clean, digests bound); inflated, foreign, edited, missing, '
                'forged, duplicated and miscounted evidence and a wrong cgroup identity are rejected',
          'B18':'bench_b18.static_checks: payload, scaffolding, replay, docs, concurrency policy, metric profiles, runtime exclusion; '
                'the child checks run in the starter gate (starter-maintenance mode) and Task 40 reads them'}

def _sub(parent,variant,rejected,control,evidence,reason):
    import bench
    return bench._sub(parent,NAMES[parent],variant,bool(rejected),bool(control),list(evidence),reason)

def _row(parent,variant,fn,reason,evidence=()):
    """One addition: fn() -> (rejected, control). An exception is FAIL with its type, never PASS or BLOCKED."""
    try:rejected,control=fn()
    except Exception as exc:          # the check could not prove its property
        return _sub(parent,variant,False,False,evidence,f'{reason}; the check raised {type(exc).__name__}: {str(exc)[:160]}')
    return _sub(parent,variant,rejected,control,evidence,reason)

def _refused(fn,*args,**kw):
    """True when fn raises GateError (a refusal); any other exception propagates (FAIL in _row)."""
    try:fn(*args,**kw)
    except GateError:return True
    return False

def _status(values):
    import bench
    return bench.selftest_status(['PASS' if v is True else 'FAIL' if v is False else v for v in values])

def _validator(root,kind):
    import jsonschema
    return jsonschema.Draft202012Validator(read_json(Path(root)/'schemas'/f'{kind}.json'))   # the validator of schema_check.validate

def protected_entry(root,rel):
    """The safety/protected-paths.json entry that protects `rel` (an exact path or a directory prefix), or None. FR3: a
    `project_protected` entry protects that path inside a project directory: the root (a project instance) or any
    directory whose benchmarks/project/bench.json exists (an example project)."""
    doc=read_json(Path(root)/'safety/protected-paths.json');paths=doc['paths']
    hit=next((p for p in paths if rel==p or (p.endswith('/') and rel.startswith(p))),None)
    if hit is not None:return hit
    for p in doc.get('project_protected',[]):
        head,sep,_=rel.partition('/'+p) if not rel.startswith(p) else ('',p,'')
        if sep and (head=='' or (Path(root)/head/bm.PROJECT_AREA/'bench.json').is_file()):return p
    return None

def _mini_root(root,dest):
    """A temporary root with byte copies of the files the decide policy and runner checks read."""
    dest=Path(dest)
    for rel in MINI_FILES:(dest/rel).parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(Path(root)/rel,dest/rel)
    return dest

def _edit_policy(mini,edit):
    p=Path(mini)/'safety/performance-policy.json';value=json.loads(p.read_text());edit(value);p.write_text(json.dumps(value,indent=1))

def _recorded(mini):
    """The policy, image and bench-profile identities that bench run records for a run made on `mini`."""
    import bench_evidence as be
    return {'policy_sha256':file_hash(Path(mini)/'safety/performance-policy.json'),'image_id':read_json(Path(mini)/'developer.lock.json')['image_id'],
            'bench_profile_sha256':be.bench_profile_sha256(mini)}

_DECISION_CASES={}
def _decision_cases(root):
    """bm.load_fixtures(root)['decision_cases'] (schema-validated), read once per file state (path, mtime, size): the
    fixture file is about 1 MB and several host variants read it."""
    p=Path(root)/'safety/performance-fixtures.json';st=p.stat();key=(str(p.resolve()),st.st_mtime_ns,st.st_size)
    if key not in _DECISION_CASES:_DECISION_CASES.clear();_DECISION_CASES[key]=bm.load_fixtures(root)['decision_cases']
    return copy.deepcopy(_DECISION_CASES[key])

def _post_hoc(problems):return any(p.startswith('post-hoc-policy-change') for p in problems)

def _integrity_input(policy):
    """A minimal recorded run that bench_evidence.check_integrity accepts: one planned caller trial and its observation."""
    plan={'sessions':[{'trials':[{'trial_id':'p10-b00-00','block':0,'scope':'caller','point':'p10','tier':'tiny','warmup':False}]}],'memory':[],
          'pyperf':{'values':1,'warmups':0},'dataset':{'kind':'synthetic','size':'small','seed':SEED,'sha256':None,'rows':None}}
    run={'run_id':RUN_ID,'dataset':{'kind':'synthetic','size':'small','seed':SEED,'sha256':'0'*64,'rows':policy['sizes']['small']}}
    obs=[{'trial_id':'p10-b00-00','run_id':RUN_ID,'scope':'caller','point':'p10','warmup':False,'eligible':True,'work_units':policy['sizes']['tiny'],
          'wall_ns':1000000,'pyperf_wall_ns':None}]
    return plan,run,obs

# ---- P10 host variants ----

def _reused_source_report(root,t):
    import bench_evidence as be
    from policy import source_identity
    a=_mini_root(root,t/'source-a');b=_mini_root(root,t/'source-b');(b/'tools').mkdir();(b/'tools/other_source.py').write_text('x = 1\n')
    ia,ib=source_identity(a)[0],source_identity(b)[0]
    return be.stale({'source_identity':ib},ia),ia!=ib and not be.stale({'source_identity':ia},ia)

def _reused_runner_report(root,t):
    import bench_evidence as be
    m=_mini_root(root,t/'runner');ok=_recorded(m)
    image=be.policy_runtime_problems(m,dict(ok,image_id='sha256:'+'0'*64));profile=be.policy_runtime_problems(m,dict(ok,bench_profile_sha256='0'*64))
    rejected=any(p.startswith('reused-runner-report: image') for p in image) and 'reused-runner-report: bench profile digest differs' in profile
    return rejected,be.policy_runtime_problems(m,ok)==[]

def _integrity_variant(root,policy,mutate,want):
    import bench_evidence as be
    plan,run,obs=_integrity_input(policy);control=be.check_integrity(plan,run,obs,policy)==[]
    mutate(plan,run,obs)
    return any(p.startswith(want) for p in be.check_integrity(plan,run,obs,policy)),control

def _post_hoc_policy_change(root,t):
    import bench_evidence as be
    m=_mini_root(root,t/'policy');ok=_recorded(m);control=be.policy_runtime_problems(m,ok)==[]
    _edit_policy(m,lambda v:v['statistics'].update(interval=0.9))           # a post-hoc change of the statistics policy
    return _post_hoc(be.policy_runtime_problems(m,ok)),control

def _parent_results_in_child(root,t):
    import bench_b18
    parent,child='b'*64,'c'*64
    def instance(name,identity):
        d=t/name/'artifacts/bench'/RUN_ID;d.mkdir(parents=True);(d/'run.json').write_text(json.dumps({'run_id':RUN_ID,'source_identity':identity}));return t/name
    return bench_b18.copied_parent_runs(parent,instance('copied',parent))==[bench_b18.COPIED],bench_b18.copied_parent_runs(parent,instance('own',child))==[]

# ---- P15 host variants ----

def _lowered_threshold(root,t):
    import bench_evidence as be
    m=_mini_root(root,t/'threshold');ok=_recorded(m)
    control=be.policy_runtime_problems(m,ok)==[] and protected_entry(root,'docs/performance-laboratory.md') is None
    def lower(v):
        for name in ('demo-latency-2x','demo-cpu-40'):pol=v['decision_policies'][name];pol['relative_threshold']=round(pol['relative_threshold']/2,6)
    _edit_policy(m,lower)
    return _post_hoc(be.policy_runtime_problems(m,ok)) and protected_entry(root,'safety/performance-policy.json') is not None,control

def _declared(root,t,decl):
    """bm.project_bench of a temporary project 'probe' whose bench.json is `decl` (one empty manifest per declared case):
    the validated declaration that bench validate and bench run read."""
    base=t/'project-root'
    if not (base/'schemas/bench-project.json').is_file():
        (base/'schemas').mkdir(parents=True);shutil.copyfile(Path(root)/'schemas/bench-project.json',base/'schemas/bench-project.json')
    area=base/'probe'/bm.PROJECT_AREA;shutil.rmtree(area,ignore_errors=True);(area/'cases').mkdir(parents=True)
    decl={k:v for k,v in decl.items() if k!='protocol'}       # FR3: the probe has no protocol file; the required checks come from the caller's policy
    for c in decl['cases']:(area/'cases'/f'{c}.json').write_text('{}\n')
    (area/'bench.json').write_text(json.dumps(decl));return bm.project_bench(base,'probe')

def _without(decl,name):return dict(copy.deepcopy(decl),checks=[c for c in decl['checks'] if c['name']!=name])

def _switched_off(decl,name):
    d=copy.deepcopy(decl)
    for c in d['checks']:
        if c['name']==name:c['before_run']=False
    return d

def _removed_safety_check(root,t):
    """T29-APP-01: bench validate and bench run (bench.refuse_dropped_checks -> bm.dropped_before_run_checks on the
    validated bench.json) refuse a case whose declaration drops or switches off a before_run check that the key
    before_run_required of the project's protected protocol file names (FR3): a probe case in a policy copy, and the real
    entry of every example project case (each required check dropped, its agreement check switched off). run --plan (bench.verify_written_plan) refuses a
    written plan in the selftest mode, the mode that runs no before-run check. Controls: the unmutated declarations give no
    reason; the unmutated written plan is accepted."""
    import bench, bench_plan as bp
    policy=bm.load_policy(root);reasons=bm.dropped_before_run_checks
    probe={'schema_version':1,'name':'probe','cases':['probe-case'],'checks':[{'name':'probe-agreement','module':'probeadapter.checks','before_run':True}]}
    pol=copy.deepcopy(policy);pol['before_run_required']={'probe-case':['probe-agreement']}
    control=reasons(pol,'probe-case',_declared(root,t,probe))==[]
    named=lambda n,got:any(f'check {n};' in r for r in got)
    rejected=all(named('probe-agreement',reasons(pol,'probe-case',_declared(root,t,d))) for d in (_without(probe,'probe-agreement'),_switched_off(probe,'probe-agreement')))
    for project in bench.example_projects(root):
        decl=bm.project_bench(root,project);ppol=bm.load_policy(root,project)     # FR3: the entries come from the project's protocol
        for case_id in decl['cases']:
            required=ppol['before_run_required'].get(case_id,[])
            if not required:continue
            control=control and reasons(ppol,case_id,_declared(root,t,decl))==[]
            rejected=rejected and all(named(n,reasons(ppol,case_id,_declared(root,t,_without(decl,n)))) for n in required)
            agreement=[n for n in required if 'agreement' in n]
            rejected=rejected and bool(agreement) and all(named(n,reasons(ppol,case_id,_declared(root,t,_switched_off(decl,n)))) for n in agreement)
    case=bm.load_case(root,CONTROL_CASE)
    plan=bp.build_plan(case,policy,mode='smoke',dataset=bp.parse_dataset(root,'synthetic:small',policy),seed=SEED,envelope=ENV)
    plan['plan_id']=bench.plan_digest(plan);plan['project_dir']=None
    control=control and not _refused(bench.verify_written_plan,case,policy,plan,ENV,None,None)
    stub=copy.deepcopy(plan);stub['mode']='selftest';stub['plan_id']=bench.plan_digest(stub)
    return rejected and _refused(bench.verify_written_plan,case,policy,stub,ENV,None,None),control

def _exceeded_resource_budget(root,t):
    """Refused before launch: a decision plan above the 8 h decision cap, a block above the 10,800 s session cap (both
    bench_plan.build_plan; the plan grows through a larger per-trial overhead), and an envelope above the container
    policy (container_policy.make_plan). Control: the unmutated decision plan is within the cap; the policy envelope is
    accepted. The owner-policy window caps (budgets.owner_policy_decision_cap_seconds) come with Task A8."""
    import bench_plan as bp, container_policy as cpol
    policy=bm.load_policy(root);case=bm.load_case(root,CONTROL_CASE);ds=bp.parse_dataset(root,'synthetic:small',policy)
    # the control case without its capacity block: a larger per-trial overhead would first hit the 120 s capacity-trial
    # bound (bench_capacity), a different refusal; the timing sessions alone must exceed the caps here
    case={k:v for k,v in case.items() if k!='capacity'};case['scopes']=[s for s in case['scopes'] if s!='capacity']
    build=lambda pol:bp.build_plan(case,pol,mode='decision',dataset=ds,seed=SEED,envelope=ENV)
    plan=build(policy);control=plan['estimate_seconds']<=policy['budgets']['decision_cap_seconds']
    first=plan['sessions'][0]['trials'];block=[x for x in first if not x['warmup'] and x['block']==first[-1]['block']];n=max(1,len(block))
    def refusal(overhead):
        pol=copy.deepcopy(policy);pol['budgets']['trial_overhead_seconds']=overhead
        try:build(pol)
        except GateError as exc:return str(exc)
        return ''
    cap='8 h decision cap' in refusal(2800.0/n)         # one block about 2,800 s: whole blocks fit a session, the plan exceeds 28,800 s
    session='session cap' in refusal(11000.0/n)         # one block above the 10,800 s session cap
    value=read_json(Path(root)/'safety/container-policy.json');image=read_json(Path(root)/'developer.lock.json')['image_id'];cpus=value['profiles']['bench']['cpus']
    src=t/'src';src.mkdir()
    env=lambda k:{'cpus':k,'cpuset':list(range(k)),'smt_siblings':[],'reduced':False,'multicore':'PASS'}
    wide=_refused(cpol.make_plan,value,image,{'/src':src},'bench',envelope=env(cpus+1))
    control=control and not _refused(cpol.make_plan,value,image,{'/src':src},'bench',envelope=env(cpus))
    return cap and session and wide,control

def _shipped_bench_assets(root,t):
    import bench_b18, runtime
    fx=Path(root)/P15_FIXTURES;image=read_json(fx/'runtime-image-inventory.json')['members'];export=read_json(fx/'default-export.json')['files']
    found=bench_b18.runtime_bench_files(root,inventories={'runtime-image':image,'project-run':export})
    rejected=_refused(runtime.inventory_gate,image,image) and any(p.startswith('runtime-image: ') for p in found) and any(p.startswith('project-run: ') for p in found)
    members=sorted(runtime.runtime_members())
    return rejected,bench_b18.runtime_bench_files(root)==[] and not _refused(runtime.inventory_gate,members,members)

def _recommendation_deploys(root,t):
    """A decision record (bench_decide.decision_record) validates; with adoption_authorized true or any deploy field the
    closed schema rejects it; bench registers no command that acts on a recommendation."""
    import bench, bench_decide as bd
    from policy import source_identity
    m=_mini_root(root,t/'record');fix=_decision_cases(root)
    c=copy.deepcopy(next(x for x in fix['cases'] if x['expect']['outcome']=='INVALID_EXPERIMENT'))
    stats=dict(bd.stats_of(bm.load_policy(root)),resamples=RECORD_RESAMPLES);ev=bd.synthetic_evidence(c)
    result=bd.decide(ev,dict(fix['policy']),c['opportunity'],stats)
    run={'run_id':RUN_ID,'case':CONTROL_CASE,'mode':'smoke','source_identity':source_identity(m)[0],'image_id':read_json(m/'developer.lock.json')['image_id'],
         'dataset':{'kind':'synthetic'}}
    rec=bd.decision_record(m,run,{},bm.load_case(root,CONTROL_CASE),'demo-latency-2x',result,ev,c['opportunity'],stats=stats)
    v=_validator(root,'bench-decision');control=v.is_valid(rec) and rec['adoption_authorized'] is False
    deploy=[dict(rec,adoption_authorized=True)]+[dict(rec,**{k:x}) for k,x in (('deploy',{'target':'production'}),('deployment',True),('rollout','now'))]
    return not any(v.is_valid(r) for r in deploy) and not any(w in bench.HANDLERS for w in DEPLOY_WORDS),control

PROBE_POLICY='probe-threshold'

def _probe_protocol(root):
    """A probe project protocol holding the engine test unit-threshold policy (decision_cases.unit_policy) as a project policy."""
    base={k:v for k,v in bm.engine_unit_policy(root).items() if k not in ('name','library_report','origin','sha256')}
    return {'schema_version':1,'cases':['probe-case'],'approval':{'state':'APPROVED','reference':'probe-protocol-approval'},
            'decision_policies':{PROBE_POLICY:dict(base,case='probe-case')}}

def _write_probe_project(root,m,proto,approve=True):
    """The probe project of the temporary root `m` with `proto` as its bound protocol file (bench.json holds its sha256).
    FR3-04: for an APPROVED protocol, `approve` also writes the approval record of the new digest (the approver's record);
    approve=False leaves the earlier record in place."""
    import hashlib
    for rel in ('schemas/bench-project.json','schemas/bench-protocol.json','schemas/bench-protocol-approval.json'):
        if not (Path(m)/rel).is_file():shutil.copyfile(Path(root)/rel,Path(m)/rel)
    area=Path(m)/'probe'/bm.PROJECT_AREA;(area/'cases').mkdir(parents=True,exist_ok=True);(area/'protocol').mkdir(exist_ok=True)
    (area/'cases/probe-case.json').write_text('{}\n');data=json.dumps(proto).encode();(area/bm.PROTOCOL_FILE).write_bytes(data)
    digest=hashlib.sha256(data).hexdigest()
    (area/'bench.json').write_text(json.dumps({'schema_version':1,'name':'probe','cases':['probe-case'],
                                               'protocol':{'file':bm.PROTOCOL_FILE,'sha256':digest}}))
    if approve and proto['approval']['state']=='APPROVED':
        (area/bm.PROTOCOL_APPROVAL_FILE).write_text(json.dumps({'schema_version':1,'protocol_sha256':digest,'reference':proto['approval']['reference'],
                                                                 'verdict':'APPROVE','approver':'fresh-context-agent'}))

def _owner_threshold_altered(root,t):
    """FR3: a unit-threshold policy is project data in the digest-bound protocol file. (a) schemas/bench-protocol.json rejects
    altered statistical constants, a malformed unit list and an unknown key; (b) a threshold or unit edit of a bound
    protocol is refused (bench_model: edited digest), and a rebind of bench.json without a new approval record is refused
    (FR3-04: the record names the old digest); (c) after a reviewed rebind with the approver's record, decide refuses the run
    (post-hoc-protocol-change). Controls: the unmutated probe protocol validates, loads with its policy, and the run that
    recorded its digest passes the policy and runtime check."""
    import bench_evidence as be
    v=_validator(root,'bench-protocol');proto=_probe_protocol(root)
    def mutated(edit):p=copy.deepcopy(proto);edit(p['decision_policies'][PROBE_POLICY]);return p
    edits=(lambda o:o.update(alpha_one_sided=[0.05,o['alpha_one_sided'][1]]),lambda o:o.update(multiplicity='none'),
           lambda o:o.update(interval_method='bootstrap'),lambda o:o.update(units=[]),lambda o:o.update(score=1),
           lambda o:o.update(threshold_ns_per_request=0))
    schema=all(not v.is_valid(mutated(e)) for e in edits)
    m=_mini_root(root,t/'owner');_write_probe_project(root,m,proto)
    ok=dict(_recorded(m),plan={'project_dir':'probe'},protocol_sha256=bm.protocol_digest(m,'probe'))
    pol=bm.load_decision_policy(m,PROBE_POLICY,'probe')
    control=(v.is_valid(proto) and pol['threshold_ns_per_request']==proto['decision_policies'][PROBE_POLICY]['threshold_ns_per_request']
             and be.policy_runtime_problems(m,ok)==[])
    area=Path(m)/'probe'/bm.PROJECT_AREA;edited=[]
    for edit in (lambda o:o.update(threshold_ns_per_request=o['threshold_ns_per_request']-1),lambda o:o.update(units=o['units'][:8])):
        (area/bm.PROTOCOL_FILE).write_text(json.dumps(mutated(edit)))           # the file changes, bench.json still binds the old digest
        edited.append(_refused(bm.load_protocol,m,'probe'))
    lowered=mutated(lambda o:o.update(threshold_ns_per_request=o['threshold_ns_per_request']-1))
    _write_probe_project(root,m,lowered,approve=False)                         # FR3-04: a rebind without a new approval record
    edited.append(_refused(bm.load_protocol,m,'probe'))
    _write_probe_project(root,m,lowered)                                        # reviewed rebind with the approver's record
    return schema and all(edited) and _post_hoc_protocol(be.policy_runtime_problems(m,ok)),control

def _post_hoc_protocol(problems):return any(p.startswith('post-hoc-protocol-change') for p in problems)

def _verdict_from_cold_row(root,t):
    """A unit_cases case decided PREFER_C by its warm C row gives no PREFER_C when that C row is cold (G7.4: cold values are
    reported, never the verdict basis); the fixture case order-8-cold-row-never-decides gives its expected verdict."""
    import bench_units as bu
    cases=_decision_cases(root)['unit_cases'];pol=bm.engine_unit_policy(root);cache={}
    c=next(x for x in cases if x['expect']['verdict']=='PREFER_C' and x['expect']['verdict_safe_route']=='PREFER_C')
    decide=lambda case:bu.decide_unit(case['unit'],unit_case_evidence(root,case,cache),_unit_policy(pol,case),None)
    control=decide(c)['verdict']=='PREFER_C'
    cold=copy.deepcopy(c)
    for r in cold['rows']:
        if r['language']=='c':r['mode']='cold'
    got=decide(cold);named=[x for x in cases if x['name']=='order-8-cold-row-never-decides']
    fixture=bool(named) and decide(named[0])['verdict']==named[0]['expect']['verdict']!='PREFER_C'
    return got['verdict']!='PREFER_C' and got['verdict_safe_route']!='PREFER_C' and fixture,control

HOST_CHECKS={('P10','reused-source-report'):(_reused_source_report,'decide refuses another source identity (bench_evidence.stale)'),
             ('P10','reused-runner-report'):(_reused_runner_report,'decide refuses another image or bench profile (policy_runtime_problems)'),
             ('P10','post-hoc-policy-change'):(_post_hoc_policy_change,'decide refuses a policy digest that differs from the run'),
             ('P10','parent-results-in-child'):(_parent_results_in_child,'a parent run in a child instance is refused (bench_b18.copied_parent_runs)'),
             ('P15','lowered-threshold'):(_lowered_threshold,'a lowered demonstration threshold changes the policy digest (decide FAILS); the file is protected'),
             ('P15','removed-safety-check'):(_removed_safety_check,'bench validate and bench run refuse a bench.json that drops or switches off a before_run check the protected project protocol requires; run --plan refuses a plan without the before-run checks'),
             ('P15','exceeded-resource-budget'):(_exceeded_resource_budget,'plans above the decision or session cap and an envelope above the policy are refused before launch'),
             ('P15','shipped-bench-assets'):(_shipped_bench_assets,'a bench driver in the runtime image or the default export is rejected'),
             ('P15','recommendation-deploys'):(_recommendation_deploys,'the decision schema rejects adoption_authorized true and deploy fields; no command deploys'),
             ('P15','owner-threshold-altered'):(_owner_threshold_altered,'schemas/bench-protocol.json rejects altered unit-threshold constants; an edited bound protocol is refused; decide refuses a changed protocol digest'),
             ('P15','verdict-from-cold-row'):(_verdict_from_cold_row,'a cold C row never gives PREFER_C')}
INTEGRITY={'reused-dataset-report':(lambda p,r,o:r['dataset'].update(seed=SEED+1),'dataset mismatch','decide refuses another dataset identity (check_integrity)'),
           'reused-scope-report':(lambda p,r,o:o[0].update(scope='kernel'),'scope mismatch','decide refuses rows of another scope (check_integrity)')}

def host_additions(root):
    """The P10 and P15 variants that need no container (HOST_VARIANTS), one row each with its control."""
    root=Path(root);rows=[];policy=bm.load_policy(root)
    with tempfile.TemporaryDirectory(prefix='safe-c-p3-') as tmp:
        for k,(parent,variant) in enumerate(HOST_VARIANTS):
            t=Path(tmp)/f'v{k:02d}';t.mkdir()
            if variant in INTEGRITY:
                mutate,want,reason=INTEGRITY[variant]
                rows.append(_row(parent,variant,lambda:_integrity_variant(root,policy,mutate,want),reason))
            else:
                fn,reason=HOST_CHECKS[(parent,variant)]
                rows.append(_row(parent,variant,lambda:fn(root,t),reason,[str(root/P15_FIXTURES)] if variant=='shipped-bench-assets' else []))
    return rows

# ---- the real smoke run: P10 rewritten-raw-samples, B12, B15 ----

def _raw_sample(run):
    """The first recorded per-session raw sample file of a run (<session>/observations.jsonl), else observations.jsonl."""
    names=sorted((run.get('evidence_digests') or {}))
    return next((n for n in names if n.count('/')==1 and n.endswith('/observations.jsonl')),'observations.jsonl' if 'observations.jsonl' in names else None)

def _rewrite(path):
    """Change the first observation of a JSONL file (wall_ns + 1); a file without one gets one appended byte."""
    lines=path.read_text().splitlines(True)
    try:
        row=loads_capped(lines[0],'container-jsonl');row['wall_ns']=int(row.get('wall_ns') or 0)+1;lines[0]=json.dumps(row,sort_keys=True)+'\n'
    except (IndexError,ValueError,TypeError):lines.append(' ')
    path.write_text(''.join(lines))

def rewritten_raw_samples(root,smoke_dir):
    """P10 rewritten-raw-samples: a raw sample file rewritten in a scratch copy of the real smoke run fails
    bench_evidence.verify (its digest); control: the recorded run verifies."""
    import bench_evidence as be
    if smoke_dir is None:return _sub('P10','rewritten-raw-samples',False,False,[],'no smoke run evidence')
    smoke_dir=Path(smoke_dir)
    def check():
        run=read_json(smoke_dir/'run.json');rel=_raw_sample(run)
        control=rel is not None and be.verify_record(run)==[] and be.verify(smoke_dir,run)==[]
        if rel is None:return False,False
        with tempfile.TemporaryDirectory(prefix='safe-c-p10-') as t:
            copy_dir=Path(t)/'run';shutil.copytree(smoke_dir,copy_dir,symlinks=True);_rewrite(copy_dir/rel)
            return 'changed after the run: '+rel in be.verify(copy_dir,run),control
    return _row('P10','rewritten-raw-samples',check,'a rewritten raw sample fails its evidence digest (bench_evidence.verify)',[str(smoke_dir/'run.json')])

def _guard(plan,policy,envelope,cp,doctor):
    import bench_guardrails as bg
    g=bg.check(plan,policy,envelope,cp,doctor);return g,bg.blocks_run(bg.affected(plan,policy,envelope,cp,doctor))

def b12_suite(root,run_dir,smoke_dir):
    """B12 on the real smoke plan, its envelope and a fresh doctor row: the real run is VALID with clean guardrails; each
    mutated plan, policy or doctor row is rejected (GATED) or blocks the run before any trial; a missing multicore envelope
    and a capacity configuration above the envelope are BLOCKED, never PASS."""
    out={'status':'FAIL','property':PROPERTY['B12'],'checks':{}}
    if smoke_dir is None:return dict(out,reason='no smoke run evidence')
    import bench, bench_guardrails as bg
    smoke_dir=Path(smoke_dir);checks=out['checks']
    try:
        root=Path(root);plan=read_json(smoke_dir/'plan.json');run=read_json(smoke_dir/'run.json');policy=bm.load_policy(root)
        cp=read_json(root/'safety/container-policy.json');env=plan['envelope']
        guard=read_json(smoke_dir/'guardrails.json') if (smoke_dir/'guardrails.json').is_file() else None
        checks['real-run-valid']=run.get('status')=='VALID' and isinstance(guard,dict) and not guard.get('rejected') and not guard.get('blocked')
        probe=bench.doctor_probe(root,Path(run_dir)/'b12-doctor');out['evidence_paths']=list(probe.get('evidence_paths',[]))+[str(smoke_dir/'plan.json')]
        if probe.get('status')!='PASS':
            out.update(status=_status(list(checks.values())+['BLOCKED']),reason='bench doctor: '+str(probe.get('status')));return out
        g,b=_guard(plan,policy,env,cp,probe);checks['control-permitted-envelope']=not g['rejected'] and not b
        def rejected(text,plan_=plan,policy_=policy,cp_=cp,doctor=probe):return any(text in r for r in _guard(plan_,policy_,env,cp_,doctor)[0]['rejected'])
        def blocked(text,plan_=plan,env_=env,doctor=probe):
            g_,b_=_guard(plan_,policy,env_,cp,doctor);return b_ and any(text in r for r in g_['blocked'])
        checks['hidden-one-cpu']=blocked('hidden CPU limit',doctor=dict(probe,cpu_max='100000 100000'))
        p=copy.deepcopy(plan);t0=next(t for t in bg.planned_trials(p));t0['workers']=env['cpus']*2;checks['oversubscribed-workers']=rejected('oversubscribed',plan_=p)
        pol=copy.deepcopy(policy);pol['pools']['window_per_worker']=0;checks['unbounded-queue']=rejected('unbounded queue',policy_=pol)
        p=copy.deepcopy(plan);p['fixed_environment']=dict(policy['envelope']['thread_environment'],OPENBLAS_NUM_THREADS='4')
        checks['changed-nested-threads']=rejected('nested-library threads changed',plan_=p)
        c2=copy.deepcopy(cp);c2.setdefault('aggregate',{}).pop('max_active',None);checks['missing-aggregate-limit']=rejected('missing aggregate limit',cp_=c2)
        checks['no-multicore-blocked']=bool(bg.multicore_trials(plan)) and blocked('multicore capacity unavailable',env_=dict(env,multicore='BLOCKED'))
        p=copy.deepcopy(plan);caps=p.get('capacity') or []
        if caps:caps[0]['clients']=env['cpus']+1
        checks['capacity-above-envelope']=bool(caps) and blocked('clients beyond',plan_=p)
    except Exception as exc:          # the suite could not prove its property: FAIL, never PASS or BLOCKED
        return dict(out,reason=f'B12 check failed: {type(exc).__name__}: {str(exc)[:200]}')
    out.update(status=_status(checks.values()),run_id=smoke_dir.name);return out

def h7_checks(policy,a0,rows,run):
    """T29-APP-06: the H7 directions of spec H1 B15 on one recorded accounting row `a0` of the run, its session rows and
    run.json. A missing host total and a host total below the trial deltas (the coordinator window above it) give reconcile
    reasons, which make bench run INVALID_EXPERIMENT; a changed run.json record (an edited recorded host total) fails
    verify_record, which makes compare and decide FAIL. Controls: the recorded values reconcile with no reason; the
    recorded run.json verifies. A host total below the deltas that cannot be built (deltas at the resolution) is False."""
    import bench_accounting as ba, bench_evidence as be
    r=policy['accounting']['resolution_usec']
    def session(host):return {'session':a0['session'],'host_total_usec':host,'window_usec':a0['window_usec'],'rows':rows,
                              'launcher_cgroup_inode':a0.get('launcher_cgroup_inode'),'job_cgroup_inode':a0.get('job_cgroup_inode')}
    def reconciled(host,want):
        reasons,out=ba.reconcile([session(host)],policy);return any(want in x for x in reasons) and out[0]['status']=='FAIL'
    control=ba.reconcile([session(a0['host_total_usec'])],policy)[0]==[]
    total=ba.checked_total(rows);low=min(total,a0['window_usec'])-2*r-1      # window > low + 2r and low < the trial deltas
    changed=copy.deepcopy(run);changed['accounting'][0]['host_total_usec']=a0['host_total_usec']+1
    return {'missing-host-total':control and reconciled(None,'host CPU total unavailable'),
            'host-total-below-trial-deltas':control and 0<=low<total and reconciled(low,'exceeds the host total'),
            'changed-run-record':be.verify_record(run)==[] and be.verify_record(changed)==[be.RECORD_CHANGED]}

def b15_suite(root,run_dir,smoke_dir):
    """B15 on the real smoke run (brief section 15): its accounting rows PASS, check_integrity is empty and its digests
    bind; copies with an inflated trial delta, a wrong cgroup identity, a foreign run_id, an edited observation, a removed
    trial, a forged pyperf wall, a duplicated row or a wrong work count are rejected; the H7 directions (h7_checks: a
    missing host total, a host total below the trial deltas, a changed run.json record) are rejected. The stub run and check of the
    first test stub of a project protocol (Task 6; FR3) are part of B15 when a project declares one: a hang is a failed
    attempt that stays visible; without a declaration B15 records why (`stub`)."""
    out={'status':'FAIL','property':PROPERTY['B15'],'checks':{}}
    if smoke_dir is None:return dict(out,reason='no smoke run evidence')
    import bench, bench_accounting as ba, bench_evidence as be
    smoke_dir=Path(smoke_dir);checks=out['checks'];out['evidence_paths']=[str(smoke_dir/'run.json')]
    try:
        root=Path(root);policy=bm.load_policy(root);run=read_json(smoke_dir/'run.json');plan=read_json(smoke_dir/'plan.json')
        obs=bench.read_jsonl(smoke_dir/'observations.jsonl');phases=bench.read_jsonl(smoke_dir/'phases.jsonl');acc=run.get('accounting') or []
        checks['accounting-rows-pass']=bool(acc) and all(isinstance(a,dict) and a.get('status')=='PASS' for a in acc)
        checks['integrity-clean']=be.check_integrity(plan,run,obs+phases,policy)==[]
        checks['digests-bound']=be.verify_record(run)==[] and be.verify(smoke_dir,run)==[]
        first=next(i for i,o in enumerate(obs) if not o.get('warmup') and o.get('scope')=='caller' and o.get('eligible'))
        def integrity(mutate,want):
            o=copy.deepcopy(obs);mutate(o);return any(p.startswith(want) for p in be.check_integrity(plan,run,o+phases,policy))
        a0=acc[0];sess=a0['session'];rows=bench.read_jsonl(smoke_dir/sess/'observations.jsonl')+bench.read_jsonl(smoke_dir/sess/'phases.jsonl')
        r=policy['accounting']['resolution_usec']
        k=next(i for i,o in enumerate(rows) if type(o.get('cpu_usage_usec')) is int)
        inflated=copy.deepcopy(rows);inflated[k]['cpu_usage_usec']+=a0['window_usec']+len(rows)*r+1
        checks['inflated-trial-delta']=(ba.check_session(sess,a0['host_total_usec'],a0['window_usec'],rows,r)==[] and
                                        any('exceed the coordinator window' in x for x in ba.check_session(sess,a0['host_total_usec'],a0['window_usec'],inflated,r)))
        bad=copy.deepcopy(run);bad['accounting'][0]['job_cgroup_inode']=a0['job_cgroup_inode']+1
        checks['wrong-cgroup-identity']=ba.recheck(run,smoke_dir)==[] and bool(ba.recheck(bad,smoke_dir))
        checks.update(h7_checks(policy,a0,rows,run))       # T29-APP-06: the H7 directions of spec H1 B15
        checks['foreign-run-id']=integrity(lambda o:o[first].update(run_id='f'*32),'cross-run metrics')
        tid=obs[first]['trial_id']
        checks['removed-failed-trial']=integrity(lambda o:o.__setitem__(slice(None),[x for x in o if x.get('trial_id')!=tid]),'missing failed attempt: '+tid)
        checks['forged-pyperf-wall']=integrity(lambda o:o[first].update(pyperf_wall_ns=2*o[first]['wall_ns']+10**9),'forged self-timing')
        checks['duplicated-row']=integrity(lambda o:o.append(copy.deepcopy(o[first])),'duplicate rows')
        checks['wrong-work-count']=integrity(lambda o:o[first].update(work_units=o[first]['work_units']+1),'wrong work count')
        with tempfile.TemporaryDirectory(prefix='safe-c-b15-') as t:
            copy_dir=Path(t)/'run';shutil.copytree(smoke_dir,copy_dir,symlinks=True);_rewrite(copy_dir/'observations.jsonl')
            checks['edited-observation']='changed after the run: observations.jsonl' in be.verify(copy_dir,run)
    except Exception as exc:          # the suite could not prove its property: FAIL, never PASS or BLOCKED
        return dict(out,reason=f'B15 check failed: {type(exc).__name__}: {str(exc)[:200]}')
    statuses=list(checks.values())
    import bench_deadline
    try:first=bench_deadline.first_stub_selftests(root,run_dir)
    except GateError as exc:first={'reason':None,'run':{'status':'BLOCKED','reason':str(exc)[:200]},'check':{'status':'BLOCKED'}}   # never a silent pass
    except Exception:first={'reason':None,'run':{'status':'FAIL'},'check':{'status':'FAIL'}}
    if first is not None:
        out['stub']={'reason':first['reason'],'run':first['run'].get('status') or 'FAIL','check':first['check'].get('status') or 'FAIL'}
        statuses+=[out['stub']['run'],out['stub']['check']]
    else:out['stub']=bench_deadline.NOT_DECLARED
    out.update(status=_status(statuses),run_id=smoke_dir.name);return out

# ---- B14 (host; the engine's bootstraps run here, never in the unit gate) ----

QUALIFICATION_PROJECT='examples/demo-project'    # FR1 (FS1 F2): a synthetic project directory string; B14 writes it only into its temporary reports

def qualification_check(root,row_id,cache=None):
    """The project_check of a truth-table row (QUALIFICATION_ROWS; KeyError for another row), from the real chain. The
    project directory is QUALIFICATION_PROJECT: the chain compares it with the report's project_dir and reads no project
    tree, so B14 needs no example project (FR1, FS1 F2)."""
    import bench_units as bu
    if cache is not None and row_id in cache:return copy.deepcopy(cache[row_id])
    exit_code,report,ci,approval=QUALIFICATION_ROWS[row_id];root=Path(root)
    gates=read_json(root/'safety/contract.json')['required_gates'];project=QUALIFICATION_PROJECT
    with tempfile.TemporaryDirectory(prefix='safe-c-b14-') as t:
        t=Path(t);(t/'safety').mkdir(parents=True);(t/'safety/contract.json').write_text(json.dumps({'required_gates':gates}))
        if report!='missing':
            p=t/bu.PROJECT_REPORT;p.parent.mkdir(parents=True,exist_ok=True)
            p.write_text(json.dumps({'exit_code':exit_code,'source_identity':IDENTITY_I,'project_dir':project}))
        rid=None if ci=='absent' else CI_RUN
        if ci in ('valid','identity-mismatch'):
            rep={'run_id':CI_RUN,'local_state':'PASS','source_identity':IDENTITY_J if ci=='identity-mismatch' else IDENTITY_I,
                 'commands':['./tools/safety ci'],'gates':[{'name':g,'status':'PASS'} for g in gates]}
            p=t/bu.CI_REPORT.format(run_id=CI_RUN);p.parent.mkdir(parents=True);p.write_text(json.dumps(rep))
        paths=[] if approval=='absent' else [VERDICT]
        if approval in ('valid','mismatch'):
            p=t/VERDICT;p.parent.mkdir(parents=True)
            p.write_text('# Verdict\nVerdict: APPROVE\n- Reviewed identity: '+(IDENTITY_J if approval=='mismatch' else IDENTITY_I)+'\n\n## Findings\n')
        pc=bu.project_check_from_report(t,bu.PROJECT_REPORT,project)
        q=bu.qualify(pc,*bu.load_local_evidence(t,rid,paths),IDENTITY_I)[0]
    if cache is not None:cache[row_id]=copy.deepcopy(q)
    return q

def _unit_policy(policy,case):return dict(policy,primary_blocks=case['primary_blocks']) if 'primary_blocks' in case else policy

def unit_case_evidence(root,case,cache=None):
    """The unit evidence of one unit_cases row (the shape of bench_units.unit_evidence_from_run), with the project_check of
    its named qualification row (default Q06)."""
    const=lambda v,n=12:{b:float(v) for b in range(n)};rows=[];sel=case['unit'].partition('/')[0]
    for s in case['rows']:
        wall={b:float(v) for b,v in enumerate(s['wall'])} if isinstance(s['wall'],list) else const(s['wall'],s.get('blocks',12))
        r={'unit':s.get('unit',case['unit']),'mode':s.get('mode','warm'),'variant':s['variant'],'workers':s['workers'],'route':s['route'],
           'route_label':SAFE_LABEL if s['route'] else None,'language':s['language'],'eligible':s.get('eligible',True),'planned':s.get('planned',True),
           'wall':wall,'cpu':dict(wall),'peak':None,'records':{x:const(s['record_wall']) for x in CELLS} if 'record_wall' in s else None}
        if s.get('detail'):r['detail']=s['detail']
        rows.append(r)
    d={'status':'VALID','reasons':[],'rows':rows,'blocked_other':[],'envelope_not_planned':[],'looks':{},'extension_not_run':[],'window_mismatch':[],
       'reference_evals':{sel:10**6},'panel_evals':{sel:{x:100 for x in CELLS}},'project_check':qualification_check(root,case.get('qualification_row','Q06'),cache),
       'current_identity':IDENTITY_I,'opportunity_state':'APPROVED','coverage_ok':True,'reference_admit_excluded':None,'library_overhead_ns_per_row':None}
    d.update(copy.deepcopy(case.get('evidence',{})));return d

def unit_case_problems(root,cases):
    """Every unit_cases case gives its expected verdict, reason, verdict_safe_route and failed_conditions; one line per miss."""
    import bench_units as bu
    pol=bm.engine_unit_policy(root);cache={};problems=[]
    for c in cases:
        try:
            r=bu.decide_unit(c['unit'],unit_case_evidence(root,c,cache),_unit_policy(pol,c),None);e=c['expect']
            got=(r['verdict'],r['reason'],r['verdict_safe_route'],r['failed_conditions'])
            want=(e['verdict'],e['reason'],e['verdict_safe_route'],e.get('failed_conditions',[]))
            if got!=want:problems.append(f"unit case {c['name']}: got {got[:3]}, expected {want[:3]}")
        except Exception as exc:problems.append(f"unit case {c.get('name')}: {type(exc).__name__}: {str(exc)[:120]}")
    return problems

def missing_approval_holds(rp,opportunity,policies,control):
    """B14 missing-approval (ruling T29-C4; T29-APP-05 precondition): `rp` is the rule result of the case without an approved
    opportunity record under the filled test policy. It must be a decided outcome: bench_decide.adoption returns INCONCLUSIVE
    and INVALID_EXPERIMENT unchanged, so with either the check would pass without testing the approval rule; and it is never
    C_CANDIDATE_FOR_REVIEW. Then the adoption outcome is INCONCLUSIVE under each policy. `control`: the approved case under
    the filled policy adopts its rule outcome."""
    import bench_decide as bd
    return (bool(control) and rp['outcome'] not in ('INCONCLUSIVE','INVALID_EXPERIMENT','C_CANDIDATE_FOR_REVIEW')
            and all(bd.adoption(rp,p,opportunity)[0]=='INCONCLUSIVE' for p in policies))

def b14_suite(root):
    """B14 (spec section 10, H1, G12): every decision_cases case gives its expected outcome and rule, the seven outcomes are
    covered; a kernel-only C win at the decision point keeps the keep outcome and is never named; a missing objective (the
    owner template) is INCONCLUSIVE; a case without approval gives the adoption outcome INCONCLUSIVE under the filled and
    the demonstration policies (ruling T29-C4) and never C_CANDIDATE_FOR_REVIEW; under a demonstration policy no valid case
    gives an adoption outcome other than INCONCLUSIVE; every unit_cases case gives its verdict."""
    import bench_decide as bd
    out={'status':'FAIL','property':PROPERTY['B14'],'checks':{}};checks=out['checks'];problems=[]
    try:
        root=Path(root);stats=bd.stats_of(bm.load_policy(root));fix=_decision_cases(root);test_pol=fix['policy']
        case=lambda name:copy.deepcopy(next(c for c in fix['cases'] if c['name']==name))
        pol_of=lambda c:dict(test_pol,modes=c.get('policy_modes',test_pol['modes']))
        run=lambda c,pol=None:bd.decide(bd.synthetic_evidence(c),pol or pol_of(c),c['opportunity'],stats)
        seen=set();results={}
        for c in fix['cases']:
            r=run(copy.deepcopy(c));seen.add(r['outcome']);results[c['name']]=r
            if (r['outcome'],r['rule'])!=(c['expect']['outcome'],c['expect']['rule']):problems.append(f"decision case {c['name']}: {r['outcome']} rule {r['rule']}")
        checks['decision-cases']=not problems
        checks['seven-outcomes']=seen==set(bd.OUTCOMES)
        if not checks['seven-outcomes']:problems.append('outcomes not covered: '+', '.join(sorted(set(bd.OUTCOMES)-seen)))
        keep=case('keep');base=results['keep'];ev=bd.synthetic_evidence(keep);injected=[]
        for r in list(ev['rows']):
            if r['variant']=='py-reference' and r['point']=='baseline':
                k=dict(copy.deepcopy(r),scope='kernel',point='baseline',variant='c-serial',language='c',route=None)
                k['wall']={b:v/100 for b,v in k['wall'].items()};k['cpu']={b:v/100 for b,v in k['cpu'].items()};k['peak']=1;ev['rows'].append(k);injected.append(bd.label(k))
        r=bd.decide(ev,pol_of(keep),keep['opportunity'],stats)
        names={x['base'] for x in r['comparisons']}|{x['other'] for x in r['comparisons']}|{x['row'] for x in r['items']}
        checks['kernel-only-win']=bool(injected) and (r['outcome'],r['rule'])==(base['outcome'],base['rule'])==(keep['expect']['outcome'],keep['expect']['rule']) and not names&set(injected)
        cand=case('c-candidate');owner=bm.load_decision_policy(root,'owner');r=run(cand,owner)
        checks['missing-objective']=(r['outcome'],r['rule'])==('INCONCLUSIVE',2) and bd.adoption(r,owner,cand['opportunity'])[0]=='INCONCLUSIVE'
        pending=case('c-candidate');pending['opportunity']['approval']={'state':'PENDING'};rp=run(pending)
        demos=[bm.load_decision_policy(root,n) for n in ('demo-latency-2x','demo-cpu-40')]
        # spec H1 and section 10 (ruling T29-C4): a missing approval gives the adoption outcome INCONCLUSIVE under the filled
        # test policy and under each demonstration policy, never C_CANDIDATE_FOR_REVIEW; control: the approved case under the
        # filled policy adopts its rule outcome
        checks['missing-approval']=missing_approval_holds(rp,pending['opportunity'],[pol_of(pending)]+demos,
                                                          bd.adoption(results['keep'],pol_of(keep),keep['opportunity'])[0]==keep['expect']['outcome'])
        named={c['name']:c for c in fix['cases']}
        checks['demonstration-adoption']=all(bd.adoption(x,p,named[n]['opportunity'])[0]=='INCONCLUSIVE' for p in demos for n,x in results.items()
                                             if x['outcome']!='INVALID_EXPERIMENT')
        out['missing_approval_outcome']=rp['outcome']
        units=unit_case_problems(root,fix['unit_cases']);problems+=units;checks['unit-cases']=not units
    except Exception as exc:          # the suite could not prove its property: FAIL, never PASS or BLOCKED
        return dict(out,reason=f'B14 check failed: {type(exc).__name__}: {str(exc)[:200]}',problems=problems[:20])
    out.update(status=_status(checks.values()),problems=problems[:20]);return out

def b18_suite(root):
    import bench_b18
    try:r=bench_b18.static_checks(root)
    except Exception as exc:          # static_checks catches per check; anything else is FAIL, never PASS or BLOCKED
        return {'status':'FAIL','property':PROPERTY['B18'],'reason':f'B18 check failed: {type(exc).__name__}: {str(exc)[:200]}'}
    return {'status':r['status'],'property':PROPERTY['B18'],'checks':{k:v['status'] for k,v in r['checks'].items()},
            'problems':{k:v['problems'][:5] for k,v in r['checks'].items() if v['problems']},
            'child_checks':'starter-maintenance mode: starter.verify_starter runs bench_b18.child_checks after the fresh child ci (Task 40 reads them)'}

def phase3_cases(root,run_dir,smoke_dir):
    """(suites, additions) of Phase 3 for bench.selftest_cases: B12, B14, B15, B18 and every P10 and P15 variant."""
    root=Path(root);run_dir=Path(run_dir);smoke_dir=Path(smoke_dir) if smoke_dir is not None else None
    suites={'B12':b12_suite(root,run_dir,smoke_dir),'B14':b14_suite(root),'B15':b15_suite(root,run_dir,smoke_dir),'B18':b18_suite(root)}
    additions=host_additions(root)+[rewritten_raw_samples(root,smoke_dir)]
    order={x:i for i,x in enumerate(ALL_VARIANTS)};additions.sort(key=lambda a:order[(a['parent'],a['variant'])])
    return suites,additions
