"""Amendment E section 1 (rule S): a standalone example leaves the framework scope.

examples/<name> is a framework example only when starter-export.json lists examples/<name>/project.json. A standalone
example (project.json, not listed) is outside the framework inventory, the framework manifest, the B18 payload and every
framework bench suite; an explicit project scope (bench selftest --project DIR, dev readiness --project DIR) runs its
suites. ci/changed-examples selects the example.yml jobs and safety.yml ignores examples/**; the trigger tables below are
the dry run of that logic. Every root here is temporary and synthetic: the tests name no real example.

FIX1 (the T3 approver findings): the selection fails closed on GitHub for framework content under examples/ (T3-A01), for
a pull request at the 300-file path filter limit (T3-A03) and for a listed path inside a standalone tree (T3-A06); the
glob emulation follows GitHub's `?` rule (T3-A04); the commit id and name bounds (T3-A05); a bench selftest record names
its scope and source identity, and decide reads only a record of the run's scope (T3-A07); ci/README.md (T3-A08)."""
import argparse, ast, contextlib, importlib.machinery, importlib.util, io, json, os, re, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from evidence import GateError
import policy
import project_model as pm
import bench

FW='examples/fw-demo';SOLO='examples/solo-demo';SOLO2='examples/solo-two';LOOSE='examples/loose-notes'
IMAGES={'sdk':'sha256:'+'a'*64,'developer':'sha256:'+'b'*64,'archive_sha256':'c'*64}

def example(prefix,case):
    return {f'{prefix}/project.json':'{}\n',f'{prefix}/src/a.c':'int a;\n',f'{prefix}/tests/project/test_a.c':'int t;\n',
            f'{prefix}/benchmarks/project/bench.json':json.dumps({'cases':[case]})+'\n',f'{prefix}/README.md':'r\n'}

def write(root,files):
    for rel,text in files.items():
        p=Path(root)/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)

def fixture(root,standalone=(SOLO,),loose=False):
    """A temporary framework root: two tools files, the exported framework example FW, the standalone examples and, with
    `loose`, a directory under examples/ without project.json."""
    root=Path(root);framework={'tools/x.py':'x\n','tools/x.c':'int x;\n',**example(FW,'fw-case')}
    write(root,framework)
    for k,name in enumerate(standalone):write(root,example(name,f'solo-case-{k}'))
    if loose:write(root,{f'{LOOSE}/src/n.c':'int n;\n'})
    (root/'starter-export.json').write_text(json.dumps({'schema_version':1,'substitutions':[],'files':sorted([*framework,'starter-export.json'])}))
    return root

def set_export(root,add=(),remove=()):
    """Add rows to, or remove rows from, the export list of a temporary root."""
    p=Path(root)/'starter-export.json';doc=json.loads(p.read_text())
    doc['files']=sorted((set(doc['files'])|set(add))-set(remove));p.write_text(json.dumps(doc))

def load_selector():
    loader=importlib.machinery.SourceFileLoader('changed_examples',str(ROOT/'ci/changed-examples'))
    spec=importlib.util.spec_from_loader('changed_examples',loader);module=importlib.util.module_from_spec(spec)
    loader.exec_module(module);return module

