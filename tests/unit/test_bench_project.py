import importlib.util, json, shutil, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from evidence import GateError
import bench_model as bm
spec=importlib.util.spec_from_file_location('bc',ROOT/'container/bench-coordinator.py');bc=importlib.util.module_from_spec(spec);spec.loader.exec_module(bc)

def project(decl,cases=('demo-case',)):
    d=Path(tempfile.mkdtemp());shutil.copytree(ROOT/'schemas',d/'schemas');shutil.copytree(ROOT/'benchmarks/performance/cases',d/'benchmarks/performance/cases')
    base=d/'p/benchmarks/project';(base/'cases').mkdir(parents=True);(base/'bench.json').write_text(json.dumps(decl))
    manifest=json.loads((ROOT/'benchmarks/performance/cases/bench-control-spin.json').read_text())
    for c in cases:(base/'cases'/f'{c}.json').write_text(json.dumps(dict(manifest,case_id=c)))
    return d

class ProjectDeclarationTests(unittest.TestCase):
    OK={'schema_version':1,'name':'demo','cases':['demo-case']}
    def test_valid_declaration_and_case_lookup(self):
        d=project(self.OK);self.assertEqual(bm.project_bench(d,'p')['cases'],['demo-case'])
        self.assertEqual(bm.load_case(d,'demo-case','p')['case_id'],'demo-case');self.assertEqual(bm.load_case(d,'bench-control-spin')['case_id'],'bench-control-spin')
        self.assertIn('demo-case',bm.case_ids(d,'p'));self.assertNotIn('demo-case',bm.case_ids(d))
        self.assertEqual(bm.container_case_path('demo-case','p'),'/src/p/benchmarks/project/cases/demo-case.json')
    def test_declaration_is_closed_no_flags_limits_or_deadlines(self):
        for extra in ({'flags':['-O3']},{'deadline_seconds':5},{'envelope':{'cpus':8}}):
            with self.subTest(extra=extra),self.assertRaises(GateError):bm.project_bench(project(dict(self.OK,**extra)),'p')
        bad_check=dict(self.OK,checks=[{'name':'agreement','module':'demo.checks','before_run':True,'timeout':9}])
        with self.assertRaises(GateError):bm.project_bench(project(bad_check),'p')
    def test_manifests_must_match_the_declaration(self):
        with self.assertRaises(GateError):bm.project_bench(project(self.OK,cases=('demo-case','extra-case')),'p')
        with self.assertRaises(GateError):bm.project_bench(project(dict(self.OK,cases=['demo-case','missing-case'])),'p')
        with self.assertRaises(GateError):bm.project_bench(project(dict(self.OK,cases=['bench-control-spin']),cases=('bench-control-spin',)),'p')
    def test_coordinator_project_path_is_confined(self):
        for bad in ('../x','/abs','a//b','a/../b','x'*201,7):
            with self.subTest(bad=bad),self.assertRaises(ValueError):bc.configure_project({'project_dir':bad})
        self.assertIsNone(bc.configure_project({}))
    def test_project_module_names_must_not_shadow(self):
        for name in ('json','numpy','benchlab'):
            d=project(self.OK);(d/f'p/benchmarks/project/python/{name}').mkdir(parents=True)
            with self.subTest(name=name),self.assertRaises(GateError):bm.project_bench(d,'p')
        d=project(dict(self.OK,checks=[{'name':'agreement','module':'random.checks','before_run':True}]))
        with self.assertRaises(GateError):bm.project_bench(d,'p')
        d=project(self.OK);(d/'p/benchmarks/project/python').mkdir(parents=True);(d/'p/benchmarks/project/python/_thread.py').write_text('')
        with self.assertRaises(GateError):bm.project_bench(d,'p')          # '_' names are checked too

