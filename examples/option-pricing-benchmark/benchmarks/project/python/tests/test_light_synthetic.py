import unittest
from pathlib import Path
ROOT=Path('/src')   # the bench container mounts the repository read-only at /src
from optionlab.synthetic import generate, dataset_digest
from optionlab.contract import load_chain
from optionlab.crosscheck import unit_scale, CANDIDATE_SCALES
from optionlab.params import CASE

SCHEMA=('s','optionSymbol','underlying','expiration','side','strike','firstTraded','dte','updated','bid','bidSize','mid','ask','askSize','last',
        'openInterest','volume','inTheMoney','intrinsicValue','extrinsicValue','underlyingPrice','iv','delta','gamma','theta','vega')

class SyntheticTests(unittest.TestCase):
    def test_tiny_chain_is_deterministic_and_valid(self):
        a=generate(1,7,CASE);b=generate(1,7,CASE)
        self.assertEqual(dataset_digest(a),dataset_digest(b));self.assertEqual(load_chain(a)['n'],1)
    def test_unit_scale_snaps_to_a_candidate(self):
        chain={'n':2,'S':[100.0,100.0],'K':[100.0,101.0],'provider':{f:[2.0,2.0] for f in ('iv','delta','gamma','theta','vega')}}
        res={'models':{'bsm':{'status':['OK','OK'],**{f:[0.02,0.02] for f in ('iv','delta','gamma','theta','vega')}}}}
        s=unit_scale(chain,res);self.assertEqual(s['vega']['scale'],100.0);self.assertTrue(s['vega']['rescaled'])
    def test_columns_match_the_market_data_schema(self):
        c=generate(30,5,CASE);self.assertEqual(sorted(c),sorted(SCHEMA))
        self.assertTrue(all(len(c[k])==30 for k in SCHEMA if k!='s'))
        self.assertEqual(dataset_digest(generate(30,5,CASE)),dataset_digest(c));self.assertNotEqual(dataset_digest(generate(30,6,CASE)),dataset_digest(c))
        self.assertEqual(sorted(CANDIDATE_SCALES),sorted((1.0,100.0,0.01,365.0,1/365.0)))
