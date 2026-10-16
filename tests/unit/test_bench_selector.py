import copy, json, math, os, random, sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import bench, bench_deadline as bd, bench_model as bm, bench_plan as bp, bench_stats as bs
from evidence import GateError
from schema_check import validate
FIXTURE='tests/fixtures/bench-project'
# FR3: the planning shares are project data; POL is the policy of the fixture project (selectors m1..m5, share_required m5).
POL=bm.load_policy(ROOT,FIXTURE);CASE=bm.load_case(ROOT,'bench-control-spin')

def fixture_stub_project(reason='stub-hang'):
    """(project, case) of the protocol stub `reason`, found by declaration over the synthetic unit-test project only (FR1,
    FS1 F3; FR3): the framework tree holds no project that declares a test stub."""
    from unittest import mock
    with mock.patch.object(bench,'example_projects',lambda root:[FIXTURE]):return bd.stub_project(ROOT,reason)[:2]

class SchemaTests(unittest.TestCase):
    def test_control_case_declares_the_test_selector(self):
        self.assertEqual(CASE['selectors'],['all','hang']);self.assertEqual(CASE['call_deadline']['reason'],'control-hang')
    def test_undeclared_selector_is_refused(self):
        c=copy.deepcopy(CASE);c['points'][0]['selector']='nope'
        with self.assertRaises(GateError):bm.case_rules(ROOT,c)
    def test_panel_needs_the_tiny_size(self):
        c=copy.deepcopy(CASE);c['points'][0]['panel']=[1,2,3,4,5,6];c['points'][0]['size']='small'
        with self.assertRaises(GateError):bm.case_rules(ROOT,c)
    def test_unit_selector_must_match(self):
        c=copy.deepcopy(CASE);c['points'][0]['selector']='all';c['points'][0]['unit']='hang/full-dataset'
        with self.assertRaises(GateError):bm.case_rules(ROOT,c)
    def test_observation_and_run_accept_the_new_fields(self):
        o=json.loads((ROOT/'schemas/bench-observation.json').read_text())['properties'];r=json.loads((ROOT/'schemas/bench-run.json').read_text())['properties']
        self.assertIn('selector',o);self.assertIn('dataset_ref',o);self.assertIn('failure_reasons',r)
    def test_share_per_selector(self):
        self.assertEqual(POL['budgets']['estimate_share_per_selector'],{'m1':0.05,'m2':0.10,'m3':1.0,'m4':0.15,'m5':3.0})
        self.assertEqual(POL['budgets']['estimate_share_per_selector'],bm.load_protocol(ROOT,FIXTURE)['budgets']['estimate_share_per_selector'])

class IntervalTests(unittest.TestCase):
    def test_index_rule(self):
        vals={b:float(b+1) for b in range(12)};R=1000;a=0.025
        lo,hi=bs.median_interval(vals,R,20261007,a)
        rng=random.Random(20261007);ids=sorted(vals);meds=[]
        for _ in range(R):
            pick=[ids[rng.randrange(12)] for _ in range(12)];meds.append(bs.median([vals[i] for i in pick]))
        meds.sort();self.assertEqual((lo,hi),(meds[math.floor(a*R)],meds[math.ceil((1-a)*R)-1]))
    def test_explicit_indices(self):
        vals={0:1.0,1:2.0,2:3.0};idx=[[0,0,0],[2,2,2],[1,1,1],[0,1,2]]
        self.assertEqual(bs.median_interval(vals,4,1,0.25,indices=idx),(2.0,2.0))
    def test_bad_arguments(self):
        with self.assertRaises(ValueError):bs.median_interval({},10,1,0.025)
        with self.assertRaises(ValueError):bs.median_interval({0:1.0},10,1,0.6)

class DeadlineTests(unittest.TestCase):
    T={'variant':'py-reference','selector':'hang','tier':'small'}
    def test_floor_and_factor(self):
        self.assertEqual(bd.trial_deadline(CASE,POL,self.T,rows=256,calls=1,calibration=None,session_remaining=10_000),
                         max(2.0,10*bd.expected_seconds(POL,self.T,256,1,None)))
    def test_session_cap_wins(self):
        self.assertEqual(bd.trial_deadline(CASE,POL,self.T,rows=256,calls=1,calibration=None,session_remaining=1.5),1.5)
    def test_uncovered_selector_has_no_deadline(self):
        self.assertIsNone(bd.trial_deadline(CASE,POL,dict(self.T,selector='all'),256,1,None,10_000))
    def test_deadline_inputs_per_job(self):
        plan={'sizes':POL['sizes'],'dataset':{'kind':'synthetic','rows':13230}}
        self.assertEqual(bd.job_inputs('timing',plan,{'tier':'large','loops':1}),(13230,1))
        self.assertEqual(bd.job_inputs('timing',plan,{'tier':'tiny','panel_passes':84,'mode':'warm','panel':[1,2,3,4,5,6]}),(1,504))
        self.assertEqual(bd.job_inputs('timing',plan,{'tier':'tiny','panel_passes':1,'mode':'cold','panel':[1,2,3,4,5,6]}),(1,6))
        self.assertEqual(bd.job_inputs('check',plan,{}),(13230,1))
        self.assertEqual(bd.job_inputs('selftest-suite',plan,{'rows':256,'calls':10}),(256,10))
    def test_estimate_uses_the_selector_share(self):
        t=dict(self.T,selector='m4');e=bd.expected_seconds(POL,t,13230,1,None)
        self.assertAlmostEqual(e,POL['budgets']['estimate_seconds_per_record']['py-reference']*0.15*13230)

