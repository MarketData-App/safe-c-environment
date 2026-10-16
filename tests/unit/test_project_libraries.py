import json, sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from evidence import GateError
import project_model as pm, project_check as pc
SCHEMA=json.loads((ROOT/'schemas/project.json').read_text())
FUZZ=[{'name':'inproc','harness':'fuzz/project/h.c','corpus':'fuzz/project/c','regressions':'fuzz/project/r'}]
def mod(name,**k):return dict({'name':name,'spec':'specs/project/x.md','sources':[f'src/{name}.c'],'headers':[],'tests':[f'tests/project/t_{name}.c'],'reads_external_input':False,'fuzz':[]},**k)
DYN='''Symbol table '.dynsym' contains 6 entries:
   Num:    Value          Size Type    Bind   Vis      Ndx Name
     1: 0000000000000000     0 FUNC    GLOBAL DEFAULT  UND exp@GLIBC_2.29 (2)
     2: 0000000000001130    40 FUNC    GLOBAL DEFAULT   12 demo_inproc_abi_version@@DEMO_INPROC
     3: 0000000000001160   900 FUNC    GLOBAL DEFAULT   12 demo_inproc_run
'''

ELF_HEADER='''ELF Header:
  Class:                             ELF64
  Type:                              DYN (Shared object file)
'''
ELF_SEGMENTS='''Program Headers:
  Type           Offset   VirtAddr           PhysAddr           FileSiz  MemSiz   Flg Align
  LOAD           0x000000 0x0000000000000000 0x0000000000000000 0x000520 0x000520 R   0x1000
  GNU_RELRO      0x002df0 0x0000000000003df0 0x0000000000003df0 0x000210 0x000210 R   0x1
  GNU_STACK      0x000000 0x0000000000000000 0x0000000000000000 0x000000 0x000000 RW  0x10
'''
ELF_DYNAMIC='''Dynamic section at offset 0x2e00 contains 20 entries:
  Tag        Type                         Name/Value
 0x0000000000000001 (NEEDED)             Shared library: [libm.so.6]
 0x000000000000001e (FLAGS)              BIND_NOW
 0x000000006ffffffb (FLAGS_1)            Flags: NOW
'''

