"""Amendment G8.4 with erratum I15: the statistics core of a decision unit (Bonferroni, intersection-union, two looks).
Stdlib only.

Under the owner policy every bound is a distribution-free order-statistic (sign-test) bound for the median of the block
values (I15; bench_stats.order_stat_rank / order_stat_bounds): no resampling, seed or resample count enters a decision.
The C claim uses the median of the per-block paired ratios X_b/P_b. The verdict engine (Task 15) decides real runs with
these functions. The B09 coverage simulation (benchmarks/performance/python/benchlab/coverage.py) loads this file inside
the container and checks that its vectorized decisions equal the decisions made here, so the coverage rate is a property
of this code.

Task 15 appends the qualification unit (G9.4: the only reader of the project report, the ci bootstrap report and the
approval verdicts under a unit-threshold policy) and the unit verdicts (`decide_units`, G9.3 orders 1, 1a and 2-9, the
safe-route verdict of G9.5 and every G9.6 record field)."""
import functools, hashlib, importlib.util, json, math, numbers, re, statistics, time
from pathlib import Path

try:
    import bench_stats as bs
except ImportError:          # loaded by path (the container coverage job): take the sibling module, never a search path
    _spec=importlib.util.spec_from_file_location('bench_stats',Path(__file__).resolve().with_name('bench_stats.py'))
    bs=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(bs)

ALPHA=(0.025,0.0125)         # one-sided error level of look 1 (12 primary blocks) and look 2 (24 blocks), G8.4

def alpha(look):
    """The one-sided level of a look: 0.025 at look 1, 0.0125 at look 2."""
    if isinstance(look,bool) or not isinstance(look,int) or look not in (1,2):raise ValueError('look must be 1 or 2')
    return ALPHA[look-1]

def _count(k):
    if isinstance(k,bool) or not isinstance(k,int) or k<1:raise ValueError('the set size must be a positive integer')
    return k

def h_pi(rows,look,stats=None):
    """H_Pi = min over Pi of U(alpha/k_Pi) (claim "Python under T": at least one row, Bonferroni over k_Pi); U is the
    order-statistic upper bound (+inf when unattainable). rows = [(label, {block: value})] in case variant order; ties keep
    the first row. (+inf, None) for an empty set. stats is accepted for the caller's signature and not used (I15)."""
    if not rows:return math.inf,None
    a=alpha(look)/len(rows);best=None
    for label,values in rows:
        u=bs.order_stat_bounds(values,a)[1]
        if best is None or u<best[0]:best=(u,label)
    return best

def l_pi(rows,look,stats=None):
    """L_Pi = min over Pi of L(alpha) (claim "every row at or above T": intersection-union, no adjustment); L is the
    order-statistic lower bound (-inf when unattainable). (+inf, None) for an empty set."""
    if not rows:return math.inf,None
    a=alpha(look);best=None
    for label,values in rows:
        lo=bs.order_stat_bounds(values,a)[0]
        if best is None or lo<best[0]:best=(lo,label)
    return best

def _same_blocks(p,x):
    return bool(p) and set(p)==set(x)

def ratio_bounds(p_series,x_series,k,look):
    """Order-statistic bounds (L, U) at alpha/k of the median of the per-block paired ratios X_b/P_b (I15.2)."""
    a=alpha(look)/_count(k)
    if not _same_blocks(p_series,x_series):raise ValueError('paired ratios need the same blocks on both sides')
    return bs.order_stat_bounds([x_series[b]/p_series[b] for b in sorted(p_series)],a)

def qualifies(p_series,x_series,k,look,stats=None):
    """Claim "C reliably faster": X qualifies when the order-statistic upper bound of the median of X_b/P_b at alpha/k
    (Bonferroni over k = k_Gamma, or k_safe for the safe-route verdict) is below 1.0; an unattainable bound (+inf) never
    qualifies. None when the block sets differ (a missing block makes the pair missing, G8.1)."""
    alpha(look);_count(k)
    if not _same_blocks(p_series,x_series):return None
    return ratio_bounds(p_series,x_series,k,look)[1]<1.0

def unattainable(rows,k_gamma,look):
    """Order 1a inputs (I15.4): U_pi when U(alpha/k_Pi) is unattainable for every row of Pi, L_pi when L(alpha) is
    unattainable for any row, C when the C bound at alpha/k_Gamma is unattainable for the block count of the rows."""
    if not rows:return {'U_pi':False,'L_pi':False,'C':False}
    a=alpha(look);ns=[len(values) for _,values in rows]
    return {'U_pi':all(bs.order_stat_rank(n,a/len(rows)) is None for n in ns),'L_pi':any(bs.order_stat_rank(n,a) is None for n in ns),
            'C':bool(k_gamma) and any(bs.order_stat_rank(n,a/_count(k_gamma)) is None for n in ns)}

POWER_CAVEAT='measured noise above the largest computed level; the 0.10 power is an upper bound, the true power is lower'

def power_rows(record,sigma_log):
    """H16.3: the power rows of the coverage record `power` (H16.2) for a unit whose noise level is sigma_log: the smallest
    computed level at or above sigma_log (never a lower level, no interpolation); above the largest level, the largest
    level's rows with POWER_CAVEAT. {'level', 'caveat' (None in range), 'all_rows_fast': {ratio: rate},
    'one_row_fast': {ratio: fast_row_rate}} (summaries use the fast-row rate, H16.2 (b))."""
    if isinstance(sigma_log,bool) or not isinstance(sigma_log,numbers.Real) or not math.isfinite(sigma_log) or sigma_log<0:
        raise ValueError('sigma_log must be a finite number >= 0')
    power=record.get('power') if isinstance(record,dict) else None
    if not isinstance(power,dict) or not power:raise ValueError('the coverage record has no power report')
    levels=[]
    for key,rows in power.items():
        try:level=float(key)
        except ValueError:raise ValueError(f'power level {key!r} is not a number') from None
        if not isinstance(rows,dict) or not isinstance(rows.get('all_rows_fast'),dict) or not isinstance(rows.get('one_row_fast'),dict):
            raise ValueError(f'power level {key!r} lacks a configuration')
        levels.append((level,key))
    levels.sort();above=[lk for lk in levels if lk[0]>=sigma_log]
    (level,key),caveat=(above[0],None) if above else (levels[-1],POWER_CAVEAT)
    rows=power[key]
    try:one={ratio:row['fast_row_rate'] for ratio,row in rows['one_row_fast'].items()}
    except (TypeError,KeyError):raise ValueError(f'power level {key!r}: one_row_fast lacks fast_row_rate') from None
    return {'level':level,'caveat':caveat,'all_rows_fast':dict(rows['all_rows_fast']),'one_row_fast':one}

# ---- B09 coverage job (Amendment G8.4): the host side of the container job `coverage` ----
COVERAGE_FILES=('tools/bench_units.py','benchmarks/performance/python/benchlab/coverage.py','safety/performance-policy.json','tools/bench_stats.py')
COVERAGE_KEYS=('bench_units_sha256','coverage_sha256','policy_sha256','bench_stats_sha256')   # bench_stats decides too (order_stat_rank, order_stat_bounds, median)

def file_digests(root):
    """sha256 of bench_units.py, benchlab/coverage.py and the performance policy, keyed as in coverage.json."""
    return {k:hashlib.sha256((Path(root)/rel).read_bytes()).hexdigest() for k,rel in zip(COVERAGE_KEYS,COVERAGE_FILES)}

def coverage_problems(record,policy,digests):
    """Why a coverage record does not certify the current code ([] when it does): status PASS, every configuration and
    sigma_log present with a rate at or below its bound, the policy's units, the order-statistic method, the current digests."""
    cov=policy['coverage'];problems=[]
    if not isinstance(record,dict):return ['no coverage record']
    if record.get('status')!='PASS':problems.append(f"coverage status {record.get('status')}")
    rates=record.get('rates') if isinstance(record.get('rates'),dict) else {}
    for cfg,bound_key in COVERAGE_BOUND.items():
        for sl in cov['sigma_log']:
            rate=(rates.get(cfg) or {}).get(str(sl))
            if isinstance(rate,bool) or not isinstance(rate,numbers.Real) or not 0<=rate<=cov['bounds'][bound_key]:
                problems.append(f'{cfg} sigma_log {sl}: rate {rate!r} not within the bound')
    if record.get('units')!=cov['units']:problems.append('units differ from the policy')
    if record.get('interval_method')!='order-statistic':problems.append('interval method is not order-statistic (I15)')
    problems+=[f'{k} differs from the current file' for k in COVERAGE_KEYS if record.get(k)!=digests[k]]
    return problems

def coverage_status(row,problems):
    """The job row decides BLOCKED: only a PASS or FAIL row is a measurement (anything else is an infrastructure failure)."""
    if not isinstance(row,dict) or row.get('status') not in ('PASS','FAIL'):return 'BLOCKED'
    return 'PASS' if not problems else 'FAIL'

COVERAGE_BOUND={'keep':'two_look','every-row':'two_look','c-one-look':'c_one_look','c-two-looks':'two_look'}

