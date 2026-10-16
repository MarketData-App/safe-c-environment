import argparse, contextlib, io, json, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import bench_privacy as bp, bench_evidence as be, bench_accounting as ba, project_model
from evidence import GateError

STATIC_CHECKS=['payload','scaffolding','replay','docs','concurrency-policy','metric-profiles','runtime-exclusion']
CHILD_CHECKS=['payload-in-instances','child-measured','no-copied-parent-runs','no-grandchildren']

def write_run(child,run_id,identity,mode='smoke',status='VALID'):
    """A digest-bound run directory of the bench run shape under <child>/artifacts/bench/<run_id>."""
    rd=Path(child)/'artifacts/bench'/run_id;rd.mkdir(parents=True);(rd/'plan.json').write_text('{}')
    run={'run_id':run_id,'mode':mode,'status':status,'source_identity':identity}
    run['evidence_digests']=be.digest_files(rd);run[be.RECORD_KEY]=be.run_record_sha256(run);(rd/'run.json').write_text(json.dumps(run))
    return rd

def family(t):
    """A parent root with one payload file, the two starter instances holding it, and a measured designated child."""
    parent=Path(t)/'parent';(parent/'tools').mkdir(parents=True);(parent/'tools/bench_x.py').write_text('x = 1\n')
    first=Path(t)/'instances'/'first project with space';second=Path(t)/'instances'/'second-project'
    for c in (first,second):(c/'tools').mkdir(parents=True);shutil.copy2(parent/'tools/bench_x.py',c/'tools/bench_x.py')
    (first/'artifacts').mkdir()
    (first/'artifacts/bootstrap-report.json').write_text(json.dumps({'local_state':'PASS','source_identity':'c'*64,
        'gates':[{'name':'bench-doctor','status':'PASS'},{'name':'bench-selftest','status':'PASS'}]}))
    write_run(first,'1'*32,'c'*64)
    return parent,first,second

TRACKED=['benchmarks/performance/case.json','examples/demo/benchmarks/project/bench.json','examples/demo/src/demo.py','tools/bench_tracked.py']
UNTRACKED=['tools/bench_ignored_local.py','examples/demo/ignored-sample-data.json','benchmarks/performance/untracked-note.json']

def git_tree(t):
    """T26-B18-01: a temporary git repository (never the real tree) whose bench area and example tree hold tracked files,
    two git-ignored synthetic files and one untracked file that is not ignored."""
    root=Path(t)/'repo'
    for rel in TRACKED+UNTRACKED:p=root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('{}\n')
    (root/'.gitignore').write_text('bench_ignored_local.py\nignored-sample-data.json\n')
    env={'PATH':os.environ.get('PATH','/usr/bin:/bin'),'HOME':str(t),'GIT_CONFIG_NOSYSTEM':'1'}
    for argv in (['init','-q'],['add','--','.gitignore',*TRACKED]):
        subprocess.run(['git','-C',str(root),*argv],env=env,check=True,capture_output=True)
    return root

def child(parent,first,second,**over):
    import bench_b18
    kw=dict(instances=[second],before_runs=[],parent_identity='a'*64,child_identity='c'*64);kw.update(over)
    return bench_b18.child_checks(parent,first,**kw)

