"""B12 resource and topology guardrails (brief section 15; Amendment H1). Host-only and pure: reads the plan, the
performance policy, the CPU envelope, the container policy and the doctor row. `check` gives the reasons that refuse a
plan before any trial (`rejected`) and the reasons that BLOCK the multicore rows (`blocked`); never a fabricated pass.
A rule whose plan key is absent (`capacity`, `fixed_environment`) is listed under `not_applicable` (T12-C5), never a
silent pass; the key appears only when such a rule exists, so a plan with both keys gives exactly the brief's two lists."""
from fractions import Fraction

THREAD_NAMES=('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS')
ORPHAN_REASON='foreign orphan alive after the call-deadline reap'

def _int(v):return isinstance(v,int) and not isinstance(v,bool)

def effective_cpus(cpu_max_text,cpuset):
    """The CPUs a container can use: `max P` gives len(cpuset); `Q P` gives min(len(cpuset), Q/P). A malformed value
    raises ValueError (the caller BLOCKS; an unreadable quota is never taken as unlimited)."""
    fields=cpu_max_text.split() if isinstance(cpu_max_text,str) else []
    if len(fields)!=2 or not fields[1].isdigit() or int(fields[1])<=0:raise ValueError('cpu.max is not "<quota|max> <period>"')
    n=len(cpuset)
    if fields[0]=='max':return n
    if not fields[0].isdigit():raise ValueError('cpu.max quota is not an integer')
    return min(n,float(Fraction(int(fields[0]),int(fields[1]))))

def _threads(value):
    """A native-library thread count as an integer >= 1, or None when the value is not one."""
    return int(value) if isinstance(value,str) and value.isdigit() and int(value)>=1 else None

NA_CAPACITY='capacity: not applicable (the plan has no capacity key)'
NA_FIXED_ENVIRONMENT='fixed_environment: not applicable (the plan has no fixed_environment key; the doctor row decides)'
UNPLANNED='unplanned'      # Task 22: the limit of a reason that names a configuration capacity_trials did not plan (it affects no planned trial)

def _native_threads(environments,policy_env):
    """The largest native-library thread count of the given *_NUM_THREADS maps (plan, doctor row); the policy values when
    none is a map. An unparsable value counts 1 here; the nested-thread rule rejects it."""
    maps=[e for e in environments if isinstance(e,dict)] or [policy_env]
    counts=[_threads(e.get(k)) for e in maps for k in THREAD_NAMES]
    return max([c for c in counts if c is not None] or [1])

def _workers(w):return 1 if w=='direct' else w if _int(w) and w>=1 else None

def planned_trials(plan):
    return [t for s in plan.get('sessions') or [] for t in s.get('trials') or []]+list(plan.get('memory') or [])

MAX_CPU=4095

def parse_cpu_list(text):
    """A kernel CPU list (`cpuset.cpus.effective`, for example "0-3" or "0,2,4-5") as a sorted list of CPU numbers. A value
    that is not such a list (None, empty, a reversed range, a number above MAX_CPU) raises ValueError."""
    if not isinstance(text,str) or not text.strip():raise ValueError('cpuset is not a CPU list')
    cpus=set()
    for part in text.strip().split(','):
        lo,dash,hi=part.partition('-')
        if not lo.isdigit() or (dash and not hi.isdigit()):raise ValueError('cpuset is not a CPU list')
        a=int(lo);b=int(hi) if dash else a
        if b<a or b>MAX_CPU:raise ValueError('cpuset range out of order or too large')
        cpus.update(range(a,b+1))
    return sorted(cpus)

def check(plan,policy,envelope,container_policy,doctor_row):
    rejected,blocked,na=_evaluate(plan,policy,envelope,container_policy,doctor_row)
    return {'rejected':rejected,'blocked':[text for text,_ in blocked],**({'not_applicable':sorted(na)} if na else {})}

