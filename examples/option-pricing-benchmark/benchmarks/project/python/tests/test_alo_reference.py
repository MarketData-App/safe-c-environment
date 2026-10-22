"""G-ALO2 part A (Task A4; spec Amendment I4.1, I2, H17, H19; Appendix I-ALO): py-reference ALO equal to QuantLib-Python
1.43 QdFpAmericanEngine(accurateScheme, Auto), the shared alo_equation/alo_segment, the shared NaN check, RunDefect.
Container suite (QuantLib-Python is available there). The planting helpers act only with SAFE_C_TEST_COUNTERS=1."""
import os
os.environ['SAFE_C_TEST_COUNTERS']='1'
import ast, dataclasses, math, unittest
from pathlib import Path
from unittest import mock
from optionlab import alo, alo_equation, models, reference, checks
from optionlab.contract import load_chain, rows as chain_rows
from optionlab.synthetic import generate
from optionlab.params import CASE

PKG=Path(alo.__file__).resolve().parent
ROWS=chain_rows(load_chain(generate(32,20261007,CASE)),CASE)    # landed row tuples (side, S, K, T, bid, ask, r, q)
def ev(row=None,info=None):
    """The landed reference.evaluate(row, model, params, info=None, engine=None) -> (status, values, flags, evals)."""
    return reference.evaluate(ROWS[alo.TEST_ROW] if row is None else row,'alo',CASE,info)

# A4R-03 with A4R2-04 (Task A5): the allow-list keys on the enclosing function chain (outer.inner), so the generic helper
# name `add` of oracle_gen.py covers exactly the BAW and the ALO edge-row helpers. A record site keeps a defect as a fixture
# or edge-row result: its handler names a record class (BawRunDefect or AloRunDefect, never the base class), binds the
# exception, uses the bound name, and holds only assignments, calls and returns. A marker site (ruling A4-C2) records a
# RunDefect raised inside a ql.Brent callback: `except RunDefect as e:` with exactly `<list>.append(e)` and a bare `raise`.
RECORD_SITES={('oracle.py','baw_edge_ok'),('oracle.py','alo_edge_ok'),('oracle_gen.py','baw_edge_rows.add'),('oracle_gen.py','alo_edge_rows.add'),
              ('alo.py','edge_vectors')}
MARKER_SITES={('library.py','brent_solve.marked')}
# Phase 2 record sites (Task A6 lock follow-up, controller-approved request of the Phase 2 session): handlers of
# optionlab/cvectors.py (Phase 2, not in every tree) that record a BawRunDefect as the expected C defect outcome. The same
# record-form rule applies to them whenever cvectors.py is present; the Phase 1 entries must name existing handlers.
PHASE2_RECORD_SITES={('cvectors.py','baw_engine_outcome'),('cvectors.py','baw_critical_outcome'),('cvectors.py','baw_greeks_outcome'),
                     ('cvectors.py','evaluate_baw_outcome'),('cvectors.py','census'),('cvectors.py','raising_models'),
                     ('cvectors.py','alo_outcome')}     # Task 10b: the one ALO record site of the C vectors (AloRunDefect)
PHASE1_RECORD_SITES=frozenset(RECORD_SITES)
RECORD_SITES=RECORD_SITES|PHASE2_RECORD_SITES
RECORD_CLASSES=('BawRunDefect','AloRunDefect')
OWNERS=(ast.FunctionDef,ast.AsyncFunctionDef,ast.Lambda)

def _handlers(tree):
    """(handler, enclosing function chain) of every except handler; module-level handlers have the chain ''. Functions,
    async functions and lambdas are owners (a lambda holds no handler, it only names the scope)."""
    out=[]
    def walk(node,chain):
        for child in ast.iter_child_nodes(node):
            if isinstance(child,OWNERS):
                name=getattr(child,'name','<lambda>');walk(child,f'{chain}.{name}' if chain else name)
            else:
                if isinstance(child,ast.ExceptHandler):out.append((child,chain))
                walk(child,chain)
    walk(tree,'');return out

