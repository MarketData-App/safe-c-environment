"""The test-only `cap` keyword of the shared baw_admit (Appendix G-BAW R4 item 3: admit when j + N_C <= cap) and the
generated tie vectors j + N_C == cap for small caps (3..6) that kill the mutant `j + N_C < cap`. The definition stays
baw_newton_max = 40 (the manifest value); `cap` is used only by tests (a guard test scans every non-test call site).

Observable of the tie: the replay admits through the certificate at iterate j, so it evaluates the map j + 1 times. The
mutant rejects the tie at j and must go on (more map evaluations, or a different result)."""
import ast, inspect, math, pathlib, unittest
from unittest import mock
from optionlab import baw_admit as ba
from optionlab.mapping import unit
from optionlab.params import CASE
from optionlab.checks import BAW_RECORD_GRID
CALL,PUT=0,1
CAPS=(3,4,5,6)
PY=pathlib.Path(__file__).resolve().parents[1]           # benchmarks/project/python
REPO=pathlib.Path(__file__).resolve().parents[6]         # the repository root (/src in the container)

def instrumented(fn,args,cap):
    """(result, map calls, certificate results in call order) of one baw_admit call (the module's own functions, wrapped)."""
    maps=[0];certs=[];real_map=ba._map;real_cert=ba.certificate
    def m(*a,**k):maps[0]+=1;return real_map(*a,**k)
    def c(*a,**k):
        r=real_cert(*a,**k);certs.append(r);return r
    with mock.patch.object(ba,'_map',m),mock.patch.object(ba,'certificate',c):
        res=fn(*args,cap=cap) if cap is not None else fn(*args)
    return res,maps[0],certs

def is_tie(res,maps,certs,cap):
    """Admitted through the certificate at iterate j = len(certs) - 1 with j + N_C == cap (the stop test failed at j)."""
    if res!=(True,True) or not certs or certs[-1] is None or maps!=len(certs):return False
    j=len(certs)-1;return j+certs[-1]==cap

def tie_vectors(per_cap=3):
    """Generated tie vectors {cap: [(side, S, K, r1, q1, v), ...]} from the record's oracle grid (case r and q)."""
    out={c:[] for c in CAPS}
    for side,S,K,T,s in BAW_RECORD_GRID:
        r1,q1,s1=unit(T,CASE.rate,CASE.dividend_yield,s);args=(side,S,K,r1,q1,s1*s1*1.0)
        for cap in CAPS:
            if len(out[cap])>=per_cap:continue
            res,maps,certs=instrumented(ba.baw_admit,args,cap)
            if is_tie(res,maps,certs,cap):out[cap].append(args)
        if all(len(v)>=per_cap for v in out.values()):break
    return out

def mutant():
    """baw_admit with the admission test `j+NC<=cap` replaced by `j+NC<cap` (the module's globals)."""
    src=inspect.getsource(ba.baw_admit)
    if src.count('j+NC<=cap')!=1:raise AssertionError('the admission test is not found exactly once')
    ns={};exec(compile(src.replace('j+NC<=cap','j+NC<cap'),'<mutant baw_admit>','exec'),ba.__dict__,ns);return ns['baw_admit']

class CapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.ties=tie_vectors()
    def test_default_cap_is_the_manifest_value(self):
        self.assertEqual((ba.NEWTON_MAX,CASE.baw_newton_max),(40,40))
        sig=inspect.signature(ba.baw_admit);p=sig.parameters['cap']
        self.assertEqual((p.kind,p.default),(inspect.Parameter.KEYWORD_ONLY,None))
        for side,S,K,T,s in BAW_RECORD_GRID[::7]:
            r1,q1,s1=unit(T,CASE.rate,CASE.dividend_yield,s);a=(side,S,K,r1,q1,s1*s1*1.0)
            self.assertEqual(ba.baw_admit(*a),ba.baw_admit(*a,cap=40))
    def test_cap_must_be_a_positive_integer(self):
        for bad in (0,-1,1.5,True,'3'):
            with self.subTest(cap=bad),self.assertRaises(ValueError):ba.baw_admit(PUT,100.0,100.0,0.04,0.012,0.09,cap=bad)
    def test_tie_vectors_exist_and_are_admitted(self):
        for cap in CAPS:
            with self.subTest(cap=cap):
                self.assertGreater(len(self.ties[cap]),0)
                for a in self.ties[cap]:
                    res,maps,certs=instrumented(ba.baw_admit,a,cap);self.assertTrue(is_tie(res,maps,certs,cap))
    def test_the_mutant_fails_every_tie_vector(self):
        mut=mutant()
        for cap in CAPS:
            for a in self.ties[cap]:
                with self.subTest(cap=cap,vector=a):
                    res,maps,certs=instrumented(ba.baw_admit,a,cap);mres,mmaps,_=instrumented(mut,a,cap)
                    self.assertTrue(mres!=res or mmaps>maps)        # killed: another result, or the replay went on past the tie
    def test_the_mutant_is_visible_to_the_tie_check(self):
        mut=mutant();a=next(v for c in CAPS for v in self.ties[c])
        cap=next(c for c in CAPS if a in self.ties[c]);mres,mmaps,mcerts=instrumented(mut,a,cap)
        self.assertFalse(is_tie(mres,mmaps,mcerts,cap))

class CapGuardTests(unittest.TestCase):
    def test_no_non_test_call_site_passes_cap(self):
        """Every .py file outside a tests/ directory under the example's python tree, benchmarks/ and tools/: no call of
        baw_admit (name or attribute) passes the keyword `cap`."""
        roots=[PY,REPO/'benchmarks',REPO/'tools'];bad=[];seen=0
        for root in roots:
            for f in root.rglob('*.py'):
                if 'tests' in f.relative_to(root).parts:continue
                tree=ast.parse(f.read_text(),str(f));seen+=1
                for n in ast.walk(tree):
                    if isinstance(n,ast.Call):
                        name=n.func.id if isinstance(n.func,ast.Name) else n.func.attr if isinstance(n.func,ast.Attribute) else None
                        if name=='baw_admit' and any(k.arg=='cap' for k in n.keywords):bad.append(f'{f.name}:{n.lineno}')
        self.assertGreater(seen,20);self.assertEqual(bad,[])
    def test_the_guard_sees_a_planted_call(self):
        tree=ast.parse('from optionlab.baw_admit import baw_admit\nbaw_admit(0,1.0,1.0,0.0,0.0,1.0,cap=3)\n')
        calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and getattr(n.func,'id',None)=='baw_admit' and any(k.arg=='cap' for k in n.keywords)]
        self.assertEqual(len(calls),1)

if __name__=='__main__':unittest.main()
