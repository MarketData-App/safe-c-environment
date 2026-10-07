"""Protected typed Docker dispatch. No caller-supplied flags or daemon endpoints."""
from __future__ import annotations
from pathlib import Path
import fcntl
import json
import os
import re
import stat
import tempfile
import time
import uuid
from evidence import GateError, bounded, read_json, digest, file_hash, atomic_json, passed
from host_capabilities import active_lsm, context_endpoint, endpoint_problems, host_problems, inherited_problems, security_options

MIB=1024*1024
LABEL='org.safe-c.containment'
# Lifetime of a session holder (Launcher.create default command). A host watchdog
# outside this repository may `docker start` an expired holder again with an empty
# /work; verify_session refuses such a container before any reuse.
HOLDER_SECONDS=1800
SESSION_RESTARTED='session container stopped or was restarted outside the launcher'
D_IDS=[f'D{i:02}' for i in range(1,15)]

def policy(root):
    value=read_json(root/'safety/container-policy.json')
    from schema_check import validate
    validate(root,'container-policy',value)
    c=value['common'];a=value['aggregate']
    if (c['uid']<=0 or c['gid']<=0 or c['capabilities'] or not c['readonly_root'] or
        not c['no_new_privileges'] or c['seccomp']!='builtin-default' or
        c['apparmor']!='docker-default' or c['restart']!='no' or c['core_bytes']!=0 or
        c['log_driver']!='local' or any(c[k]<=0 for k in ['nofile','file_bytes','log_bytes','log_files','capture_bytes','capture_record_bytes','artifact_bytes','artifact_total_bytes','artifact_files'])):
        raise GateError('mandatory container restrictions missing')
    if any(c[k]!='private' for k in ['pid_namespace','ipc_namespace','cgroup_namespace']):
        raise GateError('host namespace requested')
    required={'acquire','build','project','dependency-build','fuzz','integration','runtime-demo','runtime','probe','probe-memory','probe-pids','probe-cpu'}|{'test-'+x for x in ['asan','ubsan','integer','msan','tsan','coverage','hardened','ordinary','strict']}
    if set(value['profiles'])!=required:raise GateError('container profile inventory mismatch')
    for name,p in value['profiles'].items():
        if any(p[k]<=0 for k in ['memory_bytes','cpus','pids','work_bytes','tmp_bytes','run_bytes','shm_bytes','work_inodes','wall_seconds']) or p['swap_bytes']!=0:
            raise GateError('container hard budget absent/unlimited')
        if p['memory_bytes']>a['memory_bytes'] or p['cpus']>a['cpus'] or p['pids']>a['pids']:
            raise GateError('container exceeds approved aggregate budget')
        network='authorized-acquisition-only' if name=='acquire' else 'project-internal' if name=='integration' else 'none'
        if p['network']!=network:raise GateError('unauthorized network policy')
    if a['resource_stress_concurrency']!=1 or a['compiler_jobs']!=2 or a['fuzz_workers']!=1:
        raise GateError('unapproved parallelism')
    return value

def policy_hash(value):return digest(json.dumps(value,sort_keys=True,separators=(',',':')).encode())

def validate_plan(plan,value, image, mounts, profile, *, lsm='apparmor'):
    expected=make_plan(value,image,mounts,profile,lsm=lsm)
    if plan!=expected:raise GateError('unsafe/missing/merged container override rejected before creation')
    return plan

def canonical_mount(path):
    path=Path(path).absolute()
    if any(p.is_symlink() for p in [path,*path.parents]):raise GateError('symlink mount rejected')
    if not path.is_dir():raise GateError('mount must be a private snapshot directory')
    path=path.resolve()
    if any(ch in str(path) for ch in [',','\n','\x00']):raise GateError('ambiguous bind mount path rejected')
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        target=Path(line.split()[4].replace('\\040',' '))
        if target!=path and target.is_relative_to(path):raise GateError('nested mount surprise rejected')
    if path in [Path('/'),Path('/home'),Path('/tmp'),Path('/var'),Path('/run'),Path.home()]:
        raise GateError('broad host mount rejected')
    # bind-recursive=disabled excludes nested source submounts. No sockets,
    # special files or links can be supplied under an alternate filename.
    count=0
    for p in path.rglob('*'):
        mode=p.lstat().st_mode
        if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):raise GateError('special/link mount input rejected')
        count+=1
        if count>10000:raise GateError('mount input inventory exceeds bound')
    return str(path)

