"""FR4-IMG-BOUND-01: the eviction of unused per-project runtime cache images (tools/runtime_cache.py), with a fake docker
layer only. No real image is listed or removed by these tests."""
import fcntl, json, os, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from evidence import GateError

def ident(c):return 'sha256:'+c*64

class FakeDocker:
    """Answers image ls, image inspect, ps and image rm from a table; records every call."""
    def __init__(self,images,users=None,listing=None,fail=()):
        self.images=images;self.users=users or {};self.listing=listing;self.fail=set(fail);self.calls=[]
    def ok(self,out):return {'exit_code':0,'failure':None,'output':out}
    def bad(self):return {'exit_code':1,'failure':None,'output':''}
    def __call__(self,args,**kw):
        self.calls.append(list(args))
        if args[:2]==['image','ls']:
            if 'ls' in self.fail:return self.bad()
            if self.listing is not None:return self.ok(self.listing)
            return self.ok(''.join(i+'\n' for i,o in self.images.items() if (o['Config'].get('Labels') or {}).get('org.safe-c.project-runtime')=='1'))
        if args[:2]==['image','inspect']:
            if ('inspect',args[2]) in self.fail:return self.bad()
            return self.ok(json.dumps([self.images[args[2]]]))
        if args[0]=='ps':
            if ('ps',args[-1].split('=',1)[1]) in self.fail:return self.bad()
            return self.ok(''.join(c+'\n' for c in self.users.get(args[-1].split('=',1)[1],[])))
        if args[:2]==['image','rm']:
            if ('rm',args[2]) in self.fail:return self.bad()
            del self.images[args[2]];return self.ok('Deleted: '+args[2])
        raise AssertionError('unexpected docker call: '+' '.join(args))
    def removed(self):return [c[2] for c in self.calls if c[:2]==['image','rm']]

def runtime(c,tags=None,label='1'):
    return {'Id':ident(c),'RepoTags':tags if tags is not None else ['safe-c-project-runtime:'+c*24],
            'Config':{'Labels':{'org.safe-c.project-runtime':label,'org.safe-c.project-name':'demo'}}}

