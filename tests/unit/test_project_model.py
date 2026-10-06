import json, sys, tempfile, unittest, hashlib, io
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools'))
from evidence import GateError
import project_model as pm
ROOT=Path(__file__).resolve().parents[2]

def tree(base, files):
    for rel,text in files.items():
        p=base/rel; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(text)

PROJECT={'schema_version':1,'name':'demo-app','modules':[{'name':'greeting','spec':'specs/project/greeting.md','sources':['src/greeting.c'],
  'headers':['include/greeting.h'],'tests':['tests/project/test_greeting.c'],'reads_external_input':True,
  'fuzz':[{'name':'greeting','harness':'fuzz/project/greeting_fuzz.c','corpus':'fuzz/project/corpus/greeting','regressions':'fuzz/project/regressions/greeting'}]}],
  'programs':[{'name':'hello','main':'src/main.c','modules':['greeting']}],'run':{'program':'hello','args':['world'],'expect_exit':0}}

class ProjectModelTests(unittest.TestCase):
    def make(self, d, project=PROJECT, extra=None):
        files={'project.json':json.dumps(project),'specs/project/greeting.md':'# spec','src/greeting.c':'int x;','src/main.c':'int main(void){return 0;}',
               'include/greeting.h':'int x;','tests/project/test_greeting.c':'int main(void){return 0;}','fuzz/project/greeting_fuzz.c':'int y;',
               'fuzz/project/corpus/greeting/seed':'a','fuzz/project/regressions/greeting/.keep':''}
        files.update(extra or {}); tree(d,files)
    def test_valid_project_loads_and_inventories(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t); self.make(d); p=pm.load_project(d); pm.project_inventory(d,'.',p)
    def test_empty_project_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t); self.make(d,dict(PROJECT,modules=[]))
            with self.assertRaises(GateError): pm.load_project(d)
    def test_flags_or_unknown_keys_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t); self.make(d,dict(PROJECT,cflags=['-w']))
            with self.assertRaises(GateError): pm.load_project(d)
    def test_unlisted_project_file_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t); self.make(d,extra={'src/extra.c':'int z;'})
            with self.assertRaises(GateError): pm.project_inventory(d,'.',pm.load_project(d))
    def test_external_input_module_needs_fuzz(self):
        with tempfile.TemporaryDirectory() as t:
            m=dict(PROJECT['modules'][0],fuzz=[]); d=Path(t); self.make(d,dict(PROJECT,modules=[m]))
            with self.assertRaises(GateError): pm.project_inventory(d,'.',pm.load_project(d))
    def test_paths_with_space_and_unicode(self):
        with tempfile.TemporaryDirectory() as t:
            m=dict(PROJECT['modules'][0],spec='specs/project/grüße plan.md'); d=Path(t)
            self.make(d,dict(PROJECT,modules=[m]),{'specs/project/grüße plan.md':'# spec'})
            pm.project_inventory(d,'.',pm.load_project(d))
    def test_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            m=dict(PROJECT['modules'][0],sources=['src/../tools/x.c']); d=Path(t); self.make(d,dict(PROJECT,modules=[m]))
            with self.assertRaises(GateError): pm.load_project(d)
    def test_manifest_detects_added_removed_changed_framework_file(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t); self.make(d,extra={'tools/a.py':'a','safety/b.json':'{}'})
            files=pm.framework_files(d); ident=hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()
            (d/pm.MANIFEST).write_text(json.dumps({'schema_version':1,'framework_identity':ident,'files':files,
              'images':{'sdk':'sha256:'+'a'*64,'developer':'sha256:'+'b'*64,'archive_sha256':'c'*64},
              'qualification':{'run_id':'d'*32,'source_identity':'e'*64,'overall_state':'VALIDATED_UNSEALED'}}))
            self.assertEqual(pm.check_manifest(d),[])
            (d/'tools/new.py').write_text('n'); (d/'safety/b.json').write_text('{"x":1}'); (d/'tools/a.py').unlink()
            self.assertEqual(sorted(pm.check_manifest(d)),['added: tools/new.py','changed: safety/b.json','removed: tools/a.py'])
    def test_project_paths_are_not_framework_files(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t); self.make(d); self.assertFalse(any(p.startswith(pm.PROJECT_PATHS) or p=='project.json' for p in pm.framework_files(d)))
    def test_project_policy_lists_23_gates(self):
        self.assertEqual(len(pm.project_policy(ROOT)['gates']),23)

