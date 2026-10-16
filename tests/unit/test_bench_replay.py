import argparse, json, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import bench, bench_evidence as be, bench_model as bm, bench_replay as br
from evidence import file_hash

def current_run(**over):
    run={'run_id':'a'*32,'case':'bench-control-spin','case_version':bm.load_case(ROOT,'bench-control-spin')['version'],'mode':'smoke','status':'VALID','policy_sha256':file_hash(ROOT/'safety/performance-policy.json'),
         'image_id':json.loads((ROOT/'developer.lock.json').read_text())['image_id'],'bench_profile_sha256':be.bench_profile_sha256(ROOT),
         'plan':{'project_dir':None,'project_identity':None},'dataset':{'kind':'synthetic','size':'small'}}
    run.update(over);return run

class AuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.plan={'plan_id':'p','mode':'smoke','dataset':{'kind':'synthetic','size':'small'},'project_dir':None}
        self.patches=[mock.patch('bench.plan_digest',return_value='p'),mock.patch('bench_evidence.verify',return_value=[])]
        for p in self.patches:p.start()
    def tearDown(self):
        for p in self.patches:p.stop()
    def test_current_run_is_authorized(self):
        self.assertEqual(br.authorization(ROOT,Path('/x'),current_run(),self.plan),[])
    def test_changed_profile_blocks(self):
        self.assertIn('bench profile changed since the run',br.authorization(ROOT,Path('/x'),current_run(bench_profile_sha256='0'*64),self.plan))
    def test_missing_profile_blocks(self):
        r=current_run();r.pop('bench_profile_sha256');self.assertIn('the run predates the recorded bench profile',br.authorization(ROOT,Path('/x'),r,self.plan))
    def test_policy_image_and_case_changes_block(self):
        got=br.authorization(ROOT,Path('/x'),current_run(policy_sha256='0'*64,image_id='sha256:'+'0'*64,case_version=99),self.plan)
        for r in ('performance policy changed since the run','image changed since the run','case version changed since the run'):self.assertIn(r,got)
    def test_rewritten_plan_blocks(self):
        with mock.patch('bench.plan_digest',return_value='other'):self.assertIn('recorded plan changed',br.authorization(ROOT,Path('/x'),current_run(),self.plan))
    def test_unbound_run_is_never_replayed(self):
        with mock.patch('bench_evidence.verify',return_value=[be.UNBOUND]):
            self.assertIn('unbound runs are never replayed',br.authorization(ROOT,Path('/x'),current_run(),self.plan))

class ReplayCommandTests(unittest.TestCase):
    def test_replay_creates_a_new_run_and_never_copies(self):
        calls=[];written=[]
        def fake_run(root,args):calls.append(args);written.append(json.loads(Path(args.plan).read_text()));return 0
        with tempfile.TemporaryDirectory() as t:
            old=Path(t)/'old';old.mkdir();(old/'plan.json').write_text(json.dumps({'plan_id':'p','mode':'smoke','dataset':{'kind':'synthetic','size':'small'}}))
            (old/'observations.jsonl').write_text('')
            with mock.patch('bench._run_dir',return_value=old),mock.patch('bench.read_json',side_effect=lambda p:current_run() if p.name=='run.json' else json.loads(Path(p).read_text())),\
                 mock.patch('bench_replay.authorization',return_value=[]),mock.patch('bench.run_cmd',side_effect=fake_run):
                rc=br.replay_cmd(ROOT,argparse.Namespace(run_id='a'*32,dataset=None,format='json'))
        # T20-C1: the plan reaches run_cmd from a temporary file outside the old run directory, holding the recorded plan
        # without RUN_ADDED_PLAN_KEYS (the brief asserted calls[0].plan == str(old/'plan.json'))
        self.assertNotIn(old,Path(calls[0].plan).parents);self.assertEqual(written[0],{'plan_id':'p','mode':'smoke','dataset':{'kind':'synthetic','size':'small'}})
        self.assertEqual(calls[0].replay_of,'a'*32);self.assertEqual(calls[0].dataset,'synthetic:small')
        self.assertEqual(rc,1)    # no new run found -> FAIL, never a copied result
    def test_unauthorized_is_blocked(self):
        with mock.patch('bench._run_dir',return_value=Path('/x')),mock.patch('bench.read_json',return_value=current_run()),\
             mock.patch('bench_replay._read_plan',return_value={}),mock.patch('bench_replay.authorization',return_value=['image changed since the run']):
            self.assertEqual(br.replay_cmd(ROOT,argparse.Namespace(run_id='a'*32,dataset=None,format='json')),2)
    def test_registered(self):self.assertIn('replay',bench.HANDLERS)

