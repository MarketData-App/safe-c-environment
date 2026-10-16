"""FR3 (FS1 F5, design Task 32): the per-project protected protocol file.

A project brings its own protected data (models, oracle file, tolerances, solver constants, planning shares, decision
policies, required before_run checks) in <project>/benchmarks/project/protocol/protocol.json. The framework validates it
against schemas/bench-protocol.json, bench.json binds it by sha256, it binds each referenced file by sha256, bench run
records its digest in run.json and decide refuses a run whose recorded digest differs from the current file. An unbound,
missing or edited protocol is refused. Every mutation runs in a temporary root; the tree is never changed."""
import copy, hashlib, json, shutil, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import bench_model as bm
from evidence import GateError, file_hash, read_json

FIXTURE='tests/fixtures/bench-project';DEMO='examples/bench-demo';POLICY='fixture-request-threshold'

def scratch(test,project=FIXTURE):
    """A temporary root: the schemas, the framework policy, the developer lock, an empty framework cases directory and a
    byte copy of `project`."""
    t=Path(tempfile.mkdtemp(prefix='safe-c-protocol-'));test.addCleanup(shutil.rmtree,t,True)
    shutil.copytree(ROOT/'schemas',t/'schemas');(t/'safety').mkdir()
    for rel in ('safety/performance-policy.json','developer.lock.json'):shutil.copyfile(ROOT/rel,t/rel)
    (t/bm.CASES).mkdir(parents=True);shutil.copytree(ROOT/project,t/project)
    return t

def area(t,project=FIXTURE):return Path(t)/project/bm.PROJECT_AREA

def protocol(t,project=FIXTURE):return json.loads((area(t,project)/bm.PROTOCOL_FILE).read_text())

def approval_record(digest,reference):
    return {'schema_version':1,'protocol_sha256':digest,'reference':reference,'verdict':'APPROVE','approver':'fresh-context-agent'}

def rebind(t,doc,project=FIXTURE,approve=True):
    """Write `doc` as the protocol file and bind its new sha256 in bench.json (a reviewed edit of both files). For an
    APPROVED protocol, `approve` also writes the approval record of the new digest (FR3-04: the approver's record)."""
    p=area(t,project)/bm.PROTOCOL_FILE;p.write_text(json.dumps(doc));digest=hashlib.sha256(p.read_bytes()).hexdigest()
    decl=json.loads((area(t,project)/'bench.json').read_text());decl['protocol']['sha256']=digest
    (area(t,project)/'bench.json').write_text(json.dumps(decl))
    approval=doc.get('approval') if isinstance(doc,dict) else None
    if approve and isinstance(approval,dict) and approval.get('state')=='APPROVED' and approval.get('reference'):
        (area(t,project)/bm.PROTOCOL_APPROVAL_FILE).write_text(json.dumps(approval_record(digest,approval['reference'])))

