"""G-BAW2 part B (Task 6; spec Amendment G2.3, Appendix G-BAW R4 item 9, R12 F5): BAW in py-optimized, py-library only (single-threaded variants).
The variant identity covers the status and flag bit 64 `admit_excluded` only (G2.3); value agreement at the BAW
tolerances runs in Task 7 after the approver locks tolerances.baw (N6). The synthetic rows are the first 256 rows of the
synthetic large chain at the case seed (synthetic.generate is prefix-stable). The test-only counters (SAFE_C_TEST_COUNTERS)
show that only `baw` is computed (Task 2 merge rule). The py-library S* side-test overhead (P3R2-04) is a positive median."""
import copy, json, math, os, pathlib, unittest
os.environ['SAFE_C_TEST_COUNTERS']='1'
from optionlab import counters, synthetic, optimized, library, reference as ref
from optionlab.adapter import OptionChainGreeks
from optionlab.contract import load_chain, with_rates
from optionlab.models import BawRunDefect
from optionlab.params import CASE, CaseParams
from optionlab import protocol
MANIFEST=json.loads((pathlib.Path(__file__).resolve().parents[2]/'cases/option-chain-greeks.json').read_text())
RAW={k:v['value'] for k,v in MANIFEST['parameters'].items()}
LIMIT=json.loads(pathlib.Path('/src/safety/performance-policy.json').read_text())['pools']['request_limit']
FIX=protocol.oracle()
SEED=RAW['seed'];N=256
VARIANTS=(('py-optimized',1),('py-library',1))

def chain_of(n,seed):return with_rates(load_chain(synthetic.generate(n,seed,CASE)),CASE.rate,CASE.dividend_yield)
def key(col):return [(s,f&64) for s,f in zip(col['status'],col['flags'])]

class BawVariantIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chain=chain_of(N,SEED);cls.a=OptionChainGreeks(RAW,selector='baw',request_limit=LIMIT)
        cls.ref=cls.a.reference(cls.chain);cls.results={}
        for variant,workers in VARIANTS:
            counters.reset()
            res=cls.a.materialize(cls.a.run(cls.a.prepare(cls.chain,variant,workers),variant,workers))
            cls.results[variant]=(res,counters.snapshot())
    def test_status_and_bit_64_equal_py_reference_on_every_row(self):
        want=key(self.ref['models']['baw']);self.assertEqual(len(want),N)
        self.assertGreater(sum(1 for s,_ in want if s=='OK'),N//2)          # the rows reach the greeks, not only early statuses
        for variant,_ in VARIANTS:
            res,_=self.results[variant]
            with self.subTest(variant=variant):
                self.assertEqual(set(res['models']),{'baw'});self.assertEqual(key(res['models']['baw']),want)
    def test_counters_show_only_baw(self):
        for variant,_ in VARIANTS:
            with self.subTest(variant=variant):
                snap=self.results[variant][1];self.assertEqual({k for k,v in snap.items() if v},{'baw'})
    def test_reference_overhead_is_a_positive_median(self):
        out=self.a.reference_overhead(self.chain)
        self.assertEqual(set(out),{'library_overhead_ns_per_row'})
        self.assertTrue(math.isfinite(out['library_overhead_ns_per_row']));self.assertGreater(out['library_overhead_ns_per_row'],0.0)
    def test_overhead_refuses_fewer_than_256_rows(self):
        """Review Minor 6: the overhead is defined on the first 256 rows; a shorter chain is refused with a clear error."""
        from optionlab.contract import slice_chain
        with self.assertRaisesRegex(ValueError,'256'):self.a.reference_overhead(slice_chain(self.chain,255))
    def test_no_overhead_without_baw(self):
        self.assertIsNone(OptionChainGreeks(RAW,selector='crr',request_limit=LIMIT).reference_overhead(self.chain))
        self.assertIsNone(OptionChainGreeks(RAW,request_limit=LIMIT).reference_overhead(self.chain))

class BawEdgeRowIdentityTests(unittest.TestCase):
    """Added by the implementer: every BAW oracle edge row of the fixtures (exclusions for each reason, European branch,
    exercise side, stencil-switched and halved stencils, pre-engine statuses) gives the py-reference status and bit 64 in
    py-optimized and py-library, with the row's own parameters; the planted run-defect rows raise BawRunDefect in all three.
    Controller ruling (review Minor 1): the tests assert what G2.3 requires across variants, status and bit 64; the other
    flag bits (2, 8, 16, 32) depend on engine values and are reported in the task report, not asserted."""
    def edge_rows(self):return [e for e in FIX['oracle'].get('baw',[]) if e.get('kind')=='edge']
    def test_edge_rows(self):
        rows=self.edge_rows();self.assertGreaterEqual(len(rows),20)
        reasons=set();n=0
        for e in rows:
            pp=CaseParams(**{**CASE.__dict__,**e.get('params',{})});row=tuple(e['row'])
            with self.subTest(row=e['name']):
                if e['status']=='DEFECT':
                    with self.assertRaises(BawRunDefect):ref.evaluate(row,'baw',pp)
                    with self.assertRaises(BawRunDefect):optimized.evaluate_model('baw',optimized.prepare(load_one(row),pp),pp)
                    with self.assertRaises(BawRunDefect):library.run([row],pp,models=('baw',))      # review Minor 4
                    continue
                info={};st,_,fl,_=ref.evaluate(row,'baw',pp,info=info)
                reasons.add(info.get('admit_reason'));n+=1
                o=optimized.materialize(optimized.run(optimized.prepare(load_one(row),pp),pp,models=('baw',)))['models']['baw']
                l=library.run([row],pp,models=('baw',))['models']['baw']
                self.assertEqual((o['status'][0],o['flags'][0]&64),(st,fl&64),'py-optimized')
                self.assertEqual((l['status'][0],l['flags'][0]&64),(st,fl&64),'py-library')
        self.assertTrue({'row','brent','bump'}&reasons,reasons)
    def test_py_library_values_are_quantlib_values(self):
        """py-library BAW evaluates QuantLib's engine; on the OK edge rows the result equals py-reference (bit identity G2.4,
        measured on the record grid) within ALIGN_TOL; a reported check, value tolerances stay with Task 7."""
        from optionlab.checks import ALIGN_TOL
        for e in self.edge_rows():
            if e['status']!='OK':continue
            pp=CaseParams(**{**CASE.__dict__,**e.get('params',{})});row=tuple(e['row'])
            a=ref.evaluate(row,'baw',pp);l=library.run([row],pp,models=('baw',))['models']['baw']
            with self.subTest(row=e['name']):
                self.assertEqual(l['status'][0],'OK')
                for k,x in zip(('iv','price','delta','gamma','theta','vega','rho'),a[1]):
                    tol=1e-9 if k=='iv' else ALIGN_TOL[k]
                    self.assertLessEqual(abs(l[k][0]-x)/max(1.0,abs(x)),tol,k)

def load_one(row):
    """A one-row chain in the prepared form (optimized.prepare reads the columnar chain with per-row r and q)."""
    side,S,K,T,bid,ask,r,q=row
    return {'n':1,'side':[side],'S':[S],'K':[K],'T':[T],'bid':[bid],'ask':[ask],'r':[r],'q':[q]}

class BawStubTests(unittest.TestCase):
    """The test-only stub (G2.3): SAFE_C_TEST_STUB=baw-hang (the protocol stub reason; EX-3) makes the py-library BAW path block (no timer in the child);
    it is read only in py-library and only for `baw`; the bench run and check stubs are bench_deadline.baw_hang_selftest and
    baw_hang_check_selftest (Task 29 calls them)."""
    def test_stub_blocks_only_with_the_exact_value(self):
        import subprocess, sys
        code=("import sys;from optionlab import library;from optionlab.params import CASE;"
              "library.run([(1,100.0,100.0,0.5,5.0,5.2,0.04,0.012)],CASE,models=('baw',));print('done')")
        env=dict(os.environ,SAFE_C_TEST_STUB='baw-hang')
        with self.assertRaises(subprocess.TimeoutExpired):subprocess.run([sys.executable,'-c',code],env=env,timeout=5,capture_output=True)
        for value in (None,'run','BLOCK','block','alo-overrun'):      # 'block' was the value of the retired per-model variable; 'alo-overrun' is the other stub
            e=dict(os.environ);e.pop('SAFE_C_TEST_STUB',None)
            if value is not None:e['SAFE_C_TEST_STUB']=value
            with self.subTest(value=value):
                out=subprocess.run([sys.executable,'-c',code],env=e,timeout=120,capture_output=True,text=True)
                self.assertEqual(out.stdout.strip().splitlines()[-1:],['done'])
        code2=code.replace("models=('baw',)","models=('bsm',)")
        out=subprocess.run([sys.executable,'-c',code2],env=env,timeout=120,capture_output=True,text=True);self.assertEqual(out.stdout.strip().splitlines()[-1:],['done'])
    def test_check_is_declared_and_never_before_run(self):
        decl=json.loads((pathlib.Path(__file__).resolve().parents[2]/'bench.json').read_text())
        c={x['name']:x for x in decl['checks']}['baw-hang-stub'];self.assertIs(c['before_run'],False);self.assertEqual(c['module'],'optionlab.checks')
    def test_case_declares_the_call_deadline(self):
        self.assertEqual(MANIFEST['call_deadline'],{'selectors':['baw'],'reason':'baw-hang','factor':10,'floor_seconds':60})
        self.assertIn('baw',MANIFEST['selectors']);self.assertIn('all',MANIFEST['selectors'])

if __name__=='__main__':unittest.main()
