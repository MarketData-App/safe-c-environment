"""Decision engine (spec 10; Amendment B item 5; Amendment F item 9 C3; Amendment H2-H5). Host-only, pure Python over
recorded evidence. Never imports candidate code; never computes a single score."""
import math
from pathlib import Path
import bench_stats as bs

OUTCOMES=('INVALID_EXPERIMENT','INCONCLUSIVE','KEEP_PYTHON','C_CANDIDATE_FOR_REVIEW','OPTIMIZE_PYTHON_FIRST','USE_EXISTING_PYTHON_LIBRARY','CONSIDER_PYTHON_CONCURRENCY')
PYTHON_LANGUAGES=('python','python-library');LIBRARY_ROWS=('py-optimized','py-library');POOL_ROWS=('py-threads','py-processes')
DIRECT_PYTHON=('py-reference','py-optimized','py-library');METRICS={'wall_ns_per_unit':'wall','cpu_ns_per_unit':'cpu'}
RETAINED='Python retained pending evidence'
# T14-APP-01: the C project gate evidence. FAIL is false; BLOCKED (report absent or for another source identity), None
# and any unknown value are missing evidence, so item 1 is unknown (spec 10 rule 2), never false.
GATES={'PASS':True,'PASS_UNQUALIFIED_FRAMEWORK':True,'FAIL':False}
FACTORS=(-1.0,1.0,-0.5,0.5,-0.25,0.25,-0.75,0.75,-0.1,0.1,-0.6,0.6)   # 12 synthetic block offsets; median offset 0

def t_and(*xs):
    if any(x is False for x in xs):return False
    return None if any(x is None for x in xs) else True
def t_or(*xs):
    if any(x is True for x in xs):return True
    return None if any(x is None for x in xs) else False
def t_not(x):return None if x is None else not x
def consistent(values):
    v=list(values)
    if not v:return None
    return True if all(x is True for x in v) else False if all(x is False for x in v) else None

def stats_of(policy_doc):
    s=policy_doc['statistics'];return {'resamples':s['bootstrap_resamples'],'seed':s['bootstrap_seed'],'interval':s['interval'],'min_blocks':policy_doc['effects']['min_blocks']}

def _paired(base,other,min_blocks):
    ids=set(base)&set(other)
    if len(ids)<min_blocks or len(ids)!=len(base) or len(ids)!=len(other):return False
    return all(not isinstance(v,bool) and isinstance(v,(int,float)) and math.isfinite(v) and v>0 for v in list(base.values())+list(other.values()))

def benefit(base,other,*,relative,min_abs,stats):
    """Amendment H2: True / False / None (unknown) for 'other has a benefit over base'."""
    if not base or not other or not _paired(base,other,stats['min_blocks']):return None,{'reason':'missing, unpaired or invalid blocks'}
    b=bs.paired_block_bootstrap(base,other,stats['resamples'],stats['seed'],stats['interval'])
    d=dict(b,saving_ns_per_unit=bs.median(base.values())-bs.median(other.values()))
    if b['low']>1.0-relative:return False,d
    if b['high']<=1.0-relative:return d['saving_ns_per_unit']>=min_abs,d
    return None,dict(d,reason='interval straddles the threshold')

def limit_ok(base,other,max_regression,stats):
    if max_regression is None:return True,{}
    if not base or not other or not _paired(base,other,stats['min_blocks']):return None,{'reason':'missing, unpaired or invalid blocks'}
    b=bs.paired_block_bootstrap(base,other,stats['resamples'],stats['seed'],stats['interval'])
    if b['high']<=1.0+max_regression:return True,b
    if b['low']>1.0+max_regression:return False,b
    return None,dict(b,reason='interval straddles the limit')

def best_python_of(rows,*,variant,metric,cpu,name,guard):
    """Amendment H3, the one best-Python rule of decide and compare (N4-A02): the row with the smallest `metric` among
    `rows` (ties go to the smaller `name`). A pool row (py-threads, py-processes) counts only when a direct Python row
    exists and the pool row's median CPU per unit is at most (1 + guard) x the CPU of the best direct row (the direct row
    with the smallest metric); guard None admits every pool row. `variant`, `metric`, `cpu` and `name` read a row
    (metric and cpu may give None: such a row never counts, and a None CPU fails the guard). None without a row."""
    rows=[r for r in rows if metric(r) is not None]
    serial=[r for r in rows if variant(r) in DIRECT_PYTHON]
    best_serial=min(serial,key=lambda r:(metric(r),name(r))) if serial else None
    ref=cpu(best_serial) if best_serial is not None else None
    def ok(r):
        if variant(r) in POOL_ROWS and guard is not None:
            c=cpu(r);return ref is not None and c is not None and c<=(1.0+guard)*ref
        return True
    rs=[r for r in rows if ok(r)]
    return min(rs,key=lambda r:(metric(r),name(r))) if rs else None

