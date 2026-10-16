"""Amendment G8.4 / G12 B09 with errata I14 and I15 (Task 3): the coverage of the unit statistics, by simulation (NumPy).

Each claim of G8.4 runs at its own least favourable configuration (I14: one Python row in both C configurations) with
the full two-look procedure (look 1 on 12 blocks; look 2 on 24 when the look-1 verdict is `python-near-threshold`).
The decisions apply the rules of tools/bench_units.py (`h_pi`, `l_pi`, `qualifies`), the stdlib code that decides real
runs: distribution-free order-statistic bounds for the median (I15) with the ranks of bench_stats.order_stat_rank, which
this module loads from the same source tree (no copy of the rank rule). `decide_units_reference` calls bench_units and the
tests and the job require equal decisions. No resampling enters a decision (I15), so the simulation has no resamples.

Not simulated (no effect on the events): order 1 (a valid run), order 1a (every bound used is attainable with 12 and 24
blocks, I15.3), order 4 (no row is missing) and the order-5 full-dataset guard (taken as passed: the events are the
conditions of orders 5-9 and 6-7). Block noise: multiplicative lognormal, independent per row and block; in the C
configurations every row of the unit also shares one block factor of the same sigma_log (it cancels in the per-block
ratios X_b/P_b, so both sigma_log runs of a C configuration repeat one experiment with different draws)."""
import hashlib, importlib.util, json, time
from pathlib import Path
import numpy as np

T_NS=200_000_000                       # G9.1: the simulated threshold T (the events are scale-free; a decided policy's T must equal it)
ALPHA=(0.025,0.0125)
CONFIGS=('keep','every-row','c-one-look','c-two-looks')
SPECS={
    # KEEP claim: k_Pi = 9 rows, every true median exactly T. Event: KEEP_PYTHON (python-under-threshold) at either look.
    'keep':{'pi':[T_NS]*9,'gamma':[],'looks':2,'common':False,'event':'keep','bound':'two_look'},
    # "every row >= T": one row at T - 1 ns, eight at 10 T. Event: any verdict of orders 5-9 at either look.
    'every-row':{'pi':[T_NS-1]+[10*T_NS]*8,'gamma':[],'looks':2,'common':False,'event':'reached','bound':'two_look'},
    # C claim, one look (I14): one Pi row at 2 T (look 2 never runs); k_Gamma = 12 rows at true ratio 1.0. Event: orders
    # 6-7 at look 1. One row is the least favourable: with several equal rows P is selected low and X/P is biased up.
    'c-one-look':{'pi':[2*T_NS],'gamma':[2*T_NS]*12,'looks':1,'common':True,'event':'c','bound':'c_one_look'},
    # C claim, two looks (I14): one Pi row at 1.02 T (look 1 often near the threshold, look 2 runs); k_Gamma = 12 rows at
    # ratio 1.0. Event: orders 6-7 at either look.
    'c-two-looks':{'pi':[1.02*T_NS],'gamma':[1.02*T_NS]*12,'looks':2,'common':True,'event':'c','bound':'two_look'},
}
POWER_RATIOS=(0.9,0.8,0.7)             # I15.5 power report: the C one-look configuration with a true C advantage
POLICY_FOR_TEST={'units':10000,'sigma_log':[0.02,0.10],'seed':20261007,'bounds':{'two_look':0.0432,'c_one_look':0.0297},'alpha':ALPHA}
CHUNK_BYTES=512*1048576                # values and sorted copies of one chunk of units
EVENTS=('keep','near','reached','c')
SRC=Path('/src')
_STATS={}                              # resolved path -> (module, sha256 of the exact bytes it executed)
_ACTIVE=[SRC]                          # the source tree whose bench_stats decides; job(src=...) sets it for its run

def _bench_stats(src=None):
    """The deciding bench_stats.py of the source tree `src` (default: the active tree, /src unless a job runs on another).
    The module executes the exact bytes whose sha256 _bench_stats_sha256 returns, so the ranks and the digest of a coverage
    record come from one file (Task 3 re-review Minor 1)."""
    path=(Path(src) if src is not None else _ACTIVE[0])/'tools/bench_stats.py';key=str(path.resolve())
    if key not in _STATS:
        data=path.read_bytes();spec=importlib.util.spec_from_file_location('bench_stats_coverage',path)
        mod=importlib.util.module_from_spec(spec);exec(compile(data,str(path),'exec'),mod.__dict__)
        _STATS[key]=(mod,hashlib.sha256(data).hexdigest())
    return _STATS[key][0]

