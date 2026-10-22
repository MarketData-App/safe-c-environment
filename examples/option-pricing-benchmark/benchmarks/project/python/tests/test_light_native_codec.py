"""EX-10 (T19): the light tests of the option codec (optionlab.native_codec), the native hooks of the option adapter, the
echo control (optionlab.echo_adapter) and the refusals of optionlab.backends that need no native binary. They run in the
example unit suite. The tests with the real pl-worker, pl-kernel and libpl_inproc.so are the declared check native-routes
(optionlab.native_check), which `bench check --check native-routes --native` runs (ruling R43 item b: the unit suite has no
--native). REQUIRE-style unittest assertions; no assert statement."""
import hashlib, json, math, struct, tempfile, unittest
from pathlib import Path
from benchlab.workload import load_case_adapter, request_limit
from optionlab import native_codec as nc
from optionlab.contract import FIELDS, MODELS5, STATUSES
CASES=Path(__file__).resolve().parents[2]/'cases'
# FNV-1a 64 of the 801 ocg-v1 bytes (mask 7) of optionlab.cvectors.canonical_case(), and of the empty mask-7 document;
# tests/project/test_canonical.c holds the same literals (the vectors that the C test and this test share, R43 item d).
SHARED_DIGEST=0xb15cff783c8bac90;SHARED_BYTES=801;EMPTY_DIGEST=0x528a621ba8b587ff
NAN=math.nan;NR=nc.NOT_REQUESTED

def R(st,fl,vals):return nc.RESPONSE_RECORD.pack(*st,*fl,*vals)

def encode(result,mask):
    """Test helper: the response records of a result for `mask` (unselected parts NOT_REQUESTED, the codec's inverse)."""
    out=bytearray()
    for i in range(result['n']):
        st=[];fl=[];vals=[]
        for k,m in enumerate(MODELS5):
            if mask>>k&1:
                col=result['models'][m];st.append(STATUSES.index(col['status'][i]));fl.append(col['flags'][i]);vals+=[col[f][i] for f in FIELDS]
            else:st.append(NR);fl.append(0);vals+=[NAN]*7
        out+=R(st,fl,vals)
    return bytes(out)

def adapter(case='option-chain-greeks',selector='all'):
    return load_case_adapter(json.loads((CASES/f'{case}.json').read_text()),selector=selector)

def dataset(a,n,seed=20261007):
    data=a.synthesize(n,seed);p=Path(tempfile.mkdtemp())/'chain.json';p.write_bytes(data)
    return {'path':str(p),'sha256':hashlib.sha256(data).hexdigest()}

def chain(n=3):
    return {'n':n,'side':[0,1,-1][:n],'S':[600.0]*n,'K':[590.0,610.0,600.0][:n],'T':[0.1]*n,'bid':[12.0]*n,'ask':[12.4]*n,'r':[0.04]*n,'q':[0.012]*n}

