"""./tools/safety bench: host side. Plans, launches bench containers and collects evidence.
Never imports candidate code (benchmarks/)."""
from __future__ import annotations
from pathlib import Path
import argparse, json, math, os, re, shutil, tempfile, uuid
from fractions import Fraction
from evidence import GateError, Runner, atomic_json, file_hash, load_project_json, loads_capped, PROJECT_JSON_MAX_BYTES, read_json, passed
from evidence import read_jsonl as evidence_read_jsonl
import bench_model as bm

PYTHONPATH='/opt/bench-python:/src/benchmarks/performance/python'
EXIT={'PASS':0,'FAIL':1,'BLOCKED':2}

def last_json(output):
    for line in reversed((output or '').splitlines()):
        line=line.strip()
        if line.startswith('{'):
            try:return loads_capped(line,'container-output')      # FR3-19: container output through the boundary
            except ValueError:return {}
    return {}

def new_run_dir(root,kind):
    run_id=uuid.uuid4().hex;path=Path(root)/'artifacts/bench'/run_id;path.mkdir(parents=True)
    atomic_json(path/'kind.json',{'kind':kind,'run_id':run_id});return path

def expected_versions(root):
    return dict(read_json(Path(root)/'developer.lock.json').get('bench_python',{}))

class BenchSession:
    """One bench container (developer image) through the protected launcher."""
    def __init__(self,root,run_dir,*,fixture=None,redacted=False):
        from developer import inputs as developer_inputs
        _,dev_lock,toolchain=developer_inputs(root)
        self.root=Path(root);self.redacted=redacted
        self.lock=dict(toolchain,image_id=dev_lock['image_id'])
        self.scratch=Path(tempfile.mkdtemp(prefix='safe-c-bench-'));self.evidence_paths=[]
        try:
            self.runner=Runner(self.root,run_dir,self.lock,self.scratch,build_profile='bench',purpose='bench',
                               file_mounts={'/data/dataset.json':fixture} if fixture else None,redacted=redacted)
        except BaseException:
            shutil.rmtree(self.scratch,ignore_errors=True);raise
    def job(self,plan,label,timeout,restore=()):
        """Run one coordinator job. Every evidence record it writes goes to evidence_paths."""
        path=self.scratch/'plan.json';atomic_json(path,plan)
        self.runner.start()
        scratch=self.runner.run(['mkdir','-p','/work/bench/out','/work/bench/data','/work/bench/private'],label='bench-scratch')
        self.evidence_paths.append(scratch['evidence_path'])
        if not passed(scratch):raise GateError('bench scratch preparation failed')
        self.runner.restore('bench/plan.json',path,label=label)     # DD-02: each receipt names its destination job
        for item in restore:self.runner.restore(*item,label=label)   # (relative, source[, fetched sha256]): e.g. the run reference (Task 16), a shared check file (DD-01)
        result=self.runner.run(['python3','/src/container/bench-coordinator.py','bench/plan.json'],timeout=timeout,env={'PYTHONPATH':PYTHONPATH},label=label)
        self.evidence_paths.append(result['evidence_path']);return result
    def fetch(self,relative,destination):
        if self.redacted and relative!='bench/out/aggregate.json':raise GateError('a local run collects only its aggregate document')
        return self.runner.fetch(relative,destination)
    def fetched_sha256(self,destination):
        """DD-01: the sha256 of the bytes that fetch collected into destination (the Runner's collection record)."""
        return self.runner.collection_digests[str(Path(destination).absolute())]
    def envelope(self):
        return (self.runner.session or {}).get('bench',{}).get('envelope')
    @staticmethod
    def image(root):return read_json(Path(root)/'developer.lock.json')['image_id']
    def close(self):
        try:self.runner.close()
        finally:shutil.rmtree(self.scratch,ignore_errors=True)

def emit(args,result,text):
    print(json.dumps(result,sort_keys=True) if args.format=='json' else text)

def active_before(session):
    """The launcher's observed bench.active_before of the session (active containment jobs at admission), or None when the
    launcher recorded none. Never a substituted 0 (approval P1-R1-08: evidence records observed values only)."""
    record=getattr(session.runner,'session',None)
    bench=record.get('bench') if isinstance(record,dict) else None
    value=bench.get('active_before') if isinstance(bench,dict) else None
    return value if type(value) is int and value>=0 else None

def lock_held(session):
    """Nanoseconds the session held the exclusive bench admission lock (0 when the launcher reports none)."""
    interval=getattr(getattr(session.runner,'launcher',None),'bench_interval',None)
    return (interval() if callable(interval) else None) or 0

def doctor_probe(root,run_dir):
    """The doctor job in its own bench container. Returns the result without printing; BLOCKED on any launcher error."""
    policy=bm.load_policy(root);session=None;evidence=[]
    try:
        session=BenchSession(root,run_dir);evidence=session.evidence_paths
        r=session.job({'schema_version':1,'job':'doctor','run_id':run_dir.name,'expected':expected_versions(root),'deadline_seconds':policy['job_deadlines']['doctor']},
                      'bench-doctor',policy['job_deadlines']['doctor'])
        row=last_json(r['output']);envelope=session.envelope()
        status=doctor_status(row,envelope) if passed(r) else 'BLOCKED'
        result={'status':status,'envelope':envelope,'missing_counters':row.get('missing_counters'),'libraries':row.get('libraries'),
                'thread_environment':row.get('thread_environment'),'runtime':row.get('runtime'),'cpuset':row.get('cpuset'),'cpu_max':row.get('cpu_max'),   # B12
                'evidence_paths':list(evidence)}
    except GateError as exc:
        result={'status':'BLOCKED','reason':str(exc),'evidence_paths':list(evidence)}
    finally:
        if session is not None:
            session.close();result['lock_held_ns']=lock_held(session)
    return result

def doctor_status(row,envelope):
    """The doctor status rule: PASS only when the coordinator row passes and the launcher recorded a CPU envelope."""
    return 'PASS' if isinstance(row,dict) and row.get('status')=='PASS' and envelope else 'BLOCKED'

def doctor(root,args):
    run_dir=new_run_dir(root,'doctor');result=doctor_probe(root,run_dir);result.pop('lock_held_ns',None)
    atomic_json(run_dir/'doctor.json',result)
    emit(args,result,'bench doctor: '+result['status']);return EXIT[result['status']]

def list_cases(root,args):
    rows=[];project=project_arg(root,args)
    for case_id in bm.case_ids(root,project):
        case=bm.load_case(root,case_id,project);rows.append({'case':case_id,'version':case['version'],'variants':{v['id']:v['status'] for v in case['variants']}})
    emit(args,{'status':'PASS','cases':rows},'\n'.join(r['case']+': '+', '.join(f'{k}={v}' for k,v in r['variants'].items()) for r in rows));return 0

MIB=1048576
CPU_CONTROLS=('control-zero','wait','spin','spin-children-2','native-spin','short-children-20')
MEMORY_CONTROLS=('child-touch-64','sequential-children-64x2','children-32-64','shared-mapping-64','short-spike-64','untouched-1024')
UNITS={'wall_ns':'ns (time.perf_counter_ns at the handshake reads)','cpu_usage_usec':'us (cgroup v2 cpu.stat)','memory':'bytes (cgroup v2 memory.current, memory.peak)',
       'maxrss':'KiB (getrusage ru_maxrss)','ratio':'Fraction(cpu_usage_usec*1000, wall_ns): exact rational arithmetic, compared with Fraction(str(band))',
       'resolution':'see the policy resolution block in this document'}

def _band(value):return Fraction(str(value))   # the decimal policy value, exactly

def _check(name,ok,reason,blocked=False):return {'name':name,'status':'BLOCKED' if blocked else 'PASS' if ok else 'FAIL','reason':reason}

def _overall(checks):
    s=[c['status'] for c in checks];return {'status':'BLOCKED' if 'BLOCKED' in s and 'FAIL' not in s else 'FAIL' if 'FAIL' in s or not s else 'PASS','checks':checks}

def _missing(rows,names):
    """A control that did not run, or whose process failed, is a FAIL, never a silent pass."""
    seen={r.get('name'):r for r in rows};checks=[_check(n,False,'control row missing') for n in names if n not in seen]
    failed={r['name']:r for r in rows if r.get('exit_code',0)!=0}
    return checks+[_check(n,False,'control process failed or handshake incomplete '+json.dumps((r.get('extra') or {}).get('errors',[]))) for n,r in sorted(failed.items())],set(failed)

def evaluate_cpu_controls(rows,policy,envelope):
    c=policy['controls'];checks,failed=_missing(rows,CPU_CONTROLS)
    for r in rows:
        if r['name'] in failed:continue
        if r['name']=='control-zero':checks.append(_check(r['name'],True,'handshake overhead reported, never subtracted'));continue
        if r.get('cpu_usage_usec') is None or not r.get('wall_ns'):checks.append(_check(r['name'],False,'cpu.stat unavailable; metric is null',True));continue
        ratio=Fraction(r['cpu_usage_usec']*1000,r['wall_ns']);shown=f'cpu/wall {float(ratio):.3f}'
        if r['name']=='wait':checks.append(_check('wait',ratio<=_band(c['wait_max_ratio']),shown))
        elif r['name']=='spin':checks.append(_check('spin',_band(c['spin_ratio'][0])<=ratio<=_band(c['spin_ratio'][1]),shown))
        elif r['name']=='spin-children-2':
            if envelope.get('cpus',0)<2:checks.append(_check(r['name'],False,'fewer than 2 CPUs: multicore BLOCKED',True))
            else:checks.append(_check(r['name'],_band(c['two_children_ratio'][0])<=ratio<=_band(c['two_children_ratio'][1]),shown))
        elif r['name'] in ('native-spin','short-children-20'):
            x=r['extra'];kids=x.get('children_cpu_usec',0);self_=x.get('parent_self_cpu_usec',0);total=r['cpu_usage_usec']
            ok=(type(kids) is int and type(self_) is int and kids>0 and total>=_band(c['native_min_share'])*kids   # inclusive: the workers are counted
                and total<=(kids+self_)*_band(c['spin_ratio'][1]))                                            # once: no double counting
            reason=f'cgroup {total} us vs children {kids} us + parent self {self_} us (inclusive, counted once)'
            if r['name']=='native-spin':ok=ok and self_*10<total
            else:
                polled=x.get('polled_tree_cpu_usec')
                ok=(ok and x.get('children')==c['short_children'] and type(polled) is int and 'lower bound' in str(x.get('polled_label',''))
                    and polled*10<total)   # the live-tree poll at the handshakes misses the exited children
                reason+=f'; polled live tree {polled} us (lower bound) misses them'
            checks.append(_check(r['name'],ok,reason))
        else:checks.append(_check(r['name'],False,'unknown control'))
    return _overall(checks)

def evaluate_memory_controls(rows,policy):
    c=policy['controls'];checks,failed=_missing(rows,MEMORY_CONTROLS)
    for r in rows:
        if r['name'] in failed:continue
        peak,ready,post=r.get('group_peak_bytes'),r.get('ready_current'),r.get('post_current')
        if peak is None or ready is None or post is None:checks.append(_check(r['name'],False,'memory.peak or memory.current unavailable',True));continue
        rise=peak-ready;x=r['extra'];n=r['name'];quiet=c['quiet_mib']*MIB;label=str(x.get('label',''))
        freed=post-ready<quiet   # B05: the control frees its allocations before it exits
        try:
            if n=='child-touch-64':ok=rise>=c['touch_min_mib']*MIB
            elif n=='sequential-children-64x2':
                summed=sum(x['child_maxrss_kib'])*1024;ok=summed>rise+c['touch_mib']//2*MIB and peak!=summed
            elif n=='children-32-64':ok=x['rusage_children_maxrss_kib']==max(x['child_maxrss_kib']) and 'largest waited child' in label
            elif n=='shared-mapping-64':ok=sum(x['rss_kib'])*1024*10>=18*c['touch_mib']*MIB and max(x['uss_kib'])*1024<quiet
            elif n=='short-spike-64':ok=x['sampled_max_bytes'] is not None and x['sampled_max_bytes']-ready<quiet and rise>=c['touch_min_mib']*MIB and 'lower bound' in label
            elif n=='untouched-1024':ok=rise<quiet
            else:ok=False
        except (KeyError,TypeError,ValueError):ok=False
        checks.append(_check(n,ok and freed,f'rise {rise//MIB} MiB; after the control {(post-ready)//MIB} MiB above ready'))
    return _overall(checks)

def _rows(text):return [loads_capped(x,'container-jsonl') for x in text.splitlines() if x.strip()]   # FR3-19: fetched rows

def run_controls(root,run_dir):
    """B02/B03 in one container; B05 one container per memory control, so memory.peak (host, at disposal) belongs to that control."""
    policy=bm.load_policy(root);c=policy['controls'];deadline=policy['job_deadlines']['control'];evidence=[]
    sizes={'short_children':c['short_children'],'touch_mib':c['touch_mib'],'untouched_mib':c['untouched_mib']}   # policy values travel in the plan
    s=BenchSession(root,run_dir)
    try:
        r=s.job({'schema_version':1,'job':'controls-cpu','run_id':run_dir.name,'controls':list(CPU_CONTROLS),
                 'seconds':c['control_seconds'],'native_mib':c['native_megabytes'],'deadline_seconds':deadline,**sizes},'controls-cpu',deadline)
        cpu=_rows(s.fetch('bench/out/controls-cpu.jsonl',run_dir/'controls-cpu.jsonl').read_text()) if last_json(r['output']).get('controls') else [];envelope=s.envelope()
    finally:
        evidence+=s.evidence_paths;s.close()
    memory=[]
    for name in MEMORY_CONTROLS:
        s=BenchSession(root,run_dir)
        try:
            r=s.job({'schema_version':1,'job':'controls-memory','run_id':run_dir.name,'control':name,'seconds':c['control_seconds'],'native_mib':0,'deadline_seconds':deadline,**sizes},'controls-'+name,deadline)
            rows=_rows(s.fetch('bench/out/controls-memory.jsonl',run_dir/f'controls-{name}.jsonl').read_text()) if last_json(r['output']).get('controls') else []
        finally:
            evidence+=s.evidence_paths;s.close()
        after=((s.runner.session or {}).get('lifecycle') or {}).get('counters_after',{})
        for row in rows:row['group_peak_bytes']=int(after['memory.peak']) if 'memory.peak' in after else None
        memory+=rows
    result={'cpu':evaluate_cpu_controls(cpu,policy,envelope or {'cpus':0}),'memory':evaluate_memory_controls(memory,policy),'units':UNITS,
            'resolution':policy['resolution'],'bands':c,
            'envelope':envelope,'cpu_rows':cpu,'memory_rows':memory,'evidence_paths':evidence}
    atomic_json(run_dir/'controls.json',result);return result

def _unit_job(root,run_dir,policy,project,modules):
    """One container command of the unit suite (the whole suite, or one declared unit group of a project, ruling A6-C3)."""
    session=None;run_dir.mkdir(parents=True,exist_ok=True)
    try:
        session=BenchSession(root,run_dir)
        plan={'schema_version':1,'job':'unit','run_id':run_dir.name,'project_dir':project,'deadline_seconds':policy['job_deadlines']['selftest'],
              **({'unit_modules':modules} if modules is not None else {})}
        r=session.job(plan,'bench-unit',policy['job_deadlines']['selftest'])
        row=last_json(r['output'])
        out={'status':row.get('status','FAIL') if passed(r) or row else 'BLOCKED','tests':row.get('tests',0),
             'failed':row.get('failed',[]),'scope':row.get('scope'),'evidence_paths':list(session.evidence_paths)}
    except GateError as exc:
        out={'status':'BLOCKED','reason':str(exc)}
        if session is not None and session.evidence_paths:out['evidence_paths']=list(session.evidence_paths)
    finally:
        if session is not None:session.close()
    return out

def selftest_status(statuses):
    """T10-APP-01 (ruling T10-C3): PASS only when every status is PASS; a FAIL (or any status that is not PASS or BLOCKED, or no
    status at all) is FAIL and wins over BLOCKED; BLOCKED only when no status FAILs and some status is BLOCKED."""
    statuses=list(statuses)
    if statuses and all(s=='PASS' for s in statuses):return 'PASS'
    return 'BLOCKED' if all(s in ('PASS','BLOCKED') for s in statuses) and 'BLOCKED' in statuses else 'FAIL'

