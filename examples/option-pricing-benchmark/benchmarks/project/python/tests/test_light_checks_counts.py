import unittest
from optionlab import checks
class CountsTests(unittest.TestCase):
    def test_incomplete_items_count(self):
        self.assertIn('incomplete_items',checks.oracle_count_keys())

    def test_oracle_check_counts_hold_the_incomplete_count_last(self):
        # R1B-02: the oracle check row's counts use exactly oracle_count_keys() in natural order (ruling T28-C2: every key
        # reaches the host); incomplete_items is the number of INCOMPLETE items and comes last
        import json, tempfile
        from pathlib import Path
        from unittest import mock
        from optionlab import oracle
        def items(incomplete):
            r={str(k):{'status':'INCOMPLETE' if str(k) in incomplete else 'PASS','checked':[0]*k,'failures':[]} for k in range(1,9)}
            return r
        for incomplete,status in (((),'PASS'),(('3',),'PASS'),(('3','6'),'FAIL')):
            with self.subTest(incomplete=incomplete),tempfile.TemporaryDirectory() as t:
                fx=Path(t)/'fx.json';fx.write_text('{}')
                with mock.patch.object(checks,'FIXTURES',fx),mock.patch.object(oracle,'run_all',return_value=items(incomplete)),\
                     mock.patch.object(checks,'quantlib_agreement_item',return_value={'status':'PASS','checked':5,'failures':[]}),\
                     mock.patch.object(checks,'_edge_erf_saturated',return_value={}):
                    row=checks._oracle_check_body(t,[])
                self.assertEqual(row['status'],status)
                self.assertEqual(tuple(row['counts']),checks.oracle_count_keys(tuple(str(k) for k in range(1,10))))
                self.assertEqual(list(row['counts'])[:2]+list(row['counts'])[-1:],['item1_checked','item1_failures','incomplete_items'])
                self.assertEqual(row['counts']['incomplete_items'],len(incomplete))
                self.assertIs(type(row['counts']['incomplete_items']),int)
                self.assertEqual((row['counts']['item4_checked'],row['counts']['item9_checked'],row['counts']['item9_failures']),(4,5,0))
                self.assertEqual(json.loads((Path(t)/'oracle-check.json').read_text())['counts'],row['counts'])
