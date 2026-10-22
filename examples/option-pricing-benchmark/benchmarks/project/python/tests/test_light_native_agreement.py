"""EX-12 (T21; Phase 2 Task 22 adapted by ruling R50): the light tests of the C agreement check native-agreement
(optionlab.native_agreement) that need no native binary. The check itself runs the real pl-worker, pl-kernel and
libpl_inproc.so under `bench check --check native-agreement --native` and as the run gate of every bench run with C rows
(bench.json native.agreement). These tests hold the plan's shape tests, the mutation evidence of R50 item f (the judging
functions that the check uses FAIL when the C result of one model is replaced by another model's part, and when one route
returns a different result) and the T19-A01 carry (limit rows that do not repeat with a period that divides the request
limit, compared with the reference of the same rows). REQUIRE-style unittest assertions; no assert statement."""
import copy, math, re, struct, unittest
from unittest import mock
from benchlab.workload import request_limit
from optionlab import native_agreement as na
from optionlab import native_check, protocol
from optionlab.contract import FIELDS, MODELS5
from optionlab.reference import canonical_result

NAN=math.nan

def column(values,status=('OK','NO_BID')):
    """One model part of len(status) rows: the OK rows hold `values`, the other rows NaN."""
    return {'status':list(status),'flags':[0]*len(status),**{f:[v if s=='OK' else NAN for v,s in zip(values,status)] for f in FIELDS}}

def reference(n=2):
    """A five-model result whose parts differ from each other (model k holds 0.1 (k + 1) + i / 1000 in row i)."""
    status=('OK','NO_BID','OK')[:n]
    return {'n':n,'models':{m:column([0.1*(k+1)+i/1000 for i in range(n)],status) for k,m in enumerate(MODELS5)}}

def outcome(result):
    return {'bytes':canonical_result(result),'result':result,'n':result['n']}

def per_model_fixture(ref):
    """The C outcomes of the per-model and projection jobs, each equal to the reference, and the wanted bytes."""
    c={};want={}
    for tier in ('tiny','small'):
        for mask in range(1,32):
            sel=na.select(ref,na.models_of(mask))
            if mask in na.PER_MODEL_MASKS:want[('proj',mask,tier)]=canonical_result(sel)
            for cell in na.ROUTE_CELLS:c[(cell,'proj',mask,tier)]=outcome(sel)
    return c,want

