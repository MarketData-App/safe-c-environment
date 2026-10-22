"""G-ALO-CO part 2 (Task A2; Amendment I1.3, I6.3, I7.3, I9.2): the MODELS5 bit and record order, the pending `alo`
selector, the ocg-v1m mask and key order with `alo`, and the case declarations. No ALO pricing exists before G-ALO2."""
import json, unittest
from pathlib import Path
from optionlab import contract, reference

class Models5Tests(unittest.TestCase):
    def test_order_and_bits(self):
        self.assertEqual(contract.MODELS5,('bsm','bjs','crr','baw','alo'));self.assertEqual(contract.MODELS4,('bsm','bjs','crr','baw'))
    def test_alo_is_no_longer_pending(self):          # Task A4 (G-ALO2 part A): PENDING_MODELS is empty again (Amendment I1.3)
        self.assertEqual(contract.selector_models('alo'),('alo',));self.assertEqual(contract.check_models(('alo',)),('alo',))
    def part(self):
        p={f:[0.0] for f in contract.FIELDS};p['status']=['OK'];p['flags']=[0];return p
    def test_mask_and_key_order_with_alo(self):
        b=reference.canonical_result({'n':1,'models':{'alo':self.part(),'baw':self.part()}})
        self.assertTrue(b.startswith(b'{"digest_form":"ocg-v1m","mask":24,"models":{"alo":'))
    def test_baw_era_bytes_unchanged(self):
        b=reference.canonical_result({'n':1,'models':{'crr':self.part()}});self.assertTrue(b.startswith(b'{"digest_form":"ocg-v1m","mask":4,"models":{"crr":'))
    def test_case_declares_the_selector_and_the_deadline(self):
        c=json.loads((Path(contract.__file__).resolve().parents[2]/'cases/option-chain-greeks.json').read_text())
        self.assertEqual(c['selectors'],['all','bsm','bjs','crr','baw','alo'])
        self.assertEqual(c['call_deadlines'],[{'selectors':['alo'],'reason':'alo-overrun','factor':10,'floor_seconds':60}])

class Models5BoundaryTests(unittest.TestCase):
    """Added by the implementer: the mask bound (31), every BAW-era mask (1-15) byte-equal to the MODELS4 rule, the
    pending text, the case version and the adapter refusal of the pending selector."""
    def part(self):
        p={f:[0.0] for f in contract.FIELDS};p['status']=['OK'];p['flags']=[0];return p
    def test_every_baw_era_mask_keeps_its_bytes(self):
        import itertools, json as js
        for k in range(1,5):
            for keys in itertools.combinations(contract.MODELS4,k):
                b=reference.canonical_result({'n':1,'models':{m:self.part() for m in keys}})
                if set(keys)=={'bsm','bjs','crr'}:self.assertTrue(b.startswith(b'{"digest_form":"ocg-v1",'));continue
                doc=js.loads(b);self.assertEqual(doc['mask'],sum(1<<contract.MODELS4.index(m) for m in keys))
                self.assertEqual(list(doc['models']),sorted(keys))
    def test_the_full_mask_and_unknown_keys(self):
        doc=json.loads(reference.canonical_result({'n':1,'models':{m:self.part() for m in contract.MODELS5}}))
        self.assertEqual((doc['digest_form'],doc['mask'],list(doc['models'])),('ocg-v1m',31,['alo','baw','bjs','bsm','crr']))
        self.assertEqual(json.loads(reference.canonical_result({'n':1,'models':{'alo':self.part()}}))['mask'],16)
        for bad in ({},{'xyz':self.part()},{'alo':self.part(),'ALO':self.part()}):
            with self.subTest(keys=list(bad)),self.assertRaises(ValueError):reference.canonical_result({'n':1,'models':bad})
    def test_pending_text_and_order(self):
        self.assertEqual(contract.PENDING_MODELS,{})                       # Task A4: alo is a py-reference model
        self.assertEqual(contract.check_models(('baw','alo')),('baw','alo'))
        self.assertEqual(contract.PART_B_PENDING,{})                     # Task A5 (G-ALO2 part B): no variant refuses alo
        self.assertEqual(contract.check_models(['baw','bsm']),('bsm','baw'))
        for bad in (('bsm','bsm'),('zz',),(),'alo'):
            with self.subTest(bad=bad),self.assertRaises(ValueError):contract.check_models(bad)
    def test_case_version_and_adapter_refusal(self):
        c=json.loads((Path(contract.__file__).resolve().parents[2]/'cases/option-chain-greeks.json').read_text())
        self.assertEqual(c['version'],5)                 # Task A4 (I2.2, alo_scheme): version 2; Task A6 (I7.2, H21, ruling R-A3): the five-model panel, version 3; EX-3: version 4 (single-threaded variants only, owner C15); EX-10: version 5 (C rows, unit points)
        from benchlab.workload import load_case_adapter
        self.assertEqual(load_case_adapter(c,selector='alo').models,('alo',))

if __name__=='__main__':unittest.main()
