"""Static checks that the project CMake helper cannot change compiler flags."""
from pathlib import Path
import re
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
if __name__=='__main__':unittest.main()
