"""EX1-A03: the privacy hook's pinned route for third-party project wheels (.githooks/personal_info_check.py).

A file under <project>/benchmarks/project/third_party/wheels/ is pinned only when the protected project lock of the same
project, at the same revision, lists its exact path, sha256 and size under a wheel row whose origin is a PyPI URL that
names the wheel file. Every unlisted, mismatched or first-party archive stays an `unpinned-archive` finding.

These Python tests run the hook logic in the unit gate. .githooks/tests/regression.sh runs the hooks on real commits (the
privacy workflow).

FW-HOOK (fact F14, ruling C8): every other file under <project>/benchmarks/project/third_party/ is exempt from the content
rules only when the project lock of the same revision binds its exact path, sha256 and size (a source part, a retained
file, or a provenance or notice record with its size) in a row whose origin URL is on the upstream allowlist that the
lock schema also holds. A path that the lock binds with other bytes is the finding project-lock-mismatch. The lock itself,
every name and every unbound file get every rule. .githooks/tests/regression.sh holds the same cases as real commits."""
import contextlib, hashlib, importlib.util, io, json, os, re, subprocess, sys, tarfile, tempfile, unittest, zipfile
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[2]

def hook():
    spec=importlib.util.spec_from_file_location('personal_info_check_ex1',ROOT/'.githooks/personal_info_check.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def wheel_bytes(text='clean upstream content'):
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_STORED) as z:z.writestr(zipfile.ZipInfo('up/__init__.py',date_time=(1980,1,1,0,0,0)),text)
    return out.getvalue()

FILE='up-1.0-py3-none-any.whl'

def lock(data,path='third_party/wheels/'+FILE,url='https://files.pythonhosted.org/packages/ab/'+FILE,kind='pypi',size=None):
    return {'schema_version':1,'wheels':[{'name':'up','version':'1.0','filename':FILE,'origin':{'kind':kind,'url':url},
            'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),
            'parts':[{'path':path,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data) if size is None else size}]}],'sources':[]}

class HookCase(unittest.TestCase):
    def setUp(self):
        self.hook=hook();self.tmp=tempfile.TemporaryDirectory();self.old=os.getcwd();os.chdir(self.tmp.name)
        s=object.__new__(self.hook.Scanner);s.pins={};s.findings=[];s.rules=[];s.path_rules=[];s.raw=[];self.scanner=s
    def tearDown(self):
        os.chdir(self.old);self.tmp.cleanup()
    def write_lock(self,project,value):
        p=Path(project)/'benchmarks/project/third_party/lock.json' if project else Path('benchmarks/project/third_party/lock.json')
        p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value))
        Path(project or '.','project.json').write_text('{"schema_version": 1}\n')      # T4-A02: a lock counts only in a project root
    def findings(self,path,data,rev=None):
        self.scanner.findings=[];self.scanner.content(path,path,data,rev);return list(self.scanner.findings)

class ProjectWheelPinTests(HookCase):
    def test_a_listed_pypi_wheel_with_its_exact_path_digest_and_size_is_accepted(self):
        data=wheel_bytes()
        for project in ('examples/demo','',):
            with self.subTest(project=project):
                self.write_lock(project,lock(data))
                path=(project+'/' if project else '')+'benchmarks/project/third_party/wheels/'+FILE
                self.assertEqual(self.findings(path,data),[])
                self.assertTrue(self.scanner.project_pinned(path,data,None))

    def test_a_listed_part_of_a_split_wheel_is_accepted(self):
        data=wheel_bytes()[:40];part=FILE+'.part-00'
        self.write_lock('examples/demo',lock(data,path='third_party/wheels/'+part))
        self.assertTrue(self.scanner.project_pinned('examples/demo/benchmarks/project/third_party/wheels/'+part,data,None))

    def test_an_unlisted_or_mismatched_archive_is_refused(self):
        data=wheel_bytes();path='examples/demo/benchmarks/project/third_party/wheels/'+FILE
        self.assertEqual(self.findings(path,data),[path+': unpinned-archive'])                     # no lock at all
        cases={'other digest':(lock(wheel_bytes('other')),path),
               'other size':(lock(data,size=len(data)+1),path),
               'other path':(lock(data,path='third_party/wheels/other-1.0-py3-none-any.whl'),path),
               'no upstream URL':(lock(data,url=None,kind='first-party-fixture'),path),
               'other host':(lock(data,url='https://example.org/packages/'+FILE),path),
               'URL names another file':(lock(data,url='https://files.pythonhosted.org/packages/ab/other.whl'),path),
               'listed for another project':(lock(data),'examples/other/benchmarks/project/third_party/wheels/'+FILE),
               'outside the wheels directory':(lock(data,path='third_party/sources/'+FILE),'examples/demo/benchmarks/project/third_party/sources/'+FILE)}
        for name,(value,target) in cases.items():
            with self.subTest(case=name):
                self.write_lock('examples/demo',value)
                self.assertIn(target+': unpinned-archive',self.findings(target,data))
        self.write_lock('examples/demo',{'wheels':'not a list'});self.assertIn(path+': unpinned-archive',self.findings(path,data))
        Path('examples/demo/benchmarks/project/third_party/lock.json').write_text('{')
        self.assertIn(path+': unpinned-archive',self.findings(path,data))

    def test_a_linked_lock_is_ignored(self):
        data=wheel_bytes();real=Path('real-lock.json');real.write_text(json.dumps(lock(data)))
        p=Path('examples/demo/benchmarks/project/third_party/lock.json');p.parent.mkdir(parents=True);p.symlink_to(Path.cwd()/real)
        Path('examples/demo/project.json').write_text('{"schema_version": 1}\n')       # T4-A02: a real project root, so only the link refuses
        self.assertFalse(self.scanner.project_pinned('examples/demo/benchmarks/project/third_party/wheels/'+FILE,data,None))

    def test_the_index_and_commit_revisions_read_the_lock_at_that_revision(self):
        data=wheel_bytes();calls=[]
        def git(*args,binary=False,check=True):
            calls.append(args);return json.dumps(lock(data)).encode() if args[:2]==('cat-file','blob') else b''
        self.hook.git=git
        path='examples/demo/benchmarks/project/third_party/wheels/'+FILE
        self.assertTrue(self.scanner.project_pinned(path,data,':'))
        self.assertTrue(self.scanner.project_pinned(path,data,'abc123'))
        self.assertEqual(sorted(c[2] for c in calls),[':examples/demo/benchmarks/project/third_party/lock.json',':examples/demo/project.json',     # T4-A02: also
                                                      'abc123:examples/demo/benchmarks/project/third_party/lock.json','abc123:examples/demo/project.json'])   # project.json

    def test_other_archives_keep_their_old_rule(self):
        data=wheel_bytes()
        self.assertEqual(self.findings('tools/first-party.whl',data),['tools/first-party.whl: unpinned-archive'])
        self.write_lock('examples/demo',lock(data))
        self.assertEqual(self.findings('examples/demo/benchmarks/project/'+FILE,data),['examples/demo/benchmarks/project/'+FILE+': unpinned-archive'])

