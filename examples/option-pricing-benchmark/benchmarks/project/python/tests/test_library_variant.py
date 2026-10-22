"""Task 9b: the py-library variant (QuantLib-Python 1.43, C++ library through SWIG; spec Amendment B items 2, 5 and 7)
and section 4 item 9 "QuantLib agreement" in b06-prerequisite-oracle (Amendment D item 0(a))."""
import copy, hashlib, json, tempfile, unittest
from pathlib import Path
from unittest import mock
from benchlab.workload import load_case_adapter
from optionlab import agreement, checks, library, reference, synthetic
from optionlab.contract import load_chain, rows as chain_rows, with_rates
from optionlab.params import CASE
from tests import quantlib_cache
from optionlab import protocol
CASE_FILE=Path('/src/examples/option-pricing-benchmark/benchmarks/project/cases/option-chain-greeks.json')
FIX=protocol.oracle()

class LibraryVariantTests(unittest.TestCase):
    def test_library_run_is_eligible_against_reference(self):
        for seed in (1,2,3):
            rows=chain_rows(load_chain(synthetic.generate(64,seed,CASE)),CASE)
            v=agreement.compare(rows,library.run(rows,CASE),reference.run(rows,CASE),CASE)
            with self.subTest(seed=seed):self.assertTrue(v['eligible']);self.assertEqual(v['reduction'],'MATCH')
    def test_adapter_runs_py_library(self):
        a=load_case_adapter(json.loads(CASE_FILE.read_text()))
        for seed in (1,2,3):
            data=a.synthesize(64,seed);p=Path(tempfile.mkdtemp())/'chain.json';p.write_bytes(data)
            chain=a.load({'path':str(p),'sha256':hashlib.sha256(data).hexdigest()})
            res=a.materialize(a.run(a.prepare(chain,'py-library',1),'py-library',1))
            with self.subTest(seed=seed):
                self.assertEqual(a.work_units(res),64);self.assertTrue(a.validate(res,a.reference(chain),chain)['eligible'])
    def test_adapter_py_library_reads_the_per_row_columns(self):
        a=load_case_adapter(json.loads(CASE_FILE.read_text()))
        base=load_chain(synthetic.generate(24,5,CASE));low=with_rates(base,CASE.rate,CASE.dividend_yield);high=with_rates(base,CASE.rate,0.03)
        r_low=a.run(a.prepare(low,'py-library'),'py-library',1);r_high=a.run(a.prepare(high,'py-library'),'py-library',1)
        self.assertNotEqual(r_low['models']['bjs']['iv'],r_high['models']['bjs']['iv'])
        self.assertTrue(a.validate(r_high,a.reference(high),high)['eligible'])
    def test_manifest_declares_py_library(self):
        case=json.loads(CASE_FILE.read_text());v={x['id']:x for x in case['variants']}['py-library']
        self.assertEqual((v['language'],v['workers'],v['status']),('python-library',['direct'],'implemented'))
        self.assertIn('C++ library through SWIG',v['reason'])
        pts={p['name']:p['variants'] for p in case['points']}
        for name in ('baseline','full-dataset','crossover-tiny','crossover-small'):self.assertIn('py-library',pts[name],name)
        self.assertNotIn('py-library',pts['language-only'])

class QuantLibAgreementItemTests(unittest.TestCase):
    """Section 4 item 9: py-reference against py-library on the grid, every lattice point, the item 3 rows and every edge row."""
    @classmethod
    def setUpClass(cls):cls.result=checks.quantlib_agreement_item(FIX,CASE,evidence=quantlib_cache.doc(FIX,CASE,()))   # Task DD (DD2): the shared parts once per process
    def test_item9_passes_and_covers_every_part(self):
        r=self.result;self.assertEqual((r['status'],r['failures']),('PASS',[]))
        parts=r['parts']
        self.assertEqual(parts['grid'],3*len(checks.ALIGN_GRID));self.assertEqual(parts['edge_rows'],len(FIX['oracle']['edge_rows']))
        self.assertEqual(parts['known_answers'],len(FIX['oracle']['known_answers']))
        self.assertGreaterEqual(parts['lattice'],9*len(FIX['oracle']['lattice']))
        self.assertEqual(r['checked'],sum(parts.values()))
    def test_a_changed_lattice_value_fails_item9(self):
        fx=copy.deepcopy(FIX);fx['oracle']['lattice'][7]['euro']['400']+=1e-6
        self.assertEqual(checks.quantlib_agreement_item(fx,CASE,parts=('lattice',))['status'],'FAIL')
    def test_a_changed_library_value_fails_item9_on_the_edge_rows(self):
        real=library.run
        def shifted(rows,params):
            out=real(rows,params)
            for col in out['models'].values():col['price']=[p*(1+1e-6) if p==p else p for p in col['price']]
            return out
        with mock.patch.object(library,'run',shifted):r=checks.quantlib_agreement_item(FIX,CASE,parts=('edge_rows',))
        self.assertEqual(r['status'],'FAIL');self.assertTrue(all(f.startswith('edge ') for f in r['failures']))
    def test_a_nan_grid_value_fails_item9(self):
        real=library.price_and_greeks
        def nan_delta(*a,**k):return dict(real(*a,**k),delta=float('nan'))
        with mock.patch.object(library,'price_and_greeks',nan_delta):r=checks.quantlib_agreement_item(FIX,CASE,parts=('grid',))
        self.assertEqual(r['status'],'FAIL')
    def test_b06_holds_item9(self):
        items={str(i):{'status':'PASS','checked':1,'failures':[]} for i in range(1,9)}
        from optionlab import oracle
        with mock.patch.object(oracle,'run_all',lambda fx,params:dict(items)),\
             mock.patch.object(checks,'quantlib_agreement_item',lambda fx,params,evidence=None:{'status':'FAIL','checked':5,'failures':['edge x'],'parts':{}}):
            row=checks.CHECKS['b06-prerequisite-oracle'](Path(tempfile.mkdtemp()),[])
        self.assertEqual(row['status'],'FAIL');self.assertEqual((row['counts']['item9_checked'],row['counts']['item9_failures']),(5,1))
        self.assertEqual(len(row['counts']),19)                   # ruling T28-C1: 9 items x 2 plus incomplete_items

