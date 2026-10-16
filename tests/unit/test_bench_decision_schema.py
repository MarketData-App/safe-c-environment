import copy, json, sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import bench_model as bm
from schema_check import validate
from evidence import GateError

def record():
    return {'schema_version':1,'run_id':'0'*32,'case':'bench-control-spin','local':False,
            'policy':{'name':'demo-cpu-40','sha256':'a'*64,'demonstration_only':True,'filled':True},'adoption_authorized':False,'cgroup_identity_unrecorded':False,'qualification':None,'sensitivity':None,'windows':None,
            'source_identity_run':'b'*64,'source_identity_decision':'b'*64,'stale':False,'image_id':'sha256:'+'c'*64,
            'evidence_quality':'decision','outcome':'KEEP_PYTHON','rule':3,'adoption_outcome':'INCONCLUSIVE',
            'demonstration_outcome':'KEEP_PYTHON','adoption_note':'Python retained pending evidence','reasons':[],
            'comparisons':[],'items':[],'summary':{k:'n/a' for k in ('problem','best_python','best_c','size_range','caller_latency','cpu','memory',
            'uncertainty','missing_evidence','complexity','next_action','cpu_tradeoff','assumptions','frequency')}|{'routes':[]}}

FIXTURE='tests/fixtures/bench-project';UNIT_POLICY='fixture-request-threshold'    # FR3: a unit-threshold policy is project data

class DecisionPolicyTests(unittest.TestCase):
    def test_three_framework_policies(self):
        self.assertEqual(bm.DECISION_POLICIES,('owner','demo-latency-2x','demo-cpu-40'))
        self.assertEqual(set(bm.load_policy(ROOT)['decision_policies']),set(bm.DECISION_POLICIES))
    def test_a_project_unit_threshold_policy_loads_from_the_protocol(self):
        p=bm.load_decision_policy(ROOT,UNIT_POLICY,FIXTURE)
        self.assertEqual((p['kind'],p['state'],p['threshold_ns_per_request'],p['alpha_one_sided'],p['multiplicity'],p['primary_blocks'],p['extension_blocks']),
                         ('unit-threshold','approved',200000000,[0.025,0.0125],'bonferroni',12,12))
        self.assertEqual(len(p['units']),10);self.assertEqual(p['interval_method'],'order-statistic');self.assertTrue(bm.policy_filled(p));self.assertFalse(p['demonstration_only'])
        with self.assertRaises(GateError):bm.load_decision_policy(ROOT,UNIT_POLICY)       # never a framework policy
    def test_owner_template_is_not_filled(self):
        p=bm.load_decision_policy(ROOT,'owner');self.assertEqual(p['state'],'owner-must-fill');self.assertFalse(bm.policy_filled(p))
    def test_demo_policies_are_demonstration_only_and_filled(self):
        for n in ('demo-latency-2x','demo-cpu-40'):
            p=bm.load_decision_policy(ROOT,n);self.assertTrue(p['demonstration_only']);self.assertTrue(bm.policy_filled(p))
    def test_demo_values_are_the_spec_values(self):
        lat=bm.load_decision_policy(ROOT,'demo-latency-2x');cpu=bm.load_decision_policy(ROOT,'demo-cpu-40')
        self.assertEqual((lat['metric'],lat['modes'],lat['points'],lat['relative_threshold'],lat['min_abs_saving_ns_per_call']),('wall_ns_per_unit',['warm'],['full-dataset'],0.5,100000000))
        self.assertEqual((cpu['metric'],cpu['relative_threshold'],cpu['limits']['latency_regression']),('cpu_ns_per_unit',0.4,0.05))
    def test_unknown_policy_is_refused(self):
        with self.assertRaises(GateError):bm.load_decision_policy(ROOT,'fast')

class DecisionSchemaTests(unittest.TestCase):
    def test_valid_record(self):validate(ROOT,'bench-decision',record())
    def test_no_single_score(self):
        r=record();r['score']=1.0
        with self.assertRaises(GateError):validate(ROOT,'bench-decision',r)
        r=record();r['summary']['score']='9/10'
        with self.assertRaises(GateError):validate(ROOT,'bench-decision',r)
    def test_closed_outcomes(self):
        r=record();r['outcome']='ADOPT_C'
        with self.assertRaises(GateError):validate(ROOT,'bench-decision',r)
    def test_bounded_free_text(self):
        r=record();r['reasons']=['x'*301]
        with self.assertRaises(GateError):validate(ROOT,'bench-decision',r)

