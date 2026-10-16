import copy, json, sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import bench_guardrails as bg, bench_model as bm
POL=bm.load_policy(ROOT);CP=json.loads((ROOT/'safety/container-policy.json').read_text())
ENV={'cpus':4,'cpuset':[0,1,2,3],'smt_siblings':[],'reduced':False,'multicore':'PASS'}
DOC={'cpu_max':'max 100000','thread_environment':dict(POL['envelope']['thread_environment']),
     'cpuset':'0-3'}   # T12-APP-01 (fix round 2): the doctor's effective cpuset is a required input of the hidden-CPU rule (spec H1)
PLAN={'sessions':[{'trials':[{'trial_id':'t','variant':'py-processes','workers':4,'scope':'caller'}]}],'capacity':[],'fixed_environment':dict(POL['envelope']['thread_environment'])}

class GuardrailTests(unittest.TestCase):
    def test_permitted_envelope_passes(self):self.assertEqual(bg.check(PLAN,POL,ENV,CP,DOC),{'rejected':[],'blocked':[]})
    def test_effective_cpus(self):
        self.assertEqual(bg.effective_cpus('max 100000',[0,1,2,3]),4);self.assertEqual(bg.effective_cpus('100000 100000',[0,1,2,3]),1.0)
    def test_hidden_one_cpu_is_blocked(self):
        self.assertTrue(any('hidden CPU limit' in r for r in bg.check(PLAN,POL,ENV,CP,dict(DOC,cpu_max='100000 100000'))['blocked']))
    def test_oversubscription_is_rejected(self):
        p=copy.deepcopy(PLAN);p['sessions'][0]['trials'][0]['workers']=8
        self.assertTrue(any('oversubscribed' in r for r in bg.check(p,POL,ENV,CP,DOC)['rejected']))
    def test_unbounded_queue_is_rejected(self):
        pol=copy.deepcopy(POL);pol['pools']['window_per_worker']=0
        self.assertTrue(any('unbounded queue' in r for r in bg.check(PLAN,pol,ENV,CP,DOC)['rejected']))
    def test_changed_nested_threads_is_rejected(self):
        p=copy.deepcopy(PLAN);p['fixed_environment']['OPENBLAS_NUM_THREADS']='4'
        self.assertTrue(any('nested-library threads changed' in r for r in bg.check(p,POL,ENV,CP,DOC)['rejected']))
    def test_missing_aggregate_limit_is_rejected(self):
        cp=copy.deepcopy(CP);cp['aggregate'].pop('max_active')
        self.assertTrue(any('missing aggregate limit' in r for r in bg.check(PLAN,POL,ENV,cp,DOC)['rejected']))
    def test_missing_multicore_is_blocked_not_passed(self):
        env=dict(ENV,cpus=1,cpuset=[0],multicore='BLOCKED')
        r=bg.check({'sessions':[],'capacity':[],'fixed_environment':PLAN['fixed_environment']},POL,env,CP,dict(DOC))
        self.assertIn('multicore capacity unavailable',' '.join(r['blocked']))
    def test_live_foreign_orphan_is_blocked(self):
        self.assertEqual(bg.orphan_reasons([{'trial_id':'t','left':0,'foreign_orphans':1}]),['foreign orphan alive after the call-deadline reap'])
        self.assertEqual(bg.orphan_reasons([{'trial_id':'t','left':0,'foreign_orphans':0}]),[])
    def test_hooks(self):
        src=(ROOT/'tools/bench.py').read_text();self.assertGreaterEqual(src.count('bench_guardrails.check('),2)

# Behavior tests beside the brief's tests (the brief's test_hooks above is a source-text check; these drive the hooks).
import argparse, contextlib, io, tempfile, uuid
from unittest import mock
sys.path.insert(0,str(ROOT/'tests/unit'))
import bench, bench_plan as bp, container_policy, test_bench_accounting as tba
CASE=bm.load_case(ROOT,'bench-control-spin')
NOCAP=dict({k:v for k,v in CASE.items() if k!='capacity'},scopes=[s for s in CASE['scopes'] if s!='capacity'])   # Task 22 input: the control case without its capacity block