class NaNAgreementTests(unittest.TestCase):
    """Finding PL-T9B-NAN-MAX-01: max(0.0, nan) dropped a NaN difference, so quantlib-alignment and optimized-agreement
    could PASS with a NaN greek. Every deciding maximum now goes through checks._rel (NaN difference -> inf)."""
    def test_rel_table(self):
        import math
        nan,inf=float('nan'),math.inf
        for x,ref,want in ((nan,1.0,inf),(1.0,nan,inf),(nan,nan,0.0),(inf,inf,0.0),(inf,1.0,inf),(1.0,inf,inf),(1.0,2.0,0.5),(2.0,1.0,1.0),(3.0,-0.5,3.5),(-inf,inf,inf)):
            with self.subTest(x=x,ref=ref):self.assertEqual(checks._rel(x,ref),want)
        self.assertTrue(checks._within(math.inf,math.inf,1e-10));self.assertFalse(checks._within(nan,1.0,1e-10))
    def test_alignment_grid_nan_fails_quantlib_alignment(self):
        import math
        real=library.price_and_greeks
        def nan_delta(*a,**k):return dict(real(*a,**k),delta=float('nan'))
        # Task DD (DD2): the NaN is planted in the grid (this check's own part, computed below under the patch); the shared
        # lattice/BAW/ALO comparison, which library.price_and_greeks does not enter, is the saved copy of the session (DD1)
        out=quantlib_cache.place(tempfile.mkdtemp(),FIX,CASE)
        with mock.patch.object(library,'price_and_greeks',nan_delta):
            grid=checks._alignment_grid(CASE)
            self.assertEqual(grid['bsm']['fraction_of_tolerance']['delta'],math.inf)
            stub={'rows':1,'compare':{'eligible':True}}
            with mock.patch.object(checks,'_alignment_chain',lambda params:stub):
                row=checks.CHECKS['quantlib-alignment'](out,[])
        self.assertEqual(row['status'],'FAIL')
        self.assertEqual(json.loads((out/'alignment.json').read_text())['quantlib_evidence']['source'],'reused')
    def test_optimized_grid_nan_fails_optimized_agreement(self):
        import math
        from optionlab import optimized
        real=optimized.price_and_greeks
        def nan_lane(*a,**k):
            out=dict(real(*a,**k));d=out['delta'].copy();d[0]=float('nan');out['delta']=d;return out
        with mock.patch.object(optimized,'price_and_greeks',nan_lane):row=checks.CHECKS['optimized-agreement'](Path(tempfile.mkdtemp()),[])
        g=row['grid']['bsm']
        self.assertEqual((g['dead'],g['fraction_of_align_tol_vs_reference']['delta'],g['fraction_of_align_tol_vs_quantlib']['delta']),(0,math.inf,math.inf))
        self.assertEqual(row['status'],'FAIL')
    def test_optimized_lattice_nan_fails_optimized_agreement(self):
        import math
        import numpy as np
        from optionlab import optimized
        real=optimized.crr_price
        def nan_value(*a,**k):
            val,dead=real(*a,**k);val=np.array(val,float);val[0]=float('nan');return val,np.zeros_like(dead)
        with mock.patch.object(optimized,'crr_price',nan_value):row=checks.CHECKS['optimized-agreement'](Path(tempfile.mkdtemp()),[])
        self.assertEqual(row['lattice']['dead'],0);self.assertEqual(row['lattice']['fraction_of_align_tol_vs_quantlib'],math.inf)
        self.assertEqual(row['status'],'FAIL')

if __name__=='__main__':unittest.main()
