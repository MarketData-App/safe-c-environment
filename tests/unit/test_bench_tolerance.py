"""Tolerance calibration tool (tools/bench_tolerance.py): calibrated tolerances from recorded spreads, generic.

The field names come from the project protocol `tolerances` and the spread file, the variant names from the spread file
(the run records of the project's check). The framework names no field. The tool never widens a value: `proposed` is the
current value or None with a reason. A lock record is the protocol `tolerances` block with `state: locked-<label>` and
the approval reference (FR3 rule: the bare state `locked` is refused). Every malformed input gives GateError (exit 2).
The current values come from the bench-project fixture protocol; every spread is synthetic and lives in a temporary root."""
import argparse, contextlib, copy, hashlib, io, json, math, shutil, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import bench, bench_model as bm
import bench_tolerance as bt
from evidence import GateError
from schema_check import validate

FIXTURE='tests/fixtures/bench-project'

def spread_doc(fields):
    """A spread file: {field: (oracle_error, {variant: (max_abs, samples)})}."""
    return {'schema_version':1,'fields':{f:{'oracle_error':o,'variants':{v:{'max_abs':m,'samples':n} for v,(m,n) in vs.items()}}
                                         for f,(o,vs) in fields.items()}}

def fixture_tolerances():
    return copy.deepcopy(bm.load_protocol(ROOT,FIXTURE)['tolerances'])

def good_fixture_spread():
    """Every numeric field of the fixture protocol except the zero-valued ones (m4.terms.a, m4.terms.b), below its value."""
    return spread_doc({'abs':(1e-6,{'v-one':(2e-12,10),'v-two':(5e-12,3)}),
                       'm4.abs':(1e-6,{'v-one':(1e-12,1)}),
                       'm5.abs':(1e-6,{'v-one':(0.0,4)})})