# Behavior tests added beside the brief's tests (Task 13 implementer): each one drives a rule of the
# policy schema, the decision schema or the two loader functions with a concrete document.

OWNER_UNITS=['m1/full-dataset','m2/full-dataset','m3/full-dataset','m4/full-dataset','m5/full-dataset',
             'm1/single-record','m2/single-record','m3/single-record','m4/single-record','m5/single-record']

def qualification_none():
    return {'kind':'none','label':'framework unqualified','project_exit':None,'project_report_path':None,'project_report_sha256':None,
            'project_identity':None,'framework_ci_run_id':None,'ci_report_path':None,'ci_report_sha256':None,'ci_local_state':None,
            'ci_required_gates':'NOT_CHECKED','local_reason':None,'verdicts':[],'source_identity':'a'*64}

def refused(test,kind,doc):
    with test.assertRaises(GateError):validate(ROOT,kind,doc)

class PolicySchemaBehaviorTests(unittest.TestCase):
    def setUp(self):self.pol=json.loads((ROOT/'safety/performance-policy.json').read_text());self.proto=bm.load_protocol(ROOT,FIXTURE)
    def altered(self,name,key,value):
        v=copy.deepcopy(self.pol);v['decision_policies'][name][key]=value;return v
    def altered_unit(self,key,value):
        v=copy.deepcopy(self.proto);v['decision_policies'][UNIT_POLICY][key]=value;return v
    def test_unit_policy_keys_and_units_are_the_spec_text(self):
        p=self.proto['decision_policies'][UNIT_POLICY]
        self.assertEqual(list(p),['state','demonstration_only','kind','source','case','metric','verdict_mode','reported_modes','threshold_ns_per_request',
                                  'units','python_languages','c_languages','safe_routes','less_safe_routes','panel_statistic','primary_blocks',
                                  'interval_method','alpha_one_sided','multiplicity','extension_blocks','extension_trigger','extension_window',
                                  'c_project_check','pool_cpu_guard','limits'])
        self.assertEqual(p['units'],OWNER_UNITS)
        self.assertEqual(p['c_project_check'],{'accept_exit':[0,3],'exit_3_requires':'local-framework-qualification-g9.4',
                                               'exit_3_label':'framework qualified locally, not published'})
    def test_unit_policy_statistics_cannot_change(self):
        # FR3: the statistical constants stay pinned in schemas/bench-protocol.json; the threshold and the units are project
        # data, bound by the protocol digest (an edit is refused by bench_model; tests/unit/test_bench_protocol_file.py)
        for key,value in [('threshold_ns_per_request',0),('threshold_ns_per_request',2.5e8+0.5),('units',[]),('units',['bad unit']),('units',OWNER_UNITS+['m6/full-dataset']),
                          ('interval_method','bootstrap'),('alpha_one_sided',[0.05,0.025]),
                          ('multiplicity','none'),('primary_blocks',6),('extension_blocks',0),('panel_statistic','median'),('verdict_mode','cold')]:
            with self.subTest(key=key,value=value):refused(self,'bench-protocol',self.altered_unit(key,value))
    def test_unit_policy_is_closed_and_complete(self):
        v=self.altered_unit('score',1);refused(self,'bench-protocol',v)
        v=copy.deepcopy(self.proto);del v['decision_policies'][UNIT_POLICY]['interval_method'];refused(self,'bench-protocol',v)
        self.assertTrue(validate(ROOT,'bench-protocol',self.proto))
    def test_policy_set_is_exactly_three(self):
        v=copy.deepcopy(self.pol);v['decision_policies']['fast']=copy.deepcopy(v['decision_policies']['demo-cpu-40']);refused(self,'bench-policy',v)
        v=copy.deepcopy(self.pol);del v['decision_policies']['owner'];refused(self,'bench-policy',v)
        v=copy.deepcopy(self.pol);v['decision_policies']['unit']=copy.deepcopy(self.proto['decision_policies'][UNIT_POLICY]);refused(self,'bench-policy',v)
    def test_rule_policy_is_closed(self):
        refused(self,'bench-policy',self.altered('demo-cpu-40','score',1))
        refused(self,'bench-policy',self.altered('demo-latency-2x','metric','wall_ns_per_request'))
        refused(self,'bench-policy',self.altered('owner','state','filled'))
    def test_demonstration_only_needs_demonstration_state(self):
        refused(self,'bench-policy',self.altered('demo-latency-2x','state','approved'))
        v=self.altered('owner','demonstration_only',True);refused(self,'bench-policy',v)
        v['decision_policies']['owner']['state']='demonstration';validate(ROOT,'bench-policy',v)
    def test_owner_template_can_be_filled(self):
        v=copy.deepcopy(self.pol);o=v['decision_policies']['owner']
        o.update(state='approved',objective='caller warm latency',metric='wall_ns_per_unit',relative_threshold=0.3)
        validate(ROOT,'bench-policy',v)
        self.assertTrue(bm.policy_filled(dict(o,name='owner')))

