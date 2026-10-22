"""EX-13 (Phase 2 B06): the generic agreement mutations of benchlab.agreement act on the JSON form of a result and never
name a field; each one changes a result that it applies to."""
import math, unittest
from benchlab import agreement as ag

class AgreementMutationTests(unittest.TestCase):
    def result(self):return {'values':['0a1b','2c3d','4e5f','6071','8293','a4b5','c6d7','e8f9'],'meta':{'note':'x'}}
    def test_every_generic_mutation_changes_a_text_result(self):
        r=self.result();other={'values':list(reversed(r['values'])),'meta':{'note':'x'}}
        sl=lambda res,n,data:{'values':res['values'][:n],'meta':res['meta']}
        for name in ag.GENERIC:
            with self.subTest(name=name):
                m=ag.apply(name,r,units=8,slice_result=sl,data=None,other=other)
                self.assertIsNotNone(m);self.assertNotEqual(m,r);self.assertEqual(r,self.result())     # the input result is never changed
    def test_the_rules(self):
        r=self.result()
        self.assertEqual(ag.apply('skipped-chunk',r)['values'][-2:],['0000','0000'])
        self.assertEqual(ag.apply('wrong-order',r)['values'][:2],['2c3d','0a1b'])
        self.assertEqual(ag.apply('missing-output',r,units=8,slice_result=lambda res,n,d:{'values':res['values'][:n]},data=None)['values'],r['values'][:7])
        self.assertEqual(ag.apply('precision-change',r)['values'][0],'0a1a')
        self.assertEqual(ag.apply('range-change',r)['values'],['4e5f','4e5f','4e5f','6071','8293','a4b5','c6d7','c6d7'])
        self.assertEqual(ag.apply('hardcoded-answer',r,other={'values':['x']}),{'values':['x']})
    def test_numbers_and_nesting(self):
        r={'b':{'rows':[1.5,2.25,3.0,4.0]},'a':[[1,2],[3,4]]}
        self.assertEqual(ag.target(r)[0],('a',0))                 # depth first over sorted keys
        p=ag.apply('precision-change',r)
        self.assertEqual(p['a'],[[0,3],[2,5]]);self.assertNotEqual(p['b']['rows'][0],1.5)
        self.assertNotEqual(ag.last_place(0.1),0.1);self.assertEqual(ag.last_place(math.inf),math.inf)
        self.assertEqual(ag.last_place(1.5),math.nextafter(1.5,math.inf))      # exact in single precision: the next float
    def test_mutations_that_do_not_apply(self):
        flat={'values':['same','same']}
        for name in ('skipped-chunk','wrong-order','range-change'):self.assertIsNone(ag.apply(name,flat))
        self.assertIsNone(ag.apply('missing-output',flat,units=0,slice_result=lambda *a:None))
        self.assertIsNone(ag.apply('hardcoded-answer',flat))
        self.assertIsNone(ag.apply('precision-change',{'value':1}))
        with self.assertRaises(ValueError):ag.apply('unknown',flat)

if __name__=='__main__':unittest.main()
