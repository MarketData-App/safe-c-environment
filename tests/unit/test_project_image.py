"""EX-1: the project image layer. A project pins its own wheels and source archives in a protected third-party lock;
the framework builds a project bench image from the qualified developer image plus one data layer, and every bench job
of that project runs in it.

Unit tests only: a fake docker layer, a temporary root for every mutation, and the real extraction recipe
(container/project-wheels.py) on temporary directories. The real container test is the project unit suite of
tests/fixtures/wheel-project in its project bench image (bench selftest --suite project: project-image:<fixture>)."""
import base64, copy, hashlib, importlib.util, io, json, re, shutil, sys, tempfile, unittest, unittest.mock, warnings, zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import bench_model as bm
import project_third_party as ptp
from evidence import GateError, file_hash

FIXTURE='tests/fixtures/wheel-project'
SOURCE=ROOT/FIXTURE/'benchmarks/project/third_party/wheel-source'
SOURCE_INIT='third_party/wheel-source/scfixturewheel/__init__.py'
WHEEL='third_party/wheels/scfixturewheel-1.0.0-py3-none-any.whl'      # the path fetch-project writes (no tracked fixture archive)
DEV='sha256:'+'d'*64

def build_fixture_wheel(source):
    """An independent statement of the deterministic stored-zip rule (project_third_party.build_source_wheel): sorted
    source files, a RECORD with urlsafe sha256 digests last, fixed time stamps and modes."""
    source=Path(source)
    files=sorted(p.relative_to(source).as_posix() for p in source.rglob('*') if p.is_file())
    info=[f for f in files if f.endswith('.dist-info/WHEEL')][0].rsplit('/',1)[0]
    record=''
    for rel in files:
        data=(source/rel).read_bytes()
        record+=rel+',sha256='+base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip('=')+','+str(len(data))+'\n'
    record+=info+'/RECORD,,\n'
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_STORED) as z:
        for rel,data in [(r,(source/r).read_bytes()) for r in files]+[(info+'/RECORD',record.encode())]:
            zi=zipfile.ZipInfo(rel,date_time=(1980,1,1,0,0,0));zi.create_system=3;zi.external_attr=0o644<<16
            z.writestr(zi,data)
    return out.getvalue()

def scratch(test,project=FIXTURE,dest=None):
    """A temporary root: the schemas, the developer lock, the recipe and the assembler, an empty framework cases
    directory and a byte copy of `project` (at `dest` when given)."""
    t=Path(tempfile.mkdtemp(prefix='safe-c-project-image-'));test.addCleanup(shutil.rmtree,t,True)
    shutil.copytree(ROOT/'schemas',t/'schemas')
    for rel in ('developer.lock.json','container/project-wheels.py','tools/project_image.py','starter-export.json'):   # EX1-R1-01: the export set
        (t/rel).parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/rel,t/rel)
    (t/bm.CASES).mkdir(parents=True);shutil.copytree(ROOT/project,t/(dest or project))
    return t

def area(t,project=FIXTURE):return Path(t)/project/bm.PROJECT_AREA

def lock_of(t,project=FIXTURE):return json.loads((area(t,project)/ptp.LOCK_FILE).read_text())

def rebind(t,doc,project=FIXTURE):
    """Write `doc` as the lock and bind its new sha256 in bench.json (a reviewed edit of both protected files)."""
    p=area(t,project)/ptp.LOCK_FILE;p.write_text(json.dumps(doc))
    decl=json.loads((area(t,project)/'bench.json').read_text());decl['third_party']['sha256']=file_hash(p)
    (area(t,project)/'bench.json').write_text(json.dumps(decl))

def add_wheel(t,files,name='scextra',version='2.0',modules=None,project=FIXTURE,notice=b'MIT License\n',method=zipfile.ZIP_STORED):
    """Write a wheel of `files` ({path or ZipInfo: bytes}) with its notice and provenance, and return its lock row."""
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w',method) as z:
        for rel,body in files.items():
            zi=rel if isinstance(rel,zipfile.ZipInfo) else zipfile.ZipInfo(rel,date_time=(1980,1,1,0,0,0))
            zi.compress_type=method;z.writestr(zi,body)
    data=data.getvalue();filename=f'{name}-{version}-py3-none-any.whl';a=area(t,project)
    (a/'third_party/wheels').mkdir(parents=True,exist_ok=True);(a/'third_party/wheels'/filename).write_bytes(data)
    (a/'third_party/notices'/name).mkdir(parents=True,exist_ok=True);(a/'third_party/notices'/name/'LICENSE').write_bytes(notice)
    (a/'third_party/provenance'/(name+'.json')).write_text('{}')
    digest=hashlib.sha256(data).hexdigest()
    return {'name':name,'version':version,'filename':filename,'tag':'py3-none-any','modules':modules or [name],'sha256':digest,'bytes':len(data),
            'parts':[{'path':'third_party/wheels/'+filename,'sha256':digest,'bytes':len(data)}],'origin':{'kind':'pypi','url':'https://files.pythonhosted.org/packages/aa/'+filename},
            'provenance':{'path':f'third_party/provenance/{name}.json','sha256':hashlib.sha256(b'{}').hexdigest()},
            'notice':{'path':f'third_party/notices/{name}/LICENSE','sha256':hashlib.sha256(notice).hexdigest()},
            'license':{'tags':['MIT'],'owner':'MarketData-App','review_status':'PENDING'}}

