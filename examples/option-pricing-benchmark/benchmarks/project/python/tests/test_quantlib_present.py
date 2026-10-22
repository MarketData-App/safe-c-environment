"""FR4 moved test (ruling R15; FR4-REPORT section 4): benchmarks/performance/python/tests/test_quantlib_present.py of the
framework before FR4 (d1101c6^). The framework image no longer holds QuantLib; this project pins the QuantLib wheel in its
third-party lock (benchmarks/project/third_party/lock.json, wheel row quantlib), and the project bench image holds it under
/opt/project-python. So the locked version now comes from that lock row; the assertion is the same. Added: the module is the
one of the project layer."""
import json, unittest
from pathlib import Path

LOCK=json.loads((Path(__file__).resolve().parents[2]/'third_party/lock.json').read_text())
QL_VERSION=next(w['version'] for w in LOCK['wheels'] if w['name']=='quantlib')

class QuantLibPresentTests(unittest.TestCase):
    def test_pinned_quantlib_imports_at_the_locked_version(self):
        import QuantLib as ql
        self.assertEqual(ql.__version__,QL_VERSION)
        self.assertEqual(QL_VERSION,'1.43')
        self.assertTrue(ql.__file__.startswith('/opt/project-python/QuantLib/'),ql.__file__)

if __name__=='__main__':
    unittest.main()