# ---- Rulings T20-C1 and T20-C2 (controller): the plan identity without the run-added keys, a real recorded run, the
# run.json binding, the run lock, the created run id, a local replay and the project-instance refusal ----
import contextlib, io, uuid
import bench_plan as bp, container_policy
from evidence import GateError
sys.path.insert(0,str(ROOT/'tests/unit'));import test_bench_guardrails as tg, test_bench_privacy as tp

def recorded_smoke_run(d,run_id='a'*32):
    """A recorded run of the smoke shape: the control-case plan of build_plan with the keys bench run adds (project_dir,
    pyperf), its timed row, digest-bound files and a run.json bound by its record digest."""
    case=bm.load_case(ROOT,'bench-control-spin');pol=bm.load_policy(ROOT)
    plan=bp.build_plan(case,pol,mode='smoke',dataset=bp.parse_dataset(ROOT,'synthetic:small',pol),seed=7,envelope=tg.ENV)
    plan['project_dir']=None;plan['pyperf']={'values':1,'warmups':0}
    rd=Path(d)/run_id;rd.mkdir();(rd/'plan.json').write_text(json.dumps(plan,sort_keys=True))
    (rd/'observations.jsonl').write_text(json.dumps(timed(run_id,1000))+'\n');(rd/'phases.jsonl').write_text('')
    run=current_run(run_id=run_id,plan={'plan_id':plan['plan_id'],'project_dir':None,'project_identity':None})
    run['evidence_digests']=be.digest_files(rd);run[be.RECORD_KEY]=be.run_record_sha256(run);(rd/'run.json').write_text(json.dumps(run))
    return rd,run,json.loads((rd/'plan.json').read_text())
def timed(run_id,wall):return {'run_id':run_id,'trial_id':'t0','scope':'caller','warmup':False,'wall_ns':wall,'cpu_usage_usec':5}
def new_run(d,new_id,replay_of,rows):
    nd=Path(d)/new_id;nd.mkdir();(nd/'observations.jsonl').write_text(''.join(json.dumps(o)+'\n' for o in rows))
    r=dict(current_run(run_id=new_id),replay_of=replay_of);r[be.RECORD_KEY]=be.run_record_sha256(r);(nd/'run.json').write_text(json.dumps(r))
def ask(d,fake_run,run_id='a'*32,**more):
    out=io.StringIO()
    with mock.patch('bench._run_dir',side_effect=lambda root,i:Path(d)/i),mock.patch('bench.run_cmd',side_effect=fake_run),contextlib.redirect_stdout(out):
        rc=br.replay_cmd(ROOT,argparse.Namespace(run_id=run_id,dataset=more.get('dataset'),format='json'))
    return rc,json.loads(out.getvalue().strip().splitlines()[-1])

class PlanIdentityTests(unittest.TestCase):                           # T20-C1
    def test_a_recorded_smoke_run_is_authorized(self):
        with tempfile.TemporaryDirectory() as d:
            rd,run,plan=recorded_smoke_run(d)
            self.assertEqual(br.RUN_ADDED_PLAN_KEYS,('pyperf',))          # FR3: the market key left with the market step
            self.assertNotEqual(bench.plan_digest(plan),plan['plan_id'])                 # bench run added pyperf after plan_id
            with self.assertRaisesRegex(GateError,'edited'):bench.verify_written_plan(bm.load_case(ROOT,'bench-control-spin'),bm.load_policy(ROOT),plan,plan['envelope'],None,None,root=ROOT)
            self.assertEqual(bench.plan_digest(br.plan_body(plan)),plan['plan_id'])
            self.assertEqual(br.authorization(ROOT,rd,run,plan),[])
    def test_a_change_outside_the_run_added_keys_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            rd,run,plan=recorded_smoke_run(d)
            for k in sorted(set(plan)-{'plan_id','project_dir'}-set(br.RUN_ADDED_PLAN_KEYS)):
                with self.subTest(key=k):self.assertIn('recorded plan changed',br.authorization(ROOT,rd,run,dict(plan,**{k:{'changed':k}})))
            for k in br.RUN_ADDED_PLAN_KEYS:                                              # outside the plan identity ...
                with self.subTest(key=k):self.assertNotIn('recorded plan changed',br.authorization(ROOT,rd,run,dict(plan,**{k:{'changed':k}})))
    def test_a_change_inside_the_run_added_keys_is_caught_by_the_file_digest(self):       # ... and bound by the plan.json digest
        with tempfile.TemporaryDirectory() as d:
            rd,run,plan=recorded_smoke_run(d)
            for k in br.RUN_ADDED_PLAN_KEYS:
                with self.subTest(key=k):
                    (rd/'plan.json').write_text(json.dumps(dict(plan,**{k:{'values':3,'warmups':1}}),sort_keys=True));got=json.loads((rd/'plan.json').read_text())
                    self.assertEqual(br.authorization(ROOT,rd,run,got),['recorded evidence changed: changed after the run: plan.json'])
                    (rd/'plan.json').write_text(json.dumps(plan,sort_keys=True))
    def test_a_recorded_smoke_run_replays_to_pass(self):
        with tempfile.TemporaryDirectory() as d:
            rd,run,plan=recorded_smoke_run(d);before={p.name:p.read_bytes() for p in rd.iterdir()};seen={}
            def fake_run(root,args):
                p=Path(args.plan);seen.update(outside=rd not in p.parents,plan=json.loads(p.read_text()))
                bench.verify_written_plan(bm.load_case(ROOT,args.case),bm.load_policy(ROOT),seen['plan'],seen['plan']['envelope'],None,None,root=ROOT)   # run_cmd's check accepts it
                new_run(d,'b'*32,args.replay_of,[timed('b'*32,1200)]);args.created_run_id='b'*32;return 0
            rc,row=ask(d,fake_run)
            self.assertEqual((rc,row['status'],row['run_id'],row['replay_of'],row['reasons']),(0,'PASS','b'*32,'a'*32,[]))
            self.assertTrue(seen['outside']);self.assertEqual(seen['plan'],br.plan_body(plan))
            self.assertEqual({p.name:p.read_bytes() for p in rd.iterdir()},before)       # nothing in the old run directory changed