def recipe():
    spec=importlib.util.spec_from_file_location('project_wheels_recipe',ROOT/'container/project-wheels.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def run_recipe(test,base,lock):
    """The extraction recipe on temporary /inputs and /work directories; returns (work directory, manifest)."""
    r=recipe();tmp=Path(tempfile.mkdtemp(prefix='safe-c-recipe-'));test.addCleanup(shutil.rmtree,tmp,True)
    (tmp/'inputs').mkdir();(tmp/'inputs/lock.json').write_text(json.dumps(lock))
    for w in lock['wheels']:
        if not w['parts']:(tmp/'inputs'/w['filename']).write_bytes(ptp.build_source_wheel(Path(base),w))
        for p in w['parts']:shutil.copyfile(Path(base)/p['path'],tmp/'inputs'/Path(p['path']).name)
    r.INPUTS=tmp/'inputs';r.WORK=tmp/'work';r.main()
    return r.WORK,json.loads((r.WORK/'manifest.json').read_text())


class FixtureWheelTests(unittest.TestCase):
    def test_the_fixture_wheel_is_built_from_its_tracked_source(self):
        lock=bm.third_party_lock(ROOT,FIXTURE);row=lock['wheels'][0]
        data=ptp.build_source_wheel(ROOT/FIXTURE/bm.PROJECT_AREA,row)
        self.assertEqual(data,build_fixture_wheel(SOURCE))
        self.assertEqual((hashlib.sha256(data).hexdigest(),len(data)),(row['sha256'],row['bytes']))
        self.assertEqual((row['parts'],row['source_dir'],row['origin']['kind']),([],'third_party/wheel-source','first-party-fixture'))
        self.assertFalse((ROOT/FIXTURE/bm.PROJECT_AREA/'third_party/wheels').exists())        # no first-party archive is tracked

    def test_the_fixture_lock_is_bound_checked_and_its_files_verify(self):
        lock=bm.third_party_lock(ROOT,FIXTURE);decl=bm.project_bench(ROOT,FIXTURE)
        self.assertEqual(decl['third_party'],{'file':ptp.LOCK_FILE,'sha256':file_hash(ROOT/FIXTURE/bm.PROJECT_AREA/ptp.LOCK_FILE)})
        self.assertEqual(ptp.verify_files(ROOT/FIXTURE/bm.PROJECT_AREA,lock),{'scfixturewheel':2605})
        self.assertEqual(ptp.plan_entry(lock),{'path':'/opt/project-python','dist_info':['scfixturewheel-1.0.0.dist-info'],'modules':['scfixturewheel']})

    def test_projects_without_a_lock_have_none(self):
        for project in ('tests/fixtures/bench-project','examples/bench-demo',None):
            with self.subTest(project=project):self.assertIsNone(bm.third_party_lock(ROOT,project))

    def test_the_lock_directory_is_protected_and_the_files_are_exported(self):
        import bench_phase3
        doc=json.loads((ROOT/'safety/protected-paths.json').read_text())
        self.assertIn('benchmarks/project/third_party/',doc['project_protected'])
        self.assertEqual(bench_phase3.protected_entry(ROOT,f'{FIXTURE}/benchmarks/project/third_party/lock.json'),'benchmarks/project/third_party/')
        self.assertEqual(bench_phase3.protected_entry(ROOT,f'{FIXTURE}/{bm.PROJECT_AREA}/{SOURCE_INIT}'),'benchmarks/project/third_party/')
        exported=set(json.loads((ROOT/'starter-export.json').read_text())['files'])
        for rel in ('tools/project_image.py','tools/project_third_party.py','container/project-wheels.py','schemas/project-third-party.json',
                    f'{FIXTURE}/{bm.PROJECT_AREA}/{SOURCE_INIT}',f'{FIXTURE}/{bm.PROJECT_AREA}/{ptp.LOCK_FILE}'):
            with self.subTest(path=rel):self.assertIn(rel,exported)


class TagRuleTests(unittest.TestCase):
    def test_the_tag_rule_equals_the_acquisition_rule(self):
        import acquire_bench_wheels as aw
        for name in ('a-1-py3-none-any.whl','a-1-cp313-cp313-manylinux_2_17_x86_64.manylinux2014_x86_64.whl','a-1-cp38-abi3-manylinux_2_28_x86_64.whl',
                     'a-1-cp314-abi3-manylinux_2_28_x86_64.whl','a-1-cp312-cp312-manylinux_2_17_x86_64.whl','a-1-cp313-cp313-win_amd64.whl',
                     'a-1-cp313-cp313-manylinux_2_17_aarch64.whl','a-1-py2-none-any.whl','a-1.tar.gz'):
            with self.subTest(name=name):self.assertEqual(ptp.compatible(name),aw.compatible(name))


class LockRefusalTests(unittest.TestCase):
    """Schema and host refusals. Each mutation is bound again (a reviewed edit), so only the named rule refuses it."""
    def refused(self,mutate,pattern=None):
        t=scratch(self);doc=lock_of(t);mutate(doc,t);rebind(t,doc)
        with self.assertRaises(GateError) as caught:bm.third_party_lock(t,FIXTURE)
        if pattern:self.assertRegex(str(caught.exception),pattern)
        return caught.exception

    def test_the_unchanged_scratch_copy_loads(self):
        t=scratch(self);self.assertEqual(bm.third_party_lock(t,FIXTURE)['wheels'][0]['name'],'scfixturewheel')

    def test_a_missing_digest_is_refused(self):
        for drop in (lambda w:w.pop('sha256'),lambda w:w['parts'][0].pop('sha256'),lambda w:w['provenance'].pop('sha256'),lambda w:w['notice'].pop('sha256')):
            def mutate(d,t):
                d['wheels'].append(add_wheel(t,{'x':b''}));drop(d['wheels'][-1])
            with self.subTest(drop=drop):self.refused(mutate)
        self.refused(lambda d,t:d['wheels'][0].update(sha256='0'*63))

    def test_a_missing_notice_or_license_record_is_refused(self):
        self.refused(lambda d,t:d['wheels'][0].pop('notice'))
        self.refused(lambda d,t:d['wheels'][0].pop('license'))
        self.refused(lambda d,t:d['wheels'][0].pop('provenance'))

    def test_an_unknown_license_is_refused(self):
        for tags in (['WTFPL'],['MIT','proprietary'],[],['mit']):
            with self.subTest(tags=tags):self.refused(lambda d,t:d['wheels'][0]['license'].update(tags=tags))
        self.refused(lambda d,t:d['wheels'][0]['license'].update(review_status='WAIVED'))

    def test_a_path_outside_the_project_is_refused(self):
        for path in ('../third_party/x.whl','/etc/passwd','wheels/x.whl','third_party/../../x','third_party/./x','third_party//x','third_party/a\\b'):
            with self.subTest(path=path):self.refused(lambda d,t:d['wheels'][0]['notice'].update(path=path))

    def test_a_link_out_of_the_project_is_refused(self):
        def link(d,t):
            outside=Path(t)/'outside';outside.mkdir();(outside/'LICENSE').write_bytes((ROOT/FIXTURE/bm.PROJECT_AREA/'third_party/notices/scfixturewheel/LICENSE').read_bytes())
            n=area(t)/'third_party/notices/scfixturewheel';shutil.rmtree(n);n.symlink_to(outside,target_is_directory=True)
        self.refused(link,'link|outside')
        def leaf(d,t):
            p=area(t)/'third_party/provenance/scfixturewheel.json';(Path(t)/'p.json').write_bytes(p.read_bytes());p.unlink();p.symlink_to(Path(t)/'p.json')
        self.refused(leaf,'link|outside')

    def test_an_oversized_wheel_or_part_is_refused(self):
        def extra(change):
            def mutate(d,t):
                d['wheels'].append(add_wheel(t,{'x':b''}));change(d['wheels'][-1])
            return mutate
        self.refused(lambda d,t:d['wheels'][0].update(bytes=ptp.ITEM_MAX_BYTES+1))
        self.refused(extra(lambda w:w['parts'][0].update(bytes=ptp.PART_MAX_BYTES+1)))
        self.refused(extra(lambda w:w.update(parts=w['parts']*3)))
        self.refused(extra(lambda w:w.update(bytes=w['bytes']+1)),'add up')

    def test_an_oversized_file_on_disk_is_refused_by_the_file_check(self):
        t=scratch(self);base=area(t);doc=lock_of(t);row=add_wheel(t,{'x':b''});doc['wheels'].append(row);rebind(t,doc)
        lock=bm.third_party_lock(t,FIXTURE);path=base/row['parts'][0]['path'];size=row['bytes']
        path.write_bytes(path.read_bytes()+b'x')
        with self.assertRaisesRegex(GateError,'differs'):ptp.verify_files(base,lock)
        with unittest.mock.patch.object(ptp,'PART_MAX_BYTES',size),self.assertRaisesRegex(GateError,'exceeds'):ptp.verify_files(base,lock)   # one byte past

    def test_the_first_party_wheel_source_is_bound_and_checked(self):
        t=scratch(self);base=area(t);lock=bm.third_party_lock(t,FIXTURE)
        (base/SOURCE_INIT).write_text((base/SOURCE_INIT).read_text()+'# changed\n')
        with self.assertRaisesRegex(GateError,'differs'):ptp.verify_files(base,lock)
        t=scratch(self);base=area(t);lock=bm.third_party_lock(t,FIXTURE)
        (base/'third_party/wheel-source/scfixturewheel-1.0.0.dist-info/RECORD').write_text('')
        with self.assertRaisesRegex(GateError,'one wheel tree'):ptp.verify_files(base,lock)
        t=scratch(self);base=area(t);lock=bm.third_party_lock(t,FIXTURE)
        (base/'third_party/wheel-source/extra.py').symlink_to(base/SOURCE_INIT)
        with self.assertRaisesRegex(GateError,'link'):ptp.verify_files(base,lock)
        t=scratch(self);base=area(t);lock=bm.third_party_lock(t,FIXTURE)
        with unittest.mock.patch.object(ptp,'SOURCE_FILE_MAX_BYTES',100),self.assertRaisesRegex(GateError,'bound'):ptp.verify_files(base,lock)

    def test_a_source_dir_and_parts_are_never_mixed(self):
        part={'path':'third_party/wheel-source/scfixturewheel/__init__.py','sha256':'0'*64,'bytes':2605}
        self.refused(lambda d,t:d['wheels'][0].update(parts=[part]),'source_dir')
        self.refused(lambda d,t:d['wheels'][0].pop('source_dir'),'source_dir')
        def pypi(d,t):
            row=add_wheel(t,{'x':b''});row['source_dir']='third_party/wheel-source';d['wheels'].append(row)
        self.refused(pypi,'source_dir')

    def test_a_changed_notice_or_provenance_file_is_refused_by_the_file_check(self):
        for rel in ('third_party/notices/scfixturewheel/LICENSE','third_party/provenance/scfixturewheel.json'):
            with self.subTest(rel=rel):
                t=scratch(self);base=area(t);lock=bm.third_party_lock(t,FIXTURE);(base/rel).write_text('changed')
                with self.assertRaisesRegex(GateError,'differs'):ptp.verify_files(base,lock)
                (base/rel).unlink()
                with self.assertRaisesRegex(GateError,'missing'):ptp.verify_files(base,lock)

    def test_a_filename_tag_or_url_mismatch_is_refused(self):
        self.refused(lambda d,t:d['wheels'][0].update(filename='other-1.0.0-py3-none-any.whl'),'filename')
        self.refused(lambda d,t:d['wheels'][0].update(tag='cp312-cp312-win_amd64',filename='scfixturewheel-1.0.0-cp312-cp312-win_amd64.whl'),'tag')
        def url(value):
            def mutate(d,t):
                d['wheels'].append(add_wheel(t,{'x':b''}));d['wheels'][-1]['origin']['url']=value
            return mutate
        self.refused(url('https://files.pythonhosted.org/packages/other.whl'),'URL')
        self.refused(url('http://files.pythonhosted.org/x/scextra-2.0-py3-none-any.whl'))

    def test_module_collisions_are_refused(self):
        self.refused(lambda d,t:d['wheels'][0].update(modules=['numpy']),'collide')
        self.refused(lambda d,t:d['wheels'][0].update(modules=['json']),'collide')
        self.refused(lambda d,t:d['wheels'][0].update(modules=['benchlab']),'collide')
        def twice(d,t):d['wheels'].append(add_wheel(t,{'x':b''},modules=['scfixturewheel']))
        self.refused(twice,'collide')
        def name(d,t):d['wheels'].append(add_wheel(t,{'x':b''},name='SCFixtureWheel',version='9'))
        self.refused(name,'repeats a name')
        def shadow(d,t):(area(t)/'python/scfixturewheel').mkdir()
        self.refused(shadow,'project wheel modules')

    def test_an_unbound_or_edited_lock_is_refused(self):
        t=scratch(self);decl=json.loads((area(t)/'bench.json').read_text());decl.pop('third_party');(area(t)/'bench.json').write_text(json.dumps(decl))
        with self.assertRaisesRegex(GateError,'not bound'):bm.project_bench(t,FIXTURE)
        t=scratch(self);p=area(t)/ptp.LOCK_FILE;p.write_text(p.read_text().replace('"owner":"MarketData-App"','"owner":"someone"',1))
        with self.assertRaisesRegex(GateError,'edited'):bm.project_bench(t,FIXTURE)
        t=scratch(self);(area(t)/ptp.LOCK_FILE).unlink()
        with self.assertRaisesRegex(GateError,'missing'):bm.project_bench(t,FIXTURE)

    def test_source_archive_rows_bind_their_files(self):
        t=scratch(self);doc=lock_of(t);base=area(t)
        (base/'third_party/sources').mkdir();body=b'reference source archive bytes';(base/'third_party/sources/scref-1.0.tar.gz').write_bytes(body)
        row=add_wheel(t,{'x':b''},name='scref',version='1.0');digest=hashlib.sha256(body).hexdigest()
        row={k:v for k,v in row.items() if k not in ('tag','modules')}
        row.update(filename='scref-1.0.tar.gz',sha256=digest,bytes=len(body),parts=[{'path':'third_party/sources/scref-1.0.tar.gz','sha256':digest,'bytes':len(body)}],
                   origin={'kind':'upstream-archive','url':'https://example.org/scref-1.0.tar.gz'})
        (base/'third_party/wheels/scref-1.0-py3-none-any.whl').unlink()
        doc['sources']=[row];rebind(t,doc)
        lock=bm.third_party_lock(t,FIXTURE);self.assertEqual(ptp.verify_files(base,lock)['scref'],len(body))
        self.assertEqual(ptp.plan_entry(lock)['dist_info'],['scfixturewheel-1.0.0.dist-info'])      # a source archive never enters the image
        (base/'third_party/sources/scref-1.0.tar.gz').write_bytes(body+b'!')
        with self.assertRaisesRegex(GateError,'differs'):ptp.verify_files(base,lock)


class FixtureOriginTests(unittest.TestCase):
    """EX1-A01: the origin first-party-fixture only in a framework fixture project; a source_dir holds source text only."""
    def test_the_fixture_origin_outside_tests_fixtures_is_refused(self):
        for dest in ('examples/wheel-demo','wheel-demo','tests/wheel-demo','tests/fixturesx/wheel-demo'):
            with self.subTest(dest=dest):
                t=scratch(self,dest=dest)
                with self.assertRaisesRegex(GateError,'first-party-fixture'):bm.third_party_lock(t,dest)
        t=scratch(self,dest='examples/wheel-demo');doc=lock_of(t,'examples/wheel-demo')
        doc['wheels']=[add_wheel(t,{'x':b''},project='examples/wheel-demo')];rebind(t,doc,'examples/wheel-demo')
        self.assertEqual(bm.third_party_lock(t,'examples/wheel-demo')['wheels'][0]['origin']['kind'],'pypi')    # a PyPI row is fine there
        def fixture_source(d,t):
            row=add_wheel(t,{'x':b''},name='scref',project='examples/wheel-demo');row['origin']={'kind':'first-party-fixture','url':None};d['sources']=[{k:v for k,v in row.items() if k not in ('tag','modules')}]
        doc=lock_of(t,'examples/wheel-demo');fixture_source(doc,t);rebind(t,doc,'examples/wheel-demo')
        with self.assertRaisesRegex(GateError,'first-party-fixture'):bm.third_party_lock(t,'examples/wheel-demo')
        self.assertTrue(ptp.fixture_project(FIXTURE,ROOT));self.assertFalse(ptp.fixture_project('tests/fixtures/',ROOT));self.assertFalse(ptp.fixture_project(None,ROOT))
        self.assertFalse(ptp.fixture_project(FIXTURE))                                    # EX1-R1-01: no root, no export set: refused

    def test_only_a_framework_tracked_fixture_project_gets_the_fixture_origin(self):
        """EX1-R1-01: a project-created tests/fixtures/<x> (not in the framework export set starter-export.json), a skipped
        build path, a link to the real fixture, a non-literal path and a root without the export set are refused; an
        untracked file added to the tracked source_dir is refused; the tracked fixture stays accepted."""
        t=scratch(self);self.assertEqual(bm.third_party_lock(t,FIXTURE)['wheels'][0]['origin']['kind'],'first-party-fixture')
        for dest in ('tests/fixtures/other-project','tests/fixtures/build/wheel-project','tests/fixtures/wheel-project/copy'):
            with self.subTest(dest=dest):
                t=scratch(self,dest=dest)
                with self.assertRaisesRegex(GateError,'framework-tracked fixture'):bm.third_party_lock(t,dest)
        t=scratch(self);(t/'tests/fixtures/linked').symlink_to(t/FIXTURE,target_is_directory=True)
        self.assertFalse(ptp.fixture_project('tests/fixtures/linked',t))
        for rel in ('tests/fixtures/./wheel-project','tests/fixtures/x/../wheel-project','tests/fixtures//wheel-project','tests/fixtures/wheel-project/','/'+FIXTURE):
            with self.subTest(rel=rel):self.assertFalse(ptp.fixture_project(rel,t))
        self.assertTrue(ptp.fixture_project(FIXTURE,t))
        t=scratch(self);(t/'starter-export.json').unlink()
        with self.assertRaisesRegex(GateError,'framework-tracked fixture'):bm.third_party_lock(t,FIXTURE)
        t=scratch(self);doc=json.loads((t/'starter-export.json').read_text())
        doc['files']=[f for f in doc['files'] if f!=FIXTURE+'/benchmarks/project/third_party/lock.json'];(t/'starter-export.json').write_text(json.dumps(doc))
        with self.assertRaisesRegex(GateError,'framework-tracked fixture'):bm.third_party_lock(t,FIXTURE)
        t=scratch(self);(area(t)/'third_party/wheel-source/scfixturewheel/extra.py').write_text('X = 1\n')
        with self.assertRaisesRegex(GateError,'framework-tracked fixture'):bm.third_party_lock(t,FIXTURE)

    def test_compiled_objects_and_binary_files_in_a_source_dir_are_refused(self):
        cases={'scfixturewheel/_speed.so':b'text','scfixturewheel/_speed.cpython-313-x86_64-linux-gnu.so':b'text','scfixturewheel/libx.so.1':b'text',
               'scfixturewheel/_speed.pyd':b'text','scfixturewheel/x.dll':b'text','scfixturewheel/x.dylib':b'text','scfixturewheel/x.o':b'text',
               'scfixturewheel/x.obj':b'text','scfixturewheel/libx.a':b'text','scfixturewheel/x.lib':b'text','scfixturewheel/x.exe':b'text',
               'scfixturewheel/x.cpython-313.pyc':b'text','scfixturewheel/elf.txt':b'\x7fELF\x02\x01\x01','scfixturewheel/macho.txt':b'\xcf\xfa\xed\xfe\x07',
               'scfixturewheel/macho32.txt':b'\xfe\xed\xfa\xce','scfixturewheel/fat.txt':b'\xca\xfe\xba\xbe','scfixturewheel/pe.txt':b'MZ\x90\x00',
               'scfixturewheel/ar.txt':b'!<arch>\nx','scfixturewheel/nul.txt':b'a\0b','scfixturewheel/latin.txt':b'caf\xe9'}
        for rel,body in cases.items():
            with self.subTest(rel=rel):
                t=scratch(self)
                try:                # free each copy at once: 20 copies held to the test end fill the 64 MiB container scratch
                    base=area(t);lock=bm.third_party_lock(t,FIXTURE)
                    (base/'third_party/wheel-source'/rel).write_bytes(body)
                    with self.assertRaisesRegex(GateError,'first-party wheel source holds'):ptp.verify_files(base,lock)
                finally:shutil.rmtree(t,True)
        for rel,body in (('scfixturewheel/notes.txt','plain text, UTF-8: caf\u00e9\n'.encode()),('scfixturewheel/data.json',b'{}')):
            with self.subTest(rel=rel):self.assertIsNone(ptp.source_text_problem(rel,body))


HEADERS={'third_party/sources/scheaders-1.0.0/include/a.hpp':b'// header a\n',
         'third_party/sources/scheaders-1.0.0/include/detail/b.hpp':b'// header b\n'}

def write_refs(t,files,project=FIXTURE):
    """Write `files` ({path under third_party/: bytes}) and return their lock references (path, sha256, bytes)."""
    a=area(t,project);refs=[]
    for rel,body in files.items():
        (a/rel).parent.mkdir(parents=True,exist_ok=True);(a/rel).write_bytes(body)
        refs.append({'path':rel,'sha256':hashlib.sha256(body).hexdigest(),'bytes':len(body)})
    return refs

def retained_row(t,files,name='scheaders',project=FIXTURE,notice=b'Upstream License\n',
                 url='https://archives.boost.io/release/1.0.0/source/scheaders_1_0_0.tar.bz2'):
    """FW-HOOK: a retained row (upstream files kept without their archive) with its notice and provenance (sizes bound)."""
    refs=write_refs(t,files,project)
    notice_ref,provenance_ref=write_refs(t,{f'third_party/notices/{name}/LICENSE':notice,f'third_party/provenance/{name}.json':b'{}'},project)
    return {'name':name,'version':'1.0.0','files':refs,'origin':{'kind':'upstream-archive','url':url},'provenance':provenance_ref,
            'notice':notice_ref,'license':{'tags':['BSL-1.0'],'owner':'MarketData-App','review_status':'PENDING'}}


class RetainedFileTests(unittest.TestCase):
    """FW-HOOK (fact F14): additive lock forms. A `retained` row binds upstream files kept without their archive; `files` of a
    wheel or source row binds more upstream files of that row; a provenance or notice record may bind its size. Every path
    is checked like the other paths; verify_files checks every byte; nothing of a retained row enters the image."""
    def load(self,mutate):
        t=scratch(self);doc=lock_of(t);mutate(doc,t);rebind(t,doc);return t,bm.third_party_lock(t,FIXTURE)

    def refused(self,mutate,pattern=None):
        t=scratch(self)
        try:
            doc=lock_of(t);mutate(doc,t);rebind(t,doc)
            with self.assertRaises(GateError) as caught:bm.third_party_lock(t,FIXTURE)
            if pattern:self.assertRegex(str(caught.exception),pattern)
        finally:shutil.rmtree(t,True)

    def test_a_retained_row_loads_and_every_file_verifies(self):
        t,lock=self.load(lambda d,t:d.update(retained=[retained_row(t,HEADERS)]))
        self.assertEqual(ptp.verify_files(area(t),lock),{'scfixturewheel':2605})        # a retained row adds no item size
        self.assertEqual(ptp.plan_entry(lock)['dist_info'],['scfixturewheel-1.0.0.dist-info'])
        for rel in list(HEADERS)+['third_party/notices/scheaders/LICENSE','third_party/provenance/scheaders.json']:
            with self.subTest(rel=rel):
                t,lock=self.load(lambda d,t:d.update(retained=[retained_row(t,HEADERS)]))
                try:
                    base=area(t);(base/rel).write_bytes((base/rel).read_bytes()+b'!')
                    with self.assertRaisesRegex(GateError,'differs'):ptp.verify_files(base,lock)
                    (base/rel).unlink()
                    with self.assertRaisesRegex(GateError,'missing'):ptp.verify_files(base,lock)
                finally:shutil.rmtree(t,True)

    def test_a_bound_record_size_is_checked(self):
        def wrong(d,t):
            row=retained_row(t,HEADERS);row['notice']['bytes']+=1;d.update(retained=[row])
        t,lock=self.load(wrong)
        with self.assertRaisesRegex(GateError,'notice differs'):ptp.verify_files(area(t),lock)
        def sized(d,t):
            for key in ('provenance','notice'):
                d['wheels'][0][key]['bytes']=(area(t)/d['wheels'][0][key]['path']).stat().st_size
        t,lock=self.load(sized);self.assertEqual(ptp.verify_files(area(t),lock),{'scfixturewheel':2605})   # an existing row may add sizes

    def test_item_files_bind_more_upstream_files_of_a_row(self):
        def add(d,t):
            row=add_wheel(t,{'x':b''});row['files']=write_refs(t,{'third_party/notices/scextra/THIRD-PARTY':b'bundled notice\n'});d['wheels'].append(row)
        t,lock=self.load(add);ptp.verify_files(area(t),lock)
        self.assertEqual(lock['wheels'][1]['files'][0]['path'],'third_party/notices/scextra/THIRD-PARTY')
        (area(t)/'third_party/notices/scextra/THIRD-PARTY').write_bytes(b'changed notice\n')
        with self.assertRaisesRegex(GateError,'file differs'):ptp.verify_files(area(t),lock)

    def test_retained_rows_are_checked_like_the_other_rows(self):
        self.refused(lambda d,t:d.update(retained=[dict(retained_row(t,HEADERS),files=[])]))                       # at least one file
        self.refused(lambda d,t:d.update(retained=[{k:v for k,v in retained_row(t,HEADERS).items() if k!='notice'}]))
        self.refused(lambda d,t:d.update(retained=[dict(retained_row(t,HEADERS),filename='x.tar.gz')]))            # no other key
        self.refused(lambda d,t:d.update(retained=[retained_row(t,HEADERS,name='SCFixtureWheel')]),'repeats a name')
        def twice(d,t):
            row=retained_row(t,HEADERS);row['files'].append(dict(row['files'][0]));d.update(retained=[row])
        self.refused(twice,'repeats a path')
        def wheel_path(d,t):
            row=retained_row(t,HEADERS);row['files'].append(dict(row['files'][0],path=d['wheels'][0]['notice']['path']));d.update(retained=[row])
        self.refused(wheel_path,'repeats a path')
        for path in ('../x.hpp','third_party/../../x','sources/x.hpp','third_party//x'):
            with self.subTest(path=path):
                self.refused(lambda d,t:d.update(retained=[dict(retained_row(t,HEADERS),files=[{'path':path,'sha256':'0'*64,'bytes':1}])]))
        def link(d,t):
            outside=Path(t)/'outside.hpp';outside.write_bytes(b'// header\n');row=retained_row(t,HEADERS)
            target=area(t)/row['files'][0]['path'];target.unlink();target.symlink_to(outside);d.update(retained=[row])
        self.refused(link,'link|outside')
        self.refused(lambda d,t:d['wheels'][0]['notice'].update(bytes=0))
        self.refused(lambda d,t:d['wheels'][0]['notice'].update(bytes=ptp.RECORD_MAX_BYTES+1))
        self.refused(lambda d,t:d.update(retained=[dict(retained_row(t,HEADERS),origin={'kind':'mirror','url':'https://example.org/x'})]))

    def test_no_row_binds_the_lock_itself(self):
        lockref={'path':ptp.LOCK_FILE,'sha256':'0'*64,'bytes':1}
        self.refused(lambda d,t:d.update(retained=[dict(retained_row(t,HEADERS),files=[lockref])]),'lock itself')
        self.refused(lambda d,t:d['wheels'][0]['notice'].update(path=ptp.LOCK_FILE),'lock itself')

    def test_the_fixture_origin_in_a_retained_row_needs_a_fixture_project(self):
        dest='examples/wheel-demo';t=scratch(self,dest=dest);doc=lock_of(t,dest)
        row=retained_row(t,HEADERS,project=dest);row['origin']={'kind':'first-party-fixture','url':None}
        doc['wheels']=[];doc['retained']=[row];rebind(t,doc,dest)
        with self.assertRaisesRegex(GateError,'first-party-fixture'):bm.third_party_lock(t,dest)
        row['origin']={'kind':'upstream-archive','url':'https://archives.boost.io/release/1.0.0/source/x.tar.bz2'};rebind(t,doc,dest)
        self.assertEqual(bm.third_party_lock(t,dest)['retained'][0]['name'],'scheaders')

    def test_the_schema_holds_the_exempt_origin_allowlist(self):
        schema=json.loads((ROOT/'schemas/project-third-party.json').read_text())
        pattern=schema['$defs']['exempt_origin_url']['pattern']
        for host in ('files\\.pythonhosted\\.org','github\\.com','archives\\.boost\\.io'):
            with self.subTest(host=host):self.assertIn(host,pattern)


class NativeBoundaryTests(unittest.TestCase):
    """EX1-A02: no first-party C build sees the project wheels."""
    def test_the_native_build_job_keeps_the_developer_image(self):
        import bench
        s=bench.BenchSession(ROOT,Path(tempfile.mkdtemp(prefix='safe-c-native-')));self.addCleanup(s.close);self.addCleanup(shutil.rmtree,s.run_dir,True)
        calls=[]
        plan={'schema_version':1,'job':'native-build','project_dir':FIXTURE,'targets':[]}
        self.assertEqual(s.select_image(plan,ensure=lambda *a:calls.append(a)),plan)
        self.assertEqual((s.lock['image_id'],calls),(s.developer_image,[]))
        self.assertEqual(bench.NATIVE_BUILD_JOBS,('native-build',))
        src=(ROOT/'tools/bench_native.py').read_text();self.assertIn("'job':'native-build'",src)
        self.assertIn("@job('native-build')",(ROOT/'container/bench_native_job.py').read_text())
        self.assertNotIn('project-python',(ROOT/'container/bench_native_job.py').read_text())   # no include or library path names the layer

    def test_the_coordinator_refuses_wheels_for_a_native_build(self):
        d=Path(tempfile.mkdtemp(prefix='safe-c-layer-'));self.addCleanup(shutil.rmtree,d,True);(d/'scfixturewheel-1.0.0.dist-info').mkdir()
        spec=importlib.util.spec_from_file_location('bc_native_wheels',ROOT/'container/bench-coordinator.py')
        bc=importlib.util.module_from_spec(spec);spec.loader.exec_module(bc);bc.PROJECT_LAYER=d;saved=list(sys.path)
        try:
            with self.assertRaisesRegex(ValueError,'C build'):
                bc.configure_wheels({'job':'native-build','project_dir':FIXTURE,'project_wheels':{'path':str(d),'dist_info':['scfixturewheel-1.0.0.dist-info'],'modules':['scfixturewheel']}})
            self.assertNotIn(str(d),bc.PYTHONPATH)
        finally:sys.path[:]=saved


class RecipeTests(unittest.TestCase):
    """container/project-wheels.py on temporary directories (inside the unit gate container)."""
    def test_the_fixture_wheel_extracts_to_the_layer(self):
        work,manifest=run_recipe(self,ROOT/FIXTURE/bm.PROJECT_AREA,bm.third_party_lock(ROOT,FIXTURE))
        self.assertEqual(manifest['status'],'PROJECT_WHEELS_EXTRACTED');self.assertIs(manifest['wheel_code_executed'],False)
        self.assertEqual(manifest['dist_info'],['scfixturewheel-1.0.0.dist-info'])
        self.assertEqual(sorted(manifest['files']),['opt/project-python/scfixturewheel-1.0.0.dist-info/'+n for n in ('LICENSE','METADATA','RECORD','WHEEL')]+['opt/project-python/scfixturewheel/__init__.py'])
        self.assertTrue(all(r['mode']==0o444 for r in manifest['files'].values()))
        self.assertEqual(manifest['notices']['scfixturewheel']['sha256'],bm.third_party_lock(ROOT,FIXTURE)['wheels'][0]['notice']['sha256'])

    def extraction_refused(self,files,pattern,**kw):
        t=scratch(self);doc=lock_of(t);doc['wheels']=[add_wheel(t,files,**kw)]
        with self.assertRaisesRegex(ValueError,pattern):run_recipe(self,area(t),doc)

    def test_wrong_dist_info_modules_and_members_are_refused(self):
        info='scextra-2.0.dist-info/'
        ok={info+'METADATA':b'Name: scextra\n',info+'LICENSE':b'MIT\n','scextra/__init__.py':b''}
        self.extraction_refused({**ok,'other-2.0.dist-info/METADATA':b''},'dist-info')
        self.extraction_refused({k.replace('scextra-2.0','scextra-3.0'):v for k,v in ok.items()},'dist-info')
        self.extraction_refused({**ok,'stray.py':b''},'modules')
        self.extraction_refused({**ok,'scextra-2.0.data/purelib/x.py':b''},'data directory')
        self.extraction_refused({**ok,'../escape.py':b''},'unsafe')
        self.extraction_refused({**ok,'/abs.py':b''},'unsafe')
        link=zipfile.ZipInfo('scextra/link',date_time=(1980,1,1,0,0,0));link.external_attr=(0o120777)<<16
        self.extraction_refused({**ok,link:b'/etc/passwd'},'special')
        setuid=zipfile.ZipInfo('scextra/tool',date_time=(1980,1,1,0,0,0));setuid.external_attr=(0o104755)<<16
        self.extraction_refused({**ok,setuid:b'x'},'special')
        self.extraction_refused({info+'METADATA':b'','scextra/__init__.py':b''},'notice')

    def test_tests_and_bytecode_are_left_out_and_libs_are_allowed(self):
        t=scratch(self);info='scextra-2.0.dist-info/'
        files={info+'METADATA':b'',info+'LICENSE':b'MIT\n','scextra/__init__.py':b'','scextra/tests/test_x.py':b'','scextra/__pycache__/a.pyc':b'',
               'scextra.libs/libx.so':b'\x7fELF'}
        doc=lock_of(t);doc['wheels'].append(add_wheel(t,files,notice=b'MIT\n'))
        _,manifest=run_recipe(self,area(t),doc)
        names=sorted(manifest['files'])
        self.assertIn('opt/project-python/scextra.libs/libx.so',names)
        self.assertFalse(any('/tests/' in n or n.endswith('.pyc') for n in names))
        self.assertEqual(manifest['dist_info'],['scextra-2.0.dist-info','scfixturewheel-1.0.0.dist-info'])

    def test_the_layer_bounds_hold(self):
        r=recipe();t=scratch(self);info='scextra-2.0.dist-info/'
        doc=lock_of(t);doc['wheels']=[add_wheel(t,{info+'METADATA':b'',info+'LICENSE':b'MIT\n','scextra/__init__.py':b'x'*5000},method=zipfile.ZIP_DEFLATED)]
        self.assertLess(doc['wheels'][0]['bytes'],1000)
        for name,value,pattern in (('MAX_FILE',1000,'file bound'),('MAX_BYTES',16,'layer bound'),('MAX_FILES',1,'layer bound')):
            with self.subTest(bound=name):
                tmp=Path(tempfile.mkdtemp(prefix='safe-c-recipe-'));self.addCleanup(shutil.rmtree,tmp,True)
                (tmp/'inputs').mkdir();(tmp/'inputs/lock.json').write_text(json.dumps(doc))
                shutil.copyfile(area(t)/doc['wheels'][0]['parts'][0]['path'],tmp/'inputs'/Path(doc['wheels'][0]['parts'][0]['path']).name)
                r=recipe();r.INPUTS=tmp/'inputs';r.WORK=tmp/'work';setattr(r,name,value)
                with self.assertRaisesRegex(ValueError,pattern):r.main()

    def test_a_changed_part_is_refused_in_the_container_too(self):
        t=scratch(self);doc=lock_of(t);row=add_wheel(t,{'x':b''});doc['wheels']=[row];(area(t)/row['parts'][0]['path']).write_bytes(b'PK')
        with self.assertRaisesRegex(ValueError,'identity'):run_recipe(self,area(t),doc)
        t=scratch(self);doc=lock_of(t);doc['wheels'][0]['sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'identity'):run_recipe(self,area(t),doc)


def inspected(identity,layers,labels=None,user='1001:1001',size=1000,**config):
    return {'Id':identity,'RepoTags':[],'Size':size,'RootFS':{'Layers':list(layers)},'Config':{'Labels':labels,'User':user,**config}}

class ElfRecordTests(unittest.TestCase):
    """EX1-A02 (a): the extraction finds every ELF file that a project wheel carries by its magic bytes (never by its name)
    and records it with its wheel; the host checks that record against the bytes of the layer it unpacks."""
    ELF=b'\x7fELF\x02\x01\x01'+bytes(9)
    def wheel(self):
        t=scratch(self);info='scextra-2.0.dist-info/'
        files={info+'METADATA':b'',info+'LICENSE':b'MIT\n','scextra/__init__.py':b'',
               'scextra/_core.cpython-313-x86_64-linux-gnu.so':self.ELF+b'core',        # an extension module in the package
               '_scextra_top.cpython-313-x86_64-linux-gnu.so':self.ELF+b'top',          # an extension module at the top level
               'scextra.libs/libgfortran-0a1b2c3d.so.5.0.0':self.ELF+b'lib',            # a bundled shared library
               'scextra/bin/helper':self.ELF+b'program',                                # an ELF program without a suffix
               'scextra/linker-script.so':b'INPUT(libc.so.6)\n'}                       # a .so name that is no ELF file
        doc=lock_of(t);doc['wheels'].append(add_wheel(t,files,notice=b'MIT\n',modules=['scextra','_scextra_top']))
        work,manifest=run_recipe(self,area(t),doc)
        return doc,work,manifest
    def test_the_extraction_lists_every_elf_file_with_its_wheel(self):
        doc,work,manifest=self.wheel();L=ptp.LAYER_ROOT
        self.assertEqual(manifest['elf_files'],{L+'scextra/_core.cpython-313-x86_64-linux-gnu.so':'scextra',
                                               L+'_scextra_top.cpython-313-x86_64-linux-gnu.so':'scextra',
                                               L+'scextra.libs/libgfortran-0a1b2c3d.so.5.0.0':'scextra',L+'scextra/bin/helper':'scextra'})
        _,fixture=run_recipe(self,ROOT/FIXTURE/bm.PROJECT_AREA,bm.third_party_lock(ROOT,FIXTURE))
        self.assertEqual(fixture['elf_files'],{})                                        # the pure-Python fixture wheel carries none
    def test_the_host_refuses_an_elf_record_that_differs_from_the_layer(self):
        import project_image
        doc,work,manifest=self.wheel();L=ptp.LAYER_ROOT
        dest=Path(tempfile.mkdtemp(prefix='safe-c-layer-'));self.addCleanup(shutil.rmtree,dest,True)
        self.assertEqual(project_image.unpack(work,manifest,dest,doc)[1],len(manifest['files']))
        edits={'an ELF file left out':lambda m:m['elf_files'].pop(L+'scextra/bin/helper'),
               'a non-ELF file listed':lambda m:m['elf_files'].__setitem__(L+'scextra/linker-script.so','scextra'),
               'a wheel outside the lock':lambda m:m['elf_files'].__setitem__(L+'scextra/bin/helper','nosuchwheel'),
               'a path outside the layer files':lambda m:m['elf_files'].__setitem__(L+'scextra/missing.so','scextra'),
               'no record':lambda m:m.pop('elf_files'),
               'not an object':lambda m:m.__setitem__('elf_files',[])}
        for name,edit in edits.items():
            with self.subTest(name):
                m=copy.deepcopy(manifest);edit(m)
                out=Path(tempfile.mkdtemp(prefix='safe-c-layer-'));self.addCleanup(shutil.rmtree,out,True)
                with self.assertRaisesRegex(GateError,'ELF'):project_image.unpack(work,m,out,doc)


class WheelPathRuleTests(unittest.TestCase):
    """EX1-A02 (b): no first-party C build, analyzer, sanitizer or fuzz job names an include path, a library path or a link
    input in the project wheel layer (/opt/project-python) or in a project third-party tree
    (<project>/benchmarks/project/third_party). Each such job is refused with the stable reason project-wheel-path."""
    ROOT_DIR='/src/examples/x'
    def test_the_rule(self):
        import project_source as ps
        self.assertEqual((ps.PROJECT_WHEEL_LAYER,ps.WHEEL_PATH_REASON),(ptp.LAYER_PATH,'project-wheel-path'))
        hits=['-I/opt/project-python/scextra/include','-isystem/opt/project-python','/opt/project-python/scextra.libs/libx.so.1',
              '-L/opt/project-python/scextra.libs','-Wl,-rpath,/opt/project-python/lib','--sysroot=/opt/project-python',
              '-I/opt/./project-python/x','-I/opt//project-python/x','/usr/include:/opt/project-python/inc',
              '-I/opt/project-python-extra',                                           # any value that names the layer (fail closed)
              '-I/src/examples/x/benchmarks/project/third_party/retained','/src/examples/x/benchmarks/project/./third_party/wheels/a.whl']
        for value in hits:
            with self.subTest(hit=value):self.assertEqual(ps.wheel_path_hits([value],project_root=self.ROOT_DIR),[value])
        self.assertEqual(ps.wheel_path_hits(['-I../../opt/project-python'],project_root=self.ROOT_DIR,cwd='/work/build'),['-I../../opt/project-python'])
        self.assertEqual(ps.wheel_path_hits(['-I../third_party/x'],project_root=self.ROOT_DIR,cwd='/src/examples/x/benchmarks/project/python'),
                         ['-I../third_party/x'])
        self.assertEqual(ps.wheel_path_hits(['-I/src/benchmarks/project/third_party/h'],project_root='/src'),['-I/src/benchmarks/project/third_party/h'])
        clean=['-I/src/examples/x/include','-O2','/usr/lib/x86_64-linux-gnu/libm.so','-L/opt/foundation/lib','-I/src/foundation/include',
               '/src/examples/x/benchmarks/project/python/x.py','/src/third_party/NOTICE.md','-DTHIRD_PARTY=1','/opt/projectpython','']
        self.assertEqual(ps.wheel_path_hits(clean,project_root=self.ROOT_DIR),[])
        self.assertIsNone(ps.wheel_path_problem('gate asan compile command',clean,project_root=self.ROOT_DIR))
        problem=ps.wheel_path_problem('gate asan compile command',['cc','-I/opt/project-python'],project_root=self.ROOT_DIR)
        self.assertEqual(problem,'project-wheel-path: gate asan compile command names -I/opt/project-python')
    def test_a_dependency_in_the_layer_or_the_third_party_tree_has_the_stable_reason(self):
        import project_source as ps
        for path in ('/opt/project-python/scextra/x.h','/src/app/benchmarks/project/third_party/retained/y.h'):
            with self.subTest(path=path):
                got=ps.dependency_problems([path],'/src/app/src/a.c','app',set(),set())
                self.assertEqual(len(got),1,got);self.assertTrue(got[0]['problem'].startswith('project-wheel-path'),got)
        self.assertEqual(ps.dependency_problems(['/usr/include/stdio.h','/src/app/src/a.c'],'/src/app/src/a.c','app',set(),set()),[])
    def test_the_native_build_refuses_a_compile_command_that_names_the_layer(self):
        import bench_native as bn
        good=['clang','-O2','-ffp-contract=off','-c','/src/examples/x/src/a.c']
        self.assertEqual(bn.check_native_flags([good],self.ROOT_DIR),[])
        for extra in (['-I/opt/project-python/scextra'],['-isystem','/opt/project-python'],['-I/src/examples/x/benchmarks/project/third_party/h']):
            with self.subTest(extra=extra):
                got=bn.check_native_flags([good[:-2]+extra+good[-2:]],self.ROOT_DIR)
                self.assertTrue(got and 'project-wheel-path' in got[0],got)
        framework_unit=['clang','-O0','-I/opt/project-python','-c','/src/foundation/src/sc-foundation.c']   # judged for this rule too
        self.assertTrue(any('project-wheel-path' in p for p in bn.check_native_flags([framework_unit],self.ROOT_DIR)))
    def test_a_project_check_step_that_names_the_layer_is_refused_before_it_runs(self):
        import project_check as pc
        c=object.__new__(pc.ProjectCheck);c.project_dir='app';calls=[]
        c.launcher=type('Launcher',(),{'execute':lambda self,*a,**k:calls.append(a)})()
        for argv,env in ((['clang','-I/opt/project-python/x','-c','/src/app/src/a.c'],None),
                         (['bash','/src/container/project-fuzz-build.sh'],{'CFLAGS':'-O1 -I/opt/project-python'}),
                         (['clang','-L/src/app/benchmarks/project/third_party/lib','-c','/src/app/src/a.c'],None)):
            with self.subTest(argv=argv[1]),self.assertRaisesRegex(GateError,'^project-wheel-path: step x names '):
                c.step('x',argv,timeout=10,env=env)
        self.assertEqual(calls,[])


class FakeDocker:
    """A table of images; image ls honours label filters; build adds the image its Dockerfile names; records every call."""
    def __init__(self,images,tags=None,fail=()):
        self.images=images;self.tags=dict(tags or {});self.fail=set(fail);self.calls=[];self.built=None
    def ok(self,out):return {'exit_code':0,'failure':None,'output':out}
    def bad(self):return {'exit_code':1,'failure':None,'output':''}
    def resolve(self,ref):return ref if ref in self.images else self.tags.get(ref)
    def __call__(self,args,**kw):
        args=list(args);self.calls.append(args)
        if args[0] in self.fail:return self.bad()
        if args[:2]==['image','inspect']:
            i=self.resolve(args[2]);return self.ok(json.dumps([self.images[i]])) if i else self.bad()
        if args[:2]==['image','ls']:
            want=[a.split('=',1)[1] for a in args if a.startswith('label=')]
            def has(o,f):
                k,_,v=f.partition('=');return ((o['Config'].get('Labels') or {}).get(k))==v
            return self.ok(''.join(i+'\n' for i,o in self.images.items() if all(has(o,f) for f in want)))
        if args[:2]==['image','rm']:
            self.images.pop(args[2],None);self.tags={k:v for k,v in self.tags.items() if v!=args[2]};return self.ok('')
        if args[0]=='tag':
            self.tags[args[2]]=self.resolve(args[1]);return self.ok('')
        if args[0]=='build':
            context=Path(args[-1]);text=(context/'Dockerfile').read_text();self.built={'dockerfile':text,
                'files':sorted(p.relative_to(context/'layer').as_posix() for p in (context/'layer').rglob('*') if p.is_file()),
                'modes':{p.relative_to(context/'layer').as_posix():p.stat().st_mode&0o777 for p in (context/'layer').rglob('*')}}
            labels=dict(kv.split('=',1) for kv in text.splitlines()[2].split()[1:])
            base=self.images[self.resolve(text.splitlines()[0].split()[1])]
            new='sha256:'+'b'*64;self.images[new]=inspected(new,base['RootFS']['Layers']+['sha256:'+'f'*64],labels,size=base['Size']+4096)
            self.tags[args[args.index('--tag')+1]]=new;return self.ok('')
        raise AssertionError('unexpected docker call: '+' '.join(args))

class FakeLauncher:
    def __init__(self,docker,max_images=4):self.docker=docker;self.value={'aggregate':{'max_owned_images':max_images}}

def runtime_cache_image(c,name='other'):
    return inspected('sha256:'+c*64,['sha256:'+c*64],{'org.safe-c.project-runtime':'1','org.safe-c.project-name':name})

class ImageBuildTests(unittest.TestCase):
    def setUp(self):
        import project_image
        self.pi=project_image;self.t=scratch(self)
        self.sel=dict(project_image.selection(self.t,FIXTURE),developer_image_id=DEV)
        self.base=inspected(DEV,['sha256:'+'1'*64,'sha256:'+'2'*64],{},size=2_000_000_000)
        self.run_dir=Path(tempfile.mkdtemp(prefix='safe-c-image-run-'));self.addCleanup(shutil.rmtree,self.run_dir,True)
    def extractor(self,calls):
        def run(root,run_dir,sel,inputs):
            calls.append(sorted(p.name for p in Path(inputs).iterdir()))
            work,manifest=run_recipe(self,area(root),json.loads((Path(inputs)/'lock.json').read_text()));return work,manifest
        return run

    def test_the_selection_names_the_key_tag_and_plan_entry(self):
        sel=self.pi.selection(self.t,FIXTURE)
        self.assertEqual(sel['tag'],'safe-c-project-bench:'+sel['key'][:24]);self.assertEqual(sel['name'],'wheel-fixture')
        self.assertEqual(sel['plan']['dist_info'],['scfixturewheel-1.0.0.dist-info'])
        self.assertIsNone(self.pi.selection(self.t,None))
        doc=lock_of(self.t);doc['wheels']=[];rebind(self.t,doc);self.assertIsNone(self.pi.selection(self.t,FIXTURE))   # sources only: no image
        t=scratch(self);doc=lock_of(t);doc['owner']='MarketData-App team';rebind(t,doc)
        self.assertNotEqual(self.pi.selection(t,FIXTURE)['key'],sel['key'])     # another lock digest: another image

    def test_a_new_image_is_built_offline_as_one_data_layer(self):
        docker=FakeDocker({DEV:self.base,**{i['Id']:i for i in (runtime_cache_image('a'),)}});calls=[]
        record=self.pi.ensure_selected(self.t,self.sel,self.run_dir,launcher=FakeLauncher(docker),extractor=self.extractor(calls))
        self.assertEqual(calls,[['lock.json','scfixturewheel-1.0.0-py3-none-any.whl']])
        self.assertFalse(record['reused']);self.assertEqual(record['image_id'],'sha256:'+'b'*64);self.assertEqual(record['cache_images_before'],1)
        build=[c for c in docker.calls if c[0]=='build'][0]
        self.assertEqual(build[:5],['build','--pull=false','--network=none','--tag',self.sel['tag']])
        lines=docker.built['dockerfile'].splitlines()
        self.assertEqual(lines[0],'FROM safe-c-developer:base-'+'d'*24);self.assertEqual(lines[1],'COPY layer /');self.assertEqual(len(lines),3)
        self.assertNotIn('RUN',docker.built['dockerfile'])
        self.assertIn('org.safe-c.project-bench=1',lines[2]);self.assertIn('org.safe-c.project-bench-key='+self.sel['key'],lines[2])
        self.assertEqual(docker.built['files'][-1],'opt/project-python/scfixturewheel/__init__.py')
        self.assertTrue(all(m in (0o444,0o755) for m in docker.built['modes'].values()))
        self.assertTrue((self.run_dir/('project-image-'+self.sel['key'][:12])/'project-image.json').is_file())
        self.assertFalse(any(c[:2]==['image','rm'] for c in docker.calls))

    def test_an_existing_matching_image_is_reused_and_a_mismatch_blocks(self):
        good=inspected('sha256:'+'c'*64,self.base['RootFS']['Layers']+['sha256:'+'9'*64],
                       {'org.safe-c.project-bench':'1','org.safe-c.project-name':'wheel-fixture','org.safe-c.project-bench-key':self.sel['key']})
        docker=FakeDocker({DEV:self.base,good['Id']:good},tags={self.sel['tag']:good['Id']})
        record=self.pi.ensure_selected(self.t,self.sel,self.run_dir,launcher=FakeLauncher(docker),extractor=lambda *a:self.fail('no build'))
        self.assertTrue(record['reused']);self.assertEqual(record['image_id'],good['Id'])
        for change,why in ((lambda o:o['Config']['Labels'].update({'org.safe-c.project-bench-key':'0'*64}),'labels'),
                           (lambda o:o['RootFS']['Layers'].append('sha256:'+'8'*64),'layers'),
                           (lambda o:o['RootFS'].update(Layers=['sha256:'+'7'*64]*3),'layers'),
                           (lambda o:o['Config'].update(Entrypoint=['/bin/sh']),'entrypoint'),
                           (lambda o:o['Config'].update(User='0:0'),'user'),
                           (lambda o:o['Config']['Labels'].update({'org.safe-c.project-runtime':'1'}),'runtime')):
            with self.subTest(why=why):
                bad=copy.deepcopy(good);change(bad);docker=FakeDocker({DEV:self.base,bad['Id']:bad},tags={self.sel['tag']:bad['Id']})
                with self.assertRaisesRegex(GateError,why):
                    self.pi.ensure_selected(self.t,self.sel,self.run_dir,launcher=FakeLauncher(docker),extractor=lambda *a:self.fail('no build'))

    def test_a_missing_developer_image_blocks(self):
        with self.assertRaisesRegex(GateError,'developer image'):
            self.pi.ensure_selected(self.t,self.sel,self.run_dir,launcher=FakeLauncher(FakeDocker({})),extractor=lambda *a:self.fail('no build'))

    def test_a_notice_that_differs_from_the_wheel_license_blocks_before_any_image(self):
        notice=area(self.t)/'third_party/notices/scfixturewheel/LICENSE';notice.write_text('another text\n')
        doc=lock_of(self.t);doc['wheels'][0]['notice']['sha256']=file_hash(notice);rebind(self.t,doc)
        sel=dict(self.pi.selection(self.t,FIXTURE),developer_image_id=DEV);docker=FakeDocker({DEV:self.base})
        with self.assertRaisesRegex(GateError,'notice'):
            self.pi.ensure_selected(self.t,sel,self.run_dir,launcher=FakeLauncher(docker),extractor=self.extractor([]))
        self.assertFalse(any(c[0] in ('build','tag') for c in docker.calls))

    def test_the_owned_bound_counts_both_cache_kinds(self):
        bench=lambda c,name:inspected('sha256:'+c*64,['x'],{'org.safe-c.project-bench':'1','org.safe-c.project-name':name})
        images={DEV:self.base,**{i['Id']:i for i in (runtime_cache_image('a'),runtime_cache_image('e','p2'),bench('5','other'),bench('6','wheel-fixture'))}}
        docker=FakeDocker(dict(images))
        record=self.pi.ensure_selected(self.t,self.sel,self.run_dir,launcher=FakeLauncher(docker),extractor=self.extractor([]))
        self.assertEqual(record['cache_images_before'],3)               # this project's older bench image went first
        self.assertIn(['image','rm','sha256:'+'6'*64],docker.calls);self.assertNotIn(['image','rm','sha256:'+'5'*64],docker.calls)
        images.pop('sha256:'+'6'*64);images['sha256:'+'4'*64]=bench('4','third')
        docker=FakeDocker(dict(images))
        with self.assertRaisesRegex(GateError,'4 cache images exist; max_owned_images 4'):
            self.pi.ensure_selected(self.t,self.sel,self.run_dir,launcher=FakeLauncher(docker),extractor=self.extractor([]))
        self.assertFalse(any(c[0]=='build' for c in docker.calls))
        self.assertFalse(any(c[:2]==['image','rm'] for c in docker.calls))

    def test_too_many_added_bytes_remove_the_new_image(self):
        class Big(FakeDocker):
            def __call__(s,args,**kw):
                out=super().__call__(args,**kw)
                if args[0]=='build':s.images['sha256:'+'b'*64]['Size']=self.base['Size']+10**9
                return out
        docker=Big({DEV:self.base})
        with self.assertRaisesRegex(GateError,'added bytes'):
            self.pi.ensure_selected(self.t,self.sel,self.run_dir,launcher=FakeLauncher(docker),extractor=self.extractor([]))
        self.assertIn(['image','rm','sha256:'+'b'*64],docker.calls)

    def test_a_tampered_layer_archive_blocks(self):
        def tamper(root,run_dir,sel,inputs):
            work,manifest=self.extractor([])(root,run_dir,sel,inputs)
            (work/manifest['archives'][0]['name']).write_bytes(b'not the archive');return work,manifest
        with self.assertRaisesRegex(GateError,'archive identity'):
            self.pi.ensure_selected(self.t,self.sel,self.run_dir,launcher=FakeLauncher(FakeDocker({DEV:self.base})),extractor=tamper)
        def extra(root,run_dir,sel,inputs):
            work,manifest=self.extractor([])(root,run_dir,sel,inputs);manifest['files'].pop(sorted(manifest['files'])[0]);return work,manifest
        with self.assertRaisesRegex(GateError,'unsafe project layer member'):
            self.pi.ensure_selected(self.t,self.sel,self.run_dir,launcher=FakeLauncher(FakeDocker({DEV:self.base})),extractor=extra)


class CacheKindTests(unittest.TestCase):
    """tools/runtime_cache.py counts and evicts the project bench image as a second cache kind (FR4-IMG-BOUND-01)."""
    def setUp(self):
        import runtime_cache as rc
        self.rc=rc;self.tmp=tempfile.TemporaryDirectory();self.lock=rc.acquire_lock(str(Path(self.tmp.name)/'lock'),wait_seconds=1)
    def tearDown(self):
        self.lock.release();self.tmp.cleanup()
    def bench(self,c,tags=None,labels=None):
        o=inspected('sha256:'+c*64,['x'],labels or {'org.safe-c.project-bench':'1','org.safe-c.project-name':'wheel-fixture'})
        o['RepoTags']=tags if tags is not None else ['safe-c-project-bench:'+c*24];return o
    def runtime(self,c):
        o=runtime_cache_image(c);o['RepoTags']=['safe-c-project-runtime:'+c*24];return o
    def test_cache_ids_lists_both_kinds(self):
        images={i['Id']:i for i in (self.bench('a'),self.runtime('b'),inspected(DEV,['x'],{}))}
        self.assertEqual(self.rc.cache_ids(FakeDocker(images)),sorted(['sha256:'+'a'*64,'sha256:'+'b'*64]))
        with self.assertRaises(GateError):self.rc.cache_ids(FakeDocker(images,fail={'image'}))
    def test_unused_bench_images_are_evicted_and_others_kept(self):
        both=self.bench('c',labels={'org.safe-c.project-bench':'1','org.safe-c.project-runtime':'1','org.safe-c.project-name':'x'})
        wrongtag=self.bench('d',tags=['safe-c-project-runtime:'+'d'*24])
        images={i['Id']:i for i in (self.bench('a'),self.runtime('b'),both,wrongtag,self.bench('e',tags=[]))}
        class Ps(FakeDocker):
            def __call__(s,args,**kw):
                if args[0]=='ps':s.calls.append(list(args));return s.ok('')
                return super().__call__(args,**kw)
        docker=Ps(images)
        got=self.rc.evict_unused(docker,self.lock)
        self.assertEqual(sorted(got['evicted']),sorted(['sha256:'+'a'*64,'sha256:'+'b'*64]))
        self.assertEqual(sorted(got['refused']),sorted(['sha256:'+c*64 for c in 'cde']))
    def test_the_runtime_import_counts_both_kinds(self):
        import project_check as pc
        project={'name':'p','run':{'program':'x','args':[],'expect_exit':0}}
        bench=lambda c:inspected('sha256:'+c*64,['x'],{'org.safe-c.project-bench':'1','org.safe-c.project-name':'q'})
        for extra,pattern in ((('7','8'),'cache-image budget'),(('7',),'assembly failed')):
            with self.subTest(extra=extra):
                images={i['Id']:i for i in (self.runtime('a'),self.runtime('b'))};images.update({bench(c)['Id']:bench(c) for c in extra})
                class Docker(FakeDocker):
                    def __call__(s,args,**kw):
                        if args[0]=='import':s.calls.append(list(args));return s.bad()
                        return super().__call__(args,**kw)
                launcher=FakeLauncher(Docker(images));launcher.value['common']={'uid':1001,'gid':1001}
                with tempfile.TemporaryDirectory() as tmp,self.assertRaisesRegex(GateError,pattern):
                    pc.runtime_start(launcher,Path(tmp),project,{'bin/x':b'x'})


class SelectionTests(unittest.TestCase):
    """bench.BenchSession.select_image: a project job with wheels runs in the project image; the image is fixed per session."""
    def setUp(self):
        import bench
        self.session=bench.BenchSession(ROOT,Path(tempfile.mkdtemp(prefix='safe-c-select-')))
        self.addCleanup(self.session.close);self.addCleanup(shutil.rmtree,self.session.run_dir,True)
        self.calls=[]
    def ensure(self,root,sel,run_dir):
        self.calls.append(sel['key']);return {'key':sel['key'],'image_id':'sha256:'+'e'*64}
    def test_a_framework_or_lockless_job_keeps_the_developer_image(self):
        s=self.session;dev=s.developer_image
        for plan in ({'job':'doctor'},{'job':'unit','project_dir':None},{'job':'unit','project_dir':'examples/bench-demo'}):
            with self.subTest(plan=plan):
                self.assertEqual(s.select_image(plan,ensure=self.ensure),plan);self.assertEqual(s.lock['image_id'],dev)
        self.assertEqual(self.calls,[])
    def test_a_project_job_with_wheels_runs_in_the_project_image(self):
        s=self.session
        out=s.select_image({'job':'unit','project_dir':FIXTURE},ensure=self.ensure)
        self.assertEqual(out['project_wheels'],{'path':'/opt/project-python','dist_info':['scfixturewheel-1.0.0.dist-info'],'modules':['scfixturewheel']})
        self.assertEqual(s.lock['image_id'],'sha256:'+'e'*64)
        self.assertIs(s.runner.launcher.lock,s.lock)                   # the launcher image gate reads the same lock
        self.assertTrue(s.runner.launcher.image_gate('bench','sha256:'+'e'*64))
        with self.assertRaises(GateError):s.runner.launcher.image_gate('bench',s.developer_image)
        s.select_image({'job':'unit','project_dir':FIXTURE},ensure=self.ensure);self.assertEqual(len(self.calls),1)     # one ensure per session
        s.select_image({'job':'doctor'},ensure=self.ensure);self.assertEqual(s.lock['image_id'],s.developer_image)    # not started yet: may switch
    def test_a_started_session_refuses_another_image(self):
        s=self.session;s.select_image({'job':'unit','project_dir':FIXTURE},ensure=self.ensure);s.runner.alive=True
        try:
            with self.assertRaisesRegex(GateError,'one image'):s.select_image({'job':'doctor'},ensure=self.ensure)
            self.assertEqual(s.select_image({'job':'unit','project_dir':FIXTURE},ensure=self.ensure)['project_wheels']['modules'],['scfixturewheel'])
        finally:s.runner.alive=False


class SuiteTests(unittest.TestCase):
    def test_the_project_suites_hold_the_image_control_and_no_example_row(self):
        import bench
        rows=[]
        def quiet(fn,root,args):
            rows.append(args.project);return 0,{'suites':{'unit':{'status':'PASS','tests':4,'evidence_paths':['u.json']}}}
        with unittest.mock.patch.object(bench,'_quiet',quiet),unittest.mock.patch.object(bench,'registered_projects',lambda root,scope=None:[]):
            suites=bench.project_suites(ROOT,Path(tempfile.gettempdir()))
        self.assertEqual(rows,[FIXTURE])
        self.assertEqual(suites,{'project-image:'+FIXTURE:{'status':'PASS','property':'project bench image layer (fixture wheel)','tests':4,'evidence_paths':['u.json']}})
        self.assertEqual(bench._example_rows(suites),{})
        with unittest.mock.patch.object(bench,'_quiet',lambda fn,root,args:(2,{'suites':{'unit':{'status':'BLOCKED','reason':'no image'}}})):
            self.assertEqual(bench.project_image_suites(ROOT,Path(tempfile.gettempdir()))['project-image:'+FIXTURE]['status'],'BLOCKED')


class CoordinatorTests(unittest.TestCase):
    """container/bench-coordinator.py configure_wheels on a temporary layer directory."""
    def coordinator(self,layer):
        spec=importlib.util.spec_from_file_location('bc_project_wheels',ROOT/'container/bench-coordinator.py')
        bc=importlib.util.module_from_spec(spec);spec.loader.exec_module(bc);bc.PROJECT_LAYER=Path(layer);return bc
    def layer(self,*names):
        d=Path(tempfile.mkdtemp(prefix='safe-c-layer-'));self.addCleanup(shutil.rmtree,d,True)
        for n in names:(d/n).mkdir()
        return d
    def plan(self,layer,**kw):
        return {'project_dir':FIXTURE,'project_wheels':{'path':str(layer),'dist_info':['scfixturewheel-1.0.0.dist-info'],'modules':['scfixturewheel'],**kw}}
    def test_the_layer_joins_the_path_after_the_framework_wheels(self):
        layer=self.layer('scfixturewheel','scfixturewheel-1.0.0.dist-info');bc=self.coordinator(layer);saved=list(sys.path)
        try:
            self.assertEqual(bc.configure_wheels(self.plan(layer)),str(layer))
            self.assertEqual(bc.PYTHONPATH.split(':')[:2],['/opt/bench-python',str(layer)])
            self.assertEqual(bc.FRAMEWORK_PYTHONPATH.split(':')[:2],['/opt/bench-python',str(layer)])
            self.assertIn('scfixturewheel',bc.reserved_modules())
        finally:sys.path[:]=saved
        self.assertIsNone(self.coordinator(layer).configure_wheels({'project_dir':FIXTURE}))
    def test_a_wrong_layer_or_plan_is_refused(self):
        good=self.layer('scfixturewheel-1.0.0.dist-info')
        cases=[(self.layer(),{}),(self.layer('scfixturewheel-1.0.0.dist-info','extra-1.dist-info'),{}),(self.layer('scfixturewheel-2.0.dist-info'),{}),
               (good,{'modules':['numpy']}),(good,{'modules':['os']}),(good,{'dist_info':['../x.dist-info']}),(good,{'modules':[]}),(good,{'extra':1})]
        for layer,change in cases:
            with self.subTest(layer=sorted(p.name for p in layer.iterdir()),change=change):
                bc=self.coordinator(layer);saved=list(sys.path)
                try:
                    with self.assertRaises(ValueError):bc.configure_wheels(self.plan(layer,**change))
                finally:sys.path[:]=saved
        bc=self.coordinator(good)
        with self.assertRaises(ValueError):bc.configure_wheels({'project_wheels':self.plan(good)['project_wheels']})        # no project
        with self.assertRaises(ValueError):bc.configure_wheels(dict(self.plan(good),project_wheels=dict(self.plan(good)['project_wheels'],path='/opt/other')))
        missing=self.coordinator(Path(good)/'absent')
        with self.assertRaises(ValueError):missing.configure_wheels(self.plan(Path(good)/'absent'))


class AcquisitionTests(unittest.TestCase):
    """tools/acquire_bench_wheels.py fetch-project with a fake download function (no network)."""
    def test_fetch_project_keeps_parts_and_writes_a_candidate_row(self):
        import acquire_bench_wheels as aw
        t=scratch(self);data=build_fixture_wheel(SOURCE);name='scfixturewheel';filename='scfixturewheel-1.0.0-py3-none-any.whl'
        url='https://files.pythonhosted.org/packages/aa/'+filename
        def get(u,output=None):
            if output is None:
                self.assertEqual(u,f'https://pypi.org/pypi/{name}/1.0.0/json')
                return json.dumps({'urls':[{'packagetype':'bdist_wheel','filename':filename,'url':url,'digests':{'sha256':hashlib.sha256(data).hexdigest()},'size':len(data)}]})
            Path(output).write_bytes(data);return ''
        with unittest.mock.patch('sys.stdout',io.StringIO()):
            row=aw.fetch_project(t,FIXTURE,name,'1.0.0',get=get)
        self.assertEqual(row['parts'],[{'path':WHEEL,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}])
        self.assertEqual(row['tag'],'py3-none-any');self.assertEqual(row['origin'],{'kind':'pypi','url':url})
        self.assertIsNone(row['license']);self.assertTrue((t/'artifacts/third-party'/(filename+'.candidate.json')).is_file())
        with self.assertRaisesRegex(GateError,'exists'):aw.fetch_project(t,FIXTURE,name,'1.0.0',get=get)
        def bad(u,output=None):
            if output is None:return get(u)
            Path(output).write_bytes(data+b'x');return ''
        (area(t)/WHEEL).unlink()
        with self.assertRaisesRegex(GateError,'mismatch'):aw.fetch_project(t,FIXTURE,name,'1.0.0',get=bad)
        self.assertFalse((area(t)/WHEEL).exists())


# T6-R2 (ruling R27): host members. A wheel row of the lock may declare a few members above the container file bound. The
# extraction job hashes each one in bounded chunks and never writes it; the trusted host streams it from the verified wheel
# bytes into the layer. These tests re-state the assertions of the FR4 payload tests for the project layer, with generic
# names. Real-size members are zero bytes made and deflated at test time (a few kB on disk); no large file is tracked.
FILE_BOUND=33554432                 # safety/container-policy.json common.file_bytes: one file of any container
MEMBER_BOUND=50331648               # the host member bound (the FR4 member bound)
SMALL={'MAX_FILE':4096,'MAX_HOST_MEMBER':8192}       # scaled recipe bounds for the tests that write a host member
BIG='scbig.libs/libbig.so'

def member_body(size):
    """A host member made at test time: the ELF magic bytes, then zero bytes."""
    return b'\x7fELF'+bytes(size-4)

def big_wheel(t,members,name='scbig',executable=(),declare=None,extra=None):
    """Write the deflated wheel `name` with `members` ({member path: size}), its dist-info, its package and `extra` files;
    return its lock row with host_members for the members in `declare` (default: every member; none: no field)."""
    info=f'{name}-2.0.dist-info/';files={**(extra or {}),info+'METADATA':b'',info+'LICENSE':b'MIT\n',f'{name}/__init__.py':b'x = 1\n'}
    decl=[]
    for path,size in members.items():
        body=member_body(size);zi=zipfile.ZipInfo(path,date_time=(1980,1,1,0,0,0))
        zi.external_attr=(0o100755 if path in executable else 0o100644)<<16;files[zi]=body
        if declare is None or path in declare:decl.append({'member':path,'bytes':size,'sha256':hashlib.sha256(body).hexdigest()})
    row=add_wheel(t,files,name=name,notice=b'MIT\n',method=zipfile.ZIP_DEFLATED)
    if decl:row['host_members']=decl
    return row

def run_bounded(test,base,lock,**bounds):
    """run_recipe with the recipe bounds `bounds` set; returns (work directory, manifest, inputs directory)."""
    r=recipe();tmp=Path(tempfile.mkdtemp(prefix='safe-c-recipe-'));test.addCleanup(shutil.rmtree,tmp,True)
    (tmp/'inputs').mkdir();(tmp/'inputs/lock.json').write_text(json.dumps(lock))
    for w in lock['wheels']:
        if not w['parts']:(tmp/'inputs'/w['filename']).write_bytes(ptp.build_source_wheel(Path(base),w))
        for p in w['parts']:shutil.copyfile(Path(base)/p['path'],tmp/'inputs'/Path(p['path']).name)
    for name,value in bounds.items():
        test.assertTrue(hasattr(r,name),name);setattr(r,name,value)
    r.INPUTS=tmp/'inputs';r.WORK=tmp/'work';r.main()
    return r.WORK,json.loads((r.WORK/'manifest.json').read_text()),tmp/'inputs'

def host_bounds(file_bytes=4096,member_bytes=8192):
    """The host bounds scaled as SMALL (on the host, ptp.PART_MAX_BYTES is the container file bound)."""
    return unittest.mock.patch.multiple(ptp,PART_MAX_BYTES=file_bytes,HOST_MEMBER_MAX_BYTES=member_bytes)

def with_wheel(t,row,fixture=True):
    """The scratch lock with `row` added (and without the fixture wheel when `fixture` is false); not bound again."""
    doc=lock_of(t);doc['wheels']=(doc['wheels'] if fixture else [])+[row];return doc


class HostMemberRecipeTests(unittest.TestCase):
    """The extraction job (the real recipe on temporary directories) hashes a declared member above the container file bound
    in bounded chunks and never writes it; every other member keeps the file bound."""
    def test_the_bounds_are_named_constants_and_the_other_bounds_are_unchanged(self):
        r=recipe();schema=json.loads((ROOT/'schemas/project-third-party.json').read_text())['$defs']
        policy=json.loads((ROOT/'safety/container-policy.json').read_text())['common']['file_bytes']
        self.assertEqual((r.MAX_FILE,ptp.PART_MAX_BYTES,policy),(FILE_BOUND,)*3)
        self.assertEqual((r.MAX_HOST_MEMBER,ptp.HOST_MEMBER_MAX_BYTES),(MEMBER_BOUND,)*2)
        self.assertEqual(schema['host_member']['properties']['bytes'],{'type':'integer','minimum':FILE_BOUND+1,'maximum':MEMBER_BOUND})
        hosts=schema['wheel']['properties']['host_members']
        self.assertEqual((r.MAX_HOST_MEMBERS,ptp.HOST_MEMBERS_MAX,hosts['minItems'],hosts['maxItems']),(4,4,1,4))
        self.assertEqual((r.MAX_WHEEL,r.MAX_BYTES,r.MAX_FILES,r.MAX_MEMBERS),(67108864,201326592,3072,8192))
        self.assertEqual((ptp.ITEM_MAX_BYTES,ptp.LAYER_MAX_BYTES,ptp.LAYER_MAX_FILES),(67108864,201326592,3072))
        self.assertNotIn('host_members',schema['source']['properties']);self.assertNotIn('host_members',schema['retained']['properties'])

    def test_an_oversized_member_is_hashed_and_never_written(self):
        t=scratch(self);size=FILE_BOUND+1;row=big_wheel(t,{BIG:size});L=ptp.LAYER_ROOT
        work,manifest=run_recipe(self,area(t),with_wheel(t,row))
        self.assertEqual(manifest['host_members'],{L+BIG:{'name':BIG,'wheel':'scbig','bytes':size,'sha256':row['host_members'][0]['sha256'],'mode':0o444}})
        self.assertNotIn(L+BIG,manifest['files']);self.assertFalse((work/'extracted'/L/BIG).exists())
        self.assertFalse(any(L+BIG in a['files'] for a in manifest['archives']))
        self.assertTrue(all(p.stat().st_size<FILE_BOUND for p in work.rglob('*') if p.is_file()))     # no file of the job holds it
        self.assertEqual(manifest['payload_bytes'],sum(r['bytes'] for r in manifest['files'].values())+size)
        self.assertEqual(manifest['payload_files'],len(manifest['files'])+1)
        self.assertEqual(manifest['elf_files'],{L+BIG:'scbig'})                  # EX1-A02 (a): found by its bytes, a host member too
        self.assertEqual((manifest['bounds']['host_member_bytes'],manifest['bounds']['host_members_per_wheel']),(MEMBER_BOUND,4))
        _,plain=run_recipe(self,ROOT/FIXTURE/bm.PROJECT_AREA,bm.third_party_lock(ROOT,FIXTURE))
        self.assertEqual(plain['host_members'],{})

    def test_the_member_bound_exact_accepts_and_one_past_refuses(self):
        for size,ok in ((MEMBER_BOUND,True),(MEMBER_BOUND+1,False)):
            with self.subTest(size=size):
                t=scratch(self);doc=with_wheel(t,big_wheel(t,{BIG:size}))
                if ok:self.assertEqual(run_recipe(self,area(t),doc)[1]['host_members'][ptp.LAYER_ROOT+BIG]['bytes'],size)
                else:
                    with self.assertRaisesRegex(ValueError,'host member bound'):run_recipe(self,area(t),doc)
            self.doCleanups()               # the unit job's /tmp is 64 MiB: free each iteration's directories at once

    def test_the_file_bound_edge(self):
        """A declared member of exactly the container file bound is not oversized; an undeclared member one byte past it is
        refused as before."""
        t=scratch(self);doc=with_wheel(t,big_wheel(t,{BIG:FILE_BOUND}))
        with self.assertRaisesRegex(ValueError,'host member not oversized'):run_recipe(self,area(t),doc)
        self.doCleanups()
        t=scratch(self);doc=with_wheel(t,big_wheel(t,{BIG:FILE_BOUND+1},declare=()))
        with self.assertRaisesRegex(ValueError,'wheel file bound'):run_recipe(self,area(t),doc)

    def test_declared_member_identity_checks(self):
        """Scaled bounds (SMALL): each refusal of a declared member, and of an undeclared member above the file bound."""
        def refused(pattern,members,change=lambda row:None,**kw):
            t=scratch(self);row=big_wheel(t,members,**kw);change(row)
            with self.assertRaisesRegex(ValueError,pattern):run_bounded(self,area(t),with_wheel(t,row),**SMALL)
        first=lambda row:row['host_members'][0]
        cases={'a size that differs':('host member identity mismatch',{BIG:6000},lambda row:first(row).update(bytes=5999)),
               'a digest that differs':('host member identity mismatch',{BIG:6000},lambda row:first(row).update(sha256='0'*64)),
               'a member that the wheel does not hold':('host member missing',{BIG:6000},
                    lambda row:row['host_members'].append({'member':'scbig.libs/absent.so','bytes':6000,'sha256':'0'*64})),
               'a member that the layer leaves out':('host member missing',{'scbig/tests/big.so':6000}),
               'a member declared twice':('duplicate host member',{BIG:6000},lambda row:row['host_members'].append(dict(first(row)))),
               'an undeclared member':('wheel file bound',{BIG:6000},lambda row:row.pop('host_members')),
               'a member at the file bound':('host member not oversized',{BIG:4096}),
               'a member one past the member bound':('host member bound',{BIG:8193}),
               'five members':('host member count bound',{f'scbig.libs/lib{i}.so':6000 for i in range(5)})}
        for name,case in cases.items():
            with self.subTest(name):refused(*case)
            self.doCleanups()
        twice=zipfile.ZipInfo(BIG,date_time=(1980,1,1,0,0,0));twice.external_attr=0o100644<<16
        t=scratch(self)
        with warnings.catch_warnings():
            warnings.simplefilter('ignore');row=big_wheel(t,{BIG:6000},extra={twice:member_body(6000)})     # the zip holds it twice
        with self.assertRaisesRegex(ValueError,'duplicate wheel member'):run_bounded(self,area(t),with_wheel(t,row),**SMALL)

    def test_the_layer_bounds_count_host_members(self):
        """The layer byte and file bounds count a host member as a written file (scaled bounds; exact and one past)."""
        t=scratch(self);doc=with_wheel(t,big_wheel(t,{BIG:6000}),fixture=False)
        _,manifest,_=run_bounded(self,area(t),doc,**SMALL)
        size,count=manifest['payload_bytes'],manifest['payload_files']
        self.assertEqual((size,count),(sum(r['bytes'] for r in manifest['files'].values())+6000,len(manifest['files'])+1))
        for bound,value,ok in (('MAX_BYTES',size,True),('MAX_BYTES',size-1,False),('MAX_FILES',count,True),('MAX_FILES',count-1,False)):
            with self.subTest(bound=bound,value=value):
                if ok:self.assertEqual(run_bounded(self,area(t),doc,**SMALL,**{bound:value})[1]['payload_bytes'],size)
                else:
                    with self.assertRaisesRegex(ValueError,'project layer bound'):run_bounded(self,area(t),doc,**SMALL,**{bound:value})


class HostMemberHostTests(unittest.TestCase):
    """The trusted host (tools/project_image.py) checks the manifest record of the host members against the lock and streams
    each member from the verified wheel bytes into the layer, with the layer and image bounds counting it."""
    def setUp(self):
        import project_image
        self.pi=project_image
    def case(self,members=None,bounds=SMALL):
        t=scratch(self);doc=with_wheel(t,big_wheel(t,members or {BIG:6000},executable=(BIG,)))
        work,manifest,inputs=run_bounded(self,area(t),doc,**bounds)
        return doc,work,manifest,inputs
    def layer(self):
        d=Path(tempfile.mkdtemp(prefix='safe-c-layer-'));self.addCleanup(shutil.rmtree,d,True);return d

    def test_the_host_writes_each_declared_member_from_the_verified_wheel(self):
        doc,work,manifest,inputs=self.case();L=ptp.LAYER_ROOT;dest=self.layer()
        with host_bounds():total,count=self.pi.unpack(work,manifest,dest,doc,inputs)
        target=dest/L/BIG
        self.assertEqual(target.read_bytes(),member_body(6000));self.assertEqual(target.stat().st_mode&0o777,0o555)
        self.assertEqual((total,count),(sum(r['bytes'] for r in manifest['files'].values())+6000,len(manifest['files'])+1))
        self.assertEqual(sorted(p.relative_to(dest).as_posix() for p in dest.rglob('*') if p.is_file()),sorted([*manifest['files'],L+BIG]))
        self.assertEqual(manifest['elf_files'],{L+BIG:'scbig'})          # the host checks this record against the streamed bytes

    def test_host_streaming_exact_accepts_and_one_past_refuses(self):
        """Real constants through the chunk loop (member_chunks; no write: the unit job has the container file bound itself, so
        no real-size member can be written here), then scaled bounds with the write."""
        body=member_body(MEMBER_BOUND);row={'bytes':MEMBER_BOUND,'sha256':hashlib.sha256(body).hexdigest()}
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w',zipfile.ZIP_DEFLATED) as z:z.writestr(BIG,body)
        with zipfile.ZipFile(data) as z,z.open(BIG) as stream:
            self.assertEqual(sum(len(c) for c in self.pi.member_chunks(stream,row,BIG)),MEMBER_BOUND)
        self.assertTrue(all(len(c)<=self.pi.READ_CHUNK for c in self.pi.member_chunks(io.BytesIO(body),row,BIG)))
        past=body+b'\0'
        with self.assertRaisesRegex(GateError,'host member bound'):
            for _ in self.pi.member_chunks(io.BytesIO(past),{'bytes':MEMBER_BOUND+1,'sha256':hashlib.sha256(past).hexdigest()},BIG):pass
        with self.assertRaisesRegex(GateError,'identity mismatch'):        # more bytes than declared
            for _ in self.pi.member_chunks(io.BytesIO(body),dict(row,bytes=MEMBER_BOUND-1),BIG):pass
        with self.assertRaisesRegex(GateError,'identity mismatch'):        # fewer bytes than declared
            for _ in self.pi.member_chunks(io.BytesIO(body[:-1]),row,BIG):pass
        del body,past,data
        doc,work,manifest,inputs=self.case({BIG:8192});dest=self.layer()
        with host_bounds():self.pi.unpack(work,manifest,dest,doc,inputs)
        self.assertEqual((dest/ptp.LAYER_ROOT/BIG).stat().st_size,8192)
        self.doCleanups()
        doc,work,manifest,inputs=self.case({BIG:8193},bounds={'MAX_FILE':4096,'MAX_HOST_MEMBER':8193});dest=self.layer()
        with host_bounds(),self.assertRaisesRegex(GateError,'host member bound'):self.pi.unpack(work,manifest,dest,doc,inputs)
        self.assertEqual([p for p in dest.rglob('*')],[])                   # refused before any write

    def test_the_host_refuses_undeclared_or_changed_host_members(self):
        L=ptp.LAYER_ROOT;T=L+BIG;other='scbig.libs/absent.so';up='../../escape.so'
        record=lambda m:m['host_members'][T]
        def rename(member):
            return lambda m:m.update(host_members={L+member:dict(record(m),name=member)})
        def declare(**change):
            return lambda w:w['host_members'][0].update(change)
        def part(inputs,w):
            p=inputs/Path(w['parts'][0]['path']).name;p.write_bytes(p.read_bytes()+b'x')
        cases={'a record that the lock does not declare':dict(pattern='host members differ from the lock',lock=lambda w:w.pop('host_members')),
               'a declaration without a record':dict(pattern='host members differ from the lock',manifest=lambda m:m.update(host_members={})),
               'no record':dict(pattern='manifest incomplete',manifest=lambda m:m.pop('host_members')),
               'another size':dict(pattern='host member differs from the lock',manifest=lambda m:record(m).update(bytes=6001)),
               'another digest':dict(pattern='host member differs from the lock',manifest=lambda m:record(m).update(sha256='0'*64)),
               'another wheel':dict(pattern='host member differs from the lock',manifest=lambda m:record(m).update(wheel='scfixturewheel')),
               'a mode outside the layer modes':dict(pattern='host member differs from the lock',manifest=lambda m:record(m).update(mode=0o755)),
               'a mode that the wheel does not give':dict(pattern='host member mode differs from the wheel',manifest=lambda m:record(m).update(mode=0o444)),
               'a record that is also a written file':dict(pattern='unsafe project layer host member',
                    manifest=lambda m:m['files'].__setitem__(T,{'sha256':'0'*64,'bytes':1,'mode':0o444})),
               'a path outside the layer':dict(pattern='unsafe project layer host member',manifest=rename(up),lock=declare(member=up)),
               'a member that the wheel does not hold':dict(pattern='host member identity mismatch',manifest=rename(other),lock=declare(member=other)),
               'other member bytes':dict(pattern='host member identity mismatch',manifest=lambda m:record(m).update(sha256='0'*64),lock=declare(sha256='0'*64)),
               'a changed wheel part':dict(pattern='project wheel part changed',inputs=part),
               'another wheel digest':dict(pattern='project wheel differs from the lock',lock=lambda w:w.update(sha256='0'*64)),
               'a member that is not oversized':dict(pattern='host member not oversized',bounds={'file_bytes':6000}),
               'a member above the member bound':dict(pattern='host member bound',bounds={'member_bytes':5999}),
               'no wheel inputs':dict(pattern='verified wheel inputs',no_inputs=True)}
        for name,c in cases.items():
            with self.subTest(name):
                doc,work,manifest,inputs=self.case();dest=self.layer()
                c.get('manifest',lambda m:None)(manifest);c.get('lock',lambda w:None)(doc['wheels'][-1]);c.get('inputs',lambda i,w:None)(inputs,doc['wheels'][-1])
                with host_bounds(**c.get('bounds',{})),self.assertRaisesRegex(GateError,c['pattern']):
                    self.pi.unpack(work,manifest,dest,doc,None if c.get('no_inputs') else inputs)
                self.assertFalse((dest/T).exists())                     # never a partial member
            self.doCleanups()

    def test_the_host_layer_bounds_count_host_members(self):
        doc,work,manifest,inputs=self.case()
        size=sum(r['bytes'] for r in manifest['files'].values())+6000;count=len(manifest['files'])+1
        for name,value,ok in (('LAYER_MAX_BYTES',size,True),('LAYER_MAX_BYTES',size-1,False),('LAYER_MAX_FILES',count,True),('LAYER_MAX_FILES',count-1,False)):
            with self.subTest(bound=name,value=value):
                dest=self.layer()
                with host_bounds(),unittest.mock.patch.object(ptp,name,value):
                    if ok:self.assertEqual(self.pi.unpack(work,manifest,dest,doc,inputs),(size,count))
                    else:
                        with self.assertRaisesRegex(GateError,'total bound exceeded|manifest incomplete'):self.pi.unpack(work,manifest,dest,doc,inputs)

    def test_the_image_build_counts_host_members_in_the_payload_and_the_size_rule(self):
        t=scratch(self);doc=with_wheel(t,big_wheel(t,{BIG:6000},executable=(BIG,)))
        sel=dict(self.pi.selection(t,FIXTURE),developer_image_id=DEV,lock=doc)
        base=inspected(DEV,['sha256:'+'1'*64,'sha256:'+'2'*64],{},size=2_000_000_000);manifests=[]
        def extractor(root,run_dir,sel,inputs):
            r=recipe();tmp=Path(tempfile.mkdtemp(prefix='safe-c-recipe-'));self.addCleanup(shutil.rmtree,tmp,True)
            for name,value in SMALL.items():setattr(r,name,value)
            r.INPUTS=Path(inputs);r.WORK=tmp/'work';r.main();manifests.append(json.loads((r.WORK/'manifest.json').read_text()))
            return r.WORK,manifests[-1]
        def build(added):
            class Sized(FakeDocker):
                def __call__(s,args,**kw):
                    out=super().__call__(args,**kw)
                    if args[0]=='build':s.images['sha256:'+'b'*64]['Size']=base['Size']+added
                    return out
            docker=Sized({DEV:base});run_dir=self.layer()
            with host_bounds():return self.pi.ensure_selected(t,sel,run_dir,launcher=FakeLauncher(docker),extractor=extractor),docker
        record,docker=build(4096);files=manifests[-1]['files']
        self.assertEqual((record['payload_bytes'],record['payload_files']),(sum(r['bytes'] for r in files.values())+6000,len(files)+1))
        self.assertIn(ptp.LAYER_ROOT+BIG,docker.built['files']);self.assertEqual(docker.built['modes'][ptp.LAYER_ROOT+BIG],0o555)
        limit=2*(record['payload_bytes']+self.pi.BLOCK*record['payload_files'])+self.pi.METADATA_ALLOWANCE
        self.assertFalse(build(limit)[0]['reused'])
        with self.assertRaisesRegex(GateError,'added bytes'):build(limit+1)

    def test_the_image_key_binds_the_declarations_the_recipe_and_the_assembler(self):
        t=scratch(self);doc=lock_of(t);row=add_wheel(t,{'scextra/__init__.py':b''});doc['wheels'].append(row);rebind(t,doc)
        keys=[self.pi.selection(t,FIXTURE)['key']]
        row['host_members']=[{'member':'scextra.libs/libx.so','bytes':FILE_BOUND+1,'sha256':'a'*64}];rebind(t,doc)
        keys.append(self.pi.selection(t,FIXTURE)['key'])
        row['host_members'][0]['sha256']='b'*64;rebind(t,doc);keys.append(self.pi.selection(t,FIXTURE)['key'])
        for rel in (self.pi.RECIPE,self.pi.ASSEMBLER):
            with open(t/rel,'a') as f:f.write('\n')
            keys.append(self.pi.selection(t,FIXTURE)['key'])
        self.assertEqual(len(set(keys)),len(keys))


class HostMemberLockTests(unittest.TestCase):
    """The lock field host_members (schemas/project-third-party.json and project_third_party.check_lock)."""
    def load(self,hosts,mutate=None):
        t=scratch(self);doc=lock_of(t);row=add_wheel(t,{'scextra/__init__.py':b''})
        if hosts is not None:row['host_members']=hosts
        doc['wheels'].append(row)
        if mutate:mutate(doc)
        rebind(t,doc);return bm.third_party_lock(t,FIXTURE)
    def decl(self,member='scextra.libs/libx.so',size=FILE_BOUND+1):
        return {'member':member,'bytes':size,'sha256':'a'*64}

    def test_declarations_within_the_bounds_load(self):
        for hosts in ([self.decl()],[self.decl(size=MEMBER_BOUND)],[self.decl(f'scextra.libs/lib{i}.so') for i in range(4)],
                      [self.decl('scextra/_core.abi3.so'),self.decl('scextra/bin/tool+x-1.0')]):
            with self.subTest(hosts=hosts):self.assertEqual(self.load(hosts)['wheels'][-1]['host_members'],hosts)
            self.doCleanups()
        self.assertNotIn('host_members',self.load(None)['wheels'][-1])

    def test_declarations_outside_the_bounds_are_refused(self):
        refused={'at the file bound':[self.decl(size=FILE_BOUND)],'one past the member bound':[self.decl(size=MEMBER_BOUND+1)],
                 'five members':[self.decl(f'scextra.libs/lib{i}.so') for i in range(5)],'an empty list':[],
                 'a size that is no integer':[dict(self.decl(),bytes=str(FILE_BOUND+1))],'a short digest':[dict(self.decl(),sha256='a'*63)],
                 'another key':[dict(self.decl(),path='third_party/x.so')],'no digest':[{'member':'scextra.libs/libx.so','bytes':FILE_BOUND+1}],
                 **{'the path '+p:[self.decl(p)] for p in ('../x.so','/abs.so','a//b.so','./a.so','a/../b.so','a\\b.so','.hidden/x.so','a/b/','')}}
        for name,hosts in refused.items():
            with self.subTest(name),self.assertRaises(GateError):self.load(hosts)
            self.doCleanups()
        with self.assertRaisesRegex(GateError,'repeats a host member'):self.load([self.decl(),dict(self.decl(),sha256='b'*64)])
        # the named host constants govern check_lock too (the schema holds the same numbers)
        with unittest.mock.patch.object(ptp,'HOST_MEMBER_MAX_BYTES',MEMBER_BOUND-1),self.assertRaisesRegex(GateError,'host member'):
            self.load([self.decl(size=MEMBER_BOUND)])
        with unittest.mock.patch.object(ptp,'HOST_MEMBERS_MAX',1),self.assertRaisesRegex(GateError,'host member'):
            self.load([self.decl('a.so'),self.decl('b.so')])

    def test_only_a_wheel_of_tracked_parts_declares_host_members(self):
        with self.assertRaisesRegex(GateError,'first-party fixture wheel declares no host member'):
            self.load(None,mutate=lambda d:d['wheels'][0].update(host_members=[self.decl('scfixturewheel/x.so')]))


# T6-R3 (ruling R33). T6R2-A01: a wheel data directory of the scheme `data` (its files stay out of the layer) and a
# lock-declared notice member. T6R2-A02: the host record bounds and the host-only branches at the real constants.
# T6R2-A03: control characters in member paths. Every loop frees its temporary directories at once (the 64 MiB /tmp).
DD='scdata-2.0.data/data/'
DATA_NOTICE=DD+'share/doc/scdata/LICENSE.TXT'

def entry(name,mode=0o100644):
    """A zip entry with a fixed time stamp and the unix mode `mode` (a directory entry when the name ends with '/')."""
    zi=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0));zi.external_attr=(0o40755 if name.endswith('/') else mode)<<16;return zi

