import hashlib, importlib.util, io, json, sys, tarfile, tempfile, time, unittest, zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from evidence import GateError
import acquire_bench_wheels as aw
spec=importlib.util.spec_from_file_location('developer_package',ROOT/'container/developer-package.py')
dp=importlib.util.module_from_spec(spec);spec.loader.exec_module(dp)

class FrameworkWheelSetTests(unittest.TestCase):
    """FR4 (owner decision 2026-10-13): the framework image holds exactly the wheels that framework code imports."""
    ALLOWED={'numpy':'2.3.3','pyperf':'2.9.0','psutil':'7.1.0'}
    def test_the_pins_selection_and_lock_name_exactly_the_allowed_wheels(self):
        self.assertEqual(aw.PINS,self.ALLOWED)
        selection=json.loads((ROOT/aw.SELECTION).read_text())
        self.assertEqual({w['name']:w['version'] for w in selection['wheels']},self.ALLOWED)
        lock=json.loads((ROOT/'developer.lock.json').read_text())
        self.assertEqual(lock['bench_python'],self.ALLOWED)
        parts={p['path'] for w in selection['wheels'] for p in w['parts']}
        self.assertEqual({r['path'] for r in lock['inputs'] if r['kind']=='python-wheel-part'},parts)
        self.assertEqual({'third_party/developer/wheels/'+p.name for p in (ROOT/aw.WHEELS).iterdir()},parts)
    def test_no_removed_package_is_left_in_the_framework_tree(self):
        lock=json.loads((ROOT/'developer.lock.json').read_text())
        for name in ('QuantLib','scipy','mpmath'):
            with self.subTest(name=name):
                self.assertNotIn(name,lock['notices']);self.assertNotIn(name,lock['bench_python'])
                self.assertFalse((ROOT/'third_party/developer/notices'/name).exists())
        self.assertFalse((ROOT/'third_party/developer/sources').exists())
        manifest=json.loads((ROOT/'third_party/developer/payload/manifest.json').read_text())
        tops={n.split('/')[2] for n in manifest['files'] if n.startswith('opt/bench-python/')}
        self.assertEqual({t.split('-')[0].split('.')[0] for t in tops},{'numpy','pyperf','psutil'})
        self.assertNotIn('host_members',manifest)

class WheelSelectionTests(unittest.TestCase):
    def test_compatible_tags(self):
        good=['numpy-2.3.3-cp313-cp313-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl','pyperf-2.9.0-py3-none-any.whl',
              'psutil-7.1.0-cp36-abi3-manylinux_2_12_x86_64.manylinux2010_x86_64.manylinux_2_17_x86_64.manylinux2014_x86_64.whl']
        bad=['numpy-2.3.3-cp313-cp313t-manylinux_2_27_x86_64.whl','numpy-2.3.3-cp312-cp312-manylinux_2_27_x86_64.whl',
             'numpy-2.3.3-cp313-cp313-musllinux_1_2_x86_64.whl','numpy-2.3.3-cp313-cp313-manylinux_2_27_aarch64.whl','numpy-2.3.3.tar.gz']
        for name in good:self.assertTrue(aw.compatible(name),name)
        for name in bad:self.assertFalse(aw.compatible(name),name)
    def test_choose_needs_exactly_one_wheel(self):
        f=lambda n:{'packagetype':'bdist_wheel','filename':n,'url':'https://files.pythonhosted.org/x/'+n,'digests':{'sha256':'a'*64},'size':10,'yanked':False}
        one={'urls':[f('pyperf-2.9.0-py3-none-any.whl'),{'packagetype':'sdist','filename':'pyperf-2.9.0.tar.gz','url':'u','digests':{'sha256':'b'*64},'size':1}]}
        self.assertEqual(aw.choose(one,'pyperf','2.9.0')['sha256'],'a'*64)
        with self.assertRaises(GateError):aw.choose({'urls':[]},'pyperf','2.9.0')
        two={'urls':[f('x-1-cp313-cp313-manylinux_2_17_x86_64.whl'),f('x-1-cp313-cp313-manylinux_2_28_x86_64.whl')]}
        with self.assertRaises(GateError):aw.choose(two,'x','1')
    def test_parts_are_bounded_and_rejoin_to_the_whole_digest(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'w.whl';data=bytes(range(256))*1000;p.write_bytes(data)
            parts=aw.split_parts(p,part=100000)
            self.assertTrue(all(x['bytes']<=100000 for x in parts));self.assertEqual(len(parts),3)
            self.assertEqual(hashlib.sha256(aw.join_parts([Path(d)/Path(x['path']).name for x in parts])).hexdigest(),hashlib.sha256(data).hexdigest())

class WheelExtractionTests(unittest.TestCase):
    def test_tests_and_bytecode_are_excluded(self):
        self.assertTrue(dp.wheel_member_included('numpy/linalg/__init__.py'))
        self.assertTrue(dp.wheel_member_included('numpy/testing/__init__.py'))
        for name in ['numpy/linalg/tests/test_x.py','pyperf/__pycache__/a.cpython-313.pyc','numpy/a.pyc']:self.assertFalse(dp.wheel_member_included(name))
    def test_unsafe_wheel_member_is_rejected(self):
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w') as z:z.writestr('../escape.py','x')
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):dp.extract_wheel(buf.getvalue(),'bad',Path(d),{},0)

