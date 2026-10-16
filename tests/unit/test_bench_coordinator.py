import gc, importlib.util, json, socket, sys, tempfile, threading, time, unittest, warnings
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('bench_coordinator',ROOT/'container/bench-coordinator.py')
bc=importlib.util.module_from_spec(spec);spec.loader.exec_module(bc)
sys.path.insert(0,str(ROOT/'benchmarks/performance/python'))
from benchlab.markers import Marker

def cgroup(d,omit=()):
    files={'cpu.stat':'usage_usec 100\nuser_usec 70\nsystem_usec 30\nnr_periods 5\nnr_throttled 1\nthrottled_usec 9\n',
           'memory.stat':'anon 4096\nfile 8192\nshmem 0\nsock 0\n','memory.current':'12288\n','memory.peak':'20480\n',
           'pids.current':'3\n','pids.peak':'4\n','cgroup.procs':'',
           'cpu.pressure':'some avg10=0.00 avg60=0.00 avg300=0.00 total=11\nfull avg10=0.00 avg60=0.00 avg300=0.00 total=2\n'}
    for name,text in files.items():
        if name not in omit:(Path(d)/name).write_text(text)

class CounterTests(unittest.TestCase):
    def test_counters_parse_the_cgroup_files(self):
        with tempfile.TemporaryDirectory() as d:
            cgroup(d);c=bc.read_counters(Path(d),Path(d),clock=lambda:5)
            self.assertEqual((c['cpu']['usage_usec'],c['cpu']['throttled_usec'],c['memory_stat'],c['memory_peak'],c['pids_current'],c['cpu_pressure']),
                             (100,9,{'anon':4096,'file':8192,'shmem':0},20480,3,{'some':11,'full':2}))
            self.assertEqual(c['memory_pressure'],None);self.assertIn('memory.pressure',c['unavailable'])
    def test_missing_counter_is_null_with_reason_never_zero(self):
        with tempfile.TemporaryDirectory() as d:
            cgroup(d,omit=('cpu.stat',));c=bc.read_counters(Path(d),Path(d))
            self.assertIsNone(c['cpu']);self.assertEqual(c['unavailable']['cpu.stat'],'FileNotFoundError')
            dl=bc.delta(c,c);self.assertIsNone(dl['cpu_usage_usec']);self.assertIn('cpu.stat',dl['unavailable'])
    def test_malformed_counter_files_are_null_with_a_parse_reason(self):
        cases={'cpu.pressure':('some avg10=0.00 avg60=0.00 avg300=0.00\n','cpu_pressure'),
               'memory.pressure':('some avg10 total=3\n','memory_pressure'),
               'memory.current':('','memory_current'),'pids.peak':('many\n','pids_peak'),
               'cpu.stat':('usage_usec ten\n','cpu'),'memory.stat':('','memory_stat')}
        for name,(text,key) in cases.items():
            with self.subTest(name=name),tempfile.TemporaryDirectory() as d:
                cgroup(d);(Path(d)/'memory.pressure').write_text('some avg10=0.00 avg60=0.00 avg300=0.00 total=1\n')
                (Path(d)/name).write_text(text);c=bc.read_counters(Path(d),Path(d))
                self.assertIsNone(c[key]);self.assertEqual(c['unavailable'][name],'ParseError')
    def test_empty_pressure_file_is_a_parse_error(self):
        with tempfile.TemporaryDirectory() as d:
            cgroup(d);(Path(d)/'cpu.pressure').write_text('');c=bc.read_counters(Path(d),Path(d))
            self.assertIsNone(c['cpu_pressure']);self.assertEqual(c['unavailable']['cpu.pressure'],'ParseError')
    def test_delta_subtracts_cpu_and_wall(self):
        a={'perf_counter_ns':10,'cpu':{k:1 for k in bc.CPU_KEYS},'pids_current':1,'threads':2,'unavailable':{}}
        b={'perf_counter_ns':30,'cpu':{k:4 for k in bc.CPU_KEYS},'pids_current':2,'threads':5,'unavailable':{}}
        d=bc.delta(a,b);self.assertEqual((d['wall_ns'],d['cpu_usage_usec'],d['pids_end'],d['threads_end']),(20,3,2,5))