class ProjectWheelNameTests(HookCase):
    """EX1-R1-02: the pinned route accepts only a wheel: the lock row filename ends in .whl, and the part file name is
    that filename or that filename plus the fixed split-part suffix .part-NN (two digits). Any other file name is not
    pinned, so the hook still scans its text."""
    def row(self,data,filename,part,url_name=None):
        value=lock(data,path='third_party/wheels/'+part,url='https://files.pythonhosted.org/packages/ab/'+(url_name or filename))
        value['wheels'][0]['filename']=filename;return value
    def test_a_lock_row_whose_filename_is_no_wheel_pins_nothing_and_the_text_is_scanned(self):
        import re
        data=b'notes with SECRETWORD inside\n';self.scanner.rules=[('test-rule',re.compile('SECRETWORD'))]
        for filename,part in (('notes.txt','notes.txt'),('notes.txt','notes.txt.part-00'),('up-1.0.whl.txt','up-1.0.whl.txt'),('up-1.0-py3-none-any.WHL','up-1.0-py3-none-any.WHL')):
            with self.subTest(filename=filename,part=part):
                self.write_lock('examples/demo',self.row(data,filename,part))
                path='examples/demo/benchmarks/project/third_party/wheels/'+part
                self.assertFalse(self.scanner.project_pinned(path,data,None))
                self.assertTrue(any('test-rule' in f for f in self.findings(path,data)),self.scanner.findings)
    def test_a_part_name_must_be_the_filename_or_the_fixed_part_suffix(self):
        data=wheel_bytes()[:40]
        for part in (FILE+'.txt',FILE+'.part-0',FILE+'.part-000',FILE+'.part-0a',FILE+'.part-00.txt',FILE+'x',FILE+'.part_00',FILE+'.part-00\n'):
            with self.subTest(part=part):
                self.write_lock('examples/demo',self.row(data,FILE,part))
                self.assertFalse(self.scanner.project_pinned('examples/demo/benchmarks/project/third_party/wheels/'+part,data,None))
        for part in (FILE,FILE+'.part-00',FILE+'.part-07',FILE+'.part-99'):
            with self.subTest(accepted=part):
                self.write_lock('examples/demo',self.row(data,FILE,part))
                self.assertTrue(self.scanner.project_pinned('examples/demo/benchmarks/project/third_party/wheels/'+part,data,None))

AT=chr(64)
UPSTREAM_EMAIL='maintainer'+AT+'upstream-project.org'           # synthetic, built at run time
NOTICE=('Copyright upstream authors <'+UPSTREAM_EMAIL+'>\n').encode()
GH='https://github.com/upstream-org/up/releases/download/v1.0/up-1.0.tar.gz'
P='examples/demo/benchmarks/project/'
ALLOWED_URLS=(GH,'https://github.com/upstream-org/up/archive/refs/tags/v1.0.tar.gz',
              'https://archives.boost.io/release/1.0.0/source/up_1_0_0.tar.bz2','https://files.pythonhosted.org/packages/ab/cd/up-1.0.tar.gz')

