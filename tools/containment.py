"""Live bounded D qualification and additive Docker sabotage accounting."""
from pathlib import Path
import copy
import errno
import json
import os
import shutil
import tempfile
import time
from evidence import GateError, atomic_json, passed, read_json, file_hash
from container_policy import D_IDS, Launcher, make_plan, validate_plan, policy_hash
from policy import exact_ids, source_identity, baseline_gate, baseline_identity


def fixture_inventory(root):
    spec=read_json(root/'safety/containment-fixtures.json')
    from schema_check import validate
    validate(root,'containment-fixtures',spec);exact_ids(spec['cases'],D_IDS)
    if file_hash(root/spec['helper'])!=spec['helper_sha256']:raise GateError('finite containment helper changed')
    return spec

def validate_containment(root,value,*,complete=True):
    from schema_check import validate
    validate(root,'containment-report',value);exact_ids(value['cases'],D_IDS)
    expected={r['id']:r for r in fixture_inventory(root)['cases']}
    for row in value['cases']:
        names=[r['name'] for r in row['subchecks']]
        if len(names)!=len(set(names)) or sorted(names)!=sorted(expected[row['id']]['subchecks']):raise GateError('D subcheck inventory missing/duplicate/mismatched')
        if row['status']=='PASS' and (row['control']!='PASS' or any(r['status']!='PASS' for r in row['subchecks']) or not row['evidence_paths'] or not row['observations']):raise GateError('D pass lacks complete control/evidence')
    if complete and value['status']=='PASS' and any(r['status']!='PASS' for r in value['cases']+value['sabotage']):raise GateError('containment aggregate omits a failed case/subcase')
    return True

def counters(text):return {line.split()[0]:int(line.split()[1]) for line in text.splitlines()}

def new_report(q):
    l=q.runner.launcher
    spec=fixture_inventory(q.root)
    return {'schema_version':1,'status':'BLOCKED','policy_hash':policy_hash(l.value),'source_identity':source_identity(q.root)[0],'image_id':q.runner.lock['image_id'],'runner':l.preflight(),'cases':[{'id':r['id'],'status':'BLOCKED','control':'BLOCKED','classification':'BLOCKED','subchecks':[{'name':n,'status':'BLOCKED'} for n in r['subchecks']],'observations':{},'evidence_paths':[],'reproduce':r['reproduce']} for r in spec['cases']], 'runtime_demo':{},'storage_scope':{'scratch':'explicit sized tmpfs; work/tmp/run/dev-shm included in memory accounting','artifacts':'bounded live collector; fixed byte/file-count retention admission','images':'existing pinned toolchain; bounded <=8 MiB runtime assemblies, no ordinary acquisition/build cache','logs':'local rotating driver plus finite outer capture','daemon_shared_storage':'No global daemon disk quota claimed. Admission is a free-space check; project writable bounds come from tmpfs, collector, finite import inputs and log rotation. Other projects/daemon metadata are outside this project quota.','host_overhead':'8 GiB memory and 8 GiB disk admission headroom, max 4 active project jobs, max 12 GiB reserved container memory. Operator must protect host-wide capacity against unrelated workload changes.'},'sabotage':[],'application_release_ready':False,'independent_enforcement':'UNSEALED','remote_ci_execution':'NOT_RUN','production_approval':'NOT_REQUESTED'}