class RunStatusTests(unittest.TestCase):
    def test_deadline_failure_invalidates_the_run_with_its_reason(self):
        reasons=bench.deadline_reasons([{'trial_id':'t','warmup':False,'failure_reason':'control-hang','eligible':False}])
        self.assertEqual(reasons,['run-invalid: control-hang'])
    def test_coordinator_kills_the_process_group(self):
        src=(ROOT/'container/bench-coordinator.py').read_text()
        self.assertIn('start_new_session=True',src);self.assertIn('os.killpg',src);self.assertIn("'failure_reason'",src)

import importlib.util
from unittest import mock
_spec=importlib.util.spec_from_file_location('bc_selector',ROOT/'container/bench-coordinator.py');bc=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(bc)
ENV4={'cpus':4,'cpuset':[0,1,2,3],'smt_siblings':[],'reduced':False,'multicore':'PASS'}
DS={'kind':'synthetic','size':'small','seed':20261007,'sha256':None,'rows':256}

class PlanAndRuleTests(unittest.TestCase):
    """Task 1 additions: the planned deadline fields, the remaining refusals and the coordinator's deadline path."""
    def test_plain_plan_trials_carry_selector_all_and_no_deadline(self):
        p=bp.build_plan(CASE,POL,mode='smoke',dataset=DS,seed=1,envelope=ENV4)
        trials=[t for s in p['sessions'] for t in s['trials']]
        self.assertTrue(trials and all(t['selector']=='all' and 'call_deadline_seconds' not in t for t in trials));self.assertNotIn('datasets',p)
    def test_covered_point_trials_carry_the_deadline(self):
        c=copy.deepcopy(CASE);c['points'][0].update(selector='hang',size='small')
        p=bp.build_plan(c,POL,mode='decision',dataset=DS,seed=1,envelope=ENV4)
        t=next(t for s in p['sessions'] for t in s['trials'] if not t['warmup'])
        want=bd.trial_deadline(c,POL,t,256,1,None,POL['budgets']['session_cap_seconds'])
        self.assertEqual((t['selector'],t['call_deadline_seconds'],t['call_deadline_reason']),('hang',want,'control-hang'))
    def test_dataset_ref_points_add_plan_datasets(self):
        got=bp.plan_datasets([{'name':'unit-x-one','dataset_ref':'synthetic:large#panel','panel':[1,2,3,4,5,6]},{'name':'s','dataset_ref':'synthetic:large#row:7'}],POL)
        self.assertEqual(got['synthetic:large#panel']['indices'],[1,2,3,4,5,6]);self.assertEqual(got['synthetic:large#row:7']['rows'],1)
        with self.assertRaises(GateError):bp.plan_datasets([{'dataset_ref':'local:large'}],POL)
    def test_call_deadline_selector_must_be_declared(self):
        c=copy.deepcopy(CASE);c['call_deadline']['selectors']=['other']
        with self.assertRaises(GateError):bm.case_rules(ROOT,c)
    def test_kernel_point_with_a_selector_is_refused(self):
        c=copy.deepcopy(CASE);c['points'][0].update(selector='hang',scope='kernel',modes=['direct'])
        with self.assertRaises(GateError):bm.case_rules(ROOT,c)
    def test_control_case_passes_the_rules_and_the_schema(self):
        self.assertTrue(bm.case_rules(ROOT,CASE));self.assertTrue(validate(ROOT,'bench-case',CASE))
        c=copy.deepcopy(CASE);c['selectors']=['hang']
        with self.assertRaises(GateError):validate(ROOT,'bench-case',c)        # the closed list always holds `all`
    def test_check_outcome_names_the_reason(self):
        self.assertEqual(bench.check_outcome('x','FAIL',{'status':'FAIL','failure_reason':'control-hang'}),('FAIL','bench check x: FAIL control-hang','control-hang'))
        self.assertEqual(bench.check_outcome('x','PASS',{'status':'PASS'}),('PASS','bench check x: PASS',None))
        self.assertEqual(bd.job_reason({'failure_reason':'Bad Text'}),'call-deadline')
    def test_check_text_shows_the_incomplete_count_when_present(self):
        # R1B-02: `bench check` prints incomplete=<n> from the row's counts when the key is present (an integer)
        import argparse, contextlib, io, tempfile
        from unittest import mock
        for counts,text in (({'incomplete_items':1,'item1_checked':3},'bench check x: PASS incomplete=1'),({'incomplete_items':0},'bench check x: PASS incomplete=0'),
                            ({'item1_checked':3},'bench check x: PASS'),({},'bench check x: PASS'),({'incomplete_items':True},'bench check x: PASS'),
                            ({'incomplete_items':'1'},'bench check x: PASS'),(None,'bench check x: PASS')):
            row={'status':'PASS','files':[],**({'counts':counts} if counts is not None else {})}
            with self.subTest(counts=counts),tempfile.TemporaryDirectory() as t,mock.patch.object(bench,'project_arg',return_value='p'),\
                 mock.patch.object(bench,'new_run_dir',return_value=Path(t)),mock.patch.object(bench,'run_check',return_value=('PASS','ev',row)),\
                 contextlib.redirect_stdout(io.StringIO()) as out:
                rc=bench.check_cmd(ROOT,argparse.Namespace(check='x',format='text'))
                self.assertEqual((rc,out.getvalue()),(0,text+'\n'))
        row={'status':'FAIL','files':[],'failure_reason':'control-hang','counts':{'incomplete_items':2}}
        with tempfile.TemporaryDirectory() as t,mock.patch.object(bench,'project_arg',return_value='p'),mock.patch.object(bench,'new_run_dir',return_value=Path(t)),\
             mock.patch.object(bench,'run_check',return_value=('FAIL','ev',row)),contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(bench.check_cmd(ROOT,argparse.Namespace(check='x',format='text')),1)
        self.assertEqual(out.getvalue(),'bench check x: FAIL control-hang incomplete=2\n')
    def test_check_text_names_the_fixed_coordinator_reason(self):
        # T28-APP-04: a FAIL row with a coordinator reason from the fixed vocabulary shows it on the text line; any other
        # reason text (or a reason on a PASS row) is not printed; a call-deadline reason keeps its own form.
        import argparse, contextlib, io, tempfile
        from unittest import mock
        cases=((('FAIL',{'status':'FAIL','reason':'check row has more count keys than the bound'}),'bench check x: FAIL (check row has more count keys than the bound)'),
               (('FAIL',{'status':'FAIL','reason':'undeclared check','counts':{'incomplete_items':1}}),'bench check x: FAIL (undeclared check) incomplete=1'),
               (('FAIL',{'status':'FAIL','reason':'check exceeded its deadline'}),'bench check x: FAIL (check exceeded its deadline)'),
               (('FAIL',{'status':'FAIL','reason':'free text from a module: see /tmp/x'}),'bench check x: FAIL'),
               (('FAIL',{'status':'FAIL','reason':['undeclared check']}),'bench check x: FAIL'),
               (('FAIL',{'status':'FAIL','reason':'call deadline','failure_reason':'control-hang'}),'bench check x: FAIL control-hang'),
               (('PASS',{'status':'PASS','reason':'undeclared check'}),'bench check x: PASS'))
        for (status,row),text in cases:
            row=dict(row,files=[])
            with self.subTest(row=row),tempfile.TemporaryDirectory() as t,mock.patch.object(bench,'project_arg',return_value='p'),\
                 mock.patch.object(bench,'new_run_dir',return_value=Path(t)),mock.patch.object(bench,'run_check',return_value=(status,'ev',row)),\
                 contextlib.redirect_stdout(io.StringIO()) as out:
                rc=bench.check_cmd(ROOT,argparse.Namespace(check='x',format='text'))
                self.assertEqual((rc,out.getvalue()),(bench.EXIT[status],text+'\n'))
    def test_caller_child_kills_the_group_at_the_call_deadline(self):
        class Chan:
            events=[];open={}
            def send(self,client,command):pass
            def pump(self,until,deadline):raise TimeoutError('handshake deadline')
        class Proc:
            pid=4242;returncode=None
            def poll(self):return None
        c=bc.CallerChild.__new__(bc.CallerChild);c.channel=Chan();c.proc=Proc();c.key='py-reference:direct:warm:hang';c.log=Path('/nonexistent');c.foreign=[]
        trial={'trial_id':'t1','call_deadline_seconds':2.0,'call_deadline_reason':'control-hang'}
        with mock.patch.object(bc,'kill_group',return_value=0) as kill,self.assertRaises(bc.DeadlineKilled) as caught:c.call(trial,1,10**9)
        self.assertEqual(caught.exception.reason,'control-hang');kill.assert_called_once_with(c.proc,foreign=c.foreign)
        with mock.patch.object(bc,'kill_group') as kill,self.assertRaises(TimeoutError):c.call({'trial_id':'t2'},1,10**9)   # uncovered: the session rule
        kill.assert_not_called()
    def test_child_key_keeps_the_phase_1_key_for_all(self):
        self.assertEqual(bc.child_key({'variant':'py-threads','workers':2,'mode':'warm'}),'py-threads:2:warm')
        self.assertEqual(bc.child_key({'variant':'py-threads','workers':2,'mode':'warm','selector':'hang'}),'py-threads:2:warm:hang')
        with self.assertRaises(ValueError):bc.child_key({'variant':'v','workers':1,'mode':'warm','selector':'../x'})
    def test_hang_plan_inserts_one_covered_trial_before_a_repeated_row(self):
        plan,hang_id,next_id=bd.hang_plan(ROOT,CASE,POL,ENV4,1)
        trials=[t for s in plan['sessions'] for t in s['trials']];ids=[t['trial_id'] for t in trials];hang=trials[ids.index(hang_id)]
        self.assertEqual(ids[ids.index(hang_id)+1],next_id);self.assertEqual(plan['plan_id'],bench.plan_digest(plan))
        self.assertEqual((hang['selector'],hang['tier'],hang['call_deadline_seconds'],hang['call_deadline_reason']),('hang','tiny',2.0,'control-hang'))
        nxt=trials[ids.index(next_id)];key=lambda t:(t['variant'],t['workers'],t['mode'])
        self.assertTrue(any(key(t)==key(nxt) and not t['warmup'] for t in trials[:ids.index(hang_id)]))
        self.assertEqual(sum('call_deadline_seconds' in t for t in trials),1)
    def test_memory_eligibility_ignores_rows_of_another_selector(self):
        row=lambda **k:dict({'scope':'caller','warmup':False,'variant':'py-reference','workers':'direct','tier':'small','result_sha256':'a'*64,'eligible':True},**k)
        mem=row(scope='memory',eligible=None);obs=[row(),row(selector='hang',eligible=False,tier='tiny',result_sha256=None),mem]
        bench._memory_eligibility(obs);self.assertIs(mem['eligible'],True)
        mem2=row(scope='memory',eligible=None);obs=[row(eligible=False),mem2];bench._memory_eligibility(obs);self.assertIs(mem2['eligible'],False)