class GuardrailRules(unittest.TestCase):
    def test_bounds_of_each_rule(self):
        self.assertEqual(bg.effective_cpus('400000 100000',[0,1,2,3]),4.0);self.assertEqual(bg.effective_cpus('800000 100000',[0,1]),2)
        self.assertEqual(bg.effective_cpus('350000 100000',[0,1,2,3]),3.5)
        for bad in (None,'','max','100000','abc 100000','100000 0','-1 100000','max -5'):
            with self.subTest(cpu_max=bad),self.assertRaises(ValueError):bg.effective_cpus(bad,[0,1,2,3])
        self.assertIn('hidden CPU limit (3.5 effective of 4)',bg.check(PLAN,POL,ENV,CP,dict(DOC,cpu_max='350000 100000'))['blocked'])
        self.assertEqual(bg.check(PLAN,POL,ENV,CP,dict(DOC,cpu_max='400000 100000'))['blocked'],[])                     # exact bound
        self.assertTrue(bg.check(PLAN,POL,ENV,CP,dict(DOC,cpu_max=None))['blocked'][0].startswith('hidden CPU limit unknown'))   # unreadable: never unlimited
        self.assertEqual(bg.check(PLAN,POL,ENV,CP,None)['blocked'],['doctor not run'])
        for window,ok in ((1,True),(2,True),(0,False),(3,False),(None,False),(True,False),('2',False)):
            pol=copy.deepcopy(POL);pol['pools']['window_per_worker']=window
            with self.subTest(window=window):self.assertEqual(not bg.check(PLAN,pol,ENV,CP,DOC)['rejected'],ok)
        pol=copy.deepcopy(POL);pol['pools'].pop('window_per_worker');self.assertIn('unbounded queue',' '.join(bg.check(PLAN,pol,ENV,CP,DOC)['rejected']))
        for limit,ok in ((1,True),(4,True),(0,False),(-1,False),(True,False),('4',False),(None,False)):
            cp=copy.deepcopy(CP);cp['aggregate']['max_active']=limit
            with self.subTest(max_active=limit):self.assertEqual(not bg.check(PLAN,POL,ENV,cp,DOC)['rejected'],ok)
    def test_oversubscription_counts_native_threads(self):
        over=lambda p,doc=DOC:any('oversubscribed t' in r for r in bg.check(p,POL,ENV,CP,doc)['rejected'])
        p=copy.deepcopy(PLAN);p['sessions'][0]['trials'][0]['workers']=2;p['fixed_environment']['OMP_NUM_THREADS']='2';self.assertFalse(over(p))   # 2 x 1 x 2 = 4
        p['sessions'][0]['trials'][0]['workers']=4;self.assertTrue(over(p))                                                                          # 4 x 1 x 2 = 8
        p={k:v for k,v in PLAN.items() if k!='fixed_environment'};self.assertTrue(over(p,dict(DOC,thread_environment=dict(DOC['thread_environment'],MKL_NUM_THREADS='2'))))
        p=copy.deepcopy(PLAN);p['sessions'][0]['trials'][0].update(workers=2,threads_per_worker=3);self.assertFalse(over(p))   # T12-C5: no invented per-trial field is read
        p=copy.deepcopy(PLAN);p['memory']=[{'trial_id':'m','variant':'py-threads','workers':5}];self.assertTrue(any('oversubscribed m' in r for r in bg.check(p,POL,ENV,CP,DOC)['rejected']))
        p=copy.deepcopy(PLAN);p['sessions'][0]['trials'][0]['workers']='direct';self.assertEqual(bg.check(p,POL,ENV,CP,DOC)['rejected'],[])
        for w in (0,-1,None,True):
            p=copy.deepcopy(PLAN);p['sessions'][0]['trials'][0]['workers']=w
            with self.subTest(workers=w):self.assertTrue(any('oversubscribed' in r for r in bg.check(p,POL,ENV,CP,DOC)['rejected']))
    def test_capacity_configurations(self):
        # T12-C5: no key: an explicit "not applicable" result. Task 22 defines the capacity trial format
        # (bench_capacity.trial_format): an entry that is not of that format is rejected, never a silent pass and never a guessed field.
        r=bg.check({k:v for k,v in PLAN.items() if k!='capacity'},POL,ENV,CP,DOC)
        self.assertEqual((r['rejected'],r['blocked']),([],[]));self.assertIn(bg.NA_CAPACITY,r['not_applicable'])
        self.assertNotIn('not_applicable',bg.check(PLAN,POL,ENV,CP,DOC))                                    # capacity [] : nothing to check
        for configs in ([{'name':'python-pool','workers':4,'queue_limit':8}],[{}],['x']):
            with self.subTest(configs=configs):
                r=bg.check(dict(PLAN,capacity=configs),POL,ENV,CP,DOC)
                self.assertEqual(r['blocked'],[]);self.assertTrue(r['rejected'] and all(x.startswith('capacity: ') for x in r['rejected']),r)
    def test_not_applicable_rules_of_a_built_plan(self):
        plan=bp.build_plan(NOCAP,POL,mode='smoke',dataset={'kind':'synthetic','size':'small','seed':1,'sha256':None,'rows':256},seed=3,envelope=ENV)
        r=bg.check(plan,POL,ENV,CP,DOC)
        self.assertEqual((r['rejected'],r['blocked']),([],[]));self.assertEqual(r['not_applicable'],[bg.NA_CAPACITY,bg.NA_FIXED_ENVIRONMENT])
    def test_doctor_thread_environment(self):
        for name in bg.THREAD_NAMES:
            for value in ('4',None,'0'):
                env=dict(DOC['thread_environment']);env[name]=value
                with self.subTest(name=name,value=value):
                    self.assertIn(f'nested-library threads changed ({name})',bg.check(PLAN,POL,ENV,CP,dict(DOC,thread_environment=env))['rejected'])
        self.assertEqual(bg.check({k:v for k,v in PLAN.items() if k!='fixed_environment'},POL,ENV,CP,DOC),
                         {'rejected':[],'blocked':[],'not_applicable':[bg.NA_FIXED_ENVIRONMENT]})   # T12-C5: explicit, the doctor row decides
    def test_orphan_records(self):
        self.assertEqual(bg.orphan_reasons([]),[]);self.assertEqual(bg.orphan_reasons(None),[])
        self.assertEqual(bg.orphan_reasons([{'foreign_orphans':0},{'foreign_orphans':2}]),[bg.ORPHAN_REASON])
        for bad in (None,'1',True,-1):
            with self.subTest(foreign_orphans=bad):self.assertEqual(bg.orphan_reasons([{'trial_id':'t','left':0,'foreign_orphans':bad}]),[bg.ORPHAN_REASON])
    def test_blocked_rows_are_the_affected_rows(self):
        plan=bp.build_plan(CASE,POL,mode='smoke',dataset={'kind':'synthetic','size':'small','seed':1,'sha256':None,'rows':256},seed=3,envelope=ENV)
        aff=bg.affected(plan,POL,ENV,CP,dict(DOC,cpu_max='100000 100000'))
        rows=bg.blocked_rows(plan,aff)
        self.assertTrue(rows);self.assertTrue(all(r['workers']>=2 and r['guardrail'] is True and r['reason']=='blocked: hidden CPU limit (1 effective of 4)' for r in rows))
        self.assertEqual(bg.blocked_rows(plan,bg.affected(plan,POL,ENV,CP,DOC)),[])
        everything=bg.blocked_rows(plan,bg.affected(plan,POL,ENV,CP,dict(DOC,cpu_max=None)))   # unknown quota: every planned row
        self.assertEqual({(r['variant'],r['workers']) for r in everything},{(t['variant'],t['workers']) for t in bg.planned_trials(plan)})

