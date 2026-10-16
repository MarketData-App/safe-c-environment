"""bench-demo unit tests (run by the framework project unit suite in the bench container).

The reference (benchdemo.reference) keeps the definition of specs/project/bd_digest.md: k = 0 anchors, the seed-0
mapping, one hand-computed step, the FNV-1a fold and every request bound (zero, one, exact limits, one past). The C test
holds the generated vector block byte for byte. The adapter result is deterministic and equals the reference, the bounds
of the dataset are kept, a changed value is a mismatch, and the declared checks pass and refuse arguments or an unknown
name. The assertions of the former BLAKE2b demo-digest tests are all kept (FR6 N1)."""
import contextlib, functools, hashlib, io, json, struct, tempfile, unittest
from pathlib import Path
from benchlab.workload import load_case_adapter, load_adapter
from benchdemo import checks, reference as r, vectors
C_TEST=Path(__file__).resolve().parents[4]/'tests'/'project'/'test_bd_digest.c'
C_KERNEL=Path(__file__).resolve().parents[4]/'src'/'bd_kernel.c'

@functools.lru_cache(maxsize=1)
def block():return vectors.c_block()

def record(seed,steps):return r.encode_request([(seed,steps)])

def status(request):
    with unittest.TestCase().assertRaises(ValueError) as caught:r.check_request(request)
    return str(caught.exception)

class ReferenceTests(unittest.TestCase):
    def test_zero_steps_keep_the_offset_basis_and_the_seed(self):
        self.assertEqual(r.digest_record(0,0),(0xcbf29ce484222325,0x9E3779B97F4A7C15))     # seed 0 maps to the constant
        self.assertEqual(r.digest_record(1,0),(0xcbf29ce484222325,1))
        self.assertEqual(r.digest_record(r.MASK,0),(0xcbf29ce484222325,r.MASK))
        self.assertEqual(r.digest_record(0,5),r.digest_record(r.ZERO_SEED,5))
    def test_one_step_from_seed_one_is_the_hand_computed_value(self):
        # x = 1: x ^= x << 13 -> 0x2001; x ^= x >> 7 -> 0x2041; x ^= x << 17 -> 0x40822041
        self.assertEqual(r.digest_record(1,1),(r.fnv1a(struct.pack('<Q',0x40822041)),0x40822041))
    def test_each_step_folds_eight_little_endian_bytes(self):
        h,x=r.digest_record(3,2);_,x1=r.digest_record(3,1)
        self.assertEqual(h,r.fnv1a(struct.pack('<QQ',x1,x)))
    def test_the_shifts_wrap_modulo_two_to_the_64(self):
        _,x=r.digest_record(r.MASK,1);self.assertLessEqual(x,r.MASK);self.assertGreaterEqual(x,0)
    def test_digest_record_refuses_values_outside_the_domain(self):
        for seed,steps in ((-1,0),(r.MASK+1,0),(1,-1),(1,r.STEPS_MAX+1),(True,0),(1,1.0)):
            with self.subTest(seed=seed,steps=steps),self.assertRaises(ValueError):r.digest_record(seed,steps)
        self.assertEqual(len(r.digest_record(1,r.STEPS_MAX)),2)

