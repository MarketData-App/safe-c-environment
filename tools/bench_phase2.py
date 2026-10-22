"""Phase 2 bench selftest cases (Phase 2 Task 23, framework part; task EX-13): the suites B04, B06, B07, B08, B11, B13-echo
and B16, and the P02 (bench-build-or-scope-mismatch), P04 (bench-concurrency-or-launch-bypass) and P16
(bench-no-op-or-gamed-optimizer) subcases.

`phase2_cases(root, run_dir, project)` runs from bench.selftest_cases (one hook line). Framework code: it names no example.
The native example projects are found by layout (bench.example_projects; an explicit `bench selftest --project DIR` names
the one project instead, amendment E) and by their bench.json `native` declaration; the
native agreement check is the check that `native.agreement` names; the pool trace program is `native.trace`. For each such
project the suites use real evidence:

- one real `bench run` (smoke, synthetic:small) of the first project case with a C variant: Python, kernel and caller
  rows on every declared route, the native build record and the plan (B07, B08, B16, P02, P04, P16);
- the coordinator job `native-overlap` (container/bench_phase2_job.py): the declared trace program from its verified
  restored binary, with its exit code, trace lines, affinity size, cgroup CPU and wall time (B04, P04);
- the coordinator job `agreement-controls`: the generic mutations of benchlab.agreement (and every mutation that the
  project protocol lists in `agreement_mutations`, through the adapter's agreement_mutation hook) applied to a real C
  result and re-validated with the adapter's own `validate` (B06, P16);
- the coordinator job `failure-controls`: the framework stub worker (benchmarks/performance/python/tests/stub_worker.py)
  driven by the framework client benchlab.native_worker through every failure class, and a caller child that crashes
  (B16).

Every addition has its unmutated control: the same check must pass on the unmutated evidence, so a broken check or a
broken control never gives PASS (bench._sub). A check that raises gives FAIL with the exception type, never PASS.

Where no example project declares a feature (an echo control case in the protocol `echo_case`, a trace program), the
suite uses its fixture control and records the real part as not run with the reason; the project-specific controls of
an example (its own mutations, echo rows and selector controls) belong to that example."""
import copy, json, re
from pathlib import Path
from evidence import GateError, atomic_json, read_json
import bench_model as bm

ROOT=Path(__file__).resolve().parents[1]
NAMES={'P02':'bench-build-or-scope-mismatch','P04':'bench-concurrency-or-launch-bypass','P16':'bench-no-op-or-gamed-optimizer'}
P02_VARIANTS=('sanitized-or-debug-artifact','wrong-dependency','hidden-algorithm-or-precision-change','incomplete-workload-inventory',
              'different-cpu-envelope','different-selector-panel-or-dataset')
P04_VARIANTS=('unlimited-pool-or-queue','unauthorized-thread-api','unsafe-native-loading','host-execution','changed-affinity',
              'unmanaged-subprocess','profiler-privilege')
P16_VARIANTS=('skip-useful-work','reuse-answer','no-op-native-kernel','removed-result-consumption','selector-overcompute','selector-no-op')
ALL_VARIANTS=[('P02',v) for v in P02_VARIANTS]+[('P04',v) for v in P04_VARIANTS]+[('P16',v) for v in P16_VARIANTS]
SUITES=('B04','B06','B07','B08','B11','B13-echo','B16')
# The generic agreement mutations (benchlab.agreement.GENERIC). A project adds its own through the protocol key
# `agreement_mutations` and the adapter hook agreement_mutation (required_mutations).
AGREEMENT_MUTATIONS=('skipped-chunk','wrong-order','missing-output','hardcoded-answer','precision-change','range-change')
PRIVILEGE_KEYS=('capabilities','privileged','perf_event_paranoid','ptrace')     # bench.HOST_TUNING_KEYS holds each (P04)
RUNNERS=('pyperf','safe-c-trial-runner')
C_PHASES=('prepare','transport','work','materialize')
PROCESS_ROUTES=('stdio','shm')
DIRECT_PY=('py-reference','py-optimized','py-library')
GLIB_NAME='libglib-2.0.so.0'
SHA256_RE=re.compile(r'^[0-9a-f]{64}$')
HEADER_RE=re.compile(r'^# workers=(\d{1,3})( threads=(\d{1,3}) max_inflight=(\d{1,6}) submitted=(\d{1,6}) executed=(\d{1,6}))?(?: result=([0-9a-f]{16}))?$')
SPAN_RE=re.compile(r'^(\d{1,6}) (\d{1,20}) (\d{1,20}) (\d{1,6}) (\d{1,20})$')
MAX_TRACE_LINES=4096
CPU_SLACK_NS=1000000            # per-task thread CPU against the cgroup CPU: clock granularity of the two counters
FAILURE_CLASSES={'worker-error':('KERNEL_FAILURE',),'eof':('WORKER_EXITED',),'partial-response':('PROTOCOL_TRUNCATED',),
                 'deadline':('DEADLINE',),'crash':('WORKER_EXITED','PROTOCOL_TRUNCATED')}
SIGSEGV=11
SMOKE_DATASET='synthetic:small'
CRASH_CASE='bench-control-spin';CRASH_SEED=20261007      # EX13-A04: the framework case of the caller-crash child
AGREEMENT_ROWS=64
PROPERTY={'B04':'the declared pool trace program runs from its verified restored binary on 1, 2 and 4 workers under the '
                'approved multicore envelope: task IDs complete and unique, results equal to the serial run, separate worker '
                'identities that each spent CPU, overlapping execution, threads <= workers, in-flight <= 2 x workers, affinity '
                '>= workers, task CPU <= cgroup CPU; a serial-dispatch or one-CPU-affinity masquerade of the real trace fails; '
                'no speedup is required',
          'B06':'every generic agreement mutation (and every protocol agreement_mutations entry) changes a real C result and '
                'the adapter validate rejects it, while the unmutated C result is eligible; the declared native agreement '
                'check passed with the run build (C equals the Python reference byte for byte on every route)',
          'B07':'comparison contexts of one real run agree (dataset, scope, tier, selector, panel, case version, algorithm '
                'identity, envelope), with a release build and the loaded GLib of the build and a complete workload '
                'inventory; every P02 mutation of the real contexts is rejected',
          'B08':'real caller rows on every declared route: prepare, transport, work and materialize phases, a result digest, '
                'the route and its policy label, copied bytes; cold process rows start their worker inside the interval and '
                'report teardown apart; warm rows report startup apart; in-process rows only warm; Python direct controls '
                'without route labels; scope mutants of the real rows are rejected',
          'B11':'the foundation pool qualification of the current source: parallel lane PASS with simulated faults and every '
                'seeded mutant detected with its control, and the asan, ubsan, msan and tsan profiles PASS; and a current '
                'sanitizer-evidence report of every native example project with its ubsan, asan, msan and tsan gates PASS, '
                'the report verdict PASS and no blocker; BLOCKED without either',
          'B13-echo':'echo-control rows cover every C variant, worker count, mode and route that the echo case declares, each '
                     'labeled with its route (an example declares its echo case in the protocol `echo_case`)',
          'B16':'every failure class of the framework transport is classified and reaped (worker ERROR, EOF, partial '
                'response, deadline, a worker crash); a caller child of the framework caller path that crashes during its call '
                '(SIGSEGV) is classified by the coordinator, reaped and never observed; no process or shared-memory segment is '
                'left; no failed row counts work; a normal shutdown keeps the result'}

def _norm_problems(problems,limit=20):return [str(p)[:300] for p in problems[:limit]]

# ---- B04: actual C concurrency ----

def parse_trace(lines):
    """The pool trace of a trace program: {'serial': result or None, 'sections': {workers: {'threads', 'max_inflight',
    'submitted', 'executed', 'result', 'spans': [(thread, start_ns, end_ns, task, cpu_ns)], 'lines': [...]}}, 'problems'}.
    A header line opens a section; span lines belong to the last section. Any other line, a repeated section or more
    than MAX_TRACE_LINES lines is a problem."""
    out={'serial':None,'sections':{},'problems':[]};current=None
    if not isinstance(lines,list) or len(lines)>MAX_TRACE_LINES:
        out['problems'].append('trace is not a bounded list of lines');return out
    for number,line in enumerate(lines,1):
        if not isinstance(line,str):out['problems'].append(f'line {number}: not text');continue
        m=HEADER_RE.fullmatch(line)
        if m:
            w=int(m.group(1))
            if m.group(2) is None:
                if w!=0 or out['serial'] is not None or m.group(7) is None:out['problems'].append(f'line {number}: a serial line needs workers 0 and a result, once')
                else:out['serial']=m.group(7)
                current=None;continue
            if w==0 or w in out['sections']:out['problems'].append(f'line {number}: workers {w} repeated or zero');current=None;continue
            current={'threads':int(m.group(3)),'max_inflight':int(m.group(4)),'submitted':int(m.group(5)),'executed':int(m.group(6)),
                     'result':m.group(7),'spans':[],'lines':[line]}
            out['sections'][w]=current;continue
        s=SPAN_RE.fullmatch(line)
        if s and current is not None:current['spans'].append(tuple(int(x) for x in s.groups()));current['lines'].append(line);continue
        out['problems'].append(f'line {number}: not a trace line')
    return out

