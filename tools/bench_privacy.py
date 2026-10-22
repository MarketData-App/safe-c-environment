"""Owner-fixture rules for local: runs (spec 12). Never prints a path or content; evidence holds aggregates only."""
from pathlib import Path
import datetime, json, os, re, shutil, stat
from evidence import GateError, atomic_json, bounded, file_hash, load_project_json, passed, read_json
from schema_check import validate
import bench_model as bm
MIB=1048576
MAX_LOCAL_BYTES=32*MIB
AGGREGATE_LIMIT=262144
MIN_QUANTILE_ROWS=5        # controller ruling (Task 18 concern 2): fewer rows give near-individual quantiles
PROBE_VALUE='412.35'       # the private probe value the coordinator's stderr-probe job writes

def is_project_instance(root):
    """A project instance declares project.json at its root; local datasets are refused there."""
    return (Path(root)/'project.json').exists()

def refuse_local(root,what):
    """spec 12 (Task 26, B18): every local: path (a dataset, a local replay) is refused under CI and
    in project instances (starter exports and child instances). GateError('<what>s are refused ...'); None otherwise."""
    if os.environ.get('CI'):raise GateError(f'{what}s are refused under CI')
    if is_project_instance(root):raise GateError(f'{what}s are refused in project instances')

def _resolve_untracked(root,spec,what,limit):
    """The local: path rules (spec 12) of an untracked input file: refused under CI and in project
    instances; a regular file of at most `limit` bytes, git-ignored when it lies inside the work tree. Messages never hold
    the path. Returns the resolved path."""
    refuse_local(root,what)
    try:real=Path(spec).expanduser().resolve(strict=True)
    except (OSError,RuntimeError):raise GateError(f'{what} does not resolve to a file') from None
    # Review fix (Task 18 Important 1): every OSError after resolution (EACCES, EIO, a file removed or replaced) carries
    # the path in its text, so each becomes one fixed GateError.
    try:mode=os.lstat(real)
    except OSError:raise GateError(f'{what} is not readable') from None
    if not stat.S_ISREG(mode.st_mode):raise GateError(f'{what} must be a regular file')
    if mode.st_size>limit:raise GateError(f'{what} exceeds {limit} bytes')
    try:top=Path(root).resolve();inside=real.is_relative_to(top)
    except (OSError,RuntimeError):raise GateError('work tree does not resolve') from None
    if inside:
        try:r=bounded(['git','-C',str(top),'check-ignore','-q','--',str(real.relative_to(top))],timeout=10,limit=4096)
        except OSError:raise GateError(f'git check-ignore could not run for the {what}') from None
        if r['exit_code']!=0:raise GateError(f'a {what} inside the work tree must be git-ignored')
    return real

def resolve_local_dataset(root,spec):
    """A local: dataset: a regular file of at most 32 MiB, git-ignored when it lies inside the work tree. Refused under CI and
    in project instances. The returned `path` is removed before anything is written (F-11); messages never hold the path."""
    real=_resolve_untracked(root,spec,'local dataset',MAX_LOCAL_BYTES)
    try:digest=file_hash(real)
    except OSError:raise GateError('local dataset is not readable') from None
    return {'kind':'local','size':None,'seed':None,'sha256':digest,'rows':None,'path':str(real)}

PATH_PATTERNS='personal-path-patterns'     # Task 27 (S-06): read by .githooks/personal_info_check.py path_rules()

def _git_common_dir(root):
    """The absolute git common directory of the work tree `root` (fixed messages). `bounded` merges stderr into stdout, so
    only the last non-empty output line is the path (T27-06); it must be an absolute, existing directory, else fail closed."""
    try:r=bounded(['git','-C',str(root),'rev-parse','--path-format=absolute','--git-common-dir'],timeout=10,limit=4096)
    except OSError:raise GateError('git rev-parse could not run for the privacy path pattern') from None
    lines=[x.strip() for x in str(r.get('output') or '').splitlines() if x.strip()] if passed(r) else []
    path=Path(lines[-1]) if lines else None
    try:ok=path is not None and path.is_absolute() and path.is_dir()
    except OSError:ok=False
    if not ok:raise GateError('the git common directory was not found')
    return path