class ProtocolLoadTests(unittest.TestCase):
    def test_the_fixture_and_demo_protocols_load_validate_and_are_bound(self):
        for project in (FIXTURE,DEMO):
            with self.subTest(project=project):
                p=bm.load_protocol(ROOT,project);decl=bm.project_bench(ROOT,project)
                self.assertTrue(set(p['cases'])<=set(decl['cases']))
                digest=file_hash(ROOT/project/bm.PROJECT_AREA/bm.PROTOCOL_FILE)
                self.assertEqual(decl['protocol'],{'file':bm.PROTOCOL_FILE,'sha256':digest})
                self.assertEqual(bm.protocol_digest(ROOT,project),digest)

    def test_the_demo_protocol_requires_its_agreement_check(self):
        # FR1-02: P15 removed-safety-check now checks a real entry of the framework's example project
        pol=bm.load_policy(ROOT,DEMO);decl=bm.project_bench(ROOT,DEMO)
        self.assertEqual(pol['before_run_required'],{'demo-digest':['demo-agreement']})
        self.assertEqual(bm.dropped_before_run_checks(pol,'demo-digest',decl),[])
        gone=dict(decl,checks=[c for c in decl['checks'] if c['name']!='demo-agreement'])
        self.assertTrue(any('demo-agreement' in r for r in bm.dropped_before_run_checks(pol,'demo-digest',gone)))

    def test_the_framework_controls_have_no_protocol_values(self):
        self.assertIsNone(bm.load_protocol(ROOT,None));self.assertIsNone(bm.protocol_digest(ROOT,None))
        pol=bm.load_policy(ROOT)
        self.assertEqual((pol['tolerances'],pol['before_run_required']),({},{}))
        self.assertEqual((pol['budgets']['estimate_share_per_selector'],pol['budgets']['share_required']),({},[]))

    def test_load_policy_takes_the_project_values_from_the_protocol_only(self):
        base=bm.load_policy(ROOT);pol=bm.load_policy(ROOT,FIXTURE);proto=bm.load_protocol(ROOT,FIXTURE)
        self.assertEqual(pol['tolerances'],proto['tolerances']);self.assertEqual(pol['before_run_required'],proto['before_run_required'])
        self.assertEqual(pol['budgets']['estimate_share_per_selector'],proto['budgets']['estimate_share_per_selector'])
        self.assertEqual(pol['budgets']['share_required'],proto['budgets']['share_required'])
        for k in set(base)-set(bm.PROJECT_KEYS)-{'budgets'}:
            with self.subTest(key=k):self.assertEqual(pol[k],base[k])
        self.assertEqual({k:v for k,v in pol['budgets'].items() if k not in ('estimate_share_per_selector','share_required')},
                         {k:v for k,v in base['budgets'].items() if k not in ('estimate_share_per_selector','share_required')})

    def test_a_project_without_a_protocol_has_none(self):
        t=scratch(self);decl=json.loads((area(t)/'bench.json').read_text());decl.pop('protocol')
        (area(t)/'bench.json').write_text(json.dumps(decl));shutil.rmtree(area(t)/bm.PROTOCOL_DIR)
        self.assertIsNone(bm.load_protocol(t,FIXTURE));self.assertEqual(bm.load_policy(t,FIXTURE)['tolerances'],{})