def digest_ref(path,data,size=True):
    ref={'path':path,'sha256':hashlib.sha256(data).hexdigest()}
    if size:ref['bytes']=len(data)
    return ref

def other_ref(name):return {'path':'third_party/records/'+name,'sha256':'0'*64,'bytes':1}

def source_archive():
    out=io.BytesIO();body=('upstream authors: '+UPSTREAM_EMAIL+'\n').encode()
    with tarfile.open(fileobj=out,mode='w:gz') as t:
        info=tarfile.TarInfo('up-1.0/AUTHORS');info.size=len(body);t.addfile(info,io.BytesIO(body))
    return out.getvalue()

def upstream_row(kind='retained',url=GH,origin='upstream-archive',parts=(),files=(),notice=None,provenance=None):
    """One lock row of an upstream origin: a source row (with parts) or a retained row (files only)."""
    row={'name':'up','version':'1.0','origin':{'kind':origin,'url':url},'files':list(files),
         'provenance':provenance or other_ref('provenance.json'),'notice':notice or other_ref('NOTICE'),
         'license':{'tags':['MIT'],'owner':'upstream-fixture','review_status':'PENDING'}}
    if kind=='source':row.update(filename='up-1.0.tar.gz',sha256='0'*64,bytes=1,parts=list(parts) or [other_ref('up-1.0.tar.gz')])
    return row

def project_lock(rows):
    value={'schema_version':1,'owner':'upstream-fixture','sanitizer_boundary':'none','wheels':[],'sources':[],'retained':[]}
    for row in rows:value['sources' if 'parts' in row else 'retained'].append(row)
    return value

