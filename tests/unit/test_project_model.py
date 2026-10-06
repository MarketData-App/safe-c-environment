import json, sys, tempfile, unittest, hashlib
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
    def test_project_files_normal(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t); self.make(d); f=pm.project_files(d,'.')
            self.assertIn('src/greeting.c',f); self.assertNotIn('project.json',f)
    def test_forbidden_text(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(GateError): self.inv(Path(t),extra={'src/greeting.c':'int x; // NOLINT'},mutate=None)
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

if __name__=='__main__':unittest.main()
