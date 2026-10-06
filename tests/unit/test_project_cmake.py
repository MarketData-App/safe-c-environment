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
if __name__=='__main__':unittest.main()