class ProjectBoundFileTests(HookCase):
    """FW-HOOK (fact F14): the content of any other file under a project third_party area is exempt only through the project
    lock of the same revision. The scanner uses the generic rules only (no local values)."""
    def setUp(self):
        super().setUp();self.scanner.rules=[(name,re.compile(rx)) for name,rx in self.hook.GENERIC.items()]
    def categories(self,path,data,rev=None):
        return {f.rsplit(': ',1)[-1].split(' ')[0] for f in self.findings(path,data,rev)}
    def revisions(self,locks):
        """A fake git that returns locks[rev] for the project lock at rev ('' is the index)."""
        def git(*args,binary=False,check=True):
            rev,_,path=args[2].partition(':') if len(args)>2 else ('','','')
            hit=args[:2]==('cat-file','blob') and path==P+'third_party/lock.json' and rev in locks
            root=args[:2]==('cat-file','blob') and path=='examples/demo/project.json' and rev in locks     # T4-A02: the project root
            return json.dumps(locks[rev]).encode() if hit else b'{"schema_version": 1}' if root else b''
        self.hook.git=git

    def test_a_bound_file_of_an_allowlisted_row_is_exempt(self):
        archive=source_archive()
        cases={'notice':(NOTICE,'third_party/notices/up/LICENSE',lambda r,u:upstream_row(url=u,notice=r)),
               'provenance':(b'{"from": "'+UPSTREAM_EMAIL.encode()+b'"}\n','third_party/provenance/up.json',lambda r,u:upstream_row(url=u,provenance=r)),
               'retained file':(NOTICE,'third_party/sources/up-1.0/include/up.hpp',lambda r,u:upstream_row(url=u,files=[r])),
               'source part':(archive,'third_party/sources/up-1.0.tar.gz',lambda r,u:upstream_row('source',url=u,parts=[r])),
               'source file':(NOTICE,'third_party/notices/up/AUTHORS',lambda r,u:upstream_row('source',url=u,files=[r]))}
        for project in ('examples/demo',''):
            for name,(data,rel,make) in cases.items():
                for url in ALLOWED_URLS:
                    with self.subTest(project=project,case=name,url=url):
                        self.write_lock(project,project_lock([make(digest_ref(rel,data),url)]))
                        path=(project+'/' if project else '')+'benchmarks/project/'+rel
                        self.assertEqual(self.findings(path,data),[])
                        self.assertTrue(self.scanner.project_pinned(path,data,None))
        row=upstream_row('source',origin='pypi',url='https://files.pythonhosted.org/packages/ab/up-1.0.tar.gz',
                         parts=[digest_ref('third_party/sources/up-1.0.tar.gz',archive)])
        self.write_lock('examples/demo',project_lock([row]))                 # a PyPI source row whose URL names the file
        self.assertEqual(self.findings(P+'third_party/sources/up-1.0.tar.gz',archive),[])

    def test_one_changed_byte_is_a_mismatch_and_every_rule_applies(self):
        rel='third_party/notices/up/LICENSE';path=P+rel
        self.write_lock('examples/demo',project_lock([upstream_row(notice=digest_ref(rel,NOTICE))]))
        changed=NOTICE.replace(b'Copyright',b'copyright')
        self.assertEqual(self.categories(path,changed),{'project-lock-mismatch','email-address'})
        self.assertFalse(self.scanner.project_pinned(path,changed,None))
        self.assertEqual(self.findings(path,b'clean upstream text\n'),[path+': project-lock-mismatch'])    # clean bytes too
        self.write_lock('examples/demo',project_lock([upstream_row(notice=dict(digest_ref(rel,NOTICE),bytes=len(NOTICE)+1))]))
        self.assertEqual(self.categories(path,NOTICE),{'project-lock-mismatch','email-address'})          # another size
        self.write_lock('examples/demo',project_lock([upstream_row(notice=digest_ref(rel,NOTICE),url='https://example.org/up.tar.gz')]))
        self.assertEqual(self.categories(path,changed),{'project-lock-mismatch','email-address'})          # any origin
        archive=source_archive();rel='third_party/sources/up-1.0.tar.gz'
        self.write_lock('examples/demo',project_lock([upstream_row('source',parts=[digest_ref(rel,archive)])]))
        self.assertEqual(self.categories(P+rel,archive+b'\0'),{'project-lock-mismatch','unpinned-archive','email-address'})

    def test_an_unbound_file_gets_every_rule(self):
        self.write_lock('examples/demo',project_lock([upstream_row(notice=digest_ref('third_party/notices/up/LICENSE',NOTICE))]))
        for rel in ('third_party/notices/up/COPYING','third_party/sources/up-1.0/README'):
            with self.subTest(rel=rel):self.assertEqual(self.categories(P+rel,NOTICE),{'email-address'})
        self.assertEqual(self.categories(P+'third_party/sources/up-1.0.tar.gz',source_archive()),{'unpinned-archive','email-address'})
        self.assertEqual(self.categories('examples/other/benchmarks/project/third_party/notices/up/LICENSE',NOTICE),{'email-address'})
        Path(P+'third_party/lock.json').write_text('{')
        self.assertEqual(self.categories(P+'third_party/notices/up/LICENSE',NOTICE),{'email-address'})    # a malformed lock

    def test_a_record_without_its_size_is_not_exempt(self):
        rel='third_party/notices/up/LICENSE'
        self.write_lock('examples/demo',project_lock([upstream_row(notice=digest_ref(rel,NOTICE,size=False))]))
        self.assertEqual(self.categories(P+rel,NOTICE),{'email-address'})        # the digest matches: no mismatch, no exemption
        self.write_lock('examples/demo',project_lock([upstream_row(notice=dict(digest_ref(rel,NOTICE),bytes=True))]))
        self.assertIn('email-address',self.categories(P+rel,NOTICE))

    def test_a_row_outside_the_allowlist_exempts_nothing(self):
        archive=source_archive();rel='third_party/sources/up-1.0.tar.gz';part=[digest_ref(rel,archive)]
        rows={'other host':upstream_row('source',url='https://downloads.example.net/up/up-1.0.tar.gz',parts=part),
              'plain http':upstream_row('source',url='http://github.com/upstream-org/up/releases/download/v1.0/up-1.0.tar.gz',parts=part),
              'GitHub page, no release':upstream_row('source',url='https://github.com/upstream-org/up/blob/main/up-1.0.tar.gz',parts=part),
              'first-party origin':upstream_row('source',url=None,origin='first-party-fixture',parts=part),
              'unknown origin kind':upstream_row('source',origin='mirror',parts=part),
              'no origin':{k:v for k,v in upstream_row('source',parts=part).items() if k!='origin'},
              'PyPI URL names another file':upstream_row('source',origin='pypi',url='https://files.pythonhosted.org/packages/ab/other-1.0.tar.gz',parts=part),
              'PyPI kind on another host':upstream_row('source',origin='pypi',url=GH,parts=part)}
        for name,row in rows.items():
            with self.subTest(case=name):
                self.write_lock('examples/demo',project_lock([row]))
                self.assertEqual(self.categories(P+rel,archive),{'unpinned-archive','email-address'})
                self.assertFalse(self.scanner.project_pinned(P+rel,archive,None))

    def test_a_wheel_row_exempts_its_records_only_as_a_pypi_wheel(self):
        rel='third_party/notices/up/LICENSE';data=wheel_bytes()
        good=lock(data);good['wheels'][0]['notice']=digest_ref(rel,NOTICE);good['wheels'][0]['files']=[digest_ref('third_party/notices/up/AUTHORS',NOTICE)]
        self.write_lock('examples/demo',good)
        self.assertEqual(self.findings(P+rel,NOTICE),[]);self.assertEqual(self.findings(P+'third_party/notices/up/AUTHORS',NOTICE),[])
        for name,change in (('no wheel file name',lambda w:w.update(filename='up-1.0.tar.gz')),
                            ('other host',lambda w:w['origin'].update(url='https://example.org/packages/'+FILE)),
                            ('upstream-archive kind',lambda w:w['origin'].update(kind='upstream-archive'))):
            with self.subTest(case=name):
                value=lock(data);value['wheels'][0]['notice']=digest_ref(rel,NOTICE);change(value['wheels'][0])
                self.write_lock('examples/demo',value);self.assertEqual(self.categories(P+rel,NOTICE),{'email-address'})

    def test_the_wheels_directory_keeps_the_wheel_rule(self):
        """EX1-R1-02 stays: under third_party/wheels/ only a part of a PyPI wheel row is exempt."""
        data=wheel_bytes();rel='third_party/wheels/'+FILE
        for name,row in (('retained file',upstream_row(files=[digest_ref(rel,data)])),('source part',upstream_row('source',parts=[digest_ref(rel,data)])),
                         ('notice',upstream_row(notice=digest_ref(rel,data)))):
            with self.subTest(case=name):
                self.write_lock('examples/demo',project_lock([row]))
                self.assertIn(P+rel+': unpinned-archive',self.findings(P+rel,data));self.assertFalse(self.scanner.project_pinned(P+rel,data,None))
        self.write_lock('examples/demo',project_lock([upstream_row(files=[digest_ref('third_party/wheels/NOTES.txt',NOTICE)])]))
        self.assertEqual(self.categories(P+'third_party/wheels/NOTES.txt',NOTICE),{'email-address'})

    def test_the_lock_itself_is_never_exempt(self):
        rel='third_party/lock.json';data=b'{"owner": "'+UPSTREAM_EMAIL.encode()+b'"}\n'
        self.revisions({'':project_lock([upstream_row(files=[digest_ref(rel,data)],notice=digest_ref(rel,data))])})
        self.assertIn('email-address',self.categories(P+rel,data,':'))
        self.assertFalse(self.scanner.project_pinned(P+rel,data,':'))

    def test_the_lock_of_the_same_revision_decides(self):
        """A lock edit in the same commit that rebinds a file to new bytes is judged against the lock of that revision: the
        new bytes pass with the new lock; under the lock of another revision (an earlier commit, or the index before the lock
        edit is staged) they are a mismatch and get every rule."""
        rel='third_party/notices/up/LICENSE';path=P+rel
        new=NOTICE+('Copyright other author <'+UPSTREAM_EMAIL+'>\n').encode()
        locks={'old':project_lock([upstream_row(notice=digest_ref(rel,NOTICE))]),'new':project_lock([upstream_row(notice=digest_ref(rel,new))])}
        self.revisions(locks)
        self.assertEqual(self.findings(path,new,'new'),[])
        self.assertEqual(self.findings(path,NOTICE,'old'),[])
        self.assertEqual(self.categories(path,new,'old'),{'project-lock-mismatch','email-address'})
        self.assertEqual(self.categories(path,NOTICE,'new'),{'project-lock-mismatch','email-address'})
        locks['']=locks['old'];self.assertEqual(self.categories(path,new,':'),{'project-lock-mismatch','email-address'})
        locks['']=locks['new'];self.assertEqual(self.findings(path,new,':'),[])

    def test_a_nested_project_area_pins_nothing(self):
        """A lock inside another project's third_party area is no project lock (the wheel route too)."""
        inner='examples/demo/benchmarks/project/third_party/up';rel='third_party/notices/LICENSE'
        self.write_lock(inner,project_lock([upstream_row(notice=digest_ref(rel,NOTICE))]))
        path=inner+'/benchmarks/project/'+rel
        self.assertEqual(self.categories(path,NOTICE),{'email-address'});self.assertFalse(self.scanner.project_pinned(path,NOTICE,None))
        data=wheel_bytes();self.write_lock(inner,lock(data))
        wheel=inner+'/benchmarks/project/third_party/wheels/'+FILE
        self.assertFalse(self.scanner.project_pinned(wheel,data,None));self.assertIn(wheel+': unpinned-archive',self.findings(wheel,data))
        self.assertFalse(self.scanner.project_pinned('xbenchmarks/project/third_party/wheels/'+FILE,data,None))

    def test_the_name_is_always_checked(self):
        rel='third_party/notices/'+UPSTREAM_EMAIL+'.txt'
        self.write_lock('examples/demo',project_lock([upstream_row(notice=digest_ref(rel,NOTICE))]))
        self.assertEqual(self.categories(P+rel,NOTICE),{'file-name'})

