"""EX-1: the project image layer, tested inside the project bench image.

`./tools/safety bench selftest --suite unit --project tests/fixtures/wheel-project` runs this suite in the image that
tools/project_image.py builds from the qualified developer image plus one layer under /opt/project-python."""
import importlib.metadata
import sys
import unittest
from pathlib import Path

LAYER = Path('/opt/project-python')


class ProjectWheelTests(unittest.TestCase):
    def test_the_fixture_wheel_imports_from_the_project_layer(self):
        import scfixturewheel
        self.assertEqual(scfixturewheel.__version__, '1.0.0')
        self.assertEqual(scfixturewheel.answer(), 42)
        self.assertEqual(Path(scfixturewheel.__file__).resolve().parent.parent, LAYER)
        self.assertEqual(importlib.metadata.version('scfixturewheel'), '1.0.0')

    def test_the_layer_holds_exactly_the_declared_distribution(self):
        self.assertEqual(sorted(p.name for p in LAYER.iterdir()), ['scfixturewheel', 'scfixturewheel-1.0.0.dist-info'])
        names = sorted(d.metadata['Name'] for d in importlib.metadata.distributions(path=[str(LAYER)]))
        self.assertEqual(names, ['scfixturewheel'])
        self.assertTrue((LAYER / 'scfixturewheel-1.0.0.dist-info' / 'LICENSE').is_file())

    def test_the_framework_wheels_stay_first_on_the_path(self):
        import numpy
        self.assertTrue(numpy.__file__.startswith('/opt/bench-python/'))
        self.assertLess(sys.path.index('/opt/bench-python'), sys.path.index(str(LAYER)))

    def test_the_layer_is_read_only(self):
        with self.assertRaises(OSError):
            (LAYER / 'written-by-a-test').write_text('x')


if __name__ == '__main__':
    unittest.main()