def affected(plan,policy,envelope,container_policy,doctor_row):
    """T12-APP-02: per blocked reason, the planned trials it affects: (reason, trials, run_wide). A reason with a limit
    n affects the trials that need more than n CPUs (workers; 'direct' needs 1). A hidden CPU limit uses min(effective, 1):
    every multicore row, and the single-worker rows too when fewer than one CPU is effective.
    An unknown limit, a missing doctor row and unread capacity configurations affect the whole run (run_wide)."""
    _,blocked,_=_evaluate(plan,policy,envelope,container_policy,doctor_row);trials=planned_trials(plan);caps=_capacity_trials(plan);out=[]
    for text,limit in blocked:
        if limit==UNPLANNED:out.append((text,[],False));continue        # Task 22: a configuration that capacity_trials did not plan
        if isinstance(limit,tuple):out.append((text,[t for t in caps if t['trial_id']==limit[1]],False));continue   # ('trial', id): that capacity trial
        hit=[t for t in trials if limit is None or (_workers(t.get('workers')) or 1)>limit]
        hit+=[t for t in caps if limit is None or _capacity_need(t)>limit]      # Task 22: a capacity trial claims servers x workers CPUs
        out.append((text,hit,limit is None))
    return out

def _capacity_trials(plan):
    """Task 22: the planned capacity trials that have the defined format (bench_capacity.trial_format); others are rejected."""
    import bench_capacity
    caps=plan.get('capacity')
    return [t for t in caps if bench_capacity.trial_format(t) is None] if isinstance(caps,list) else []

def _capacity_need(t):
    import bench_capacity
    return bench_capacity.cpu_need(t)

def blocks_run(affected_reasons):
    """C1 and T12-APP-02: the run is BLOCKED when a blocked reason is run-wide or affects a planned trial."""
    return any(run_wide or hit for _,hit,run_wide in affected_reasons)

def _evaluate(plan,policy,envelope,container_policy,doctor_row):
    rejected=[];blocked=[];na=[];cpus=envelope['cpus'];policy_env=policy['envelope']['thread_environment']
    if 'fixed_environment' in plan:
        plan_env=plan['fixed_environment']
        if not isinstance(plan_env,dict):rejected.append('nested-library threads changed (fixed_environment is not an object)');plan_env={}
    else:plan_env=None;na.append(NA_FIXED_ENVIRONMENT)
    doc_env=(doctor_row or {}).get('thread_environment')
    # hidden one-CPU availability (spec H1): "the effective cpuset or quota gives fewer CPUs than the envelope claims".
    # T12-APP-01: effective CPUs = min(len(doctor effective cpuset intersected with the envelope cpuset), cpu.max quota).
    if doctor_row is None:blocked.append(('doctor not run',None))
    else:
        try:usable=sorted(set(parse_cpu_list(doctor_row.get('cpuset')))&set(envelope['cpuset']))
        except ValueError:usable=None;blocked.append((f"hidden CPU limit unknown (cpuset {str(doctor_row.get('cpuset'))[:40]!r})",None))
        try:n=effective_cpus(doctor_row.get('cpu_max'),usable if usable is not None else envelope['cpuset'])
        except ValueError:n=None;blocked.append((f"hidden CPU limit unknown (cpu.max {str(doctor_row.get('cpu_max'))[:40]!r})",None))
        if usable is not None and n is not None and n<cpus:blocked.append((f'hidden CPU limit ({n:g} effective of {cpus})',min(n,1)))
        # the multicore rows are always affected (they claim the envelope); single-worker rows too when n < 1
    # oversubscription: workers x per-worker threads x native-library threads above the envelope. A planned trial has no
    # per-worker thread field: each Python pool worker (thread or process) is one thread, so the factor is 1 (T12-C5).
    native=_native_threads([plan_env,doc_env],policy_env)
    for t in planned_trials(plan):
        w=_workers(t.get('workers'))
        if w is None:rejected.append(f"oversubscribed {t.get('trial_id')} (workers {t.get('workers')!r})");continue
        if w*native>cpus:rejected.append(f"oversubscribed {t.get('trial_id')} ({w} workers x 1 x {native} threads > {cpus} CPUs)")
    window=(policy.get('pools') or {}).get('window_per_worker')
    if not _int(window) or window<1 or window>2:rejected.append('unbounded queue: pools.window_per_worker must be 1 or 2')
    # capacity configurations (Task 22, spec H1 and H6): no key is "not applicable"; each planned trial has the defined format
    # (else rejected), claims servers x workers x native-library threads within the envelope (else oversubscribed, rejected)
    # and has at most `cpus` clients (else BLOCKED, that trial); each configuration that capacity_trials did not plan is
    # listed as BLOCKED with its reason and affects no planned trial
    if 'capacity' not in plan:na.append(NA_CAPACITY)
    else:_capacity_rules(plan,cpus,native,rejected,blocked)
    # nested-library threads: the plan's or the doctor row's value differs from the policy value
    for name in THREAD_NAMES:
        want=policy_env.get(name)
        if (plan_env is not None and name in plan_env and plan_env[name]!=want) or (isinstance(doc_env,dict) and doc_env.get(name)!=want):
            rejected.append(f'nested-library threads changed ({name})')
    limit=(container_policy.get('aggregate') or {}).get('max_active')
    if not _int(limit) or limit<1:rejected.append('missing aggregate limit')
    if envelope.get('multicore')!='PASS':blocked.append(('multicore capacity unavailable',1))   # affects the rows that need 2 or more CPUs
    return rejected,blocked,na

