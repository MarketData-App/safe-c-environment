"""EX-14 (T22; Phase 2 Task 23 example part, case B06): the light tests of the agreement controls of the option example,
without a native binary. The framework job agreement-controls (container/bench_phase2_job.py AGREEMENT_CODE; the cases suite
runs it on the real C rows) takes the C result of the case adapter (selector all) on 64 synthetic rows of the run seed,
applies the generic mutations of benchlab.agreement and each protocol `agreement_mutations` entry through the adapter hook
agreement_mutation(name, result, data), and requires (tools/bench_phase2.check_agreement_controls): the unmutated C result is
eligible; each mutated result has another adapter digest and the adapter's validate refuses it. `job` below runs the same
steps in the same order on a C result without a binary: the 290-byte response records of the py-reference result
(C = py-reference byte for byte, native-agreement) decoded by the adapter's own decoder (unpack_native).

T19R2 cause of B06 FAIL (cases run 2700434e): the generic precision-change changes every status text ('OK' becomes 'OJ'),
and the adapter digest (reference.canonical_result) raised ValueError for the unknown status, so the job child ended.
REQUIRE-style unittest assertions; no assert statement."""
import copy, hashlib, json, math, re, struct, sys, tempfile, unittest
from pathlib import Path
from benchlab import agreement as generic
from benchlab.trial import verdict_fields
from benchlab.workload import load_case_adapter
from optionlab import protocol
from optionlab import native_codec as nc
from optionlab.contract import FIELDS, MODELS5, STATUSES
from optionlab.reference import result_digest
from tests.test_light_native_codec import encode

CASES=Path(__file__).resolve().parents[2]/'cases'
ROWS=64;SEED=20261007           # tools/bench_phase2.AGREEMENT_ROWS rows; a smoke run plan has the case seed
HEX64=re.compile(r'^[0-9a-f]{64}$')
PROJECT_MUTATIONS=('wrong-model','not-requested-garbage','misplaced-flag')

def adapter(selector='all'):
    return load_case_adapter(json.loads((CASES/'option-chain-greeks.json').read_text()),selector=selector)

def data_of(a,n,seed):
    d=a.synthesize(n,seed);p=Path(tempfile.mkdtemp())/'d';p.write_bytes(d)
    return a.load({'path':str(p),'sha256':hashlib.sha256(d).hexdigest()})

def c_result(a,data,reference=None):
    """The C result of the selector's models on `data` without a binary: the response records of py-reference (encode) decoded
    by the adapter (unpack_native: the record rule of the codec)."""
    return a.unpack_native(encode(a.selected(reference if reference is not None else a.reference(data)),a.native_mask()))

def bits(x):
    """`x` with every float replaced by the hex of its binary64 bits: exact equality, NaN included."""
    if isinstance(x,float):return 'f'+struct.pack('<d',x).hex()
    if isinstance(x,dict):return {k:bits(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)):return [bits(v) for v in x]
    return x