def wheel_bytes(members):
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w') as z:
        for name,body in members:z.writestr(name,body)
    return buf.getvalue()

class PayloadBoundTests(unittest.TestCase):
    """Controller ruling on PLAN-T5-BOUND-01: separate wheel pass bounds; Debian bounds unchanged."""
    def test_debian_bounds_are_unchanged(self):
        self.assertEqual(dp.MAX_BYTES,268435456);self.assertEqual(dp.MAX_FILES,4096);self.assertEqual(dp.MAX_FILE,33554432)
        spec2=importlib.util.spec_from_file_location('assemble_developer_image',ROOT/'tools/assemble_developer_image.py')
        asm=importlib.util.module_from_spec(spec2);spec2.loader.exec_module(asm)
        self.assertEqual((asm.DEBIAN_MAX_BYTES,asm.DEBIAN_MAX_FILES),(268435456,4096))
        self.assertEqual((asm.WHEEL_MAX_BYTES,asm.WHEEL_MAX_FILES,asm.WHEEL_ROOT),(dp.WHEEL_MAX_BYTES,dp.WHEEL_MAX_FILES,dp.WHEEL_ROOT))
    def test_wheel_bounds_are_separate_and_named(self):
        self.assertEqual(dp.WHEEL_MAX_BYTES,201326592);self.assertEqual(dp.WHEEL_MAX_FILES,1536)
    def test_wheel_byte_bound_exact_accepts_and_one_past_refuses(self):
        data=wheel_bytes([('pkg/a.py','xy')])
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(dp.extract_wheel(data,'pkg',Path(d),{},dp.WHEEL_MAX_BYTES-2),dp.WHEEL_MAX_BYTES)
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError,'wheel total byte bound'):dp.extract_wheel(data,'pkg',Path(d),{},dp.WHEEL_MAX_BYTES-1)
    def test_wheel_zero_and_one_member(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(dp.extract_wheel(wheel_bytes([]),'pkg',Path(d),{},0),0)
            owners={};self.assertEqual(dp.extract_wheel(wheel_bytes([('pkg/a.py','x')]),'pkg',Path(d),owners,0),1)
            self.assertEqual(owners,{'opt/bench-python/pkg/a.py':'pkg'})
    def test_wheel_file_bound_exact_accepts_and_one_past_refuses(self):
        data=wheel_bytes([('pkg/a.py','x')])
        with tempfile.TemporaryDirectory() as d:
            owners={f'opt/bench-python/f{i}':'x' for i in range(dp.WHEEL_MAX_FILES-1)}
            dp.extract_wheel(data,'pkg',Path(d),owners,0);self.assertEqual(len(owners),dp.WHEEL_MAX_FILES)
        with tempfile.TemporaryDirectory() as d:
            owners={f'opt/bench-python/f{i}':'x' for i in range(dp.WHEEL_MAX_FILES)}
            with self.assertRaisesRegex(ValueError,'wheel file inventory bound'):dp.extract_wheel(data,'pkg',Path(d),owners,0)
    def test_duplicate_wheel_member_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError,'duplicate wheel member'):
                dp.extract_wheel(wheel_bytes([('pkg/a.py','x')]),'pkg',Path(d),{'opt/bench-python/pkg/a.py':'other'},0)