class StandaloneExampleTests(unittest.TestCase):
    def test_rule_s_selects_the_unlisted_examples_with_project_json(self):
        with tempfile.TemporaryDirectory() as t:
            d=fixture(t,standalone=(SOLO2,SOLO),loose=True)
            self.assertEqual(pm.standalone_examples(d),[SOLO,SOLO2])
    def test_no_candidate_needs_no_export_list(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t);self.assertEqual(pm.standalone_examples(d),[])
            write(d,{f'{LOOSE}/src/n.c':'int n;\n'});self.assertEqual(pm.standalone_examples(d),[])
    def test_an_unreadable_export_list_fails_closed(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t);write(d,example(SOLO,'c'))
            with self.assertRaises(GateError):pm.standalone_examples(d)
            (d/'starter-export.json').write_text('{')
            with self.assertRaises(GateError):pm.standalone_examples(d)
    def test_symbolic_links_are_refused(self):
        for case in ('directory','project-json','examples'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as t:
                d=fixture(Path(t)/'r')
                if case=='directory':(d/'examples/linked').symlink_to(d/SOLO)
                elif case=='project-json':(d/SOLO2).mkdir(parents=True);(d/SOLO2/'project.json').symlink_to(d/SOLO/'project.json')
                else:real=Path(t)/'real';os.replace(d/'examples',real);(d/'examples').symlink_to(real)
                with self.assertRaises(GateError):pm.standalone_examples(d)
    def test_a_listed_path_inside_a_standalone_tree_is_refused(self):
        """FIX1 T3-A06: a standalone tree that still holds a path of the export list is a mixed state: the path would stay in
        the manifest and the export but leave the framework source inventory and the B18 payload. It is refused."""
        for rel in (f'{SOLO}/README.md',f'{SOLO}/src/a.c',f'{SOLO}/src/absent.c'):
            with self.subTest(rel=rel),tempfile.TemporaryDirectory() as t:
                d=fixture(t,standalone=(SOLO,SOLO2));set_export(d,add=[rel])
                with self.assertRaisesRegex(GateError,'lists a file of the standalone example '+SOLO):pm.standalone_examples(d)
                with self.assertRaises(GateError):policy.first_party_sources(d)
                set_export(d,remove=[rel]);self.assertEqual(pm.standalone_examples(d),[SOLO,SOLO2])
    def test_the_scopes_of_a_path_list(self):
        """FIX1 T3-A01: rule S over the tracked paths of one commit (ci/changed-examples reads base and head this way)."""
        paths=[f'{FW}/project.json',f'{FW}/src/a.c',f'{SOLO}/project.json',f'{SOLO}/src/a.c',f'{LOOSE}/src/n.c','examples/notes.md','tools/x.py']
        self.assertEqual(pm.example_scopes(paths,{f'{FW}/project.json',f'{LOOSE}/project.json'}),
                         {FW:'framework',SOLO:'standalone',LOOSE:'project-less'})
        self.assertEqual(pm.example_scopes([],set()),{})
        with tempfile.TemporaryDirectory() as t:              # the same rule as standalone_examples on a working tree
            d=fixture(t,standalone=(SOLO,SOLO2),loose=True)
            listed=json.loads((d/'starter-export.json').read_text())['files']
            files=[p.relative_to(d).as_posix() for p in d.rglob('*') if p.is_file()]
            self.assertEqual(sorted(k for k,v in pm.example_scopes(files,listed).items() if v=='standalone'),pm.standalone_examples(d))

class FrameworkInventoryTests(unittest.TestCase):
    def test_first_party_sources_skip_only_the_standalone_trees(self):
        with tempfile.TemporaryDirectory() as t:
            d=fixture(t,standalone=(SOLO,SOLO2),loose=True)
            self.assertEqual(policy.first_party_sources(d),{'tools/x.c',f'{FW}/src/a.c',f'{FW}/tests/project/test_a.c',f'{LOOSE}/src/n.c'})
    def test_the_source_inventory_gate_passes_without_the_standalone_files(self):
        with tempfile.TemporaryDirectory() as t:
            d=fixture(t,loose=True)
            declared={rel:{'sha256':policy.file_hash(d/rel)} for rel in ('tools/x.c',f'{FW}/src/a.c',f'{FW}/tests/project/test_a.c',f'{LOOSE}/src/n.c')}
            self.assertEqual(policy.source_inventory_gate(d,declared),set(declared))
            write(d,{f'{SOLO}/src/new.c':'int z;\n',f'{SOLO}/src/a.c':'int changed;\n'})      # a standalone edit needs no framework row
            self.assertEqual(policy.source_inventory_gate(d,declared),set(declared))
            for rel in (f'{FW}/src/new.c',f'{LOOSE}/src/m.c'):        # a framework example and a directory without project.json stay inventoried
                with self.subTest(rel=rel):
                    write(d,{rel:'int y;\n'})
                    with self.assertRaisesRegex(GateError,'inventory mismatch'):policy.source_inventory_gate(d,declared)
                    (d/rel).unlink()
            write(d,{f'{FW}/src/a.c':'int edited;\n'})
            with self.assertRaisesRegex(GateError,'fingerprint changed'):policy.source_inventory_gate(d,declared)
    def test_the_inventory_gate_runs_the_source_inventory_gate(self):
        declared=json.loads((ROOT/'safety/source-inventory.json').read_text())['files']
        with mock.patch.object(policy,'source_inventory_gate',side_effect=GateError('source part reached')) as gate:
            with self.assertRaisesRegex(GateError,'source part reached'):policy.inventory_gate(ROOT)
        self.assertEqual(gate.call_args.args,(ROOT,declared))

class ManifestScopeTests(unittest.TestCase):
    def report(self,d):return {'overall_state':'VALIDATED_UNSEALED','source_identity':policy.source_identity(d)[0],'run_id':'d'*32}
    def test_a_standalone_edit_keeps_the_framework_files_and_the_manifest(self):
        with tempfile.TemporaryDirectory() as t:
            d=fixture(t);value=pm.write_manifest(d,self.report(d),IMAGES,framework_root=ROOT)
            self.assertEqual([rel for rel in value['files'] if rel.startswith(SOLO+'/')],[])
            self.assertIn(f'{FW}/src/a.c',value['files'])
            before=pm.framework_files(d)
            write(d,{f'{SOLO}/src/a.c':'int changed;\n',f'{SOLO}/src/b.c':'int b;\n',f'{SOLO}/README.md':'edited\n'})
            self.assertEqual(pm.framework_files(d),before)
            self.assertEqual(pm.check_manifest(d,framework_root=ROOT),[])
    def test_an_edit_of_the_exported_example_is_reported(self):
        with tempfile.TemporaryDirectory() as t:
            d=fixture(t);pm.write_manifest(d,self.report(d),IMAGES,framework_root=ROOT)
            write(d,{f'{FW}/src/a.c':'int changed;\n'})
            self.assertEqual(pm.check_manifest(d,framework_root=ROOT),[f'changed: {FW}/src/a.c'])

class B18PayloadTests(unittest.TestCase):
    def test_the_payload_leaves_out_the_standalone_tree(self):
        import bench_b18
        with tempfile.TemporaryDirectory() as t:
            d=fixture(t);got=bench_b18.payload(d)
            self.assertIn(f'{FW}/benchmarks/project/bench.json',got);self.assertIn(f'{FW}/src/a.c',got)
            self.assertEqual([p for p in got if p.startswith(SOLO+'/')],[])
            self.assertEqual(bench_b18.check_payload(d),[])

class BenchScopeTests(unittest.TestCase):
    def test_the_framework_scope_and_the_explicit_project(self):
        with tempfile.TemporaryDirectory() as t:
            d=fixture(t,standalone=(SOLO,SOLO2))
            write(d,{'examples/legacy/benchmarks/project/bench.json':'{}\n'})      # no project.json: framework content (fail closed)
            self.assertEqual(bench.example_projects(d),[FW,'examples/legacy'])
            self.assertEqual(bench.example_projects(d,SOLO),[SOLO])
            self.assertEqual(bench.registered_projects(d),[FW,'examples/legacy'])
            self.assertEqual(bench.registered_projects(d,SOLO),[SOLO])
    def test_demo_cases_follow_the_scope(self):
        import bench_readiness as br
        with tempfile.TemporaryDirectory() as t:
            d=fixture(t)
            self.assertEqual(br.demo_cases(d),{(FW,'fw-case')})
            self.assertEqual(br.demo_cases(d,SOLO),{(SOLO,'solo-case-0')})
    def test_the_stub_native_b17_and_unit_smoke_targets_follow_the_scope(self):
        import bench_deadline as bd, bench_phase2 as b2, bench_phase3 as b3
        decl={'cases':['c'],'native':{}};case={'variants':[{'id':'c-serial','language':'c','status':'implemented'}]}
        with tempfile.TemporaryDirectory() as t,mock.patch.object(bd,'declared_project_stubs',lambda root,p:[(p,case,{'reason':'r'})]),\
             mock.patch.object(bench.bm,'project_bench',lambda root,p:decl),mock.patch.object(bench.bm,'load_case',lambda root,cid,p=None:case),\
             mock.patch.object(bench.bm,'unit_policy_names',lambda root,p:['u']):
            d=fixture(t)
            self.assertEqual([x[0] for x in bd.declared_stubs(d)],[FW])        # the default is the framework scope
            for scope,want in ((None,FW),(SOLO,SOLO)):
                with self.subTest(scope=scope):
                    self.assertEqual([x[0] for x in bd.declared_stubs(d,scope)],[want])
                    self.assertEqual([x[0] for x in b2.native_projects(d,scope)],[want])
                    self.assertEqual(b3.b17_targets(d,scope),[(None,b3.CONTROL_CASE),(want,'c')])
                    self.assertEqual(b3.unit_smoke_targets(d,scope),[(want,'u')])
    def test_the_sanitizer_evidence_step_of_the_ci_stays_framework_scope(self):
        import bench_phase2 as b2, project_check
        seen=[]
        with tempfile.TemporaryDirectory() as t,mock.patch.object(bench.bm,'project_bench',lambda root,p:{'cases':['c'],'native':{}}),\
             mock.patch.object(bench.bm,'load_case',lambda root,cid,p=None:{'variants':[{'language':'c','status':'implemented'}]}),\
             mock.patch.object(project_check,'run_sanitizer_evidence',lambda root,p,path:seen.append(p) or {'verdict':'PASS'}):
            self.assertEqual(b2.sanitizer_evidence_all(fixture(t)),{FW:'PASS'})
        self.assertEqual(seen,[FW])
    def run_selftest(self,suite,project):
        run_dir=Path(tempfile.mkdtemp());seen=[]
        class NoSession:
            def __init__(self,*a,**k):raise GateError('no launcher in the unit test')
        with mock.patch.object(bench,'new_run_dir',lambda root,kind:run_dir),mock.patch.object(bench,'BenchSession',NoSession),\
             mock.patch.object(bench,'project_arg',lambda root,args:args.project),\
             mock.patch.object(bench,'_privacy_suite',lambda root,rd:{'status':'PASS'}),\
             mock.patch.object(bench,'project_suites',lambda root,rd,scope=None:seen.append(('project',scope)) or {}),\
             mock.patch.object(bench,'selftest_cases',lambda root,rd,scope=None:seen.append(('cases',scope)) or ({},[])),\
             mock.patch.object(bench,'emit',lambda args,result,text:None):
            bench.selftest(ROOT,argparse.Namespace(suite=suite,project=project,format='json'))
        return seen
    def test_selftest_passes_only_an_explicit_project(self):
        for suite in ('cases','project'):
            for project in (None,SOLO):
                with self.subTest(suite=suite,project=project):self.assertEqual(self.run_selftest(suite,project),[(suite,project)])
    def test_the_ci_gates_run_the_framework_scope(self):
        seen=[]
        with tempfile.TemporaryDirectory() as t:
            d=fixture(t);(d/'artifacts').mkdir()
            with mock.patch.object(bench,'doctor_probe',lambda root,run_dir:{'status':'PASS','evidence_paths':[]}),\
                 mock.patch.object(bench,'selftest_cases',lambda root,run_dir,scope=None:seen.append(('cases',scope)) or ({},[])),\
                 mock.patch.object(bench,'_quiet',lambda fn,root,args:seen.append(('unit',args.project)) or (0,{'status':'PASS'})),\
                 mock.patch.object(bench.bm,'project_bench',lambda root,p:{'cases':[],'checks':[]}),\
                 mock.patch.object(bench,'_privacy_suite',lambda root,run_dir:{'status':'PASS','evidence_paths':[]}),\
                 mock.patch.object(bench,'project_image_suites',lambda root,run_dir:{}):
                gates,_=bench.ci_gates(d)
        gate=next(g for g in gates if g['name']=='bench-selftest')
        self.assertEqual(list(gate['details']['examples']),[FW])
        self.assertEqual(seen,[('unit',None),('cases',None),('unit',FW)])
    def test_selftest_cases_pass_the_scope_to_the_example_parts(self):
        import bench_deadline as bd, bench_phase2 as b2, bench_phase3 as b3, bench_units as bu
        seen=[];ctl={'cpu':{'checks':[]},'memory':{'status':'PASS'}}
        patches=((bench,'_doctor_job',lambda root,run_dir,mutation=None:('PASS',{},'doctor.json')),(bench,'run_controls',lambda root,run_dir:ctl),
                 (bench,'_smoke_or_decision',lambda root,case,mode:(1,None,None)),(bd,'selftest_suite',lambda root,run_dir:{'status':'PASS'}),
                 (bd,'stub_suites',lambda root,run_dir,project=None:seen.append(('stubs',project)) or ({},[])),
                 (bu,'coverage_suite',lambda root,run_dir,row:row),(bench,'b09_extension_checks',lambda root:{'status':'PASS'}),
                 (b3,'phase3_cases',lambda root,run_dir,smoke,project=None:seen.append(('phase3',project)) or ({},[],[])),
                 (b2,'phase2_cases',lambda root,run_dir,project=None:seen.append(('phase2',project)) or ({},[],[])),
                 (policy,'verify_bench_wheels',lambda root:None))
        with tempfile.TemporaryDirectory() as t,contextlib.ExitStack() as stack:
            for target,name,value in patches:stack.enter_context(mock.patch.object(target,name,value))
            for scope in (None,SOLO):
                with self.subTest(scope=scope):
                    seen.clear();bench.selftest_cases(ROOT,Path(t),scope)
                    self.assertEqual(seen,[('stubs',scope),('phase3',scope),('phase2',scope)])
    def test_phase3_cases_pass_the_scope(self):
        import bench_phase3 as b3
        seen=[]
        patches=(('b12_suite',lambda root,run_dir,smoke:{'status':'PASS'}),('b14_suite',lambda root:{'status':'PASS'}),
                 ('b15_suite',lambda root,run_dir,smoke,project=None:seen.append(('B15',project)) or {'status':'PASS'}),
                 ('b18_suite',lambda root:seen.append(('B18',)) or {'status':'PASS'}),
                 ('b17_suite',lambda root,run_dir,project=None:seen.append(('B17',project)) or ({'status':'PASS'},[])),
                 ('unit_smoke_suite',lambda root,run_dir,scope=None:seen.append(('unit-smoke',scope)) or ({'status':'PASS'},[])),
                 ('host_additions',lambda root,project=None:seen.append(('host',project)) or []),
                 ('rewritten_raw_samples',lambda root,smoke:{'parent':'P10','variant':'rewritten-raw-samples'}))
        with contextlib.ExitStack() as stack:
            for name,value in patches:stack.enter_context(mock.patch.object(b3,name,value))
            for scope in (None,SOLO):
                with self.subTest(scope=scope):
                    seen.clear();b3.phase3_cases(ROOT,Path('/nonexistent'),None,scope)
                    self.assertEqual(seen,[('B15',scope),('B18',),('B17',scope),('unit-smoke',scope),('host',scope)])
    def test_phase2_cases_pass_the_scope(self):
        import bench_phase2 as b2
        seen=[]
        with tempfile.TemporaryDirectory() as t,mock.patch.object(b2,'native_projects',lambda root,project=None:seen.append(('native',project)) or []),\
             mock.patch.object(b2,'b11_suite',lambda root,project=None:seen.append(('B11',project)) or {'status':'BLOCKED'}),\
             mock.patch.object(b2,'failure_job',side_effect=GateError('no launcher in the unit test')):
            for scope in (None,SOLO):
                with self.subTest(scope=scope):
                    seen.clear();b2.phase2_cases(ROOT,Path(t),scope)
                    self.assertEqual(seen,[('native',scope),('B11',scope)])
    def test_the_host_additions_pass_the_scope_to_the_scoped_check_only(self):
        import bench_phase3 as b3
        seen=[]
        checks={key:((lambda root,t,project=None,key=key:seen.append((key,project)) or (True,True)),'r') for key in b3.HOST_CHECKS}
        with mock.patch.dict(b3.HOST_CHECKS,checks),mock.patch.object(b3,'_integrity_variant',lambda *a:(True,True)):
            rows=b3.host_additions(ROOT,SOLO)
        self.assertEqual(len(rows),len(b3.HOST_VARIANTS))
        self.assertEqual({key for key,project in seen if project==SOLO},{('P15','removed-safety-check')})
    def test_the_removed_safety_check_reads_the_scope(self):
        import bench_phase3 as b3
        seen=[]
        with tempfile.TemporaryDirectory() as t,mock.patch.object(bench,'example_projects',lambda root,project=None:seen.append(project) or []):
            b3._removed_safety_check(ROOT,Path(t),SOLO)
        self.assertEqual(seen,[SOLO])

def calls(module,function,callee):
    """The calls of `callee` (a name or an attribute) inside the function `function` of tools/<module>.py."""
    tree=ast.parse((ROOT/'tools'/f'{module}.py').read_text())
    fn=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name==function)
    return [c for c in ast.walk(fn) if isinstance(c,ast.Call) and callee in (getattr(c.func,'attr',None),getattr(c.func,'id',None))]

