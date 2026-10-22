"""Amendment G4.3 and G4.8: every Python variant computes only the selected model. The test-only counters
(optionlab.counters, active only with SAFE_C_TEST_COUNTERS=1, which this module sets for the example container suite)
count each model's engine calls in every variant.

Adaptation of the brief's draft (no check is weaker): synthetic.generate returns the raw Market Data JSON object, so the
fixture decodes it with contract.load_chain and fills the per-row r and q columns from the case parameters, as
OptionChainGreeks.load does."""
import os, unittest
os.environ['SAFE_C_TEST_COUNTERS']='1'
from optionlab import counters, synthetic, reference as ref, optimized, library
from optionlab.adapter import OptionChainGreeks
from optionlab.contract import ALL_MODELS, rows, load_chain, with_rates
from optionlab.params import CASE
import json, pathlib
import hashlib, struct, sys, tempfile
from optionlab.contract import MODELS5, STATUSES
RAW={k:v['value'] for k,v in json.loads((pathlib.Path(__file__).resolve().parents[2]/'cases/option-chain-greeks.json').read_text())['parameters'].items()}

LIMIT=json.loads(pathlib.Path('/src/safety/performance-policy.json').read_text())['pools']['request_limit']

def chain_of(n,seed):return with_rates(load_chain(synthetic.generate(n,seed,CASE)),CASE.rate,CASE.dividend_yield)

class PerModelTests(unittest.TestCase):
    def setUp(self):self.chain=chain_of(64,20261007)
    def test_only_the_selected_model_is_evaluated_in_every_variant(self):
        for variant,workers in (('py-reference','direct'),('py-optimized','direct'),('py-library','direct')):
            for m in ALL_MODELS:
                with self.subTest(variant=variant,model=m):
                    a=OptionChainGreeks(RAW,selector=m,request_limit=LIMIT);counters.reset()
                    res=a.materialize(a.run(a.prepare(self.chain,variant,1 if workers=='direct' else workers),variant,1 if workers=='direct' else workers))
                    self.assertEqual(set(res['models']),{m});snap=counters.snapshot()
                    self.assertEqual({k for k,v in snap.items() if v},{m})
    def test_selected_model_agrees_with_py_reference(self):
        for m in ALL_MODELS:
            a=OptionChainGreeks(RAW,selector=m,request_limit=LIMIT);ref_res=a.reference(self.chain)
            for variant in ('py-optimized','py-library'):
                res=a.materialize(a.run(a.prepare(self.chain,variant,1),variant,1))
                self.assertTrue(a.validate(res,ref_res,self.chain)['eligible'],(m,variant))
    def test_reference_counts(self):
        a=OptionChainGreeks(RAW,selector='crr',request_limit=LIMIT);c=a.reference_counts(a.reference(self.chain));self.assertEqual(set(c),{'crr'});self.assertGreater(c['crr'],0)

class PerModelExactTests(unittest.TestCase):
    """Added by the implementer (G4.8, G1.6, G4.2)."""
    def setUp(self):self.chain=chain_of(24,20261008)
    def test_py_reference_counter_equals_the_engine_evals_total(self):
        for m in ALL_MODELS:
            with self.subTest(model=m):
                a=OptionChainGreeks(RAW,selector=m,request_limit=LIMIT);counters.reset()
                res=a.run(a.prepare(self.chain,'py-reference'),'py-reference',1)
                self.assertEqual(counters.snapshot(),{m:sum(res['models'][m]['engine_evals'])});self.assertEqual(a.reference_counts(res),counters.snapshot())
    def test_all_models_reference_counts_every_model(self):
        a=OptionChainGreeks(RAW,request_limit=LIMIT);c=a.reference_counts(a.reference(self.chain))
        self.assertEqual(set(c),set(ALL_MODELS));self.assertTrue(all(type(v) is int and v>0 for v in c.values()))
    def test_projection_identity_in_every_variant(self):
        """G1.6: the per-model result of model m is bit-identical to the model-m part of the same variant's all-models result."""
        for variant,workers in (('py-reference',1),('py-optimized',1),('py-library',1)):
            full=OptionChainGreeks(RAW,request_limit=LIMIT);whole=full.materialize(full.run(full.prepare(self.chain,variant,workers),variant,workers))
            for m in ALL_MODELS:
                with self.subTest(variant=variant,model=m):
                    a=OptionChainGreeks(RAW,selector=m,request_limit=LIMIT);one=a.materialize(a.run(a.prepare(self.chain,variant,workers),variant,workers))
                    self.assertEqual(json.dumps(one['models'][m]),json.dumps(whole['models'][m]))
                    self.assertEqual(a.digest(one),ref.result_digest({'n':whole['n'],'models':{m:whole['models'][m]}}))
    def test_validate_takes_the_selector_part_of_an_all_models_reference(self):
        full=OptionChainGreeks(RAW,request_limit=LIMIT).reference(self.chain)
        for m in ALL_MODELS:
            with self.subTest(model=m):
                a=OptionChainGreeks(RAW,selector=m,request_limit=LIMIT);res=a.materialize(a.run(a.prepare(self.chain,'py-optimized'),'py-optimized',1))
                self.assertTrue(a.validate(res,full,self.chain)['eligible'])
                res['models']['bsm' if m!='bsm' else 'bjs']=res['models'][m]          # a result with an unselected model is refused
                self.assertFalse(a.validate(res,full,self.chain)['eligible'])
    def test_counters_are_inactive_without_the_variable(self):
        a=OptionChainGreeks(RAW,selector='bsm',request_limit=LIMIT);prep=a.prepare(self.chain,'py-optimized')
        counters.reset();a.run(prep,'py-optimized',1)                      # the process keeps its own counts
        self.assertGreater(counters.snapshot().get('bsm',0),0)
        os.environ['SAFE_C_TEST_COUNTERS']='0'
        try:
            counters.reset();a.run(prep,'py-optimized',1);ref.run(rows(self.chain),CASE,models=('bsm',));self.assertEqual(counters.snapshot(),{})
        finally:os.environ['SAFE_C_TEST_COUNTERS']='1'
    def test_merge_refuses_a_malformed_snapshot(self):
        for bad in ({'bsm':-1},{'bsm':1.0},{3:1},['bsm'],{'bsm':True}):
            with self.subTest(snapshot=bad):
                with self.assertRaises(ValueError):counters.merge(bad)

