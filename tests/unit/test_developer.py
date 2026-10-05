"""Developer metadata boundaries; native execution uses the protected runner."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from evidence import read_json, GateError
from schema_check import validate
from developer import admission
from developer_lsp import position, scalar_position, uri
import tempfile

ROOT = Path(__file__).resolve().parents[2]


class DeveloperInputTests(unittest.TestCase):
    def test_pinned_debian_version_paths_are_accepted(self):
        lock = read_json(ROOT / 'developer.lock.json')
        self.assertTrue(any('~' in row['path'] for row in lock['inputs']))
        validate(ROOT, 'developer-lock', lock)

    def test_admission_rejects_same_worktree_profile_and_releases(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            with admission(root,'debug'):
                with self.assertRaises(GateError):
                    with admission(root,'debug'):
                        self.fail('duplicate worktree/profile admitted')
                with admission(root,'clang-O0'):
                    pass
            with admission(root,'debug'):
                pass

    def test_unicode_positions_roundtrip_and_reject_split_scalars(self):
        text='/* café 😀 */ symbol\r\nnext'
        column=text.split('\r\n')[0].index('symbol')+1
        self.assertEqual(position(text,1,column,'utf-8')['character'],17)
        self.assertEqual(position(text,1,column,'utf-16')['character'],14)
        self.assertEqual(position(text,1,column,'utf-32')['character'],13)
        for encoding in ['utf-8','utf-16','utf-32']:
            self.assertEqual(scalar_position(text,position(text,1,column,encoding),encoding),
                             {'line':1,'column':column})
        for line,col in [(0,1),(1,0),(-1,1),(2147483647,1),(1,2147483647)]:
            with self.assertRaises(GateError):position(text,line,col,'utf-8')
        with self.assertRaises(GateError):scalar_position(text,{'line':0,'character':9},'utf-16')
        self.assertIn('%20',uri(Path('/src/path with space/µ.c')))
        self.assertIn('%C2%B5',uri(Path('/src/path with space/µ.c')))
