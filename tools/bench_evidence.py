"""Evidence binding (spec 13; Amendment H8; P10, P15): digests of recorded evidence, staleness, policy and runtime checks.

Threat model (T16-APP-01, T17-APP-01). `evidence_digests` binds every raw evidence file. `run_record_sha256` binds
`run.json` itself: the sha256 of its canonical JSON without that key (`run_record_sha256`). `compare`, `report` and
`decide` recompute it and refuse a mismatch, so a plain edit of a run.json field (status, reasons, source identity, image
id, policy and profile digests, accounting, case, mode, envelope) is as evident as an edit of a raw file. A run that has
digests but no record digest is unbound when it was recorded before the record digest existed (a label in compare and
report; refused by decide) and stripped after that (refused). `decide` also refuses every unbound run (no digests, no
record digest, no recorded cgroup identity), takes case, mode, project_dir and envelope from the digest-bound plan.json
and refuses a run.json that differs from it, re-derives the run status from the raw files (`recorded_status`, a recorded
status never upgrades), and checks the dataset identity against plan.json. S3-03: `decide` then binds the decision
records it wrote: run.json `decision_digests` holds the sha256 of each record, and the record digest is recomputed over
it (bind_decisions), so the decided policy set of a run is bound data (bench_readiness.run_policies).
Residual: the digests are unsigned. Like the framework manifest, they are tamper-evident, not tamper-proof: they make an
accidental or unreviewed edit evident, but someone who rewrites the raw files and recomputes every digest and the record
digest is not detected. The creation-time cutoffs are fallback signals only (a host clock can be wrong). Review and the
framework CI are the controls (AGENTS.md)."""
import contextlib, datetime, fcntl, hashlib, json, os, re, time
from collections import Counter
from pathlib import Path
from evidence import GateError, atomic_json, file_hash, read_json

DERIVED=('run.json','compare.json','summary.json','summary.csv','summary.md');MAX_FILES=4096
UNBOUND='unbound: the run predates evidence digests'
# Task 16 (7856aa5, committed 2026-10-11T18:32:45-04:00): every run recorded by bench run after this time carries digests.
DIGESTS_SINCE=datetime.datetime(2026,10,11,22,32,45,tzinfo=datetime.timezone.utc)
STRIPPED='stripped: the run has no evidence digests, but it was recorded with them (bench_profile_sha256 or a creation time after Task 16)'
IDENTITY=('kind','size','seed','sha256','rows','indices')
FILLED_BY_RUN=('sha256','rows')      # null in the plan: the run fills them (a local row count; a G6.6 named-dataset digest)
PHASE_ROWS=('pool_start','teardown','control-zero')
TIMED_SCOPES=('caller','kernel','capacity')
RUN_LOCK_SECONDS=120.0;_HELD={}
MAX_PATH=512                         # schemas/bench-run.json evidence_digests property names
# Task 17 fix round 1 (T17-APP-01): every run recorded by bench run after this time carries run_record_sha256.
RECORD_KEY='run_record_sha256';RECORD_EXCLUDED=(RECORD_KEY,)
RECORD_SINCE=datetime.datetime(2026,10,12,0,0,0,tzinfo=datetime.timezone.utc)
RECORD_UNBOUND='unbound: run.json is not digest-bound (recorded before the run record digest)'
RECORD_STRIPPED='stripped: run.json has no run record digest, but it was recorded after the run record digest existed'
RECORD_CHANGED='changed after the run: run.json'
UNBINDABLE='evidence digests unavailable'
PLAN_FACTS=('case','mode','project_dir','envelope')

def _derived(rel):return rel in DERIVED or Path(rel).name.startswith('decision')

def digest_files(run_dir):
    run_dir=Path(run_dir);out={}
    for p in sorted(run_dir.rglob('*')):
        if p.is_symlink():raise GateError('evidence directory holds a symlink')
        if not p.is_file():continue
        rel=p.relative_to(run_dir).as_posix()
        if _derived(rel):continue
        if len(rel)>MAX_PATH:raise GateError(f'evidence path longer than {MAX_PATH} characters')     # T17-APP-03
        out[rel]=file_hash(p)
        if len(out)>MAX_FILES:raise GateError('evidence directory holds too many files')
    return out

def verify(run_dir,run):
    rec=run.get('evidence_digests')
    if rec is None:return [UNBOUND]
    now=digest_files(run_dir);problems=[]
    for rel,h in sorted(rec.items()):
        if rel not in now:problems.append('missing: '+rel)
        elif now[rel]!=h:problems.append('changed after the run: '+rel)
    problems+=['unrecorded file: '+rel for rel in sorted(set(now)-set(rec))]
    return problems

def is_unbound(problems):return problems==[UNBOUND]

