import copy, fcntl, os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from evidence import GateError
import container_policy as cp

IMAGE='sha256:'+'a'*64
class EnvelopeTests(unittest.TestCase):
    def test_parse_cpu_list(self):
        self.assertEqual(cp.parse_cpu_list('0-3,8,10-11\n'),[0,1,2,3,8,10,11])
    def test_choose_envelope_prefers_distinct_cores(self):
        sib={c:frozenset({c,c+16} if c<16 else {c-16,c}) for c in range(32)}
        e=cp.choose_envelope(list(range(32)),sib)
        self.assertEqual((e['cpus'],e['cpuset'],e['smt_siblings'],e['reduced'],e['multicore']),(4,[0,1,2,3],[],False,'PASS'))
    def test_choose_envelope_labels_smt_siblings_when_needed(self):
        e=cp.choose_envelope([0,1,2,3],{0:frozenset({0,1}),1:frozenset({0,1}),2:frozenset({2,3}),3:frozenset({2,3})})
        self.assertEqual((e['cpus'],e['cpuset'],e['smt_siblings']),(4,[0,1,2,3],[[0,1],[2,3]]))
    def test_choose_envelope_reduces_on_two_or_three_cpus(self):
        for allowed in ([0,1],[0,1,2]):
            e=cp.choose_envelope(allowed,{c:frozenset({c}) for c in allowed})
            self.assertEqual((e['cpus'],e['reduced'],e['multicore']),(2,True,'PASS'))
    def test_choose_envelope_blocks_multicore_on_one_cpu(self):
        e=cp.choose_envelope([5],{5:frozenset({5})})
        self.assertEqual((e['cpus'],e['cpuset'],e['multicore']),(1,[5],'BLOCKED'))

class BenchPolicyTests(unittest.TestCase):
    def test_policy_has_a_closed_bench_profile(self):
        p=cp.policy(ROOT)['profiles']['bench']
        self.assertEqual((p['cpus'],p['memory_bytes'],p['pids'],p['network'],p['wall_seconds']),(4,2147483648,256,'none',10800))
        self.assertEqual(p['fixed_environment'],cp.BENCH_ENVIRONMENT)
    def test_bench_profile_weakening_is_rejected(self):
        value=cp.read_json(ROOT/'safety/container-policy.json')
        for mutate in [lambda v:v['profiles']['bench'].update(network='bridge'),lambda v:v['profiles']['bench']['fixed_environment'].update(OMP_NUM_THREADS='8'),
                       lambda v:v['profiles']['bench'].update(cpus=16),lambda v:v['profiles']['build'].update(fixed_environment={'OMP_NUM_THREADS':'1'})]:
            v=copy.deepcopy(value);mutate(v)
            with self.subTest(),self.assertRaises(GateError):cp.check_policy(ROOT,v)
    def test_bench_plan_needs_an_envelope_and_takes_its_cpus(self):
        value=cp.policy(ROOT)
        with tempfile.TemporaryDirectory() as d:
            src=Path(d)/'src';src.mkdir()
            with self.assertRaises(GateError):cp.make_plan(value,IMAGE,{'/src':src},'bench')
            env={'cpus':2,'cpuset':[0,2],'smt_siblings':[],'reduced':True,'multicore':'PASS'}
            plan=cp.make_plan(value,IMAGE,{'/src':src},'bench',envelope=env)
            self.assertEqual((plan['resources']['cpus'],plan['cpuset'],plan['fixed_environment']),(2,'0,2',cp.BENCH_ENVIRONMENT))
    def test_file_mount_only_for_bench_at_the_fixed_target(self):
        value=cp.policy(ROOT);env={'cpus':4,'cpuset':[0,1,2,3],'smt_siblings':[],'reduced':False,'multicore':'PASS'}
        with tempfile.TemporaryDirectory() as d:
            src=Path(d)/'src';src.mkdir();f=Path(d)/'dataset.json';f.write_text('{}')
            plan=cp.make_plan(value,IMAGE,{'/src':src},'bench',envelope=env,file_mounts={'/data/dataset.json':f})
            self.assertEqual(plan['file_mounts'],{'/data/dataset.json':{'source':str(f.resolve()),'readonly':True}})
            with self.assertRaises(GateError):cp.make_plan(value,IMAGE,{'/src':src},'bench',envelope=env,file_mounts={'/data/other.json':f})
            with self.assertRaises(GateError):cp.make_plan(value,IMAGE,{'/src':src},'build',file_mounts={'/data/dataset.json':f})

