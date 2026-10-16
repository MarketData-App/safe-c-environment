import json, sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import bench_accounting as ba, bench_model as bm
POLICY=bm.load_policy(ROOT)
STAT='usage_usec {}\nuser_usec 1\nsystem_usec 1\nnr_periods 0\n'
def record(before,after):
    return {'effective':{'events_before':{'cpu.stat':STAT.format(before)}},'lifecycle':{'counters_after':{'cpu.stat':STAT.format(after)}}}
def rows(*deltas):return [{'trial_id':f't{i}','cpu_usage_usec':d} for i,d in enumerate(deltas)]

class AccountingTests(unittest.TestCase):
    def test_usage_line(self):
        self.assertEqual(ba.usage_usec(STAT.format(42)),42);self.assertIsNone(ba.usage_usec('user_usec 1\n'));self.assertIsNone(ba.usage_usec(None))
    def test_host_total(self):
        self.assertEqual(ba.host_total_usec(record(100,1100)),1000);self.assertIsNone(ba.host_total_usec({'effective':None}))
    def test_consistent_session_passes(self):
        self.assertEqual(ba.check_session('s0',1000,900,rows(300,300,250),1),[])
    def test_inflated_trial_delta_is_invalid(self):
        self.assertTrue(any('B15' in r for r in ba.check_session('s0',1000,900,rows(300,300,400),1)))
    def test_window_above_host_total_is_invalid(self):
        self.assertTrue(ba.check_session('s0',800,900,rows(100),1))
    def test_missing_host_total_is_invalid(self):
        self.assertIn('host CPU total unavailable',ba.check_session('s0',None,900,rows(100),1)[0])
    def test_missing_window_is_invalid(self):
        self.assertIn('coordinator window unavailable',ba.check_session('s0',1000,None,rows(100),1)[0])
    def test_negative_delta_is_invalid(self):
        self.assertTrue(ba.check_session('s0',1000,900,rows(-1),1))
    def test_resolution_allows_rounding(self):
        self.assertEqual(ba.check_session('s0',901,900,rows(451,451),1),[])   # 902 <= 900 + 2 x 1
    def test_reconcile_rows(self):
        reasons,acc=ba.reconcile([{'session':'s0','host_total_usec':1000,'window_usec':900,'rows':rows(300),'launcher_cgroup_inode':4242,'job_cgroup_inode':4242}],POLICY)
        self.assertEqual(reasons,[]);self.assertEqual(acc,[{'session':'s0','host_total_usec':1000,'window_usec':900,'trial_sum_usec':300,'trials':1,
                                                           'launcher_cgroup_inode':4242,'job_cgroup_inode':4242,'status':'PASS'}])
    def test_reconcile_rejects_a_wrong_cgroup(self):
        reasons,acc=ba.reconcile([{'session':'s0','host_total_usec':1000,'window_usec':900,'rows':rows(300),'launcher_cgroup_inode':4242,'job_cgroup_inode':17}],POLICY)
        self.assertIn('incorrect cgroup identity',reasons[0]);self.assertEqual(acc[0]['status'],'FAIL')
    def test_recheck_on_recorded_rows(self):
        self.assertEqual(ba.recheck({'accounting':[{'session':'s0','launcher_cgroup_inode':5,'job_cgroup_inode':5}]}),[])                  # match
        self.assertIn('incorrect cgroup identity',ba.recheck({'accounting':[{'session':'s0','launcher_cgroup_inode':5,'job_cgroup_inode':6}]})[0])   # mismatch
        self.assertEqual(ba.recheck({}),[ba.UNRECORDED]);self.assertEqual(ba.recheck({'accounting':[]}),[ba.UNRECORDED])                       # missing
    def test_incorrect_cgroup_identity_is_invalid(self):
        self.assertEqual(ba.check_cgroup_identity('s0',4242,4242),[])
        self.assertIn('incorrect cgroup identity',ba.check_cgroup_identity('s0',4242,999)[0])
        self.assertIn('incorrect cgroup identity',ba.check_cgroup_identity('s0',None,4242)[0])
    def test_launcher_records_the_inode(self):
        src=(ROOT/'tools/container_policy.py').read_text();self.assertIn("'cgroup_inode':os.stat(cg).st_ino",src)
    def test_policy_resolution(self):self.assertEqual(POLICY['accounting'],{'resolution_usec':1})
    def test_coordinator_reports_the_window(self):
        # T11-APP-02: behavior of job_timing (was a source-text check). usage_usec only, first before last, inode of CG.
        row,seen,cg=coordinator_timing([{'cpu':{'usage_usec':100,'user_usec':7,'system_usec':3}},{'cpu':{'usage_usec':250,'user_usec':9,'system_usec':4}}])
        self.assertEqual(row['cgroup_window'],{'first_usage_usec':100,'last_usage_usec':250})
        self.assertEqual(row['cgroup_inode'],cg);self.assertEqual(seen,['read','materialize','read'])
    def test_coordinator_window_without_a_cpu_sample(self):
        row,_,_=coordinator_timing([{'cpu':None},{'cpu':None}])
        self.assertEqual(row['cgroup_window'],{'first_usage_usec':None,'last_usage_usec':None})
    def test_run_schema_accepts_accounting(self):
        schema=json.loads((ROOT/'schemas/bench-run.json').read_text());self.assertIn('accounting',schema['properties'])
    def test_recorded_trial_sum_is_the_checked_sum(self):
        # T11-APP-05: the recorded trial_sum_usec is the total that check_session compares (non-negative integer deltas).
        reasons,acc=ba.reconcile([{'session':'s0','host_total_usec':1000,'window_usec':900,'rows':rows(300,-5),'launcher_cgroup_inode':4,'job_cgroup_inode':4}],POLICY)
        self.assertEqual(acc[0]['trial_sum_usec'],300);self.assertEqual(acc[0]['status'],'FAIL');self.assertTrue(any('missing or negative' in r for r in reasons))