def coverage_suite(root,run_dir,suite):
    """B09 sub-check: run the container job `coverage` (four least favourable configurations x two sigma_log values),
    keep its coverage.json in the run directory, and PASS B09 only when B09 passed and the record certifies the current
    bench_units.py, coverage.py and policy. Framework code only."""
    import bench, bench_model as bm
    from evidence import GateError, read_json
    root=Path(root);policy=bm.load_policy(root);deadline=policy['job_deadlines']['selftest'];started=time.monotonic()
    out={'status':'FAIL','property':'B09 coverage of the unit statistics (G8.4): every rate within its bound'}
    session=None;evidence=[]
    try:
        session=bench.BenchSession(root,run_dir)
        r=session.job({'schema_version':1,'job':'coverage','run_id':run_dir.name,'deadline_seconds':deadline},'bench-coverage',deadline)
        row=bench.last_json(r['output'])
        record=read_json(session.fetch('bench/out/coverage.json',run_dir/'coverage.json')) if row.get('status') in ('PASS','FAIL') else None
        problems=coverage_problems(record,policy,file_digests(root))
        out.update(status=coverage_status(row,problems),problems=problems[:20],report=str(run_dir/'coverage.json') if record else None,
                   rates=(record or {}).get('rates'),look2_rate=(record or {}).get('look2_rate'),seconds=(record or {}).get('seconds'))
    except GateError as exc:out.update(status='BLOCKED',reason=str(exc)[:200])
    finally:
        if session is not None:evidence=list(session.evidence_paths);session.close()
    out['evidence_paths']=evidence;out['duration_seconds']=round(time.monotonic()-started,1)
    merged=dict(suite,coverage=out)
    merged['status']=suite['status'] if suite.get('status')!='PASS' else out['status']
    return merged

# ---- Task 15, qualification unit (G9.4; P3R11-01 to P3R11-04, P3R12-01 to P3R12-05): for a unit-threshold policy the only
# reader of a project report, a ci bootstrap report or an approval verdict, and the only builder of a project_check or a
# qualification object. ----
PROJECT_REPORT='artifacts/project-report.json'
CI_REPORT='artifacts/runs/{run_id}/bootstrap-report.json'
RUN_ID=re.compile(r'^[0-9a-f]{32}$');HEX64=re.compile(r'^[0-9a-f]{64}$')
LABEL_MANIFEST='manifest recorded';LABEL_LOCAL='framework qualified locally, not published';LABEL_NONE='framework unqualified'
LOCAL_REASONS=('ci-evidence-missing','ci-report-not-passing','ci-identity-mismatch','approval-missing','approval-not-valid')
MAX_VERDICTS=8;MAX_PATH=300

def _sha(data):return hashlib.sha256(data).hexdigest()
def _hex64(v):return isinstance(v,str) and bool(HEX64.match(v))
def _read_object(path):
    from evidence import CAPPED_JSON_MAX_BYTES, loads_capped, read_capped
    try:data=read_capped(Path(path),CAPPED_JSON_MAX_BYTES,'record','record');doc=loads_capped(data,'record')     # FR3-19
    except (OSError,ValueError):return None,None
    return (doc,data) if isinstance(doc,dict) else (None,None)

def _project_check(exit,report_path,report_sha256,identity,local=None):
    """The one project_check shape; private: only this unit calls it."""
    if exit is None:
        if (report_path,report_sha256,identity,local)!=(None,None,None,None):raise ValueError('no report means no report fields')
    else:
        if type(exit) is not int or exit not in (0,1,2,3) or not isinstance(report_path,str) or not _hex64(report_sha256):raise ValueError('bad project report fields')
        if not (_hex64(identity) or (identity is None and exit==2)):raise ValueError('identity required unless the check blocked before it')
        if local is not None and exit!=3:raise ValueError('local evidence belongs to exit 3 only')
    return {'exit':exit,'report_path':report_path,'report_sha256':report_sha256,'identity':identity,'local':local}

def _same_project(root,a,b):
    """P3R12-04: both spellings through the project_check normalization (tools/project_model.py _project_dir)."""
    import project_model
    from evidence import GateError
    if not isinstance(a,str) or not isinstance(b,str):return False
    try:return project_model._project_dir(Path(root),a)==project_model._project_dir(Path(root),b)
    except (GateError,ValueError,OSError):return False

def project_check_from_report(root,report_rel,project_dir):
    """Freeze time and decide time; needs no run. Absent, unreadable, malformed or another project's report -> the no-report shape."""
    doc,data=_read_object(Path(root)/report_rel)
    if doc is None or not _same_project(root,doc.get('project_dir'),project_dir):return _project_check(None,None,None,None)
    exit,identity=doc.get('exit_code'),doc.get('source_identity')
    if type(exit) is not int or exit not in (0,1,2,3):return _project_check(None,None,None,None)
    if not (_hex64(identity) or (identity is None and exit==2)):return _project_check(None,None,None,None)
    return _project_check(exit,report_rel,_sha(data),identity)

def load_local_evidence(root,ci_run_id,verdict_paths):
    """The only reader of ci and approval files. Returns (ci_evidence | None, approvals)."""
    root=Path(root);approvals=[]
    for p in verdict_paths or []:
        if len(str(p))>MAX_PATH:approvals.append({'path':str(p)[:MAX_PATH],'sha256':None,'text':None});continue   # never accepted (the CLI refuses it first)
        f=Path(p) if Path(p).is_absolute() else root/p
        try:data=f.read_bytes()
        except OSError:approvals.append({'path':str(p),'sha256':None,'text':None});continue
        approvals.append({'path':str(p),'sha256':_sha(data),'text':data.decode('utf-8','replace')})
    if not isinstance(ci_run_id,str) or not RUN_ID.match(ci_run_id):return None,approvals
    rel=CI_REPORT.format(run_id=ci_run_id);report,data=_read_object(root/rel)
    if report is None or report.get('run_id')!=ci_run_id:return None,approvals
    gates=json.loads((root/'safety/contract.json').read_text())['required_gates']
    return {'ci_run_id':ci_run_id,'report_path':rel,'report_sha256':_sha(data),'report':report,'required_gates':list(gates)},approvals

def _approved_identity(text):
    head=('\n'+text).split('\n## ',1)[0]                    # the header block before the first '## ' heading
    lines=[l.strip() for l in head.splitlines()]
    ids=[l[len('- Reviewed identity: '):] for l in lines if l.startswith('- Reviewed identity: ')]
    return ids[0] if 'Verdict: APPROVE' in lines and len(ids)==1 and _hex64(ids[0]) else None

def check_local_evidence(ci_evidence,approvals,current_identity):
    """Pure. G9.4 rules 1-4 on loaded inputs; the first failed rule names the reason."""
    accepted=[{'path':a['path'],'sha256':a['sha256']} for a in approvals if a['text'] is not None and _approved_identity(a['text'])==current_identity]
    out={'ok':False,'reason':None,'ci_run_id':None,'report_path':None,'report_sha256':None,'local_state':None,'required_gates':'NOT_CHECKED','verdicts':accepted[:MAX_VERDICTS]}
    if ci_evidence is None:out['reason']='ci-evidence-missing';return out
    r=ci_evidence['report'];rows=r.get('gates') if isinstance(r.get('gates'),list) else []      # P3R12-02: a malformed gates value counts as absent
    status={g['name']:g.get('status') for g in rows if isinstance(g,dict) and isinstance(g.get('name'),str)}
    state=(r.get('local_state') if isinstance(r.get('local_state'),str) else '')[:32] or 'MISSING'
    # G9.4 rule 2: the required names come only from safety/contract.json (ci_evidence['required_gates']); the report's own
    # 'required_gates' key, if any, is never read, and a required gate that the report omits is not PASS.
    gates='PASS' if all(status.get(n)=='PASS' for n in ci_evidence['required_gates']) else 'FAIL'
    commands=r.get('commands') if isinstance(r.get('commands'),list) else []
    out.update(ci_run_id=ci_evidence['ci_run_id'],report_path=ci_evidence['report_path'],report_sha256=ci_evidence['report_sha256'],local_state=state,required_gates=gates)
    if state!='PASS' or gates!='PASS' or not commands or commands[-1]!='./tools/safety ci':out['reason']='ci-report-not-passing'
    elif r.get('source_identity')!=current_identity:out['reason']='ci-identity-mismatch'
    elif not approvals:out['reason']='approval-missing'
    elif len(approvals)>MAX_VERDICTS or len(accepted)!=len(approvals):out['reason']='approval-not-valid'
    else:out['ok']=True
    return out

def kind_label(pc,current_identity):
    """Pure; total over every project_check that _project_check accepts."""
    e,i=pc['exit'],pc['identity']
    if e is None:return 'none',LABEL_NONE
    if e in (1,2):return ('failed',LABEL_NONE) if i is None or i==current_identity else ('stale',LABEL_NONE)
    if i!=current_identity:return 'stale',LABEL_NONE
    if e==0:return 'manifest',LABEL_MANIFEST
    return 'local',(LABEL_LOCAL if pc['local'] is not None and pc['local']['ok'] else LABEL_NONE)

def qualify(pc,ci_evidence,approvals,current_identity):
    """Pure; returns a new project_check (the input is unchanged), its kind and its label."""
    local=check_local_evidence(ci_evidence,approvals,current_identity) if pc['exit']==3 and pc['identity']==current_identity else None
    q=_project_check(pc['exit'],pc['report_path'],pc['report_sha256'],pc['identity'],local)
    kind,label=kind_label(q,current_identity);return q,kind,label