class AgreementShapeTests(unittest.TestCase):
    def test_sample_and_tiers(self):
        self.assertEqual(na.TIERS,('tiny','small','medium'))
        self.assertEqual(len(range(0,13230,na.LARGE_SAMPLE_STEP)),509)
        self.assertEqual(na.LARGE_ROWS,13230)
        self.assertEqual(na.sample_indices(),list(range(0,13230,26)))
    def test_digest_rows_restricts_and_is_stable(self):
        col={'status':['OK','NO_BID'],'flags':[0,0],**{f:[0.5,NAN] for f in ('iv','price','delta','gamma','theta','vega','rho')}}
        res={'n':2,'models':{m:dict(col) for m in ('bsm','bjs','crr')}}
        self.assertEqual(na.digest_rows(res,[0]),na.digest_rows(res,[0]));self.assertNotEqual(na.digest_rows(res,[0]),na.digest_rows(res,[1]))
        self.assertRegex(na.digest_rows(res,[0,1]),r'^[0-9a-f]{64}$')
    def test_projection_compares_every_mask_part(self):
        col={'status':['OK'],'flags':[0],**{f:[0.5] for f in ('iv','price','delta','gamma','theta','vega','rho')}}
        full={'n':1,'models':{m:dict(col) for m in ('bsm','bjs','crr','baw','alo')}}
        self.assertEqual(na.projection_problems(full,{'n':1,'models':{'baw':dict(col)}},8),[])
        self.assertTrue(na.projection_problems(full,{'n':1,'models':{'baw':dict(col,price=[NAN])}},8))      # a changed field is found
        self.assertTrue(na.projection_problems(full,{'n':1,'models':{'bsm':dict(col)}},8))                  # wrong-model part is found
    def test_projection_compares_status_flags_and_the_binary64_bits(self):
        col={'status':['OK'],'flags':[0],**{f:[0.0] for f in FIELDS}}
        full={'n':1,'models':{m:dict(col) for m in MODELS5}}
        self.assertEqual(na.projection_problems(full,{'n':1,'models':{'bsm':dict(col),'alo':dict(col)}},17),[])
        for bad in (dict(col,status=['MODEL_DOMAIN']),dict(col,flags=[8]),dict(col,rho=[-0.0])):     # -0.0 has other bits than 0.0
            self.assertTrue(na.projection_problems(full,{'n':1,'models':{'bsm':bad}},1))
        self.assertTrue(na.projection_problems(full,{'n':1,'models':{'bsm':dict(col)}},3))              # a selected part is missing
        self.assertTrue(na.projection_problems(full,{'n':1,'models':{'bsm':dict(col),'bjs':dict(col),'crr':dict(col)}},3))   # an extra part
        self.assertTrue(na.projection_problems(full,{'n':2,'models':{'bsm':dict(col)}},1))              # another row count
        nan_a=struct.unpack('<d',struct.pack('<Q',0x7FF8000000000000))[0];nan_b=struct.unpack('<d',struct.pack('<Q',0x7FF8000000000001))[0]
        self.assertTrue(na.projection_problems({'n':1,'models':{'bsm':dict(col,iv=[nan_a])}},{'n':1,'models':{'bsm':dict(col,iv=[nan_b])}},1))
    def test_the_items_and_the_wired_mask(self):
        self.assertEqual(na.ITEMS,('py_reference','large_sample','baw_alo_reference','routes','limits','edge_rows','per_model','projection',
                                   'trap','counters','quantlib','baw_quantlib','alo_quantlib','route_mechanics'))     # EX-16: baw_alo_reference (T21-A05)
        self.assertEqual(na.PER_MODEL_MASKS,(1,2,4,8,16))
        self.assertEqual((na.ALL_MASK,na.CASE_MASK),(31,7))
        self.assertEqual(na.ROUTE_CELLS,('stdio-warm','stdio-cold','shm-warm','shm-cold','inproc-warm'))
        self.assertEqual(na.ALL_CELLS,na.ROUTE_CELLS+('kernel',))
        self.assertTrue(na.mask_wired())           # plan Step 1 (approver finding L1): PL_MASK_WIRED == PL_MASK_MODELS5, the ALO stub is gone
        self.assertEqual(na.WIRED_HEADER.read_text().count(na.WIRED_LINE),1)
    def test_the_check_row_fits_the_framework_bounds(self):
        """container/bench-coordinator.py check_result: at most 32 count keys, each [a-z][a-z0-9_]{0,40} with an integer value,
        and a label of at most 120 characters of its grammar. A failed item is named in the label."""
        items={k:na.item([],5,1.0) for k in na.ITEMS}
        row=na.check_row(items,12.5)
        self.assertEqual(row['status'],'PASS');self.assertLessEqual(len(row['counts']),32)
        self.assertTrue(all(re.fullmatch(r'[a-z][a-z0-9_]{0,40}',k) and type(v) is int for k,v in row['counts'].items()))
        self.assertTrue(all(row['counts'][k]==5 for k in na.ITEMS))
        items['trap']=na.item(['inproc-warm trap 4: no run defect'],3,0.1)
        row=na.check_row(items,12.5)
        self.assertEqual(row['status'],'FAIL');self.assertEqual(row['counts']['ok_trap'],0)
        self.assertRegex(row['label'],r'^[A-Za-z0-9 ._:,()=+-]{0,120}$');self.assertIn('trap',row['label'])
        self.assertEqual(na.item([],0,0.0)['status'],'FAIL')                 # an item without a compared row never passes

