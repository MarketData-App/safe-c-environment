"""Payload boundary regression tests, executed only by the protected runner."""
from pathlib import Path
import hashlib
import io
import json
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from assemble_developer_image import unpack
from evidence import GateError


class DeveloperPayloadTests(unittest.TestCase):
    def fixture(self, directory, *, name='usr/bin/gdb', mode=0o555,
                link=False, duplicate=False, bad_hash=False, omitted=False):
        data = b'finite package data\n'
        archive = directory / 'development-layer-0.tar.gz'
        with tarfile.open(archive, 'w:gz') as target:
            for _ in range(2 if duplicate else 1):
                member = tarfile.TarInfo(name)
                member.mode = mode
                member.size = len(data)
                if link:
                    member.type = tarfile.SYMTYPE
                    member.linkname = 'gdb'
                    member.size = 0
                target.addfile(member, None if link else io.BytesIO(data))
        record = {'sha256': '0' * 64 if bad_hash else hashlib.sha256(data).hexdigest(),
                  'bytes': len(data), 'mode': mode, 'package': 'gdb'}
        manifest = {'status': 'CANDIDATE_DATA_EXTRACTED',
                    'package_scripts_executed': False,
                    'files': {name: record},
                    'archives': [{'name': archive.name, 'files': [] if omitted else [name],
                                  'bytes': archive.stat().st_size,
                                  'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}]}
        (directory / 'manifest.json').write_text(json.dumps(manifest))
        return data

    def rejected(self, **options):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root, **options)
            with self.assertRaises(GateError):
                unpack(root, root / 'layer')
            self.assertFalse((root / 'outside').exists())

    def test_regular_payload_roundtrip_preserves_bytes_and_mode(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected = self.fixture(root)
            unpack(root, root / 'layer')
            result = root / 'layer/usr/bin/gdb'
            self.assertEqual(result.read_bytes(), expected)
            self.assertEqual(result.stat().st_mode & 0o777, 0o555)

    def test_external_paths_and_unregistered_roots_are_rejected(self):
        for name in ['../outside', '/outside', 'opt/unregistered']:
            self.rejected(name=name)

    def test_duplicate_link_and_set_id_members_are_rejected(self):
        self.rejected(duplicate=True)
        self.rejected(link=True)
        self.rejected(mode=0o4555)

    def test_member_identity_and_exact_chunk_inventory_are_required(self):
        self.rejected(bad_hash=True)
        self.rejected(omitted=True)

    def test_retained_archive_tampering_is_rejected_before_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            archive = root / 'development-layer-0.tar.gz'
            archive.write_bytes(archive.read_bytes() + b'changed')
            with self.assertRaises(GateError):
                unpack(root, root / 'layer')
            self.assertFalse((root / 'layer').exists())
