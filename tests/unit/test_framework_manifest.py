"""Framework file set, manifest export through instantiate and the source identity exclusions."""
import json, shutil, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'tools'))
sys.path.insert(0,str(HERE))
from evidence import GateError
import policy
import project_model as pm
from test_project_model import framework_copy, tree

IMAGES={'sdk':'sha256:'+'a'*64,'developer':'sha256:'+'b'*64,'archive_sha256':'c'*64}

def exported(base, files):
    (base/'starter-export.json').write_text(json.dumps({'schema_version':1,'substitutions':[],'files':sorted(files+['starter-export.json'])}))

def report(root):
    return {'overall_state':'VALIDATED_UNSEALED','source_identity':policy.source_identity(root)[0],'run_id':'d'*32}

class FrameworkFileSetTests(unittest.TestCase):
    def test_set_is_export_list_minus_instance_files(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t); tree(d,{'tools/a.py':'a','docs/x.md':'x','starter.json':'{}','starter-baseline.lock.json':'{}','README.md':'r'})
            exported(d,['tools/a.py','docs/x.md','starter.json','starter-baseline.lock.json','README.md'])
            files=pm.framework_files(d)
            self.assertEqual(set(files),{'tools/a.py','docs/x.md','README.md','starter-export.json'})
            self.assertEqual(files['tools/a.py'],policy.file_hash(d/'tools/a.py'))
    def test_unlisted_file_under_framework_directory_is_added(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t); tree(d,{'tools/a.py':'a'}); exported(d,['tools/a.py'])
            unlisted=['tools/b.py','safety/x.json','schemas/s.json','cmake/c.cmake','container/f','ci/w.yml','foundation/z.c',
                      'third_party/l/n.c','.githooks/h','.github/workflows/other.yml','fuzz/f.c','tests/unit/t.py','tests/integration/i.c']
            ignored=['tools/__pycache__/a.pyc','.superpowers/s.md','artifacts/r.json','build/x.o','tests/project/p.c','fuzz/project/q.c',
                     'docs/new.md','notes.txt','.github/workflows/project-ci.yml','tools/.cache/c','foundation/build/o','safety/.direnv/e',
                     'project.json',pm.MANIFEST]
            tree(d,{rel:'n' for rel in unlisted+ignored})
            self.assertEqual(set(pm.framework_files(d)),{'tools/a.py','starter-export.json',*unlisted})
    def test_missing_listed_file_is_absent_not_an_error(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t); tree(d,{'tools/a.py':'a'}); exported(d,['tools/a.py','tools/gone.py'])
            self.assertEqual(set(pm.framework_files(d)),{'tools/a.py','starter-export.json'})
    def test_missing_or_unsafe_export_list_is_gate_error(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t); tree(d,{'tools/a.py':'a'})
            with self.assertRaises(GateError): pm.framework_files(d)
            for bad in (['../x'],['/etc/passwd'],['a//b'],[3],'tools/a.py'):
                (d/'starter-export.json').write_text(json.dumps({'files':bad}))
                with self.assertRaises(GateError): pm.framework_files(d)
    def test_symlink_in_framework_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t); tree(d,{'tools/a.py':'a'}); exported(d,['tools/a.py']); (d/'tools/link').symlink_to(d/'tools/a.py')
            with self.assertRaises(GateError): pm.framework_files(d)
    def test_write_manifest_refuses_unexported_framework_file(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t); tree(d,{'tools/a.py':'a','tools/b.py':'b'}); exported(d,['tools/a.py'])
            with self.assertRaises(GateError): pm.write_manifest(d,report(d),IMAGES,framework_root=ROOT)
            self.assertFalse((d/pm.MANIFEST).exists())