class MutationTests(unittest.TestCase):
    """R50 item f: the check FAILS when the C result of one model is replaced by another model's part, and when one route
    returns a different result. Each test first shows that the unmutated outcomes pass the same function."""
    def test_a_wrong_model_part_fails_the_per_model_comparison(self):
        ref=reference();c,want=per_model_fixture(ref)
        self.assertEqual(na.equal_problems(c,want,na.ROUTE_CELLS)[0],[])
        wrong={'n':2,'models':{'baw':ref['models']['bsm']}}         # the baw part of the C result holds the bsm part
        c[('shm-warm','proj',8,'small')]=outcome(wrong)
        problems,_=na.equal_problems(c,want,na.ROUTE_CELLS)
        self.assertEqual(len(problems),1);self.assertIn('shm-warm',problems[0])
    def test_a_wrong_model_part_fails_the_projection(self):
        ref=reference();c,_=per_model_fixture(ref)
        self.assertEqual(na.projection_set_problems(c,na.ROUTE_CELLS,('tiny','small'))[0],[])
        c[('inproc-warm','proj',24,'tiny')]=outcome({'n':2,'models':{'baw':ref['models']['baw'],'alo':ref['models']['crr']}})   # alo holds crr
        problems,_=na.projection_set_problems(c,na.ROUTE_CELLS,('tiny','small'))
        self.assertEqual(len(problems),1);self.assertIn('inproc-warm',problems[0])
        c,_=per_model_fixture(ref)
        c[('stdio-cold','proj',2,'small')]=outcome({'n':2,'models':{'bsm':ref['models']['bjs']}})      # the part of another model's key
        self.assertTrue(na.projection_set_problems(c,na.ROUTE_CELLS,('tiny','small'))[0])
    def test_one_route_with_another_result_fails_the_reference_and_route_comparisons(self):
        ref=reference(3);sel=na.select(ref,('bsm','bjs','crr'))
        c={(cell,'tier',7,'small'):outcome(sel) for cell in na.ALL_CELLS};want={('tier',7,'small'):canonical_result(sel)}
        self.assertEqual(na.equal_problems(c,want,na.ALL_CELLS)[0],[])
        self.assertEqual(na.routes_problems(c,[('tier',7,'small')],na.ALL_CELLS)[0],[])
        other=na.select(ref,('bsm','bjs','crr'));other['models']=dict(other['models'])
        other['models']['crr']=dict(other['models']['crr'],price=[math.nextafter(other['models']['crr']['price'][0],1.0)]+other['models']['crr']['price'][1:])
        c[('shm-cold','tier',7,'small')]=outcome(other)            # one ulp in one field of one route
        for problems in (na.equal_problems(c,want,na.ALL_CELLS)[0],na.routes_problems(c,[('tier',7,'small')],na.ALL_CELLS)[0]):
            self.assertEqual(len(problems),1);self.assertIn('shm-cold',problems[0])
    def test_a_missing_or_failed_route_fails(self):
        ref=reference();sel=na.select(ref,('bsm',))
        c={(cell,'tier',1,'tiny'):outcome(sel) for cell in na.ALL_CELLS};want={('tier',1,'tiny'):canonical_result(sel)}
        self.assertEqual(na.equal_problems(c,want,na.ALL_CELLS)[0],[])          # T21-A06: the unmutated outcomes pass
        c[('kernel','tier',1,'tiny')]={'raised':'KernelExit','detail':'exit 3 reason kernel'}
        self.assertTrue(na.equal_problems(c,want,na.ALL_CELLS)[0])
        del c[('kernel','tier',1,'tiny')]
        self.assertTrue(na.equal_problems(c,want,na.ALL_CELLS)[0])
    def test_the_large_tier_sample_and_route_identity(self):
        c={(cell,'large',7,'large'):{'sha256':'a'*64,'sample_bytes':b'x','n':3} for cell in na.ALL_CELLS}
        self.assertEqual(na.routes_problems(c,[('large',7,'large')],na.ALL_CELLS,field='sha256')[0],[])
        self.assertEqual(na.equal_problems(c,{('large',7,'large'):b'x'},na.ALL_CELLS,field='sample_bytes')[0],[])
        c[('inproc-warm','large',7,'large')]={'sha256':'b'*64,'sample_bytes':b'y','n':3}
        self.assertTrue(na.routes_problems(c,[('large',7,'large')],na.ALL_CELLS,field='sha256')[0])
        self.assertTrue(na.equal_problems(c,{('large',7,'large'):b'x'},na.ALL_CELLS,field='sample_bytes')[0])
    def test_the_large_sample_count_is_the_compared_sample_rows(self):
        """large_sample compares the sample rows of each cell (509 of the 13,230 rows of the C result): its count is the sample
        rows times the cells, not the rows of the C results (EX-12 round 2: the first run counted 79,380 for 3,054 rows)."""
        res={'n':3,'models':{m:column([0.1,0.2,0.3],['OK']*3) for m in ('bsm','bjs','crr')}}
        o=na._outcome(res,('sample',[0,2]))
        self.assertEqual((o['n'],o['sample_n']),(3,2))
        self.assertEqual(o['sample_bytes'],canonical_result(na.select(res,('bsm','bjs','crr'),[0,2])))
        c={(cell,'large',7,'large'):o for cell in na.ALL_CELLS}
        self.assertEqual(na.equal_problems(c,{('large',7,'large'):o['sample_bytes']},na.ALL_CELLS,field='sample_bytes',count_key='sample_n'),
                         ([],2*len(na.ALL_CELLS)))
    def test_a_trap_row_must_end_as_a_run_defect_on_every_cell(self):
        defects={'stdio-warm':('FrameError','KERNEL_FAILURE'),'stdio-cold':('FrameError','KERNEL_FAILURE'),'shm-warm':('FrameError','KERNEL_FAILURE'),
                 'shm-cold':('FrameError','KERNEL_FAILURE'),'inproc-warm':('RuntimeError','libpl_inproc.so returned 2'),'kernel':('KernelExit','exit 3 reason kernel')}
        c={(cell,'trap',4,'trap'):{'raised':r,'detail':d,'n':1} for cell,(r,d) in defects.items()}
        self.assertEqual(na.defect_problems(c,[('trap',4,'trap')],na.ALL_CELLS)[0],[])
        for cell,bad in (('inproc-warm',{'raised':'RuntimeError','detail':'libpl_inproc.so returned 1','n':1}),
                         ('stdio-cold',{'raised':'FrameError','detail':'WORKER_EXITED','n':1}),('kernel',{'bytes':b'{}','n':1})):
            d=dict(c);d[(cell,'trap',4,'trap')]=bad
            problems,_=na.defect_problems(d,[('trap',4,'trap')],na.ALL_CELLS)
            self.assertEqual(len(problems),1);self.assertIn(cell,problems[0])
    def test_the_counters_of_unselected_and_selected_models(self):
        want={'bsm':40,'bjs':50,'crr':60,'baw':70,'alo':80}
        good={'calls':{m:(10 if m=='baw' else 0) for m in MODELS5},'evals':{m:(70 if m=='baw' else 0) for m in MODELS5},'requests':1}
        self.assertEqual(na.counter_problems({('stdio',8):good},want,10)[0],[])
        self.assertEqual(na.counter_problems({('kernel',8):{'evals':{'baw':70}}},want,10)[0],[])
        for bad in (dict(good,evals=dict(good['evals'],bsm=1)),dict(good,evals=dict(good['evals'],baw=69)),dict(good,calls=dict(good['calls'],baw=9))):
            self.assertTrue(na.counter_problems({('shm',8):bad},want,10)[0])
        self.assertTrue(na.counter_problems({('kernel',8):{'evals':{'baw':70,'bsm':0}}},want,10)[0])     # the kernel lists only selected models

