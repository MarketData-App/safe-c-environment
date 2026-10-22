"""Amendment G1.7, G3.7, G4.3 and G5: the model constants, per-model py-reference runs, the projection identity, the
ocg-v1 / ocg-v1m digest forms and the engine_evals column. `baw` is priced by py-reference since G-BAW2 part A (Task 5)."""
import json, pathlib, unittest
from optionlab import contract, reference as ref
from optionlab.params import CASE

ROW=(0,100.0,100.0,0.25,4.9,5.1,0.04,0.012)
RAW={k:v['value'] for k,v in json.loads((pathlib.Path(__file__).resolve().parents[2]/'cases/option-chain-greeks.json').read_text())['parameters'].items()}

class SelectorTests(unittest.TestCase):
    def test_constants(self):
        self.assertEqual(contract.ALL_MODELS,('bsm','bjs','crr'));self.assertIs(contract.MODELS,contract.ALL_MODELS)
        self.assertEqual(contract.MODELS4,('bsm','bjs','crr','baw'))
    def test_selector_models(self):
        self.assertEqual(contract.selector_models('all'),contract.ALL_MODELS);self.assertEqual(contract.selector_models('crr'),('crr',))
        for bad in ('','x','BSM'):
            with self.assertRaises(ValueError):contract.selector_models(bad)
    def test_per_model_run_holds_only_its_model(self):
        r=ref.run([ROW],CASE,models=('bjs',));self.assertEqual(set(r['models']),{'bjs'})
    def test_projection_identity(self):
        full=ref.run([ROW],CASE);one=ref.run([ROW],CASE,models=('crr',))
        for k in ('status','flags','iv','price','delta','gamma','theta','vega','rho'):self.assertEqual(json.dumps(one['models']['crr'][k]),json.dumps(full['models']['crr'][k]))
    def test_digest_forms(self):
        full=ref.run([ROW],CASE);self.assertTrue(ref.canonical_result(full).startswith(b'{"digest_form":"ocg-v1",'))
        one=ref.run([ROW],CASE,models=('crr',));b=ref.canonical_result(one)
        self.assertTrue(b.startswith(b'{"digest_form":"ocg-v1m","mask":4,"models":{"crr":'));self.assertNotIn(b'engine_evals',b)
    def test_engine_evals_column(self):
        r=ref.run([ROW],CASE);self.assertTrue(all(isinstance(r['models'][m]['engine_evals'][0],int) and r['models'][m]['engine_evals'][0]>0 for m in contract.ALL_MODELS))
    def test_unknown_digest_keys(self):
        with self.assertRaises(ValueError):ref.canonical_result({'n':0,'models':{}})