PLAN_LSM_LABELS={'apparmor':'docker-default-apparmor','selinux':'container_t-selinux'}

def make_plan(value,image,mounts,profile,*,lsm='apparmor'):
    """lsm is the active host LSM from preflight; host-independent callers describe the AppArmor plan."""
    if lsm not in PLAN_LSM_LABELS:raise GateError('unapproved Linux security module for plan')
    if profile not in value['profiles']:raise GateError('unknown container profile')
    if not re.fullmatch(r'sha256:[0-9a-f]{64}',image):raise GateError('immutable image ID required')
    if profile in ['acquire','runtime']:raise GateError('acquisition/production execution requires separate authority')
    c=value['common'];p=value['profiles'][profile]
    if any(k not in ['/src','/inputs','/fixture'] for k in mounts):raise GateError('unapproved mount target')
    return {'schema_version':1,'profile':profile,'image_id':image,'policy_hash':policy_hash(value),
            'user':f"{c['uid']}:{c['gid']}",'root_readonly':True,'capabilities':[],
            'security':['no-new-privileges','default-seccomp',PLAN_LSM_LABELS[lsm]],
            'namespaces':{'pid':'private','ipc':'private','cgroup':'private'},
            'mounts':{k:{'source':canonical_mount(v),'readonly':True,'recursive':'disabled'} for k,v in mounts.items()},
            'resources':dict(p),'restart':'no','devices':[],'ports':[],
            'logging':{'driver':'local','max_size':c['log_bytes'],'max_files':c['log_files']},
            'ulimits':{'core':0,'nofile':c['nofile'],'fsize':c['file_bytes']},'environment_names':list(c['environment_names'])}

def kernel_limits_gate(limits,p):
    expected={'memory.max':str(p['memory_bytes']),'memory.swap.max':'0','pids.max':str(p['pids']),'cpu.max':str(int(p['cpus']*100000))+' 100000'}
    if limits!=expected:raise GateError('kernel limit missing/ignored/unlimited')
    return True

def dispatch_gate(record):
    if (record.get('execution_path')!='docker' or not record.get('container_id') or
        not record.get('effective') or record.get('lifecycle') is not None or
        record.get('profile')!=record.get('plan',{}).get('profile')):
        raise GateError('native execution bypass or unrecorded dispatch rejected')
    return True

def completion_gate(outcome,lifecycle):
    if type(outcome.get('exit_code')) is not int:raise GateError('workload status lost')
    if not lifecycle.get('state_before') or not lifecycle.get('removed') or not lifecycle.get('children_reaped') or lifecycle.get('state_after',{}).get('Pid')!=0:
        raise GateError('workload lifecycle evidence incomplete')
    if outcome.get('failure') is None and outcome.get('evidence_complete') is not True:
        raise GateError('collector overflow/incomplete evidence cannot become success')
    return True