def check_concurrency(doc,workers,envelope):
    """B04 for one traced run on `workers` workers: doc = {'exit', 'trace': the header and span lines of that run,
    'affinity', 'cgroup_cpu_usec', 'wall_ns'}. Returns {'status', 'reasons', 'busy_threads', 'overlap', 'tasks'}."""
    reasons=[];env=envelope or {}
    if doc.get('exit')!=0:reasons.append(f"trace program exit {doc.get('exit')}")
    if env.get('multicore')!='PASS':reasons.append('no approved multicore envelope')
    if type(env.get('cpus')) is not int or env['cpus']<workers:reasons.append(f'envelope cpus below {workers} workers')
    parsed=parse_trace(list(doc.get('trace') or []));reasons+=parsed['problems'][:5]
    sec=parsed['sections'].get(workers)
    if sec is None or len(parsed['sections'])!=1:
        reasons.append(f'no single trace section for {workers} workers')
        return {'status':'FAIL','reasons':_norm_problems(reasons),'busy_threads':0,'overlap':False,'tasks':0}
    spans=sec['spans'];tasks=[s[3] for s in spans];threads={s[0] for s in spans}
    if sec['submitted']<1 or sec['executed']!=sec['submitted'] or len(spans)!=sec['submitted'] or sorted(tasks)!=list(range(sec['submitted'])):
        reasons.append('task IDs are not complete and unique')
    if sec['threads']!=len(threads):reasons.append('header thread count differs from the spans')
    if len(threads)>workers or any(t>=workers for t in threads):reasons.append('more threads than workers')
    if sec['max_inflight']>2*workers:reasons.append('in-flight tasks above 2 x workers')
    if type(doc.get('affinity')) is not int or doc['affinity']<workers:reasons.append('CPU affinity below the worker count')
    if any(s[2]<s[1] for s in spans):reasons.append('a task ends before it starts')
    cpu={t:sum(s[4] for s in spans if s[0]==t) for t in threads};busy=sum(1 for v in cpu.values() if v>0)
    total=sum(cpu.values());cg=doc.get('cgroup_cpu_usec')
    if type(cg) is not int or total>cg*1000+CPU_SLACK_NS:reasons.append('task thread CPU above the cgroup CPU')
    overlap=any(a[0]!=b[0] and a[1]<b[2] and b[1]<a[2] for i,a in enumerate(spans) for b in spans[i+1:])
    if workers==1:
        if len(threads)!=1:reasons.append('one worker used more than one identity')
    else:
        if busy<2:reasons.append('fewer than two worker identities spent CPU')
        if not overlap:reasons.append('no overlapping execution across workers')
    return {'status':'FAIL' if reasons else 'PASS','reasons':_norm_problems(reasons),'busy_threads':busy,'overlap':overlap,'tasks':len(tasks)}

def overlap_sections(doc):
    """The per-worker docs of one native-overlap record (one run of the trace program) and the serial result."""
    parsed=parse_trace(list(doc.get('lines') or []))
    base={k:doc.get(k) for k in ('exit','affinity','cgroup_cpu_usec','wall_ns')}
    return {w:dict(base,trace=list(s['lines'])) for w,s in parsed['sections'].items()},parsed

def _serialized(section_doc):
    """The serial-dispatch masquerade of one real section: every span on thread 0, one after the other."""
    parsed=parse_trace(section_doc['trace']);w,sec=next(iter(parsed['sections'].items()));t=0;lines=[]
    for s in sec['spans']:
        d=max(1,s[2]-s[1]);lines.append(f'0 {t} {t+d} {s[3]} {s[4]}');t+=d
    head=sec['lines'][0].replace(f" threads={sec['threads']} ",' threads=1 ')
    return dict(section_doc,trace=[head]+lines)

def b04_project(doc,envelope):
    """B04 for one project's native-overlap record: (status, detail)."""
    sections,parsed=overlap_sections(doc);detail={'sections':{},'problems':list(parsed['problems'][:5])}
    want=[w for w in (1,2,4) if type((envelope or {}).get('cpus')) is int and w<=envelope['cpus']]
    if (envelope or {}).get('multicore')!='PASS' or 2 not in want:
        return 'BLOCKED',dict(detail,reason='no approved multicore envelope: multicore evidence cannot qualify')
    for w in want:
        if w not in sections:detail['problems'].append(f'no trace section for {w} workers');continue
        r=check_concurrency(sections[w],w,envelope);detail['sections'][w]={k:r[k] for k in ('status','busy_threads','overlap','tasks')}
        detail['problems']+=[f'{w} workers: {x}' for x in r['reasons']]
    results={s['result'] for s in parsed['sections'].values()}
    if parsed['serial'] is None or results!={parsed['serial']}:detail['problems'].append('a traced result differs from the serial result')
    top=max(w for w in want if w in sections) if any(w in sections for w in want) else None
    if top is not None and top>=2:
        serial=check_concurrency(_serialized(sections[top]),top,envelope)['status']
        pinned=check_concurrency(dict(sections[top],affinity=1),top,envelope)['status']
        detail['masquerades']={'serial-dispatch':serial,'one-cpu-affinity':pinned}
        if serial!='FAIL' or pinned!='FAIL':detail['problems'].append('a masquerade of the real trace was not rejected')
    else:detail['problems'].append('no multicore section to test the masquerades')
    detail['problems']=_norm_problems(detail['problems']);return ('PASS' if not detail['problems'] else 'FAIL'),detail

# ---- B06: equal work and the correctness oracle ----

def required_mutations(root,project_dir):
    """The generic mutations plus every name of the project protocol `agreement_mutations` (each once, in order)."""
    extra=bm.protocol_value(root,project_dir,'agreement_mutations',[]) or []
    return list(AGREEMENT_MUTATIONS)+[m for m in extra if m not in AGREEMENT_MUTATIONS]

def check_agreement_controls(doc,required=AGREEMENT_MUTATIONS):
    """B06: the control C result is eligible; every required mutation changed the result and is ineligible."""
    problems=[];ctl=(doc or {}).get('control') or {}
    if ctl.get('eligible') is not True:problems.append('the unmutated C result is not eligible')
    muts=(doc or {}).get('mutations') or {}
    for name in required:
        m=muts.get(name)
        if not isinstance(m,dict):problems.append(f'{name}: not applied');continue
        if m.get('changed') is not True:problems.append(f'{name}: the result did not change')
        if m.get('eligible') is not False:problems.append(f'{name}: the mutated result stays eligible')
    return problems

# ---- B10 note: one row, one chunk ----

def check_one_row_one_chunk(observations):
    """A pooled row of one work unit (a one-row request) has exactly one chunk of one row."""
    problems=[]
    for o in observations:
        p=o.get('pool')
        if o.get('work_units')!=1 or not isinstance(p,dict) or 'chunk_sizes' not in p:continue
        if p.get('chunks')!=1 or p.get('chunk_sizes')!=[1]:problems.append(f"{o.get('trial_id')}: a one-row request has more than one chunk")
    return problems

# ---- B07 / P02: fair build and resource context ----

COMPARED=('dataset_sha256','scope','tier','selector','panel','dataset','case_version','algorithm','envelope')

def check_comparison_context(contexts):
    """B07, P02: every compared key agrees across the contexts; each context has a release build (no flag problem), the
    loaded GLib of the build and a complete workload inventory."""
    problems=[]
    if len(contexts)<2:problems.append('fewer than two comparison contexts')
    for k in COMPARED:
        if len({json.dumps(c.get(k),sort_keys=True) for c in contexts})>1:problems.append(f'{k} differs between compared rows')
    for i,c in enumerate(contexts):
        build=c.get('build');glib=c.get('glib')
        if not isinstance(build,dict):problems.append(f'context {i}: no build identity')
        elif build.get('problems'):problems.append(f"context {i}: not a release build ({str(build['problems'][0])[:120]})")
        if not isinstance(glib,dict):problems.append(f'context {i}: no GLib identity')
        elif glib.get('loaded')!=glib.get('build'):problems.append(f'context {i}: the loaded GLib differs from the build')
        if c.get('inventory_complete') is not True:problems.append(f'context {i}: workload inventory incomplete')
    return problems