class LibraryTests(unittest.TestCase):
    def test_schema_is_closed(self):
        lib=SCHEMA['properties']['libraries']
        self.assertEqual(lib['maxItems'],2);self.assertFalse(lib['items']['additionalProperties'])
        self.assertEqual(sorted(lib['items']['required']),['exports','modules','name'])
    def test_inventory_rules(self):
        good={'modules':[mod('batch'),mod('inproc',uses=['batch'],reads_external_input=True,fuzz=FUZZ)],
              'libraries':[{'name':'demo_inproc','modules':['inproc'],'exports':['demo_inproc_run']}]}
        pm.check_libraries(good)
        bad=json.loads(json.dumps(good));bad['libraries'][0]['modules']=['nope']
        with self.assertRaisesRegex(GateError,'unknown module'):pm.check_libraries(bad)
        bad=json.loads(json.dumps(good));bad['modules'][1]['fuzz']=[]
        with self.assertRaisesRegex(GateError,'fuzz target'):pm.check_libraries(bad)
    def test_exports_check(self):
        self.assertEqual(pc.library_exports_ok(DYN,['demo_inproc_abi_version','demo_inproc_run']),[])
        self.assertTrue(pc.library_exports_ok(DYN,['demo_inproc_run']))                                   # an extra export
        self.assertTrue(pc.library_exports_ok(DYN,['demo_inproc_run','demo_inproc_abi_version','demo_x']))     # a missing export
        weak=DYN+'     5: 0000000000004010     8 OBJECT  WEAK   DEFAULT   22 demo_table\n'
        self.assertIn('unexpected export: demo_table',pc.library_exports_ok(weak,['demo_inproc_abi_version','demo_inproc_run']))   # WEAK and OBJECT count
        py=DYN+'     4: 0000000000000000     0 FUNC    GLOBAL DEFAULT  UND PyErr_SetString\n'
        self.assertIn('Python API',' '.join(pc.library_exports_ok(py,['demo_inproc_abi_version','demo_inproc_run'])))
    def test_cmake_builds_a_hidden_versioned_shared_library(self):
        # The flags live in the framework helper safety_shared_library (cmake/Safety.cmake):
        # test_project_cmake forbids flag and property commands in cmake/Project.cmake.
        text=(ROOT/'cmake/Project.cmake').read_text()
        for needle in ('SHARED','WHOLE_ARCHIVE','safety_position_independent(','safety_shared_library(','cmake/empty.c'):self.assertIn(needle,text)
        safety=(ROOT/'cmake/Safety.cmake').read_text()
        helper=safety[safety.index('function(safety_position_independent'):safety.index('function(safety_add_program')]
        for needle in ('C_VISIBILITY_PRESET hidden','POSITION_INDEPENDENT_CODE ON','PRIVATE -fPIC','--version-script=','-Wl,-z,text',
                       '-Wl,-z,defs','^(ordinary|strict|hardened)$','safety_position_independent(${target})'):
            self.assertIn(needle,helper)
    def test_target_name_and_output_file_name(self):
        # Target project-library-<name> (never a module target or a link name such as m); the
        # file stays lib<name>.so in the build directory root (OUTPUT_NAME <name>).
        text=(ROOT/'cmake/Project.cmake').read_text()
        self.assertIn('set(target "project-library-${library_name}")',text)
        self.assertIn('add_library("${target}" SHARED',text)
        self.assertIn('safety_shared_library("${target}" "${library_name}" "${map}")',text)
        safety=(ROOT/'cmake/Safety.cmake').read_text()
        helper=safety[safety.index('function(safety_shared_library'):safety.index('function(safety_add_program')]
        self.assertIn('function(safety_shared_library target output_name map)',helper)
        self.assertIn('OUTPUT_NAME "${output_name}" LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}"',helper)
        self.assertNotIn('PREFIX',helper);self.assertNotIn('SUFFIX',helper)
    def test_schema_requires_at_least_one_library_when_present(self):
        self.assertEqual(SCHEMA['properties']['libraries']['minItems'],1)
    def test_exports_check_counts_unique_notype_tls_and_ifunc(self):
        ok=['demo_inproc_abi_version','demo_inproc_run']
        for kind,bind in (('OBJECT','UNIQUE'),('NOTYPE','GLOBAL'),('TLS','GLOBAL'),('IFUNC','GLOBAL'),('NOTYPE','WEAK')):
            row=DYN+f'     5: 0000000000004010     8 {kind:7} {bind:6} DEFAULT   22 demo_extra\n'
            self.assertEqual(pc.library_exports_ok(row,ok),['unexpected export: demo_extra'],(kind,bind))
        und=DYN+'     5: 0000000000000000     0 NOTYPE  WEAK   DEFAULT  UND __gmon_start__\n'
        self.assertEqual(pc.library_exports_ok(und,ok),[])
        pyund=DYN+'     5: 0000000000000000     0 NOTYPE  GLOBAL DEFAULT  UND _Py_NoneStruct\n'
        self.assertIn('undefined Python API symbol: _Py_NoneStruct',pc.library_exports_ok(pyund,ok))
        self.assertEqual(pc.library_exports_ok(DYN.replace('demo_inproc_run','demo_inproc_run@@V1'),ok),[])
    def test_library_elf_hardening(self):
        good=(ELF_HEADER+ELF_SEGMENTS+ELF_DYNAMIC)
        self.assertEqual(pc.library_elf_hardened(good),(True,{'shared_object':True,'relro':True,'bind_now':True,
                         'non_executable_stack':True,'no_text_relocation':True,'failed':[]}))
        self.assertTrue(pc.library_elf_hardened(good.replace(' (FLAGS)              BIND_NOW\n',''))[0])     # FLAGS_1 NOW alone
        cases={'shared_object':good.replace('DYN (Shared object file)','EXEC (Executable file)'),
               'relro':good.replace('  GNU_RELRO','  LOAD     '),
               'bind_now':good.replace(' (FLAGS)              BIND_NOW\n','').replace('Flags: NOW','Flags: NODELETE'),
               'non_executable_stack':good.replace(' RW  0x10',' RWE 0x10'),
               'no_text_relocation':good+' 0x0000000000000016 (TEXTREL)            0x0\n'}
        for name,text in cases.items():
            ok,details=pc.library_elf_hardened(text)
            self.assertFalse(ok,name);self.assertEqual(details['failed'],[name],name)
        ok,details=pc.library_elf_hardened(good.replace('(FLAGS)              BIND_NOW','(FLAGS)              TEXTREL BIND_NOW'))
        self.assertEqual(details['failed'],['no_text_relocation'])
        self.assertEqual(pc.library_elf_hardened('')[1]['failed'],['shared_object','relro','bind_now','non_executable_stack'])
    def test_library_objects_must_be_pic_last(self):
        row=lambda f,flags:{'file':'/src/'+f,'arguments':['clang','-std=c17',*flags,'-c','/src/'+f]}
        units=['examples/x/src/a.c','cmake/empty.c']
        good=[row('examples/x/src/a.c',['-fPIC','-fPIE','-fPIC']),row('cmake/empty.c',['-fPIC']),row('examples/x/src/main.c',['-fPIE'])]
        self.assertEqual(pc.library_pic_problems(good,units),[])
        self.assertEqual(pc.library_pic_problems([{'file':'/src/cmake/empty.c','command':'clang -fPIC -fPIE -c x'},good[0]],units),
                         ['library object is not compiled with -fPIC last: cmake/empty.c'])
        self.assertEqual(pc.library_pic_problems([good[0]],units),['library object missing from compilation database: cmake/empty.c'])
        self.assertEqual(pc.library_pic_problems([row('cmake/empty.c',[]),good[0]],units),['library object is not compiled with -fPIC last: cmake/empty.c'])
        self.assertEqual(pc.library_pic_problems([row('cmake/empty.c',['-fpic']),good[0]],units),['library object is not compiled with -fPIC last: cmake/empty.c'])
    def test_library_sources(self):
        p=self._good()
        self.assertEqual(pc.library_sources('examples/x',p),['examples/x/src/batch.c','examples/x/src/inproc.c','cmake/empty.c'])
        p['modules'][0]['foundation']='glib-parallel'
        self.assertEqual(pc.library_sources('examples/x',p),['examples/x/src/batch.c','examples/x/src/inproc.c',
                         'foundation/src/sc-foundation.c','foundation/parallel/sc-parallel.c','cmake/empty.c'])
        self.assertEqual(pc.library_sources('examples/x',{'modules':[mod('a')]}),[])

    # Additions beyond the brief's minimum: the remaining inventory errors, the closure and fuzz hooks.
    def _good(self):
        return {'modules':[mod('batch'),mod('inproc',uses=['batch'],reads_external_input=True,fuzz=FUZZ)],
                'programs':[{'name':'demo-kernel','main':'src/main.c','modules':['batch']}],
                'libraries':[{'name':'demo_inproc','modules':['inproc'],'exports':['demo_inproc_run']}]}
    def test_export_must_be_a_valid_c_name(self):
        for word in ('int','return','static','bool','typeof'):
            bad=self._good();bad['libraries'][0]['exports']=['demo_inproc_run',word]
            with self.assertRaisesRegex(GateError,'library export is not a valid C name'):pm.check_libraries(bad)
        bad=self._good();bad['libraries'][0]['exports']=['Pl_x']
        with self.assertRaisesRegex(GateError,'library export is not a valid C name'):pm.check_libraries(bad)
    def test_library_names_are_unique_and_not_program_names(self):
        bad=self._good();bad['libraries'].append(dict(bad['libraries'][0]))
        with self.assertRaisesRegex(GateError,'library name'):pm.check_libraries(bad)
        bad=self._good();bad['programs'][0]['name']='demo_inproc'
        with self.assertRaisesRegex(GateError,'library name'):pm.check_libraries(bad)
        bad=self._good();bad['libraries'][0]['modules']=['inproc','inproc']
        with self.assertRaisesRegex(GateError,'twice'):pm.check_libraries(bad)
        pm.check_libraries({'modules':[mod('a')],'programs':[]})                                          # no libraries: nothing to check
    def test_library_closure_includes_the_uses_closure(self):
        p=self._good()
        self.assertEqual(pm.library_closure(p,p['libraries'][0]),['batch','inproc'])
    def test_closure_script_skips_the_interpreter_only_for_a_library(self):
        self.assertIn("sys.argv[3]=='library'",pc._CLOSURE)
    def test_fuzz_library_build_argv(self):
        p=self._good();p['modules'][0]['foundation']='glib-parallel'
        p['libraries'][0]['exports']=['demo_inproc_abi_version','demo_inproc_run']
        argv=pc.fuzz_library_argv('examples/x',p['libraries'][0],p)
        self.assertEqual(argv[:7],['bash','/src/container/project-fuzz-build.sh','--library','examples/x','demo_inproc',
                                   'demo_inproc_abi_version,demo_inproc_run','src/batch.c'])
        self.assertEqual(argv[7],'src/inproc.c')
        self.assertEqual(argv[argv.index('--glib')+1],'/opt/foundation/fuzz')
        p['modules'][0].pop('foundation')
        self.assertNotIn('--glib',pc.fuzz_library_argv('examples/x',p['libraries'][0],p))

if __name__=='__main__':unittest.main()