class ProjectModelMoreTests(unittest.TestCase):
    make=ProjectModelTests.make
    def inv(self, d, project=PROJECT, extra=None, mutate=None):
        self.make(d, project, extra)
        if mutate: mutate(d)
        pm.project_inventory(d, '.', pm.load_project(d))
    def test_symlinked_top_dir_rejected(self):
        with tempfile.TemporaryDirectory() as t, tempfile.TemporaryDirectory() as o:
            d=Path(t); self.make(d); import shutil; shutil.rmtree(d/'src'); (d/'src').symlink_to(o)
            with self.assertRaises(GateError): pm.project_files(d,'.')
    def test_symlinked_intermediate_dir_rejected(self):
        with tempfile.TemporaryDirectory() as t, tempfile.TemporaryDirectory() as o:
            d=Path(t); real=Path(o)/'real'; real.mkdir(); self.make(real)
            (d/'examples').mkdir(); (d/'examples/link').symlink_to(real); (d/'examples/link/proj').mkdir()
            self.make(d/'examples/link/proj')
            with self.assertRaises(GateError): pm.project_files(d,'examples/link/proj')
    def test_project_files_normal(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t); self.make(d); f=pm.project_files(d,'.')
            self.assertIn('src/greeting.c',f); self.assertNotIn('project.json',f)
    def test_forbidden_text(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(GateError): self.inv(Path(t),extra={'src/greeting.c':'int x; // NOLINT'},mutate=None)
    def test_forbidden_sanitizer_and_pragma_patterns(self):
        # Built from fragments so this file does not itself hold the forbidden spellings.
        us='_'+'_'; feat=us+'has_feature'
        cases={'no_sanitize':'__attribute__((no'+'_sanitize("address"))) int f(void);',
               'ignorelist':'// -fsanitize-'+'ignorelist=x.txt',
               'sanitize macro':'#if defined('+us+'SANITIZE_ADDRESS'+us+')\n#endif',
               'feature':'#if '+feat+'(address_sanitizer)\n#endif',
               'feature spaced':'#if '+feat+' ( memory_sanitizer )\n#endif',
               'feature thread':'#if '+feat+'(thread_sanitizer)\n#endif',
               'feature ub':'#if '+feat+'(undefined_behavior_sanitizer)\n#endif',
               'extension':'#if '+us+'has_extension(address_sanitizer)\n#endif',
               'pragma operator':'_'+'Pragma("GCC diagnostic ignored \\"-Wconversion\\"")',
               'pragma spaced':'#  pragma   GCC  diagnostic ignored "-Wconversion"',
               'pragma clang':'# pragma clang diagnostic push',
               'pragma optimize':'#pragma GCC optimize("O0")',
               'pragma comment':'#/**/pragma GCC diagnostic push',
               'spliced pragma':'_Pra\\\ngma("x")',
               'spliced feature':feat+'\\\n(address_sanitizer)',
               'attribute optimize':'__attribute__ (( optimize("O0"))) int f(void);',
               'no_address_safety':'__attribute__((no'+'_address_safety_analysis)) int f(void);',
               'disable instrumentation':'__attribute__((disable'+'_sanitizer_instrumentation)) int f(void);',
               'nolint':'int x; // NO'+'LINT'}
        for name,text in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as t:
                with self.assertRaises(GateError): self.inv(Path(t),extra={'src/greeting.c':text},mutate=None)
        for name in ('feature spaced','pragma comment','spliced pragma','spliced feature','extension'):
            with self.subTest(header=name), tempfile.TemporaryDirectory() as t:
                with self.assertRaises(GateError): self.inv(Path(t),extra={'include/greeting.h':cases[name]},mutate=None)
    def test_ordinary_code_is_not_forbidden(self):
        with tempfile.TemporaryDirectory() as t:
            self.inv(Path(t),extra={'src/greeting.c':'#pragma once\n/* sanitize the input */ int has_feature_x(void);'},mutate=None)
    def test_missing_spec(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(GateError): self.inv(Path(t),mutate=lambda d:(d/'specs/project/greeting.md').unlink())
    def test_empty_corpus(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(GateError): self.inv(Path(t),mutate=lambda d:(d/'fuzz/project/corpus/greeting/seed').unlink())
    def test_missing_regressions(self):
        import shutil
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(GateError): self.inv(Path(t),mutate=lambda d:shutil.rmtree(d/'fuzz/project/regressions'))
    def test_duplicate_module(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t); self.make(d,dict(PROJECT,modules=[PROJECT['modules'][0]]*2))
            with self.assertRaises(GateError): pm.load_project(d)
    def test_unknown_program_module(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t); self.make(d,dict(PROJECT,programs=[dict(PROJECT['programs'][0],modules=['nope'])]))
            with self.assertRaises(GateError): pm.load_project(d)
    def test_undeclared_run_program(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t); self.make(d,dict(PROJECT,run=dict(PROJECT['run'],program='nope')))
            with self.assertRaises(GateError): pm.load_project(d)
    def test_write_manifest(self):
        import policy
        with tempfile.TemporaryDirectory() as t:
            d=Path(t); self.make(d); images={'sdk':'sha256:'+'a'*64,'developer':'sha256:'+'b'*64,'archive_sha256':'c'*64}
            ident=policy.source_identity(d)[0]
            good={'overall_state':'VALIDATED_UNSEALED','source_identity':ident,'run_id':'d'*32}
            with self.assertRaises(GateError): pm.write_manifest(d,dict(good,overall_state='PASS'),images)
            with self.assertRaises(GateError): pm.write_manifest(d,dict(good,source_identity='0'*64),images)
            with self.assertRaises(GateError): pm.write_manifest(d,{k:v for k,v in good.items() if k!='run_id'},images)
            with self.assertRaises(GateError): pm.write_manifest(d,dict(good,run_id='D'*32),images)
            m=pm.write_manifest(d,good,images); self.assertEqual(m['qualification']['run_id'],'d'*32)
            self.assertEqual(pm.check_manifest(d),[])
    def test_manifest_identity_mismatch(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t); self.make(d,extra={'tools/a.py':'a'}); files=pm.framework_files(d)
            (d/pm.MANIFEST).write_text(json.dumps({'schema_version':1,'framework_identity':'0'*64,'files':files,
              'images':{'sdk':'sha256:'+'a'*64,'developer':'sha256:'+'b'*64,'archive_sha256':'c'*64},
              'qualification':{'run_id':'d'*32,'source_identity':'e'*64,'overall_state':'VALIDATED_UNSEALED'}}))
            self.assertEqual(pm.check_manifest(d),['identity: framework_identity mismatch'])

def framework_copy(base):
    """Small exported framework in base (the full payload exceeds container scratch); stand-in CI template if absent."""
    import shutil, policy
    exported=policy.export_inventory(ROOT)
    files=[rel for rel in exported if rel in ('starter.json','starter-baseline.lock.json','README.md','AGENTS.md','safety/project-policy.json',
           'ci/project-ci.yml') or rel.startswith(('schemas/','examples/hello-world/'))]
    for rel in files:
        q=base/rel; q.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(ROOT/rel,q)
    if 'ci/project-ci.yml' not in files:
        (base/'ci').mkdir(exist_ok=True); (base/'ci/project-ci.yml').write_text('name: project-ci stand-in\n')
        files.append('ci/project-ci.yml')
    (base/'starter-export.json').write_text(json.dumps(dict(json.loads((ROOT/'starter-export.json').read_text()),
        files=sorted(files+['starter-export.json'])),indent=2)+'\n')
    return base

class ProjectModeInstantiateTests(unittest.TestCase):
    def test_instantiate_creates_project_mode(self):
        import starter, policy
        with tempfile.TemporaryDirectory() as t:
            parent=framework_copy(Path(t)/'parent'); child=Path(t)/'out'/'my-app'
            result=starter.instantiate(parent,child,'my-app',maintenance=True)
            self.assertEqual(result['status'],'CREATED_UNSEALED')
            example=json.loads((ROOT/'examples/hello-world/project.json').read_text())
            project=json.loads((child/'project.json').read_text())
            self.assertEqual(project,dict(example,name='my-app'))
            pm.project_inventory(child,'.',pm.load_project(child))
            for rel in ['src/greeting.c','src/main.c','include/greeting.h','tests/project/test_greeting.c','fuzz/project/greeting_fuzz.c',
                        'fuzz/project/corpus/greeting/seed-world','fuzz/project/regressions/greeting/.keep','specs/project/greeting.md','review/ledger.json']:
                self.assertEqual((child/rel).read_bytes(),(ROOT/'examples/hello-world'/rel).read_bytes(),rel)
            for rel in ['README.md','AGENTS.md']:
                self.assertEqual((child/rel).read_bytes(),(parent/rel).read_bytes(),rel)
            self.assertEqual((child/'.github/workflows/project-ci.yml').read_bytes(),(parent/'ci/project-ci.yml').read_bytes())
            mine,theirs=pm.framework_files(child),pm.framework_files(parent)
            self.assertEqual(set(mine),set(theirs))
            changed={rel for rel in mine if mine[rel]!=theirs[rel]}
            self.assertEqual(changed,{'starter.json','starter-baseline.lock.json'})
            self.assertEqual(set(policy.source_identity(child)[1]),starter.instance_files(parent))
            self.assertTrue(policy.project_mode(child))
            policy.bootstrap_source_rule(child,'bootstrap')
            self.assertFalse(any(rel.startswith(pm.PROJECT_PATHS) for rel in policy.first_party_sources(child)))
            self.assertIn('examples/hello-world/src/greeting.c',policy.first_party_sources(child))
            self.assertEqual(pm.undeclared_application_sources(child),[])
    def test_instantiate_requires_project_ci_template(self):
        import starter
        with tempfile.TemporaryDirectory() as t:
            parent=framework_copy(Path(t)/'parent')
            manifest=json.loads((parent/'starter-export.json').read_text())
            manifest['files'].remove('ci/project-ci.yml'); (parent/'starter-export.json').write_text(json.dumps(manifest))
            (parent/'ci/project-ci.yml').unlink(); child=Path(t)/'child'
            with self.assertRaises(GateError): starter.instantiate(parent,child,'my-app',maintenance=True)
            self.assertFalse(child.exists())
            self.assertEqual([p.name for p in Path(t).iterdir()],['parent'])

class ProjectModeSourceRuleTests(unittest.TestCase):
    make=ProjectModelTests.make
    def test_bootstrap_rule_still_blocks_without_project_json(self):
        import policy
        with tempfile.TemporaryDirectory() as t:
            d=Path(t); tree(d,{'src/app.c':'int a;','tools/x.c':'int b;'})
            self.assertFalse(policy.project_mode(d))
            with self.assertRaises(GateError): policy.bootstrap_source_rule(d,'bootstrap')
            self.assertEqual(policy.first_party_sources(d),{'src/app.c','tools/x.c'})
            self.assertEqual(pm.undeclared_application_sources(d),['src/app.c'])
    def test_bootstrap_rule_blocks_headers_without_project_json(self):
        import policy
        with tempfile.TemporaryDirectory() as t:
            d=Path(t); tree(d,{'include/app.h':'int a;'})
            with self.assertRaises(GateError): policy.bootstrap_source_rule(d,'bootstrap')
    def test_empty_bootstrap_tree_passes(self):
        import policy
        with tempfile.TemporaryDirectory() as t:
            d=Path(t); tree(d,{'src/README':'x'}); policy.bootstrap_source_rule(d,'bootstrap')
            self.assertEqual(pm.undeclared_application_sources(d),[])
    def test_project_json_relaxes_rule_for_root_project_paths_only(self):
        import policy
        with tempfile.TemporaryDirectory() as t:
            d=Path(t); self.make(d,extra={'tools/x.c':'int b;','examples/hello-world/src/greeting.c':'int c;'})
            policy.bootstrap_source_rule(d,'bootstrap')
            self.assertEqual(policy.first_party_sources(d),{'tools/x.c','examples/hello-world/src/greeting.c'})
    def test_undeclared_project_source_still_blocks_developer(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t); self.make(d,extra={'src/extra.c':'int z;','include/extra.h':'int z;'})
            self.assertEqual(pm.undeclared_application_sources(d),['include/extra.h','src/extra.c'])
    def test_invalid_project_json_blocks_developer(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t); self.make(d,dict(PROJECT,modules=[]))
            with self.assertRaises(GateError): pm.undeclared_application_sources(d)

class ProjectCliTests(unittest.TestCase):
    make=ProjectModelTests.make
    def run_cli(self, argv):
        import cli
        from unittest import mock
        with mock.patch.object(cli,'environment_gate',lambda:None):
            return cli.main(argv)
    def test_project_check_routes_to_run_project_check(self):
        import types, os
        from unittest import mock
        calls=[]
        fake=types.ModuleType('project_check')
        fake.run_project_check=lambda root,project_dir,development=False: calls.append((root,project_dir,development)) or {'exit_code':3}
        with tempfile.TemporaryDirectory() as t, tempfile.TemporaryDirectory() as elsewhere, mock.patch.dict(sys.modules,{'project_check':fake}):
            d=Path(t).resolve(); cwd=os.getcwd(); os.chdir(elsewhere)
            try:
                self.assertEqual(self.run_cli(['--candidate',str(d),'project','check']),3)
                self.assertEqual(self.run_cli(['--candidate',str(d),'project','check','--project','examples/hello-world','--development']),3)
                self.assertEqual(self.run_cli(['--candidate',str(d),'project','check','--project',str(d/'examples/hello-world')]),3)
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(self.run_cli(['--candidate',str(d),'project','check','--project',elsewhere]),2)
                    for bad in ('../x','a/../../x','/etc'):
                        self.assertEqual(self.run_cli(['--candidate',str(d),'project','check','--project',bad]),2)
                self.assertEqual(self.run_cli(['--candidate',str(d),'project','check','--project','examples/../examples/hello-world']),3)
            finally: os.chdir(cwd)
        self.assertEqual(calls,[(d,'.',False),(d,'examples/hello-world',True),(d,'examples/hello-world',False),(d,'examples/hello-world',False)])
    def test_project_requires_known_operation(self):
        with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()): self.run_cli(['project','build'])
    def manifest_tree(self, d, bundle_ids=None, extra=None):
        import policy
        files={'tools/a.py':'a','toolchain.lock.json':json.dumps({'image_id':'sha256:'+'1'*64}),
               'developer.lock.json':json.dumps({'image_id':'sha256:'+'2'*64}),
               'ci/image-bundle.json':json.dumps({'archive_sha256':'3'*64,'image_ids':bundle_ids if bundle_ids is not None else ['sha256:'+'1'*64,'sha256:'+'2'*64]})}
        files.update(extra or {}); self.make(d,extra=files)
        report={'overall_state':'VALIDATED_UNSEALED','source_identity':policy.source_identity(d)[0],'run_id':'d'*32}
        tree(d,{'artifacts/bootstrap-report.json':json.dumps(report)})
        return report
    def manifest_cli(self, d, fresh=True):
        from unittest import mock
        from contextlib import nullcontext
        patch=mock.patch.object(pm,'_fresh_report',lambda root,report:None) if fresh else nullcontext()
        with patch, redirect_stdout(io.StringIO()):
            return self.run_cli(['--candidate',str(d),'framework','manifest'])
    def test_framework_manifest(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t); report=self.manifest_tree(d)
            self.assertEqual(self.manifest_cli(d),0)
            value=json.loads((d/pm.MANIFEST).read_text())
            self.assertEqual(value['images'],{'sdk':'sha256:'+'1'*64,'developer':'sha256:'+'2'*64,'archive_sha256':'3'*64})
            self.assertEqual(pm.check_manifest(d),[])
            tree(d,{'artifacts/bootstrap-report.json':json.dumps(dict(report,overall_state='PASS'))})
            self.assertEqual(self.manifest_cli(d),1)
    def test_framework_manifest_runs_report_freshness_checks(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t); self.manifest_tree(d)
            with self.assertRaises(GateError): pm.framework_manifest(d)
            self.assertEqual(self.manifest_cli(d,fresh=False),1)
            self.assertFalse((d/pm.MANIFEST).exists())
    def test_framework_manifest_requires_bundled_images(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t); self.manifest_tree(d,bundle_ids=['sha256:'+'1'*64])
            self.assertEqual(self.manifest_cli(d),1); self.assertFalse((d/pm.MANIFEST).exists())
    def test_framework_manifest_missing_key_is_gate_error(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t); self.manifest_tree(d,extra={'developer.lock.json':'{}'})
            with self.assertRaises(GateError): pm.framework_manifest(d)
            self.assertEqual(self.manifest_cli(d),1); self.assertFalse((d/pm.MANIFEST).exists())

class ProjectModeFixRoundTests(unittest.TestCase):
    make=ProjectModelTests.make
    def test_undeclared_project_test_source_blocks_inventory(self):
        import policy
        with tempfile.TemporaryDirectory() as t:
            d=Path(t); self.make(d); policy.project_source_gate(d)
            tree(d,{'tests/project/x.c':'int x;'})
            self.assertNotIn('tests/project/x.c',policy.first_party_sources(d))
            with self.assertRaises(GateError): policy.project_source_gate(d)
    def test_inventory_gate_runs_project_source_gate(self):
        import policy
        from unittest import mock
        root=Path(__file__).resolve().parents[2]
        with mock.patch.object(policy,'project_mode',lambda r:True), mock.patch.object(pm,'load_project',lambda r:{}), \
             mock.patch.object(pm,'project_inventory',side_effect=GateError('undeclared tests/project/x.c')) as inv:
            with self.assertRaisesRegex(GateError,'undeclared tests/project/x.c'): policy.inventory_gate(root)
        self.assertEqual(inv.call_count,1)
    def test_undeclared_project_fuzz_source_blocks_inventory(self):
        import policy
        with tempfile.TemporaryDirectory() as t:
            d=Path(t); self.make(d,extra={'fuzz/project/other.c':'int x;'})
            with self.assertRaises(GateError): policy.project_source_gate(d)
    def test_no_project_json_leaves_project_gate_inactive(self):
        import policy
        with tempfile.TemporaryDirectory() as t:
            d=Path(t); tree(d,{'tests/project/x.c':'int x;'}); policy.project_source_gate(d)
            self.assertIn('tests/project/x.c',policy.first_party_sources(d))
    def test_symlinked_project_json_is_not_project_mode(self):
        import policy, os
        with tempfile.TemporaryDirectory() as t:
            d=Path(t)/'p'; self.make(d); real=Path(t)/'real.json'; os.replace(d/'project.json',real); (d/'project.json').symlink_to(real)
            self.assertFalse(policy.project_mode(d))
            with self.assertRaises(GateError): policy.bootstrap_source_rule(d,'bootstrap')
            self.assertIn('src/greeting.c',policy.first_party_sources(d))
            with self.assertRaises(GateError): pm.undeclared_application_sources(d)
    def test_instantiate_refuses_payload_collision(self):
        import starter, shutil
        with tempfile.TemporaryDirectory() as t:
            parent=framework_copy(Path(t)/'parent'); child=Path(t)/'child'
            (parent/'src').mkdir(); shutil.copy2(ROOT/'examples/hello-world/src/greeting.c',parent/'src/greeting.c')
            manifest=json.loads((parent/'starter-export.json').read_text())
            manifest['files']=sorted(manifest['files']+['src/greeting.c']); (parent/'starter-export.json').write_text(json.dumps(manifest))
            with self.assertRaises(GateError): starter.instantiate(parent,child,'my-app',maintenance=True)
            self.assertFalse(child.exists())

if __name__=='__main__':unittest.main()
