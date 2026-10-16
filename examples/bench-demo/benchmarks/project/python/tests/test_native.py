"""bench-demo native codec tests (FR6 N3; run by the framework project unit suite in the bench container, without the
native binaries). The codec values agree with the C header, the request bounds are kept, the demo-native check refuses
to run without restored binaries or with arguments, the request set holds the specified edge cases, and the in-process
child refuses a bad argument list. The exchange with the real C peers is the demo-native check (bench check --native)."""
import contextlib, io, os, re, struct, tempfile, unittest
from pathlib import Path
from unittest import mock
from benchlab import native_inproc as ni, native_worker as nw
from benchdemo import checks, native, reference as r
HEADER=Path(__file__).resolve().parents[4]/'include'/'bd_wire.h'
INPROC=Path(__file__).resolve().parents[4]/'include'/'bd_inproc.h'

class CodecValueTests(unittest.TestCase):
    def test_values_agree_with_the_c_headers(self):
        text=HEADER.read_text()
        self.assertIn('BD_SHM_INPUT_BYTES = BD_REQUEST_MAX_BYTES',text);self.assertIn('BD_SHM_OUTPUT_BYTES = BD_OUTPUT_MAX_BYTES',text)
        self.assertIn('BD_SELECTOR_DIGEST = 1',text)
        self.assertEqual((native.INPUT_REGION,native.OUTPUT_REGION),(172032,229376))
        self.assertLessEqual(native.OUTPUT_REGION,nw.MAX_FRAME)
        self.assertEqual((native.SELECTOR,native.THREADS,native.RECORD_IN,native.RECORD_OUT),(1,0,12,16))
        inproc=INPROC.read_text()
        self.assertIn('BD_INPROC_ABI = 2',inproc);self.assertEqual(ni.ABI,2)
        self.assertIn('BD_INPROC_ECHO_WORDS = 6',inproc);self.assertEqual(native.ECHO_WORDS,6)
        params=re.search(r'int bd_inproc_digest\(([^;]*)\);',inproc).group(1)
        self.assertEqual(len(native.ARGTYPES),params.count(',')+1)
        self.assertGreaterEqual(native.SCRATCH,8*native.ECHO_WORDS)
    def test_records_keeps_the_request_bounds(self):
        one=r.encode_request([(1,1)])
        self.assertEqual(native.records(one),1);self.assertEqual(native.records(one*r.RECORDS_MAX),r.RECORDS_MAX)
        for bad in (b'',one[:-1],one*(r.RECORDS_MAX+1),'x'*12,None):
            with self.subTest(n=len(bad) if bad is not None else None),self.assertRaises(ValueError):native.records(bad)
    def test_the_response_length_needs_the_request_count(self):
        expect=native.response_length(3)
        self.assertEqual(expect({'count':3}),48);self.assertEqual(expect({'count':2}),-1)