# Amendment E 1.2 item 3: (module, function, callee, name of the scope it passes). Together with the behavior tests above
# this is the scope of every call site: each scoped call passes its caller's scope on.
SCOPED=(('bench','selftest','selftest_cases','scope'),('bench','selftest','project_suites','scope'),
        ('bench','project_suites','registered_projects','scope'),('bench','selftest_cases','stub_suites','project'),
        ('bench','selftest_cases','phase3_cases','project'),('bench','selftest_cases','phase2_cases','project'),
        ('bench_deadline','declared_stubs','example_projects','project'),('bench_deadline','stub_suites','declared_stubs','project'),
        ('bench_deadline','first_stub_selftests','declared_stubs','project'),('bench_phase2','native_projects','example_projects','project'),
        ('bench_phase2','b11_suite','native_projects','project'),('bench_phase2','phase2_cases','native_projects','project'),
        ('bench_phase2','phase2_cases','b11_suite','project'),('bench_phase3','_removed_safety_check','example_projects','project'),
        ('bench_phase3','b15_suite','first_stub_selftests','project'),('bench_phase3','b17_targets','native_projects','project'),
        ('bench_phase3','b17_suite','b17_targets','project'),('bench_phase3','unit_smoke_targets','example_projects','project'),
        ('bench_phase3','unit_smoke_suite','unit_smoke_targets','scope'),('bench_phase3','phase3_cases','b15_suite','project'),
        ('bench_phase3','phase3_cases','b17_suite','project'),('bench_phase3','phase3_cases','unit_smoke_suite','project'),
        ('bench_phase3','phase3_cases','host_additions','project'),('bench_readiness','demo_cases','example_projects','project'),
        ('bench_readiness','demo_run','demo_cases','project'),('bench_readiness','_smoke_evidence','demo_cases','project'),
        ('bench_readiness','performance_axes','demo_run','project'),('bench_readiness','performance_axes','_smoke_evidence','project'),
        ('developer_acceptance','readiness','performance_axes','project'))
# The framework-only call sites: they pass no scope, so a standalone example never runs there (the ci and B18).
FRAMEWORK_ONLY=(('bench','ci_gates','selftest_cases',2),('bench','ci_gates','project_suites',2),('bench_b18','payload','example_projects',1),
                ('bench_phase2','sanitizer_evidence_all','native_projects',1))