def _capacity_rules(plan,cpus,native,rejected,blocked):
    import bench_capacity
    caps=plan['capacity'];gone=plan.get('capacity_blocked',[])
    if not isinstance(caps,list):rejected.append('capacity: the plan capacity key is not a list');caps=[]
    if not isinstance(gone,list):rejected.append('capacity: the plan capacity_blocked key is not a list');gone=[]
    for i,t in enumerate(caps):
        why=bench_capacity.trial_format(t)
        if why is not None:rejected.append(f'capacity: plan entry {i} is not a capacity trial ({why})');continue
        need=bench_capacity.cpu_need(t)
        if need*native>cpus:rejected.append(f"oversubscribed {t['trial_id']} ({t['servers']} servers x {need//t['servers']} workers x {native} threads > {cpus} CPUs)")
        if t['clients']>cpus:blocked.append((f"capacity {t['trial_id']}: {t['clients']} clients beyond the {cpus}-CPU envelope",('trial',t['trial_id'])))
    for i,b in enumerate(gone):
        why=bench_capacity.blocked_format(b)
        if why is not None:rejected.append(f'capacity: capacity_blocked entry {i} ({why})');continue
        blocked.append((f"capacity configuration {b['configuration']} ({b['variant']}"+(f", {b['clients']} clients" if 'clients' in b else '')+f"): {b['reason']}",UNPLANNED))

def multicore_trials(plan):
    """The planned trials that need more than one CPU (integer workers >= 2)."""
    return [t for t in planned_trials(plan) if _int(t.get('workers')) and t['workers']>=2]

def blocked_rows(plan,affected_reasons):
    """plan['blocked_rows'] entries for the rows each blocked reason affects (see `affected`), one per reason and row;
    `guardrail` marks them as host state (bench.plan_digest leaves them out of the plan identity)."""
    out=[]
    for text,hit,_ in affected_reasons:
        rows=sorted({(t['variant'],t['workers']) for t in hit if t.get('scope')!='capacity'},key=lambda r:(r[0],str(r[1])))   # Task 22: capacity trials are no timing rows
        out+=[{'variant':v,'workers':w,'reason':'blocked: '+text,'guardrail':True} for v,w in rows]
    return out

def orphan_reasons(kills):
    """Task 1 parked Minor: a call-deadline kill record whose foreign_orphans > 0 (a process outside the killed group
    still alive after the reap). The evidence decides: run_cmd records it as `run-invalid:` (T12-APP-03), so the run is
    INVALID_EXPERIMENT, never VALID and never BLOCKED. A malformed count is treated as alive (fail closed)."""
    for k in kills or []:
        n=k.get('foreign_orphans') if isinstance(k,dict) else None
        if not _int(n) or n!=0:return [ORPHAN_REASON]
    return []