class ProtocolBindingTests(unittest.TestCase):
    def test_an_unbound_protocol_is_refused(self):
        t=scratch(self);decl=json.loads((area(t)/'bench.json').read_text());decl.pop('protocol');(area(t)/'bench.json').write_text(json.dumps(decl))
        with self.assertRaisesRegex(GateError,'not bound'):bm.project_bench(t,FIXTURE)

    def test_an_edited_protocol_is_refused(self):
        t=scratch(self);p=area(t)/bm.PROTOCOL_FILE;p.write_bytes(p.read_bytes()+b' ')
        with self.assertRaisesRegex(GateError,'edited'):bm.project_bench(t,FIXTURE)
        with self.assertRaisesRegex(GateError,'edited'):bm.load_policy(t,FIXTURE)

    def test_a_missing_protocol_is_refused(self):
        t=scratch(self);(area(t)/bm.PROTOCOL_FILE).unlink()
        with self.assertRaisesRegex(GateError,'missing'):bm.project_bench(t,FIXTURE)

    def test_a_symbolic_link_is_refused(self):
        t=scratch(self);p=area(t)/bm.PROTOCOL_FILE;data=p.read_bytes();p.unlink();(t/'elsewhere.json').write_bytes(data);p.symlink_to(t/'elsewhere.json')
        with self.assertRaises(GateError):bm.project_bench(t,FIXTURE)

    def test_an_edited_referenced_file_is_refused(self):
        t=scratch(self);o=area(t)/bm.PROTOCOL_DIR/'oracle.json';o.write_bytes(o.read_bytes()+b' ')
        bm.project_bench(t,FIXTURE)                                  # the protocol file itself is still bound
        with self.assertRaisesRegex(GateError,'oracle'):bm.load_protocol(t,FIXTURE)
        self.assertEqual(bm.protocol_data(ROOT,FIXTURE,'oracle')['rows'],[[0,1],[1,2],[2,3]])

    def test_an_open_aggregate_schema_is_refused(self):
        """FR3-01: the protocol's aggregate schema must be closed (bench_privacy.summary_schema_problems)."""
        for schema in ({},{'type':'object'},{'type':'object','additionalProperties':False,'properties':{'a':{'type':'object'}}},
                       {'type':'object','additionalProperties':False,'properties':{'a':{}}},                                   # FR3-10
                       {'type':'object','additionalProperties':False,'properties':{'a':{'anyOf':[{'type':'number'}]}}},
                       {'type':'object','additionalProperties':False,'properties':{'a':{'type':'array','maxItems':4}}},
                       {'type':'object','additionalProperties':False,'properties':{'a':{'type':'number'}},'required':[['a']]},   # FR3-15
                       {'type':'object','additionalProperties':False,'properties':{'a':{'type':'number','multipleOf':0}}}):
            with self.subTest(schema=schema):
                t=scratch(self);f=area(t)/bm.PROTOCOL_DIR/'aggregate.schema.json';f.write_text(json.dumps(schema))
                doc=protocol(t);doc['aggregate_schema']['sha256']=hashlib.sha256(f.read_bytes()).hexdigest();rebind(t,doc)
                with self.assertRaisesRegex(GateError,'aggregate schema'):bm.load_protocol(t,FIXTURE)
        self.assertEqual(bm.load_protocol(ROOT,FIXTURE)['aggregate_schema']['file'],'aggregate.schema.json')   # control: the closed fixture schema
    def test_a_huge_or_odd_number_in_the_aggregate_schema_is_a_gate_error(self):
        """FR3-16: a huge integer bound or multipleOf (10**400, -10**400), a bool, NaN, an infinity (also the JSON literal
        1e9999) or a numeric string in the aggregate schema file gives GateError with the stable grammar message, never
        OverflowError, at the top level and in a nested node."""
        big=10**400
        def inner(node):return {'type':'object','additionalProperties':False,'properties':{'a':node}}
        texts={f'nested-{k}-big':json.dumps(inner({'type':'number',k:big})) for k in ('minimum','maximum','exclusiveMinimum','exclusiveMaximum','multipleOf')}
        texts.update({'nested-integer-minimum-big':json.dumps(inner({'type':'integer','minimum':big})),
                      'nested-maximum-minus-big':json.dumps(inner({'type':'number','maximum':-big})),
                      'deep-multipleOf-big':json.dumps(inner(inner({'type':'number','multipleOf':big}))),
                      'top-minimum-big':json.dumps({'type':'number','minimum':big}),
                      'top-object-with-big-bound':json.dumps({'type':'object','additionalProperties':False,'properties':{},'minimum':big}),
                      'nested-maxItems-big':json.dumps(inner({'type':'array','items':{'type':'number'},'maxItems':big})),
                      'nested-minItems-minus-big':json.dumps(inner({'type':'array','items':{'type':'number'},'maxItems':4,'minItems':-big})),
                      'nested-minimum-bool':json.dumps(inner({'type':'number','minimum':True})),
                      'nested-maximum-nan':json.dumps(inner({'type':'number','maximum':float('nan')})),
                      'nested-minimum-inf':json.dumps(inner({'type':'number','minimum':float('inf')})),
                      'nested-maximum-literal-1e9999':'{"type":"object","additionalProperties":false,"properties":{"a":{"type":"number","maximum":1e9999}}}',
                      'nested-multipleOf-string':json.dumps(inner({'type':'number','multipleOf':'1e9999'}))})
        # FR3-17 (ruling FR3-R7): the NaN and Infinity literals that json.dumps writes for nan and inf are refused by the
        # one boundary before the grammar runs; they give the stable boundary problem name, still a GateError (exit 2).
        # FR3-20: the literal 1e9999 parses to inf, so the boundary refuses it too, before the grammar (still exit 2)
        literal={'nested-maximum-nan','nested-minimum-inf','nested-maximum-literal-1e9999'}
        for name,text in texts.items():
            with self.subTest(case=name):
                t=scratch(self);f=area(t)/bm.PROTOCOL_DIR/'aggregate.schema.json';f.write_text(text)
                doc=protocol(t);doc['aggregate_schema']['sha256']=hashlib.sha256(f.read_bytes()).hexdigest();rebind(t,doc)
                want=(r'^project-data-invalid:aggregate-schema:non-finite-literal ' if name in literal
                      else r'^protocol aggregate schema breaks the framework schema grammar \(FR3-10\)$')
                with self.assertRaisesRegex(GateError,want):bm.load_protocol(t,FIXTURE)
    def test_the_schema_and_the_cross_checks_refuse_a_bad_protocol(self):
        doc=protocol(scratch(self))
        bad={'unknown-key':dict(doc,score=1),
             'case-outside-bench-json':dict(doc,cases=['fixture-case','other-case']),
             'framework-policy-name':dict(doc,decision_policies={'owner':doc['decision_policies'][POLICY]}),
             'altered-alpha':dict(doc,decision_policies={POLICY:dict(doc['decision_policies'][POLICY],alpha_one_sided=[0.05,0.0125])}),
             'altered-interval':dict(doc,decision_policies={POLICY:dict(doc['decision_policies'][POLICY],interval_method='bootstrap')}),
             'approved-without-reference':dict(doc,approval={'state':'APPROVED','reference':None}),
             'share-outside-models':dict(doc,budgets={'estimate_share_per_selector':{'zz':1.0},'share_required':[]}),
             'required-outside-cases':dict(doc,before_run_required={'other-case':['fixture-oracle']}),
             'policy-case-outside-protocol':dict(doc,decision_policies={POLICY:dict(doc['decision_policies'][POLICY],case='bench-control-spin')})}   # FR3-08
        for name,value in bad.items():
            with self.subTest(case=name):
                t=scratch(self);rebind(t,value)
                with self.assertRaises(GateError):bm.load_protocol(t,FIXTURE)
        t=scratch(self);rebind(t,doc);self.assertEqual(bm.load_protocol(t,FIXTURE),doc)          # control: the rebound original loads

