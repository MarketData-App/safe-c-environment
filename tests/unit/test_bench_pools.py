import json, math, sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'benchmarks/performance/python'))
sys.path.insert(0,str(ROOT/'tools'))
from benchlab.pools import chunk_bounds, request_splits, start_pool, is_tracker_cmdline
from benchlab.recordscan import pack, scan_reference, RECORD, RecordScan
from benchlab.controlcase import Spin, Wait, Touch
import bench_model as bm
import bench_plan as bp
LIMIT=json.loads((ROOT/'safety/performance-policy.json').read_text())['pools']['request_limit']   # G-ALO-CO: 14,336 (Amendment I item I5.5)
SCAN={'day_min':7,'day_max':60,'ratio_lo':0.9,'ratio_hi':1.1,'seed':20261007}

# Task 16a controller ruling, Task 19a residual: the spin control holds one primary-class qualification point (12 blocks, so 6 per A/A half; warm caller).
QUAL_POINTS={'bench-control-spin':[{'name':'qual-caller','scope':'caller','size':'small','modes':['warm'],'variants':['py-reference','py-threads','py-processes'],'class':'primary'}]}

class ChunkTests(unittest.TestCase):
    def test_known_answer_vectors(self):
        from benchlab.pools import SplitMix64, PARTITION_SEED, permutation
        g=SplitMix64(PARTITION_SEED);self.assertEqual([g.next() for _ in range(3)],[0xae58eab7f35199e4,0xa16951b663213f43,0xcc4ea8b7bd8207bd])
        self.assertEqual(permutation(10,0),[0,3,1,4,8,2,7,9,5,6]);self.assertEqual(permutation(10,1),[9,6,2,7,8,5,1,3,4,0])
        self.assertEqual(chunk_bounds(10,4),[[0,3],[1,4,8],[2,7],[5,6,9]])
    def test_chunk_size_rule(self):
        from benchlab.pools import chunk_sizes
        self.assertEqual(chunk_sizes(10,4,LIMIT),[2,3,2,3]);self.assertEqual(chunk_sizes(13230,4,LIMIT),[3307,3308,3307,3308])
        self.assertEqual(chunk_sizes(300,2,LIMIT),[150,150]);self.assertEqual(chunk_sizes(3,4,LIMIT),[1,1,1]);self.assertEqual(chunk_sizes(1,2,LIMIT),[1])
        self.assertEqual(chunk_bounds(0,2),[]);self.assertEqual(chunk_bounds(256,1),[list(range(256))])
    def test_request_chunks_split_requests_first(self):
        from benchlab.pools import request_chunks, chunk_sizes
        req=request_chunks(20000,2,14336);self.assertEqual(len(req),2)
        self.assertEqual(sorted(i for c in req[0] for i in c),list(range(14336)));self.assertEqual(sorted(i for c in req[1] for i in c),list(range(14336,20000)))
        self.assertEqual(chunk_sizes(20000,2,14336),[7168,7168,2832,2832]);self.assertEqual(request_chunks(0,4,14336),[]);self.assertLessEqual(len(chunk_sizes(20000,4,14336)),8)
    def test_every_partition_function_requires_the_limit(self):
        """G-ALO-CO (item I13.1): no default limit. A missing limit is a TypeError; a non-positive or non-integer limit a ValueError."""
        from benchlab.pools import request_chunks, chunk_indices, chunk_sizes
        for fn,args in ((request_splits,(10,)),(request_chunks,(10,2)),(chunk_indices,(10,2)),(chunk_sizes,(10,2))):
            with self.subTest(fn=fn.__name__):
                with self.assertRaises(TypeError):fn(*args)
                for bad in (0,-1,True,2.0,'16',None):
                    with self.subTest(limit=bad),self.assertRaises(ValueError):fn(*args,bad)
                self.assertTrue(fn(*args,LIMIT) is not None)
        self.assertEqual(LIMIT,14336)
    def test_scatter_round_trip_keeps_row_order(self):
        from benchlab.pools import request_chunks
        rows=list(range(37))
        for w in (1,2,4):
            back=[None]*37
            for req in request_chunks(37,w,limit=16):
                for idx in req:
                    part=[rows[i] for i in idx]
                    for i,v in zip(idx,part):back[i]=v
            with self.subTest(w=w):self.assertEqual(back,rows)
    def test_periodic_and_sorted_inputs_are_broken_up(self):
        """Amendment E item 1: no chunk gets one residue class of a period (generator pattern) or one end of a sorted chain."""
        for w in (2,4):
            chunks=chunk_bounds(1024,w)
            for period in (2,4,16):
                with self.subTest(w=w,period=period):
                    self.assertTrue(all(len({i%period for i in c})==period for c in chunks))
            with self.subTest(w=w,sorted=True):     # each chunk spans the sorted order: some index in every quarter
                self.assertTrue(all(all(any(q*256<=i<(q+1)*256 for i in c) for q in range(4)) for c in chunks))
    def test_host_rule_copy_matches(self):
        sys.path.insert(0,str(ROOT/'tools'));import bench_plan
        from benchlab.pools import chunk_sizes
        for n in (0,1,3,10,256,1024,13230,14336,14337,16384,20000):
            for w in (1,2,4):
                with self.subTest(n=n,w=w):self.assertEqual(bench_plan.expected_chunk_sizes(n,w,14336),chunk_sizes(n,w,14336))
    def test_bounded_draw_rejection_path(self):
        """Review Minor 3: the Lemire rejection loop. t = 3: threshold = (2**64 - 3) % 3 = 1. A first output 0 gives
        low = 0 < threshold (rejected); the second output 2**63 gives p = 3 * 2**63, low = 2**63 (accepted), result 1.
        An output with 0 < low < t but low >= threshold is accepted at once: x = 3**-1 mod 2**64 gives low = 1, result 2."""
        from benchlab import pools
        class Stub(pools.SplitMix64):
            def __init__(self,outputs):super().__init__(0);self.outputs=list(outputs);self.calls=0
            def next(self):self.calls+=1;return self.outputs.pop(0)
        self.assertEqual(((1<<64)-3)%3,1)
        g=Stub([0,1<<63]);self.assertEqual((g.bounded(3),g.calls),(1,2))                      # one rejection, p recomputed
        g=Stub([0,0,0,(1<<64)-1]);self.assertEqual((g.bounded(3),g.calls),(2,4))              # three rejections in a row
        inv3=pow(3,-1,1<<64);self.assertEqual((3*inv3)&((1<<64)-1),1)
        g=Stub([inv3]);self.assertEqual((g.bounded(3),g.calls),(2,1))                         # low < t, not below the threshold
        g=Stub([(1<<64)-1]);self.assertEqual((g.bounded(1<<32),g.calls),((1<<32)-1,1))      # threshold 0 at t = 2**32
        for bad in (0,(1<<32)+1,True,2.0):
            with self.subTest(t=bad),self.assertRaises(ValueError):pools.SplitMix64(1).bounded(bad)
    def test_plan_constants_equal_the_pool_constants(self):
        """Review Minor 8: tools/bench_plan.py copies the pool constants (the host imports no benchlab)."""
        from benchlab import pools
        self.assertEqual(bp.PARTITION_SEED,'0x%016X'%pools.PARTITION_SEED);self.assertEqual(bp.PARTITION,pools.PARTITION)
        self.assertEqual(bp.CHUNK_RULE,pools.CHUNK_RULE)
    def test_a_dict_chunk_without_its_gather_index_is_refused(self):
        """Review Minor 1: a dict chunk must carry `index` (run_pool's refusal before submission: test_pools.py)."""
        from benchlab.pools import _chunk_size
        self.assertEqual(_chunk_size({'index':[0,2,5]}),3);self.assertEqual(_chunk_size([1,2]),2)
        for bad in ({'n':3,'S':[1,2,3]},7):
            with self.subTest(chunk=bad),self.assertRaises(ValueError):_chunk_size(bad)
    def test_l2_request_splits(self):
        self.assertEqual(request_splits(13230,14336),[(0,13230)])
        self.assertEqual(request_splits(20000,14336),[(0,14336),(14336,20000)])
        self.assertEqual(request_splits(16384,14336),[(0,14336),(14336,16384)]);self.assertEqual(request_splits(16385,14336),[(0,14336),(14336,16385)])
        self.assertEqual(request_splits(14336,14336),[(0,14336)]);self.assertEqual(request_splits(14337,14336),[(0,14336),(14336,14337)])
        self.assertEqual(request_splits(0,14336),[])
        with self.assertRaises(ValueError):request_splits(-1,14336)
    def test_worker_count_is_a_positive_integer(self):
        for bad in (0,-1,True,False,2.0,'2',None):
            with self.subTest(workers=bad):
                with self.assertRaises(ValueError):start_pool('py-threads',bad)
                with self.assertRaises(ValueError):start_pool('py-processes',bad,('benchlab.controlcase:Spin',{}))
    def test_tracker_is_identified_by_its_command_line(self):
        self.assertTrue(is_tracker_cmdline(['/usr/bin/python3','-B','-c','from multiprocessing.resource_tracker import main;main(5)']))
        self.assertFalse(is_tracker_cmdline(['/usr/bin/python3','-c','from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=5)']))
        self.assertFalse(is_tracker_cmdline([]))

