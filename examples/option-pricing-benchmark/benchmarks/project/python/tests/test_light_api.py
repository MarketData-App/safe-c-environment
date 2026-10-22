"""EX-11 (T20): the light tests of optionlab.api.price_chain, the service entry of the option example (plan Task 21,
test_light_api.py, adapted by ruling R49: single-threaded backends only, ALO wired). They run in the example unit suite and
start no native process. The tests with the real pl-worker are the declared check api-native (optionlab.api_check), which
`bench check --check api-native --native` runs (the unit suite has no --native). REQUIRE-style unittest assertions."""
import os, subprocess, sys, unittest
from unittest import mock
from optionlab import api, backends
from optionlab.contract import MODELS5, load_chain, with_rates
from optionlab.params import CASE
from optionlab.reference import result_digest
from optionlab.synthetic import generate

SUBSETS=(('bsm',),('baw',),('alo',),('bjs','crr'),MODELS5)

def project(result,models):
    """The result restricted to `models` (the projection of the mask-31 result, G5.4)."""
    return {'n':result['n'],'models':{m:result['models'][m] for m in models}}

class ApiTests(unittest.TestCase):
    def setUp(self):self.chain=with_rates(load_chain(generate(4,20261007,CASE)),CASE.rate,CASE.dividend_yield)
    def test_python_backend_and_model_subset(self):
        out=api.price_chain(self.chain,models=('bsm',),backend='python')
        self.assertEqual(sorted(out['models']),['bsm']);self.assertEqual(out['n'],4)
    def test_defaults_are_the_three_model_python_call(self):
        out=api.price_chain(self.chain);self.assertEqual(list(out['models']),['bsm','bjs','crr']);self.assertEqual(out['n'],4)
    def test_four_model_subsets(self):
        out=api.price_chain(self.chain,models=('baw','bsm'),backend='python')
        self.assertEqual(sorted(out['models']),['baw','bsm'])
    def test_every_subset_is_the_projection_of_the_five_model_result(self):
        full=api.price_chain(self.chain,models=MODELS5,backend='python');self.assertEqual(list(full['models']),list(MODELS5))
        for models in SUBSETS:
            with self.subTest(models=models):
                out=api.price_chain(self.chain,models=models,backend='python')
                self.assertEqual(list(out['models']),list(models))
                self.assertEqual(result_digest(out),result_digest(project(full,models)))
    def test_model_order_follows_models5_and_a_list_is_accepted(self):
        out=api.price_chain(self.chain,models=['crr','bsm'],backend='python');self.assertEqual(list(out['models']),['bsm','crr'])
    def test_the_result_is_the_reference_run_shape(self):
        out=api.price_chain(self.chain,models=('bsm',),backend='python');col=out['models']['bsm']
        for key in ('status','flags','iv','price','delta','gamma','theta','vega','rho','engine_evals'):
            with self.subTest(key=key):self.assertEqual(len(col[key]),4)
    def test_an_empty_chain_gives_an_empty_result(self):
        empty={**self.chain,'n':0,**{k:[] for k in ('side','S','K','T','bid','ask','r','q')}}
        out=api.price_chain(empty,models=('bsm',),backend='python');self.assertEqual((out['n'],out['models']['bsm']['status']),(0,[]))
    REFUSALS=({'backend':'c-shm'},{'backend':'c-inproc'},{'backend':7},{'models':()},{'models':('heston',)},{'models':('bsm','bsm2')},
              {'models':('bsm','bsm')},{'models':'bsm'},{'models':None},{'backend':'python-processes','workers':2},
              {'backend':'python-processes','workers':3},{'backend':'c-worker','workers':8},{'backend':'c-worker','workers':2},
              {'backend':'c-worker','workers':1},{'backend':'python','workers':1},{'backend':'python','workers':0},
              {'backend':'python','workers':True})
    def test_refusals(self):
        for kw in self.REFUSALS:
            with self.subTest(kw=kw):
                with self.assertRaises(ValueError):api.price_chain(self.chain,**kw)
    def test_a_chain_without_per_row_rates_is_refused(self):
        for gone in ('q','r'):
            with self.subTest(gone=gone):
                with self.assertRaises(ValueError):api.price_chain({k:v for k,v in self.chain.items() if k!=gone})
        with self.assertRaises(ValueError):api.price_chain({k:v for k,v in self.chain.items() if k not in ('r','q')})
    def malformed(self):
        """Every malformed chain and every chain without the per-row rates (the value cases are in the value test)."""
        return (None,[],{},{'n':4},{**self.chain,'S':self.chain['S'][:3]},{**self.chain,'q':self.chain['q'][:2]},{**self.chain,'n':-1},
                {k:v for k,v in self.chain.items() if k!='q'},{k:v for k,v in self.chain.items() if k!='r'},
                {k:v for k,v in self.chain.items() if k not in ('r','q')})
    def test_a_malformed_chain_is_refused(self):
        for bad in self.malformed():
            with self.subTest(bad=repr(bad)[:40]):
                with self.assertRaises(ValueError):api.price_chain(bad)
    def spied(self):
        """Patches every backend entry point and the adapter builder with a recorder; returns (the list of calls, the patches)."""
        calls=[]
        def spy(name):
            def record(*a,**k):calls.append(name);raise AssertionError(f'{name} was called')
            return record
        patches=[mock.patch.object(backends,'cold_price',spy('cold_price')),mock.patch.object(backends,'start_backend',spy('start_backend')),
                 mock.patch.object(backends,'prepare',spy('prepare')),mock.patch.object(api,'_adapter',spy('_adapter'))]
        for name,cls in list(backends.BACKENDS.items()):
            patches.append(mock.patch.dict(backends.BACKENDS,{name:spy('BACKENDS.'+name)}))
        return calls,patches
    def assertRefusedWithoutBackend(self,chain,**kw):
        calls,patches=self.spied()
        for p in patches:p.start()
        try:
            with self.assertRaises(ValueError):api.price_chain(chain,**kw)
        finally:
            for p in reversed(patches):p.stop()
        self.assertEqual(calls,[],f'a refusal reached a backend entry point: {calls}')
    def test_refusals_come_before_any_native_start(self):
        for backend in ('python','c-worker'):
            for kw in self.REFUSALS+({'workers':2},{'workers':1},{'workers':True},{'models':()},{'models':('heston',)},{'models':('bsm','bsm')}):
                with self.subTest(backend=backend,kw=kw):self.assertRefusedWithoutBackend(self.chain,**{'backend':backend,**kw} if 'backend' not in kw else kw)
        for bad in self.malformed()+(self.bad(0,'S',None),):
            for backend in ('python','c-worker'):
                with self.subTest(backend=backend,bad=repr(bad)[:40]):self.assertRefusedWithoutBackend(bad,backend=backend)
    def test_the_spy_sees_a_valid_c_worker_call(self):
        calls,patches=self.spied()
        for p in patches:p.start()
        try:
            with self.assertRaises(AssertionError):api.price_chain(self.chain,backend='c-worker')
        finally:
            for p in reversed(patches):p.stop()
        self.assertTrue(calls)
    def bad(self,i,key,value):
        col=list(self.chain[key]);col[i]=value;return {**self.chain,key:col}
    def test_chain_values_are_refused_the_same_on_both_backends(self):
        big=10**400                     # an int beyond binary64: float(big) overflows (T20b-A06)
        cases=[(1,'S',None),(1,'K','100'),(0,'T',True),(2,'bid',None),(2,'ask','x'),(3,'side',True),(3,'side',False),
               (3,'side',1.0),(3,'side',None),(3,'side','call'),(1,'r',float('nan')),(1,'r',float('inf')),(2,'q',float('-inf')),(2,'q',None),
               (0,'r','0.05'),(0,'q',True),(1,'r',big),(2,'q',-big)]
        for backend in ('python','c-worker'):
            for i,key,value in cases:
                with self.subTest(backend=backend,row=i,key=key,value=value):
                    chain=self.bad(i,key,value)
                    with self.assertRaises(ValueError) as caught:api.price_chain(chain,backend=backend)
                    self.assertTrue(str(caught.exception).startswith(f'chain row {i} field {key}:'),str(caught.exception)[:60])
                    self.assertRefusedWithoutBackend(chain,backend=backend)
    def assertReachesBackend(self,chain,backend):
        """price_chain accepts `chain`: with every backend entry spied, the call gets as far as the backend and not a ValueError."""
        calls,patches=self.spied()
        for p in patches:p.start()
        try:
            try:api.price_chain(chain,backend=backend)
            except AssertionError:pass
        finally:
            for p in reversed(patches):p.stop()
        self.assertTrue(calls)
    def test_an_unknown_side_code_is_an_invalid_input_row(self):
        base=api.price_chain(self.chain,models=('bsm','crr'),backend='python')
        for code in (-1,2,7,-10**400):
            with self.subTest(code=code):
                out=api.price_chain(self.bad(3,'side',code),models=('bsm','crr'),backend='python')
                for m in ('bsm','crr'):
                    self.assertEqual(out['models'][m]['status'][3],'INVALID_INPUT')
                    self.assertEqual(out['models'][m]['status'][:3],base['models'][m]['status'][:3])
                self.assertReachesBackend(self.bad(3,'side',code),'c-worker')
    def test_a_decoded_chain_with_an_unknown_side_prices_like_before(self):
        obj=generate(4,20261007,CASE);obj['side'][3]='straddle';obj['side'][2]=None
        chain=with_rates(load_chain(obj),CASE.rate,CASE.dividend_yield);self.assertEqual(chain['side'][2:],[-1,-1])
        out=api.price_chain(chain,models=('bsm',),backend='python')
        self.assertEqual(out['models']['bsm']['status'][2:],['INVALID_INPUT','INVALID_INPUT'])
        self.assertReachesBackend(chain,'c-worker')
    def test_an_int_beyond_binary64_is_a_non_finite_market_value(self):
        big=10**400;base=api.price_chain(self.chain,models=('bsm',),backend='python')
        for key in ('S','K','T','bid','ask'):
            for value in (big,-big):
                with self.subTest(key=key,value=value):
                    out=api.price_chain(self.bad(2,key,value),models=('bsm',),backend='python')
                    self.assertEqual(out['models']['bsm']['status'][2],'INVALID_INPUT')
                    self.assertEqual(out['models']['bsm']['status'][:2],base['models']['bsm']['status'][:2])
                    self.assertReachesBackend(self.bad(2,key,value),'c-worker')
    def test_non_finite_market_values_stay_accepted(self):
        out=api.price_chain(self.bad(1,'bid',float('nan')),models=('bsm',),backend='python');self.assertEqual(out['n'],4)
    def test_api_native_without_the_native_environment_fails(self):
        from optionlab import api_check
        env={k:v for k,v in os.environ.items() if k!='SAFE_C_BENCH_NATIVE'}
        with mock.patch.dict(os.environ,env,clear=True):
            out=api_check.api_native('/nonexistent-out-dir',[])
        self.assertEqual(out['status'],'FAIL');self.assertNotIn('skip',str(out).lower())
    def test_the_child_scan_sees_a_live_child(self):
        from optionlab import api_check
        proc=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
        try:self.assertIn(proc.pid,api_check._children());api_check.scan_control()
        finally:proc.kill();proc.wait()
        self.assertNotIn(proc.pid,api_check._children())
    def test_a_blind_child_scan_fails_the_control(self):
        from optionlab import api_check, native_check
        with mock.patch.object(api_check,'_children',return_value=[]):
            with self.assertRaises(native_check.NativeCheckError) as caught:api_check.scan_control()
        self.assertIn('does not see',str(caught.exception))
    def test_a_scan_that_keeps_the_reaped_child_fails_the_control(self):
        from optionlab import api_check, native_check
        made=[];real=subprocess.Popen
        def popen(*a,**k):
            proc=real(*a,**k);made.append(proc);return proc
        with mock.patch.object(subprocess,'Popen',popen),mock.patch.object(api_check,'_children',lambda:[made[0].pid]):
            with self.assertRaises(native_check.NativeCheckError) as caught:api_check.scan_control()
        self.assertIn('still lists',str(caught.exception));self.assertEqual(len(made),1)

if __name__=='__main__':unittest.main()