class CodecTests(unittest.TestCase):
    def test_pack_and_side_values(self):
        data=nc.pack_requests(chain());self.assertEqual(len(data),3*64)
        self.assertEqual([struct.unpack_from('<d',data,64*i)[0] for i in range(3)],[0.0,1.0,2.0])
        self.assertEqual(struct.unpack_from('<8d',data,64),(1.0,600.0,610.0,0.1,12.0,12.4,0.04,0.012))
        for key in ('r','q'):
            with self.subTest(missing=key),self.assertRaises(ValueError):nc.pack_requests({k:v for k,v in chain().items() if k!=key})
        with self.assertRaises(ValueError):nc.pack_requests(dict(chain(),K=[1.0]))           # a column of another length
        self.assertEqual(nc.pack_requests(chain(0)),b'')
    def test_columns_are_the_packed_values(self):
        cols=nc.columns(chain());packed=nc.pack_requests(chain())
        self.assertEqual(len(cols),8)
        for j,c in enumerate(cols):
            with self.subTest(column=j):
                self.assertEqual((str(c.dtype),c.shape,bool(c.flags['C_CONTIGUOUS'])),('float64',(3,),True))
                self.assertEqual(c.tolist(),[struct.unpack_from('<d',packed,64*i+8*j)[0] for i in range(3)])
    def test_materialize_and_reserved(self):
        rec=R((8,5,4,NR,NR),(0,9,0,0,0),[0.5]*7+[NAN]*28)
        res=nc.materialize(rec,1,7)
        self.assertEqual(sorted(res['models']),['bjs','bsm','crr']);self.assertEqual(res['n'],1)
        self.assertEqual((res['models']['bsm']['status'][0],res['models']['bjs']['status'][0],res['models']['bjs']['flags'][0]),('OK','BELOW_MIN',9))
        self.assertEqual(res['models']['bsm']['iv'],[0.5]);self.assertTrue(math.isnan(res['models']['crr']['rho'][0]))
        for bad,mask in ((R((9,5,4,NR,NR),(0,0,0,0,0),[0.0]*21+[NAN]*14),7),(R((8,5,4,NR,NR),(16,0,0,0,0),[0.0]*21+[NAN]*14),7),   # status 9; bit 16 outside baw/alo
                         (R((8,5,4,NR,NR),(0,128,0,0,0),[0.0]*21+[NAN]*14),7),(R((255,5,4,NR,NR),(0,0,0,0,0),[0.0]*21+[NAN]*14),7),   # bit 128; 255 without echo
                         (R((8,5,4,8,NR),(0,0,0,0,0),[0.0]*28+[NAN]*7),7),(R((8,5,4,NR,NR),(0,0,0,1,0),[0.0]*21+[NAN]*14),7),         # unselected status; flags
                         (R((8,5,4,NR,NR),(0,0,0,0,0),[0.0]*21+[NAN]*13+[0.0]),7),(R((8,5,4,NR,NR),(0,0,0,0,0),[0.0]*21+[-NAN]*14),7),  # unselected bits not exact
                         (R((8,5,4,NR,NR),(0,0,0,0,0),[0.0]*21+[NAN]*14),15),                                                 # a selected part with 254
                         (R((NR,NR,NR,NR,8),(0,0,0,0,64),[NAN]*28+[0.5]*7),16),(R((NR,NR,NR,NR,8),(0,0,0,0,0),[NAN]*28+[0.5]*7),24)):  # bit 64 in alo; baw 254
            with self.subTest(mask=mask),self.assertRaisesRegex(ValueError,'RESERVED_NONZERO'):nc.materialize(bad,1,mask)
        baw=nc.materialize(R((NR,NR,NR,4,NR),(0,0,0,112,0),[NAN]*35),1,8)                                     # flags 16|32|64 in baw only
        self.assertEqual((sorted(baw['models']),baw['models']['baw']['flags']),(['baw'],[112]))
        alo=nc.materialize(R((NR,NR,NR,NR,8),(0,0,0,0,48),[NAN]*28+[0.5]*7),1,16)                            # flags 16|32 valid in alo (I5.3)
        self.assertEqual((sorted(alo['models']),alo['models']['alo']['flags']),(['alo'],[48]))
        echo=nc.materialize(R((255,255,255,NR,NR),(0,0,0,0,0),[NAN]*35),1,7,echo=True)
        self.assertEqual(echo['models']['crr']['status'],['ECHO']);self.assertNotIn('baw',echo['models']);self.assertNotIn('alo',echo['models'])
        for bad in (R((255,255,8,NR,NR),(0,0,0,0,0),[NAN]*35),R((255,255,255,NR,NR),(1,0,0,0,0),[NAN]*35),R((255,255,255,NR,NR),(0,0,0,0,0),[0.0]+[NAN]*34)):
            with self.subTest(echo_record=bad[:10]),self.assertRaisesRegex(ValueError,'RESERVED_NONZERO'):nc.materialize(bad,1,7,echo=True)   # echo parts: 255, flags 0, NaN only
        with self.assertRaisesRegex(ValueError,'LENGTH_MISMATCH'):nc.materialize(rec+b'\0',1,7)
        with self.assertRaisesRegex(ValueError,'LENGTH_MISMATCH'):nc.materialize(rec,2,7)
        self.assertEqual(nc.materialize(b'',0,7),{'n':0,'models':{m:{'status':[],'flags':[],**{f:[] for f in FIELDS}} for m in ('bsm','bjs','crr')}})
    def test_round_trip_of_every_canonical_mask(self):
        """The records of cvectors.canonical_case (every flag kind, -0.0, NaN) decode to the same canonical bytes for every mask of
        cvectors.CANON_MASKS."""
        from optionlab import cvectors
        from optionlab.reference import canonical_result
        res=cvectors.canonical_case()
        for mask in cvectors.CANON_MASKS:
            with self.subTest(mask=mask):
                got=nc.materialize(encode(res,mask),2,mask)
                self.assertEqual(canonical_result(got),canonical_result(cvectors.subset(res,mask)))
    def test_masks(self):
        self.assertEqual((nc.mask_for('all'),nc.mask_for('baw'),nc.mask_of(('bsm','baw'))),(7,8,9))
        self.assertEqual((nc.mask_for('alo'),nc.mask_of(('bsm','alo')),nc.mask_of(('bsm','bjs','crr','baw','alo'))),(16,17,31))
        self.assertEqual((nc.models_of(7),nc.models_of(24)),(('bsm','bjs','crr'),('baw','alo')))
        for bad in ('ALL','hang',None,7):
            with self.subTest(selector=bad),self.assertRaises(ValueError):nc.mask_for(bad)
        for bad in ((),('bsm','bsm'),('xyz',),'bsm'):
            with self.subTest(models=bad),self.assertRaises(ValueError):nc.mask_of(bad)
        for bad in (0,32,-1,True,7.0):
            with self.subTest(mask=bad),self.assertRaises(ValueError):nc.models_of(bad)
    def test_parse_reduction(self):
        self.assertEqual(sorted(nc.parse_reduction('bsm:1,0,0,0,0,0,0,0,0:null:-1',1)),['bsm'])
        got=nc.parse_reduction('bsm:0,0,0,0,0,0,0,0,3:3fd0000000000000:2;crr:1,0,0,0,0,0,0,0,2:null:-1',5)
        self.assertEqual(got['bsm'],{'counts':[0,0,0,0,0,0,0,0,3],'max_iv_bits':'3fd0000000000000','max_iv_index':2})
        self.assertEqual(got['crr'],{'counts':[1,0,0,0,0,0,0,0,2],'max_iv_bits':None,'max_iv_index':-1})
        for text,mask in (('bsm:1,0,0,0,0,0,0,0,0:null:-1;crr:1,0,0,0,0,0,0,0,0:null:-1',1),     # a part of an unselected model
                          ('bsm:1,0,0,0,0,0,0,0,0:null:-1',3),                                      # a selected part missing
                          ('bjs:1,0,0,0,0,0,0,0,0:null:-1;bsm:1,0,0,0,0,0,0,0,0:null:-1',3),        # not MODELS5 order
                          (';'.join(['bsm:1,0,0,0,0,0,0,0,0:null:-1']*6),1),                        # more than five parts
                          ('bsm:1,0,0,0,0,0,0,0:null:-1',1),('bsm:1,0,0,0,0,0,0,0,0:NULL:-1',1),       # eight counts; not a hex or null
                          ('bsm:1,0,0,0,0,0,0,0,0:null:2',1),('bsm:1,0,0,0,0,0,0,0,0:3fd0000000000000:-1',1),('',1)):
            with self.subTest(text=text,mask=mask),self.assertRaises(ValueError):nc.parse_reduction(text,mask)
    def test_trailer_and_lengths(self):
        self.assertEqual(nc.response_length(14336,4),4157508);self.assertEqual(nc.response_length(0,2),4);self.assertEqual(nc.response_length(3,0),874)
        payload=b'\0'*(2*290)+struct.pack('<I',2)+struct.pack('<IIQ',1,0,10)+struct.pack('<IIQ',1,0,12)
        t=nc.trailer(payload,2,2);self.assertEqual((t['chunks'],t['chunk_sizes'],t['chunk_wall_ns'],t['chunk_rule']),(2,[1,1],[10,12],'one-per-worker'))
        self.assertEqual(nc.trailer(b'\0'*(3*290+4),3,0),{'chunk_rule':'direct','chunks':0,'chunk_sizes':[],'chunk_wall_ns':[]})
        for bad,n,threads in ((b'\0'*(3*290+3),3,0),(b'\0'*(3*290)+struct.pack('<I',1),3,0),                      # short; k 1 for threads 0
                              (b'\0'*(2*290)+struct.pack('<I',2)+struct.pack('<IIQ',1,0,10)+struct.pack('<IIQ',2,0,12),2,2),   # sizes sum to 3
                              (b'\0'*(2*290)+struct.pack('<I',2)+struct.pack('<IIQ',1,7,10)+struct.pack('<IIQ',1,0,12),2,2)):  # reserved u32
            with self.subTest(length=len(bad)),self.assertRaises(ValueError):nc.trailer(bad,n,threads)
    def test_the_option_specific_codec_values(self):
        """Ledger EXL-CODEC-ASSERT-01 (the option assertions that left the framework tests, FR6-N3-A04): the 16 ABI 2 argument
        types, the response length of 8 records with 2 chunks, the scratch length of 8 records and the shm regions at the policy
        request limit (the worker's region bounds)."""
        from optionlab import backends
        self.assertEqual(len(backends.INPROC_ARGTYPES),16)
        self.assertEqual((nc.response_length(8,2),backends.scratch_length(8)),(2356,136))
        self.assertEqual(backends.shm_region_sizes(request_limit()),(917504,4157508))
    def test_requests_follow_the_l2_split(self):
        self.assertEqual(nc.requests(14337,14336),[(0,14336),(14336,14337)])
        self.assertEqual(nc.requests(14336,request_limit()),[(0,14336)]);self.assertEqual(request_limit(),14336)   # the policy value (R43 item e)
        with self.assertRaises(TypeError):nc.requests(14337)                  # no default limit (I13.1, AI3-03)
    def test_fnv1a64_known_answers_and_the_shared_vector(self):
        from optionlab import cvectors
        from optionlab.reference import canonical_result
        self.assertEqual([nc.fnv1a64(x) for x in (b'',b'a',b'foobar')],[0xcbf29ce484222325,0xaf63dc4c8601ec8c,0x85944171f73967e8])
        text=canonical_result(cvectors.subset(cvectors.canonical_case(),7))
        self.assertEqual((len(text),nc.fnv1a64(text)),(SHARED_BYTES,SHARED_DIGEST))
        self.assertEqual(nc.canonical_digest(cvectors.subset(cvectors.canonical_case(),7)),'%016x'%SHARED_DIGEST)
        empty={'n':0,'models':{m:{'status':[],'flags':[],**{f:[] for f in FIELDS}} for m in ('bsm','bjs','crr')}}
        self.assertEqual(nc.fnv1a64(canonical_result(empty)),EMPTY_DIGEST)