class RuntimeCacheTests(unittest.TestCase):
    def setUp(self):
        import runtime_cache as rc
        self.tmp=tempfile.TemporaryDirectory();self.lock=rc.acquire_lock(str(Path(self.tmp.name)/'lock'),wait_seconds=1)
    def tearDown(self):
        self.lock.release();self.tmp.cleanup()
    def test_only_unused_runtime_caches_are_evicted(self):
        import runtime_cache as rc
        images={ident('a'):runtime('a'),ident('b'):runtime('b'),
                ident('d'):{'Id':ident('d'),'RepoTags':['safe-c-developer:'+'d'*24],'Config':{'Labels':{}}},      # a locked image: never listed
                ident('e'):{'Id':ident('e'),'RepoTags':['safe-c-toolchain:x'],'Config':{'Labels':None}}}
        docker=FakeDocker(images,users={ident('b'):['c0ffee']})
        got=rc.evict_unused(docker,self.lock)
        self.assertEqual(got,{'evicted':[ident('a')],'kept':[ident('b')],'refused':[]})
        self.assertEqual(docker.removed(),[ident('a')])
        self.assertEqual(sorted(images),[ident('b'),ident('d'),ident('e')])
        self.assertTrue(all('--force' not in c and '-f' not in c for c in docker.calls))
        ps=[c for c in docker.calls if c[0]=='ps']
        self.assertTrue(all(c[:4]==['ps','--all','--no-trunc','--quiet'] for c in ps))       # stopped containers count too
    def test_an_image_that_is_not_exactly_a_runtime_cache_is_never_removed(self):
        import runtime_cache as rc
        mixed=runtime('a',tags=['safe-c-project-runtime:'+'a'*24,'safe-c-developer:'+'a'*24])     # one tag is not a cache tag
        relabeled=runtime('b');relabeled['Config']['Labels']['org.safe-c.project-runtime']='2'
        other_id=runtime('c');other_id['Id']=ident('9')
        listing=''.join(i+'\n' for i in (ident('a'),ident('b'),ident('c'),ident('d')))
        images={ident('a'):mixed,ident('b'):relabeled,ident('c'):other_id,ident('d'):runtime('d')}
        docker=FakeDocker(images,listing=listing,fail={('inspect',ident('d'))})
        got=rc.evict_unused(docker,self.lock)
        self.assertEqual(got['evicted'],[]);self.assertEqual(sorted(got['refused']),sorted([ident('a'),ident('b'),ident('c'),ident('d')]))
        self.assertEqual(docker.removed(),[])
    def test_a_failed_container_listing_or_removal_keeps_the_image(self):
        import runtime_cache as rc
        images={ident('a'):runtime('a'),ident('b'):runtime('b')}
        docker=FakeDocker(images,fail={('ps',ident('a')),('rm',ident('b'))})
        got=rc.evict_unused(docker,self.lock)
        self.assertEqual(got,{'evicted':[],'kept':[],'refused':[ident('a'),ident('b')]})
        self.assertEqual(docker.removed(),[ident('b')])           # the refused removal of the unused image; no force, no retry
    def test_a_malformed_inventory_blocks(self):
        import runtime_cache as rc
        for listing in ('not-an-id\n','sha256:'+'A'*64+'\n',''.join('sha256:'+format(i,'064x')+'\n' for i in range(rc.MAX_IMAGES+1))):
            with self.subTest(listing=listing[:20]),self.assertRaises(GateError):rc.evict_unused(FakeDocker({},listing=listing),self.lock)
        with self.assertRaises(GateError):rc.evict_unused(FakeDocker({},fail={'ls'}),self.lock)
        docker=FakeDocker({},listing='');self.assertEqual(rc.evict_unused(docker,self.lock),{'evicted':[],'kept':[],'refused':[]})
    def test_the_command_takes_the_launcher_lock_and_refuses_without_it(self):
        """FR7b-A01: the command takes the launcher lock itself with a bounded wait. While another holder keeps the lock, it
        gives GateError and lists or removes nothing; without a held lock, evict_unused removes nothing."""
        import runtime_cache as rc
        with tempfile.TemporaryDirectory() as tmp:
            path=str(Path(tmp)/'lock');Path(path).write_text('')
            fd=os.open(path,os.O_RDONLY)
            try:
                fcntl.flock(fd,fcntl.LOCK_EX)                      # another holder (flock(1) of another command)
                t=[0.0];clock=lambda:t[0]
                def sleep(x):t[0]+=x
                with self.assertRaisesRegex(GateError,'launcher lock'):rc.acquire_lock(path,wait_seconds=5,clock=clock,sleep=sleep)
                self.assertGreaterEqual(t[0],5)                    # it waited, bounded
            finally:os.close(fd)
            held=rc.acquire_lock(path,wait_seconds=1)
            try:
                other=os.open(path,os.O_RDONLY)
                try:
                    with self.assertRaises(BlockingIOError):fcntl.flock(other,fcntl.LOCK_EX|fcntl.LOCK_NB)   # it is really held
                finally:os.close(other)
            finally:held.release()
            self.assertFalse(held.held)
            images={ident('a'):runtime('a')}
            for lock in (None,held,object()):
                docker=FakeDocker(dict(images))
                with self.subTest(lock=lock),self.assertRaisesRegex(GateError,'launcher lock'):rc.evict_unused(docker,lock)
                self.assertEqual(docker.calls,[])
    def test_the_command_refuses_while_a_safe_c_container_is_active(self):
        """FR7b-A01: under the lock, the command also needs zero active safe-c containment containers (a project check
        between its cache inspect and its container creation keeps its image)."""
        import runtime_cache as rc
        class Busy(FakeDocker):
            def __call__(self,args,**kw):
                if args[0]=='ps' and any(a=='label=org.safe-c.containment=1' for a in args):
                    self.calls.append(list(args));return self.ok('c0ffee\n')
                return super().__call__(args,**kw)
        docker=Busy({ident('a'):runtime('a')})
        with self.assertRaisesRegex(GateError,'active'):rc.run(docker,self.lock)
        self.assertEqual(docker.removed(),[])
        docker=FakeDocker({ident('a'):runtime('a')})
        self.assertEqual(rc.run(docker,self.lock)['evicted'],[ident('a')])
        self.assertEqual(docker.calls[0][:2],['ps','--all'])         # the active check comes first
    def test_an_untagged_or_unnamed_labelled_image_is_kept(self):
        """FR7b-A02: a labelled image needs at least one cache tag and the project-name label; a child image built FROM a
        cache inherits the label but has no cache tag."""
        import runtime_cache as rc
        untagged=runtime('a',tags=[]);nulltags=runtime('b');nulltags['RepoTags']=None
        unnamed=runtime('c');del unnamed['Config']['Labels']['org.safe-c.project-name']
        images={ident('a'):untagged,ident('b'):nulltags,ident('c'):unnamed,ident('d'):runtime('d')}
        docker=FakeDocker(images)
        got=rc.evict_unused(docker,self.lock)
        self.assertEqual(got['evicted'],[ident('d')]);self.assertEqual(sorted(got['refused']),[ident('a'),ident('b'),ident('c')])
        self.assertEqual(docker.removed(),[ident('d')])
    def test_the_pinned_assembler_is_unchanged(self):
        """The assembly recipe is pinned by developer.lock.json; the eviction is a separate command (no new acquisition)."""
        import hashlib
        lock=json.loads((ROOT/'developer.lock.json').read_text())
        self.assertEqual(hashlib.sha256((ROOT/lock['assembly_recipe']).read_bytes()).hexdigest(),lock['assembly_recipe_sha256'])
        self.assertIn('tools/runtime_cache.py',json.loads((ROOT/'starter-export.json').read_text())['files'])

if __name__=='__main__':unittest.main()