def install_fixture_pattern(root,spec):
    """Task 27 (S-06): the local: dataset `spec` resolves with every spec 12 rule (resolve_local_dataset); then
    `^<re.escape(basename)>$` is appended to <git common dir>/info/personal-path-patterns (untracked, mode 0600) when that
    line is absent, so the privacy hooks block a staged or pushed file of that name. True when it added the line. The name
    is never printed; every message is fixed."""
    kind,_,value=str(spec).partition(':')
    if kind!='local' or not value:raise GateError('the privacy path pattern needs a local:PATH dataset')
    line='^'+re.escape(Path(resolve_local_dataset(root,value)['path']).name)+'$'
    info=_git_common_dir(root)/'info'
    try:
        info.mkdir(mode=0o700,exist_ok=True)
        target=info/PATH_PATTERNS
        if target.is_symlink():raise GateError('the privacy path pattern file must not be a symbolic link')
        fd=os.open(target,os.O_RDWR|os.O_CREAT|os.O_APPEND|os.O_NOFOLLOW,0o600)
        try:
            os.fchmod(fd,0o600)
            with os.fdopen(os.dup(fd),'rb') as f:old=f.read()
            if line in old.decode('utf-8',errors='replace').splitlines():return False
            os.write(fd,((b'\n' if old and not old.endswith(b'\n') else b'')+line.encode()+b'\n'))
        finally:os.close(fd)
    except OSError:raise GateError('the privacy path pattern file could not be written') from None
    return True

def _read_bounded(path,limit):
    with open(path,'rb') as f:return f.read(limit+1)

def _withheld(exc,path):
    """True when the text of an exception, or of any exception a traceback would print with it (its __cause__, and its
    __context__ unless suppressed by `raise ... from None`), names the fixture (its path or its file name). Task 19b."""
    seen=set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc));text=str(exc)
        if str(path) in text or Path(path).name in text:return True
        exc=exc.__cause__ if exc.__cause__ is not None else None if exc.__suppress_context__ else exc.__context__
    return False

def accept_aggregate(root,path,limit=AGGREGATE_LIMIT,project_dir=None,summary_schema=None,exceptions=()):
    """The host gate of the closed aggregate: at most `limit` bytes, valid against bench-local-aggregate (the framework
    envelope), a non-null `summary` valid against the project's protocol aggregate schema (`summary_schema`, or read from
    the protocol of `project_dir`; FR3), every exception type either a framework name or a name of the protocol's
    local_exceptions (`exceptions`), and no small-count quantile anywhere in the summary. FR3-17: the document is read by
    the one boundary (evidence.load_project_json: size cap `limit`, strict UTF-8, at most 64 nesting levels, no duplicate key,
    no NaN or Infinity literal) and every check runs inside it, so any failure is a GateError. A rejected document is
    deleted; the reason keeps the exception type, the stable problem name and the byte count only."""
    import jsonschema
    p=Path(path);size=p.stat().st_size if p.is_file() and not p.is_symlink() else 0
    def check(doc):
        validate(root,'bench-local-aggregate',doc)
        schema,names=summary_schema,exceptions
        if schema is None and project_dir is not None:
            proto=bm.load_protocol(root,project_dir) or {}            # FR3-R10: one protocol load
            schema=bm.protocol_data(root,project_dir,'aggregate_schema',proto=proto)
            names=tuple(proto.get('local_exceptions',[]))
        if doc['summary'] is not None:
            if schema is None:raise GateError('aggregate summary without a project aggregate schema')
            if summary_schema_problems(schema):raise GateError('project aggregate schema breaks the framework schema grammar')
            if summary_value_problems(doc['summary']):raise GateError('aggregate summary breaks the framework privacy rule')
            try:jsonschema.Draft202012Validator(schema).validate(doc['summary'])
            except jsonschema.ValidationError:raise GateError('aggregate summary fails the project aggregate schema') from None
        if any(e['type'] not in LOCAL_EXCEPTIONS and e['type'] not in names for e in doc['exceptions']):raise GateError('aggregate names an undeclared exception type')
        small_quantiles(doc)
    try:
        if not p.is_file() or p.is_symlink():raise GateError('aggregate missing')
        doc=load_project_json(p,'aggregate',limit,label='local aggregate',check=check)
        return doc,'valid'
    except (GateError,ValueError,UnicodeDecodeError,OSError) as exc:
        problem=' '.join(x for x in (getattr(exc,'problem',None),getattr(exc,'original',None)) if x)
        reason=f'aggregate rejected ({type(exc).__name__}{" "+problem if problem else ""}); {size} bytes kept as a count only'
        _remove(p)
        return None,reason