def _uses(body,name):return any(isinstance(n,ast.Name) and n.id==name for s in body for n in ast.walk(s))

def reraise_violations(fname,source):
    """The A4R-03 rule (tightened by A4R2-04) on one source: every handler that names RunDefect (or a subclass) is exactly
    `except RunDefect:` with one bare `raise`, or a record site or marker site of the allow-lists with the restricted body.
    Returns the violations as 'file:line:type'."""
    bad=[]
    for h,chain in _handlers(ast.parse(source)):
        n=ast.unparse(h.type) if h.type else ''
        if 'RunDefect' not in n:continue
        body=h.body
        if n=='RunDefect' and len(body)==1 and isinstance(body[0],ast.Raise) and body[0].exc is None:continue
        if (fname,chain) in RECORD_SITES and n in RECORD_CLASSES and h.name is not None and _uses(body,h.name) \
           and all(isinstance(s,(ast.Assign,ast.Return)) or (isinstance(s,ast.Expr) and isinstance(s.value,ast.Call)) for s in body):continue
        if (fname,chain) in MARKER_SITES and n=='RunDefect' and h.name is not None and len(body)==2 and isinstance(body[1],ast.Raise) and body[1].exc is None \
           and isinstance(body[0],ast.Expr) and isinstance(body[0].value,ast.Call) and isinstance(body[0].value.func,ast.Attribute) \
           and body[0].value.func.attr=='append' and [ast.unparse(a) for a in body[0].value.args]==[h.name]:continue
        bad.append(f'{fname}:{h.lineno}:{n}')
    return bad