class SelectorBoundaryTests(unittest.TestCase):
    """Added by the implementer: the refusals and bounds that the brief's interface states."""
    def test_baw_is_priced_by_every_python_variant(self):
        # G-BAW2 part A (Task 5) enabled baw for py-reference; part B (Task 6) for py-optimized, py-library
        self.assertEqual(contract.selector_models('baw'),('baw',));self.assertEqual(set(ref.run([ROW],CASE,models=('baw',))['models']),{'baw'})
        from optionlab.adapter import OptionChainGreeks
        a=OptionChainGreeks(RAW,selector='baw');self.assertEqual(a.models,('baw',))
        chain={'n':1,'side':[0],'S':[100.0],'K':[100.0],'T':[0.25],'bid':[4.9],'ask':[5.1],'r':[0.04],'q':[0.012]}
        res=a.materialize(a.run(a.prepare(chain,'py-optimized'),'py-optimized',1));self.assertEqual(set(res['models']),{'baw'})
        self.assertEqual(res['models']['baw']['status'],ref.run([ROW],CASE,models=('baw',))['models']['baw']['status'])
        for bad in ('','x','BSM',None,3):
            with self.subTest(selector=bad):
                with self.assertRaises(ValueError):OptionChainGreeks(RAW,selector=bad)
        self.assertEqual(OptionChainGreeks(RAW,selector='crr').models,('crr',));self.assertEqual(OptionChainGreeks(RAW).models,contract.ALL_MODELS)
    def test_model_lists_are_refused_when_empty_unknown_or_repeated(self):
        for bad in ((),('x',),('bsm','bsm'),'bsm',('bsm',None)):
            with self.subTest(models=bad):
                with self.assertRaises(ValueError):ref.run([ROW],CASE,models=bad)
    def test_each_single_model_run_equals_its_all_models_part(self):
        rows=[ROW,(1,100.0,110.0,1.0,11.0,11.4,0.04,0.012),(0,100.0,100.0,0.0,1.0,1.1,0.04,0.012)]
        full=ref.run(rows,CASE)
        for m in contract.ALL_MODELS:
            with self.subTest(model=m):
                one=ref.run(rows,CASE,models=(m,));self.assertEqual(json.dumps(one['models'][m]),json.dumps(full['models'][m]))
    def test_engine_evals_is_zero_for_a_row_stopped_before_the_engine(self):
        r=ref.run([(0,100.0,100.0,0.0,1.0,1.1,0.04,0.012)],CASE)
        self.assertEqual({m:r['models'][m]['engine_evals'] for m in contract.ALL_MODELS},{m:[0] for m in contract.ALL_MODELS})
    def test_evaluate_returns_the_count_and_evaluate3_the_old_triple(self):
        st,vals,flags,ev=ref.evaluate(ROW,'bsm',CASE);self.assertEqual(ref.evaluate3(ROW,'bsm',CASE),(st,vals,flags));self.assertGreater(ev,1)
        self.assertEqual(ref.run([ROW],CASE,models=('bsm',))['models']['bsm']['engine_evals'],[ev])
    def test_crr_count_includes_the_engine_greek_call_and_each_bump(self):
        """CRR: Brent evaluations + 1 engine greek call + 3 or 4 bump evaluations (vega forward or central, rho central)."""
        from unittest import mock
        calls=[]
        real=ref.model_price
        def counting(*a,**k):calls.append(1);return real(*a,**k)
        with mock.patch('optionlab.reference.model_price',counting):st,_,_,ev=ref.evaluate(ROW,'crr',CASE)
        self.assertEqual(st,'OK');self.assertEqual(ev,len(calls)+1)         # every model_price call plus the engine greek call
    def test_ocg_v1m_bytes_and_masks(self):
        one=ref.run([ROW],CASE,models=('bsm',));b=ref.canonical_result(one)
        self.assertTrue(b.startswith(b'{"digest_form":"ocg-v1m","mask":1,"models":{"bsm":{"delta":['));self.assertTrue(b.endswith(b',"n":1}'))
        two=ref.run([ROW],CASE,models=('crr','bsm'))
        self.assertTrue(ref.canonical_result(two).startswith(b'{"digest_form":"ocg-v1m","mask":5,"models":{"bsm":'))
        full=ref.run([ROW],CASE);self.assertNotIn(b'"mask"',ref.canonical_result(full))
        stripped={'n':1,'models':{m:{k:v for k,v in col.items() if k!='engine_evals'} for m,col in full['models'].items()}}
        self.assertEqual(ref.canonical_result(stripped),ref.canonical_result(full))     # engine_evals never enters the bytes
    def test_unknown_or_partial_model_keys_are_refused(self):
        full=ref.run([ROW],CASE)
        bad=[{'n':1,'models':{'xyz':full['models']['bsm']}},{'n':1,'models':{**full['models'],'baw2':full['models']['bsm']}}]
        for i,res in enumerate(bad):
            with self.subTest(case=i):
                with self.assertRaises(ValueError):ref.canonical_result(res)
        short=json.loads(json.dumps(full));short['models']['bsm']['engine_evals']=[]
        with self.assertRaises(ValueError):ref.canonical_result(short)

class ReviewFollowUpTests(unittest.TestCase):
    """Task 2 review Minors 2 and 6."""
    def test_local_summary_refuses_a_selector_that_the_protocol_units_do_not_declare(self):
        """EX-20 item 4 (plan Task 31): the Task 2 refusal stays only for a single-model selector that no unit of the protocol
        decision policies declares (here: the protocol with that model's units removed); it comes before any work (both
        arguments None). The declared selectors are tested in tests.test_local_summary.PerUnitLocalSummaryTests."""
        from unittest import mock
        from optionlab import protocol
        from optionlab.adapter import OptionChainGreeks
        real=protocol.protocol()
        for m in contract.MODELS5:
            other=json.loads(json.dumps(real))
            for pol in other['decision_policies'].values():pol['units']=[u for u in pol['units'] if u.split('/',1)[0]!=m]
            with self.subTest(selector=m),mock.patch.object(protocol,'protocol',lambda other=other:other):
                with self.assertRaisesRegex(ValueError,'Task 31'):OptionChainGreeks(RAW,selector=m).local_summary(None,None)
    def test_engine_evals_values_are_type_checked(self):
        full=ref.run([ROW],CASE)
        for bad in ([-1],[1.5],[True],['1'],[None],5,None,'1'):
            with self.subTest(engine_evals=bad):
                res=json.loads(json.dumps(full));res['models']['crr']['engine_evals']=bad
                with self.assertRaises(ValueError):ref.canonical_result(res)
        res=json.loads(json.dumps(full));res['models']['crr']['engine_evals']=[0]
        self.assertEqual(ref.canonical_result(res),ref.canonical_result(full))