class HeavyReferenceTests(unittest.TestCase):
    """EX-16 (T23; T21-A05): the item baw_alo_reference byte-compares the C result of baw (mask 8) with py-reference on the medium
    tier and on the large-tier sample rows, and of alo (mask 16) on the medium tier, on every cell, with the comparison code of
    py_reference and large_sample (equal_problems, no copy). Each part counts its compared rows; a part without a compared row,
    without a py-reference result or with a differing cell FAILS the item."""
    def fixture(self):
        ref=reference(3);baw=na.select(ref,('baw',));alo=na.select(ref,('alo',));c={}
        for cell in na.ALL_CELLS:
            c[(cell,'tier',8,'medium')]=outcome(baw);c[(cell,'tier',16,'medium')]=outcome(alo)
            c[(cell,'large',8,'large')]=na._outcome(baw,('sample',[0,2]))
        want={'baw_medium':canonical_result(baw),'baw_large_sample':canonical_result(na.select(baw,('baw',),[0,2])),'alo_medium':canonical_result(alo)}
        return c,want
    def test_the_parts_are_baw_on_medium_and_the_large_sample_and_alo_on_medium(self):
        self.assertEqual([(name,key) for name,key,_,_ in na.HEAVY_PARTS],
                         [('baw_medium',('tier',8,'medium')),('baw_large_sample',('large',8,'large')),('alo_medium',('tier',16,'medium'))])
    def test_each_part_counts_its_compared_rows_on_every_cell(self):
        c,want=self.fixture();r=na.heavy_item(c,want,1.0)
        cells=len(na.ALL_CELLS)
        self.assertEqual(r['status'],'PASS');self.assertEqual(r['parts'],{'baw_medium':3*cells,'baw_large_sample':2*cells,'alo_medium':3*cells})
        self.assertTrue(all(v>0 for v in r['parts'].values()));self.assertEqual(r['count'],sum(r['parts'].values()))
    def test_a_differing_cell_a_missing_reference_or_a_missing_part_fails(self):
        c,want=self.fixture()
        bad=dict(c);bad[('shm-cold','tier',8,'medium')]=outcome(na.select(reference(3),('bsm',)))
        r=na.heavy_item(bad,want,1.0);self.assertEqual(r['status'],'FAIL');self.assertTrue(any(p.startswith('shm-cold') for p in r['problems']))
        w=dict(want);del w['alo_medium'];r=na.heavy_item(c,w,1.0)
        self.assertEqual(r['status'],'FAIL');self.assertEqual(r['parts']['alo_medium'],0);self.assertTrue(any(p.startswith('alo_medium') for p in r['problems']))
        gone={k:v for k,v in c.items() if k[1:]!=('large',8,'large')};r=na.heavy_item(gone,want,1.0)
        self.assertEqual(r['status'],'FAIL');self.assertEqual(r['parts']['baw_large_sample'],0)