def comparison_contexts(run,plan,observations,native,policy):
    """One context per comparison group (variant, workers, route) of the first caller point of a real run."""
    import bench
    caller=[o for o in observations if o.get('scope')=='caller' and not o.get('warmup')]
    point=caller[0]['point'] if caller else None;env=run.get('envelope') or {};seen={};complete=not bench.check_completeness(plan,observations,policy)
    rec=run.get('native') or {}
    for o in caller:
        if o['point']!=point:continue
        key=(o['variant'],str(o['workers']),o.get('route'))
        if key in seen:continue
        c_row=str(o['variant']).startswith('c-')
        seen[key]={'row':'/'.join(str(x) for x in key),'dataset_sha256':(run.get('dataset') or {}).get('sha256'),'scope':o['scope'],'tier':o['tier'],
                   'selector':o.get('selector','all'),'panel':o.get('panel'),
                   'dataset':{k:(run.get('dataset') or {}).get(k) for k in ('kind','size','seed','rows')},'case_version':run.get('case_version'),
                   'algorithm':(run.get('plan') or {}).get('project_identity'),
                   'envelope':{'cpus':env.get('cpus'),'cpuset':env.get('cpuset'),'memory_bytes':policy['envelope']['memory_bytes']},
                   'build':{'problems':list(((native or {}).get('flags') or {}).get('problems') or [])} if c_row else {'problems':[]},
                   'glib':{'build':((native or {}).get('glib') or {}).get('sha256'),'loaded':rec.get('glib_sha256')} if c_row else {'build':None,'loaded':None},
                   'inventory_complete':complete}
    return list(seen.values())

# ---- B08 / B13-echo: caller boundary, cold and warm separation ----

def _labels(labels):return labels if labels is not None else bm.load_policy(ROOT)['routes']

def check_caller_scope(observations,phases,labels=None,routes=(),plan=None):
    """B08: every non-warmup C caller row has the phases prepare, transport, work and materialize, a result digest (it
    ends after result receipt), its route with that route's policy label and copied bytes; a cold row includes the worker
    startup inside its interval (pool_start, or a process route whose processes grew during the interval) and a process
    route reports its teardown apart (a teardown phase of the same trial); a warm row starts nothing inside its interval
    and reports its startup as a pool_start phase; an in-process row is warm only; a row that records request and
    response masks has equal masks; Python controls carry no route; a Python direct control exists, and a Python process
    control too when a C row uses more than one worker; every route of `routes` has a C row; with `plan`, each C row
    keeps its planned route (no fallback)."""
    labels=_labels(labels);problems=[]
    rows=[o for o in observations if o.get('scope')=='caller' and not o.get('warmup')]
    c=[o for o in rows if str(o.get('variant','')).startswith('c-')];py=[o for o in rows if str(o.get('variant','')).startswith('py-')]
    planned={t['trial_id']:t.get('route') for s in (plan or {}).get('sessions',[]) for t in s['trials']}
    starts={(p.get('variant'),p.get('workers'),p.get('route')) for p in phases if p.get('phase')=='pool_start' and p.get('mode')=='warm'}
    teardowns={p.get('trial_id') for p in phases if p.get('phase')=='teardown'}
    for o in c:
        tid=o.get('trial_id');ph=o.get('phases') or {};route=o.get('route');mode=o.get('mode')
        missing=[k for k in C_PHASES if type(ph.get(k)) is not int]
        if missing:problems.append(f"{tid}: the interval misses {', '.join(missing)}")
        if not (isinstance(o.get('result_sha256'),str) and SHA256_RE.fullmatch(o['result_sha256'])):problems.append(f'{tid}: no result digest (ends before result receipt)')
        if route not in labels:problems.append(f'{tid}: no route')
        elif o.get('route_label')!=labels[route]:problems.append(f'{tid}: the route label is not the label of route {route}')
        if type(o.get('copied_bytes')) is not int or o['copied_bytes']<0:problems.append(f'{tid}: no copy accounting')
        if plan is not None and tid in planned and planned[tid]!=route:problems.append(f'{tid}: route {route} replaces the planned route {planned[tid]}')
        if route=='inproc' and mode!='warm':problems.append(f'{tid}: an in-process row is not warm')
        if mode=='cold':
            grew=route in PROCESS_ROUTES and type(o.get('pids_start')) is int and type(o.get('pids_end')) is int and o['pids_end']>o['pids_start']
            if ph.get('pool_start') is None and not grew:problems.append(f'{tid}: a cold row without worker startup inside the interval')
            if route in PROCESS_ROUTES and ph.get('pool_start') is None and tid not in teardowns:problems.append(f'{tid}: a cold row without its teardown phase')
        if mode=='warm':
            if ph.get('pool_start') is not None:problems.append(f'{tid}: a warm row started its worker inside the interval')
            if (o.get('variant'),o.get('workers'),route) not in starts:problems.append(f'{tid}: warm startup not reported as a separate phase')
        if ('request_mask' in o or 'response_mask' in o) and o.get('request_mask')!=o.get('response_mask'):problems.append(f'{tid}: the response mask differs from the request mask')
    for o in py:
        if o.get('route') is not None or o.get('route_label') is not None or o.get('copied_bytes') is not None:problems.append(f"{o.get('trial_id')}: a Python control carries a route")
    if c and not any(o.get('variant') in DIRECT_PY and o.get('workers')=='direct' for o in py):problems.append('Python direct control missing')
    if any(o.get('workers') not in ('direct',1) for o in c) and not any(o.get('variant')=='py-processes' for o in py):problems.append('Python process control missing')
    for r in routes:
        if not any(o.get('route')==r for o in c):problems.append(f'route {r}: no caller row')
    return problems

def echo_cells(case):
    """The (variant, workers, mode, route) cells of an echo case: each implemented C variant of the manifest, each of its
    worker counts, each mode of a caller point that names it and each of its routes (in-process rows only warm)."""
    cells=set()
    for v in case.get('variants',[]):
        if v.get('language')!='c' or v.get('status')!='implemented':continue
        modes={m for p in case.get('points',[]) if p.get('scope')=='caller' and v['id'] in p.get('variants',[]) for m in p.get('modes',[])}
        for w in v.get('workers',[]):
            for r in v.get('routes') or ['stdio']:
                for m in modes:
                    if not (r=='inproc' and m!='warm'):cells.add((v['id'],w,m,r))
    return cells

def check_echo_coverage(observations,case,labels=None):
    """B13-echo: every cell of echo_cells(case) has an eligible non-warmup caller row with its route label."""
    labels=_labels(labels);problems=[];cells=echo_cells(case)
    if not cells:problems.append('the echo case declares no C caller cell')
    have={(o.get('variant'),o.get('workers'),o.get('mode'),o.get('route')) for o in observations
          if o.get('scope')=='caller' and not o.get('warmup') and o.get('eligible') is True and o.get('route') in labels and o.get('route_label')==labels[o['route']]}
    for cell in sorted(cells,key=str):
        if cell not in have:problems.append('echo cell without a labeled row: '+'/'.join(str(x) for x in cell))
    return problems

# ---- B11: pool ownership and lifecycle ----

SANITIZERS=('asan','ubsan','msan','tsan')

def check_pool_lifecycle(foundation_report,project_reports=()):
    """B11: the foundation parallel lane PASS with faults labeled simulated and at least three seeded mutants, each
    detected (bad PASS) with its control PASS; the foundation profiles asan, ubsan, msan and tsan PASS; each project
    report has the gates asan, ubsan, msan and tsan PASS."""
    problems=[];fr=foundation_report or {};par=fr.get('parallel') or {}
    if par.get('status')!='PASS':problems.append('foundation parallel lane is not PASS')
    faults=par.get('faults') or {}
    if faults.get('label')!='simulated' or faults.get('status')!='PASS':problems.append('pool fault injection is not PASS with the label simulated')
    mutants=par.get('mutants') or []
    if len(mutants)<3:problems.append('fewer than three seeded pool mutants')
    for m in mutants:
        if not isinstance(m,dict) or m.get('bad')!='PASS' or m.get('control')!='PASS':problems.append(f"pool mutant {(m or {}).get('id')}: not detected with its control")
    profiles={p.get('profile') or p.get('name'):p.get('status') for p in fr.get('profiles') or [] if isinstance(p,dict)}
    for s in SANITIZERS:
        if profiles.get(s)!='PASS':problems.append(f'foundation profile {s} is not PASS')
    for rep in project_reports:
        gates={g.get('name'):g.get('status') for g in (rep or {}).get('gates') or [] if isinstance(g,dict)}
        for s in SANITIZERS:
            if gates.get(s)!='PASS':problems.append(f"project {(rep or {}).get('project_dir')}: gate {s} is not PASS")
    return problems

# ---- B16: failure, cancellation and cleanup ----

def check_incomplete_never_counts(observations):
    """B16: a row that is not eligible counts no work."""
    return [f"{o.get('trial_id')}: an ineligible row counts {o.get('work_units')} work units" for o in observations
            if o.get('eligible') is not True and isinstance(o.get('work_units'),int) and o['work_units']>0]

def caller_crash_problems(cc):
    """EX13-A04: the caller crash runs through the framework caller-child path (the coordinator CallerChild of a
    benchlab.trial child, the fault a SIGSEGV to that child during its call); its classification is the coordinator's
    failure_row of the ChildExited error (child exit -11), the child is reaped, and the framework made no observation of
    the call (so nothing can count). A record without that path is not run, which fails the check."""
    if not isinstance(cc,dict):return ['caller-crash: not run']
    if cc.get('not_run'):return ['caller-crash: not run (the framework caller-child path is absent)']
    row=cc.get('framework_row') or {};problems=[]
    if row.get('error_type')!='ChildExited' or row.get('child_exit_code')!=-SIGSEGV:problems.append('caller-crash: the framework did not classify the crashed caller child')
    if cc.get('reaped') is not True:problems.append('caller-crash: the caller child was not reaped')
    if cc.get('observations')!=0:problems.append('caller-crash: the framework made an observation of the crashed call')
    return problems