def data_files(extra=None):
    """The members of the wheel scdata 2.0: a dist-info without a license file, a package, and a `data` scheme tree that
    holds the license file and one more file."""
    return {'scdata-2.0.dist-info/METADATA':b'Name: scdata\n','scdata/__init__.py':b'x = 1\n',DATA_NOTICE:b'Data License\n',
            DD+'share/scdata/table.txt':b'rows\n',**(extra or {})}

def data_row(t,files,name='scdata',version='2.0',notice=b'Data License\n',notice_member=DATA_NOTICE,modules=None):
    """add_wheel of `files` (deflated); the row declares `notice_member` when it is not None."""
    row=add_wheel(t,files,name=name,version=version,modules=modules,notice=notice,method=zipfile.ZIP_DEFLATED)
    if notice_member is not None:row['notice_member']=notice_member
    return row

def scaled_host_case(test,members=None,bounds=SMALL):
    """(lock, work, manifest, inputs) of the fixture wheel plus a wheel with executable host members (default: one of 6000
    bytes), extracted by the real recipe with `bounds`."""
    t=scratch(test);doc=with_wheel(t,big_wheel(t,members or {BIG:6000},executable=tuple(members or {BIG:6000})))
    work,manifest,inputs=run_bounded(test,area(t),doc,**bounds)
    return doc,work,manifest,inputs