class AloReferenceTests(unittest.TestCase):
    def test_equation_switch_matches_quantlib(self):
        for v in checks.alo_switch_vectors(CASE):
            with self.subTest(v=v['name']):
                self.assertEqual(alo_equation.alo_equation(v['r1'],v['q1']),v['quantlib_equation'])
    def test_reference_equals_quantlib_bit_for_bit(self):
        r=checks.alo_alignment(CASE,grid=checks.ALIGN_GRID[:200])
        self.assertEqual((r['status'],r['mismatches']),('PASS',0))
    def test_call_is_the_exchanged_put(self):
        for S,K,T,r,q,s in ((100.0,90.0,0.5,0.03,0.01,0.25),(50.0,55.0,2.0,0.04,0.02,0.4)):
            self.assertEqual(alo.price('call',S,K,T,r,q,s,CASE),alo.price('put',K,S,T,q,r,s,CASE))
    def test_planted_nan_at_every_value_mask_is_a_run_defect(self):
        for site in alo.VALUE_MASK_SITES:
            with self.subTest(site=site),alo.plant_nan(site):
                with self.assertRaises(models.AloRunDefect):ev()
    def test_persistent_qdplus_nan_raises_at_the_first_halley_step(self):
        with alo.plant_nan('qdplus:66',persistent=True),alo.count_halley() as n:
            with self.assertRaises(models.AloRunDefect):ev()
        self.assertEqual(n.value,1)
    def test_inner_bracket_error_is_order_5(self):
        with alo.force_inner_bracket_error():
            self.assertEqual(ev()[0],'MODEL_DOMAIN')
    def test_cap_excess_is_a_run_defect(self):
        with alo.force_cap_excess('halley'):
            with self.assertRaises(models.AloRunDefect):ev()
    def test_run_defect_hierarchy(self):
        self.assertTrue(issubclass(models.BawRunDefect,models.RunDefect));self.assertTrue(issubclass(models.AloRunDefect,models.RunDefect))
        self.assertFalse(issubclass(models.RunDefect,models.ModelDefect))
    def test_every_handler_reraises_run_defect(self):
        bad=[]
        for f in PKG.glob('*.py'):
            for node in ast.walk(ast.parse(f.read_text())):
                if isinstance(node,ast.Try):
                    names=[ast.unparse(h.type) if h.type else '' for h in node.handlers]
                    risky=[i for i,n in enumerate(names) if n=='' or 'ModelDefect' in n or 'Exception' in n or 'ArithmeticError' in n]
                    if risky and not any('RunDefect' in n for n in names[:risky[0]]):bad.append(f'{f.name}:{node.lineno}')
        self.assertEqual(bad,[])
    # A4R-03: a re-raise clause takes the base class and its body is exactly one bare `raise`; the record sites (b)
    # (a defect kept as a fixture or edge-row result) are an explicit allow-list (file, function).
    def test_reraise_clauses_are_bare_raises_of_the_base_class(self):
        bad=[]
        for f in PKG.glob('*.py'):bad+=reraise_violations(f.name,f.read_text())
        self.assertEqual(sorted(set(bad)),[])
    def test_phase1_allow_list_names_existing_handlers(self):
        """The Phase 1 record and marker sites name a file of the package and an enclosing function chain that holds a
        handler; the Phase 2 group (cvectors.py) is checked the same way whenever that file is present."""
        sites=set(PHASE1_RECORD_SITES)|set(MARKER_SITES)
        if (PKG/'cvectors.py').is_file():sites|=PHASE2_RECORD_SITES
        for fname,chain in sorted(sites):
            with self.subTest(site=(fname,chain)):
                self.assertTrue((PKG/fname).is_file())
                self.assertIn(chain,{c for _,c in _handlers(ast.parse((PKG/fname).read_text()))})
    def test_phase2_sites_keep_the_record_form(self):
        ok='def census(rows):\n    try:f(rows)\n    except BawRunDefect as exc:\n        out.append(exc.args[0]);return\n    except RunDefect:raise\n'
        self.assertEqual(reraise_violations('cvectors.py',ok),[])
        for bad in ('def census(rows):\n    try:f(rows)\n    except BawRunDefect as exc:pass\n',
                    'def census(rows):\n    try:f(rows)\n    except RunDefect as exc:return exc.args\n',
                    'def other(rows):\n    try:f(rows)\n    except BawRunDefect as exc:return exc.args\n'):
            with self.subTest(src=bad):self.assertNotEqual(reraise_violations('cvectors.py',bad),[])
        self.assertNotEqual(reraise_violations('library.py','def census(rows):\n    try:f(rows)\n    except BawRunDefect as exc:return exc.args\n'),[])
    def test_reraise_rule_flags_seeded_sources(self):
        """A4R2-04 (carried to Task A5): the allow-list keys on the enclosing function chain, so a new helper named `add`
        in another function of oracle_gen.py is not covered; an allow-listed handler must name a record class (not the base
        class), bind the exception and use it, and hold only assignments, calls and returns; async functions and lambdas
        are owners too."""
        cases={
            'new add helper':('oracle_gen.py','def other_rows():\n    def add(row):\n        try:f(row)\n        except AloRunDefect as exc:return exc.args\n'),
            'record site swallows':('oracle.py','def alo_edge_ok(e,params):\n    try:f(e)\n    except AloRunDefect as exc:pass\n'),
            'record site base class':('oracle.py','def alo_edge_ok(e,params):\n    try:f(e)\n    except RunDefect as exc:return exc.args\n'),
            'record site unused name':('oracle.py','def alo_edge_ok(e,params):\n    try:f(e)\n    except AloRunDefect as exc:return True\n'),
            'async owner':('library.py','async def solve(x):\n    try:await f(x)\n    except (RunDefect,ValueError):raise\n'),
            'module level':('library.py','try:f()\nexcept RunDefect:pass\n'),
        }
        for name,(fname,src) in cases.items():
            with self.subTest(case=name):self.assertNotEqual(reraise_violations(fname,src),[])
        ok=('oracle_gen.py','def alo_edge_rows(params):\n    def add(name):\n        try:f(name)\n        except AloRunDefect as exc:\n            rows.append(exc.args[0]);return\n')
        self.assertEqual(reraise_violations(*ok),[])
        self.assertEqual(reraise_violations('library.py','async def solve(x):\n    try:await f(x)\n    except RunDefect:raise\n'),[])
    def test_engine_evals_follow_the_count_rule(self):
        info={};status,values,flags,evals=ev(info=info);self.assertEqual(status,'OK')
        self.assertEqual(evals,info['brent_evals']+alo.IV_CALL_TERM+info['stencil_points'])
    def test_every_handler_site_propagates_a_planted_run_defect(self):
        for site in alo.HANDLER_SITES:                          # the (c) sites of the Modify list, one entry each
            with self.subTest(site=site),alo.plant_run_defect(site):
                with self.assertRaises(models.RunDefect):alo.call_through(site)
    def test_baw_rows_unchanged_by_the_base_class_move(self):
        self.assertEqual(checks.baw_oracle_digest(),checks.BAW_ORACLE_DIGEST_14747B4)