class FileMountTests(unittest.TestCase):
    def test_regular_file_and_link_to_regular_file_are_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'a.json';f.write_text('{}');link=Path(d)/'l.json';link.symlink_to(f)
            self.assertEqual(cp.canonical_file_mount(f),str(f.resolve()));self.assertEqual(cp.canonical_file_mount(link),str(f.resolve()))
    def test_fifo_directory_dangling_link_and_oversize_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            fifo=Path(d)/'p';os.mkfifo(fifo);big=Path(d)/'big';big.write_bytes(b'abc')
            dangling=Path(d)/'x';dangling.symlink_to(Path(d)/'missing')
            for path in (fifo,Path(d),dangling):
                with self.subTest(path=path.name),self.assertRaises(GateError):cp.canonical_file_mount(path)
            # One past an explicit cap with a real file; exact cap accepted.
            with self.assertRaises(GateError):cp.canonical_file_mount(big,max_bytes=2)
            self.assertEqual(cp.canonical_file_mount(big,max_bytes=3),str(big.resolve()))
    def test_default_cap_is_32_mib_exact_bound_and_one_past(self):
        # The sandbox fsize ulimit is exactly 32 MiB, so a 32 MiB + 1 file cannot be
        # written inside the job; the size seen by lstat is substituted instead.
        real_lstat=os.lstat
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'dataset.json';f.write_text('{}');target=str(f.resolve())
            for size,accepted in ((32*1024*1024,True),(32*1024*1024+1,False)):
                def fake(path,*a,size=size,**k):
                    st=real_lstat(path,*a,**k)
                    if os.fspath(path)!=target:return st
                    fields=list(st[:10]);fields[6]=size;return os.stat_result(fields)
                with self.subTest(size=size),mock.patch.object(cp.os,'lstat',side_effect=fake):
                    if accepted:self.assertEqual(cp.canonical_file_mount(f),target)
                    else:
                        with self.assertRaises(GateError):cp.canonical_file_mount(f)

class AdmissionAndRedactionTests(unittest.TestCase):
    def test_non_bench_admission_blocks_while_a_bench_session_holds_the_lock(self):
        with tempfile.TemporaryDirectory() as d:
            old=cp.BENCH_LOCK_PREFIX;cp.BENCH_LOCK_PREFIX=d+'/lock-'
            try:
                fd=os.open(cp.BENCH_LOCK_PREFIX+str(os.getuid()),os.O_CREAT|os.O_RDWR,0o600);fcntl.flock(fd,fcntl.LOCK_EX)
                launcher=cp.Launcher.__new__(cp.Launcher);launcher.bench_lock=None
                with self.assertRaises(GateError):launcher.bench_wait(seconds=0)
                fcntl.flock(fd,fcntl.LOCK_UN);self.assertTrue(launcher.bench_wait(seconds=0));os.close(fd)
            finally:cp.BENCH_LOCK_PREFIX=old
    def test_bench_admission_needs_zero_active_jobs(self):
        launcher=cp.Launcher.__new__(cp.Launcher);launcher.bench_lock=None
        with self.assertRaises(GateError):launcher.bench_exclusive(1)
    def test_fixture_path_is_redacted_from_evidence_structures(self):
        real='/data-owner/private/dataset.json'
        rec={'plan':{'file_mounts':{'/data/dataset.json':{'source':real}}},'create_command':['--mount','type=bind,src='+real+',dst=/data/dataset.json,readonly'],
             'effective':{'inspect':{'mounts':[{'Source':real,'Destination':'/data/dataset.json'}]}}}
        out=cp.redact_fixture(rec,real);self.assertNotIn(real,repr(out));self.assertIn('<redacted fixture>',repr(out))
    def test_redaction_keeps_a_byte_count_and_no_digest(self):
        r=cp.redact_output({'output':'value 412.35\n','exit_code':0,'failure':None})
        self.assertEqual((r['output'],r['output_bytes']),('',13));self.assertNotIn('output_sha256',r)

def bare_launcher(config=None):
    launcher=cp.Launcher.__new__(cp.Launcher)
    launcher.bench_lock=None;launcher.bench_started=None;launcher.bench_held_ns=None
    launcher.records=[];launcher.config=Path(config or tempfile.mkdtemp())
    return launcher