ENV1={'cpus':1,'cpuset':[0],'smt_siblings':[],'reduced':True,'multicore':'BLOCKED'}

class HiddenCpuset(unittest.TestCase):
    """T12-APP-01: spec H1 "the effective cpuset or quota gives fewer CPUs than the envelope claims": effective CPUs =
    min(len(doctor effective cpuset intersected with the envelope cpuset), quota); a missing or malformed cpuset is unknown."""
    def blocked(self,**doc):return bg.check(PLAN,POL,ENV,CP,dict(DOC,**doc))['blocked']
    def test_parse(self):
        self.assertEqual(bg.parse_cpu_list('0-3'),[0,1,2,3]);self.assertEqual(bg.parse_cpu_list('3,1,0-1'),[0,1,3]);self.assertEqual(bg.parse_cpu_list(' 2 \n'),[2])
        for bad in (None,'','abc','3-1','0-','-1','0,,1','1.5',[0,1],'0-99999'):
            with self.subTest(cpuset=bad),self.assertRaises(ValueError):bg.parse_cpu_list(bad)
    def test_smaller_effective_set_is_blocked(self):
        self.assertEqual(self.blocked(cpuset='0-1'),['hidden CPU limit (2 effective of 4)']);self.assertEqual(self.blocked(cpuset='0'),['hidden CPU limit (1 effective of 4)'])
    def test_disjoint_set_is_blocked(self):
        self.assertEqual(self.blocked(cpuset='4-7'),['hidden CPU limit (0 effective of 4)'])
        self.assertEqual(self.blocked(cpuset='2-5'),['hidden CPU limit (2 effective of 4)'])            # only the envelope CPUs count
    def test_equal_set_is_the_exact_bound(self):
        for cpuset in ('0-3','3,2,1,0','0-1,2-3','0-7'):
            with self.subTest(cpuset=cpuset):self.assertEqual(self.blocked(cpuset=cpuset),[])
    def test_missing_or_malformed_set_is_unknown(self):
        for cpuset in (None,'','x','3-0'):
            with self.subTest(cpuset=cpuset):
                b=self.blocked(cpuset=cpuset);self.assertEqual(len(b),1);self.assertTrue(b[0].startswith('hidden CPU limit unknown (cpuset'),b)
        b=bg.check(PLAN,POL,ENV,CP,{k:v for k,v in DOC.items() if k!='cpuset'})['blocked'];self.assertTrue(b[0].startswith('hidden CPU limit unknown (cpuset'),b)
    def test_set_and_quota_combine(self):
        self.assertEqual(self.blocked(cpuset='0-2',cpu_max='800000 100000'),['hidden CPU limit (3 effective of 4)'])
        self.assertEqual(self.blocked(cpuset='0-3',cpu_max='250000 100000'),['hidden CPU limit (2.5 effective of 4)'])

