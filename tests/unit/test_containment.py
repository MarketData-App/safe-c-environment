"""Fail-closed evidence and dispatch tests, without unsafe Docker launches."""
import copy
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools'))
from evidence import GateError,read_json
from container_policy import Launcher,policy,make_plan,validate_plan,kernel_limits_gate,dispatch_gate,completion_gate,policy_hash
from containment import fixture_inventory,validate_containment,container_binding_gate,expected_binding
from qualification import designated_runtime_result
ROOT=Path(__file__).resolve().parents[2]

class ContainerEvidenceTests(unittest.TestCase):
    def setUp(self):self.value=policy(ROOT);self.image=read_json(ROOT/'toolchain.lock.json')['image_id']
    def test_unapproved_images_are_rejected_before_creation(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            launcher=Launcher(ROOT,Path(d),read_json(ROOT/'toolchain.lock.json'))
            try:
                launcher.image_gate('build',self.image)
                for profile,image in [('build','sha256:'+'0'*64),('fuzz','sha256:'+'0'*64),('runtime-demo',self.image)]:
                    with self.assertRaises(GateError):launcher.image_gate(profile,image)
            finally:launcher.close()
    def test_profile_request_rejects_merged_overrides(self):
        good=make_plan(self.value,self.image,{},'build');validate_plan(good,self.value,self.image,{},'build')
        for key,value in [('user','0:0'),('capabilities',['SYS_ADMIN']),('privileged',True),('ports',['123:123']),('logging',{}),('restart','always')]:
            bad=copy.deepcopy(good);bad[key]=value
            with self.assertRaises(GateError):validate_plan(bad,self.value,self.image,{},'build')
    def test_ignored_runtime_controls_fail_actual_limit_gate(self):
        p=self.value['profiles']['build'];good={'memory.max':str(p['memory_bytes']),'memory.swap.max':'0','pids.max':str(p['pids']),'cpu.max':'200000 100000'}
        kernel_limits_gate(good,p)
        for key in good:
            bad=dict(good);bad[key]='max'
            with self.assertRaises(GateError):kernel_limits_gate(bad,p)
    def test_host_or_missing_dispatch_is_rejected(self):
        good={'execution_path':'docker','container_id':'recorded','effective':{'limits':'verified'},'lifecycle':None,'profile':'build','plan':{'profile':'build'}};dispatch_gate(good)
        for key,v in [('execution_path','host'),('container_id',None),('effective',None),('lifecycle',{}),('profile','unrecorded')]:
            bad=copy.deepcopy(good);bad[key]=v
            with self.assertRaises(GateError):dispatch_gate(bad)
    def test_masked_capture_and_missing_lifecycle_cannot_pass(self):
        good={'exit_code':0,'failure':None,'evidence_complete':True};life={'state_before':{'Running':True},'state_after':{'Pid':0},'removed':True,'children_reaped':True};completion_gate(good,life)
        for key,v in [('exit_code',None),('exit_code',False),('evidence_complete',False)]:
            bad=dict(good);bad[key]=v
            with self.assertRaises(GateError):completion_gate(bad,life)
        for key,v in [('state_before',{}),('removed',False),('children_reaped',False),('state_after',{'Pid':123})]:
            bad=copy.deepcopy(life);bad[key]=v
            with self.assertRaises(GateError):completion_gate(good,bad)
    def test_runtime_failure_cannot_become_designated_detection(self):
        good={'exit_code':1,'failure':None,'output':'designated-marker'};designated_runtime_result(good,'designated-marker')
        for failure in ['STARTUP_FAILURE','SECCOMP_FAILURE','CGROUP_OOM','PID_LIMIT','TIMEOUT','OUTPUT_LIMIT','RECORD_LIMIT']:
            bad=dict(good);bad['failure']=failure
            with self.assertRaises(GateError):designated_runtime_result(bad,'designated-marker')
        for code in [None,False,0]:
            bad=dict(good);bad['exit_code']=code
            with self.assertRaises(GateError):designated_runtime_result(bad,'designated-marker')
    def report(self):
        spec=fixture_inventory(ROOT);runner={'KernelVersion':'kernel','ServerVersion':'runtime','ID':'daemon'};binding=expected_binding(ROOT,runner,self.image,self.value)
        return {'schema_version':1,'status':'PASS','source_identity':binding['source'],'instance_identity':binding['instance'],'policy_hash':binding['profile'],'image_id':self.image,'runner':runner,'cases':[{'id':r['id'],'status':'PASS','control':'PASS','classification':'CONTAINED_EXPECTED','subchecks':[{'name':n,'status':'PASS'} for n in r['subchecks']],'observations':{'test_control':'schema-only'},'evidence_paths':['schema-only-path'],'reproduce':r['reproduce']} for r in spec['cases']],'runtime_demo':{},'storage_scope':{},'sabotage':[{**r,'status':'PASS','control':'PASS','evidence_paths':['schema-only-path'],'reason':'schema-only positive control'} for r in spec['sabotage_variants']],'application_release_ready':False,'independent_enforcement':'UNSEALED','remote_ci_execution':'NOT_RUN','production_approval':'NOT_REQUESTED'}
    def test_D_accounting_rejects_missing_duplicate_and_control_free_results(self):
        good=self.report();validate_containment(ROOT,good)
        for mode in ['missing','duplicate','missing-control','missing-evidence','missing-subcheck','mismatched-subcheck','missing-sabotage','duplicate-sabotage','malformed']:
            bad=copy.deepcopy(good)
            if mode=='missing':bad['cases'].pop()
            elif mode=='duplicate':bad['cases'][1]=copy.deepcopy(bad['cases'][0])
            elif mode=='missing-control':bad['cases'][0]['control']='BLOCKED'
            elif mode=='missing-evidence':bad['cases'][0]['evidence_paths']=[]
            elif mode=='missing-subcheck':bad['cases'][0]['subchecks'].pop()
            elif mode=='mismatched-subcheck':bad['cases'][0]['subchecks'][0]['name']='unknown'
            elif mode=='missing-sabotage':bad['sabotage'].pop()
            elif mode=='duplicate-sabotage':bad['sabotage'][1]=copy.deepcopy(bad['sabotage'][0])
            else:bad['cases'][0]['status']=True
            with self.assertRaises(GateError):validate_containment(ROOT,bad)
    def test_stale_runner_and_instance_evidence_is_rejected(self):
        good=self.report();expected=expected_binding(ROOT,good['runner'],self.image,self.value);container_binding_gate(good,expected)
        for name in ['KernelVersion','ServerVersion','ID','image_id','source_identity','policy_hash','instance_identity']:
            bad=copy.deepcopy(good)
            if name in bad['runner']:bad['runner'][name]='stale'
            else:bad[name]='stale'
            with self.assertRaises(GateError):container_binding_gate(bad,expected)

class ProbeHomeExposureTests(unittest.TestCase):
    """Positive and negative controls for the D04 home exposure predicate."""
    def setUp(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('containment_probe',ROOT/'safety/qualification/containment/probe.py')
        self.probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.probe)
    def line(self,target):return f'36 25 0:32 / {target} rw,nosuid - tmpfs tmpfs rw'
    def test_mount_points_at_or_below_home_are_exposed(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            empty=Path(d)
            for target in ['/home','/home/user','/home/user/nested']:
                self.assertTrue(self.probe.home_exposed(self.line(target),empty),target)
    def test_unrelated_mount_points_are_not_exposed(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            empty=Path(d)
            for target in ['/','/homework','/src','/work/home','/home\\040x']:
                self.assertFalse(self.probe.home_exposed(self.line(target),empty),target)
            self.assertFalse(self.probe.home_exposed('',empty))
            self.assertFalse(self.probe.home_exposed('short line',empty))
    def test_home_directory_contents_are_exposed(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            home=Path(d)
            self.assertFalse(self.probe.home_exposed('',home))
            self.assertFalse(self.probe.home_exposed('',home/'missing'))
            (home/'someone').mkdir()
            self.assertTrue(self.probe.home_exposed('',home))

class HostCapabilityTests(unittest.TestCase):
    def info(self, **kw):
        base={'ID':'any-daemon','Architecture':'x86_64','CgroupVersion':'2','MemoryLimit':True,'SwapLimit':True,
              'PidsLimit':True,'CpuCfsQuota':True,'CpuCfsPeriod':True,
              'SecurityOptions':['name=seccomp,profile=builtin','name=apparmor','name=cgroupns']}
        base.update(kw); return base
    def ctx(self, endpoint='unix:///var/run/docker.sock'): return {'Name':'default','Endpoints':{'docker':{'Host':endpoint}}}
    def test_any_daemon_id_qualifies(self):
        from host_capabilities import host_problems
        self.assertEqual(host_problems(self.info(ID='other'),self.ctx(),{},'core'),[])
    def test_rootless_socket_qualifies(self):
        from host_capabilities import host_problems
        self.assertEqual(host_problems(self.info(),self.ctx('unix:///run/user/1000/docker.sock'),{},'core'),[])
    def test_selinux_qualifies_without_apparmor(self):
        from host_capabilities import host_problems
        i=self.info(SecurityOptions=['name=seccomp,profile=builtin','name=selinux'])
        self.assertEqual(host_problems(i,self.ctx(),{},'core',True),[])
    def test_selinux_must_enforce(self):
        from host_capabilities import host_problems
        i=self.info(SecurityOptions=['name=seccomp,profile=builtin','name=selinux'])
        for enforcing in [False,None]:
            with self.subTest(enforcing=enforcing):
                self.assertIn('linux-security-module: SELinux not enforcing',host_problems(i,self.ctx(),{},'core',enforcing))
        self.assertEqual(host_problems(self.info(),self.ctx(),{},'core',False),[])
    def test_security_options_fail_closed_without_lsm(self):
        from host_capabilities import security_options
        with self.assertRaises(GateError):security_options(self.info(SecurityOptions=['name=seccomp,profile=builtin']))
    def test_plan_security_label_follows_the_lsm(self):
        value=policy(ROOT);image=read_json(ROOT/'toolchain.lock.json')['image_id']
        apparmor=make_plan(value,image,{},'build')
        self.assertEqual(apparmor,make_plan(value,image,{},'build',lsm='apparmor'))
        self.assertEqual(apparmor['security'],['no-new-privileges','default-seccomp','docker-default-apparmor'])
        selinux=make_plan(value,image,{},'build',lsm='selinux')
        self.assertNotIn('docker-default-apparmor',selinux['security']);self.assertIn('container_t-selinux',selinux['security'])
        validate_plan(selinux,value,image,{},'build',lsm='selinux')
        with self.assertRaises(GateError):validate_plan(selinux,value,image,{},'build')
        with self.assertRaises(GateError):make_plan(value,image,{},'build',lsm=None)
    def launcher(self,d):
        launcher=Launcher(ROOT,Path(d),read_json(ROOT/'toolchain.lock.json'))
        launcher.read_core_pattern=lambda:'core'
        return launcher
    def fake_docker(self,calls,info):
        def fake(argv,**kw):
            calls.append(list(argv))
            return {'exit_code':0,'failure':None,'output':json.dumps(info() if callable(info) else info)}
        return fake
    def clean_environ(self):
        import os
        from unittest import mock
        return mock.patch.dict(os.environ,{k:'' for k in ['DOCKER_HOST','DOCKER_CONTEXT','DOCKER_TLS_VERIFY','DOCKER_CERT_PATH','DOCKER_API_VERSION','DOCKER_CONFIG']})
    def test_endpoint_and_daemon_are_bound_for_the_launcher_lifetime(self):
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as d,self.clean_environ():
            launcher=self.launcher(d);calls=[];state={'ctx':self.ctx(),'info':self.info(ID='first')}
            launcher.inspect_context=lambda:state['ctx']
            try:
                with mock.patch('container_policy.bounded',side_effect=self.fake_docker(calls,lambda:state['info'])):
                    launcher.qualify_host();self.assertEqual(launcher.endpoint,'unix:///var/run/docker.sock')
                    launcher.qualify_host()
                    state['ctx']=self.ctx('unix:///run/user/1000/docker.sock')
                    with self.assertRaisesRegex(GateError,'daemon or endpoint changed'):launcher.qualify_host()
                    self.assertEqual(launcher.prefix[-1],'unix:///var/run/docker.sock')
                    state['ctx']=self.ctx();state['info']=self.info(ID='second')
                    with self.assertRaisesRegex(GateError,'daemon or endpoint changed'):launcher.qualify_host()
            finally:launcher.close()
    def test_selinux_permissive_host_is_rejected_by_the_launcher(self):
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as d,self.clean_environ():
            launcher=self.launcher(d);calls=[];launcher.inspect_context=self.ctx
            launcher.read_selinux_enforcing=lambda:False
            try:
                with mock.patch('container_policy.bounded',side_effect=self.fake_docker(calls,self.info(SecurityOptions=['name=seccomp,profile=builtin','name=selinux']))):
                    with self.assertRaisesRegex(GateError,'SELinux not enforcing'):launcher.qualify_host()
                    launcher.read_selinux_enforcing=lambda:True
                    launcher.qualify_host()
            finally:launcher.close()
    def test_no_docker_call_for_remote_endpoint_or_inherited_setting(self):
        import os,tempfile
        from unittest import mock
        for endpoint,environ in [('tcp://127.0.0.1:1',{}),('ssh://host',{}),('unix:///var/run/docker.sock',{'DOCKER_HOST':'unix:///x'}),('unix:///var/run/docker.sock',{'DOCKER_CONTEXT':'other'})]:
            with self.subTest(endpoint=endpoint,environ=environ),tempfile.TemporaryDirectory() as d,self.clean_environ(),mock.patch.dict(os.environ,environ):
                launcher=self.launcher(d);calls=[];inspected=[]
                launcher.inspect_context=lambda endpoint=endpoint:inspected.append(1) or self.ctx(endpoint)
                try:
                    with mock.patch('container_policy.bounded',side_effect=self.fake_docker(calls,self.info())):
                        with self.assertRaisesRegex(GateError,'host capability check failed'):launcher.preflight()
                        with self.assertRaisesRegex(GateError,'host capability check failed'):launcher.docker(['ps'])
                    self.assertEqual(calls,[])
                    if environ:self.assertEqual(inspected,[])
                finally:launcher.close()
    def test_rejections_name_the_capability(self):
        from host_capabilities import host_problems
        cases=[(self.info(SecurityOptions=['name=seccomp,profile=builtin']),self.ctx(),{},'core','linux-security-module'),
               (self.info(SecurityOptions=['name=apparmor']),self.ctx(),{},'core','seccomp'),
               (self.info(),self.ctx('tcp://10.0.0.1:2376'),{},'core','local-unix-endpoint'),
               (self.info(),self.ctx('ssh://host'),{},'core','local-unix-endpoint'),
               (self.info(),self.ctx(),{'DOCKER_HOST':'unix:///x'},'core','inherited-docker-setting'),
               (self.info(CgroupVersion='1'),self.ctx(),{},'core','cgroup-v2'),
               (self.info(Architecture='aarch64'),self.ctx(),{},'core','architecture'),
               (self.info(PidsLimit=False),self.ctx(),{},'core','resource-controllers'),
               (self.info(),self.ctx(),{},'|/usr/lib/systemd/systemd-coredump','core-handling')]
        for info,ctx,env,core,expected in cases:
            with self.subTest(expected=expected):
                problems=host_problems(info,ctx,env,core)
                self.assertTrue(any(expected in p for p in problems),problems)
    def test_security_options_follow_the_lsm(self):
        from host_capabilities import security_options
        self.assertIn('apparmor=docker-default',security_options(self.info()))
        self.assertIn('label=type:container_t',security_options(self.info(SecurityOptions=['name=seccomp','name=selinux'])))
    def test_project_profile_is_in_policy(self):
        value=policy(ROOT); self.assertIn('project',value['profiles']); self.assertEqual(value['profiles']['project']['network'],'none')
    def test_project_work_fits_its_memory_and_matches_build(self):
        # /work is tmpfs inside the memory limit; a larger value only raises disk admission.
        profiles=policy(ROOT)['profiles']
        self.assertEqual(profiles['project']['work_bytes'],profiles['build']['work_bytes'])
        self.assertLessEqual(profiles['project']['work_bytes'],profiles['project']['memory_bytes'])
    def test_p15_text_mutations_change_their_protected_file(self):
        # A replace() whose target is absent is a no-op: the broken state would be accepted.
        import re
        text=(ROOT/'tools/sabotage.py').read_text()
        rows=re.findall(r"\('([\w/-]+)','([\w./-]+)',lambda s:s\.replace\('([^']+)','([^']+)'\)\)",text)
        names={row[0] for row in rows}
        self.assertTrue({'coverage-budget','fuzz-budget','required-CI-job','child-policy-or-floating-pin/child-policy'}<=names,names)
        for name,rel,old,new in rows:
            self.assertIn(old,(ROOT/rel).read_text(),name)
            self.assertNotEqual(old,new,name)
        required=[row for row in rows if row[0]=='required-CI-job'][0]
        self.assertEqual(required[1],'.github/workflows/safety.yml')
        self.assertIn('./tools/safety ci',(ROOT/required[1]).read_text())
    def test_runner_block_pins_no_machine_identity(self):
        self.assertEqual(policy(ROOT)['runner'],{'role':'portable','endpoint_scheme':'unix','architecture':'x86_64','cgroup_version':'2','lsm':['apparmor','selinux']})
    def test_launcher_accepts_project_purpose(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            launcher=Launcher(ROOT,Path(d),read_json(ROOT/'toolchain.lock.json'),purpose='project')
            launcher.close()
            with self.assertRaises(GateError):Launcher(ROOT,Path(d),read_json(ROOT/'toolchain.lock.json'),purpose='unregistered')

if __name__=='__main__':unittest.main()
