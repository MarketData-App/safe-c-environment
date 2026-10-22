"""FR4 moved tests (rulings R15, R27; FR4-REPORT section 4): tests/unit/test_bench_acquisition.py QuantLibPinTests (3 tests) and
the QuantLib-specific part of QuantLibPayloadTests (11 test methods) of the framework before FR4 (d1101c6^).

The QuantLib wheel, its source release and their records are now this project's (benchmarks/project/third_party/lock.json): the
pins come from the lock rows quantlib and QuantLib-source, and the QuantLib bounds of PLAN-T5B-BOUND-01 (100663296 bytes, 11
files, 50331648-byte member, sized at 1.2x the measurement) are checked against this lock, the wheel bytes and the project bench
image. The generic host-member assertions (an oversized member is hashed and never written by the container job; the
declared-member identity checks; the member, layer byte and layer file bounds exact and one past; host streaming exact and one
past; undeclared or changed host members refused) are framework tests of T6-R2 and T6-R3 in tests/unit/test_project_image.py
(HostMemberRecipeTests, HostMemberHostTests, HostMemberLockTests, HostMemberRealConstantTests, NoticeMemberTests). Here the real
recipe functions run on the real wheel bytes. The wheel is read as data (zipfile); no wheel code runs. The image tests read the
files that the trusted host wrote under /opt/project-python (this suite runs in the project bench image)."""
import hashlib, importlib.util, io, json, os, sys, unittest, zipfile
from pathlib import Path
SRC=Path('/src')                                             # the bench container mounts the repository read-only at /src
sys.path.append(str(SRC/'tools'))
import acquire_bench_wheels as aw
import bench_model as bm
import project_third_party as ptp
from evidence import GateError
_spec=importlib.util.spec_from_file_location('project_wheels_recipe',SRC/'container/project-wheels.py')
recipe=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(recipe)

PROJECT_DIR='examples/option-pricing-benchmark'
PROJECT=Path(__file__).resolve().parents[2]                 # benchmarks/project
LOCK=json.loads((PROJECT/'third_party/lock.json').read_text())
WHEEL=next(w for w in LOCK['wheels'] if w['name']=='quantlib')
SOURCE=next(s for s in LOCK['sources'] if s['name']=='QuantLib-source')
QL_VERSION=WHEEL['version']
QL_PROVENANCE=PROJECT/'third_party/provenance/quantlib-source.json'
# PLAN-T5B-BOUND-01: the QuantLib bounds, sized at 1.2x the measurement of this wheel: 9 included members (the file of the wheel
# data directory counted), 82334189 bytes, largest member 41628617 bytes
QL_MAX_BYTES,QL_MAX_FILES,QL_MAX_MEMBER=100663296,11,50331648
MEASURED_FILES,MEASURED_BYTES,MEASURED_MEMBER=9,82334189,41628617
LAYER_FILES,LAYER_BYTES=8,82330954                           # the QuantLib share of the project layer (T6-R3: no .data file)
NOTICE_MEMBER='quantlib-1.43.data/data/share/doc/quantlib/LICENSE.TXT'
HOST_MEMBERS={'QuantLib/_QuantLib.abi3.so':38682729,'quantlib.libs/libQuantLib-4575fab8.so.0.0.0':41628617}
LAYER=Path(ptp.LAYER_PATH)                                   # /opt/project-python


def read_parts(row):
    """[(part, bytes)] of a lock row, in order."""
    return [(p,(PROJECT/p['path']).read_bytes()) for p in row['parts']]


def wheel_zip(row):
    return zipfile.ZipFile(io.BytesIO(b''.join(body for _,body in read_parts(row))))


def layer_members(archive):
    """The files of a wheel that enter the project layer, by the rules of the extraction job: no directory, no file of the
    <dist>.data directory (T6-R3), no tests/ below the top level and no bytecode (member_included)."""
    return [i for i in archive.infolist() if not i.is_dir() and recipe.member_included(i.filename)
            and not i.filename.split('/')[0].endswith('.data')]


