import ast, re, sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
# Review Minor 1: every framework Python file, the tools/safety script and every framework unit test (this file excepted).
FRAMEWORK=[*ROOT.glob('tools/*.py'),ROOT/'tools/safety',*ROOT.glob('container/*.py'),*ROOT.glob('benchmarks/performance/python/benchlab/*.py'),
           *ROOT.glob('benchmarks/performance/python/tests/*.py'),*[p for p in ROOT.glob('tests/unit/*.py') if p.name!=Path(__file__).name]]
NAMES=re.compile(r'\boptionlab\b|option-pricing-benchmark|\boption-chain-greeks\b')
# The only framework strings that may name the example: assertions that the framework refuses or no longer reserves it.
# FR3: the local-aggregate case enum left the protected schema (the case is project data), so its entry is gone.
ALLOWED={('tests/unit/test_bench_cli.py','optionlab'),('tests/unit/test_bench_project.py','optionlab'),
         ('tests/unit/test_bench_framework_neutral.py','option[-_]chain|optionlab|ocg-v1m')}     # FR3: the scan pattern that refuses the names

def findings(path,text):
    bad=[];rel=path.relative_to(ROOT).as_posix()
    for node in ast.walk(ast.parse(text,str(path))):
        names=[a.name for a in node.names] if isinstance(node,ast.Import) else [node.module or ''] if isinstance(node,ast.ImportFrom) else []
        bad+=[f'{rel}: import {n}' for n in names if n.split('.')[0]=='optionlab']
        if isinstance(node,ast.Constant) and isinstance(node.value,str) and NAMES.search(node.value) and (rel,node.value) not in ALLOWED:
            bad.append(f'{rel}: string names the example')
    return bad

class FrameworkImportTests(unittest.TestCase):
    """Amendment A: the framework uses a project workload only through the registered-workload interface."""
    def test_no_tool_or_market_test_is_allowlisted(self):
        """Task 18a review Important 1: no tool file may name the example (FR3: the market test left with the example)."""
        self.assertEqual([a for a in ALLOWED if a[0].startswith('tools/') or a[0]=='tests/unit/test_bench_market.py'],[])
    def test_no_framework_file_imports_a_project_workload(self):
        self.assertTrue((ROOT/'tools/safety').is_file())
        bad=[]
        for path in FRAMEWORK:bad+=findings(path,path.read_text())
        self.assertEqual(bad,[])
    def test_dynamic_and_argv_names_are_found(self):
        for code in ("import importlib\nimportlib.import_module('optionlab')\n","__import__('optionlab')\n","argv=['-m','optionlab.checks']\n",
                     "p='examples/option-pricing-benchmark'\n","case='option-chain-greeks'\n","from optionlab import x\n","import optionlab.params\n"):
            with self.subTest(code=code):self.assertTrue(findings(ROOT/'tools/probe.py',code))
        self.assertEqual(findings(ROOT/'tools/probe.py',"import benchlab\nx='optionlabel'\n"),[])
    def test_framework_package_exists_and_optionlab_left_the_framework(self):
        self.assertTrue((ROOT/'benchmarks/performance/python/benchlab/markers.py').is_file())
        self.assertFalse((ROOT/'benchmarks/performance/python/optionlab').exists())