class ProjectConfinementTests(unittest.TestCase):
    OK={'schema_version':1,'name':'demo','cases':['demo-case']}
    def test_coordinator_appends_the_project_after_the_framework_and_refuses_shadowing(self):
        d=project(self.OK);py=d/'p/benchmarks/project/python';(py/'demo_pkg').mkdir(parents=True)
        saved=(bc.SRC,bc.PYTHONPATH,bc.PROJECT_PY,list(sys.path))
        try:
            bc.SRC=d;base=bc.configure_project({'project_dir':'p'})
            self.assertEqual(base,str(py));self.assertTrue(bc.PYTHONPATH.startswith(saved[1]+':'));self.assertTrue(bc.PYTHONPATH.endswith(':'+str(py)))
            self.assertEqual(bc.child_env()['PYTHONPATH'].split(':')[-1],str(py))
            for name in ('_thread.py','json','benchlab','numpy'):
                bc.PYTHONPATH=saved[1];target=py/name
                (target.write_text('') if name.endswith('.py') else target.mkdir())
                with self.subTest(name=name),self.assertRaises(ValueError):bc.configure_project({'project_dir':'p'})
                (target.unlink() if name.endswith('.py') else target.rmdir())
            with self.assertRaises(ValueError):bc.configure_project({'project_dir':'missing'})
        finally:bc.SRC,bc.PYTHONPATH,bc.PROJECT_PY=saved[:3];sys.path[:]=saved[3]
    def test_a_rejected_project_dir_is_a_fail_result(self):
        d=Path(tempfile.mkdtemp());(d/'bench').mkdir();(d/'bench/plan.json').write_text(json.dumps({'job':'unit','project_dir':'../x','deadline_seconds':60}))
        saved=bc.WORK
        try:
            bc.WORK=d;import io, contextlib
            with contextlib.redirect_stdout(io.StringIO()):code=bc.main(['x','bench/plan.json'])
            self.assertEqual(code,1);self.assertEqual(json.loads((d/'bench/out/result.json').read_text()),{'status':'FAIL','reason':'project_dir rejected'})
        finally:bc.WORK=saved
    def test_a_project_outside_the_root_or_a_linked_declaration_is_refused(self):
        d=project(self.OK);outside=project(self.OK);(d/'q').symlink_to(outside/'p')
        with self.assertRaises(GateError):bm.project_bench(d,'q')
        d=project(self.OK);decl=d/'p/benchmarks/project/bench.json';real=d/'decl.json';decl.rename(real);decl.symlink_to(real)
        with self.assertRaises(GateError):bm.project_bench(d,'p')
        d=project(self.OK);m=d/'p/benchmarks/project/cases/demo-case.json';real=d/'m.json';m.rename(real);m.symlink_to(real)
        with self.assertRaises(GateError):bm.project_bench(d,'p')
    def test_container_case_paths(self):
        self.assertEqual(bm.container_case_path('demo-case','.'),'/src/benchmarks/project/cases/demo-case.json')
        self.assertEqual(bm.container_case_path('bench-control-spin'),'/src/benchmarks/performance/cases/bench-control-spin.json')
        d=project(self.OK)
        self.assertEqual(bm.container_case_path('bench-control-spin','p',d),'/src/benchmarks/performance/cases/bench-control-spin.json')
        self.assertEqual(bm.container_case_path('demo-case','p',d),'/src/p/benchmarks/project/cases/demo-case.json')
    def test_project_arg_defaults_only_inside_a_registered_project(self):
        import argparse
        import bench
        d=project(self.OK);ns=argparse.Namespace(project=None)
        self.assertIsNone(bench.project_arg(d,ns));self.assertEqual(bench.project_arg(d,argparse.Namespace(project='p')),'p')
        base=d/'p';shutil.copytree(d/'schemas',base/'schemas');shutil.copytree(d/'benchmarks/performance',base/'benchmarks/performance')
        self.assertIsNone(bench.project_arg(base,ns));(base/'project.json').write_text('{}')
        self.assertEqual(bench.project_arg(base,ns),'.')
        with self.assertRaises(GateError):bench.project_arg(d,argparse.Namespace(project='../x'))
    def test_run_check_refuses_an_undeclared_check_before_any_container(self):
        import bench
        d=project(self.OK);(d/'safety').mkdir();shutil.copy(ROOT/'safety/performance-policy.json',d/'safety')
        with self.assertRaises(GateError):bench.run_check(d,d/'run','p','agreement')

