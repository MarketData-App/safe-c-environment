"""Capacity scope host side (spec 14 Phase 3, brief 7.3; Amendment H6; the capacity part of the B17 scopes; configurations beyond the envelope are a B12 guardrail)."""
import math
from evidence import GateError
REQUIRED_SAMPLES={50:20,90:100,99:1000};LABEL='exploratory; capacity rows never decide'
NAMES=('serial-workers','threaded-worker','python-pool')
TRIAL_KEYS=('trial_id','block','order','point','scope','mode','variant','workers','route','tier','configuration','clients','servers','requests_per_client','loops','warmup')
BLOCKED_KEYS=('configuration','variant','reason')
REQUESTS_MAX=64
# T22-APP-03: the configuration/variant pairs that make_server can start. serial-workers runs direct variants (workers 'direct');
# threaded-worker and python-pool run pooled variants with N workers (bench_model: direct variants use workers ["direct"] only).
DIRECT_VARIANTS=('py-reference','py-optimized','py-library','c-serial');POOLED_VARIANTS=('py-threads','py-processes','c-threads')
PAIRS={'serial-workers':DIRECT_VARIANTS,'threaded-worker':POOLED_VARIANTS,'python-pool':POOLED_VARIANTS}
CPU_NOTE='not reconciled (B15)'     # T22-APP-01 (choice b): the capacity session has no cgroup window in the H7/B15 whole-workload reconciliation

def percentiles(samples):
    s=sorted(samples);n=len(s);out={'n':n,'reasons':{}}
    for p,need in REQUIRED_SAMPLES.items():
        if n<need:out[f'p{p}']=None;out['reasons'][f'p{p}']=f'too few samples ({n} < {need})'
        else:out[f'p{p}']=s[math.ceil(p*n/100)-1]
    return out

def capacity_trials(case,policy,envelope,mode,seed):
    import random
    from bench_plan import trial_estimate
    cap=case.get('capacity')
    if not cap or 'capacity' not in case['scopes']:return [],[],0.0
    pc=policy['capacity'];n=envelope['cpus'];size=policy['sizes'][cap['tier']];status={v['id']:v['status'] for v in case['variants']}
    names=[c['name'] for c in cap['configurations']]
    if len(names)!=len(set(names)):raise GateError('capacity configuration names must be unique')
    clients=pc['smoke_clients'] if mode=='smoke' else cap['clients'];blocks=pc['trials']['smoke' if mode=='smoke' else 'decision'];specs=[];blocked=[]
    for c in cap['configurations']:
        if c['name'] not in NAMES:raise GateError('unknown capacity configuration')
        if c['variant'] not in PAIRS[c['name']]:raise GateError(f"capacity configuration {c['name']} cannot run variant {c['variant']}")   # T22-APP-03
        if status.get(c['variant'])!='implemented':blocked.append({'configuration':c['name'],'variant':c['variant'],'reason':f"variant {c['variant']} not implemented"});continue
        for k in clients:
            if k>n:blocked.append({'configuration':c['name'],'variant':c['variant'],'clients':k,'reason':f'{k} clients beyond the {n}-CPU envelope'});continue
            specs.append((c,k))
    trials=[];total=0.0
    for b in range(blocks):
        order=list(specs);random.Random(f'{seed}:capacity:{b}').shuffle(order)
        for o,(c,k) in enumerate(order):
            servers=n if c['name']=='serial-workers' else 1;workers='direct' if c['name']=='serial-workers' else n
            est=cap['requests_per_client']*k*trial_estimate(policy,c['variant'],size,1)
            if est>pc['trial_seconds_max']:raise GateError(f"capacity trial {c['name']} x{k} exceeds the {pc['trial_seconds_max']} s bound; a new case version must choose fewer requests")
            total+=est
            trials.append({'trial_id':f"capacity-b{b:02d}-{o:02d}",'block':b,'order':o,'point':'capacity','scope':'capacity','mode':'warm','variant':c['variant'],'workers':workers,
                           'route':c.get('route'),'tier':cap['tier'],'configuration':c['name'],'clients':k,'servers':servers,'requests_per_client':cap['requests_per_client'],'loops':1,'warmup':False})
    return trials,blocked,total

def _count(v,lo=1,hi=None):return type(v) is int and v>=lo and (hi is None or v<=hi)

def trial_format(t):
    """B12 (Task 22 defines the format that bench_guardrails reads): None for a capacity trial of the capacity_trials shape,
    else the first problem. The configuration rule of H6: serial-workers has N servers with workers 'direct'; threaded-worker
    and python-pool have 1 server with N workers."""
    if not isinstance(t,dict):return 'not an object'
    if sorted(t)!=sorted(TRIAL_KEYS):return 'keys differ from the capacity trial format'
    if (t['point'],t['scope'],t['mode'],t['loops'],t['warmup'])!=('capacity','capacity','warm',1,False):return 'point, scope, mode, loops or warmup differ'
    if t['configuration'] not in NAMES:return 'unknown configuration'
    if not (isinstance(t['trial_id'],str) and _count(t['block'],0) and _count(t['order'],0) and isinstance(t['variant'],str) and isinstance(t['tier'],str)):return 'trial identity malformed'
    if not (t['route'] is None or isinstance(t['route'],str)):return 'route malformed'
    if not (_count(t['clients']) and _count(t['servers']) and _count(t['requests_per_client'],1,REQUESTS_MAX)):return 'clients, servers or requests_per_client malformed'
    serial=t['configuration']=='serial-workers'
    if serial and t['workers']!='direct':return 'serial-workers uses workers direct'
    if not serial and (t['servers']!=1 or not _count(t['workers'])):return f"{t['configuration']} uses 1 server with integer workers"
    return None