import argparse, contextlib, hashlib, importlib.util, io, os, tempfile, uuid
from unittest import mock
_spec=importlib.util.spec_from_file_location('bc_accounting',ROOT/'container/bench-coordinator.py');bc=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(bc)

def coordinator_timing(samples):
    """job_timing with no trials; the cgroup reads, CG, WORK, the channel, the dataset and the reference are fakes."""
    with tempfile.TemporaryDirectory() as d:
        d=Path(d);cg=d/'cg';cg.mkdir();work=d/'work';(work/'bench').mkdir(parents=True);out=d/'out';out.mkdir();ref=d/'ref.json';ref.write_text('{}')
        it=iter(samples);seen=[]
        def read(*a,**k):seen.append('read');return next(it)
        def materialize(plan):seen.append('materialize');return {'path':'x','sha256':'y'}
        class Channel:
            def __init__(self,*a,**k):pass
            def close(self):pass
        with mock.patch.object(bc,'read_counters',read),mock.patch.object(bc,'CG',cg),mock.patch.object(bc,'WORK',work),mock.patch.object(bc,'Channel',Channel),\
             mock.patch.object(bc,'materialize_dataset',materialize),mock.patch.object(bc,'reference_path',lambda plan,dataset:str(ref)):
            row=bc.job_timing({'deadline_seconds':100,'trials':[]},out)
        return row,seen,os.stat(cg).st_ino

import bench, container_policy, schema_check, policy as policy_module
ENV={'cpus':4,'cpuset':[0,1,2,3],'smt_siblings':[],'reduced':False,'multicore':'PASS'}
REF=b'{"reference":[]}'

def session_config(i,trials,**over):
    """One consistent timing session: trial deltas 100, one phase row 10, window = sum + 1000, host = window + 1000."""
    obs=[{**{k:t[k] for k in ('trial_id','scope','point','variant','workers','tier','warmup')},'eligible':True,'result_sha256':None,'cpu_usage_usec':100,
          'work_units':POLICY['sizes'][t['tier']]} for t in trials]      # T16-C1: point and work count of the planned trial (run_id: FakeSession.fetch)
    phases=[{'trial_id':trials[0]['trial_id'],'scope':trials[0]['scope'],'phase':'pool_start','warmup':True,'cpu_usage_usec':10}]
    total=100*len(trials)+10;c={'obs':obs,'phases':phases,'launcher':7000+i,'job':7000+i,'window':{'first_usage_usec':5000,'last_usage_usec':5000+total+1000},
                                 'before':20000,'after':20000+total+2000}
    c.update(over);return c