class B18Tests(unittest.TestCase):
    def test_payload_is_exported(self):
        import bench_b18
        files=set(json.loads((ROOT/'starter-export.json').read_text())['files'])
        self.assertEqual([p for p in bench_b18.payload(ROOT) if p not in files],[])
    def test_payload_holds_every_bench_area_and_no_generated_file(self):
        import bench_b18
        got=bench_b18.payload(ROOT)
        for p in ('tools/bench_b18.py','tools/bench_replay.py','container/bench-coordinator.py','schemas/bench-run.json',
                  'safety/performance-policy.json','docs/performance-laboratory.md'):self.assertIn(p,got)
        self.assertTrue(any(p.startswith('benchmarks/performance/') for p in got))
        import bench
        examples=bench.example_projects(ROOT);self.assertTrue(examples)       # found by layout; the framework names no example
        for e in examples:self.assertTrue(any(p.startswith(e+'/') for p in got),e)
        self.assertFalse(any('__pycache__' in p or p.startswith('artifacts/') or '/artifacts/' in p for p in got))
        self.assertEqual(got,sorted(set(got)))
    def test_runtime_exclusion(self):
        import bench_b18
        self.assertEqual(bench_b18.runtime_bench_files(ROOT),[])
    def test_runtime_exclusion_rejects_planted_bench_assets(self):
        import bench_b18
        planted={'runtime-image':['demo','benchlab/trial.py','opt/pyperf/__init__.py','lib/sc-mutant.so','data/dataset.jsonl','bin/bench-coordinator.py']}
        got=bench_b18.runtime_bench_files(ROOT,inventories=planted)
        self.assertEqual(len(got),5);self.assertFalse(any(g.endswith(': demo') for g in got))
        self.assertEqual(bench_b18.runtime_bench_files(ROOT,inventories={'runtime-image':['demo','lib/x86_64-linux-gnu/libc.so.6']}),[])
    def test_child_checks_reject_copied_parent_runs(self):
        import bench_b18
        with tempfile.TemporaryDirectory() as t:
            child=Path(t)/'c';(child/'artifacts/bench').mkdir(parents=True)
            r=bench_b18.copied_parent_runs(parent_identity='a'*64,child_root=child,child_runs=[{'source_identity':'a'*64}])
            self.assertEqual(r,['a child run carries the parent source identity'])
    def test_copied_parent_runs_accepts_the_child_own_runs(self):
        import bench_b18
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(bench_b18.copied_parent_runs(parent_identity='a'*64,child_root=Path(t),child_runs=[{'source_identity':'c'*64}]),[])
    def test_instance_mode_runs_only_the_static_checks(self):
        """Child-instance mode (--instance): bench_b18.static_checks decides the bench part; no export, no instance, no child."""
        import bench_b18, starter
        for static,want in (('PASS','PASS'),('FAIL','FAIL')):
            with self.subTest(static=static),tempfile.TemporaryDirectory() as t:
                root=Path(t);(root/'starter-baseline.lock.json').write_text(json.dumps({'kind':'project-instance','origin_digest':'e'*64}))
                never=mock.Mock(side_effect=AssertionError('maintenance work in instance mode'))
                result={'status':static,'checks':{}}
                with mock.patch.object(starter,'baseline_gate',return_value='bound'),mock.patch.object(starter,'instantiate',never),\
                     mock.patch.object(starter,'package_candidate',never),mock.patch.object(starter,'run_child',never),\
                     mock.patch.object(bench_b18,'static_checks',return_value=result) as sc,mock.patch.object(bench_b18,'child_checks',never):
                    got=starter.verify_starter(root,{},root,instance=True,expected='e'*64,baseline=root)
                sc.assert_called_once_with(root)
                self.assertEqual((got['status'],got['bench_b18']),(want,result))