class CalibrationGateTests(unittest.TestCase):
    """EX-16 (T23; ruling R74 item 5, T21-A08): the quantlib item takes the top-level tolerances only in the calibrated state,
    with the values of the calibration proposal (compared by digest), as the baw_quantlib and alo_quantlib items take only
    their locked blocks. Each mutated protocol below FAILS the item (a problem of _tolerance); the protocol passes."""
    def quantlib(self,t):
        with mock.patch('optionlab.protocol.tolerances',return_value=t):return na._tolerance('quantlib')
    def test_the_protocol_is_calibrated_and_passes(self):
        tl,state,problems=na._tolerance('quantlib')
        self.assertEqual((tl,state,problems),(None,'calibrated-phase-2',[]))
        rec=protocol.tolerances()['calibration']
        self.assertEqual(sorted(rec),['proposal','proposal_sha256','verdict']);self.assertEqual(rec['verdict'],'artifacts/approvals/ex-option-T23/verdict.md')
    def test_a_state_other_than_the_calibrated_state_fails(self):
        for state in ('provisional-phase-1','calibrated-phase-1','locked-phase-2',None):
            with self.subTest(state=state):
                t=copy.deepcopy(protocol.tolerances());t['state']=state
                if state is None:del t['state']
                self.assertTrue(self.quantlib(t)[2])
    def test_values_other_than_the_proposal_values_fail(self):
        for key,value in (('iv_abs',2e-8),('price_rel',5e-13),('flat_vega',1e-11)):    # wider, narrower, a threshold
            with self.subTest(field=key):
                t=copy.deepcopy(protocol.tolerances());t[key]=value
                self.assertEqual(self.quantlib(t)[2],['the top-level tolerance values differ from the calibration proposal'])
        t=copy.deepcopy(protocol.tolerances());t['extra_rel']=1e-9                        # a field outside the proposal
        self.assertTrue(self.quantlib(t)[2])
        t=copy.deepcopy(protocol.tolerances());del t['ambiguity_rel']
        self.assertTrue(self.quantlib(t)[2])
    def test_a_missing_or_other_calibration_record_fails(self):
        t=copy.deepcopy(protocol.tolerances());del t['calibration'];self.assertTrue(self.quantlib(t)[2])
        t=copy.deepcopy(protocol.tolerances());t['calibration']['proposal_sha256']='0'*64
        self.assertEqual(self.quantlib(t)[2],['the calibration proposal file differs from its sha256'])
        for path in ('protocol/../bench.json','protocol/no-such-file.json','oracle.json','/etc/passwd'):
            with self.subTest(path=path):
                t=copy.deepcopy(protocol.tolerances());t['calibration']['proposal']=path;self.assertTrue(self.quantlib(t)[2])
        t=copy.deepcopy(protocol.tolerances());t['calibration']['extra']='x';self.assertTrue(self.quantlib(t)[2])