class TrackerSetupTests(unittest.TestCase):
    """PL-FLAKY-B13-01: resource_tracker.ensure_running() returns after the fork, before the tracker child completes exec.
    A /proc scan in that window sees the parent's command line. Session setup must wait for the exec (bounded) and
    still require exactly one tracker."""
    PRE_EXEC=(41,['/usr/bin/python3','-m','benchlab.trial','--client','py-processes:4:warm'])
    TRACKER=(41,['/usr/bin/python3','-B','-c','from multiprocessing.resource_tracker import main;main(5)'])
    def _setup(self,scans,clock=None,sleeps=None):
        from unittest import mock
        from benchlab import pools
        calls=iter(scans);sleeps=[] if sleeps is None else sleeps
        patches=[mock.patch.object(pools.resource_tracker,'ensure_running',lambda:None),
                 mock.patch.object(pools,'_descendants',lambda:next(calls)),
                 mock.patch.object(pools,'_sleep',lambda s:sleeps.append(s),create=True)]
        if clock is not None:patches.append(mock.patch.object(pools,'_clock',clock,create=True))
        saved=dict(pools._SESSION)
        try:
            for x in patches:x.start()
            return pools.ensure_tracker(),sleeps
        finally:
            for x in reversed(patches):x.stop()
            pools._SESSION.clear();pools._SESSION.update(saved)
    def test_tracker_found_after_exec_completes(self):
        result,sleeps=self._setup([[self.PRE_EXEC],[self.PRE_EXEC],[self.TRACKER]])
        self.assertEqual(result,{'label':'session-setup','pid':41});self.assertEqual(len(sleeps),2)
    def test_tracker_still_missing_after_the_settle_deadline_fails(self):
        import itertools
        ticks=itertools.count(0.0,0.5)
        with self.assertRaises(RuntimeError):self._setup(itertools.repeat([self.PRE_EXEC]),clock=lambda:next(ticks))
    def test_two_trackers_fail_without_waiting(self):
        sleeps=[]
        with self.assertRaises(RuntimeError):self._setup([[self.TRACKER,(42,self.TRACKER[1])]],sleeps=sleeps)
        self.assertEqual(sleeps,[])

