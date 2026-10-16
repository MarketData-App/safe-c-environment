"""B18 starter/child and normal workflow integration (owner brief section 15; spec Amendment H1; Task 26).

Two parts:
- static_checks(root): the bench-selftest suite B18 (Task 29 registers it), in the framework repository and in project
  instances alike: the bench payload is complete in the export; Python-first scaffolding; replay registered and refusing
  an unauthorized bench profile; the docs; the concurrency policy; the metric profiles; runtime exclusion.
- child_checks(parent_root, child_root): starter-maintenance mode only, called by starter.verify_starter after the fresh
  child ci: both instances hold the whole payload; the designated child's combined qualification passed with real
  measurement of its own source identity; no copied parent run (P10 parent-results-in-child); no grandchild.
Child-instance mode (--instance) runs only static_checks and local execution, never an export or a grandchild.

Every check gives a list of problems; an empty list is PASS. A check that raises is FAIL (never PASS, never BLOCKED):
it could not prove its property on a tree that should hold it."""
import fnmatch, json, os, shutil, tempfile
from pathlib import Path
from evidence import GateError, file_hash, read_json

PAYLOAD_GLOBS=('tools/bench*.py','container/bench*','schemas/bench-*.json','safety/performance-*.json')
PAYLOAD_TREES=('benchmarks/performance/',)     # plus every example project tree (bench.example_projects; the framework names no example)
DOCS=('docs/performance-laboratory.md','docs/python-first-performance.md','prompts/performance-decision.md')
PAYLOAD_TOPS=('tools','container','schemas','safety','benchmarks/performance','docs','prompts')
# policy.source_files excludes the same parts: generated or local files never belong to the payload
EXCLUDED_PARTS={'.git','.cache','artifacts','build','.direnv','.codex','.agentwatch','__pycache__','.pytest_cache','.superpowers'}
STATIC_CHECKS=('payload','scaffolding','replay','docs','concurrency-policy','metric-profiles','runtime-exclusion')
CHILD_CHECKS=('payload-in-instances','child-measured','no-copied-parent-runs','no-grandchildren')
PROBLEMS_MAX=50

SCAFFOLD_SCHEMAS=('bench-case','bench-opportunity','bench-project')
SCAFFOLD_CASE='b18-scaffold-probe'
C_ROW={'id':'c-serial','language':'c','workers':['direct'],'status':'implemented'}
REPLAY_CASE='bench-control-spin'
POOLS={'chunk_rule':'one-per-worker','window_per_worker':2,'start_method':'spawn'}
BENCH_GATES=('bench-doctor','bench-selftest')
INTERPRETER='lib64/ld-linux-x86-64.so.2'
DATA_SUFFIXES=('.jsonl','.csv','.parquet','.npy','.npz')
COPIED='a child run carries the parent source identity'

def _payload_path(rel,trees):
    return any(fnmatch.fnmatchcase(rel,g) for g in PAYLOAD_GLOBS) or rel.startswith(trees) or rel in DOCS

def tracked_files(root,tops):
    """T26-B18-01: the git-tracked paths under `tops` of a root that is itself a git checkout (a `.git` entry at the root),
    from `git ls-files` of that root. T27-03: a tree without .git that holds the host tracked set (policy.TRACKED_MANIFEST,
    written by evidence.Runner into the container source snapshot of a git checkout) uses that set, so a git-ignored file
    copied into the snapshot never enters the payload. None for a tree with neither (a starter export instance, or the
    snapshot of one: it holds only that tree's files). A tracked set that cannot be read raises GateError (fail closed)."""
    root=Path(root)
    if not (root/'.git').exists() and not (root/'.git').is_symlink():
        from policy import TRACKED_MANIFEST
        m=root/TRACKED_MANIFEST
        if not m.exists() and not m.is_symlink():return None
        try:value=read_json(m) if not m.is_symlink() and m.is_file() else None     # FR3-19
        except (OSError,ValueError):value=None
        tracked=value.get('tracked') if isinstance(value,dict) else None
        if not isinstance(tracked,list) or not all(isinstance(p,str) for p in tracked):
            raise GateError('the host tracked set of the source snapshot is missing or unreadable')
        return set(tracked)
    from evidence import bounded, passed
    try:r=bounded(['git','-C',str(root),'-c','core.quotePath=false','ls-files','-z','--',*tops],timeout=60,limit=16*1024*1024)
    except OSError:raise GateError('git ls-files could not run for the bench payload') from None
    if not passed(r):raise GateError('git ls-files failed for the bench payload')
    return {p for p in r['output'].split('\0') if p}