class ChannelTests(unittest.TestCase):
    def test_begin_and_end_are_acknowledged_after_a_counter_read(self):
        with tempfile.TemporaryDirectory() as d:
            reads=[];ch=bc.Channel(Path(d)/'m.sock',reader=lambda:reads.append(1) or {'n':len(reads)});self.addCleanup(ch.close)
            def child():
                m=Marker(str(Path(d)/'m.sock'))
                try:m.hello('c1');m.begin('work','t0');m.end('work','t0',units=3)
                finally:m.close()
            t=threading.Thread(target=child);t.start()
            ch.pump(lambda:sum(1 for e in ch.events if e['msg'].get('m')=='end')==1,time.monotonic()+5);t.join(5)
            kinds=[e['msg']['m'] for e in ch.events];self.assertEqual(kinds,['hello','begin','end'])
            self.assertEqual([e['sample'] for e in ch.events],[None,{'n':1},{'n':2}]);self.assertEqual(ch.events[-1]['msg']['units'],3)
    def test_marker_without_channel_is_a_no_op(self):
        m=Marker(None);self.assertEqual(m.begin('work','t'),{})

    def test_close_releases_every_connection_without_resource_warnings(self):
        with tempfile.TemporaryDirectory() as d, warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always',ResourceWarning)
            ch=bc.Channel(Path(d)/'m.sock',reader=lambda:{});m=Marker(str(Path(d)/'m.sock'))
            t=threading.Thread(target=lambda:(m.hello('c1'),m.begin('work','t0')));t.start()
            ch.pump(lambda:any(e['msg'].get('m')=='begin' for e in ch.events),time.monotonic()+5);t.join(5)
            held=list(ch.conns.items());self.assertEqual(len(held),1)
            ch.close();m.close();gc.collect()
            self.assertEqual([s.fileno() for s,_ in held],[-1]);self.assertTrue(all(f.closed for _,f in held))
            self.assertEqual((ch.conns,ch.open,m.sock.fileno()),({},{},-1))
            self.assertFalse(Path(d,'m.sock').exists())
        self.assertEqual([str(w.message) for w in caught if issubclass(w.category,ResourceWarning)],[])
    def test_client_eof_drops_the_connection_and_its_open_entry(self):
        with tempfile.TemporaryDirectory() as d:
            ch=bc.Channel(Path(d)/'m.sock',reader=lambda:{});self.addCleanup(ch.close)
            def child():
                m=Marker(str(Path(d)/'m.sock'))
                try:m.hello('c1')
                finally:m.close()
            t=threading.Thread(target=child);t.start()
            ch.pump(lambda:bool(ch.events) and not ch.open and not ch.conns,time.monotonic()+5);t.join(5)
            self.assertEqual((ch.open,ch.conns),({},{}))
    def test_malformed_messages_are_protocol_errors(self):
        for line in (b'{"m":"hello"}\n',b'{"m":"hello","client":7}\n',b'not json\n',b'[1]\n'):
            with self.subTest(line=line),tempfile.TemporaryDirectory() as d:
                ch=bc.Channel(Path(d)/'m.sock',reader=lambda:{});self.addCleanup(ch.close)
                s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);self.addCleanup(s.close)
                s.connect(str(Path(d)/'m.sock'));s.sendall(line)
                with self.assertRaises(bc.ProtocolError):ch.pump(lambda:False,time.monotonic()+5)
                self.assertEqual(ch.open,{})

class RuntimeIdentityTests(unittest.TestCase):
    def test_missing_gil_api_does_not_crash_or_impersonate_free_threading(self):
        r=bc.runtime_identity(type('S',(),{})(),gil_disabled_build=0)
        self.assertEqual((r['gil_enabled'],r['free_threaded_build']),(None,False));self.assertIn('not exposed',r['gil_label'])
    def test_exposed_gil_api_is_reported(self):
        r=bc.runtime_identity(type('S',(),{'_is_gil_enabled':staticmethod(lambda:True)})(),gil_disabled_build=0)
        self.assertEqual(r['gil_enabled'],True)
    def test_free_threaded_build_without_api_is_unverified(self):
        r=bc.runtime_identity(type('S',(),{})(),gil_disabled_build=1);self.assertIsNone(r['gil_enabled']);self.assertIn('unverified',r['gil_label'])