def gate(plan,envelope,probe_over):
    with tempfile.TemporaryDirectory() as d:
        probe=dict({'status':'PASS','envelope':envelope,'evidence_paths':[]},**DOC);probe.update(probe_over)
        p=copy.deepcopy(plan);reasons,state=bench.guardrail_gate(ROOT,Path(d),p,POL,envelope,probe)
        return reasons,state,json.loads((Path(d)/'guardrails.json').read_text()),p

class SingleWorkerRows(unittest.TestCase):
    """T12-APP-02: a blocked reason that also affects single-worker rows BLOCKS the run, also without a multicore trial."""
    PLAN1=bp.build_plan(CASE,POL,mode='smoke',dataset={'kind':'synthetic','size':'small','seed':1,'sha256':None,'rows':256},seed=3,envelope=ENV1)
    def test_the_one_cpu_plan_has_no_multicore_trial(self):
        self.assertTrue(bg.planned_trials(self.PLAN1));self.assertEqual(bg.multicore_trials(self.PLAN1),[])
    def test_a_quota_below_one_cpu_blocks(self):
        reasons,state,guard,p=gate(self.PLAN1,ENV1,{'cpu_max':'50000 100000','cpuset':'0'})
        self.assertEqual(state,'BLOCKED');self.assertIn('blocked: hidden CPU limit (0.5 effective of 1)',reasons)
        self.assertTrue([r for r in p['blocked_rows'] if r.get('guardrail') and r['workers'] in (1,'direct')])
    def test_an_unknown_quota_or_cpuset_blocks(self):
        for over in ({'cpu_max':None,'cpuset':'0'},{'cpuset':None}):
            with self.subTest(over=over):
                reasons,state,_,_=gate(self.PLAN1,ENV1,over);self.assertEqual(state,'BLOCKED');self.assertTrue(any(r.startswith('blocked: hidden CPU limit unknown') for r in reasons))
    def test_malformed_capacity_configurations_are_rejected(self):      # Task 22: the defined format; a malformed entry is a real failure (GATED), never BLOCKED
        reasons,state,_,_=gate(dict(self.PLAN1,capacity=[{}]),ENV1,{'cpuset':'0'});self.assertEqual(state,'GATED')
        self.assertTrue(reasons and all(r.startswith('rejected: capacity: ') for r in reasons),reasons)
    def test_missing_multicore_alone_leaves_single_worker_rows(self):
        reasons,state,guard,p=gate(self.PLAN1,ENV1,{'cpuset':'0'})            # accepted C1 path: the multicore rows are already blocked by build_plan
        self.assertEqual((reasons,state),([],'PASS'));self.assertEqual(guard['blocked'],['multicore capacity unavailable'])
        self.assertFalse([r for r in p['blocked_rows'] if r.get('guardrail')])
    def test_through_run_cmd(self):
        code,run,_,_=run_cmd_with({'cpu_max':'50000 100000','cpuset':'0'},envelope=ENV1)
        self.assertEqual((code,run['status']),(2,'BLOCKED'));self.assertIn('blocked: hidden CPU limit (0.5 effective of 1)',run['reasons'])

class NoSession:
    image=staticmethod(bench.BenchSession.image)
    def __init__(self,*a,**k):raise AssertionError('no trial container may start')