def qualification_block(pc,source_identity):
    """The bench-decision `qualification` object; every field value is a function of (pc, source_identity)."""
    kind,label=kind_label(pc,source_identity)
    loc=(pc['local'] or check_local_evidence(None,[],source_identity)) if kind=='local' else None   # an unqualified exit-3 check reads as row Q10
    return {'kind':kind,'label':label,'project_exit':pc['exit'],'project_report_path':pc['report_path'],'project_report_sha256':pc['report_sha256'],
            'project_identity':pc['identity'],'framework_ci_run_id':loc['ci_run_id'] if loc else None,'ci_report_path':loc['report_path'] if loc else None,
            'ci_report_sha256':loc['report_sha256'] if loc else None,'ci_local_state':loc['local_state'] if loc else None,
            'ci_required_gates':loc['required_gates'] if loc else 'NOT_CHECKED','local_reason':None if loc is None or loc['ok'] else loc['reason'],
            'verdicts':list(loc['verdicts']) if loc else [],'source_identity':source_identity}

def failed_conditions(uev):
    """G9.4 conditions that make a reliably faster C `c-not-eligible` (order 7)."""
    pc=uev['project_check'];kind,label=kind_label(pc,uev['current_identity']);out=[]
    if kind=='failed':out.append('project-gates-failed' if pc['exit']==1 else 'project-check-blocked')
    elif label not in (LABEL_MANIFEST,LABEL_LOCAL):out.append('framework-unqualified')
    if uev['opportunity_state']!='APPROVED':out.append('opportunity-not-approved')
    return out

# ---- Task 15, unit verdicts (G8, G9.2-G9.7, H14, H15.2, H16.3, H21.4/H21.6, I8, I15): decide_units ----
SUMMARY_LESS_SAFE='PREFER_C only on the in-process route (less safe); safe routes: {v} ({r})'
VARIANT_ORDER=('py-reference','py-optimized','py-library','py-threads','py-processes','c-serial','c-threads')
LESS_SAFE_LABEL=('in-process shared library: native code shares the interpreter address space; a C defect can corrupt the '
                 'interpreter (fast route, least safe)')                                                    # G9.7
COLD_LABEL='reported, not the verdict basis'                                                                # G7.4
COLD_START_FLAG='deployment starts a worker per request: the cold values apply'                             # G7.4
TREND_LABEL='trend of P over blocks (assumption check, never a verdict)'                                    # I15.2
ONE_ROW_LABEL='power is lower when only one C row is fast'                                                  # H16.3
SENSITIVITY_SENTENCE=('A C advantage smaller than the ratios with high power at this noise level can stay unrecognized; '
                      'then the action is KEEP_PYTHON (order 9) or INCONCLUSIVE where the order table says so.')   # H16.3
ACCURACY_LABEL='documented metric, never a verdict'                                                         # I8.3, I4.5
MAX_REPORT_TABLES=16        # FR3: per selector, the project report object of project-report.json holds at most 16 keys
DIAGNOSTIC_LABEL='diagnostic, never a verdict'                                                              # G9.6, G3.6
PANEL_CELLS=6               # bench_model.PANEL_CELLS: the six panel cells of a project's cell rule (G7.3)
PANEL_KEYS=('cell','category','values','level')     # H21.6 with FR5: the cell, its category label, the rule's report values, the level

def worst_record(records):
    blocks=set.intersection(*(set(c) for c in records.values()))
    return {b:max(c[b] for c in records.values()) for b in sorted(blocks)}

def _blocks(look,policy):return policy['primary_blocks']+(policy['extension_blocks'] if look==2 else 0)   # 12 and 24 under the approved policy (schema consts)
def _measured(r,look,policy):return r['eligible'] and len(r['wall'])==_blocks(look,policy) and all(b in r['wall'] for b in range(_blocks(look,policy)))
def _label(r):return f"{r['variant']} x{r['workers']}"+(f" [{r['route']}]" if r.get('route') else '')
def _median(r):import bench_stats as bs;return bs.median(r['wall'].values())
def _pick(rows):return min(rows,key=lambda r:(_median(r),VARIANT_ORDER.index(r['variant']),str(r['workers']),str(r.get('route'))))

def _positive(v):return not isinstance(v,bool) and isinstance(v,numbers.Real) and math.isfinite(v) and v>0

def _envelope_note(unit,uev):
    """G6.3 (AG2-11): envelope-blocked rows are not planned; the verdict holds for the recorded envelope."""
    rows=[e['label'] for e in uev.get('envelope_not_planned',[]) if e.get('unit')==unit]
    if not rows:return None
    n=uev.get('envelope_cpus')
    return (f"verdict for an envelope of {n if n is not None else 'an unrecorded number of'} CPUs; rows not run on this envelope: "+', '.join(rows))[:600]

def py_reference_guard(unit,uev,P_upper):
    """G8.2 with I15.2: c_e = min over the six panel records of w(c)/e(c) (w(c) the per-record warm median of the
    py-reference row of m/single-record, e(c) = panel_evals[m][c]); estimate = c_e x reference_evals[m]. False when the
    estimate < P_upper or any input is missing."""
    m=unit.split('/')[0]
    ref=[r for r in uev['rows'] if r['unit']==f'{m}/single-record' and r['variant']=='py-reference' and r['mode']=='warm' and r.get('eligible')]
    evals=(uev.get('panel_evals') or {}).get(m) or {};E=(uev.get('reference_evals') or {}).get(m)
    if len(ref)!=1 or not _positive(E):return False
    records=ref[0].get('records') or {}
    if len(records)!=PANEL_CELLS or set(records)!=set(evals):return False      # FR5: the cell names of the project's panel reference
    ce=[]
    for cell,blocks in records.items():
        e=evals.get(cell)
        if not _positive(e) or not blocks or not all(_positive(v) for v in blocks.values()):return False
        ce.append(bs.median(blocks.values())/e)
    return min(ce)*E>=P_upper

def decide_unit(unit,uev,policy,stats):
    look=uev['looks'].get(unit,1);a=alpha(look);T=policy['threshold_ns_per_request'];mode=policy['verdict_mode']
    rows=[r for r in uev['rows'] if r['unit']==unit];warm=[r for r in rows if r['mode']==mode]
    base={'unit':unit,'look':look,'alpha':a,'blocks':_blocks(look,policy),'envelope_note':_envelope_note(unit,uev),'extension':{'trigger':False,'note':None}}
    if uev['status']!='VALID':return _rec(base,'INVALID_EXPERIMENT','run-invalid',uev,policy)
    if unit in uev['window_mismatch']:return _rec(dict(base,detail='window-envelope-mismatch'),'INVALID_EXPERIMENT','run-invalid',uev,policy)
    if unit in uev.get('window_pressure',()):return _rec(dict(base,detail='window-pressure'),'INVALID_EXPERIMENT','run-invalid',uev,policy)   # H15.2 exhausted look-1 window
    if not uev.get('coverage_ok'):return _rec(dict(base,detail='coverage-unqualified'),'INVALID_EXPERIMENT','run-invalid',uev,policy)   # G8.4, H14
    bad=[r for r in rows if r.get('planned',True) and not r['eligible']]
    if bad:return _rec(dict(base,detail=next((r['detail'] for r in bad if r.get('detail')),None)),'INVALID_EXPERIMENT','ineligible-row',uev,policy)   # H21.4 panel-status
    py=[r for r in warm if r['language'] in policy['python_languages']];c=[r for r in warm if r['language'] in policy['c_languages']]
    pi=[r for r in py if _measured(r,look,policy)];gamma=[r for r in c if _measured(r,look,policy)];gsafe=[r for r in gamma if r.get('route') in policy['safe_routes']]
    blocked=[b for b in uev['blocked_other'] if b['unit']==unit]
    miss_py=len(pi)<len(py) or any(b['label'].startswith('py-') for b in blocked)
    miss_c=len(gamma)<len(c) or any(b['label'].startswith('c-') for b in blocked)
    miss_c_safe=len(gsafe)<len([r for r in c if r.get('route') in policy['safe_routes']]) or any(b['label'].startswith('c-') and ('[inproc]' not in b['label']) for b in blocked)
    un=unattainable([(_label(r),r['wall']) for r in pi],len(gamma),look)
    if un['U_pi'] or un['L_pi']:return _rec(base,'INCONCLUSIVE','bound-unattainable',uev,policy,pi=pi,gamma=gamma,gsafe=gsafe)   # I15.4 order 1a
    H,h_row=h_pi([(_label(r),r['wall']) for r in pi],look,stats);base.update(k_pi=len(pi),k_gamma=len(gamma),k_safe=len(gsafe),H_pi=(H,h_row))
    if H<T:return _rec(base,'KEEP_PYTHON','python-under-threshold',uev,policy,pi=pi,gamma=gamma,gsafe=gsafe)
    L,l_row=l_pi([(_label(r),r['wall']) for r in pi],look,stats);base['L_pi']=(L,l_row)
    if L<T:
        ex=unit in uev.get('extension_exhausted',())
        base['extension']={'trigger':look==1 and not ex,'note':'extension-not-run' if (unit in uev['extension_not_run'] or ex) else None}
        if ex:base['detail']='extension-exhausted'   # H15.2 exhausted extension window
        return _rec(base,'INCONCLUSIVE','python-near-threshold' if look==1 else 'python-at-threshold',uev,policy,pi=pi,gamma=gamma,gsafe=gsafe)
    if not pi or miss_py:return _rec(base,'INCONCLUSIVE','python-evidence-missing',uev,policy,pi=pi,gamma=gamma,gsafe=gsafe)
    P=_pick(pi);U_P=bs.order_stat_bounds(P['wall'],a/len(pi))[1]   # G8.2 with I15.2: U(α/k_Π) of P
    if unit.endswith('/full-dataset') and not py_reference_guard(unit,uev,U_P):return _rec(base,'INCONCLUSIVE','py-reference-not-measured',uev,policy,pi=pi,gamma=gamma,gsafe=gsafe)
    all_v=_c_orders(P,gamma,miss_c,look,stats,uev);safe_v=_c_orders(P,gsafe,miss_c_safe,look,stats,uev)
    return _rec(base,all_v['verdict'],all_v['reason'],uev,policy,pi=pi,gamma=gamma,gsafe=gsafe,P=P,c=all_v,c_safe=safe_v)