class RecordScanTests(unittest.TestCase):
    def test_exact_integer_sum(self):
        records={'n':3,'kind':[0,1,-1],'base':[100.0,100.0,100.0],'level':[100.0,95.0,150.0],'span':[30/365,30/365,30/365],'low':[1.0]*3,'high':[1.1]*3,'weight':[7.0,9.0,11.0]}
        data=pack(records);self.assertEqual(len(data),3*RECORD.size)
        self.assertEqual(scan_reference(data,7,60,0.9,1.1),{'count':2,'weight':16,'records':3})
    def test_generator_is_seeded_and_needs_no_project_code(self):
        cs=RecordScan(SCAN);a=cs.synthesize(64,1)
        self.assertEqual(a,cs.synthesize(64,1));self.assertNotEqual(a,cs.synthesize(64,2));self.assertEqual(len(a),64*RECORD.size)
    def test_slice_bounds(self):
        cs=RecordScan(SCAN);d=cs.synthesize(4,1)
        self.assertEqual(len(cs.slice(d,0)),0);self.assertEqual(len(cs.slice(d,4)),len(d))
        with self.assertRaises(ValueError):cs.slice(d,5)
        with self.assertRaises(ValueError):cs.slice(d,-1)
    def test_day_window_compares_whole_days_exactly(self):
        days=[6,29,5,30,0,400];n=len(days)
        records={'n':n,'kind':[0]*n,'base':[100.0]*n,'level':[100.0]*n,'span':[d/365.0 for d in days],'low':[1.0]*n,'high':[1.1]*n,'weight':[1.0]*n}
        self.assertEqual(scan_reference(pack(records),6,29,0.9,1.1),{'count':2,'weight':2,'records':n})
        self.assertEqual(scan_reference(pack(records),0,400,0.9,1.1)['count'],n)
        odd=dict(records,n=3,span=[math.nan,math.inf,-math.inf],kind=[0]*3,base=[100.0]*3,level=[100.0]*3,low=[1.0]*3,high=[1.1]*3,weight=[1.0]*3)
        self.assertEqual(scan_reference(pack(odd),-10**9,10**9,0.0,10.0),{'count':0,'weight':0,'records':3})
    def test_whole_days_of_a_huge_finite_span_are_out_of_window(self):
        """Task 12a re-review: a finite span whose span*365.0 overflows is out of the window, never an OverflowError."""
        from benchlab.recordscan import whole_days
        for span in (1e307,1.7976931348623157e308,-1e307):
            with self.subTest(span=span):self.assertIsNone(whole_days(span))
        self.assertEqual(whole_days(30/365.0),30)
        n=2;records={'n':n,'kind':[0]*n,'base':[100.0]*n,'level':[100.0]*n,'span':[1e307,30/365.0],'low':[1.0]*n,'high':[1.1]*n,'weight':[1.0]*n}
        self.assertEqual(scan_reference(pack(records),-10**9,10**9,0.0,10.0),{'count':1,'weight':1,'records':2})
    def test_pack_rejects_a_fractional_weight(self):
        records={'n':1,'kind':[0],'base':[100.0],'level':[100.0],'span':[0.1],'low':[1.0],'high':[1.1],'weight':[7.9]}
        with self.assertRaises(ValueError):pack(records)
        self.assertEqual(len(pack(dict(records,weight=[math.nan]))),RECORD.size)

