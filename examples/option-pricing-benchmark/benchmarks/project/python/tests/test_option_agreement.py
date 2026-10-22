"""The L2 request splits (at most 14,336 records per request, G-ALO-CO; responses keep the request order) and the check
b06-prerequisite-agreement (B06 prerequisite). Single-threaded variants only (owner 2026-10-16, amendment E C15); the pool
tests of Task 12b are removed with the pool rows."""
import json, tempfile, unittest
from pathlib import Path
from unittest import mock
from benchlab.pools import request_splits
from optionlab import checks, optimized as opt
from optionlab.contract import load_chain, with_rates
from optionlab.reference import result_digest as digest
from optionlab.synthetic import generate
from optionlab.params import CASE
from optionlab import protocol
CASE_FILE=Path('/src/examples/option-pricing-benchmark/benchmarks/project/cases/option-chain-greeks.json')
LIMIT=json.loads(Path('/src/safety/performance-policy.json').read_text())['pools']['request_limit']   # G-ALO-CO: 14,336
FIX=protocol.oracle()

def chain_of(n,seed):return with_rates(load_chain(generate(n,seed,CASE)),CASE.rate,CASE.dividend_yield)

def raw_bytes(result):
    """Every column of a raw (NumPy) run result as (dtype, bytes): identical bytes, NaN payloads and -0.0 included."""
    return result['n'],{m:{k:(v.dtype.str,v.tobytes()) for k,v in col.items()} for m,col in result['models'].items()}

class OptionRequestSplitTests(unittest.TestCase):
    def test_l2_request_splits_keep_the_response_order(self):
        """Compared by bytes: a materialized list holds NaN for non-OK fields, and NaN != NaN in a list comparison."""
        c=chain_of(40,7);prep=opt.prepare(c);whole=opt.run(prep,CASE)
        parts=[opt.run(opt.slice_prepared(prep,s,e),CASE) for s,e in request_splits(40,limit=16)]
        self.assertEqual([len(p['models']['bsm']['status']) for p in parts],[16,16,8])
        self.assertEqual(raw_bytes(opt.concat(parts)),raw_bytes(whole))
        self.assertEqual(digest(opt.materialize(opt.concat(parts))),digest(opt.materialize(whole)))
        self.assertNotEqual(raw_bytes(opt.concat(parts[::-1])),raw_bytes(whole))   # the order is observable on this chain
    def test_l2_chains_at_and_above_the_request_limit_recombine_to_identical_bytes(self):
        """L2: 14,336 records (one request), 14,337 (one record past the limit) and 20,000 (the contract maximum)."""
        c=chain_of(20000,7);prep=opt.prepare(c);runs={}
        def run(s,e):
            if (s,e) not in runs:runs[s,e]=opt.run(opt.slice_prepared(prep,s,e),CASE)
            return runs[s,e]
        self.assertEqual(LIMIT,14336)
        for n,sizes in ((14336,[14336]),(14337,[14336,1]),(20000,[14336,5664])):
            splits=request_splits(n,LIMIT)
            with self.subTest(n=n):
                self.assertEqual([e-s for s,e in splits],sizes);self.assertEqual(splits[0][0],0);self.assertEqual(splits[-1][1],n)
                self.assertTrue(all(a[1]==b[0] for a,b in zip(splits,splits[1:])))
                joined=opt.concat([run(s,e) for s,e in splits])
                self.assertEqual(raw_bytes(joined),raw_bytes(run(0,n)))

class AgreementCheckTests(unittest.TestCase):
    """b06-prerequisite-agreement: py-optimized and py-library on synthetic
    seeds 1-3 (64 rows) and on every oracle edge row under its own parameters. The tests run the check body on a reduced
    input; the declared check runs the full set (bench check, before_run)."""
    EDGE=[e['name'] for e in FIX['oracle']['edge_rows'] if e.get('params')][:1]+[e['name'] for e in FIX['oracle']['edge_rows'] if not e.get('params')][:1]
    def run_body(self,**kw):
        out=Path(tempfile.mkdtemp());row=checks.agreement_body(out,chains=((1,64),),edge_names=self.EDGE,**kw)
        return row,json.loads((out/'agreement.json').read_text())
    def test_declared_before_run_and_registered(self):
        decl=json.loads((CASE_FILE.parents[1]/'bench.json').read_text())
        self.assertIn(('b06-prerequisite-agreement','optionlab.checks',True),[(c['name'],c['module'],c['before_run']) for c in decl['checks']])
        self.assertIn('b06-prerequisite-agreement',checks.CHECKS)
    def test_the_check_refuses_arguments(self):
        self.assertEqual(checks.CHECKS['b06-prerequisite-agreement'](Path(tempfile.mkdtemp()),['x'])['status'],'FAIL')
    def test_every_variant_row_agrees(self):
        row,out=self.run_body()
        self.assertEqual(row['status'],'PASS');self.assertEqual(row['files'],['agreement.json'])
        want=[('py-optimized','direct'),('py-library','direct')]
        self.assertEqual(len(out),2*(1+len(self.EDGE)));self.assertEqual(row['counts']['rows'],len(out))
        self.assertEqual([(r['variant'],r['workers']) for r in out if r.get('seed')==1],want)
        self.assertEqual(sorted({r['edge_row'] for r in out if 'edge_row' in r}),sorted(self.EDGE))
        for r in out:
            with self.subTest(r=(r.get('seed',r.get('edge_row')),r['variant'],r['workers'])):
                self.assertTrue(r['eligible'],r['failures']);self.assertEqual(r['failures'],{})
                self.assertTrue(r['status_equal_reference'])
    def test_a_changed_library_status_fails_the_check(self):
        """Injected defect: the py-library row reports another status; the check refuses it."""
        from optionlab import library
        real=library.run
        def wrong(rw,p,**kw):
            out=real(rw,p,**kw);col=list(out['models']['bsm']['status']);col[0]='NOT_CONVERGED' if col[0]!='NOT_CONVERGED' else 'OK'
            out['models']['bsm']['status']=col;return out
        with mock.patch.object(library,'run',wrong):row,out=self.run_body()
        self.assertEqual(row['status'],'FAIL')
        bad=[r for r in out if r['variant']=='py-library']
        self.assertTrue(bad and all(not r['eligible'] and not r['status_equal_reference'] for r in bad))
        self.assertTrue(all(r['eligible'] for r in out if r['variant']=='py-optimized'))
    def test_the_declared_chains_are_the_case_chains(self):
        self.assertEqual([s for s,n in checks.AGREEMENT_CHAINS if n==64],[1,2,3]);self.assertIn((4,256),checks.AGREEMENT_CHAINS)

class CallCostTests(unittest.TestCase):
    """The exploratory call-cost check (Task 12b review, Important 1), on a reduced input."""
    def test_call_cost_records_the_runs_and_the_fit(self):
        out=Path(tempfile.mkdtemp());row=checks.call_cost_body(out,sizes=(1,32),reps=2)
        doc=json.loads((out/'call-cost.json').read_text())
        self.assertEqual((row['status'],row['label']),('PASS','exploratory'));self.assertIn('not decision evidence',doc['label'])
        self.assertEqual([r['rows'] for r in doc['opt_run']],[1,32]);self.assertEqual(set(doc['opt_run'][0]['models']),{'bsm','bjs','crr'})
        self.assertIn('fixed_s_per_call',doc['fit'])

if __name__=='__main__':unittest.main()