def _bench_stats_sha256(src=None):
    path=(Path(src) if src is not None else _ACTIVE[0])/'tools/bench_stats.py';_bench_stats(src)
    return _STATS[str(path.resolve())][1]

def rank(n,a,src=None):
    """k(n, a) of I15.2 from the deciding code of the active source tree (or `src`); None when the bound is unattainable."""
    return _bench_stats(src).order_stat_rank(n,a)

def threshold(policy_doc):
    """T_NS, after a check that every unit-threshold policy (kind unit-threshold) in the policy document holds T_NS as its
    threshold_ns_per_request (ValueError otherwise). FR3: the framework policy holds no unit-threshold policy; a project
    policy's T is checked against the record's threshold_ns at decide time (bench_units.coverage_record_ok)."""
    for entry in (policy_doc.get('decision_policies') or {}).values():
        if isinstance(entry,dict) and entry.get('kind')=='unit-threshold' and entry.get('threshold_ns_per_request')!=T_NS:
            raise ValueError('unit-threshold policy threshold differs from the coverage T')
    return T_NS

def _median(values):
    """bench_stats.median over the last axis: the middle value, or the mean of the two middle values."""
    s=np.sort(values,axis=-1);n=s.shape[-1]
    return s[...,n//2] if n%2 else (s[...,n//2-1]+s[...,n//2])/2.0

def _upper(sorted_values,k):
    return np.full(sorted_values.shape[:-1],np.inf) if k is None else sorted_values[...,k-1]

def _lower(sorted_values,k):
    n=sorted_values.shape[-1];return np.full(sorted_values.shape[:-1],-np.inf) if k is None else sorted_values[...,n-k]

def decide_units_np(pi,gamma,look,blocks=None,alpha=ALPHA,threshold=T_NS,rows=False):
    """The G9.3 conditions of a batch of simulated units at one look, as boolean arrays over the units:
    keep (order 2: H_Pi < T), near (order 3: L_Pi < T), reached (orders 5-9: neither) and c (orders 6-7: reached and some
    row of Gamma qualifies: the order-statistic upper bound of the median of X_b/P_b at alpha/k_Gamma is < 1, P the Pi row
    with the smallest median, first row on ties). The look uses the first `blocks` blocks (default min(12*look, given)).
    rows=True adds c_rows (units, k_Gamma): the unit reached orders 5-9 and that Gamma row qualifies (c is its any())."""
    if look not in (1,2):raise ValueError('look must be 1 or 2')
    pi=np.asarray(pi,dtype=np.float64);gamma=np.asarray(gamma,dtype=np.float64)
    nb=min(12*look,pi.shape[-1]) if blocks is None else blocks
    pi=pi[...,:nb];gamma=gamma[...,:nb];n,kpi=pi.shape[:2];kg=gamma.shape[1];a=alpha[look-1]
    out={k:np.zeros(n,dtype=bool) for k in EVENTS}
    if rows:out['c_rows']=np.zeros((n,kg),dtype=bool)
    k_u=rank(nb,a/kpi) if kpi else None;k_l=rank(nb,a);k_c=rank(nb,a/kg) if kg else None
    step=max(1,CHUNK_BYTES//((kpi+kg)*nb*8*3))
    for s in range(0,n,step):
        e=min(n,s+step);u=e-s
        if kpi:
            sp=np.sort(pi[s:e],axis=-1);H=_upper(sp,k_u).min(axis=1);L=_lower(sp,k_l).min(axis=1)
        else:
            H=np.full(u,np.inf);L=np.full(u,np.inf)
        keep=H<threshold;near=~keep&(L<threshold);reached=~keep&~near
        out['keep'][s:e]=keep;out['near'][s:e]=near;out['reached'][s:e]=reached
        sel=np.flatnonzero(reached)
        if kg and kpi and sel.size:
            chunk=pi[s:e][sel];prow=np.argmin(_median(chunk),axis=1);P=chunk[np.arange(sel.size),prow]      # (s', blocks)
            ratios=np.sort(gamma[s:e][sel]/P[:,None,:],axis=-1)
            q=_upper(ratios,k_c)<1.0                                                                       # (s', k_Gamma)
            c=np.zeros(u,dtype=bool);c[sel]=q.any(axis=1);out['c'][s:e]=c
            if rows:out['c_rows'][s+sel]=q
    return out

def decide_units_reference(units,bu,look,blocks=None,threshold=T_NS):
    """The same conditions through the deciding code: bench_units.h_pi, l_pi and qualifies, one unit at a time."""
    pi=np.asarray(units['pi']);gamma=np.asarray(units['gamma']);nb=min(12*look,pi.shape[-1]) if blocks is None else blocks
    n=pi.shape[0];out={k:np.zeros(n,dtype=bool) for k in EVENTS}
    for i in range(n):
        rows=[(f'p{j}',{b:float(pi[i,j,b]) for b in range(nb)}) for j in range(pi.shape[1])]
        xs=[{b:float(gamma[i,j,b]) for b in range(nb)} for j in range(gamma.shape[1])]
        keep=bu.h_pi(rows,look)[0]<threshold
        near=not keep and bu.l_pi(rows,look)[0]<threshold;reached=not keep and not near
        c=False
        if reached and rows and xs:
            P=min(rows,key=lambda r:bu.bs.median(r[1].values()))[1]
            c=any(bu.qualifies(P,x,len(xs),look) for x in xs)
        out['keep'][i]=keep;out['near'][i]=near;out['reached'][i]=reached;out['c'][i]=c
    return out

def mixed_units(n,look,seed):
    """Equivalence units that give both outcomes of every event: k_Pi = 3 rows at f*(1, 1.05, 1.1)*T with f cycling over
    0.8 (keep), 0.99 and 1.01 (near), 1.3 (reached); k_Gamma = 4 rows at ratio r*(1, 1.02, 1.04, 1.06) to f*T with r cycling
    over 0.85 (qualifies) and 1.0, 1.1 (does not). sigma_log 0.02 and a common block factor."""
    rng=np.random.default_rng(seed);blocks=12*look
    f=np.array([0.8,0.99,1.01,1.3])[np.arange(n)%4];r=np.array([0.85,1.0,1.1])[np.arange(n)%3]
    pi=(f[:,None,None]*np.array([1.0,1.05,1.1])[None,:,None]*T_NS)*np.exp(0.02*rng.standard_normal((n,3,blocks)))
    gamma=((f*r)[:,None,None]*np.array([1.0,1.02,1.04,1.06])[None,:,None]*T_NS)*np.exp(0.02*rng.standard_normal((n,4,blocks)))
    common=np.exp(0.02*rng.standard_normal((n,1,blocks)))
    return {'pi':pi*common,'gamma':gamma*common}

def _draw(rng,spec,sigma_log,n):
    blocks=12*spec['looks'];kpi=len(spec['pi']);kg=len(spec['gamma'])
    pi=np.asarray(spec['pi'],dtype=np.float64)[None,:,None]*np.exp(sigma_log*rng.standard_normal((n,kpi,blocks)))
    gamma=np.asarray(spec['gamma'],dtype=np.float64).reshape(1,kg,1)*np.exp(sigma_log*rng.standard_normal((n,kg,blocks)))
    if spec['common']:
        f=np.exp(sigma_log*rng.standard_normal((n,1,blocks)));pi=pi*f;gamma=gamma*f
    return {'pi':pi,'gamma':gamma}

def sample_units(cfg,sigma_log,n,seed):
    """n simulated units of one configuration: {'pi': (n, k_Pi, blocks), 'gamma': (n, k_Gamma, blocks)} in ns per request;
    blocks = 24 for a two-look configuration (look 1 uses the first 12), 12 otherwise."""
    return _draw(np.random.default_rng(seed),SPECS[cfg],sigma_log,n)

def _run_spec(spec,stream,sigma_log,policy,units):
    N=policy['units'] if units is None else units;seed=policy['seed'];alpha=tuple(policy['alpha']);started=time.perf_counter()
    rng=np.random.default_rng([seed,stream,int(round(sigma_log*1000))])
    step=max(1,CHUNK_BYTES//((len(spec['pi'])+len(spec['gamma']))*12*spec['looks']*8*4));events=0;triggered=0
    for s in range(0,N,step):
        u=_draw(rng,spec,sigma_log,min(step,N-s));d1=decide_units_np(u['pi'],u['gamma'],1,alpha=alpha);trig=d1['near']
        hit=d1[spec['event']].copy()
        if spec['looks']==2 and trig.any():
            d2=decide_units_np(u['pi'][trig],u['gamma'][trig],2,alpha=alpha);hit[trig]|=d2[spec['event']]
        events+=int(hit.sum());triggered+=int(trig.sum())
    return {'rate':events/N,'units':N,'look2_rate':triggered/N,'seconds':time.perf_counter()-started,'events':events}

def run(config,sigma_log,policy,units=None):
    """One least favourable configuration at one sigma_log: N units (policy 'units' unless given), the full two-look
    procedure, fixed seed. {'rate', 'units', 'look2_rate', 'seconds', 'events'}; look2_rate is the share of units whose
    look-1 verdict is python-near-threshold (look 2 runs for a two-look configuration)."""
    return _run_spec(SPECS[config],CONFIGS.index(config),sigma_log,policy,units)

def one_row_fast_spec(ratio):
    """H16.2 configuration (b): the c-one-look configuration with one Gamma row (row 0) at the true ratio and 11 at 1.0."""
    return dict(SPECS['c-one-look'],gamma=[ratio*2*T_NS]+[2*T_NS]*11)

def _run_rows(spec,stream,sigma_log,policy,units):
    """Look 1 of a one-look configuration with per-row decisions: (rate at which row 0 qualifies, rate at which some row
    qualifies). Row 0 qualifies only in a unit that reached orders 5-9, as in `c`."""
    N=policy['units'] if units is None else units;alpha=tuple(policy['alpha'])
    rng=np.random.default_rng([policy['seed'],stream,int(round(sigma_log*1000))])
    step=max(1,CHUNK_BYTES//((len(spec['pi'])+len(spec['gamma']))*12*spec['looks']*8*4));fast=0;some=0
    for s in range(0,N,step):
        u=_draw(rng,spec,sigma_log,min(step,N-s));d=decide_units_np(u['pi'],u['gamma'],1,alpha=alpha,rows=True)
        fast+=int(d['c_rows'][:,0].sum());some+=int(d['c'].sum())
    return fast/N,some/N

def power(sigma_log,policy,units=None,configuration='all_rows_fast'):
    """I15.5 / H16.2 power report (reported, never a pass condition), look 1, one Pi row at 2 T, k_Gamma = 12 (rank 12 of
    12), true ratio 0.9, 0.8 or 0.7. Configuration (a) 'all_rows_fast': all 12 rows at the ratio; {str(ratio): rate at
    which some row qualifies}. Configuration (b) 'one_row_fast': one row at the ratio, 11 at 1.0; {str(ratio):
    {'fast_row_rate': the fast row qualifies, 'some_row_rate': some row qualifies (false qualifications of the 11 null rows
    included)}}."""
    out={}
    for i,r in enumerate(POWER_RATIOS):
        if configuration=='all_rows_fast':
            spec=dict(SPECS['c-one-look'],gamma=[r*2*T_NS]*12);out[str(r)]=_run_spec(spec,10+i,sigma_log,policy,units)['rate']
        elif configuration=='one_row_fast':
            fast,some=_run_rows(one_row_fast_spec(r),20+i,sigma_log,policy,units);out[str(r)]={'fast_row_rate':fast,'some_row_rate':some}
        else:raise ValueError('configuration must be all_rows_fast or one_row_fast')
    return out

def power_report(sigma_logs,policy,units=None):
    """coverage.json `power`: {str(sigma_log): {'all_rows_fast': ..., 'one_row_fast': ...}} (H16.2)."""
    return {str(sl):{c:power(sl,policy,units,c) for c in ('all_rows_fast','one_row_fast')} for sl in sigma_logs}

def _sha256(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def _equivalence(bu,policy):
    """The job's own check that this code decides as the loaded bench_units.py: 48 mixed units per look whose decisions
    hold both outcomes of every event, and 20 units per configuration and look."""
    alpha=tuple(policy['alpha'])
    for look in (1,2):
        units=mixed_units(48,look,31+look);got=decide_units_np(units['pi'],units['gamma'],look,alpha=alpha);want=decide_units_reference(units,bu,look)
        if any(not np.array_equal(got[k],want[k]) or not want[k].any() or want[k].all() for k in EVENTS):return False
    for cfg in CONFIGS:
        for look in range(1,SPECS[cfg]['looks']+1):
            units=sample_units(cfg,sigma_log=0.10 if look==1 else 0.02,n=20,seed=17+look)
            got=decide_units_np(units['pi'],units['gamma'],look,alpha=alpha);want=decide_units_reference(units,bu,look)
            if any(not np.array_equal(got[k],want[k]) for k in EVENTS):return False
    return True

def job(plan,out,src=SRC):
    """Coordinator job `coverage`: every configuration x sigma_log at the policy's N; writes coverage.json. PASS only
    when the decisions equal the loaded bench_units.py, T equals the owner policy's T and every rate is within its bound.
    The ranks of every decision and the bench_stats digest come from the one bench_stats.py of `src`."""
    previous=_ACTIVE[0];_ACTIVE[0]=Path(src)
    try:return _job(plan,out,Path(src))
    finally:_ACTIVE[0]=previous

def _job(plan,out,src):
    started=time.perf_counter()
    units_path=src/'tools/bench_units.py';policy_path=src/'safety/performance-policy.json'
    stats_sha=_bench_stats_sha256(src)
    spec=importlib.util.spec_from_file_location('bench_units',units_path);bu=importlib.util.module_from_spec(spec);spec.loader.exec_module(bu)
    policy_bytes=policy_path.read_bytes();doc=json.loads(policy_bytes);cov=doc['coverage'];policy=dict(cov,alpha=tuple(bu.ALPHA))
    try:threshold(doc);threshold_ok=True
    except ValueError:threshold_ok=False
    equivalent=_equivalence(bu,policy)
    rates={};look2={};events={};seconds={}
    for cfg in CONFIGS:
        for sl in cov['sigma_log']:
            r=run(cfg,sl,policy);key=str(sl)
            rates.setdefault(cfg,{})[key]=r['rate'];look2.setdefault(cfg,{})[key]=r['look2_rate']
            events.setdefault(cfg,{})[key]=r['events'];seconds.setdefault(cfg,{})[key]=round(r['seconds'],1)
    powers=power_report(cov['sigma_log'],policy)
    within=all(rates[cfg][str(sl)]<=cov['bounds'][SPECS[cfg]['bound']] for cfg in CONFIGS for sl in cov['sigma_log'])
    look2_tested={str(sl):look2['c-two-looks'][str(sl)]>0 for sl in cov['sigma_log']}
    status='PASS' if equivalent and within and threshold_ok else 'FAIL'
    ranks={f'look{look}':{str(m):rank(12*look,bu.ALPHA[look-1]/m) for m in range(1,13)} for look in (1,2)}
    record={'status':status,'rates':rates,'look2_rate':look2,'c_two_looks_tests_look2':look2_tested,'events':events,'run_seconds':seconds,
            'power':powers,'ranks':ranks,'interval_method':'order-statistic',
            'seconds':round(time.perf_counter()-started,1),'bench_units_sha256':_sha256(units_path),
            'coverage_sha256':_sha256(Path(__file__).resolve()),'policy_sha256':hashlib.sha256(policy_bytes).hexdigest(),
            'bench_stats_sha256':stats_sha,'threshold_ns':T_NS,'threshold_ok':threshold_ok,
            'units':cov['units'],'bounds':cov['bounds'],'equivalence':'PASS' if equivalent else 'FAIL',
            'labels':{'look2_rate':'share of units whose look-1 verdict is python-near-threshold; look 2 runs only in a two-look configuration',
                      'power':'per sigma_log, look 1, k_Gamma = 12 (rank 12 of 12), one Pi row at 2 T, true ratio 0.9/0.8/0.7: all_rows_fast = rate at which some Gamma row qualifies when all 12 rows are at the ratio; one_row_fast = one row at the ratio and 11 at 1.0: fast_row_rate (the fast row qualifies) and some_row_rate (some row qualifies, false qualifications of the 11 null rows included); reported, never a pass condition (H16.2)',
                      'ranks':'order-statistic rank k(n, alpha/m) of the bounds, n = 12 (look 1) and 24 (look 2), m = 1..12 (I15.3)',
                      'sigma_log':'in the C configurations the common block factor cancels in X_b/P_b: the two sigma_log runs repeat one experiment'}}
    (Path(out)/'coverage.json').write_text(json.dumps(record,sort_keys=True))
    return {'status':status,'rates':rates,'seconds':record['seconds'],'equivalence':record['equivalence']}
