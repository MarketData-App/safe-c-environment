"""Static checks that the project CMake helper cannot change compiler flags."""
from pathlib import Path
import importlib.util
import re
import sys
import unittest
ROOT=Path(__file__).resolve().parents[2]
FORBIDDEN=['CMAKE_C_FLAGS','CMAKE_EXE_LINKER_FLAGS','CMAKE_SHARED_LINKER_FLAGS','CMAKE_STATIC_LINKER_FLAGS',
           'add_compile_options','add_compile_definitions','add_definitions','add_link_options',
           'target_compile_options','target_compile_definitions','target_link_options','COMPILE_OPTIONS',
           'COMPILE_FLAGS','COMPILE_DEFINITIONS','LINK_OPTIONS','LINK_FLAGS','CMAKE_C_COMPILER','CMAKE_BUILD_TYPE',
           'SAFETY_PROFILE']

class ProjectCMakeTests(unittest.TestCase):
    def test_cmake_helper_has_no_flag_inputs(self):
        text=(ROOT/'cmake/Project.cmake').read_text()
        text=re.sub(r'(?m)#.*$','',text)
        self.assertIsNone(re.search(r'(?<![_a-z])link_libraries',text))
        for name in FORBIDDEN:self.assertNotIn(name,text,name)
        self.assertIn('safety_target',text)
        self.assertIn('safety_add_program',text)
        self.assertNotRegex(text,r'(?m)^\s*set_target_properties')
    def test_root_keeps_bootstrap_error_text(self):
        text=(ROOT/'CMakeLists.txt').read_text()
        self.assertIn('message(FATAL_ERROR "bootstrap contract forbids application sources; obtain approved production inventory")',text)
        self.assertLess(text.index('safety_project('),text.index('bootstrap contract forbids'))
        self.assertLess(text.index('return()'),text.index('bootstrap contract forbids'))
    def root_code(self):
        return re.sub(r'(?m)#.*$','',(ROOT/'CMakeLists.txt').read_text())
    def test_project_mode_only_with_explicit_project_dir(self):
        # project.json alone never switches a configure to project mode: a child's own
        # framework ci configures /src and must keep the qualification targets.
        text=self.root_code()
        branches=re.findall(r'(?m)^\s*if\((.*)\)\s*$',text[:text.index('safety_project(')])
        self.assertEqual(branches,['DEFINED SAFE_C_PROJECT_DIR'])
        project=text[text.index('if(DEFINED SAFE_C_PROJECT_DIR)'):text.index('return()')]
        self.assertNotIn('project.json',project)
        self.assertNotIn('set(SAFE_C_PROJECT_DIR',text)
        self.assertEqual(text.count('return()'),1)
        for line in ('include(cmake/Foundation.cmake)','include(cmake/Developer.cmake)','include(safety/targets.cmake)',
                     'safety_add_program(infrastructure_demo'):
            self.assertLess(text.index('return()'),text.index(line),line)
    def test_bootstrap_error_applies_only_without_project_json(self):
        text=self.root_code()
        guard='if(NOT EXISTS "${PROJECT_SOURCE_DIR}/project.json")'
        self.assertEqual(text.count(guard),1)
        start=text.index(guard);end=text.index('endif()',text.index('message(FATAL_ERROR "bootstrap'))
        end=text.index('endif()',end+len('endif()'))
        block=text[start:end]
        for line in ('file(GLOB_RECURSE app_sources','if(app_sources)','message(FATAL_ERROR "bootstrap contract forbids'):
            self.assertIn(line,block,line)
        self.assertEqual(text.count('GLOB_RECURSE app_sources'),1)
        self.assertLess(text.index('return()'),start)
    def code(self):
        return re.sub(r'(?m)#.*$','',(ROOT/'cmake/Project.cmake').read_text())
    def test_json_values_are_validated_and_quoted(self):
        text=self.code()
        for call in ('target_link_libraries','safety_add_program','add_test','add_library','safety_target',
                     'set_tests_properties','target_include_directories'):
            for line in re.findall(r'(?m)^\s*'+call+r'\(.*$',text):
                bare=re.sub(r'"[^"]*"','',line).replace('${run_args}','').replace('${sources}','')
                self.assertNotIn('${',bare,line)
        for target in ('module_name','program_name','run_program','module','base'):
            self.assertRegex(text,r'_project_name\('+target+r' "\$\{\w+\}"')
        for key in ('raw_name','raw_program','raw_run','raw_module'):
            self.assertIn('"${'+key+'}"',text)
        self.assertIn('if(NOT TARGET "project_${module}")',text)
        self.assertIn('must be an array',text)
        self.assertIn('FATAL_ERROR',text)
        self.assertRegex(text,r'\$<')
    def test_include_argument_rejections(self):
        sys.path.insert(0,str(ROOT/'tools'))
        spec=importlib.util.spec_from_file_location('foundation_policy',ROOT/'container/foundation-policy.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        parse=module.parse_arguments
        self.assertEqual(parse(['a.c','clang-O0','x'])[3],[])
        self.assertEqual(parse(['a.c','p','x','--include','/src/p/include'])[3],['-idirafter','/src/p/include'])
        for bad in (['--include','/etc'],['--include','/src/../etc'],['--include'],['--include','/srcx/a'],
                    ['--other','/src/a'],['/src/a']):
            with self.assertRaises(ValueError):parse(['a.c','p','x']+bad)
        with self.assertRaises(ValueError):parse(['a.c','p'])
    def test_project_rules_flag(self):
        sys.path.insert(0,str(ROOT/'tools'))
        spec=importlib.util.spec_from_file_location('foundation_policy',ROOT/'container/foundation-policy.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        parse=module.parse_arguments
        self.assertFalse(parse(['a.c','p','x','--include','/src/p/include'])[4])
        self.assertTrue(parse(['a.c','p','x','--include','/src/p/include','--project-rules'])[4])
        self.assertTrue(parse(['a.c','p','x','--project-rules','--include','/src/p/include'])[4])
        with self.assertRaises(ValueError):parse(['a.c','p','x','--project-rules','--project-rules'])
    def test_banned_attribute_nodes(self):
        sys.path.insert(0,str(ROOT/'tools'))
        from qualification import ast_banned_attributes,PROJECT_BANNED_ATTRIBUTES
        tree={'kind':'TranslationUnitDecl','inner':[
            {'kind':'FunctionDecl','name':'f','inner':[{'kind':'NakedAttr'},{'kind':'CompoundStmt','inner':[]}]},
            {'kind':'FunctionDecl','name':'g','inner':[{'kind':'OptimizeNoneAttr','implicit':True}]},
            {'kind':'FunctionDecl','name':'h','inner':[{'kind':'UnusedAttr'},{'kind':'NoStackProtectorAttr'}]}]}
        self.assertEqual(ast_banned_attributes(tree),['NakedAttr','NoStackProtectorAttr','OptimizeNoneAttr'])
        self.assertEqual(ast_banned_attributes({'kind':'TranslationUnitDecl','inner':[{'kind':'UnusedAttr'}]}),[])
        for kind in ('NoSanitizeAttr','DisableSanitizerInstrumentationAttr','NoInstrumentFunctionAttr','NoProfileFunctionAttr'):
            self.assertIn(kind,PROJECT_BANNED_ATTRIBUTES)
    def test_project_runtime_interface_and_builtin_rules(self):
        sys.path.insert(0,str(ROOT/'tools'))
        from qualification import ast_project_findings
        us='_'+'_'
        tree={'kind':'TranslationUnitDecl','inner':[
            {'kind':'FunctionDecl','name':us+'asan_default_options','inner':[]},
            {'kind':'FunctionDecl','name':us+'sanitizer_set_death_callback','inner':[{'kind':'WeakAttr'}]},
            {'kind':'FunctionDecl','name':'f','inner':[{'kind':'CompoundStmt','inner':[
                {'kind':'CallExpr','inner':[{'kind':'ImplicitCastExpr','inner':[
                    {'kind':'DeclRefExpr','referencedDecl':{'kind':'FunctionDecl','name':'__builtin_constant_p'}}]}]},
                {'kind':'CallExpr','inner':[{'kind':'DeclRefExpr','referencedDecl':{'name':us+'lsan_disable'}}]},
                {'kind':'DeclRefExpr','referencedDecl':{'name':us+'llvm_profile_runtime'}}]}]},
            {'kind':'VarDecl','name':us+'gcov_x'},
            {'kind':'FunctionDecl','name':'g','inner':[{'kind':'NakedAttr'}]}]}
        self.assertEqual(ast_project_findings(tree),[
            ('project-attribute','NakedAttr'),('project-builtin','__builtin_constant_p'),
            ('runtime-interface',us+'asan_default_options'),('runtime-interface',us+'gcov_x'),
            ('runtime-interface',us+'llvm_profile_runtime'),('runtime-interface',us+'lsan_disable'),
            ('runtime-interface',us+'sanitizer_set_death_callback')])
        self.assertEqual(ast_project_findings({'kind':'TranslationUnitDecl','inner':[{'kind':'FunctionDecl','name':'asan_like'}]}),[])
    def test_runtime_sanitizer_options_name_nonzero_exit_codes(self):
        sys.path.insert(0,str(ROOT/'tools'))
        from evidence import RUNTIME_ENV
        for name in ('ASAN_OPTIONS','UBSAN_OPTIONS','LSAN_OPTIONS','MSAN_OPTIONS','TSAN_OPTIONS'):
            options=dict(item.split('=',1) for item in RUNTIME_ENV[name].split(':'))
            self.assertNotEqual(int(options.get('exitcode','0')),0,name)
        self.assertIn('halt_on_error=1',RUNTIME_ENV['ASAN_OPTIONS'])
        self.assertIn('halt_on_error=1',RUNTIME_ENV['UBSAN_OPTIONS'])
    def test_project_targets_omit_framework_include_directories(self):
        safety=re.sub(r'(?m)#.*$','',(ROOT/'cmake/Safety.cmake').read_text())
        guarded=re.search(r'if\(NOT _SAFETY_PROJECT_TARGETS\)\s*target_include_directories\(\$\{target\} PRIVATE [^)]*/fuzz\)\s*endif\(\)',safety)
        self.assertIsNotNone(guarded)
        self.assertEqual(safety.count('target_include_directories'),1)
        project=self.code()
        body=project[project.index('function(safety_project'):]
        self.assertLess(body.index('set(_SAFETY_PROJECT_TARGETS ON)'),body.index('safety_target('))
        self.assertNotIn('_SAFETY_PROJECT_TARGETS',(ROOT/'CMakeLists.txt').read_text())
if __name__=='__main__':unittest.main()