def payload(root):
    """The bench payload of `root`: sorted relative paths of the files (and links) under the bench areas and every example
    project tree (bench.example_projects, found by layout), without generated or local parts (the exclusions of
    policy.source_files). In a git checkout and in its container source snapshot only git-tracked files count
    (tracked_files), so a git-ignored or untracked
    local file there never enters the payload. Each must be listed in starter-export.json."""
    import bench
    root=Path(root);out=set();examples=tuple(bench.example_projects(root))
    trees=PAYLOAD_TREES+tuple(e+'/' for e in examples)
    tracked=tracked_files(root,PAYLOAD_TOPS+examples)
    for top in PAYLOAD_TOPS+examples:
        base=root/top
        if base.is_symlink():
            if tracked is None or top in tracked:out.add(top)
            continue
        if not base.is_dir():continue
        for dirpath,dirnames,filenames in os.walk(base):
            dirnames[:]=[d for d in dirnames if d not in EXCLUDED_PARTS and not os.path.islink(os.path.join(dirpath,d))]
            names=filenames+[d for d in os.listdir(dirpath) if d not in EXCLUDED_PARTS and os.path.islink(os.path.join(dirpath,d))]
            for name in names:
                if name.startswith('.env'):continue
                rel=Path(dirpath,name).relative_to(root).as_posix()
                if _payload_path(rel,trees) and (tracked is None or rel in tracked):out.add(rel)
    return sorted(out)

def _export(root):return set(read_json(Path(root)/'starter-export.json')['files'])

def check_payload(root):
    files=payload(root)
    if not files:return ['no bench payload found']
    listed=_export(root)
    return ['not exported: '+p for p in files if p not in listed]

def check_scaffolding(root):
    """`bench new` in a temporary project creates Python variants and Python files only, and a C row without an approved
    opportunity record is refused; control: the same C row passes the rule once the record is APPROVED."""
    import bench, bench_model as bm
    root=Path(root);problems=[]
    with tempfile.TemporaryDirectory(prefix='safe-c-b18-') as t:
        t=Path(t);(t/'schemas').mkdir();(t/'benchmarks/performance/cases').mkdir(parents=True);(t/'project').mkdir()
        for k in SCAFFOLD_SCHEMAS:shutil.copyfile(root/'schemas'/f'{k}.json',t/'schemas'/f'{k}.json')
        paths=bench.new_case(t,SCAFFOLD_CASE,project_dir='project')
        case=read_json(Path(paths['manifest']))
        other=sorted(f"{v.get('id')} ({v.get('language')})" for v in case.get('variants') or [] if v.get('language')!='python')
        if other or not case.get('variants'):problems.append('bench new created a variant that is not Python: '+(', '.join(other) or 'no variants'))
        native=sorted(p.relative_to(t).as_posix() for p in (t/'project').rglob('*') if p.is_file() and p.suffix not in ('.py','.json'))
        if native:problems.append('bench new wrote a file that is not Python or JSON: '+', '.join(native[:5]))
        c_case=dict(case,variants=[v for v in case.get('variants') or [] if v.get('language')!='c']+[dict(C_ROW)])
        try:
            bm.case_rules(t,c_case,'project');problems.append('a C row without an approved opportunity record was accepted')
        except GateError:pass
        record=Path(paths['opportunity']);value=read_json(record);value['approval']={'state':'APPROVED','reference':'b18-control'}
        record.write_text(json.dumps(value))
        try:bm.case_rules(t,c_case,'project')
        except GateError as exc:problems.append('control: a C row with an approved record was refused: '+str(exc)[:200])
    return problems