class ReviewFixTests(unittest.TestCase):
    OK={'schema_version':1,'name':'demo','cases':['demo-case']}
    def test_an_intermediate_symlink_cannot_escape_the_project(self):
        d=project(self.OK);outside=project(self.OK)
        shutil.rmtree(d/'p/benchmarks');(d/'p/benchmarks').symlink_to(outside/'p/benchmarks')
        for call in (lambda:bm.project_bench(d,'p'),lambda:bm.case_ids(d,'p'),lambda:bm.load_case(d,'demo-case','p')):
            with self.assertRaises(GateError):call()
        d=project(self.OK);shutil.rmtree(d/'p/benchmarks/project/cases');(d/'p/benchmarks/project/cases').symlink_to(outside/'p/benchmarks/project/cases',target_is_directory=True)
        with self.assertRaises(GateError):bm.project_bench(d,'p')
    def test_an_opportunity_record_outside_the_project_is_refused(self):
        d=project(self.OK);outside=project(self.OK);record=json.loads((ROOT/'tests/unit/data/bench-plan-case.opportunity.json').read_text())
        (outside/'p/benchmarks/project/cases/demo-case.opportunity.json').write_text(json.dumps(dict(record,case_id='demo-case')))
        bm.load_opportunity(outside,{'case_id':'demo-case','opportunity_record':'benchmarks/project/cases/demo-case.opportunity.json'},'p')   # valid in place
        shutil.rmtree(d/'p/benchmarks/project/cases');(d/'p/benchmarks/project/cases').symlink_to(outside/'p/benchmarks/project/cases')
        with self.assertRaises(GateError):bm.load_opportunity(d,{'case_id':'demo-case','opportunity_record':'benchmarks/project/cases/demo-case.opportunity.json'},'p')
    def test_coordinator_refuses_an_intermediate_symlink(self):
        d=project(self.OK);outside=project(self.OK);(outside/'p/benchmarks/project/python').mkdir()
        shutil.rmtree(d/'p/benchmarks');(d/'p/benchmarks').symlink_to(outside/'p/benchmarks')
        saved=(bc.SRC,bc.PYTHONPATH,bc.PROJECT_PY,list(sys.path))
        try:
            bc.SRC=d
            with self.assertRaises(ValueError):bc.configure_project({'project_dir':'p'})
            self.assertFalse(bc.inside_src(outside/'x'));self.assertTrue(bc.inside_src(d/'p'))
        finally:bc.SRC,bc.PYTHONPATH,bc.PROJECT_PY=saved[:3];sys.path[:]=saved[3]
    def test_startup_hooks_and_framework_packages_are_reserved(self):
        for name in ('sitecustomize.py','usercustomize','benchlab','tests.py'):
            d=project(self.OK);py=d/'p/benchmarks/project/python';py.mkdir(parents=True)
            (py/name).write_text('') if name.endswith('.py') else (py/name).mkdir()
            with self.subTest(name=name),self.assertRaises(GateError):bm.project_bench(d,'p')
        for module in ('sitecustomize','tests.checks','benchlab.checks'):
            d=project(dict(self.OK,checks=[{'name':'agreement','module':module,'before_run':True}]))
            with self.subTest(module=module),self.assertRaises(GateError):bm.project_bench(d,'p')
        self.assertTrue({'sitecustomize','usercustomize','tests','benchlab'}<=bc.reserved_modules())
        # Amendment A: the example library left the framework, so a project (the reference example) may own that package name.
        self.assertNotIn('optionlab',bc.reserved_modules());self.assertNotIn('optionlab',bm.RESERVED_MODULES)
    def test_project_children_start_isolated_so_no_startup_hook_runs(self):
        import subprocess
        d=Path(tempfile.mkdtemp());marker=d/'ran'
        (d/'sitecustomize.py').write_text(f'open({str(marker)!r},"w").write("x")\n')
        env={'PATH':'/usr/bin:/bin','PYTHONPATH':str(d)}
        subprocess.run([sys.executable,'-c','pass'],env=env,check=True,timeout=20)
        self.assertTrue(marker.exists());marker.unlink()                       # control: a plain start runs the hook
        argv=bc.python_argv(str(d),'-c','import sys;print(sys.flags.isolated, sys.dont_write_bytecode, sys.argv[1:])','a1')
        self.assertEqual(argv[1],'-I')
        out=subprocess.run(argv,env=env,capture_output=True,text=True,check=True,timeout=20).stdout.split()
        self.assertFalse(marker.exists());self.assertEqual(out[:2],['1','True']);self.assertIn("'a1']",out[-1])
    def test_jobs_start_children_through_the_isolated_argv(self):
        from unittest import mock
        seen=[]
        class Done:
            returncode=0;stdout='{"status":"PASS"}\n';stderr=''
        def fake(argv,**k):seen.append(argv);return Done()
        d=Path(tempfile.mkdtemp());py=d/'p/benchmarks/project/python';py.mkdir(parents=True);out=d/'out';out.mkdir()
        (d/'p/benchmarks/project/bench.json').write_text(json.dumps(dict(self.OK,checks=[{'name':'agreement','module':'demo.checks','before_run':True}])))
        saved=(bc.SRC,bc.PYTHONPATH,bc.PROJECT_PY,list(sys.path))
        try:
            bc.SRC=d;bc.configure_project({'project_dir':'p'})
            with mock.patch.object(bc.subprocess,'run',fake):
                bc.job_unit({'deadline_seconds':100},out);bc.job_validate({'deadline_seconds':100,'case_manifest':str(d/'p/benchmarks/project/cases/x.json')},out)
                bc.job_check({'deadline_seconds':100,'check':'agreement'},out)
        finally:bc.SRC,bc.PYTHONPATH,bc.PROJECT_PY=saved[:3];sys.path[:]=saved[3]
        self.assertEqual(len(seen),3);self.assertTrue(all(a[1]=='-I' for a in seen),[a[:2] for a in seen])
    def check_row(self,stdout,returncode=0,decl=None):
        from unittest import mock
        class Done:pass
        done=Done();done.returncode=returncode;done.stdout=stdout;done.stderr=''
        d=Path(tempfile.mkdtemp());py=d/'p/benchmarks/project/python';py.mkdir(parents=True);out=d/'out';out.mkdir()
        (d/'p/benchmarks/project/bench.json').write_text(decl if decl is not None else json.dumps(dict(self.OK,checks=[{'name':'agreement','module':'demo.checks','before_run':True}])))
        saved=(bc.SRC,bc.PYTHONPATH,bc.PROJECT_PY,list(sys.path))
        try:
            bc.SRC=d;bc.configure_project({'project_dir':'p'})
            with mock.patch.object(bc.subprocess,'run',lambda *a,**k:done):return bc.job_check({'deadline_seconds':100,'check':'agreement'},out)
        finally:bc.SRC,bc.PYTHONPATH,bc.PROJECT_PY=saved[:3];sys.path[:]=saved[3]
    def test_check_row_keeps_only_allowlisted_bounded_keys(self):
        row=self.check_row(json.dumps({'status':'PASS','files':['a.json','../b','/abs']+[f'f{i}.json' for i in range(40)],'counts':{'rows':3,'Bad Key':1,'big':True},
                                       'label':'x'*500,'path':'/data/owner/dataset.json','secret':[1,2]})+'\n')
        self.assertEqual(set(row),{'status','check','files','counts','dropped_keys'})
        self.assertEqual(row['status'],'PASS');self.assertEqual(row['counts'],{'rows':3});self.assertEqual(row['files'][0],'a.json')
        self.assertLessEqual(len(row['files']),32);self.assertNotIn('../b',row['files']);self.assertNotIn('/abs',row['files'])
        self.assertNotIn('/data/owner',json.dumps(row));self.assertEqual(row['dropped_keys'],3)
        self.assertEqual(self.check_row(json.dumps({'label':'rows/agree'})+'\n')['status'],'PASS')
        self.assertNotIn('label',self.check_row(json.dumps({'label':'rows/agree'})+'\n'))      # a path-like label is dropped
    def test_check_counts_reach_the_host_whole_or_the_row_fails(self):
        # ruling T28-C2: no silent truncation. The 19 oracle count keys (natural order) all reach the host, 32 keys pass,
        # and 33 keys make the row FAIL with a named reason and no partial counts
        oracle={**{f'item{k}_{x}':k for k in range(1,10) for x in ('checked','failures')},'incomplete_items':1}
        row=self.check_row(json.dumps({'status':'PASS','counts':oracle})+'\n')
        self.assertEqual((row['status'],row['counts']),('PASS',oracle))
        for key in ('item8_failures','item9_checked','item9_failures','incomplete_items'):self.assertIn(key,row['counts'])
        full={f'k{i}':i for i in range(32)}
        row=self.check_row(json.dumps({'status':'PASS','counts':full})+'\n')
        self.assertEqual((row['status'],row['counts']),('PASS',full))
        over={f'k{i}':i for i in range(33)}
        row=self.check_row(json.dumps({'status':'PASS','counts':over})+'\n')
        self.assertEqual(row['status'],'FAIL');self.assertEqual(row['reason'],'check row has more count keys than the bound')
        self.assertNotIn('counts',row)
    def test_check_status_comes_from_the_framework(self):
        self.assertEqual(self.check_row('{"status":"PASS"}\n',returncode=3)['status'],'FAIL')    # the row never upgrades
        self.assertEqual(self.check_row('{"status":"FAIL"}\n')['status'],'FAIL')                 # it may only report a failure
        self.assertEqual(self.check_row('{"status":"GREAT"}\n')['status'],'FAIL')
        self.assertEqual(self.check_row('not json\n')['status'],'FAIL')
    def test_check_with_a_broken_declaration_is_a_fail_result(self):
        for decl in ('{','[]',json.dumps({'checks':[{'name':'agreement'}]}),json.dumps({'checks':[{'name':'agreement','module':'../x','before_run':True}]})):
            with self.subTest(decl=decl):self.assertEqual(self.check_row('{}\n',decl=decl)['status'],'FAIL')
    def test_host_revalidates_fetched_file_names(self):
        import bench
        self.assertEqual(bench.check_files({'files':['ok.json','../x','/abs','.','..','a'*81,7,'b.txt']}),['ok.json','b.txt'])
        self.assertEqual(bench.check_files({'files':'ok.json'}),[]);self.assertEqual(bench.check_files({}),[])
    def test_host_and_container_share_one_path_rule(self):
        self.assertEqual(bm.PROJECT_RE.pattern,bc.PROJECT_RE.pattern)
        d=project(self.OK)
        for bad in ('.hidden','a b','caf\u00e9','p/.x'):
            with self.subTest(bad=bad),self.assertRaises(GateError):bm.project_bench(d,bad)
    def test_plan_identity_binds_content_not_location(self):
        import bench_plan as bp
        a=project(self.OK);b=Path(tempfile.mkdtemp());shutil.copytree(a/'schemas',b/'schemas');shutil.copytree(a/'benchmarks',b/'benchmarks')
        shutil.copytree(a/'p/benchmarks',b/'benchmarks',dirs_exist_ok=True);(b/'project.json').write_text('{}')
        for d in (a,b):
            py=(d/'p' if d is a else d)/'benchmarks/project/python';(py/'benchlab_x').mkdir(parents=True);(py/'benchlab_x/__init__.py').write_text('X=1\n')
        case=bm.load_case(a,'demo-case','p');case_b=bm.load_case(b,'demo-case','.')
        ia=bm.project_identity(a,'p',case);ib=bm.project_identity(b,'.',case_b);self.assertEqual(ia,ib);self.assertRegex(ia,'^[0-9a-f]{64}$')
        policy=bm.load_policy(ROOT);ds={'kind':'synthetic','size':'small','seed':1,'sha256':None,'rows':256};env={'cpus':4,'cpuset':[0,1,2,3]}
        pa=bp.build_plan(case,policy,mode='smoke',dataset=ds,seed=1,envelope=env,project_dir='p',project_identity=ia)
        pb=bp.build_plan(case_b,policy,mode='smoke',dataset=ds,seed=1,envelope=env,project_dir='.',project_identity=ib)
        self.assertEqual(pa['plan_id'],pb['plan_id']);self.assertEqual((pa['project_dir'],pb['project_dir']),('p','.'))
        manifest=json.loads((ROOT/'benchmarks/performance/cases/bench-control-spin.json').read_text())
        (a/'p/benchmarks/project/cases/demo-case.json').write_text(json.dumps(dict(manifest,case_id='demo-case',adapter='benchlab_x:Thing')))
        self.assertNotEqual(bm.project_identity(a,'p',bm.load_case(a,'demo-case','p')),ia)
        case2=bm.load_case(a,'demo-case','p');i2=bm.project_identity(a,'p',case2);(a/'p/benchmarks/project/python/benchlab_x/__init__.py').write_text('X=2\n')
        self.assertNotEqual(bm.project_identity(a,'p',case2),i2)                  # the adapter package is bound

