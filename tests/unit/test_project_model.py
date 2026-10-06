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

if __name__=='__main__':unittest.main()