def check_replay(root):
    """`bench replay` is registered, and its authorization refuses a recorded run whose bench profile is not the current
    one; control: the same run with the current profile is authorized."""
    import bench, bench_replay as br, bench_evidence as be, bench_model as bm
    root=Path(root);problems=[]
    if bench.HANDLERS.get('replay') is not br.replay_cmd or 'replay' not in bench.ARGUMENTS:problems.append('bench replay is not registered')
    with tempfile.TemporaryDirectory(prefix='safe-c-b18-') as t:
        rd=Path(t);plan={'case':REPLAY_CASE,'mode':'smoke','dataset':{'kind':'synthetic','size':'small'},'project_dir':None}
        plan['plan_id']=bench.plan_digest(br.plan_body(plan));(rd/'plan.json').write_text(json.dumps(plan,sort_keys=True))
        version=bm.load_case(root,REPLAY_CASE)['version'];policy=file_hash(root/'safety/performance-policy.json')
        image=read_json(root/'developer.lock.json')['image_id']
        def recorded(profile):
            run={'run_id':'0'*32,'case':REPLAY_CASE,'case_version':version,'mode':'smoke','status':'VALID','policy_sha256':policy,'image_id':image,
                 'bench_profile_sha256':profile,'plan':{'plan_id':plan['plan_id'],'project_dir':None,'project_identity':None},
                 'evidence_digests':be.digest_files(rd)}
            run[be.RECORD_KEY]=be.run_record_sha256(run);return run
        control=br.authorization(root,rd,recorded(be.bench_profile_sha256(root)),plan)
        if control:problems.append('control: an authorized recorded run is refused: '+'; '.join(control[:3]))
        if 'bench profile changed since the run' not in br.authorization(root,rd,recorded('0'*64),plan):
            problems.append('bench replay accepts a run recorded under another bench profile')
    return problems

def _nonempty(path):return path.is_file() and not path.is_symlink() and path.stat().st_size>0

def check_docs(root):
    """docs/performance-laboratory.md always; the two Task 34 files once the export list holds them."""
    root=Path(root);listed=_export(root)
    required=[DOCS[0]]+[d for d in DOCS[1:] if d in listed]
    return ['missing: '+d for d in required if not _nonempty(root/d)]

def check_pools(pools):
    """The concurrency policy: one chunk per worker, a window of 2 x workers, the spawn start method."""
    if not isinstance(pools,dict):return ['the pools policy is missing']
    return [f'pools.{k} is {pools.get(k)!r}, expected {v!r}' for k,v in POOLS.items() if pools.get(k)!=v]

def check_profiles(container_policy):
    """The metric profile: the `bench` container profile with its fixed thread environment."""
    from container_policy import BENCH_ENVIRONMENT
    profile=((container_policy or {}).get('profiles') or {}).get('bench')
    if not isinstance(profile,dict):return ['the bench container profile is missing']
    env=profile.get('fixed_environment')
    if env!=BENCH_ENVIRONMENT:return [f'the bench profile fixed_environment is {env!r}, expected {BENCH_ENVIRONMENT!r}']
    return []

def _bench_asset(name):
    parts=[p for p in name.lower().split('/') if p]
    for p in parts:
        if p.startswith('bench') or any(w in p for w in ('profil','pyperf','py-spy','mutant','dataset','option_chain','option-chain')):return True
    return bool(parts) and parts[-1].endswith(DATA_SUFFIXES)

def runtime_inventories(root):
    """The runtime image inventory (tools/runtime.py runtime_members and the COPY lines of container/runtime.Dockerfile) and
    the project run closure (bin/<run program> and the interpreter; tools/project_check.py collect_runtime adds only
    system libraries resolved in the container). A project instance reads its own project.json; the framework reads the
    exported example project."""
    import runtime, starter
    root=Path(root);image=sorted(runtime.runtime_members())
    docker=root/'container/runtime.Dockerfile'
    if docker.is_file():
        for line in docker.read_text().splitlines():
            words=line.split()
            if len(words)>=3 and words[0]=='COPY':image+=[w.lstrip('/') for w in words[1:]]
    project=root/'project.json' if (root/'project.json').is_file() else root/starter.EXAMPLE/'project.json'
    program=((read_json(project).get('run') or {}).get('program')) if project.is_file() else None
    closure=([f'bin/{program}'] if isinstance(program,str) else [])+[INTERPRETER]
    return {'runtime-image':image,'project-run':closure}

