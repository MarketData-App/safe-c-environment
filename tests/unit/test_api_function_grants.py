import copy, json, sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from evidence import GateError
from qualification import ast_foundation_uses
from foundation import grants_consistent
POLICY=json.loads((ROOT/'safety/foundation-api-policy.json').read_text())
SC='foundation/parallel/sc-parallel.c';FOUNDATION='foundation/src/sc-foundation.c';PROJECT='examples/hello-world/src/greeting.c'
INVENTORY={SC:{'role':'parallel-adapter','targets':['sc_parallel'],'sha256':'0'*64},FOUNDATION:dict(POLICY['boundary_inventory'][FOUNDATION])}

def ref(name,kind='FunctionDecl',qual=''):return {'kind':'DeclRefExpr','referencedDecl':{'kind':kind,'name':name},'type':{'qualType':qual}}
def call(inner):return {'kind':'CallExpr','inner':[{'kind':'ImplicitCastExpr','inner':[inner]}]}
def member_call(qual):
    member={'kind':'MemberExpr','type':{'qualType':qual},'inner':[{'kind':'ImplicitCastExpr','inner':[ref('s','ParmVarDecl','RunState *')]}]}
    return {'kind':'CallExpr','inner':[{'kind':'ImplicitCastExpr','type':{'qualType':qual},'inner':[member]}]}
def tree(fn,*stmts):return {'inner':[{'kind':'FunctionDecl','name':fn,'loc':{},'inner':[{'kind':'CompoundStmt','inner':list(stmts)}]}]}
def rules(source,fn,*stmts,inventory=INVENTORY,sha='0'*64):return sorted({f['rule'] for f in ast_foundation_uses(tree(fn,*stmts),POLICY,source,inventory,sha)})
SUB={'kind':'ArraySubscriptExpr','inner':[]}