class LoaderBehaviorTests(unittest.TestCase):
    def test_load_returns_an_independent_copy_with_the_name(self):
        p=bm.load_decision_policy(ROOT,'demo-cpu-40');self.assertEqual(p['name'],'demo-cpu-40')
        p['limits']['latency_regression']=1.0;p['modes'].append('x')
        q=bm.load_decision_policy(ROOT,'demo-cpu-40');self.assertEqual(q['limits']['latency_regression'],0.05);self.assertEqual(q['modes'],['warm','cold'])
    def test_policy_filled_unit_threshold(self):
        p=bm.load_decision_policy(ROOT,UNIT_POLICY,FIXTURE)
        self.assertFalse(bm.policy_filled(dict(p,protocol_approved=False)))        # FR3: an unapproved protocol fills no policy
        self.assertFalse(bm.policy_filled(dict(p,state='owner-must-fill')))
        self.assertFalse(bm.policy_filled(dict(p,threshold_ns_per_request=None)))
        self.assertFalse(bm.policy_filled(dict(p,threshold_ns_per_request=2e8)))
    def test_policy_filled_rule_policy(self):
        p=bm.load_decision_policy(ROOT,'demo-cpu-40')
        for key,value in [('metric',None),('relative_threshold',None),('modes',[]),('points',None),('metric','')]:
            with self.subTest(key=key):self.assertFalse(bm.policy_filled(dict(p,**{key:value})))
        self.assertFalse(bm.policy_filled(dict(p,state='owner-must-fill')))