class AdapterNativeHookTests(unittest.TestCase):
    def test_kernel_hooks_share_the_canonical_digest(self):
        """pack_native writes the 64-byte request records; unpack_native decodes the 290-byte records of the kernel output for
        the selector mask; native_reference_digest is FNV-1a 64 over the ocg-v1 or ocg-v1m bytes of the selected reference
        models (the value that pl-kernel prints as PLK1 digest=)."""
        from optionlab import cvectors
        a=adapter();res=cvectors.canonical_case()
        self.assertEqual(a.pack_native(chain()),nc.pack_requests(chain()))
        got=a.unpack_native(encode(res,7))
        self.assertEqual(a.native_reference_digest(res),'%016x'%SHARED_DIGEST)      # the reference holds five models; the selector all uses three
        self.assertEqual(nc.canonical_digest(got),a.native_reference_digest(res))
        with self.assertRaises(ValueError):a.unpack_native(encode(res,7)[:-1])
        one=adapter(selector='baw')
        self.assertEqual(one.native_reference_digest(res),nc.canonical_digest(cvectors.subset(res,8)))
        self.assertEqual(sorted(one.unpack_native(encode(res,8))['models']),['baw'])
    def test_a_c_row_needs_its_route_and_the_serial_variant(self):
        a=adapter();c=a.load(dataset(a,2))
        self.assertIsNone(a.route)
        with self.assertRaises(ValueError):a.prepare(c,'c-serial',1)          # no route: no fallback to a default route
        a.route='stdio';p=a.prepare(c,'c-serial',1)
        self.assertEqual((p['n'],p['route'],len(p['wire'])),(2,'stdio',128));self.assertNotIn('columns',p)
        a.route='inproc';p=a.prepare(c,'c-serial',1)
        self.assertEqual((p['route'],len(p['columns'])),('inproc',8));self.assertNotIn('wire',p)
        for variant in ('c-threads','c-pool'):
            with self.subTest(variant=variant),self.assertRaises(ValueError):a.prepare(c,variant,1)
        a.route='tcp'
        with self.assertRaises(ValueError):a.prepare(c,'c-serial',1)
    def test_take_and_row_status(self):
        """Base Task 18 (G7.3): take(data, i) is the one-row request of row i of the synthetic panel dataset (synthetic:large,
        the case seed). The loaded chain holds the row when it is long enough; a synthetic run dataset shorter than the row
        index takes the row from the prefix-stable generator (optionlab.synthetic.row); any other chain refuses the index."""
        from optionlab.synthetic import SIZES
        a=adapter();c=a.load(dataset(a,4))
        two=a.take(c,2);self.assertEqual(two['n'],1)
        self.assertEqual([two[k][0] for k in ('side','S','K','T','bid','ask','r','q')],[c[k][2] for k in ('side','S','K','T','bid','ask','r','q')])
        self.assertTrue(two['synthetic'])
        far=a.take(c,11798);big=a.load(dataset(a,3))       # row 11798: the first panel index of option-chain-greeks.panel.json
        from optionlab.synthetic import row
        from optionlab.contract import decode_chain_origin
        rec=row(11798,20261007,a.params);obj={'s':'ok',**{k:[v] for k,v in rec.items()}};want,syn=decode_chain_origin(json.dumps(obj).encode())
        self.assertTrue(syn);self.assertEqual([far[k][0] for k in ('side','S','K','T','bid','ask')],[want[k][0] for k in ('side','S','K','T','bid','ask')])
        self.assertEqual((far['r'][0],far['q'][0]),(a.params.rate,a.params.dividend_yield))
        self.assertIs(a.take(big,11798),a.take(big,11798))          # cached: no generator work inside a pass
        for bad in (-1,SIZES['large'],True,1.0):
            with self.subTest(index=bad),self.assertRaises(ValueError):a.take(c,bad)
        owner=dict(c,synthetic=False)
        with self.assertRaises(ValueError):a.take(owner,4)             # not synthetic: no generator row
        ref=a.reference(two);self.assertEqual(a.row_status(ref),'OK' if all(ref['models'][m]['status'][0]=='OK' for m in a.models) else
                                               next(ref['models'][m]['status'][0] for m in a.models if ref['models'][m]['status'][0]!='OK'))
        part=lambda s:{'status':[s],'flags':[0],**{f:[0.5 if s=='OK' else math.nan] for f in FIELDS}}     # EX-16 (T22-A01): a result in the canonical form
        self.assertEqual(a.row_status({'n':1,'models':{'bsm':part('OK'),'bjs':part('NO_BID'),'crr':part('EXPIRED')}}),'NO_BID')
        self.assertEqual(a.row_status({'n':2,'models':{'bsm':{'status':['OK','OK']}}}),'ROW_COUNT')