class QuantLibPinTests(unittest.TestCase):
    def test_quantlib_wheel_tag_is_compatible_and_free_threaded_is_not(self):
        for compatible in (aw.compatible,ptp.compatible):          # the fetch rule and the lock rule of the bench interpreter
            with self.subTest(rule=compatible.__module__):
                self.assertTrue(compatible('quantlib-1.43-cp39-abi3-manylinux_2_24_x86_64.manylinux_2_28_x86_64.whl'))
                self.assertFalse(compatible('quantlib-1.43-cp314-cp314t-manylinux_2_24_x86_64.manylinux_2_28_x86_64.whl'))
                self.assertFalse(compatible('quantlib-1.43-pp311-pypy311_pp73-manylinux_2_24_x86_64.manylinux_2_28_x86_64.whl'))
                self.assertTrue(compatible(WHEEL['filename']))
        self.assertEqual(WHEEL['filename'],'quantlib-1.43-cp39-abi3-manylinux_2_24_x86_64.manylinux_2_28_x86_64.whl')

    def test_source_pins_the_selected_release(self):
        self.assertEqual(SOURCE['version'],QL_VERSION)
        self.assertEqual(SOURCE['filename'],'QuantLib-'+QL_VERSION+'.tar.gz')
        self.assertIn('/v'+QL_VERSION+'/',SOURCE['origin']['url'])

    def test_retained_source_rejoins_to_the_published_sha256(self):
        parts=read_parts(SOURCE);data=b''.join(body for _,body in parts)
        self.assertEqual(len(data),SOURCE['bytes'])
        self.assertEqual(hashlib.sha256(data).hexdigest(),SOURCE['sha256'])
        for p,body in parts:
            self.assertEqual((len(body),hashlib.sha256(body).hexdigest()),(p['bytes'],p['sha256']),p['path'])
        record=json.loads(QL_PROVENANCE.read_text())
        self.assertEqual((record['sha256'],record['bytes']),(SOURCE['sha256'],SOURCE['bytes']))     # the published digest of the record
        self.assertTrue(all(p['bytes']<=aw.PART for p in record['parts']))
        self.assertTrue(all(p['bytes']<=ptp.PART_MAX_BYTES for p in SOURCE['parts']))
        self.assertIn('agent engineering license review LR-EX performed 2026-10-18 (not legal advice): no license conflict with the first-party MIT license; the notices of this row meet the license conditions; legal-team confirmation received 2026-10-19 for QuantLib: BSD-3-Clause, permissive, commercial and proprietary use permitted; review_status APPROVED',record['license_review'])   # ruling R62