def _c_orders(P,G,missing,look,stats,uev):
    if G and any(bs.order_stat_rank(len(x['wall']),alpha(look)/len(G)) is None for x in G):return {'verdict':'INCONCLUSIVE','reason':'bound-unattainable','C':None,'failed':[]}   # I15.4: the C bound while orders 6-7 would be reached
    qual=[x for x in G if qualifies(P['wall'],x['wall'],len(G),look,stats)]
    if qual:
        C=_pick(qual);conds=failed_conditions(uev)
        return {'verdict':'PREFER_C' if not conds else 'INCONCLUSIVE','reason':'c-reliably-faster' if not conds else 'c-not-eligible','C':C,'failed':conds}
    if not G or missing:return {'verdict':'INCONCLUSIVE','reason':'c-evidence-missing','C':None,'failed':[]}
    return {'verdict':'KEEP_PYTHON','reason':'c-not-reliably-faster','C':_pick(G),'failed':[]}

def decide_units(uev,policy,stats):
    """The unit records in policy['units'] order (I8.1, I8.2)."""
    return [decide_unit(u,uev,policy,stats) for u in policy['units']]

# ---- record helpers (G9.6) ----
def _ms(v):return None if v is None or not math.isfinite(v) else v/1e6
def _num(v):return None if v is None or not math.isfinite(v) else float(v)

def _interval(values,a):
    """(median, L(a), U(a)) in ms of a block series; the bounds are null when unattainable or the series is empty."""
    if not values:return None,None,None
    lo,hi=bs.order_stat_bounds(values,a);return _ms(bs.median(values.values())),_ms(lo),_ms(hi)

def _row_summary(r,a):
    med,lo,hi=_interval(r['wall'],a);return {'label':_label(r),'median_ms':med,'low_ms':lo,'high_ms':hi}

def _p_summary(P,a):
    if P is None:return None
    return dict(_row_summary(P,a),cpu_ms=_ms(bs.median(P['cpu'].values())) if P.get('cpu') else None,peak=P.get('peak'))

def _c_summary(C,P,k,look,T,a):
    """G9.6 C (and C_safe): label, route and its label, median and [L(α), U(α)], the ratio C/P (median of the per-block
    ratios) with its order-statistic interval at α/k (I15.2), the absolute saving, c_under_threshold, CPU and peak."""
    if C is None or P is None:return None
    med,lo,hi=_interval(C['wall'],a);blocks=sorted(P['wall'])
    rl,rh=ratio_bounds(P['wall'],C['wall'],k,look);ratio=bs.median([C['wall'][b]/P['wall'][b] for b in blocks])
    clo,chi=bs.order_stat_bounds(C['wall'],a)                                    # in ns, against T
    return {'label':_label(C),'route':C.get('route'),'route_label':C.get('route_label'),'median_ms':med,'low_ms':lo,'high_ms':hi,
            'ratio':float(ratio),'ratio_low':_num(rl),'ratio_high':_num(rh),'saving_ms':_ms(_median(P)-_median(C)),
            'c_under_threshold':True if chi<T else False if clo>=T else 'unknown',
            'cpu_ms':_ms(bs.median(C['cpu'].values())) if C.get('cpu') else None,'peak':C.get('peak')}

def _cold(rows,ident_row,policy,a):
    """The cold value of the same row identity: median and interval, labeled "reported, not the verdict basis" (G7.4)."""
    if ident_row is None:return None
    key=(ident_row['variant'],ident_row['workers'],ident_row.get('route'))
    hit=[r for r in rows if r['mode']!=policy['verdict_mode'] and (r['variant'],r['workers'],r.get('route'))==key and r.get('wall')]
    return _row_summary(hit[0],a) if hit else None

@functools.lru_cache(maxsize=None)
def _inversion_counts(n):
    """Number of permutations of n items with i inversions (Mahonian numbers), i = 0 .. n(n-1)/2."""
    counts=[1]
    for m in range(2,n+1):
        new=[0]*(len(counts)+m-1)
        for i,cnt in enumerate(counts):
            for j in range(m):new[i+j]+=cnt
        counts=new
    return tuple(counts)

def kendall_trend(values):
    """I15.2 assumption check, never a verdict: Kendall's tau between block value and block index, and its exact two-sided
    p-value from the permutation distribution of S (n! orderings without ties, Mahonian numbers). Tied pairs count as
    neither concordant nor discordant (tau-a), which only makes |S| smaller."""
    keys=sorted(values);y=[values[k] for k in keys];n=len(y)
    if n<2:return {'tau':None,'p_two_sided':None,'n':n,'label':TREND_LABEL}
    s=sum((y[j]>y[i])-(y[j]<y[i]) for i in range(n) for j in range(i+1,n));pairs=n*(n-1)//2
    extreme=sum(cnt for inv,cnt in enumerate(_inversion_counts(n)) if abs(pairs-2*inv)>=abs(s))
    return {'tau':s/pairs,'p_two_sided':extreme/math.factorial(n),'n':n,'label':TREND_LABEL}

def unit_sensitivity(P,gamma,gsafe,look,coverage_power):
    """H16.3: the measured sensitivity of the C claim, bound to the unit's own evidence at the current look."""
    a=alpha(look);n=len(P['wall']) if P else 0;sds=[]
    for x in (gamma if P else []):
        blocks=sorted(P['wall'])
        if set(x['wall'])!=set(blocks) or not all(_positive(x['wall'][b]) and _positive(P['wall'][b]) for b in blocks):continue
        lr=[math.log(x['wall'][b]/P['wall'][b]) for b in blocks]
        if len(lr)>=2:sds.append(statistics.stdev(lr))
    sigma_hat=bs.median(sds) if sds else None;sigma_log=None if sigma_hat is None else sigma_hat/math.sqrt(2)
    kg,ks=len(gamma),len(gsafe);rank=lambda k:bs.order_stat_rank(n,a/k) if k and n else None
    caveats=[];level=all_fast=one_fast=None
    if sigma_log is not None and coverage_power is not None:
        try:pw=power_rows(coverage_power,sigma_log)
        except ValueError as exc:caveats.append(f'coverage power report unusable: {exc}'[:200])
        else:
            level,all_fast,one_fast=pw['level'],dict(pw['all_rows_fast']),{'label':ONE_ROW_LABEL,'fast_row_rate':dict(pw['one_row_fast'])}
            if pw['caveat']:caveats.append(pw['caveat'])
    elif sigma_log is not None:caveats.append('no coverage power report')
    if kg!=12:caveats.append(f'k_Gamma = {kg} in this unit; the coverage configuration has k_Gamma = 12')
    return {'sigma_hat':sigma_hat,'sigma_log':sigma_log,'rows':len(sds),'blocks':n,'level':level,'caveat':'; '.join(caveats) or None,
            'k_gamma':kg,'rank_gamma':rank(kg),'k_safe':ks,'rank_safe':rank(ks),'all_rows_fast':all_fast,'one_row_fast':one_fast,'sentence':SENSITIVITY_SENTENCE}

def _ranks(pi,P,C,C_safe,kg,ks,look):
    """I15.2: the order-statistic ranks of every report line. Per row of Π: k_upper of U(α/k_Π) and the position k_lower
    = n + 1 - k(n, α) of L(α) (None when unattainable); for C and C_safe the rank k of the ratio bound at α/k_Γ or α/k_safe."""
    a=alpha(look);rows=[]
    for r in pi or []:
        n=len(r['wall']);ku=bs.order_stat_rank(n,a/len(pi));kl=bs.order_stat_rank(n,a)
        rows.append({'label':_label(r),'n':n,'k_upper':ku,'k_lower':None if kl is None else n+1-kl})
    one=lambda X,k:None if X is None or not k else {'n':len(X['wall']),'k':bs.order_stat_rank(len(X['wall']),a/k)}
    return {'rows':rows,'C':one(C,kg),'C_safe':one(C_safe,ks)}

def _project_report(unit,uev):
    """FR3 (was the I8.3 model report): the project's documented report of the unit's selector, from the run directory's
    project-report.json ({selector: object of at most 16 keys}); None when the run has none for the selector. Never a
    verdict (ACCURACY_LABEL)."""
    tables=(uev.get('project_report') or {}).get(unit.partition('/')[0])
    return {'label':ACCURACY_LABEL,'tables':tables} if isinstance(tables,dict) else None

def _library_selector(unit,policy):
    """G2.3: True when the policy's project protocol lists the unit's selector in library_report.selectors."""
    lib=policy.get('library_report') or {}
    return unit.partition('/')[0] in (lib.get('selectors') or [])