def label(r):
    if r is None:return 'missing'
    return f"{r['variant']} x{r['workers']}"+(f" [{r['route']}]" if r.get('route') else '')+f" @{r['point']}/{r['mode']}"

class Decider:
    def __init__(self,ev,policy,opportunity,stats):
        self.ev=ev;self.p=policy;self.opp=opportunity or {};self.stats=stats;self.comparisons=[];self.items=[]
        self.metric=METRICS.get(policy.get('metric'));self.modes=list(policy.get('modes') or []);self.points=list(policy.get('points') or [])
        self.caller=[r for r in ev['rows'] if r.get('scope','caller')=='caller']     # B14: kernel and capacity rows never decide
        self.c_memo={}                     # T14-APP-03: one c_items evaluation per C identity in this Decider
        self.begin()
    def begin(self):
        """Start the record of one rule: its comparisons and its notes (T14-APP-03, 04)."""
        self.current={'cmps':[],'notes':[]}
    def note(self,text):self.current['notes'].append(text)
    def agree(self,what,pairs):
        """consistent() over (point, mode, value) triples (H2); a true/false mix is unknown and its values are named (T14-APP-04)."""
        v=consistent([x for _,_,x in pairs]);vals=[x for _,_,x in pairs]
        if v is None and any(x is True for x in vals) and any(x is False for x in vals):
            self.note(f'disagreement: {what}: '+', '.join(f"{p}/{m} {'unknown' if x is None else str(x).lower()}" for p,m,x in pairs))
        return v
    def row(self,point,mode,variant,workers,route=None):
        return next((r for r in self.caller if (r['point'],r['mode'],r['variant'],r['workers'],r.get('route'))==(point,mode,variant,workers,route)),None)
    def med(self,r,which=None):
        s=(r or {}).get(which or self.metric) or {};return bs.median(s.values()) if s else None
    def min_abs(self):
        """The policy's absolute saving per call, per unit of its largest declared tier (demo-latency-2x: 100 ms per large dataset)."""
        v=self.p.get('min_abs_saving_ns_per_call') or 0;tier=(self.p.get('sizes') or [None])[-1];u=self.ev.get('tier_units',{}).get(tier)
        return v/u if u else v
    def cmp(self,name,base,other,point,mode):
        if base is None or other is None:val,d=None,{'reason':'row not measured'}
        else:val,d=benefit(base[self.metric],other[self.metric],relative=self.p['relative_threshold'],min_abs=self.min_abs(),stats=self.stats)
        entry={'name':name,'base':label(base),'other':label(other),'point':point,'mode':mode,'metric':self.p['metric'],'value':val,
               **{k:d.get(k) for k in ('ratio','low','high','blocks','saving_ns_per_unit','reason')}}
        self.comparisons.append(entry);self.current['cmps'].append(entry)
        return val
    def python_rows(self,point,mode):
        return [r for r in self.caller if r['point']==point and r['mode']==mode and r['language'] in PYTHON_LANGUAGES and r['eligible'] and r.get(self.metric)]
    def best_serial(self,point,mode):
        rs=[r for r in self.python_rows(point,mode) if r['variant'] in DIRECT_PYTHON]
        return min(rs,key=lambda r:(self.med(r),label(r))) if rs else None
    def best_python(self,point,mode):
        """Amendment H3: smallest median among rows within the limits; a pool row needs the CPU guard. The rule is
        best_python_of, which bench compare also calls (N4-A02)."""
        return best_python_of(self.python_rows(point,mode),variant=lambda r:r['variant'],metric=self.med,cpu=lambda r:self.med(r,'cpu'),
                              name=label,guard=self.p.get('pool_cpu_guard'))

def _pm(d):return [(p,m) for p in d.points for m in d.modes]