class StaticCheckTests(unittest.TestCase):
    def test_static_checks_pass_on_this_tree(self):
        import bench_b18
        r=bench_b18.static_checks(ROOT)
        self.assertEqual(list(r['checks']),STATIC_CHECKS)
        self.assertEqual({k:v['status'] for k,v in r['checks'].items()},{k:'PASS' for k in STATIC_CHECKS},{k:v.get('problems') for k,v in r['checks'].items()})
        self.assertEqual(r['status'],'PASS')
    def test_a_failed_or_raising_check_is_fail_never_pass_or_blocked(self):
        import bench_b18
        for effect in (['missing: docs/performance-laboratory.md'],GateError('docs unreadable'),OSError('gone')):
            kw={'side_effect':effect} if isinstance(effect,Exception) else {'return_value':effect}
            with self.subTest(effect=repr(effect)),mock.patch.object(bench_b18,'check_docs',**kw):
                r=bench_b18.static_checks(ROOT)
            self.assertEqual((r['status'],r['checks']['docs']['status']),('FAIL','FAIL'))
            self.assertTrue(r['checks']['docs']['problems'])
            self.assertEqual(r['checks']['payload']['status'],'PASS')
    def test_unexported_payload_fails(self):
        import bench_b18
        with mock.patch.object(bench_b18,'payload',return_value=['tools/bench_unlisted.py']):
            self.assertEqual(bench_b18.check_payload(ROOT),['not exported: tools/bench_unlisted.py'])
    def test_payload_takes_only_git_tracked_files(self):
        # T26-B18-01: in a git checkout the payload is the git-tracked files of the bench areas and example trees only, so a
        # git-ignored (or untracked) file there never enters the payload, the export check or a child payload check.
        import bench_b18
        with tempfile.TemporaryDirectory() as t:
            root=git_tree(t)
            self.assertEqual(bench_b18.payload(root),TRACKED)
            (root/'starter-export.json').write_text(json.dumps({'files':TRACKED}))
            self.assertEqual(bench_b18.check_payload(root),[])
            inst=Path(t)/'instance'
            for rel in TRACKED:(inst/rel).parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/rel,inst/rel)
            self.assertEqual(bench_b18._payload_missing(root,[inst]),[])
            (inst/TRACKED[-1]).unlink()
            self.assertEqual(bench_b18._payload_missing(root,[inst]),['instance: missing '+TRACKED[-1]])
    def test_payload_of_an_unreadable_git_checkout_fails_closed(self):
        # T26-B18-01: a tree that declares a git checkout whose tracked set cannot be read gives no walked payload
        import bench_b18
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)/'repo';(root/'tools').mkdir(parents=True);(root/'tools/bench_x.py').write_text('x = 1\n')
            (root/'.git').write_text('gitdir: '+str(Path(t)/'absent-git-dir')+'\n')
            with self.assertRaises(GateError):bench_b18.payload(root)
            self.assertEqual(bench_b18._result('payload',lambda:bench_b18.check_payload(root))['status'],'FAIL')
    def test_container_source_snapshot_payload_takes_only_the_host_tracked_files(self):
        # T27-03: the container source snapshot has no .git and holds git-ignored files (policy.source_files copies them).
        # The real Runner.start snapshot of a temporary git repository carries the host tracked set, so a git-ignored or
        # untracked synthetic file never enters the B18 payload or a `not exported:` line inside the container.
        import bench_b18, evidence, policy
        with tempfile.TemporaryDirectory() as t:
            root=git_tree(t);(root/'starter-export.json').write_text(json.dumps({'files':TRACKED}))
            launcher=mock.MagicMock();launcher.create.return_value={'container_id':'c'}
            with mock.patch('container_policy.Launcher',return_value=launcher),\
                 mock.patch('containment.expected_binding',return_value={'source':policy.source_identity(root)[0]}):
                runner=evidence.Runner(root,Path(t)/'run',{'image_id':'sha256:test'},Path(t)/'scratch');runner.start()
            snap=runner.snapshot
            self.assertFalse((snap/'.git').exists())
            self.assertTrue(all((snap/rel).is_file() for rel in UNTRACKED))       # the snapshot itself still holds them
            self.assertEqual(bench_b18.payload(snap),TRACKED)
            self.assertEqual(bench_b18.check_payload(snap),[])
            self.assertEqual(policy.source_identity(snap)[0],policy.source_identity(root)[0])
    def test_snapshot_without_a_readable_tracked_set_fails_closed(self):
        # T27-03: a snapshot whose host tracked set could not be read (or is malformed) gives no walked payload: FAIL
        import bench_b18, policy
        with tempfile.TemporaryDirectory() as t:
            snap=Path(t)/'snap'
            for rel in TRACKED+UNTRACKED:p=snap/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('{}\n')
            m=snap/policy.TRACKED_MANIFEST;m.parent.mkdir(parents=True)
            for text in ('{"tracked": null, "reason": "git ls-files failed for the source snapshot"}','{"tracked": "x"}','[]','{"tracked": [1]}','not json'):
                m.write_text(text)
                with self.subTest(manifest=text):
                    with self.assertRaises(GateError):bench_b18.payload(snap)
                    self.assertEqual(bench_b18._result('payload',lambda:bench_b18.check_payload(snap))['status'],'FAIL')
            m.write_text(json.dumps({'tracked':TRACKED+['tools/elsewhere.py']}))
            self.assertEqual(bench_b18.payload(snap),TRACKED)
    def test_write_tracked_manifest(self):
        # T27-03: a git checkout gets its tracked set; a tree without .git gets none; an unreadable checkout records null
        import policy
        with tempfile.TemporaryDirectory() as t:
            root=git_tree(t);snap=Path(t)/'snap';snap.mkdir()
            self.assertEqual(policy.write_tracked_manifest(root,snap),{'tracked':sorted(['.gitignore',*TRACKED])})
            self.assertEqual(json.loads((snap/policy.TRACKED_MANIFEST).read_text()),{'tracked':sorted(['.gitignore',*TRACKED])})
            plain=Path(t)/'plain';plain.mkdir();other=Path(t)/'snap2';other.mkdir()
            self.assertIsNone(policy.write_tracked_manifest(plain,other));self.assertFalse((other/policy.TRACKED_MANIFEST).exists())
            broken=Path(t)/'broken';broken.mkdir();(broken/'.git').write_text('gitdir: '+str(Path(t)/'absent')+'\n')
            self.assertIsNone(policy.write_tracked_manifest(broken,other)['tracked'])
            self.assertIsNone(json.loads((other/policy.TRACKED_MANIFEST).read_text())['tracked'])
    def test_concurrency_policy(self):
        import bench_b18, bench_model as bm
        pools=bm.load_policy(ROOT)['pools'];self.assertEqual(bench_b18.check_pools(pools),[])
        for k,v in (('chunk_rule','one-per-call'),('window_per_worker',3),('start_method','fork')):
            with self.subTest(key=k):self.assertTrue(bench_b18.check_pools(dict(pools,**{k:v})))
        self.assertTrue(bench_b18.check_pools({k:v for k,v in pools.items() if k!='window_per_worker'}))
    def test_metric_profiles(self):
        import bench_b18
        pol=json.loads((ROOT/'safety/container-policy.json').read_text());self.assertEqual(bench_b18.check_profiles(pol),[])
        for var in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):
            changed=json.loads(json.dumps(pol));changed['profiles']['bench']['fixed_environment'][var]='4'
            with self.subTest(var=var):self.assertTrue(bench_b18.check_profiles(changed))
        gone=json.loads(json.dumps(pol));gone['profiles'].pop('bench');self.assertTrue(bench_b18.check_profiles(gone))
    def test_docs_follow_the_export_list(self):
        import bench_b18
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);(root/'docs').mkdir();(root/'starter-export.json').write_text(json.dumps({'files':['docs/performance-laboratory.md']}))
            self.assertEqual(bench_b18.check_docs(root),['missing: docs/performance-laboratory.md'])
            (root/'docs/performance-laboratory.md').write_text('# Performance laboratory\n');self.assertEqual(bench_b18.check_docs(root),[])
            (root/'starter-export.json').write_text(json.dumps({'files':['docs/performance-laboratory.md','prompts/performance-decision.md']}))
            self.assertEqual(bench_b18.check_docs(root),['missing: prompts/performance-decision.md'])
            (root/'docs/performance-laboratory.md').write_text('');(root/'starter-export.json').write_text(json.dumps({'files':[]}))
            self.assertEqual(bench_b18.check_docs(root),['missing: docs/performance-laboratory.md'])
    def test_scaffolding_check_detects_a_c_scaffold(self):
        import bench_b18, bench
        real=bench.new_case
        def c_scaffold(root,case_id,project_dir=None):
            paths=real(root,case_id,project_dir);m=Path(paths['manifest']);case=json.loads(m.read_text())
            case['variants'].append({'id':'c-serial','language':'c','workers':['direct'],'status':'implemented'});m.write_text(json.dumps(case))
            return paths
        self.assertEqual(bench_b18.check_scaffolding(ROOT),[])
        with mock.patch.object(bench,'new_case',side_effect=c_scaffold):self.assertTrue(bench_b18.check_scaffolding(ROOT))
    def test_replay_check_needs_the_registration(self):
        import bench_b18, bench
        self.assertEqual(bench_b18.check_replay(ROOT),[])
        with mock.patch.dict(bench.HANDLERS):
            bench.HANDLERS.pop('replay');self.assertIn('bench replay is not registered',bench_b18.check_replay(ROOT))