def run_cmd_with(probe_over,envelope=ENV):
    """bench.run_cmd with a fake doctor probe; any BenchSession fails the test (no trial container)."""
    with tempfile.TemporaryDirectory() as d:
        run_dir=Path(d)/uuid.uuid4().hex;out=io.StringIO()
        probe=dict({'status':'PASS','envelope':envelope,'evidence_paths':[],'lock_held_ns':0,'runtime':{}},**DOC);probe.update(probe_over)
        def new_run_dir(root,kind):run_dir.mkdir();return run_dir
        args=argparse.Namespace(case='bench-control-spin',plan=None,project=None,format='json',mode='smoke',dataset='synthetic:small',calibrate=None)
        with mock.patch.object(container_policy,'host_topology',lambda:(4,[0,1,2,3],[])),mock.patch.object(container_policy,'choose_envelope',lambda *a,**k:envelope),\
             mock.patch.object(bench,'new_run_dir',new_run_dir),mock.patch.object(bench,'doctor_probe',lambda root,rd:dict(probe)),\
             mock.patch.object(bench,'before_run_checks',lambda *a:([],[])),mock.patch.object(bench,'BenchSession',NoSession),\
             mock.patch.object(tba.policy_module,'source_identity',lambda root:('0'*64,[])),contextlib.redirect_stdout(out):
            code=bench.run_cmd(ROOT,args)
        guard=run_dir/'guardrails.json'
        return code,json.loads((run_dir/'run.json').read_text()),json.loads((run_dir/'plan.json').read_text()),json.loads(guard.read_text()) if guard.is_file() else None

class RunHook(unittest.TestCase):
    def test_rejected_plan_starts_no_trial(self):
        code,run,_,_=run_cmd_with({'thread_environment':dict(DOC['thread_environment'],OMP_NUM_THREADS='8')})
        self.assertEqual((code,run['status']),(1,'INVALID_EXPERIMENT'))
        self.assertIn('rejected: nested-library threads changed (OMP_NUM_THREADS)',run['reasons']);self.assertEqual(run['accounting'],[])
    def test_the_run_records_the_guardrail_result(self):       # T12-C5: the not-applicable rules are explicit in the run evidence
        with mock.patch.object(bench.bm,'load_case',lambda *a,**k:copy.deepcopy(NOCAP)):code,run,_,guard=run_cmd_with({'cpu_max':'100000 100000'})   # Task 22 input: no capacity block
        self.assertEqual(guard['not_applicable'],[bg.NA_CAPACITY,bg.NA_FIXED_ENVIRONMENT]);self.assertIn('hidden CPU limit (1 effective of 4)',guard['blocked'])
    def test_hidden_cpu_limit_blocks_the_run(self):
        code,run,plan,_=run_cmd_with({'cpu_max':'100000 100000'})
        self.assertEqual((code,run['status']),(2,'BLOCKED'));self.assertIn('blocked: hidden CPU limit (1 effective of 4)',run['reasons'])
        rows=[r for r in plan['blocked_rows'] if r.get('guardrail')]
        self.assertTrue(rows);self.assertTrue(all(r['workers']>=2 for r in rows))
        built=bp.build_plan(CASE,POL,mode='smoke',dataset=plan['dataset'],seed=plan['seed'],envelope=ENV)       # the planned blocked rows stay; guardrail rows are added
        self.assertEqual(bench.without_guardrail_rows(plan)['blocked_rows'],json.loads(json.dumps(built['blocked_rows'])))
    def test_effective_cpuset_through_run_cmd(self):               # T12-APP-01
        for cpuset,text in (('0-1','blocked: hidden CPU limit (2 effective of 4)'),('4-7','blocked: hidden CPU limit (0 effective of 4)')):
            with self.subTest(cpuset=cpuset):
                code,run,_,_=run_cmd_with({'cpuset':cpuset});self.assertEqual((code,run['status']),(2,'BLOCKED'));self.assertIn(text,run['reasons'])
        for cpuset in (None,'zz'):
            with self.subTest(cpuset=cpuset):
                code,run,_,_=run_cmd_with({'cpuset':cpuset});self.assertEqual((code,run['status']),(2,'BLOCKED'))
                self.assertTrue(any(r.startswith('blocked: hidden CPU limit unknown (cpuset') for r in run['reasons']),run['reasons'])
        code,run=tba.run_with(lambda name,trials:tba.session_config(1,trials));self.assertEqual(run['status'],'VALID')   # equal set '0-3': runs
    def test_permitted_envelope_runs_with_accounting(self):
        code,run=tba.run_with(lambda name,trials:tba.session_config(1,trials))      # the T11 harness: doctor cpu_max 'max 100000'
        self.assertEqual((code,run['status']),(0,'VALID'))
    def test_live_foreign_orphan_is_a_run_reason(self):
        kills=lambda n:(lambda name,trials:tba.session_config(1,trials,row={'deadline_kills':[{'trial_id':trials[0]['trial_id'],'left':0,'foreign_orphans':n}]}))
        code,run=tba.run_with(kills(1))
        self.assertEqual((code,run['status']),(1,'INVALID_EXPERIMENT'));self.assertIn('run-invalid: '+bg.ORPHAN_REASON,run['reasons'])   # T12-APP-03
        self.assertFalse([r for r in run['reasons'] if r.startswith('blocked:')])
        code,run=tba.run_with(kills(0));self.assertEqual((code,run['status']),(0,'VALID'))