class RouteMechanicsTests(unittest.TestCase):
    """R58 (T21-A01): native-routes stays a per-run gate. native-agreement (the declared native.agreement check, the run gate of
    every bench run with C rows) runs the route-mechanics items of native-routes as its item route_mechanics, with the item
    functions of optionlab.native_check themselves (no copy). Each failed or missing route-mechanics item FAILS that item and
    so the check row (the gate); each case first shows that the unmutated results pass."""
    def test_the_item_runs_the_native_routes_items_that_no_other_item_covers(self):
        names=[n for n,_ in native_check.ITEMS]
        self.assertEqual(native_check.MECHANICS,('sides','kernel','panel','zero-copy','gil','crash','shm','refusal','echo'))
        self.assertEqual([n for n in names if n not in native_check.MECHANICS],['routes','limits','reference'])   # the items routes, limits, py_reference
        self.assertEqual(native_check.mechanics_items(),[(n,f) for n,f in native_check.ITEMS if n in native_check.MECHANICS])
        self.assertIn('route_mechanics',na.ITEMS)
    def test_a_failed_or_missing_route_mechanics_item_fails_the_gate(self):
        ok={n:{'status':'PASS','counts':{},'seconds':0.1} for n in native_check.MECHANICS}
        good=na.mechanics_item(ok,1.0)
        self.assertEqual((good['status'],good['count']),('PASS',len(native_check.MECHANICS)))
        items={k:na.item([],5,1.0) for k in na.ITEMS};items['route_mechanics']=good
        self.assertEqual(na.check_row(items,10.0)['status'],'PASS')
        for name in native_check.MECHANICS:
            with self.subTest(item=name):
                bad=dict(ok);bad[name]={'status':'FAIL','reason':'exception OSError','seconds':0.1}
                got=na.mechanics_item(bad,1.0)
                self.assertEqual(got['status'],'FAIL');self.assertIn(name,got['problems'][0])
                items['route_mechanics']=got;row=na.check_row(items,10.0)
                self.assertEqual(row['status'],'FAIL');self.assertEqual(row['counts']['ok_route_mechanics'],0);self.assertIn('route_mechanics',row['label'])
        missing=dict(ok);del missing['crash']
        self.assertEqual(na.mechanics_item(missing,1.0)['status'],'FAIL')
        self.assertEqual(na.mechanics_item({},1.0)['status'],'FAIL')