class ProposeTests(unittest.TestCase):
    def test_keeps_a_value_between_spread_and_oracle(self):
        p=bt.propose({'f_abs':2e-12},{'f_abs':1e-6},current={'f_abs':1e-8})
        self.assertEqual(p['f_abs']['proposed'],1e-8)
        self.assertEqual(p['f_abs']['measured'],2e-12)
        self.assertEqual(p['f_abs']['margin_low'],1e-8/2e-12)          # hand-computed: 5000
        self.assertEqual(p['f_abs']['margin_high'],1e-6/1e-8)          # hand-computed: 100
        self.assertAlmostEqual(p['f_abs']['margin_low'],5000.0,places=6);self.assertAlmostEqual(p['f_abs']['margin_high'],100.0,places=9)

    def test_measured_is_the_largest_spread_over_all_variants(self):
        p=bt.propose({'f':{'v-a':1e-12,'v-b':4e-12,'v-c':3e-12}},{'f':1e-6},current={'f':1e-8})
        self.assertEqual(p['f']['measured'],4e-12);self.assertEqual(p['f']['worst_variant'],'v-b')
        self.assertEqual(p['f']['margin_low'],1e-8/4e-12)

    def test_never_widens_automatically(self):
        for measured in (2e-8,1e-8):            # above and exactly at the current value: strict inequality
            with self.subTest(measured=measured):
                p=bt.propose({'f':measured},{'f':1e-6},current={'f':1e-8})
                self.assertIsNone(p['f']['proposed']);self.assertIn('spread',p['f']['reason'])
                self.assertIsNone(p['f']['margin_low']);self.assertIsNone(p['f']['margin_high'])

    def test_a_current_value_at_or_above_the_oracle_bound_is_not_proposed(self):
        for oracle in (1e-8,1e-9):
            with self.subTest(oracle=oracle):
                p=bt.propose({'f':1e-12},{'f':oracle},current={'f':1e-8})
                self.assertIsNone(p['f']['proposed']);self.assertIn('oracle',p['f']['reason'])

    def test_a_locked_field_keeps_its_value_and_never_gets_a_new_one(self):
        p=bt.propose({'m.f':2e-12},{'m.f':1e-6},current={'m.f':1e-8},locked={'m.f'})
        self.assertEqual(p['m.f']['proposed'],1e-8);self.assertTrue(p['m.f']['locked'])
        q=bt.propose({'m.f':2e-8},{'m.f':1e-6},current={'m.f':1e-8},locked={'m.f'})
        self.assertIsNone(q['m.f']['proposed']);self.assertIn('locked',q['m.f']['reason'])

    def test_one_sample_and_zero_spread(self):
        p=bt.calibrate(spread_doc({'f':(1e-6,{'v':(3e-12,1)})}),{'f':1e-8})
        self.assertEqual(p['fields']['f']['proposed'],1e-8);self.assertEqual(p['fields']['f']['samples'],1)
        z=bt.propose({'f':0.0},{'f':1e-6},current={'f':1e-8})
        self.assertEqual(z['f']['proposed'],1e-8);self.assertEqual(z['f']['measured'],0.0)
        self.assertIsNone(z['f']['margin_low']);self.assertEqual(z['f']['margin_high'],1e-6/1e-8)   # unbounded low margin: None
        zero=bt.propose({'f':0.0},{'f':1e-6},current={'f':0})
        self.assertIsNone(zero['f']['proposed']);self.assertIn('spread',zero['f']['reason'])       # a zero tolerance is never kept

    def test_missing_spread_oracle_or_current_value_gives_no_proposal(self):
        p=bt.propose({'a':1e-12,'b':1e-12},{'a':1e-6,'c':1e-6},current={'b':1e-8,'c':1e-8})
        self.assertIn('current',p['a']['reason']);self.assertIn('oracle',p['b']['reason']);self.assertIn('spread',p['c']['reason'])
        self.assertTrue(all(p[k]['proposed'] is None for k in 'abc'))

    def test_propose_without_current_values_uses_an_empty_set(self):
        # EX15-PROPOSE-DEFAULT-01: the source interface propose(spread, oracle) works; no field has a current value
        for p in (bt.propose({'f':1e-12},{'f':1e-6}),bt.propose({'f':1e-12},{'f':1e-6},current=None)):
            self.assertIsNone(p['f']['proposed']);self.assertIn('current',p['f']['reason']);self.assertIsNone(p['f']['current'])

    def test_an_overflowing_margin_is_none(self):
        p=bt.propose({'f':5e-324},{'f':1e300},current={'f':1.0})              # 1/5e-324 overflows to inf
        self.assertEqual(p['f']['proposed'],1.0);self.assertIsNone(p['f']['margin_low']);self.assertEqual(p['f']['margin_high'],1e300)
        q=bt.propose({'f':0.0},{'f':1e300},current={'f':1e-300})              # 1e300/1e-300 overflows to inf
        self.assertEqual(q['f']['proposed'],1e-300);self.assertIsNone(q['f']['margin_low']);self.assertIsNone(q['f']['margin_high'])

    def test_malformed_direct_inputs_are_gate_errors(self):
        nan,inf=float('nan'),float('inf')
        cases=[({'f':nan},{'f':1e-6},{'f':1e-8}),({'f':inf},{'f':1e-6},{'f':1e-8}),({'f':1e-12},{'f':nan},{'f':1e-8}),
               ({'f':1e-12},{'f':1e-6},{'f':inf}),({'f':-1e-12},{'f':1e-6},{'f':1e-8}),({'f':True},{'f':1e-6},{'f':1e-8}),
               ({'f':'x'},{'f':1e-6},{'f':1e-8}),({'f':10**400},{'f':1e-6},{'f':1e-8}),({'f':{}},{'f':1e-6},{'f':1e-8}),
               ({'f':{'v':nan}},{'f':1e-6},{'f':1e-8}),({'F':1e-12},{'F':1e-6},{'F':1e-8}),(['f'],{'f':1e-6},{'f':1e-8}),
               ({'f':1e-12},{'f':1e-6},'x'),({'f':1e-12},{'f':1e-6},[1e-8]),({'f':{'Bad Variant':1e-12}},{'f':1e-6},{'f':1e-8})]
        for spread,oracle,current in cases:
            with self.subTest(spread=repr(spread)[:40],oracle=repr(oracle)[:40]),self.assertRaises(GateError):
                bt.propose(spread,oracle,current=current)
        with self.assertRaises(GateError):bt.propose({'f':1e-12},{'f':1e-6},current={'f':1e-8},locked='f')

    def test_field_and_variant_counts_are_bounded(self):
        many={f'f{i}':1e-12 for i in range(bt.MAX_FIELDS+1)}
        with self.assertRaises(GateError):bt.propose(many,{k:1e-6 for k in many},current={k:1e-8 for k in many})
        ok={f'f{i}':1e-12 for i in range(bt.MAX_FIELDS)}
        self.assertEqual(len(bt.propose(ok,{k:1e-6 for k in ok},current={k:1e-8 for k in ok})),bt.MAX_FIELDS)
        wide={'f':{f'v{i}':1e-12 for i in range(bt.MAX_VARIANTS+1)}}
        with self.assertRaises(GateError):bt.propose(wide,{'f':1e-6},current={'f':1e-8})