def plan_cmd_with(policy,doctor_row):
    with tempfile.TemporaryDirectory() as d:
        run_dir=Path(d)/uuid.uuid4().hex;out=io.StringIO();made=[]
        def new_run_dir(root,kind):made.append(kind);run_dir.mkdir();return run_dir
        args=argparse.Namespace(case='bench-control-spin',project=None,format='json',mode='smoke',dataset='synthetic:small',calibrate=None)
        with mock.patch.object(container_policy,'host_topology',lambda:(4,[0,1,2,3],[])),mock.patch.object(container_policy,'choose_envelope',lambda *a,**k:ENV),\
             mock.patch.object(bench,'new_run_dir',new_run_dir),mock.patch.object(bench.bm,'load_policy',lambda root,project_dir=None:policy),\
             mock.patch.object(bench,'last_doctor_record',lambda root:(doctor_row,{'path':'artifacts/bench/x/doctor.json','age_seconds':7} if doctor_row else None)),\
             contextlib.redirect_stdout(out):
            code=bench.plan_cmd(ROOT,args)
        plan=json.loads((run_dir/'plan.json').read_text()) if (run_dir/'plan.json').is_file() else None
        return code,json.loads(out.getvalue().strip().splitlines()[-1]),plan,made

class PlanHook(unittest.TestCase):
    def test_rejected_plan_is_refused(self):
        pol=copy.deepcopy(POL);pol['pools']['window_per_worker']=3
        code,row,plan,made=plan_cmd_with(pol,DOC)
        self.assertEqual(code,1);self.assertEqual(row['status'],'FAIL');self.assertIn('unbounded queue',' '.join(row['rejected']));self.assertIsNone(plan);self.assertEqual(made,[])
    def test_missing_doctor_row_blocks_and_the_plan_still_verifies(self):
        code,row,plan,_=plan_cmd_with(POL,None)
        self.assertEqual((code,row['status']),(0,'PASS'));self.assertIn('blocked: doctor not run',[r['reason'] for r in row['blocked_rows']])
        self.assertEqual(row['blocked_rows'],plan['blocked_rows']);self.assertEqual(bench.plan_digest(plan),plan['plan_id'])
        bench.verify_written_plan(CASE,POL,plan,ENV,None,None)         # `bench run --plan` still accepts it (host-state rows are outside the identity)
        planned=[i for i,r in enumerate(plan['blocked_rows']) if not r.get('guardrail')]
        if planned:                                                      # a planned row relabelled as a guardrail row is an edit
            p=copy.deepcopy(plan);p['blocked_rows'][planned[0]]['guardrail']=True;p['plan_id']=bench.plan_digest(p)
            with self.assertRaises(bench.GateError):bench.verify_written_plan(CASE,POL,p,ENV,None,None)
        p=copy.deepcopy(plan);p['sessions']=p['sessions'][1:];p['plan_id']=bench.plan_digest(p)
        with self.assertRaises(bench.GateError):bench.verify_written_plan(CASE,POL,p,ENV,None,None)
    def test_permitted_envelope_plans_unchanged(self):
        with mock.patch.object(bench.bm,'load_case',lambda *a,**k:copy.deepcopy(NOCAP)):code,row,plan,_=plan_cmd_with(POL,DOC)   # Task 22 input: no capacity block
        built=bp.build_plan(NOCAP,POL,mode='smoke',dataset=plan['dataset'],seed=plan['seed'],envelope=ENV)
        self.assertEqual(code,0);self.assertEqual(plan,json.loads(json.dumps(built)));self.assertFalse([r for r in row['blocked_rows'] if r.get('guardrail')])
        self.assertEqual(row['guardrails'],{'rejected':[],'blocked':[],'not_applicable':[bg.NA_CAPACITY,bg.NA_FIXED_ENVIRONMENT],
                                            'doctor_row':{'path':'artifacts/bench/x/doctor.json','age_seconds':7}})   # T12-C5, T12-APP-04
    def test_missing_doctor_row_source_is_null(self):
        _,row,_,_=plan_cmd_with(POL,None);self.assertIsNone(row['guardrails']['doctor_row'])
    def test_last_doctor_record_names_its_source_and_age(self):    # T12-APP-04
        import os, time
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.assertEqual(bench.last_doctor_record(root),(None,None))
            for name,status,age in (('a'*32,'OLD',100),('b'*32,'NEW',10)):
                p=root/'artifacts/bench'/name/'doctor.json';p.parent.mkdir(parents=True);p.write_text(json.dumps({'status':status}))
                t=time.time()-age;os.utime(p,(t,t))
            (root/'artifacts/bench'/('c'*32)).mkdir();(root/'artifacts/bench'/('c'*32)/'doctor.json').write_text('{not json')   # newest, unreadable: skipped
            row,src=bench.last_doctor_record(root)
            self.assertEqual(row,{'status':'NEW'});self.assertEqual(src['path'],'artifacts/bench/'+'b'*32+'/doctor.json');self.assertTrue(9<=src['age_seconds']<=60)