class RequestTests(unittest.TestCase):
    def test_counts_and_the_exact_limits(self):
        self.assertEqual(r.check_request(record(1,0)),1)
        self.assertEqual(r.check_request(record(0,r.STEPS_MAX)),1)
        self.assertEqual(r.check_request(record(1,0)*r.RECORDS_MAX),r.RECORDS_MAX)
        self.assertEqual(r.check_request(bytearray(record(2,3))),1)
    def test_refusals_name_the_c_status_in_order(self):
        one=record(1,0)
        for request,want in ((b'','BD_EMPTY_REQUEST'),(one[:1],'BD_PARTIAL_RECORD'),(one[:-1],'BD_PARTIAL_RECORD'),(one+b'\0','BD_PARTIAL_RECORD'),
                             (one*(r.RECORDS_MAX+1),'BD_TOO_MANY_RECORDS'),(one*r.RECORDS_MAX+b'\0','BD_TOO_MANY_RECORDS'),
                             (record(1,r.STEPS_MAX+1),'BD_STEPS_TOO_LARGE'),(record(1,0xFFFFFFFF),'BD_STEPS_TOO_LARGE'),
                             (one+record(1,r.STEPS_MAX+1),'BD_STEPS_TOO_LARGE'),(record(1,r.STEPS_MAX+1)+b'\0','BD_PARTIAL_RECORD'),
                             (None,'BD_NULL_ARGUMENT'),('text','BD_NULL_ARGUMENT')):
            with self.subTest(length=len(request) if request is not None else None,want=want):self.assertEqual(status(request),want)
    def test_output_is_sixteen_little_endian_bytes_per_record(self):
        request=r.encode_request([(0,0),(1,1),(r.MASK,3)]);out=r.digest_request(request)
        self.assertEqual(len(out),3*r.RECORD_OUT)
        for i,(seed,steps) in enumerate(((0,0),(1,1),(r.MASK,3))):
            with self.subTest(record=i):self.assertEqual(struct.unpack_from('<QQ',out,i*16),r.digest_record(seed,steps))
        with self.assertRaises(ValueError):r.digest_request(b'')
    def test_the_record_layout_is_seed_then_steps_little_endian(self):
        self.assertEqual(record(0x0102030405060708,0x0A0B0C0D),bytes([8,7,6,5,4,3,2,1,0x0D,0x0C,0x0B,0x0A]))

class VectorTests(unittest.TestCase):
    def test_the_c_test_holds_the_generated_block_byte_for_byte(self):
        self.assertTrue(C_TEST.is_file(),'tests/project/test_bd_digest.c is missing')
        self.assertEqual(vectors.extract_block(C_TEST.read_text()),block())
    def test_the_kernel_self_check_holds_the_generated_rows(self):
        """FR6 N2: bd-kernel --self-check runs the rows of src/bd_kernel.c; they are the generated rows, in order."""
        self.assertTrue(C_KERNEL.is_file(),'src/bd_kernel.c is missing')
        rows=lambda text:[x for x in text.splitlines() if x.startswith('    {0x')]
        self.assertEqual(rows(C_KERNEL.read_text()),rows(block()))
        self.assertEqual(len(rows(block())),len(vectors.RECORDS))
    def test_the_block_has_one_row_per_vector_and_the_named_boundaries(self):
        b=block();self.assertEqual(b.count('\n    {0x'),len(vectors.RECORDS))
        steps={k for _,k in vectors.RECORDS};seeds={s for s,_ in vectors.RECORDS}
        self.assertTrue({0,1,r.STEPS_MAX-1,r.STEPS_MAX}<=steps);self.assertTrue({0,1,r.ZERO_SEED,r.MASK}<=seeds)
    def test_the_max_request_has_exactly_the_limit_and_starts_at_seed_zero(self):
        req=vectors.max_request();self.assertEqual(r.check_request(req),r.RECORDS_MAX)
        self.assertEqual(struct.unpack_from('<QI',req,0),(0,0));self.assertEqual(struct.unpack_from('<QI',req,12*32),((32*r.ZERO_SEED)&r.MASK,1))
    def test_extract_block_refuses_a_missing_or_doubled_block(self):
        for text in ('',vectors.BEGIN,block()+block(),vectors.END+vectors.BEGIN):
            with self.subTest(n=len(text)),self.assertRaises(ValueError):vectors.extract_block(text)

