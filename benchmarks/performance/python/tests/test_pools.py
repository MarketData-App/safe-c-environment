import json, os, tempfile, hashlib, multiprocessing, time, unittest, warnings
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import psutil
from benchlab.pools import start_pool, run_pool, verify_thread_environment, chunk_bounds, POOLED, ensure_tracker, verify_session_end, is_tracker_cmdline, _init_worker
from benchlab.controlcase import Spin, Wait, Touch
from benchlab.recordscan import RecordScan, scan_reference, scan_optimized
P={'rounds':200,'wait_us':200,'touch_kib':64,'seed':20261007}
LIMIT=json.loads(Path('/src/safety/performance-policy.json').read_text())['pools']['request_limit']   # G-ALO-CO: pooled controls need the limit
SEEDS=list(range(300))
ONE_PER_CHUNK={'seeds':SEEDS,'chunks':[[s] for s in SEEDS]}

def stderr_of(fn):
    """Run fn with file descriptor 2 redirected (spawned children inherit it); return (stderr bytes, exception or None)."""
    with tempfile.TemporaryFile() as tmp:
        saved=os.dup(2);os.dup2(tmp.fileno(),2);error=None
        try:fn()
        except Exception as exc:error=exc
        finally:os.dup2(saved,2);os.close(saved)
        tmp.seek(0);return tmp.read(),error

def other_children():
    return [c for c in psutil.Process().children(recursive=True) if not is_tracker_cmdline(c.cmdline())]