import bench_privacy

def run_local_with(probe_over,checks=True):
    """T12-C4: bench_privacy.run_local (the owner-fixture path) with a fake doctor probe. No BenchSession and no pre-run
    check container may start when the guardrails refuse or BLOCK; the fixture path is never opened."""
    with tempfile.TemporaryDirectory() as d:
        run_dir=Path(d)/uuid.uuid4().hex;out=io.StringIO();probed=[]
        plan=bp.build_plan(CASE,POL,mode='smoke',dataset={'kind':'local','size':None,'seed':None,'sha256':'0'*64,'rows':256},seed=3,envelope=ENV)
        plan['dataset']['path']=str(Path(d)/'absent-fixture.json');plan['pyperf']={'values':1,'warmups':0};plan['project_dir']=None
        probe=dict({'status':'PASS','envelope':ENV,'evidence_paths':[],'lock_held_ns':0,'runtime':{}},**DOC);probe.update(probe_over)
        def new_run_dir(root,kind):run_dir.mkdir();return run_dir
        def no_checks(*a):raise AssertionError('no pre-run check container may start')
        args=argparse.Namespace(case='bench-control-spin',format='json')
        with mock.patch.object(bench,'new_run_dir',new_run_dir),mock.patch.object(bench,'doctor_probe',lambda root,rd:probed.append(1) or dict(probe)),\
             mock.patch.object(bench,'before_run_checks',no_checks) if checks else contextlib.nullcontext(),mock.patch.object(bench,'BenchSession',NoSession),\
             mock.patch.object(tba.policy_module,'source_identity',lambda root:('0'*64,[])),contextlib.redirect_stdout(out),\
             mock.patch.object(bench_privacy,'install_fixture_pattern',return_value=True):   # Task 27: never the real git common dir
            code=bench_privacy.run_local(ROOT,args,plan,CASE,POL)
        guard=run_dir/'guardrails.json'
        return code,json.loads((run_dir/'run.json').read_text()),json.loads(guard.read_text()) if guard.is_file() else None,probed