class BindingTests(unittest.TestCase):                                # T20-C2
    def test_a_tampered_run_record_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            rd,run,plan=recorded_smoke_run(d);edited=dict(run,bench_profile_sha256=run['bench_profile_sha256']);edited['status']='INVALID_EXPERIMENT'
            (rd/'run.json').write_text(json.dumps(edited))
            self.assertEqual(br.authorization(ROOT,rd,edited,plan),['recorded evidence changed: changed after the run: run.json'])
            rc,row=ask(d,lambda root,args:self.fail('no run may start'))
            self.assertEqual((rc,row['status']),(2,'BLOCKED'))
    def test_the_old_run_is_read_under_its_run_lock(self):
        state={'held':False,'entered':[],'reads':[]}
        @contextlib.contextmanager
        def lock(run_id):
            state['held']=True;state['entered'].append(run_id)
            try:yield
            finally:state['held']=False
        def read(*a):state['reads'].append(state['held'])
        def fake_run(root,args):state['run_held']=state['held'];return 0
        with tempfile.TemporaryDirectory() as t:
            old=Path(t)/'old';old.mkdir();(old/'observations.jsonl').write_text('')
            with mock.patch('bench_evidence.run_lock',lock),mock.patch('bench._run_dir',return_value=old),mock.patch('bench.read_json',side_effect=lambda p:read() or current_run()),\
                 mock.patch('bench_replay._read_plan',side_effect=lambda p:read() or {'plan_id':'p','mode':'smoke','dataset':{'kind':'synthetic','size':'small'}}),\
                 mock.patch('bench_replay.authorization',side_effect=lambda *a:read() or []),mock.patch('bench.read_jsonl',side_effect=lambda p:read() or []),\
                 mock.patch('bench.run_cmd',side_effect=fake_run),contextlib.redirect_stdout(io.StringIO()):
                br.replay_cmd(ROOT,argparse.Namespace(run_id='a'*32,dataset=None,format='json'))
        self.assertEqual(state['entered'],['a'*32]);self.assertEqual(state['reads'],[True]*4);self.assertIs(state['run_held'],False)
    def test_the_replay_uses_the_run_id_that_bench_run_creates(self):
        with tempfile.TemporaryDirectory() as d:
            recorded_smoke_run(d);new_run(d,'c'*32,'a'*32,[timed('c'*32,1500)])           # a newer run of this replay that bench run did not create now
            rc,row=ask(d,lambda root,args:0)
            self.assertEqual((rc,row['status']),(1,'FAIL'));self.assertNotIn('run_id',row)
            def other(root,args):new_run(d,'b'*32,'f'*32,[timed('b'*32,1200)]);args.created_run_id='b'*32;return 0
            rc,row=ask(d,other)                                                             # the created run names another run
            self.assertEqual((rc,row['status'],row['run_id']),(1,'FAIL','b'*32));self.assertTrue(any('replay_of' in r for r in row['reasons']))
    def test_copied_numbers_fail(self):
        with tempfile.TemporaryDirectory() as d:
            recorded_smoke_run(d)
            def copy(root,args):new_run(d,'b'*32,args.replay_of,[timed('b'*32,1000)]);args.created_run_id='b'*32;return 0
            rc,row=ask(d,copy);self.assertEqual((rc,row['status']),(1,'FAIL'));self.assertIn('replay copied the recorded numbers',row['reasons'])
    def test_a_local_replay_needs_its_dataset_and_is_refused_in_a_project_instance(self):
        local={'plan_id':'p','mode':'smoke','dataset':{'kind':'local','size':None,'seed':None,'sha256':'a'*64,'rows':None},'project_dir':None}
        calls=[]
        def fake_run(root,args):calls.append(args.dataset);return 0
        with tempfile.TemporaryDirectory() as t:
            old=Path(t)/'old';old.mkdir()
            with mock.patch('bench._run_dir',return_value=old),mock.patch('bench.read_json',return_value=current_run()),mock.patch('bench_replay._read_plan',return_value=local),\
                 mock.patch('bench_replay.authorization',return_value=[]),mock.patch('bench.run_cmd',side_effect=fake_run),contextlib.redirect_stdout(io.StringIO()) as out:
                ns=lambda ds:argparse.Namespace(run_id='a'*32,dataset=ds,format='json')
                with mock.patch('bench_privacy.is_project_instance',return_value=True):self.assertEqual(br.replay_cmd(ROOT,ns('local:/x')),2)
                self.assertIn('project instance',out.getvalue());self.assertEqual(calls,[])
                with mock.patch('bench_privacy.is_project_instance',return_value=False):
                    with self.assertRaisesRegex(GateError,'--dataset local'):br.replay_cmd(ROOT,ns(None))
                    self.assertEqual(br.replay_cmd(ROOT,ns('local:/x')),1)              # no run created -> FAIL
                self.assertEqual(calls,['local:/x'])