def check_stub_classes(doc):
    """The stub-worker part of check_failure_classes (without the caller crash)."""
    return [p for p in check_failure_classes(doc) if not p.startswith('caller-crash')]

def check_failure_classes(doc):
    """B16 on a failure-controls record: each failure class has its classification, its process reaped and no counted
    work; the crash cases end by SIGSEGV; the caller crash follows caller_crash_problems; no child process and no
    shared-memory segment is left; a normal shutdown keeps the result."""
    problems=[];cases={c.get('case'):c for c in (doc or {}).get('cases') or [] if isinstance(c,dict)}
    for name,want in FAILURE_CLASSES.items():
        c=cases.get(name)
        if c is None:problems.append(f'{name}: not run');continue
        if c.get('class') not in want:problems.append(f"{name}: classified {c.get('class')}, expected {' or '.join(want)}")
        if c.get('reaped') is not True:problems.append(f'{name}: the worker was not reaped')
        if c.get('eligible') is not False or c.get('work_units')!=0:problems.append(f'{name}: a failed call counts work')
    if (cases.get('crash') or {}).get('returncode')!=-SIGSEGV:problems.append('crash: the worker did not end by SIGSEGV')
    problems+=caller_crash_problems(cases.get('caller-crash'))
    normal=(doc or {}).get('normal') or {}
    if normal.get('result_kept') is not True or normal.get('returncode')!=0:problems.append('a normal shutdown did not keep its result')
    if (doc or {}).get('leftover_processes'):problems.append('a child process is left after the failure controls')
    if (doc or {}).get('leftover_shm'):problems.append('a shared-memory segment is left after the failure controls')
    return problems

# ---- P04: concurrency or launch bypass ----

def check_launch(observations):
    """P04 host-execution: every row ran under a framework runner in its bench container."""
    return [f"{o.get('trial_id')}: runner {o.get('runner')!r} is not a framework runner" for o in observations if o.get('runner') not in RUNNERS]

def check_pool_request(plan,policy):
    """P04 unlimited-pool-or-queue: every pooled row asks for a policy worker count within the envelope and a window of
    at most window_per_worker x workers."""
    problems=[];cpus=((plan or {}).get('envelope') or {}).get('cpus');allowed=policy['pools']['workers'];per=policy['pools']['window_per_worker']
    rows=(plan or {}).get('rows') or [t for s in (plan or {}).get('sessions',[]) for t in s['trials']]
    for r in rows:
        w=r.get('workers')
        if w=='direct':continue
        if isinstance(w,bool) or not isinstance(w,int) or w not in allowed:problems.append(f"{r.get('trial_id',r.get('variant'))}: worker count {w!r} outside the policy");continue
        if type(cpus) is not int or w>cpus:problems.append(f"{r.get('trial_id',r.get('variant'))}: {w} workers above the envelope")
        if 'window' in r and (type(r['window']) is not int or r['window']>per*w):problems.append(f"{r.get('trial_id',r.get('variant'))}: an unbounded queue window")
    return problems

def check_native_identity(plan_native,native):
    """P04 unsafe-native-loading: the plan's binary and GLib digests are exactly the run build's."""
    want={n:b.get('sha256') for n,b in ((native or {}).get('binaries') or {}).items()}
    want[((native or {}).get('glib') or {}).get('name',GLIB_NAME)]=((native or {}).get('glib') or {}).get('sha256')
    got=dict(plan_native or {})
    return [] if got==want and all(isinstance(v,str) and SHA256_RE.fullmatch(v) for v in got.values()) else ['the planned native binaries differ from the run build']

def check_inproc_isolation(observations):
    """P04 unsafe-native-loading: every in-process row loaded its library in a caller child, never in the coordinator."""
    problems=[]
    for o in observations:
        if o.get('route')!='inproc':continue
        lp=o.get('load_process')
        if not isinstance(lp,dict) or lp.get('role')!='caller' or type(lp.get('pid')) is not int:problems.append(f"{o.get('trial_id')}: the in-process load was not in a caller child")
    return problems

def check_process_cleanup(phases):
    """P04 unmanaged-subprocess: a teardown never adds processes; the teardowns of one trial on a process route remove at
    least one process together; and each warm startup that started processes is followed by a teardown of the same group
    that removes at least as many."""
    problems=[];rows=list(phases);removed={}
    for p in rows:
        if p.get('phase')!='teardown':continue
        if type(p.get('pids_start')) is not int or type(p.get('pids_end')) is not int or p['pids_end']>p['pids_start']:
            problems.append(f"{p.get('trial_id')}: a teardown left processes");continue
        if p.get('route') in PROCESS_ROUTES:removed[p.get('trial_id')]=removed.get(p.get('trial_id'),0)+p['pids_start']-p['pids_end']
    problems+=[f'{tid}: the teardown of a process route removed no process' for tid,n in removed.items() if n<1]
    for i,p in enumerate(rows):
        if p.get('phase')!='pool_start' or type(p.get('pids_start')) is not int or type(p.get('pids_end')) is not int:continue
        started=p['pids_end']-p['pids_start']
        if started<=0:continue
        key=(p.get('variant'),p.get('workers'),p.get('mode'),p.get('route'))
        later=[q for q in rows[i+1:] if q.get('phase')=='teardown' and (q.get('variant'),q.get('workers'),q.get('mode'),q.get('route'))==key
               and type(q.get('pids_start')) is int and type(q.get('pids_end')) is int]
        if not any(q['pids_start']-q['pids_end']>=started for q in later):problems.append(f"{p.get('trial_id')}: started processes without a teardown that removes them")
    return problems

def check_affinity(plan_envelope,run_envelope,affinity=None):
    """P04 changed-affinity: the run's CPU set is the planned one and the job's affinity covers the envelope CPUs."""
    problems=[];pe=plan_envelope or {};re_=run_envelope or {}
    if pe.get('cpuset')!=re_.get('cpuset') or pe.get('cpus')!=re_.get('cpus'):problems.append('the run CPU set differs from the planned envelope')
    if affinity is not None and affinity!=re_.get('cpus'):problems.append(f'the job affinity {affinity} differs from the envelope CPUs')
    return problems

def thread_api_findings(root,name):
    """P04 unauthorized-thread-api: the AST foundation-use findings of a minimal first-party function that calls `name`
    (qualification.ast_foundation_uses with the protected foundation API policy and source inventory)."""
    import qualification
    policy=read_json(Path(root)/'safety/foundation-api-policy.json');inventory=read_json(Path(root)/'safety/source-inventory.json')['files']
    call={'kind':'CallExpr','inner':[{'kind':'ImplicitCastExpr','inner':[{'kind':'DeclRefExpr','referencedDecl':{'kind':'FunctionDecl','name':name}}]}]}
    node={'inner':[{'kind':'FunctionDecl','name':'probe','loc':{},'inner':[{'kind':'CompoundStmt','inner':[call]}]}]}
    return qualification.ast_foundation_uses(node,policy,'src/probe.c',inventory)

# ---- P16: no-op or gamed optimizer ----

def check_replay(notes):
    """P16 reuse-answer: two different inputs never give the same result digest."""
    by={}
    for n in notes:by.setdefault(n.get('result_sha256'),set()).add(n.get('seed'))
    return [f'result {d[:12]} reused for seeds {sorted(s)}' for d,s in by.items() if len(s)>1]

def check_no_op(notes):
    """P16 no-op-native-kernel: a kernel row whose digest differs from the reference is never eligible."""
    return [f"{n.get('case')}: a kernel result that differs from the reference is eligible" for n in notes if n.get('digest_match') is not True and n.get('eligible') is True]

def check_skipped_work(notes):
    """P16 skip-useful-work: a row that processed fewer records than planned is never eligible."""
    return [f"{n.get('trial_id','row')}: {n.get('records')} of {n.get('planned_rows')} records is eligible" for n in notes
            if n.get('eligible') is True and (type(n.get('records')) is not int or n['records']<n.get('planned_rows',0))]

def check_result_consumption(notes):
    """P16 removed-result-consumption: a row whose self-reduction does not match is never eligible."""
    return [f"{n.get('trial_id','row')}: an unmatched self-reduction is eligible" for n in notes if n.get('self_reduction_match') is not True and n.get('eligible') is True]

def check_selector_counters(notes):
    """P16 selector-overcompute and selector-no-op: an eligible per-selector row evaluated no unselected part, evaluated
    the selected part and agrees on fresh inputs."""
    problems=[]
    for n in notes:
        if n.get('eligible') is not True:continue
        if n.get('unselected_evals')!=0:problems.append(f"selector {n.get('selector')}: evaluations of an unselected part")
        if type(n.get('selected_evals')) is not int or n['selected_evals']<=0:problems.append(f"selector {n.get('selector')}: no evaluation of the selected part")
        if n.get('agreement') is not True:problems.append(f"selector {n.get('selector')}: no agreement on fresh inputs")
    return problems