def _panel(P,C,a):
    """G9.6: every panel record (cell name only) with the median and interval of P and C."""
    out=[]
    for cell in sorted((P or {}).get('records') or {}):
        cc=((C or {}).get('records') or {}).get(cell)
        p=_interval(P['records'][cell],a);c=_interval(cc,a) if cc else None
        out.append({'cell':cell,'P':dict(zip(('median_ms','low_ms','high_ms'),p)),'C':dict(zip(('median_ms','low_ms','high_ms'),c)) if c else None})
    return out[:PANEL_CELLS]

def _unattainable_text(pi,gamma,c,look):
    a=alpha(look)
    if c and c.get('reason')=='bound-unattainable' and gamma:return f'the C bound at level {a/len(gamma):.6g} is unattainable with n = {min(len(x["wall"]) for x in gamma)} blocks'
    n=min(len(r['wall']) for r in pi) if pi else 0
    if pi and all(bs.order_stat_rank(len(r['wall']),a/len(pi)) is None for r in pi):return f'U at level {a/len(pi):.6g} is unattainable with n = {n} blocks'
    return f'L at level {a:.6g} is unattainable with n = {n} blocks'

def _power_text(s):
    if not s or s['level'] is None:return 'no coverage power report for this noise level'
    rates=lambda d:', '.join(f'{k}: {v}' for k,v in sorted(d.items()))
    return f"power at sigma_log level {s['level']}: all rows fast {{{rates(s['all_rows_fast'])}}}; one row fast (fast-row rate) {{{rates(s['one_row_fast']['fast_row_rate'])}}}"

def unit_record(base,verdict,reason,uev,policy,pi=None,gamma=None,gsafe=None,P=None,c=None,c_safe=None):
    """Every G9.6 field of one unit record (the closed `units` item of schemas/bench-decision.json)."""
    unit=base['unit'];look=base['look'];a=alpha(look);T=policy['threshold_ns_per_request']
    rows=[r for r in uev['rows'] if r['unit']==unit];warm_c=[r for r in rows if r['mode']==policy['verdict_mode'] and r['language'] in policy['c_languages']]
    reached=pi is not None
    P=P if P is not None else (_pick(pi) if pi else None)
    kg=len(gamma) if gamma is not None else None;ks=len(gsafe) if gsafe is not None else None
    C=(c or {}).get('C');C_safe=(c_safe or {}).get('C')
    vsafe,rsafe=(c_safe['verdict'],c_safe['reason']) if c_safe else (verdict,reason)
    conds=list(dict.fromkeys(((c or {}).get('failed') or [])+((c_safe or {}).get('failed') or []))) if 'c-not-eligible' in (reason,rsafe) else []
    kind,label=kind_label(uev['project_check'],uev['current_identity'])
    H=h_pi([(_label(r),r['wall']) for r in pi],look) if pi else (math.inf,None)
    L=l_pi([(_label(r),r['wall']) for r in pi],look) if pi else (math.inf,None)
    sens=unit_sensitivity(P,gamma or [],gsafe or [],look,uev.get('coverage_power'))
    ranks=_ranks(pi,P,C,C_safe,kg,ks,look)
    less_safe=any(r.get('route') in policy['less_safe_routes'] for r in rows if r['language'] in policy['c_languages'])
    named_safe=False                 # T15-APP-04: a differing safe-route verdict is always visible in the summary line
    if conds:summary='C is reliably faster but not eligible: '+', '.join(conds)
    elif verdict=='PREFER_C' and C is not None and C.get('route') in policy['less_safe_routes'] and vsafe!=verdict:summary=SUMMARY_LESS_SAFE.format(v=vsafe,r=rsafe);named_safe=True
    elif reason=='c-not-reliably-faster' and ranks['C']:
        k,n=ranks['C']['k'],ranks['C']['n'];summary=f'C bound = x_({k}) of {n} per-block ratios, k = {k}; '+_power_text(sens)
    elif reason=='bound-unattainable':summary='bound unattainable: '+_unattainable_text(pi,gamma,c,look)
    elif reason=='python-at-threshold':summary=f'Python at the threshold; default action KEEP_PYTHON (L_Pi = {_ms(L[0])} ms, H_Pi = {_ms(H[0])} ms)'
    else:summary=f'{verdict} ({reason})'+(f", detail {base['detail']}" if base.get('detail') else '')
    if (vsafe,rsafe)!=(verdict,reason) and not named_safe:
        tail=f'; safe routes: {vsafe} ({rsafe})';summary=summary[:600-len(tail)]+tail      # the tail survives the 600-character limit
    missing=[{'label':b['label'][:200],'reason':str(b.get('reason'))[:300]} for b in uev['blocked_other'] if b['unit']==unit]
    if reached:
        measured={id(r) for r in (pi or [])+(gamma or [])}
        missing+=[{'label':_label(r),'reason':'not measured in every block of this look'} for r in rows
                  if r['mode']==policy['verdict_mode'] and r['language'] in policy['python_languages']+policy['c_languages'] and id(r) not in measured]
    lib=_library_selector(unit,policy);one=unit.endswith('/single-record')
    return {'unit':unit,'rows_per_request':(uev.get('rows_per_request') or {}).get(unit),'blocks':base['blocks'],'look':look,'alpha':a,
            'k_pi':len(pi) if reached else None,'k_gamma':kg,'k_safe':ks,
            'verdict':verdict,'reason':reason,'detail':base.get('detail'),'verdict_safe_route':vsafe,'reason_safe_route':rsafe,'failed_conditions':conds,
            'default_action':None if verdict=='INVALID_EXPERIMENT' else 'KEEP_PYTHON' if verdict=='INCONCLUSIVE' else verdict,
            'next_action':f'C prototype review for {unit}' if verdict=='PREFER_C' else None,
            'framework_basis':kind,'framework_label':label,
            'H_pi':{'value_ms':_ms(H[0]),'row':H[1]} if reached else None,'L_pi':{'value_ms':_ms(L[0]),'row':L[1]} if reached else None,
            'P':_p_summary(P,a),'python_rows':[_row_summary(r,a) for r in pi or []],
            'C':_c_summary(C,P,kg,look,T,a),'C_safe':_c_summary(C_safe,P,ks,look,T,a),
            'c_rows':[{'label':_label(r),'route':r.get('route'),'route_label':r.get('route_label'),'median_ms':_ms(_median(r)) if r.get('wall') else None} for r in warm_c][:24],
            'less_safe_label':LESS_SAFE_LABEL if less_safe else None,
            'cold':{'label':COLD_LABEL,'P':_cold(rows,P,policy,a),'C':_cold(rows,C,policy,a),'C_safe':_cold(rows,C_safe,policy,a),
                    'cold_start_flag':COLD_START_FLAG if uev.get('deployment_starts_worker_per_request') else None},
            'missing_rows':missing[:48],'panel':_panel(P,C,a) if one else None,
            'panel_records':[{k:p.get(k) for k in PANEL_KEYS} for p in (uev.get('panel_rows') or [])][:PANEL_CELLS] if one else None,
            'diagnostics':{'label':DIAGNOSTIC_LABEL,'entries':[str(x)[:300] for x in ((uev.get('diagnostics') or {}).get(unit) or [])][:32]},
            'possible_python_improvements':[str(x)[:120] for x in (uev.get('opportunity_proposed') or [])][:16],
            'ranks':ranks,'trend':kendall_trend(P['wall']) if P else {'tau':None,'p_two_sided':None,'n':0,'label':TREND_LABEL},'sensitivity':sens,
            'project_report':_project_report(unit,uev),
            'reference_admit_excluded':uev.get('reference_admit_excluded') if lib else None,'library_label':str(policy['library_report']['label'])[:120] if lib else None,
            'library_overhead_ns_per_row':uev.get('library_overhead_ns_per_row') if lib else None,
            'envelope_note':base['envelope_note'],'extension':dict(base['extension']),'summary_line':summary[:600],'adoption_authorized':False}

_rec=unit_record

# ---- Task 18 (G6.3, G6.6, G7.1-G7.3, G9.4, G9.6, G9.9, H14, H16, H21.4, H21.6): unit evidence from a recorded run, the
# coverage record binding and the owner-policy decision record. Host code: these functions import tools modules lazily,
# so the container coverage job (which loads this file by path and uses only the statistics above) never needs them. ----
ADOPTION_NOTE=('unit-threshold objective (G9.9): the adoption outcome is the set of unit verdicts; PREFER_C names a C prototype '
               'review and authorizes no adoption (G9.8)')

def _variant_language(variant):
    """The G8.2 set of a variant (the language of the case variants): py-library is python-library, every other py-* row is
    python, every c-* row is c; any other variant (a control) enters no set."""
    if variant=='py-library':return 'python-library'
    if isinstance(variant,str) and variant.startswith('py-'):return 'python'
    if isinstance(variant,str) and variant.startswith('c-'):return 'c'
    return None

def _timed(observations):
    return [o for o in observations if not o.get('warmup') and o.get('eligible') is True and o.get('block') is not None]

def per_request(observations,planned=None,cells=None):
    """G7.1-G7.3 (P3R2-01): {block: ns per request} of the observations of one unit row. A full-dataset row: per trial the
    median of its inner per-call walls, bench.per_trial(rows, 'wall_ns')[block] (ns per record) x the trial's recorded
    request size (work_units, equal for every inner sample: the records of one call). A single-record row: per trial the
    worst record, the largest over the panel records of the recorded median of the record's L per-call walls
    (panel_stats, computed in the container; T18-C1b). The audit sample panel_walls is never a decision input. Only
    eligible non-warmup trials count. `planned` as in _medians. ValueError for inconsistent evidence."""
    use=_timed(observations)
    panel=[o for o in use if _is_panel(o)]
    if panel:
        if len(panel)!=len(use):raise ValueError('a unit row mixes panel and full-dataset trials')
        out={}
        for o in panel:
            if o['block'] in out:raise ValueError(f"two trials of one row share block {o['block']}")
            out[o['block']]=max(_medians(o,planned,cells).values())
        return out
    import bench
    size={}
    for o in use:size.setdefault(o['block'],set()).add(o.get('work_units'))
    if any(len(s)!=1 for s in size.values()):raise ValueError('inner samples of one trial disagree on the request size')
    return {b:v*next(iter(size[b])) for b,v in bench.per_trial(use,'wall_ns').items()}