class ReviewRound1Tests(unittest.TestCase):
    """Task 1 review round 1 (task-1-review.md): Important 1-2, Minor 1-4 and 6."""
    PLAN={'sizes':POL['sizes'],'dataset':{'kind':'synthetic','rows':13230}}
    def test_every_remaining_table_row_is_pinned(self):
        p=dict(self.PLAN,sessions=[{'tier':'small'},{'tier':'tiny'}],memory=[{'tier':'medium'}])
        self.assertEqual(bd.job_inputs('memory',self.PLAN,{'tier':'medium'}),(1024,1))
        self.assertEqual(bd.job_inputs('reference',p,{}),(1024,1))                # the largest planned tier
        self.assertEqual(bd.job_inputs('reference',self.PLAN,{}),(13230,1))        # nothing planned: the large upper bound
        self.assertEqual(bd.job_inputs('validate',self.PLAN,{}),(256,1))
        self.assertEqual(bd.job_inputs('validate',self.PLAN,{'oracle_edge_rows':12}),(268,1))
        self.assertEqual(bd.job_inputs('panel',self.PLAN,{'selectors':['m1','m4']}),(13230,1))
        self.assertEqual(bd.job_inputs('timing',dict(self.PLAN,dataset={'kind':'local','rows':900}),{'tier':'large','loops':2}),(900,2))
        e=bd.expected_seconds(POL,{'variant':'py-reference','selectors':['m1','m4']},13230,1,None)
        self.assertAlmostEqual(e,POL['budgets']['estimate_seconds_per_record']['py-reference']*(0.05+0.15)*13230)
        with self.assertRaises(GateError):bd.job_inputs('profile',self.PLAN,{})
    @staticmethod
    def _obs(variant,selector,seconds_per_record,blocks=3,size=256):
        out=[]
        for b in range(blocks):
            o={'trial_id':f'{variant}-{selector}-{b}','warmup':False,'eligible':True,'work_units':size,'phase':'caller','workers':'direct','variant':variant,
               'loops':1,'wall_ns':int(seconds_per_record*size*1e9)}
            if selector!='all':o['selector']=selector
            out.append(o)
        return out
    def test_calibration_uses_selector_all_rows_only(self):
        obs=self._obs('py-reference','all',0.2)+self._obs('py-optimized','all',0.01)+self._obs('py-reference','m4',0.03)+self._obs('py-reference','m1',0.01)
        cal=bp.calibration_from_observations(obs,POL)
        self.assertAlmostEqual(cal['py-reference'],0.2);self.assertAlmostEqual(cal['py-optimized'],0.01)
        t={'variant':'py-reference','selector':'m4','tier':'large'};real=0.03*13230      # the true m4 wall of a large trial
        case={'call_deadline':{'selectors':['m4'],'reason':'stub-hang','factor':10,'floor_seconds':60}}
        d=bd.trial_deadline(case,POL,t,13230,1,cal,10**9)
        self.assertGreaterEqual(d/real,10*0.999)          # the share is applied once: the 10x margin holds
    def test_run_deadline_session_expiry_reports_the_declared_reason(self):
        class P:
            pid=99;returncode=-9;n=0
            def __init__(self,*a,**k):pass
            def communicate(self,timeout=None):
                P.n+=1
                if P.n==1:raise bc.subprocess.TimeoutExpired('x',timeout)
                return '',''
        with mock.patch.object(bc.subprocess,'Popen',P),mock.patch.object(bc,'kill_group',return_value=0),self.assertRaises(bc.DeadlineKilled) as caught:
            bc.run_deadline(['x'],{'call_deadline_seconds':600,'call_deadline_reason':'control-hang'},5,{},capture=True)   # the session limit binds
        self.assertEqual(caught.exception.reason,'control-hang')
    def test_kill_group_reaps_or_records_foreign_orphans(self):
        me=os.getpid();members=[[(7001,me)],[]]
        stats={7002:'Z',7003:'S'}
        reaped=[]
        def fake_members(pgid,proc=None):return members.pop(0) if members else []
        class Proc:
            pid=7001
            def wait(self):return -9
        foreign=[]
        with mock.patch.object(bc,'group_members',fake_members),mock.patch.object(bc,'_subreaper',return_value=True),\
             mock.patch.object(bc.os,'killpg'),mock.patch.object(bc,'_children',side_effect=[{8000},{8000,7002,7003}]),\
             mock.patch.object(bc,'_state',side_effect=lambda pid:stats.get(pid)),\
             mock.patch.object(bc.os,'waitpid',side_effect=lambda pid,flags:reaped.append(pid) or (pid,0)):
            left=bc.kill_group(Proc(),grace=1.0,foreign=foreign)
        self.assertEqual(left,0);self.assertIn(7002,reaped);self.assertNotIn(8000,reaped);self.assertEqual(foreign,[7003])
    def test_a_fresh_child_after_a_kill_keeps_the_old_log(self):
        import tempfile
        d=Path(tempfile.mkdtemp());first=bc.fresh_log(d,'py-reference:direct:warm:hang');first.write_text('x')
        second=bc.fresh_log(d,'py-reference:direct:warm:hang')
        self.assertNotEqual(first,second);self.assertFalse(second.exists());self.assertEqual(first.read_text(),'x')
    def test_selftest_plan_contents_are_checked(self):
        plan,hang_id,_=bd.hang_plan(ROOT,CASE,POL,ENV4,3)
        self.assertIs(bd.check_selftest_plan(plan,CASE,POL,ENV4,bench.plan_digest(plan)),plan)
        def edited(change):
            p=copy.deepcopy(plan);change(p);p['plan_id']=bench.plan_digest(p);return p
        hang=lambda p:next(t for s in p['sessions'] for t in s['trials'] if t['trial_id']==hang_id)
        for change in (lambda p:p['sessions'][0]['trials'].pop(-1),lambda p:hang(p).update(call_deadline_seconds=999.0),
                       lambda p:hang(p).update(selector='all'),lambda p:p.update(mode='decision')):
            p=edited(change)
            with self.assertRaises(GateError):bd.check_selftest_plan(p,CASE,POL,ENV4,bench.plan_digest(p))
    def test_run_invalid_reasons_are_not_repeated(self):
        reasons=['x','run-invalid: control-hang']
        self.assertEqual(bench.extend_unique(reasons,['run-invalid: control-hang','run-invalid: other']),['x','run-invalid: control-hang','run-invalid: other'])

