import argparse, importlib.util, json, shutil, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from evidence import GateError
import bench
spec=importlib.util.spec_from_file_location('bench_coordinator_profile',ROOT/'container/bench-coordinator.py')
bc=importlib.util.module_from_spec(spec);spec.loader.exec_module(bc)

def tmpdir(test):
    d=Path(tempfile.mkdtemp());test.addCleanup(shutil.rmtree,d,True);return d

def cases_dir(test):
    d=tmpdir(test);(d/'benchmarks/performance/cases').mkdir(parents=True);m=d/'benchmarks/performance/cases/x.json';m.write_text('{}');out=d/'out';out.mkdir()
    return d,m,out

def child(returncode=0,stdout='',stderr='',timed_out=False):return mock.Mock(returncode=returncode,stdout=stdout,stderr=stderr,timed_out=timed_out)

class FakeSession:
    """A bench container whose launcher reports `result` for the job; fetch copies `files` into place."""
    BASE={'exit_code':0,'failure':None,'output':'','evidence_path':'e.json'};result=dict(BASE);files={}
    def __init__(self,root,run_dir,**kw):self.evidence_paths=['e.json']
    def job(self,plan,label,timeout,restore=()):FakeSession.plan=plan;return dict(FakeSession.result)
    def fetch(self,relative,destination):
        Path(destination).parent.mkdir(parents=True,exist_ok=True);Path(destination).write_text(FakeSession.files[relative]);return Path(destination)
    def close(self):pass

class ProfileRuleTests(unittest.TestCase):
    def test_profile_refuses_local_data(self):
        with self.assertRaises(GateError):bench.profile_dataset('local:/tmp/x.json')
        self.assertEqual(bench.profile_dataset('synthetic:medium'),'medium')
    def test_profile_refuses_unknown_sizes(self):
        for spec_ in ('synthetic:','synthetic:huge','synthetic','tiny',''):
            with self.subTest(spec=spec_),self.assertRaises(GateError):bench.profile_dataset(spec_)
    def test_compare_refuses_a_profiled_run(self):
        d=tmpdir(self);run=d/'artifacts/bench/'/('a'*32);run.mkdir(parents=True);(run/'run.json').write_text(json.dumps({'mode':'profile'}))
        with self.assertRaises(GateError):bench.compare_cmd(d,argparse.Namespace(run_id='a'*32,format='json'))
    def test_profile_variants_must_be_implemented_python_variants(self):
        case=bench.bm.load_case(ROOT,'bench-control-spin')
        self.assertEqual(bench.profile_variants(case,['py-reference','py-processes']),['py-reference','py-processes'])
        self.assertEqual(bench.profile_variants(case,['py-reference','py-reference']),['py-reference'])   # one profile per variant
        self.assertEqual(bench.profile_variants(case,None),['py-reference'])      # default: py-reference and py-optimized where implemented
        for bad in (['py-optimized'],['c-reference'],['py-nothing'],['py-reference','py-optimized']):
            with self.subTest(variants=bad),self.assertRaises(GateError):bench.profile_variants(case,bad)
    def test_profile_refuses_before_any_container(self):
        args=argparse.Namespace(case='bench-control-spin',variant=['py-optimized'],dataset='synthetic:small',project=None,format='json')
        with mock.patch.object(bench,'BenchSession',side_effect=AssertionError('container started')):
            with self.assertRaises(GateError):bench.profile_cmd(ROOT,args)
        args=argparse.Namespace(case='bench-control-spin',variant=None,dataset='local:/tmp/x.json',project=None,format='json')
        with mock.patch.object(bench,'BenchSession',side_effect=AssertionError('container started')):
            with self.assertRaises(GateError):bench.profile_cmd(ROOT,args)
    def test_profile_files_follow_the_file_rule(self):
        row={'files':['profile.json','pstats/py-reference.pstats','pstats/py-processes-worker-12-0000.pstats','../x','pstats/../x','other/x.pstats','pstats/a/b',7]}
        self.assertEqual(bench.profile_files(row),['profile.json','pstats/py-reference.pstats','pstats/py-processes-worker-12-0000.pstats'])
    def test_profile_is_a_registered_operation(self):
        self.assertIn('profile',bench.HANDLERS)
        self.assertEqual({a[0] for a in bench.ARGUMENTS['profile']},{'--case','--variant','--dataset','--project'})