class PoolTests(unittest.TestCase):
    def test_every_control_pool_matches_its_reference(self):
        for cls in (Spin,Wait,Touch):
            w=cls(P,request_limit=LIMIT);ref=w.reference(SEEDS)
            for variant in POOLED:
                for workers in (1,2):
                    with start_pool(variant,workers,w.bench_ref) as ex:got=w.materialize(run_pool(w,w.prepare(SEEDS,variant,workers),workers,ex))
                    with self.subTest(control=cls.__name__,variant=variant,workers=workers):self.assertTrue(w.validate(got,ref,SEEDS)['eligible'])
    def test_thread_errors_propagate_and_the_window_is_bounded(self):
        w=Spin(P,request_limit=LIMIT);calls=[]
        def failing(chunk):
            calls.append(1)
            if len(calls)==3:raise RuntimeError('chunk failure')
            return w.run_chunk(chunk)
        stats={}
        with start_pool('py-threads',2) as ex:
            with self.assertRaises(RuntimeError):run_pool(w,dict(ONE_PER_CHUNK),2,ex,stats=stats,chunk_fn=failing)
        # M5: queued chunks after the error did not run; only submitted chunks can run
        self.assertEqual(stats['outcome'],'error');self.assertLessEqual(len(calls),stats['submitted']);self.assertLessEqual(stats['submitted'],3+2*4)
        self.assertLessEqual(stats['max_pending'],4)
        stats={}
        with start_pool('py-threads',2) as ex:run_pool(w,w.prepare(SEEDS,'py-threads',2),2,ex,stats=stats)
        self.assertLessEqual(stats['max_pending'],4);self.assertEqual(stats['window'],4);self.assertEqual(stats['chunks'],len(chunk_bounds(300,2)))
        self.assertEqual(stats['chunks'],2);self.assertEqual(stats['chunk_sizes'],[150,150]);self.assertEqual(stats['chunk_rule'],'one-per-worker')   # Amendment E
        self.assertEqual(len(stats['chunk_wall_ns']),2);self.assertTrue(all(isinstance(t,int) and t>=0 for t in stats['chunk_wall_ns']))
        self.assertEqual((stats['outcome'],stats['submitted']),('ok',stats['chunks']))
    def test_control_combine_refuses_parts_that_do_not_cover_every_position(self):
        """Review Minor 4: Control.combine scatters gathered parts; a missing position is an error, not a None value."""
        w=Spin(P,request_limit=LIMIT)
        self.assertEqual(w.combine([{'index':[1,3],'values':[11,13]},{'index':[0,2],'values':[10,12]}]),[10,11,12,13])
        self.assertEqual(w.combine([[1,2],[3]]),[1,2,3]);self.assertEqual(w.combine([]),[])
        with self.assertRaises(ValueError):w.combine([{'index':[0,0],'values':[10,12]}])                 # overlap: position 1 uncovered
        with self.assertRaises(ValueError):w.combine([{'index':[0,5],'values':[1,2]}])                   # position outside 0..n-1
        with self.assertRaises(ValueError):w.combine([{'index':[0,1],'values':[1]}])                     # one value per position
    def test_a_dict_chunk_without_its_gather_index_is_refused_before_submission(self):
        """Review Minor 1: run_pool refuses a dict chunk without `index` with a clear error; no chunk runs."""
        class W:
            calls=0
            def chunks(self,prepared,workers):return [{'n':2,'seeds':[1,2]}]
            def run_chunk(self,chunk):W.calls+=1;return chunk
            def combine(self,parts):return parts
        with start_pool('py-threads',1) as ex:
            with self.assertRaises(ValueError) as cm:run_pool(W(),{},1,ex)
        self.assertIn('index',str(cm.exception));self.assertEqual(W.calls,0)
    def test_control_chunks_are_gathered_by_the_pool_index(self):
        from benchlab.pools import chunk_indices
        w=Spin(P,request_limit=LIMIT);p=w.prepare(SEEDS,'py-processes',2)
        self.assertEqual([c['index'] for c in p['chunks']],chunk_indices(len(SEEDS),2,LIMIT))
        self.assertTrue(all(c['seeds']==[SEEDS[i] for i in c['index']] for c in p['chunks']))
    def test_a_deadline_is_a_timeout_not_a_cancel(self):
        w=Spin(P,request_limit=LIMIT)
        def slow(chunk):time.sleep(0.3);return w.run_chunk(chunk)
        stats={}
        with start_pool('py-threads',1) as ex:
            with self.assertRaises(TimeoutError):run_pool(w,dict(ONE_PER_CHUNK),1,ex,stats=stats,chunk_fn=slow,timeout=0.05)
        self.assertEqual(stats['outcome'],'timeout');self.assertLessEqual(stats['submitted'],2)
        for bad in (0,-1.0,True,'1'):
            with self.subTest(timeout=bad):
                with start_pool('py-threads',1) as ex:
                    with self.assertRaises(ValueError):run_pool(w,dict(ONE_PER_CHUNK),1,ex,timeout=bad)
    def test_workers_must_match_the_pool(self):
        w=Spin(P,request_limit=LIMIT)
        with start_pool('py-threads',2) as ex:
            for bad in (1,4,True,0):
                with self.subTest(workers=bad):
                    with self.assertRaises(ValueError):run_pool(w,w.prepare(SEEDS,'py-threads',2),bad,ex)
    def test_initializer_failure_keeps_its_cause_and_prints_no_traceback(self):
        w=Spin(P,request_limit=LIMIT)
        for ref,kind in ((('benchlab.no_such_module:Thing',{}),ModuleNotFoundError),(('benchlab.recordscan:RecordScan',{}),KeyError)):
            def go():
                with start_pool('py-processes',1,ref) as ex:run_pool(w,w.prepare(SEEDS,'py-processes',1),1,ex)
            err,error=stderr_of(go)
            with self.subTest(ref=ref[0]):
                self.assertIsInstance(error,kind);self.assertNotIn(b'Traceback',err)
                if kind is ModuleNotFoundError:self.assertIn('no_such_module',str(error))
    def test_a_passed_pool_reports_its_actual_start_method(self):
        w=Spin(P,request_limit=LIMIT);stats={}
        with warnings.catch_warnings():
            warnings.simplefilter('ignore',DeprecationWarning)
            with ProcessPoolExecutor(max_workers=1,mp_context=multiprocessing.get_context('fork'),initializer=_init_worker,initargs=(w.bench_ref,)) as ex:
                run_pool(w,w.prepare(SEEDS,'py-processes',1),1,ex,stats=stats)
        self.assertEqual(stats['start_method'],'fork')
    def test_process_errors_propagate_and_cleanup_leaves_no_worker(self):
        tracker=ensure_tracker();self.assertEqual(tracker['label'],'session-setup');self.assertIsInstance(tracker['pid'],int)
        w=Spin(dict(P,rounds=-1),request_limit=LIMIT);stats={}
        with self.assertRaises(ValueError):
            with start_pool('py-processes',2,w.bench_ref) as ex:run_pool(w,dict(ONE_PER_CHUNK),2,ex,stats=stats)
        self.assertEqual(stats['outcome'],'error');self.assertLessEqual(stats['max_pending'],4);self.assertLess(stats['submitted'],len(SEEDS))
        self.assertTrue(stats['tracker_session_setup'])
        self.assertEqual(other_children(),[])
        ok=Spin(P,request_limit=LIMIT)
        with start_pool('py-processes',2,ok.bench_ref) as ex:run_pool(ok,ok.prepare(SEEDS,'py-processes',2),2,ex)
        self.assertEqual(other_children(),[])
        # the tracker is session infrastructure: the trials neither restart nor stop it
        self.assertEqual(ensure_tracker()['pid'],tracker['pid'])
        self.assertEqual(verify_session_end(),{'tracker_pids':[tracker['pid']],'other_pids':[]})
    def test_b10_identity_threads_in_the_caller_processes_outside(self):
        w=Spin(P,request_limit=LIMIT)
        for variant,workers in (('py-threads',2),('py-processes',2)):
            stats={}
            with start_pool(variant,workers,w.bench_ref) as ex:
                run_pool(w,w.prepare(SEEDS,variant,workers),workers,ex,stats=stats)
                if variant=='py-processes':self.assertEqual(ex._mp_context.get_start_method(),'spawn')
            with self.subTest(variant=variant):
                self.assertLessEqual(stats['max_pending'],stats['window'])
                if variant=='py-threads':self.assertEqual((stats['caller_pid_included'],stats['pids_distinct'],stats['start_method']),(True,1,'thread'))
                else:self.assertFalse(stats['caller_pid_included']);self.assertTrue(1<=stats['pids_distinct']<=workers);self.assertEqual(stats['start_method'],'spawn')
    def test_a_foreign_executor_is_refused_clearly(self):
        """Task 12a re-review: run_pool reads _max_workers and _mp_context only through a guard."""
        w=Spin(P,request_limit=LIMIT)
        class Foreign:
            def submit(self,*a,**k):raise AssertionError('never submitted')
        with self.assertRaises(ValueError) as ctx:run_pool(w,w.prepare(SEEDS,'py-threads',1),1,Foreign())
        self.assertIn('start_pool',str(ctx.exception))
        ex=ProcessPoolExecutor(max_workers=1,mp_context=multiprocessing.get_context('spawn'))
        try:
            ex._mp_context=None
            with self.assertRaises(ValueError) as ctx:run_pool(w,w.prepare(SEEDS,'py-processes',1),1,ex)
            self.assertIn('start_pool',str(ctx.exception))
        finally:ex.shutdown(wait=True)
    def test_process_pool_needs_a_workload_reference(self):
        with self.assertRaises(ValueError):start_pool('py-processes',1)
        with self.assertRaises(ValueError):start_pool('py-reference',1)
    def test_thread_environment_is_one_everywhere(self):
        self.assertEqual(set(verify_thread_environment().values()),{'1'})
    def test_record_scan_variants_agree_exactly(self):
        cs=RecordScan({'day_min':7,'day_max':60,'ratio_lo':0.9,'ratio_hi':1.1,'seed':1});raw=cs.synthesize(300,9)
        p=Path(tempfile.mkdtemp())/'scan.bin';p.write_bytes(raw);data=cs.load({'path':str(p),'sha256':hashlib.sha256(raw).hexdigest()})
        self.assertEqual(scan_reference(data,7,60,0.9,1.1),scan_optimized(data,7,60,0.9,1.1))
        with self.assertRaises(ValueError):cs.prepare(data,'py-threads',2)