def _remove(p):
    """FR3-17: a rejected aggregate never stays on disk (a link or file is unlinked, a directory removed)."""
    if p.is_symlink() or p.is_file():p.unlink()
    elif p.is_dir():shutil.rmtree(p)

LOCAL_EXCEPTIONS=('TimeoutError','MemoryError','OSError','ValueError','Other')   # the framework exception names of a local aggregate

# FR3-01 (ruling): the framework privacy rule on the project `summary` of a local aggregate. The project aggregate schema
# can only narrow it: a summary holds numbers (finite and representable as an IEEE-754 double: an int within
# +-int(DBL_MAX), FR3-16), booleans, null, objects and arrays; a string only when it is a
# framework label below (never a value of the private dataset); keys are short identifiers; depth, list length and node
# count are capped.
SUMMARY_LABELS=bm.SUMMARY_LABELS;SUMMARY_KEY=bm.SUMMARY_KEY       # one vocabulary with the schema grammar (FR3-10)
SUMMARY_MAX_DEPTH=bm.SUMMARY_MAX_DEPTH;SUMMARY_MAX_ITEMS=bm.SUMMARY_MAX_ITEMS;SUMMARY_MAX_NODES=bm.SUMMARY_MAX_NODES

def summary_value_problems(summary):
    """The framework rule above for one summary value: [] when it holds, else the problem kinds (never a value)."""
    import math
    problems=set();nodes=[0]
    def walk(v,depth):
        nodes[0]+=1
        if nodes[0]>SUMMARY_MAX_NODES:problems.add('too-many-nodes');return
        if depth>SUMMARY_MAX_DEPTH:problems.add('too-deep');return
        if isinstance(v,bool) or v is None:return
        if isinstance(v,int):
            if not bm.finite_number(v):problems.add('number-range')      # FR3-16: |int| at most int(DBL_MAX), a double
            return
        if isinstance(v,float):
            if not math.isfinite(v):problems.add('non-finite-number')
            return
        if isinstance(v,str):
            if v not in SUMMARY_LABELS:problems.add('string')
            return
        if isinstance(v,dict):
            for k,x in v.items():
                if not isinstance(k,str) or not SUMMARY_KEY.fullmatch(k):problems.add('key')
                walk(x,depth+1)
            return
        if isinstance(v,list):
            if len(v)>SUMMARY_MAX_ITEMS:problems.add('long-list')
            for x in v[:SUMMARY_MAX_ITEMS+1]:walk(x,depth+1)
            return
        problems.add('type')
    walk(summary,0)
    return sorted(problems)

summary_schema_problems=bm.summary_schema_problems     # the allowlist schema grammar (also applied by bench_model.load_protocol)

def job_reason(exit_code):
    return 'local job refused (exit 3)' if exit_code==3 else f'local job failed (exit {exit_code})'

def local_run_status(doc,reason,job_exit=0):
    """(run status, reasons) of a local run from the accepted aggregate (or None), the gate reason and the job exit code. A
    gate reason other than 'valid' comes first; a failed or refused job keeps its own reason (review fix round 1)."""
    if doc is None or reason!='valid':return 'INVALID_EXPERIMENT',[reason]
    if job_exit!=0:return 'INVALID_EXPERIMENT',[job_reason(job_exit)]
    if doc['status']=='VALID':return 'VALID',[]
    return 'INVALID_EXPERIMENT',['aggregate status '+doc['status']]

QUANTILE_KEYS=('median','p90')

def small_quantiles(doc):
    """Refuse a quantile (median or p90) that is a number while its count is below MIN_QUANTILE_ROWS: every object of the
    summary, at any depth, that holds `count` and a quantile key is checked (FR3: the summary shape is project data, so
    the controller ruling applies to the shape, not to named fields)."""
    def walk(node,depth=0):
        if depth>32:raise GateError('aggregate summary is nested too deeply')
        if isinstance(node,dict):
            if 'count' in node and any(k in node for k in QUANTILE_KEYS):
                c=node['count']
                if not (type(c) is int and c>=0):raise GateError('aggregate quantile count is not a count')
                if c<MIN_QUANTILE_ROWS and any(node.get(k) is not None for k in QUANTILE_KEYS):raise GateError('aggregate holds a quantile over fewer than 5 rows')
            for v in node.values():walk(v,depth+1)
        elif isinstance(node,list):
            for v in node:walk(v,depth+1)
    walk(doc.get('summary'))