def run_record_sha256(run):
    """T17-APP-01: sha256 of the canonical JSON (sorted keys, no whitespace) of run.json without RECORD_EXCLUDED."""
    body={k:v for k,v in run.items() if k not in RECORD_EXCLUDED}
    return hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()

def _after(created,since):
    """True for a creation time at or after `since`, and for a missing-zone or unparsable one (never proven older). A
    missing creation time is False, as in is_stripped (bench run always writes one; the schema requires it)."""
    if created is None:return False
    try:
        t=datetime.datetime.fromisoformat(created)
        return t.tzinfo is None or t>=since
    except (TypeError,ValueError):return True

def verify_record(run):
    """T17-APP-01: [] when run.json matches its run_record_sha256; [RECORD_CHANGED] on a mismatch. A run with digests but
    no record digest gives [RECORD_UNBOUND] (recorded before the record digest existed) or [RECORD_STRIPPED]. A run
    without digests and without a record digest gives [] (the unbound and stripped checks of verify and is_stripped)."""
    if RECORD_KEY in run:return [] if run[RECORD_KEY]==run_record_sha256(run) else [RECORD_CHANGED]
    if 'evidence_digests' not in run:return []
    return [RECORD_STRIPPED] if _after(run.get('created_at'),RECORD_SINCE) else [RECORD_UNBOUND]

def unbindable_blocked(run):
    """T17-APP-03: a BLOCKED run whose evidence digests failed (bench run wrote it without them) and whose run record
    digest holds. It decides nothing; compare, report and decide give BLOCKED, not a stripped refusal."""
    reasons=run.get('reasons') if isinstance(run.get('reasons'),list) else []
    return ('evidence_digests' not in run and RECORD_KEY in run and verify_record(run)==[] and run.get('status')=='BLOCKED'
            and bool(reasons) and isinstance(reasons[0],str) and reasons[0].startswith(UNBINDABLE+':'))

DECISIONS_KEY='decision_digests'
DECISIONS_UNBINDABLE='decisions not bound: run.json does not match its run record digest'

def bindable_run(run_dir):
    """S3-03: run.json of run_dir when it carries a run record digest that holds, else GateError. bench decide calls it
    before it writes any decision record, so that a changed run.json is never re-bound over its change."""
    run=read_json(Path(run_dir)/'run.json')
    if not isinstance(run,dict) or RECORD_KEY not in run or verify_record(run):raise GateError(DECISIONS_UNBINDABLE)
    return run

def bind_decisions(run_dir,run,names):
    """S3-03: binds the decision records that bench decide wrote into run.json. decision_digests maps each policy name to
    the sha256 of decision-<name>.json (merged over the records of earlier decides of the run), and run_record_sha256 is
    recomputed over it, so a removed, edited or added record differs from the bound set (bench_readiness.run_policies).
    run is the run.json that bindable_run returned under the same run lock. Returns the written run.json.
    S4-01: the record is validated against schemas/bench-run.json before the write; GateError and nothing written
    when it does not validate."""
    from schema_check import validate
    digests=dict(run.get(DECISIONS_KEY) or {})
    for name in names:digests[name]=file_hash(Path(run_dir)/f'decision-{name}.json')
    body=_bound_body(run,digests)
    validate(Path(__file__).resolve().parents[1],'bench-run',body)
    atomic_json(Path(run_dir)/'run.json',body)
    return body

def _bound_body(run,digests):
    body={k:v for k,v in run.items() if k!=RECORD_KEY};body[DECISIONS_KEY]=dict(sorted(digests.items()))
    body[RECORD_KEY]=run_record_sha256(body);return body

def check_bind(run,names):
    """FR12-A04: GateError when the run record that bind_decisions would write for names does not validate against
    schemas/bench-run.json. Each new digest stands as 64 zero hex digits (the schema shape of every file sha256), so the
    check runs before any decision file is written, and a refusal leaves no partial decision file."""
    from schema_check import validate
    digests=dict(run.get(DECISIONS_KEY) or {});digests.update((name,'0'*64) for name in names)
    validate(Path(__file__).resolve().parents[1],'bench-run',_bound_body(run,digests))

def plan_fact_problems(run,plan):
    """T17-APP-01 (d): case, mode, project_dir and envelope of run.json against the digest-bound plan.json."""
    got={'case':run.get('case'),'mode':run.get('mode'),'project_dir':(run.get('plan') or {}).get('project_dir'),'envelope':run.get('envelope')}
    return ['run.json differs from plan.json: '+k for k in PLAN_FACTS if got[k]!=plan.get(k) and not (k=='envelope' and got[k] is None)]

def has_timed_rows(observations):
    """T17-APP-05: one definition of 'a trial ran' for compare, decide and recorded_status."""
    return any(not o.get('warmup') and o.get('scope') in TIMED_SCOPES for o in observations)