def assembler():
    s=importlib.util.spec_from_file_location('assemble_developer_image',ROOT/'tools/assemble_developer_image.py')
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def d(c):return 'sha256:'+c*64

class OwnedImageBytesTests(unittest.TestCase):
    """Controller ruling on PLAN-T5-IMAGES-01: layers counted once; bounds unchanged."""
    def setUp(self):
        self.a=assembler()
        # base: two layers; child: base + one layer. History sizes oldest first; Size = snapshots + platform closure blobs.
        self.base=self.a.layer_measure('base',{'RootFS':{'Layers':[d('1'),d('2')]},'Size':100+200+10+20+1+2},
            ['100','0','200'],{d('a'):10,d('b'):20,d('d'):1,d('c'):2,d('9'):7},{d('a'),d('b'),d('d'),d('c')})
        self.child=self.a.layer_measure('child',{'RootFS':{'Layers':[d('1'),d('2'),d('3')]},'Size':100+200+50+10+20+5+3+4},
            ['100','200','50'],{d('a'):10,d('b'):20,d('e'):5,d('8'):3,d('f'):4},{d('a'),d('b'),d('e'),d('8'),d('f')})
    def test_shared_layers_are_counted_once(self):
        self.assertEqual(self.a.unique_bytes([self.base,self.child]),100+200+50+10+20+1+2+7+5+3+4)
        self.assertLess(self.a.unique_bytes([self.base,self.child]),self.base['size']+self.child['size'])
    def test_same_diff_at_another_position_is_not_shared(self):
        other=self.a.layer_measure('o',{'RootFS':{'Layers':[d('2')]},'Size':9+1},['9'],{d('6'):1},{d('6')})
        self.assertEqual(self.a.unique_bytes([self.base,other]),self.a.unique_bytes([self.base])+10)
    def test_exact_bound_is_accepted_and_one_byte_over_is_refused(self):
        total=self.a.unique_bytes([self.base,self.child])
        self.assertEqual(self.a.admit([self.base,self.child],5,total+5),total+5)
        with self.assertRaisesRegex(GateError,'owned-image admission bound'):self.a.admit([self.base,self.child],6,total+5)
    def test_inexact_measurement_is_refused(self):
        with self.assertRaisesRegex(GateError,'not exact'):
            self.a.layer_measure('x',{'RootFS':{'Layers':[d('1')]},'Size':12},['10'],{d('a'):1},{d('a')})
        with self.assertRaisesRegex(GateError,'does not match'):
            self.a.layer_measure('x',{'RootFS':{'Layers':[d('1'),d('2')]},'Size':11},['10'],{d('a'):1},{d('a')})
        with self.assertRaisesRegex(GateError,'blob inventory'):
            self.a.layer_measure('x',{'RootFS':{'Layers':[d('1')]},'Size':11},['10'],{d('a'):1},{d('b')})
    def test_bounds_are_unchanged(self):
        policy=json.loads((ROOT/'safety/container-policy.json').read_text())['aggregate']
        self.assertEqual((policy['max_owned_images'],policy['owned_image_bytes']),(4,5368709120))
    def test_platform_closure_excludes_index_and_attestations(self):
        index={'manifests':[{'digest':d('d'),'platform':{'os':'linux','architecture':'amd64'}},
                            {'digest':d('7'),'platform':{'os':'unknown','architecture':'unknown'},'annotations':{'vnd.docker.reference.type':'attestation-manifest'}}]}
        docs={'index.json':json.dumps({'manifests':[{'digest':d('9')}]}).encode(),d('9'):json.dumps(index).encode(),
              d('d'):json.dumps({'config':{'digest':d('c')},'layers':[{'digest':d('a')}]}).encode()}
        self.assertEqual(self.a.platform_closure(docs),{d('d'),d('c'),d('a')})
        docs[d('9')]=json.dumps({'manifests':index['manifests'][:1]*2}).encode()
        with self.assertRaises(GateError):self.a.platform_closure(docs)