class UnitGroupTests(unittest.TestCase):
    """Ruling A6-C3 (Task A6 lock follow-up): a project may declare `unit_groups`, a fixed partition of its
    python/tests/test_*.py modules; `bench selftest --suite unit --project` then runs one container command per group
    (each within one container's lifetime). Every module must be in exactly one group; no test is removed."""
    BASE={'schema_version':1,'name':'demo','cases':['demo-case']}
    def make(self,groups,modules=('test_a','test_b','test_c')):
        d=project(dict(self.BASE,unit_groups=groups) if groups is not None else self.BASE);t=d/'p/benchmarks/project/python/tests';t.mkdir(parents=True)
        (t/'__init__.py').write_text('')
        for m in modules:(t/f'{m}.py').write_text('')
        self.addCleanup(shutil.rmtree,d);return d
    def test_no_groups_is_one_discover_run(self):
        self.assertIsNone(bm.unit_groups(self.make(None),'p'))
    def test_a_partition_is_returned_in_order(self):
        self.assertEqual(bm.unit_groups(self.make([['test_b'],['test_a','test_c']]),'p'),[['test_b'],['test_a','test_c']])
    def test_a_missing_duplicate_or_unknown_module_is_refused(self):
        for groups in ([['test_a'],['test_b']],[['test_a','test_b'],['test_b','test_c']],[['test_a','test_b'],['test_c','test_d']]):
            with self.subTest(groups=groups),self.assertRaises(GateError):bm.unit_groups(self.make(groups),'p')
    def test_the_schema_refuses_a_bad_group_form(self):
        for groups in ([['test_a','test_b','test_c']],[['a'],['test_b','test_c']],[[],['test_a','test_b','test_c']],[['test_a.py'],['test_b','test_c']]):
            with self.subTest(groups=groups),self.assertRaises(GateError):bm.unit_groups(self.make(groups),'p')
    def test_the_coordinator_accepts_only_module_names(self):
        self.assertEqual(bc.unit_modules({'unit_modules':['test_a','test_b']}),['test_a','test_b'])
        self.assertIsNone(bc.unit_modules({}))
        for bad in ({'unit_modules':[]},{'unit_modules':['a']},{'unit_modules':['test_a;x']},{'unit_modules':'test_a'},{'unit_modules':['test_a']*65}):
            with self.subTest(bad=bad),self.assertRaises(ValueError):bc.unit_modules(bad)

class CheckCountTests(unittest.TestCase):
    """Phase 2 merge request (Task A6 lock follow-up, controller-approved): a project declares at most 32 checks (the
    reference example held 18 checks at the time)."""
    def decl(self,n):
        return {'schema_version':1,'name':'demo','cases':['demo-case'],'checks':[{'name':f'check-{i:02d}','module':'demo_checks','before_run':False} for i in range(n)]}
    def test_32_checks_are_accepted_and_33_refused(self):
        from schema_check import validate
        self.assertTrue(validate(ROOT,'bench-project',self.decl(32)))
        with self.assertRaises(GateError):validate(ROOT,'bench-project',self.decl(33))