def selftest(root,args):
    policy=bm.load_policy(root);project=project_arg(root,args);run_dir=new_run_dir(root,'selftest');result={'status':'BLOCKED','suites':{}}   # a project replaces the unit suite's tests; controls stay framework
    if args.suite in ('unit','all'):
        groups=bm.unit_groups(root,project) if project is not None else None      # ruling A6-C3: one container command per declared group
        if groups is None:result['suites']['unit']=_unit_job(root,run_dir,policy,project,None)
        else:
            import time
            rows=[]
            for k,g in enumerate(groups):
                t0=time.monotonic();r=_unit_job(root,run_dir/f'unit-group-{k}',policy,project,g);r['seconds']=round(time.monotonic()-t0,1);rows.append(r)
            st=[r['status'] for r in rows]
            result['suites']['unit']={'status':selftest_status(st),
                                      'tests':sum(r.get('tests',0) for r in rows),'failed':[f for r in rows for f in r.get('failed',[])],'scope':rows[0].get('scope'),
                                      'groups':[{k:r.get(k) for k in ('status','tests','failed','seconds','reason') if k in r} for r in rows],
                                      'evidence_paths':[e for r in rows for e in r.get('evidence_paths',[])]}
    if args.suite=='controls':                  # `all` runs the controls inside the B02/B03/B05 cases
        try:
            out=run_controls(root,run_dir);statuses=(out['cpu']['status'],out['memory']['status'])
            status=selftest_status(statuses)
            result['suites']['controls']={'status':status,'cpu':out['cpu']['status'],'memory':out['memory']['status'],'report':str(run_dir/'controls.json')}
        except GateError as exc:
            result['suites']['controls']={'status':'BLOCKED','reason':str(exc)}
    if args.suite in ('privacy','all'):         # Task 18 (spec 16): a redacted stderr probe keeps only a byte count
        result['suites']['privacy']=_privacy_suite(root,run_dir)
    if args.suite in ('cases','all'):
        try:
            suites,additions=selftest_cases(root,run_dir);result['suites'].update(suites)
            result['suites']['subcases']={'status':'PASS' if additions and all(a['status']=='PASS' for a in additions) else 'FAIL',
                                          'passed':sum(a['status']=='PASS' for a in additions),'total':len(additions),'report':str(run_dir/'cases.json')}
        except GateError as exc:
            result['suites']['cases']={'status':'BLOCKED','reason':str(exc)}
    if args.suite in ('project','all'):result['suites'].update(project_suites(root,run_dir))     # Task 19b (Amendment A)
    statuses=[s['status'] for s in result['suites'].values()]
    result['status']=selftest_status(statuses)
    atomic_json(run_dir/'selftest.json',result)
    emit(args,result,'bench selftest: '+result['status']+' '+json.dumps({k:v['status'] for k,v in result['suites'].items()}));return EXIT[result['status']]

HANDLERS={'doctor':doctor,'list':list_cases,'selftest':selftest}
ARGUMENTS={'selftest':[('--suite',{'choices':['unit','controls','privacy','cases','project','all'],'default':'all'})]}

def plan_cmd(root,args):
    """Task 15: bench plan writes artifacts/bench/<id>/plan.json; the plan never holds the owner-fixture path (F-11)."""
    import bench_plan as bp
    from container_policy import choose_envelope, host_topology
    project=project_arg(root,args);policy=bm.load_policy(root,project);case=bm.load_case(root,args.case,project);bm.case_rules(root,case,project_dir=project);dataset=bp.parse_dataset(root,args.dataset,policy)
    calibration,source=bp.calibration_record(root,args.calibrate,policy) if args.calibrate else (None,None)
    envelope=choose_envelope(*host_topology(),wanted=policy['envelope']['cpus']);seed=int(uuid.uuid4().int%2**31)   # recorded as plan['seed']
    identity=bm.project_identity(root,project,case) if project is not None and case['case_id'] in bm.project_bench(root,project)['cases'] else None
    plan=bp.build_plan(case,policy,mode=args.mode,dataset=dataset,seed=seed,envelope=envelope,calibration=calibration,project_dir=project,project_identity=identity,
                       calibration_source=source)
    import bench_guardrails            # B12 (Task 12): plan-time guardrails with the last recorded doctor row; no container runs here
    cp=read_json(Path(root)/'safety/container-policy.json');doctor_row,source=last_doctor_record(root)
    guard=dict(bench_guardrails.check(plan,policy,envelope,cp,doctor_row),doctor_row=source)   # T12-APP-04: the row's path and age
    if guard['rejected']:
        emit(args,{'status':'FAIL','rejected':guard['rejected'],'blocked':guard['blocked'],'doctor_row':source},'bench plan refused: '+'; '.join(guard['rejected']));return 1
    plan['blocked_rows']=plan['blocked_rows']+bench_guardrails.blocked_rows(plan,bench_guardrails.affected(plan,policy,envelope,cp,doctor_row))
    run_dir=new_run_dir(root,'plan');atomic_json(run_dir/'plan.json',plan)
    emit(args,{'status':'PASS','plan':str(run_dir/'plan.json'),'plan_version':plan['plan_version'],'estimate_seconds':plan['estimate_seconds'],'blocked_rows':plan['blocked_rows'],
               'guardrails':guard},
         f"plan {plan['plan_version']}: {plan['estimate_seconds']} s estimated -> {run_dir/'plan.json'}");return 0

def last_doctor_record(root):
    """B12: the newest readable recorded `bench doctor` result (artifacts/bench/<id>/doctor.json) and its source
    {'path' (relative to the root), 'age_seconds'} (T12-APP-04), or (None, None) (`doctor not run`)."""
    import time
    for p in sorted(Path(root).glob('artifacts/bench/*/doctor.json'),key=lambda p:p.stat().st_mtime,reverse=True):
        try:row=read_json(p);age=max(0,int(time.time()-p.stat().st_mtime))
        except (GateError,ValueError,OSError):continue
        if isinstance(row,dict):return row,{'path':p.relative_to(Path(root)).as_posix(),'age_seconds':age}
    return None,None

HANDLERS['plan']=plan_cmd
ARGUMENTS['plan']=[('--case',{'required':True}),('--dataset',{'default':'synthetic:small'}),('--mode',{'choices':['smoke','decision'],'default':'smoke'}),('--calibrate',{})]

CASE_RE=re.compile(r'^[a-z][a-z0-9-]{2,40}$')
REQUIRED_METHODS=('load','prepare','run','work_units','validate','synthesize','slice','slice_result','materialize','reference','digest')

def project_arg(root,args):
    """`--project DIR` (relative to the root). Default `.` only when the root holds project.json and benchmarks/project/bench.json.
    The path and the declaration are validated before any container exists."""
    value=getattr(args,'project',None)
    if value is None and (Path(root)/'project.json').is_file() and (Path(root)/bm.PROJECT_AREA/'bench.json').is_file():value='.'
    if value is not None:bm.project_bench(root,value)
    return value

DEFAULT_PROJECT_NAME='project'   # owner privacy rule: never copy a directory (possibly login) name into a tracked file
FILE_RE=re.compile(r'^[A-Za-z0-9._-]{1,80}$')

def check_files(row):
    """Review fix: the host re-applies the container's file-name rule before any fetch."""
    files=row.get('files') if isinstance(row,dict) else None
    return [f for f in files if isinstance(f,str) and FILE_RE.fullmatch(f) and f not in ('.','..')][:32] if isinstance(files,list) else []

def new_case(root,case_id,project_dir=None):
    """spec 11.1: Python-only scaffold; never generates C. In a project it registers the case in bench.json."""
    root=Path(root)
    if not isinstance(case_id,str) or not CASE_RE.fullmatch(case_id) or case_id.endswith('-'):raise GateError('case id must match ^[a-z][a-z0-9-]{2,40}$')
    if case_id in bm._framework_case_ids(root):raise GateError('case already exists')
    module=case_id.replace('-','_')
    if project_dir is None:
        base=root/'benchmarks/performance';record_rel=f'benchmarks/performance/cases/{case_id}.opportunity.json';stage_parent=base
    else:
        base=bm._project_base(root,project_dir);record_rel=f'{bm.PROJECT_AREA}/cases/{case_id}.opportunity.json';stage_parent=root/project_dir
        if (base/'bench.json').is_file():bm.project_bench(root,project_dir)          # an existing declaration must be valid first
        elif (base/'cases').is_dir() and any(p for p in (base/'cases').glob('*.json')):
            raise GateError('benchmarks/project/cases holds manifests but there is no bench.json; declare those cases in bench.json first')
    if module in bm.RESERVED_MODULES:raise GateError('case module name collides with stdlib, startup hooks, bench wheels or framework packages: '+module)
    cases=base/'cases';python=base/'python'
    paths={'manifest':cases/f'{case_id}.json','opportunity':cases/f'{case_id}.opportunity.json','init':python/module/'__init__.py','adapter':python/module/'adapter.py','test':python/'tests'/f'test_{module}.py'}
    if any(p.exists() or p.is_symlink() for p in list(paths.values())+[python/module]):raise GateError('case already exists')
    manifest={'schema_version':1,'case_id':case_id,'version':1,'kind':'function','adapter':f'{module}.adapter:Workload',
              'description':'scaffold: describe the operation','work_unit':'scaffold: define one unit of work','parameters':{'seed':{'value':20261007,'label':'declared'}},
              'variants':[{'id':'py-reference','language':'python','workers':['direct'],'status':'implemented'},
                          {'id':'py-optimized','language':'python','workers':['direct'],'status':'same-as-reference','reason':'no optimized implementation yet'}],
              'scopes':['kernel','caller'],'sizes':['tiny','small'],'points':[],'opportunity_record':record_rel}
    measured={'value':None,'reason':'not yet measured'};share={'share':None,'uncertainty':'not yet measured'}
    record={'schema_version':1,'case_id':case_id,'operation':'scaffold','sizes':{'records_per_call':None},'frequency':'unknown','target':{'kind':'none','value':None,'unit':None},
            'footprint':{k:dict(measured) for k in ('cpu_ns_per_unit','wall_ns_per_unit','ready_state_bytes','group_peak_bytes')},
            'breakdown':{k:dict(share) for k in ('computation','allocation','serialization','database','io_wait','lock_contention','queueing')},
            'python_options':[],'approval':{'state':'PENDING','reference':'scaffold'}}
    from schema_check import validate
    validate(root,'bench-case',manifest);validate(root,'bench-opportunity',record);bm.case_rules(root,manifest)   # no C row: the record is not read
    decl=None
    if project_dir is not None:
        path=base/'bench.json'
        def merge(d):d['cases']=sorted(set(d['cases'])|{case_id});validate(root,'bench-project',d)
        if path.is_file():decl=load_project_json(path,'bench-json',PROJECT_JSON_MAX_BYTES,label='benchmarks/project/bench.json',check=merge)   # FR3-17
        else:decl={'schema_version':1,'name':DEFAULT_PROJECT_NAME,'cases':[]};merge(decl)
        paths['declaration']=base/'bench.json'
    texts=_scaffold_texts()
    # Review fix: write every file into a staging directory first, then move each into place; any failure removes
    # what was moved and every directory this call created, so no half scaffold remains.
    if not stage_parent.is_dir():raise GateError('the project directory does not exist')
    stage=Path(tempfile.mkdtemp(prefix='.bench-new-',dir=stage_parent));moved=[];created=[]
    try:
        staged={k:stage/k for k in paths}
        atomic_json(staged['manifest'],manifest);atomic_json(staged['opportunity'],record)
        if decl is not None:atomic_json(staged['declaration'],decl)
        for k in ('init','adapter','test'):staged[k].write_text(texts[k])
        for k in [k for k in paths if k!='declaration']+(['declaration'] if decl is not None else []):   # bench.json last
            missing=[];d=paths[k].parent
            while not d.exists():missing.append(d);d=d.parent
            for d in reversed(missing):d.mkdir();created.append(d)
            if k!='declaration' and paths[k].exists():raise GateError('case already exists')
            os.replace(staged[k],paths[k]);moved.append(paths[k])
    except BaseException:
        for p in moved:
            if p.name!='bench.json':p.unlink(missing_ok=True)
        for d in reversed(created):
            try:d.rmdir()
            except OSError:pass
        raise
    finally:shutil.rmtree(stage,ignore_errors=True)
    paths.pop('declaration',None)
    return {k:str(v) for k,v in paths.items()}

def _scaffold_texts():
    return {'init':'"""Registered workload scaffold."""\n','adapter':('"""Adapter scaffold (Amendment A contract): implement the reference first; it must pass correctness tests before any timing."""\n'
        'class Workload:\n    def __init__(self, params):\n        self.params = params\n'
        + ''.join(f'    def {m}(self, *args, **kwargs):\n        raise NotImplementedError("{m}: write the reference implementation")\n' for m in REQUIRED_METHODS)),
        'test':('import unittest\n\nclass ScaffoldTests(unittest.TestCase):\n'
        '    def test_correctness_against_a_known_answer(self):\n        self.fail("write a correctness test from the case specification")\n'
        '    def test_boundaries(self):\n        self.fail("write zero, one, exact-bound and one-past boundary tests")\n')}

def new(root,args):
    project=getattr(args,'project',None)
    if project is None and (Path(root)/'project.json').is_file():project='.'      # inside a project, never write framework files
    paths=new_case(root,args.case,project);emit(args,{'status':'PASS','paths':paths},'\n'.join(paths.values()));return 0

def refuse_dropped_checks(root,args,policy,case,project,command):
    """T29-APP-01 (P15 removed-safety-check): `bench validate` and `bench run` FAIL (exit 1) before any container when the
    project declaration drops or switches off a before_run check that the protected policy requires for the case
    (bm.dropped_before_run_checks). Returns the exit code of the refusal, or None."""
    reasons=bm.dropped_before_run_checks(policy,case['case_id'],bm.project_bench(root,project))
    if not reasons:return None
    emit(args,{'status':'FAIL','case':case['case_id'],'reason':reasons[0],'reasons':reasons},f"bench {command} {case['case_id']}: FAIL ({reasons[0]})")
    return EXIT['FAIL']

def validate_case(root,args):
    project=project_arg(root,args);case=bm.load_case(root,args.case,project);bm.case_rules(root,case,project_dir=project);policy=bm.load_policy(root,project)
    refused=refuse_dropped_checks(root,args,policy,case,project,'validate')
    if refused is not None:return refused
    deadline=policy['job_deadlines']['doctor'];run_dir=new_run_dir(root,'validate');session=BenchSession(root,run_dir)
    try:
        r=session.job({'schema_version':1,'job':'validate','run_id':run_dir.name,'project_dir':project,'case_manifest':bm.container_case_path(args.case,project,root),
                       'deadline_seconds':deadline},'bench-validate',deadline)
        row=last_json(r['output']);evidence=list(session.evidence_paths)
    finally:session.close()
    import bench_plan as bp
    expected={v['id'] for v in case['variants'] if v['language'] in bp.PYTHON_LANGUAGES and v['status']=='implemented'}   # Task 9b: py-library included
    seen={x.get('variant') for x in row.get('variants') or [] if isinstance(x,dict)}
    status='PASS' if passed(r) and row.get('status')=='PASS' and expected and seen==expected else 'FAIL'
    result={'status':status,'case':args.case,'adapter':row.get('adapter'),'variants':row.get('variants'),'evidence_paths':evidence}
    atomic_json(run_dir/'validate.json',result)
    emit(args,result,f'bench validate {args.case}: {status}');return EXIT[status]

CHECK_MARGIN_SECONDS=30     # the coordinator's job_check runs the check with deadline_seconds - 30 (container/bench-coordinator.py)

def check_call_deadline(case,policy,selectors,deadline_key):
    """Task A2 (PB-02; Task 1 parked note): the call-deadline fields of a `bench check` job, or None. A check declares in
    bench.json the selectors that its calls evaluate; a selector that budgets.share_required lists without an approved
    share is left out. The covering deadline is sized as one large-dataset call (the landed job_inputs('check') rows and
    calls) and armed on the whole check process only when it is below the job's own timeout (the policy job deadline
    minus the coordinator's 30 s margin); otherwise the job limit governs and an expiry stays "check exceeded its
    deadline". `bench validate` is never armed: it evaluates the selector `all` only."""
    import bench_deadline
    selectors=[s for s in selectors if s not in bench_deadline.unapproved_shares(policy,selectors)]
    if case is None or not selectors:return None
    limit=float(policy['job_deadlines'][deadline_key]-CHECK_MARGIN_SECONDS)
    rows,calls=bench_deadline.job_inputs('check',{'sizes':policy['sizes']},{})
    c=bench_deadline.covering_deadline(case,policy,{'variant':'py-reference','selectors':selectors},rows,calls,None,limit)
    if c is None or c[0]>=limit:return None
    return {'call_deadline_seconds':c[0],'call_deadline_reason':c[1]}

def _check_case(root,project_dir,decl,selectors):
    """The project case whose call-deadline entries cover one of the declared selectors (first in bench.json order), or None."""
    import bench_deadline
    for cid in decl['cases']:
        case=bm.load_case(root,cid,project_dir)
        if any(bench_deadline.entry_for(case,s) for s in selectors):return case
    return None

SHARED_PREFIX='shared-'          # Task DD (ruling D1-R2(b)): an output file a passed check hands to the later checks of its session
SHARED_RE=re.compile(r'^bench/shared/[A-Za-z0-9._-]{1,80}/shared-[A-Za-z0-9._-]{1,73}$')
SHA256_RE=re.compile(r'[0-9a-f]{64}')

def shared_outputs(run_dir,name,status,row):
    """Task DD (ruling D1-R2(b)): the files that check `name` hands to the later checks of the same check session (one
    `before_run_checks` call or one project's checks in `project_suites`). Only a PASS check hands files on, and only its
    fetched output files named shared-*: each as (container path bench/shared/<check>/<file>, the fetched copy in the run's
    own evidence run_dir/<check>/<file>, the sha256 that run_check recorded from the fetched bytes in the row's
    file_sha256). Runner.restore hands the copy on only while its bytes have that digest (DD-01) and writes a transfer
    receipt; a file without a recorded digest is not handed on. The consumer check uses the content only on an exact
    match of its own binding and recomputes otherwise."""
    if status!='PASS':return []
    base=Path(run_dir)/name;digests=row.get('file_sha256') if isinstance(row.get('file_sha256'),dict) else {}
    return [(f'bench/shared/{name}/{f}',base/f,digests[f]) for f in check_files(row) if f.startswith(SHARED_PREFIX) and (base/f).is_file() and not (base/f).is_symlink()
            and type(digests.get(f)) is str and SHA256_RE.fullmatch(digests[f])]