SELECTOR_LEDGER='EX13-P16-SELECTOR-01'

def kernel_notes(doc):
    """P16 notes of the real kernel controls of the agreement-controls job: the real C kernel ran once on the job's
    synthetic rows, and the framework kernel verifier (container/bench_native_job.py KERNEL_VERIFY_CODE) checked three
    outputs: the real one with the kernel's canonical digest (control), an output of the same length that no kernel
    computed (no-op) and the real one with its canonical digest removed (removed-consumption). Each note keeps the
    verifier's verdict: eligible = validated and canonical_ok, as run_native_kernel decides."""
    k=(doc or {}).get('kernel') or {};notes=k.get('notes') or {}
    return {name:dict(n,records=n.get('records'),planned_rows=k.get('planned_rows')) for name,n in notes.items() if isinstance(n,dict)}

# ---- the suites and additions on real evidence ----

def _sub(parent,variant,rejected,control,evidence,reason):
    import bench
    return bench._sub(parent,NAMES[parent],variant,bool(rejected),bool(control),list(evidence),reason)

def _row(parent,variant,fn,reason,evidence=()):
    """One addition: fn() -> (rejected, control). An exception is FAIL with its type, never PASS or BLOCKED."""
    try:rejected,control=fn()
    except Exception as exc:          # the check could not prove its property
        return _sub(parent,variant,False,False,evidence,f'{reason}; the check raised {type(exc).__name__}: {str(exc)[:160]}')
    return _sub(parent,variant,rejected,control,evidence,reason)

def _status(values):
    import bench
    return bench.selftest_status(['PASS' if v is True else 'FAIL' if v is False else v for v in values])

def native_projects(root,project=None):
    """[(project dir, bench.json declaration, case id, C variant)] of every example project of the scope (bench.example_projects:
    the framework examples, or the explicit `project`) with a native declaration: the first case of the project whose
    manifest has an implemented C variant."""
    import bench
    out=[]
    for p in bench.example_projects(root,project):
        decl=bm.project_bench(root,p)
        if not decl or 'native' not in decl:continue
        for cid in decl['cases']:
            case=bm.load_case(root,cid,p)
            v=next((x for x in case['variants'] if x['language']=='c' and x['status']=='implemented'),None)
            if v is not None:out.append((p,decl,cid,v));break
    return out

def real_run(root,project,case_id):
    """One real bench run (smoke, synthetic:small) of the case: (exit code, run directory or None)."""
    import argparse, bench
    try:rc,row=bench._quiet(bench.run_cmd,root,argparse.Namespace(case=case_id,project=project,mode='smoke',dataset=SMOKE_DATASET,calibrate=None,plan=None,format='json'))
    except GateError:return 2,None         # a refused run (BLOCKED) gives no evidence
    run_id=row.get('run_id')
    if not isinstance(run_id,str) or not re.fullmatch(r'[0-9a-f]{32}',run_id):return rc,None
    return rc,Path(root)/'artifacts/bench'/run_id

def load_run(run_dir):
    import bench
    d=Path(run_dir)
    return {'plan':read_json(d/'plan.json'),'run':read_json(d/'run.json'),'native':read_json(d/'native.json') if (d/'native.json').is_file() else None,
            'observations':bench.read_jsonl(d/'observations.jsonl'),'phases':bench.read_jsonl(d/'phases.jsonl'),'dir':str(d)}

def run_jobs(root,run_dir,project,decl,case_id,variant,ev,policy):
    """The coordinator jobs of one project in one bench session: native-overlap (with a declared trace program) and
    agreement-controls, on the binaries of the real run's build. Returns {job: (status, record or None, evidence path)}."""
    import shutil, bench, bench_native
    out={};deadline=policy['job_deadlines']['smoke'];copies={}
    # A session restores only files of its own run directory: the binaries of the real run's build are copied there, and
    # each restore still checks the bytes against the sha256 of that build (native.json).
    for name,b in ev['native']['binaries'].items():
        dst=Path(run_dir)/'native'/name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(b['path'],dst);copies[name]=dict(b,path=str(dst))
    native=dict(ev['native'],binaries=copies);s=bench.BenchSession(root,run_dir)
    restore=tuple(bench_native.native_restore(native));plan_native=bench_native.native_plan(native)
    base={'schema_version':1,'run_id':Path(run_dir).name,'project_dir':project,'native':plan_native,'deadline_seconds':deadline}
    try:
        trace=(decl['native'] or {}).get('trace')
        if trace:
            r=s.job(dict(base,job='native-overlap',trace=dict(trace)),'native-overlap',deadline,restore=restore);row=bench.last_json(r['output'])
            doc=None
            if bench.passed(r) and row.get('status')=='PASS':doc=read_json(s.fetch('bench/out/overlap.json',Path(run_dir)/'overlap.json'))
            out['native-overlap']=(row.get('status','FAIL'),doc,r['evidence_path'])
        r=s.job(dict(base,job='agreement-controls',case_manifest=bm.container_case_path(case_id,project,root),variant=variant['id'],
                     workers=str(variant['workers'][0]),route=(variant.get('routes') or ['stdio'])[0],rows=AGREEMENT_ROWS,seed=int(ev['plan']['seed']),
                     native_kernel=dict(decl['native']['kernel']),     # EX13-A02: the real kernel controls
                     mutations=required_mutations(root,project)[len(AGREEMENT_MUTATIONS):]),'agreement-controls',deadline,restore=restore)
        row=bench.last_json(r['output']);doc=None
        if bench.passed(r) and row.get('status')=='PASS':doc=read_json(s.fetch('bench/out/agreement-controls.json',Path(run_dir)/'agreement-controls.json'))
        out['agreement-controls']=(row.get('status','FAIL'),doc,r['evidence_path'])
    finally:s.close()
    return out

def failure_job(root,run_dir,policy):
    """The failure-controls job (framework stub worker; no project): (status, record or None, evidence path)."""
    import bench
    s=bench.BenchSession(root,run_dir);deadline=policy['job_deadlines']['smoke']
    try:
        sizes=policy['sizes']      # EX13-A04: the caller crash runs a caller child of the framework control case
        r=s.job({'schema_version':1,'job':'failure-controls','run_id':Path(run_dir).name,'deadline_seconds':deadline,
                 'case_manifest':bm.container_case_path(CRASH_CASE,None,root),'dataset':{'kind':'synthetic','size':'tiny','seed':CRASH_SEED,'sha256':None,'rows':sizes['tiny']},
                 'rows':sizes['tiny'],'sizes':sizes},'failure-controls',deadline)
        row=bench.last_json(r['output']);doc=None
        if bench.passed(r) and row.get('status')=='PASS':doc=read_json(s.fetch('bench/out/failure-controls.json',Path(run_dir)/'failure-controls.json'))
        return row.get('status','FAIL'),doc,r['evidence_path']
    finally:s.close()

def _fail_suite(name,reason):return {'status':'FAIL','property':PROPERTY[name],'reason':str(reason)[:300]}

def b07_contexts(ev,policy):return comparison_contexts(ev['run'],ev['plan'],ev['observations'],ev['native'],policy)

def p02_additions(root,ev,policy,evidence):
    """P02 on the real comparison contexts of one run: each variant mutates a copy; its control is the unmutated set."""
    import bench_native, bench
    ctx=b07_contexts(ev,policy);control=bool(ctx) and not check_comparison_context(ctx)
    c_index=next((i for i,c in enumerate(ctx) if c['glib']['build'] is not None),None)
    def mutated(edit):
        m=copy.deepcopy(ctx);edit(m);return bool(check_comparison_context(m))
    project_src='/src/'+str(ev['plan'].get('project_dir') or '').rstrip('/')+'/src/x.c'
    def sanitized():
        flags=bench_native.check_native_flags([['clang','-O2','-ffp-contract=off','-fsanitize=address','-c',project_src]],project_src.rsplit('/src/x.c',1)[0])
        clean=bench_native.check_native_flags([['clang','-O2','-ffp-contract=off','-c',project_src]],project_src.rsplit('/src/x.c',1)[0])
        return mutated(lambda m:m[c_index]['build'].update(problems=flags)) and bool(flags),control and not clean and c_index is not None
    def incomplete():
        obs=[o for o in ev['observations'] if o['trial_id']!=next(o['trial_id'] for o in ev['observations'] if not o['warmup'] and o['scope']=='caller')]
        m=comparison_contexts(ev['run'],ev['plan'],obs,ev['native'],policy);return bool(check_comparison_context(m)) and bool(bench.check_completeness(ev['plan'],obs,policy)),control
    edits={'wrong-dependency':lambda m:m[c_index]['glib'].update(loaded='0'*64),
           'hidden-algorithm-or-precision-change':lambda m:m[-1].update(case_version=(m[-1]['case_version'] or 0)+1,algorithm='f'*64),
           'different-cpu-envelope':lambda m:m[-1].update(envelope=dict(m[-1]['envelope'],cpus=(m[-1]['envelope']['cpus'] or 0)+1)),
           'different-selector-panel-or-dataset':lambda m:m[-1].update(selector='other-sel',dataset=dict(m[-1]['dataset'],seed=1))}
    rows=[_row('P02','sanitized-or-debug-artifact',sanitized,'an instrumented or debug build is never comparable',evidence)]
    for v in ('wrong-dependency','hidden-algorithm-or-precision-change'):
        rows.append(_row('P02',v,lambda e=edits[v]:(c_index is not None and mutated(e),control),'a changed dependency or algorithm is never comparable',evidence))
    rows.append(_row('P02','incomplete-workload-inventory',incomplete,'an incomplete workload inventory is never comparable',evidence))
    for v in ('different-cpu-envelope','different-selector-panel-or-dataset'):
        rows.append(_row('P02',v,lambda e=edits[v]:(mutated(e),control),'a different envelope, selector or dataset is never comparable',evidence))
    return ctx,control,rows

