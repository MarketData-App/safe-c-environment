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

if __name__=='__main__':unittest.main()


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