def run_check(root,run_dir,project_dir,name,args=(),deadline_key='smoke',shared=(),native=None):
    """Run one check declared in the project's bench.json. The deadline is the host policy's (`deadline_key`); a project never
    names one. A check that declares covered selectors gets the call-deadline fields of check_call_deadline (Task A2).
    `shared` (Task DD): the shared_outputs of the earlier checks of the same session, restored into the check container
    before the check starts; a single `bench check` has none. Each entry carries the sha256 of its fetched bytes, and the
    restore refuses a copy whose bytes differ (DD-01). The container path names the copy's own check directory, which is
    a directory of this run_dir (DD-03). A passed check records the sha256 of every file it fetched in
    row['file_sha256'], taken from the bytes that collect fetched."""
    decl=bm.project_bench(root,project_dir)
    if decl is None or name not in [c['name'] for c in decl.get('checks',[])]:raise GateError('undeclared project check')
    args=[str(a) for a in args]
    if len(args)>8 or not all(re.fullmatch(r'[A-Za-z0-9._:/-]{1,128}',a) for a in args):raise GateError('check arguments rejected')
    if not all(isinstance(x,(tuple,list)) and len(x)==3 for x in shared):raise GateError('shared check files rejected')
    shared=[(str(rel),Path(src),sha) for rel,src,sha in shared]
    if len(shared)>32 or not all(SHARED_RE.fullmatch(rel) and '..' not in rel.split('/') and '..' not in src.parts and src.is_relative_to(Path(run_dir))
                                 and type(sha) is str and SHA256_RE.fullmatch(sha)
                                 and rel.split('/')[2]==src.parent.name and src.parent.parent==Path(run_dir)    # DD-03: the copy's own check directory of this run
                                 for rel,src,sha in shared):raise GateError('shared check files rejected')
    policy=bm.load_policy(root,project_dir);deadline=policy['job_deadlines'][deadline_key]
    selectors=next(c for c in decl['checks'] if c['name']==name).get('selectors',[])
    armed=(check_call_deadline(_check_case(root,project_dir,decl,selectors),policy,selectors,deadline_key) if selectors else None) or {}
    s=BenchSession(root,run_dir)
    try:
        # Task 17 (FR6 N2): with a native build, the plan carries the binary digests and the job restores the binaries
        r=s.job({'schema_version':1,'job':'check','run_id':run_dir.name,'project_dir':project_dir,'check':name,'check_args':args,'deadline_seconds':deadline,**armed,
                 **({'native':bench_native.native_plan(native)} if native else {})},'check-'+name,deadline,
                restore=tuple(shared)+tuple(bench_native.native_restore(native) if native else ()))
        row=last_json(r['output']);row['files']=check_files(row)
        if passed(r):
            for f in row['files']:s.fetch('bench/out/'+f,run_dir/name/f)
            row['file_sha256']={f:s.fetched_sha256(run_dir/name/f) for f in row['files']}
    finally:s.close()
    return ('PASS' if passed(r) and row.get('status')=='PASS' else 'FAIL'),r['evidence_path'],row

def check_outcome(name,status,row):
    """Amendment G2.6: a check job killed at its call deadline is FAIL with the declared reason (`FAIL <reason>`, exit 1),
    never BLOCKED. Returns (status, text, reason or None)."""
    import bench_deadline
    reason=bench_deadline.job_reason(row)
    if reason is not None:return 'FAIL',f'bench check {name}: FAIL {reason}',reason
    return status,f'bench check {name}: {status}',None

# T28-APP-04: the fixed reasons of the coordinator's check job (container/bench-coordinator.py job_check, control_check and
# check_result); only these reach the `bench check` text line, never free text.
CHECK_REASONS=('check row has more count keys than the bound','bench.json is missing or malformed','undeclared check',
               'check module shadows a container module','check arguments rejected','check exceeded its deadline',
               'a check needs a project','case manifest path rejected','selector rejected','call deadline',
               'restored native binary digest mismatch',                  # Task 17 (FR6 N2): container native_env
               'shared-memory segment left after the job')                # Task 19 (FR6 N4): container job_end_check

def check_cmd(root,args):
    project=project_arg(root,args)
    if project is None:raise GateError('bench check needs --project')
    # FR3: --long selects the framework job deadline long_check (a long project check, for example a data generation that
    # the example project's oracle driver ran); each --arg reaches the check (run_check bounds count and characters)
    key='long_check' if getattr(args,'long',False) else 'smoke'
    run_dir=new_run_dir(root,'check')
    native=bench_native.build_native(root,run_dir,project) if getattr(args,'native',False) else None    # Task 17 (FR6 N2): --native
    status,evidence,row=run_check(root,run_dir,project,args.check,list(getattr(args,'arg',None) or []),deadline_key=key,
                                  **({'native':native} if native is not None else {}))
    status,text,reason=check_outcome(args.check,status,row)
    if status=='FAIL' and reason is None and isinstance(row.get('reason'),str) and row['reason'] in CHECK_REASONS:text+=f" ({row['reason']})"   # T28-APP-04
    incomplete=(row.get('counts') if isinstance(row.get('counts'),dict) else {}).get('incomplete_items')
    if type(incomplete) is int:text+=f' incomplete={incomplete}'          # R1B-02: the oracle check's INCOMPLETE item count
    result={'status':status,'check':args.check,'evidence':evidence,'files':row.get('files',[]),**({'failure_reason':reason} if reason else {})};atomic_json(run_dir/'check.json',result)
    emit(args,result,text);return EXIT[status]

HANDLERS.update(new=new,validate=validate_case,check=check_cmd)
PROJECT=('--project',{})
ARGUMENTS.update(new=[('--case',{'required':True}),PROJECT],validate=[('--case',{'required':True}),PROJECT],check=[('--check',{'required':True}),PROJECT,('--long',{'action':'store_true'}),('--arg',{'action':'append','default':[]})])
ARGUMENTS['plan']=[('--case',{'required':True})]+[a for a in ARGUMENTS['plan'] if a[0]!='--case']+[PROJECT]
ARGUMENTS['selftest']=ARGUMENTS['selftest']+[PROJECT];ARGUMENTS['list']=ARGUMENTS.get('list',[])+[PROJECT]
# Task 17 (FR6 N2): the operation native-build and the --native flag of check. After the check arguments above, which the
# source anchor (the HANDLERS.update line) precedes; at that line ARGUMENTS['check'] does not exist yet.
import bench_native;bench_native.register_cli(HANDLERS,ARGUMENTS)

# ---- Task 16a: bench run, compare and report (workload-generic; qualified on the framework controls) ----
POOLED=('py-threads','py-processes')

def read_jsonl(path):
    p=Path(path);return evidence_read_jsonl(p,'container-jsonl') if p.is_file() else []    # FR3-19: fetched rows, capped

def check_completeness(plan,observations,policy):
    """P07: every planned non-warmup row is observed with its full work and no dropped result rows."""
    problems=[];by={}
    for o in observations:by.setdefault(o['trial_id'],[]).append(o)
    for t in [t for s in plan['sessions'] for t in s['trials'] if not t['warmup']]+plan['memory']:
        got=by.get(t['trial_id'])
        if not got:problems.append(f"{t['trial_id']}: planned row missing");continue
        n=policy['sizes'][t['tier']]
        for o in got:
            if not o['work_units']:problems.append(f"{t['trial_id']}: zero work units")
            elif o['work_units']!=n:problems.append(f"{t['trial_id']}: {o['work_units']} of {n} units completed")
            if (o.get('verdict') or {}).get('reduction') in ('ROW_COUNT','MISSING_ROWS'):problems.append(f"{t['trial_id']}: result rows dropped")
    return problems

def check_caller_semantics(plan,observations,phases):
    """B10/B13: a cold pool starts inside the caller interval; a warm pool starts once, observed separately."""
    problems=[];starts={(p['variant'],p['workers']) for p in phases if p['phase']=='pool_start'}
    for o in observations:
        if o['scope']!='caller' or o['variant'] not in POOLED:continue
        inside=(o.get('phases') or {}).get('pool_start')
        if o['mode']=='cold' and inside is None:problems.append(f"{o['trial_id']}: cold pool row without pool start inside the interval")
        if o['mode']=='warm' and inside is not None:problems.append(f"{o['trial_id']}: warm pool row started a pool inside the interval")
        if o['mode']=='warm' and (o['variant'],o['workers']) not in starts:problems.append(f"{o['trial_id']}: warm pool start not observed separately")
    return problems

HOST_TUNING_KEYS=('host_tuning','drop_caches','cpu_governor','disable_aslr','isolcpus','turbo','nice','perf_event_paranoid','irq_affinity')

def reject_host_tuning(plan):
    """B13: the laboratory never tunes the host (no cache flush, governor, ASLR, isolation or priority changes)."""
    asked=[k for k in HOST_TUNING_KEYS if k in plan]
    if asked:raise GateError('host tuning requests are not authorized: '+', '.join(asked))

def check_perturbation(run,plan,observations,phases):
    """B13: timing runs apart from profiling and memory diagnostics; empty-overhead control visible; launch time never inside a variant."""
    problems=[]
    if run.get('mode')=='profile':problems.append('a profiled run is not a timing run')
    if any(t['scope']=='kernel' and not t['variant'].startswith('c-') for s in plan['sessions'] for t in s['trials']) and not any(p['phase']=='control-zero' for p in phases):problems.append('empty-overhead control missing')   # Task 19: a C kernel row has no pyperf control
    problems+=[f"{o['trial_id']}: launch or pool start recorded as a timed variant row" for o in observations if o.get('phase') in ('import','pool_start','teardown')]
    problems+=[f"{o['trial_id']}: memory diagnostics inside a timing row" for o in observations if o.get('scope') in ('caller','kernel') and o.get('memory') is not None]
    return problems

def blocked_start_reasons(row):
    """N4-A10: one run reason per BLOCKED row of a timing job (`blocked_rows`, a warm C row whose child exited during its
    start). Every value is bounded; a malformed entry is still a reason. [] without blocked rows."""
    rows=row.get('blocked_rows') if isinstance(row,dict) else None
    if rows is None:return []
    if not isinstance(rows,list):return ['planned row BLOCKED: malformed blocked_rows']
    out=[]
    for b in rows[:32]:
        if not isinstance(b,dict):out.append('planned row BLOCKED: malformed entry');continue
        text=lambda k:re.sub(r'[^A-Za-z0-9 ._:,()-]','?',str(b.get(k)))[:120]
        out.append(f"planned row BLOCKED: {text('variant')} route {text('route')} {text('mode')}: {text('reason')}"[:300])
    return out

PY_POOL_KEYS=('max_pending','window','pids_distinct','caller_pid_included','start_method')

def check_concurrency_identity(observations,plan,policy):
    """B10: a thread row ran in the caller process; a process row ran only in spawned workers, at most `workers` of them, with the
    resource tracker started at session setup; the submission window held. Amendment E item 6: every pooled row records the
    one-per-worker chunk rule and exactly the chunk sizes of that rule for its row count (bench_plan.b10_row_count) and workers."""
    import bench_plan as bp
    problems=[];limit=policy['pools']['request_limit']
    for o in observations:
        if o.get('scope')=='caller' and o.get('variant')=='c-threads' and not o.get('warmup') and o.get('eligible') is True:   # Task 19: per route
            problems+=_c_threads_identity(plan,o,policy,limit);continue
        if o.get('scope') not in ('caller','kernel') or o.get('variant') not in POOLED or o.get('warmup') or o.get('eligible') is not True:continue
        p=o.get('pool')
        if not p:problems.append(f"{o['trial_id']}: pool identity not recorded");continue
        if not isinstance(p,dict) or any(k not in p for k in PY_POOL_KEYS):     # N4-A03: never a KeyError (a native shape here)
            problems.append(f"{o['trial_id']}: pool identity not recorded in the Python pool shape");continue
        if p['max_pending']>p['window'] or p['window']!=2*o['workers']:problems.append(f"{o['trial_id']}: submission window not bounded by 2 x workers")
        rows=None          # Task 19b: a chunk-rule or row-count problem no longer skips the identity checks below; every reason is reported
        if p.get('chunk_rule')!=bp.CHUNK_RULE:problems.append(f"{o['trial_id']}: chunk rule is not one-per-worker")
        else:
            try:rows=bp.b10_row_count(plan,o,policy)
            except GateError as exc:problems.append(f"{o['trial_id']}: no B10 row count ({str(exc)[:80]})")
        if rows is None:pass
        elif p.get('chunk_sizes')!=bp.expected_chunk_sizes(rows,o['workers'],limit) or p.get('chunks')!=len(p['chunk_sizes']):
            problems.append(f"{o['trial_id']}: chunk sizes differ from the one-per-worker rule")
        elif not isinstance(p.get('chunk_wall_ns'),list) or len(p['chunk_wall_ns'])!=p['chunks']:
            problems.append(f"{o['trial_id']}: chunk time count differs from the chunk count")
        if o['variant']=='py-threads' and not (p['caller_pid_included'] and p['pids_distinct']==1 and p['start_method']=='thread'):problems.append(f"{o['trial_id']}: thread row left the caller process")
        if o['variant']=='py-processes' and (p['caller_pid_included'] or not 1<=p['pids_distinct']<=o['workers'] or p['start_method']!='spawn'):problems.append(f"{o['trial_id']}: process row identity wrong")
        if o['variant']=='py-processes' and p.get('tracker_session_setup') is not True:problems.append(f"{o['trial_id']}: resource tracker not started at session setup")
    return problems

def _c_threads_identity(plan,o,policy,limit):
    """B10 for a c-threads caller row (Task 19): the native pool evidence records the one-per-worker chunk rule and exactly
    the Amendment E chunk sizes for its row count and workers, on every route."""
    import bench_plan as bp
    p=o.get('pool');tid=f"{o['trial_id']} [{o.get('route')}]"
    if not isinstance(p,dict):return [f'{tid}: native pool evidence not recorded']
    if p.get('chunk_rule')!=bp.CHUNK_RULE:return [f'{tid}: chunk rule is not one-per-worker']
    try:rows=bp.b10_row_count(plan,o,policy)
    except GateError as exc:return [f'{tid}: no B10 row count ({str(exc)[:80]})']
    if p.get('chunk_sizes')!=bp.expected_chunk_sizes(rows,o['workers'],limit) or p.get('chunks')!=len(p.get('chunk_sizes') or []):return [f'{tid}: chunk sizes differ from the one-per-worker rule']
    if not isinstance(p.get('chunk_wall_ns'),list) or len(p['chunk_wall_ns'])!=p['chunks']:return [f'{tid}: chunk time count differs from the chunk count']
    return []

def check_control_identity(case_id,rows):
    """B10 on the framework controls (compare rows, warm caller scope): the GIL-held spin scales with processes, not threads;
    the GIL-releasing wait overlaps in threads. Relational checks only; no absolute timing threshold."""
    def med(v,w,f):return next((r[f]['median'] for r in rows if r['scope']=='caller' and r['mode']=='warm' and r['variant']==v and r['workers']==w and r[f]['median'] is not None),None)
    problems=[]
    if case_id=='bench-control-spin':
        t,p=med('py-threads',2,'busy_cpus'),med('py-processes',2,'busy_cpus')
        if t is None or p is None or not p>t:problems.append('spin: py-processes x2 busy CPUs not above py-threads x2 (GIL identity)')
    if case_id=='bench-control-wait':
        one,two=med('py-threads',1,'wall_ns_per_unit'),med('py-threads',2,'wall_ns_per_unit')
        if one is None or two is None or not two<one:problems.append('wait: py-threads x2 wall per unit not below x1 (the released GIL overlaps)')
    return problems

def before_run_checks(root,run_dir,project_dir):
    """Amendment A: every `before_run` check of the project passes before a timing run of its cases. Task DD: the checks
    are one session; each check gets the shared_outputs of the earlier passed checks."""
    decl=bm.project_bench(root,project_dir);reasons=[];evidence=[];shared=[]
    for c in (decl or {}).get('checks',[]):
        if not c['before_run']:continue
        status,ev,row=run_check(root,run_dir,project_dir,c['name'],shared=tuple(shared));evidence.append(ev)
        shared+=shared_outputs(run_dir,c['name'],status,row)
        if status!='PASS':reasons.append(f"pre-run check {c['name']}: {status}")
    return reasons,evidence