class UpstreamAllowlistTests(unittest.TestCase):
    """FW-HOOK: the upstream origins whose bound files are exempt. The lock schema holds the same pattern."""
    def test_the_hook_allowlist_equals_the_lock_schema_allowlist(self):
        schema=json.loads((ROOT/'schemas/project-third-party.json').read_text())
        self.assertEqual(schema['$defs']['exempt_origin_url']['pattern'],'^'+hook().UPSTREAM_URL.pattern+'$')

    def test_the_allowlist_names_upstream_release_downloads_only(self):
        rx=hook().UPSTREAM_URL
        for url in ALLOWED_URLS+('https://github.com/a/b/releases/download/v1/x.zip',):
            with self.subTest(url=url):self.assertIsNotNone(rx.fullmatch(url))
        for url in ('http://github.com/a/b/releases/download/v1/x.zip','https://github.com/a/b/blob/main/x.zip','https://github.com/a/x.zip',
                    'https://github.com/a/b/raw/main/x.zip','https://gist.github.com/a/b/releases/download/v1/x',
                    'https://github.com.example.net/a/b/releases/download/v1/x','https://raw.githubusercontent.com/a/b/main/x',
                    'https://github.com/../b/releases/download/v1/x','https://github.com/a/.b/releases/download/v1/x',
                    'https://archives.boost.io/other/x.tar.bz2','https://example.org/x.tar.gz','https://files.pythonhosted.org/',
                    'https://github.com/a/b/releases/download/',GH+'\n','https://u'+AT+'github.com/a/b/releases/download/v1/x',
                    'https://github.com/a/b/releases/download/v1/x?y=1','https://github.com/a/b/releases/download/../../c/d/x'):
            with self.subTest(url=url):self.assertIsNone(rx.fullmatch(url))