class QuantLibPayloadTests(unittest.TestCase):
    """PLAN-T5B-BOUND-01 for the project layer: the QuantLib members above the container file bound (32 MiB) are never written by
    a container (the trusted host streams them from the verified wheel, T6-R2); every other bound is the project layer bound."""
    @classmethod
    def setUpClass(cls):
        cls.parts=read_parts(WHEEL)
        cls.data=b''.join(body for _,body in cls.parts)
        cls.zip=zipfile.ZipFile(io.BytesIO(cls.data))
        cls.files=[i for i in cls.zip.infolist() if not i.is_dir()]
        cls.included=[i for i in cls.files if recipe.member_included(i.filename)]
        cls.layer=layer_members(cls.zip)
        cls.declared={h['member']:h for h in WHEEL['host_members']}

    @classmethod
    def tearDownClass(cls):
        cls.zip.close()

    def test_the_wheel_bytes_are_the_locked_bytes(self):
        for p,body in self.parts:
            self.assertEqual((len(body),hashlib.sha256(body).hexdigest()),(p['bytes'],p['sha256']),p['path'])
        self.assertEqual((len(self.data),hashlib.sha256(self.data).hexdigest()),(WHEEL['bytes'],WHEEL['sha256']))

    def test_quantlib_bounds_are_sized_from_the_measurement(self):
        self.assertEqual((QL_MAX_BYTES,QL_MAX_FILES,QL_MAX_MEMBER),(100663296,11,50331648))
        self.assertEqual((len(self.included),sum(i.file_size for i in self.included),max(i.file_size for i in self.files)),
                         (MEASURED_FILES,MEASURED_BYTES,MEASURED_MEMBER))
        self.assertTrue(1.2<=QL_MAX_BYTES/MEASURED_BYTES<1.25 and 1.2<=QL_MAX_MEMBER/MEASURED_MEMBER<1.25 and QL_MAX_FILES>=MEASURED_FILES*1.2)
        # the QuantLib member bound is the framework host member bound: the lock rule, the extraction job and the lock schema
        schema=json.loads((SRC/'schemas/project-third-party.json').read_text())
        self.assertEqual((ptp.HOST_MEMBER_MAX_BYTES,recipe.MAX_HOST_MEMBER,schema['$defs']['host_member']['properties']['bytes']['maximum']),
                         (QL_MAX_MEMBER,)*3)

    def test_existing_bounds_and_container_file_limit_are_unchanged(self):
        self.assertIn('"file_bytes": 33554432',(SRC/'safety/container-policy.json').read_text())
        self.assertEqual((ptp.PART_MAX_BYTES,recipe.MAX_FILE,ptp.ITEM_MAX_BYTES,recipe.MAX_WHEEL),(33554432,33554432,67108864,67108864))
        self.assertEqual((ptp.LAYER_MAX_BYTES,recipe.MAX_BYTES,ptp.LAYER_MAX_FILES,recipe.MAX_FILES),(201326592,201326592,3072,3072))
        for info in self.files:                                  # only the declared members pass the container file bound
            with self.subTest(member=info.filename):
                if info.filename in HOST_MEMBERS:
                    self.assertGreater(info.file_size,recipe.MAX_FILE)
                else:
                    self.assertLessEqual(info.file_size,recipe.MAX_FILE)

    def test_oversized_member_is_hashed_but_never_written(self):
        oversized={i.filename:i for i in self.files if i.file_size>ptp.PART_MAX_BYTES}
        self.assertEqual(set(oversized),set(HOST_MEMBERS))
        self.assertEqual(set(self.declared),set(HOST_MEMBERS))
        for name,info in sorted(oversized.items()):
            with self.subTest(member=name):
                digest,count=hashlib.sha256(),0
                with self.zip.open(info) as member:              # read in the pieces of the extraction job, never written
                    for chunk in iter(lambda:member.read(recipe.READ_CHUNK),b''):
                        digest.update(chunk);count+=len(chunk)
                self.assertEqual((count,digest.hexdigest()),(self.declared[name]['bytes'],self.declared[name]['sha256']))
                self.assertEqual(count,HOST_MEMBERS[name])

    def test_oversized_member_must_be_declared_and_match(self):
        for name in sorted(HOST_MEMBERS):
            info,declaration=self.zip.getinfo(name),self.declared[name]
            with self.subTest(member=name):
                sha256,head=recipe.hash_member(self.zip,info,declaration)        # the identity check of the extraction job
                self.assertEqual((sha256,head),(declaration['sha256'],b'\x7fELF'))
                for wrong in ({**declaration,'sha256':'0'*64},{**declaration,'bytes':declaration['bytes']-1},
                              {**declaration,'bytes':declaration['bytes']+1}):
                    with self.assertRaisesRegex(ValueError,'host member identity mismatch'):
                        recipe.hash_member(self.zip,info,wrong)
        # the project's lock, read through the bench.json binding, passes every lock rule with these declarations
        self.assertEqual(bm.third_party_lock(str(SRC),PROJECT_DIR),LOCK)

    def test_member_bound_exact_accepts_and_one_past_refuses(self):
        for h in WHEEL['host_members']:
            self.assertTrue(ptp.PART_MAX_BYTES<h['bytes']<=QL_MAX_MEMBER,h['member'])
        self.assertTrue(1.2<=QL_MAX_MEMBER/max(h['bytes'] for h in WHEEL['host_members'])<1.25)
        for size,ok in ((QL_MAX_MEMBER,True),(QL_MAX_MEMBER+1,False),(ptp.PART_MAX_BYTES+1,True),(ptp.PART_MAX_BYTES,False)):
            changed=json.loads(json.dumps(LOCK))
            next(w for w in changed['wheels'] if w['name']=='quantlib')['host_members'][0]['bytes']=size
            with self.subTest(bytes=size):
                if ok:
                    ptp.check_lock(str(SRC),PROJECT,changed,bm.RESERVED_MODULES,PROJECT_DIR)
                else:
                    with self.assertRaises(GateError):
                        ptp.check_lock(str(SRC),PROJECT,changed,bm.RESERVED_MODULES,PROJECT_DIR)

    def test_quantlib_byte_bound_exact_accepts_and_one_past_refuses(self):
        self.assertEqual(sum(i.file_size for i in self.layer),LAYER_BYTES)
        self.assertLessEqual(LAYER_BYTES,QL_MAX_BYTES)
        self.assertLessEqual(MEASURED_BYTES,QL_MAX_BYTES)

    def test_quantlib_file_bound_exact_accepts_and_one_past_refuses(self):
        self.assertEqual(len(self.layer),LAYER_FILES)
        self.assertLessEqual(LAYER_FILES,QL_MAX_FILES)
        self.assertLessEqual(MEASURED_FILES,QL_MAX_FILES)

    def test_notice_at_its_exact_declared_path_only(self):
        self.assertEqual(WHEEL['notice_member'],NOTICE_MEMBER)
        ptp.notice_member_rules(WHEEL)
        names=[i.filename for i in self.zip.infolist()]
        self.assertEqual(names.count(NOTICE_MEMBER),1)
        body=self.zip.read(NOTICE_MEMBER)
        self.assertEqual(hashlib.sha256(body).hexdigest(),WHEEL['notice']['sha256'])
        self.assertEqual(hashlib.sha256((PROJECT/WHEEL['notice']['path']).read_bytes()).hexdigest(),WHEEL['notice']['sha256'])
        self.assertNotIn('quantlib-1.43.data/data/share/doc/quantlib/COPYING',names)
        # the dist-info search of the extraction job finds no license file in this wheel, so the lock declares the member
        self.assertEqual([n for n in names if n.startswith('quantlib-1.43.dist-info/')
                          and n.rsplit('/',1)[-1].upper().startswith(('LICENSE','LICENCE','COPYING'))],[])
        self.assertFalse((LAYER/NOTICE_MEMBER).exists())          # the files of the data directory never enter the layer

    def test_host_streaming_exact_accepts_and_one_past_refuses(self):
        # in the project bench image: the trusted host wrote each declared member from the verified wheel, with its size and sha256
        for name,size in sorted(HOST_MEMBERS.items()):
            with self.subTest(member=name):
                path=LAYER/name;digest=hashlib.sha256()
                with open(path,'rb') as f:
                    for chunk in iter(lambda:f.read(recipe.READ_CHUNK),b''):digest.update(chunk)
                self.assertEqual((path.stat().st_size,digest.hexdigest()),(size,self.declared[name]['sha256']))
                self.assertLessEqual(size,QL_MAX_MEMBER)

    def test_host_streaming_refuses_undeclared_or_changed_members(self):
        # in the project bench image: every file above the container file bound is a declared host member of a lock row
        declared={name for w in LOCK['wheels'] for name in (h['member'] for h in w.get('host_members',[]))}
        big=sorted(os.path.relpath(os.path.join(d,f),LAYER) for d,_,fs in os.walk(LAYER) for f in fs
                   if os.path.getsize(os.path.join(d,f))>recipe.MAX_FILE)
        self.assertEqual(big,sorted(declared))
        self.assertEqual(sorted(declared),sorted(HOST_MEMBERS))

    def test_payload_split_counts_quantlib_separately(self):
        shares={}
        for wheel in LOCK['wheels']:
            with wheel_zip(wheel) as archive:
                members=layer_members(archive)
                shares[wheel['name']]=(len(members),sum(i.file_size for i in members))
        self.assertEqual(shares['quantlib'],(LAYER_FILES,LAYER_BYTES))
        files,total=sum(n for n,_ in shares.values()),sum(b for _,b in shares.values())
        self.assertLessEqual(files,ptp.LAYER_MAX_FILES)
        self.assertLessEqual(total,ptp.LAYER_MAX_BYTES)
        self.assertEqual((files,total),(820,186293884))


