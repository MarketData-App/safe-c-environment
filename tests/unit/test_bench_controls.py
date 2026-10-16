import sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import bench, bench_model as bm
POLICY=bm.load_policy(ROOT);ENV={'cpus':4,'multicore':'PASS'};MIB=1048576

def cpu_rows():
    r=lambda name,ratio,**extra:{'name':name,'wall_ns':10**9,'cpu_usage_usec':int(ratio*10**6),'cpu_user_usec':0,'cpu_system_usec':0,'extra':extra,'unavailable':{}}
    return [r('control-zero',0.0),r('wait',0.01),r('spin',1.0),r('spin-children-2',2.0),
            r('native-spin',1.0,children_cpu_usec=950000,parent_self_cpu_usec=20000),r('short-children-20',1.2,children_cpu_usec=1150000,parent_self_cpu_usec=30000,children=20,
              polled_tree_cpu_usec=31000,polled_label='lower bound: live process tree sampled at the handshakes')]
def mem_rows():
    r=lambda name,peak,**extra:{'name':name,'ready_current':100*MIB,'post_current':100*MIB,'group_peak_bytes':(100+peak)*MIB,'extra':extra,'unavailable':{}}
    return [r('child-touch-64',75),r('sequential-children-64x2',76,child_maxrss_kib=[76*1024,76*1024]),
            r('children-32-64',76,child_maxrss_kib=[44*1024,76*1024],rusage_children_maxrss_kib=76*1024,label='largest waited child, not a sum'),
            r('shared-mapping-64',70,rss_kib=[70*1024,66*1024],uss_kib=[4*1024,3*1024]),
            r('short-spike-64',66,sampled_max_bytes=101*MIB,label='lower bound: handshake samples'),r('untouched-1024',2)]

class ControlEvaluationTests(unittest.TestCase):
    def test_valid_controls_pass(self):
        self.assertEqual(bench.evaluate_cpu_controls(cpu_rows(),POLICY,ENV)['status'],'PASS')
        self.assertEqual(bench.evaluate_memory_controls(mem_rows(),POLICY)['status'],'PASS')
    def test_parent_only_cpu_total_is_rejected(self):
        rows=cpu_rows();native=next(r for r in rows if r['name']=='native-spin');native['cpu_usage_usec']=native['extra']['parent_self_cpu_usec']
        self.assertEqual(bench.evaluate_cpu_controls(rows,POLICY,ENV)['status'],'FAIL')
    def test_missing_cpu_counter_blocks(self):
        rows=cpu_rows();rows[2]['cpu_usage_usec']=None;rows[2]['unavailable']={'cpu.stat':'FileNotFoundError'}
        self.assertEqual(bench.evaluate_cpu_controls(rows,POLICY,ENV)['status'],'BLOCKED')
    def test_single_cpu_envelope_blocks_the_two_children_control(self):
        out=bench.evaluate_cpu_controls(cpu_rows(),POLICY,{'cpus':1,'multicore':'BLOCKED'})
        self.assertEqual([c['status'] for c in out['checks'] if c['name']=='spin-children-2'],['BLOCKED'])
    def test_summed_rss_presented_as_group_peak_is_rejected(self):
        rows=mem_rows();rows[1]['group_peak_bytes']=sum(rows[1]['extra']['child_maxrss_kib'])*1024
        self.assertEqual(bench.evaluate_memory_controls(rows,POLICY)['status'],'FAIL')
    def test_b02_wait_without_busy_cpu_and_compute_with_cpu(self):
        rows=cpu_rows();rows[1]['cpu_usage_usec']=rows[1]['wall_ns']//1000   # a "wait" that burned a full CPU
        self.assertEqual([c['status'] for c in bench.evaluate_cpu_controls(rows,POLICY,ENV)['checks'] if c['name']=='wait'],['FAIL'])
        rows=cpu_rows();rows[2]['cpu_usage_usec']=0                          # a compute control with no measured CPU
        self.assertEqual([c['status'] for c in bench.evaluate_cpu_controls(rows,POLICY,ENV)['checks'] if c['name']=='spin'],['FAIL'])
    def test_b03_short_lived_children_missing_from_the_total_fail(self):
        rows=cpu_rows();rows[-1]['cpu_usage_usec']=100000
        self.assertEqual([c['status'] for c in bench.evaluate_cpu_controls(rows,POLICY,ENV)['checks'] if c['name']=='short-children-20'],['FAIL'])
    def test_short_spike_seen_by_sampling_is_a_control_failure(self):
        rows=mem_rows();rows[4]['extra']['sampled_max_bytes']=170*MIB
        self.assertEqual(bench.evaluate_memory_controls(rows,POLICY)['status'],'FAIL')