class RootCase(HookCase):
    """A project area with a lock (and by default a project.json) in the temporary working tree; the generic rules only."""
    def setUp(self):
        super().setUp();self.scanner.rules=[(name,re.compile(rx)) for name,rx in self.hook.GENERIC.items()]
    def categories(self,path,data,rev=None):
        return {f.rsplit(': ',1)[-1].split(' ')[0] for f in self.findings(path,data,rev)}
    def bound(self,project,project_json=True,value=None,rel='third_party/notices/up/LICENSE'):
        area=Path(project or '.')/'benchmarks/project/third_party';area.mkdir(parents=True,exist_ok=True)
        (area/'lock.json').write_text(json.dumps(value or project_lock([upstream_row(notice=digest_ref(rel,NOTICE))])))
        if project_json:Path(project or '.','project.json').write_text('{"schema_version": 1}\n')
        return (project+'/' if project else '')+'benchmarks/project/'+rel

class ProjectRootTests(RootCase):
    """T4-A02: a project lock counts only in a project root of the same revision: the repository root or examples/<name>/,
    with a project.json (a JSON object, a regular file in the working tree). A look-alike lock anywhere else exempts
    nothing (the wheel route too)."""
    def test_a_lock_outside_a_project_root_exempts_nothing(self):
        for project in ('docs','tests/unit','src/x','examples','examples/demo/sub','tests/fixtures/demo','examplesx/demo'):
            with self.subTest(project=project):
                path=self.bound(project)                                   # a project.json is there, but it is no project root
                self.assertEqual(self.categories(path,NOTICE),{'email-address'})
                self.assertFalse(self.scanner.project_pinned(path,NOTICE,None))
                self.assertEqual(self.categories(path,b'other bytes\n'),set())         # no project lock: no mismatch either
        for project in ('examples/demo',''):
            with self.subTest(root=project):
                path=self.bound(project);self.assertEqual(self.findings(path,NOTICE),[])     # a real project root

    def test_a_project_root_needs_its_project_json(self):
        for project in ('examples/demo',''):
            with self.subTest(project=project):
                path=self.bound(project,project_json=False)
                self.assertEqual(self.categories(path,NOTICE),{'email-address'});self.assertFalse(self.scanner.project_pinned(path,NOTICE,None))
        path=self.bound('examples/demo')
        for text in ('[1]','{','"project"',''):
            with self.subTest(project_json=text):
                Path('examples/demo/project.json').write_text(text)
                self.assertEqual(self.categories(path,NOTICE),{'email-address'})
        Path('examples/demo/project.json').unlink();Path('real.json').write_text('{"schema_version": 1}')
        Path('examples/demo/project.json').symlink_to(Path.cwd()/'real.json')          # a linked project.json counts as absent
        self.assertEqual(self.categories(path,NOTICE),{'email-address'})

    def test_the_project_json_of_the_same_revision_decides(self):
        rel='third_party/notices/up/LICENSE';value=project_lock([upstream_row(notice=digest_ref(rel,NOTICE))])
        files={':'+P+'third_party/lock.json':json.dumps(value).encode()}
        def git(*args,binary=False,check=True):
            return files.get(args[2],b'') if args[:2]==('cat-file','blob') else b''
        self.hook.git=git;self.bound('examples/demo')                    # the working tree has project.json, the index not
        self.assertEqual(self.categories(P+rel,NOTICE,':'),{'email-address'})
        files[':examples/demo/project.json']=b'{"schema_version": 1}'
        self.assertEqual(self.findings(P+rel,NOTICE,':'),[])

    def test_a_bound_wheel_outside_a_project_root_is_not_pinned(self):
        data=wheel_bytes()
        for project,project_json in (('docs',True),('tests/unit',True),('src/x',True),('examples/demo',False),('',False)):
            with self.subTest(project=project,project_json=project_json):
                path=self.bound(project,project_json,lock(data),'third_party/wheels/'+FILE)
                self.assertFalse(self.scanner.project_pinned(path,data,None))
                self.assertIn(path+': unpinned-archive',self.findings(path,data))

