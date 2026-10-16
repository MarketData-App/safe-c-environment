import ast, argparse, contextlib, io, json, sys, tempfile, types, unittest
from unittest import mock
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import bench

class BenchCliTests(unittest.TestCase):
    def test_parser_registers_the_current_operations(self):
        p=argparse.ArgumentParser();bench.configure_parser(p)
        self.assertEqual(p.parse_args(['doctor']).operation,'doctor')
        self.assertEqual(p.parse_args(['selftest','--suite','unit']).suite,'unit')
    def test_host_bench_tools_never_import_candidate_code(self):
        for path in sorted((ROOT/'tools').glob('bench*.py')):
            tree=ast.parse(path.read_text())
            names=[a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names]+[n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
            with self.subTest(path=path.name):self.assertFalse([x for x in names if x.split('.')[0] in ('optionlab','benchmarks')])
    def test_last_json_reads_the_final_object_line(self):
        self.assertEqual(bench.last_json('noise\n{"status":"PASS"}\n'),{'status':'PASS'})
        self.assertEqual(bench.last_json('no json'),{})

class FakeRunner:
    def __init__(self,root,run_dir,lock,scratch,**options):
        self.run_dir=Path(run_dir);self.session=None;self.count=0;self.closed=False
    def start(self):self.session={'bench':{'envelope':{'cpus':4,'cpuset':[0,1,2,3]}}}
    def run(self,args,*,timeout=30,env=None,label='process'):
        self.count+=1;row={'status':'PASS','tests':1,'missing_counters':[],'libraries':{}}
        return {'exit_code':0,'failure':None,'output':json.dumps(row) if args[0]=='python3' else '',
                'evidence_path':str(self.run_dir/'evidence'/f'{self.count:04d}-{label}.json')}
    def restore(self,relative,path,fetched=None,label=None):pass     # the Runner.restore signature (DD-01, DD-02)
    def close(self):self.closed=True

class BenchSessionTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(tempfile.mkdtemp());self.addCleanup(__import__('shutil').rmtree,self.root,True)
        developer=types.ModuleType('developer');developer.inputs=lambda root:({},{'image_id':'sha256:'+'0'*64},{'image_id':'base'})
        for patch in (mock.patch.dict(sys.modules,{'developer':developer}),
                      mock.patch.object(bench.bm,'load_policy',lambda root,project_dir=None:{'job_deadlines':{'doctor':120,'selftest':3000}}),
                      mock.patch.object(bench,'expected_versions',lambda root:{})):
            patch.start();self.addCleanup(patch.stop)
    def call(self,handler,**fields):
        out=io.StringIO()
        with contextlib.redirect_stdout(out):code=handler(self.root,argparse.Namespace(format='json',**fields))
        (run,)=(self.root/'artifacts/bench').iterdir();return code,run
    def test_doctor_evidence_lists_the_scratch_record_and_the_coordinator_run(self):
        with mock.patch.object(bench,'Runner',FakeRunner):code,run=self.call(bench.doctor)
        doc=json.loads((run/'doctor.json').read_text())
        self.assertEqual([Path(p).name for p in doc['evidence_paths']],['0001-bench-scratch.json','0002-bench-doctor.json'])
    def failing_setup(self):
        scratch=self.root/'scratch';scratch.mkdir()
        def refuse(*a,**k):raise bench.GateError('launcher refused')
        return scratch,mock.patch.object(bench,'Runner',refuse),mock.patch.object(bench.tempfile,'mkdtemp',lambda prefix:str(scratch))
    def test_doctor_setup_failure_writes_a_blocked_record_and_removes_scratch(self):
        scratch,runner,mkdtemp=self.failing_setup()
        with runner,mkdtemp:code,run=self.call(bench.doctor)
        doc=json.loads((run/'doctor.json').read_text())
        self.assertEqual((code,doc['status'],doc['reason'],scratch.exists()),(2,'BLOCKED','launcher refused',False))
    def test_selftest_setup_failure_writes_a_blocked_record_and_removes_scratch(self):
        scratch,runner,mkdtemp=self.failing_setup()
        with runner,mkdtemp:code,run=self.call(bench.selftest,suite='unit')
        doc=json.loads((run/'selftest.json').read_text())
        self.assertEqual((code,doc['status'],doc['suites']['unit'],scratch.exists()),(2,'BLOCKED',{'status':'BLOCKED','reason':'launcher refused'},False))
    def test_selftest_evidence_lists_the_scratch_record_and_the_unit_run(self):
        with mock.patch.object(bench,'Runner',FakeRunner):code,run=self.call(bench.selftest,suite='unit')
        doc=json.loads((run/'selftest.json').read_text())
        self.assertEqual((code,[Path(p).name for p in doc['suites']['unit']['evidence_paths']]),(0,['0001-bench-scratch.json','0002-bench-unit.json']))

class BenchCheckOptionTests(unittest.TestCase):
    """FR3: the example project's oracle driver (tools/bench_oracle.py) left the framework (FR3 handoff list). `bench check`
    runs any declared project check: `--long` selects the framework job deadline long_check (10,800 s) and each `--arg`
    reaches the check (run_check bounds the arguments). The project's protocol, not the framework, holds the oracle data."""
    def call(self,argv,status='PASS'):
        seen=[]
        def fake(root,run_dir,project,name,args=(),deadline_key='smoke',shared=()):
            seen.append((project,name,list(args),deadline_key));return status,'evidence.json',{'status':status,'check':name,'files':[]}
        p=argparse.ArgumentParser();bench.configure_parser(p);a=p.parse_args(argv)
        with tempfile.TemporaryDirectory() as tmp,mock.patch.object(bench,'run_check',fake),mock.patch.object(bench,'project_arg',lambda root,args:args.project),\
             contextlib.redirect_stdout(io.StringIO()):
            code=bench.check_cmd(Path(tmp),a)
        return code,seen
    def test_long_selects_the_long_check_deadline(self):
        self.assertEqual(self.call(['check','--check','some-check','--project','p','--long']),(0,[('p','some-check',[],'long_check')]))
        self.assertEqual(self.call(['check','--check','some-check','--project','p']),(0,[('p','some-check',[],'smoke')]))
    def test_each_arg_reaches_the_check_in_order(self):
        self.assertEqual(self.call(['check','--check','gen-part','--project','p','--arg','part-a','--arg','2'])[1],[('p','gen-part',['part-a','2'],'smoke')])
    def test_a_failed_check_exits_1(self):
        self.assertEqual(self.call(['check','--check','x-check','--project','p'],status='FAIL')[0],1)
    def test_the_long_deadline_is_a_framework_job_deadline(self):
        import bench_model as bm
        self.assertEqual(bm.load_policy(ROOT)['job_deadlines']['long_check'],10800)
    def test_run_check_bounds_the_arguments(self):
        with tempfile.TemporaryDirectory() as tmp,self.assertRaises(bench.GateError):
            bench.run_check(ROOT,Path(tmp),'tests/fixtures/bench-project','fixture-agreement',['bad arg with spaces'])
