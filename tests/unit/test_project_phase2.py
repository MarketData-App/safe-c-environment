import copy, json, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from evidence import GateError
import project_model as pm, project_check as pc
SCHEMA=json.loads((ROOT/'schemas/project.json').read_text())
BASE=json.loads((ROOT/'examples/hello-world/project.json').read_text())

def module(name,**extra):
    return dict({'name':name,'spec':'specs/project/x.md','sources':[f'src/{name}.c'],'headers':[],'tests':[f'tests/project/t_{name}.c'],
                 'reads_external_input':False,'fuzz':[]},**extra)

class ProjectPhase2Tests(unittest.TestCase):
    def test_schema_knows_uses_and_foundation_only_with_closed_values(self):
        props=SCHEMA['properties']['modules']['items']['properties']
        # FR2-01: the closed value keeps one const; the description documents the build rule
        self.assertEqual({k:v for k,v in props['foundation'].items() if k!='description'},{'const':'glib-parallel'})
        for field in (props['foundation'],props['uses'],SCHEMA['properties']['libraries']):
            self.assertIsInstance(field.get('description'),str)
        self.assertEqual(props['uses']['items']['pattern'],'^[a-z][a-z0-9_]{0,62}$')
        self.assertNotIn('uses',SCHEMA['properties']['modules']['items']['required'])
    def test_uses_closure_and_rules(self):
        p={'modules':[module('models'),module('protocol'),module('batch',uses=['models','protocol']),module('serve',uses=['batch'])]}
        self.assertEqual(pm.uses_closure(p,'serve'),['models','protocol','batch'])
        self.assertEqual(pm.uses_closure(p,'models'),[])
        for bad,msg in (([module('a',uses=['zz'])],'unknown'),([module('a',uses=['a'])],'itself'),
                        ([module('a',uses=['b']),module('b',uses=['a'])],'cycle')):
            with self.assertRaisesRegex(GateError,msg):pm.check_module_dependencies({'modules':bad})
    def test_closure_allowlist_comes_from_the_lock(self):
        allow=pc.closure_allowlist(ROOT)
        lock=json.loads((ROOT/'foundation.lock.json').read_text())['profiles']['clang-O2']['files']
        self.assertEqual(allow,{'libglib-2.0.so.0':lock['lib/libglib-2.0.so.0'],'libpcre2-8.so.0':lock['lib/libpcre2-8.so.0']})
    def test_closure_script_accepts_only_lock_identified_profile_libraries(self):
        self.assertIn("'/opt/foundation/clang-O2/lib'",pc._CLOSURE)
        self.assertIn('def resolve_library',pc._CLOSURE)
        self.assertNotIn('/opt/foundation/clang-O0',pc._CLOSURE)
    def test_planted_system_copy_never_wins(self):
        import hashlib
        with tempfile.TemporaryDirectory() as d:
            sysdir=Path(d)/'usr-lib';prof=Path(d)/'profile';sysdir.mkdir();prof.mkdir()
            (sysdir/'libpcre2-8.so.0').write_bytes(b'debian copy');(sysdir/'libglib-2.0.so.0').write_bytes(b'ambient glib')
            (prof/'libpcre2-8.so.0').write_bytes(b'locked pcre');(sysdir/'libc.so.6').write_bytes(b'libc')
            sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
            allow={'libpcre2-8.so.0':sha(prof/'libpcre2-8.so.0'),'libglib-2.0.so.0':'0'*64}
            res=lambda n:pc.resolve_library(n,allow,[str(sysdir)],str(prof),lambda x:Path(x).is_file(),sha)
            self.assertEqual(res('libpcre2-8.so.0'),str(prof/'libpcre2-8.so.0'))          # the planted system copy is ignored
            self.assertEqual(res('libc.so.6'),str(sysdir/'libc.so.6'))
            with self.assertRaises(SystemExit) as c:res('libglib-2.0.so.0')                 # locked file missing: never the system copy
            self.assertEqual(c.exception.code,44)
            (prof/'libglib-2.0.so.0').write_bytes(b'tampered')
            with self.assertRaises(SystemExit) as c:res('libglib-2.0.so.0')
            self.assertEqual(c.exception.code,43)
            with self.assertRaises(SystemExit) as c:res('libnope.so.1')
            self.assertEqual(c.exception.code,42)
    def test_fuzz_build_compiles_the_uses_closure_and_glib_when_opted_in(self):
        p={'modules':[module('models'),module('batch',uses=['models'],foundation='glib-parallel'),
                      module('inproc',uses=['batch'],reads_external_input=True,fuzz=[{'name':'inproc','harness':'fuzz/project/h.c','corpus':'fuzz/project/c','regressions':'fuzz/project/r'}])]}
        argv,env=pc.fuzz_build_argv('examples/x',p['modules'][2]['fuzz'][0],p['modules'][2],p)
        self.assertIn('src/models.c',argv);self.assertIn('src/batch.c',argv);self.assertIn('src/inproc.c',argv)
        self.assertEqual(argv[argv.index('--glib')+1],'/opt/foundation/fuzz');self.assertEqual(env,{})
        self.assertEqual(argv[argv.index('--framework')+1:],['foundation/src/sc-foundation.c','foundation/parallel/sc-parallel.c'])
        argv2,env2=pc.fuzz_build_argv('examples/x',{'name':'m','harness':'fuzz/project/m.c','corpus':'fuzz/project/c','regressions':'fuzz/project/r'},p['modules'][0],p)
        self.assertEqual(env2,{});self.assertNotIn('--glib',argv2);self.assertNotIn('--framework',argv2)
    def test_strict_contraction_everywhere_project_code_compiles(self):
        self.assertIn('-ffp-contract=off',pc.FUZZ_ENV['CFLAGS'].split())
        self.assertIn('-ffp-contract=off',pc._ast_scan_flags('examples/x'))
        self.assertIn('-ffp-contract=off',pc.analyzer_argv('tidy','examples/x/src/a.c',0,'examples/x'))
        text=(ROOT/'cmake/Safety.cmake').read_text();self.assertIn('-ffp-contract=off',text)
    def test_project_cmake_links_libm_and_the_locked_foundation(self):
        text=(ROOT/'cmake/Project.cmake').read_text()
        self.assertIn('target_link_libraries("${library}" PUBLIC m)',text)
        self.assertIn('include("${PROJECT_SOURCE_DIR}/cmake/FoundationLibraries.cmake")',text)
        self.assertIn('glib-parallel',text)

if __name__=='__main__':unittest.main()