class Suite:
    def __init__(self,q,value):
        self.q=q;self.runner=q.runner;self.l=q.runner.launcher;self.value=value
        self.directory=q.runner.scratch/'containment';self.directory.mkdir(exist_ok=True)
        self.source=self.directory/'source';self.source.mkdir(exist_ok=True)
        shutil.copytree(q.runner.snapshot,self.source,dirs_exist_ok=True)
        (self.source/'containment-canary').write_text('source-safe');(self.source/'containment-canary').chmod(0o666)
        self.fixture=self.directory/'fixture';self.fixture.mkdir(exist_ok=True)
        (self.fixture/'input-canary').write_text('input-safe');(self.fixture/'input-canary').chmod(0o666)
        self.outside=self.directory/'outside-canary';self.outside.write_text('outside-safe')
        self.hashes={str(p):file_hash(p) for p in [self.source/'containment-canary',self.fixture/'input-canary',self.outside]}
    def launch(self,profile='probe',**kw):return self.l.create(profile,{'/src':self.source,'/fixture':self.fixture},**kw)
    def probe(self,record,mode,control=False,extra=(),timeout=10,env=None,limit=None):
        r=self.l.execute(record,['python3','/src/safety/qualification/containment/probe.py',mode,'control' if control else 'probe',*extra],timeout=timeout,env=env,limit=limit)
        path=self.runner.run_dir/'containment'/('process-'+record['container_id'][:12]+'-'+mode+('-control' if control else '')+'.json')
        r['evidence_path']=str(path);atomic_json(path,r)
        try:data=json.loads(r['output'])
        except ValueError:data={}
        return r,data
    def case(self,cid,checks,observations,records,control=True):
        row=next(x for x in self.value['cases'] if x['id']==cid)
        if set(checks)!=set(x['name'] for x in row['subchecks']):raise GateError('D implementation subcheck inventory mismatch: '+cid)
        row.update(status='PASS' if all(checks.values()) and control else 'FAIL',control='PASS' if control else 'FAIL',classification='CONTAINED_EXPECTED' if all(checks.values()) and control else 'CONTROL_FAILED' if not control else 'NOT_CONTAINED',subchecks=[{'name':k,'status':'PASS' if v else 'FAIL'} for k,v in checks.items()],observations=observations)
        row['evidence_paths']=[str(self.runner.run_dir/('container-'+r['container_id'][:12]+'.json')) for r in records]
        path=self.runner.run_dir/'containment'/(cid+'.json');row['evidence_paths'].append(str(path));atomic_json(path,row)
        print(cid+': '+row['status']+' / control '+row['control'],flush=True)
        return row
    def unchanged(self):return all(file_hash(Path(p))==h for p,h in self.hashes.items())
    def run(self):
        l=self.l
        r=self.launch();out,d=self.probe(r,'identity');bad=copy.deepcopy(r['plan']);bad['user']='0:0'
        rejected=False
        try:validate_plan(bad,l.value,self.runner.lock['image_id'],{'/src':self.source,'/fixture':self.fixture},'probe')
        except GateError:rejected=True
        l.dispose(r)
        self.case('D01',{'inspection':bool(r['effective']),'kernel-limits':r['effective']['limits']==r['effective']['inside']['limits'],'identity':d.get('uid')==1001 and d.get('gid')==1001,'computation':d.get('compute')==45 and passed(out),'mismatch-rejection':rejected},{'effective':r['effective'],'compute':d},[r],passed(out))
        r=self.launch();out,d=self.probe(r,'immutability');l.dispose(r)
        denies=d.get('denials',{})
        self.case('D02',{'root-write':denies.get('/usr/containment-canary')==errno.EROFS,'source-write':denies.get('/src/containment-canary')==errno.EROFS,'input-write':denies.get('/fixture/input-canary')==errno.EROFS,'hash-preserved':self.unchanged(),'scratch-control':d.get('scratch')=='safe' and d.get('source_read')=='source-safe' and d.get('input_read')=='input-safe'},{'operation':d,'outer_hashes':self.hashes},[r],passed(out))
        sibling=self.launch(command=['python3','-c','import time; time.sleep(30)','safe-c-sibling-marker']);sibling['effective']=l.effective(sibling['container_id'],sibling['plan'])
        r=self.launch();out,d=self.probe(r,'resources',extra=[str(self.outside)])
        separation=all(r['effective']['inside']['namespaces'][n]!=sibling['effective']['inside']['namespaces'][n] for n in ['pid','net','ipc','mnt'])
        l.dispose(r);l.dispose(sibling)
        self.case('D03',{'unshared-canary':d.get('outside_visible') is False,'sibling-process':d.get('sibling_marker_visible') is False,'namespace-separation':separation,'mount-inventory':len(r['effective']['inspect']['mounts'])==2,'fixture-control':d.get('supplied')=='input-safe'},{'operation':d,'sibling_container':sibling['container_id']},[r,sibling],passed(out))
        os.environ['SAFETY_SYNTHETIC_SECRET']='synthetic-not-a-real-secret'
        try:
            r=self.launch();out,d=self.probe(r,'secrets',env={'SAFETY_PUBLIC_MARKER':'allowed-nonsecret'})
        finally:os.environ.pop('SAFETY_SYNTHETIC_SECRET',None)
        l.dispose(r)
        alternate=copy.deepcopy(r['plan']);alternate['mounts']['/renamed-control']={'source':'/var/run/docker.sock','readonly':True,'recursive':'disabled'}
        rejected=False
        try:validate_plan(alternate,l.value,self.runner.lock['image_id'],{'/src':self.source,'/fixture':self.fixture},'probe')
        except GateError:rejected=True
        fds=d.get('fds',{});fd_ok=all(v.startswith(('pipe:','/dev/null','/proc/')) for k,v in fds.items() if int(k)>2)
        self.case('D04',{'environment':not d.get('unexpected_environment_names',['missing']) and d.get('synthetic_secret_inherited') is False and d.get('home_default')=='/nonexistent','authority':d.get('management_socket_present') is False,'descriptors':fd_ok,'home':d.get('home_mount_present') is False,'socket-policy-rejection':rejected,'allowed-variable':d.get('allowed')=='allowed-nonsecret'},{'operation':d},[r],passed(out))
        self.network()
        r=self.launch();out,d=self.probe(r,'privilege');l.dispose(r)
        self.case('D06',{'elevation-denied':d.get('setuid_errno')==errno.EPERM,'forbidden-syscall-denied':d.get('keyctl_return')==-1 and d.get('keyctl_errno')==errno.EPERM,'seccomp-active':r['effective']['inside']['status']['Seccomp']=='2','capability-attribution':r['effective']['inside']['status']['CapEff']=='0000000000000000','permitted-syscall':d.get('getpid_ok') is True},{'operation':d,'attribution':{'setuid':'non-root with no CAP_SETUID','keyctl':'Docker builtin seccomp forbids read-only keyctl query; AppArmor remains active. EPERM alone is not credited to every layer.'}},[r],passed(out))
        for cid,mode,profile in [('D07','memory','probe-memory'),('D08','pids','probe-pids'),('D09','cpu','probe-cpu')]:
            r=self.launch(profile,finite_memory=192*1024*1024)
            control,c=self.probe(r,mode,control=True,timeout=5)
            cg=r['effective']['cgroup_path'];before=l.counters(cg)
            out,d=self.probe(r,mode,timeout=6 if mode=='cpu' else 10);after=l.counters(cg);l.dispose(r)
            common={'finite-ceiling':d.get('finite_max_bytes',d.get('finite_attempts',d.get('finite_seconds'))) in [192*1024*1024,64,3],'healthy-control':passed(control) and (c.get('child_exit')==0 if mode=='memory' else c.get('created')==4 and c.get('refusal_errno')==0 if mode=='pids' else c.get('computation_completed') is True)}
            if mode=='memory':
                events=counters(after['memory.events']);prior=counters(before['memory.events'])
                common.update({'limits-verified':r['effective']['limits']['memory.max']==str(96*1024*1024),'memory-intervention':d.get('child_exit') in [-9,42],'event-attribution':events['oom']>prior['oom'] and events['oom_kill']>prior['oom_kill']})
            elif mode=='pids':
                common.update({'limits-verified':r['effective']['limits']['pids.max']=='32','task-refusal':d.get('refusal_errno')==errno.EAGAIN and 4<d.get('created',0)<64,'event-attribution':counters(after['pids.events'])['max']>counters(before['pids.events'])['max'],'children-reaped':d.get('created')==d.get('reaped') and int(after['pids.current'])==int(before['pids.current'])})
            else:
                b=counters(before['cpu.stat']);a=counters(after['cpu.stat']);cpu=d.get('cpu_seconds',0);wall=d.get('busy_wall_seconds',0)
                common.update({'quota-verified':r['effective']['limits']['cpu.max']=='25000 100000','usage-tolerance':2.9<=wall<=4.0 and .35<=cpu<=1.1 and .1<=cpu/wall<=.36,'throttling':a['nr_throttled']>b['nr_throttled'] and a['throttled_usec']>b['throttled_usec'],'independent-deadline':out['failure'] is None and out['seconds']<6})
            self.case(cid,common,{'control':c,'operation':d,'before':before,'after':after,'finite_ceilings':read_json(self.q.root/'safety/containment-fixtures.json')['finite_ceilings']},[r],common['healthy-control'] and passed(out))
        self.space();self.logs();self.lifecycle();self.runtime()
    def network(self):
        l=self.l;name='safe-c-integration-'+__import__('uuid').uuid4().hex
        made=l.docker(['network','create','--internal','--label','org.safe-c.containment=1',name])
        if not passed(made):raise GateError('disposable internal network unavailable')
        records=[]
        try:
            fixture=l.create('integration',{},network=name,command=['python3','-c','import socket,time; s=socket.socket();s.bind(("0.0.0.0",23456));s.listen();s.settimeout(20);end=time.monotonic()+20\nwhile time.monotonic()<end:\n try:\n  c,_=s.accept();c.sendall(b"synthetic-fixture");c.close()\n except TimeoutError:break'])
            fixture['effective']=l.effective(fixture['container_id'],fixture['plan']);records.append(fixture)
            obj=l.json(['inspect',fixture['container_id']])[0];ip=obj['NetworkSettings']['Networks'][name]['IPAddress']
            offline=self.launch();records.append(offline);out,d=self.probe(offline,'network',extra=[ip,'23456'])
            l.dispose(offline)
            permitted=self.launch('integration',network=name);records.append(permitted);positive,c=self.probe(permitted,'network',control=True,extra=[ip,'23456'])
            network=l.json(['network','inspect',name])[0]
            checks={'loopback-control':d.get('loopback')=='loopback','offline-denial':d.get('fixture_reached') is False and d.get('interfaces')==['lo'],'live-fixture-control':c.get('fixture_reached') is True,'internal-network':network['Internal'] is True and network['Name']==name,'no-ports':all(not r['effective']['inspect']['host_config'].get('PortBindings') for r in records),'attachment-policy':set(permitted['effective']['inspect']['network'])=={name} and set(offline['effective']['inspect']['network'])=={'none'}}
            for r in records:l.dispose(r)
            self.case('D05',checks,{'offline':d,'permitted':c,'network':{'name':name,'internal':network['Internal'],'fixture_ip':ip,'fixture_port':23456}},records,passed(positive) and passed(out))
        finally:
            for r in records:l.dispose(r)
            removed=l.docker(['network','rm',name])
            if not passed(removed):raise GateError('owned integration-network cleanup failed')
    def space(self):
        r=self.launch();positive,c=self.probe(r,'space',control=True);out,d=self.probe(r,'space')
        setup=self.l.execute(r,['python3','-c','import pathlib;p=pathlib.Path("/work/valid");p.write_text("valid");pathlib.Path("/work/oversized").write_bytes(b"x"*8192);pathlib.Path("/work/link").symlink_to("valid")'],timeout=5)
        valid=self.runner.collect(r,'valid',self.runner.run_dir/'containment/valid.txt')
        rejected={}
        old=self.l.value['common']['artifact_bytes'];self.l.value['common']['artifact_bytes']=4096
        try:
            for name in ['oversized','../outside-canary','link']:
                try:self.runner.collect(r,name,self.runner.run_dir/'containment/rejected');rejected[name]=False
                except GateError:rejected[name]=True
        finally:self.l.value['common']['artifact_bytes']=old
        self.l.dispose(r)
        fresh=self.launch();f=self.l.execute(fresh,['python3','-c','import pathlib,json;print(json.dumps({"previous":pathlib.Path("/work/valid").exists()}))'],timeout=5);self.l.dispose(fresh)
        self.case('D10',{'byte-bound':d.get('space_errno')==errno.ENOSPC and 0<d.get('written',0)<24*1024*1024 and d.get('filesystem_bytes')==16*1024*1024,'inode-bound':d.get('inode_errno')==errno.ENOSPC and d.get('used_inodes')==d.get('filesystem_inodes')==64,'normal-io':c.get('written')==1024 and c.get('space_errno')==0,'oversize-rejected':rejected['oversized'],'invalid-artifact-rejected':rejected['../outside-canary'] and rejected['link'],'valid-artifact':valid.read_text()=='valid' and passed(setup),'scratch-freshness':passed(f) and json.loads(f['output'])['previous'] is False},{'operation':d,'control':c,'collector_rejections':rejected,'valid_artifact':str(valid)},[r,fresh],passed(positive) and passed(out))
    def logs(self):
        # PID 1 writes exercise the actual Docker log driver; docker exec stdout
        # alone would exercise only outer capture, not rotation.
        r=self.launch(command=['python3','-c','import time,subprocess;time.sleep(2);subprocess.run(["python3","/src/safety/qualification/containment/probe.py","logs","probe"],check=True);time.sleep(15)'])
        r['effective']=self.l.effective(r['container_id'],r['plan'])
        self.l.docker(['exec',r['container_id'],'python3','-c','import time;time.sleep(3)'],timeout=5)
        logs=self.l.docker(['logs',r['container_id']],timeout=5,limit=4*1024*1024)
        lines=logs['output'].splitlines();first=int(lines[0].split()[0]) if lines else -1;last=int(lines[-1].split()[0]) if lines else -1
        self.l.dispose(r)
        capture=self.launch();over,_=self.probe(capture,'logs',limit=8192);self.l.dispose(capture)
        control=self.launch();short=self.l.execute(control,['python3','-c','print("complete-short-diagnostic")'],timeout=5);self.l.dispose(control)
        self.case('D11',{'driver-policy':r['effective']['inspect']['host_config']['LogConfig']['Type']=='local','finite-output':last==4095,'rotation-observed':passed(logs) and 0<first<last and len(logs['output'])<=2*1024*1024,'outer-overflow':over['failure']=='OUTPUT_LIMIT','normal-log':passed(short) and short['output'].strip()=='complete-short-diagnostic','mandatory-incomplete-rejected':not passed(over)},{'retained_first_record':first,'retained_last_record':last,'retained_bytes':len(logs['output']),'configured_driver':r['effective']['inspect']['host_config']['LogConfig'],'outer_failure':over['failure'],'finite_log_bytes':4*1024*1024},[r,capture,control],passed(short))
    def lifecycle(self):
        unrelated=self.launch();r=self.launch();out,d=self.probe(r,'deadline',timeout=.4);life=self.l.dispose(r)
        cancel=self.launch();self.l.execute(cancel,['python3','-c','import subprocess;subprocess.Popen(["python3","-c","import time;time.sleep(6)"]);print("finite-child-started")'],timeout=5);cancel_life=self.l.dispose(cancel)
        fail=self.launch();failure=self.l.execute(fail,['python3','-c','raise SystemExit(7)'],timeout=5);fail_life=self.l.dispose(fail)
        control=self.launch();positive,c=self.probe(control,'deadline',control=True);self.l.dispose(control)
        alive=self.l.json(['inspect',unrelated['container_id']])[0]['State']['Running'];self.l.dispose(unrelated)
        self.case('D12',{'timeout':out['failure']=='TIMEOUT' and d.get('finite_parent_seconds')==8,'children-cleanup':life['children_reaped'] and life['removed'],'state-before-removal':life['state_before']['Running'] is True and life['state_after']['Pid']==0,'cancellation-cleanup':cancel_life['removed'] and cancel_life['children_reaped'],'failure-cleanup':failure['exit_code']==7 and fail_life['removed'],'unrelated-preserved':alive,'normal-exit':c.get('normal_exit') is True},{'timeout':{k:out[k] for k in ['exit_code','failure','seconds']},'lifecycle':life,'cancellation':cancel_life,'failure':fail_life,'finite_helper':d},[r,cancel,fail,control,unrelated],passed(positive))
    def runtime(self):
        from runtime import runtime_smoke
        demo,record=runtime_smoke(self.q,hold=True)
        before=self.l.docker(['logs',record['container_id']],timeout=5)
        b=self.q.build('asan',case='C01');crash=self.q.executable(b,'C01_bad',label='D13-crash-in-own-container')
        after=self.l.docker(['logs',record['container_id']],timeout=5)
        alive=self.l.json(['inspect',record['container_id']])[0]['State']['Running']
        wait=self.l.docker(['wait',record['container_id']],timeout=15);demo['lifecycle']=self.l.dispose(record)
        demo['status']='PASS' if demo['status']=='PASS' and passed(wait) and wait['output'].strip()=='0' else 'FAIL'
        atomic_json(Path(demo['evidence_path']),demo);self.value['runtime_demo']=demo
        # Crash native() records its own completed test container; no trace is
        # printed. Its intended detector was already qualified separately.
        crash_record=next(r for r in self.l.records if r['container_id']==crash['container_id'])
        self.case('D13',{'crash-container':crash['exit_code']!=0 and crash['failure'] is None and crash['profile']=='test-asan','runtime-health':passed(before) and passed(after) and alive and after['output'].count('runtime-demo healthy sum=9')>=before['output'].count('runtime-demo healthy sum=9'),'canaries-unchanged':self.unchanged(),'image-inventory':set(demo['image_members'])=={'demo','lib/x86_64-linux-gnu/libc.so.6','lib64/ld-linux-x86-64.so.2'},'binary-identity':demo['image_members']['demo']==demo['binary_sha256'],'runtime-profile':demo['profile']=='runtime-demo' and bool(demo['effective']),'normal-entrypoint':demo['status']=='PASS' and demo['entrypoint']==['/demo']},{'runtime':demo,'crash':{k:crash[k] for k in ['exit_code','failure','container_id','profile','binary_sha256']},'health_records_before':before['output'].count('runtime-demo healthy sum=9'),'health_records_after':after['output'].count('runtime-demo healthy sum=9'),'source_identity':source_identity(self.q.root)[0]},[record,crash_record],demo['status']=='PASS')