class PanelFallbackTests(unittest.TestCase):
    """Ruling R44 item 3: the generator fallback of take() gives the same one-row request as the full synthetic:large dataset
    (same seed, same parameters) for each of the six panel indices, and a local (owner) chain never gets a generated row."""
    KEYS=('side','S','K','T','bid','ask','r','q','provider_mid','open_interest','expiration','updated')
    def test_the_fallback_rows_equal_the_rows_of_the_full_large_dataset(self):
        from optionlab.synthetic import SIZES
        a=adapter();panel=json.loads((CASES/'option-chain-greeks.panel.json').read_text())
        self.assertEqual((panel['dataset'],panel['seed'],panel['rows']),('synthetic:large',20261007,SIZES['large']))
        large=a.load(dataset(a,SIZES['large'],panel['seed']));small=a.load(dataset(adapter(),SIZES['small'],panel['seed']))
        self.assertEqual(large['n'],SIZES['large'])
        for i in panel['indices']:
            with self.subTest(index=i):
                self.assertGreaterEqual(i,small['n'])                      # each panel index lies beyond the small run dataset
                got=adapter().take(small,i);want=a.take(large,i)           # generator row against the loaded row
                self.assertEqual([got[k] for k in self.KEYS],[want[k] for k in self.KEYS])
                self.assertEqual(got['provider'],want['provider']);self.assertEqual((got['n'],want['n']),(1,1))
                self.assertEqual(want['K'][0]/want['S'][0],panel['rows_columns']['k_over_s'][i])
    def test_a_local_chain_never_gets_a_generated_row(self):
        from optionlab.synthetic import as_local_sample
        a=adapter();data=as_local_sample(a.synthesize(3,20261007));p=Path(tempfile.mkdtemp())/'local.json';p.write_bytes(data)
        local=a.load({'path':str(p),'sha256':hashlib.sha256(data).hexdigest()})
        self.assertFalse(local['synthetic'])
        self.assertEqual(a.take(local,1)['n'],1)                            # its own rows only
        for i in (3,11798):
            with self.subTest(index=i),self.assertRaises(ValueError):a.take(local,i)
        syn=a.load(dataset(a,2));m=a.with_market([])
        with self.assertRaises(ValueError):m.take(syn,11798)                  # a market-priced adapter never generates a row