class DemoDigestTests(unittest.TestCase):
    def setUp(self):self.a=load_case_adapter(checks.load_case())
    def result(self,data,variant='py-reference',adapter=None):
        a=adapter or self.a
        return a.materialize(a.run(a.prepare(data,variant,1),variant,1))
    def test_result_is_deterministic_and_equals_the_reference(self):
        data=checks.synthetic(self.a,4);first=self.result(data)
        self.assertEqual(first,self.result(data));self.assertEqual(first,self.result(data,'py-optimized'))
        self.assertEqual(self.a.work_units(first),4);self.assertTrue(self.a.validate(first,self.a.reference(data),data)['eligible'])
        self.assertEqual(len(set(first['values'])),4)                  # distinct seeds give distinct digests
        self.assertTrue(all(len(v)==32 for v in first['values']))      # 16 output bytes in hex
        self.assertEqual(bytes.fromhex(''.join(first['values'])),r.digest_request(data))
    def test_zero_and_one_row(self):
        for rows in (0,1):
            with self.subTest(rows=rows):
                data=checks.synthetic(self.a,rows);self.assertEqual(self.a.work_units(self.result(data)),rows)
    def test_more_records_than_one_request_are_split_at_the_limit(self):
        a=load_adapter('benchdemo.adapter:DemoDigest',{'steps':0,'seed':1})
        data=checks.synthetic(a,r.RECORDS_MAX+1);prepared=a.prepare(data,'py-reference')
        self.assertEqual([len(p)//r.RECORD_IN for p in prepared],[r.RECORDS_MAX,1])
        self.assertEqual(a.work_units(self.result(data,adapter=a)),r.RECORDS_MAX+1)
    def test_slice_bounds(self):
        data=checks.synthetic(self.a,3)
        self.assertEqual(self.a.slice(data,3),data);self.assertEqual(self.a.slice(data,0),b'')
        for n in (-1,4):
            with self.subTest(n=n),self.assertRaises(ValueError):self.a.slice(data,n)
    def test_negative_rows_are_refused(self):
        with self.assertRaises(ValueError):self.a.synthesize(-1,checks.SEED)
    def test_invalid_steps_parameters_are_refused(self):
        for steps in (-1,r.STEPS_MAX+1,'64',None):
            with self.subTest(steps=steps),self.assertRaises(ValueError):load_adapter('benchdemo.adapter:DemoDigest',{'steps':steps,'seed':1})
    def test_a_changed_value_is_a_mismatch(self):
        data=checks.synthetic(self.a,2);ref=self.a.reference(data);bad={'values':[ref['values'][0],'0'*32]}
        v=self.a.validate(bad,ref,data);self.assertEqual((v['eligible'],v['reduction']),(False,'MISMATCH'))
        v=self.a.validate({'values':ref['values'][:1]},ref,data);self.assertEqual((v['eligible'],v['reduction']),(False,'ROW_COUNT'))
    def test_a_control_or_malformed_dataset_is_refused(self):
        good=self.a.synthesize(1,1)
        for data in (b'{"kind":"spin","seeds":[1]}',good[8:],good[:-1],b'bd-demo\x01'+record(1,r.STEPS_MAX+1)):
            with tempfile.TemporaryDirectory() as t:
                p=Path(t)/'d.bin';p.write_bytes(data)
                with self.subTest(n=len(data)),self.assertRaises(ValueError):self.a.load({'path':str(p),'sha256':hashlib.sha256(data).hexdigest()})

class CheckTests(unittest.TestCase):
    def test_agreement_passes_and_refuses_arguments(self):
        with tempfile.TemporaryDirectory() as t:
            row=checks.agreement(Path(t),[])
            self.assertEqual((row['status'],row['counts']['mismatched_variants'],row['counts']['rows']),('PASS',0,checks.ROWS))
            self.assertEqual(row['counts']['failed_anchors'],0)
            self.assertEqual(checks.agreement(Path(t),['x'])['status'],'FAIL')
    def test_vectors_writes_the_block_and_refuses_arguments(self):
        with tempfile.TemporaryDirectory() as t:
            row=checks.generate_vectors(Path(t),[])
            self.assertEqual((row['status'],row['files']),('PASS',[checks.VECTOR_FILE]))
            self.assertEqual((Path(t)/checks.VECTOR_FILE).read_text(),block())
            self.assertEqual(checks.generate_vectors(Path(t),['x'])['status'],'FAIL')
    def test_main_prints_one_row_and_refuses_an_unknown_check(self):
        with tempfile.TemporaryDirectory() as t:
            for argv,code,state in ((['m','demo-agreement',t],0,'PASS'),(['m','nope',t],2,'FAIL'),(['m'],2,'FAIL')):
                out=io.StringIO()
                with self.subTest(argv=argv[1:2]):
                    with contextlib.redirect_stdout(out):self.assertEqual(checks.main(argv),code)
                    self.assertEqual(json.loads(out.getvalue().strip().splitlines()[-1])['status'],state)

if __name__=='__main__':unittest.main()