class ProjectSymlinkTests(RootCase):
    """T4-A04: a symlink entry (mode 120000) under a project third_party area is the finding project-third-party-symlink
    and is never exempt; its link text gets every content rule. The project tool refuses links there too."""
    def test_a_symlink_entry_is_a_finding_and_never_pinned(self):
        home=('/ho'+'me/someone/notes').encode()                               # synthetic home path as link text
        for link in (b'LICENSE',home):
            with self.subTest(link=link):
                path=self.bound('examples/demo',rel='third_party/notices/up/COPYING',
                                value=project_lock([upstream_row(notice=digest_ref('third_party/notices/up/COPYING',link))]))
                self.assertEqual(self.findings(path,link),[])                  # as a regular file the bound text is exempt
                self.scanner.findings=[];self.scanner.content(path,path,link,None,'120000')
                self.assertIn(path+': project-third-party-symlink',self.scanner.findings)
                self.assertEqual(any('user-home-path' in f for f in self.scanner.findings),link==home)
        for path in ('docs/benchmarks/project/third_party/x','benchmarks/project/third_party/wheels/'+FILE):
            with self.subTest(path=path):
                self.scanner.findings=[];self.scanner.content(path,path,b'target',None,'120000')
                self.assertEqual(self.scanner.findings,[path+': project-third-party-symlink'])
        self.scanner.findings=[];self.scanner.content('docs/link','docs/link',b'target',None,'120000')
        self.assertEqual(self.scanner.findings,[])                             # outside a third-party area: the old rules only

    def test_the_entry_mode_reaches_the_scan(self):
        listing=(':100644 120000 '+'0'*40+' '+'1'*40+' T\0a/b\0'+':000000 160000 '+'0'*40+' '+'2'*40+' A\0sub\0'
                 +':000000 100644 '+'0'*40+' '+'3'*40+' A\0c\0')
        self.assertEqual(self.hook.changed(listing),{'a/b':'120000','c':'100644'})
        path=P+'third_party/notices/up/COPYING'
        self.hook.git=lambda *args,binary=False,check=True:b'LICENSE' if args[:2]==('cat-file','blob') else b''
        self.scanner.findings=[];self.scanner.blob(path,path,':','120000')
        self.assertEqual(self.scanner.findings,[path+': project-third-party-symlink'])

NOTICES='third_party/notices/up/'

def two_bound_files():
    """A lock that binds the same notice bytes under two paths: LICENSE and COPYING."""
    return project_lock([upstream_row(files=[digest_ref(NOTICES+'LICENSE',NOTICE),digest_ref(NOTICES+'COPYING',NOTICE)])])

class TreeRouteModeTests(RootCase):
    """T4-A14 (coverage, FIX1): the --tree route passes column 0 of `git ls-files -s` (the entry mode) to the scan. A symlink
    entry under a project third_party area is project-third-party-symlink on this route too; the same bytes as a regular
    file are exempt. A temporary repository (git init and git add only); the generic rules only, no local values."""
    def tree(self,link):
        license_path=self.bound('examples/demo',value=two_bound_files(),rel=NOTICES+'LICENSE')
        Path(license_path).parent.mkdir(parents=True,exist_ok=True);Path(license_path).write_bytes(NOTICE)
        copying=P+NOTICES+'COPYING'
        if link:Path(copying).symlink_to('LICENSE')
        else:Path(copying).write_bytes(NOTICE)
        env={'PATH':os.environ.get('PATH','/usr/bin:/bin'),'HOME':os.getcwd(),'GIT_CONFIG_NOSYSTEM':'1'}
        for argv in (('init','-q'),('add','-A')):subprocess.run(['git',*argv],env=env,check=True,capture_output=True)
        modes={row.split('\t',1)[1]:row.split()[0] for row in subprocess.run(['git','ls-files','-s','-z'],env=env,check=True,capture_output=True,
                                                                                text=True).stdout.split('\0') if row}
        self.assertEqual(modes[copying],'120000' if link else '100644')
        return license_path,copying
    def run_tree(self):
        self.hook.Scanner=lambda:self.scanner;self.scanner.findings=[]
        with mock.patch.object(sys,'argv',['personal_info_check.py','--tree']),contextlib.redirect_stderr(io.StringIO()):rc=self.hook.main()
        return rc,list(self.scanner.findings)
    def test_a_symlink_entry_is_a_finding_on_the_tree_route(self):
        license_path,copying=self.tree(link=True)
        rc,findings=self.run_tree()
        self.assertEqual(rc,1);self.assertIn(copying+': project-third-party-symlink',findings)
        self.assertEqual([f for f in findings if f.startswith(license_path)],[])          # the bound regular file stays exempt
    def test_the_same_bytes_as_a_regular_file_are_exempt(self):
        self.tree(link=False);self.assertEqual(self.run_tree(),(0,[]))