class ProfileCommandTests(unittest.TestCase):
    """Review fix (Important 1, 2, Minor 5): infrastructure failures BLOCK; run.json binds the profile to its input and runtime."""
    def run_cmd(self,result,files=None,variant=None):
        d=tmpdir(self);FakeSession.result=dict(FakeSession.BASE,**result);FakeSession.files=files or {}
        args=argparse.Namespace(case='bench-control-spin',variant=variant,dataset='synthetic:small',project=None,format='json')
        with mock.patch.object(bench,'BenchSession',FakeSession),mock.patch.object(bench,'new_run_dir',side_effect=lambda root,kind:(d/'run').mkdir() or d/'run'),\
             mock.patch('builtins.print'):
            code=bench.profile_cmd(ROOT,args)
        return code,json.loads((d/'run/run.json').read_text())
    def test_a_runner_failure_without_a_result_row_is_blocked(self):
        code,run=self.run_cmd({'exit_code':125,'failure':'launcher','output':''})
        self.assertEqual((code,run['status']),(2,'BLOCKED'))
    def test_a_failed_coordinator_row_is_a_fail(self):
        code,run=self.run_cmd({'exit_code':1,'failure':'exit','output':json.dumps({'status':'FAIL','files':['profile.json']})+'\n'},{'bench/out/profile.json':'[]'})
        self.assertEqual((code,run['status']),(1,'FAIL'))
    def test_run_json_records_identity_and_omitted_defaults(self):
        ident={'dataset_sha256':'d'*64,'case_manifest_sha256':'c'*64,'bench_ref':['benchlab.controlcase:Spin',{'rounds':2000}],
               'runtime':{'version':'3.13.1','implementation':'cpython','profiler':'cProfile (_lsprof) on sys.monitoring'}}
        prof=[dict(ident,variant='py-reference',coverage='adapter run, one process',top=[{'function':'f'}],files=['py-reference.pstats'])]
        code,run=self.run_cmd({'output':json.dumps({'status':'PASS','files':['profile.json','pstats/py-reference.pstats']})+'\n'},
                              {'bench/out/profile.json':json.dumps(prof),'bench/out/pstats/py-reference.pstats':'x'})
        self.assertEqual((code,run['status']),(0,'PASS'))
        self.assertEqual(run['omitted_defaults'],[{'variant':'py-optimized','reason':'not an implemented variant of the case'}])
        self.assertEqual(run['identity'],{'py-reference':ident})
        self.assertEqual(FakeSession.plan['variants'],['py-reference'])
    def test_explicit_variants_omit_no_defaults(self):
        code,run=self.run_cmd({'exit_code':125,'failure':'launcher','output':''},variant=['py-processes'])
        self.assertEqual(run['omitted_defaults'],[])

class ProfileJobTests(unittest.TestCase):
    def test_job_refuses_a_manifest_outside_the_cases(self):
        r=bc.job_profile({'deadline_seconds':100,'case_manifest':'/etc/x.json','variants':['py-reference'],'rows':64,'dataset':{'kind':'synthetic','seed':1}},tmpdir(self))
        self.assertEqual(r['status'],'FAIL')
    def test_job_refuses_bad_variants_and_sizes(self):
        d,m,out=cases_dir(self)
        with mock.patch.object(bc,'SRC',d),mock.patch.object(bc,'run_group',side_effect=AssertionError('child started')):
            for variants,rows in ((['../x'],64),([],64),(['py-reference'],0),(['py-reference'],True),(['py-reference']*9,64)):
                with self.subTest(variants=variants,rows=rows):
                    self.assertEqual(bc.job_profile({'deadline_seconds':100,'case_manifest':str(m),'variants':variants,'rows':rows,'dataset':{'kind':'synthetic','seed':1}},out)['status'],'FAIL')
    def test_job_runs_each_variant_in_an_isolated_child(self):
        d,m,out=cases_dir(self);calls=[]
        def fake(argv,timeout):
            calls.append(argv);v=argv[argv.index('benchlab.profiling')+2]
            return child(stdout=json.dumps({'variant':v,'coverage':'adapter run, one process','top':[{'function':'f'}],'files':[v+'.pstats']})+'\n')
        with mock.patch.object(bc,'SRC',d),mock.patch.object(bc,'run_group',side_effect=fake):
            r=bc.job_profile({'deadline_seconds':100,'case_manifest':str(m),'variants':['py-reference','py-processes'],'rows':64,'dataset':{'kind':'synthetic','seed':1}},out)
        self.assertEqual(r['status'],'PASS');self.assertEqual(len(calls),2)
        self.assertTrue(all(a[1]=='-I' for a in calls))                      # isolated: no startup hook from a project path
        self.assertEqual(r['files'],['profile.json','pstats/py-reference.pstats','pstats/py-processes.pstats'])
        rows=json.loads((out/'profile.json').read_text());self.assertEqual([x['variant'] for x in rows],['py-reference','py-processes'])
        self.assertTrue(all(x['label']=='profiled run; diagnostic only, never compared with unprofiled runs' for x in rows))
    def test_job_reports_a_failed_child_and_drops_its_files(self):
        d,m,out=cases_dir(self)
        for result,error in ((child(returncode=1),'profile failed'),(child(returncode=-9,timed_out=True),'deadline')):
            with self.subTest(error=error),mock.patch.object(bc,'SRC',d),mock.patch.object(bc,'run_group',return_value=result):
                r=bc.job_profile({'deadline_seconds':100,'case_manifest':str(m),'variants':['py-reference'],'rows':64,'dataset':{'kind':'synthetic','seed':1}},out)
                self.assertEqual(r['status'],'FAIL');self.assertEqual(r['files'],['profile.json'])
                self.assertEqual(json.loads((out/'profile.json').read_text())[0]['error'],error)

