import os, unittest
from benchlab.markers import Marker
class MarkerTests(unittest.TestCase):
    def test_marker_is_inactive_without_the_environment_name(self):
        os.environ.pop('SAFE_C_BENCH_MARKER',None);self.assertIsNone(Marker().sock)