def b08_mutants(ev,labels,routes):
    """B08 scope mutants of the real rows; each must be rejected."""
    obs=ev['observations'];phases=ev['phases'];plan=ev['plan']
    first=next((i for i,o in enumerate(obs) if o['scope']=='caller' and not o['warmup'] and str(o['variant']).startswith('c-')),None)
    inproc=next((i for i,o in enumerate(obs) if o['scope']=='caller' and not o['warmup'] and o.get('route')=='inproc'),None)
    def m(edit):
        x=copy.deepcopy(obs);edit(x);return bool(check_caller_scope(x,phases,labels,routes,plan))
    out={}
    if first is not None:
        out['omitted-transport']=m(lambda x:x[first]['phases'].pop('transport'))
        out['ends-before-result']=m(lambda x:x[first].update(result_sha256=None))
        out['mislabeled-route']=m(lambda x:x[first].update(route_label='a label of another route'))
        out['no-copy-accounting']=m(lambda x:x[first].update(copied_bytes=None))
        out['route-fallback']=m(lambda x:x[first].update(route=next(r for r in labels if r!=x[first]['route']),route_label=labels[next(r for r in labels if r!=x[first]['route'])]))
    out['python-direct-control-missing']=m(lambda x:x.__setitem__(slice(None),[o for o in x if not str(o['variant']).startswith('py-')]))
    if inproc is not None:out['cold-in-process']=m(lambda x:x[inproc].update(mode='cold'))
    return out

def b13_fixture(labels):
    """The B13-echo fixture control: a synthetic echo case and rows that cover every cell; dropping one cell is rejected."""
    case={'variants':[{'id':'c-serial','language':'c','workers':['direct'],'status':'implemented','routes':['stdio','shm','inproc']},
                      {'id':'c-threads','language':'c','workers':[1,2,4],'status':'implemented','routes':['stdio','shm','inproc']}],
          'points':[{'name':'echo-caller','scope':'caller','modes':['warm','cold'],'variants':['c-serial','c-threads']}]}
    rows=[{'trial_id':f'e{i}','scope':'caller','warmup':False,'eligible':True,'variant':v,'workers':w,'mode':m,'route':r,'route_label':labels[r]}
          for i,(v,w,m,r) in enumerate(sorted(echo_cells(case),key=str))]
    control=not check_echo_coverage(rows,case,labels)
    dropped=bool(check_echo_coverage(rows[1:],case,labels));relabeled=bool(check_echo_coverage([dict(rows[0],route_label='x')]+rows[1:],case,labels))
    return {'status':'PASS' if control and dropped and relabeled else 'FAIL','cells':len(rows),'control':control,'dropped_cell_rejected':dropped,'relabeled_rejected':relabeled}

SANITIZER_DIR='artifacts/project-sanitizers'

def sanitizer_report_path(root,project_dir):
    """EX13-A08: the sanitizer-evidence report of one project: one file per project under SANITIZER_DIR."""
    return Path(root)/SANITIZER_DIR/((re.sub(r'[^A-Za-z0-9._-]','-',str(project_dir).strip('/')) or 'root')+'.json')

def sanitizer_evidence_all(root):
    """EX13-A08: the sanitizer evidence of every native framework example project (project_check.run_sanitizer_evidence),
    one report per project. `./tools/safety ci` runs it before its bench gates, so B11 has current evidence in the parent
    and in the fresh child ci. Framework scope only (amendment E): a standalone example gets its report from
    `bench sanitizer-evidence --project DIR`. Returns {project: verdict}."""
    import project_check
    out={}
    for p,_,_,_ in native_projects(root):
        out[p]=project_check.run_sanitizer_evidence(root,p,sanitizer_report_path(root,p))['verdict']
    return out

def b11_status(fr,reports,current,projects,refused=None):
    """(status, reason, project dirs) of B11 (EX13-A03, EX13-A08): BLOCKED without a foundation qualification report of the
    current source with the parallel lane, and BLOCKED without a current sanitizer-evidence report (kind
    sanitizer-evidence, the project's own file, the same source) for every native example project: the project sanitizer
    gates are part of the property, never skipped. EX13-A11: a report also needs the verdict PASS and no blocker; a
    report with another verdict than PASS or FAIL, or with a blocker (a container cleanup or report schema failure after
    the gates), is BLOCKED, and the verdict FAIL is FAIL. FWN1-B11-SHAPE-01: `refused` {project: reason} holds the reports
    that b11_suite read but refused (no JSON, or not valid against schemas/project-sanitizer-report.json): BLOCKED; and
    `blockers` must be an empty list, so a report without the field (or with '', 0, {} or None) is BLOCKED, never "no
    blocker". Then check_pool_lifecycle decides PASS or FAIL."""
    if fr is None or (fr.get('binding') or {}).get('source')!=current or 'parallel' not in fr:
        return 'BLOCKED','no foundation qualification report with the parallel lane for the current source (./tools/safety foundation selftest or ci writes it)',[]
    if not projects:return 'BLOCKED','no native example project: the project sanitizer part of B11 has no evidence',[]
    bad=[p for p in projects if p in (refused or {})]
    if bad:return 'BLOCKED','sanitizer evidence refused (schema project-sanitizer-report) for: '+', '.join(f'{p} ({str(refused[p])[:120]})' for p in bad),[]
    def current_report(p):
        r=(reports or {}).get(p)
        return isinstance(r,dict) and r.get('kind')=='sanitizer-evidence' and r.get('project_dir')==p and r.get('source_identity')==current
    missing=[p for p in projects if not current_report(p)]
    if missing:return 'BLOCKED','no current sanitizer evidence (bench sanitizer-evidence or ci, same source) for: '+', '.join(missing),[]
    def no_blocker(r):b=r.get('blockers');return isinstance(b,list) and not b      # FWN1-B11-SHAPE-01: the field is required
    unfinished=[p for p in projects if reports[p].get('verdict') not in ('PASS','FAIL') or not no_blocker(reports[p])]
    if unfinished:return 'BLOCKED','sanitizer evidence without the verdict PASS or FAIL and empty blockers for: '+', '.join(unfinished),[]
    problems=check_pool_lifecycle(fr,[reports[p] for p in projects])
    problems+=[f'project {p}: the sanitizer evidence verdict is FAIL' for p in projects if reports[p].get('verdict')=='FAIL']
    return ('PASS' if not problems else 'FAIL'),'; '.join(problems)[:300],list(projects)

def read_sanitizer_report(root,path):
    """FWN1-B11-SHAPE-01: (report, None) for a per-project sanitizer report that is JSON and valid against
    schemas/project-sanitizer-report.json, else (None, reason). B11 never reads a field of a refused report."""
    from schema_check import validate
    try:doc=read_json(path)
    except (GateError,OSError,ValueError) as exc:return None,f'unreadable: {type(exc).__name__}'
    try:validate(root,'project-sanitizer-report',doc)
    except GateError as exc:return None,str(exc)[:200]
    return doc,None

def b11_suite(root,project=None):
    """B11 on the current evidence (b11_status): the foundation report and the per-project sanitizer reports of the
    native projects of the example scope `project` (native_projects), each checked against its schema when it is read
    (read_sanitizer_report)."""
    from policy import source_identity
    out={'status':'FAIL','property':PROPERTY['B11']}
    try:
        current=source_identity(root)[0];path=Path(root)/'artifacts/foundation-qualification-report.json'
        fr=read_json(path) if path.is_file() else None;projects=[p for p,_,_,_ in native_projects(root,project)]
        paths={p:sanitizer_report_path(root,p) for p in projects};reports={};refused={}
        for p,x in paths.items():
            if not x.is_file() or x.is_symlink():continue
            doc,why=read_sanitizer_report(root,x)
            if why is None:reports[p]=doc
            else:refused[p]=why
        status,reason,ok=b11_status(fr,reports,current,projects,refused)
        row=dict(out,status=status,evidence_paths=[str(x) for x in [path,*paths.values()] if x.is_file()],project_reports=ok,
                 mutants=[m.get('id') for m in ((fr or {}).get('parallel') or {}).get('mutants') or [] if isinstance(m,dict)])
        if reason:row['reason']=reason
        return row
    except Exception as exc:          # the suite could not prove its property: FAIL, never PASS or BLOCKED
        return dict(out,reason=f'B11 check failed: {type(exc).__name__}: {str(exc)[:200]}')

