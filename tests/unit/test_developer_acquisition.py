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


class NoticeRecordTests(unittest.TestCase):
    """Phase 1 approval finding P1-R1-01: every notice entry names an explicit owner, its declared license tags
    and an open review status (AGENTS.md: every dependency needs explicit owners and license review)."""
    def test_every_notice_entry_has_owner_license_tags_and_review_status(self):
        lock = json.loads((Path(__file__).resolve().parents[2] / 'developer.lock.json').read_text())
        for name, row in lock['notices'].items():
            with self.subTest(notice=name):
                self.assertTrue(isinstance(row.get('owner'), str) and row['owner'])
                self.assertTrue(isinstance(row.get('license_tags'), list) and row['license_tags'])
                self.assertTrue(all(isinstance(tag, str) and tag for tag in row['license_tags']))
                self.assertEqual(row.get('review_status'), 'PENDING')
        # The owner's license confirmation of the v3 image bundle (2026-10-15) covers this developer image, as in
        # ci/image-bundle.json. Each notice row keeps its own PENDING review status.
        self.assertEqual(lock['license_review'], 'OWNER_CONFIRMED_2026-10-15')
    def test_promote_keeps_notice_review_fields(self):
        import acquire_bench_wheels as a
        lock={'notices':{'numpy':{'path':'p','sha256':'0'*64,'owner':'o','license_tags':['BSD-3-Clause'],'review_status':'PENDING'}}}
        a._promote_notice(lock,'numpy','p2','1'*64)
        self.assertEqual(lock['notices']['numpy'],{'path':'p2','sha256':'1'*64,'owner':'o','license_tags':['BSD-3-Clause'],'review_status':'PENDING'})
    def test_new_notice_without_review_fields_is_refused(self):
        import acquire_bench_wheels as a
        with self.assertRaises(a.GateError):a._promote_notice({'notices':{}},'newwheel','p','0'*64)
    def test_changed_notice_text_resets_the_review_status(self):
        # T28-APP-02: a review status never carries over to notice text that nobody reviewed (sha256 changed -> PENDING)
        import acquire_bench_wheels as a
        old={'path':'p','sha256':'0'*64,'owner':'o','license_tags':['BSD-3-Clause'],'review_status':'APPROVED'}
        lock={'notices':{'numpy':dict(old)}};a._promote_notice(lock,'numpy','p2','1'*64)
        self.assertEqual(lock['notices']['numpy'],dict(old,path='p2',sha256='1'*64,review_status='PENDING'))
        lock={'notices':{'numpy':dict(old)}};a._promote_notice(lock,'numpy','p2','0'*64)
        self.assertEqual(lock['notices']['numpy'],dict(old,path='p2'))
    def test_a_refused_promotion_leaves_no_half_promoted_payload(self):
        # T28-APP-01: promote refuses a pinned notice whose lock entry lacks a review field before any file changes: the
        # payload directory, the notices and developer.lock.json stay byte-identical (temporary root only).
        import acquire_bench_wheels as a
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)/'root';ext=Path(t)/'extraction';payload=root/'third_party/developer/payload';payload.mkdir(parents=True);ext.mkdir()
            (payload/'development-layer-old.tar.gz').write_bytes(b'old archive');(payload/'manifest.json').write_text('{"old": true}')
            (ext/'development-layer-new.tar.gz').write_bytes(b'new archive');(ext/'manifest.json').write_text('{"new": true}')
            for name in ('numpy','psutil'):(ext/'notices'/name).mkdir(parents=True);(ext/'notices'/name/'LICENSE').write_text(name+' notice\n')
            for rel in ('recipe-e','recipe-a'):(root/rel).write_text(rel)
            sel=root/a.SELECTION;sel.parent.mkdir(parents=True);sel.write_text('{"wheels": []}')
            lock={'image_id':'sha256:old','inputs':[],'extraction_recipe':'recipe-e','assembly_recipe':'recipe-a','notices':{
                  'numpy':{'path':'n','sha256':'0'*64,'owner':'o','license_tags':['BSD-3-Clause'],'review_status':'PENDING'},
                  'psutil':{'path':'s','sha256':'0'*64,'owner':'o','license_tags':['BSD-3-Clause']}}}      # psutil lacks review_status
            (root/'developer.lock.json').write_text(json.dumps(lock))
            cand=Path(t)/'candidate.json'
            cand.write_text(json.dumps({'image_id':'sha256:new','payload':{'archives':[{'name':'development-layer-new.tar.gz','bytes':11,'files':1,'sha256':'1'*64}],
                                        'notices':{'numpy':{'path':'x/LICENSE'},'psutil':{'path':'y/LICENSE'}}}}))
            def tree():return {p.relative_to(root).as_posix():p.read_bytes() for p in sorted(root.rglob('*')) if p.is_file()}
            before=tree()
            with self.assertRaises(GateError):a.promote(root,cand,ext)
            self.assertEqual(tree(),before)
            self.assertFalse((root/'third_party/developer/notices').exists())


ROOT = Path(__file__).resolve().parents[2]


class DependencyOwnerTests(unittest.TestCase):
    """FR2-05: the dependency owner of the developer lock is the organization MarketData-App, never an account name."""
    def lock(self):
        return json.loads((ROOT / 'developer.lock.json').read_text())

    def test_the_lock_names_the_organization(self):
        lock = self.lock()
        self.assertEqual(lock['owner'], 'MarketData-App')
        for name, row in lock['notices'].items():
            with self.subTest(notice=name):
                self.assertRegex(row['owner'], r'^MarketData-App(?: |$)')
        for rel in ('developer.lock.json', 'specs/image-transfer.md', 'tools/assemble_developer_image.py'):
            with self.subTest(path=rel):
                self.assertNotIn('MarketDataApp', (ROOT / rel).read_text())
        self.assertIn("'owner': 'MarketData-App'", (ROOT / 'tools/assemble_developer_image.py').read_text())

    def test_the_schema_refuses_another_owner(self):
        from schema_check import validate
        lock = self.lock()
        validate(ROOT, 'developer-lock', lock)
        for owner in ('MarketDataApp', 'someone', ''):
            with self.subTest(owner=owner):
                with self.assertRaises(GateError):
                    validate(ROOT, 'developer-lock', dict(lock, owner=owner))
        name = sorted(lock['notices'])[0]
        notices = dict(lock['notices'], **{name: dict(lock['notices'][name], owner='MarketDataApp legal team')})
        with self.assertRaises(GateError):
            validate(ROOT, 'developer-lock', dict(lock, notices=notices))
        notices = dict(lock['notices'], **{name: {k: v for k, v in lock['notices'][name].items() if k != 'owner'}})
        with self.assertRaises(GateError):
            validate(ROOT, 'developer-lock', dict(lock, notices=notices))