def rule3(d):
    base={m:d.row('baseline',m,'py-reference','direct') for m in d.modes};target=d.p.get('absolute_target_ns_per_unit');margin=d.p.get('target_margin') or 0.0
    met=all(d.med(base[m]) is not None and d.med(base[m])*(1.0+margin)<=target for m in d.modes) if target is not None else False
    others=[r for r in d.caller if r['point']=='baseline' and r['mode'] in d.modes and r['eligible'] and r['variant']!='py-reference']
    return t_or(met,t_not(t_or(*[d.cmp('benefit over baseline',base[r['mode']],r,'baseline',r['mode']) for r in others])))

def c_identities(d):return sorted({(r['variant'],r['workers'],r.get('route')) for r in d.caller if r['language']=='c'},key=str)

OPERATIONAL_COSTS=('transport','deployment_artifacts','observability','failure_handling','retries_idempotency','ownership_abi','native_boundary_maintenance')

def c_items(d,ident):
    """Amendment H4: brief section 12 items 1-8 for one C row identity (variant, workers, route) against best Python.
    Returns (i1, i2_strongest, i2_no_untested, i3, i4, i5, i6, i7, i8). Evaluated once per identity in a Decider
    (T14-APP-03): a repeated call adds the stored comparisons and notes to the current rule and appends no row twice."""
    if ident in d.c_memo:
        m_=d.c_memo[ident];d.current['cmps']+=m_['cmps'];d.current['notes']+=m_['notes'];return m_['result']
    outer=d.current;d.begin()
    v,w,route=ident;keys=_pm(d);xs={k:d.row(k[0],k[1],v,w,route) for k in keys};ps={k:d.best_python(*k) for k in keys}
    lim=d.p.get('limits') or {};name=label(next((x for x in xs.values() if x),None))
    gates=GATES.get(d.ev.get('native_gates'))                                   # T14-APP-01: BLOCKED or None is unknown
    threaded=True if v!='c-threads' else d.ev.get('threaded_correctness')
    i1=t_and(all(x['eligible'] for x in xs.values() if x),gates,threaded)
    i2s=all(ps[k] is not None for k in keys)                                   # compared with the strongest measured Python row
    i2u=not any(o.get('state')=='proposed' for o in d.opp.get('python_options',[]))   # spec rule 5: an untested credible alternative stays explicit
    benefit=d.agree(f'C over best Python {name}',[(*k,d.cmp('C over best Python',ps[k],xs[k],*k)) for k in keys if xs[k] is not None])
    target=d.p.get('absolute_target_ns_per_unit');margin=d.p.get('target_margin') or 0.0
    if target is None:i3=benefit
    else:
        miss=all(ps[k] is not None and d.med(ps[k])>target for k in keys)
        meets=all(xs[k] is not None and bs.median_interval(xs[k][d.metric],d.stats['resamples'],d.stats['seed'],0.025)[1]<=target/(1.0+margin) for k in keys)
        i3=t_or(benefit,miss and meets)
    measured=all(x is not None and x.get('cpu') for x in xs.values()) and all(p_ is not None and p_.get('cpu') for p_ in ps.values())
    # H4 item 4: the caller-scope group peaks at the baseline point, in every policy mode (T14-APP-06). A missing row or
    # a missing peak on a present row is missing evidence: unknown, never false (T14-APP-01).
    m=lim.get('memory_regression');pk=[];mm=[]
    for mode in d.modes:
        xb=d.row('baseline',mode,v,w,route);pb=d.best_python('baseline',mode)
        ok=None if not xb or not pb or xb.get('peak') is None or pb.get('peak') is None else True
        pk.append(ok);mm.append(True if m is None else None if ok is None else xb['peak']<=(1.0+m)*pb['peak'])
    peaks=t_and(*pk) if pk else None;mem=t_and(*mm) if mm else None
    i4=t_and(measured,peaks,d.ev.get('envelope_ok'))
    i5=t_and(d.agree(f'CPU limit {name}',[(*k,limit_ok(ps[k]['cpu'],xs[k]['cpu'],lim.get('cpu_regression'),d.stats)[0]) for k in keys if xs[k] and ps[k]]),
             d.agree(f'latency limit {name}',[(*k,limit_ok(ps[k]['wall'],xs[k]['wall'],lim.get('latency_regression'),d.stats)[0]) for k in keys if xs[k] and ps[k]]) if d.metric=='cpu' else True,mem)
    i6=True if d.ev.get('crossover_measured') else None
    oc=d.opp.get('operational_costs') or {}
    i7=set(oc)==set(OPERATIONAL_COSTS) and all(isinstance(oc[k],str) and oc[k].strip() for k in OPERATIONAL_COSTS)
    appr=d.opp.get('approval') or {}
    i8=appr.get('state')=='APPROVED' and appr.get('baseline_variant')==d.ev.get('baseline_variant','py-reference') and d.ev.get('policy_bound') is True and d.p.get('state') in ('approved','demonstration')
    vals={1:i1,2:t_and(i2s,i2u),3:i3,4:i4,5:i5,6:i6,7:i7,8:i8}
    for n,val in vals.items():d.items.append({'row':name,'item':n,'value':val})
    result=(i1,i2s,i2u,i3,i4,i5,i6,i7,i8)
    d.c_memo[ident]={'result':result,'vals':vals,'name':name,'cmps':d.current['cmps'],'notes':d.current['notes']}
    outer['cmps']+=d.current['cmps'];outer['notes']+=d.current['notes'];d.current=outer
    return result