class RequestLimitTests(unittest.TestCase):
    """G-ALO-CO (item I13.1, step 2): the coordinator gives every child SAFE_C_BENCH_REQUEST_LIMIT, from the job plan's
    request_limit when it has one, else from the protected policy file."""
    POLICY=ROOT/'safety/performance-policy.json'
    def setUp(self):
        saved=dict(bc.REQUEST_LIMIT);self.addCleanup(lambda:(bc.REQUEST_LIMIT.clear(),bc.REQUEST_LIMIT.update(saved)))
    def test_the_plan_value_or_the_policy_value_reaches_every_child(self):
        bc.set_request_limit({'request_limit':14336},policy_path=Path('/nonexistent/policy.json'))
        self.assertEqual(bc.child_env()['SAFE_C_BENCH_REQUEST_LIMIT'],'14336')
        self.assertEqual(bc.child_env(7,{'X':'1'})['SAFE_C_BENCH_REQUEST_LIMIT'],'14336')
        bc.set_request_limit({},policy_path=self.POLICY)
        self.assertEqual(bc.child_env()['SAFE_C_BENCH_REQUEST_LIMIT'],str(json.loads(self.POLICY.read_text())['pools']['request_limit']))
        self.assertEqual(bc.POLICY_FILE,Path('/src/safety/performance-policy.json'))
    def test_a_malformed_limit_is_refused(self):
        for bad in (0,-1,True,14336.0,'14336',None):
            with self.subTest(value=bad),self.assertRaises(ValueError):bc.set_request_limit({'request_limit':bad},policy_path=self.POLICY)
        with self.assertRaises(ValueError):bc.set_request_limit({},policy_path=Path('/nonexistent/policy.json'))
    def test_main_sets_the_variable_before_the_job_runs(self):
        import contextlib, io
        from unittest import mock
        d=Path(tempfile.mkdtemp());seen={}
        def fake(plan,out):seen['env']=bc.child_env().get('SAFE_C_BENCH_REQUEST_LIMIT');return {'status':'PASS'}
        (d/'plan.json').write_text(json.dumps({'job':'fake-limit','output':'out','request_limit':14336}))
        with mock.patch.object(bc,'WORK',d),mock.patch.dict(bc.JOBS,{'fake-limit':fake}),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(bc.main(['x','plan.json']),0)
        self.assertEqual(seen['env'],'14336')
        (d/'plan.json').write_text(json.dumps({'job':'fake-limit','output':'out','request_limit':0}))
        seen.clear()
        with mock.patch.object(bc,'WORK',d),mock.patch.dict(bc.JOBS,{'fake-limit':fake}),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(bc.main(['x','plan.json']),1)
        self.assertEqual(seen,{});self.assertEqual(json.loads((d/'out/result.json').read_text())['reason'],'request_limit rejected')

class PanelPartTests(unittest.TestCase):
    """Task A6 (I7.2, H21): the five-model panel inputs exceed one container's holder lifetime (about 1,800 s), so `bench
    panel` runs them as row parts in separate jobs and one join job; the coordinator accepts exactly these plan forms."""
    def test_panel_mode(self):
        self.assertEqual(bc.panel_mode({}),('whole',0,1))
        self.assertEqual(bc.panel_mode({'panel_part':[2,8]}),('part',2,8))
        self.assertEqual(bc.panel_mode({'panel_join':8}),('join',0,8))
    def test_panel_mode_refuses_other_forms(self):
        for bad in ({'panel_part':[8,8]},{'panel_part':[0,1]},{'panel_part':[-1,4]},{'panel_part':[0,65]},{'panel_part':[True,4]},{'panel_part':'0/4'},
                    {'panel_join':1},{'panel_join':True},{'panel_join':65},{'panel_part':[0,2],'panel_join':2}):
            with self.subTest(bad=bad),self.assertRaises(ValueError):bc.panel_mode(bad)