def new_layer(test):
    d=Path(tempfile.mkdtemp(prefix='safe-c-layer-'));test.addCleanup(shutil.rmtree,d,True);return d


class WheelDataTests(unittest.TestCase):
    """T6R2-A01: the recipe admits a wheel data directory of the scheme `data` and leaves its files out of the layer; every
    other scheme stays refused; the directory name matches the lock; every member bound still applies."""
    def manifest(self,files,bounds=None,change=None,**row):
        t=scratch(self);row=data_row(t,files,**row)
        if change:change(row)
        return run_bounded(self,area(t),with_wheel(t,row,fixture=False),**(bounds or {}))[1]
    def refused(self,files,pattern,bounds=None,change=None,**row):
        with self.assertRaisesRegex(ValueError,pattern):self.manifest(files,bounds,change,**row)
        self.doCleanups()

    def test_a_data_scheme_tree_is_admitted_and_left_out_of_the_layer(self):
        t=scratch(self);L=ptp.LAYER_ROOT
        doc=with_wheel(t,data_row(t,data_files({entry('scdata-2.0.data/'):b'',entry(DD):b''})))
        work,manifest=run_recipe(self,area(t),doc)
        self.assertEqual(sorted(n for n in manifest['files'] if n.startswith(L+'scdata')),[L+'scdata-2.0.dist-info/METADATA',L+'scdata/__init__.py'])
        self.assertFalse((work/'extracted'/L/'scdata-2.0.data').exists())
        self.assertFalse(any('.data/' in n for a in manifest['archives'] for n in a['files']))
        self.assertEqual(manifest['data_files'],{'scfixturewheel':0,'scdata':2})
        self.assertEqual(manifest['notices']['scdata'],{'path':DATA_NOTICE,'sha256':hashlib.sha256(b'Data License\n').hexdigest(),'declared':True})
        self.assertEqual((work/'notices/scdata/LICENSE.TXT').read_bytes(),b'Data License\n')
        self.assertEqual(manifest['notices']['scfixturewheel']['path'],L+'scfixturewheel-1.0.0.dist-info/LICENSE')     # the search rule
        self.assertIs(manifest['notices']['scfixturewheel']['declared'],False)
        self.assertEqual(manifest['dist_info'],['scdata-2.0.dist-info','scfixturewheel-1.0.0.dist-info'])
        self.doCleanups()
        # the data directory name matches without case, as the dist-info name does; it is never a module
        files={(k.replace('scdata-2.0.','ScData-2.0.') if isinstance(k,str) else k):v for k,v in data_files().items()}
        m=self.manifest(files,notice_member=DATA_NOTICE.replace('scdata-2.0.','ScData-2.0.'))
        self.assertEqual((m['data_files'],m['dist_info']),({'scdata':2},['ScData-2.0.dist-info']))

    def test_every_other_data_scheme_is_refused(self):
        for scheme in ('purelib','platlib','scripts','headers','unknown'):
            with self.subTest(scheme=scheme):self.refused(data_files({f'scdata-2.0.data/{scheme}/x.py':b''}),'^wheel data directory scheme is not supported$')
        for name,extra in (('a file in the data directory',{'scdata-2.0.data/loose.txt':b''}),
                           ('an empty other scheme',{entry('scdata-2.0.data/purelib/'):b''}),
                           ('a top-level file with the data directory name',{'scdata-2.0.data':b''})):
            with self.subTest(name):self.refused(data_files(extra),'^wheel data directory scheme is not supported$')

    def test_the_data_directory_name_matches_the_lock(self):
        for top in ('other-2.0.data','scdata-3.0.data','scdata.data'):
            with self.subTest(top=top):self.refused(data_files({f'{top}/data/x.txt':b''}),'^wheel data directory name differs from the lock$')

    def test_data_members_keep_the_member_bounds(self):
        self.assertEqual(self.manifest(data_files({DD+'big.bin':bytes(4096)}),{'MAX_FILE':4096})['data_files'],{'scdata':3})    # exact
        self.doCleanups()
        self.refused(data_files({DD+'big.bin':bytes(4097)}),'^wheel file bound$',{'MAX_FILE':4096})                           # one past
        self.refused(data_files({DD+'../../escape.txt':b''}),'unsafe wheel member path')
        self.refused(data_files({entry(DD+'link',0o120777):b'/etc/hosts'}),'^special wheel member$')
        self.refused(data_files({entry(DD+'tool',0o104755):b'x'}),'^special wheel member$')
        body=member_body(6000)
        self.refused(data_files({DD+'big.so':body}),'^host member missing$',SMALL,
                     change=lambda r:r.update(host_members=[{'member':DD+'big.so','bytes':6000,'sha256':hashlib.sha256(body).hexdigest()}]))
        self.assertEqual(self.manifest(data_files({DD+'x':b''}),{'MAX_MEMBERS':5})['data_files'],{'scdata':3})                  # entries count
        self.doCleanups()
        self.refused(data_files({DD+'x':b''}),'^wheel member count bound$',{'MAX_MEMBERS':4})