def _unknown_items(d,ident,vals):
    """Name the unknown items of an identity whose combination is unknown (H2: the unknowns are named)."""
    name=d.c_memo[ident]['name']
    for n,val in vals.items():
        if val is None:d.note(f'unknown item {n} for {name}')

def rule4(d):
    out=[]
    for i in c_identities(d):
        r=c_items(d,i);t=t_and(*r);out.append(t)
        if t is None:_unknown_items(d,i,d.c_memo[i]['vals'])
    return t_or(*out)
def rule5(d):
    out=[]
    for i in c_identities(d):
        i1,i2s,i2u,i3,i4,i5,i6,i7,i8=c_items(d,i);t=t_and(i1,i2s,t_not(i2u),i3,i4,i5,i6,i7,i8);out.append(t)
        if t is None:_unknown_items(d,i,{1:i1,2:t_and(i2s,t_not(i2u)),3:i3,4:i4,5:i5,6:i6,7:i7,8:i8})
    return t_or(*out)
def rule6(d):
    vals=[]
    for m in d.modes:
        b=d.best_python('baseline',m)
        vals.append(('baseline',m,None if b is None else False if b['variant'] not in LIBRARY_ROWS else d.cmp('library benefit over baseline',d.row('baseline',m,'py-reference','direct'),b,'baseline',m)))
    return d.agree('library benefit over baseline',vals)
def rule7(d):
    vals=[]
    for p,m in _pm(d):
        b=d.best_python(p,m)
        vals.append((p,m,None if b is None else False if b['variant'] not in POOL_ROWS or b['workers'] in ('direct',1) else d.cmp('pool benefit over best serial Python',d.best_serial(p,m),b,p,m)))
    return d.agree('pool benefit over best serial Python',vals)

def _rule8_reasons(d):
    """T14-APP-05: name the false items of each C row that shows a benefit (item 3); otherwise say that no C row has one.
    T14-RR-01: the fallback text claims nothing about Python rows; rule 3 is false here, so some row can have a benefit
    over the baseline, and rules 6 and 7 did not match."""
    out=[]
    for ident in c_identities(d):
        memo=d.c_memo.get(ident)
        if memo and memo['vals'][3] is True:
            false=[str(n) for n,val in memo['vals'].items() if val is False]
            out.append(f"no earlier rule matched: {memo['name']} shows a benefit over best Python (item 3) but items {', '.join(false)} are false")
    return out or ['no earlier rule matched: no C row shows a benefit over best Python, and rules 6 and 7 did not match']

RULES=((3,'KEEP_PYTHON',rule3),(4,'C_CANDIDATE_FOR_REVIEW',rule4),(5,'OPTIMIZE_PYTHON_FIRST',rule5),(6,'USE_EXISTING_PYTHON_LIBRARY',rule6),(7,'CONSIDER_PYTHON_CONCURRENCY',rule7))

def _done(d,outcome,rule,reasons):
    best={f'{p}/{m}':label(d.best_python(p,m)) for p,m in _pm(d)} if d.metric else {}
    return {'outcome':outcome,'rule':rule,'reasons':[r[:300] for r in reasons[:50]],'comparisons':d.comparisons[:600],'items':d.items[:600],'best':best}