class CallDeadlinesTests(unittest.TestCase):
    """Task A2 (Amendment I9.1, I9.2, controller ruling R-A8, PB-02): the union of call-deadline entries, the overlap
    refusal, the larger deadline of a doubly covered job and the arming rule of `bench check`."""
    CASE={'call_deadline':{'selectors':['m4'],'reason':'stub-hang','factor':10,'floor_seconds':60},
          'call_deadlines':[{'selectors':['m5'],'reason':'stub-overrun','factor':10,'floor_seconds':60}]}
    def test_union(self):
        import bench_deadline as bd
        self.assertEqual([e['reason'] for e in bd.entries(self.CASE)],['stub-hang','stub-overrun'])
    def test_overlap_is_refused(self):
        import bench_model as bm
        case=dict(self.CASE,call_deadlines=[{'selectors':['m4'],'reason':'x','factor':10,'floor_seconds':60}])
        with self.assertRaises(Exception) as e:bm.check_call_deadlines(case)
        self.assertIn('overlap',str(e.exception))
    def test_a_job_covered_twice_takes_the_larger_deadline(self):
        import copy, bench_deadline as bd, bench_model as bm
        pol=copy.deepcopy(bm.load_policy(ROOT,FIXTURE));pol['budgets']['estimate_share_per_selector']['m5']=1.5     # test share only
        case=copy.deepcopy(self.CASE);case['call_deadlines'][0]['factor']=20
        plan={'sizes':pol['sizes'],'dataset':{'kind':'synthetic'}};job={'variant':'py-reference','selectors':['m4','m5']}
        e=bd.expected_seconds(pol,job,pol['sizes']['large'],1,None)
        f=bd.deadline_fields(case,pol,'panel',plan,job,None,10**7)        # the landed signature (case, policy, job, plan, trial, calibration, session_remaining)
        self.assertEqual((f['call_deadline_seconds'],f['call_deadline_reason']),(max(60.0,20*e),'stub-overrun'))
        case['call_deadlines'][0]['factor']=10
        self.assertEqual(bd.deadline_fields(case,pol,'panel',plan,job,None,10**7)['call_deadline_reason'],'stub-hang')   # tie: declaration order
    def job_of(self,name,deadline_key,policy):
        import bench, tempfile
        from evidence import GateError
        from unittest import mock
        jobs=[]
        class S:
            evidence_paths=[]
            def __init__(self,*a,**k):pass
            def job(self,job,name,deadline,restore=()):jobs.append(job);raise GateError('stop after the job dict')
            def close(self):pass
        tmp=Path(tempfile.mkdtemp());project=fixture_stub_project()[0]     # found by declaration: a framework test names no example
        with mock.patch('bench.BenchSession',S),mock.patch('bench.bm.load_policy',return_value=policy):
            with self.assertRaises(GateError):bench.run_check(ROOT,tmp,project,name,(),deadline_key)
        return jobs[0]
    def test_only_declared_checks_below_the_job_limit_are_armed(self):
        import copy, bench_model as bm, bench_deadline as bd
        pol=bm.load_policy(ROOT,FIXTURE);big=copy.deepcopy(pol);big['job_deadlines']['smoke']=10800
        e=bd.expected_seconds(pol,{'variant':'py-reference','selectors':['m4']},pol['sizes']['large'],1,None);d=max(60.0,10*e)
        armed=self.job_of('hang-stub','smoke',big)
        self.assertEqual((armed['call_deadline_seconds'],armed['call_deadline_reason']),(d,'stub-hang'))     # d < 10,800 - 30
        if d>=pol['job_deadlines']['smoke']-30:self.assertNotIn('call_deadline_seconds',self.job_of('hang-stub','smoke',pol))   # the job limit governs
        self.assertNotIn('call_deadline_seconds',self.job_of('oracle-generate','long_check',pol))    # declares no selector: job limit only