STALL="import sys,tarfile,time\ni=tarfile.TarInfo('blobs/sha256/'+'a'*64);i.size=1<<20\nsys.stdout.buffer.write(i.tobuf()+b'x'*100);sys.stdout.buffer.flush();time.sleep(30)"
GARBAGE="import sys\nsys.stdout.buffer.write(b'not a tar stream'*64)"

class FakeLauncher:
    def __init__(self,script,history='10',inspect=None):
        self.prefix=[sys.executable,'-c',script];self.env=None;self.history=history;self.inspect=inspect
    def json(self,args):return json.loads(self.inspect)
    def docker(self,args,**kw):return {'exit_code':0,'failure':None,'output':self.history}

class SaveStreamTests(unittest.TestCase):
    """Review fix: docker image save has a finite wall limit and fails closed."""
    def test_stalled_stream_ends_with_gate_error_within_the_limit(self):
        a=assembler();started=time.monotonic()
        with self.assertRaisesRegex(GateError,'timed out'):a.save_content(FakeLauncher(STALL),'x',timeout=0.2)
        self.assertLess(time.monotonic()-started,5)
    def test_malformed_stream_is_a_gate_error(self):
        with self.assertRaisesRegex(GateError,'malformed'):assembler().save_content(FakeLauncher(GARBAGE),'x',timeout=5)
    def test_malformed_history_and_inspect_are_gate_errors(self):
        a=assembler()
        good=json.dumps([{'RootFS':{'Layers':[d('1')]},'Size':11}])
        with self.assertRaisesRegex(GateError,'history malformed'):a.measure_owned(FakeLauncher(GARBAGE,history='12kB',inspect=good),'x')
        with self.assertRaisesRegex(GateError,'inspect malformed'):a.measure_owned(FakeLauncher(GARBAGE,inspect='{'),'x')
    def test_malformed_manifest_json_is_a_gate_error(self):
        a=assembler()
        with self.assertRaisesRegex(GateError,'manifest malformed'):a.platform_closure({'index.json':b'{'})
        with self.assertRaisesRegex(GateError,'manifest malformed'):a.platform_closure({'index.json':b'{"manifests":[{"digest":"%s"}]}'%d('9').encode(),d('9'):b'{}'})

class FakeDpkg:
    """dpkg-deb stand-in: an empty filesystem tar stream (synthetic packages hold no members)."""
    def __init__(self,*args,**kwargs):
        buf=io.BytesIO()
        with tarfile.open(fileobj=buf,mode='w'):pass
        self.stdout=io.BytesIO(buf.getvalue())
    def wait(self,timeout=None):return 0
    def poll(self):return 0
    def kill(self):pass

