import json, sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import bench
from schema_check import validate
from evidence import GateError

class ReferenceCountTests(unittest.TestCase):
    def test_reference_exclusions_reach_the_run_record(self):
        run={};bench.copy_reference_counts({'reference_evals':{'m4':40},'reference_admit_excluded':{'row':2,'brent':1,'bump':0}},run)
        self.assertEqual(run,{'reference_evals':{'m4':40},'reference_admit_excluded':{'row':2,'brent':1,'bump':0}})
    def test_no_library_selector_means_the_key_is_absent(self):
        run={};bench.copy_reference_counts({'reference_evals':{'m3':40}},run);self.assertNotIn('reference_admit_excluded',run)
    def test_schema_is_closed(self):
        props=json.loads((ROOT/'schemas/bench-run.json').read_text())['properties']['reference_admit_excluded']
        self.assertFalse(props['additionalProperties']);self.assertEqual(sorted(props['required']),['brent','bump','row'])
    def test_overhead_reaches_the_run_record(self):
        run={};bench.copy_reference_counts({'reference_evals':{'m4':40},'reference_admit_excluded':{'row':0,'brent':0,'bump':0},'reference_overhead':{'library_overhead_ns_per_row':812.5}},run)
        self.assertEqual(run['reference_overhead'],{'library_overhead_ns_per_row':812.5})
    def test_no_overhead_without_a_library_selector(self):
        run={};bench.copy_reference_counts({'reference_evals':{'m3':1}},run);self.assertNotIn('reference_overhead',run)
    def test_malformed_overhead_is_never_copied(self):
        """Added by the implementer: a closed object with one number >= 0; anything else is a run reason."""
        for bad in ({},{'library_overhead_ns_per_row':-1.0},{'library_overhead_ns_per_row':True},{'library_overhead_ns_per_row':float('nan')},
                    {'library_overhead_ns_per_row':float('inf')},{'library_overhead_ns_per_row':1.0,'x':2.0},{'x':1.0},[1.0],'x'):
            with self.subTest(bad=bad):
                run={};why=bench.copy_reference_counts({'reference_overhead':bad},run)
                self.assertEqual(run,{});self.assertEqual(why,['reference job overhead is malformed'])
        run={};bench.copy_reference_counts({'reference_overhead':{'library_overhead_ns_per_row':0}},run);self.assertEqual(run,{'reference_overhead':{'library_overhead_ns_per_row':0}})
    def test_overhead_schema_is_closed(self):
        import jsonschema
        v=jsonschema.Draft202012Validator(json.loads((ROOT/'schemas/bench-run.json').read_text())['properties']['reference_overhead'])
        self.assertTrue(v.is_valid({'library_overhead_ns_per_row':812.5}));self.assertTrue(v.is_valid({'library_overhead_ns_per_row':0}))
        for bad in ({},{'library_overhead_ns_per_row':-0.5},{'library_overhead_ns_per_row':1.0,'x':1},{'library_overhead_ns_per_row':'1'}):
            with self.subTest(bad=bad):self.assertFalse(v.is_valid(bad))
    def test_coordinator_reads_the_overhead(self):
        import importlib.util, shutil, tempfile
        spec=importlib.util.spec_from_file_location('bc_ov',ROOT/'container/bench-coordinator.py');bc=importlib.util.module_from_spec(spec);spec.loader.exec_module(bc)
        d=Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,d,True);p=d/'reference.json.overhead'
        self.assertIsNone(bc.reference_overhead(p))
        p.write_text('{"library_overhead_ns_per_row": 812.5}');self.assertEqual(bc.reference_overhead(p),{'library_overhead_ns_per_row':812.5})
        for bad in ('[]','{}','{"library_overhead_ns_per_row": -1}','{"library_overhead_ns_per_row": true}','{"x": 1}','not json','{"library_overhead_ns_per_row": NaN}'):
            with self.subTest(bad=bad):
                p.write_text(bad)
                with self.assertRaises(ValueError):bc.reference_overhead(p)
        self.assertIn('reference_overhead',bc.REFERENCE_CODE);self.assertIn("'.overhead'",bc.REFERENCE_CODE)


class ReferenceCountBoundaryTests(unittest.TestCase):
    """Added by the implementer: malformed values are never copied, the schema bounds, and the coordinator reader."""
    def test_malformed_values_give_reasons_and_are_not_copied(self):
        for bad in ({},{'row':1,'brent':0},{'row':1,'brent':0,'bump':0,'x':0},{'row':-1,'brent':0,'bump':0},{'row':1.0,'brent':0,'bump':0},
                    {'row':True,'brent':0,'bump':0},['row'],'x',3):
            with self.subTest(bad=bad):
                run={};why=bench.copy_reference_counts({'reference_admit_excluded':bad},run)
                self.assertEqual(run,{});self.assertEqual(why,['reference job exclusion counts are malformed'])
        run={};why=bench.copy_reference_counts({'reference_evals':{'BAD':1}},run);self.assertEqual((run,why),({},['reference job evaluation counts are malformed']))
        self.assertEqual(bench.copy_reference_counts(None,{}),[])
    def test_schema_accepts_and_rejects(self):
        import jsonschema
        schema=json.loads((ROOT/'schemas/bench-run.json').read_text())['properties']['reference_admit_excluded']
        v=jsonschema.Draft202012Validator(schema);self.assertTrue(v.is_valid({'row':0,'brent':0,'bump':123456789012}))
        for bad in ({'row':0,'brent':0},{'row':0,'brent':0,'bump':0,'x':1},{'row':-1,'brent':0,'bump':0},{'row':0.5,'brent':0,'bump':0}):
            with self.subTest(bad=bad):self.assertFalse(v.is_valid(bad))
    def test_coordinator_reads_the_reference_exclusion_counts(self):
        import importlib.util, shutil, tempfile
        spec=importlib.util.spec_from_file_location('bc_rc',ROOT/'container/bench-coordinator.py');bc=importlib.util.module_from_spec(spec);spec.loader.exec_module(bc)
        d=Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,d,True);p=d/'reference.json.admit'
        self.assertIsNone(bc.reference_admit_excluded(p))
        p.write_text('{"row": 2, "brent": 0, "bump": 1}');self.assertEqual(bc.reference_admit_excluded(p),{'row':2,'brent':0,'bump':1})
        for bad in ('[]','{}','{"row": 1, "brent": 0}','{"row": -1, "brent": 0, "bump": 0}','{"row": 1.0, "brent": 0, "bump": 0}','not json',
                    '{"row": 0, "brent": 0, "bump": 0, "x": 0}'):
            with self.subTest(bad=bad):
                p.write_text(bad)
                with self.assertRaises(ValueError):bc.reference_admit_excluded(p)
        self.assertIn("reference_exclusions",bc.REFERENCE_CODE);self.assertIn("'.admit'",bc.REFERENCE_CODE)

if __name__=='__main__':unittest.main()