class BenchSessionTests(unittest.TestCase):
    def setUp(self):
        self.dir=tempfile.TemporaryDirectory();self.old=cp.BENCH_LOCK_PREFIX;cp.BENCH_LOCK_PREFIX=self.dir.name+'/lock-'
    def tearDown(self):
        cp.BENCH_LOCK_PREFIX=self.old;self.dir.cleanup()
    def test_one_bench_session_excludes_another_and_its_own_non_bench_jobs(self):
        first=bare_launcher(self.dir.name+'/c1');second=bare_launcher(self.dir.name+'/c2');other=bare_launcher(self.dir.name+'/c3')
        self.assertTrue(first.bench_exclusive(0));self.assertIsNotNone(first.bench_lock)
        self.assertTrue(first.bench_exclusive(0))
        with self.assertRaises(GateError):second.bench_exclusive(0)
        with self.assertRaises(GateError):first.bench_wait(seconds=0)
        with self.assertRaises(GateError):other.bench_wait(seconds=0)
        self.assertIsNone(first.bench_interval())
        first.close()
        self.assertIsNone(first.bench_lock);self.assertIsInstance(first.bench_interval(),int);self.assertGreaterEqual(first.bench_interval(),0)
        self.assertTrue(other.bench_wait(seconds=0));self.assertTrue(second.bench_exclusive(0));second.close()
    def test_bench_wait_is_bounded(self):
        fd=os.open(cp.BENCH_LOCK_PREFIX+str(os.getuid()),os.O_CREAT|os.O_RDWR,0o600);fcntl.flock(fd,fcntl.LOCK_EX)
        try:
            now=[0.0];sleeps=[]
            def sleep(s):sleeps.append(s);now[0]+=s
            with self.assertRaises(GateError):bare_launcher(self.dir.name+'/c').bench_wait(seconds=3,poll=1.0,clock=lambda:now[0],sleep=sleep)
            self.assertEqual(sleeps,[1.0,1.0,1.0])
        finally:os.close(fd)
    def test_negative_and_positive_active_counts_are_refused(self):
        for active in (-1,1,4):
            with self.subTest(active=active),self.assertRaises(GateError):bare_launcher(self.dir.name+'/c').bench_exclusive(active)

class LauncherRedactionTests(unittest.TestCase):
    def launcher(self,output):
        launcher=bare_launcher();launcher.value=cp.policy(ROOT);launcher.runner_identity=None
        launcher.verify_session=lambda record:True
        launcher.docker=lambda argv,**kw:{'exit_code':0,'failure':None,'output':output}
        return launcher
    def record(self,redacted):
        return {'container_id':'c'*64,'profile':'bench','plan':{'profile':'bench','resources':{'wall_seconds':10800}},'policy_hash':'h',
                'effective':{'inspect':{}},'lifecycle':None,'execution_path':'docker','redacted':redacted}
    def test_redacted_session_stream_never_returns(self):
        r=self.launcher('value 412.35\n').execute(self.record(True),['true'],timeout=5)
        self.assertEqual((r['output'],r['output_bytes'],r['exit_code']),('',13,0))
    def test_unredacted_session_keeps_the_stream(self):
        r=self.launcher('ok\n').execute(self.record(False),['true'],timeout=5)
        self.assertEqual(r['output'],'ok\n');self.assertNotIn('output_bytes',r)
    def test_file_mounts_and_redaction_are_refused_for_other_profiles(self):
        launcher=bare_launcher()
        launcher.preflight=lambda:self.fail('options must be refused before preflight')
        for kw in ({'file_mounts':{cp.BENCH_FILE_TARGET:'/nonexistent'}},{'redacted':True}):
            with self.subTest(kw=kw),self.assertRaises(GateError):launcher.create('build',{},**kw)
    def test_envelope_is_refused_for_other_profiles_and_must_match_its_cpuset(self):
        value=cp.policy(ROOT)
        with self.assertRaises(GateError):cp.make_plan(value,IMAGE,{},'build',envelope={'cpus':2,'cpuset':[0,1]})
        for env in ({'cpus':5,'cpuset':[0,1,2,3,4]},{'cpus':2,'cpuset':[0]},{'cpus':2,'cpuset':[1,1]},{'cpus':0,'cpuset':[]},{'cpus':1,'cpuset':[-1]}):
            with self.subTest(env=env),self.assertRaises(GateError):cp.make_plan(value,IMAGE,{},'bench',envelope=env)
    def test_existing_profiles_carry_empty_bench_fields(self):
        plan=cp.make_plan(cp.policy(ROOT),IMAGE,{},'build')
        self.assertEqual((plan['file_mounts'],plan['fixed_environment']),({},{}));self.assertNotIn('cpuset',plan)
        self.assertEqual(plan['resources'],cp.policy(ROOT)['profiles']['build'])