class CallDeadlinesBoundaryTests(unittest.TestCase):
    """Added by the implementer: the schema bounds of call_deadlines and check selectors, the undeclared-selector and
    unapproved-share rules, and the container's re-check of bench.json (post-approval ruling PC-01)."""
    ENTRY={'selectors':['hang2'],'reason':'other-hang','factor':10,'floor_seconds':60}
    def test_schema_bounds(self):
        c=copy.deepcopy(CASE);c['selectors']=c['selectors']+['hang2'];c['call_deadlines']=[self.ENTRY]
        self.assertTrue(validate(ROOT,'bench-case',c));self.assertTrue(bm.case_rules(ROOT,c))
        for bad in ([self.ENTRY]*9,[dict(self.ENTRY,extra=1)],[dict(self.ENTRY,factor=0.5)],{'x':1}):
            with self.subTest(bad=str(bad)[:40]),self.assertRaises(GateError):validate(ROOT,'bench-case',dict(c,call_deadlines=bad))
        c['call_deadlines']=[dict(self.ENTRY,selectors=['nope'])]
        with self.assertRaises(GateError):bm.case_rules(ROOT,c)                 # an entry names an undeclared selector
        c['call_deadlines']=[dict(self.ENTRY,selectors=['hang'])]
        with self.assertRaises(GateError) as e:bm.case_rules(ROOT,c)            # overlaps the landed call_deadline
        self.assertEqual(str(e.exception),'call deadline selectors overlap: hang')
    def test_entries_without_any_declaration(self):
        self.assertEqual(bd.entries({}),[]);self.assertIsNone(bd.covering_deadline({},POL,{'variant':'py-reference','selector':'hang'},1,1,None,100))
        self.assertEqual(bd.entries({'call_deadlines':[self.ENTRY]}),[self.ENTRY])
    def test_covering_deadline_is_capped_by_the_session(self):
        case={'call_deadlines':[self.ENTRY]};t={'variant':'py-reference','selector':'hang2'}
        self.assertEqual(bd.covering_deadline(case,POL,t,1,1,None,10_000),(60.0,'other-hang'))
        self.assertEqual(bd.covering_deadline(case,POL,t,1,1,None,1.5),(1.5,'other-hang'))
        self.assertEqual(bd.trial_deadline(case,POL,t,1,1,None,10_000),60.0)
    def test_check_selectors_in_the_project_schema(self):
        decl={'schema_version':1,'name':'demo','cases':['demo-case'],'checks':[{'name':'one-check','module':'m.c','before_run':False,'selectors':['m4']}]}
        self.assertTrue(validate(ROOT,'bench-project',decl))
        for bad in ([],['Bad'],['a']*9,['a','a'],'m4'):
            d=copy.deepcopy(decl);d['checks'][0]['selectors']=bad
            with self.subTest(bad=bad),self.assertRaises(GateError):validate(ROOT,'bench-project',d)
        d=copy.deepcopy(decl);d['checks'][0]['other']=1
        with self.assertRaises(GateError):validate(ROOT,'bench-project',d)
    def test_coordinator_accepts_check_selectors_and_refuses_other_keys(self):
        import tempfile
        d=Path(tempfile.mkdtemp());(d/'p/benchmarks/project/python').mkdir(parents=True)
        saved=(bc.SRC,bc.PYTHONPATH,bc.PROJECT_PY,bc.PROJECT_ROOT,list(sys.path))
        def write(entry):(d/'p/benchmarks/project/bench.json').write_text(json.dumps({'schema_version':1,'name':'demo','cases':['demo-case'],'checks':[entry]}))
        base={'name':'one-check','module':'m.c','before_run':False}
        try:
            bc.SRC=d;bc.configure_project({'project_dir':'p'})
            write(dict(base,selectors=['m4']));self.assertEqual(bc.project_checks(),[dict(base,selectors=['m4'])])
            write(base);self.assertEqual(bc.project_checks(),[base])
            for bad in ({'extra':1},{'selectors':[]},{'selectors':['Bad Name']},{'selectors':['a']*9},{'selectors':['a','a']},{'selectors':'m4'},{'selectors':[1]}):
                write(dict(base,**bad))
                with self.subTest(bad=bad):
                    self.assertIsNone(bc.project_checks())
                    self.assertEqual(bc.job_check({'check':'one-check','deadline_seconds':100},d),{'status':'FAIL','reason':'bench.json is missing or malformed'})
        finally:bc.SRC,bc.PYTHONPATH,bc.PROJECT_PY,bc.PROJECT_ROOT=saved[:4];sys.path[:]=saved[4]
    def test_coordinator_check_count_bound_is_the_schema_bound(self):
        # Branch join (2026-10-12): the container re-check of bench.json takes the bench-project schema's checks
        # maxItems (32 since 9dcb0e8), so 17 and 32 checks are accepted and 33 are refused.
        import tempfile
        bound=json.loads((ROOT/'schemas/bench-project.json').read_text())['properties']['checks']['maxItems']
        self.assertEqual(bound,32)
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);(d/'p/benchmarks/project/python').mkdir(parents=True)
            saved=(bc.SRC,bc.PYTHONPATH,bc.PROJECT_PY,bc.PROJECT_ROOT,list(sys.path))
            def write(n):
                checks=[{'name':f'check-{k:02d}','module':'m.c','before_run':False} for k in range(n)]
                (d/'p/benchmarks/project/bench.json').write_text(json.dumps({'schema_version':1,'name':'demo','cases':['demo-case'],'checks':checks}))
                return checks
            try:
                bc.SRC=d;bc.configure_project({'project_dir':'p'})
                for n in (16,17,bound):
                    checks=write(n)
                    with self.subTest(n=n):self.assertEqual(bc.project_checks(),checks)
                write(bound+1);self.assertIsNone(bc.project_checks())
            finally:bc.SRC,bc.PYTHONPATH,bc.PROJECT_PY,bc.PROJECT_ROOT=saved[:4];sys.path[:]=saved[4]
    def test_an_unapproved_required_share_leaves_a_check_unarmed(self):
        import bench as b
        pol=copy.deepcopy(POL);pol['budgets']['share_required']=['m4'];del pol['budgets']['estimate_share_per_selector']['m4']
        pol['job_deadlines']['smoke']=10800
        project,case=fixture_stub_project()
        self.assertIsNone(b.check_call_deadline(case,pol,['m4'],'smoke'))
        self.assertIsNotNone(b.check_call_deadline(case,POL|{'job_deadlines':pol['job_deadlines']},['m4'],'smoke'))
        self.assertIsNone(b.check_call_deadline(case,POL,[],'smoke'))