def is_stripped(run):
    """T16-APP-01: a run without `evidence_digests` that bench run recorded with them: it has `bench_profile_sha256`, or a
    creation time after Task 16, or a creation time that does not parse. An older unbound run (R-8) is not stripped."""
    if 'evidence_digests' in run:return False
    if 'bench_profile_sha256' in run:return True
    created=run.get('created_at')
    if created is None:return False
    try:
        t=datetime.datetime.fromisoformat(created)
        if t.tzinfo is None:return True
        return t>=DIGESTS_SINCE
    except (TypeError,ValueError):return True

def run_lock_path(run_id):
    if not isinstance(run_id,str) or not re.fullmatch(r'[0-9a-f]{32}',run_id):raise GateError('run id must be 32 lowercase hex digits')
    return f'/tmp/safe-c-bench-run-{os.getuid()}-{run_id}.lock'

@contextlib.contextmanager
def run_lock(run_id):
    """T16-APP-06 (c): compare, report and decide on one run are serialized, so that one command never reads the temporary
    file of another as an unrecorded evidence file. Re-entrant in one process (report calls compare). A held lock is
    waited for at most RUN_LOCK_SECONDS, then the command is BLOCKED (GateError)."""
    path=run_lock_path(run_id)
    if run_id in _HELD:
        _HELD[run_id]+=1
        try:yield
        finally:_HELD[run_id]-=1
        return
    try:fd=os.open(path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    except OSError as exc:raise GateError(f'run lock {path} cannot be opened ({type(exc).__name__})') from None    # T17-APP-04
    try:
        deadline=time.monotonic()+RUN_LOCK_SECONDS
        while True:
            try:
                fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);break
            except BlockingIOError:
                if time.monotonic()>=deadline:raise GateError('another compare, report or decide holds this run') from None
                time.sleep(0.05)
        _HELD[run_id]=1
        try:yield
        finally:
            del _HELD[run_id];fcntl.flock(fd,fcntl.LOCK_UN)
    finally:os.close(fd)

def dataset_differs(planned,recorded):
    """T16-APP-03: the full identity (kind, size, seed, sha256, rows, indices when present) of a recorded dataset against
    its planned entry. A null sha256 or row count in the plan is filled by the run; every other key must be equal."""
    if planned is None and recorded is None:return False
    if not isinstance(planned,dict) or not isinstance(recorded,dict):return True
    return any(planned.get(k)!=recorded.get(k) for k in IDENTITY if not (k in FILLED_BY_RUN and planned.get(k) is None))

def recorded_status(plan,run,observations,phases,policy):
    """T16-APP-01: decide never trusts the `status` of run.json (not digest-bound). The status comes from the digest-bound
    files: bench.run_status (trial design, completeness, caller semantics, perturbation, concurrency identity, metrics,
    eligibility, call-deadline kills) and the plan request limit (I13.1); an accounting row of run.json that is not PASS
    adds a reason. A recorded status never upgrades: INVALID_EXPERIMENT stays INVALID_EXPERIMENT; BLOCKED stays BLOCKED
    only without a derived problem. Returns (status, reasons), the derived reasons first."""
    import bench
    recorded=run.get('status');reasons=[str(r)[:300] for r in run.get('reasons') or [] if isinstance(r,str)][:200] if isinstance(run.get('reasons'),list) else []
    if recorded=='BLOCKED' and not has_timed_rows(observations):return 'BLOCKED',reasons
    derived=[]
    try:derived+=bench.run_status(plan,observations,phases,policy)[1]
    except (KeyError,TypeError,ValueError,AttributeError,GateError) as exc:derived.append(f'run status not derivable from the recorded files ({type(exc).__name__})')
    limit=bench.plan_request_limit_reason(plan,policy)
    if limit:derived.append(limit)
    rows=run.get('accounting') if isinstance(run.get('accounting'),list) else []
    derived+=[f"B15 accounting row {str(a.get('session','?'))[:80]}: {str(a.get('status'))[:20]}" if isinstance(a,dict) else 'B15 accounting row malformed'
              for a in rows if not isinstance(a,dict) or a.get('status')!='PASS']
    if recorded not in ('VALID','INVALID_EXPERIMENT','BLOCKED'):derived.append(f'recorded status {str(recorded)[:40]!r} unknown')
    if not derived and recorded in ('VALID','BLOCKED'):return recorded,reasons
    return 'INVALID_EXPERIMENT',list(dict.fromkeys([str(x)[:300] for x in derived]+reasons))[:200]