def local_run(replay_of):
    """bench_privacy.run_local with the harness of test_bench_privacy.LocalCollectionTests and a passing aggregate."""
    import shutil
    with tempfile.TemporaryDirectory() as d:
        root=Path(d);shutil.copytree(ROOT/'schemas',root/'schemas');(root/'safety').mkdir();shutil.copytree(ROOT/tp.FIXTURE,root/tp.FIXTURE)
        for name in ('safety/performance-policy.json','safety/performance-fixtures.json','developer.lock.json','safety/container-policy.json'):shutil.copy(ROOT/name,root/name)
        doc=tp.closed_aggregate()             # FR3: the summary follows the fixture project's protocol aggregate schema
        class Runner:
            session=None
            def run(self,*a,**k):return {'exit_code':0,'failure':None}
        class Session:
            image=staticmethod(lambda root:'sha256:'+'e'*64)
            def __init__(self,*a,**k):self.runner=Runner()
            def job(self,plan,*a,**k):return {'exit_code':0,'failure':None,'evidence_path':'x'}
            def fetch(self,rel,dst):Path(dst).write_text(json.dumps(doc));return dst
            def close(self):pass
        plan={'mode':'smoke','project_dir':tp.FIXTURE,'dataset':{'kind':'local','size':None,'seed':None,'sha256':'a'*64,'rows':None,'path':'/private/dataset.json'},
              'sessions':[{'tier':'small','trials':[]}],'pyperf':{'values':1,'warmups':0},'plan_id':'p','plan_version':'v1'}
        args=argparse.Namespace(format='json',**({'replay_of':replay_of} if replay_of else {}))
        with mock.patch.object(bench,'before_run_checks',return_value=([],[])),mock.patch.object(bench,'BenchSession',Session),\
             mock.patch.object(bench,'doctor_probe',tp.PERMITTED_PROBE),mock.patch.object(bench,'guardrail_gate',tp.PERMITTED_GATE),\
             mock.patch('policy.source_identity',return_value=('f'*64,None)),contextlib.redirect_stdout(io.StringIO()),\
             mock.patch.object(tp.bp,'install_fixture_pattern',return_value=True):   # Task 27 pattern step
            rc=tp.bp.run_local(root,args,plan,{'case_id':'record-scan','version':1},{'sizes':{'small':256},'job_deadlines':{'session':10800}})
        return rc,json.loads(next(root.glob('artifacts/bench/*/run.json')).read_text()),args