def raw(records,mask=7):return {'records':bytes(records),'n':len(records)//nc.RECORD_OUT,'mask':mask,'echo':False}

def job(a,d1,d2,extra):
    """The steps of AGREEMENT_CODE (container/bench_phase2_job.py) on c_result: the control, the generic mutations, then the
    project mutations through the hook, each with `changed` (another digest) and `eligible` (adapter.validate)."""
    ref=a.reference(d1);c1=c_result(a,d1,ref);c2=c_result(a,d2);base=a.digest(c1)
    def eligible(r):
        v=a.validate(r,ref,d1);return bool(v.get('eligible')) if isinstance(v,dict) else False
    doc={'control':{'eligible':eligible(c1),'result_sha256':base},'seeds':[base,a.digest(c2)],'mutations':{}}
    for name in generic.GENERIC:
        m=generic.apply(name,c1,units=a.work_units(c1),slice_result=a.slice_result,data=d1,other=c2)
        doc['mutations'][name]={'changed':m is not None and a.digest(m)!=base,'eligible':None if m is None else eligible(m)}
    hook=getattr(a,'agreement_mutation',None)
    for name in extra:
        m=hook(name,c1,d1) if callable(hook) else None
        doc['mutations'][name]={'changed':m is not None and a.digest(m)!=base,'eligible':None if m is None else eligible(m),'realized':callable(hook)}
    return doc

class AgreementControlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a=adapter();cls.d1=data_of(cls.a,ROWS,SEED);cls.d2=data_of(cls.a,ROWS,SEED+1)
        cls.ref=cls.a.reference(cls.d1);cls.c1=c_result(cls.a,cls.d1,cls.ref);cls.c2=c_result(cls.a,cls.d2)
        cls.base=cls.a.digest(cls.c1)
    def verdict(self,r):return self.a.validate(r,self.ref,self.d1)
    def test_the_control_is_the_reference_and_eligible(self):
        self.assertEqual(self.base,result_digest(self.a.selected(self.ref)))
        self.assertEqual(sorted(self.c1['models']),['bjs','bsm','crr']);self.assertEqual(self.c1['n'],ROWS)
        self.assertIs(self.verdict(self.c1)['eligible'],True)
        self.assertNotEqual(self.base,self.a.digest(self.c2))           # P16 reuse-answer control: two seeds, two digests
    def test_the_job_passes_on_the_c_result(self):
        """B06 as the cases suite checks it: every generic mutation and every protocol agreement_mutations entry changes the C
        result and is refused, and the unmutated C result is eligible (tools/bench_phase2.check_agreement_controls)."""
        sys.path.insert(0,'/src/tools');import bench_phase2
        extra=list(protocol.protocol().get('agreement_mutations',[]))
        doc=job(self.a,self.d1,self.d2,extra)
        self.assertEqual(bench_phase2.check_agreement_controls(doc,list(generic.GENERIC)+extra),[])
        self.assertEqual(sorted(doc['mutations']),sorted(list(generic.GENERIC)+extra))
        self.assertTrue(all(doc['mutations'][n]['realized'] for n in extra))
    def test_the_protocol_lists_the_project_mutations(self):
        self.assertEqual(protocol.protocol().get('agreement_mutations'),list(PROJECT_MUTATIONS))
    def test_a_mutated_status_text_gets_a_digest_and_is_refused(self):
        """precision-change: every status text changes in its last character ('OK' becomes 'OJ'). The digest is a value that
        differs from the control's (the canonical form refuses the text, so the adapter gives the refused-form digest), and
        validate refuses the result (the status rule of agreement.compare)."""
        m=generic.apply('precision-change',self.c1)
        self.assertIn('OJ',m['models']['bsm']['status'])
        d=self.a.digest(m);self.assertRegex(d,HEX64);self.assertNotEqual(d,self.base)
        v=self.verdict(m)
        self.assertIs(v['eligible'],False);self.assertEqual(v['reduction'],'MISMATCH')
        self.assertTrue(any(k.endswith('.status') for k in v['failures']))
    def test_an_unknown_status_in_a_real_result_stays_refused(self):
        """The real-run refusal. (1) A result with an unknown status text has the verdict of agreement.compare (a status
        failure, reduction MISMATCH, not eligible), and the trial note (benchlab.trial: verdict_fields, then the digest) is
        written as refused; (2) a C answer with an unknown status byte is refused by the codec before any result exists, and
        validate refuses that answer (failure `record`)."""
        r=copy.deepcopy(self.c1);i=r['models']['bsm']['status'].index('OK');r['models']['bsm']['status'][i]='OJ'
        v=self.verdict(r)
        self.assertEqual((v['eligible'],v['reduction'],v['failures'].get('bsm.status')),(False,'MISMATCH',1))
        self.assertIs(verdict_fields(v)['eligible'],False)
        d=self.a.digest(r);self.assertRegex(d,HEX64);self.assertNotEqual(d,self.base)
        records=bytearray(encode(self.c1,7));records[0]=len(STATUSES)          # the bsm status byte of record 0: code 9, no status
        with self.assertRaises(ValueError):self.a.unpack_native(bytes(records))
        v=self.verdict(raw(records))
        self.assertEqual((v['eligible'],v['failures']),(False,{'record':1}))
        self.assertIs(verdict_fields(v)['eligible'],False)
    def test_validate_decodes_a_raw_c_answer_with_the_record_rule(self):
        """A raw C answer (the run form of a backend: records, n, mask, echo) is decoded by the adapter's own decoder: the
        unmutated answer has the control's digest and is eligible; an answer of another mask is refused."""
        ok=raw(encode(self.c1,7))
        self.assertEqual(self.a.digest(ok),self.base);self.assertIs(self.verdict(ok)['eligible'],True)
        other=dict(ok,mask=15)
        self.assertEqual((self.verdict(other)['eligible'],self.verdict(other)['failures']),(False,{'record':1}))
        self.assertNotEqual(self.a.digest(other),self.base)
    def test_validate_refuses_a_result_that_the_canonical_form_refuses(self):
        """The digest no longer ends the trial for a value outside the canonical form, so validate refuses every such value
        that agreement.compare alone would accept (here a model part with a column outside the form)."""
        r=copy.deepcopy(self.c1);r['models']['bsm']['extra']=[0]*ROWS
        v=self.verdict(r)
        self.assertIs(v['eligible'],False);self.assertEqual(v['failures'].get('canonical'),1)
        d=self.a.digest(r);self.assertRegex(d,HEX64);self.assertNotEqual(d,self.base)
    def test_the_digest_of_a_canonical_result_is_unchanged(self):
        for res in (self.c1,self.c2,self.a.selected(self.ref)):
            self.assertEqual(self.a.digest(res),result_digest(res))
    def test_encode_records_is_the_inverse_of_the_decoder(self):
        self.assertEqual(nc.encode_records(self.c1,7),encode(self.c1,7))
        self.assertEqual(bits(self.a.unpack_native(nc.encode_records(self.c1,7))),bits(self.c1))
        with self.assertRaises(ValueError):nc.encode_records(self.c1,15)           # the result lacks the baw part of mask 15
        bad=copy.deepcopy(self.c1);bad['models']['bsm']['status'][0]='OJ'
        with self.assertRaises(ValueError):nc.encode_records(bad,7)

class ProjectMutationTests(unittest.TestCase):
    """The project mutations of the hook agreement_mutation (protocol agreement_mutations): each changes the C result and the
    adapter refuses it; the record-level mutations act on the response records and the codec's record rule refuses them."""
    @classmethod
    def setUpClass(cls):
        cls.a=adapter();cls.d1=data_of(cls.a,ROWS,SEED);cls.ref=cls.a.reference(cls.d1);cls.c1=c_result(cls.a,cls.d1,cls.ref)
        cls.base=cls.a.digest(cls.c1);cls.records=encode(cls.c1,7)
    def refused(self,a,m,ref,data,base):
        d=a.digest(m);self.assertRegex(d,HEX64);self.assertNotEqual(d,base)
        self.assertIs(a.validate(m,ref,data)['eligible'],False)
    def test_wrong_model_on_the_three_model_result(self):
        """wrong-model: the first selected part (bsm) holds the values of another selected model (bjs)."""
        m=self.a.agreement_mutation('wrong-model',self.c1,self.d1)
        self.assertEqual(bits(m['models']['bsm']),bits(self.c1['models']['bjs']))
        self.assertEqual(bits({k:m['models'][k] for k in ('bjs','crr')}),bits({k:self.c1['models'][k] for k in ('bjs','crr')}))
        self.assertNotEqual(bits(self.c1['models']['bsm']),bits(self.c1['models']['bjs']))
        self.refused(self.a,m,self.ref,self.d1,self.base)
    def test_wrong_model_on_a_per_model_result(self):
        """wrong-model on a per-model call (selector bjs): the bjs part holds the values of another model (bsm, py-reference
        of the same rows)."""
        one=adapter('bjs');ref=one.reference(self.d1);c=c_result(one,self.d1,ref)
        m=one.agreement_mutation('wrong-model',c,self.d1)
        self.assertEqual(list(m['models']),['bjs'])
        want={k:self.ref['models']['bsm'][k] for k in ('status','flags')+FIELDS}
        self.assertEqual(bits({k:m['models']['bjs'][k] for k in want}),bits(want))
        self.refused(one,m,ref,self.d1,one.digest(c))
    def test_not_requested_garbage(self):
        """not-requested-garbage: the first unselected part (baw) of record 0 holds a status (OK) instead of NOT_REQUESTED."""
        m=self.a.agreement_mutation('not-requested-garbage',self.c1,self.d1)
        self.assertEqual(sorted(m),['echo','mask','n','records']);self.assertEqual((m['n'],m['mask'],m['echo']),(ROWS,7,False))
        diff=[i for i,(x,y) in enumerate(zip(m['records'],self.records)) if x!=y]
        self.assertEqual(diff,[MODELS5.index('baw')]);self.assertEqual(m['records'][diff[0]],STATUSES.index('OK'))
        with self.assertRaises(ValueError):self.a.unpack_native(m['records'])
        self.assertEqual(self.a.validate(m,self.ref,self.d1)['failures'],{'record':1})
        self.refused(self.a,m,self.ref,self.d1,self.base)
    def test_misplaced_flag(self):
        """misplaced-flag (I5.3): bit 16 in the flag byte of the first selected part (bsm) of record 0, a byte where the rule
        forbids it."""
        m=self.a.agreement_mutation('misplaced-flag',self.c1,self.d1)
        diff=[i for i,(x,y) in enumerate(zip(m['records'],self.records)) if x!=y]
        at=len(MODELS5)+MODELS5.index('bsm')
        self.assertEqual(diff,[at]);self.assertEqual(m['records'][at],self.records[at]|16)
        with self.assertRaises(ValueError):self.a.unpack_native(m['records'])
        self.assertEqual(self.a.validate(m,self.ref,self.d1)['failures'],{'record':1})
        self.refused(self.a,m,self.ref,self.d1,self.base)
    def test_an_unknown_mutation_is_refused(self):
        with self.assertRaises(ValueError):self.a.agreement_mutation('no-such-mutation',self.c1,self.d1)

def one_row(result,i):
    """The one-row result of row i of `result` (every column of each model part)."""
    return {'n':1,'models':{m:{k:[v[i]] for k,v in col.items()} for m,col in result['models'].items()}}

def outside_the_form(result,i,m='bsm'):
    """[(name, a copy of `result` that reference.canonical_result refuses only at row i of part m)]: an infinity in an OK field,
    a float flag, a bool flag, a text in a numeric field; and the whole-result form: an extra column."""
    out=[]
    for name,key,value in (('infinity','price',math.inf),('negative-infinity','delta',-math.inf),('float-flag','flags',0.0),
                           ('bool-flag','flags',False),('text-value','gamma','0.5')):
        r=copy.deepcopy(result);r['models'][m][key][i]=value;out.append((name,r))
    r=copy.deepcopy(result);r['models'][m]['extra']=[0]*result['n'];out.append(('extra-column',r))
    return out

class PanelAndMemoryRefusalTests(unittest.TestCase):
    """EX-16 (T23; T22-A01, ruling R72). Since EX-14 the digest is total, so a result outside the canonical form no longer ends
    the panel trial (benchlab.trial run_panel) or the memory trial (benchlab.trial: work_units and digest only, no validate)
    with an exception. The refusal is restored in the adapter: row_status gives NON_CANONICAL, a text outside STATUSES, for a
    one-row result that reference.canonical_result refuses, so the panel status differs from every reference status and the
    panel row is not eligible; work_units counts only the rows that the canonical form accepts, so such a result never has
    the planned work (the host completeness rule P07, tools/bench.py check_completeness). An unknown status text stays the
    row_status, as before."""
    @classmethod
    def setUpClass(cls):
        cls.a=adapter();cls.d=data_of(cls.a,ROWS,SEED);cls.ref=cls.a.reference(cls.d);cls.c=c_result(cls.a,cls.d,cls.ref)
        cls.i=next(i for i in range(ROWS) if all(cls.c['models'][m]['status'][i]=='OK' for m in cls.a.models))
        cls.one=one_row(cls.c,cls.i)
    def test_row_status_refuses_a_one_row_result_outside_the_canonical_form(self):
        self.assertEqual(self.a.row_status(self.one),'OK')
        self.assertNotIn('NON_CANONICAL',STATUSES)
        for name,m in outside_the_form(self.one,0):
            with self.subTest(mutation=name):
                with self.assertRaises((ValueError,TypeError,OverflowError)):result_digest(m)
                self.assertEqual(self.a.row_status(m),'NON_CANONICAL')
                self.assertRegex(self.a.digest(m),HEX64)          # the digest stays total (B06)
    def test_an_unknown_status_text_stays_the_row_status(self):
        m=copy.deepcopy(self.one);m['models']['bjs']['status'][0]='OJ'
        self.assertEqual(self.a.row_status(m),'OJ')
        m['models']['bsm']['price'][0]=math.inf                         # the unknown text comes first; both are refused
        self.assertEqual(self.a.row_status(m),'OJ')
        m=copy.deepcopy(self.one);m['models']['crr']['status'][0]='NO_BID';m['models']['crr']['price'][0]=math.inf
        self.assertEqual(self.a.row_status(m),'NON_CANONICAL')          # a known status with a value outside the form
    def test_the_panel_row_of_a_result_outside_the_form_is_not_eligible(self):
        """benchlab.trial.run_panel with the case adapter's hooks (take, digest, row_status, work_units) and a call that gives
        the result: the canonical result is an eligible panel row with one unit; each result outside the form is not."""
        from benchlab.trial import run_panel
        a=self.a
        class Call:
            def __init__(self,result):self.result=result;self.bench_ref=a.bench_ref
            def take(self,data,i):return a.take(data,i)
            def prepare(self,sub,variant,workers):return sub
            def run(self,prepared,variant,workers,pool=None):return None
            def materialize(self,raw):return copy.deepcopy(self.result)
            def __getattr__(self,name):return getattr(a,name)
        note=run_panel(Call(self.one),self.d,'py-optimized','direct',None,False,[self.i],['cell-0'],['OK'],1,'all')
        self.assertEqual((note['eligible'],note['work_units'],note['panel_status_diff']),(True,1,[]))
        for name,m in outside_the_form(self.one,0):
            with self.subTest(mutation=name):
                note=run_panel(Call(m),self.d,'py-optimized','direct',None,False,[self.i],['cell-0'],['OK'],1,'all')
                self.assertIs(note['eligible'],False);self.assertEqual(note['detail'],'panel-status')
                self.assertEqual(note['panel_status_diff'][0]['status'],'NON_CANONICAL');self.assertEqual(note['work_units'],0)
    def test_work_units_count_only_the_rows_of_the_canonical_form(self):
        """The memory trial path: a full result with one row outside the form has one unit less than its rows; a model part
        with a column outside the form has no unit. A NaN in a field is in the form (null) and stays a unit, as do rows of
        a result whose columns all end early (dropped rows give fewer units, as before)."""
        self.assertEqual(self.a.work_units(self.c),ROWS)
        for name,m in outside_the_form(self.c,self.i):
            with self.subTest(mutation=name):
                self.assertEqual(self.a.work_units(m),0 if name=='extra-column' else ROWS-1)
                self.assertNotEqual(self.a.digest(m),self.a.digest(self.c))
        m=copy.deepcopy(self.c);m['models']['crr']['vega'][self.i]=math.nan
        self.assertEqual(self.a.work_units(m),ROWS)
        m=copy.deepcopy(self.c);m['models']['bsm']['status'][self.i]='OJ'
        self.assertEqual(self.a.work_units(m),ROWS-1)                  # an unknown status text was never a unit
        m=copy.deepcopy(self.c)
        for col in m['models'].values():
            for k in col:col[k]=col[k][:ROWS-3]
        self.assertEqual(self.a.work_units(m),ROWS-3)

if __name__=='__main__':unittest.main()