class ChildCheckTests(unittest.TestCase):
    def test_a_measured_child_with_the_payload_passes(self):
        with tempfile.TemporaryDirectory() as t:
            r=child(*family(t))
            self.assertEqual(list(r['checks']),CHILD_CHECKS)
            self.assertEqual({k:v['status'] for k,v in r['checks'].items()},{k:'PASS' for k in CHILD_CHECKS},{k:v.get('problems') for k,v in r['checks'].items()})
            self.assertEqual(r['status'],'PASS')
    def assert_fails(self,r,check):
        self.assertEqual((r['status'],r['checks'][check]['status']),('FAIL','FAIL'));self.assertTrue(r['checks'][check]['problems'])
    def test_an_instance_without_the_whole_payload_fails(self):
        with tempfile.TemporaryDirectory() as t:
            parent,first,second=family(t);(second/'tools/bench_x.py').write_text('x = 2\n')
            self.assert_fails(child(parent,first,second),'payload-in-instances')
            (parent/'tools/bench_y.py').write_text('y = 1\n');(second/'tools/bench_x.py').write_text('x = 1\n')
            self.assert_fails(child(parent,first,second),'payload-in-instances')
    def test_a_child_without_its_own_measured_runs_fails(self):
        for name in ('unreadable run.json','decision mode only','tampered run.json','changed evidence file','failed bench gate','parent identity in the report'):
            with self.subTest(case=name),tempfile.TemporaryDirectory() as t:
                parent,first,second=family(t);rd=first/'artifacts/bench'/('1'*32);over={}
                if name=='unreadable run.json':(rd/'run.json').write_text('')
                if name=='decision mode only':
                    run=json.loads((rd/'run.json').read_text());run['mode']='decision';run[be.RECORD_KEY]=be.run_record_sha256(run);(rd/'run.json').write_text(json.dumps(run))
                if name=='tampered run.json':
                    run=json.loads((rd/'run.json').read_text());run['reasons']=['edited after the run'];(rd/'run.json').write_text(json.dumps(run))   # record digest only
                if name=='changed evidence file':(rd/'plan.json').write_text('{"edited": true}')          # evidence digest only
                if name=='failed bench gate':
                    rep=json.loads((first/'artifacts/bootstrap-report.json').read_text());rep['gates'][1]['status']='FAIL'
                    (first/'artifacts/bootstrap-report.json').write_text(json.dumps(rep))
                if name=='parent identity in the report':over=dict(parent_identity='c'*64)
                self.assert_fails(child(parent,first,second,**over),'child-measured')
    def test_copied_parent_runs_fail(self):
        with tempfile.TemporaryDirectory() as t:
            parent,first,second=family(t);write_run(first,'2'*32,'a'*64)
            r=child(parent,first,second);self.assert_fails(r,'no-copied-parent-runs')
            self.assertIn('a child run carries the parent source identity',r['checks']['no-copied-parent-runs']['problems'])
        with tempfile.TemporaryDirectory() as t:
            parent,first,second=family(t);write_run(parent,'1'*32,'a'*64)
            self.assert_fails(child(parent,first,second),'no-copied-parent-runs')        # a parent run id inside the child
        with tempfile.TemporaryDirectory() as t:
            parent,first,second=family(t)
            self.assert_fails(child(parent,first,second,before_runs=[{'run_id':'3'*32,'source_identity':'b'*64}]),'no-copied-parent-runs')
            self.assert_fails(child(parent,first,second,before_runs=None),'no-copied-parent-runs')   # unknown is never PASS
    def test_a_grandchild_fails(self):
        with tempfile.TemporaryDirectory() as t:
            parent,first,second=family(t);g=first/'artifacts/instances/r/grandchild';g.mkdir(parents=True)
            (g/'starter-baseline.lock.json').write_text('{}')
            self.assert_fails(child(parent,first,second),'no-grandchildren')