class SpreadFileTests(unittest.TestCase):
    def test_a_good_spread_validates_and_calibrates(self):
        doc=good_fixture_spread();validate(ROOT,'bench-tolerance-spread',doc);bt.check_spread(doc)
        p=bt.calibrate(doc,fixture_tolerances())
        f=p['fields']
        self.assertEqual(f['abs']['measured'],5e-12);self.assertEqual(f['abs']['worst_variant'],'v-two');self.assertEqual(f['abs']['samples'],13)
        self.assertEqual(f['abs']['proposed'],1e-9);self.assertFalse(f['abs']['locked'])
        self.assertTrue(f['m4.abs']['locked']);self.assertTrue(f['m5.abs']['locked'])        # locked-fixture blocks of the protocol
        self.assertEqual(f['m4.abs']['proposed'],1e-9);self.assertEqual(f['m5.abs']['proposed'],1e-9)
        for zero in ('m4.terms.a','m4.terms.b'):self.assertIsNone(f[zero]['proposed'])        # current 0, no spread
        self.assertEqual(p['status'],'FAIL');self.assertEqual(p['unproposed'],['m4.terms.a','m4.terms.b'])
        validate(ROOT,'bench-tolerance-proposal',p)

    def test_the_protocol_tolerance_walk_names_fields_by_their_protocol_path(self):
        current,locked=bt.current_fields(fixture_tolerances())
        self.assertEqual(current,{'abs':1e-9,'m4.abs':1e-9,'m4.terms.a':0,'m4.terms.b':0,'m5.abs':1e-9})
        self.assertEqual(locked,{'m4.abs','m4.terms.a','m4.terms.b','m5.abs'})
        with self.assertRaises(GateError):bt.current_fields([1])

    def test_a_lock_exists_only_in_a_selector_block_with_an_approval_reference(self):
        # EX15-TOPLOCK-01 (ruling EX15-R2): a locked- state is a lock only inside a selector block with a valid approval
        # reference; every other locked state is refused, so no state can skip the oracle bound check without approval
        ok={'m':{'state':'locked-x','approval':'fixture-ref-0001','abs':1e-9},'abs':1e-9,'state':'provisional-x'}
        self.assertEqual(bt.current_fields(ok),({'m.abs':1e-9,'abs':1e-9},{'m.abs'}))
        refused=[{'state':'locked-x','approval':'fixture-ref-0001','abs':1e-9},       # a top-level lock, approved or not
                 {'state':'locked-x','abs':1e-9},{'state':'locked','abs':1e-9},
                 {'m':{'state':'locked-x','abs':1e-9}},                                # a selector lock without approval
                 {'m':{'state':'locked-x','approval':'short','abs':1e-9}},            # an invalid approval reference
                 {'m':{'state':'locked-x','approval':7,'abs':1e-9}},
                 {'m':{'state':'locked','approval':'fixture-ref-0001','abs':1e-9}},  # the bare state locked
                 {'m':{'state':'other','abs':1e-9}},
                 {'m':{'g':{'state':'locked-x','approval':'fixture-ref-0001','a':1e-9}}}]   # a lock below a selector block
        for tol in refused:
            with self.subTest(tol=tol),self.assertRaises(GateError):bt.current_fields(tol)
        with self.assertRaises(GateError):
            bt.calibrate(spread_doc({'abs':(1e-10,{'v':(1e-12,1)})}),{'state':'locked-x','abs':1e-9})   # no oracle bypass

    def test_calibrate_takes_its_locks_only_from_the_approved_protocol_blocks(self):
        # EX15-CALLOCK-01: a caller cannot add a lock to calibrate, so no field skips the oracle bound check without the
        # approval reference of its selector block; the pure kernel propose keeps its locked parameter
        import inspect
        self.assertEqual(list(inspect.signature(bt.calibrate).parameters),['doc','tolerances'])
        self.assertIn('locked',inspect.signature(bt.propose).parameters)
        doc=spread_doc({'m.abs':(1e-9,{'v':(1e-12,1)})})          # the current value 1e-8 reaches the oracle bound 1e-9
        unlocked={'m':{'state':'provisional-x','abs':1e-8}}
        for locked in ({'m.abs'},['m.abs'],'m.abs',frozenset()):
            with self.subTest(locked=locked),self.assertRaises(TypeError):bt.calibrate(doc,unlocked,locked=locked)
        with self.assertRaises(TypeError):bt.calibrate(doc,unlocked,{'m.abs'})
        row=bt.calibrate(doc,unlocked)['fields']['m.abs']
        self.assertIsNone(row['proposed']);self.assertFalse(row['locked']);self.assertIn('oracle',row['reason'])
        row=bt.calibrate(doc,{'m':{'state':'locked-x','approval':'fixture-ref-0001','abs':1e-8}})['fields']['m.abs']   # the control
        self.assertEqual(row['proposed'],1e-8);self.assertTrue(row['locked'])

    def test_malformed_spread_documents_are_refused_by_the_check_and_the_schema(self):
        good=good_fixture_spread()
        def edit(fn):
            d=copy.deepcopy(good);fn(d);return d
        bad=[edit(lambda d:d.update(schema_version=2)),edit(lambda d:d.pop('fields')),edit(lambda d:d.update(fields={})),
             edit(lambda d:d.update(extra=1)),edit(lambda d:d['fields']['abs'].pop('oracle_error')),
             edit(lambda d:d['fields']['abs'].update(variants={})),
             edit(lambda d:d['fields']['abs']['variants']['v-one'].update(samples=0)),
             edit(lambda d:d['fields']['abs']['variants']['v-one'].update(samples=bt.MAX_SAMPLES+1)),
             edit(lambda d:d['fields']['abs']['variants']['v-one'].update(samples=10**400)),
             edit(lambda d:d['fields']['abs']['variants']['v-one'].update(samples=1.5)),
             edit(lambda d:d['fields']['abs']['variants']['v-one'].update(max_abs=-1.0)),
             edit(lambda d:d['fields']['abs']['variants']['v-one'].update(max_abs='0')),
             edit(lambda d:d['fields']['abs']['variants']['v-one'].update(extra=1)),
             edit(lambda d:d['fields']['abs'].update(oracle_error=-1.0)),
             edit(lambda d:d['fields'].update({'a.b.c.d':d['fields']['abs']})),
             edit(lambda d:d['fields'].update({'Abs':d['fields']['abs']})),
             edit(lambda d:d['fields'].update({f'f{i}':d['fields']['abs'] for i in range(bt.MAX_FIELDS)}))]
        for i,doc in enumerate(bad):
            with self.subTest(case=i):
                with self.assertRaises(GateError):bt.check_spread(doc)
                with self.assertRaises(GateError):validate(ROOT,'bench-tolerance-spread',doc)
        for doc in ([],None,'x',{'schema_version':1,'fields':[]}):
            with self.subTest(doc=repr(doc)),self.assertRaises(GateError):bt.check_spread(doc)

    def test_the_largest_sample_count_is_accepted(self):
        doc=spread_doc({'f':(1e-6,{'v-a':(1e-12,bt.MAX_SAMPLES),'v-b':(1e-12,bt.MAX_SAMPLES)})})
        bt.check_spread(doc);validate(ROOT,'bench-tolerance-spread',doc)
        self.assertEqual(bt.calibrate(doc,{'f':1e-8})['fields']['f']['samples'],2*bt.MAX_SAMPLES)