def sanitizer_evidence_cmd(root,args):
    """./tools/safety bench sanitizer-evidence --project DIR [--format json]: the sanitizer evidence of one project (the
    report that B11 reads). PASS 0, FAIL 1, BLOCKED 2."""
    import bench, project_check
    project=bench.project_arg(root,args)
    if project is None:raise GateError('bench sanitizer-evidence needs --project')
    r=project_check.run_sanitizer_evidence(root,project,sanitizer_report_path(root,project))
    result={k:r[k] for k in ('verdict','run_id','project_dir','source_identity','elapsed_seconds','stopped_after','blockers')}
    result['report']=str(sanitizer_report_path(root,project))
    bench.emit(args,result,f"bench sanitizer-evidence {project}: {r['verdict']} ({r['elapsed_seconds']} s)");return bench.EXIT[r['verdict']]

def register_cli(handlers,arguments):
    """Adds the operation sanitizer-evidence (EX13-A08)."""
    handlers['sanitizer-evidence']=sanitizer_evidence_cmd
    arguments['sanitizer-evidence']=[('--project',{})]

def b04_row(ov,envelope,project,work=None):
    """B04 for one project from its native-overlap job record (status, record, evidence) or None: NOT_RUN with the reason
    when the project declares no optional native.trace (EX13-A05), else the check of the record."""
    if ov is None:return {'status':'NOT_RUN','reason':f'{project} declares no optional native.trace (pool trace program)'}
    if ov[1] is None:return dict(_fail_suite('B04',f'native-overlap job {ov[0]}'),evidence_paths=[ov[2]])
    try:st,detail=b04_project(ov[1],envelope)
    except Exception as exc:return _fail_suite('B04',f'B04 check failed: {type(exc).__name__}: {str(exc)[:200]}')
    return {'status':st,**detail,'evidence_paths':[ov[2]]+([str(Path(work)/'overlap.json')] if work else [])}

def join_project_rows(name,rows):
    """(suite or None, not_run entries) of one B case over the projects: a project row that did not run goes to not_run
    with its reason; the suite joins the rows that ran (None when none ran)."""
    ran={p:r for p,r in rows.items() if r.get('status')!='NOT_RUN'}
    not_run=[{'suite':f'{name} {p}','reason':str(r.get('reason') or 'not run')[:300]} for p,r in rows.items() if r.get('status')=='NOT_RUN']
    if not ran:return None,not_run
    return {'status':_status([r['status'] for r in ran.values()]),'property':PROPERTY[name],'projects':ran},not_run

def echo_not_run(echo):
    """EX13-A06: the not_run entry of the real B13-echo part when no example project declares echo_case."""
    return [] if echo else [{'suite':'B13-echo real rows','reason':'no example project declares echo_case in its protocol (ledger EX13-B13ECHO-01)'}]

def project_suites(root,p2_dir,item,policy,labels):
    """B04, B06, B07 (the unmutated contexts), B08 and the real-row part of B16 for one native example project:
    (suites {name: row}, evidence or None, jobs, real run directory or None)."""
    project,decl,case_id,variant=item;names=('B04','B06','B07','B08','B16')
    rc,real=real_run(root,project,case_id)
    if real is None or rc!=0:
        why=f'the real run of {case_id} in {project} exited {rc}'
        return {n:dict(_fail_suite(n,why),run_dir=str(real) if real else None) for n in names},None,{},real
    ev=load_run(real);routes=tuple(variant.get('routes') or ['stdio']);s={};work=p2_dir/re.sub(r'[^A-Za-z0-9._-]','-',project)
    try:jobs=run_jobs(root,work,project,decl,case_id,variant,ev,policy)
    except GateError as exc:jobs={'error':str(exc)[:300]}
    envelope=ev['run'].get('envelope') or {}
    s['B04']={'status':'BLOCKED','reason':jobs['error']} if 'error' in jobs else b04_row(jobs.get('native-overlap'),envelope,project,work)
    ag=jobs.get('agreement-controls');required=required_mutations(root,project)
    if 'error' in jobs:s['B06']={'status':'BLOCKED','reason':jobs['error']}
    elif ag is None or ag[1] is None:s['B06']=_fail_suite('B06',f"agreement-controls job {ag[0] if ag else 'not run'}")
    else:
        problems=check_agreement_controls(ag[1],required);agreement=((ev['run'].get('native') or {}).get('agreement') or {})
        if agreement.get('status')!='PASS':problems.append(f"the native agreement check {agreement.get('check')} did not pass with the run build")
        s['B06']={'status':'PASS' if not problems else 'FAIL','mutations':required,'native_agreement':agreement.get('check'),'problems':_norm_problems(problems),
                  'evidence_paths':[ag[2],str(work/'agreement-controls.json'),str(real/'run.json')]}
    try:
        ctx=b07_contexts(ev,policy);problems=check_comparison_context(ctx)
        s['B07']={'status':'PASS' if not problems else 'FAIL','contexts':[c['row'] for c in ctx],'problems':_norm_problems(problems),'run_id':real.name}
    except Exception as exc:s['B07']=_fail_suite('B07',f'B07 check failed: {type(exc).__name__}: {str(exc)[:200]}')
    try:
        real_problems=check_caller_scope(ev['observations'],ev['phases'],labels,routes,ev['plan']);mutants=b08_mutants(ev,labels,routes)
        s['B08']={'status':'PASS' if not real_problems and mutants and all(mutants.values()) else 'FAIL','routes':list(routes),
                  'problems':_norm_problems(real_problems),'mutants_rejected':mutants,'run_id':real.name}
    except Exception as exc:s['B08']=_fail_suite('B08',f'B08 check failed: {type(exc).__name__}: {str(exc)[:200]}')
    try:
        problems=check_incomplete_never_counts(ev['observations'])
        x=copy.deepcopy(ev['observations']);next(o for o in x if not o['warmup'] and o['scope']=='caller').update(eligible=False)
        if not check_incomplete_never_counts(x):problems.append('an ineligible real row with work was not rejected')
        s['B16']={'status':'PASS' if not problems else 'FAIL','problems':_norm_problems(problems),'run_id':real.name}
    except Exception as exc:s['B16']=_fail_suite('B16',f'B16 check failed: {type(exc).__name__}: {str(exc)[:200]}')
    return s,ev,jobs,real