class FakeRunner:
    def __init__(self):self.session={'bench':{'active_before':0}}

class FakeSession:
    """BenchSession for run_cmd: reference, timing and memory jobs; the timing job's launcher record and row come from `config`."""
    config=None
    image=staticmethod(bench.BenchSession.image)
    def __init__(self,root,run_dir,**k):self.runner=FakeRunner();self.run_dir=Path(run_dir);self.c=None
    def job(self,plan,label,timeout,restore=()):
        ev=self.run_dir/f'{label}.json';ev.write_text('{}')
        if plan['job']=='reference':row={'status':'PASS','reference_sha256':hashlib.sha256(REF).hexdigest()}
        elif plan['job']=='timing':
            self.c=FakeSession.config(label[len('timing-'):],plan['trials'])
            self.runner.session['effective']={'events_before':{'cpu.stat':STAT.format(self.c['before'])},'cgroup_inode':self.c['launcher']}
            row={'status':'PASS','files':['observations.jsonl','phases.jsonl'],'children':[],'cgroup_window':self.c['window'],'cgroup_inode':self.c['job'],**self.c.get('row',{})}
        elif plan['job']=='capacity':row={'status':'PASS','files':['capacity.jsonl']};self.cap=plan['trials']    # Task 22: the control case plans capacity trials
        else:row={'status':'PASS'};self.mem=plan.get('trial')
        return {'exit_code':0,'failure':None,'evidence_path':str(ev),'output':json.dumps(row)}
    def fetch(self,relative,destination):
        dest=Path(destination);dest.parent.mkdir(parents=True,exist_ok=True);name=relative.rsplit('/',1)[-1]
        if name=='reference.json':dest.write_bytes(REF)
        elif name in ('observations.jsonl','phases.jsonl'):dest.write_text(''.join(json.dumps(dict(r,run_id=self.run_dir.name))+'\n' for r in self.c['obs' if name=='observations.jsonl' else 'phases']))
        elif name=='memory.jsonl' and getattr(self,'mem',None):      # T16-C1: the one row of the planned memory trial
            m=self.mem;dest.write_text(json.dumps({'run_id':self.run_dir.name,**{k:m[k] for k in ('trial_id','point','mode','variant','workers','tier')},'scope':'memory',
                                                   'warmup':False,'eligible':True,'result_sha256':None,'cpu_usage_usec':100,'work_units':POLICY['sizes'][m['tier']],'memory':{}})+'\n')
        elif name=='capacity.jsonl' and getattr(self,'cap',None):     # Task 22: one complete row per planned capacity trial
            rows=[]
            for t in self.cap:
                n=t['clients']*t['requests_per_client']
                rows.append({'run_id':self.run_dir.name,**{k:t[k] for k in ('trial_id','point','scope','mode','variant','workers','tier')},'warmup':False,'eligible':True,
                             'result_sha256':None,'cpu_usage_usec':100,'wall_ns':10**6,'work_units':POLICY['sizes'][t['tier']]*n,
                             'capacity':{'configuration':t['configuration'],'clients':t['clients'],'servers':t['servers'],'requests_per_client':t['requests_per_client'],
                                         'completed':n,'errors':0,'latencies_ns':[1000]*n,'route':t['route']}})
            dest.write_text(''.join(json.dumps(r)+'\n' for r in rows))
        else:dest.write_text('')
        return dest
    def close(self):           # the launcher reads counters_after at dispose
        if self.c is not None and self.c['after'] is not None:self.runner.session['lifecycle']={'counters_after':{'cpu.stat':STAT.format(self.c['after'])}}

def run_with(config):
    """bench.run_cmd through the timing loop with fakes; the other run checks pass (run_status, observation schema)."""
    with tempfile.TemporaryDirectory() as d:return _run_with(Path(d)/uuid.uuid4().hex,config)

