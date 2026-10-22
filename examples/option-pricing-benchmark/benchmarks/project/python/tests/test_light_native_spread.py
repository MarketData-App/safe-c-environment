"""EX-16 (T23; Phase 2 Task 24 example part, ruling R68): the light tests of the check native-spread (optionlab.native_spread)
that need no native binary. The check itself runs the real pl-worker and libpl_inproc.so under `bench check --check native-spread
--native`. These tests hold the variant, call and set matrix (single-thread rule R3), the row rules and the section 3.7
fractions of compare_part, the field table, the framework spread file (tools/bench_tolerance.py accepts it), the FAIL rules
and the check row bounds. REQUIRE-style unittest assertions; no assert statement."""
import copy, math, os, re, sys, tempfile, unittest
from pathlib import Path
from optionlab import native_agreement as na, native_check, native_spread as ns, protocol
from optionlab.agreement import tau_sigma
from optionlab.reference import FLAG_BOUNDARY_AMBIGUOUS, FLAG_ROUNDING_BAND

ROW=(0,100.0,100.0,0.5,4.9,5.1,0.04,0.0)        # side, S, K, T, bid, ask, r, q: mid 5.0
NU=0.2*100.0                                     # nu of vega 0.2 per vol point, the expression of compare_part

def part(n,status='OK',iv=0.3,price=5.0,vega=0.2,greek=0.5,flags=0):
    return {'status':[status]*n,'flags':[flags]*n,'iv':[iv]*n,'price':[price]*n,'delta':[greek]*n,'gamma':[greek]*n,
            'theta':[greek]*n,'vega':[vega]*n,'rho':[greek]*n}

def stats(**frac):
    s=ns.empty_stats();s['rows']=4;s['compared']=4
    for b,v in frac.items():s['frac'][b]=v;s['frac_at'][b]=1;s['samples'][b]=4
    return s

class MatrixTests(unittest.TestCase):
    def test_variants_calls_and_sets(self):
        self.assertEqual(ns.VARIANTS,('py-optimized','py-library','c-serial-stdio-warm','c-serial-stdio-cold','c-serial-shm-warm',
                                      'c-serial-shm-cold','c-serial-inproc-warm'))
        self.assertFalse(any('threads' in v or 'processes' in v or 'pool' in v for v in ns.VARIANTS))     # R3: single thread only
        self.assertEqual(ns.CALLS,(31,1,2,4,8,16));self.assertEqual(ns.SETS,('tiny','small','medium','edges'))
        self.assertEqual(len(ns.expected_keys()),7*6*4)
        self.assertEqual([ns.spread_variant(v,m) for v,m in (('py-library',31),('c-serial-shm-cold',8))],['py-library-all','c-serial-shm-cold-one'])
        self.assertTrue(all(re.fullmatch(r'[a-z][a-z0-9_-]{0,40}',ns.spread_variant(v,m)) for v in ns.VARIANTS for m in ns.CALLS))   # the variant key grammar
    def test_each_model_reads_its_tolerance_block(self):
        t=protocol.tolerances()
        self.assertEqual([ns.block_of(m) for m in ('bsm','bjs','crr','baw','alo')],['','','','baw','alo'])
        self.assertEqual([ns.field_name(b,'iv_abs') for b in ns.BLOCKS],['iv_abs','baw.iv_abs','alo.iv_abs'])
        top=ns.block_values(t,'');baw=ns.block_values(t,'baw')
        self.assertEqual(top['iv_abs'],float(t['iv_abs']));self.assertEqual(baw['sstar_k'],{g:0.0 for g in ns.GREEKS})
        bad=copy.deepcopy(t);del bad['alo']['fit_rel']
        with self.assertRaises(ns.NativeSpreadError):ns.block_values(bad,'alo')
        bad=copy.deepcopy(t);bad['baw']['sstar_k']={'delta':0}
        with self.assertRaises(ns.NativeSpreadError):ns.block_values(bad,'baw')
    def test_the_fields_without_a_spread_are_named(self):
        self.assertEqual(set(ns.NO_SPREAD),{'flat_vega','ambiguity_rel','provider_mid_diff','sstar_k'})
        self.assertEqual(set(ns.FIELD_BASIS),{'iv_abs','iv_ulp_rel','price_rel','fit_nu','fit_rel','greek_abs','greek_rel'})
        t=protocol.tolerances()
        keys={k for k,v in t.items() if not isinstance(v,(dict,str))}|{f'{b}.{k}' for b in ('baw','alo') for k,v in t[b].items() if not isinstance(v,str)}
        covered={ns.field_name(b,f) for b in ns.BLOCKS for f in ns.FIELD_BASIS}|{k for k in keys if k.split('.')[-1] in ns.NO_SPREAD}
        self.assertEqual(keys-covered,set())          # every protocol tolerance field is measured or named without a spread

class ComparePartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p=na.case_params();cls.tol=ns.block_values(protocol.tolerances(),'');cls.ts=tau_sigma(5.0,NU,cls.tol)
    def run_part(self,a,b,n=None,model='bsm',tol=None):
        rows=[ROW]*(n or len(a['status']))
        return ns.compare_part(rows,a,b,tol or self.tol,model,self.p)
    def test_equal_parts_compare_every_row_with_zero_fractions(self):
        s=self.run_part(part(3),part(3))
        self.assertEqual((s['rows'],s['compared'],s['status_failures']),(3,3,0))
        self.assertEqual(s['frac'],{b:0.0 for b in ns.BASES});self.assertEqual(s['samples'],{b:3 for b in ns.BASES})
    def test_the_fraction_of_each_rule(self):
        b=part(3);b['iv'][1]=0.3+0.5*self.ts;b['price'][2]=5.0+1e-9;b['delta'][0]=0.5+1e-9
        s=self.run_part(part(3),b)
        dp=abs((5.0+1e-9)-5.0);dg=abs((0.5+1e-9)-0.5)                                # the binary64 differences
        self.assertAlmostEqual(s['frac']['iv'],0.5,delta=1e-6);self.assertEqual(s['frac_at']['iv'],1)
        self.assertEqual(s['frac']['price'],dp/(NU*self.ts+self.tol['price_rel']*5.0));self.assertEqual(s['frac_at']['price'],2)
        g=self.tol['greek_abs']+(self.tol['greek_rel']+self.ts/0.3)*0.5
        self.assertEqual(s['frac']['greeks'],dg/g);self.assertEqual(s['frac_at']['greeks'],0)
        self.assertEqual(s['max_abs']['delta'],dg);self.assertEqual(s['max_abs']['price'],dp)
        self.assertEqual(s['frac']['fit'],dp/(abs(0.2)*100.0*self.tol['fit_nu']+self.tol['fit_rel']*max(1.0,5.0)))
    def test_status_rules(self):
        a=part(4);b=part(4);b['status'][0]='NO_BID'                                 # a status difference: a failure, no comparison
        a['status'][1]=b['status'][1]='NO_BID';a['iv'][1]=b['iv'][1]=math.nan       # equal non-OK statuses: no comparison, no failure
        b['price'][2]=math.inf                                                      # a non-finite value on an OK row: a failure
        s=self.run_part(a,b)
        self.assertEqual((s['rows'],s['compared'],s['status_failures']),(4,1,2))
    def test_boundary_ambiguous_and_rounding_band_rows(self):
        a=part(4);b=part(4)
        a['flags'][0]=FLAG_BOUNDARY_AMBIGUOUS;b['status'][0]='BELOW_MIN'           # a neighbor status: accepted, not compared
        a['flags'][1]=FLAG_BOUNDARY_AMBIGUOUS;b['status'][1]='NO_BID'              # not a neighbor: a failure
        b['flags'][2]=FLAG_ROUNDING_BAND;b['status'][2]='MODEL_DOMAIN'              # OK <-> MODEL_DOMAIN on a band row: accepted
        b['flags'][3]=FLAG_ROUNDING_BAND;b['status'][3]='NO_BID'                    # another pair on a band row: a failure
        s=self.run_part(a,b)
        self.assertEqual((s['ambiguous'],s['band'],s['status_failures'],s['compared']),(2,2,2,0))
    def test_a_flat_vega_row_has_the_fit_rule_only(self):
        a=part(2,vega=1e-16);b=part(2,vega=1e-16);b['iv'][0]=0.9
        s=self.run_part(a,b)
        self.assertEqual((s['flat_vega'],s['compared'],s['samples']['fit'],s['samples']['iv']),(2,0,2,0))
    def test_another_column_length_is_a_failure_of_every_row(self):
        b=part(3);b['rho']=b['rho'][:2]
        s=self.run_part(part(3),b)
        self.assertEqual((s['rows'],s['status_failures'],s['compared']),(3,3,0))
    def test_the_baw_greek_need_beyond_the_general_rule(self):
        tol=ns.block_values(protocol.tolerances(),'baw');b=part(1);b['gamma'][0]=0.5+1e-3
        s=self.run_part(part(1),b,model='baw',tol=tol)
        general=tol['greek_abs']+(tol['greek_rel']+self.ts/0.3)*0.5
        self.assertAlmostEqual(s['need_sstar_k']['gamma'],(1e-3-general)/100.0,delta=1e-12)
        self.assertGreater(s['frac']['greeks'],1.0)

