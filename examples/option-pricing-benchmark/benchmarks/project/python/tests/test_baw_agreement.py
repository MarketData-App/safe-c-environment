import copy, json, math, tempfile, unittest
from pathlib import Path
from unittest import mock
from optionlab import checks

BENCH=Path(checks.__file__).resolve().parents[2]/'bench.json'

class BawAgreementTests(unittest.TestCase):
    def test_declared_before_run(self):
        rows=[c for c in json.loads(BENCH.read_text())['checks'] if c['name']=='baw-agreement']
        self.assertEqual([(c['module'],c['before_run']) for c in rows],[('optionlab.checks',True)])
        self.assertIn('baw-agreement',checks.CHECKS)
    def test_small_input_passes_at_the_locked_tolerances(self):
        with tempfile.TemporaryDirectory() as t:
            r=checks.baw_agreement_body(t,chains=((20261007,32),),edge_names=())
        self.assertEqual((r['status'],r['tolerance_state']),('PASS','locked-g-baw2'))
        self.assertTrue(all(x['status_equal'] and x['bit64_equal'] for x in r['rows']))
    def test_refused_before_the_lock(self):
        with tempfile.TemporaryDirectory() as t,mock.patch('optionlab.checks._baw_tolerances',return_value={'state':'provisional-g-baw2'}):
            r=checks.baw_agreement_body(t,chains=((20261007,8),),edge_names=())
        self.assertEqual((r['status'],r['reason']),('FAIL','tolerances.baw not locked'))
    def test_a_perturbed_variant_fails(self):
        # T14 (ledger EX5-BAW-PERTURB-01): the plant shifts the price of the first OK row of the run. Row 0 of this chain is
        # ABOVE_MAX (price NaN), so a shift of row 0 changes nothing: with the direct variants only (T9 removed the pooled rows)
        # the check passed and this test failed. `shifted_rows` proves that the plant ran.
        from optionlab import optimized
        real=optimized.run;shifted_rows=[]
        def shifted(*a,**k):
            out=real(*a,**k);out=copy.deepcopy(out);price=out['models']['baw']['price']
            i=next(i for i,x in enumerate(price) if math.isfinite(x));price[i]+=1e-3;shifted_rows.append(i);return out
        with tempfile.TemporaryDirectory() as t,mock.patch('optionlab.optimized.run',side_effect=shifted):
            self.assertEqual(checks.baw_agreement_body(t,chains=((20261007,8),),edge_names=())['status'],'FAIL')
        self.assertTrue(shifted_rows)