CASE_FILE=pathlib.Path(__file__).resolve().parents[2]/'cases/option-chain-greeks.json'

def bits(x):
    """`x` with every float replaced by the hex of its binary64 bits (signed zeros and NaN payloads included): exact equality."""
    if isinstance(x,float):return 'f'+struct.pack('<d',x).hex()
    if isinstance(x,dict):return {k:bits(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)):return [bits(v) for v in x]
    return x

def roundtrip(x):return json.loads(json.dumps(x))      # reference.json: the reference child writes it, each job reads it back

STATUS_EDGES=('bsm-no-bid','bsm-crossed')      # M2c-A01 (R59): the oracle edge rows of NO_BID and CROSSED (case parameters)

def status_rows():
    """M2c-A01 (ruling R59): the rows that the 32 synthetic rows lack, from the protocol oracle (case parameters, no row
    parameters): NO_BID and CROSSED (oracle edge_rows STATUS_EDGES) and every baw admission row (oracle baw part, kind edge,
    status MODEL_DOMAIN: flag 64 and the admit_reason of its `reason`, row, brent or bump). [(name, row tuple, reason or None)].
    NOT_CONVERGED is not among the statuses: no row of the case parameters reaches it (optionlab.synthetic module text; the
    oracle holds no such row)."""
    from optionlab import protocol
    fx=protocol.oracle()['oracle'];by={e['name']:e for e in fx['edge_rows']}
    out=[(n,tuple(by[n]['row']),None) for n in STATUS_EDGES]
    out+=[(e['name'],tuple(e['row']),e['reason']) for e in fx['baw'] if e.get('kind')=='edge' and e.get('status')=='MODEL_DOMAIN' and not e.get('params')]
    return out

def chain_from_rows(rows_):
    """The chain columns that reference.run, reference_cover, py-optimized and validate read: n and the eight request columns
    (side, S, K, T, bid, ask, r, q) of row tuples, each row with its own r and q."""
    return {'n':len(rows_),**{k:[r[j] for r in rows_] for j,k in enumerate(('side','S','K','T','bid','ask','r','q'))}}