def _is_panel(o):return 'panel_stats' in o or 'panel_walls' in o or 'panel_passes' in o

def _medians(o,planned=None,cells=None):
    """{record: recorded median} of one panel trial (panel_stats; T18-C1b). ValueError when the record is incomplete.
    T18-APP-04: the medians and the audit sample name exactly the six panel cells (`cells`: the cell names of the
    project's protocol, bench_panel.cell_names; FR5: none known gives ValueError), so the worst
    record is never taken over fewer records; with `planned` ({trial_id: L of the plan trial}, planned_passes) the
    recorded L equals the plan trial's L (an unplanned trial has none). A row with such a trial is ineligible."""
    stats=o.get('panel_stats');passes=o.get('panel_passes');walls=o.get('panel_walls')
    if not isinstance(stats,dict) or not stats or type(passes) is not int or passes<1:raise ValueError(f"{o.get('trial_id')}: panel medians missing")
    if not cells or len(set(cells))!=PANEL_CELLS:raise ValueError(f"{o.get('trial_id')}: the panel cells of the project are unknown")
    cells=set(cells)
    if set(stats)!=cells or not isinstance(walls,dict) or set(walls)!=cells:raise ValueError(f"{o.get('trial_id')}: the panel trial does not hold the six panel records")
    if planned is not None and planned.get(o.get('trial_id'))!=passes:raise ValueError(f"{o.get('trial_id')}: panel passes differ from the plan")
    out={}
    for cell,s in stats.items():
        m=s.get('median_ns') if isinstance(s,dict) else None
        if isinstance(m,bool) or not isinstance(m,numbers.Real) or not math.isfinite(m) or m<0:raise ValueError(f"{o.get('trial_id')}: panel median rejected")
        out[cell]=m
    return out

def _records(observations,planned=None,cells=None):
    """{cell: {block: recorded median of the cell's L per-call walls}} of a single-record row (eligible non-warmup trials)."""
    out={}
    for o in _timed(observations):
        for cell,m in _medians(o,planned,cells).items():out.setdefault(cell,{})[o['block']]=m
    return out

def planned_passes(plan):
    """T18-APP-04: {trial_id: panel_passes} of the panel trials of the digest-bound plan ({} for a plan without sessions,
    so that no panel trial is planned)."""
    return {t.get('trial_id'):t.get('panel_passes') for s in (plan.get('sessions') or []) if isinstance(s,dict)
            for t in (s.get('trials') or []) if isinstance(t,dict) and 'panel_passes' in t}

def trial_wall_flags(observations,unit):
    """T18-APP-03 (G7.3): per warm single-record row of `unit`, the eligible timed trials whose recorded trial wall
    (panel_call_ns, the sum of the 6 x L timed calls) is below the 0.5 s target, and the trials without a recorded wall.
    Report lines only (diagnostic, never a verdict): L comes from the planned rate, which the calibration never replaces
    for C rows, so a fast row can give a shorter wall; the recorded medians still decide."""
    import bench_plan as bp
    target=bp.PANEL_TRIAL_SECONDS*1e9;groups={}
    for o in _timed(observations):
        if o.get('unit')==unit and o.get('scope')=='caller' and o.get('mode')=='warm' and _is_panel(o):groups.setdefault(_label(o),[]).append(o)
    lines=[]
    for label,obs in sorted(groups.items()):
        known=[w for w in (o.get('panel_call_ns') for o in obs) if type(w) is int and w>=0];short=[w for w in known if w<target]
        if short:lines.append(f'warm trial wall below the {bp.PANEL_TRIAL_SECONDS:g} s target of G7.3: {label} {len(short)} of {len(obs)} trials, '
                              f'shortest {_ms(min(short)):.6g} ms (L comes from the planned rate; the recorded medians still decide)')
        if len(known)<len(obs):lines.append(f'warm trial wall not recorded: {label} {len(obs)-len(known)} of {len(obs)} trials')
    return lines

def _cpu_per_request(observations,panel):
    """G7.5 (reported, never a verdict): CPU ns per request per block; {} when a trial has no CPU delta."""
    import bench
    use=[o for o in _timed(observations) if o.get('cpu_usage_usec') is not None]
    if not use:return {}
    size={o['block']:o.get('work_units') for o in use}
    try:per=bench.per_trial(use,'cpu_usage_usec')
    except (ValueError,KeyError,TypeError):return {}
    return {b:v*1000.0*(1 if panel else size[b]) for b,v in per.items()}

def rows_from_observations(observations,planned=None,cells=None):
    """The pure part of unit_evidence_from_run: the unit rows of the caller-scope observations that carry a `unit` key, one
    row per (unit, mode, variant, workers, route). A row is ineligible when any of its trials is ineligible or carries a
    panel status difference (H21.4: detail panel-status); `wall` is per_request (a single-record row: the worst record of
    `records`); kernel rows never enter (G6.5). `planned` ({trial_id: planned L}, planned_passes of the plan): a panel
    trial whose L differs from its plan trial makes its row ineligible (T18-APP-04); None skips only that comparison."""
    groups={}
    for o in observations:
        if not isinstance(o,dict) or not o.get('unit') or o.get('warmup') or o.get('scope')!='caller':continue
        groups.setdefault((o['unit'],o.get('mode'),o.get('variant'),o.get('workers'),o.get('route')),[]).append(o)
    rows=[]
    for (unit,mode,variant,workers,route),obs in sorted(groups.items(),key=lambda kv:str(kv[0])):
        detail='panel-status' if any(o.get('detail')=='panel-status' or o.get('panel_status_diff') for o in obs) else None
        eligible=detail is None and all(o.get('eligible') is True for o in obs)
        panel=any(_is_panel(o) for o in obs);records=None
        try:
            if panel:records=_records(obs,planned,cells);wall=worst_record(records) if records else {}
            else:wall=per_request(obs,planned,cells)
        except ValueError:wall={};records=None;eligible=False          # inconsistent evidence is never a value
        rows.append({'unit':unit,'mode':mode,'variant':variant,'workers':workers,'route':route,
                     'route_label':next((o.get('route_label') for o in obs if o.get('route_label')),None),'language':_variant_language(variant),
                     'eligible':eligible,'planned':True,'wall':wall,'cpu':_cpu_per_request(obs,panel),'peak':None,'records':records,'detail':detail})
    return rows

def _rows_per_request(observations,rows):
    """G9.6: rows per request of each unit: 1 for a single-record unit; the one recorded request size of a full-dataset unit."""
    out={}
    for unit in sorted({r['unit'] for r in rows}):
        if unit.endswith('/single-record'):out[unit]=1;continue
        sizes={o.get('work_units') for o in _timed(observations) if o.get('unit')==unit and o.get('scope')=='caller'}
        out[unit]=sizes.pop() if len(sizes)==1 and isinstance(next(iter(sizes)),int) and next(iter(sizes))>0 else None
    return out

def _blocked(plan,units):
    """G6.3 (AG2-11): envelope-blocked rows are not planned (envelope_not_planned); every other BLOCKED row of the plan is
    planned and missing (blocked_other). A plan row names a variant and workers; it applies to every unit of the run."""
    env,other=[],[]
    for b in plan.get('blocked_rows') or []:
        if not isinstance(b,dict):continue
        label=f"{b.get('variant')} x{b.get('workers')}"+(f" [{b['route']}]" if b.get('route') else '');reason=str(b.get('reason'))
        for u in units:
            if 'envelope' in reason and 'beyond' in reason:env.append({'unit':u,'label':label})
            else:other.append({'unit':u,'label':label,'reason':reason[:300]})
    return env,other

def _count_or_none(v):return v if type(v) is int and v>=0 else None

def _report_tables(doc):
    """project-report.json: {selector: object of at most MAX_REPORT_TABLES keys}; None when absent or malformed."""
    if not isinstance(doc,dict) or len(doc)>16:return None
    if not all(isinstance(k,str) and re.fullmatch(r'[a-z0-9-]{1,16}',k) and isinstance(v,dict) and len(v)<=MAX_REPORT_TABLES for k,v in doc.items()):return None
    return doc

def _panel_reference(root,project,case_id):
    """The checked panel reference of the case (Task 7, bench_panel.check), or None when the case has none."""
    import bench_panel
    if project is None or not case_id:return None
    path=bench_panel.panel_path(root,project,case_id)
    if not path.is_file():return None
    from evidence import GateError, PROJECT_JSON_LARGE_BYTES, load_project_json
    def check(doc):
        if not isinstance(doc,dict):raise GateError('panel reference is not a JSON object')
        bench_panel.check(root,doc,bench_panel.panel_rule(root,project))
    # FR3-17: project data through the one boundary; a malformed reference is GateError (exit 2), never a silent None
    return load_project_json(path,'panel-reference',PROJECT_JSON_LARGE_BYTES,label='panel reference',check=check)