def check_native_timing(observations,policy,kernel_sha256):
    """Phase 2 Task 19 (FR6 N4): every non-warmup C kernel row has its self-timing within max(abs_ns, rel x bracket wall)
    of its bracket wall, a self CPU of at most the cgroup CPU plus abs_ns, and the native_sha256 of the run build."""
    nt=policy['native_timing'];problems=[]
    for o in observations:
        if o.get('scope')!='kernel' or not str(o.get('variant','')).startswith('c-') or o.get('warmup'):continue
        tid=o.get('trial_id','?');st=o.get('self_timing');wall=o.get('wall_ns');cpu=o.get('cpu_usage_usec')
        if not isinstance(st,dict) or type(st.get('mono_ns')) is not int or type(st.get('cpu_ns')) is not int or type(wall) is not int:
            problems.append(f'{tid}: C kernel row without its self-timing or bracket wall');continue
        if abs(st['mono_ns']-wall)>max(nt['abs_ns'],nt['rel']*wall):problems.append(f'{tid}: C kernel self-timing differs from the bracket wall')
        if type(cpu) is not int or st['cpu_ns']>cpu*1000+nt['abs_ns']:problems.append(f'{tid}: C kernel self CPU above the cgroup CPU')
        if o.get('native_sha256')!=kernel_sha256:problems.append(f'{tid}: C kernel binary differs from the run build')
    return problems

def route_summary(rows,policy):
    """Phase 2 Task 19 (C3): one line per route present in the rows, with its policy label and its row count."""
    count={}
    for r in rows:
        if r.get('route'):count[r['route']]=count.get(r['route'],0)+1
    return [f"route {route}: {policy['routes'].get(route,'unknown route')} (compare rows: {n})" for route,n in sorted(count.items())]

def dataset_identity_reasons(case,policy,plan):
    """G6.6 (Task 19 start check): the named dataset of each planned trial's dataset_ref is in plan.datasets with exactly
    the identity that the case's dataset_ref points give (bench_plan.plan_datasets: kind, size, seed, rows, indices). A
    difference is a run-invalid reason; bench run stops before any container. A named dataset that no trial uses is only
    recorded (T16-APP-03)."""
    import bench_plan as bp
    want=bp.plan_datasets(bp._points(case,plan.get('mode')),policy);got=plan.get('datasets') or {}
    refs=sorted({t['dataset_ref'] for s in plan.get('sessions',[]) for t in s['trials'] if isinstance(t.get('dataset_ref'),str)})
    keys=('kind','size','seed','rows','indices')
    bad=[n for n in refs if n not in want or n not in got or any(want[n].get(k)!=got[n].get(k) for k in keys)]
    return [f'run-invalid: dataset identity differs from its case derivation: {n}'[:300] for n in bad]

def check_metrics(observations):
    """Owner focus: a mandatory metric that is missing FAILS the run. Each non-warmup timed row needs its wall time, its
    cgroup CPU delta and an empty `unavailable` map."""
    problems=[]
    for o in observations:
        if o.get('warmup') or o.get('scope') not in ('caller','kernel'):continue
        missing=[k for k in ('wall_ns','cpu_usage_usec') if o.get(k) is None]+sorted((o.get('unavailable') or {}).keys())
        if missing:problems.append(f"{o['trial_id']}: mandatory metric missing or unreadable ({', '.join(missing)[:120]})")
    return problems

def run_status(plan,observations,phases,policy):
    """One rule set for real runs and the P11 checks (Task 19a)."""
    import bench_plan as bp
    reasons=bp.check_trial_design(plan,[o for o in observations if o['scope'] in ('caller','kernel')])+check_completeness(plan,observations,policy)
    reasons+=check_caller_semantics(plan,observations,phases)+check_perturbation({'mode':plan['mode']},plan,observations,phases)+check_concurrency_identity(observations,plan,policy)
    reasons+=check_metrics(observations)
    bad=[o['trial_id'] for o in observations if not o['warmup'] and o['eligible'] is not True]
    if bad:reasons.append(f'{len(bad)} required rows ineligible (oracle, agreement or failure)')
    reasons+=deadline_reasons(observations)
    return ('VALID' if not reasons else 'INVALID_EXPERIMENT'),reasons

def extend_unique(reasons,new):
    """Append each new reason once (a trial and a job killed with the same reason give one run-invalid line)."""
    for r in new:
        if r not in reasons:reasons.append(r)
    return reasons

def deadline_reasons(observations):
    """Amendment G2.6: a trial killed at its call deadline makes the whole run INVALID_EXPERIMENT (`run-invalid: <reason>`).
    A warmup trial counts too: a hang is a defect of the definition, not a slow row."""
    return sorted({f"run-invalid: {o['failure_reason']}" for o in observations if o.get('failure_reason')})

def _memory_eligibility(observations):
    """Memory trials take eligibility from the timing session: the same variant was eligible and, where a timing row of the
    same tier exists, the result digest matches. Amendment G4.2: rows of another selector never decide (absent selector: all)."""
    timed=[o for o in observations if o['scope'] in ('caller','kernel') and not o['warmup']];sel=lambda o:o.get('selector','all')
    ok_rows={(o['variant'],o['workers'],sel(o)) for o in timed if o['eligible']};bad_rows={(o['variant'],o['workers'],sel(o)) for o in timed if not o['eligible']}
    digests={(o['variant'],o['workers'],o['tier'],sel(o)):o['result_sha256'] for o in timed if o['scope']=='caller' and o['eligible']}
    for o in observations:
        if o['scope']=='memory' and o.get('failure_reason'):o['eligible']=False;continue      # T16-APP-05: a killed memory trial stays ineligible
        if o['scope']=='memory':
            k=(o['variant'],o['workers'],o['tier'],sel(o));row=(o['variant'],o['workers'],sel(o))
            o['eligible']=row in ok_rows and row not in bad_rows and digests.get(k,o['result_sha256'])==o['result_sha256']

def plan_digest(plan):
    """plan_id of a plan body (bench_plan.build_plan): sha256 over every key except plan_id and the project locator."""
    import hashlib
    body={k:v for k,v in without_guardrail_rows(plan).items() if k not in ('plan_id','project_dir')}
    return hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()[:32]

def without_guardrail_rows(plan):
    """B12 (Task 12): the plan without the blocked rows that bench_guardrails added (`guardrail: true`). They record host
    state at plan or run time, not the plan identity; bench run re-evaluates the guardrails and replaces them."""
    rows=plan.get('blocked_rows')
    if not isinstance(rows,list):return plan
    return dict(plan,blocked_rows=[r for r in rows if not (isinstance(r,dict) and r.get('guardrail') is True)])

def plan_request_limit_reason(plan,policy):
    """G-ALO-CO (Amendment I item I13.1): plan.request_limit (part of the plan identity) must equal the policy
    pools.request_limit. Returns None or the run-invalid reason; a run (and a later decision) with a mismatch is
    INVALID_EXPERIMENT. A plan that is not an object is left to verify_written_plan."""
    if not isinstance(plan,dict):return None
    value=plan.get('request_limit');want=policy['pools']['request_limit']
    if isinstance(value,bool) or not isinstance(value,int) or value!=want:
        return f'run-invalid: plan request_limit {value!r} differs from the policy pools.request_limit {want}'
    return None

def verify_written_plan(case,policy,plan,envelope,project,identity,root=None):
    """`bench run --plan`: the written plan must be exactly the plan that case, policy, mode, dataset, seed, calibration and
    this host's envelope produce. An edited plan (fewer blocks, other variants, other pyperf values, another seed) is refused.
    Task 19a: a calibration is never taken from the plan. It is re-derived from the recorded calibration run that the plan
    names, whose observation bytes must still have the recorded sha256; an edited calibration fails even with a recomputed id."""
    import bench_plan as bp
    if not isinstance(plan,dict):raise GateError('the written plan is not an object')
    if plan.get('plan_id')!=plan_digest(plan):raise GateError('the written plan was edited: plan_id differs from its content')
    if plan.get('envelope')!=envelope:raise GateError('the written plan was made for another CPU envelope')
    import bench_deadline                         # P3P-07 (Task 6): the selftest mode and its keys never come from a written plan
    if plan.get('mode')=='selftest':raise GateError('a written plan never has the selftest mode')
    bench_deadline.check_test_floor(plan)
    calibration=source=None
    if plan.get('calibration') is not None or 'calibration_source' in plan:
        source=plan.get('calibration_source')
        if root is None or not isinstance(source,dict) or set(source)!={'run_id','observations_sha256'}:
            raise GateError('the written plan calibration is not bound to a recorded calibration run')
        calibration,fresh=bp.calibration_record(root,source['run_id'],policy)
        if fresh!=source:raise GateError('the calibration run changed after the plan was written')
        if plan.get('calibration')!=calibration:raise GateError('the written plan calibration differs from its recorded calibration run')
    try:rebuilt=bp.build_plan(case,policy,mode=plan['mode'],dataset=plan['dataset'],seed=plan['seed'],envelope=envelope,calibration=calibration,
                              project_dir=project,project_identity=identity,calibration_source=source)
    except (KeyError,TypeError,ValueError):raise GateError('the written plan is malformed') from None
    strip=lambda p:{k:v for k,v in without_guardrail_rows(p).items() if k!='project_dir'}
    if strip(rebuilt)!=strip(plan):raise GateError('the written plan differs from the plan its case, policy, mode, dataset and seed produce')

def session_files(row):
    """The host re-applies the file-name rule to a timing job's file list: a plain name, or pyperf/<name>."""
    files=row.get('files') if isinstance(row,dict) else None;out=[]
    for f in (files if isinstance(files,list) else [])[:512]:
        if not isinstance(f,str):continue
        head,_,tail=f.rpartition('/')
        if head in ('','pyperf') and FILE_RE.fullmatch(tail) and tail not in ('.','..'):out.append(f)
    return out

EVALS_KEY=re.compile(r'^[a-z0-9-]{1,16}$')

def reference_evals_of(row):
    """Amendment G3.7: (counts, reason) of a reference job row. `reference_evals` is opaque {key: integer >= 0}, 1 to 8
    keys; absent gives (None, None); a malformed value is never copied and gives a run reason."""
    value=row.get('reference_evals') if isinstance(row,dict) else None
    if value is None:return None,None
    if isinstance(value,dict) and 0<len(value)<=8 and all(isinstance(k,str) and EVALS_KEY.fullmatch(k) and type(v) is int and v>=0 for k,v in value.items()):
        return dict(value),None
    return None,'reference job evaluation counts are malformed'

ADMIT_KEYS=('row','brent','bump')

def copy_reference_counts(row,run):
    """Amendment G3.7 and G2.3 (P3R2-04): copy the reference job's `reference_evals` (validated by reference_evals_of) and
    `reference_admit_excluded` (a closed object with exactly row, brent and bump, integers >= 0) into `run`. An absent key
    stays absent; a malformed value is never copied. Returns the run reasons of the malformed values."""
    reasons=[];value,why=reference_evals_of(row)
    if why:reasons.append(why)
    if value is not None:run['reference_evals']=value
    x=row.get('reference_admit_excluded') if isinstance(row,dict) else None
    if x is not None:
        if isinstance(x,dict) and sorted(x)==sorted(ADMIT_KEYS) and all(type(v) is int and v>=0 for v in x.values()):run['reference_admit_excluded']=dict(x)
        else:reasons.append('reference job exclusion counts are malformed')
    o=row.get('reference_overhead') if isinstance(row,dict) else None
    if o is not None:                 # G2.3 (P3R2-04, Task 6): the py-library S* side-test overhead, a closed object of one number >= 0
        v=o.get(OVERHEAD_KEY) if isinstance(o,dict) and list(o)==[OVERHEAD_KEY] else None
        if isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) and v>=0:run['reference_overhead']={OVERHEAD_KEY:v}
        else:reasons.append('reference job overhead is malformed')
    return reasons

OVERHEAD_KEY='library_overhead_ns_per_row'

def guardrail_gate(root,run_dir,plan,policy,envelope,probe):
    """B12 (Task 12; T12-C4 also for a local run): bench_guardrails.check after the doctor probe, before any trial or check
    container. Replaces the plan's guardrail rows, writes run_dir/plan.json and run_dir/guardrails.json, and returns
    (reasons, state): GATED when rejected (INVALID_EXPERIMENT; also after a BLOCKED probe, a real failure is never
    BLOCKED), BLOCKED when a PASS probe meets a blocked reason and a multicore trial is planned, else the probe status."""
    import bench_guardrails
    cp=read_json(Path(root)/'safety/container-policy.json')
    guard=bench_guardrails.check(plan,policy,envelope,cp,probe);hits=bench_guardrails.affected(plan,policy,envelope,cp,probe)
    plan['blocked_rows']=list(without_guardrail_rows(plan).get('blocked_rows') or [])+bench_guardrails.blocked_rows(plan,hits)
    atomic_json(run_dir/'plan.json',plan);atomic_json(run_dir/'guardrails.json',guard)
    if guard['rejected']:return ['rejected: '+r for r in guard['rejected']],'GATED'
    if probe['status']=='PASS' and bench_guardrails.blocks_run(hits):      # T12-APP-02: also a reason that affects single-worker rows
        return ['blocked: '+r for r,hit,wide in hits if wide or hit],'BLOCKED'
    return [],probe['status']

def native_run_declaration(root,project,plan):
    """Task 19: None for a plan without a C trial; else the project's bench.json `native` declaration (kernel program and
    argument template, agreement check). A planned C row without a project or without the declaration is BLOCKED."""
    trials=[t for s in plan.get('sessions',[]) for t in s['trials']]+list(plan.get('memory',[]))
    if not any(str(t.get('variant','')).startswith('c-') for t in trials):return None
    decl=bm.project_bench(root,project) if project is not None else None
    if not decl or 'native' not in decl:raise GateError('a planned C row needs a project with a bench.json native declaration')
    return decl['native']

def run_native_build(root,run_dir,project,decl):
    """Task 19: one native build per run (bench_native.build_native), then the declared agreement check with the restored
    binaries before any timing. Returns (native, record, reasons, evidence paths); any problem is a reason (the run is gated)."""
    reasons=[];evidence=[]
    try:native=bench_native.build_native(root,run_dir,project)      # run_dir/native.json and run_dir/native/<name>
    except GateError as exc:return None,None,[f'native build: {str(exc)[:200]}'],evidence
    evidence+=list(native.get('evidence_paths') or [])
    program=decl['kernel']['program']
    if program not in native['binaries']:return None,None,[f'native build: the kernel program {program} is not a native target'],evidence
    status,ev,row=run_check(root,run_dir,project,decl['agreement'],native=native);evidence.append(ev)
    if status!='PASS':reasons.append(f"native agreement check {decl['agreement']}: {status}")
    record={'binaries':{n:b['sha256'] for n,b in native['binaries'].items()},'glib_sha256':native['glib']['sha256'],'compiler':native.get('compiler'),
            'project_identity':native.get('project_identity'),'kernel':{'program':program,'sha256':native['binaries'][program]['sha256']},
            'agreement':{'check':decl['agreement'],'status':status,'files':list(row.get('files') or [])[:32]}}
    return native,record,reasons,evidence

def undeclared_counts(root,project,observations):
    """FR5 (ruling FR5-R1 item 2): the sorted verdict count names of the observations that the project protocol does not
    declare (`verdict_counts`; none without a project or a protocol). A run with such a name is INVALID_EXPERIMENT."""
    declared=set(bm.protocol_value(root,project,'verdict_counts',[]) or []) if project is not None else set()
    names={k for o in observations if isinstance(o,dict) and isinstance(o.get('verdict'),dict) and isinstance(o['verdict'].get('verdict_counts'),dict)
           for k in o['verdict']['verdict_counts']}
    return sorted(str(k) for k in names-declared)