def phase2_cases(root,run_dir,project=None):
    """(suites, additions, not_run) of Phase 2 for bench.selftest_cases: B04, B06, B07, B08, B11, B13-echo, B16 and the
    P02, P04 and P16 variants (ALL_VARIANTS order). The suites cover every native example project; the P subcases use the
    real evidence of the first one in name order (the control project). A case, project part or subcase without a real
    path goes to not_run with its reason and a ledger row (ruling EX13-R4); `seconds` records the measured time per
    project. `project`: the example scope (native_projects; amendment E 1.2 item 3)."""
    import time
    root=Path(root);run_dir=Path(run_dir);policy=bm.load_policy(root);labels=policy['routes']
    suites={};additions=[];not_run=[];p2_dir=run_dir/'phase2';p2_dir.mkdir(parents=True,exist_ok=True)
    projects=native_projects(root,project)
    suites['B11']=b11_suite(root,project)
    t0=time.monotonic()
    try:fstatus,fdoc,fev=failure_job(root,p2_dir/'failure-controls',policy)
    except GateError as exc:fstatus,fdoc,fev=('BLOCKED',None,None)
    seconds={'failure-controls':round(time.monotonic()-t0,1)};per={}
    for item in projects:
        t0=time.monotonic();per[item[0]]=project_suites(root,p2_dir,item,policy,labels);seconds[item[0]]=round(time.monotonic()-t0,1)
    for name in ('B04','B06','B07','B08'):
        suite,nr=join_project_rows(name,{p:v[0][name] for p,v in per.items()});not_run+=nr
        if suite is not None:suites[name]=suite
        elif not projects:suites[name]=_fail_suite(name,'no example project with a native declaration (the control project)')
    failure=check_failure_classes(fdoc) if fdoc is not None else [f'failure-controls job {fstatus}']
    rows={p:v[0]['B16'] for p,v in per.items()}
    suites['B16']={'status':_status([not failure]+[r['status'] for r in rows.values()]) if rows else 'FAIL','property':PROPERTY['B16'],
                   'problems':_norm_problems(failure),'classes':{c.get('case'):c.get('class') or (c.get('framework_row') or {}).get('error_type') for c in (fdoc or {}).get('cases') or []},
                   'projects':rows,'evidence_paths':[e for e in (fev,str(p2_dir/'failure-controls'/'failure-controls.json') if fdoc is not None else None) if e]}
    echo=[(p,bm.protocol_value(root,p,'echo_case')) for p,_,_,_ in projects if bm.protocol_value(root,p,'echo_case')]
    fixture=b13_fixture(labels);not_run+=echo_not_run(echo)
    if not echo:suites['B13-echo']=dict(fixture,property=PROPERTY['B13-echo'],control='fixture rows (the check itself)',real_rows='NOT_RUN (cases.json not_run)')
    else:
        rows=[]
        for p,cid in echo:
            t0=time.monotonic();erc,edir=real_run(root,p,cid);seconds[f'{p} echo']=round(time.monotonic()-t0,1)
            got=check_echo_coverage(load_run(edir)['observations'],bm.load_case(root,cid,p),labels) if edir is not None and erc==0 else [f'the echo run of {cid} exited {erc}']
            rows.append({'project':p,'case':cid,'problems':_norm_problems(got),'run_id':edir.name if edir else None})
        suites['B13-echo']=dict(fixture,status='PASS' if fixture['status']=='PASS' and all(not r['problems'] for r in rows) else 'FAIL',
                                property=PROPERTY['B13-echo'],real_rows=rows)
    first=per[projects[0][0]] if projects else None
    if first is None or first[1] is None:
        why='no real evidence of the control project' if first is None else f'the real run of the control project failed ({first[3]})'
        additions=[_sub(p,v,False,False,[],why) for p,v in ALL_VARIANTS if not v.startswith('selector-')]
        not_run+=[{'suite':f"P16 {NAMES['P16']}/{v}",'reason':f'no framework example project has per-selector evaluation counters (ledger {SELECTOR_LEDGER})'} for v in ('selector-overcompute','selector-no-op')]
        if 'B07' in suites:suites['B07']['status']='FAIL'
    else:
        _,ev,jobs,real=first;run_ev=[str(real/n) for n in ('plan.json','observations.jsonl','phases.jsonl','run.json','native.json')]
        try:_,_,p02=p02_additions(root,ev,policy,run_ev)
        except Exception as exc:p02=[_sub('P02',v,False,False,run_ev,f'B07 contexts failed: {type(exc).__name__}') for v in P02_VARIANTS]
        p16,nr=p16_additions(ev,policy,jobs,run_ev);not_run+=nr
        additions=p02+p04_additions(root,ev,policy,jobs,run_ev)+p16
        if 'B07' in suites:
            suites['B07']['p02']={a['variant']:a['status'] for a in p02}
            if not all(a['status']=='PASS' for a in p02):suites['B07']['status']='FAIL'      # B07 needs every P02 mutation of the control project rejected
    for s in ('B04','B06','B07','B08','B16'):
        if s in suites:suites[s]['seconds']=seconds
    order={x:i for i,x in enumerate(ALL_VARIANTS)};additions.sort(key=lambda a:order[(a['parent'],a['variant'])])
    atomic_json(p2_dir/'phase2.json',{'suites':suites,'additions':additions,'not_run':not_run,'seconds':seconds});return suites,additions,not_run

def p04_additions(root,ev,policy,jobs,evidence):
    """P04 on the real run, its build and the native-overlap record; each variant's control is the unmutated evidence."""
    import bench, bench_native
    obs=ev['observations'];phases=ev['phases'];plan=ev['plan'];native=ev['native'];envelope=ev['run'].get('envelope') or {}
    ov=(jobs.get('native-overlap') or (None,None,None))[1]
    rows=[]
    def pool():
        bad=[{'rows':[{'variant':'c-threads','workers':w}],'envelope':envelope} for w in (0,-1,8,64,True,'4')]
        bad.append({'rows':[{'variant':'c-threads','workers':2,'window':64}],'envelope':envelope})
        return all(check_pool_request(b,policy) for b in bad),not check_pool_request(plan,policy) and not check_pool_request({'rows':[{'variant':'c-threads','workers':w} for w in policy['pools']['workers'] if w<=envelope.get('cpus',0)],'envelope':envelope},policy)
    rows.append(_row('P04','unlimited-pool-or-queue',pool,'a worker count outside the policy or envelope, or an unbounded window, is refused',evidence))
    def thread_api():
        return any(f['rule']=='threading-outside-grant' for f in thread_api_findings(root,'g_thread_pool_new')),not thread_api_findings(root,'sc_parallel_run')
    rows.append(_row('P04','unauthorized-thread-api',thread_api,'a thread API outside the foundation grant is an AST finding',['safety/foundation-api-policy.json']))
    def loading():
        x=copy.deepcopy(obs);i=next(k for k,o in enumerate(x) if o.get('route')=='inproc');x[i]['load_process']={'pid':1,'role':'coordinator'}
        other=dict(bench_native.native_plan(native));name=next(n for n in other if n!=GLIB_NAME);other[name]='0'*64
        return bool(check_inproc_isolation(x)) and bool(check_native_identity(other,native)),not check_inproc_isolation(obs) and not check_native_identity(bench_native.native_plan(native),native)
    rows.append(_row('P04','unsafe-native-loading',loading,'a coordinator load or a binary outside the run build is refused',evidence))
    def host():
        x=copy.deepcopy(obs);x[0]['runner']='host';return bool(check_launch(x)),not check_launch(obs)
    rows.append(_row('P04','host-execution',host,'a row outside the framework runners is refused',evidence))
    def affinity():
        a=(ov or {}).get('affinity')
        return bool(check_affinity(plan.get('envelope'),dict(envelope,cpuset=[0],cpus=1),a)) and bool(check_affinity(plan.get('envelope'),envelope,1)),ov is not None and not check_affinity(plan.get('envelope'),envelope,a)
    rows.append(_row('P04','changed-affinity',affinity,'a changed CPU set or job affinity is refused',evidence))
    def subprocess_left():
        x=copy.deepcopy(phases);i=next(k for k,p in enumerate(x) if p.get('phase')=='teardown' and p['pids_start']>p['pids_end']);x[i]['pids_end']=x[i]['pids_start']
        return bool(check_process_cleanup(x)),not check_process_cleanup(phases) and any(p.get('phase')=='teardown' for p in phases)
    rows.append(_row('P04','unmanaged-subprocess',subprocess_left,'a teardown that leaves processes is refused',evidence))
    def privilege():
        refused=[]
        for k in PRIVILEGE_KEYS:
            try:bench.reject_host_tuning({k:True});refused.append(False)
            except GateError:refused.append(True)
        try:bench.reject_host_tuning(plan);ok=True
        except GateError:ok=False
        return all(refused),ok
    rows.append(_row('P04','profiler-privilege',privilege,'a privilege or profiler request is refused before any container',evidence))
    return rows

def p16_additions(ev,policy,jobs,evidence):
    """P16 on real observations: (additions, not_run). skip-useful-work mutates the real kernel rows of the run (records
    below the plan); reuse-answer reads the C results of two seeds of the agreement-controls job; no-op-native-kernel and
    removed-result-consumption read the real kernel controls of that job (kernel_notes). The selector variants need a
    project with per-selector counters; no framework example has one, so they are NOT_RUN with the ledger row
    SELECTOR_LEDGER (never a PASS)."""
    obs=ev['observations'];ag=(jobs.get('agreement-controls') or (None,None,None))[1] or {}
    seeds=list(ag.get('seeds') or []);kn=kernel_notes(ag)
    rows=[]
    run_kernel=[{'trial_id':o.get('trial_id'),'records':o.get('work_units'),'planned_rows':policy['sizes'][o['tier']],'eligible':o.get('eligible')}
                for o in obs if o.get('scope')=='kernel' and str(o.get('variant','')).startswith('c-') and not o.get('warmup')]
    def skipped():
        x=copy.deepcopy(run_kernel);x[0]['records']=x[0]['planned_rows']//2;return bool(check_skipped_work(x)),bool(run_kernel) and not check_skipped_work(run_kernel)
    rows.append(_row('P16','skip-useful-work',skipped,'fewer records than planned is never eligible',evidence))
    def reuse():
        if len(seeds)!=2:return False,False      # no record of two seeds: never PASS
        x=copy.deepcopy(seeds);x[1]['result_sha256']=x[0]['result_sha256'];return bool(check_replay(x)),seeds[0]['seed']!=seeds[1]['seed'] and not check_replay(seeds)
    rows.append(_row('P16','reuse-answer',reuse,'a result reused for another input is refused',evidence))
    ctl=kn.get('control') or {}
    control=ctl.get('eligible') is True and ctl.get('validated') is True and ctl.get('canonical_ok') is True
    def no_op():
        n=kn.get('no-op') or {};return n.get('eligible') is False and n.get('validated') is False,control
    rows.append(_row('P16','no-op-native-kernel',no_op,'the framework kernel verifier refuses an output that no kernel computed (real kernel controls)',evidence))
    def consumption():
        n=kn.get('removed-consumption') or {};return n.get('eligible') is False and n.get('canonical_ok') is False,control
    rows.append(_row('P16','removed-result-consumption',consumption,'the framework kernel verifier refuses a result whose canonical digest was removed (real kernel controls)',evidence))
    not_run=[{'suite':f"P16 {NAMES['P16']}/{v}",'reason':f'no framework example project has per-selector evaluation counters; an example project with selectors runs them (ledger {SELECTOR_LEDGER})'}
             for v in ('selector-overcompute','selector-no-op')]
    return rows,not_run