def decide(ev,policy,opportunity,stats):
    if policy.get('kind')=='unit-threshold':raise ValueError('unit-threshold policies decide through bench_units.decide_units')
    d=Decider(ev,policy,opportunity,stats)
    if ev['status']!='VALID':return _done(d,'INVALID_EXPERIMENT',1,['run status '+ev['status']]+list(ev.get('reasons',[]))[:20])
    need=set(d.points)|{'baseline'}
    bad=[label(r) for r in d.caller if r['point'] in need and r['mode'] in d.modes and not r['eligible']]
    if bad:return _done(d,'INVALID_EXPERIMENT',1,['ineligible required row: '+b for b in bad])
    from bench_model import policy_filled
    if not policy_filled(policy):return _done(d,'INCONCLUSIVE',2,['policy objective missing: the owner template is not filled'])
    missing=[f"{b['variant']} x{b['workers']}"+(f" [{b['route']}]" if b.get('route') else '')+': '+b['reason'] for b in ev.get('blocked',[])]
    missing+=[f'baseline row py-reference missing at baseline/{m}' for m in d.modes if d.row('baseline',m,'py-reference','direct') is None]
    missing+=[f'decision point {p} not measured' for p in d.points if not any(r['point']==p for r in d.caller)]
    if missing:return _done(d,'INCONCLUSIVE',2,['required evidence missing: '+x for x in missing])
    for n,outcome,fn in RULES:
        d.begin();v=fn(d)
        if v is True:return _done(d,outcome,n,[])
        if v is None:      # T14-APP-03, 04: only the unknowns of this rule, each once, and the disagreements
            seen=set();unknown=[]
            for c in d.current['cmps']:
                key=(c['name'],c['base'],c['other'],c['point'],c['mode'])
                if c['value'] is None and key not in seen:
                    seen.add(key);unknown.append(f"unknown deciding comparison: {c['name']} {c['other']} vs {c['base']} ({c.get('reason') or 'interval straddles the threshold'})")
            notes=list(dict.fromkeys(d.current['notes']))
            return _done(d,'INCONCLUSIVE',2,[f'rule {n} ({outcome}) depends on an unknown deciding comparison']+notes+unknown)
    return _done(d,'KEEP_PYTHON',8,_rule8_reasons(d))

def approved(opportunity,baseline='py-reference'):
    """Spec H4 item 8: the opportunity record is APPROVED and its approval names the case's baseline variant."""
    appr=(opportunity or {}).get('approval') if isinstance(opportunity,dict) else None
    return isinstance(appr,dict) and appr.get('state')=='APPROVED' and appr.get('baseline_variant')==baseline

def adoption(result,policy,opportunity=None,baseline='py-reference'):
    """(adoption outcome, demonstration outcome, note). Spec section 10 adoption context and H1: a demonstration-only policy,
    an unfilled template (missing objective) or a missing approval (ruling T29-C4: no approved opportunity record naming
    the baseline; None counts as missing) gives INCONCLUSIVE, with the rule 3-8 result as the labeled demonstration
    outcome. An invalid experiment stays INVALID_EXPERIMENT."""
    if result['outcome']=='INVALID_EXPERIMENT':return 'INVALID_EXPERIMENT',None,'invalid experiment: nothing decided'
    if result['outcome']=='INCONCLUSIVE':return 'INCONCLUSIVE',None,RETAINED
    if policy.get('demonstration_only') or policy.get('state')=='owner-must-fill':return 'INCONCLUSIVE',result['outcome'],RETAINED
    if not approved(opportunity,baseline):return 'INCONCLUSIVE',result['outcome'],RETAINED+' (no approved opportunity record)'
    return result['outcome'],None,'policy decision'

