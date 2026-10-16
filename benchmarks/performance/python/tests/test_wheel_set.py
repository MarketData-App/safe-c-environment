"""FR4 (owner decision 2026-10-13; replaces the QuantLib presence test): the developer image holds exactly the framework
bench wheels numpy, pyperf and psutil at the locked versions, and no QuantLib, scipy or mpmath module is importable."""
import importlib.metadata, importlib.util, json, unittest
from pathlib import Path
ALLOWED={'numpy','pyperf','psutil'}
LOCKED=json.loads(Path('/src/developer.lock.json').read_text())['bench_python']

class WheelSetTests(unittest.TestCase):
    def test_the_image_holds_exactly_the_allowed_distributions(self):
        stems=[p.name.removesuffix('.dist-info').split('-',1) for p in Path('/opt/bench-python').glob('*.dist-info')]
        found={name.lower():version for name,version in stems}
        self.assertEqual(set(found),ALLOWED)
        self.assertEqual(found,{k.lower():v for k,v in LOCKED.items()})
        self.assertEqual(set(LOCKED),ALLOWED)
    def test_the_allowed_modules_import_at_the_locked_versions(self):
        for name in sorted(ALLOWED):
            with self.subTest(name=name):
                self.assertIsNotNone(importlib.util.find_spec(name))
                self.assertEqual(importlib.metadata.version(name),LOCKED[name])
    def test_no_removed_module_is_importable(self):
        for name in ('QuantLib','quantlib','scipy','mpmath'):
            with self.subTest(name=name):self.assertIsNone(importlib.util.find_spec(name))
        self.assertEqual([p.name for p in Path('/opt/bench-python').iterdir() if p.name.lower().startswith(('quantlib','scipy','mpmath'))],[])

if __name__=='__main__':unittest.main()
