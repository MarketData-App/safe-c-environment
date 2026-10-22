"""Task DD (DD1; finding P3-T15-CHILD-BUDGET-01, ruling D1-R2(b)): b06-prerequisite-oracle saves the shared QuantLib
comparison (lattice, BAW grid/record/edge, ALO) with its binding; quantlib-alignment reuses it only on an exact binding
match and recomputes otherwise. The verdict, the counts and alignment.json are the same with and without the saved copy,
on a passing and on a failing comparison. The part functions are deterministic stand-ins here: the full-domain comparison
itself stays proven by the two before-run checks in the same ci."""
import dataclasses, json, shutil, tempfile, unittest
from pathlib import Path
from unittest import mock
import QuantLib as ql
from optionlab import checks, oracle
from optionlab.params import CASE
from optionlab import protocol
FIX=protocol.oracle()
PARTS=list(checks.QL_EVIDENCE_PARTS)

def fakes(fail=False):
    """Stand-ins for the five part functions and for quantlib-alignment's own part; `calls` records each part computed."""
    calls=[];tol={k:0.0 for k in checks.ALIGN_TOL}
    def lattice(fx,params,on_point=None):calls.append('lattice');return {'sigma<=1|T<=7d':True,'sigma>1|T>1y':not fail},1e-12,40
    def baw_alignment(params,grid=None,on_field=None):
        calls.append('baw_alignment')
        return {'rows':324,'raised':2,'flags_differ':0,'max_rel':dict(tol),'fraction_of_tolerance':dict(tol),'bit_equal':{k:322 for k in tol},
                'iv':{'rows':10,'equal':10,'ok':9,'max_iv_abs':0.0,'root_bit_equal':9,'max_evaluations':12},'failures':[]}
    def baw_record_grid(params,on_point=None):
        calls.append('baw_record_grid');return {'points':100,'admitted':80,'excluded':10,'european':10,'bit_equal':90,'both_raise':0,'excluded_ql_raises':10,'mismatch':int(fail)}
    def baw_edge(fx,params,on_row=None):calls.append('baw_edge_rows');return {'rows':5,'bit_equal_rows':5,'failures':[]}
    def alo(fx,params):
        calls.append('alo')
        return (not fail),{'grid':{'status':'PASS','rows':324,'mismatches':0,'failures':[]},'record_grid':{'points':50,'grid':7,'bit_equal':50,'both_raise':0,'mismatch':0},
                           'switch_vectors':{'vectors':28,'equation_equal':28,'transcription_bit_equal':28},'edge_rows':{'rows':3,'bit_equal_rows':3,'failures':[]}}
    grid={m:{'max_rel':dict(tol),'fraction_of_tolerance':dict(tol),'iv':{'rows':3,'equal':3,'ok':3,'max_iv_abs':0.0,'max_evaluations':9}} for m in ('bsm','bjs','crr')}
    patches=[mock.patch.object(checks,'lattice_agreement',lattice),mock.patch.object(checks,'baw_alignment',baw_alignment),
             mock.patch.object(checks,'baw_record_grid',baw_record_grid),mock.patch.object(checks,'baw_edge_agreement',baw_edge),
             mock.patch.object(checks,'alo_quantlib_evidence',alo),mock.patch.object(checks,'_alignment_grid',lambda params:json.loads(json.dumps(grid))),
             mock.patch.object(checks,'_alignment_chain',lambda params:{'rows':12,'seed':checks.ALIGN_SEED,'compare':{'eligible':True}}),
             mock.patch.object(oracle,'crr_accuracy',lambda fx,params,agreement=None:{'bands':len(agreement)})]
    return calls,patches

class Patched:
    def __init__(self,patches):self.patches=patches
    def __enter__(self):
        for p in self.patches:p.start()
    def __exit__(self,*exc):
        for p in reversed(self.patches):p.stop()

def alignment(session_dir):
    """quantlib-alignment with output directory <session_dir>/out (the check's shared files are under <session_dir>/shared)."""
    out=Path(session_dir)/'out';out.mkdir(parents=True,exist_ok=True)
    row=checks.CHECKS['quantlib-alignment'](out,[])
    return row,json.loads((out/'alignment.json').read_text())

