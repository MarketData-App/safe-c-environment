"""Task 17 (spec 10, B14): the decision record, summary and Markdown tests of the Task 17 brief (RecordTests). Ruling T14-C1:
they run here, not in tests/unit/test_bench_decide_cli.py, because each record runs `decide` on the c-candidate or keep
case under the demonstration policies (rules 3-8: paired bootstraps of the policy's 10,000 resamples), which exceeds the
plan's 0.5 s per-file budget for tests/unit. Assertions are the brief's; the resample count stays the policy value. The
brief's case name of the example project is replaced by the framework case record-scan (input data only), because
test_bench_framework_imports forbids the example name in framework tests.

The host tools are loaded by path from /src/tools (the container has no host tool imports). They are registered in
sys.modules only while this module runs (setUpModule/tearDownModule), so later container tests that load a modified
copy of a tool (test_coverage) never receive these modules."""
import copy, importlib.util, json, sys, unittest
from pathlib import Path
from unittest import mock
ROOT=Path('/src')
TOOLS=('evidence','schema_check','bench_stats','bench_model','bench_decide','bench_phase3_cli')   # dependency order
_SAVED={}
bd=bm=cli=validate=POL=FIX=None

def setUpModule():
    global bd,bm,cli,validate,POL,FIX
    for name in TOOLS:_SAVED[name]=sys.modules.get(name)
    for name in TOOLS:
        spec=importlib.util.spec_from_file_location(name,ROOT/'tools'/f'{name}.py');mod=importlib.util.module_from_spec(spec)
        sys.modules[name]=mod;spec.loader.exec_module(mod)
    bd=sys.modules['bench_decide'];bm=sys.modules['bench_model'];cli=sys.modules['bench_phase3_cli'];validate=sys.modules['schema_check'].validate
    POL=bm.load_policy(ROOT);FIX=bm.load_fixtures(ROOT)['decision_cases']

def tearDownModule():
    for name in TOOLS:
        if _SAVED.get(name) is None:sys.modules.pop(name,None)
        else:sys.modules[name]=_SAVED[name]

class RecordTests(unittest.TestCase):
    def record(self,name,policy):
        c=copy.deepcopy(next(x for x in FIX['cases'] if x['name']==name));ev=bd.synthetic_evidence(c)
        r=bd.decide(ev,policy,c['opportunity'],bd.stats_of(POL))
        run={'run_id':'0'*32,'case':'record-scan','mode':'decision','source_identity':'a'*64,'image_id':'sha256:'+'1'*64,'policy_sha256':'2'*64,'dataset':{'kind':'synthetic'}}
        with mock.patch('bench_decide._current_identity',return_value='a'*64):
            return bd.decision_record(ROOT,run,{},{'case_id':'record-scan','variants':[]},policy['name'],r,ev,c['opportunity'])
    def record_with_flag(self,name,policy):
        c=copy.deepcopy(next(x for x in FIX['cases'] if x['name']==name));ev=bd.synthetic_evidence(c);r=bd.decide(ev,policy,c['opportunity'],bd.stats_of(POL))
        run={'run_id':'0'*32,'case':'record-scan','mode':'decision','source_identity':'a'*64,'image_id':'sha256:'+'1'*64,'policy_sha256':'2'*64,'dataset':{'kind':'synthetic'}}
        with mock.patch('bench_decide._current_identity',return_value='a'*64):
            return bd.decision_record(ROOT,run,{},{'case_id':'record-scan','variants':[]},policy['name'],r,ev,c['opportunity'],cgroup_unrecorded=True)
    def test_unrecorded_cgroup_identity_is_labeled_in_rule_policy_records(self):
        r=self.record_with_flag('keep',bm.load_decision_policy(ROOT,'demo-cpu-40'))
        validate(ROOT,'bench-decision',r);self.assertIs(r['cgroup_identity_unrecorded'],True);self.assertEqual(r['evidence_quality'],'decision')
    def test_records_validate_for_every_policy(self):
        for n in cli.RULE_POLICIES:                       # a unit-threshold policy has its own path (G9.9; Task 18)
            validate(ROOT,'bench-decision',self.record('c-candidate',bm.load_decision_policy(ROOT,n)))
    def test_rule_policy_adoption_is_retained_python(self):
        for n in cli.RULE_POLICIES:                       # a unit-threshold policy has its own path (G9.9; Task 18)
            r=self.record('c-candidate',bm.load_decision_policy(ROOT,n))
            self.assertEqual(r['adoption_outcome'],'INCONCLUSIVE');self.assertEqual(r['adoption_note'],'Python retained pending evidence')
    def test_summary_has_the_brief_fields_and_no_score(self):
        s=self.record('keep',bm.load_decision_policy(ROOT,'demo-cpu-40'))['summary']
        self.assertEqual(set(s),{'problem','best_python','best_c','size_range','caller_latency','cpu','cpu_tradeoff','memory','assumptions','frequency','uncertainty','missing_evidence','complexity','next_action','routes'})
        self.assertNotIn('score',json.dumps(s).lower())
    def test_markdown_states_the_demo_label(self):
        md=bd.render_markdown([self.record('c-candidate',bm.load_decision_policy(ROOT,'demo-latency-2x'))])
        self.assertIn('demonstration outcome',md);self.assertIn('Python retained pending evidence',md)