def blocked_format(b):
    if not isinstance(b,dict) or not set(BLOCKED_KEYS)<=set(b) or not set(b)<=set(BLOCKED_KEYS)|{'clients'}:return 'not a blocked capacity configuration'
    if b['configuration'] not in NAMES or not isinstance(b['reason'],str) or ('clients' in b and not _count(b['clients'])):return 'blocked capacity configuration malformed'
    return None

def cpu_need(t):
    """CPUs a capacity trial claims: servers x workers ('direct' is 1)."""
    return t['servers']*(1 if t['workers']=='direct' else t['workers'])

def expected_work(t,sizes):
    """Work units of a complete capacity trial: every request of every client processes the tier's rows."""
    return sizes[t['tier']]*t['clients']*t['requests_per_client']

def check_capacity(plan,observations):
    planned={t['trial_id']:t for t in plan.get('capacity',[])};seen={};problems=[]
    for o in observations:
        if o.get('scope')=='capacity':seen.setdefault(o['trial_id'],[]).append(o)
    for tid,t in planned.items():
        got=seen.get(tid,[])
        if len(got)!=1:problems.append(f'{tid}: {len(got)} observations, 1 planned');continue
        c=got[0].get('capacity') or {};want=t['clients']*t['requests_per_client']
        if c.get('completed')!=want:problems.append(f"{tid}: {c.get('completed')} of {want} requests completed")
        elif c.get('errors'):problems.append(f"{tid}: {c['errors']} request errors")
        elif len(c.get('latencies_ns') or [])!=want or not got[0].get('eligible'):problems.append(f'{tid}: latency samples or eligibility incomplete')
    problems+=[f'{tid}: not in the plan' for tid in seen if tid not in planned]
    return problems

def capacity_rows(observations,policy):
    import bench_stats as bs
    by={}
    for o in observations:
        if o.get('scope')=='capacity' and o.get('capacity'):by.setdefault((o['capacity']['configuration'],o['capacity']['clients'],o.get('variant'),o.get('route',o['capacity'].get('route'))),[]).append(o)
    rows=[]
    for (conf,k,variant,route),all_ in sorted(by.items(),key=str):
        os_=[o for o in all_ if o.get('eligible') is True]     # T22-APP-02: only eligible trials are pooled; the others are counted
        thr=[o['work_units']*1e9/o['wall_ns'] for o in os_ if o.get('wall_ns')];cpu=[o['cpu_usage_usec']*1000.0/o['work_units'] for o in os_ if o.get('work_units') and o.get('cpu_usage_usec') is not None]
        lat=[x for o in os_ for x in o['capacity']['latencies_ns']]
        rows.append({'configuration':conf,'clients':k,'variant':variant,'route':route,'trials':len(os_),'ineligible_trials':len(all_)-len(os_),'throughput_units_per_s':bs.summarize(thr),
                     'cpu_ns_per_unit':bs.summarize(cpu),'cpu_ns_per_unit_note':CPU_NOTE,'latency_ns':percentiles(lat),'label':LABEL})
    return rows

REPORT_TITLE='## Capacity (exploratory; capacity rows never decide)'

def report_lines(rows):
    """report_cmd's capacity section: one line per capacity row; a percentile without enough samples prints n/a (<reason>)."""
    fmt=lambda x:'n/a' if x is None else f'{x:.4g}' if isinstance(x,float) else str(x)
    def pct(lat,p):return f'p{p} '+(fmt(lat[f"p{p}"]) if lat.get(f'p{p}') is not None else f"n/a ({lat['reasons'].get(f'p{p}','no samples')})")
    out=[REPORT_TITLE]
    for r in rows:
        lat=r['latency_ns']
        out.append(f"- {r['configuration']}, {r['clients']} clients, {r['variant']}, route {r['route'] or 'none'}: {r['trials']} trials ({r.get('ineligible_trials',0)} ineligible excluded), throughput median "
                   f"{fmt(r['throughput_units_per_s']['median'])} units/s, CPU median {fmt(r['cpu_ns_per_unit']['median'])} ns/unit ({r.get('cpu_ns_per_unit_note',CPU_NOTE)}), "
                   +', '.join(pct(lat,p) for p in REQUIRED_SAMPLES)+' (ns)')
    return out if rows else out+['none']

def run_capacity(root,run_dir,plan,base,restore,policy,session_factory,finish):
    from bench import last_json, passed, read_jsonl
    s=session_factory(root,run_dir);reasons=[];ev=[];got=[]
    try:
        r=s.job({**base,'job':'capacity','trials':plan['capacity'],'latency_samples_max':policy['capacity']['latency_samples_max'],
                 'deadline_seconds':policy['job_deadlines']['session']},'capacity',policy['job_deadlines']['session'],restore=restore);ev.append(r['evidence_path']);row=last_json(r['output'])
        if passed(r) and row.get('status')=='PASS':got=read_jsonl(s.fetch('bench/out/capacity.jsonl',run_dir/'capacity'/'capacity.jsonl'))
        else:reasons.append('capacity session did not complete')
    finally:finish(s)
    return got,reasons+check_capacity(plan,got),ev