class AloBoundaryTests(unittest.TestCase):
    """Added by the implementer: the European-edge value mask, the helper guard, the sigma_lo form, the segment tuple,
    the part B acceptance (Task A5), the record's ALO1-02 edge vectors (sub-hour T at sigma_lo and sigma_lo (1 +- 1e-3))."""
    def test_european_edge_nan_is_a_run_defect(self):
        row=(1,100.0,100.0,0.5,1.0,1.2,0.0,0.012)            # r <= 0 and r <= q: the European edge branch (qdplus:207)
        for site in alo.EUROPEAN_MASK_SITES:
            with self.subTest(site=site),alo.plant_nan(site):
                with self.assertRaises(models.AloRunDefect):ev(row)
    def test_helpers_refuse_without_the_test_variable(self):
        with mock.patch.dict(os.environ,{'SAFE_C_TEST_COUNTERS':'0'}):
            for cm in (lambda:alo.plant_nan('qdplus:66'),alo.count_halley,alo.force_inner_bracket_error,lambda:alo.force_cap_excess('halley'),
                       lambda:alo.plant_run_defect(alo.HANDLER_SITES[0])):
                with self.assertRaises(RuntimeError):
                    with cm():pass
    def test_sigma_lo_is_the_approved_closed_form(self):
        T=3600/31536000;s=models.sigma_lo('alo',1,T,0.04,0.012,CASE)
        self.assertEqual(s,max(1e-4,(0.75*max(0.0,(0.04-0.012)+1e-4))*math.sqrt(T)))
        self.assertEqual(models.sigma_lo('alo',0,3.0,0.04,0.012,CASE),max(1e-4,(0.003*max(0.0,(0.04-0.012)+1e-4))*math.sqrt(3.0)))
        self.assertEqual(models.sigma_lo('alo',0,0.5,0.04,0.012,CASE),1e-4)          # calls FP-A: d_A = q - r < 0
    def test_segment_tuple(self):
        self.assertEqual(alo_equation.alo_segment('put',0.04,0.012),('FP_B',False,False,1,False))
        self.assertEqual(alo_equation.alo_segment(1,0.0,0.012),('FP_B',True,False,4,None))
        self.assertEqual(alo_equation.alo_segment('call',0.0,0.012),('FP_B',False,False,2,None))      # the exchanged put: (q_e, r_e)
    def test_part_b_variants_accept_alo(self):
        """Task A5 (G-ALO2 part B) removed the part A refusal: py-library and py-optimized return an alo column."""
        from optionlab import optimized, library
        self.assertEqual(set(library.run([ROWS[0]],CASE,models=('alo',))['models']),{'alo'})
        from optionlab.contract import with_rates
        res=optimized.run(optimized.prepare(with_rates(load_chain(generate(4,1,CASE)),CASE.rate,CASE.dividend_yield)),CASE,models=('alo',))
        self.assertEqual(set(res['models']),{'alo'});self.assertEqual(res['n'],4)
    def test_aggregate_columns_stay_outside_the_digest(self):
        res=reference.run(ROWS[:4],CASE,models=('alo',));col=res['models']['alo']
        self.assertTrue(set(col['alo_equation'])<={'FP_A','FP_B',None});self.assertEqual(len(col['alo_nan_guarded']),4)
        stripped={'n':4,'models':{'alo':{k:v for k,v in col.items() if k not in ('alo_equation','alo_nan_guarded')}}}
        self.assertEqual(reference.canonical_result(res),reference.canonical_result(stripped))
        agg=reference.alo_aggregate(res)
        self.assertEqual(set(agg),{'reference_alo_equation','stencil_switched','stencil_unresolved','alo_nan_guarded'})
    def test_sub_hour_edge_vectors(self):
        """ALO1-02: T in (0, 1 h); sigma = sigma_lo and sigma_lo (1 +- 1e-3); FP-A puts (case rates), FP-B calls (test-only
        rates r = 0.002/T, q = 0, so |r' - q'| = 0.002 >= 0.001 below 1 h) and r = q. At an admitted sigma (>= sigma_lo) the shared NaN check
        must pass (no run defect); below sigma_lo the outcome is recorded (alo.edge_vectors)."""
        res=alo.edge_vectors(CASE)
        self.assertGreater(len(res),0)
        bad=[v for v in res if v['admitted'] and v['outcome']!='value']
        self.assertEqual(bad,[])
        self.assertTrue(any(v['equation']=='FP_B' for v in res));self.assertTrue(any(v['equation']=='FP_A' for v in res))