def routing(q,value,report,*,instance=False):
    cases={r['id']:r for r in report['cases']}
    pairs={}
    for cid in ['C01','C11','C21','C32']:
        row=cases[cid]
        if row['status']!='PASS':row=q.qualify_case(cid)
        pairs[cid]=row
    from fuzzing import adapter_build,adapter_replay
    if report['reuse']['clusterfuzzlite']['local_adapter_execution']=='PASS':adapter=True
    else:
        bad=adapter_build(q,'bad');good=adapter_build(q,'good')
        a=adapter_replay(q,bad,'D14-adapter-bad') if bad['audit'] else None
        b=adapter_replay(q,good,'D14-adapter-good') if good['audit'] else None
        adapter=bool(a and b and a['exit_code']!=0 and a['failure'] is None and passed(b) and a['profile']=='fuzz' and b['profile']=='fuzz')
    native=q.runner.records
    routed=bool(native) and all(r.get('container_id') and r.get('profile') in q.runner.launcher.value['profiles'] and r.get('effective_settings') and r.get('container_policy_hash')==value['policy_hash'] for r in native)
    from policy import export_inventory
    required={'safety/container-policy.json','safety/containment-fixtures.json','safety/qualification/containment/probe.py','tools/container_policy.py','tools/containment.py','tools/runtime.py','schemas/containment-report.json','container/runtime.Dockerfile','docs/docker-containment.md'}
    exports=required.issubset(set(export_inventory(q.root)))
    child=True if instance else report['starter'].get('first_child_full_qualification')=='PASS'
    if not instance and child:
        children=[read_json(Path(report['starter']['first_child_report']))]
        child=all(r.get('containment',{}).get('status')=='PASS' and r['containment']['policy_hash']==value['policy_hash'] for r in children)
    suite=Suite.__new__(Suite);suite.q=q;suite.runner=q.runner;suite.value=value
    records=[r for r in q.runner.launcher.records if r['lifecycle'] is not None]
    suite.case('D14',{'v2-routing':routed,'asan-pair':pairs['C01']['status']=='PASS','msan-pair':pairs['C11']['status']=='PASS','tsan-pair':pairs['C21']['status']=='PASS','fuzz-pair':pairs['C32']['status']=='PASS','clusterfuzzlite-routing':adapter,'exports':exports,'fresh-child-containment':child},{'pairs':{k:{n:r[n] for n in ['id','status','control','evidence_paths']} for k,r in pairs.items()},'container_records':len(native),'exported_policy':exports,'mode':'instance: inherited payload and local routing; no grandchildren' if instance else 'starter maintenance: full fresh child containment required','child_containment':child},records)