class NoticeMemberTests(unittest.TestCase):
    """T6R2-A01: a wheel row may declare its notice member; the recipe takes exactly that member (bounded), and without the
    declaration the dist-info search stays. The host compares the notice digest with the lock as before."""
    INFO='scx-2.0.dist-info/'
    def files(self,extra=None):
        return {self.INFO+'METADATA':b'',self.INFO+'COPYING':b'Other text\n',self.INFO+'licenses/LICENSE':b'Declared text\n','scx/__init__.py':b'',
                **(extra or {})}
    def manifest(self,files,bounds=None,**row):
        t=scratch(self);doc=with_wheel(t,data_row(t,files,name='scx',notice=b'lock copy\n',**row),fixture=False)
        return run_bounded(self,area(t),doc,**(bounds or {}))[1]
    def refused(self,files,pattern,bounds=None,**row):
        with self.assertRaisesRegex(ValueError,pattern):self.manifest(files,bounds,**row)
        self.doCleanups()

    def test_the_declared_member_is_the_notice_and_the_search_rule_stays(self):
        sha=lambda b:hashlib.sha256(b).hexdigest();I=self.INFO
        self.assertEqual(self.manifest(self.files(),notice_member=I+'licenses/LICENSE')['notices']['scx'],
                         {'path':I+'licenses/LICENSE','sha256':sha(b'Declared text\n'),'declared':True})
        self.assertEqual(self.manifest(self.files(),notice_member=None)['notices']['scx'],          # no declaration: the first match
                         {'path':ptp.LAYER_ROOT+I+'COPYING','sha256':sha(b'Other text\n'),'declared':False})
        self.assertEqual(self.manifest(self.files(),{'MAX_NOTICE':14},notice_member=I+'licenses/LICENSE')['notices']['scx']['sha256'],
                         sha(b'Declared text\n'))                                                  # exactly at the notice bound
        self.doCleanups()

    def test_a_declared_member_is_refused_when_absent_a_directory_too_large_special_twice_or_elsewhere(self):
        I=self.INFO;outside='^wheel notice member outside the dist-info and data directories$'
        cases=(('absent',self.files(),I+'LICENSE','^wheel notice member missing$',None),
               ('a directory',self.files({entry(I+'licenses/'):b''}),I+'licenses','^wheel notice member is a directory$',None),
               ('one past the notice bound',self.files(),I+'licenses/LICENSE','^wheel notice member bound$',{'MAX_NOTICE':13}),
               ('a special type',self.files({entry(I+'NOTICE',0o120777):b'COPYING'}),I+'NOTICE','^special wheel member$',None),
               ('a package file',self.files({'scx/LICENSE':b'x'}),'scx/LICENSE',outside,None),
               ('another data scheme',self.files({'scx-2.0.data/data/LICENSE':b'x'}),'scx-2.0.data/purelib/LICENSE',outside,None),
               ('the data scheme directory',self.files({'scx-2.0.data/data/LICENSE':b'x'}),'scx-2.0.data/data',outside,None),
               ('the dist-info directory',self.files(),'scx-2.0.dist-info',outside,None),
               ('another dist-info directory',self.files(),'other-2.0.dist-info/LICENSE',outside,None))
        for name,files,member,pattern,bounds in cases:
            with self.subTest(name):self.refused(files,pattern,bounds,notice_member=member)
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            self.refused(self.files({entry('scx-2.0.data/data/LICENSE'):b'one\n',entry('scx-2.0.data/data/LICENSE'+''):b'two\n'}),
                         '^wheel notice member twice$',notice_member='scx-2.0.data/data/LICENSE')

    def test_the_host_checks_the_declared_notice_digest(self):
        import project_image as pi
        t=scratch(self);doc=with_wheel(t,data_row(t,data_files()))
        sel=dict(pi.selection(t,FIXTURE),developer_image_id=DEV,lock=doc)
        base=inspected(DEV,['sha256:'+'1'*64,'sha256:'+'2'*64],{},size=2_000_000_000)
        def extractor(root,run_dir,sel,inputs):
            r=recipe();tmp=Path(tempfile.mkdtemp(prefix='safe-c-recipe-'));self.addCleanup(shutil.rmtree,tmp,True)
            r.INPUTS=Path(inputs);r.WORK=tmp/'work';r.main();return r.WORK,json.loads((r.WORK/'manifest.json').read_text())
        record=pi.ensure_selected(t,sel,new_layer(self),launcher=FakeLauncher(FakeDocker({DEV:base})),extractor=extractor)
        self.assertFalse(record['reused'])
        bad=copy.deepcopy(doc);notice=area(t)/bad['wheels'][-1]['notice']['path'];notice.write_bytes(b'Another text\n')
        bad['wheels'][-1]['notice']['sha256']=file_hash(notice);docker=FakeDocker({DEV:base})
        with self.assertRaisesRegex(GateError,'^wheel notice differs from the license file in the wheel: scdata$'):
            pi.ensure_selected(t,dict(sel,lock=bad),new_layer(self),launcher=FakeLauncher(docker),extractor=extractor)
        self.assertFalse(any(c[0] in ('build','tag') for c in docker.calls))


