"""Task 15 (G9.4; P3R11, P3R12): the qualification truth table over all 680 feasible input combinations. Ruling T15-C4 (as
T14-C1): test_truth_table moved here from tests/unit/test_bench_qualification.py because the plan gives each tests/unit file
0.5 s in the check-fast unit gate. Its assertions are unchanged. The table data, combos, producer_chain, tokens, resolve, uev_for and
the record producer stay in tests/unit/test_bench_qualification.py and are imported from there (T15-APP-10); the eight
named rows that test_bench_units uses keep running in check-fast (NamedRowTests there).

The host tools and the tests/unit module are imported in setUpModule from /src and every module that this import added
is removed again in tearDownModule, so later container tests that load a modified copy of a tool (test_coverage) never
receive these modules."""
import sys, tempfile, unittest
from pathlib import Path
ROOT=Path('/src')
NAMES=('ROWS','combos','rows_for','producer_chain','tokens','resolve','uev_for')
_MODULES=set();_PATH=[];tq=None

def setUpModule():
    global _MODULES,_PATH,tq
    _MODULES=set(sys.modules);_PATH=list(sys.path)
    sys.path.insert(0,str(ROOT/'tests/unit'))
    import test_bench_qualification as m
    tq=m;globals().update({n:getattr(m,n) for n in NAMES})

def tearDownModule():
    for name in set(sys.modules)-_MODULES:sys.modules.pop(name,None)
    sys.path[:]=_PATH

class TruthTableTests(unittest.TestCase):
    def record(self,uev):
        """The producer of the decision record: tests/unit/test_bench_qualification.record (Task 18 Step 1 changes it there)."""
        return tq.record(uev)
    def test_truth_table(self):
        seen=set()
        for c in combos():
            with self.subTest(combination=c):
                hits=rows_for(c);self.assertEqual(len(hits),1)                   # exhaustive and disjoint
                row=hits[0];seen.add(row['id'])
                with tempfile.TemporaryDirectory() as t:
                    q,kind,label,pc,before=producer_chain(t,*c);tok=tokens(t)
                rec=self.record(uev_for(q))
                self.assertEqual(pc,before)                                    # P3R12-05: qualify never changes its input
                self.assertEqual(set(q),{'exit','report_path','report_sha256','identity','local'})
                self.assertEqual((kind,label),(row['kind'],row['label']))
                self.assertEqual(None if q['local'] is None else (q['local']['ok'],q['local']['reason']),row['local'])
                self.assertEqual(rec['qualification'],resolve(row['q'],tok))   # every field; sha(PR) is the digest of the report bytes
                u=next(x for x in rec['units'] if x['unit']=='m3/full-dataset')
                if row['condition'] is None:self.assertEqual((u['verdict'],u['reason'],u['failed_conditions']),('PREFER_C','c-reliably-faster',[]))
                else:self.assertEqual((u['verdict'],u['reason'],u['failed_conditions']),('INCONCLUSIVE','c-not-eligible',[row['condition']]))
                self.assertEqual(u['framework_basis'],row['kind'])
        self.assertEqual(seen,{r['id'] for r in ROWS})                        # every row is reachable