import importlib.util, tempfile, time
spec=importlib.util.spec_from_file_location('bench_coordinator_controls',ROOT/'container/bench-coordinator.py')
bc=importlib.util.module_from_spec(spec);spec.loader.exec_module(bc)
PYPATH={'PYTHONPATH':str(ROOT/'benchmarks/performance/python')}
CLIENT=("import sys;from benchlab.markers import Marker;m=Marker();m.hello('c1');m.begin('control','c1');"
        "m.end('control','c1',sampled=True,children=3) if sys.argv[1]=='end' else None;m.close();sys.exit(0 if sys.argv[1]=='end' else 4)")

def fake_reader():
    fake_reader.n+=1;n=fake_reader.n
    return {'perf_counter_ns':n*1000,'cpu':{'usage_usec':n*7,'user_usec':n,'system_usec':n,'nr_throttled':0,'throttled_usec':0},
            'memory_current':n*MIB,'unavailable':{}}
fake_reader.n=0

class RunMarkedTests(unittest.TestCase):
    def marked(self,mode):
        d=tempfile.TemporaryDirectory();self.addCleanup(d.cleanup)
        ch=bc.Channel(Path(d.name)/'m.sock',reader=fake_reader);self.addCleanup(ch.close)
        return bc.run_marked(ch,[sys.executable,'-c',CLIENT,mode],'c1',time.monotonic()+20,env=PYPATH)
    def test_row_holds_the_handshake_delta_end_fields_and_sampled_bound(self):
        row=self.marked('end')
        self.assertEqual((row['exit_code'],row['wall_ns'],row['cpu_usage_usec'],row['extra']['children']),(0,1000,7,3))
        self.assertEqual(row['extra']['sampled_max_bytes'],max(row['ready_current'],row['post_current']))
        self.assertNotIn('sampled',row['extra'])
    def test_client_exit_without_end_is_a_control_failure(self):
        # Task 19a (0.5 s per-file budget): the process part, a client that exits without its end handshake, takes about 1 s and
        # runs in benchmarks/performance/python/tests/test_marked_run.py, which asserts that run_marked returns exactly this row.
        row={'name':'c1','exit_code':4,'extra':{'errors':[]},'unavailable':{'handshake':'missing begin or end'}}
        self.assertEqual(bench.evaluate_cpu_controls([dict(row,name='spin')]+[r for r in cpu_rows() if r['name']!='spin'],POLICY,ENV)['status'],'FAIL')
    def test_missing_control_row_is_a_failure(self):
        self.assertEqual(bench.evaluate_cpu_controls(cpu_rows()[:-1],POLICY,ENV)['status'],'FAIL')
        self.assertEqual(bench.evaluate_memory_controls([],POLICY)['status'],'FAIL')

def cpu_status(rows,name,env=ENV):return [c['status'] for c in bench.evaluate_cpu_controls(rows,POLICY,env)['checks'] if c['name']==name]
def mem_status(rows,name):return [c['status'] for c in bench.evaluate_memory_controls(rows,POLICY)['checks'] if c['name']==name]
def row(rows,name):return next(r for r in rows if r['name']==name)