class NoticeMemberLockTests(unittest.TestCase):
    """The lock field notice_member (T6R2-A01) and control characters in member paths (T6R2-A03): the schema and
    project_third_party.check_lock."""
    def load(self,change):
        t=scratch(self);doc=lock_of(t);row=add_wheel(t,{'scextra/__init__.py':b''});change(row);doc['wheels'].append(row)
        rebind(t,doc);return bm.third_party_lock(t,FIXTURE)
    def refused(self,change):
        with self.assertRaises(GateError) as caught:self.load(change)
        self.doCleanups();return str(caught.exception)

    def test_a_notice_member_in_the_dist_info_or_the_data_scheme_loads(self):
        for member in ('scextra-2.0.dist-info/LICENSE','scextra-2.0.dist-info/licenses/LICENSE.txt','scextra-2.0.data/data/share/doc/scextra/LICENSE.TXT',
                       'SCEXTRA-2.0.dist-info/LICENSE','ScExtra-2.0.data/data/COPYING'):
            with self.subTest(member=member):self.assertEqual(self.load(lambda r:r.update(notice_member=member))['wheels'][-1]['notice_member'],member)
            self.doCleanups()
        self.assertNotIn('notice_member',self.load(lambda r:None)['wheels'][-1])

    def test_a_notice_member_elsewhere_or_with_a_control_character_is_refused(self):
        place='a notice member lies outside the dist-info directory and the data scheme directory of its wheel: scextra'
        for member,text in (('scextra/LICENSE',place),('scextra-3.0.dist-info/LICENSE',place),('scextra-2.0.data/purelib/LICENSE',place),
                            ('scextra-2.0.data/data',place),('scextra-2.0.dist-info',place),('other-2.0.dist-info/LICENSE',place),
                            ('scextra-2.0.dist-info/LICENSE\n','a notice member path holds a control character: scextra')):
            with self.subTest(member=member):self.assertEqual(self.refused(lambda r:r.update(notice_member=member)),text)
        for member in ('../x','/abs/LICENSE','a//b','a\\b','.hidden/LICENSE','','scextra-2.0.dist-info/LICENSE\tx'):     # the schema pattern
            with self.subTest(member=member):self.refused(lambda r:r.update(notice_member=member))

    def test_a_host_member_with_a_control_character_is_refused(self):
        """T6R2-A03: jsonschema `$` admits one trailing newline, so check_lock refuses every control character."""
        decl={'member':'scextra.libs/libx.so\n','bytes':FILE_BOUND+1,'sha256':'a'*64}
        self.assertEqual(self.refused(lambda r:r.update(host_members=[decl])),'a host member path holds a control character: scextra')
        self.assertEqual(self.load(lambda r:r.update(host_members=[dict(decl,member='scextra.libs/libx.so')]))['wheels'][-1]['host_members'][0]['member'],
                         'scextra.libs/libx.so')

    def test_the_notice_bound_and_the_member_path_rule_are_named(self):
        r=recipe();schema=json.loads((ROOT/'schemas/project-third-party.json').read_text())['$defs']
        self.assertEqual((r.MAX_NOTICE,ptp.RECORD_MAX_BYTES),(1048576,1048576))
        self.assertEqual(r.DATA_SCHEME,'data')
        self.assertEqual(schema['wheel']['properties']['notice_member']['pattern'],schema['host_member']['properties']['member']['pattern'])
        self.assertEqual(schema['wheel']['properties']['notice_member']['maxLength'],200)
        self.assertNotIn('notice_member',schema['source']['properties']);self.assertNotIn('notice_member',schema['retained']['properties'])