def place(session_dir,doc):
    """The framework's restore: the producer's file at bench/shared/<producer>/<file> next to the consumer's output."""
    target=Path(session_dir)/'shared'/checks.QL_EVIDENCE_PRODUCER/checks.QL_EVIDENCE_FILE;target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(doc if isinstance(doc,str) else json.dumps(doc));return target

class QuantLibEvidenceTests(unittest.TestCase):
    def produce(self,fail=False):
        """b06-prerequisite-oracle with stand-ins: items 1-8 stubbed, item 9 fills the evidence through quantlib_evidence."""
        calls,patches=fakes(fail);out=Path(tempfile.mkdtemp())/'out';out.mkdir()
        items={str(i):{'status':'PASS','checked':1,'failures':[]} for i in range(1,9)}
        def item9(fx,params,evidence=None):
            checks.quantlib_evidence(fx,params,doc=evidence);return {'status':'PASS','checked':3,'failures':[],'parts':{}}
        with Patched(patches),mock.patch.object(oracle,'run_all',lambda fx,params:dict(items)),mock.patch.object(checks,'quantlib_agreement_item',item9),\
             mock.patch.object(checks,'_edge_erf_saturated',lambda fx,params:{}):
            row=checks.CHECKS['b06-prerequisite-oracle'](out,[])
        return row,out,calls
    def test_the_producer_saves_the_complete_comparison_with_its_binding(self):
        row,out,calls=self.produce()
        self.assertEqual(row['files'],['oracle-check.json',checks.QL_EVIDENCE_FILE]);self.assertEqual(calls,PARTS)
        doc=json.loads((out/checks.QL_EVIDENCE_FILE).read_text())
        self.assertEqual(doc['binding'],checks.quantlib_binding(FIX,CASE));self.assertEqual(sorted(doc['evidence']),sorted(PARTS))
        b=doc['binding']
        self.assertEqual((b['params']['alo_scheme'],b['quantlib_version'],b['parts']),(CASE.alo_scheme,ql.__version__,PARTS))
        self.assertEqual(len(row['counts']),19)                          # the check's counts are unchanged (ruling T28-C1)
    def test_an_incomplete_comparison_is_not_saved(self):
        items={str(i):{'status':'PASS','checked':1,'failures':[]} for i in range(1,9)};out=Path(tempfile.mkdtemp())
        with mock.patch.object(oracle,'run_all',lambda fx,params:dict(items)),mock.patch.object(checks,'_edge_erf_saturated',lambda fx,params:{}),\
             mock.patch.object(checks,'quantlib_agreement_item',lambda fx,params,evidence=None:evidence.update(lattice=[{},0.0,0]) or {'status':'PASS','checked':1,'failures':[]}):
            row=checks.CHECKS['b06-prerequisite-oracle'](out,[])
        self.assertEqual(row['files'],['oracle-check.json']);self.assertFalse((out/checks.QL_EVIDENCE_FILE).exists())
    def test_reuse_gives_the_same_verdict_counts_and_document(self):
        for fail,status in ((False,'PASS'),(True,'FAIL')):
            with self.subTest(fail=fail):
                _,out,_=self.produce(fail)
                calls,patches=fakes(fail)
                with Patched(patches):
                    alone_row,alone=alignment(tempfile.mkdtemp());alone_calls=list(calls);calls.clear()
                    session=tempfile.mkdtemp();place(session,(out/checks.QL_EVIDENCE_FILE).read_text())
                    reused_row,reused=alignment(session)
                self.assertEqual((alone_calls,calls),(PARTS,[]))         # without the copy every part is computed; with it none
                self.assertEqual((alone_row['status'],reused_row['status']),(status,status))
                self.assertEqual(alone_row['counts'],reused_row['counts'])
                self.assertEqual((alone.pop('quantlib_evidence'),reused.pop('quantlib_evidence')),
                                 ({'source':'computed','reason':'absent'},{'source':'reused','reason':'reused'}))
                self.assertEqual(alone,reused)
    def test_any_binding_mismatch_forces_recomputation(self):
        _,out,_=self.produce();good=json.loads((out/checks.QL_EVIDENCE_FILE).read_text())
        edits={'fixture':lambda b:b.update(fixture_sha256='0'*64),'parameter':lambda b:b['params'].update(h_r=2e-4),
               'alo_scheme':lambda b:b['params']['alo_scheme'].update(eps=1e-9),'source':lambda b:b.update(source_sha256='0'*64),
               'quantlib_version':lambda b:b.update(quantlib_version='1.44'),'schema':lambda b:b.update(schema_version=2),
               'parts':lambda b:b.update(parts=PARTS[:-1]),'extra key':lambda b:b.update(note='x')}
        calls,patches=fakes()
        with Patched(patches):
            want_row,want=alignment(tempfile.mkdtemp());want.pop('quantlib_evidence');calls.clear()
            cases=[(name,json.loads(json.dumps(good)),edit) for name,edit in edits.items()]
            for name,doc,edit in cases:
                edit(doc['binding'])
                with self.subTest(binding=name):
                    row,got=alignment(place(tempfile.mkdtemp(),doc).parents[2])
                    self.assertEqual(calls,PARTS);calls.clear()
                    self.assertEqual(got.pop('quantlib_evidence'),{'source':'computed','reason':'binding mismatch'})
                    self.assertEqual((row['status'],row['counts'],got),(want_row['status'],want_row['counts'],want))
            missing=dict(good,evidence={k:v for k,v in good['evidence'].items() if k!='alo'})
            for name,doc,reason in (('unreadable','{not json','unreadable'),('incomplete',missing,'incomplete'),('no binding',{'evidence':good['evidence']},'binding mismatch')):
                with self.subTest(file=name):
                    row,got=alignment(place(tempfile.mkdtemp(),doc).parents[2])
                    self.assertEqual(calls,PARTS);calls.clear()
                    self.assertEqual(got['quantlib_evidence'],{'source':'computed','reason':reason});self.assertEqual(row['status'],want_row['status'])
    def test_the_binding_follows_every_input(self):
        base=checks.quantlib_binding(FIX,CASE);self.assertEqual(checks.quantlib_binding(json.loads(json.dumps(FIX)),CASE),base)
        fx=json.loads(json.dumps(FIX));fx['oracle']['lattice'][0]['euro']['400']+=1e-6
        self.assertNotEqual(checks.quantlib_binding(fx,CASE)['fixture_sha256'],base['fixture_sha256'])
        for field,value in (('h_r',2e-4),('rate',0.05),('baw_newton_max',39),('alo_scheme',dict(CASE.alo_scheme,eps=1e-9)),('alo_plant_nan','x')):
            with self.subTest(param=field):self.assertNotEqual(checks.quantlib_binding(FIX,dataclasses.replace(CASE,**{field:value}))['params'],base['params'])
        with mock.patch.object(ql,'__version__','1.44'):self.assertEqual(checks.quantlib_binding(FIX,CASE)['quantlib_version'],'1.44')
        pkg=Path(checks.__file__).resolve().parent;copy=Path(tempfile.mkdtemp())/'optionlab'
        shutil.copytree(pkg,copy,ignore=shutil.ignore_patterns('__pycache__'))
        with mock.patch.object(checks,'__file__',str(copy/'checks.py')):
            self.assertEqual(checks.quantlib_binding(FIX,CASE)['source_sha256'],base['source_sha256'])   # the digest is the content
            (copy/'alo.py').write_bytes((copy/'alo.py').read_bytes()+b'\n')
            self.assertNotEqual(checks.quantlib_binding(FIX,CASE)['source_sha256'],base['source_sha256'])
    def test_a_lone_check_has_no_saved_copy(self):
        self.assertEqual(checks.shared_quantlib_evidence(Path(tempfile.mkdtemp())/'out',FIX,CASE),(None,'absent'))

if __name__=='__main__':unittest.main()