class CallSiteTests(unittest.TestCase):
    def test_each_scoped_call_passes_the_scope_on(self):
        for module,function,callee,name in SCOPED:
            with self.subTest(site=f'{module}.{function} -> {callee}'):
                found=calls(module,function,callee);self.assertTrue(found)
                for c in found:
                    self.assertIn(name,[a.id for a in [*c.args,*(k.value for k in c.keywords)] if isinstance(a,ast.Name)])
    def test_the_framework_only_calls_pass_no_scope(self):
        for module,function,callee,count in FRAMEWORK_ONLY:
            with self.subTest(site=f'{module}.{function} -> {callee}'):
                found=calls(module,function,callee);self.assertTrue(found)
                for c in found:self.assertEqual((len(c.args),c.keywords),(count,[]))

class ReadinessScopeTests(unittest.TestCase):
    def test_dev_readiness_takes_a_project(self):
        import developer
        p=argparse.ArgumentParser();developer.configure_parser(p)
        dev=json.loads((ROOT/'safety/developer-policy.json').read_text())
        self.assertEqual(developer.request(p.parse_args(['readiness','--project',SOLO]),dev)['project'],SOLO)
        self.assertNotIn('project',developer.request(p.parse_args(['readiness']),dev))
        for bad in ('/abs/dir','../up','a/../b','x\nline',''):
            with self.subTest(bad=bad),self.assertRaises(GateError):developer.request(p.parse_args(['readiness','--project',bad]),dev)
        with self.assertRaises(SystemExit),contextlib.redirect_stderr(io.StringIO()):p.parse_args(['status','--project',SOLO])
    def test_readiness_validates_and_passes_the_project_to_the_demo_axes(self):
        import developer_acceptance as da, bench_readiness as br
        seen=[]
        with mock.patch.object(br,'performance_axes',lambda root,identity,axes,project=None:seen.append(project) or {}),\
             mock.patch.object(br,'performance_details',lambda root,identity:{}),\
             mock.patch.object(bench.bm,'project_bench',lambda root,p:seen.append(('validated',p)) or {}),\
             mock.patch.object(da,'source_identity',return_value=('i',{})):
            da.readiness(ROOT,'context',{'worktree':'w'},{'project':SOLO},'i')
            self.assertEqual(seen,[('validated',SOLO),SOLO])
            seen.clear();da.readiness(ROOT,'context',{'worktree':'w'},{},'i')
            self.assertEqual(seen,[None])

class SelectionTests(unittest.TestCase):
    """ci/changed-examples: the selection table of amendment E 1.6 (one exported and one standalone example). Rule of 1.4:
    `examples` holds the changed standalone examples, or every standalone example when `framework` is true."""
    def test_the_selection_table(self):
        sel=load_selector()
        with tempfile.TemporaryDirectory() as t:
            examples=pm.standalone_examples(fixture(t))
        self.assertEqual(examples,[SOLO])
        for name,changed,framework,selected in (('only the standalone example',[f'{SOLO}/src/a.c',f'{SOLO}/README.md'],False,[SOLO]),
                                                ('the standalone example and tools/x',[f'{SOLO}/src/a.c','tools/x.py'],True,[SOLO]),
                                                ('the framework example only',[f'{FW}/src/a.c'],True,[SOLO]),
                                                ('absent base',None,True,[SOLO])):
            with self.subTest(name):self.assertEqual(sel.select(examples,changed),(framework,selected))
    def test_two_standalone_examples(self):
        sel=load_selector();examples=[SOLO,SOLO2]
        self.assertEqual(sel.select(examples,[f'{SOLO}/src/a.c']),(False,[SOLO]))
        self.assertEqual(sel.select(examples,[f'{SOLO2}/x',f'{SOLO}/y']),(False,[SOLO,SOLO2]))
        self.assertEqual(sel.select(examples,['tools/x.py']),(True,[SOLO,SOLO2]))
        self.assertEqual(sel.select(examples,[f'{SOLO}-extra/a.c']),(True,[SOLO,SOLO2]))       # a name prefix is no tree
        self.assertEqual(sel.select(examples,[f'{LOOSE}/n.c']),(True,[SOLO,SOLO2]))             # no project.json: framework
        self.assertEqual(sel.select(examples,[]),(False,[]))
    def git(self,repo,*argv):
        env={'PATH':os.environ.get('PATH','/usr/bin:/bin'),'HOME':str(repo.parent),'GIT_CONFIG_NOSYSTEM':'1','GIT_AUTHOR_NAME':'t',
             'GIT_AUTHOR_EMAIL':'t','GIT_COMMITTER_NAME':'t','GIT_COMMITTER_EMAIL':'t'}
        # T6 (ledger row T6-ZOMBIE-01): git 2.47 detaches its auto-maintenance after a commit; in a holder container (PID 1
        # never reaps) each detached process stays a zombie that holds a pids slot, so these repositories turn it off.
        return subprocess.run(['git','-c','maintenance.auto=false','-c','gc.auto=0','-C',str(repo),*argv],env=env,check=True,
                              capture_output=True,text=True).stdout.strip()
    def run_main(self,sel,repo,*argv):
        out=io.StringIO()
        with contextlib.redirect_stdout(out),contextlib.redirect_stderr(io.StringIO()):
            try:rc=sel.main(list(argv),root=repo)
            except SystemExit as exc:rc=exc.code          # an argparse refusal
        return rc,dict(line.split('=',1) for line in out.getvalue().splitlines())
    def test_the_script_on_a_temporary_repository(self):
        sel=load_selector();one=json.dumps([SOLO],separators=(',',':'))
        with tempfile.TemporaryDirectory() as t:
            repo=fixture(Path(t)/'repo')
            self.git(repo,'init','-q');self.git(repo,'add','-A');self.git(repo,'commit','-q','-m','base');base=self.git(repo,'rev-parse','HEAD')
            write(repo,{f'{SOLO}/src/a.c':'int changed;\n'});self.git(repo,'commit','-q','-am','standalone');solo=self.git(repo,'rev-parse','HEAD')
            write(repo,{'tools/x.py':'y\n'});self.git(repo,'commit','-q','-am','tools');tools=self.git(repo,'rev-parse','HEAD')
            self.git(repo,'mv',f'{SOLO}/README.md','tools/moved.md');self.git(repo,'commit','-q','-m','rename');moved=self.git(repo,'rev-parse','HEAD')
            for name,base_arg,head,want in (('standalone only',base,solo,(0,{'framework':'false','examples':one})),
                                            ('tools change',solo,tools,(0,{'framework':'true','examples':one})),
                                            ('a rename out of the tree',tools,moved,(0,{'framework':'true','examples':one})),
                                            ('no change',solo,solo,(0,{'framework':'false','examples':'[]'})),
                                            ('all-zero base','0'*40,solo,(0,{'framework':'true','examples':one})),
                                            ('absent base','',solo,(0,{'framework':'true','examples':one})),
                                            ('unknown base','e'*40,solo,(0,{'framework':'true','examples':one}))):
                with self.subTest(name):self.assertEqual(self.run_main(sel,repo,'--base',base_arg,'--head',head),want)
            for argv in (('--base','HEAD','--head',solo),('--base',base,'--head','HEAD'),('--base',base[:12],'--head',solo),('--base=--output=x','--head',solo),('--base','--output=x','--head',solo)):
                with self.subTest(argv=argv):self.assertEqual(self.run_main(sel,repo,*argv)[0],2)
            (repo/'examples/linked').symlink_to(repo/SOLO)
            self.assertEqual(self.run_main(sel,repo,'--base',base,'--head',solo)[0],2)

def run_script(repo,argv):
    """(exit code, outputs, stderr text) of ci/changed-examples main() on `repo` (an argparse refusal gives its exit code)."""
    out,err=io.StringIO(),io.StringIO()
    with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
        try:rc=load_selector().main(list(argv),root=repo)
        except SystemExit as exc:rc=exc.code
    return rc,dict(line.split('=',1) for line in out.getvalue().splitlines() if '=' in line),err.getvalue()

def git_in(repo,*argv):
    """A git command in a temporary repository (SelectionTests.git without a test instance)."""
    return SelectionTests.git(None,repo,*argv)