def run_cmd(root,args):
    import bench_plan as bp
    import bench_accounting
    from schema_check import validate
    from policy import source_identity
    root=Path(root);project=project_arg(root,args);policy=bm.load_policy(root,project);case=bm.load_case(root,args.case,project);bm.case_rules(root,case,project_dir=project)
    protocol_sha256=bm.protocol_digest(root,project)      # FR3: bound at the start; decide refuses a later change (bench_evidence.protocol_problems)
    refused=refuse_dropped_checks(root,args,policy,case,project,'run')     # T29-APP-01: also for a written plan and a local run
    if refused is not None:return refused
    identity=bm.project_identity(root,project,case) if project is not None and case['case_id'] in bm.project_bench(root,project)['cases'] else None
    from container_policy import choose_envelope, host_topology
    envelope=choose_envelope(*host_topology(),wanted=policy['envelope']['cpus'])
    if args.plan:                                 # G-ALO-CO: the limit is compared first, so a mismatch is run-invalid, not BLOCKED
        plan=read_json(Path(args.plan))
        if plan_request_limit_reason(plan,policy) is None:verify_written_plan(case,policy,plan,envelope,project,identity,root=root)
    elif getattr(args,'selftest_plan',None) is not None:     # G2.6 call-deadline suite only; never from the command line
        import bench_deadline
        plan=bench_deadline.check_selftest_plan(args.selftest_plan,case,policy,envelope,plan_digest(args.selftest_plan),project=project,identity=identity,root=root)
    else:
        calibration,source=bp.calibration_record(root,args.calibrate,policy) if args.calibrate else (None,None)
        plan=bp.build_plan(case,policy,mode=args.mode,dataset=bp.parse_dataset(root,args.dataset,policy),seed=int(uuid.uuid4().int%2**31),
                           envelope=envelope,calibration=calibration,project_dir=project,project_identity=identity,calibration_source=source)
    limit_reason=plan_request_limit_reason(plan,policy)
    if limit_reason is not None:                  # G-ALO-CO (Amendment I item I13.1): before any container
        emit(args,{'status':'INVALID_EXPERIMENT','reason':limit_reason,'observations':0,'reasons':1},f'bench run: INVALID_EXPERIMENT ({limit_reason})');return 1
    identity_reasons=dataset_identity_reasons(case,policy,plan)       # G6.6 (Task 19): each named dataset identity at the start
    if identity_reasons:
        emit(args,{'status':'INVALID_EXPERIMENT','reason':identity_reasons[0],'observations':0,'reasons':len(identity_reasons)},f'bench run: INVALID_EXPERIMENT ({identity_reasons[0]})');return 1
    kernel_decl=native_run_declaration(root,project,plan)         # Task 19: a planned C row needs the project native declaration (BLOCKED otherwise)
    reject_host_tuning(plan);plan['project_dir']=project
    bm.require_locked_selectors(policy,sorted({t.get('selector','all') for x in plan.get('sessions',[]) for t in x.get('trials',[])}))   # A6P-05, also for a written plan
    selftest=plan['mode']=='selftest'      # Task 6 / A5: a stub plan (bench_deadline.stub_plan), checked above; never decision evidence
    plan['pyperf']=plan.get('pyperf') or ({'values':1,'warmups':0} if plan['mode'] in ('smoke','selftest') else {'values':3,'warmups':1})
    if plan['dataset']['kind']=='local':
        if 'path' not in plan['dataset']:           # a written plan lost its path (F-11); --dataset local:PATH must give the same digest
            fresh=bp.parse_dataset(root,args.dataset,policy)
            if fresh['kind']!='local' or fresh['sha256']!=plan['dataset']['sha256']:raise GateError('local dataset differs from the planned digest')
            plan['dataset']['path']=fresh['path']
        from bench_privacy import run_local
        return run_local(root,args,plan,case,policy,envelope=envelope)
    run_dir=new_run_dir(root,'run');atomic_json(run_dir/'plan.json',plan);held=[]
    args.created_run_id=run_dir.name             # Task 20 (T20-C2): bench replay uses the run id that this run created
    probe=doctor_probe(root,run_dir);held.append(probe.pop('lock_held_ns',0) or 0);reasons=[] if probe['status']=='PASS' else ['bench doctor: '+probe['status']]
    import bench_guardrails            # B12 (Task 12): after the doctor probe, before any trial container
    more,state=guardrail_gate(root,run_dir,plan,policy,envelope,probe);reasons+=more;probe=dict(probe,status=state)
    sizes=policy['sizes'];tiers=[s['tier'] for s in plan['sessions']]+[m['tier'] for m in plan['memory']]+[c['tier'] for c in plan.get('capacity') or []];rows=max(sizes[t] for t in tiers) if tiers else 0   # Task 22: the reference covers the capacity tier
    if probe['status']=='PASS' and selftest:       # Task 6: a selftest plan measures no row; its run is never VALID
        reasons.append('selftest plan: test-only stub run, never decision evidence (before-run checks not run)')
    elif probe['status']=='PASS':                    # Amendment A: correctness gates of the project before any timing
        pre,pre_ev=before_run_checks(root,run_dir,project);reasons+=pre;probe['evidence_paths']+=pre_ev
        if pre:probe=dict(probe,status='GATED')
    native=None;native_record=None
    if probe['status']=='PASS' and kernel_decl is not None and not selftest:   # Task 19: build once per run, then the three-version agreement
        native,native_record,more,ev=run_native_build(root,run_dir,project,kernel_decl);reasons+=more;probe['evidence_paths']+=ev
        if more:probe=dict(probe,status='GATED')
    base={'schema_version':1,'run_id':run_dir.name,'case':case['case_id'],'case_manifest':bm.container_case_path(case['case_id'],project,root),'project_dir':project,
          'project_identity':identity,'dataset':plan['dataset'],'rows':rows,'sizes':sizes,'pyperf':plan['pyperf'],'local':False,'output':'bench/out',
          'request_limit':plan['request_limit']}   # G-ALO-CO: the coordinator gives every child SAFE_C_BENCH_REQUEST_LIMIT from it
    native_restore=()
    if native is not None:                           # Task 19: the binary digests and the kernel declaration reach every timing and memory job
        base['native']=bench_native.native_plan(native);base['native_kernel']=dict(kernel_decl['kernel']);native_restore=tuple(bench_native.native_restore(native))
    observations=[];sess_acc=[];phases=[];evidence=list(probe['evidence_paths']);admission=[];restore=[];children=[];killed=[];ref_counts={}
    import bench_deadline        # G2.6: the once-per-run reference evaluates every planned selector
    covered=[t for s in plan['sessions'] for t in s['trials'] if 'call_deadline_seconds' in t]
    ref_plan={k:v for k,v in plan.items() if k!='test_floor_seconds'}     # the test floor binds only the stub trial (Task 6)
    ref_deadline=bench_deadline.deadline_fields(case,policy,'reference',dict(ref_plan,sizes=sizes),{'variant':'py-reference','selectors':sorted({t['selector'] for t in covered})},
                                                plan.get('calibration'),policy['job_deadlines']['session']) if covered else {}
    # G2.3 (P3R2-04, Task 6): the planned selectors other than `all` (opaque strings) reach the reference job, which asks each
    # selector's adapter for its reference_overhead (outside every timed interval); absent when every trial is `all`.
    overhead={'overhead_selectors':sel} if (sel:=sorted({t.get('selector','all') for s in plan['sessions'] for t in s['trials']}-{'all'})) else {}
    def finish(s):
        s.close();held.append(lock_held(s));admission.append(active_before(s))
    if probe['status']=='PASS':                      # spec 4: one reference per run, outside timing; restored by digest into each session
        s=BenchSession(root,run_dir)
        try:
            r=s.job({**base,'job':'reference','deadline_seconds':policy['job_deadlines']['session'],**ref_deadline,**overhead},'reference',policy['job_deadlines']['session']);evidence.append(r['evidence_path']);row=last_json(r['output'])
            killed+=[x for x in [bench_deadline.job_reason(row)] if x]
            if passed(r) and row.get('status')=='PASS':
                s.fetch('bench/out/reference.json',run_dir/'reference.json')
                if file_hash(run_dir/'reference.json')!=row.get('reference_sha256'):raise GateError('fetched reference digest differs')
                # S3-04: restored with the digest checked at fetch, so a later host edit is refused (DD-01)
                base['reference_sha256']=row['reference_sha256'];restore=[('bench/private/reference.json',run_dir/'reference.json',row['reference_sha256'])]
                reasons+=copy_reference_counts(row,ref_counts)
            else:reasons.append('reference job failed')
        finally:finish(s)
    for sess in (plan['sessions'] if probe['status']=='PASS' and restore else []):
        deadline=policy['job_deadlines']['smoke' if plan['mode'] in ('smoke','selftest') else 'session'];s=BenchSession(root,run_dir)
        stub={'mode':'selftest','test_env':plan['test_env']} if selftest else {}    # Task 6: the coordinator passes test_env only for this mode
        try:
            r=s.job({**base,'job':'timing','trials':sess['trials'],'deadline_seconds':deadline,**stub},'timing-'+sess['session'],deadline,restore=tuple(restore)+native_restore);evidence.append(r['evidence_path']);row=last_json(r['output'])
            if not passed(r) or row.get('status')!='PASS':reasons.append(f"timing session {sess['session']} did not complete")
            reasons+=blocked_start_reasons(row)       # N4-A10: a BLOCKED row makes the run not VALID
            for src in session_files(row):s.fetch('bench/out/'+src,run_dir/sess['session']/src)
            children+=[dict(c,session=sess['session']) for c in row.get('children',[]) if isinstance(c,dict)]
        finally:finish(s)
        observations+=read_jsonl(run_dir/sess['session']/'observations.jsonl');phases+=read_jsonl(run_dir/sess['session']/'phases.jsonl')
        win=row.get('cgroup_window') or {};w=(win.get('last_usage_usec')-win.get('first_usage_usec')) if isinstance(win.get('first_usage_usec'),int) and isinstance(win.get('last_usage_usec'),int) else None
        sess_acc.append({'session':sess['session'],'host_total_usec':bench_accounting.host_total_usec(s.runner.session),'window_usec':w,
                         'launcher_cgroup_inode':((s.runner.session or {}).get('effective') or {}).get('cgroup_inode'),'job_cgroup_inode':row.get('cgroup_inode'),
                         'rows':read_jsonl(run_dir/sess['session']/'observations.jsonl')+read_jsonl(run_dir/sess['session']/'phases.jsonl')})   # T11-APP-04: every row; a missing delta is a B15 reason
        kills=row.get('deadline_kills')                # B12: a foreign orphan alive after a call-deadline reap, after the session ended
        extend_unique(reasons,['run-invalid: '+r for r in bench_guardrails.orphan_reasons([] if kills is None else kills if isinstance(kills,list) else [kills])])
    for mem in (plan['memory'] if probe['status']=='PASS' and restore else []):
        s=BenchSession(root,run_dir);got=[]
        try:
            r=s.job({**base,'job':'memory','trial':mem,'deadline_seconds':policy['job_deadlines']['memory']},'memory-'+mem['trial_id'],policy['job_deadlines']['memory'],restore=native_restore);evidence.append(r['evidence_path'])
            row=last_json(r['output']);reason=bench_deadline.job_reason(row);killed+=[x for x in [reason] if x]
            ok=passed(r) and row.get('status')=='PASS'
            # T16-APP-05 (G2.6 "the failed row is kept"): a job killed at its call deadline keeps its failed row, an ineligible
            # observation, so the attempt stays visible (never a false "missing failed attempt")
            if ok or reason is not None:got=read_jsonl(s.fetch('bench/out/memory.jsonl',run_dir/'memory'/(mem['trial_id']+'.jsonl')))
            if not ok:reasons.append(f"memory trial {mem['trial_id']} did not complete")
            children+=[dict(c,session='memory-'+mem['trial_id']) for c in row.get('children',[]) if isinstance(c,dict)]
        finally:finish(s)
        after=((s.runner.session or {}).get('lifecycle') or {}).get('counters_after',{})
        for o in got:
            if isinstance(o.get('memory'),dict):o['memory']['group_peak_bytes']=int(after['memory.peak']) if 'memory.peak' in after else None   # a killed row has no memory figure
        observations+=got
    if probe['status']=='PASS' and restore and plan.get('capacity'):     # Task 22 (H6): one capacity session after the memory trials; exploratory, never decides
        import bench_capacity
        got,cr,ce=bench_capacity.run_capacity(root,run_dir,plan,base,restore,policy,BenchSession,finish);observations+=got;reasons+=cr;evidence+=ce
    _memory_eligibility(observations)
    invalid=0
    for o in observations+phases:
        try:validate(root,'bench-observation',o)
        except GateError:invalid+=1
    if invalid:reasons.append(f'{invalid} observation rows fail the bench-observation schema')
    undeclared=undeclared_counts(root,project,observations)        # FR5: the verdict count names come from the project protocol
    if undeclared:reasons.append('observation verdict counts outside the project protocol verdict_counts: '+', '.join(undeclared)[:200])
    if probe['status']=='PASS' and restore:reasons+=run_status(plan,observations,phases,policy)[1]
    if native_record is not None and restore:reasons+=check_native_timing(observations,policy,(native_record.get('kernel') or {}).get('sha256'))   # Task 19
    extend_unique(reasons,[f'run-invalid: {x}' for x in sorted(set(killed))])   # G2.6: a reference or memory job killed at its call deadline
    if probe['status']=='PASS' and any(c.get('isolated') is not True for c in children):reasons.append('a trial child did not start isolated')
    (run_dir/'observations.jsonl').write_text(''.join(json.dumps(o,sort_keys=True)+'\n' for o in observations))
    (run_dir/'phases.jsonl').write_text(''.join(json.dumps(o,sort_keys=True)+'\n' for o in phases))
    acc_reasons,accounting=bench_accounting.reconcile(sess_acc,policy) if sess_acc else ([],[]);reasons+=acc_reasons
    import bench_evidence            # B15 (Task 16): integrity of the recorded rows, only when trials ran (a BLOCKED run started none)
    recorded_datasets={'dataset':{k:plan['dataset'][k] for k in ('kind','size','seed','sha256','rows')},**({'datasets':json.loads(json.dumps(plan['datasets']))} if plan.get('datasets') else {})}   # T16-APP-03
    if probe['status']=='PASS' and restore:reasons+=bench_evidence.check_integrity(plan,{'run_id':run_dir.name,**recorded_datasets},observations+phases,policy)
    status='INVALID_EXPERIMENT' if probe['status']=='GATED' else 'BLOCKED' if probe['status']!='PASS' else 'VALID' if not reasons else 'INVALID_EXPERIMENT'
    import datetime
    run={'schema_version':1,'run_id':run_dir.name,'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'case':case['case_id'],
         'case_version':case['version'],'mode':plan['mode'],'dataset':{k:plan['dataset'][k] for k in ('kind','size','seed','sha256','rows')},
         'plan':{'plan_id':plan['plan_id'],'plan_version':plan['plan_version'],'estimate_seconds':plan['estimate_seconds'],'seed':plan['seed'],
                 'project_dir':project,'project_identity':identity},
         'envelope':probe.get('envelope'),'image_id':BenchSession.image(root),'policy_sha256':file_hash(root/'safety/performance-policy.json'),
         'protocol_sha256':protocol_sha256,       # FR3: the project's protected protocol file (null without one)
         'fixtures_sha256':file_hash(root/'safety/performance-fixtures.json'),'source_identity':source_identity(root)[0],
         'runtime':{**(probe.get('runtime') or {}),'pool_start_method':'spawn','pool_pending_window':'2 x workers','chunk_rule':'one chunk per worker per request, fixed-seed permutation (max '+format(plan['request_limit'],',')+' records per request)','children':children,
                    'idle_children':'one session container keeps every trial child of its plan alive between calls; idle warm pools of other rows share the cgroup during a trial (no work, small CPU and pids)'},
         'admission':{'lock_held_ns':sum(held),'active_at_handshake':admission},'evidence':{'observations':'observations.jsonl','phases':'phases.jsonl','jobs':evidence},
         'status':status,'reasons':[r[:300] for r in reasons[:200]],'accounting':accounting,'replay_of':getattr(args,'replay_of',None)}
    if run['replay_of'] is None:run.pop('replay_of')     # Task 20: only a replay names the replayed run
    failure_reasons=sorted({o['failure_reason'] for o in observations if o.get('failure_reason')}|set(killed))
    if failure_reasons:run['failure_reasons']=failure_reasons[:16]
    run.update(ref_counts)          # G3.7 and G2.3: aggregate engine evaluations and admit exclusions of the run reference
    if native_record is not None:run['native']=native_record        # Task 19: the run build and its agreement check
    if 'datasets' in recorded_datasets:run['datasets']=recorded_datasets['datasets']    # T16-APP-03: the named datasets of the run
    try:run['evidence_digests']=bench_evidence.digest_files(run_dir)     # H8
    except (GateError,OSError) as exc:        # T16-APP-06 (b), T17-APP-03: the run is never lost; unbound evidence decides nothing (a real failure keeps its status)
        why=str(exc) if isinstance(exc,GateError) else type(exc).__name__
        run['reasons']=([f'{bench_evidence.UNBINDABLE}: {why}'[:300]]+run['reasons'])[:200]
        if status=='VALID':status=run['status']='BLOCKED'
    run['bench_profile_sha256']=bench_evidence.bench_profile_sha256(root)
    run[bench_evidence.RECORD_KEY]=bench_evidence.run_record_sha256(run)      # T17-APP-01: the last key; binds run.json itself
    validate(root,'bench-run',run);atomic_json(run_dir/'run.json',run)
    emit(args,{'status':status,'run_id':run_dir.name,'observations':len(observations),'reasons':len(reasons)},f"bench run {run_dir.name}: {status} ({len(observations)} observations, {len(reasons)} reasons)")
    return {'VALID':0,'INVALID_EXPERIMENT':1,'BLOCKED':2}[status]

def per_trial(observations,field):
    """F-07/B09: per-unit value = field / (loops x units); the correlated inner samples (pyperf values) of one trial collapse to
    their median. Only eligible non-warmup rows with work count. Returns {block: value}: classify pairs blocks, not trial ids."""
    import bench_stats as bs
    use=[o for o in observations if not o['warmup'] and o['eligible'] and o['work_units'] and o.get(field) is not None and o.get('block') is not None]
    values=bs.per_trial_values(use,field);block={o['trial_id']:o['block'] for o in use};out={}
    for tid,v in values.items():
        if block[tid] in out:raise ValueError(f'two trials of one row share block {block[tid]}')
        out[block[tid]]=v
    return out

def per_trial_busy(observations):
    """B09: busy CPUs (cgroup CPU / wall) as one value per trial, the median over its inner samples; {block: value}."""
    import bench_stats as bs
    by={}
    for o in observations:
        if o['warmup'] or not o['eligible'] or o.get('block') is None or o.get('cpu_usage_usec') is None or not o.get('wall_ns'):continue
        by.setdefault(o['trial_id'],(o['block'],[]))[1].append(o['cpu_usage_usec']*1000.0/o['wall_ns'])
    out={}
    for block,vals in by.values():
        if block in out:raise ValueError(f'two trials of one row share block {block}')
        out[block]=bs.trial_value(vals)
    return out