def synthetic_evidence(c):
    """Deterministic evidence from a decision_cases row: 12 blocks per row, value = median x (1 + spread x FACTORS[b])."""
    rows=[]
    for s in c['rows']:
        sp=s.get('spread',0.02);series=lambda m:{b:m*(1.0+sp*f) for b,f in enumerate(FACTORS)}
        rows.append({'point':s['point'],'scope':s.get('scope','caller'),'mode':s['mode'],'variant':s['variant'],'workers':s['workers'],'route':s.get('route'),
                     'route_label':s.get('route_label'),'language':s['language'],'eligible':s.get('eligible',True),'wall':series(s['wall']),'cpu':series(s['cpu']),'peak':s.get('peak')})
    return {'status':c.get('status','VALID'),'reasons':[],'units':{'baseline':1024,'full-dataset':13230},'tier_units':{'tiny':1,'small':256,'medium':1024,'large':13230},
            'rows':rows,'blocked':c.get('blocked',[]),'native_gates':c.get('native_gates'),'threaded_correctness':c.get('threaded_correctness',True),
            'envelope_ok':c.get('envelope_ok',True),'crossover_measured':c.get('crossover_measured',True),'policy_bound':c.get('policy_bound',True),'not_applicable':c.get('not_applicable',[])}

# ---- Task 17: evidence of a recorded run, summary, decision record and report ----
NEXT_ACTIONS={'KEEP_PYTHON':'keep the Python implementation; re-run when the objective or the workload changes',
              'OPTIMIZE_PYTHON_FIRST':'measure the proposed Python alternatives of the opportunity record first',
              'USE_EXISTING_PYTHON_LIBRARY':'adopt the library-backed Python row through review',
              'CONSIDER_PYTHON_CONCURRENCY':'review the Python pool row (CPU guard held)',
              'C_CANDIDATE_FOR_REVIEW':'independent review of the C candidate; never adoption',
              'INCONCLUSIVE':'supply the missing evidence or an owner objective; Python retained',
              'INVALID_EXPERIMENT':'repair the experiment; nothing decided'}

def _current_identity(root):
    from policy import source_identity
    return source_identity(root)[0]

def _language(case,variant):
    return next((v['language'] for v in case.get('variants',[]) if v['id']==variant),'python')

def _suite_status(root,run,names):
    """True when every named suite is PASS in the newest bench-selftest record (artifacts/bench/*/selftest.json) and that
    record names the run's source identity; else None (missing evidence is unknown, never false or true). A selftest
    record without a source identity is never current."""
    from evidence import read_json
    paths=[p for p in Path(root).glob('artifacts/bench/*/selftest.json') if p.is_file() and not p.is_symlink()]
    if not paths or not run.get('source_identity'):return None
    try:doc=read_json(max(paths,key=lambda p:p.stat().st_mtime))
    except (OSError,ValueError):return None
    if not isinstance(doc,dict) or doc.get('source_identity')!=run['source_identity']:return None
    suites=doc.get('suites') if isinstance(doc.get('suites'),dict) else {}
    return True if all(isinstance(suites.get(n),dict) and suites[n].get('status')=='PASS' for n in names) else None

def evidence_from_run(root,run_dir,run,plan,case):
    import bench, bench_model as bm
    from evidence import read_json, file_hash
    policy=bm.load_policy(root);obs=bench.read_jsonl(run_dir/'observations.jsonl');groups={}
    for o in obs:
        if o['warmup'] or o['scope'] not in ('caller','kernel'):continue     # Task 22 (H6): capacity rows are reported by bench compare only and never decide
        groups.setdefault((o.get('point'),o['scope'],o['mode'],o['variant'],o['workers'],o.get('route')),[]).append(o)
    mem={}
    for o in obs:
        if o['scope']=='memory' and o.get('eligible') and (o.get('memory') or {}).get('group_peak_bytes') is not None:
            mem.setdefault((o['variant'],o['workers'],o.get('route'),o.get('mode')),[]).append(o['memory']['group_peak_bytes'])
    rows=[]
    for (point,scope,mode,variant,workers,route),os_ in sorted(groups.items(),key=str):
        peaks=mem.get((variant,workers,route,mode)) or []
        rows.append({'point':point,'scope':scope,'mode':mode,'variant':variant,'workers':workers,'route':route,
                     'route_label':next((o.get('route_label') for o in os_ if o.get('route_label')),None),'language':_language(case,variant),
                     'eligible':all(o['eligible'] for o in os_),'wall':bench.per_trial(os_,'wall_ns'),
                     'cpu':{b:v*1000.0 for b,v in bench.per_trial(os_,'cpu_usage_usec').items()},'peak':bs.median(peaks) if peaks and point=='baseline' else None})
    blocked=[{'variant':b.get('variant'),'workers':b.get('workers'),'route':b.get('route'),'reason':str(b.get('reason'))[:200]} for b in plan.get('blocked_rows') or []]
    units={s['point']:policy['sizes'][s['tier']] for s in plan.get('sessions',[])}
    gates=None
    if any(v['language']=='c' for v in case.get('variants',[]) if v.get('status')=='implemented'):
        rep=Path(root)/'artifacts/project-report.json';gates='BLOCKED'
        if rep.is_file():
            r=read_json(rep)
            if r.get('project_dir')==(run.get('plan') or {}).get('project_dir') and r.get('source_identity')==run.get('source_identity'):gates=r.get('verdict')
    threaded=_suite_status(root,run,('B04','B11'))      # PASS of both suites in the newest current bench-selftest evidence, else None
    return {'status':run['status'],'reasons':run.get('reasons',[]),'units':units,'tier_units':dict(policy['sizes']),'rows':rows,'blocked':blocked,'native_gates':gates,
            'threaded_correctness':threaded,'envelope_ok':(run.get('envelope') or {}).get('cpus')==policy['envelope']['cpus'],
            'crossover_measured':any(r['point'].startswith('crossover-') for r in rows),'policy_bound':run.get('policy_sha256')==file_hash(Path(root)/'safety/performance-policy.json'),
            'baseline_variant':'py-reference'}   # spec 10: the baseline row of the rule policies