def commit_pair(change,before=None,base_arg=None,extra=()):
    """(exit code, outputs, stderr) of ci/changed-examples for the commit pair base -> head of a temporary repository: the
    fixture (with `before`) is the base, `change` makes the head, and the working tree stays at the head."""
    with tempfile.TemporaryDirectory() as t:
        repo=fixture(Path(t)/'repo')
        if before:before(repo)
        git_in(repo,'init','-q');git_in(repo,'add','-A');git_in(repo,'commit','-q','-m','base');base=git_in(repo,'rev-parse','HEAD')
        change(repo);git_in(repo,'add','-A');git_in(repo,'commit','-q','--allow-empty','-m','head');head=git_in(repo,'rev-parse','HEAD')
        return run_script(repo,['--base',base if base_arg is None else base_arg,'--head',head,*extra])

class ScopeRuleTests(unittest.TestCase):
    """FIX1 T3-A01: a pull request that changes only examples/ skips safety.yml, so ci/changed-examples itself fails closed
    (exit 1) for framework content under examples/: at the head, starter-export.json lists every file of a framework
    example tree and of an examples/<name> without project.json (no project-less file and no unlisted file), and no missing
    example file and no file of a standalone tree; an examples/<name> keeps its scope between base and head unless the
    change also changes starter-export.json (that change runs safety.yml). The allowed forms keep the selection of 1.4."""
    git=SelectionTests.git
    pair=staticmethod(commit_pair)
    def test_an_unlisted_file_in_a_framework_example_tree_is_refused(self):          # (a)
        for rel in (f'{FW}/src/new.c',f'{FW}/docs/notes.md',f'{FW}/benchmarks/project/cases/new.json'):
            for base_arg in (None,'','0'*40):                                       # the head rule needs no base
                with self.subTest(rel=rel,base=base_arg):
                    rc,out,err=self.pair(lambda r:write(r,{rel:'int n;\n'}),base_arg=base_arg)
                    self.assertEqual((rc,out),(1,{}));self.assertIn('unlisted file under examples/: '+rel,err)
    def test_a_file_of_a_project_less_directory_is_refused(self):                   # (b)
        for rel in (f'{LOOSE}/src/n.c',f'{LOOSE}/README.md','examples/notes.md'):
            with self.subTest(rel=rel):
                rc,out,err=self.pair(lambda r:write(r,{rel:'int n;\n'}))
                self.assertEqual((rc,out),(1,{}));self.assertIn('unlisted file under examples/: '+rel,err)
    def test_a_scope_change_without_an_export_change_is_refused(self):              # (c)
        # project-less -> standalone: a base whose project-less tree holds an unlisted file (a base that broke the head rule)
        rc,out,err=self.pair(lambda r:write(r,{f'{LOOSE}/project.json':'{}\n'}),before=lambda r:write(r,{f'{LOOSE}/src/n.c':'int n;\n'}))
        self.assertEqual((rc,out),(1,{}));self.assertIn(f'{LOOSE} changes its scope from project-less to standalone',err)
        # standalone -> project-less: project.json removed from a standalone example
        rc,out,err=self.pair(lambda r:(r/SOLO/'project.json').unlink())
        self.assertEqual((rc,out),(1,{}));self.assertIn(f'{SOLO} changes its scope from standalone to project-less',err)
        self.assertIn(f'unlisted file under examples/: {SOLO}/src/a.c',err)
        # framework -> project-less: the listed project.json of a framework example removed, its row kept
        rc,out,err=self.pair(lambda r:(r/FW/'project.json').unlink())
        self.assertEqual((rc,out),(1,{}));self.assertIn(f'{FW} changes its scope from framework to project-less',err)
        self.assertIn(f'starter-export.json lists a missing file: {FW}/project.json',err)
        # project-less -> standalone while its listed files keep their rows: the mixed state of T3-A06 (exit 2)
        rc,out,err=self.pair(lambda r:write(r,{f'{LOOSE}/project.json':'{}\n'}),
                             before=lambda r:(write(r,{f'{LOOSE}/src/n.c':'int n;\n'}),set_export(r,add=[f'{LOOSE}/src/n.c'])))
        self.assertEqual((rc,out),(2,{}));self.assertIn('lists a file of the standalone example '+LOOSE,err)
    def test_the_allowed_forms(self):
        new=f'{FW}/src/new.c'
        def leave(r):set_export(r,remove=[p for p in json.loads((r/'starter-export.json').read_text())['files'] if p.startswith(FW+'/')])
        both=json.dumps([FW,SOLO],separators=(',',':'));one=json.dumps([SOLO],separators=(',',':'))
        for name,change,before,want in (
                ('a listed new framework example file',lambda r:(write(r,{new:'int n;\n'}),set_export(r,add=[new])),None,('true',one)),
                ('a listed project-less file',lambda r:(write(r,{f'{LOOSE}/src/n.c':'int n;\n'}),set_export(r,add=[f'{LOOSE}/src/n.c'])),None,('true',one)),
                ('an edit of a listed file (the manifest check of the project job sees it)',lambda r:write(r,{f'{FW}/src/a.c':'int changed;\n'}),None,('true',one)),
                ('a removed listed file with its row',lambda r:((r/FW/'README.md').unlink(),set_export(r,remove=[f'{FW}/README.md'])),None,('true',one)),
                ('a standalone edit',lambda r:write(r,{f'{SOLO}/src/b.c':'int b;\n'}),None,('false',one)),
                ('a new standalone example',lambda r:write(r,example(SOLO2,'solo-case-new')),None,('false',json.dumps([SOLO2],separators=(',',':')))),
                ('a removed standalone example',lambda r:shutil.rmtree(r/SOLO),None,('true','[]')),
                ('a framework example that leaves the framework with all its rows',leave,None,('true',both)),
                ('a project-less tree that becomes a framework example',
                 lambda r:(write(r,{f'{LOOSE}/project.json':'{}\n'}),set_export(r,add=[f'{LOOSE}/project.json'])),
                 lambda r:(write(r,{f'{LOOSE}/src/n.c':'int n;\n'}),set_export(r,add=[f'{LOOSE}/src/n.c'])),('true',one))):
            with self.subTest(name):
                rc,out,err=self.pair(change,before=before)
                self.assertEqual((rc,out.get('framework'),out.get('examples')),(0,*want),err)
    def test_a_checkout_that_differs_from_the_head_is_refused(self):
        """The script reads the standalone examples from the checkout and the rules from the --head commit; both must agree."""
        with tempfile.TemporaryDirectory() as t:
            repo=fixture(Path(t)/'repo')
            self.git(repo,'init','-q');self.git(repo,'add','-A');self.git(repo,'commit','-q','-m','base');head=self.git(repo,'rev-parse','HEAD')
            write(repo,example(SOLO2,'solo-case-new'))                                # not committed
            rc,out,err=run_script(repo,['--base','','--head',head])
            self.assertEqual((rc,out),(2,{}));self.assertIn('the checkout and --head disagree',err)
    def test_an_unreadable_head_is_refused(self):
        with tempfile.TemporaryDirectory() as t:
            repo=fixture(Path(t)/'repo');self.git(repo,'init','-q')                  # no commit: git cannot read the head
            rc,out,err=run_script(repo,['--base','','--head','e'*40])
            self.assertEqual((rc,out),(2,{}))