class RunRecordTests(unittest.TestCase):
    def test_a_local_replay_records_replay_of(self):                 # T20-C2: run_local, as run_cmd
        rc,run,args=local_run('a'*32)
        self.assertEqual((rc,run['replay_of'],args.created_run_id),(0,'a'*32,run['run_id']));self.assertEqual(be.verify_record(run),[])
        rc,run,args=local_run(None);self.assertNotIn('replay_of',run);self.assertEqual(args.created_run_id,run['run_id'])
    def test_a_replay_through_bench_run_creates_a_new_bound_run_that_names_the_old_one(self):
        with tempfile.TemporaryDirectory() as d:
            def new_run_dir(root,kind):p=Path(d)/uuid.uuid4().hex;p.mkdir();return p
            probe=dict({'status':'PASS','envelope':tg.ENV,'evidence_paths':[],'lock_held_ns':0,'runtime':{}},**tg.DOC);probe['cpu_max']='100000 100000'    # BLOCKED: no trial container
            out=io.StringIO()
            with mock.patch.object(container_policy,'host_topology',lambda:(4,[0,1,2,3],[])),mock.patch.object(container_policy,'choose_envelope',lambda *a,**k:tg.ENV),\
                 mock.patch.object(bench,'new_run_dir',new_run_dir),mock.patch.object(bench,'doctor_probe',lambda root,rd:dict(probe)),\
                 mock.patch.object(bench,'before_run_checks',lambda *a:([],[])),mock.patch.object(bench,'BenchSession',tg.NoSession),\
                 mock.patch.object(tg.tba.policy_module,'source_identity',lambda root:('0'*64,[])),mock.patch('bench._run_dir',side_effect=lambda root,i:Path(d)/i),\
                 contextlib.redirect_stdout(out):
                code=bench.run_cmd(ROOT,argparse.Namespace(case='bench-control-spin',plan=None,project=None,format='json',mode='smoke',dataset='synthetic:small',calibrate=None))
                old=json.loads(out.getvalue().strip().splitlines()[-1])['run_id'];oldrun=json.loads((Path(d)/old/'run.json').read_text())
                rc=br.replay_cmd(ROOT,argparse.Namespace(run_id=old,dataset=None,format='json'))
            row=json.loads(out.getvalue().strip().splitlines()[-1]);new=row['run_id'];newrun=json.loads((Path(d)/new/'run.json').read_text())
        self.assertEqual(code,2);self.assertNotIn('replay_of',oldrun);self.assertNotEqual(new,old)
        self.assertEqual((rc,row['status'],row['replay_of']),(2,'BLOCKED',old))             # a BLOCKED run replays to a BLOCKED run, never PASS
        self.assertEqual((newrun['replay_of'],newrun['plan']['plan_id']),(old,oldrun['plan']['plan_id']));self.assertEqual(be.verify_record(newrun),[])

class NewRunCheckTests(unittest.TestCase):                            # T20-APP-01: each new-run check of replay_cmd is pinned
    def test_an_edited_new_run_record_fails(self):
        with tempfile.TemporaryDirectory() as d:
            recorded_smoke_run(d)
            def edited(root,args):
                new_run(d,'b'*32,args.replay_of,[timed('b'*32,1200)]);p=Path(d)/('b'*32)/'run.json';r=json.loads(p.read_text())
                r['status']='INVALID_EXPERIMENT';p.write_text(json.dumps(r));args.created_run_id='b'*32;return 0     # edited after its record digest
            rc,row=ask(d,edited)
            self.assertEqual((rc,row['status'],row['run_id'],row['reasons']),(1,'FAIL','b'*32,[be.RECORD_CHANGED]))
    def test_a_created_run_id_equal_to_the_old_id_fails(self):
        with tempfile.TemporaryDirectory() as d:
            recorded_smoke_run(d)
            def reused(root,args):          # bench run reports the old id and rewrites that directory with a consistent new record
                od=Path(d)/args.replay_of;(od/'observations.jsonl').write_text(json.dumps(timed('b'*32,1200))+'\n')
                r=dict(current_run(run_id=args.replay_of),replay_of=args.replay_of);r[be.RECORD_KEY]=be.run_record_sha256(r);(od/'run.json').write_text(json.dumps(r))
                args.created_run_id=args.replay_of;return 0
            rc,row=ask(d,reused)
            self.assertEqual((rc,row['status'],row['run_id'],row['reasons']),(1,'FAIL','a'*32,['replay reused the run identity']))
    def test_a_new_run_that_exits_1_fails(self):
        with tempfile.TemporaryDirectory() as d:
            recorded_smoke_run(d)
            def failed(root,args):new_run(d,'b'*32,args.replay_of,[timed('b'*32,1200)]);args.created_run_id='b'*32;return 1
            rc,row=ask(d,failed)
            self.assertEqual((rc,row['status'],row['run_id'],row['reasons']),(1,'FAIL','b'*32,[]))