def _run_dir(root,run_id):
    if not isinstance(run_id,str) or not re.fullmatch(r'[0-9a-f]{32}',run_id):raise GateError('run id must be 32 lowercase hex digits')
    path=Path(root)/'artifacts/bench'/run_id
    if not (path/'run.json').is_file():raise GateError('no recorded run with this id')
    return path

def chunk_imbalance(observations):
    """Amendment E item 4: per trial, max(chunk_wall_ns) / median(chunk_wall_ns) over its chunks (the median of its inner
    samples), summarized over the trials; None values (no chunk times, or a zero median) are left out."""
    import bench_stats as bs
    by={}
    for o in observations:
        t=(o.get('pool') or {}).get('chunk_wall_ns')
        if o.get('warmup') or not o.get('eligible') or not t:continue
        med=bs.median(t)
        if med and med>0:by.setdefault(o['trial_id'],[]).append(max(t)/med)
    return bs.summarize([bs.median(v) for v in by.values()])

VARIANT_LABELS={'py-library':'C++ library through SWIG; per-evaluation Python callback cost included'}   # spec Amendment B item 5

def best_python_key(groups,point,scope,mode,tier,guard=None):
    """Task 19 (C3): the group key of the strongest Python row of (point, scope, mode, tier) by the decide rule
    bench_decide.best_python_of (N4-A02): the smallest median per-unit wall among the Python rows (py-library included)
    with eligible trials, ties to the smaller key text; a pool row counts only within the pool CPU guard `guard` against
    the best direct Python row (None: no guard). None without one."""
    import bench_stats as bs, bench_decide
    keys=[k for k,os_ in groups.items() if k[:3]==(point,scope,mode) and k[5]==tier and not k[3].startswith('c-') and per_trial(os_,'wall_ns')]
    def med(k,field,scale=1.0):
        v=per_trial(groups[k],field);return bs.median([x*scale for x in v.values()]) if v else None
    return bench_decide.best_python_of(keys,variant=lambda k:k[3],metric=lambda k:med(k,'wall_ns'),cpu=lambda k:med(k,'cpu_usage_usec',1000.0),
                                       name=str,guard=guard)

def compare_pool_cpu_guard(policy):
    """N4-A02: compare has no decision policy, so its best Python row uses the smallest non-null pool_cpu_guard of the
    framework decision policies (a pool row within it is within the guard of every framework policy); None when every
    policy has null."""
    guards=[p.get('pool_cpu_guard') for p in (policy.get('decision_policies') or {}).values() if isinstance(p,dict)]
    guards=[g for g in guards if isinstance(g,(int,float)) and not isinstance(g,bool)]
    return min(guards) if guards else None

def compare_cmd(root,args):
    import bench_evidence
    with bench_evidence.run_lock(args.run_id):return _compare_locked(root,args)     # T16-APP-06 (c): one command per run

def _compare_locked(root,args):
    import bench_stats as bs
    run_dir=_run_dir(root,args.run_id);run=read_json(run_dir/'run.json')
    import bench_evidence, bench_accounting
    if bench_evidence.unbindable_blocked(run):          # T17-APP-03: bench run could not bind the evidence; nothing to compare
        emit(args,{'status':'BLOCKED','reasons':run['reasons'][:1]},'BLOCKED: '+run['reasons'][0]);return 2
    ev_problems=bench_evidence.verify(run_dir,run)
    if ev_problems and not bench_evidence.is_unbound(ev_problems):
        emit(args,{'status':'FAIL','reasons':ev_problems[:20]},'compare refused: '+'; '.join(ev_problems[:5]));return 1
    if bench_evidence.is_unbound(ev_problems) and bench_evidence.is_stripped(run):     # T16-APP-01
        emit(args,{'status':'FAIL','reasons':[bench_evidence.STRIPPED]},'compare refused: '+bench_evidence.STRIPPED);return 1
    record=bench_evidence.verify_record(run)           # T17-APP-01: run.json itself
    if record and record!=[bench_evidence.RECORD_UNBOUND]:
        emit(args,{'status':'FAIL','reasons':record},'compare refused: '+record[0]);return 1
    acc=bench_accounting.recheck(run,run_dir)          # P3R4-01, P3R5-02: before any observation is read
    if acc and acc!=[bench_accounting.UNRECORDED]:
        emit(args,{'status':'FAIL','reasons':acc[:20]},'compare refused: '+'; '.join(acc[:5]));return 1
    causes=(['recorded before evidence digests'] if bench_evidence.is_unbound(ev_problems) else [])+(['run.json not bound'] if record else [])+(['cgroup identity unrecorded'] if acc else [])
    unbound=f"unbound ({'; '.join(causes)})" if causes else None
    if run['mode']=='profile':raise GateError('profiled runs never enter a comparison')
    pol=bm.load_policy(root);stat=pol['statistics'];pa=pol['pyperf'];eff=pol['effects'];obs=read_jsonl(run_dir/'observations.jsonl');phases=read_jsonl(run_dir/'phases.jsonl')
    try:plan=read_json(run_dir/'plan.json')
    except FileNotFoundError:            # T16-APP-06 (a): a structured refusal
        emit(args,{'status':'FAIL','reasons':['missing: plan.json']},'compare refused: missing: plan.json');return 1
    blocked=run['status']=='BLOCKED' and not bench_evidence.has_timed_rows(obs)   # T16-APP-04: no trial ran
    integrity=[] if blocked else bench_evidence.check_integrity(plan,run,obs+phases,pol)     # B15, P10 on the recorded files
    if integrity:
        emit(args,{'status':'FAIL','reasons':integrity[:20]},'compare refused: '+'; '.join(integrity[:5]));return 1
    timed=[o for o in obs if not o['warmup'] and o['scope'] in ('caller','kernel')];memory=[o for o in obs if o['scope']=='memory']
    valid=run['status']=='VALID';undecided={'outcome':'INCONCLUSIVE','reason':f"invalid run ({run['status']})"}
    decide=lambda a,b:bs.classify(a,b,relative=eff['relative'],min_abs=eff['min_abs_ns_per_unit'],min_blocks=eff['min_blocks'],resamples=stat['bootstrap_resamples'],seed=stat['bootstrap_seed'],interval=stat['interval'])
    cls=lambda a,b:decide(a,b) if valid else dict(undecided)     # Important 5: an invalid run decides nothing
    groups={};guard=compare_pool_cpu_guard(pol)      # N4-A02: the decide rule, with the strictest framework pool CPU guard
    for o in timed:groups.setdefault((o['point'],o['scope'],o['mode'],o['variant'],o['workers'],o['tier'],o.get('route')),[]).append(o)   # Task 19: the route
    rows=[]
    for key in sorted(groups,key=str):
        point,scope,mode,variant,workers,tier,route=key;os_=groups[key];el=[o for o in os_ if o['eligible'] and o['work_units']]
        wall=per_trial(os_,'wall_ns');cpu=[v*1000.0 for v in per_trial(os_,'cpu_usage_usec').values()]
        base=groups.get((point,scope,mode,'py-reference','direct',tier,None),[]);rel=None
        if variant!='py-reference' and base:rel=cls(per_trial(base,'wall_ns'),wall)
        best=best_python_key(groups,point,scope,mode,tier,guard) if variant.startswith('c-') else None      # Task 19 (C3): every C row against the strongest Python row
        vs_best=cls(per_trial(groups[best],'wall_ns'),wall) if best is not None else None
        mem=[o['memory'] for o in memory if scope=='caller' and o.get('mode')==mode and o['variant']==variant and o['workers']==workers and o.get('route')==route and o.get('eligible') and o.get('memory')]   # memory trials are caller-scope
        trials={o['trial_id'] for o in os_};good={o['trial_id'] for o in el}
        rows.append({'case':run['case'],'size':tier,'scope':scope,'mode':mode,'runtime':(run.get('runtime') or {}).get('python'),'variant':variant,'workers':workers,
                     'variant_label':VARIANT_LABELS.get(variant),'language':'c' if variant.startswith('c-') else 'python','route':route,
                     'route_label':(pol.get('routes') or {}).get(route) if route else None,
                     'best_python':None if best is None else row_label(best[3],best[4]),'relative_wall_vs_best_python':vs_best,
                     'envelope':(run.get('envelope') or {}).get('cpus'),'point':point,'completed_units':sum(o['loops']*(o['work_units'] or 0) for o in el),'failures':len(trials-good),'repetitions':len(trials),
                     'wall_ns_per_unit':bs.summarize(wall.values()),'throughput_per_s':(1e9/bs.median(list(wall.values()))) if wall else None,
                     'cpu_usec':bs.summarize([o['cpu_usage_usec'] for o in el if o['cpu_usage_usec'] is not None]),'cpu_ns_per_unit':bs.summarize(cpu),
                     'busy_cpus':bs.summarize(per_trial_busy(os_).values()),
                     'group_peak_bytes':bs.summarize([m['group_peak_bytes'] for m in mem if m.get('group_peak_bytes') is not None]),
                     'ready_state_bytes':bs.summarize([m['ready_current'] for m in mem if m.get('ready_current') is not None]),
                     'sampled_rss_uss_pss':'not sampled (diagnostic runs only)','relative_wall_vs_py_reference':rel,
                     'pyperf_disagreements':sum(1 for o in os_ if o.get('pyperf_wall_ns') is not None and abs(o['pyperf_wall_ns']-o['wall_ns'])>max(pa['agreement_abs_ns'],pa['agreement_rel']*o['wall_ns'])),
                     'chunk_imbalance':chunk_imbalance(os_) if variant in POOLED else None,
                     'correctness':f'{len(good)}/{len(trials)} eligible','evidence_quality':'exploratory (smoke)' if run['mode']=='smoke' else 'decision','decision':'not evaluated in Phase 1'})
        if rows[-1]['pyperf_disagreements']:rows[-1]['evidence_quality']='pyperf-disagreement'
        if unbound:rows[-1]['evidence_quality']=unbound             # H8, R-8; ruling T16-C1: the invalid-run label below wins
        if not valid:rows[-1]['evidence_quality']=f"invalid run ({run['status']})"
    no_change=[];aa='py-optimized' if any(k[3]=='py-optimized' for k in groups) else 'py-reference'   # Amendment A 6b: control cases have no implemented py-optimized
    for (point,scope,mode,variant,workers,tier,route),os_ in sorted(groups.items(),key=lambda kv:str(kv[0])):
        if variant!=aa:continue
        pt=per_trial(os_,'wall_ns');vals=[pt[b] for b in sorted(pt)]
        a=vals[0::2];b=vals[1::2];n=min(len(a),len(b))
        no_change.append({'point':point,'scope':scope,'mode':mode,'workers':workers,'tier':tier,'control':f'no-change (A/A: even versus odd blocks of {aa})',**cls({i:a[i] for i in range(n)},{i:b[i] for i in range(n)})})
    scaling=[]      # B10 on real data: the largest worker count of a pool variant against its 1-worker row, paired by block
    for (point,scope,mode,variant,workers,tier,route),os_ in sorted(groups.items(),key=lambda kv:str(kv[0])):
        if variant not in POOLED+('c-threads',) or workers!=1:continue
        top=max((k[4] for k in groups if k[:4]==(point,scope,mode,variant) and k[5]==tier and k[6]==route and k[4]!=1),default=None)
        if top is None:continue
        tag=f' [{route}]' if route else ''
        scaling.append({'point':point,'scope':scope,'mode':mode,'variant':variant,'base':f'{variant} x1{tag}','other':f'{variant} x{top}{tag}',
                        **cls(per_trial(os_,'wall_ns'),per_trial(groups[(point,scope,mode,variant,top,tier,route)],'wall_ns'))})
    empty=bs.summarize([p['wall_ns'] for p in phases if p['phase']=='control-zero'])
    identity=check_control_identity(run['case'],rows) if valid and run['case'] in ('bench-control-spin','bench-control-wait') else None
    import bench_capacity
    atomic_json(run_dir/'compare.json',{'run_id':args.run_id,'status':run['status'],'rows':rows,'capacity':bench_capacity.capacity_rows(obs,pol),   # Task 22: exploratory
                'routes':route_summary(rows,pol),       # Task 19 (C3): one labeled line per route present in the run
                'best_python_rule':{'metric':'wall_ns_per_unit','pool_cpu_guard':guard,       # N4-A02
                                    'rule':'bench_decide.best_python_of (the decide rule) with the smallest pool_cpu_guard of the framework decision policies; ranked by wall, so it may differ from the row of a decide policy with another metric or guard'},
                'controls':{'no_change':no_change,'scaling':scaling,'empty_overhead':dict(empty,label='handshake overhead; reported, never subtracted'),
                            'identity':None if identity is None else {'status':'PASS' if not identity else 'FAIL','problems':identity}}})
    result='BLOCKED' if blocked else 'PASS' if valid else 'FAIL'       # T16-APP-04: a BLOCKED run without rows keeps its BLOCKED result
    emit(args,{'status':result,'rows':len(rows),'run_status':run['status']},f"compare {args.run_id}: {len(rows)} rows"+('' if valid else f" (invalid run {run['status']}: nothing decided)"))
    return EXIT[result]

def row_label(variant,workers):return variant if workers=='direct' else f'{variant} x{workers}'

def row_language(r):return r.get('language') or ('c' if str(r.get('variant','')).startswith('c-') else 'python')

def route_report_lines(data):
    """Task 19 (C3): the summary lines of every route present in the compare rows (with its label) and of each C row against
    the strongest Python row; [] for a run without C rows (an older compare.json has no `routes` key)."""
    c_rows=[r for r in data['rows'] if row_language(r)=='c']
    if not c_rows and not data.get('routes'):return []
    out=['Routes (Task 19): '+('; '.join(data.get('routes') or []) or 'none')]
    for r in c_rows:
        vb=r.get('relative_wall_vs_best_python') or {};ratio=f" ratio {vb['ratio']:.3g} [{vb['low']:.3g}, {vb['high']:.3g}]" if 'ratio' in vb else ''
        out.append(f"C row {row_label(r['variant'],r['workers'])} route {r.get('route') or 'none'} ({r['scope']}/{r['mode']} at {r['point']}): against best Python {r.get('best_python') or 'none'}: {vb.get('outcome','n/a')}{ratio}"
                   +(f"; route label: {r['route_label']}" if r.get('route_label') else ''))
    return out+['']

def report_cmd(root,args):
    import bench_evidence
    with bench_evidence.run_lock(args.run_id):return _report_locked(root,args)      # T16-APP-06 (c); re-entrant for the compare call