DEFAULT_STATS={'resamples':10000,'seed':20261007,'interval':0.95}     # the policy statistics (bootstrap 10,000, seed, 95 %)

def _row_text(r,ev_rows,stats=None):
    """Spec 10 (T17-APP-02): the row, its median per unit and its 95 % interval against the baseline row (py-reference,
    direct, same point and mode): the paired-block bootstrap of the wall ratio."""
    if not r:return 'none'
    s=(r.get('wall') or {})
    if not s:return label(r)
    text=f"{label(r)}: median {bs.median(s.values()):.4g} ns/unit"
    if r['variant']=='py-reference' and r['workers']=='direct' and not r.get('route'):return text+' (the baseline row)'
    base=next((x for x in ev_rows if (x['point'],x['mode'],x['variant'],x['workers'],x.get('route'))==(r['point'],r['mode'],'py-reference','direct',None) and x.get('wall')),None)
    if base is None:return text+'; no baseline row for an interval'
    st=stats or DEFAULT_STATS
    try:b=bs.paired_block_bootstrap(base['wall'],s,st['resamples'],st['seed'],st['interval'])
    except ValueError:return text+'; interval against py-reference not available (unpaired blocks)'
    return text+f"; ratio {b['ratio']:.3g} [{b['low']:.3g}, {b['high']:.3g}] ({st['interval']*100:g} % interval) vs py-reference"

def summary(ev,result,opportunity,case,stats=None):
    caller=[r for r in ev['rows'] if r['scope']=='caller'];py=[r for r in caller if r['language'] in PYTHON_LANGUAGES and r['wall']]
    cs=[r for r in caller if r['language']=='c' and r['wall']];med=lambda r:bs.median(r['wall'].values())
    bp=min(py,key=med) if py else None;bc=min(cs,key=med) if cs else None
    routes={}
    for r in caller:
        if r.get('route'):routes.setdefault(r['route'],{'route':r['route'],'label':r.get('route_label') or '','rows':0})['rows']+=1
    unknown=[c for c in result['comparisons'] if c['value'] is None]
    return {'problem':str(opportunity.get('operation') or case.get('description',''))[:600],
            'best_python':_row_text(bp,caller,stats)[:600],'best_c':(_row_text(bc,caller,stats)+(f" (route label: {bc.get('route_label')})" if bc and bc.get('route_label') else ''))[:600],
            'size_range':', '.join(sorted({f"{p}={u}" for p,u in ev['units'].items()}))[:600],
            'caller_latency':'; '.join(f"{label(r)} {med(r):.4g} ns/unit" for r in sorted(caller,key=med)[:6] if r['wall'])[:600],
            'cpu':'; '.join(f"{label(r)} {bs.median(r['cpu'].values()):.4g} ns/unit" for r in caller if r['cpu'])[:600],
            'memory':'; '.join(f"{label(r)} group peak {r['peak']}" for r in caller if r.get('peak') is not None)[:600] or 'not measured',
            'uncertainty':(f"{len(unknown)} unknown comparisons; " if unknown else '')+'95 % paired-block intervals per comparison in the record',
            'missing_evidence':'; '.join(x for x in result['reasons'] if 'missing' in x)[:600] or 'none',
            'complexity':('C17 project module with the 23 project gates; routes: '+', '.join(sorted(routes)) if cs else 'Python only')[:600],
            'cpu_tradeoff':_cpu_tradeoff(bp,bc,stats)[:600],
            'assumptions':('; '.join(f"{label(r)}: workers {r['workers']}, one chunk per worker, mode {r['mode']}" for r in [x for x in (bp,bc) if x]) or 'none')[:600],
            'frequency':('production frequency: '+str(opportunity.get('frequency','unknown')))[:600],
            'next_action':NEXT_ACTIONS[result['outcome']],'routes':list(routes.values())[:8]}