class GrantTests(unittest.TestCase):
    def test_grant_holder_may_use_exactly_the_granted_names(self):
        self.assertEqual(rules(SC,'run_pool',call(ref('g_thread_pool_new')),call(ref('g_mutex_lock')),call(ref('g_set_error_literal'))),[])
        self.assertIn('unapproved-glib-api',rules(SC,'run_pool',call(ref('g_hash_table_new'))))
        self.assertIn('unapproved-glib-api',rules(SC,'run_pool',call(ref('g_thread_new'))))
    def test_indirect_call_only_in_the_named_function_and_type(self):
        self.assertEqual(rules(SC,'sc_parallel_worker',member_call('ScParallelTaskFn')),[])
        self.assertIn('unknown-call-indirection',rules(SC,'run_pool',member_call('ScParallelTaskFn')))
        self.assertIn('unknown-call-indirection',rules(SC,'sc_parallel_worker',member_call('void (*)(void)')))
    def test_grant_holder_keeps_every_other_rule(self):
        self.assertIn('raw-indexing',rules(SC,'run_pool',SUB))
        self.assertIn('raw-memory-api',rules(SC,'run_pool',call(ref('memcpy'))))
    def test_threading_outside_the_grant_is_refused_everywhere(self):
        self.assertIn('threading-outside-grant',rules(FOUNDATION,'f',call(ref('g_mutex_lock'))))   # a blanket boundary
        self.assertIn('threading-outside-grant',rules(PROJECT,'f',call(ref('g_thread_pool_push'))))
    def test_atomics_are_threading(self):
        atomic={'kind':'AtomicExpr','inner':[]}
        self.assertIn('threading-outside-grant',rules(FOUNDATION,'f',atomic))
        self.assertIn('threading-outside-grant',rules(PROJECT,'f',call(ref('__atomic_load_n'))))
        self.assertIn('threading-outside-grant',rules(PROJECT,'f',call(ref('__sync_fetch_and_add'))))
        self.assertEqual(rules(SC,'sc_parallel_worker',atomic),[])
    def test_an_inventory_mismatch_removes_the_grant(self):
        inv=copy.deepcopy(INVENTORY);inv[SC]['role']='other'
        self.assertIn('threading-outside-grant',rules(SC,'run_pool',call(ref('g_thread_pool_new')),inventory=inv))
        self.assertIn('unknown-call-indirection',rules(SC,'sc_parallel_worker',member_call('ScParallelTaskFn'),inventory=inv))
    def test_the_grant_binds_to_the_inventory_sha256(self):
        self.assertIn('threading-outside-grant',rules(SC,'run_pool',call(ref('g_thread_pool_new')),sha='1'*64))
        self.assertIn('threading-outside-grant',rules(SC,'run_pool',call(ref('g_thread_pool_new')),sha=None))
        self.assertIn('unknown-call-indirection',rules(SC,'sc_parallel_worker',member_call('ScParallelTaskFn'),sha='1'*64))
        self.assertIn('threading-outside-grant',rules(SC,'sc_parallel_worker',{'kind':'AtomicExpr','inner':[]},sha='1'*64))
    def test_one_granted_call_site_through_a_member_expression(self):
        self.assertIn('unknown-call-indirection',rules(SC,'sc_parallel_worker',member_call('ScParallelTaskFn'),member_call('ScParallelTaskFn')))
        local={'kind':'CallExpr','inner':[{'kind':'ImplicitCastExpr','type':{'qualType':'ScParallelTaskFn'},'inner':[ref('fn','VarDecl','ScParallelTaskFn')]}]}
        self.assertIn('unknown-call-indirection',rules(SC,'sc_parallel_worker',local))
    def test_consistency(self):
        grants_consistent(POLICY,INVENTORY)
        bad=copy.deepcopy(POLICY);bad['boundaries'][SC]='threading'
        with self.assertRaises(GateError):grants_consistent(bad,INVENTORY)
        bad=copy.deepcopy(POLICY);bad['function_grants'][SC]['glib_functions'].append('g_thread_new')
        with self.assertRaises(GateError):grants_consistent(bad,INVENTORY)
        inv=copy.deepcopy(INVENTORY);inv[SC]['targets']=['other']
        with self.assertRaises(GateError):grants_consistent(POLICY,inv)
    def test_an_inventoried_grant_holder_must_be_scanned_by_the_ast_gate(self):
        from qualification import INFRA
        self.assertIn(SC,INFRA);self.assertIn('foundation/parallel/tests/contracts.c',INFRA)
        grants_consistent(POLICY,INVENTORY,infra=INFRA)
        with self.assertRaises(GateError):grants_consistent(POLICY,INVENTORY,infra=[x for x in INFRA if x!=SC])
        inv=copy.deepcopy(INVENTORY);del inv[SC]
        grants_consistent(POLICY,inv,infra=[x for x in INFRA if x!=SC])   # not inventoried: the grant is inactive anyway
    def test_grant_is_exactly_the_amendment_f_list(self):
        names=['g_thread_pool_new','g_thread_pool_push','g_thread_pool_free','g_thread_pool_get_num_threads','g_thread_self','g_mutex_init','g_mutex_clear',
               'g_mutex_lock','g_mutex_unlock','g_cond_init','g_cond_clear','g_cond_wait','g_cond_broadcast']
        self.assertEqual(POLICY['threading_functions'],names)
        self.assertEqual(POLICY['function_grants'][SC]['glib_functions'],names+['g_set_error_literal','g_quark_from_static_string'])
        self.assertEqual(POLICY['function_grants'][SC]['indirect_calls'],[{'function':'sc_parallel_worker','callee_type':'ScParallelTaskFn'}])
        self.assertIs(POLICY['function_grants'][SC]['atomic_expressions'],True)
        self.assertEqual(list(POLICY['function_grants']),[SC])
    def test_schema_constant_equals_policy(self):
        self.assertEqual(json.loads((ROOT/'schemas/foundation-api-policy.json').read_text())['const'],POLICY)

if __name__=='__main__':unittest.main()