def _report_locked(root,args):
    run_dir=_run_dir(root,args.run_id)
    import bench_evidence
    run=read_json(run_dir/'run.json')
    if bench_evidence.unbindable_blocked(run):          # T17-APP-03
        emit(args,{'status':'BLOCKED','reasons':run['reasons'][:1]},'BLOCKED: '+run['reasons'][0]);return 2
    ev_problems=bench_evidence.verify(run_dir,run)       # H8: verify before use
    if ev_problems and not bench_evidence.is_unbound(ev_problems):
        emit(args,{'status':'FAIL','reasons':ev_problems[:20]},'report refused: '+'; '.join(ev_problems[:5]));return 1
    if bench_evidence.is_unbound(ev_problems) and bench_evidence.is_stripped(run):     # T16-APP-01
        emit(args,{'status':'FAIL','reasons':[bench_evidence.STRIPPED]},'report refused: '+bench_evidence.STRIPPED);return 1
    record=bench_evidence.verify_record(run)           # T17-APP-01: run.json itself
    if record and record!=[bench_evidence.RECORD_UNBOUND]:
        emit(args,{'status':'FAIL','reasons':record},'report refused: '+record[0]);return 1
    if not (run_dir/'compare.json').is_file():
        import contextlib, io
        with contextlib.redirect_stdout(io.StringIO()):compare_cmd(root,argparse.Namespace(run_id=args.run_id,format='json'))
    if not (run_dir/'compare.json').is_file():          # ruling T16-C1: compare refused the recorded evidence, so nothing is reported
        emit(args,{'status':'FAIL','reasons':['compare refused the recorded evidence']},'report refused: compare refused the recorded evidence');return 1
    data=read_json(run_dir/'compare.json');atomic_json(run_dir/'summary.json',data)
    cols=['case','point','size','scope','mode','runtime','variant','workers','envelope','completed_units','failures','repetitions','throughput_per_s','correctness','evidence_quality','decision']
    outcome=lambda r:(r['relative_wall_vs_py_reference'] or {}).get('outcome','baseline')
    import csv, io
    buf=io.StringIO();w=csv.writer(buf);w.writerow(cols+['wall_ns_per_unit_median','cpu_ns_per_unit_median','busy_cpus_median','group_peak_bytes_median','ready_state_bytes_median','outcome','ratio','ratio_low','ratio_high','blocks','variant_label',
                                                    'language','route','route_label','best_python','outcome_vs_best_python','ratio_vs_best_python'])    # Task 19: appended columns
    for r in data['rows']:
        rel=r['relative_wall_vs_py_reference'] or {};vb=r.get('relative_wall_vs_best_python') or {}
        w.writerow([r[c] for c in cols]+[r['wall_ns_per_unit']['median'],r['cpu_ns_per_unit']['median'],r['busy_cpus']['median'],r['group_peak_bytes']['median'],r['ready_state_bytes']['median'],outcome(r),rel.get('ratio'),rel.get('low'),rel.get('high'),rel.get('blocks'),r.get('variant_label'),
                    row_language(r),r.get('route'),r.get('route_label'),r.get('best_python'),vb.get('outcome'),vb.get('ratio')])
    (run_dir/'summary.csv').write_text(buf.getvalue())
    md=['# Bench run '+args.run_id,'',f"Status: {data['status']}. Evidence quality and decision per row; a CI smoke number never fails or approves a change.",
        'Denominators: per-unit values divide by loops x completed work units of each trial; completed units are summed over eligible non-warmup trials.','',
        'Language: python rows are the native Python versions; c rows run native C code. Route: the data transfer route of a C caller row (none for Python rows and C kernel rows).','',
        '| point | variant | language | route | workers | scope | mode | size | completed units | repetitions | wall ns/unit (median) | CPU ns/unit (median) | busy CPUs (median) | outcome | ratio vs py-reference [95%] | blocks | correctness | evidence quality |',
        '|'+'---|'*18]
    fmt=lambda x:'n/a' if x is None else f'{x:.4g}' if isinstance(x,float) else str(x)
    for r in data['rows']:
        rel=r['relative_wall_vs_py_reference'] or {};ratio=f"{rel['ratio']:.3g} [{rel['low']:.3g}, {rel['high']:.3g}]" if 'ratio' in rel else 'n/a'
        variant=r['variant']+(f" ({r['variant_label']})" if r.get('variant_label') else '')
        md.append(f"| {r['point']} | {variant} | {row_language(r)} | {r.get('route') or 'none'} | {r['workers']} | {r['scope']} | {r['mode']} | {r['size']} | {r['completed_units']} | {r['repetitions']} | {fmt(r['wall_ns_per_unit']['median'])} | "
                  f"{fmt(r['cpu_ns_per_unit']['median'])} | {fmt(r['busy_cpus']['median'])} | {outcome(r)} | {ratio} | {fmt(rel.get('blocks'))} | {r['correctness']} | {r['evidence_quality']} |")
    ident=data['controls'].get('identity');scaling=data['controls'].get('scaling',[]);import bench_capacity
    md+=['','Controls (B13): empty overhead median '+fmt(data['controls']['empty_overhead']['median'])+' ns (reported, never subtracted); no-change A/A outcomes: '+
         (', '.join(f"{c['point']}/{c['mode']}={c['outcome']}" for c in data['controls']['no_change']) or 'none'),
         'Scaling (B10): '+(', '.join(f"{s['point']}/{s['mode']} {s['other']} vs {s['base']}={s['outcome']}"+(f" (ratio {s['ratio']:.3g} [{s['low']:.3g}, {s['high']:.3g}], {s['blocks']} blocks)" if 'ratio' in s else '') for s in scaling) or 'none'),
         *([f"Control identity (B10): {ident['status']}"+(': '+'; '.join(ident['problems']) if ident['problems'] else '')] if ident else []),'',
         *((bench_capacity.report_lines(data['capacity'])+['']) if 'capacity' in data else []),      # Task 22: capacity section (exploratory; absent in an older compare.json)
         *(route_report_lines(data) or []),                                                        # Task 19 (C3): routes and C rows against the strongest Python row
         'An INCONCLUSIVE outcome is final for this run; no measurement is repeated to change it (B09).']
    (run_dir/'summary.md').write_text('\n'.join(md)+'\n')
    ok=data['status']=='VALID'
    emit(args,{'status':'PASS' if ok else 'FAIL','summary':str(run_dir/'summary.md')},str(run_dir/'summary.md'));return 0 if ok else 1

HANDLERS.update(run=run_cmd,compare=compare_cmd,report=report_cmd)
ARGUMENTS.update(run=ARGUMENTS['plan']+[('--plan',{})],compare=[('--run-id',{'required':True})],report=[('--run-id',{'required':True})])

# ---- Task 17: bench profile (cProfile on synthetic data; diagnostic only, never compared) ----
PROFILE_SIZES=('tiny','small','medium','large');PROFILE_DEFAULT=('py-reference','py-optimized')
PROFILE_LABEL='profiled run; diagnostic only, never compared with unprofiled runs'

def profile_dataset(spec):
    kind,_,size=(spec or '').partition(':')
    if kind!='synthetic':raise GateError('profiling runs on synthetic data only')
    if size not in PROFILE_SIZES:raise GateError('unknown synthetic size')
    return size

def profile_variants(case,requested):
    """Each variant is an implemented Python variant of the case, profiled once. The default is py-reference and
    py-optimized where the case implements them (a control case implements no separate py-optimized)."""
    import bench_plan as bp
    known=[v['id'] for v in case['variants'] if v['language'] in bp.PYTHON_LANGUAGES and v['status']=='implemented']   # Task 9b: py-library
    if requested:
        variants=list(dict.fromkeys(requested))
        if not set(variants)<=set(known):raise GateError('profile variants must be implemented Python variants of the case')
    else:variants=[v for v in PROFILE_DEFAULT if v in known]
    if not variants:raise GateError('the case implements no default profile variant; name one with --variant')
    return variants

def profile_files(row):
    """The host re-applies the file-name rule: profile.json, or pstats/<name>."""
    files=row.get('files') if isinstance(row,dict) else None;out=[]
    for f in (files if isinstance(files,list) else [])[:64]:
        if not isinstance(f,str):continue
        head,_,tail=f.rpartition('/')
        if (f=='profile.json' or head=='pstats') and FILE_RE.fullmatch(tail) and tail not in ('.','..'):out.append(f)
    return out

IDENTITY_KEYS=('dataset_sha256','case_manifest_sha256','bench_ref','runtime')

def profile_status(r,row,have_profile):
    """Review fix: a runner or controller failure without a coordinator result row BLOCKS (AGENTS.md); FAIL is kept for a
    coordinator row whose status is not PASS or a missing profile document."""
    if r is None or (not passed(r) and not row):return 'BLOCKED'
    return 'PASS' if passed(r) and row.get('status')=='PASS' and have_profile else 'FAIL'

def profile_identity(path):
    """{variant: input and runtime identity} from the fetched profile.json (rows without an error only)."""
    try:rows=read_json(path)
    except (OSError,ValueError,GateError):return {}
    return {r['variant']:{k:r.get(k) for k in IDENTITY_KEYS} for r in (rows if isinstance(rows,list) else [])
            if isinstance(r,dict) and isinstance(r.get('variant'),str) and 'error' not in r}

def profile_cmd(root,args):
    policy=bm.load_policy(root);size=profile_dataset(args.dataset or 'synthetic:medium');project=project_arg(root,args)
    case=bm.load_case(root,args.case,project);bm.case_rules(root,case,project_dir=project);variants=profile_variants(case,args.variant)
    omitted=[] if args.variant else [{'variant':v,'reason':'not an implemented variant of the case'} for v in PROFILE_DEFAULT if v not in variants]
    deadline=policy['job_deadlines']['smoke'];run_dir=new_run_dir(root,'profile');row={};r=None;evidence=[]
    s=BenchSession(root,run_dir)
    try:
        r=s.job({'schema_version':1,'job':'profile','run_id':run_dir.name,'case_manifest':bm.container_case_path(case['case_id'],project,root),'project_dir':project,
                 'variants':variants,'rows':policy['sizes'][size],'dataset':{'kind':'synthetic','seed':20261007},'deadline_seconds':deadline},'bench-profile',deadline)
        row=last_json(r['output']);evidence=list(s.evidence_paths)
        if passed(r):
            for name in profile_files(row):s.fetch('bench/out/'+name,run_dir/name)
    finally:s.close()
    have=(run_dir/'profile.json').is_file();status=profile_status(r,row,have)
    atomic_json(run_dir/'run.json',{'mode':'profile','status':status,'case':case['case_id'],'variants':variants,'omitted_defaults':omitted,'size':size,'rows':policy['sizes'][size],
                                   'dataset':{'kind':'synthetic','seed':20261007},'identity':profile_identity(run_dir/'profile.json') if have else {},
                                   'label':PROFILE_LABEL,'profile':'profile.json','evidence':evidence})
    emit(args,{'status':status,'run_id':run_dir.name,'profile':str(run_dir/'profile.json')},f'bench profile {run_dir.name}: {status}');return EXIT[status]

HANDLERS['profile']=profile_cmd
ARGUMENTS['profile']=[('--case',{'required':True}),('--variant',{'action':'append'}),('--dataset',{'default':'synthetic:medium'}),PROJECT]

# ---- Task 19a: framework selftest cases, bench ci gates and the P01/P07/P11 bench subcases (framework controls only) ----
AA_MIN_BLOCKS_PER_HALF=6      # the A/A no-change control of the qualification run: 12 primary blocks, even versus odd
DOCTOR_MUTATIONS=(('missing-cgroup-counter','hide-counter:cpu.stat'),('missing-pyperf','hide-module:pyperf'))

def _doctor_job(root,run_dir,mutation=None):
    """One doctor job; with a mutation the plan is a selftest plan. Returns (status, coordinator row, evidence path)."""
    policy=bm.load_policy(root);s=BenchSession(root,run_dir)
    try:
        plan={'schema_version':1,'job':'doctor','run_id':run_dir.name,'expected':expected_versions(root),'deadline_seconds':policy['job_deadlines']['doctor']}
        if mutation:plan.update(selftest=True,mutation=mutation)
        r=s.job(plan,'doctor-'+(mutation or 'control').replace(':','-').replace('.','-'),policy['job_deadlines']['doctor'])
        row=last_json(r['output']);return doctor_job_status(passed(r),row,s.envelope(),mutated=bool(mutation)),row,r['evidence_path']
    finally:s.close()

def doctor_job_status(ok,row,envelope,mutated=False):
    """Review Minor 2: the control doctor is PASS only when its job passed (exit 0), its row passes and an envelope exists.
    A mutated job is expected to exit BLOCKED (2), so its row decides; a job without a row is BLOCKED."""
    if not ok and not (mutated and isinstance(row,dict) and row):return 'BLOCKED'
    return doctor_status(row,envelope)

def _sub(parent,name,variant,rejected,control,evidence,reason):
    return {'parent':parent,'name':name,'variant':variant,'status':'PASS' if rejected and control else 'FAIL','control':'PASS' if control else 'FAIL',
            'evidence_paths':list(evidence),'reason':reason}

def _quiet(fn,root,args):
    """Run one bench operation with its JSON line captured instead of printed. Returns (exit code, last JSON row)."""
    import contextlib, io
    buf=io.StringIO()
    with contextlib.redirect_stdout(buf):rc=fn(root,args)
    return rc,last_json(buf.getvalue())

def _smoke_or_decision(root,case,mode):
    """bench run + compare of one framework control on synthetic:small. Returns (exit code, run directory or None, compare rows)."""
    rc,row=_quiet(run_cmd,root,argparse.Namespace(case=case,project=None,mode=mode,dataset='synthetic:small',calibrate=None,plan=None,format='json'))
    run_id=row.get('run_id')
    if not isinstance(run_id,str) or not re.fullmatch(r'[0-9a-f]{32}',run_id):return rc,None,None
    run_dir=Path(root)/'artifacts/bench'/run_id;_quiet(compare_cmd,root,argparse.Namespace(run_id=run_id,format='json'))
    return rc,run_dir,read_json(run_dir/'compare.json') if (run_dir/'compare.json').is_file() else None

def check_no_change(compare,min_per_half=AA_MIN_BLOCKS_PER_HALF):
    """B13 (Task 16a residual, review Minor 6): the A/A control is visible, pairs at least `min_per_half` blocks per half and is
    EQUAL. FASTER or SLOWER is a false difference; INCONCLUSIVE with the 6-pair design fails B13 with its reason (the run is
    never repeated to change it, B09)."""
    rows=((compare or {}).get('controls') or {}).get('no_change') or []
    if not rows:return ['no-change (A/A) control missing']
    problems=[]
    for c in rows:
        label=f"{c.get('point')}/{c.get('mode')}"
        if c.get('outcome') in ('FASTER','SLOWER'):problems.append(f"{label}: A/A reports {c['outcome']} (a false difference)")
        elif c.get('outcome')!='EQUAL':problems.append(f"{label}: A/A outcome {c.get('outcome')}; EQUAL required with the {min_per_half}-pair design")
        blocks=c.get('blocks')
        if type(blocks) is not int or blocks<min_per_half:problems.append(f"{label}: {blocks} blocks per half, at least {min_per_half} required")
    return problems

def _pressure(o):
    v=o.get('cpu_pressure_total');return v if isinstance(v,(int,float)) and not isinstance(v,bool) else None