class ReferenceCoverTests(unittest.TestCase):
    """R48 (T6-R6, rulings R48 and R51; task M2c): the optional framework hook reference_cover(data, selectors)
    (benchlab.workload) and the count hooks of a covered reference.
    T6R6-A01: for each selector s of the case (all, bsm, bjs, crr, baw, alo), the covered reference gives the adapter of s
    exactly what reference(data) of s gives: the same models and columns, the statuses, the flags and the binary64 bits of
    every field, also after the JSON round trip of reference.json, and the same validate verdict.
    T6R6-A05: the count hooks count every model that the reference holds, so the local decision merge of window jobs with
    different covers gives no counts-differ, and its blocks equal the blocks of each model's own reference.
    M2c-A01 (ruling R59): the rows are the 32 synthetic rows of the case seed and the oracle rows of status_rows (NO_BID,
    CROSSED and the four baw admission rows with a non-None admit_reason), so every comparison above also covers each status
    that py-reference reaches under the case parameters and the admit_reason values row, brent and bump."""
    N=32;SEED=20261007
    @classmethod
    def setUpClass(cls):
        case=json.loads(CASE_FILE.read_text());cls.selectors=list(case['selectors']);cls.full=sorted(cls.selectors)
        a=OptionChainGreeks(RAW,request_limit=LIMIT);data=a.synthesize(cls.N,cls.SEED)
        p=pathlib.Path(tempfile.mkdtemp())/'chain.json';p.write_bytes(data)
        base=a.slice(a.load({'path':str(p),'sha256':hashlib.sha256(data).hexdigest()}),cls.N)
        cls.extra=status_rows();cls.chain=chain_from_rows(rows(base)+[r for _,r,_ in cls.extra]);cls.n=cls.chain['n']
        cls.ad={s:OptionChainGreeks(RAW,selector=s,request_limit=LIMIT) for s in cls.selectors}
        cls.own={s:cls.ad[s].reference(cls.chain) for s in cls.selectors};cls.covers={}
        cls.evals={m:sum(cls.own[m]['models'][m]['engine_evals']) for m in MODELS5}      # each model's own total
    def cover(self,selectors):
        """The reference that the adapter of the reference selector `all` computes for the listed selectors (cached)."""
        key=tuple(selectors)
        if key not in self.covers:self.covers[key]=self.ad['all'].reference_cover(self.chain,list(selectors))
        return self.covers[key]
    def test_each_selector_takes_its_own_reference_from_the_cover(self):
        self.assertEqual(self.selectors,['all','bsm','bjs','crr','baw','alo'])
        for sel in (self.full,['all','baw'],['alo','all'],['alo','baw'],['bsm']):
            cov=self.cover(sel);want=[m for m in MODELS5 if any(m in self.ad[s].models for s in sel)]
            self.assertEqual((cov['n'],list(cov['models'])),(self.n,want))          # the union of the listed models, MODELS5 order
            for s in sel:
                with self.subTest(cover=sel,selector=s):
                    a=self.ad[s];got=a.selected(cov);own=self.own[s]
                    self.assertEqual(list(got['models']),list(own['models']))
                    for m in own['models']:self.assertEqual(list(got['models'][m]),list(own['models'][m]))    # the same columns
                    self.assertEqual(bits(got),bits(own))
                    self.assertEqual(bits(a.selected(roundtrip(cov))),bits(roundtrip(own)))
                    self.assertEqual(a.digest(got),a.digest(own))
    def test_the_rows_hold_every_reachable_status_and_a_non_none_admit_reason(self):
        """M2c-A01 (ruling R59): the binding rows are not only OK, ABOVE_MAX, BELOW_MIN, INVALID_INPUT and EXPIRED rows with
        admit_reason None. The five-model cover holds every status except NOT_CONVERGED (status_rows), each model holds NO_BID
        and CROSSED rows, and the baw admit_reason column holds row, brent and bump at the baw admission rows (the oracle
        reasons), so the comparisons of every field above (status, flags, the binary64 bits, admit_reason) see them."""
        cov=self.cover(self.full)
        self.assertEqual(list(cov['models']),list(MODELS5))
        self.assertEqual({s for col in cov['models'].values() for s in col['status']},set(STATUSES)-{'NOT_CONVERGED'})
        for m in MODELS5:
            with self.subTest(model=m):
                self.assertEqual(cov['models'][m]['status'][self.N:self.N+len(STATUS_EDGES)],['NO_BID','CROSSED'])
        baw=[(i,reason) for i,(_,_,reason) in enumerate(self.extra,start=self.N) if reason is not None]
        self.assertEqual(sorted({reason for _,reason in baw}),['brent','bump','row'])
        for got in (cov['models']['baw'],self.own['baw']['models']['baw']):
            self.assertEqual([got['admit_reason'][i] for i,_ in baw],[reason for _,reason in baw])
            self.assertEqual([got['status'][i] for i,_ in baw],['MODEL_DOMAIN']*len(baw))
            self.assertTrue(all(got['flags'][i]&64 for i,_ in baw))
            self.assertEqual(got['admit_reason'][:self.N],[None]*self.N)
    def test_the_validate_verdict_of_each_selector_is_the_same_with_the_cover(self):
        cov=self.cover(self.full)
        for s in self.selectors:
            with self.subTest(selector=s):
                a=self.ad[s];res=a.materialize(a.run(a.prepare(self.chain,'py-optimized'),'py-optimized',1))
                v=a.validate(res,cov,self.chain);self.assertEqual(bits(v),bits(a.validate(res,self.own[s],self.chain)));self.assertIs(v['eligible'],True)
    def test_the_hook_refuses_a_malformed_selector_list(self):
        for bad in ([],'bsm',('bsm',),None,['x'],['BSM'],['bsm','bsm'],[None],[['bsm']]):
            with self.subTest(selectors=bad),self.assertRaises(ValueError):self.ad['all'].reference_cover(self.chain,bad)
    def test_the_count_hooks_count_every_model_of_a_covered_reference(self):
        a=self.ad['all'];both=ref.run(rows(self.chain),a.params,models=MODELS5)        # a reference that covers the five models
        self.assertEqual(a.reference_counts(both),self.evals)
        x=self.ad['baw'].reference_exclusions(self.own['baw']);y=self.ad['alo'].reference_alo_counts(self.own['alo'])
        self.assertIsNotNone(x);self.assertIsNotNone(y)
        self.assertEqual((a.reference_exclusions(both),a.reference_alo_counts(both)),(x,y))
        part=ref.run(rows(self.chain),a.params,models=('baw','alo'))     # a cover without the models of `all`: counted, not refused
        self.assertEqual(a.reference_counts(part),{m:self.evals[m] for m in ('baw','alo')})
        self.assertEqual((a.reference_exclusions(part),a.reference_alo_counts(part)),(x,y))
        for s in self.selectors:                                          # an own reference: the selected models, as before
            with self.subTest(selector=s):
                b=self.ad[s];self.assertEqual(b.reference_counts(self.own[s]),{m:self.evals[m] for m in b.models})
        self.assertEqual((a.reference_exclusions(self.own['all']),a.reference_alo_counts(self.own['all'])),(None,None))
        for bad in ({'n':self.N,'models':{'xyz':both['models']['bsm']}},{'n':self.N,'models':{}}):
            for hook in (a.reference_counts,a.reference_exclusions,a.reference_alo_counts):
                with self.subTest(hook=hook.__name__,models=list(bad['models'])),self.assertRaises(ValueError):hook(bad)
    def test_window_jobs_of_different_covers_merge_without_counts_differ(self):
        """T6R6-A05: tools/bench_local_decision.merge_aggregates over the count blocks that the reference child writes
        (REFERENCE_CODE: reference_counts and reference_exclusions of the job's reference selector over its covered or own
        reference) for window jobs of different covers (job selector `all`) and single-selector jobs: no problem;
        reference_evals holds every model with the total of its own reference; reference_admit_excluded is the baw block. A
        count or a block that differs in one job gives counts-differ (the check is live)."""
        sys.path.insert(0,'/src/tools');import bench_local_decision as ld
        run='m2c-cover-merge';ds='a'*64
        plan=[('w-baw','all',['all','baw']),('w-alo','all',['alo','all']),('w-crr','all',['all','bsm','crr']),('w-units','all',['alo','baw']),
              ('w-full','all',self.full),('s-all','all',None),('s-baw','baw',None),('s-alo','alo',None)]
        def doc(sel,cov):
            a=self.ad[sel];r=a.reference(self.chain) if cov is None else self.cover(cov);x=a.reference_exclusions(r)
            return {'status':'VALID','run_id':run,'case':'option-chain-greeks','dataset_sha256':ds,'cgroup_inode':1,'isolated':True,'selector':sel,
                    'partial':False,'rules':{'agreement':0},'rows':self.N,'timings':[],'reference_evals':a.reference_counts(r),
                    **({'reference_admit_excluded':x} if x is not None else {})}
        jobs=[{'name':n,'kind':'timing','trials':[],'selector':sel,'rows':self.N,'partial':False} for n,sel,_ in plan]
        docs={n:doc(sel,cov) for n,sel,cov in plan}
        host={'run_id':run,'case':'option-chain-greeks','dataset_sha256':ds,'problems':[],'accounting':[],'not_run':[]}
        out=ld.merge_aggregates(docs,jobs,host);block=self.ad['baw'].reference_exclusions(self.own['baw'])
        self.assertEqual((out['status'],out['problems']),('VALID',[]))
        self.assertEqual(out['reference_evals'],dict(sorted(self.evals.items())));self.assertEqual(out['reference_admit_excluded'],block)
        self.assertEqual(sorted(n for n,d in docs.items() if 'reference_admit_excluded' in d),['s-baw','w-baw','w-full','w-units'])
        bad=json.loads(json.dumps(docs));bad['w-alo']['reference_evals']['alo']+=1
        self.assertIn('counts-differ',ld.merge_aggregates(bad,jobs,host)['problems'])
        bad=json.loads(json.dumps(docs));bad['w-units']['reference_admit_excluded']['row']+=1
        self.assertIn('counts-differ',ld.merge_aggregates(bad,jobs,host)['problems'])