class AloStatsPerCallTests(unittest.TestCase):
    """A4R-06 (carried to Task A5): the engine statistics are per call. A thread reads the statistics of its own last engine
    evaluation (alo.last_stats), never those of another thread's later evaluation, and alo.price_stats returns the
    statistics object of that one call, which no later call changes."""
    A=(1,100.0,100.0,0.5,0.04,0.012,0.3)                 # put, FP-B
    B=(0,90.0,100.0,7/365,0.04,0.012,0.6)                # call, FP-A: other counts than A
    FIELDS=('qd_calls','halley_max','fallback_nodes','fallback_max','levels','integrand','guarded','equation')
    def snap(self,st):return tuple(getattr(st,k) for k in self.FIELDS)
    def test_last_stats_belong_to_the_calling_thread(self):
        import threading
        alo.price(*self.A,CASE);want_a=self.snap(alo.last_stats())
        alo.price(*self.B,CASE);want_b=self.snap(alo.last_stats())
        self.assertNotEqual(want_a,want_b)
        a_done=threading.Event();b_done=threading.Event();got={}
        def thread_a():
            alo.price(*self.A,CASE);a_done.set();b_done.wait(60);got['a']=self.snap(alo.last_stats())
        def thread_b():
            a_done.wait(60);alo.price(*self.B,CASE);got['b']=self.snap(alo.last_stats());b_done.set()
        ts=[threading.Thread(target=thread_a),threading.Thread(target=thread_b)]
        for x in ts:x.start()
        for x in ts:x.join(120)
        self.assertEqual(got,{'a':want_a,'b':want_b})
    def test_price_stats_returns_the_statistics_of_that_call(self):
        v,st=alo.price_stats(*self.A,CASE)
        self.assertEqual(v,alo.price(*self.A,CASE));kept=self.snap(st)
        _,other=alo.price_stats(*self.B,CASE)
        self.assertIsNot(st,other);self.assertEqual(self.snap(st),kept)
        self.assertEqual(st.equation,'FP_B');self.assertEqual(other.equation,'FP_A')

if __name__=='__main__':unittest.main()