class NativeCheckTests(unittest.TestCase):
    def test_demo_native_needs_restored_binaries_and_no_arguments(self):
        with tempfile.TemporaryDirectory() as t,mock.patch.dict(os.environ,{},clear=False):
            os.environ.pop('SAFE_C_BENCH_NATIVE',None)
            self.assertEqual(checks.native_agreement(Path(t),[])['reason'],'demo-native needs bench check --native')
            self.assertEqual(checks.native_agreement(Path(t),['x'])['status'],'FAIL')
    def test_the_request_set_holds_the_edge_cases(self):
        sets=dict(checks.native_requests())
        self.assertEqual(sorted(sets),['largest','largest-zero','mixed','one','one-kmax'])      # FR6 N4: the N3 set plus two requests
        self.assertEqual([r.check_request(sets[k]) for k in ('one','mixed','largest','one-kmax','largest-zero')],[1,5,r.RECORDS_MAX,1,r.RECORDS_MAX])
        self.assertEqual(struct.unpack('<QI',sets['one-kmax']),(0,r.STEPS_MAX))
        self.assertEqual(set(struct.iter_unpack('<QI',sets['largest-zero'])),{(0,0)})
        rows=[struct.unpack_from('<QI',sets['mixed'],12*i) for i in range(5)]
        self.assertIn((r.MASK,r.STEPS_MAX),rows);self.assertIn((1,0),rows);self.assertEqual(struct.unpack('<QI',sets['one']),(0,0))
    def test_a_route_failure_is_counted_and_never_passes(self):
        def broken(route,native_dir,request):
            if route=='shm':raise nw.FrameError('DEADLINE')
            return r.digest_request(request) if route!='kernel' else b'x'
        with tempfile.TemporaryDirectory() as t,mock.patch.dict(os.environ,{'SAFE_C_BENCH_NATIVE':t}),\
             mock.patch.object(native,'route_digest',broken),mock.patch.object(checks,'native_requests',lambda:(('one',r.encode_request([(0,0)])),)):
            row=checks.native_agreement(Path(t),[])
        self.assertEqual(row['status'],'FAIL')
        self.assertEqual(row['routes']['shm'],{'matched':0,'mismatched':0,'errors':1,'error_types':['FrameError']})
        self.assertEqual(row['routes']['kernel']['mismatched'],1);self.assertEqual(row['routes']['stdio']['matched'],1)
        self.assertEqual((row['counts']['shm_errors'],row['counts']['kernel_mismatched'],row['counts']['inproc_matched']),(1,1,1))
    def test_every_route_matching_passes(self):
        with tempfile.TemporaryDirectory() as t,mock.patch.dict(os.environ,{'SAFE_C_BENCH_NATIVE':t}),\
             mock.patch.object(native,'route_digest',lambda route,d,q:r.digest_request(q)),\
             mock.patch.object(checks,'native_requests',lambda:(('one',r.encode_request([(5,3)])),)):
            row=checks.native_agreement(Path(t),[])
        self.assertEqual((row['status'],row['counts']['requests'],row['counts']['routes']),('PASS',1,4))
        self.assertEqual([row['counts'][r+'_matched'] for r in native.ROUTES],[1,1,1,1])
        self.assertEqual((row['files'],row['counts']['identical_requests']),(['native-agreement.json'],1))
    def test_the_agreement_evidence_names_the_digest_of_every_version_per_request(self):
        import hashlib, json
        q=r.encode_request([(5,3)]);want=hashlib.sha256(r.digest_request(q)).hexdigest()
        def route(route,d,request):return r.digest_request(request) if route!='shm' else b'\x00'*16
        with tempfile.TemporaryDirectory() as t,mock.patch.dict(os.environ,{'SAFE_C_BENCH_NATIVE':t}),\
             mock.patch.object(native,'route_digest',route),mock.patch.object(checks,'native_requests',lambda:(('one',q),)):
            row=checks.native_agreement(Path(t),[]);ev=json.loads((Path(t)/'native-agreement.json').read_text())
        self.assertEqual(row['status'],'FAIL');self.assertEqual(row['counts']['identical_requests'],0)
        self.assertEqual(ev['versions'],['python','stdio','shm','inproc','kernel'])
        got=ev['requests'][0];self.assertEqual((got['request'],got['records'],got['identical']),('one',1,False))
        self.assertEqual({k:v for k,v in got['sha256'].items() if k!='shm'},{k:want for k in ('python','stdio','inproc','kernel')})
        self.assertNotEqual(got['sha256']['shm'],want)
    def test_the_inproc_child_refuses_a_bad_argument_list(self):
        out=io.StringIO()
        with contextlib.redirect_stdout(out):self.assertEqual(native.main(['native.py']),2)
        os.environ.pop('SAFE_C_BENCH_ROLE',None)
        with tempfile.TemporaryDirectory() as t:
            req=Path(t)/'q';req.write_bytes(r.encode_request([(1,1)]))
            with self.assertRaises(ni.InprocRefused):native.inproc_call(t,req.read_bytes())

class AdapterNativeTests(unittest.TestCase):
    """FR6 N4: the c-serial rows of the adapter. A caller row uses the route that the trial child sets and gives the
    reference result; a kernel row packs the sliced records, reads the bd-kernel output and gives the canonical digest."""
    def adapter(self):
        from benchdemo.adapter import DemoDigest
        return DemoDigest({'steps':64,'seed':20261007})
    def data(self,a,rows=20):
        return a.synthesize(rows,7)[len(b'bd-demo\x01'):]
    def test_a_caller_row_runs_its_route_session_and_gives_the_reference(self):
        a=self.adapter();data=self.data(a);seen=[]
        class Session:
            def __init__(self,route):self.route=route;self.stats={'transport_ns':0,'copied_bytes':0,'load_process':None};self.stopped=0;seen.append(route)
            def start(self):pass
            def digest(self,request):self.stats['transport_ns']+=5;self.stats['copied_bytes']+=len(request);return r.digest_request(request)
            def stop(self):self.stopped+=1
        with mock.patch.object(native,'Session',Session):
            with self.assertRaisesRegex(ValueError,'route'):a.run(a.prepare(data,'c-serial'),'c-serial',1)
            a.route='shm';nw.LAST_STATS.clear()
            got=a.materialize(a.run(a.prepare(data,'c-serial'),'c-serial',1))
            self.assertEqual(got,a.reference(data));self.assertTrue(a.validate(got,a.reference(data),data)['eligible'])
            self.assertEqual((nw.LAST_STATS['transport_ns'],nw.LAST_STATS['copied_bytes']),(5,len(data)))
            a.native_stop('c-serial',1);self.assertEqual(a.session.stopped,1)
            a.route='inproc';a.native_start('c-serial',1);self.assertEqual(seen,['shm','inproc'])
    def test_a_kernel_row_packs_the_records_and_reads_the_kernel_output(self):
        a=self.adapter();data=self.data(a);ref=a.reference(data);output=r.digest_request(data)
        self.assertEqual(a.pack_native(data),data)
        self.assertEqual(a.unpack_native(output),ref)
        self.assertEqual(a.native_reference_digest(ref),format(r.fnv1a(output),'016x'))
        with self.assertRaises(ValueError):a.unpack_native(output[:-1])
    def test_the_kernel_declaration_keeps_the_bd_kernel_option_order(self):
        import json
        decl=json.loads((Path(__file__).resolve().parents[2]/'bench.json').read_text())['native']
        self.assertEqual(decl,{'kernel':{'program':'bd-kernel','args':['--input','{input}','--records','{records}','--loops','{loops}','--handshake','--output','{output}']},
                               'agreement':'demo-native'})
        usage=(Path(__file__).resolve().parents[4]/'src'/'bd_kernel_cli.c').read_text()
        self.assertIn('--input F --records N --loops L [--handshake] [--output F]',usage)