class PathFilterLimitTests(unittest.TestCase):
    """FIX1 T3-A03: GitHub evaluates the path filters of a pull request workflow over at most 300 changed files, so
    safety.yml could skip a pull request whose framework path is not among them. ci/changed-examples refuses (exit 1) a
    pull request with a framework change and 300 or more changed paths (or an unknown count). A push (safety.yml has no
    push trigger) and a change of standalone examples only are not affected."""
    def test_the_rule(self):
        sel=load_selector();paths=lambda n:[f'tools/f{k}.py' for k in range(n)]
        self.assertEqual(sel.PATH_FILTER_LIMIT,300)
        self.assertIsNone(sel.path_filter_problem('pull_request',paths(299),True))
        for changed in (paths(300),paths(301),None):
            with self.subTest(count=None if changed is None else len(changed)):
                self.assertIn('300',sel.path_filter_problem('pull_request',changed,True))
        for event,changed,framework in (('push',paths(300),True),('push',None,True),('pull_request',paths(300),False),('pull_request',paths(0),False)):
            with self.subTest(event=event,framework=framework):self.assertIsNone(sel.path_filter_problem(event,changed,framework))
    def test_the_script_applies_the_rule(self):
        many=lambda prefix,n:(lambda r:write(r,{f'{prefix}/f{k}.txt':'x\n' for k in range(n)}))
        for name,change,event,want in (('299 framework paths',many('tools/gen',299),'pull_request',0),
                                       ('300 framework paths',many('tools/gen',300),'pull_request',1),
                                       ('300 framework paths on a push',many('tools/gen',300),'push',0),
                                       ('300 standalone paths',many(SOLO+'/gen',300),'pull_request',0)):
            with self.subTest(name):
                rc,out,err=commit_pair(change,extra=('--event',event))
                self.assertEqual(rc,want,err)
                if want:self.assertIn('300',err)
        self.assertEqual(commit_pair(lambda r:None,extra=('--event','schedule'))[0],2)       # only push and pull_request
        self.assertEqual(commit_pair(many('tools/gen',300))[0],0)                            # without --event: a push (the workflow passes it)

class SelectionBoundTests(unittest.TestCase):
    """FIX1 T3-A05: exact bounds and one-past values of the commit id and example name rules of ci/changed-examples."""
    def test_the_commit_id_rule(self):
        sel=load_selector()
        for value,ok in (('a'*40,True),('a'*39,False),('a'*41,False),('a'*64,True),('a'*63,False),('a'*65,False),
                         ('A'*40,False),('A'*64,False),('g'*40,False),('',False)):
            with self.subTest(length=len(value),value=value[:2]):self.assertEqual(bool(sel.COMMIT.fullmatch(value)),ok)
    def test_the_example_name_rule(self):
        sel=load_selector()
        for name,ok in (('a',True),('a'*64,True),('a'*65,False),('.hidden',False),('-a',False),('_a',False),('a.b_c-D9',True),
                        ('démo',False),('a b',False),('',False)):
            with self.subTest(name=name[:8],length=len(name)):self.assertEqual(bool(sel.EXAMPLE.fullmatch('examples/'+name)),ok)
    def test_the_script_refuses_a_bad_id(self):
        with tempfile.TemporaryDirectory() as t:
            repo=fixture(Path(t)/'repo');git=lambda *a:SelectionTests.git(None,repo,*a)
            git('init','-q');git('add','-A');git('commit','-q','-m','base');head=git('rev-parse','HEAD')
            self.assertEqual(run_script(repo,['--base','','--head',head])[0],0)
            upper=head.upper() if head.upper()!=head else 'A'*40
            for argv in (('--base','','--head',head+'0'),('--base','','--head',upper),('--base','','--head',head[:39]),
                         ('--base',head+'0','--head',head),('--base',upper,'--head',head),('--base','a'*65,'--head',head)):
                with self.subTest(argv=argv):self.assertEqual(run_script(repo,argv)[0],2)
    def test_the_script_refuses_a_bad_name_and_takes_a_name_at_the_bound(self):
        for name,want in (('a'*64,0),('a'*65,2),('.hidden',2),('démo',2)):
            with self.subTest(length=len(name),name=name[:8]),tempfile.TemporaryDirectory() as t:
                repo=fixture(Path(t)/'repo',standalone=(SOLO,'examples/'+name));git=lambda *a:SelectionTests.git(None,repo,*a)
                git('init','-q');git('add','-A');git('commit','-q','-m','base');head=git('rev-parse','HEAD')
                rc,out,err=run_script(repo,['--base','','--head',head])
                self.assertEqual(rc,want,err)
                if want:self.assertIn('example directory name refused',err)
                else:self.assertEqual(json.loads(out['examples']),sorted([SOLO,'examples/'+name]))

class SelftestRecordScopeTests(unittest.TestCase):
    """FIX1 T3-A07: a bench selftest record names its scope (None: the framework scope; else the --project directory) and
    the source identity of the tree it checked (None when the tree changed during the run). bench decide reads the newest
    record of the run's own scope (plan.project_dir) and only when it names the run's source identity."""
    def run_selftest(self,project,identities):
        ids=iter(identities)
        with tempfile.TemporaryDirectory() as t:
            run_dir=Path(t)
            with mock.patch.object(bench,'new_run_dir',lambda root,kind:run_dir),mock.patch.object(bench,'project_arg',lambda root,args:args.project),\
                 mock.patch.object(bench,'_selftest_identity',lambda root:next(ids)),\
                 mock.patch.object(bench,'selftest_cases',lambda root,rd,scope=None:({'B04':{'status':'PASS'},'B11':{'status':'PASS'}},[{'status':'PASS'}])),\
                 mock.patch.object(bench,'emit',lambda args,result,text:None):
                bench.selftest(ROOT,argparse.Namespace(suite='cases',project=project,format='json'))
            return json.loads((run_dir/'selftest.json').read_text())
    def test_the_record_names_its_scope_and_source_identity(self):
        for project in (None,SOLO):
            with self.subTest(project=project):
                doc=self.run_selftest(project,['a'*64,'a'*64])
                self.assertEqual((doc['status'],doc['scope'],doc['source_identity']),('PASS',project,'a'*64))
        self.assertIsNone(self.run_selftest(None,['a'*64,'b'*64])['source_identity'])       # the tree changed during the run
        self.assertIsNone(self.run_selftest(None,[None,None])['source_identity'])           # no identity could be computed
    def test_decide_reads_the_newest_record_of_the_run_scope(self):
        import bench_decide
        names=('B04','B11')
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            def record(run_id,scope,mtime,identity='a'*64,status='PASS',scoped=True):
                d=root/'artifacts/bench'/run_id;d.mkdir(parents=True)
                doc={'status':status,'source_identity':identity,'suites':{n:{'status':status} for n in names}}
                if scoped:doc['scope']=scope
                p=d/'selftest.json';p.write_text(json.dumps(doc));os.utime(p,(mtime,mtime))
            status=lambda project,identity='a'*64:bench_decide._suite_status(root,{'source_identity':identity,'plan':{'project_dir':project}},names)
            self.assertIsNone(status(None))                                       # no record
            record('1'*32,None,1000)
            self.assertTrue(status(None));self.assertIsNone(status(SOLO))         # a framework-scope record is no evidence for SOLO
            self.assertIsNone(status(None,'b'*64))                                # another tree
            record('2'*32,SOLO,2000,status='FAIL')
            self.assertTrue(status(None));self.assertIsNone(status(SOLO))         # the newest record of each scope decides
            record('3'*32,SOLO,3000)
            self.assertTrue(status(SOLO))
            record('4'*32,None,4000,status='FAIL',scoped=False)                   # a record without a scope is no record of any scope
            self.assertTrue(status(None))
            record('5'*32,None,5000,status='FAIL')
            self.assertIsNone(status(None));self.assertTrue(status(SOLO))

class WorkflowDocTests(unittest.TestCase):
    """FIX1 T3-A08: ci/README.md describes the jobs of example.yml and the ci/project-ci.yml template as they are."""
    def test_the_template_is_the_project_job_of_example_yml(self):
        e=jobs((ROOT/'.github/workflows/example.yml').read_text());p=jobs((ROOT/'ci/project-ci.yml').read_text())
        self.assertEqual(list(p),['project'])
        gate=('    needs: select',"    if: needs.select.outputs.framework == 'true'")
        ej=[line.replace(' --project examples/hello-world','') for line in e['project'].rstrip('\n').split('\n') if line not in gate]
        self.assertEqual(ej,p['project'].rstrip('\n').split('\n'))
    def test_the_readme_names_the_jobs_and_the_template_as_they_are(self):
        text=' '.join((ROOT/'ci/README.md').read_text().split())
        for phrase in ('It has one job, `project`, and no `select` or `examples` job.',
                       '`python3 ci/changed-examples --base B --head H --event E`',
                       '`starter-export.json` must list every file under a framework example tree and under an `examples/<name>` without `project.json`.',
                       'without a change of `starter-export.json`',
                       '300 or more changed paths'):
            with self.subTest(phrase=phrase[:40]):self.assertIn(phrase,text)
        for phrase in ('It is the same as `example.yml`','start `safety.yml` by hand for a larger pull request'):
            with self.subTest(absent=phrase[:40]):self.assertNotIn(phrase,text)