class FrameworkPayloadTests(unittest.TestCase):
    """FR4-A01: the framework payload assertions that left with the QuantLib tests, on synthetic wheels."""
    def test_an_oversized_member_of_an_ordinary_wheel_is_refused(self):
        from unittest import mock
        with mock.patch.object(dp,'MAX_FILE',100):
            with tempfile.TemporaryDirectory() as d:
                self.assertEqual(dp.extract_wheel(wheel_bytes([('pkg/exact.so',b'z'*100)]),'numpy',Path(d),{},0),100)
            with tempfile.TemporaryDirectory() as d:
                with self.assertRaisesRegex(ValueError,'^wheel file bound$'):
                    dp.extract_wheel(wheel_bytes([('pkg/big.so',b'z'*101)]),'numpy',Path(d),{},0)
                self.assertEqual([p for p in Path(d).rglob('*') if p.is_file()],[])
    def test_the_container_file_limit_equals_the_policy_file_bytes(self):
        policy=json.loads((ROOT/'safety/container-policy.json').read_text())
        self.assertIn('"file_bytes": 33554432',(ROOT/'safety/container-policy.json').read_text())
        self.assertEqual(dp.MAX_FILE,33554432)
        self.assertIn(33554432,[v for section in policy.values() if isinstance(section,dict) for v in section.values()])
    def test_payload_of_sorts_wheel_and_debian_files(self):
        a=assembler()
        files={'opt/bench-python/numpy/a.py':{'package':'numpy'},'opt/bench-python/pyperf-2.9.0.dist-info/METADATA':{'package':'pyperf'},
               'usr/lib/x':{'package':'gdb'},'usr/bin/gdb':{'package':'gdb'},'opt/other/a.py':{'package':'numpy'}}
        self.assertEqual({n:a.payload_of(n,r) for n,r in files.items()},
                         {'opt/bench-python/numpy/a.py':'wheels','opt/bench-python/pyperf-2.9.0.dist-info/METADATA':'wheels',
                          'usr/lib/x':'debian','usr/bin/gdb':'debian','opt/other/a.py':'debian'})
    def extraction(self,d,extra):
        """Run developer-package main on two synthetic packages and one synthetic wheel record (+ extra fields)."""
        from unittest import mock
        inputs=Path(d)/'inputs';inputs.mkdir();work=Path(d)/'work'/'developer-acquisition';work.parent.mkdir()
        packages=[]
        for name in ('gdb','clangd-19'):
            body=name.encode();(inputs/(name+'.deb')).write_bytes(body)
            packages.append({'Package':name,'Filename':'pool/'+name+'.deb','Size':str(len(body)),'SHA256':hashlib.sha256(body).hexdigest(),'Version':'1'})
        (inputs/'selection.json').write_text(json.dumps({'packages':packages,'dependencies':[]}))
        data=wheel_bytes([('pkg/a.py','x')]);(inputs/'w.whl').write_bytes(data);sha=hashlib.sha256(data).hexdigest()
        wheel={'name':'pkg','version':'1','filename':'w.whl','url':'u','sha256':sha,'bytes':len(data),
               'parts':[{'path':'third_party/developer/wheels/w.whl','bytes':len(data),'sha256':sha}],**extra}
        (inputs/'wheel-selection.json').write_text(json.dumps({'wheels':[wheel]}))
        with mock.patch.object(dp,'INPUTS',inputs),mock.patch.object(dp,'WORK',work),mock.patch.object(dp.subprocess,'Popen',FakeDpkg):
            dp.main()
    def test_a_wheel_record_outside_the_bench_wheel_pass_is_refused(self):
        for extra in ({'payload':'quantlib'},{'host_members':{}},{'notice':'x/LICENSE'}):
            with self.subTest(extra=sorted(extra)),tempfile.TemporaryDirectory() as d:
                with self.assertRaisesRegex(ValueError,'^wheel record outside the bench wheel pass$'):self.extraction(d,extra)
        with tempfile.TemporaryDirectory() as d:        # control: the plain record passes this check (the next refusal is the missing notice)
            with self.assertRaisesRegex(ValueError,'^package notice unavailable$'):self.extraction(d,{})
    def test_a_manifest_with_host_members_is_refused(self):
        a=assembler()
        base={'status':'CANDIDATE_DATA_EXTRACTED','package_scripts_executed':False,'files':{},'archives':[]}
        for value in ({},{'opt/bench-python/pkg/big.so':{'bytes':1}}):
            with self.subTest(host_members=value),tempfile.TemporaryDirectory() as d:
                (Path(d)/'manifest.json').write_text(json.dumps(dict(base,host_members=value)))
                with self.assertRaisesRegex(GateError,'^developer extraction manifest incomplete$'):a.unpack(Path(d),Path(d)/'layer')
        with tempfile.TemporaryDirectory() as d:        # control: the same manifest without host_members unpacks
            (Path(d)/'manifest.json').write_text(json.dumps(base))
            self.assertEqual(a.unpack(Path(d),Path(d)/'layer')['files'],{})