def _run_with(run_dir,config):
    FakeSession.config=staticmethod(config)
    probe={'status':'PASS','envelope':ENV,'evidence_paths':[],'lock_held_ns':0,'runtime':{},'cpu_max':'max 100000','cpuset':'0-3','thread_environment':dict(POLICY['envelope']['thread_environment'])}
    real=schema_check.validate
    def validate(root,name,doc):
        if name!='bench-observation':return real(root,name,doc)
    def new_run_dir(root,kind):run_dir.mkdir();return run_dir
    args=argparse.Namespace(case='bench-control-spin',plan=None,project=None,format='json',mode='smoke',dataset='synthetic:small',calibrate=None)
    with mock.patch.object(container_policy,'host_topology',lambda:(4,[0,1,2,3],[])),mock.patch.object(container_policy,'choose_envelope',lambda *a,**k:ENV),\
         mock.patch.object(bench,'new_run_dir',new_run_dir),mock.patch.object(bench,'doctor_probe',lambda root,rd:dict(probe)),\
         mock.patch.object(bench,'before_run_checks',lambda *a:([],[])),mock.patch.object(bench,'BenchSession',FakeSession),\
         mock.patch.object(bench,'run_status',lambda *a:('VALID',[])),mock.patch.object(schema_check,'validate',validate),\
         mock.patch.object(policy_module,'source_identity',lambda root:('0'*64,[])),contextlib.redirect_stdout(io.StringIO()):
        code=bench.run_cmd(ROOT,args)
    return code,json.loads((run_dir/'run.json').read_text())