class FieldTableTests(unittest.TestCase):
    def table(self):
        st={('py-optimized',31,'tiny','bsm'):stats(iv=0.5,price=0.1,fit=0.2,greeks=0.3),
            ('c-serial-stdio-warm',1,'small','bjs'):stats(iv=0.2,price=0.4,fit=0.1,greeks=0.1),
            ('py-library',8,'medium','baw'):stats(iv=0.9,price=0.0,fit=0.0,greeks=0.0),
            ('py-library',16,'edges','alo'):stats(iv=0.0,price=0.0,fit=0.6,greeks=0.0)}
        return st,ns.field_table(st,protocol.tolerances())
    def test_measured_is_the_current_value_times_the_largest_fraction_of_its_block(self):
        st,f=self.table();t=protocol.tolerances()
        self.assertEqual(f['iv_abs']['measured'],t['iv_abs']*0.5);self.assertEqual(f['iv_ulp_rel']['measured'],t['iv_ulp_rel']*0.5)
        self.assertEqual(f['iv_abs']['at'],{'variant':'py-optimized','call':31,'set':'tiny','model':'bsm','row':1,'fraction':0.5})
        self.assertEqual(f['price_rel']['measured'],t['price_rel']*0.4);self.assertEqual(f['price_rel']['at']['variant'],'c-serial-stdio-warm')
        self.assertEqual(f['baw.iv_abs']['measured'],t['baw']['iv_abs']*0.9);self.assertEqual(f['alo.fit_rel']['measured'],t['alo']['fit_rel']*0.6)
        self.assertEqual(f['alo.iv_abs']['measured'],0.0);self.assertEqual(f['alo.iv_abs']['samples'],4)
        self.assertEqual(sorted(f['iv_abs']['variants']),['c-serial-stdio-warm-one','py-optimized-all'])
        self.assertEqual(f['iv_abs']['variants']['py-optimized-all'],{'max_abs':t['iv_abs']*0.5,'samples':4})
        self.assertEqual(len(f),3*len(ns.FIELD_BASIS))
    def test_the_framework_accepts_the_spread_file(self):
        sys.path.insert(0,'/src/tools');import bench_tolerance as bt
        st,f=self.table();t=protocol.tolerances()
        oracle={'iv_abs':1e-8,'iv_ulp_rel':1e-13,'price_rel':5e-13,'greek_abs':2e-9,'greek_rel':2e-6,'baw.iv_abs':1e-8}
        doc=ns.spread_document(f,oracle)
        self.assertEqual(sorted(doc['fields']),sorted(oracle));self.assertEqual(doc['source'],ns.SOURCE)
        self.assertIs(bt.check_spread(doc),doc)
        rec=bt.calibrate(doc,t)
        self.assertEqual(rec['fields']['greek_abs']['proposed'],t['greek_abs'])          # measured < current < oracle error
        self.assertIsNone(rec['fields']['iv_abs']['proposed'])                            # the current value reaches the item 6 bound
        self.assertIsNone(rec['fields']['fit_nu']['proposed'])                            # no oracle bound: not in the spread file
        self.assertEqual(rec['fields']['baw.iv_abs']['proposed'],t['baw']['iv_abs'])      # a locked block: measured < current
        self.assertEqual(rec['status'],'FAIL')
    def test_the_fail_rules(self):
        st,f=self.table()
        self.assertEqual(ns.problems_of(st,f,[]),[])
        st2=copy.deepcopy(st);st2[('py-library',16,'edges','alo')]['rows']=0;st2[('py-optimized',31,'tiny','bsm')]['status_failures']=2
        st2[('py-library',8,'medium','baw')]['frac']['iv']=1.0
        p=ns.problems_of(st2,ns.field_table(st2,protocol.tolerances()),[('py-library',4,'small')])
        self.assertIn('py-library mask 4 small: no result',p);self.assertIn('py-library mask 16 edges alo: no compared row',p)
        self.assertIn('py-optimized mask 31 tiny bsm: 2 status failures',p)
        self.assertTrue(any(x.startswith('baw.iv_abs: measured spread') for x in p))
    def test_the_check_row_fits_the_framework_bounds(self):
        row=ns.check_row([],{'fields':{'iv_abs':{}}},12.5,{'parts':168,'compared_rows':9,'multi_root':0,'status_failures':0,'missing':0,'edge_rows':53})
        self.assertEqual(row['status'],'PASS');self.assertLessEqual(len(row['counts']),32)
        self.assertTrue(all(re.fullmatch(r'[a-z][a-z0-9_]{0,40}',k) and type(v) is int for k,v in row['counts'].items()))
        row=ns.check_row(['iv_abs: measured spread 2e-08 not below the current value 1e-08'],{'fields':{}},1.0,{})
        self.assertEqual(row['status'],'FAIL');self.assertRegex(row['label'],r'^[A-Za-z0-9 ._:,()=+-]{0,120}$')

class RegistrationTests(unittest.TestCase):
    def test_native_check_registers_the_check_and_needs_the_native_binaries(self):
        self.assertIs(native_check.CHECKS['native-spread'],native_check.native_spread)
        out=Path(tempfile.mkdtemp())
        self.assertEqual(native_check.native_spread(out,['extra'])['status'],'FAIL')
        saved=os.environ.pop('SAFE_C_BENCH_NATIVE',None)
        try:row=native_check.native_spread(out,[])
        finally:
            if saved is not None:os.environ['SAFE_C_BENCH_NATIVE']=saved
        self.assertEqual((row['status'],row['reason']),('FAIL','native-spread needs bench check --native'))

if __name__=='__main__':unittest.main()