def bench_profile_sha256(root):
    pol=read_json(Path(root)/'safety/container-policy.json');profile=pol['profiles']['bench']
    return hashlib.sha256(json.dumps(profile,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def stale(run,current_identity):return run.get('source_identity')!=current_identity

def policy_runtime_problems(root,run):
    root=Path(root);problems=[]
    now=file_hash(root/'safety/performance-policy.json')
    if run.get('policy_sha256')!=now:problems.append(f"post-hoc-policy-change: the run used {str(run.get('policy_sha256'))[:12]}, the current policy is {now[:12]}")
    img=read_json(root/'developer.lock.json')['image_id']
    if run.get('image_id')!=img:problems.append(f"reused-runner-report: image {str(run.get('image_id'))[:19]} differs from the locked {img[:19]}")
    if 'bench_profile_sha256' in run and run['bench_profile_sha256']!=bench_profile_sha256(root):problems.append('reused-runner-report: bench profile digest differs')
    problems+=protocol_problems(root,run)
    return problems

def protocol_problems(root,run):
    """FR3 (design Task 32): the run's recorded protocol_sha256 equals the digest of the current protocol file of the run's
    project (None for a framework case or a project without a protocol). A run of a project with a protocol that recorded
    no digest, a changed protocol and a protocol that no longer loads (unbound, edited, invalid) are refused."""
    import bench_model as bm
    plan=run.get('plan') if isinstance(run.get('plan'),dict) else {}
    project=plan.get('project_dir');recorded=run.get('protocol_sha256')
    try:now=bm.protocol_digest(root,project)
    except GateError as exc:return [f'post-hoc-protocol-change: the protocol of the run project does not load ({str(exc)[:120]})']
    if recorded!=now:return [f'post-hoc-protocol-change: the run used protocol {str(recorded)[:12]}, the current protocol is {str(now)[:12]}']
    return []

def _timed(obs):return Counter((o.get('trial_id'),o.get('wall_ns'),o.get('cpu_usage_usec')) for o in obs if not o.get('warmup') and o.get('scope') in ('caller','kernel','capacity'))

def check_replay_fresh(old,new):
    problems=[]
    a=_timed(old);b=_timed(new)
    if a and a==b:problems.append('replay copied the recorded numbers')
    old_ids={o.get('run_id') for o in old}
    if any(o.get('run_id') in old_ids for o in new):problems.append('replay reused the run identity')
    return problems

def check_integrity(plan,run,observations,policy):
    """B15 (brief section 15) and P10 dataset/scope binding on recorded evidence."""
    problems=[];planned={}
    for sess in plan.get('sessions',[]):
        for t in sess['trials']:planned[t['trial_id']]=t
    for t in plan.get('memory',[]):planned[t['trial_id']]=dict(t,scope='memory')
    for t in plan.get('capacity') or []:planned[t['trial_id']]=t          # Task 22: planned capacity trials (scope and point capacity)
    want=lambda t:(plan.get('pyperf',{}).get('values',1)+plan.get('pyperf',{}).get('warmups',0)) if t.get('scope')=='kernel' else 1
    seen={}
    for o in observations:
        if o.get('phase') in ('pool_start','teardown','control-zero'):continue
        seen.setdefault(o['trial_id'],[]).append(o)
        if o.get('run_id')!=run['run_id']:problems.append('cross-run metrics: '+o['trial_id'])
        t=planned.get(o['trial_id'])
        if t is None:problems.append('unplanned row: '+o['trial_id'])           # T16-APP-02: an added row is a B15 duplicate or altered row
        if t is not None and (o.get('scope')!=t.get('scope') or (t.get('point') and o.get('point')!=t.get('point'))):problems.append('scope mismatch: '+o['trial_id'])
        pw=o.get('pyperf_wall_ns')
        if pw is not None and o.get('wall_ns') is not None and abs(pw-o['wall_ns'])>max(policy['pyperf']['agreement_abs_ns'],policy['pyperf']['agreement_rel']*o['wall_ns']):
            problems.append('forged self-timing: '+o['trial_id'])
    for tid,t in planned.items():
        got=seen.get(tid,[])
        if not got:problems.append('missing failed attempt: '+tid)
        elif len(got)>want(t):problems.append('duplicate rows: '+tid)
        elif not t.get('warmup'):
            n=policy['sizes'][t['tier']]*(t['clients']*t['requests_per_client'] if t.get('scope')=='capacity' else 1)   # Task 22: every request of a capacity trial
            if any(o.get('eligible') and o.get('work_units')!=n for o in got):problems.append('wrong work count: '+tid)
    if dataset_differs(plan.get('dataset'),run.get('dataset')):problems.append('dataset mismatch: primary dataset')    # T16-APP-03: full identity
    named=plan.get('datasets') or {};recorded=run.get('datasets') or {}
    for name in sorted(set(named)|set(recorded)):
        if dataset_differs(named.get(name),recorded.get(name)) or (name in named)!=(name in recorded):problems.append('dataset mismatch: '+name)
    return sorted(set(problems))