class RunAccountingWiring(unittest.TestCase):
    """T11-APP-01: run_cmd takes the window from the job row's cgroup_window, the launcher inode from the session's effective
    record, the job inode from the row, and adds the B15 reasons to the run status. T11-APP-04: no row leaves the sum silently."""
    def test_matching_values_are_valid(self):
        code,run=run_with(lambda name,trials:session_config(len(name),trials))
        self.assertEqual((code,run['status']),(0,'VALID'));self.assertTrue(run['accounting'])
        self.assertFalse([r for r in run['reasons'] if 'B15' in r])
        for a in run['accounting']:
            self.assertEqual(a['status'],'PASS');self.assertEqual(a['launcher_cgroup_inode'],a['job_cgroup_inode'])
            self.assertEqual(a['window_usec'],a['trial_sum_usec']+1000);self.assertEqual(a['host_total_usec'],a['window_usec']+1000)
            self.assertEqual(a['trials'],a['trial_sum_usec']//100+1)
    def assert_b15(self,config,text):
        code,run=run_with(config)
        self.assertEqual((code,run['status']),(1,'INVALID_EXPERIMENT'))
        self.assertTrue(any('B15' in r and text in r for r in run['reasons']),run['reasons']);self.assertIn('FAIL',[a['status'] for a in run['accounting']])
    def test_inode_mismatch_is_invalid(self):
        self.assert_b15(lambda name,trials:session_config(1,trials,job=9),'incorrect cgroup identity')
    def test_launcher_inode_comes_from_the_session_record(self):
        self.assert_b15(lambda name,trials:session_config(1,trials,launcher=None),'incorrect cgroup identity')
    def test_cpu_that_does_not_reconcile_is_invalid(self):
        self.assert_b15(lambda name,trials:session_config(1,trials,window={'first_usage_usec':5000,'last_usage_usec':5001}),'exceed the coordinator window')
    def test_window_above_the_host_total_is_invalid(self):
        self.assert_b15(lambda name,trials:session_config(1,trials,after=20001),'exceeds the host total')
    def test_missing_window_is_invalid(self):
        self.assert_b15(lambda name,trials:session_config(1,trials,window={}),'coordinator window unavailable')
    def test_non_integer_window_read_is_invalid(self):
        self.assert_b15(lambda name,trials:session_config(1,trials,window={'first_usage_usec':'5000','last_usage_usec':9000}),'coordinator window unavailable')
    def test_missing_lifecycle_is_invalid(self):
        self.assert_b15(lambda name,trials:session_config(1,trials,after=None),'host CPU total unavailable')
    def test_missing_phase_delta_is_a_reason(self):
        def config(name,trials):
            c=session_config(1,trials);c['phases'][0]['cpu_usage_usec']=None;return c
        self.assert_b15(config,'missing or negative')
    def test_missing_warmup_delta_is_a_reason(self):
        def config(name,trials):
            c=session_config(1,trials);c['obs'][0]['cpu_usage_usec']=None;return c
        self.assert_b15(config,'missing or negative')

class KilledMemorySession(FakeSession):
    """The coordinator's job_memory after a call-deadline kill (G2.6): FAIL with the declared reason, and memory.jsonl holds
    the failed row (deadline_row: eligible False, no memory figure, failure_reason)."""
    def job(self,plan,label,timeout,restore=()):
        r=super().job(plan,label,timeout,restore)
        if plan['job']=='memory':r['output']=json.dumps({'status':'FAIL','failure_reason':'call-deadline','files':['memory.jsonl'],'child_exit_codes':[],'children':[]})
        return r
    def fetch(self,relative,destination):
        if relative.rsplit('/',1)[-1]!='memory.jsonl':return super().fetch(relative,destination)
        m=self.mem;dest=Path(destination);dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_text(json.dumps({'run_id':self.run_dir.name,**{k:m[k] for k in ('trial_id','point','mode','variant','workers','tier')},'scope':'memory','phase':'caller',
                                    'warmup':False,'eligible':False,'result_sha256':None,'cpu_usage_usec':None,'work_units':0,'memory':None,
                                    'verdict':{'failures':{'call-deadline':1},'reduction':'NOT_RUN'},'failure_reason':'call-deadline'})+'\n')
        return dest

class RestoringSession(FakeSession):
    """S3-04: records the restore items of every timing and capacity job (the jobs that receive the run reference)."""
    restores=[]
    def job(self,plan,label,timeout,restore=()):
        if plan['job'] in ('timing','capacity'):RestoringSession.restores.append((label,[tuple(x) for x in restore]))
        return super().job(plan,label,timeout,restore)

class ReferenceRestoreDigestTests(unittest.TestCase):
    def test_the_reference_is_restored_with_the_digest_checked_at_fetch(self):
        # S3-04: each timing and capacity job restores run_dir/reference.json with the reference job row's reference_sha256
        # (the digest that run_cmd checked against the fetched file) as the fetched digest, not with a digest read at
        # restore, so Runner.restore refuses a later host edit (DD-01) and the transfer receipt names the fetched digest.
        RestoringSession.restores=[]
        with tempfile.TemporaryDirectory() as d,mock.patch.dict(globals(),{'FakeSession':RestoringSession}):
            run_dir=Path(d)/uuid.uuid4().hex;code,run=_run_with(run_dir,lambda name,trials:session_config(len(name),trials))
        self.assertEqual((code,run['status']),(0,'VALID'))
        self.assertTrue([label for label,_ in RestoringSession.restores if label.startswith('timing-')])
        want=('bench/private/reference.json',run_dir/'reference.json',hashlib.sha256(REF).hexdigest())
        for label,items in RestoringSession.restores:
            with self.subTest(job=label):self.assertEqual(items,[want])

class KilledMemoryRowTests(unittest.TestCase):
    def test_the_failed_memory_row_of_a_deadline_kill_is_kept(self):    # T16-APP-05 (G2.6: "the failed row is kept")
        with tempfile.TemporaryDirectory() as d,mock.patch.dict(globals(),{'FakeSession':KilledMemorySession}):
            run_dir=Path(d)/uuid.uuid4().hex;code,run=_run_with(run_dir,lambda name,trials:session_config(1,trials))
            obs=[json.loads(x) for x in (run_dir/'observations.jsonl').read_text().splitlines() if x.strip()]
        mem=[o for o in obs if o['scope']=='memory'];self.assertTrue(mem)
        self.assertTrue(all(o['eligible'] is False and o['failure_reason']=='call-deadline' and o['memory'] is None for o in mem))
        self.assertFalse([r for r in run['reasons'] if r.startswith('missing failed attempt')],run['reasons'])
        self.assertEqual((code,run['status']),(1,'INVALID_EXPERIMENT'));self.assertIn('run-invalid: call-deadline',run['reasons'])
