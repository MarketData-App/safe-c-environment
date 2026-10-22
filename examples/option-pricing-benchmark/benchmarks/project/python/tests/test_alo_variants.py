"""G-ALO2 part B (Task A5; spec Amendment I4.2, I9.4, H17, H19; Appendix I-ALO R3, R8): ALO in py-optimized, py-library
and no pool. The cross-variant identity covers the status and the flag bits 16 `stencil_unresolved` and 32
`stencil_switched` only (I4.2); the values are reported by the `alo-spread` check and never gated before the Task A6 lock
(N6). The synthetic rows are the first 256 rows of the synthetic large chain at the case seed (synthetic.generate is
prefix-stable); the switch vectors are the 28 record R4 vectors (checks.alo_switch_vectors) quoted at the py-reference
price at sigma 0.3. The test-only counters (SAFE_C_TEST_COUNTERS) show that only `alo` is computed (G4.8). The adaptive
path divergence (I4.2) is test-only instrumentation outside timing. Carried rulings: A4-C2 / A4R-05 (a run defect raised
inside a ql.Brent callback leaves through a recorded marker, never as the RuntimeError of SWIG)."""
import os
os.environ['SAFE_C_TEST_COUNTERS']='1'
import json, math, pathlib, tempfile, unittest
from unittest import mock
from optionlab import counters, synthetic, optimized, library, reference as ref, alo, checks, models, contract
from optionlab.adapter import OptionChainGreeks
from optionlab.contract import load_chain, with_rates, MODELS5
from optionlab.params import CASE
from optionlab import protocol
HERE=pathlib.Path(__file__).resolve().parents[2]
MANIFEST=json.loads((HERE/'cases/option-chain-greeks.json').read_text())
RAW={k:v['value'] for k,v in MANIFEST['parameters'].items()}
LIMIT=json.loads(pathlib.Path('/src/safety/performance-policy.json').read_text())['pools']['request_limit']
SEED=RAW['seed'];N=256;M=('alo',)
VARIANTS=(('py-optimized',1),('py-library',1))

def chain_of(n,seed):return with_rates(load_chain(synthetic.generate(n,seed,CASE)),CASE.rate,CASE.dividend_yield)

def switch_rows(params):
    """The 28 record R4 switch vectors as quote rows (S = K = 100, sigma 0.3, bid = ask = the py-reference price; a call
    vector carries the exchanged rates, as checks.alo_switch_vectors prices it)."""
    out=[]
    for v in checks.alo_switch_vectors(params):
        p=alo.price(v['side'],100.0,100.0,v['T'],v['r'],v['q'],0.3,params);out.append((v['side'],100.0,100.0,v['T'],p,p,v['r'],v['q']))
    return out

def chain_of_rows(rows):
    """A columnar chain with per-row r and q (the form OptionChainGreeks.load returns) holding exactly `rows`."""
    cols=list(zip(*rows))
    return {'n':len(rows),**{k:list(c) for k,c in zip(('side','S','K','T','bid','ask','r','q'),cols)}}

def key(col):return [(s,f&48) for s,f in zip(col['status'],col['flags'])]

def run_variant(a,chain,variant,workers):
    counters.reset();res=a.materialize(a.run(a.prepare(chain,variant,workers),variant,workers));return res,counters.snapshot()

class AloVariantIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rows=[tuple(r) for r in zip(*(chain_of(N,SEED)[k] for k in ('side','S','K','T','bid','ask','r','q')))]
        cls.switch=switch_rows(CASE);cls.rows=rows+cls.switch;cls.chain=chain_of_rows(cls.rows)
        cls.a=OptionChainGreeks(RAW,selector='alo',request_limit=LIMIT)
        cls.ref=cls.a.reference(cls.chain);cls.results={v:run_variant(cls.a,cls.chain,v,w) for v,w in VARIANTS}
    def test_status_and_flags_equal_reference(self):
        want=key(self.ref['models']['alo']);self.assertEqual(len(want),N+28);self.assertEqual(len(self.switch),28)
        self.assertGreater(sum(1 for s,_ in want if s=='OK'),N//2)          # the rows reach the greeks, not only early statuses
        self.assertTrue(any(f&32 for _,f in want))                          # a switched or halved stencil is compared
        for variant,_ in VARIANTS:
            res,_=self.results[variant]
            with self.subTest(variant=variant):
                self.assertEqual(set(res['models']),{'alo'});self.assertEqual(key(res['models']['alo']),want)
    def test_only_alo_is_counted(self):
        for variant,_ in VARIANTS:
            with self.subTest(variant=variant):self.assertEqual({k for k,v in self.results[variant][1].items() if v},{'alo'})

class AloCounterTests(unittest.TestCase):
    """Task 2 parked Minor 5 (G4.8, I12): an `alo` run shows only `alo` counts in py-optimized direct, and the
    alo part of every run equals (status and bits 16/32) the alo projection of the mask-31 py-reference result; the
    py-reference alo-only result is bit-identical to that projection."""
    def test_counters_show_only_alo(self):
        chain=chain_of(16,SEED+1);a=OptionChainGreeks(RAW,selector='alo',request_limit=LIMIT)
        from optionlab.contract import rows as chain_rows
        rws=chain_rows(chain);counters.reset();full=ref.run(rws,CASE,models=MODELS5)
        self.assertEqual({k for k,v in counters.snapshot().items() if v},set(MODELS5))
        part={'n':full['n'],'models':{'alo':full['models']['alo']}}
        one=ref.run(rws,CASE,models=M);self.assertEqual(ref.result_digest(one),ref.result_digest(part))
        want=key(full['models']['alo']);self.assertTrue(any(s=='OK' for s,_ in want))
        for variant,workers in (('py-optimized',1),):
            with self.subTest(variant=variant,workers=workers):
                res,snap=run_variant(a,chain,variant,workers)
                self.assertEqual({k for k,v in snap.items() if v},{'alo'});self.assertGreater(snap['alo'],0)
                self.assertEqual(key(res['models']['alo']),want)

class AloLibraryMarkerTests(unittest.TestCase):
    """py-library ALO: the order-5 marker of record R8 (an engine exception inside the IV callback is MODEL_DOMAIN, never
    orders 6-7, whatever its text) and the run-defect marker of ruling A4-C2 (a RunDefect raised inside the callback is
    re-raised as that RunDefect after ql.Brent returns or fails; SWIG alone would turn it into RuntimeError)."""
    ROW=(1,100.0,100.0,0.5,5.0,5.2,CASE.rate,CASE.dividend_yield)
    def test_library_marker_is_order_5(self):
        self.assertEqual(library.evaluate_alo(self.ROW,CASE)[0],'OK')
        for text in ('root not bracketed: f[0.0001,5] -> [1,2]',library.MAX_EVAL_TEXT,'maximum number of function evaluations (100) exceeded','x'):
            with self.subTest(text=text),mock.patch.object(library._Problem,'npv',side_effect=RuntimeError(text)):
                st,_,_=library.evaluate_alo(self.ROW,CASE);self.assertEqual(st,'MODEL_DOMAIN')
    def test_run_defect_in_the_library_callback_leaves_as_a_run_defect(self):
        planted=models.AloRunDefect('alo-nan','planted-in-callback')
        def pre(*a,**k):raise planted
        with mock.patch.object(ref,'alo_pre',side_effect=pre) as m:
            with self.assertRaises(models.AloRunDefect) as e:library.evaluate_alo(self.ROW,CASE)
        self.assertIs(e.exception,planted);self.assertGreater(m.call_count,0)
    def test_run_defect_in_every_brent_callback_leaves_as_a_run_defect(self):
        """A4R-05: the same marker at the other ql.Brent callbacks (library _solve and _baw_solve, the checks IV helpers);
        the defect is planted inside the callback itself (not at ql.Brent.solve)."""
        r,q=CASE.rate,CASE.dividend_yield
        def boom(*a,**k):raise models.RunDefect('planted in callback (test-only)')
        cases=(('library._solve',mock.patch.object(library._Problem,'npv',side_effect=boom),lambda:library._solve('bsm',1,100.0,100.0,1.0,r,q,10.0,CASE,1e-4)),
               ('library._baw_solve',mock.patch.object(ref,'baw_admitted',side_effect=boom),
                lambda:library._baw_solve(library._Problem('baw',1,100.0,100.0,1.0,r,q,0.3,CASE),1,100.0,100.0,1.0,r,q,10.0,CASE,1e-4)),
               ('checks.ql_baw_implied_vol',mock.patch.object(ref,'baw_admitted',side_effect=boom),lambda:checks.ql_baw_implied_vol(1,100.0,100.0,1.0,r,q,10.0,CASE)),
               ('checks.ql_alo_implied_vol',mock.patch.object(ref,'alo_pre',side_effect=boom),lambda:checks.ql_alo_implied_vol(1,100.0,100.0,1.0,r,q,10.0,CASE)))
        for name,patch,call in cases:
            with self.subTest(site=name),patch as m:
                with self.assertRaises(models.RunDefect):call()
                self.assertGreater(m.call_count,0)
    def test_python_error_in_every_brent_callback_is_a_defect(self):
        """A5R-05 (Task A6): a Python error other than RunDefect inside a ql.Brent callback (a TypeError from a coding
        defect, planted here) never becomes a value status: brent_solve records it and raises models.CallbackDefect (a
        RunDefect) after the solve, so the run fails. The expected stops of each callback (order 5, an engine error, an
        admission exclusion, a failed pre check) stay statuses."""
        r,q=CASE.rate,CASE.dividend_yield
        def typo(*a,**k):raise TypeError('planted coding defect (test-only)')
        row=(1,100.0,100.0,1.0,10.0,10.0,r,q)
        cases=(('library._solve',mock.patch.object(library._Problem,'npv',side_effect=typo),lambda:library.evaluate(row,'bsm',CASE)),
               ('library._solve crr',mock.patch.object(library._Problem,'npv',side_effect=typo),lambda:library.evaluate(row,'crr',CASE)),
               ('library._baw_solve',mock.patch.object(library._Problem,'npv',side_effect=typo),lambda:library.evaluate_baw(row,CASE)),
               ('library._alo_solve',mock.patch.object(library._Problem,'npv',side_effect=typo),lambda:library.evaluate_alo(row,CASE)),
               ('library._alo_solve pre',mock.patch.object(ref,'alo_pre',side_effect=typo),lambda:library.evaluate_alo(row,CASE)),
               ('library._baw_solve admit',mock.patch.object(ref,'baw_admitted',side_effect=typo),lambda:library.evaluate_baw(row,CASE)),
               ('checks.ql_baw_implied_vol',mock.patch.object(ref,'baw_admitted',side_effect=typo),lambda:checks.ql_baw_implied_vol(1,100.0,100.0,1.0,r,q,10.0,CASE)),
               ('checks.ql_alo_implied_vol',mock.patch.object(ref,'alo_pre',side_effect=typo),lambda:checks.ql_alo_implied_vol(1,100.0,100.0,1.0,r,q,10.0,CASE)))
        for name,patch,call in cases:
            with self.subTest(site=name),patch as m:
                with self.assertRaises(models.CallbackDefect) as e:call()
                self.assertGreater(m.call_count,0)
                self.assertTrue(issubclass(models.CallbackDefect,models.RunDefect))
                self.assertEqual(e.exception.args[:2],('callback-error','TypeError'))
    def test_brent_solve_keeps_expected_stops_and_flags_any_other_error(self):
        with self.assertRaises(models.CallbackDefect):library.brent_solve(lambda s:{}['x'],1e-4,5.0,2.5)       # KeyError
        def stop(s):raise library.CallbackStop('order 5')
        with self.assertRaises(RuntimeError) as e:library.brent_solve(stop,1e-4,5.0,2.5)                    # a stop leaves as the solve's error
        self.assertNotIsInstance(e.exception,models.RunDefect)
        self.assertAlmostEqual(library.brent_solve(lambda s:s-0.3,1e-4,5.0,2.5),0.3,places=9)
    def test_expected_stops_remain_statuses(self):
        """The order-5 and engine-error stops of the callbacks are still MODEL_DOMAIN (unchanged behaviour)."""
        r,q=CASE.rate,CASE.dividend_yield;row=(1,100.0,100.0,1.0,10.0,10.0,r,q)
        for name,call in (('bsm',lambda:library.evaluate(row,'bsm',CASE)),('baw',lambda:library.evaluate_baw(row,CASE)),('alo',lambda:library.evaluate_alo(row,CASE))):
            with self.subTest(site=name),mock.patch.object(library._Problem,'npv',side_effect=RuntimeError('engine error text')):
                self.assertEqual(call()[0],'MODEL_DOMAIN')
            with self.subTest(site=name+' nan'),mock.patch.object(library._Problem,'npv',return_value=math.nan):
                self.assertEqual(call()[0],'MODEL_DOMAIN')

class AloOptimizedTests(unittest.TestCase):
    """py-optimized ALO: the shared NaN check raises AloRunDefect (never a status, Review Focus 6); the adaptive-path
    divergence instrumentation returns integer counts per field; the part B refusal is gone."""
    def test_optimized_nan_is_a_run_defect(self):
        chain=chain_of(4,SEED);prep=optimized.prepare(chain)
        with mock.patch.object(optimized,'_cheb_value',side_effect=lambda y,x:x*math.nan):
            with self.assertRaises(models.AloRunDefect) as e:optimized.run(prep,CASE,models=M)
        self.assertEqual(e.exception.args[0],'alo-nan')
    def test_divergence_counts_are_reported(self):
        from optionlab.contract import rows as chain_rows
        rws=chain_rows(chain_of(8,SEED))+switch_rows(CASE)[:4]
        out=optimized.alo_divergence(rws,CASE)
        self.assertEqual(set(out),{'rows','evaluations','halley','fallback','levels','any','rows_with_divergence'})
        for k,v in out.items():
            with self.subTest(field=k):self.assertIs(type(v),int);self.assertGreaterEqual(v,0)
        self.assertEqual(out['rows'],len(rws));self.assertGreater(out['evaluations'],len(rws))
        self.assertLessEqual(max(out['halley'],out['fallback'],out['levels']),out['any']);self.assertLessEqual(out['any'],out['evaluations'])
    def test_part_b_refusal_is_removed(self):
        self.assertEqual(contract.PART_B_PENDING,{});self.assertEqual(contract.check_variant_models(('alo','bsm')),('bsm','alo'))

class AloSpreadTests(unittest.TestCase):
    def test_spread_reports_flags_equal(self):
        """The `alo-spread` report holds status_equal, flags_equal (the full flag byte), bits_16_32_equal and bit-equal
        counts per variant, and the divergence counts; `baw-spread` rows hold flags_equal too (the Task 6 parked finding)."""
        d=tempfile.mkdtemp();out=checks.alo_spread_body(d,chains=((SEED,6),),switch=False,oracle_sigmas=(),oracle_edges=False,item7_points=1)
        doc=json.loads((pathlib.Path(d)/'alo-spread.json').read_text())
        self.assertEqual(out['status'],'PASS');self.assertEqual(set(doc['chain_spread']),{f'{v}/{w}' for v,w in checks.SPREAD_VARIANTS})
        for name,row in doc['chain_spread'].items():
            with self.subTest(variant=name):
                for k in ('rows','status_equal','flags_equal','bits_16_32_equal','bit_equal','compared_ok_rows'):self.assertIn(k,row)
                self.assertEqual(row['rows'],6);self.assertEqual(row['status_equal'],6);self.assertEqual(row['bits_16_32_equal'],6)
        self.assertIn('divergence',doc);self.assertEqual(doc['label'].split(';')[0],'G-ALO2 part B spread (Task A5)')
        acc=checks._empty_spread();self.assertIn('flags_equal',acc)
        a={'status':['OK','OK'],'flags':[0,32],**{f:[1.0,1.0] for f in checks.BAW_ROW_FIELDS}};b=dict(a,flags=[0,0])
        rows=[(1,100.0,100.0,0.5,1.0,1.0,CASE.rate,CASE.dividend_yield)]*2
        checks._merge_spread(acc,rows,a,b,CASE,{'failures':{},'eligible':True});self.assertEqual(acc['flags_equal'],1)

class AloToleranceProposalTests(unittest.TestCase):
    """Task A6 (I4.3, section 3.7): `alo-spread` also runs the ALO oracle set (the edge rows, the item 7 points and the
    record grid quoted at py-reference's price) on the direct variants and writes the tolerance proposal: per section 3.7
    field the general value when the measured fraction is below 1 (a widening is never proposed automatically), the
    margins against the spread, and per greek the margin of the allowance below the E-ALO-6 item 7 tolerance (the oracle
    error) at every item 7 point. The proposal state is provisional-g-alo2; the approver locks it."""
    def test_proposal_fields_and_margins(self):
        d=tempfile.mkdtemp()
        out=checks.alo_spread_body(d,chains=((SEED,4),),switch=False,oracle_sigmas=(0.3,),oracle_edges=True,item7_points=2,oracle_grid_limit=6)
        self.assertEqual(out['status'],'PASS',out.get('counts'))
        doc=json.loads((pathlib.Path(d)/'alo-spread.json').read_text());p=doc['proposal']
        self.assertEqual(p['state'],'provisional-g-alo2')
        self.assertEqual(set(p['fields']),{'iv_abs','iv_ulp_rel','price_rel','fit_nu','fit_rel','greek_abs','greek_rel','flat_vega'})
        from optionlab.agreement import TOLERANCES
        for k,f in p['fields'].items():
            with self.subTest(field=k):
                self.assertEqual(f['current'],TOLERANCES[k])
                if f.get('measured_fraction') is not None and f['measured_fraction']<1.0:self.assertEqual(f['proposed'],TOLERANCES[k])
                if f.get('measured_fraction') is not None and f['measured_fraction']>=1.0:self.assertIsNone(f['proposed'])
        self.assertEqual(set(p['item7_margins']),{'delta','gamma','vega','rho','theta'})
        for g,m in p['item7_margins'].items():
            with self.subTest(greek=g):
                self.assertEqual(m['points'],2);self.assertIn('min_tol_over_allowance',m);self.assertIn('points_allowance_above_tol',m)
        self.assertGreater(doc['oracle_counts']['edge'],0);self.assertEqual(doc['oracle_counts']['item7'],2);self.assertEqual(doc['oracle_counts']['grid'],6)
        self.assertEqual(set(doc['oracle_spread']),{'py-optimized/1','py-library/1'})
    def test_policy_alo_block_is_the_proposal_shape(self):
        a=protocol.tolerances()['alo']
        self.assertIn(a['state'],('provisional-g-alo2','locked-g-alo2'))
        self.assertEqual(set(a)-{'state','approval'},{'iv_abs','iv_ulp_rel','price_rel','fit_nu','fit_rel','greek_abs','greek_rel','flat_vega'})

class AloAccuracyTests(unittest.TestCase):
    """Task A6 (I4.5): the documented model-accuracy metrics of `alo-accuracy` (never a gate): ALO against A_ref per
    SIGMA_BANDS x T_BANDS, ALO against BAW, the scheme truncation |accurateScheme - highPrecisionScheme| (QuantLib), the
    equation-switch jump of R4, the mapping consequence of R11 and the count of OK rows priced below intrinsic."""
    def test_metrics_on_a_small_input(self):
        d=tempfile.mkdtemp()
        out=checks.alo_accuracy_body(d,lattice_limit=12,grid_limit=8,switch_sigmas=(0.3,),mapping_days=(30,),chain_rows=3)
        self.assertEqual(out['status'],'PASS',out.get('reason'));self.assertEqual(out['label'],'documented metric, never a gate')
        doc=json.loads((pathlib.Path(d)/'alo-accuracy.json').read_text())
        self.assertEqual(set(doc)>={'label','alo_vs_lattice','alo_vs_baw','scheme_truncation','equation_switch_jump','mapping_consequence','ok_below_intrinsic'},True)
        self.assertEqual(doc['label'],'documented metric, never a gate (Amendment I4.5, Amendment D)')
        lat=doc['alo_vs_lattice'];self.assertEqual(lat['points'],12)
        for k in ('count','skipped_below_0.01','above_lattice','below_lattice','bands'):self.assertIn(k,lat)
        for band in lat['bands'].values():self.assertEqual(set(band),{'count','median','p90','max'})
        self.assertIn('both_admitted',doc['alo_vs_baw'])
        sch=doc['scheme_truncation'];self.assertEqual(sch['points'],8);self.assertEqual(sch['high_precision'],{'scheme':'QdFpTanhSinhIterationScheme','m':10,'n':30,'eps':1e-10,'fp_equation':'Auto'})
        sw=doc['equation_switch_jump'];self.assertEqual(sw['t_fp_a'],checks.ALO_SWITCH_T[0]);self.assertEqual(sw['t_fp_b'],checks.ALO_SWITCH_T[1])
        self.assertGreater(sw['points'],0);self.assertIn('max_abs',sw);self.assertNotIn('max_rel_k100',sw)    # A6P-03: renamed, plus the R4 relative measure
        self.assertEqual(sw['max_abs_per_k'],sw['max_abs']/100.0);self.assertGreaterEqual(sw['max_rel_to_value'],0.0)
        self.assertIn('relative to the larger of the two values',sw['max_rel_to_value_label'])
        mc=doc['mapping_consequence'];self.assertEqual(mc['days'],[30]);self.assertGreater(mc['points'],0)
        bi=doc['ok_below_intrinsic'];self.assertEqual(set(bi),{'lattice','record_grid','chain_rows','chain_ok_rows','chain_ok_below_intrinsic'})
    def test_check_is_declared_and_never_before_run(self):
        decl={x['name']:x for x in json.loads((HERE/'bench.json').read_text())['checks']}
        self.assertEqual(decl['alo-accuracy'],{'name':'alo-accuracy','module':'optionlab.checks','before_run':False,'selectors':['alo']})

class AloOverrunStubTests(unittest.TestCase):
    """The test-only stub (I9.4): SAFE_C_TEST_STUB=alo-overrun (the protocol stub reason; EX-3) makes the py-library ALO path block (no timer in the child);
    it is read only in py-library and only for `alo`; the bench run and check stubs are bench_deadline.alo_overrun_selftest
    and alo_overrun_check_selftest (the cases suite calls them)."""
    # A5R-03 (Task A6): the child prints 'stub' from inside the real stub entry, so the positive case proves that the
    # exact value takes the blocking path; the 5 s wait starts only after that readiness handshake (a slow child start
    # on a loaded host delays the handshake, never the decision). The controls must print 'done' and never 'stub'.
    CODE=("import sys;from optionlab import library;from optionlab.params import CASE;real=library._alo_stub\n"
          "def entered():\n print('stub',flush=True);real()\n"
          "library._alo_stub=entered;print('ready',flush=True)\n"
          "library.run([(1,100.0,100.0,0.5,5.0,5.2,0.04,0.012)],CASE,models=(MODEL,));print('done',flush=True)\n")
    def child(self,value,model='alo'):
        import subprocess, sys
        e=dict(os.environ);e.pop('SAFE_C_TEST_STUB',None)
        if value is not None:e['SAFE_C_TEST_STUB']=value
        return subprocess.Popen([sys.executable,'-c',self.CODE.replace('MODEL',repr(model))],env=e,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True)
    def lines_until(self,proc,marker,limit):
        """Read stdout lines until `marker` or EOF, at most `limit` seconds (a reader thread; the limit is only a guard)."""
        import queue, threading
        q=queue.Queue();seen=[]
        threading.Thread(target=lambda:[q.put(l.strip()) for l in proc.stdout]+[q.put(None)],daemon=True).start()
        import time
        end=time.monotonic()+limit
        while time.monotonic()<end:
            try:line=q.get(timeout=max(0.0,end-time.monotonic()))
            except queue.Empty:break
            if line is None:break
            seen.append(line)
            if line==marker:break
        return seen,q
    def test_stub_blocks_only_with_the_exact_value(self):
        p=self.child('alo-overrun')
        try:
            seen,q=self.lines_until(p,'stub',600)
            self.assertEqual(seen,['ready','stub'])                     # handshake: the exact value entered the stub
            import subprocess
            with self.assertRaises(subprocess.TimeoutExpired):p.wait(timeout=5)   # timed only after the handshake: it stays blocked
            self.assertTrue(q.empty())                                  # no 'done' line arrived
        finally:
            p.kill();p.wait()
        for value,model in ((None,'alo'),('run','alo'),('BLOCK','alo'),('block','alo'),('baw-hang','alo'),('alo-overrun','bsm')):   # 'block' was the retired value; 'baw-hang' is the other stub
            p=self.child(value,model)
            with self.subTest(value=value,model=model):
                try:
                    out,_=p.communicate(timeout=600)
                finally:
                    p.kill();p.wait()
                self.assertEqual(out.split(),['ready','done'])           # the control never enters the stub
    def test_checks_are_declared_and_never_before_run(self):
        decl={x['name']:x for x in json.loads((HERE/'bench.json').read_text())['checks']}
        for name in ('alo-overrun-stub','alo-spread'):
            with self.subTest(check=name):
                c=decl[name];self.assertIs(c['before_run'],False);self.assertEqual(c['module'],'optionlab.checks');self.assertEqual(c['selectors'],['alo'])
    def test_case_declares_the_call_deadline(self):
        self.assertEqual(MANIFEST['call_deadlines'],[{'selectors':['alo'],'reason':'alo-overrun','factor':10,'floor_seconds':60}])
        self.assertIn('alo',MANIFEST['selectors'])

if __name__=='__main__':unittest.main()