def runtime_bench_files(root,inventories=None):
    """Members of the runtime inventories that are a bench driver, benchlab, a profiler, a mutant or a dataset file, as
    '<inventory>: <member>'. An empty list is the runtime exclusion."""
    inv=runtime_inventories(root) if inventories is None else inventories
    return sorted({f'{k}: {m}' for k,members in inv.items() for m in members if isinstance(m,str) and _bench_asset(m)})

def _result(name,fn):
    try:problems=[str(p)[:300] for p in fn()]
    except Exception as exc:        # the check could not prove its property: FAIL, never PASS or BLOCKED
        problems=[f'{name} check failed: {type(exc).__name__}: {str(exc)[:200]}']
    return {'status':'FAIL' if problems else 'PASS','problems':problems[:PROBLEMS_MAX]}

def _combine(checks):
    return {'status':'PASS' if all(c['status']=='PASS' for c in checks.values()) else 'FAIL','checks':checks}

def static_checks(root):
    """The bench-selftest suite B18 (framework repository and instances alike)."""
    import bench_model as bm
    root=Path(root)
    steps={'payload':lambda:check_payload(root),'scaffolding':lambda:check_scaffolding(root),'replay':lambda:check_replay(root),
           'docs':lambda:check_docs(root),'concurrency-policy':lambda:check_pools(bm.load_policy(root).get('pools')),
           'metric-profiles':lambda:check_profiles(read_json(root/'safety/container-policy.json')),
           'runtime-exclusion':lambda:runtime_bench_files(root)}
    return _combine({k:_result(k,steps[k]) for k in STATIC_CHECKS})

def bench_runs(root):
    """Every artifacts/bench/<id>/run.json of `root` as a dict with its directory name as run_id when the record has none
    (an unreadable record gives {'run_id': <id>, 'unreadable': True})."""
    base=Path(root)/'artifacts/bench';out=[]
    if base.is_symlink() or not base.is_dir():return out
    for d in sorted(base.iterdir()):
        p=d/'run.json'
        if d.is_symlink() or not d.is_dir() or not (p.exists() or p.is_symlink()):continue
        try:run=read_json(p) if not p.is_symlink() else None     # FR3-19
        except (OSError,ValueError):run=None
        entry=dict(run) if isinstance(run,dict) else {'unreadable':True}
        entry.setdefault('run_id',d.name);out.append(entry)
    return out

def copied_parent_runs(parent_identity,child_root,child_runs=None):
    """P10 parent-results-in-child: a run in the child that carries the parent's source identity is a copied parent
    measurement. `child_runs` defaults to the child's recorded runs."""
    if not parent_identity:return ['the parent source identity is unknown']
    runs=bench_runs(child_root) if child_runs is None else child_runs
    return [COPIED] if any(isinstance(r,dict) and r.get('source_identity')==parent_identity for r in runs) else []

def _payload_missing(parent_root,instances):
    files=payload(parent_root)
    if not files:return ['no bench payload in the parent']
    problems=[]
    for inst in instances:
        inst=Path(inst)
        for rel in files:
            src,dst=Path(parent_root)/rel,inst/rel
            if dst.is_symlink() or not dst.is_file():problems.append(f'{inst.name}: missing {rel}')
            elif src.is_file() and file_hash(src)!=file_hash(dst):problems.append(f'{inst.name}: differs {rel}')
    return problems

def _report(child_root):
    try:rep=read_json(Path(child_root)/'artifacts/bootstrap-report.json')     # FR3-19
    except (OSError,ValueError):return None
    return rep if isinstance(rep,dict) else None