class ProtocolApprovalTests(unittest.TestCase):
    """FR3-04 (ruling FR3-R2): an APPROVED protocol is bound to the digest in its approval record
    (protocol/approval.json, schemas/bench-protocol-approval.json). The project's own APPROVED state is never enough: a
    missing, malformed, other-digest or other-reference record BLOCKS every plan, run, check and decide of the project.
    Tamper-evident, not tamper-proof: an agent that rewrites the record too is found by review."""
    def test_the_fixture_record_binds_the_fixture_protocol(self):
        rec=read_json(area(ROOT)/bm.PROTOCOL_APPROVAL_FILE)
        self.assertEqual(rec['protocol_sha256'],file_hash(area(ROOT)/bm.PROTOCOL_FILE))
        self.assertEqual(rec['reference'],protocol(ROOT)['approval']['reference'])
        from schema_check import validate
        self.assertTrue(validate(ROOT,'bench-protocol-approval',rec))
    def test_a_rebind_without_a_new_approval_record_is_blocked(self):
        t=scratch(self);doc=protocol(t);doc['decision_policies'][POLICY]['threshold_ns_per_request']-=1
        rebind(t,doc,approve=False)                                  # bench.json binds the edit; the record names the old digest
        with self.assertRaisesRegex(GateError,'approval record'):bm.load_protocol(t,FIXTURE)
        with self.assertRaisesRegex(GateError,'approval record'):bm.load_policy(t,FIXTURE)
        rebind(t,doc);self.assertEqual(bm.load_protocol(t,FIXTURE),doc)        # control: the approver's new record
    def test_a_missing_or_malformed_record_is_blocked(self):
        digest=file_hash(area(ROOT)/bm.PROTOCOL_FILE);ref=protocol(ROOT)['approval']['reference']
        for name,value in (('missing',None),('other-reference',approval_record(digest,'another-approval-ref')),
                           ('reject-verdict',dict(approval_record(digest,ref),verdict='REJECT')),('self-approver',dict(approval_record(digest,ref),approver='implementer')),
                           ('extra-key',dict(approval_record(digest,ref),note='x')),('short-digest',approval_record(digest[:12],ref)),('not-json','{')):
            with self.subTest(case=name):
                t=scratch(self);rec=area(t)/bm.PROTOCOL_APPROVAL_FILE
                if value is None:rec.unlink()
                else:rec.write_text(value if isinstance(value,str) else json.dumps(value))
                with self.assertRaisesRegex(GateError,'approval record'):bm.load_protocol(t,FIXTURE)
        t=scratch(self);rec=area(t)/bm.PROTOCOL_APPROVAL_FILE;rec.unlink();rec.symlink_to(area(ROOT).resolve()/bm.PROTOCOL_APPROVAL_FILE)
        with self.assertRaises(GateError):bm.load_protocol(t,FIXTURE)                       # a link is refused
    def test_a_pending_protocol_needs_no_record(self):
        t=scratch(self);doc=protocol(t);doc['approval']={'state':'PENDING','reference':None};rebind(t,doc)
        (area(t)/bm.PROTOCOL_APPROVAL_FILE).unlink();self.assertEqual(bm.load_protocol(t,FIXTURE),doc)
        self.assertEqual(bm.load_protocol(ROOT,DEMO)['approval']['state'],'PENDING')
    def test_bench_plan_blocks_on_a_mismatch(self):
        import argparse, contextlib, io, bench
        t=scratch(self);doc=protocol(t);doc['decision_policies'][POLICY]['threshold_ns_per_request']-=1;rebind(t,doc,approve=False);out=io.StringIO()
        with contextlib.redirect_stdout(out):
            rc=bench.execute(t,argparse.Namespace(operation='plan',format='json',project=FIXTURE,case='fixture-case',dataset='synthetic:small:1',
                                                  mode='smoke',calibrate=None))
        self.assertEqual(rc,2);self.assertIn('BLOCKED',out.getvalue());self.assertIn('approval record',out.getvalue())