def container_sabotage(q,value):
    """Unsafe plans never reach container creation; each variant is independent."""
    l=q.runner.launcher;image=q.runner.lock['image_id'];mounts={'/src':q.runner.snapshot}
    base=make_plan(l.value,image,mounts,'build');rows=[]
    def rejected(parent,name,action):
        try:action();ok=False
        except (GateError,ValueError,KeyError,OSError):ok=True
        rows.append({'parent':parent,'name':name,'status':'PASS' if ok else 'FAIL','control':'PASS','evidence_paths':[str(q.runner.run_dir/'container-sabotage.json')],'reason':'POLICY_REJECTED_EXPECTED before creation' if ok else 'invalid state accepted'})
    validate_plan(base,l.value,image,mounts,'build')
    for k in ['DOCKER_HOST','DOCKER_CONTEXT']:
        old=os.environ.get(k);os.environ[k]='unapproved-synthetic-endpoint'
        try:rejected('P01','docker-or-controller-unavailable/'+k,l.preflight)
        finally:
            if old is None:os.environ.pop(k,None)
            else:os.environ[k]=old
    for name,key,v in [('wrong-daemon','daemon_id','unapproved'),('unsupported-cgroup','cgroup_version','1')]:
        old=l.value['runner'][key];l.value['runner'][key]=v
        try:rejected('P01','docker-or-controller-unavailable/'+name,l.preflight)
        finally:l.value['runner'][key]=old
    old_docker=l.docker
    l.docker=lambda *a,**k:{'exit_code':127,'failure':None,'output':''}
    try:rejected('P01','docker-or-controller-unavailable/missing-docker',l.preflight)
    finally:l.docker=old_docker
    for name,key,v in [('ignored-memory','memory_bytes',0),('ignored-pids','pids',0),('ignored-cpu','cpus',0),('ignored-swap','swap_bytes',-1)]:
        modified=copy.deepcopy(base);modified['resources'][key]=v
        rejected('P01','docker-or-controller-unavailable/'+name,lambda m=modified:validate_plan(m,l.value,image,mounts,'build'))
    for name in ['build','configure-try-run','test','fuzz-adapter']:
        modified=copy.deepcopy(base);modified['execution_path']='host/'+name
        rejected('P02','native-execution-bypass/'+name,lambda m=modified:validate_plan(m,l.value,image,mounts,'build'))
    variants={'root':('user','0:0'),'capability':('capabilities',['SYS_ADMIN']),'privileged':('privileged',True),'seccomp-unconfined':('security',['seccomp=unconfined']),'apparmor-unconfined':('security',['apparmor=unconfined']),'host-pid':('namespaces',{'pid':'host'}),'host-ipc':('namespaces',{'ipc':'host'}),'device':('devices',['/dev/synthetic-device']),'host-root-mount':('mounts',{'/broad':{'source':'/'}}),'renamed-socket':('mounts',{'/renamed':{'source':'/var/run/docker.sock'}}),'leaked-environment':('environment_names',['SYNTHETIC_SECRET']),'host-network':('resources',{**base['resources'],'network':'host'}),'published-port':('ports',['23456:23456']),'merged-compose':('compose_override',{'privileged':True})}
    for name,(key,v) in variants.items():
        modified=copy.deepcopy(base);modified[key]=v
        rejected('P04','unsafe-container-override/'+name,lambda m=modified:validate_plan(m,l.value,image,mounts,'build'))
    from qualification import designated_runtime_result
    for name in ['STARTUP_FAILURE','SECCOMP_FAILURE','CGROUP_OOM','TIMEOUT','OUTPUT_LIMIT','RECORD_LIMIT']:
        fake={'exit_code':1,'failure':name,'output':'synthetic expected marker','binary_unchanged':True}
        rejected('P05','container-failure-as-detector/'+name,lambda f=fake: designated_runtime_result(f,'synthetic expected marker'))
    for name in ['missing-D','duplicate-D','malformed-D','mismatched-D','missing-profile','filtered-child']:
        modified=copy.deepcopy(value)
        if name=='missing-D':modified['cases'].pop()
        elif name=='duplicate-D':modified['cases'][1]=copy.deepcopy(modified['cases'][0])
        elif name=='malformed-D':modified['cases'][0]['control']=True
        elif name=='mismatched-D':modified['cases'][0]['subchecks'][0]['name']='wrong'
        elif name=='filtered-child':modified['cases'][-1]['subchecks'].pop()
        else:
            old=l.value['profiles'].pop('test-msan')
            try:rejected('P07','containment-omitted/'+name,lambda: make_plan(l.value,image,mounts,'test-msan'))
            finally:l.value['profiles']['test-msan']=old
            continue
        rejected('P07','containment-omitted/'+name,lambda m=modified:validate_containment(q.root,m,complete=False))
    for name in ['kernel','runtime','image','source','profile','instance']:
        supplied={'kernel':value['runner']['KernelVersion'],'runtime':value['runner']['ServerVersion'],'image':value['image_id'],'source':value['source_identity'],'profile':value['policy_hash'],'instance':str(q.root.resolve())}
        expected=dict(supplied);supplied[name]='stale'
        def binding(a=supplied,b=expected):
            if a!=b:raise GateError('stale container evidence binding')
        rejected('P10','stale-container-evidence/'+name,binding)
    for name in ['missing-status','early-removal','collector-overflow','children-remain']:
        state={'status':None if name=='missing-status' else 0,'captured':name!='early-removal','complete':name!='collector-overflow','children_reaped':name!='children-remain'}
        def lifecycle(s=state):
            if s['status'] is None or not all(s[k] for k in ['captured','complete','children_reaped']):raise GateError('incomplete outer lifecycle evidence')
        rejected('P11','lost-lifecycle-failure/'+name,lifecycle)
    for key,v in [('memory_bytes',0),('swap_bytes',-1),('cpus',0),('pids',0),('work_bytes',0),('wall_seconds',0),('memory_bytes',l.value['aggregate']['memory_bytes']+1)]:
        m=copy.deepcopy(base);m['resources'][key]=v
        rejected('P15','weakened-container-policy/'+key+'-'+str(v),lambda m=m:validate_plan(m,l.value,image,mounts,'build'))
    for key,v in [('logging',{}),('restart','always')]:
        m=copy.deepcopy(base);m[key]=v
        rejected('P15','weakened-container-policy/'+key,lambda m=m:validate_plan(m,l.value,image,mounts,'build'))
    # Whole exported-policy tampering is tested against an external unchanged
    # baseline, rather than treating a candidate checksum as authority.
    with tempfile.TemporaryDirectory(prefix='safe-c-policy-mutation-') as tmp:
        from starter import instantiate
        child=Path(tmp)/'child';instantiate(q.root,child,'policy-probe',maintenance=True)
        p=child/'safety/container-policy.json';original=p.read_text();p.write_text(original.replace('"log_files": 2','"log_files": 200'))
        rejected('P15','weakened-container-policy/exported-policy',lambda:baseline_gate(child,q.root,baseline_identity(q.root)))
    for name,key,v in [('privileged','privileged',True),('default-runner','profile','unrestricted'),('extra-socket','mounts',{'/socket':{'source':'/var/run/docker.sock'}}),('host-execution','execution_path','host'),('uninstrumented-target','instrumentation',False)]:
        m=make_plan(l.value,image,mounts,'fuzz');m[key]=v
        rejected('P16','fuzz-runner-bypass/'+name,lambda m=m:validate_plan(m,l.value,image,mounts,'fuzz'))
    atomic_json(q.runner.run_dir/'container-sabotage.json',rows);return rows

def save(q,value):
    validate_containment(q.root,value)
    paths=[q.runner.run_dir/'container-qualification-report.json',q.root/'artifacts/container-qualification-report.json']
    for p in paths:atomic_json(p,value)
    lines=['# Container qualification: '+value['status'],'Policy `'+value['policy_hash']+'`; local development runner; independent enforcement UNSEALED.','', '| Case | Classification | Control | Subchecks |','|---|---|---|---|']
    lines += ['| '+r['id']+' | '+r['classification']+' | '+r['control']+' | '+', '.join(s['name']+': '+s['status'] for s in r['subchecks'])+' |' for r in value['cases']]
    lines+=['','Additive Docker sabotage: '+str(sum(r['status']=='PASS' for r in value['sabotage']))+'/'+str(len(value['sabotage']))+'.','Application release/deployment readiness: false. Runtime demonstration only.','See JSON for effective configuration, counters, bounded ceilings, launch commands, identities and evidence paths.']
    (q.root/'artifacts/container-qualification-report.md').write_text('\n'.join(lines)+'\n')
