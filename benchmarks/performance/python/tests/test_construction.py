"""G-ALO-CO part 1 (spec Amendment I, item I13.1 step 7c), framework control case: chunk sizes equal
bench_plan.expected_chunk_sizes(n, w, policy limit) and benchlab.pools.chunk_sizes(n, w, policy limit) at n = 14,336, 14,337
and 20,000 for w = 1, 2, 4, built through benchlab.workload.construct_adapter and in a pool worker through the four-item
bench_ref. The coordinator sets SAFE_C_BENCH_REQUEST_LIMIT for this suite (child_env)."""
import json, os, unittest
from pathlib import Path
from benchlab import pools, workload
from benchlab.workload import construct_adapter, load_case_adapter
CASES=Path('/src/benchmarks/performance/cases')
POLICY=json.loads(Path('/src/safety/performance-policy.json').read_text())
LIMIT=POLICY['pools']['request_limit'];NS=(14336,14337,20000);WS=(1,2,4)
def _host_rule():
    """tools/bench_plan.expected_chunk_sizes, read by path (the container has no host tool imports): the function node only."""
    import ast, types
    tree=ast.parse(Path('/src/tools/bench_plan.py').read_text());node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='expected_chunk_sizes')
    ns={};exec(compile(ast.Module(body=[node],type_ignores=[]),'/src/tools/bench_plan.py','exec'),ns);return types.SimpleNamespace(expected_chunk_sizes=ns['expected_chunk_sizes'])
bp=_host_rule()

def worker_sizes(cases):
    """Runs in a pool worker: the adapter that benchlab.pools._resolve built from the ref, its limit and its chunk sizes."""
    a=pools._WORKER['adapter'];return a.request_limit,a.bench_ref,{(n,w):[len(c['index']) for c in a.prepare(list(range(n)),'py-processes',w)['chunks']] for n,w in cases}

class ControlConstructionTests(unittest.TestCase):
    def test_the_suite_runs_with_the_coordinator_variable(self):
        self.assertEqual(os.environ.get('SAFE_C_BENCH_REQUEST_LIMIT'),str(LIMIT));self.assertEqual((LIMIT,workload.request_limit()),(14336,14336))
    def test_helper_built_control_chunks_follow_the_policy_limit(self):
        a=load_case_adapter(json.loads((CASES/'bench-control-spin.json').read_text()))
        self.assertEqual((a.request_limit,len(a.bench_ref),a.bench_ref[3]),(LIMIT,4,LIMIT))
        for n in NS:
            seeds=list(range(n))
            for w in WS:
                with self.subTest(n=n,w=w):
                    got=[len(c['index']) for c in a.prepare(seeds,'py-threads',w)['chunks']]
                    self.assertEqual(got,bp.expected_chunk_sizes(n,w,LIMIT));self.assertEqual(got,pools.chunk_sizes(n,w,LIMIT))
        self.assertEqual(pools.chunk_sizes(20000,2,LIMIT),[7168,7168,2832,2832])
    def test_pool_workers_rebuild_the_adapter_with_the_ref_limit(self):
        a=construct_adapter('benchlab.controlcase:Spin',{'rounds':1,'seed':1},pooled=True)
        with pools.start_pool('py-processes',1,a.bench_ref) as ex:
            limit,ref,sizes=ex.submit(worker_sizes,[(n,w) for n in NS for w in WS]).result(timeout=120)
        self.assertEqual((limit,tuple(ref) if ref else ref),(LIMIT,a.bench_ref))
        for (n,w),got in sizes.items():
            with self.subTest(n=n,w=w):self.assertEqual(got,bp.expected_chunk_sizes(n,w,LIMIT))
    def test_a_pooled_run_records_the_policy_chunk_sizes(self):
        a=construct_adapter('benchlab.controlcase:Spin',{'rounds':0,'seed':1},pooled=True);seeds=list(range(14337));stats={}
        with pools.start_pool('py-processes',2,a.bench_ref) as ex:out=pools.run_pool(a,a.prepare(seeds,'py-processes',2),2,ex,stats=stats)
        self.assertEqual(len(out),14337);self.assertEqual(stats['chunk_sizes'],bp.expected_chunk_sizes(14337,2,LIMIT))

if __name__=='__main__':unittest.main()