class LocalRunHook(unittest.TestCase):
    def test_guardrail_block_starts_no_trial(self):
        code,run,guard,probed=run_local_with({'cpu_max':'100000 100000'})
        self.assertEqual(probed,[1]);self.assertEqual((code,run['status']),(2,'BLOCKED'))
        self.assertIn('blocked: hidden CPU limit (1 effective of 4)',run['reasons']);self.assertIn('hidden CPU limit (1 effective of 4)',guard['blocked'])
    def test_rejected_local_run_is_invalid(self):
        code,run,_,_=run_local_with({'thread_environment':dict(DOC['thread_environment'],OPENBLAS_NUM_THREADS='2')})
        self.assertEqual((code,run['status']),(1,'INVALID_EXPERIMENT'))
        self.assertIn('rejected: nested-library threads changed (OPENBLAS_NUM_THREADS)',run['reasons'])
    def test_effective_cpuset_through_run_local(self):             # T12-APP-01
        for cpuset,text in (('0-1','hidden CPU limit (2 effective of 4)'),('5','hidden CPU limit (0 effective of 4)')):
            with self.subTest(cpuset=cpuset):
                code,run,guard,_=run_local_with({'cpuset':cpuset});self.assertEqual((code,run['status']),(2,'BLOCKED'));self.assertIn('blocked: '+text,run['reasons'])
        for cpuset in (None,'0--3'):
            with self.subTest(cpuset=cpuset):
                code,run,_,_=run_local_with({'cpuset':cpuset});self.assertEqual((code,run['status']),(2,'BLOCKED'))
                self.assertTrue(any(r.startswith('blocked: hidden CPU limit unknown (cpuset') for r in run['reasons']),run['reasons'])
    def test_equal_cpuset_passes_the_local_gate(self):
        class Reached(Exception):pass
        def checks(*a):raise Reached()           # the first job after the gate: the gate let the run continue
        with mock.patch.object(bench,'before_run_checks',checks),self.assertRaises(Reached):run_local_with({'cpuset':'0-3'},checks=False)
    def test_blocked_doctor_blocks_the_local_run(self):
        code,run,_,_=run_local_with({'status':'BLOCKED'})
        self.assertEqual((code,run['status']),(2,'BLOCKED'));self.assertIn('bench doctor: BLOCKED',run['reasons'])
    def test_guardrail_stopped_local_run_is_unbound_and_never_valid(self):   # T16-C3: this path records no evidence digests
        for over in ({'status':'BLOCKED'},{'cpu_max':'100000 100000'},{'thread_environment':dict(DOC['thread_environment'],OPENBLAS_NUM_THREADS='2')}):
            with self.subTest(over=sorted(over)):
                code,run,_,_=run_local_with(over)
                self.assertNotEqual(run['status'],'VALID');self.assertIn(code,(1,2));self.assertNotIn('evidence_digests',run)

class CoordinatorDoctorRow(unittest.TestCase):
    """job_doctor gains cpu_max: the text of cpu.max in the container cgroup, or null with a reason."""
    def doctor(self,cpu_max):
        saved=(list(sys.path),list(sys.meta_path))
        with tempfile.TemporaryDirectory() as d:
            cg=Path(d)/'cg';cg.mkdir();work=Path(d)/'work';work.mkdir()
            for name,text in {'cpu.stat':'usage_usec 1\nuser_usec 1\nsystem_usec 0\nnr_throttled 0\nthrottled_usec 0\n','memory.stat':'anon 1\nfile 1\nshmem 0\n',
                              'memory.current':'1\n','pids.current':'1\n','cgroup.procs':'','cpuset.cpus.effective':'0-3\n'}.items():(cg/name).write_text(text)
            if cpu_max is not None:(cg/'cpu.max').write_text(cpu_max)
            (Path(d)/'selftestwheel.py').write_text("__version__='1.0'\n")
            try:
                sys.path.insert(0,d)
                with mock.patch.object(tba.bc,'CG',cg),mock.patch.object(tba.bc,'WORK',work):return tba.bc.job_doctor({'job':'doctor','expected':{'selftestwheel':'1.0'}},work)
            finally:
                sys.path[:]=saved[0];sys.meta_path[:]=saved[1];sys.modules.pop('selftestwheel',None)
    def test_cpu_max_text(self):
        self.assertEqual(self.doctor('400000 100000\n')['cpu_max'],'400000 100000');self.assertEqual(self.doctor('max 100000\n')['cpu_max'],'max 100000')
    def test_unreadable_cpu_max_is_null_with_a_reason(self):
        row=self.doctor(None);self.assertIsNone(row['cpu_max']);self.assertEqual(row['unavailable'].get('cpu.max'),'FileNotFoundError')
        self.assertTrue(bg.check(PLAN,POL,ENV,CP,row)['blocked'][0].startswith('hidden CPU limit unknown'))
    def test_doctor_probe_passes_cpu_max_on(self):
        row={'status':'PASS','cpu_max':'100000 100000','thread_environment':DOC['thread_environment']}
        class Session:
            evidence_paths=[]
            def __init__(self,*a,**k):pass
            def job(self,*a,**k):return {'exit_code':0,'failure':None,'evidence_path':'x','output':json.dumps(row)}
            def envelope(self):return ENV
            def close(self):pass
            runner=None
        with mock.patch.object(bench,'BenchSession',Session):probe=bench.doctor_probe(ROOT,Path(tempfile.gettempdir()))
        self.assertEqual(probe['cpu_max'],'100000 100000')

if __name__=='__main__':unittest.main()