def paths_ignore(text):
    """The paths-ignore patterns of the pull_request trigger of a workflow text (the quoted items after `paths-ignore:`)."""
    lines=text.split('\n');out=[]
    for line in lines[lines.index('    paths-ignore:')+1:]:
        m=re.fullmatch(r"      - '([^']+)'",line)
        if not m:break
        out.append(m.group(1))
    return out

def glob(pattern):
    """GitHub's path filter glob for the characters the workflow may use: ** any characters, * no slash, and (FIX1 T3-A04,
    GitHub's filter pattern cheat sheet) ? zero or one of the preceding character. A ? without a preceding literal
    character is refused (ValueError)."""
    atoms=[];i=0                                   # (regular expression, a literal character)
    while i<len(pattern):
        if pattern.startswith('**',i):atoms.append(('.*',False));i+=2
        elif pattern[i]=='*':atoms.append(('[^/]*',False));i+=1
        elif pattern[i]=='?':
            if not atoms or not atoms[-1][1]:raise ValueError(f'? without a preceding character: {pattern}')
            atoms[-1]=(f'(?:{atoms[-1][0]})?',False);i+=1
        else:atoms.append((re.escape(pattern[i]),True));i+=1
    return re.compile(''.join(a for a,_ in atoms))

def safety_runs(patterns,changed):
    """GitHub skips a paths-ignore workflow only when every changed path matches an ignore pattern."""
    return not all(any(glob(p).fullmatch(path) for p in patterns) for path in changed)

def jobs(text):
    """{job name: its text} of a workflow text (the two-space keys under `jobs:`)."""
    out={};name=None
    for line in text.split('\njobs:\n',1)[1].split('\n'):
        m=re.fullmatch(r'  ([A-Za-z0-9_-]+):',line)
        if m:name=m.group(1);out[name]=[]
        elif name:out[name].append(line)
    return {k:'\n'.join(v) for k,v in out.items()}

class TriggerDryRunTests(unittest.TestCase):
    """GOAL item 5: the dry run of the trigger logic for the change tables of amendment E 1.6: safety.yml (text read, glob
    match) and the example.yml selection."""
    def test_safety_yml_ignores_every_examples_path_and_has_no_push_trigger(self):
        text=(ROOT/'.github/workflows/safety.yml').read_text();patterns=paths_ignore(text)
        self.assertIn('examples/**',patterns);self.assertNotIn('examples/**/README.md',patterns)
        self.assertEqual([p for p in patterns if p.startswith('!') or any(c in p for c in '[]+')],[])      # inside the emulated glob subset
        trigger=text.split('\npermissions:',1)[0]+'\n'
        self.assertIn('\n  pull_request:\n',trigger);self.assertIn('\n  workflow_dispatch:\n',trigger);self.assertNotIn('\n  push:',trigger)
    def test_the_glob_emulation(self):
        self.assertTrue(glob('examples/**').fullmatch('examples/a/b/c.c'));self.assertTrue(glob('src/**').fullmatch('src/a.c'))
        self.assertFalse(glob('src/**').fullmatch('srcx/a.c'));self.assertFalse(glob('project.json').fullmatch('examples/x/project.json'))
        self.assertFalse(glob('a/*').fullmatch('a/b/c'));self.assertTrue(glob('a/*').fullmatch('a/b'))
    def test_the_question_mark_follows_github(self):
        """FIX1 T3-A04: GitHub's filter pattern cheat sheet defines `?` as zero or one of the preceding character (not one
        character as in a shell glob). A `?` without a preceding literal character is refused."""
        self.assertTrue(glob('a/?.c').fullmatch('a.c'));self.assertTrue(glob('a/?.c').fullmatch('a/.c'))
        self.assertFalse(glob('a/?.c').fullmatch('a/b.c'))
        for path,ok in (('ac',True),('abc',True),('abbc',False),('axc',False)):
            with self.subTest(path=path):self.assertEqual(bool(glob('ab?c').fullmatch(path)),ok)
        self.assertTrue(glob('docs/**/x?').fullmatch('docs/a/b/'));self.assertTrue(glob('docs/**/x?').fullmatch('docs/a/x'))
        for bad in ('?a','a/*?','a/**?','a??'):
            with self.subTest(bad=bad),self.assertRaises(ValueError):glob(bad)
    def test_the_dry_run_table(self):
        sel=load_selector();patterns=paths_ignore((ROOT/'.github/workflows/safety.yml').read_text())
        with tempfile.TemporaryDirectory() as t:
            examples=pm.standalone_examples(fixture(t))
        # (name, changed paths, safety.yml runs on the pull request, framework, examples)
        for name,changed,full,framework,selected in (('only the standalone example',[f'{SOLO}/src/a.c',f'{SOLO}/README.md'],False,False,[SOLO]),
                                                     ('the standalone example and tools/x',[f'{SOLO}/src/a.c','tools/x.py'],True,True,[SOLO]),
                                                     ('the framework example only',[f'{FW}/src/a.c'],False,True,[SOLO]),
                                                     ('a root project path only',['src/app.c'],False,True,[SOLO])):
            with self.subTest(name):
                self.assertEqual(safety_runs(patterns,changed),full)
                self.assertEqual(sel.select(examples,changed),(framework,selected))
        self.assertEqual(sel.select(examples,None),(True,[SOLO]))        # absent base (a push of a new branch): safety.yml has no push trigger
    def test_the_example_workflow_jobs(self):
        text=(ROOT/'.github/workflows/example.yml').read_text();j=jobs(text)
        self.assertEqual(list(j),['select','project','examples'])
        trigger=text.split('\npermissions:',1)[0]+'\n';self.assertIn('\n  push:\n',trigger);self.assertIn('\n  pull_request:\n',trigger)
        s=j['select']
        for line in ('timeout-minutes: 5','fetch-depth: 0','framework: ${{ steps.select.outputs.framework }}','examples: ${{ steps.select.outputs.examples }}',
                     "BASE: ${{ github.event_name == 'pull_request' && github.event.pull_request.base.sha || github.event.before }}",
                     'HEAD: ${{ github.sha }}','EVENT: ${{ github.event_name }}',        # FIX1 T3-A03: the path filter limit applies to a pull request
                     'PR_FILES: ${{ github.event.pull_request.changed_files }}',         # T6 (FIX1-A03): GitHub's own count of the pull request
                     'run: python3 ci/changed-examples --base "$BASE" --head "$HEAD" --event "$EVENT" --pr-files "$PR_FILES" >> "$GITHUB_OUTPUT"'):
            with self.subTest(job='select',line=line):self.assertIn(line,s)
        p=j['project']
        for line in ('needs: select',"if: needs.select.outputs.framework == 'true'",'timeout-minutes: 30',
                     'run: ./tools/safety project check --project examples/hello-world','name: project-report\n'):
            with self.subTest(job='project',line=line):self.assertIn(line,p)
        e=j['examples']
        for line in ('needs: select',"if: needs.select.outputs.examples != '[]'",'timeout-minutes: 45','fail-fast: false',
                     'example: ${{ fromJSON(needs.select.outputs.examples) }}','EXAMPLE: ${{ matrix.example }}',
                     'run: ./tools/safety project check --project "$EXAMPLE"','name: project-report-${{ strategy.job-index }}'):
            with self.subTest(job='examples',line=line):self.assertIn(line,e)
        setup=lambda job:job.split('    steps:\n',1)[1].split('      - name: Project gates',1)[0]
        self.assertEqual(setup(e),setup(p))           # the same checkout, dependencies, core pattern, image store and image load
        self.assertNotIn('--development',text)
        self.assertEqual(sorted(set(re.findall(r'examples/[A-Za-z0-9._-]+',text))),['examples/hello-world'])     # no standalone example named
        self.assertEqual([line for line in text.split('\n') if line.strip().startswith('run:') and '${{' in line],[])   # values reach the shell through env