class LockRecordTests(unittest.TestCase):
    def test_lock_record_needs_a_reference(self):
        for ref in ('','short',None,'has space here','x'*161):
            with self.subTest(ref=ref),self.assertRaises(ValueError):bt.lock_record({'m.f':{'proposed':1e-8}},ref)
        rec=bt.lock_record({'m.f':{'proposed':1e-8}},'fixture-calibration-r1-abc',label='phase-two')
        self.assertEqual(rec,{'m':{'state':'locked-phase-two','approval':'fixture-calibration-r1-abc','f':1e-8}})

    def test_lock_record_refuses_a_bare_or_bad_label_and_an_unproposed_field(self):
        for label in ('','Locked','-x','a'*40,None):
            with self.subTest(label=label),self.assertRaises(ValueError):bt.lock_record({'m.f':{'proposed':1e-8}},'fixture-ref-0001',label=label)
        with self.assertRaises(ValueError):bt.lock_record({'m.f':{'proposed':None,'reason':'spread'}},'fixture-ref-0001')
        with self.assertRaises(ValueError):bt.lock_record({},'fixture-ref-0001')
        with self.assertRaises(ValueError):bt.lock_record({'m.f':{'proposed':float('nan')}},'fixture-ref-0001')

    def test_lock_record_never_widens_and_needs_every_field_of_a_locked_block(self):
        tol=fixture_tolerances()
        with self.assertRaises(ValueError):bt.lock_record({'m5.abs':{'proposed':2e-9}},'fixture-ref-0001',tolerances=tol)  # wider
        with self.assertRaises(ValueError):bt.lock_record({'m4.abs':{'proposed':1e-9}},'fixture-ref-0001',tolerances=tol)   # m4.terms.* missing
        with self.assertRaises(ValueError):bt.lock_record({'zz.abs':{'proposed':1e-9}},'fixture-ref-0001',tolerances=tol)   # not a protocol field

    def test_lock_record_refuses_a_top_level_field(self):
        # EX15-TOPLOCK-01 (ruling EX15-R2): a lock exists only inside a selector block; a top-level field is refused with
        # a GateError (exit 2) that names the selector block, with or without the protocol tolerances
        tol=fixture_tolerances()
        for args in (({'abs':{'proposed':1e-9}},),({'abs':{'proposed':1e-9},'m5.abs':{'proposed':1e-9}},)):
            for kw in ({},{'tolerances':tol}):
                with self.subTest(fields=sorted(args[0]),kw=sorted(kw)):
                    with self.assertRaisesRegex(GateError,'selector block'):bt.lock_record(*args,'fixture-ref-0001',**kw)

    def test_lock_record_refuses_a_value_that_the_record_would_drop(self):
        # EX15-LOCKREC-01: the record writes state and approval into each block, so a proposed <block>.state or
        # <block>.approval field (or a group of that name), a field that is a path prefix of another field, and a
        # numeric approval are refused (GateError), never silently overwritten
        for fields in ({'m.state':1e-9},{'m.approval':1e-9},{'m.abs':1e-9,'m.state':1e-9},{'m.abs':1e-9,'m.approval':1e-9},
                       {'m.state.a':1e-9},{'m.approval.a':1e-9},
                       {'m.g.a':1e-9,'m.g':1e-9},{'m.g':1e-9,'m.g.a':1e-9}):        # the prefix in both orders
            proposal={n:{'proposed':v} for n,v in fields.items()}
            with self.subTest(fields=list(fields)),self.assertRaises(GateError):bt.lock_record(proposal,'fixture-ref-0001')
        for tol in ({'m':{'approval':7,'abs':1e-8}},{'m':{'state':'provisional-x','approval':7.5,'abs':1e-8}},
                    {'m':{'approval':True,'abs':1e-8}},{'m':{'approval':None,'abs':1e-8}}):
            with self.subTest(tol=tol):
                with self.assertRaises(GateError):bt.current_fields(tol)      # the schema refuses a non-string approval too
                with self.assertRaises(GateError):
                    bt.lock_record({'m.abs':{'proposed':1e-8},'m.approval':{'proposed':7}},'fixture-ref-0001',tolerances=tol)
                with self.assertRaises(GateError):bt.calibrate(spread_doc({'m.abs':(1e-6,{'v':(1e-12,1)})}),tol)
        # the controls: a third-level field named state keeps its value, and a block with a string approval locks
        rec=bt.lock_record({'m.g.state':{'proposed':1e-9},'m.abs':{'proposed':1e-9}},'fixture-ref-0001')
        self.assertEqual(rec,{'m':{'state':'locked-calibrated','approval':'fixture-ref-0001','abs':1e-9,'g':{'state':1e-9}}})
        proto=bm.load_protocol(ROOT,FIXTURE);validate(ROOT,'bench-protocol',dict(proto,tolerances=rec))
        tol={'m':{'state':'provisional-x','approval':'fixture-ref-0002','abs':1e-8}}
        self.assertEqual(bt.current_fields(tol),({'m.abs':1e-8},set()))
        rec=bt.lock_record({'m.abs':{'proposed':1e-8}},'fixture-ref-0001',tolerances=tol)
        self.assertEqual(rec,{'m':{'state':'locked-calibrated','approval':'fixture-ref-0001','abs':1e-8}})

    def test_the_lock_record_is_accepted_by_the_protocol_grammar_and_enforced(self):
        tol=fixture_tolerances()
        rec=bt.lock_record({'m5.abs':{'proposed':5e-10}},'fixture-calibration-r1-abc',tolerances=tol,label='calibrated')  # m5 tightened
        self.assertEqual(rec['m5'],{'state':'locked-calibrated','approval':'fixture-calibration-r1-abc','abs':5e-10})
        self.assertEqual(rec['state'],tol['state']);self.assertNotIn('approval',rec)       # the top level is never locked
        self.assertEqual(rec['m4'],tol['m4']);self.assertEqual(rec['abs'],tol['abs'])        # untouched values stay as they are
        self.assertEqual(tol,fixture_tolerances())                                # the input is never changed
        proto=bm.load_protocol(ROOT,FIXTURE);validate(ROOT,'bench-protocol',dict(proto,tolerances=rec))
        bm.require_locked_selectors({'tolerances':rec},['m5'])
        long='r'*160
        only=bt.lock_record({'m5.abs':{'proposed':1e-9}},long,tolerances=tol)
        self.assertEqual(only['m5']['approval'],long);validate(ROOT,'bench-protocol',dict(proto,tolerances=only))
        prov=dict(rec,m5={'state':'provisional-calibrated','abs':5e-10})
        with self.assertRaises(GateError):bm.require_locked_selectors({'tolerances':prov},['m5'])     # not locked: refused
        for bad in (dict(rec,m5={'state':'locked','approval':'fixture-calibration-r1-abc','abs':5e-10}),
                    dict(rec,m5={'state':'locked-calibrated','abs':5e-10})):                  # bare state; no approval
            with self.subTest(bad=bad['m5']):
                with self.assertRaises(GateError):validate(ROOT,'bench-protocol',dict(proto,tolerances=bad))
                with self.assertRaises(GateError):bt.current_fields(bad)
        with self.assertRaises(GateError):bm.require_locked_selectors({'tolerances':dict(rec,m5={'state':'locked-calibrated','abs':5e-10})},['m5'])

    def test_the_protocol_grammar_refuses_a_top_level_lock(self):
        # EX15-TOPLOCK-01 (ruling EX15-R2): a top-level locked state is refused (GateError, exit 2), with or without approval
        proto=bm.load_protocol(ROOT,FIXTURE)
        for top in ({'state':'locked-x','approval':'fixture-ref-0001','abs':1e-9},{'state':'locked-x','abs':1e-9},
                    {'state':'locked','abs':1e-9}):
            with self.subTest(top=top),self.assertRaises(GateError):validate(ROOT,'bench-protocol',dict(proto,tolerances=top))
        validate(ROOT,'bench-protocol',dict(proto,tolerances={'state':'provisional-x','abs':1e-9}))