def pressure_blocks(observations,point,mode,variant,policy,scope=None,workers=None,tier=None):
    """Amendment H12 (rulings T10-C5, T10-APP-05): the paired blocks of the A/A row (same point, scope, mode, variant, workers and
    tier: the compare group) whose cpu_pressure_total exceeds factor x the median over that row's paired blocks and min_usec.
    Paired blocks are the ones compare pairs: eligible non-warmup rows with work and a wall time, sorted by block, the first
    2 x floor(n/2)."""
    import bench_stats as bs
    rule=policy['controls']['aa_pressure']
    rows=[o for o in observations if not o.get('warmup') and o.get('eligible') and o.get('work_units') and o.get('wall_ns') is not None
          and o.get('block') is not None and o.get('point')==point and o.get('scope')==scope and o.get('mode')==mode and o.get('variant')==variant
          and o.get('workers')==workers and o.get('tier')==tier]
    order=sorted({o['block'] for o in rows});paired=set(order[:len(order)//2*2])
    rows=[o for o in rows if o['block'] in paired and _pressure(o) is not None]
    vals=[_pressure(o) for o in rows]
    if len(vals)<2:return []
    med=bs.median(vals)
    return sorted({o['block'] for o in rows if _pressure(o)>rule['factor']*med and _pressure(o)>rule['min_usec']})

def classify_no_change(compare,observations,policy,min_per_half=AA_MIN_BLOCKS_PER_HALF):
    """B13 with Amendment H12: PASS (EQUAL), FAIL (false difference, too few blocks per half (ruling T10-C4), or INCONCLUSIVE
    without pressure evidence), BLOCKED (INCONCLUSIVE with pressure-evidenced blocks: environmental contamination, never a pass)."""
    problems=check_no_change(compare,min_per_half)
    if not problems:return 'PASS',[]
    rows=((compare or {}).get('controls') or {}).get('no_change') or []
    if not rows or any(c.get('outcome')!='INCONCLUSIVE' for c in rows if c.get('outcome')!='EQUAL'):return 'FAIL',problems
    if any(type(c.get('blocks')) is not int or c['blocks']<min_per_half for c in rows):return 'FAIL',problems
    blocked=[]
    for c in rows:
        if c.get('outcome')!='INCONCLUSIVE':continue
        variant=(c.get('control') or '').rsplit(' of ',1)[-1].rstrip(')')
        hot=pressure_blocks(observations,c.get('point'),c.get('mode'),variant,policy,scope=c.get('scope'),workers=c.get('workers'),tier=c.get('tier'))
        if not hot:return 'FAIL',problems
        blocked.append(f"{c.get('point')}/{c.get('mode')}: A/A INCONCLUSIVE with cpu pressure evidence in blocks {hot} (environmental; BLOCKED)")
    return 'BLOCKED',blocked

def b13_status(other_ok,aa_status):
    """B13 status (ruling T10-C3): a failing B13 condition is FAIL and wins over a BLOCKED A/A control; PASS needs both."""
    if not other_ok or aa_status not in ('PASS','BLOCKED'):return 'FAIL'
    return 'PASS' if aa_status=='PASS' else 'BLOCKED'

def b13_suite(rc,plan,obs,phases,run,cmp,run_id,rc_q,q_run_id,q_cmp,q_obs,policy):
    """B13 suite row of selftest_cases (T10-APP-03), pure: the smoke run (exit code, plan, rows, run record, comparison) gives the
    B13 conditions; the decision qualification run (exit code, comparison, observations) gives the A/A status (classify_no_change);
    b13_status joins them (ruling T10-C3)."""
    aa_status,aa=classify_no_change(q_cmp,q_obs,policy) if rc_q==0 and q_cmp else ('FAIL',['the decision qualification run is not VALID'])
    other_ok=bool(rc==0 and not check_caller_semantics(plan,obs,phases) and not check_perturbation(run,plan,obs,phases)
                  and cmp['controls']['no_change'] and cmp['controls']['empty_overhead']['n'])
    return {'status':b13_status(other_ok,aa_status),'aa_status':aa_status,'run_id':run_id,
            'qualification_run_id':q_run_id,'no_change_problems':aa[:20],
            'no_change':[{k:c.get(k) for k in ('point','mode','outcome','ratio','low','high','blocks')} for c in ((q_cmp or {}).get('controls') or {}).get('no_change',[])],
            'property':'timing apart from profiling and memory diagnostics; empty-overhead and no-change controls visible; '
                       f'A/A of the qualification run pairs {AA_MIN_BLOCKS_PER_HALF} blocks per half and must be EQUAL for PASS; '
                       'an INCONCLUSIVE A/A with cpu pressure evidence in its paired blocks is BLOCKED (Amendment H12), never PASS; '
                       'echo-control part in Phase 2'}

def run_subcases(root,plan,observations,phases,ctl,policy,evidence):
    """P07 and P11 on recorded framework-control evidence. Every mutation works on a copy; each row also records whether the
    unmutated evidence passes the same check (its control), so a broken control never yields PASS. `evidence` names the
    recorded files the rows mutated: {'run': [plan, observations, phases of the smoke run], 'controls': [controls.json]}."""
    run_ev=list(evidence['run']);ctl_ev=list(evidence['controls'])
    import copy
    from schema_check import validate
    rows=[];first=next((i for i,o in enumerate(observations) if not o['warmup'] and o['scope']=='caller'),None)
    control=first is not None and not check_completeness(plan,observations,policy)
    def p07(mutate):
        if first is None:return False
        o=copy.deepcopy(observations);mutate(o);return bool(check_completeness(plan,o,policy))
    name='bench-missing-work-or-rows'
    rows+=[_sub('P07',name,'dropped-result-rows',p07(lambda o:o[first]['verdict'].update(reduction='MISSING_ROWS')),control,run_ev,'dropped rows rejected'),
           _sub('P07',name,'zero-work-units',p07(lambda o:o[first].update(work_units=0)),control,run_ev,'zero work rejected'),
           _sub('P07',name,'missing-planned-row',p07(lambda o:o.pop(first)),control,run_ev,'missing row rejected'),
           # Amendment G4.3: a per-selector row whose work units count every part of a three-part (selector `all`) result
           _sub('P07',name,'unselected-model-units',p07(lambda o:o[first].update(selector='unit-one',work_units=3*policy['sizes'][o[first]['tier']])),control,run_ev,
                'per-selector row counting unselected parts rejected')]
    name='bench-fast-failure-or-false-total'
    base=run_status(plan,observations,phases,policy)[0]=='VALID';rejected=False
    if first is not None:
        fast=copy.deepcopy(observations);row=fast[first];row.update(eligible=False,wall_ns=1);row['verdict']=dict(row.get('verdict') or {},failures={'exception':1})
        key=lambda o:(o.get('point'),o['scope'],o['mode'],o['variant'],o['workers'],o['tier'])
        group=[o for o in fast if key(o)==key(row)]
        rejected=run_status(plan,fast,phases,policy)[0]=='INVALID_EXPERIMENT' and row.get('block') not in per_trial(group,'wall_ns')
    rows.append(_sub('P11',name,'fast-failing-variant',rejected,base,run_ev,'a failed trial never becomes a fast time'))
    cpu=copy.deepcopy(ctl.get('cpu_rows') or []);native=next((r for r in cpu if r.get('name')=='native-spin'),None);rejected=False
    if native is not None:
        native['cpu_usage_usec']=(native.get('extra') or {}).get('parent_self_cpu_usec')
        rejected=evaluate_cpu_controls(cpu,policy,ctl.get('envelope') or {'cpus':0})['status']=='FAIL'
    rows.append(_sub('P11',name,'parent-only-cpu-total',rejected,ctl['cpu']['status']=='PASS',ctl_ev,'parent-only CPU rejected'))
    def schema_ok(row):
        try:validate(root,'bench-observation',row);return True
        except GateError:return False
    original=copy.deepcopy(observations[first]) if first is not None else None;trace=copy.deepcopy(original) if original else None
    if trace is not None:trace['tracemalloc_bytes']=1
    rows.append(_sub('P11',name,'tracemalloc-as-memory',trace is not None and not schema_ok(trace),original is not None and schema_ok(original),run_ev,'no schema field for tracemalloc'))
    mem=copy.deepcopy(ctl.get('memory_rows') or []);seq=next((r for r in mem if r.get('name')=='sequential-children-64x2'),None);rejected=False
    if seq is not None:
        try:seq['group_peak_bytes']=sum(seq['extra']['child_maxrss_kib'])*1024;rejected=evaluate_memory_controls(mem,policy)['status']=='FAIL'
        except (KeyError,TypeError):rejected=False
    rows.append(_sub('P11',name,'summed-rss-peak',rejected,ctl['memory']['status']=='PASS',ctl_ev,'summed RSS is never a group peak'))
    return rows

def selftest_cases(root,run_dir):
    """B01, B02, B03, B05, B09, B10 and B13 on the framework controls, plus every P01/P07/P11 bench subcase.
    Framework code only: the control cases and benchlab; never a project workload or project code."""
    from policy import verify_bench_wheels
    import bench_plan
    root=Path(root);policy=bm.load_policy(root);suites={};additions=[]
    def pick(evaluation,names):
        rows=[c for c in evaluation['checks'] if c['name'] in names]
        return 'BLOCKED' if any(c['status']=='BLOCKED' for c in rows) else 'PASS' if rows and all(c['status']=='PASS' for c in rows) and {c['name'] for c in rows}==set(names) else 'FAIL'
    st,_,ev=_doctor_job(root,run_dir)
    want=len(read_json(root/'developer.lock.json').get('bench_python',{}))     # M1: the lock decides the count (five before Task 5b, six after)
    try:have=verify_bench_wheels(root)
    except GateError:have=None
    suites['B01']={'status':st if want and have==want else 'FAIL','wheels':have,'expected_wheels':want,'evidence_paths':[ev],'property':'tools, wheel manifest and runner qualified'}
    ctl=run_controls(root,run_dir)
    suites['B02']={'status':pick(ctl['cpu'],('wait','spin','control-zero')),'report':str(run_dir/'controls.json'),'property':'wait without busy CPU, compute with measured CPU; unit tests in the unit gate'}
    suites['B03']={'status':pick(ctl['cpu'],('spin-children-2','native-spin','short-children-20')),'report':str(run_dir/'controls.json'),'property':'descendant and short-lived worker CPU'}
    suites['B05']={'status':ctl['memory']['status'],'report':str(run_dir/'controls.json'),'property':'whole-workload memory and peak semantics'}
    rc,latest,cmp=_smoke_or_decision(root,'bench-control-spin','smoke')
    if latest is None or cmp is None:
        for b in ('B09','B10','B13'):suites[b]={'status':'FAIL','reason':'the spin smoke run left no run or comparison'}
        plan,obs,phases,run={'sessions':[],'memory':[]},[],[],{}
    else:
        plan=read_json(latest/'plan.json');obs=read_jsonl(latest/'observations.jsonl');phases=read_jsonl(latest/'phases.jsonl');run=read_json(latest/'run.json')
        outcomes={(r['relative_wall_vs_py_reference'] or {}).get('outcome','baseline') for r in cmp['rows']}
        suites['B09']={'status':'PASS' if rc==0 and not bench_plan.check_trial_design(plan,[o for o in obs if o['scope'] in ('caller','kernel')])
                       and outcomes<={'baseline','EQUAL','FASTER','SLOWER','INCONCLUSIVE'} else 'FAIL','run_id':latest.name,'outcomes':sorted(outcomes),
                       'property':'real repeated demo measurements (smoke blocks); statistics unit tests in the unit gate; no retry'}
        pools=[o for o in obs if o['variant'] in POOLED and not o['warmup']];rt=run.get('runtime') or {}
        rc_wait,wait_dir,wait_cmp=_smoke_or_decision(root,'bench-control-wait','smoke')
        identity=check_concurrency_identity(obs,plan,policy)+check_control_identity('bench-control-spin',cmp['rows'])+(check_control_identity('bench-control-wait',wait_cmp['rows']) if wait_cmp else ['wait: no comparison'])
        suites['B10']={'status':'PASS' if rc==0 and rc_wait==0 and not identity and pools and all(o['eligible'] for o in pools) and 'gil_label' in rt and rt.get('pool_start_method')=='spawn' else 'FAIL',
                       'identity_problems':identity[:20],'run_id':latest.name,'wait_run_id':wait_dir.name if wait_dir else None,'gil_label':rt.get('gil_label'),
                       'property':'thread/process variants, spawn, bounded window; pool error tests in the container suite'}
        rc_q,q_dir,q_cmp=_smoke_or_decision(root,'bench-control-spin','decision')    # the qualification point: 12 blocks, A/A 6 versus 6
        q_obs=read_jsonl(q_dir/'observations.jsonl') if q_dir and (q_dir/'observations.jsonl').is_file() else []
        suites['B13']=b13_suite(rc,plan,obs,phases,run,cmp,latest.name,rc_q,q_dir.name if q_dir else None,q_cmp,q_obs,policy)
    control_doctor=st=='PASS';name='bench-metric-or-runner-unavailable'
    for variant,mutation in DOCTOR_MUTATIONS:
        s_,row,e_=_doctor_job(root,run_dir,mutation)
        seen='cpu.stat' in (row.get('missing_counters') or []) if mutation.startswith('hide-counter:') else (row.get('libraries') or {}).get('pyperf')=='UNAVAILABLE'
        additions.append(_sub('P01',name,variant,s_=='BLOCKED' and seen,control_doctor,[e_],'doctor BLOCKS; metric null with a reason'))
    additions.append(_sub('P01',name,'cpuset-unrecorded',doctor_status({'status':'PASS'},None)=='BLOCKED',control_doctor,[],'no envelope, no PASS'))
    evidence={'run':[str(latest/n) for n in ('plan.json','observations.jsonl','phases.jsonl')] if latest is not None else [],'controls':[str(run_dir/'controls.json')]}
    additions+=run_subcases(root,plan,obs,phases,ctl,policy,evidence) if latest is not None else [_sub(p,n,v,False,False,[],'no smoke run evidence') for r in bm.load_fixtures(root)['pipeline_subcases']
                                                                                         for p,n in [(r['parent'],r['name'])] for v in r['variants'] if p!='P01']
    import bench_deadline;suites['call-deadline']=bench_deadline.selftest_suite(root,run_dir)    # Amendment G2.6 framework control
    # FR1 (FS1 F2), FR3: a stub run and a stub check per test stub of a project protocol (G2.3, I9.4); the framework control
    # suite `call-deadline` above always runs. FR1-01: suites that do not run are recorded in cases.json `not_run` with the
    # reason; a malformed declaration gives a BLOCKED suite, never a silent skip.
    stub,not_run=bench_deadline.stub_suites(root,run_dir);suites.update(stub)
    import bench_units;suites['B09']=bench_units.coverage_suite(root,run_dir,suites['B09'])     # Amendment G8.4: B09 also requires the coverage job PASS
    import bench_phase3;s3,a3=bench_phase3.phase3_cases(root,run_dir,latest);suites.update(s3);additions+=a3     # Task 29: B12, B14, B15, B18, P10, P15
    atomic_json(run_dir/'cases.json',{'suites':suites,'additions':additions,'not_run':not_run});return suites,additions

def example_projects(root):
    """Controller ruling (Task 11a review): every directory examples/<name> with benchmarks/project/bench.json is a framework
    example project, qualified with the framework. Found by layout; the framework names no example."""
    base=Path(root)/'examples'
    if not base.is_dir() or base.is_symlink():return []
    return sorted(f'examples/{p.name}' for p in base.iterdir() if p.is_dir() and not p.is_symlink() and (p/bm.PROJECT_AREA/'bench.json').is_file())

def registered_projects(root):
    """Task 19b: the registered projects of this repository, found by layout: `.` when the root itself declares
    benchmarks/project/bench.json, then every example project (example_projects). The framework names none of them."""
    return (['.'] if (Path(root)/bm.PROJECT_AREA/'bench.json').is_file() else [])+example_projects(root)

def project_suites(root,run_dir):
    """Amendment A (Task 19b): each registered project runs its bench unit suite and every declared `before_run` check through
    the framework, one suite each: project:<dir>:unit and project:<dir>:<check>. A generation tool is declared
    `before_run: false` and is not run. A refused check is BLOCKED with its reason; the later checks still run."""
    suites={}
    for project in registered_projects(root):
        key=f'project:{project}:'
        try:
            rc,out=_quiet(selftest,root,argparse.Namespace(suite='unit',project=project,format='json'))
            suites[key+'unit']={'status':'PASS' if rc==0 else 'BLOCKED' if rc==2 else 'FAIL','property':'project bench unit suite',
                                'evidence_paths':list(((out.get('suites') or {}).get('unit') or {}).get('evidence_paths',[]))}
        except GateError as exc:suites[key+'unit']={'status':'BLOCKED','reason':str(exc)[:200],'evidence_paths':[]}
        try:checks=[c['name'] for c in (bm.project_bench(root,project) or {}).get('checks',[]) if c['before_run']]
        except GateError as exc:suites[key+'declaration']={'status':'BLOCKED','reason':str(exc)[:200],'evidence_paths':[]};continue
        shared=[]                            # Task DD: one project's checks are one session (shared_outputs)
        for name in checks:
            try:
                status,evidence,row=run_check(root,run_dir,project,name,deadline_key='selftest',shared=tuple(shared))
                shared+=shared_outputs(run_dir,name,status,row)
                suites[key+name]={'status':status,'evidence_paths':[evidence],'property':'declared project check'}
            except GateError as exc:suites[key+name]={'status':'BLOCKED','reason':str(exc)[:200],'evidence_paths':[],'property':'declared project check'}
    return suites

def _example_rows(suites):
    """The ci detail per project ({dir: {'unit': status, 'checks': {name: status}}}) from the project suites."""
    rows={}
    for key,value in suites.items():
        project,name=key[len('project:'):].rsplit(':',1);row=rows.setdefault(project,{'unit':'BLOCKED','checks':{}})
        if name=='unit':row['unit']=value['status']
        else:row['checks'][name]=value['status']
    return rows

def _privacy_suite(root,run_dir):
    """Task 18 (spec 16) privacy suite: the redacted stderr probe only (privacy_suite_jobs)."""
    try:
        from bench_privacy import privacy_probe
        return privacy_probe(root,run_dir)
    except GateError as exc:return {'status':'BLOCKED','reason':str(exc)[:200],'evidence_paths':[]}

def ci_gates(root):
    """`./tools/safety ci`: the bench-doctor and bench-selftest gates and the bench subcase additions. The bench-selftest
    gate also holds the privacy suite and the project suites (project_suites: every registered project's bench unit suite
    and `before_run` checks)."""
    run_dir=new_run_dir(root,'ci');probe=doctor_probe(root,run_dir);probe.pop('lock_held_ns',None)
    gates=[{'name':'bench-doctor','status':probe['status'],'details':{k:probe.get(k) for k in ('envelope','libraries','missing_counters','reason') if k in probe},
            'evidence_paths':list(probe.get('evidence_paths',[]))}]
    try:unit_rc,_=_quiet(selftest,root,argparse.Namespace(suite='unit',project=None,format='json'))
    except GateError:unit_rc=2
    try:suites,additions=selftest_cases(root,run_dir)
    except GateError as exc:
        suites={'cases':{'status':'BLOCKED','reason':str(exc)}}
        additions=[dict(_sub(r['parent'],r['name'],v,False,False,[],'bench selftest BLOCKED: '+str(exc)[:200]),status='BLOCKED',control='BLOCKED')
                   for r in bm.load_fixtures(root)['pipeline_subcases'] for v in r['variants']]
    unit='PASS' if unit_rc==0 else 'BLOCKED' if unit_rc==2 else 'FAIL'
    projects=project_suites(root,run_dir);suites.update(projects);suites['privacy']=_privacy_suite(root,run_dir);examples=_example_rows(projects)
    statuses=[v['status'] for v in suites.values()]+[unit]+[a['status'] for a in additions]
    status='PASS' if all(s=='PASS' for s in statuses) else 'BLOCKED' if 'BLOCKED' in statuses and 'FAIL' not in statuses else 'FAIL'
    paths=[p for v in suites.values() for p in v.get('evidence_paths',[])]+[p for a in additions for p in a['evidence_paths']]
    gates.append({'name':'bench-selftest','status':status,'details':{**{k:v['status'] for k,v in suites.items()},'unit':unit,'report':str(run_dir/'ci-gates.json'),
                                                                     'no_change':(suites.get('B13') or {}).get('no_change'),'examples':examples},
                  'evidence_paths':list(dict.fromkeys(paths))})
    atomic_json(run_dir/'ci-gates.json',{'gates':gates,'additions':additions,'suites':suites});return gates,additions

# FR3: the network rate fetch and its run option of the reference example left the framework (FR3 report, handoff list).
# The bench tools make no network call.

def privacy_suite_jobs():
    """The jobs of `bench selftest --suite privacy`: only the stderr probe (Task 18), never a local: project-case run."""
    return ['stderr-probe']

import bench_phase3_cli;bench_phase3_cli.register(HANDLERS,ARGUMENTS)

def configure_parser(parser):
    operations=parser.add_subparsers(dest='operation',required=True)
    for name in HANDLERS:
        command=operations.add_parser(name);command.add_argument('--format',choices=['text','json'],default='text')
        for flag,options in ARGUMENTS.get(name,[]):command.add_argument(flag,**options)

def execute(root,args):
    try:return HANDLERS[args.operation](root,args)
    except GateError as exc:
        print(json.dumps({'status':'BLOCKED','reason':str(exc)}) if getattr(args,'format','text')=='json' else 'BLOCKED: '+str(exc));return 2