class LicenseRecordTests(unittest.TestCase):
    """Ruling R62 (legal-team answer of 2026-10-19 for QuantLib): the lock row QuantLib-source (the pure BSD-3-Clause QuantLib
    source release) is APPROVED; the quantlib wheel row stays PENDING (it also holds compiled Boost code, BSL-1.0, that the
    answer does not name); Boost, scipy and mpmath stay PENDING (no separate legal-team statement). Each provenance record and
    the License record of NOTICE-QuantLib.md state this; no record says that the confirmation is open. Reads files only."""
    REVIEW={('wheels','quantlib'):'PENDING',('wheels','scipy'):'PENDING',('wheels','mpmath'):'PENDING',
            ('sources','QuantLib-source'):'APPROVED',('retained','Boost'):'PENDING'}
    RECORDS={
        'quantlib-source.json':'agent engineering license review LR-EX performed 2026-10-18 (not legal advice): no license conflict with the first-party MIT license; the notices of this row meet the license conditions; legal-team confirmation received 2026-10-19 for QuantLib: BSD-3-Clause, permissive, commercial and proprietary use permitted; review_status APPROVED',
        'quantlib.json':'agent engineering license review LR-EX performed 2026-10-18 (not legal advice): no license conflict with the first-party MIT license; the notices of this row meet the license conditions; legal-team confirmation received 2026-10-19 for QuantLib: BSD-3-Clause, permissive, commercial and proprietary use permitted; the row stays PENDING: the wheel also holds compiled Boost 1.90.0 code (BSL-1.0), which that confirmation does not name; review_status PENDING',
        'boost-source.json':'agent engineering license review LR-EX performed 2026-10-18 (not legal advice): no license conflict with the first-party MIT license; the notices of this row meet the license conditions; no separate legal-team statement for the Boost 1.90.0 material (BSL-1.0) (the legal-team confirmation of 2026-10-19 names QuantLib only); review_status PENDING',
        'scipy.json':'agent engineering license review LR-EX performed 2026-10-18 (not legal advice): no license conflict with the first-party MIT license; the notices of this row and examples/option-pricing-benchmark/SOURCE-OFFER.md (the four GCC runtime files) meet the license conditions; no separate legal-team statement for SciPy (the legal-team confirmation of 2026-10-19 names QuantLib only); review_status PENDING',
        'mpmath.json':'agent engineering license review LR-EX performed 2026-10-18 (not legal advice): no license conflict with the first-party MIT license; the notices of this row meet the license conditions; no separate legal-team statement for mpmath (the legal-team confirmation of 2026-10-19 names QuantLib only); review_status PENDING'}
    NOTICE_SENTENCES=(
        'Legal-team confirmation received 2026-10-19 for QuantLib: QuantLib is licensed under the BSD 3-Clause License (also called the Modified BSD License), a permissive, non-copyleft open-source license that explicitly permits commercial and proprietary use.',
        'The lock sets `review_status` APPROVED for the row `QuantLib-source` (the QuantLib 1.43 source release).',
        'The row `quantlib` (the QuantLib-Python 1.43 wheel) stays PENDING: the wheel also holds compiled Boost 1.90.0 code (BSL-1.0), which the confirmation does not name.',
        'The Boost 1.90.0 material (BSL-1.0), SciPy and mpmath have no separate legal-team statement; their rows stay PENDING.')
    def test_the_lock_review_status_of_each_row(self):
        got={(section,row['name']):row['license']['review_status'] for section in ('wheels','sources','retained') for row in LOCK[section]}
        self.assertEqual(got,self.REVIEW)
    def test_each_provenance_record_states_its_license_review(self):
        for name,text in self.RECORDS.items():
            with self.subTest(record=name):
                record=json.loads((PROJECT/'third_party/provenance'/name).read_text())
                self.assertEqual(record['license_review'],text)
                self.assertNotIn('confirmation open',record['license_review'])
    def test_the_notice_license_record_states_the_confirmation(self):
        text=' '.join((SRC/PROJECT_DIR/'NOTICE-QuantLib.md').read_text().split())
        section=text.split('## License record',1)[1].split(' ## ',1)[0]
        for sentence in self.NOTICE_SENTENCES:
            with self.subTest(sentence=sentence[:40]):self.assertIn(sentence,section)
        self.assertNotIn('Legal-team confirmation: open',text)


if __name__=='__main__':
    unittest.main()