def _measured(child_root,parent_identity,child_identity):
    """The designated child's combined qualification passed with real measurement: its report passes with both bench gates,
    names the child (never the parent) source identity, and at least one VALID smoke run of that identity under the child's
    artifacts/bench holds its run record digest and its evidence digests."""
    import bench_evidence as be
    rep=_report(child_root)
    if rep is None:return ['the child has no readable bootstrap report']
    problems=[];ident=rep.get('source_identity')
    if not ident:problems.append('the child report has no source identity')
    elif ident==parent_identity:problems.append('the child report carries the parent source identity')
    if child_identity is not None and ident!=child_identity:problems.append('the child report names another source identity than the child')
    if rep.get('local_state')!='PASS':problems.append(f"the child qualification is {rep.get('local_state')!r}, not PASS")
    gates={g.get('name'):g.get('status') for g in rep.get('gates') or [] if isinstance(g,dict)}
    problems+=[f'child gate {g}: {gates.get(g) or "missing"}' for g in BENCH_GATES if gates.get(g)!='PASS']
    base=Path(child_root)/'artifacts/bench';measured=0
    for d in (sorted(base.iterdir()) if base.is_dir() and not base.is_symlink() else []):
        p=d/'run.json'
        if d.is_symlink() or not d.is_dir() or p.is_symlink() or not p.is_file():continue
        try:run=read_json(p)     # FR3-19
        except (OSError,ValueError):continue
        if not isinstance(run,dict) or run.get('mode')!='smoke' or run.get('status')!='VALID' or not ident or run.get('source_identity')!=ident:continue
        try:bound=not be.verify_record(run) and not be.verify(d,run)
        except GateError:bound=False
        measured+=bound
    if not measured:problems.append('no VALID, digest-bound bench smoke run of the child source identity in the child artifacts/bench')
    return problems

def _copies(parent_root,child_root,before_runs,parent_identity,child_identity):
    """No copied parent measurements: the child held no run before its ci other than its own; no child run carries the
    parent source identity or a parent run id."""
    problems=[]
    own=child_identity or (_report(child_root) or {}).get('source_identity')
    if before_runs is None:problems.append('the child bench runs before its ci were not recorded')
    else:
        problems+=[f"a bench run of another source was in the child before its ci: {str(r.get('run_id'))[:64]}" for r in before_runs
                   if not isinstance(r,dict) or not own or r.get('source_identity')!=own]
        problems+=copied_parent_runs(parent_identity,child_root,before_runs)
    after=bench_runs(child_root);problems+=copied_parent_runs(parent_identity,child_root,after)
    base=Path(parent_root)/'artifacts/bench'
    parent_ids={d.name for d in base.iterdir()} if base.is_dir() and not base.is_symlink() else set()
    problems+=[f"a child run has a parent run id: {r['run_id']}" for r in after if r.get('run_id') in parent_ids]
    return list(dict.fromkeys(problems))

def _grandchildren(child_root):
    return ['grandchild instance: '+p.relative_to(child_root).as_posix() for p in sorted((Path(child_root)/'artifacts/instances').glob('*/*/starter-baseline.lock.json'))]

def child_checks(parent_root,child_root,*,instances=(),before_runs=None,parent_identity=None,child_identity=None):
    """Starter-maintenance mode only (starter.verify_starter after the fresh child ci). `instances` are the other starter
    instances that must hold the payload too; `before_runs` the child's bench_runs before its ci (None: not recorded, never
    a pass); `parent_identity` the parent source identity (computed when None); `child_identity` the child's."""
    parent_root,child_root=Path(parent_root),Path(child_root)
    if parent_identity is None:
        from policy import source_identity
        parent_identity=source_identity(parent_root)[0]
    steps={'payload-in-instances':lambda:_payload_missing(parent_root,[child_root,*instances]),
           'child-measured':lambda:_measured(child_root,parent_identity,child_identity),
           'no-copied-parent-runs':lambda:_copies(parent_root,child_root,before_runs,parent_identity,child_identity),
           'no-grandchildren':lambda:_grandchildren(child_root)}
    return _combine({k:_result(k,steps[k]) for k in CHILD_CHECKS})