class FixturePrivacyTests(unittest.TestCase):
    T=cp.BENCH_FILE_TARGET
    def setUp(self):
        self.dir=tempfile.TemporaryDirectory();self.old=cp.BENCH_LOCK_PREFIX;cp.BENCH_LOCK_PREFIX=self.dir.name+'/lock-'
        self.fixture=Path(self.dir.name)/'owner-private-dataset.json';self.fixture.write_text('{"synthetic":1}')
        self.real=str(self.fixture.resolve());self.calls=[]
    def tearDown(self):
        cp.BENCH_LOCK_PREFIX=self.old;self.dir.cleanup()
    def launcher(self):
        l=bare_launcher(self.dir.name+'/cfg');l.root=ROOT;l.run_dir=Path(self.dir.name);l.value=cp.policy(ROOT);l.lock={'image_id':IMAGE}
        l.purpose='bench';l.worktree_scope='w';l.info={'SecurityOptions':['name=apparmor']};l.prefix=['docker'];l.endpoint='unix:///fake'
        l.runner_identity=None;l.approved_runtime_images=set();l.preflight=lambda:None
        l.admission=lambda plan,finite_memory=0:{'active_before':0}
        def docker(argv,**kw):self.calls.append(list(argv));return {'exit_code':0,'failure':None,'output':'c'*64+'\n'}
        l.docker=docker
        l.effective=lambda container,plan:{'inspect':{'mounts':[{'Source':plan['file_mounts'][self.T]['source'],'Destination':self.T,'RW':False}]}}
        return l
    def topology(self):return mock.patch.object(cp,'host_topology',return_value=([0,1,2,3],{c:frozenset({c}) for c in range(4)}))
    def test_file_mount_without_redaction_is_refused_without_the_path(self):
        l=self.launcher();l.preflight=lambda:self.fail('refused before preflight')
        with self.assertRaises(GateError) as ctx:l.create('bench',{},file_mounts={self.T:self.real})
        self.assertNotIn(self.real,str(ctx.exception));self.assertEqual(self.calls,[])
    def test_fixture_errors_carry_no_path(self):
        missing=str(Path(self.dir.name)/'owner-private-missing.json')
        with self.assertRaises(GateError) as ctx:cp.canonical_file_mount(missing)
        self.assertNotIn(missing,str(ctx.exception));self.assertIsNone(ctx.exception.__cause__);self.assertTrue(ctx.exception.__suppress_context__)
        l=self.launcher()
        with self.topology(),mock.patch.object(cp,'file_hash',side_effect=lambda p:(_ for _ in ()).throw(FileNotFoundError(2,'gone',str(p)))):
            with self.assertRaises(GateError) as ctx:l.create('bench',{},file_mounts={self.T:self.fixture},redacted=True)
        self.assertNotIn(self.real,str(ctx.exception));self.assertIsNone(ctx.exception.__cause__);self.assertTrue(ctx.exception.__suppress_context__)
        self.assertEqual(self.calls,[]);self.assertEqual(l.records,[])
        l.close()
    def test_create_redacts_the_record_and_keeps_the_fixture_digest(self):
        l=self.launcher()
        with self.topology():rec=l.create('bench',{},file_mounts={self.T:self.fixture},redacted=True)
        try:
            create=[c for c in self.calls if c[0]=='create'][0]
            self.assertIn(f'type=bind,src={self.real},dst={self.T},readonly',create)
            self.assertEqual(create[create.index('--cpuset-cpus')+1],'0,1,2,3')
            self.assertNotIn(self.real,repr(rec));self.assertNotIn('owner-private-dataset',repr(rec))
            self.assertEqual(rec['plan']['file_mounts'][self.T]['source'],'<redacted fixture>')
            self.assertEqual(rec['effective']['inspect']['mounts'][0]['Source'],'<redacted fixture>')
            self.assertEqual(rec['fixture_sha256'],cp.file_hash(self.fixture));self.assertTrue(rec['redacted'])
            self.assertEqual(rec['bench'],{'envelope':cp.choose_envelope([0,1,2,3],{c:frozenset({c}) for c in range(4)}),'active_before':0})
        finally:
            rec['lifecycle']={};l.close()