class ProtocolPolicyTests(unittest.TestCase):
    def test_a_project_decision_policy_names_its_protocol(self):
        pol=bm.load_decision_policy(ROOT,POLICY,FIXTURE)
        self.assertEqual((pol['name'],pol['origin'],pol['sha256'],pol['protocol_approved']),(POLICY,'project',bm.protocol_digest(ROOT,FIXTURE),True))
        self.assertEqual(pol['source'],'unit-test fixture (synthetic)')                   # the policy's own source text is kept
        self.assertTrue(bm.policy_filled(pol))
        rule=bm.load_decision_policy(ROOT,'demo-cpu-40')
        self.assertEqual((rule['origin'],rule['sha256']),('framework',file_hash(ROOT/'safety/performance-policy.json')))
        with self.assertRaises(GateError):bm.load_decision_policy(ROOT,POLICY)               # a project policy needs its project
        with self.assertRaises(GateError):bm.load_decision_policy(ROOT,'no-such-policy',FIXTURE)

    def test_a_policy_of_an_unapproved_protocol_is_not_filled(self):
        t=scratch(self);doc=protocol(t);doc['approval']={'state':'PENDING','reference':None};rebind(t,doc)
        pol=bm.load_decision_policy(t,POLICY,FIXTURE)
        self.assertFalse(pol['protocol_approved']);self.assertFalse(bm.policy_filled(pol))

    def test_the_framework_lists_only_its_rule_policies(self):
        self.assertEqual(bm.DECISION_POLICIES,('owner','demo-latency-2x','demo-cpu-40'))
        self.assertEqual(sorted(read_json(ROOT/'safety/performance-policy.json')['decision_policies']),sorted(bm.DECISION_POLICIES))