class HostMemberRealConstantTests(unittest.TestCase):
    """T6R2-A02: tools/project_image.py at the real constants. A real-size member never reaches the disk: the 'xb' open of
    stream_host_members gets a sink that creates the target empty and hashes the streamed bytes (the unit job has a 64 MiB
    /tmp and the 32 MiB file bound). Then the three host-only branches (scaled bounds)."""
    EDGE={'scbig.libs/liblow.so':FILE_BOUND+1,'scbig.libs/libhigh.so':MEMBER_BOUND}
    def setUp(self):
        import project_image
        self.pi=project_image
    def sink(self):
        """(patch of the module's open, {path: sink}): mode 'xb' gets a hashing sink; every other mode the real open."""
        opened,real={},open
        class Sink:
            def __init__(s,path):
                Path(path).touch(exist_ok=False);s.hasher=hashlib.sha256();s.count=0;opened[Path(path)]=s
            def write(s,chunk):
                s.hasher.update(chunk);s.count+=len(chunk);return len(chunk)
            def __enter__(s):return s
            def __exit__(s,*exc):return False
        def fake(path,mode='r',*a,**kw):
            return Sink(path) if mode=='xb' else real(path,mode,*a,**kw)
        return unittest.mock.patch.object(self.pi,'open',fake,create=True),opened
    def case(self):
        t=scratch(self);doc=with_wheel(t,big_wheel(t,self.EDGE,executable=('scbig.libs/libhigh.so',)))
        work,manifest,inputs=run_bounded(self,area(t),doc)            # the real recipe constants: it hashes both, writes neither
        return doc,work,manifest,inputs

    def test_unpack_at_the_real_constants_streams_both_edge_members_through_a_hashing_sink(self):
        doc,work,manifest,inputs=self.case();L=ptp.LAYER_ROOT;dest=new_layer(self);patch,opened=self.sink()
        with patch:total,count=self.pi.unpack(work,manifest,dest,doc,inputs)
        decl={h['member']:h for h in doc['wheels'][-1]['host_members']}
        self.assertEqual({p.relative_to(dest).as_posix():(s.count,s.hasher.hexdigest()) for p,s in opened.items()},
                         {L+m:(h['bytes'],h['sha256']) for m,h in decl.items()})
        self.assertEqual((total,count),(sum(r['bytes'] for r in manifest['files'].values())+FILE_BOUND+1+MEMBER_BOUND,len(manifest['files'])+2))
        self.assertEqual({m:(dest/L/m).stat().st_mode&0o777 for m in decl},{'scbig.libs/liblow.so':0o444,'scbig.libs/libhigh.so':0o555})
        self.assertEqual(sorted(manifest['elf_files']),sorted(L+m for m in decl))
        self.assertTrue(all((dest/L/m).stat().st_size==0 for m in decl))                 # the sink wrote nothing

    def test_the_one_past_records_are_refused_before_any_write(self):
        doc,work,manifest,inputs=self.case();L=ptp.LAYER_ROOT
        for member,size,pattern in (('scbig.libs/liblow.so',FILE_BOUND,'^project layer host member not oversized: '),
                                    ('scbig.libs/libhigh.so',MEMBER_BOUND+1,'^project layer host member bound: ')):
            with self.subTest(member=member,size=size):
                d=copy.deepcopy(doc);m=copy.deepcopy(manifest);dest=new_layer(self);patch,opened=self.sink()
                next(h for h in d['wheels'][-1]['host_members'] if h['member']==member)['bytes']=size;m['host_members'][L+member]['bytes']=size
                with patch,self.assertRaisesRegex(GateError,pattern+re.escape(L+member)+'$'):self.pi.unpack(work,m,dest,d,inputs)
                self.assertEqual((opened,list(dest.iterdir())),({},[]))

    def test_the_host_only_branches(self):
        """The recipe refuses these first, so only a changed input reaches the host: a special-type zip member, a zip that holds
        the member twice (the input part rewritten and bound again in the lock row), and the early refusal when the host
        bytes alone pass the layer byte bound."""
        def rewrite(doc,inputs,entries):
            row=doc['wheels'][-1];data=io.BytesIO()
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                with zipfile.ZipFile(data,'w',zipfile.ZIP_DEFLATED) as z:
                    for zi,body in entries:
                        zi.compress_type=zipfile.ZIP_DEFLATED;z.writestr(zi,body)     # a ZipInfo keeps its own type (stored)
            data=data.getvalue();digest=hashlib.sha256(data).hexdigest()
            (inputs/Path(row['parts'][0]['path']).name).write_bytes(data)
            row.update(sha256=digest,bytes=len(data));row['parts'][0].update(sha256=digest,bytes=len(data))
        body=member_body(6000)
        for name,entries,pattern in (('a special-type member',[(entry(BIG,0o120777),body)],'^project layer host member mode differs from the wheel: '),
                                     ('the member twice',[(entry(BIG,0o100755),body),(entry(BIG,0o100755),body)],'^project layer host member identity mismatch: ')):
            with self.subTest(name):
                doc,work,manifest,inputs=scaled_host_case(self);dest=new_layer(self);rewrite(doc,inputs,entries)
                with host_bounds(),self.assertRaisesRegex(GateError,pattern):self.pi.unpack(work,manifest,dest,doc,inputs)
                self.assertFalse((dest/ptp.LAYER_ROOT/BIG).exists())
            self.doCleanups()
        doc,work,manifest,inputs=scaled_host_case(self);dest=new_layer(self)
        with host_bounds(),unittest.mock.patch.object(ptp,'LAYER_MAX_BYTES',5999),self.assertRaisesRegex(GateError,'^project layer total bound exceeded$'):
            self.pi.unpack(work,manifest,dest,doc,inputs)
        self.assertEqual(list(dest.iterdir()),[])                                         # refused before any archive member


if __name__=='__main__':unittest.main()
