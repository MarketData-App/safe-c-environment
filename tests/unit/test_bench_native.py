import hashlib, importlib.util, json, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from evidence import GateError
import bench_native as bn

def temp_project(root,programs,libraries=()):
    """A minimal project declaration made inside the test (H3: framework tests never name the example)."""
    d=Path(root)/'proj';d.mkdir()
    doc={'schema_version':1,'name':'fixture-proj','modules':[{'name':'m','spec':'specs/project/m.md','sources':['src/m.c'],'headers':[],
         'tests':['tests/project/t.c'],'reads_external_input':False,'fuzz':[]}],'programs':[{'name':n,'main':f'src/{n}.c','modules':['m']} for n in programs],
         'run':{'program':programs[0],'args':[],'expect_exit':0}}
    if libraries:doc['libraries']=[{'name':n,'modules':['m'],'exports':['f']} for n in libraries]
    (d/'project.json').write_text(json.dumps(doc));return 'proj'

class NativeBuildTests(unittest.TestCase):
    def test_targets_come_from_project_json(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(bn.native_targets(d,temp_project(d,['tool-a','tool-b'],['lib_x'])),['tool-a','tool-b','liblib_x.so'])
        self.assertEqual(bn.native_targets(ROOT,'examples/hello-world'),['hello'])
        self.assertEqual(bn.native_targets(ROOT,'examples/bench-demo'),['bd-digest','bd-kernel','bd-worker','libbd_inproc.so'])   # FR6-R2 delta 2: the declared targets
    def test_flag_check(self):
        good=['clang','-O2','-ffp-contract=off','-c','/src/examples/x/src/a.c']
        self.assertEqual(bn.check_native_flags([good],'/src/examples/x'),[])
        for bad in (good+['-fsanitize=address'],good+['-march=native'],[f for f in good if f!='-ffp-contract=off'],good+['-O0'],good+['-ffast-math']):
            self.assertTrue(bn.check_native_flags([bad],'/src/examples/x'),bad)
        self.assertEqual(bn.check_native_flags([['clang','-O0','-c','/src/foundation/src/sc-foundation.c']],'/src/examples/x'),[])   # framework TUs are not judged here
    def test_restore_and_plan(self):
        native={'binaries':{'bd-kernel':{'path':'/tmp/a','sha256':'a'*64}},'glib':{'name':'libglib-2.0.so.0','sha256':'f'*64}}
        self.assertEqual(bn.native_restore(native),[('bench/private/native/bd-kernel',Path('/tmp/a'),'a'*64)])   # N2-A04: the transfer checks the digest
        self.assertEqual(bn.native_plan(native),{'bd-kernel':'a'*64,'libglib-2.0.so.0':'f'*64})
    def test_build_refuses_a_digest_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'bd-kernel';f.write_bytes(b'x')
            with self.assertRaises(GateError):bn.verify_fetched({'bd-kernel':'0'*64},Path(d))

def sha(data):return hashlib.sha256(data).hexdigest()

class FlagDetailTests(unittest.TestCase):
    def test_one_problem_per_translation_unit_and_a_sibling_directory_is_not_the_project(self):
        bad=['clang','-O0','-c','/src/examples/x/src/a.c']           # misses -O2 and -ffp-contract=off, carries -O0
        problems=bn.check_native_flags([bad,['clang','-O2','-ffp-contract=off','-fprofile-instr-generate','-c','/src/examples/x/src/b.c']],'/src/examples/x')
        self.assertEqual(len(problems),2)
        self.assertIn('/src/examples/x/src/a.c',problems[0]);self.assertIn('-O0',problems[0]);self.assertIn('-ffp-contract=off',problems[0])
        self.assertEqual(bn.check_native_flags([['clang','-O0','-c','/src/examples/xy/src/a.c']],'/src/examples/x'),[])
    def test_verify_fetched_accepts_equal_digests_and_refuses_a_missing_file(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'bd-kernel').write_bytes(b'x')
            self.assertEqual(bn.verify_fetched({'bd-kernel':sha(b'x')},Path(d)),{'bd-kernel':sha(b'x')})
            with self.assertRaises(GateError):bn.verify_fetched({'bd-kernel':sha(b'x'),'libq.so':sha(b'y')},Path(d))
    def test_cmake_target_names(self):
        self.assertEqual(bn.cmake_target('bd-kernel'),'bd-kernel')
        self.assertEqual(bn.cmake_target('libbd_inproc.so'),'project-library-bd_inproc')

class FakeSession:
    """A bench session that answers the native-build job with `row` and `files` (name -> bytes)."""
    def __init__(self,row,files):self.row=row;self.files=files;self.plans=[];self.digests={}
    def __call__(self,root,run_dir):return self
    def job(self,plan,label,timeout,restore=()):
        self.plans.append((plan,label,tuple(restore)))
        return {'output':json.dumps(self.row),'exit_code':0,'failure':None,'evidence_path':'job.json'}
    def fetch(self,relative,destination):
        data=self.files[relative.split('/')[-1]];Path(destination).parent.mkdir(parents=True,exist_ok=True);Path(destination).write_bytes(data)
        self.digests[str(Path(destination).absolute())]=sha(data);return destination
    def fetched_sha256(self,destination):return self.digests[str(Path(destination).absolute())]
    def close(self):pass

class BuildNativeTests(unittest.TestCase):
    def setUp(self):
        import project_check
        self.glib=project_check.closure_allowlist(ROOT)['libglib-2.0.so.0']
        self.files={'bd-digest':b'digest-binary','bd-kernel':b'kernel-binary','bd-worker':b'worker-binary','libbd_inproc.so':b'library'}
        tu=['clang','-O2','-ffp-contract=off','-c','/src/examples/bench-demo/src/bd_digest.c']
        self.row={'status':'PASS','files':list(self.files),'sha256':{k:sha(v) for k,v in self.files.items()},'glib_sha256':self.glib,
                  'compiler':'clang version 19.1.7','commands':[tu],'commands_cut':False,'smoke_exit':0}
    def build(self,row,files=None):
        import bench
        session=FakeSession(row,files or self.files)
        d=Path(tempfile.mkdtemp());self.addCleanup(__import__('shutil').rmtree,d,True)
        with mock.patch.object(bench,'BenchSession',session):
            return bn.build_native(ROOT,d,'examples/bench-demo'),session,d
    def test_a_good_row_writes_native_json_with_the_fetched_digests(self):
        native,session,d=self.build(self.row)
        plan,label,_=session.plans[0]
        self.assertEqual((plan['job'],plan['project_dir'],plan['targets'],label),('native-build','examples/bench-demo',list(self.files),'native-build'))
        self.assertEqual(json.loads((d/'native.json').read_text()),native)
        self.assertEqual({k:v['sha256'] for k,v in native['binaries'].items()},self.row['sha256'])
        self.assertEqual(native['binaries']['bd-kernel']['path'],str(d/'native'/'bd-kernel'))
        self.assertEqual((native['glib'],native['smoke'],native['flags']['problems']),({'name':'libglib-2.0.so.0','sha256':self.glib},{'program':'bd-kernel','exit':0},[]))
        self.assertEqual(native['flags']['required'],list(bn.REQUIRED_FLAGS));self.assertEqual(native['flags']['forbidden'],list(bn.FORBIDDEN_FLAGS))
        self.assertEqual(len(native['project_identity']),64);self.assertEqual(native['project_dir'],'examples/bench-demo')
    def test_every_problem_raises(self):
        bad_tu=['clang','-O2','-c','/src/examples/bench-demo/src/bd_digest.c']
        for name,row,files in (('smoke',dict(self.row,smoke_exit=1),None),('status',dict(self.row,status='FAIL'),None),
                               ('glib',dict(self.row,glib_sha256='0'*64),None),('flags',dict(self.row,commands=[bad_tu]),None),
                               ('no unit',dict(self.row,commands=[]),None),('digest',self.row,dict(self.files,**{'bd-kernel':b'changed'})),
                               ('missing target',dict(self.row,sha256={'bd-digest':sha(b'digest-binary')}),None),
                               ('cut',dict(self.row,commands_cut=True),None),('cut unknown',{k:v for k,v in self.row.items() if k!='commands_cut'},None),
                               ('host cut',dict(self.row,commands=[self.row['commands'][0]]*(bn.MAX_COMMANDS+1)),None)):
            with self.subTest(name=name),self.assertRaises(GateError):self.build(row,files)
    def test_a_flag_problem_still_records_native_json(self):
        bad_tu=['clang','-O2','-c','/src/examples/bench-demo/src/bd_digest.c']
        import bench
        session=FakeSession(dict(self.row,commands=[bad_tu]),self.files);d=Path(tempfile.mkdtemp());self.addCleanup(__import__('shutil').rmtree,d,True)
        with mock.patch.object(bench,'BenchSession',session),self.assertRaises(GateError):bn.build_native(ROOT,d,'examples/bench-demo')
        self.assertEqual(len(json.loads((d/'native.json').read_text())['flags']['problems']),1)

class LastWinsFlagTests(unittest.TestCase):
    """N2-A01: clang uses the last flag of a family, so the check judges the effective value of each family."""
    BASE=['clang','-O2','-ffp-contract=off']
    def problems(self,extra,base=None):
        return bn.check_native_flags([(base or self.BASE)+extra+['-c','/src/examples/x/src/a.c']],'/src/examples/x')
    def test_a_later_optimization_level_overrides_o2(self):
        for later in ('-O3','-Os','-Oz','-Og','-O','-O4'):
            with self.subTest(later=later):self.assertTrue(self.problems([later]))
        self.assertEqual(self.problems([],['clang','-ffp-contract=off','-O3','-O2']),[])          # the last level is -O2
        self.assertTrue(self.problems([],['clang','-O2','-ffp-contract=off','-O3']))
    def test_a_later_fp_contract_overrides_off(self):
        for later in ('-ffp-contract=fast','-ffp-contract=on','-ffp-contract=fast-honor-pragmas'):
            with self.subTest(later=later):self.assertTrue(self.problems([later]))
        self.assertEqual(self.problems([],['clang','-O2','-ffp-contract=fast','-ffp-contract=off']),[])
    def test_every_fast_math_family_flag_is_refused_unless_a_later_flag_turns_it_off(self):
        for flag in bn.FAST_MATH_FLAGS:
            with self.subTest(flag=flag):
                self.assertTrue(self.problems([flag]))
                off=bn.FAST_MATH_OFF.get(flag)
                if off and not flag.startswith(bn.FORBIDDEN_FLAGS):self.assertEqual(self.problems([flag,off]),[])   # the membership rule stays stricter
                if off:self.assertTrue(self.problems([off,flag]))
        self.assertEqual(set(bn.FAST_MATH_FLAGS),{'-ffast-math','-funsafe-math-optimizations','-fassociative-math','-freciprocal-math',
                         '-fno-signed-zeros','-fno-trapping-math','-ffinite-math-only','-fno-honor-nans','-fno-honor-infinities','-Ofast'})
    def test_the_problem_names_the_effective_value(self):
        p=self.problems(['-O3','-ffp-contract=fast'])
        self.assertEqual(len(p),1);self.assertIn('-O3',p[0]);self.assertIn('-ffp-contract=fast',p[0])

class CutDatabaseTests(unittest.TestCase):
    """N2-A02: a compile database cut at the job limits is reported, and the host refuses it."""
    def setUp(self):
        self.bc=coordinator();self.job=sys.modules['bench_native_job']
        d=Path(tempfile.mkdtemp());self.addCleanup(__import__('shutil').rmtree,d,True);self.build=d
    def write(self,rows):
        (self.build/'compile_commands.json').write_text(json.dumps(rows))
        with mock.patch.object(self.job,'BUILD',self.build):return self.job._commands('/src/examples/x')
    def unit(self,k,args=None):
        return {'file':f'/src/examples/x/src/u{k}.c','arguments':args or ['clang','-O2','-ffp-contract=off','-c',f'/src/examples/x/src/u{k}.c']}
    def test_within_the_limits_nothing_is_cut(self):
        rows,cut=self.write([self.unit(k) for k in range(3)]+[{'file':'/src/foundation/a.c','arguments':['clang']}])
        self.assertEqual((len(rows),cut),(3,False))
        rows,cut=self.write([self.unit(k) for k in range(self.job.MAX_COMMANDS)])
        self.assertEqual((len(rows),cut),(self.job.MAX_COMMANDS,False))
    def test_each_limit_reports_a_cut(self):
        for name,rows in (('units',[self.unit(k) for k in range(self.job.MAX_COMMANDS+1)]),
                          ('arguments',[self.unit(0,['clang']*(self.job.MAX_ARGS+1))]),
                          ('characters',[self.unit(0,['clang','-D'+'x'*self.job.MAX_ARG_CHARS])])):
            with self.subTest(name=name):self.assertTrue(self.write(rows)[1])

class Sha256JsonTests(unittest.TestCase):
    """Task 20 framework part (FR6-R3 item 4): native_env writes sha256.json (name -> sha256) beside the restored binaries."""
    def setUp(self):
        self.bc=coordinator();self.job=sys.modules['bench_native_job']
        d=Path(tempfile.mkdtemp());self.addCleanup(__import__('shutil').rmtree,d,True)
        self.dir=d/'native';self.dir.mkdir();self.glib=d/'libglib-2.0.so.0';self.glib.write_bytes(b'glib')
        (self.dir/'bd-kernel').write_bytes(b'kernel');(self.dir/'libq.so').write_bytes(b'lib')
    def test_the_file_names_every_restored_binary(self):
        plan={'native':{'bd-kernel':sha(b'kernel'),'libq.so':sha(b'lib'),'libglib-2.0.so.0':sha(b'glib')}}
        with mock.patch.object(self.job,'NATIVE_DIR',self.dir),mock.patch.object(self.job,'GLIB',self.glib):self.job.native_env(plan)
        self.assertEqual(json.loads((self.dir/'sha256.json').read_text()),{'bd-kernel':sha(b'kernel'),'libq.so':sha(b'lib')})
        self.assertEqual((self.dir/'sha256.json').stat().st_mode&0o777,0o444)
    def test_a_refused_plan_writes_no_file(self):
        plan={'native':{'bd-kernel':'0'*64,'libglib-2.0.so.0':sha(b'glib')}}
        with mock.patch.object(self.job,'NATIVE_DIR',self.dir),mock.patch.object(self.job,'GLIB',self.glib),self.assertRaises(ValueError):self.job.native_env(plan)
        self.assertFalse((self.dir/'sha256.json').exists())
    def test_the_bench_reader_returns_the_restored_digest(self):
        sys.path.insert(0,str(ROOT/'benchmarks/performance/python'))
        from benchlab import native_worker as nw
        (self.dir/'sha256.json').write_text(json.dumps({'bd-kernel':sha(b'kernel')}))
        with mock.patch.dict('os.environ',{'SAFE_C_BENCH_NATIVE':str(self.dir)}):
            self.assertEqual(nw.native_sha256('bd-kernel'),sha(b'kernel'));self.assertEqual(nw.native_path('bd-kernel'),self.dir/'bd-kernel')
            for bad in ('absent','../x',''):
                with self.subTest(bad=bad),self.assertRaises(ValueError):nw.native_sha256(bad)
        with mock.patch.dict('os.environ',{},clear=True),self.assertRaises(ValueError):nw.native_sha256('bd-kernel')

class CliHookTests(unittest.TestCase):
    def test_the_operation_and_the_check_flag_are_registered(self):
        import bench
        self.assertIs(bench.HANDLERS['native-build'],bn.native_build_cmd)
        self.assertIn('--project',dict(bench.ARGUMENTS['native-build']))
        self.assertEqual(dict(bench.ARGUMENTS['check'])['--native'],{'action':'store_true'})
        self.assertIn('--check',dict(bench.ARGUMENTS['check']))      # the hook keeps the earlier check arguments
    def test_run_check_restores_the_native_binaries_and_plans_their_digests(self):
        import bench
        seen=[]
        class Session:
            def __init__(self,root,rd):pass
            def job(self,plan,label,timeout,restore=()):
                seen.append((plan,tuple(restore)));return {'output':json.dumps({'status':'PASS','files':[]}),'exit_code':0,'failure':None,'evidence_path':'e.json'}
            def close(self):pass
        native={'binaries':{'bd-kernel':{'path':'/tmp/k','sha256':'a'*64}},'glib':{'name':'libglib-2.0.so.0','sha256':'f'*64}}
        with tempfile.TemporaryDirectory() as d,mock.patch.object(bench,'BenchSession',Session):
            self.assertEqual(bench.run_check(ROOT,Path(d),'examples/bench-demo','demo-vectors',native=native)[0],'PASS')
            self.assertEqual(bench.run_check(ROOT,Path(d),'examples/bench-demo','demo-vectors')[0],'PASS')
        self.assertEqual(seen[0][0]['native'],{'bd-kernel':'a'*64,'libglib-2.0.so.0':'f'*64})
        self.assertEqual(seen[0][1],(('bench/private/native/bd-kernel',Path('/tmp/k'),'a'*64),))
        self.assertNotIn('native',seen[1][0]);self.assertEqual(seen[1][1],())
    def test_check_cmd_builds_first_only_with_the_flag(self):
        import argparse, bench
        calls=[]
        with tempfile.TemporaryDirectory() as d:
            run_dir=Path(d)
            with mock.patch.object(bench,'new_run_dir',lambda root,kind:run_dir),\
                 mock.patch.object(bn,'build_native',lambda root,rd,project:calls.append(('build',project)) or {'binaries':{}}),\
                 mock.patch.object(bench,'run_check',lambda *a,**k:calls.append(('check',k.get('native'))) or ('PASS','e.json',{'files':[]})),\
                 mock.patch('builtins.print'):
                for flag in (True,False):
                    bench.check_cmd(ROOT,argparse.Namespace(project='examples/bench-demo',check='demo-vectors',native=flag,arg=[],long=False,format='json'))
        self.assertEqual(calls,[('build','examples/bench-demo'),('check',{'binaries':{}}),('check',None)])

def coordinator():
    spec=importlib.util.spec_from_file_location('bc_native',ROOT/'container/bench-coordinator.py');bc=importlib.util.module_from_spec(spec);spec.loader.exec_module(bc);return bc

class ContainerNativeTests(unittest.TestCase):
    def setUp(self):
        self.bc=coordinator();self.job=sys.modules['bench_native_job']
        d=Path(tempfile.mkdtemp());self.addCleanup(__import__('shutil').rmtree,d,True)
        self.dir=d/'native';self.dir.mkdir();self.glib=d/'libglib-2.0.so.0';self.glib.write_bytes(b'glib')
        (self.dir/'bd-kernel').write_bytes(b'kernel')
        self.plan={'native':{'bd-kernel':sha(b'kernel'),'libglib-2.0.so.0':sha(b'glib')}}
    def env(self,plan):
        with mock.patch.object(self.job,'NATIVE_DIR',self.dir),mock.patch.object(self.job,'GLIB',self.glib):return self.job.native_env(plan)
    def test_the_coordinator_registers_the_job(self):
        self.assertIn('native-build',self.bc.JOBS)
        self.assertIsNot(sys.modules.get('bench_native'),self.job)   # its own module name: tools/bench_native.py has the other one
        self.assertIs(sys.modules.get('bench_native'),bn)
    def test_a_plan_without_native_gives_no_environment(self):
        self.assertEqual(self.env({}),{})
    def test_matching_digests_give_the_directory_and_mode_0555(self):
        self.assertEqual(self.env(self.plan),{'SAFE_C_BENCH_NATIVE':str(self.dir)})
        self.assertEqual((self.dir/'bd-kernel').stat().st_mode&0o777,0o555)
    def test_a_changed_binary_or_glib_or_a_malformed_plan_is_refused(self):
        for plan in ({'native':dict(self.plan['native'],**{'bd-kernel':'0'*64})},{'native':dict(self.plan['native'],**{'libglib-2.0.so.0':'0'*64})},
                     {'native':{'bd-kernel':sha(b'kernel')}},{'native':dict(self.plan['native'],**{'../x':sha(b'kernel')})},{'native':[]},
                     {'native':dict(self.plan['native'],**{'absent':sha(b'kernel')})}):
            with self.subTest(plan=plan),self.assertRaises(ValueError):self.env(plan)
    def hashed_then(self,change):
        """The job's hashlib with a hook: right after the first sha256 of the restored kernel bytes, change() runs once
        (a swap or an in-place change between the hash and the use)."""
        import hashlib as real
        done=[]
        class Hash:
            def __init__(self):self.h=real.sha256()
            def update(self,data):self.h.update(data)
            def hexdigest(self):
                value=self.h.hexdigest()
                if value==sha(b'kernel') and not done:done.append(1);change()
                return value
        return mock.patch.object(self.job,'hashlib',type('H',(),{'sha256':staticmethod(Hash)}))
    def test_a_binary_swapped_after_the_hash_is_refused(self):          # N3-A01
        def swap():
            tmp=self.dir/'swap.tmp';tmp.write_bytes(b'other');__import__('os').replace(tmp,self.dir/'bd-kernel')
        with self.hashed_then(swap),self.assertRaisesRegex(ValueError,'mismatch'):self.env(self.plan)
        self.assertFalse((self.dir/'sha256.json').exists())
        self.assertNotEqual((self.dir/'bd-kernel').stat().st_mode&0o777,0o555)     # the swapped file got no mode change
    def test_a_binary_changed_in_place_after_the_hash_is_refused(self):  # N3-A01
        def rewrite():
            with open(self.dir/'bd-kernel','r+b') as f:f.write(b'K')
        with self.hashed_then(rewrite),self.assertRaisesRegex(ValueError,'mismatch'):self.env(self.plan)
        self.assertFalse((self.dir/'sha256.json').exists())
    def test_a_symlink_or_a_non_regular_restored_binary_is_refused(self):  # N3-A01: O_NOFOLLOW and fstat
        import os
        (self.dir/'bd-kernel').rename(self.dir/'real');(self.dir/'bd-kernel').symlink_to(self.dir/'real')
        with self.assertRaisesRegex(ValueError,'mismatch'):self.env(self.plan)
        (self.dir/'bd-kernel').unlink();os.mkfifo(self.dir/'bd-kernel')
        with self.assertRaisesRegex(ValueError,'mismatch'):self.env(self.plan)
    def test_targets_and_cmake_names_are_checked_in_the_container(self):
        self.assertEqual(self.job.cmake_target('libbd_inproc.so'),'project-library-bd_inproc')
        for bad in ('../x','lib.so','Bd',''):
            with self.subTest(bad=bad),self.assertRaises(ValueError):self.job.cmake_target(bad)

if __name__=='__main__':unittest.main()