class BackendRefusalTests(unittest.TestCase):
    def test_start_backend_refuses_every_other_row(self):
        """R43 item a: c-serial only (threads 0, workers direct); every other variant, an unknown route and an inproc echo are
        refused with ValueError before any process or library starts."""
        from optionlab import backends
        self.assertEqual(backends.ROUTES,('stdio','shm','inproc'))
        for variant,workers,route,kw in (('c-threads',2,'stdio',{}),('py-reference','direct','stdio',{}),('c-serial',2,'stdio',{}),
                                         ('c-serial','direct','tcp',{}),('c-serial','direct','inproc',{'echo':True}),('c-serial','direct','stdio',{'models':0}),
                                         ('c-serial','direct','stdio',{'models':32})):
            with self.subTest(variant=variant,workers=workers,route=route,kw=kw),self.assertRaises(ValueError):
                backends.start_backend(variant,workers,route,**kw)
        for route in backends.ROUTES:
            with self.subTest(route=route):
                b=backends.start_backend('c-serial','direct',route,models=31)
                self.assertEqual((b.route,b.threads,b.models,b.limit),(route,0,31,request_limit()))   # R43 item e: the policy limit, never a literal
                b.close()
        with self.assertRaises(ValueError):backends.cold_price('c-serial','direct','inproc',{'n':0},models=7)      # inproc cold: not-applicable

