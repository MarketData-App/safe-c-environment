"""Task 13b: the option-chain Greeks adapter on the registered-workload contract (spec 11.1, Amendment A), and the
per-row r and q columns of the prepared input (controller ruling on Task 13b; spec 3.1, Amendment C item 3)."""
import hashlib, json, math, tempfile, unittest
from pathlib import Path
from benchlab.workload import load_case_adapter
CASE_FILE=Path('/src/examples/option-pricing-benchmark/benchmarks/project/cases/option-chain-greeks.json')
ROWS=(('py-reference',1),('py-optimized',1))

class OptionAdapterTests(unittest.TestCase):
    def setUp(self):self.a=load_case_adapter(json.loads(CASE_FILE.read_text()))
    def dataset(self,n):
        data=self.a.synthesize(n,11);p=Path(tempfile.mkdtemp())/'chain.json';p.write_bytes(data)
        return {'path':str(p),'sha256':hashlib.sha256(data).hexdigest()}
    def test_round_trip_every_variant(self):
        chain=self.a.load(self.dataset(40));ref=self.a.reference(chain)
        for variant,workers in ROWS:
            res=self.a.materialize(self.a.run(self.a.prepare(chain,variant,workers),variant,workers))
            with self.subTest(variant=variant):self.assertEqual(self.a.work_units(res),40);self.assertTrue(self.a.validate(res,ref,chain)['eligible'])
    def test_validate_reports_the_protocol_verdict_counts_under_counts(self):
        """T11 (FR5 item 2): the verdict holds `counts` with exactly the protocol verdict_counts names, each {model: count}; the
        names are not top-level keys of the verdict, and the framework keys stay (py-reference against itself, no SciPy)."""
        from optionlab import protocol
        chain=self.a.load(self.dataset(12));ref=self.a.reference(chain)
        res=self.a.materialize(self.a.run(self.a.prepare(chain,'py-reference',1),'py-reference',1));v=self.a.validate(res,ref,chain)
        names=protocol.protocol()['verdict_counts']
        self.assertEqual(sorted(v['counts']),sorted(names));self.assertEqual(names,['multi_root','boundary_ambiguous','flat_vega'])
        self.assertTrue(all(isinstance(n,int) and n>=0 for per in v['counts'].values() for n in per.values()))
        self.assertTrue(set(names).isdisjoint(v));self.assertTrue({'eligible','failures','reduction','model_errors'}<=set(v))
        self.assertTrue(v['eligible'])
    def test_dataset_digest_is_checked(self):
        d=self.dataset(2);d['sha256']='0'*64
        with self.assertRaises(ValueError):self.a.load(d)
    def test_dropped_rows_give_fewer_work_units(self):
        chain=self.a.load(self.dataset(10));res=self.a.materialize(self.a.run(self.a.prepare(chain,'py-optimized'),'py-optimized',1))
        for col in res['models'].values():
            for k in col:col[k]=col[k][:9]
        self.assertEqual(self.a.work_units(res),9);self.assertFalse(self.a.validate(res,self.a.reference(chain),chain)['eligible'])
    def test_slice_result_matches_a_prefix_reference(self):
        chain=self.a.load(self.dataset(12));ref=self.a.reference(chain);sub=self.a.slice(chain,5)
        self.assertEqual(self.a.digest(self.a.slice_result(ref,5,sub)),self.a.digest(self.a.reference(sub)))

    # ---- additions to the brief's draft (no check is weaker) ----
    def test_tiny_dataset_round_trip_with_one_worker(self):
        """The `bench validate` path: one synthesized row at the case seed, every implemented Python variant, 1 worker."""
        data=self.a.synthesize(1,20261007);p=Path(tempfile.mkdtemp())/'tiny';p.write_bytes(data)
        chain=self.a.load({'path':str(p),'sha256':hashlib.sha256(data).hexdigest()});ref=self.a.reference(chain)
        for variant,_ in ROWS:
            res=self.a.materialize(self.a.run(self.a.prepare(chain,variant,1),variant,1))
            with self.subTest(variant=variant):self.assertEqual(self.a.work_units(res),1);self.assertTrue(self.a.validate(res,ref,chain)['eligible'])
    def test_empty_prepared_has_every_prepared_column(self):
        """Review Minor 1 (retargeted from combine([]), a pool-only method): the empty input is built from optimized.PREPARED, so a new column cannot drift."""
        from unittest import mock
        from optionlab import optimized
        e=optimized.empty_prepared()
        self.assertEqual(set(e),{'n',*optimized.PREPARED});self.assertTrue(all(len(e[k])==0 for k in optimized.PREPARED))
        with mock.patch.object(optimized,'PREPARED',optimized.PREPARED+('extra',)):self.assertIn('extra',optimized.empty_prepared())
    def test_the_adapter_has_no_pool_interface(self):
        """Owner 2026-10-16 (amendment E C15): single-threaded variants only; no chunk, run_chunk or combine, and a pool variant is refused."""
        for name in ('chunks','run_chunk','combine'):self.assertFalse(hasattr(self.a,name),name)
        for variant in ('py-parallel',):
            with self.subTest(variant=variant),self.assertRaises(ValueError):self.a.run(None,variant,2)
    def test_loaded_chain_carries_per_row_rates_from_the_case_parameters(self):
        chain=self.a.load(self.dataset(6))
        self.assertEqual((chain['r'],chain['q']),([0.04]*6,[0.012]*6))
        p=self.a.prepare(chain,'py-optimized');self.assertEqual((p['r'].tolist(),p['q'].tolist()),([0.04]*6,[0.012]*6))
        self.assertEqual([(x[6],x[7]) for x in self.a.prepare(chain,'py-reference')],[(0.04,0.012)]*6)
        sub=self.a.slice(chain,2);self.assertEqual((sub['r'],sub['q']),([0.04]*2,[0.012]*2))