class Stop(Exception):
    """Raised by a recording stand-in once it has seen the start or load arguments."""

class RestoredBinaryTests(unittest.TestCase):
    """N3b-A02: every route (stdio, shm, inproc, kernel) starts or loads its binary from SAFE_C_BENCH_NATIVE with the
    sha256 of that same directory; a native directory other than the restore directory is refused before any start."""
    DIGESTS={'bd-worker':'1'*64,'bd-kernel':'2'*64,'libbd_inproc.so':'3'*64}
    def setUp(self):
        import json, shutil
        self.dir=Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,self.dir,True)
        (self.dir/'sha256.json').write_text(json.dumps(self.DIGESTS))
        env=mock.patch.dict(os.environ,{'SAFE_C_BENCH_NATIVE':str(self.dir),'SAFE_C_BENCH_ROLE':'caller'});env.start();self.addCleanup(env.stop)
        self.request=r.encode_request([(1,1)]);self.seen=[]
    def worker(self):
        test=self
        class Worker:
            def __init__(self,argv,**kwargs):test.seen.append((argv[0],kwargs.get('sha256')))
            def __enter__(self):return self
            def __exit__(self,*exc):return False
            def start(self):raise Stop()
        return mock.patch.object(native.nw,'NativeWorker',Worker)
    def test_stdio_and_shm_start_the_restored_worker_with_its_digest(self):
        with self.worker():
            for route in (native.stdio_digest,native.shm_digest):
                with self.subTest(route=route.__name__),self.assertRaises(Stop):route(str(self.dir),self.request)
        self.assertEqual(self.seen,[(str(self.dir/'bd-worker'),self.DIGESTS['bd-worker'])]*2)
    def test_the_kernel_starts_the_restored_kernel_with_its_digest(self):
        def run_kernel(argv,**kwargs):self.seen.append((argv[0],kwargs.get('sha256')));raise Stop()
        with mock.patch.object(native.nk,'run_kernel',run_kernel),self.assertRaises(Stop):native.kernel_digest(str(self.dir),self.request)
        self.assertEqual(self.seen,[(str(self.dir/'bd-kernel'),self.DIGESTS['bd-kernel'])])
    def test_inproc_loads_the_restored_library_with_its_digest(self):
        def load(path,sha256,**kwargs):self.seen.append((str(path),sha256));raise Stop()
        with mock.patch.object(native.ni,'load',load),self.assertRaises(Stop):native.inproc_call(str(self.dir),self.request)
        self.assertEqual(self.seen,[(str(self.dir/'libbd_inproc.so'),self.DIGESTS['libbd_inproc.so'])])
    def test_a_native_directory_other_than_the_restore_directory_is_refused(self):
        other=Path(tempfile.mkdtemp());self.addCleanup(other.rmdir)
        def run_kernel(argv,**kwargs):self.seen.append(argv[0]);raise Stop()
        def load(path,sha256,**kwargs):self.seen.append(str(path));raise Stop()
        with self.worker(),mock.patch.object(native.nk,'run_kernel',run_kernel),mock.patch.object(native.ni,'load',load):
            for route in (native.stdio_digest,native.shm_digest,native.kernel_digest,native.inproc_call):
                with self.subTest(route=route.__name__),self.assertRaisesRegex(ValueError,'restore directory'):route(str(other),self.request)
        self.assertEqual(self.seen,[])

if __name__=='__main__':unittest.main()