def _panel_parts(doc,rule=None):
    """(panel_evals {model: {cell: engine_evals}}, panel_rows [PANEL_KEYS]) of a panel reference under the project's cell
    `rule` (bench_panel.panel_rule); the cell names are the protocol's cell names (FR5)."""
    import bench_panel
    if doc is None:return {},None
    rows=bench_panel.panel_rows(doc,rule)
    evals={m:{r['cell']:doc['per_model'][m]['engine_evals'][r['index']] for r in rows} for m in doc['models']}
    return evals,[{k:r[k] for k in PANEL_KEYS} for r in rows]

def _panel_num(v):return f'{v:.6g}' if isinstance(v,(int,float)) and not isinstance(v,bool) else 'null'

def _panel_text(p):
    vals=', '.join(f"{k} {_panel_num(v)}" for k,v in (p.get('values') or {}).items())
    return f"panel record {p['cell']}: {p['category']}, {vals}, level {p['level']}"

def _diagnostics(observations,units,panel_rows):
    """G9.6 slow-row diagnostic (G3.6, the unit-<m>-slowest points) and, for each panel record, its cell name, its category
    label, the report values of the project's cell rule and its fallback level (H21.6 with FR5). Labeled "diagnostic, never
    a verdict" in the record."""
    out={}
    for unit in units:
        m=unit.split('/')[0];point=f'unit-{m}-slowest';lines=trial_wall_flags(observations,unit);groups={}     # T18-APP-03: the flags first (32-entry cap)
        for o in _timed(observations):
            if o.get('point')==point and o.get('scope')=='caller':groups.setdefault((o.get('variant'),o.get('workers'),o.get('mode')),[]).append(o)
        for (v,w,mode),obs in sorted(groups.items(),key=str):
            try:vals=list(per_request(obs).values())
            except ValueError:continue
            if vals:lines.append(f'slowest row ({point}) {v} x{w} {mode}: median {_ms(bs.median(vals))} ms per request over {len(vals)} trials')
        lines+=[_panel_text(p) for p in panel_rows or []]
        out[unit]=lines[:32]
    return out

def _resolve(root,path):
    p=Path(path);return p if p.is_absolute() else Path(root)/p

def _read_coverage(path):
    doc,_=_read_object(path);return doc

def _newest_coverage_path(root):
    """The newest artifacts/bench/*/coverage.json (modification time, then path), or None."""
    paths=[p for p in (Path(root)/'artifacts/bench').glob('*/coverage.json') if p.is_file() and not p.is_symlink()]
    return max(paths,key=lambda p:(p.stat().st_mtime_ns,str(p))) if paths else None

def _newest_coverage(root):
    p=_newest_coverage_path(root);return _read_coverage(p) if p is not None else None

def coverage_record_ok(root,record_path=None,unit_policy=None):
    """H14, H16.1: coverage_problems(record, policy, file_digests(root)) == [] for the record at record_path (the record the
    owner confirmed) or, without one, the newest artifacts/bench/*/coverage.json. No readable record: False. FR3: with
    `unit_policy` (the decided unit-threshold policy, now project data), its threshold_ns_per_request must also equal the
    record's simulated threshold_ns (the check the coverage job made on the framework policy before the move)."""
    import bench_model as bm
    rec=_read_coverage(_resolve(root,record_path)) if record_path is not None else _newest_coverage(root)
    if rec is None:return False
    if unit_policy is not None and rec.get('threshold_ns')!=unit_policy.get('threshold_ns_per_request'):return False
    return coverage_problems(rec,bm.load_policy(root),file_digests(root))==[]

def coverage_power(root,record_path):
    """H16.2, H16.3: the power block of the coverage record at record_path, in the shape power_rows reads ({'power': ...}),
    or None when the record has none."""
    rec=_read_coverage(_resolve(root,record_path)) if record_path is not None else None
    power=rec.get('power') if isinstance(rec,dict) else None
    return {'power':power} if isinstance(power,dict) and power else None

def confirmed_coverage_path(root,args):
    """The coverage_path of the owner's sensitivity confirmation (bench_phase3_cli._sensitivity checked it), or None."""
    p=getattr(args,'sensitivity_confirmation',None)
    if p is None:return None
    doc,_=_read_object(_resolve(root,p))
    path=(doc or {}).get('coverage_path')
    return _resolve(root,path) if isinstance(path,str) and path else None

def unit_evidence_from_run(root,run_dir,run,plan,case,policy,args):
    """The unit evidence (Task 15 shape) of a recorded run whose status decide_cmd re-derived. `run` holds the plan facts
    (case, mode, envelope, project_dir) and the re-derived status and reasons; `plan` is the digest-bound plan.json."""
    import bench, bench_decide as bd, bench_model as bm
    root=Path(root);run_dir=Path(run_dir);obs=bench.read_jsonl(run_dir/'observations.jsonl')
    import bench_panel
    project=plan.get('project_dir') if plan.get('project_dir') is not None else (run.get('plan') or {}).get('project_dir')
    rows=rows_from_observations(obs,planned=planned_passes(plan),cells=bench_panel.cell_names(root,project))   # FR5: the protocol's cells
    seen=sorted({r['unit'] for r in rows});units=list(policy['units'])
    env,other=_blocked(plan,seen)
    current=bd._current_identity(root)
    pc=qualify(project_check_from_report(root,PROJECT_REPORT,project),*load_local_evidence(root,getattr(args,'ci_run_id',None),getattr(args,'approval',None) or []),current)[0]
    cov=confirmed_coverage_path(root,args);power_path=cov if cov is not None else _newest_coverage_path(root)
    opp=bm.load_opportunity(root,case,project) if case.get('opportunity_record') else None
    ref=_panel_reference(root,project,case.get('case_id'))
    panel_evals,panel_rows=_panel_parts(ref,bench_panel.panel_rule(root,project) if ref is not None else None)
    report,_=_read_object(run_dir/'project-report.json')
    return {'status':run.get('status'),'reasons':list(run.get('reasons') or []),'rows':rows,'blocked_other':other,'envelope_not_planned':env,
            'envelope_cpus':(run.get('envelope') or plan.get('envelope') or {}).get('cpus'),'looks':{},'extension_not_run':[],'window_mismatch':[],
            'reference_evals':dict(run.get('reference_evals') or {}),'reference_admit_excluded':run.get('reference_admit_excluded'),
            'panel_evals':panel_evals,'panel_rows':panel_rows,'library_overhead_ns_per_row':(run.get('reference_overhead') or {}).get('library_overhead_ns_per_row'),
            'project_check':pc,'current_identity':current,'coverage_ok':coverage_record_ok(root,cov,policy),
            'coverage_power':coverage_power(root,power_path) if power_path is not None else None,
            'opportunity_state':((opp or {}).get('approval') or {}).get('state'),
            'opportunity_proposed':[o.get('name') for o in (opp or {}).get('python_options',[]) if isinstance(o,dict) and o.get('state')=='proposed'],
            'project_report':_report_tables(report),
            'case_params':bm.params_from_case(case) if isinstance(case.get('parameters'),dict) else None,
            'rows_per_request':_rows_per_request(obs,rows),'diagnostics':_diagnostics(obs,units,panel_rows),
            'deployment_starts_worker_per_request':bool(plan.get('deployment_starts_worker_per_request'))}

def _fmt(v):return 'n/a' if v is None else f'{v:.6g}' if isinstance(v,float) else str(v)

def _owner_summary(units,uev,case,policy):
    """The closed `summary` object of a unit-threshold record: the brief's fields, filled from the unit records."""
    t=lambda s:s[:600]
    P=[f"{u['unit']}: {u['P']['label']} {_fmt(u['P']['median_ms'])} ms" for u in units if u.get('P')]
    C=[f"{u['unit']}: {u['C']['label']} {_fmt(u['C']['median_ms'])} ms" for u in units if u.get('C')]
    missing=[f"{u['unit']} ({u['reason']})" for u in units if u['reason'] in ('python-evidence-missing','c-evidence-missing','py-reference-not-measured','run-invalid','ineligible-row','bound-unattainable')]
    routes={}
    for r in uev.get('rows') or []:
        if r.get('language')=='c' and r.get('route'):routes.setdefault(r['route'],{'route':str(r['route'])[:32],'label':str(r.get('route_label') or '')[:600],'rows':0})['rows']+=1
    nxt=[u['next_action'] for u in units if u.get('next_action')]
    name=str(policy.get('name'));T=_fmt(policy['threshold_ns_per_request']/1e6)
    return {'problem':t(f'{name}: does the computation of each unit add {T} ms or more to one request (warm wall per request, G7.1)?'),
            'best_python':t('; '.join(P) or 'none measured'),'best_c':t('; '.join(C) or 'none measured'),
            'size_range':t('; '.join(f"{u['unit']}: {_fmt(u['rows_per_request'])} rows per request" for u in units)),
            'caller_latency':t('; '.join(f"{u['unit']}: {u['verdict']} ({u['reason']})" for u in units)),
            'cpu':t('; '.join(f"{u['unit']}: {_fmt(u['P']['cpu_ms'])} ms CPU per request" for u in units if u.get('P')) or 'reported per unit, never a verdict (G7.5)'),
            'cpu_tradeoff':t(f'CPU per request is reported and never decides under {name} (G7.5)'),
            'memory':'caller-scope peak reported per unit, never a verdict (G7.5)',
            'assumptions':'warm mode is the verdict basis; cold values are reported, not the verdict basis (G7.4); one client, one request at a time (G7.1)',
            'frequency':'per request; concurrent requests belong to the capacity scope and never decide (G7.1)',
            'uncertainty':'distribution-free order-statistic bounds (I15) at alpha 0.025 (look 1) or 0.0125 (look 2), Bonferroni within each set (G8.4)',
            'missing_evidence':t('; '.join(missing) or 'none'),
            'complexity':'PREFER_C names a C prototype review; no adoption or production use is authorized (G9.8)',
            'next_action':t('; '.join(nxt) or 'KEEP_PYTHON (default action of every unit without PREFER_C)'),
            'routes':list(routes.values())[:8]}