class TaggedTreeRouteModeTests(RootCase):
    """T4-A14 (coverage, FIX1): a tagged tree passes column 0 of `git ls-tree` (the entry mode) to the scan (Scanner.tag): a
    symlink entry under a project third_party area is project-third-party-symlink; the same bytes as a regular entry are
    exempt. A fake git serves the tree object."""
    def tag_tree(self,mode):
        obj='ab'*20;copying=P+NOTICES+'COPYING'
        blobs={P+'third_party/lock.json':json.dumps(two_bound_files()).encode(),'examples/demo/project.json':b'{"schema_version": 1}',
               P+NOTICES+'LICENSE':NOTICE,copying:NOTICE}
        listing=''.join(f"{mode if path==copying else '100644'} blob {'0'*40}\t{path}\0" for path in sorted(blobs))
        def git(*args,binary=False,check=True):
            if args[:2]==('cat-file','-t'):out='tree\n' if args[2]==obj else ''
            elif args[:2]==('ls-tree','-r'):out=listing if args[-1]==obj else ''
            elif args[:2]==('cat-file','blob'):
                rev,_,path=args[2].partition(':');data=blobs.get(path,b'') if rev==obj else b''
                return data if binary else data.decode()
            else:out=''
            return out.encode() if binary else out
        self.hook.git=git;self.scanner.findings=[]
        self.assertEqual(self.scanner.tag(obj),obj)
        return obj,copying,list(self.scanner.findings)
    def test_a_symlink_entry_of_a_tagged_tree_is_a_finding(self):
        obj,copying,findings=self.tag_tree('120000')
        self.assertIn(f'tagged-tree {obj[:12]}:{copying}: project-third-party-symlink',findings)
        self.assertEqual([f for f in findings if 'LICENSE' in f],[])
    def test_the_same_bytes_as_a_regular_entry_are_exempt(self):
        self.assertEqual(self.tag_tree('100644')[2],[])

class WrongSizeTests(RootCase):
    """T4-A05: each wrong `bytes` value of a binding is not exempt and is a project-lock-mismatch; a record without bytes is
    not exempt and is no mismatch; an uppercase sha256 is a mismatch."""
    def test_each_wrong_size_value_is_a_mismatch(self):
        size=len(NOTICE);rel='third_party/notices/up/LICENSE'
        for value in (True,False,float(size),str(size),None,[size],{'bytes':size},-size,0,size-1,size+1):
            for role in ('notice','file','part'):
                with self.subTest(value=value,role=role):
                    ref=dict(digest_ref(rel,NOTICE),bytes=value)
                    row={'notice':lambda:upstream_row(notice=ref),'file':lambda:upstream_row(files=[ref]),
                         'part':lambda:upstream_row('source',parts=[ref])}[role]()
                    path=self.bound('examples/demo',value=project_lock([row]))
                    self.assertEqual(self.categories(path,NOTICE),{'project-lock-mismatch','email-address'})
                    self.assertFalse(self.scanner.project_pinned(path,NOTICE,None))
        path=self.bound('examples/demo',value=project_lock([upstream_row(notice=digest_ref(rel,NOTICE,size=False))]))
        self.assertEqual(self.categories(path,NOTICE),{'email-address'})                  # no bytes: no exemption, no mismatch
        upper=dict(digest_ref(rel,NOTICE),sha256=hashlib.sha256(NOTICE).hexdigest().upper())
        path=self.bound('examples/demo',value=project_lock([upstream_row(notice=upper)]))
        self.assertEqual(self.categories(path,NOTICE),{'project-lock-mismatch','email-address'})

class RegressionSuiteKeepModeTests(unittest.TestCase):
    """T4-A03 (ruling R9): with HOOKREG_KEEP=1, .githooks/tests/regression.sh runs no rm at all. fresh() refuses an existing
    path instead of deleting it, the final cleanup is skipped and the script prints the one directory that it keeps. The
    default mode (the privacy workflow on its runner) is unchanged. This scan reads the script; it does not run it."""
    RM=re.compile(r'(?:^|[\s;&|({])rm\s')
    def lines(self):
        text=(ROOT/'.githooks/tests/regression.sh').read_text()
        return text,[l for l in text.splitlines() if not l.lstrip().startswith('#') and self.RM.search(l)]
    def test_every_rm_is_skipped_in_keep_mode(self):
        text,rm=self.lines()
        self.assertIn('KEEP=${HOOKREG_KEEP:-}',text)
        self.assertTrue(rm)
        for line in rm:
            with self.subTest(line=line.strip()[:60]):
                self.assertEqual(len(self.RM.findall(line)),1)
                self.assertRegex(line,r'\[ "\$KEEP" = 1 \] \|\| rm ')
    def test_keep_mode_refuses_an_existing_path_and_prints_the_kept_directory(self):
        text,rm=self.lines()
        self.assertIn('if [ "$KEEP" = 1 ] && { [ -e "$R" ] || [ -e "$R.git" ]; }; then',text)
        self.assertIn('[ "$KEEP" = 1 ] && echo "HOOKREG_KEEP=1: kept $BASE"',text)
        self.assertIn('[ "$KEEP" = 1 ] || rm -rf "$BASE"',text)                 # the default mode still removes its directory

if __name__=='__main__':unittest.main()