class WarmStartBlockedTests(unittest.TestCase):
    """N4-A10: a warm C child that exits during its start makes that one row BLOCKED with a bounded reason (exit code and
    exception class only); the timing job runs every other row, and the host makes the run not VALID."""
    def trials(self):
        t=lambda i,v,r:{'trial_id':f't{i}','scope':'caller','point':'p','variant':v,'workers':'direct','mode':'warm','route':r,'tier':'small','warmup':False}
        return [t(0,'py-reference',None),t(1,'c-serial','shm'),t(2,'c-serial','stdio'),t(3,'c-serial','shm'),t(4,'py-reference',None)]
    def run_job(self,refuse):
        from unittest import mock
        started=[];called=[]
        class Proc:
            returncode=0
            def poll(self):return 0
        class Child:
            def __init__(self,channel,plan,trial,dataset,reference,deadline,memory=False,extra=None):
                self.key=bc.child_key(trial);self.trial=trial;self.start=0;self.proc=Proc();started.append(self.key)
                if refuse(trial):
                    e=bc.ChildExited('trial child exited');e.returncode=3;e.error_class='benchlab.native_worker.BinaryRefused';raise e
            def identity(self):return {'isolated':True}
            def call(self,trial,size,deadline):called.append(trial['trial_id']);return 0
            def shutdown(self,deadline):return 0
        class Channel:
            def __init__(self,path):self.events=[]
            def close(self):pass
        native=type('N',(),{'caller_env':staticmethod(lambda plan:{}),'native_shm_snapshot':staticmethod(lambda:{}),'job_end_check':staticmethod(lambda before:[]),'SHM_LEFT':'x'})
        with tempfile.TemporaryDirectory() as tmp:
            ref=Path(tmp)/'ref.json';ref.write_text('{}');out=Path(tmp)/'out';out.mkdir()
            ev=lambda channel,start,tid,kind=None,phase=None:[{'sample':{},'msg':{'trial':tid}}]
            with mock.patch.multiple(bc,CallerChild=Child,Channel=Channel,_bench_native=native,WORK=Path(tmp),CG=Path(tmp),_events=ev,_pairs_of=lambda *a:[],
                                     materialize_dataset=lambda plan:{'path':'d','sha256':'0'*64},reference_path=lambda plan,ds:str(ref),read_counters=lambda *a,**k:{},
                                     observation=lambda plan,trial,phase,b,e,n,runner,warmup:{'trial_id':trial['trial_id']}):
                row=bc.JOBS['timing']({'trials':self.trials(),'deadline_seconds':600,'sizes':{'small':4}},out)
                obs=[json.loads(x)['trial_id'] for x in (out/'observations.jsonl').read_text().splitlines()]
        return row,obs,started,called
    def test_a_failed_warm_c_start_blocks_only_its_row(self):
        row,obs,started,called=self.run_job(lambda t:t.get('route')=='shm')
        self.assertEqual(row['status'],'PASS')                        # the job completed every row it could run
        self.assertEqual(obs,['t0','t2','t4']);self.assertEqual(called,['t0','t2','t4'])
        self.assertEqual(started.count('c-serial:direct:warm:shm'),1)  # one start attempt; the later trial of the row is not retried
        self.assertEqual(row['blocked_rows'],[{'variant':'c-serial','workers':'direct','route':'shm','mode':'warm','selector':'all','trials':['t1','t3'],
                                               'reason':'warm C start failed (child exit 3, benchlab.native_worker.BinaryRefused)'}])
        self.assertEqual(row['child_exit_codes'],[0,0])
    def test_a_python_start_failure_still_ends_the_job(self):
        with self.assertRaises(bc.ChildExited):self.run_job(lambda t:t['variant']=='py-reference')
    def test_a_job_without_a_blocked_row_has_no_blocked_rows_key(self):
        row,obs,_,_=self.run_job(lambda t:False)
        self.assertNotIn('blocked_rows',row);self.assertEqual(obs,['t0','t1','t2','t3','t4']);self.assertEqual(row['status'],'PASS')