class LimitRowsTests(unittest.TestCase):
    """T19-A01: the T19 limit rows repeated with period 256, which divides the request limit (14,336 = 56 x 256), so a route that
    sent the first rows again for request 2 passed. The rows now repeat with a period that does not divide the limit, and each
    split result is compared with the reference of the same rows."""
    def test_the_native_routes_limit_rows(self):
        limit=request_limit()
        self.assertEqual(native_check.LIMIT_PERIOD,257);self.assertNotEqual(limit%native_check.LIMIT_PERIOD,0)
        base={'n':257,**{k:[float(i) for i in range(257)] for k in ('side','S','K','T','bid','ask','r','q')}}
        ref={'n':257,'models':{'bsm':column([float(i) for i in range(257)],['OK']*257)}}
        for n in native_check.LIMIT_SIZES:
            t=native_check._tile(base,n);r=native_check._tile_result(ref,n)
            self.assertEqual(t['S'],[float(i%257) for i in range(n)]);self.assertEqual(r['models']['bsm']['price'],t['S'])
            self.assertEqual(r['n'],n)
            if n>limit:self.assertNotEqual(t['S'][limit],t['S'][0])     # request 2 reads other rows than request 1: a wrong offset is visible
    def test_the_agreement_limit_rows(self):
        limit=request_limit();rows=[(0,float(i),100.0,1.0,1.0,1.1,0.04,0.012) for i in range(na.LARGE_ROWS)]
        self.assertNotEqual(limit%na.LARGE_ROWS,0);self.assertEqual(na.LIMIT_SIZES,(14336,14337,16384,20000))
        for n in na.LIMIT_SIZES:
            t=na.tile(rows,n);self.assertEqual(len(t),n);self.assertEqual(t[n-1],rows[(n-1)%na.LARGE_ROWS])
            if n>limit:self.assertNotEqual(t[limit],t[0])
        ref={'n':3,'models':{'bsm':column([1.0,2.0,3.0],['OK']*3)}}
        self.assertEqual(na.tile_result(ref,7)['models']['bsm']['price'],[1.0,2.0,3.0,1.0,2.0,3.0,1.0])

class PoolTests(unittest.TestCase):
    """A pool worker that dies (future.result() raises BrokenProcessPool) is a task error of its own item: the other items keep
    their results, and the check row names the failed item instead of one exception for the whole check."""
    def test_a_dead_worker_fails_its_item_only(self):
        from concurrent.futures import Future
        from concurrent.futures.process import BrokenProcessPool
        P=na._Pool(None)
        dead=Future();dead.set_exception(BrokenProcessPool('a worker died'))
        good=Future();good.set_result({'value':{'k':1},'error':None,'seconds':1.5})
        failed=Future();failed.set_result({'value':None,'error':'ValueError','seconds':0.5})
        self.assertIsNone(P.get(('trap',dead)))
        self.assertEqual(P.get(('counters',good)),{'k':1})
        self.assertIsNone(P.get(('edge_rows',failed)))
        self.assertEqual(P.task_problems('trap'),['task error BrokenProcessPool'])
        self.assertEqual(P.task_problems('counters'),[])
        self.assertEqual(P.task_problems('edge_rows'),['task error ValueError'])
        self.assertEqual(P.seconds,{'trap':0.0,'counters':1.5,'edge_rows':0.5})

if __name__=='__main__':unittest.main()