class PerRowRateTests(unittest.TestCase):
    """Controller ruling: the pricing path reads r and q per row, never the scalar case parameters. A chain with two
    different q values is priced per row identically by py-reference and py-optimized: each row equals the row of a chain
    that holds its q everywhere, and the two variants agree (agreement.compare eligible, equal statuses)."""
    N=24;Q2=0.03;R2=0.055
    def setUp(self):
        from optionlab.contract import with_rates
        self.a=load_case_adapter(json.loads(CASE_FILE.read_text()));self.with_rates=with_rates
        data=self.a.synthesize(self.N,5);p=Path(tempfile.mkdtemp())/'chain.json';p.write_bytes(data)
        self.base=self.a.load({'path':str(p),'sha256':hashlib.sha256(data).hexdigest()})
    def priced(self,chain,variant):return self.a.materialize(self.a.run(self.a.prepare(chain,variant,1),variant,1))
    def test_two_q_values_are_priced_per_row_by_both_variants(self):
        self.check_per_row(lambda v:(0.04,v),0.012,self.Q2,'q',('bjs','iv'))
    def test_two_r_values_are_priced_per_row_by_both_variants(self):
        """Review Minor 2: r varies per row, so an r value sent to the wrong row in the CRR rate bump or the rho path of
        any variant changes a bit-compared field (CRR rho is compared at every row)."""
        self.check_per_row(lambda v:(v,0.012),0.04,self.R2,'r',('crr','rho'))
    def check_per_row(self,pair,lo_v,hi_v,key,moved):
        vals=[hi_v if i%2 else lo_v for i in range(self.N)]
        mixed=self.with_rates(self.base,*pair(vals));flat_lo=self.with_rates(self.base,*pair(lo_v));flat_hi=self.with_rates(self.base,*pair(hi_v))
        self.assertEqual(mixed[key],vals)
        results={}
        for variant in ('py-reference','py-optimized'):
            got=self.priced(mixed,variant);lo=self.priced(flat_lo,variant);hi=self.priced(flat_hi,variant);results[variant]=got
            for m in got['models']:
                for i in range(self.N):
                    want=(hi if i%2 else lo)['models'][m]
                    with self.subTest(variant=variant,model=m,row=i):
                        self.assertEqual(got['models'][m]['status'][i],want['status'][i])
                        for f in ('iv','price','delta','gamma','theta','vega','rho'):
                            a,b=got['models'][m][f][i],want[f][i]
                            self.assertTrue(a==b or (math.isnan(a) and math.isnan(b)),(f,a,b))
            m,f=moved
            changed=sum(1 for i in range(1,self.N,2) if lo['models'][m][f][i]!=hi['models'][m][f][i] and lo['models'][m]['status'][i]==hi['models'][m]['status'][i]=='OK')
            self.assertGreater(changed,0,f'{key} must move {m} {f} of some OK row')
        v=self.a.validate(results['py-optimized'],results['py-reference'],mixed)
        self.assertTrue(v['eligible'],v['failures'])
        for m in ('bsm','bjs','crr'):self.assertEqual(results['py-optimized']['models'][m]['status'],results['py-reference']['models'][m]['status'])
    def test_rate_columns_are_checked(self):
        for r,q in ((0.04,[0.012]*(self.N-1)),([0.04]*(self.N+1),0.012),(math.nan,0.012),(0.04,math.inf),(True,0.012),('0.04',0.012)):
            with self.subTest(r=type(r).__name__,q=type(q).__name__),self.assertRaises(ValueError):self.with_rates(self.base,r,q)
    def test_optimized_prepare_needs_rate_columns_or_case_parameters(self):
        from optionlab import optimized
        bare={k:v for k,v in self.base.items() if k not in ('r','q')}
        with self.assertRaises(ValueError):optimized.prepare(bare)

if __name__=='__main__':unittest.main()