def unit_decision_record(root,run,plan,case,pol,units,uev,opportunity,sensitivity=None,windows=None):
    """The unit-threshold decision record: every required field of the closed bench-decision schema (Task 13 common fields
    with null outcome, rule, adoption and demonstration outcomes), the qualification object of the Task 15 unit for the
    run's source identity, the unit records, `sensitivity` (H16.1) and `windows` (Task A9) as given. `pol` is the loaded
    policy (bench_model.load_decision_policy): the record binds its name and the sha256 of the file that holds it (FR3:
    the project's protocol file for a project policy)."""
    import bench_decide as bd
    from bench_model import policy_filled
    now=bd._current_identity(root);policy_name=pol['name']
    if [u.get('unit') for u in units]!=list(pol['units']):      # FR3: the order check the schema made with fixed unit names
        raise ValueError('unit records differ from the policy units or their order')
    stale=run.get('source_identity')!=now;local=(run.get('dataset') or {}).get('kind')=='local'
    quality='stale' if stale else 'owner fixture, local run, aggregate' if local else 'exploratory (smoke)' if run.get('mode')=='smoke' else 'decision'
    return {'schema_version':1,'run_id':run['run_id'],'case':run.get('case') or case.get('case_id'),'local':local,
            'policy':{'name':policy_name,'sha256':pol['sha256'],'demonstration_only':bool(pol.get('demonstration_only')),'filled':policy_filled(pol)},
            'source_identity_run':run.get('source_identity'),'source_identity_decision':now,'stale':stale,'image_id':run.get('image_id'),'evidence_quality':quality,
            'outcome':None,'rule':None,'adoption_outcome':None,'demonstration_outcome':None,'adoption_note':ADOPTION_NOTE,'adoption_authorized':False,
            'cgroup_identity_unrecorded':False,'qualification':qualification_block(uev['project_check'],run['source_identity']),
            'sensitivity':sensitivity,'windows':windows,'reasons':[str(r)[:300] for r in (run.get('reasons') or [])][:50],
            'comparisons':[],'items':[],'summary':_owner_summary(units,uev,case,pol),'units':list(units)}

def _ms_range(d):return f"{_fmt(d.get('median_ms'))} ms [{_fmt(d.get('low_ms'))}, {_fmt(d.get('high_ms'))}]" if d else 'n/a'

def _c_line(name,c):
    if not c:return f'- {name}: none'
    return (f"- {name}: {c['label']} route {c['route']} ({c['route_label']}); {_ms_range(c)}; ratio C/P {_fmt(c['ratio'])} [{_fmt(c['ratio_low'])}, {_fmt(c['ratio_high'])}]; "
            f"saving {_fmt(c['saving_ms'])} ms; c_under_threshold {c['c_under_threshold']}; CPU {_fmt(c['cpu_ms'])} ms; peak {_fmt(c['peak'])}")

def render_units_markdown(record):
    """Markdown of a unit-threshold record with every G9.6 field of every unit: verdicts and reasons, ranks, the trend line,
    the sensitivity block (H16.3), the project report of a unit and, for every panel record, its cell name, category
    label, report values and fallback level (H21.6 with FR5)."""
    q=record.get('qualification') or {};s=record.get('sensitivity') or {};oc=s.get('owner_confirmation') or {}
    md=[f"## Policy {record['policy']['name']} (unit-threshold objective, not a demonstration)",'',f"- Adoption outcome: the set of {len(record.get('units') or [])} unit verdicts - {record['adoption_note']}",
        f"- Adoption authorized: {record['adoption_authorized']}",f"- Evidence quality: {record['evidence_quality']}"+(' (source changed after the run)' if record['stale'] else ''),
        f"- Framework qualification: {q.get('kind')} ({q.get('label')}); project exit {q.get('project_exit')}; local reason {q.get('local_reason')}",
        f"- Sensitivity confirmation: ledger {oc.get('ledger_id')}, coverage record sha256 {oc.get('coverage_sha256')}" if oc else '- Sensitivity confirmation: none',
        *[f"- {k.replace('_',' ')}: {v}" for k,v in record['summary'].items() if k!='routes'],
        *[f"- route {x['route']}: {x['label']} ({x['rows']} rows)" for x in record['summary']['routes']],
        *[f'- reason: {x}' for x in record['reasons'][:10]],'']
    for u in record.get('units') or []:
        sn=u['sensitivity'];tr=u['trend'];rk=u['ranks']
        md+=[f"### {u['unit']}",'',f"- Summary: {u['summary_line']}",
             f"- Verdict {u['verdict']} ({u['reason']})"+(f", detail {u['detail']}" if u['detail'] else '')+f"; safe routes: {u['verdict_safe_route']} ({u['reason_safe_route']})",
             f"- Failed conditions: {', '.join(u['failed_conditions']) or 'none'}; default action {u['default_action']}; next action {u['next_action']}",
             f"- Framework basis: {u['framework_basis']} ({u['framework_label']})",
             f"- Rows per request {u['rows_per_request']}; blocks {u['blocks']}; look {u['look']}; alpha {u['alpha']}; k_Pi {u['k_pi']}; k_Gamma {u['k_gamma']}; k_safe {u['k_safe']}",
             f"- P: "+(f"{u['P']['label']} {_ms_range(u['P'])}; CPU {_fmt(u['P']['cpu_ms'])} ms; peak {_fmt(u['P']['peak'])}" if u['P'] else 'none'),
             f"- H_Pi: "+(f"{_fmt(u['H_pi']['value_ms'])} ms ({u['H_pi']['row']})" if u['H_pi'] else 'n/a')+"; L_Pi: "+(f"{_fmt(u['L_pi']['value_ms'])} ms ({u['L_pi']['row']})" if u['L_pi'] else 'n/a'),
             *[f"- Python row {r['label']}: {_ms_range(r)}" for r in u['python_rows']],
             _c_line('C',u['C']),_c_line('C_safe',u['C_safe']),
             *[f"- C row {r['label']} route {r['route']} ({r['route_label']}): median {_fmt(r['median_ms'])} ms" for r in u['c_rows']],
             *([f"- {u['less_safe_label']}"] if u['less_safe_label'] else []),
             f"- Cold ({u['cold']['label']}): P {_ms_range(u['cold']['P'])}; C {_ms_range(u['cold']['C'])}; C_safe {_ms_range(u['cold']['C_safe'])}"+(f"; {u['cold']['cold_start_flag']}" if u['cold']['cold_start_flag'] else ''),
             *[f"- Missing row {r['label']}: {r['reason']}" for r in u['missing_rows']],
             *[f"- Panel {p['cell']}: P {_ms_range(p['P'])}; C {_ms_range(p['C'])}" for p in u['panel'] or []],
             *[f"- {_panel_text(p)}" for p in u['panel_records'] or [] if None not in (p.get('values') or {None:None}).values()],
             f"- Diagnostics ({u['diagnostics']['label']}): "+('; '.join(u['diagnostics']['entries']) or 'none'),
             f"- Possible Python improvements not measured: {', '.join(u['possible_python_improvements']) or 'none'}",
             f"- Order-statistic ranks: "+('; '.join(f"{r['label']} n {r['n']} k_upper {r['k_upper']} k_lower {r['k_lower']}" for r in rk['rows']) or 'no Python rows')
             +f"; C {rk['C']}; C_safe {rk['C_safe']}",
             f"- Trend ({tr['label']}): tau {_fmt(tr['tau'])}, p {_fmt(tr['p_two_sided'])}, n {tr['n']}",
             f"- Measured sensitivity (H16.3): sigma_hat {_fmt(sn['sigma_hat'])}, sigma_log {_fmt(sn['sigma_log'])}, rows {sn['rows']}, blocks {sn['blocks']}, level {_fmt(sn['level'])}; "
             f"k_Gamma {sn['k_gamma']} (rank {sn['rank_gamma']}), k_safe {sn['k_safe']} (rank {sn['rank_safe']}); all rows fast {sn['all_rows_fast']}; "
             +(f"{sn['one_row_fast']['label']}: {sn['one_row_fast']['fast_row_rate']}" if sn['one_row_fast'] else 'one row fast: n/a')
             +(f"; caveat: {sn['caveat']}" if sn['caveat'] else ''),f"  {sn['sentence']}"]
        if u['project_report']:
            a=u['project_report'];md.append(f"- Project report ({a['label']}): {a['tables']}")
        if u['library_label']:md.append(f"- {u['library_label']}; library overhead {u['library_overhead_ns_per_row']} ns per row; reference admit excluded {u['reference_admit_excluded']}")
        if u['envelope_note']:md.append(f"- {u['envelope_note']}")
        md+=[f"- Extension: trigger {u['extension']['trigger']}, note {u['extension']['note']}",'']
    return '\n'.join(md)+'\n'