class ProtocolProtectionTests(unittest.TestCase):
    def test_protocol_paths_are_protected(self):
        import bench_phase3
        self.assertEqual(read_json(ROOT/'safety/protected-paths.json')['project_protected'],['benchmarks/project/protocol/'])
        for project in (FIXTURE,DEMO):
            with self.subTest(project=project):
                self.assertEqual(bench_phase3.protected_entry(ROOT,f'{project}/benchmarks/project/protocol/protocol.json'),'benchmarks/project/protocol/')
        self.assertIsNone(bench_phase3.protected_entry(ROOT,f'{DEMO}/benchmarks/project/bench.json'))
        self.assertIsNone(bench_phase3.protected_entry(ROOT,'docs/performance-laboratory.md'))

    def test_the_run_records_and_decide_checks_the_protocol_digest(self):
        import bench_evidence as be
        from schema_check import validate
        self.assertIn('protocol_sha256',read_json(ROOT/'schemas/bench-run.json')['properties'])
        t=scratch(self)
        run={'policy_sha256':file_hash(t/'safety/performance-policy.json'),'image_id':read_json(t/'developer.lock.json')['image_id'],
             'plan':{'project_dir':FIXTURE},'protocol_sha256':bm.protocol_digest(t,FIXTURE)}
        self.assertEqual(be.policy_runtime_problems(t,run),[])                                  # control
        unbound=be.policy_runtime_problems(t,{k:v for k,v in run.items() if k!='protocol_sha256'})
        self.assertTrue(any(p.startswith('post-hoc-protocol-change') for p in unbound))
        doc=protocol(t);doc['decision_policies'][POLICY]['threshold_ns_per_request']-=1;rebind(t,doc)
        self.assertTrue(any(p.startswith('post-hoc-protocol-change') for p in be.policy_runtime_problems(t,run)))
        framework={k:v for k,v in run.items() if k not in ('plan','protocol_sha256')}
        self.assertEqual(be.policy_runtime_problems(t,dict(framework,plan={'project_dir':None},protocol_sha256=None)),[])

class RequiredShareTests(unittest.TestCase):
    """Moved from the removed tests/unit/test_bench_budget.py (FR5B-04: the planning-budget constants are example data and
    leave the framework): the planning shares are project data (the protocol's budgets), and the required-share rule
    (budgets.share_required) of bench_deadline.expected_seconds refuses a missing share."""
    FIXTURE='tests/fixtures/bench-project'
    def test_the_required_share_is_the_protocol_value(self):
        pol=bm.load_policy(ROOT,self.FIXTURE)
        self.assertEqual(pol['budgets']['estimate_share_per_selector']['m5'],3.0);self.assertEqual(pol['budgets']['share_required'],['m5'])
        self.assertEqual(pol['budgets']['estimate_share_per_selector']['m4'],0.15)
        self.assertEqual(bm.load_policy(ROOT)['budgets']['estimate_share_per_selector'],{})
    def test_expected_seconds_refuses_a_required_share(self):
        import copy, bench_deadline as bd
        from evidence import GateError
        pol=copy.deepcopy(bm.load_policy(ROOT,self.FIXTURE));del pol['budgets']['estimate_share_per_selector']['m5']
        with self.assertRaises(GateError):bd.expected_seconds(pol,{'variant':'py-reference','selector':'m5'},13230,1,None)
        full=bm.load_policy(ROOT,self.FIXTURE)
        self.assertAlmostEqual(bd.expected_seconds(full,{'variant':'py-reference','selector':'m5'},10,1,None),
                               3.0*bd.expected_seconds(full,{'variant':'py-reference','selector':'m3'},10,1,None))
        self.assertGreater(bd.expected_seconds(pol,{'variant':'py-reference','selector':'other-test'},10,1,None),0)   # not listed: 1.0 as landed

if __name__=='__main__':unittest.main()