class Launcher:
    def __init__(self,root,run_dir,lock,*,purpose='qualification'):
        if purpose not in {'qualification','development','project'}:raise GateError('unregistered container purpose')
        self.root=Path(root);self.run_dir=Path(run_dir);self.lock=lock;self.value=policy(self.root)
        self.purpose=purpose
        self.worktree_scope=__import__('hashlib').sha256(str(self.root.resolve()).encode()).hexdigest()
        self.runner_identity=None
        self.info=None;self.endpoint=None;self.prefix=None;self.daemon_id=None
        self.config=Path(tempfile.mkdtemp(prefix='safe-c-docker-config-'))
        self.env={'PATH':'/usr/bin:/bin','HOME':str(self.config),'LANG':'C.UTF-8'}
        self.records=[]
        self.approved_runtime_images=set()
    def image_gate(self,profile,image):
        if profile=='runtime-demo':
            if image not in self.approved_runtime_images:raise GateError('runtime image has not been assembled and approved by the trusted adapter')
        elif image!=self.lock['image_id']:raise GateError('unapproved workload image rejected before creation')
        return True
    def inspect_context(self):
        r=bounded(['/usr/bin/docker','context','inspect'],timeout=15,limit=65536)
        if not passed(r):raise GateError('active Docker context unavailable')
        try:rows=json.loads(r['output'])
        except ValueError as exc:raise GateError('active Docker context unreadable') from exc
        if not isinstance(rows,list) or len(rows)!=1 or not isinstance(rows[0],dict):raise GateError('active Docker context ambiguous')
        return rows[0]
    def connect(self):
        """Resolve the active local Unix endpoint before any daemon is contacted."""
        inherited=inherited_problems(os.environ)
        if inherited:raise GateError('host capability check failed: '+'; '.join(inherited))
        context=self.inspect_context()
        problems=endpoint_problems(context,os.environ)
        if problems:raise GateError('host capability check failed: '+'; '.join(problems))
        endpoint=context_endpoint(context)
        # The first resolved endpoint is bound for this Launcher's lifetime, so
        # admission, creation and disposal all address one daemon.
        if self.endpoint is not None and endpoint!=self.endpoint:raise GateError('host capability check failed: daemon or endpoint changed during the run')
        self.endpoint=endpoint
        self.prefix=['/usr/bin/docker','--config',str(self.config),'--host',self.endpoint]
        return context
    def qualify_host(self):
        context=self.connect()
        info=self.json(['info','--format','{{json .}}'])
        if not info.get('ID'):raise GateError('host capability check failed: daemon identity unavailable')
        if self.daemon_id is not None and info.get('ID')!=self.daemon_id:raise GateError('host capability check failed: daemon or endpoint changed during the run')
        enforcing=self.read_selinux_enforcing() if active_lsm(info)=='selinux' else None
        problems=host_problems(info,context,os.environ,self.read_core_pattern(),enforcing)
        if problems:raise GateError('host capability check failed: '+'; '.join(problems))
        self.daemon_id=info.get('ID');self.info=info
        return info,context
    @staticmethod
    def read_core_pattern():return Path('/proc/sys/kernel/core_pattern').read_text()
    @staticmethod
    def read_selinux_enforcing():
        try:return Path('/sys/fs/selinux/enforce').read_text().strip()=='1'
        except OSError:return None
    def host_info(self):
        if self.info is None:self.qualify_host()
        return self.info
    def docker(self,args,**kw):
        if self.prefix is None:self.connect()
        return bounded(self.prefix+list(args),env=self.env,**kw)
    def reap_scope(self,scope,*,seconds=120,poll=5,quiet_polls=2,clock=None,sleep=None):
        """Dispose every containment container labelled with worktree `scope` after its
        controller was killed (a child TIMEOUT). Nothing else will dispose them, so they
        are killed and removed at once (running or stopped), never restarted; the scope
        is then polled for up to `seconds` and anything that reappears is removed again
        until it stays empty for `quiet_polls` polls.
        Returns {'waited_seconds','removed','remaining'}."""
        import time as _time
        clock=clock or _time.monotonic;sleep=sleep or _time.sleep
        if not re.fullmatch(r'[0-9a-f]{64}',scope or ''):raise GateError('container scope must be a worktree digest')
        def ids():
            r=self.docker(['ps','-aq','--filter','label='+LABEL+'=1','--filter','label=org.safe-c.worktree='+scope],timeout=15)
            if not passed(r):raise GateError('child container inventory unavailable')
            return r['output'].split()
        started=clock();removed=[];quiet=0;current=ids()
        while True:
            for cid in current:
                self.docker(['kill',cid],timeout=15)
                if passed(self.docker(['rm','--force',cid],timeout=15)) and cid not in removed:removed.append(cid)
            quiet=quiet+1 if not current else 0
            if quiet>=quiet_polls or clock()-started>=seconds:break
            sleep(poll);current=ids()
        return {'waited_seconds':round(clock()-started,1),'removed':removed,'remaining':ids()}
    def json(self,args):
        r=self.docker(args)
        if not passed(r):raise GateError('Docker API command failed: '+str(args[:2]))
        return json.loads(r['output'])
    def preflight(self):
        info,context=self.qualify_host();expected=self.value['runner']
        if (expected['role']!='portable' or expected['endpoint_scheme']!='unix' or expected['architecture']!='x86_64' or
                expected['cgroup_version']!='2' or active_lsm(info) not in expected['lsm']):raise GateError('unapproved production/remote/emulated runner')
        security=info['SecurityOptions']
        image=self.json(['image','inspect',self.lock['image_id']])[0]
        cfg=image['Config']
        if image['Size']>self.value['aggregate']['owned_image_bytes']:raise GateError('retained toolchain-image storage exceeds approved project bound')
        if image['Id']!=self.lock['image_id'] or cfg.get('Volumes') or cfg.get('Healthcheck') or cfg.get('Entrypoint'):raise GateError('unexpected toolchain image runtime metadata')
        core=Path('/proc/sys/kernel/core_pattern').read_text().strip()
        if core.startswith('|'):raise GateError('piped host core handling requires independent operator review')
        runtime=info.get('Runtimes',{}).get(info['DefaultRuntime'],{}).get('status',{})
        features=json.loads(runtime.get('org.opencontainers.runtime-spec.features','{}'))
        annotations=features.get('annotations',{})
        self.runner_identity={k:info.get(k) for k in ['ID','Name','ServerVersion','KernelVersion','OperatingSystem','Architecture','NCPU','MemTotal','CgroupDriver','CgroupVersion','SecurityOptions','Driver','DefaultRuntime']}
        self.runner_identity.update(endpoint=self.endpoint,role=expected['role'],lsm=active_lsm(info),rootless=any('rootless' in x for x in security),runtime_annotations=annotations,controllers=Path('/sys/fs/cgroup/cgroup.controllers').read_text().split(),core_pattern=core)
        return self.runner_identity
    def admission(self,plan,finite_memory=0):
        a=self.value['aggregate'];p=plan['resources']
        ids=self.docker(['ps','-aq','--filter','label='+LABEL+'=1'])
        if not passed(ids):raise GateError('active-job admission unavailable')
        rows=self.json(['inspect',*ids['output'].split()]) if ids['output'].split() else []
        active=[r for r in rows if r['State']['Running']]
        if len(active)>=a['max_active']:raise GateError('aggregate concurrency budget exhausted')
        for field,key,convert in [('Memory','memory_bytes',1),('NanoCpus','cpus',1e-9),('PidsLimit','pids',1)]:
            if sum(r['HostConfig'][field]*convert for r in active)+p[key]>a[key]:raise GateError('aggregate '+key+' reservation exhausted')
        available=int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:')))*1024
        if available<a['reserved_memory_bytes']+max(p['memory_bytes'],finite_memory):raise GateError('insufficient independent finite-probe memory headroom')
        free=os.statvfs(self.run_dir).f_bavail*os.statvfs(self.run_dir).f_frsize
        if free<a['reserved_disk_bytes']+self.value['common']['artifact_total_bytes']:raise GateError('insufficient collector/daemon disk admission headroom')
        files=list((self.root/'artifacts').rglob('*'))
        sizes=[x.stat().st_size for x in files if x.is_file() and not x.is_symlink()]
        if len(sizes)>a['evidence_files'] or sum(sizes)>a['evidence_bytes']:raise GateError('evidence retention budget exhausted; archive owned prior evidence')
        return {'active_before':len(active),'available_memory_bytes':available,'reserved_memory_bytes':a['reserved_memory_bytes'],'finite_probe_memory_bytes':finite_memory,'disk_free_bytes':free,'retained_evidence_bytes':sum(sizes),'max_active':a['max_active']}
    def create(self,profile,mounts, *,image=None,network=None,command=None,finite_memory=0):
        self.preflight()
        image=image or self.lock['image_id'];self.image_gate(profile,image);lsm=active_lsm(self.info);plan=make_plan(self.value,image,mounts,profile,lsm=lsm)
        validate_plan(plan,self.value,image,mounts,profile,lsm=lsm)
        if network is not None and (profile!='integration' or not network.startswith('safe-c-integration-')):raise GateError('unauthorized test network')
        if profile=='integration' and not network:raise GateError('integration requires a disposable internal network')
        c=self.value['common'];p=plan['resources'];name='safe-c-'+uuid.uuid4().hex
        argv=['create','--pull=never','--name',name,'--label',LABEL+'=1','--label','org.safe-c.profile='+profile,'--label','org.safe-c.source='+file_hash(self.root/'safety/contract.json'),
              '--label','org.safe-c.purpose='+self.purpose,'--label','org.safe-c.worktree='+self.worktree_scope,
              '--label','org.safe-c.run='+self.run_dir.name,
              '--network',network or 'none','--read-only','--cap-drop=ALL',*['--security-opt='+o for o in security_options(self.info)],
              '--ipc=private','--cgroupns=private','--restart=no','--user',plan['user'],
              '--memory',str(p['memory_bytes']),'--memory-swap',str(p['memory_bytes']),
              '--cpus',str(p['cpus']),'--pids-limit',str(p['pids']),
              '--ulimit','core=0:0','--ulimit',f"nofile={c['nofile']}:{c['nofile']}",'--ulimit',f"fsize={c['file_bytes']}:{c['file_bytes']}",
              '--log-driver=local','--log-opt','max-size='+str(c['log_bytes']),'--log-opt','max-file='+str(c['log_files']),'--log-opt','compress=false','--shm-size',str(p['shm_bytes']),
              '--tmpfs',f"/tmp:rw,nosuid,nodev,noexec,size={p['tmp_bytes']},uid={c['uid']},gid={c['gid']}",
              '--tmpfs',f"/run:rw,nosuid,nodev,noexec,size={p['run_bytes']},uid={c['uid']},gid={c['gid']}",
              '--tmpfs',f"/work:rw,nosuid,nodev,exec,size={p['work_bytes']},nr_inodes={p['work_inodes']},uid={c['uid']},gid={c['gid']}",
              '--workdir=/work']
        for key,v in c['fixed_environment'].items():argv+=['--env',key+'='+v]
        for target,m in plan['mounts'].items():argv+=['--mount',f"type=bind,src={m['source']},dst={target},readonly,bind-recursive=disabled"]
        argv+=[image,*(command or ['python3','-c','import time; time.sleep(1800)'])]
        # Cross-process admission and creation are one short critical section.
        fd=os.open('/tmp/safe-c-containment-admission-'+str(os.getuid()),os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        try:
            fcntl.flock(fd,fcntl.LOCK_EX)
            reservation=self.admission(plan,finite_memory)
            r=self.docker(argv)
            if not passed(r):raise GateError('protected container creation failed')
            container=r['output'].strip()
            start=self.docker(['start',container])
            if not passed(start):self.docker(['rm','--force',container]);raise GateError('protected container startup failed')
            record={'container_id':container,'name':name,'profile':profile,'plan':plan,'policy_hash':plan['policy_hash'],'runner':self.runner_identity,'reservation':reservation,'create_command':self.prefix[:1]+['--host',self.endpoint]+argv,'effective':None,'lifecycle':None,'execution_path':'docker'}
            self.records.append(record)
        finally:os.close(fd)
        if command is None:
            try:record['effective']=self.effective(container,plan)
            except Exception:
                self.dispose(record);raise
        return record
    def effective(self,container,plan,python_probe=True):
        obj=self.json(['inspect',container])[0];h=obj['HostConfig'];cfg=obj['Config'];p=plan['resources']
        checks=[obj['Image']==plan['image_id'],cfg['User']==plan['user'],h['ReadonlyRootfs'],h['CapDrop']==['ALL'],not h.get('CapAdd'),not h['Privileged'],not h['Devices'],not h['DeviceRequests'],h['NetworkMode']!='host',h['PidMode']=='',h['IpcMode']=='private',h['CgroupnsMode']=='private',h['RestartPolicy']['Name']=='no',h['Memory']==p['memory_bytes'],h['MemorySwap']==p['memory_bytes'],h['NanoCpus']==int(p['cpus']*1e9),h['PidsLimit']==p['pids'],h['LogConfig']=={'Type':'local','Config':{'max-size':str(self.value['common']['log_bytes']),'max-file':str(self.value['common']['log_files']),'compress':'false'}},sorted(h['SecurityOpt'])==sorted(security_options(self.host_info())),(obj['AppArmorProfile']=='docker-default' if active_lsm(self.host_info())=='apparmor' else ':container_t:' in obj.get('ProcessLabel','')),not cfg.get('Volumes'),not cfg.get('Healthcheck'),not h.get('PortBindings'),not h.get('ExtraHosts')]
        if not all(checks):raise GateError('effective Docker settings mismatch')
        c=self.value['common']
        expected_tmpfs={'/tmp':f"rw,nosuid,nodev,noexec,size={p['tmp_bytes']},uid={c['uid']},gid={c['gid']}",'/run':f"rw,nosuid,nodev,noexec,size={p['run_bytes']},uid={c['uid']},gid={c['gid']}",'/work':f"rw,nosuid,nodev,exec,size={p['work_bytes']},nr_inodes={p['work_inodes']},uid={c['uid']},gid={c['gid']}"}
        actual_ulimits={x['Name']:(x['Soft'],x['Hard']) for x in h['Ulimits']}
        if h['Tmpfs']!=expected_tmpfs or h['ShmSize']!=p['shm_bytes'] or actual_ulimits!={'core':(0,0),'nofile':(c['nofile'],c['nofile']),'fsize':(c['file_bytes'],c['file_bytes'])} or h.get('GroupAdd'):
            raise GateError('effective writable mounts/ulimits/groups differ')

        if p['network']=='none' and h['NetworkMode']!='none':raise GateError('effective network mismatch')
        # The host-side /proc and /sys/fs/cgroup reads below (workload cgroup and
        # namespace comparison) are the locality proof for the unix-socket endpoint:
        # they succeed only when the daemon runs the workload on this kernel.
        if len(obj['Mounts'])!=len(plan['mounts']) or any(m['RW'] or m['Destination'] not in plan['mounts'] or m['Source']!=plan['mounts'][m['Destination']]['source'] for m in obj['Mounts']):raise GateError('unexpected effective bind mounts')
        pid=obj['State']['Pid']
        paths=Path(f'/proc/{pid}/cgroup').read_text().splitlines()
        unified=[line.split(':',2)[2] for line in paths if line.startswith('0::')]
        if len(unified)!=1:raise GateError('actual workload cgroup unresolved')
        cg=Path('/sys/fs/cgroup')/unified[0].lstrip('/')
        limits={k:(cg/k).read_text().strip() for k in ['memory.max','memory.swap.max','pids.max','cpu.max']}
        kernel_limits_gate(limits,p)
        if python_probe:
            probe=self.docker(['exec',container,'python3','-c','import os,json,pathlib,resource; s=pathlib.Path("/proc/self/status").read_text(); print(json.dumps({"uid":os.getuid(),"gid":os.getgid(),"status":{x.split(":")[0]:x.split(":")[1].strip() for x in s.splitlines() if x.startswith(("CapEff:","CapBnd:","NoNewPrivs:","Seccomp:","Groups:"))},"limits":{k:pathlib.Path("/sys/fs/cgroup",k).read_text().strip() for k in ["memory.max","memory.swap.max","pids.max","cpu.max"]},"namespaces":{k:os.readlink("/proc/self/ns/"+k) for k in ["pid","net","ipc","mnt","cgroup"]},"compute":sum(range(10)),"apparmor_active":pathlib.Path("/proc/self/attr/current").read_text().strip(),"scratch":{k:{"bytes":os.statvfs(k).f_blocks*os.statvfs(k).f_frsize,"inodes":os.statvfs(k).f_files} for k in ["/work","/tmp","/run","/dev/shm"]},"ulimits":{k:resource.getrlimit(v) for k,v in {"core":resource.RLIMIT_CORE,"nofile":resource.RLIMIT_NOFILE,"fsize":resource.RLIMIT_FSIZE,"address":resource.RLIMIT_AS}.items()},"mount_inventory":[x for x in pathlib.Path("/proc/self/mountinfo").read_text().splitlines() if x.split()[4] in ["/","/work","/tmp","/run","/dev/shm","/src","/inputs","/fixture"]]}))'])
            if not passed(probe):raise GateError('harmless in-container capability probe failed')
            inside=json.loads(probe['output'])
        else:
            status={x.split(':',1)[0]:x.split(':',1)[1].strip() for x in Path(f'/proc/{pid}/status').read_text().splitlines() if ':' in x}
            logs=self.docker(['logs',container],timeout=5)
            namespaces=dict(re.findall(r'^namespace (pid|net|ipc|mnt|cgroup)=(.+)$',logs['output'],re.M))
            if not passed(logs) or set(namespaces)!={'pid','net','ipc','mnt','cgroup'}:raise GateError('runtime self-observed namespace interface incomplete')
            inside={'uid':int(status['Uid'].split()[0]),'gid':int(status['Gid'].split()[0]),'status':{k:status[k] for k in ['CapEff','CapBnd','NoNewPrivs','Seccomp','Groups']},'limits':limits,'namespaces':namespaces,'runtime_health_observed':'runtime-demo healthy sum=9' in logs['output']}
        s=inside['status'];c=self.value['common']
        if inside['uid']!=c['uid'] or inside['gid']!=c['gid'] or int(s['CapEff'],16) or int(s['CapBnd'],16) or s['NoNewPrivs']!='1' or s['Seccomp']!='2' or inside['limits']!=limits or (inside.get('compute')!=45 if python_probe else not inside['runtime_health_observed']):raise GateError('in-container control verification failed')
        if python_probe:
            lsm=active_lsm(self.host_info())
            if (inside['apparmor_active']!='docker-default (enforce)' if lsm=='apparmor' else ':container_t:' not in inside['apparmor_active']):raise GateError('active Linux security module enforcement mismatch')
            if any(inside['scratch'][path]['bytes']!=p[key] for path,key in [('/work','work_bytes'),('/tmp','tmp_bytes'),('/run','run_bytes'),('/dev/shm','shm_bytes')]) or inside['scratch']['/work']['inodes']!=p['work_inodes']:raise GateError('scratch byte/inode hard boundary not effective')
            expected_ulimits={'core':[0,0],'nofile':[c['nofile'],c['nofile']],'fsize':[c['file_bytes'],c['file_bytes']],'address':[-1,-1]}
            if inside['ulimits']!=expected_ulimits:raise GateError('effective ulimits mismatch or sanitizer address-space cap')
            mounts={line.split()[4]:line.split()[5].split(',') for line in inside['mount_inventory']}
            if 'ro' not in mounts['/'] or any(not {'nosuid','nodev','noexec'}.issubset(set(mounts[k])) for k in ['/tmp','/run','/dev/shm']) or not {'nosuid','nodev'}.issubset(set(mounts['/work'])) or 'noexec' in mounts['/work']:raise GateError('effective scratch/root mount restrictions differ')
        groups=s['Groups'].split()
        if any(int(x)!=c['gid'] for x in groups):raise GateError('unnecessary supplementary groups')
        if any(inside['namespaces'][k]==os.readlink('/proc/self/ns/'+k) for k in ['pid','net','ipc','mnt','cgroup']):raise GateError('host namespace sharing')
        return {'inspect':{'host_config':h,'image_id':obj['Image'],'user':cfg['User'],'apparmor':obj['AppArmorProfile'],'mounts':obj['Mounts'],'state':obj['State'],'network':obj['NetworkSettings']['Networks']},'cgroup_path':str(cg),'limits':limits,'inside':inside,'events_before':self.counters(cg)}
    @staticmethod
    def counters(cg):
        return {k:(Path(cg)/k).read_text().strip() for k in ['memory.events','pids.events','cpu.stat','memory.current','pids.current','memory.peak','pids.peak'] if (Path(cg)/k).exists()}
    def execute(self,record,args,*,timeout,env=None,limit=None):
        dispatch_gate(record)
        p=record['plan']['resources'];c=self.value['common']
        if limit is not None and (type(limit) is not int or not 0<limit<=c['capture_bytes']):raise GateError('unapproved output capture budget')
        if timeout<=0 or timeout>p['wall_seconds']:raise GateError('job deadline exceeds protected profile')
        env=env or {}
        if any(k not in c['environment_names'] or not isinstance(v,str) or '\x00' in v for k,v in env.items()):raise GateError('unapproved workload environment')
        self.verify_session(record)
        argv=['exec','--workdir=/work']
        for k,v in env.items():argv+=['--env',k+'='+v]
        argv+=[record['container_id'],*args]
        result=self.docker(argv,timeout=timeout,limit=limit or c['capture_bytes'])
        if any(len(line)>c['capture_record_bytes'] for line in result['output'].splitlines()):result['failure']='RECORD_LIMIT';result['evidence_complete']=False
        result.update(container_id=record['container_id'],profile=record['profile'],container_policy_hash=record['policy_hash'],effective_settings=record['effective'],runner_identity=self.runner_identity)
        if result['failure']:self.dispose(record)
        return result
    def verify_session(self,record):
        """Refuse an existing container unless it still runs the process the launcher
        started: Running, not paused/restarting, State.StartedAt equal to the value
        recorded by effective() at creation, and RestartCount 0. A refused container is
        disposed (best effort; close() retries) and never reused."""
        expected=((record.get('effective') or {}).get('inspect') or {}).get('state') or {}
        r=self.docker(['inspect',record['container_id']],timeout=15)
        ok=False
        if passed(r) and expected.get('StartedAt'):
            try:rows=json.loads(r['output'])
            except ValueError:rows=None
            if isinstance(rows,list) and len(rows)==1 and isinstance(rows[0],dict):
                state=rows[0].get('State') or {}
                ok=(state.get('Running') is True and state.get('Paused') is False and state.get('Restarting') is False and
                    state.get('StartedAt')==expected['StartedAt'] and rows[0].get('RestartCount')==0)
        if not ok:
            try:self.dispose(record)
            except (GateError,ValueError,KeyError,IndexError,TypeError,OSError):pass
            raise GateError(SESSION_RESTARTED)
        return True
    def dispose(self,record):
        if record['lifecycle'] is not None:return record['lifecycle']
        obj=self.json(['inspect',record['container_id']])[0]
        before=dict(obj['State']);events={}
        if record['effective']:events=self.counters(record['effective']['cgroup_path'])
        if obj['State']['Running']:self.docker(['kill',record['container_id']],timeout=15)
        after=self.json(['inspect',record['container_id']])[0]['State']
        removed=self.docker(['rm','--force',record['container_id']],timeout=15)
        exists=self.docker(['inspect',record['container_id']],timeout=15)
        record['lifecycle']={'state_before':before,'state_after':after,'counters_after':events,'removed':passed(removed) and not passed(exists),'children_reaped':not after['Running'] and after['Pid']==0}
        if not record['lifecycle']['removed'] or not record['lifecycle']['children_reaped']:raise GateError('workload cleanup incomplete')
        atomic_json(self.run_dir/('container-'+record['container_id'][:12]+'.json'),record)
        return record['lifecycle']
    def close(self):
        import shutil
        for record in self.records:
            if record['lifecycle'] is None:self.dispose(record)
        shutil.rmtree(self.config,ignore_errors=True)