class DecisionSchemaBehaviorTests(unittest.TestCase):
    def test_no_record_authorizes_adoption(self):
        r=record();r['adoption_authorized']=True;refused(self,'bench-decision',r)
    def test_rule_policy_record_needs_an_outcome_and_a_rule(self):
        for key,value in [('outcome',None),('adoption_outcome',None),('rule',None),('rule',0),('rule',9)]:
            with self.subTest(key=key,value=value):
                r=record();r[key]=value;refused(self,'bench-decision',r)
        r=record();r['demonstration_outcome']=None;validate(ROOT,'bench-decision',r)
    def test_rule_policy_record_has_no_qualification_or_sensitivity(self):
        r=record();r['qualification']=qualification_none();refused(self,'bench-decision',r)
        r=record();r['sensitivity']={'owner_confirmation':{'ledger_id':'P3-OWNER-SENS-01','coverage_sha256':'0'*64}};refused(self,'bench-decision',r)
    def test_unit_threshold_record_needs_null_outcomes_and_units(self):
        r=record();r['policy']={'name':UNIT_POLICY,'sha256':'a'*64,'demonstration_only':False,'filled':True}
        r['qualification']=qualification_none()
        refused(self,'bench-decision',r)            # rule-policy outcome fields are set
        for k in ('outcome','rule','adoption_outcome','demonstration_outcome'):r[k]=None
        refused(self,'bench-decision',r)            # units (Task 15) is required
    def test_policy_name_is_closed(self):
        r=record();r['policy']['name']='fast';refused(self,'bench-decision',r)    # FR3: any other name is a unit-threshold record: needs units
        r=record();r['policy']['name']='Not A Name';refused(self,'bench-decision',r)
    def test_evidence_quality_is_closed(self):
        for q in ('decision','exploratory (smoke)','stale','owner fixture, local run, aggregate'):
            r=record();r['evidence_quality']=q;validate(ROOT,'bench-decision',r)
        r=record();r['evidence_quality']='good';refused(self,'bench-decision',r)
    def test_qualification_fragment_rules(self):
        import jsonschema
        frag=jsonschema.Draft202012Validator(json.loads((ROOT/'schemas/bench-decision.json').read_text())['properties']['qualification'])
        self.assertTrue(frag.is_valid(None));self.assertTrue(frag.is_valid(qualification_none()))
        bad=dict(qualification_none(),kind='manifest');self.assertFalse(frag.is_valid(bad))
        bad=dict(qualification_none(),kind='manifest',label='manifest recorded',project_exit=3,project_report_path='artifacts/project-report.json',
                 project_report_sha256='b'*64,project_identity='a'*64);self.assertFalse(frag.is_valid(bad))
        good=dict(bad,project_exit=0);self.assertTrue(frag.is_valid(good))
        self.assertFalse(frag.is_valid(dict(good,framework_ci_run_id='c'*32)))
    def test_sensitivity_object(self):
        frag=json.loads((ROOT/'schemas/bench-decision.json').read_text())['properties']['sensitivity']
        import jsonschema;v=jsonschema.Draft202012Validator(frag)
        self.assertTrue(v.is_valid(None))
        self.assertTrue(v.is_valid({'owner_confirmation':{'ledger_id':'P3-OWNER-SENS-01','coverage_sha256':'0'*64}}))
        self.assertFalse(v.is_valid({'owner_confirmation':{'ledger_id':'P3-OWNER-SENS-1','coverage_sha256':'0'*64}}))
        self.assertFalse(v.is_valid({'owner_confirmation':{'ledger_id':'P3-OWNER-SENS-01','coverage_sha256':'0'*63}}))
        self.assertFalse(v.is_valid({'owner_confirmation':{'ledger_id':'P3-OWNER-SENS-01','coverage_sha256':'0'*64,'x':1}}))
    def test_windows_object(self):
        r=record();r['windows']={'plan_id':'p1','positions':[{'window':'1a','attempt':1,'run_id':'0'*32,'record_sha256':'1'*64,'status':'PASS',
                                                              'envelope_identity_sha256':'2'*64}],
                                 'superseded':[{'window':'1a','attempt':1,'record_sha256':'3'*64,'status':'BLOCKED','reason':'window-pressure'}],'exhausted':[]}
        validate(ROOT,'bench-decision',r)
        r['windows']['positions'][0]['extra']=1;refused(self,'bench-decision',r)
        r=record();r['windows']={'plan_id':'p','positions':[],'superseded':[],'exhausted':['1a']*33};refused(self,'bench-decision',r)
    def test_comparison_and_item_rows(self):
        c={'name':'baseline benefit','base':'py-reference','other':'py-optimized','point':'baseline','mode':'warm','metric':'cpu_ns_per_unit',
           'value':None,'ratio':0.5,'low':0.4,'high':0.6,'saving_ns_per_unit':12.5,'blocks':12,'reason':None}
        r=record();r['comparisons']=[c];r['items']=[{'row':'c-serial','item':1,'value':True}];validate(ROOT,'bench-decision',r)
        r=record();r['comparisons']=[dict(c,score=1)];refused(self,'bench-decision',r)
        r=record();r['items']=[{'row':'c-serial','item':9,'value':True}];refused(self,'bench-decision',r)
        r=record();r['comparisons']=[c]*601;refused(self,'bench-decision',r)
        r=record();r['summary']['routes']=[{'route':'stdio','label':'separate process','rows':2}]*9;refused(self,'bench-decision',r)