class ReviewMutantTests(unittest.TestCase):
    def test_b03_double_counted_children_are_rejected(self):
        for name in ('native-spin','short-children-20'):
            rows=cpu_rows();r=row(rows,name);r['cpu_usage_usec']=2*r['extra']['children_cpu_usec']+r['extra']['parent_self_cpu_usec']
            self.assertEqual(cpu_status(rows,name),['FAIL'],name)
    def test_b03_polled_live_tree_used_as_the_total_is_rejected(self):
        rows=cpu_rows();r=row(rows,'short-children-20');r['cpu_usage_usec']=r['extra']['polled_tree_cpu_usec']
        self.assertEqual(cpu_status(rows,'short-children-20'),['FAIL'])
    def test_b03_polled_value_that_sees_the_children_is_rejected(self):
        rows=cpu_rows();r=row(rows,'short-children-20');r['extra']['polled_tree_cpu_usec']=r['cpu_usage_usec']
        self.assertEqual(cpu_status(rows,'short-children-20'),['FAIL'])
    def test_b03_polled_value_needs_its_lower_bound_label(self):
        for key in ('polled_tree_cpu_usec','polled_label'):
            rows=cpu_rows();del row(rows,'short-children-20')['extra'][key]
            self.assertEqual(cpu_status(rows,'short-children-20'),['FAIL'],key)
    def test_b03_child_count_comes_from_the_policy(self):
        rows=cpu_rows();row(rows,'short-children-20')['extra']['children']=POLICY['controls']['short_children']-1
        self.assertEqual(cpu_status(rows,'short-children-20'),['FAIL'])
    def test_b05_memory_not_freed_before_exit_is_rejected(self):
        for name in bench.MEMORY_CONTROLS:
            rows=mem_rows();row(rows,name)['post_current']+=70*MIB
            self.assertEqual(mem_status(rows,name),['FAIL'],name)
    def test_b05_sampled_and_largest_child_rows_need_their_labels(self):
        for name,word in (('short-spike-64','lower bound'),('children-32-64','largest waited child')):
            rows=mem_rows();del row(rows,name)['extra']['label']
            self.assertEqual(mem_status(rows,name),['FAIL'],name)
            rows=mem_rows();row(rows,name)['extra']['label']='peak'
            self.assertEqual(mem_status(rows,name),['FAIL'],name)
    def test_error4_children_maxrss_presented_as_a_sum_is_rejected(self):
        rows=mem_rows();r=row(rows,'children-32-64');r['extra']['rusage_children_maxrss_kib']=sum(r['extra']['child_maxrss_kib'])
        self.assertEqual(mem_status(rows,'children-32-64'),['FAIL'])
    def test_error5_uss_equal_to_rss_is_rejected(self):
        rows=mem_rows();r=row(rows,'shared-mapping-64');r['extra']['uss_kib']=list(r['extra']['rss_kib'])
        self.assertEqual(mem_status(rows,'shared-mapping-64'),['FAIL'])
    def test_error2_parent_only_peak_without_the_child_allocation_is_rejected(self):
        rows=mem_rows();r=row(rows,'child-touch-64');r['group_peak_bytes']=r['ready_current']+8*MIB
        self.assertEqual(mem_status(rows,'child-touch-64'),['FAIL'])
    def test_error8_untouched_reservation_counted_as_resident_is_rejected(self):
        rows=mem_rows();r=row(rows,'untouched-1024');r['group_peak_bytes']=r['ready_current']+1024*MIB
        self.assertEqual(mem_status(rows,'untouched-1024'),['FAIL'])
    def test_cpu_ratio_is_exact_integer_arithmetic(self):
        rows=cpu_rows();r=row(rows,'wait');r['wall_ns']=10**21;r['cpu_usage_usec']=10**17+1   # ratio 0.1 + 1e-21; a float ratio rounds it to 0.1
        self.assertEqual(cpu_status(rows,'wait'),['FAIL'])
        r['cpu_usage_usec']=10**17                                                               # exactly at the 0.1 band
        self.assertEqual(cpu_status(rows,'wait'),['PASS'])

from unittest import mock
class ControlsTimeoutTests(unittest.TestCase):
    def test_a_control_that_times_out_keeps_the_completed_rows(self):
        d=tempfile.TemporaryDirectory();self.addCleanup(d.cleanup);out=Path(d.name)/'out';out.mkdir();(Path(d.name)/'bench').mkdir()
        calls=[]
        def fake(channel,argv,client,deadline):
            calls.append(client)
            if client=='spin':raise TimeoutError('handshake deadline')
            return {'name':client,'exit_code':0,'extra':{},'unavailable':{}}
        plan={'deadline_seconds':60,'seconds':1.0,'native_mib':1,'short_children':20,'touch_mib':64,'untouched_mib':1024}
        with mock.patch.object(bc,'WORK',Path(d.name)),mock.patch.object(bc,'run_marked',fake):
            result=bc._controls(plan,out,['wait','spin','native-spin'],'controls-cpu.jsonl')
        rows=bench._rows((out/'controls-cpu.jsonl').read_text())
        self.assertEqual(([r['name'] for r in rows],[r['exit_code'] for r in rows],result['status']),(['wait','spin'],[0,1],'FAIL'))
        self.assertEqual(rows[1]['unavailable'],{'handshake':'deadline'})