def tracked_examples(root):
    """(paths under examples/, the export list) of a root: its git-tracked set (git ls-files, or the host tracked set
    policy.TRACKED_MANIFEST of a container source snapshot, as bench_b18.tracked_files reads it), else its files."""
    import bench_b18
    root=Path(root);tracked=bench_b18.tracked_files(root,['examples'])
    if tracked is None:tracked={p.relative_to(root).as_posix() for p in (root/'examples').rglob('*') if p.is_file() or p.is_symlink()}
    return {p for p in tracked if p.startswith('examples/')},set(json.loads((root/'starter-export.json').read_text())['files'])

class RealTreeListingTests(unittest.TestCase):
    """FIX1-A02: check-fast applies the head listing rule of ci/changed-examples (example_scopes and the export list) to the
    tracked tree, so an unlisted examples/README.md or an unlisted file of a framework example or of a project-less
    examples/<x> fails locally, not only in the select job on GitHub."""
    def test_a_temporary_root_with_unlisted_files_has_problems(self):
        sel=load_selector()
        with tempfile.TemporaryDirectory() as t:
            root=fixture(t,loose=True);write(root,{'examples/README.md':'r\n',f'{FW}/docs/notes.md':'n\n'})
            problems,standalone=sel.head_problems(*tracked_examples(root))
        self.assertEqual(standalone,[SOLO])
        for rel in ('examples/README.md',f'{FW}/docs/notes.md',f'{LOOSE}/src/n.c'):
            with self.subTest(rel=rel):self.assertIn('unlisted file under examples/: '+rel,problems)
    def test_the_real_tree_passes(self):
        problems,_=load_selector().head_problems(*tracked_examples(ROOT))
        self.assertEqual(problems,[])

class PullRequestCountTests(unittest.TestCase):
    """FIX1-A03: GitHub evaluates path filters over the three-dot diff of a pull request, which can hold more paths than the
    merge diff. select also compares GitHub's own count (github.event.pull_request.changed_files, --pr-files) with the
    300-file limit; the larger count decides, and an empty count of a pull request is unknown (fail closed). A push passes
    an empty value, which is not used."""
    def test_the_rule_reads_the_github_count(self):
        sel=load_selector();paths=lambda n:[f'tools/f{k}.py' for k in range(n)]
        for count in (300,301,10**6,'unknown'):
            with self.subTest(count=count):self.assertIn('300',sel.path_filter_problem('pull_request',paths(1),True,pr_files=count))
        self.assertIsNone(sel.path_filter_problem('pull_request',paths(1),True,pr_files=299))
        self.assertIsNone(sel.path_filter_problem('pull_request',paths(1),True,pr_files=0))
        self.assertIn('300',sel.path_filter_problem('pull_request',paths(300),True,pr_files=1))       # the larger count decides
        for event,framework in (('pull_request',False),('push',True)):
            with self.subTest(event=event,framework=framework):
                self.assertIsNone(sel.path_filter_problem(event,paths(1),framework,pr_files=500))
    def test_the_script_takes_the_count(self):
        change=lambda r:write(r,{'tools/new.py':'x\n'})
        for event,value,want in (('pull_request','299',0),('pull_request','300',1),('pull_request','',1),('push','',0),('push','300',0)):
            with self.subTest(event=event,value=value):
                rc,out,err=commit_pair(change,extra=('--event',event,'--pr-files',value))
                self.assertEqual(rc,want,err)
        for bad in ('-1','3.0','x','1'*13,' 3'):
            with self.subTest(bad=bad):self.assertEqual(commit_pair(change,extra=('--event','pull_request','--pr-files',bad))[0],2)
    def test_the_workflow_passes_the_github_count(self):
        s=jobs((ROOT/'.github/workflows/example.yml').read_text())['select']
        self.assertIn('PR_FILES: ${{ github.event.pull_request.changed_files }}',s)
        self.assertIn('run: python3 ci/changed-examples --base "$BASE" --head "$HEAD" --event "$EVENT" --pr-files "$PR_FILES" >> "$GITHUB_OUTPUT"',s)

class FrameworkModeTests(unittest.TestCase):
    """FIX1-A07: safety.yml ignores the project paths (project.json, src/, include/, tests/project/, fuzz/project/,
    specs/project/, review/), so in the framework repository (no root project.json) a pull request that changes only such a
    path would run only the hello-world project job. select fails (exit 1) in framework mode for a tracked file under a
    project path at --head, and for a root project.json that --head adds to a framework repository. A project repository
    (a root project.json at --base and --head) keeps its project paths."""
    def test_a_project_path_in_the_framework_repository_is_refused(self):
        for rel in ('src/app.c','include/app.h','tests/project/t.c','fuzz/project/f.c','specs/project/s.md','review/r.md'):
            for event in ('pull_request','push'):
                with self.subTest(rel=rel,event=event):
                    rc,out,err=commit_pair(lambda r:write(r,{rel:'x\n'}),extra=('--event',event))
                    self.assertEqual((rc,out),(1,{}),err);self.assertIn('a project path in the framework repository: '+rel,err)
    def test_a_root_project_json_added_to_the_framework_repository_is_refused(self):
        for event in ('pull_request','push'):
            with self.subTest(event=event):
                rc,out,err=commit_pair(lambda r:write(r,{'project.json':'{}\n'}),extra=('--event',event))
                self.assertEqual((rc,out),(1,{}),err);self.assertIn('a root project.json added to the framework repository',err)
    def test_a_project_repository_keeps_its_project_paths(self):
        project=lambda r:write(r,{'project.json':'{}\n','src/a.c':'int a;\n'})
        rc,out,err=commit_pair(lambda r:write(r,{'src/b.c':'int b;\n','include/b.h':'int b(void);\n'}),before=project,extra=('--event','pull_request'))
        self.assertEqual(rc,0,err)
        rc,out,err=commit_pair(project,base_arg='')                                    # a new project repository: no base
        self.assertEqual(rc,0,err)
    def test_the_real_tree_in_framework_mode_has_empty_project_paths(self):
        if (ROOT/'project.json').is_file():return                                       # project mode: the rule does not apply
        for top in pm.PROJECT_PATHS:
            with self.subTest(top=top):self.assertEqual([p for p in (ROOT/top).rglob('*') if p.is_file()] if (ROOT/top).is_dir() else [],[])

class SymbolicLinkTextTests(unittest.TestCase):
    """FIX1-A06: the text names exactly the links that give exit 2 (examples/, examples/<name>, examples/<name>/project.json);
    a deeper link follows the listing rule (exit 1 when it is unlisted outside a standalone tree; a standalone tree may hold it)."""
    def test_the_text_is_exact(self):
        readme=' '.join((ROOT/'ci/README.md').read_text().split());doc=' '.join(load_selector().__doc__.split())
        self.assertIn('a symbolic link at `examples/`, `examples/<name>` or `examples/<name>/project.json`',readme)
        self.assertIn('a symbolic link at examples/, examples/<name> or examples/<name>/project.json',doc)
        self.assertIn('A deeper link follows the listing rule',readme);self.assertIn('A deeper link follows the listing rule',doc)
        self.assertNotIn('symbolic link under `examples/`',readme);self.assertNotIn('a symbolic link under examples/',doc)
    def test_a_deeper_link_follows_the_listing_rule(self):
        rc,out,err=commit_pair(lambda r:os.symlink('a.c',r/SOLO/'src/link.c'))
        self.assertEqual(rc,0,err)
        rc,out,err=commit_pair(lambda r:os.symlink('a.c',r/FW/'src/link.c'))
        self.assertEqual((rc,out),(1,{}),err);self.assertIn(f'unlisted file under examples/: {FW}/src/link.c',err)

if __name__=='__main__':unittest.main()