class EchoControlTests(unittest.TestCase):
    def test_echo_results_and_validation(self):
        e=adapter('echo-control');c=e.load(dataset(e,3));ref=e.reference(c)
        self.assertEqual(ref,e.echo_result(3));self.assertEqual(sorted(ref['models']),['bjs','bsm','crr'])
        self.assertTrue(all(col['status']==['ECHO']*3 and col['flags']==[0]*3 for col in ref['models'].values()))
        res=e.materialize(e.run(e.prepare(c,'py-reference',1),'py-reference',1))
        v=e.validate(res,ref,c);self.assertTrue(v['eligible']);self.assertEqual(e.work_units(res),3)
        bad=json.loads(json.dumps(res).replace('NaN','0.5'))
        self.assertFalse(e.validate(bad,ref,c)['eligible'])
        bad=e.echo_result(3);bad['models']['bjs']['status'][1]='OK'
        self.assertFalse(e.validate(bad,ref,c)['eligible']);self.assertEqual(e.work_units(bad),2)
        self.assertFalse(e.validate(e.echo_result(2),ref,c)['eligible'])
        self.assertEqual(e.digest(res),e.digest(e.echo_result(3)));self.assertNotEqual(e.digest(res),e.digest(bad))
        recs=R((255,255,255,NR,NR),(0,0,0,0,0),[NAN]*35)*3
        got=e.materialize({'records':recs,'n':3,'mask':7,'echo':True})
        self.assertTrue(e.validate(got,ref,c)['eligible'])
    def test_echo_rows_are_c_serial_on_the_process_routes(self):
        """R43 item h: libpl_inproc.so has no echo mode, so the echo case declares stdio and shm only and the adapter refuses
        inproc; the selector is all (mask 7)."""
        e=adapter('echo-control');c=e.load(dataset(e,1))
        e.route='inproc'
        with self.assertRaises(ValueError):e.prepare(c,'c-serial',1)
        e.route='stdio';self.assertEqual(len(e.prepare(c,'c-serial',1)['wire']),64)
        with self.assertRaises(ValueError):adapter('echo-control',selector='bsm')

if __name__=='__main__':unittest.main()