def _cpu_tradeoff(bp,bc,stats=None):
    """H4 item 5: a tradeoff statement when the lower end of the 95 % CPU ratio interval (C over Python) is above 1."""
    if not bp or not bc or not bp.get('cpu') or not bc.get('cpu'):return 'not measured'
    st=stats or {'resamples':10000,'seed':20261007,'interval':0.95}
    try:b=bs.paired_block_bootstrap(bp['cpu'],bc['cpu'],st['resamples'],st['seed'],st['interval'])
    except ValueError:return 'not comparable (unpaired blocks)'
    text=f"C/Python CPU ratio {b['ratio']:.3g} [{b['low']:.3g}, {b['high']:.3g}]"
    return text+(' - a latency gain with more CPU is a tradeoff, not an efficiency win' if b['low']>1.0 else '')

def decision_record(root,run,plan,case,policy_name,result,ev,opportunity,cgroup_unrecorded=False,stats=None):
    from bench_model import load_decision_policy, policy_filled
    from evidence import file_hash
    pol=load_decision_policy(root,policy_name);adopt,demo,note=adoption(result,pol,opportunity,baseline=ev.get('baseline_variant','py-reference'));now=_current_identity(root)
    stale=run.get('source_identity')!=now;local=(run.get('dataset') or {}).get('kind')=='local'
    quality='stale' if stale else 'owner fixture, local run, aggregate' if local else 'exploratory (smoke)' if run.get('mode')=='smoke' else 'decision'
    return {'schema_version':1,'run_id':run['run_id'],'case':run['case'],'local':local,
            'policy':{'name':policy_name,'sha256':file_hash(Path(root)/'safety/performance-policy.json'),'demonstration_only':bool(pol.get('demonstration_only')),'filled':policy_filled(pol)},
            'source_identity_run':run.get('source_identity'),'source_identity_decision':now,'stale':stale,'image_id':run.get('image_id'),'evidence_quality':quality,
            'outcome':result['outcome'],'rule':result['rule'],'adoption_outcome':adopt,'demonstration_outcome':demo,'adoption_note':note,'adoption_authorized':False,'cgroup_identity_unrecorded':bool(cgroup_unrecorded),'qualification':None,'sensitivity':None,'windows':None,
            'reasons':result['reasons'],'comparisons':result['comparisons'],'items':result['items'],'summary':summary(ev,result,opportunity,case,stats)}

def render_markdown(records):
    md=['# Decision','','No single score. Each policy gives the rule outcome and the adoption outcome; a demonstration policy never adopts.','']
    for r in records:
        md+=[f"## Policy {r['policy']['name']}"+(' (demonstration only)' if r['policy']['demonstration_only'] else ''),'',
             f"- Rule {r['rule']}: {r['outcome']}"+(f" (demonstration outcome: {r['demonstration_outcome']})" if r['demonstration_outcome'] else ''),
             f"- Adoption outcome: {r['adoption_outcome']} - {r['adoption_note']}",f"- Evidence quality: {r['evidence_quality']}"+(' (source changed after the run)' if r['stale'] else '')+(' (cgroup identity unrecorded)' if r.get('cgroup_identity_unrecorded') else '')]
        md+=[f"- {k.replace('_',' ')}: {v}" for k,v in r['summary'].items() if k!='routes']
        md+=[f"- route {x['route']}: {x['label']} ({x['rows']} rows)" for x in r['summary']['routes']]
        md+=[f"- reason: {x}" for x in r['reasons'][:10]]+['']
    return '\n'.join(md)+'\n'