class SourceIdentityTests(unittest.TestCase):
    def test_manifest_and_scratch_are_not_source_inputs(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t); tree(d,{'tools/a.py':'a'})
            before=policy.source_identity(d)
            tree(d,{pm.MANIFEST:'{}','.superpowers/sdd/x.md':'x','tools/.superpowers/y':'y'})
            self.assertEqual(policy.source_identity(d),before)
            tree(d,{'tools/'+pm.MANIFEST:'{}'})
            self.assertIn('tools/'+pm.MANIFEST,policy.source_files(d))
    def test_manifest_write_keeps_report_fresh_and_binds_current_identity(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t); tree(d,{'tools/a.py':'a'}); exported(d,['tools/a.py']); value=report(d)
            pm.write_manifest(d,value,IMAGES,framework_root=ROOT)
            self.assertEqual(policy.source_identity(d)[0],value['source_identity'])
            pm.write_manifest(d,value,IMAGES,framework_root=ROOT)
            (d/'tools/a.py').write_text('changed')
            with self.assertRaises(GateError): pm.write_manifest(d,value,IMAGES,framework_root=ROOT)

def manifest_parent(base):
    """Reduced framework copy with a tools/ file, and a manifest written for its framework set."""
    parent=framework_copy(base)
    extra=['tools/project_model.py','safety/contract.json']
    for rel in extra:
        (parent/rel).parent.mkdir(parents=True,exist_ok=True); shutil.copy2(ROOT/rel,parent/rel)
    manifest=json.loads((parent/'starter-export.json').read_text())
    manifest['files']=sorted(manifest['files']+extra)
    (parent/'starter-export.json').write_text(json.dumps(manifest,indent=2)+'\n')
    pm.write_manifest(parent,report(parent),IMAGES)
    return parent

class ManifestInstantiateTests(unittest.TestCase):
    def test_child_manifest_matches_and_detects_drift(self):
        import starter, project_check
        with tempfile.TemporaryDirectory() as t:
            parent=manifest_parent(Path(t)/'parent'); child=Path(t)/'out'/'my-app'
            self.assertEqual(pm.check_manifest(parent),[])
            starter.instantiate(parent,child,'my-app',maintenance=True)
            self.assertEqual((child/pm.MANIFEST).read_bytes(),(parent/pm.MANIFEST).read_bytes())
            self.assertEqual(pm.check_manifest(child),[])
            self.assertEqual(project_check.framework_differences(child,child,IMAGES['sdk']),[])
            self.assertEqual(set(policy.source_identity(child)[1]),starter.instance_files(parent))
            policy.baseline_gate(child,parent,policy.baseline_identity(parent))
            (child/'tools/project_model.py').write_text('# edited\n'); (child/'tools/extra.py').write_text('x')
            self.assertEqual(pm.check_manifest(child),['added: tools/extra.py','changed: tools/project_model.py'])
    def test_stale_parent_manifest_is_refused(self):
        import starter, containment
        with tempfile.TemporaryDirectory() as t:
            parent=manifest_parent(Path(t)/'parent'); child=Path(t)/'child'
            tree(parent,{'toolchain.lock.json':json.dumps({'image_id':'sha256:'+'1'*64}),
                         'artifacts/bootstrap-report.json':json.dumps({'local_state':'PASS','commands':['./tools/safety ci']})})
            (parent/'tools/project_model.py').write_text('# drift\n')
            with mock.patch.object(starter,'validate_fresh_report',lambda *a:None), \
                 mock.patch.object(containment,'fresh_container_evidence',lambda *a:None):
                with self.assertRaises(GateError): starter.instantiate(parent,child,'my-app')
                self.assertFalse(child.exists())
                (parent/'tools/project_model.py').write_bytes((ROOT/'tools/project_model.py').read_bytes())
                self.assertEqual(starter.instantiate(parent,child,'my-app')['status'],'CREATED_UNSEALED')
            self.assertEqual(pm.check_manifest(child),[])
    def test_symlinked_parent_manifest_is_refused(self):
        import starter
        with tempfile.TemporaryDirectory() as t:
            parent=framework_copy(Path(t)/'parent'); (parent/'elsewhere.json').write_text('{}')
            (parent/pm.MANIFEST).symlink_to(parent/'elsewhere.json')
            with self.assertRaises(GateError): starter.instantiate(parent,Path(t)/'child','my-app',maintenance=True)

if __name__=='__main__':unittest.main()