class CallDeadlineReapedTests(unittest.TestCase):
    """P3-T15-REAPED-FLAKY-01 (diagnosis D1 section 10.8, ruling D1-R2(a)): suite `call-deadline` judges the reap from the
    killed group itself (the coordinator's deadline_kills row of the hang trial: left 0, foreign_orphans 0, the timing
    session complete), never from the process count of the next trial, which a pool row changes without any kill (42-48
    observed; run 1aaeb1ad FAILED on 45 against 46). A surviving member of the killed group still FAILS. The suite runs on
    a recorded-shape run: hang_plan, the run, the two check jobs and the host topology are replaced, nothing starts."""
    S='control-small-s00';HANG=S+'-hang';NEXT=S+'-b01-00'
    def row(self,trial_id,variant,workers,pids,**extra):
        return dict({'trial_id':trial_id,'warmup':False,'scope':'caller','variant':variant,'workers':workers,'mode':'warm','pids_end':pids},**extra)
    def suite(self,*,earlier,nxt,kills,reasons=()):
        import tempfile, shutil, container_policy
        root=Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,root,True);rid='a'*32;run=root/'artifacts/bench'/rid;(run/'evidence').mkdir(parents=True)
        timing=run/'evidence'/f'0007-timing-{self.S}.json'
        job_row={'status':'PASS' if not reasons else 'FAIL',**({'deadline_kills':kills} if kills is not None else {})}
        timing.write_text(json.dumps({'output':'coordinator log\n'+json.dumps(job_row)+'\n'}))
        (run/'run.json').write_text(json.dumps({'status':'INVALID_EXPERIMENT','failure_reasons':['control-hang'],
                                                'reasons':['run-invalid: control-hang',*reasons],'evidence':{'jobs':[str(timing)]}}))
        obs=[self.row(self.S+'-b00-00','py-threads',2,earlier),
             self.row(self.HANG,'py-reference','direct',42,selector='hang',eligible=False,verdict={'failures':{'call-deadline':1}},failure_reason='control-hang'),
             self.row(self.NEXT,'py-threads',2,nxt)]
        (run/'observations.jsonl').write_text(''.join(json.dumps(o)+'\n' for o in obs))
        plan={'sessions':[{'session':self.S,'trials':[{'trial_id':self.S+'-b00-00'},{'trial_id':self.HANG,'call_deadline_seconds':2.0},{'trial_id':self.NEXT}]}]}
        def check(root_,run_dir,case,policy,selector):
            return ('FAIL','check FAIL control-hang','control-hang','p1') if selector=='hang' else ('PASS','PASS',None,'p2')
        with mock.patch.object(bm,'load_policy',return_value=POL),mock.patch.object(bm,'load_case',return_value=CASE),\
             mock.patch.object(container_policy,'host_topology',return_value=((0,1,2,3),[])),mock.patch.object(container_policy,'choose_envelope',return_value=ENV4),\
             mock.patch.object(bd,'hang_plan',return_value=(plan,self.HANG,self.NEXT)),mock.patch.object(bench,'_quiet',return_value=(1,{'run_id':rid})),\
             mock.patch.object(bd,'_control_check',side_effect=check):
            return bd.selftest_suite(root,root/'selftest-run')
    def kill(self,left=0,foreign=0,trial_id=None):return [{'trial_id':trial_id or self.HANG,'left':left,'foreign_orphans':foreign}]
    def test_a_pool_row_as_the_next_trial_does_not_change_the_verdict(self):
        for earlier,nxt in ((46,45),(42,48),(48,42),(42,42)):          # 46/45: run 1aaeb1ad; 42 = 42: the passing run 7d68e75b
            with self.subTest(earlier=earlier,next=nxt):
                out=self.suite(earlier=earlier,nxt=nxt,kills=self.kill())
                self.assertEqual((out['status'],out['reaped']),('PASS',True))
    def test_a_surviving_member_of_the_killed_group_still_fails(self):
        for reasons in ((f'timing session {self.S} did not complete',),()):   # the coordinator marks the session; the kill row alone also fails
            with self.subTest(reasons=reasons):
                out=self.suite(earlier=42,nxt=42,kills=self.kill(left=1),reasons=reasons)   # equal next-trial counts never hide a survivor
                self.assertEqual((out['status'],out['reaped']),('FAIL',False))
    def test_a_foreign_orphan_a_missing_or_foreign_kill_row_fails(self):
        for kills in (self.kill(foreign=1),None,[],self.kill(trial_id=self.NEXT),self.kill()+self.kill(trial_id=self.NEXT),[{'trial_id':self.HANG}]):
            with self.subTest(kills=kills):
                out=self.suite(earlier=42,nxt=42,kills=kills)
                self.assertEqual((out['status'],out['reaped']),('FAIL',False))
    def test_kill_counts_must_be_integers(self):
        # F1-REAP-TYPE-01: False or 0.0 never stands for "no member left"
        for left,foreign in ((False,0),(0.0,0),(0,False),(0,0.0),('0',0),(None,0)):
            with self.subTest(left=left,foreign=foreign):
                out=self.suite(earlier=42,nxt=42,kills=[{'trial_id':self.HANG,'left':left,'foreign_orphans':foreign}])
                self.assertEqual((out['status'],out['reaped']),('FAIL',False))
    def test_an_incomplete_timing_session_fails(self):
        out=self.suite(earlier=42,nxt=42,kills=self.kill(),reasons=(f'timing session {self.S} did not complete',))
        self.assertEqual((out['status'],out['reaped']),('FAIL',False))