def run_local(root,args,plan,case,policy,envelope=None,window=None):
    """One local: smoke run in a single redacted container (spec 12). The fixture path leaves the plan before it is written.
    EX-19 (Task 31): a decision plan, and every window attempt (H15.2), is a local decision run
    (bench_local_decision.run_local_decision: one redacted container per timing session, merged closed aggregates)."""
    from bench import BenchSession, new_run_dir, emit, before_run_checks, lock_held, active_before, doctor_probe, guardrail_gate
    from policy import source_identity
    if plan['mode']=='decision':
        path=plan['dataset'].pop('path')
        from bench_local_decision import run_local_decision
        return run_local_decision(root,args,plan,case,policy,path,envelope=envelope,window=window)
    if plan['mode']!='smoke' or window is not None:raise GateError('a local run is a smoke run or a decision run; a window attempt is a decision run')
    root=Path(root);path=plan['dataset'].pop('path');protocol_sha256=bm.protocol_digest(root,plan.get('project_dir'))   # FR3
    # FR3: the summary block is validated with the project's protocol aggregate schema (no schema: a non-null summary is
    # rejected); read once here so a protocol change during the run cannot switch the schema
    summary_schema=bm.protocol_data(root,plan.get('project_dir'),'aggregate_schema') if plan.get('project_dir') is not None else None
    local_exceptions=tuple((bm.load_protocol(root,plan.get('project_dir')) or {}).get('local_exceptions',[])) if plan.get('project_dir') is not None else ()
    install_fixture_pattern(root,'local:'+path)  # Task 27 (S-06): the hooks know the fixture file name before the first container
    run_dir=new_run_dir(root,'run-local');atomic_json(run_dir/'plan.json',plan)
    args.created_run_id=run_dir.name             # Task 20 (T20-C2): bench replay uses the run id that this run created
    replay={'replay_of':args.replay_of} if getattr(args,'replay_of',None) is not None else {}     # Task 20: a local replay names the replayed run
    # B12 (T12-C4): the doctor probe (a synthetic container, no fixture) and the guardrails before any check or trial job
    probe=doctor_probe(root,run_dir);held=probe.pop('lock_held_ns',0) or 0;reasons=[] if probe['status']=='PASS' else ['bench doctor: '+probe['status']]
    more,state=guardrail_gate(root,run_dir,plan,policy,envelope if envelope is not None else plan.get('envelope'),probe);reasons+=more
    if state!='PASS':
        status='INVALID_EXPERIMENT' if state=='GATED' else 'BLOCKED'
        run={'schema_version':1,'run_id':run_dir.name,'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'case':case['case_id'],
             'case_version':case['version'],'mode':'smoke','dataset':dict(plan['dataset'],rows=None),'plan':{'plan_id':plan['plan_id'],'plan_version':plan['plan_version']},
             'envelope':probe.get('envelope'),'image_id':BenchSession.image(root),'policy_sha256':file_hash(root/'safety/performance-policy.json'),
             'protocol_sha256':protocol_sha256,'fixtures_sha256':file_hash(root/'safety/performance-fixtures.json'),'source_identity':source_identity(root)[0],'runtime':None,
             'admission':{'lock_held_ns':held,'active_at_handshake':[]},'evidence':{'aggregate':None,'guardrails':'guardrails.json','jobs':list(probe.get('evidence_paths') or [])},
             'status':status,'reasons':[r[:300] for r in reasons[:200]],**replay}
        validate(root,'bench-run',run);atomic_json(run_dir/'run.json',run)
        emit(args,{'status':status,'run_id':run_dir.name},f'bench run (owner fixture, local) {run_dir.name}: {status} (guardrails or doctor)')
        return 1 if status=='INVALID_EXPERIMENT' else 2
    pre,_=before_run_checks(root,run_dir,plan.get('project_dir'))      # Amendment A item 4: correctness gates in synthetic containers first
    if pre:
        emit(args,{'status':'INVALID_EXPERIMENT','run_id':run_dir.name,'reasons':len(pre)},f'bench run (owner fixture, local) {run_dir.name}: INVALID_EXPERIMENT (pre-run checks failed)');return 1
    sizes=policy['sizes'];rows=max(sizes[s['tier']] for s in plan['sessions']);deadline=policy['job_deadlines']['session']
    job={'schema_version':1,'job':'local','run_id':run_dir.name,'case':case['case_id'],'case_manifest':bm.container_case_path(case['case_id'],plan.get('project_dir'),root),
         'project_dir':plan.get('project_dir'),'project_identity':plan.get('project_identity'),'dataset':plan['dataset'],'rows':rows,'sizes':sizes,'pyperf':plan['pyperf'],
         'local':True,'output':'bench/out','trials':[t for s in plan['sessions'] for t in s['trials']],'deadline_seconds':deadline,
         'local_exceptions':list(local_exceptions),**({'request_limit':plan['request_limit']} if 'request_limit' in plan else {})}   # FR3: the protocol's exception names; G-ALO-CO: the limit for every child
    doc=None;reason='not collected';job_exit=0
    try:                                    # review fix: an error whose text names the fixture is replaced by a fixed one
        s=BenchSession(root,run_dir,fixture=path,redacted=True)
        try:
            r=s.job(job,'local-timing',deadline)
            check=s.runner.run(['python3','/src/container/bench-coordinator.py','--local-check','bench/out'],timeout=30,label='local-check')
            # Task 18b: the aggregate is collected whenever the artifact-directory check passes, also after a failed job (a
            # failed trial), so its reason reaches run.json; a failed job never yields a VALID one.
            job_exit=r['exit_code'] if not passed(r) and isinstance(r.get('exit_code'),int) and r.get('failure') is None else 0 if passed(r) else 1
            if passed(check):
                doc,reason=accept_aggregate(root,s.fetch('bench/out/aggregate.json',run_dir/'aggregate.json'),summary_schema=summary_schema,exceptions=local_exceptions)
                if doc is not None and not passed(r) and doc['status']=='VALID':
                    (run_dir/'aggregate.json').unlink(missing_ok=True);doc,reason=None,'local job failed with a VALID aggregate'
            else:reason='local job or artifact-directory check failed'
        finally:s.close()
    except Exception as exc:
        if _withheld(exc,path):raise GateError('local run failed; the error named the fixture and is withheld') from None
        raise
    status,reasons=local_run_status(doc,reason,job_exit)
    if doc is not None:          # T5-A11: every timing row of a smoke aggregate is a planned row of the run (the decision jobs' host check)
        from bench_local_decision import row_problems
        codes=sorted({c for c,_ in row_problems(doc,job['trials'])})      # the codes only: a row text names a value of the container
        if codes:status='INVALID_EXPERIMENT';reasons=list(reasons)+[f'local rows: {c}' for c in codes]
    run={'schema_version':1,'run_id':run_dir.name,'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'case':case['case_id'],
         'case_version':case['version'],'mode':'smoke','dataset':dict(plan['dataset'],rows=doc['rows'] if doc else None),
         'plan':{'plan_id':plan['plan_id'],'plan_version':plan['plan_version']},
         'envelope':None,'image_id':BenchSession.image(root),'policy_sha256':file_hash(root/'safety/performance-policy.json'),'protocol_sha256':protocol_sha256,'fixtures_sha256':file_hash(root/'safety/performance-fixtures.json'),
         'source_identity':source_identity(root)[0],'runtime':None,'admission':{'lock_held_ns':lock_held(s)+held,'active_at_handshake':[active_before(s)]},
         'evidence':{'aggregate':'aggregate.json' if doc else None},'status':status,'reasons':reasons,**replay}
    import bench_evidence;run['evidence_digests']=bench_evidence.digest_files(run_dir);run['bench_profile_sha256']=bench_evidence.bench_profile_sha256(root)   # H8 (Task 16)
    run[bench_evidence.RECORD_KEY]=bench_evidence.run_record_sha256(run)      # T17-APP-01: binds run.json itself (the last key)
    validate(root,'bench-run',run);atomic_json(run_dir/'run.json',run)
    emit(args,{'status':status,'run_id':run_dir.name},f'bench run (owner fixture, local, aggregate) {run_dir.name}: {status}')
    return 0 if status=='VALID' else 1

def privacy_probe(root,run_dir):
    """spec 16: a redacted job that writes a private probe value to stderr leaves only a byte count, no digest."""
    from bench import BenchSession
    s=BenchSession(root,run_dir,redacted=True)
    try:r=s.job({'schema_version':1,'job':'stderr-probe','run_id':run_dir.name,'local':True,'deadline_seconds':60},'privacy-probe',60)
    finally:s.close()
    record=read_json(Path(r['evidence_path']))
    ok=(passed(r) and record.get('output')=='' and record.get('output_bytes',0)>0 and not any('sha' in k and 'output' in k for k in record)
        and PROBE_VALUE not in json.dumps(record))         # review Minor 2: the value is absent from the whole record
    return {'status':'PASS' if ok else 'FAIL','evidence_paths':[r['evidence_path']]}