class RunGroupTests(unittest.TestCase):
    """Review fix (Minor 7): a child past its deadline is killed with its whole process group (spawned workers included)."""
    # Task 19a (0.5 s per-file budget): the 2 s timeout test runs in benchmarks/performance/python/tests/test_marked_run.py.
    def test_a_normal_child_returns_its_output(self):
        r=bc.run_group([sys.executable,'-c','import sys;print("ok");sys.stderr.write("e")'],timeout=30)
        self.assertEqual((r.returncode,r.stdout.strip(),r.stderr,r.timed_out),(0,'ok','e',False))


class PyLibraryValidateTests(unittest.TestCase):
    """Task 9b: py-library (language python-library) is an implemented Python variant for profile and validate."""
    def case(self):
        import copy
        case=copy.deepcopy(bench.bm.load_case(ROOT,'bench-control-spin'))
        case['variants'].append({'id':'py-library','language':'python-library','workers':['direct'],'status':'implemented','reason':'C++ library through SWIG'})
        return case
    def test_profile_accepts_py_library(self):
        self.assertEqual(bench.profile_variants(self.case(),['py-library']),['py-library'])
    def run_validate(self,variants):
        d=tmpdir(self);row={'status':'PASS','adapter':'importable','variants':[{'variant':v,'eligible':True,'work_units':1} for v in variants]}
        FakeSession.result=dict(FakeSession.BASE,output=json.dumps(row)+'\n')
        case=self.case()
        policy=bench.bm.load_policy(ROOT)
        with mock.patch.object(bench,'BenchSession',FakeSession),mock.patch.object(bench,'project_arg',lambda root,args:None),\
             mock.patch.object(bench.bm,'load_case',lambda root,name,project=None:case),mock.patch.object(bench.bm,'case_rules',lambda *a,**k:True),\
             mock.patch.object(bench.bm,'load_policy',lambda root,project_dir=None:policy),\
             mock.patch.object(bench.bm,'container_case_path',lambda *a,**k:'/src/x.json'),mock.patch('builtins.print'):
            code=bench.validate_case(d,argparse.Namespace(case='x',project=None,format='json'))
        FakeSession.result=dict(FakeSession.BASE)
        return code,json.loads((next((d/'artifacts/bench').iterdir())/'validate.json').read_text())
    def test_validate_fails_when_an_implemented_python_variant_is_missing(self):
        ids=[v['id'] for v in self.case()['variants'] if v['language'] in ('python','python-library') and v['status']=='implemented']
        self.assertIn('py-library',ids)
        code,result=self.run_validate(ids);self.assertEqual((code,result['status']),(0,'PASS'))
        code,result=self.run_validate([v for v in ids if v!='py-library']);self.assertEqual(result['status'],'FAIL');self.assertNotEqual(code,0)

if __name__=='__main__':unittest.main()