class ControlTests(unittest.TestCase):
    P={'rounds':10,'wait_us':0,'touch_kib':8,'seed':20261007}
    def test_controls_are_deterministic_and_exact(self):
        for cls in (Spin,Wait,Touch):
            w=cls(self.P);seeds=json.loads(w.synthesize(5,3))['seeds'];ref=w.reference(seeds)
            with self.subTest(control=cls.__name__):
                self.assertEqual(ref,w.reference(seeds));self.assertEqual(w.work_units(ref),5);self.assertTrue(w.validate(ref,ref,seeds)['eligible'])
                self.assertEqual(len(w.digest(ref)),64);self.assertEqual(w.slice_result(ref,2,seeds[:2]),w.reference(seeds[:2]))
                short={'values':ref['values'][:4]};v=w.validate(short,ref,seeds);self.assertFalse(v['eligible']);self.assertEqual(v['reduction'],'ROW_COUNT')
    def test_boundaries(self):
        w=Spin(self.P)
        self.assertEqual(json.loads(w.synthesize(0,1))['seeds'],[]);self.assertEqual(w.reference([]),{'values':[]})
        self.assertEqual(json.loads(w.synthesize(1,1))['seeds'],[1000003%4294967296])
        with self.assertRaises(ValueError):w.synthesize(-1,1)
        with self.assertRaises(ValueError):Spin(dict(self.P,rounds=-1)).reference([1])
        with self.assertRaises(ValueError):Touch(dict(self.P,touch_kib=-1)).reference([1])
        with self.assertRaises(ValueError):Wait(dict(self.P,wait_us=-1)).reference([1])
        for bad in ('10',10.0,True,None):
            with self.subTest(rounds=bad):
                with self.assertRaises(ValueError):Spin(dict(self.P,rounds=bad)).reference([1])
    def test_bench_ref_names_the_class(self):
        self.assertEqual(Spin(self.P).bench_ref,('benchlab.controlcase:Spin',self.P,'all',None))
        self.assertEqual(Spin(self.P,request_limit=LIMIT).bench_ref,('benchlab.controlcase:Spin',self.P,'all',LIMIT))   # G-ALO-CO: four items

class ManifestTests(unittest.TestCase):
    """The three framework control manifests and the record-scan adapter (no project code) (Task 12a Interfaces)."""
    CONTROLS={'bench-control-spin':('Spin','rounds',2000),'bench-control-wait':('Wait','wait_us',1000),'bench-control-touch':('Touch','touch_kib',1024)}
    def test_control_manifests_hold_the_declared_values(self):
        policy=bm.load_policy(ROOT)
        for case_id,(cls,key,value) in self.CONTROLS.items():
            with self.subTest(case=case_id):
                case=bm.load_case(ROOT,case_id);self.assertTrue(bm.case_rules(ROOT,case));self.assertEqual(bp.point_problems(case,policy),[])
                self.assertEqual((case['kind'],case['adapter'],case['scopes'],case['sizes'],case['points'],case['opportunity_record']),
                                 ('function','benchlab.controlcase:'+cls,['kernel','caller','capacity'] if case_id=='bench-control-spin' else ['kernel','caller'],   # ruling T22-C1
                                  ['tiny','small','medium'],QUAL_POINTS.get(case_id,[]),None))
                self.assertEqual(case['parameters'],{key:{'value':value,'label':'protocol'},'seed':{'value':20261007,'label':'protocol'}})
                rows={v['id']:(v['workers'],v['status'],v.get('reason')) for v in case['variants']}
                self.assertEqual(rows,{'py-reference':(['direct'],'implemented',None),
                                       'py-optimized':(['direct'],'same-as-reference','control: no separate optimized implementation'),
                                       'py-threads':([1,2,4],'implemented',None),'py-processes':([1,2,4],'implemented',None)})
    def test_record_scan_uses_the_framework_adapter(self):
        self.assertEqual(bm.load_case(ROOT,'record-scan')['adapter'],'benchlab.recordscan:RecordScan')