def scratch(test):
    """A temporary root: the schemas, the framework policy, the developer lock, an empty framework cases directory and a
    byte copy of the fixture project."""
    t=Path(tempfile.mkdtemp(prefix='safe-c-tolerance-'));test.addCleanup(shutil.rmtree,t,True)
    shutil.copytree(ROOT/'schemas',t/'schemas');(t/'safety').mkdir()
    for rel in ('safety/performance-policy.json','developer.lock.json'):shutil.copyfile(ROOT/rel,t/rel)
    (t/bm.CASES).mkdir(parents=True);shutil.copytree(ROOT/FIXTURE,t/FIXTURE)
    return t

class ToleranceCliTests(unittest.TestCase):
    def run_cli(self,root,*argv):
        p=argparse.ArgumentParser();bench.configure_parser(p);args=p.parse_args(['tolerance',*argv,'--format','json'])
        out=io.StringIO()
        with contextlib.redirect_stdout(out):rc=bench.execute(root,args)
        return rc,json.loads(out.getvalue().strip().splitlines()[-1])

    def test_the_cli_writes_the_proposal_of_a_complete_spread(self):
        t=scratch(self);doc=good_fixture_spread()
        for f in ('m4.terms.a','m4.terms.b'):doc['fields'][f]={'oracle_error':1e-6,'variants':{'v-one':{'max_abs':0.0,'samples':1}}}
        (t/'spread.json').write_text(json.dumps(doc))
        rc,out=self.run_cli(t,'--spread','spread.json','--project',FIXTURE)
        self.assertEqual((rc,out['status']),(1,'FAIL'))             # the zero fields: a zero tolerance is never kept
        self.assertEqual(out['unproposed'],['m4.terms.a','m4.terms.b'])
        rec=json.loads(Path(out['proposal']).read_text());validate(t,'bench-tolerance-proposal',rec)
        self.assertEqual(Path(out['proposal']).name,'tolerance-proposal.json');self.assertEqual(Path(out['proposal']).parent.parent,t/'artifacts/bench')
        self.assertEqual(rec['spread_sha256'],hashlib.sha256((t/'spread.json').read_bytes()).hexdigest())
        self.assertEqual(rec['protocol_sha256'],bm.protocol_digest(t,FIXTURE));self.assertEqual(rec['project'],FIXTURE)

    def set_tolerances(self,t,tolerances):
        """A reviewed edit of the fixture protocol in the scratch root: new tolerances, the new sha256 bound in bench.json
        and in the approval record. Returns the protocol path."""
        p=t/FIXTURE/bm.PROJECT_AREA/bm.PROTOCOL_FILE;proto=json.loads(p.read_text());proto['tolerances']=tolerances
        p.write_text(json.dumps(proto));digest=hashlib.sha256(p.read_bytes()).hexdigest()
        decl=t/FIXTURE/bm.PROJECT_AREA/'bench.json';d=json.loads(decl.read_text());d['protocol']['sha256']=digest;decl.write_text(json.dumps(d))
        rec=json.loads((t/FIXTURE/bm.PROJECT_AREA/bm.PROTOCOL_APPROVAL_FILE).read_text());rec['protocol_sha256']=digest
        (t/FIXTURE/bm.PROJECT_AREA/bm.PROTOCOL_APPROVAL_FILE).write_text(json.dumps(rec))
        return p

    def test_the_cli_writes_a_lock_record_only_for_a_full_proposal(self):
        t=scratch(self);doc=spread_doc({'m1.abs':(1e-6,{'v-one':(2e-12,10)}),'m5.abs':(1e-6,{'v-one':(1e-12,2)})})
        p=self.set_tolerances(t,{'m1':{'state':'provisional-fixture','abs':1e-9},'m5':{'state':'provisional-fixture','abs':1e-9}})
        (t/'spread.json').write_text(json.dumps(doc))
        rc,out=self.run_cli(t,'--spread',str(t/'spread.json'),'--project',FIXTURE,'--approval','fixture-calibration-r1-abc','--label','calibrated')
        self.assertEqual((rc,out['status']),(0,'PASS'))
        lock=json.loads(Path(out['lock']).read_text())
        for s in ('m1','m5'):self.assertEqual(lock[s],{'state':'locked-calibrated','approval':'fixture-calibration-r1-abc','abs':1e-9})
        self.assertEqual(sorted(lock),['m1','m5'])
        self.assertEqual(json.loads(p.read_text())['tolerances']['m5']['state'],'provisional-fixture')     # the protocol is never edited
        (t/'wide.json').write_text(json.dumps(spread_doc({'m1.abs':(1e-6,{'v-one':(2e-9,10)}),'m5.abs':(1e-6,{'v-one':(1e-12,2)})})))
        rc,out=self.run_cli(t,'--spread','wide.json','--project',FIXTURE,'--approval','fixture-calibration-r1-abc')
        self.assertEqual((rc,out['status']),(1,'FAIL'));self.assertNotIn('lock',out);self.assertEqual(out['unproposed'],['m1.abs'])

    def test_the_cli_refuses_a_top_level_lock(self):
        # EX15-TOPLOCK-01 (ruling EX15-R2): a full proposal with a top-level field gets no lock (GateError, exit 2), and a
        # protocol with a top-level locked state is refused (exit 2)
        t=scratch(self);doc=spread_doc({'abs':(1e-6,{'v-one':(2e-12,10)}),'m5.abs':(1e-6,{'v-one':(1e-12,2)})})
        self.set_tolerances(t,{'abs':1e-9,'m5':{'state':'provisional-fixture','abs':1e-9}})
        (t/'spread.json').write_text(json.dumps(doc))
        rc,out=self.run_cli(t,'--spread','spread.json','--project',FIXTURE)
        self.assertEqual((rc,out['status']),(0,'PASS'))                       # the proposal itself is complete
        rc,out=self.run_cli(t,'--spread','spread.json','--project',FIXTURE,'--approval','fixture-calibration-r1-abc')
        self.assertEqual((rc,out['status']),(2,'BLOCKED'));self.assertIn('selector block',out['reason'])
        self.assertFalse(any((t/'artifacts/bench').rglob('tolerance-lock.json')))
        for top in ({'state':'locked-x','approval':'fixture-ref-0001','abs':1e-9,'m5':{'state':'provisional-fixture','abs':1e-9}},
                    {'state':'locked-x','abs':1e-9,'m5':{'state':'provisional-fixture','abs':1e-9}}):
            with self.subTest(top=sorted(top)):
                self.set_tolerances(t,top)
                rc,out=self.run_cli(t,'--spread','spread.json','--project',FIXTURE)
                self.assertEqual((rc,out['status']),(2,'BLOCKED'))

    def test_malformed_files_and_arguments_are_blocked(self):
        t=scratch(self)
        texts={'nan.json':'{"schema_version":1,"fields":{"abs":{"oracle_error":NaN,"variants":{"v":{"max_abs":0,"samples":1}}}}}',
               'inf.json':'{"schema_version":1,"fields":{"abs":{"oracle_error":1e999,"variants":{"v":{"max_abs":0,"samples":1}}}}}',
               'dup.json':'{"schema_version":1,"schema_version":1,"fields":{}}','deep.json':'['*100000+']'*100000,
               'text.json':'not json','bin.json':b'\xff\xfe'.decode('latin-1'),
               'huge.json':'{"schema_version":1,"fields":{"abs":{"oracle_error":1,"variants":{"v":{"max_abs":0,"samples":'+'9'*500+'}}}}}'}
        for name,text in texts.items():(t/name).write_bytes(text.encode('latin-1'))
        (t/'big.json').write_bytes(b' '*(bt.SPREAD_MAX_BYTES+1))
        (t/'link.json').symlink_to(t/'nan.json')
        for name in [*texts,'big.json','link.json','missing.json']:
            with self.subTest(name=name):
                rc,out=self.run_cli(t,'--spread',name,'--project',FIXTURE)
                self.assertEqual((rc,out['status']),(2,'BLOCKED'))
        (t/'ok.json').write_text(json.dumps(good_fixture_spread()))
        rc,out=self.run_cli(t,'--spread','ok.json')                                   # no project
        self.assertEqual(rc,2)
        rc,out=self.run_cli(t,'--spread','ok.json','--project',FIXTURE,'--approval','bad ref')
        self.assertEqual(rc,2)
        self.assertFalse((t/'artifacts/bench').exists() and any((t/'artifacts/bench').rglob('tolerance-lock.json')))

if __name__=='__main__':unittest.main()