class LocalRefusalTests(unittest.TestCase):
    def test_refused_under_ci(self):
        with mock.patch.dict(os.environ,{'CI':'true'}):
            with self.assertRaises(GateError):bp.refuse_local(ROOT,'local dataset')
    def test_refused_in_instances(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t)/'project.json').write_text('{}')
            with mock.patch.dict(os.environ,{},clear=False):
                os.environ.pop('CI',None)
                with self.assertRaises(GateError):bp.refuse_local(Path(t),'local dataset')
    def test_allowed_outside_ci_and_instances(self):
        with tempfile.TemporaryDirectory() as t,mock.patch.dict(os.environ,{},clear=False):
            os.environ.pop('CI',None);self.assertIsNone(bp.refuse_local(Path(t),'local dataset'))
    def test_messages(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t)/'project.json').write_text('{}')
            with mock.patch.dict(os.environ,{'CI':'1'}),self.assertRaisesRegex(GateError,'^local replays are refused under CI$'):bp.refuse_local(Path(t),'local replay')
            with mock.patch.dict(os.environ,{},clear=False):
                os.environ.pop('CI',None)
                with self.assertRaisesRegex(GateError,'^local replays are refused in project instances$'):bp.refuse_local(Path(t),'local replay')
    def test_the_local_path_rules_call_refuse_local(self):
        with mock.patch.object(bp,'refuse_local',side_effect=GateError('refused here')) as rl:
            with self.assertRaisesRegex(GateError,'refused here'):bp.resolve_local_dataset(ROOT,'/nonexistent/dataset.json')
        rl.assert_called_once_with(ROOT,'local dataset')
    def test_replay_of_a_local_plan_is_refused_under_ci(self):
        import bench_replay as br
        local={'plan_id':'p','mode':'smoke','dataset':{'kind':'local','size':None,'seed':None,'sha256':'a'*64,'rows':None},'project_dir':None}
        run={'run_id':'a'*32,'case':'bench-control-spin','mode':'smoke'}
        calls=[]
        def fake_run(root,args):calls.append(args.dataset);return 0
        with tempfile.TemporaryDirectory() as t:
            old=Path(t)/'old';old.mkdir()
            for ci,want in (('true',2),(None,1)):
                env={'CI':ci} if ci else {}
                with self.subTest(ci=ci),mock.patch.dict(os.environ,env,clear=False),mock.patch('bench._run_dir',return_value=old),\
                     mock.patch('bench.read_json',return_value=run),mock.patch('bench_replay._read_plan',return_value=local),\
                     mock.patch('bench_replay.authorization',return_value=[]),mock.patch('bench.run_cmd',side_effect=fake_run),\
                     mock.patch('bench_privacy.is_project_instance',return_value=False),contextlib.redirect_stdout(io.StringIO()) as out:
                    if not ci:os.environ.pop('CI',None)
                    rc=br.replay_cmd(ROOT,argparse.Namespace(run_id='a'*32,dataset='local:/x',format='json'))
                self.assertEqual(rc,want)
                if ci:
                    row=json.loads(out.getvalue().strip().splitlines()[-1])
                    self.assertEqual((row['status'],row['reasons']),('BLOCKED',['local replays are refused under CI']));self.assertEqual(calls,[])
                else:self.assertEqual(calls,['local:/x'])       # control: outside CI and instances bench run is called

class ExportTests(unittest.TestCase):
    def test_every_bench_file_is_exported(self):
        self.assertEqual(len(project_model._framework_sets(str(ROOT))[1]),0)
    def test_bench_runs_are_never_exported(self):
        files=json.loads((ROOT/'starter-export.json').read_text())['files']
        self.assertFalse(any(f.startswith('artifacts/') for f in files))

class SpacesTests(unittest.TestCase):
    def test_bench_paths_with_spaces(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t)/'first project with space'/'artifacts/bench'/('0'*32);d.mkdir(parents=True);(d/'plan.json').write_text('{}')
            run={'evidence_digests':be.digest_files(d)};self.assertEqual(be.verify(d,run),[])

if __name__=='__main__':unittest.main()