# Task 13 approval findings BD-T13-01..03 (the Task 13 policy approval verdict): behavior tests.

def owner_record_schema():
    """The decision schema with a permissive `units` property, as Task 15 adds it additively, so that the owner branch
    of the schema can be evaluated now (the schema itself still refuses every owner record until Task 15)."""
    import jsonschema
    s=json.loads((ROOT/'schemas/bench-decision.json').read_text());s['properties']['units']={}
    return jsonschema.Draft202012Validator(s)

def owner_record():
    r=record();r['policy']={'name':UNIT_POLICY,'sha256':'a'*64,'demonstration_only':False,'filled':True}
    for k in ('outcome','rule','adoption_outcome','demonstration_outcome'):r[k]=None
    r['qualification']=qualification_none();r['units']=[];return r

class ApprovalFindingTests(unittest.TestCase):
    def test_bd_t13_01_demonstration_policy_adoption_is_inconclusive(self):
        for outcome in ('KEEP_PYTHON','C_CANDIDATE_FOR_REVIEW','OPTIMIZE_PYTHON_FIRST','USE_EXISTING_PYTHON_LIBRARY','CONSIDER_PYTHON_CONCURRENCY'):
            with self.subTest(outcome=outcome):
                r=record();r['adoption_outcome']=outcome;r['demonstration_outcome']=outcome;refused(self,'bench-decision',r)
        r=record();r['outcome']='INVALID_EXPERIMENT';r['rule']=1;r['adoption_outcome']='INVALID_EXPERIMENT';r['demonstration_outcome']=None
        validate(ROOT,'bench-decision',r)
    def test_bd_t13_01_unfilled_template_adoption_is_inconclusive(self):
        r=record();r['policy']={'name':'owner','sha256':'a'*64,'demonstration_only':False,'filled':False}
        r['outcome']='INCONCLUSIVE';r['rule']=2;r['demonstration_outcome']=None;validate(ROOT,'bench-decision',r)
        for outcome in ('KEEP_PYTHON','C_CANDIDATE_FOR_REVIEW'):
            with self.subTest(outcome=outcome):
                r['adoption_outcome']=outcome;refused(self,'bench-decision',r)
    def test_bd_t13_01_filled_policy_adopts_its_outcome(self):
        r=record();r['policy']={'name':'owner','sha256':'a'*64,'demonstration_only':False,'filled':True}
        r['outcome']='C_CANDIDATE_FOR_REVIEW';r['rule']=4;r['adoption_outcome']='C_CANDIDATE_FOR_REVIEW';r['demonstration_outcome']=None
        r['adoption_note']='policy decision';validate(ROOT,'bench-decision',r)
    def test_bd_t13_02_owner_record_needs_a_qualification_object(self):
        v=owner_record_schema();r=owner_record()
        self.assertTrue(v.is_valid(r))
        r['qualification']=None;self.assertFalse(v.is_valid(r))
        r=owner_record();r['qualification']='manifest';self.assertFalse(v.is_valid(r))
    def test_bd_t13_02_rule_record_keeps_null_qualification(self):
        v=owner_record_schema();r=record();self.assertTrue(v.is_valid(r))
        r['qualification']=qualification_none();self.assertFalse(v.is_valid(r))
    def test_bd_t13_03_owner_identity_fields_are_pinned(self):
        # FR3: the case and the source text are project data (bound by the protocol digest); the identity constants stay pinned
        proto=bm.load_protocol(ROOT,FIXTURE);validate(ROOT,'bench-protocol',proto)
        for key,value in [('state','demonstration'),('state','owner-must-fill'),('demonstration_only',True),('case','Bad Case'),
                          ('source',''),('reported_modes',['warm']),
                          ('reported_modes',['cold','warm']),('reported_modes',['warm','cold','hot'])]:
            with self.subTest(key=key,value=value):
                v=copy.deepcopy(proto);v['decision_policies'][UNIT_POLICY][key]=value;refused(self,'bench-protocol',v)
        v=copy.deepcopy(proto);v['decision_policies'][UNIT_POLICY].update(state='demonstration',demonstration_only=True)
        refused(self,'bench-protocol',v)

if __name__=='__main__':unittest.main()
