import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools'))
from evidence import GateError
import project_model as pm
import project_check as pc
ROOT=Path(__file__).resolve().parents[2]

PROJECT={'schema_version':1,'name':'demo-app','modules':[{'name':'greeting','spec':'specs/project/greeting.md','sources':['src/greeting.c'],
  'headers':['include/greeting.h'],'tests':['tests/project/test_greeting.c'],'reads_external_input':True,
  'fuzz':[{'name':'greeting','harness':'fuzz/project/greeting_fuzz.c','corpus':'fuzz/project/corpus/greeting','regressions':'fuzz/project/regressions/greeting'}]}],
  'programs':[{'name':'hello','main':'src/main.c','modules':['greeting']}],'run':{'program':'hello','args':['world'],'expect_exit':0}}

def finding(state, severity):
    return {'id':'F-1','origin':'reviewer','source_identity':'s','location':'src/greeting.c:1','property':'p','severity':severity,
            'rationale':'r','reproducer':'t','state':state,'attempts':0,'history':[],'verification':None}

def ledger(*findings):
    return {'schema_version':1,'source_identity':'s','units':{'greeting':['src/greeting.c']},'findings':list(findings),
            'review':[{'unit':'greeting','question':'q','locations':[1]}]}

def make(base, extra=None, project=PROJECT):
    files={'project.json':json.dumps(project),'specs/project/greeting.md':'# spec','src/greeting.c':'int x;','src/main.c':'int main(void){return 0;}',
           'include/greeting.h':'int x;','tests/project/test_greeting.c':'int main(void){return 0;}','fuzz/project/greeting_fuzz.c':'int y;',
           'fuzz/project/corpus/greeting/seed':'a','fuzz/project/regressions/greeting/.keep':'',
           'review/ledger.json':json.dumps(ledger(finding('REJECTED','high')))}
    files.update(extra or {})
    for rel,text in files.items():
        p=base/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)

def cov_file(name, lines, lines_cov, branches, branches_cov):
    return {'filename':name,'summary':{'lines':{'count':lines,'covered':lines_cov},'branches':{'count':branches,'covered':branches_cov}}}

class GatePlanTests(unittest.TestCase):
    def test_plan_is_the_23_policy_gates_in_policy_order(self):
        policy=pm.project_policy(ROOT)
        plan=pc.gate_plan(policy)
        self.assertEqual(plan,policy['gates'])
        self.assertEqual(len(plan),23)
        self.assertEqual(plan[:6],['format','gcc-O0','gcc-O2','clang-O0','clang-O2','hardened'])
    def test_dropped_or_renamed_gate_is_rejected(self):
        policy=pm.project_policy(ROOT)
        for gates in [policy['gates'][1:],policy['gates']+['format'],['fmt']+policy['gates'][1:]]:
            with self.assertRaises(GateError):pc.gate_plan(dict(policy,gates=gates))
    def test_fuzz_budget_below_30_seconds_is_rejected(self):
        policy=pm.project_policy(ROOT)
        with self.assertRaises(GateError):pc.gate_plan(dict(policy,fuzz_seconds=29))

class CoverageTests(unittest.TestCase):
    FILES={'app/src/greeting.c','app/src/main.c'}
    def summary(self,*files):return {'data':[{'files':list(files)}]}
    def test_exact_thresholds_pass(self):
        ok,details=pc.coverage_ok(self.summary(cov_file('/src/app/src/greeting.c',80,72,16,14),cov_file('/src/app/src/main.c',20,18,4,3),
                                               cov_file('/src/app/tests/project/test_greeting.c',50,10,10,1)),self.FILES,90,85)
        self.assertTrue(ok)
        self.assertEqual(details['totals']['lines'],{'count':100,'covered':90,'percent':90.0})
        self.assertEqual(details['totals']['branches'],{'count':20,'covered':17,'percent':85.0})
        self.assertEqual(sorted(details['files']),sorted(self.FILES))
    def test_one_line_below_threshold_fails(self):
        ok,details=pc.coverage_ok(self.summary(cov_file('/src/app/src/greeting.c',80,71,16,16),cov_file('/src/app/src/main.c',20,18,4,4)),self.FILES,90,85)
        self.assertFalse(ok);self.assertEqual(details['totals']['lines']['covered'],89)
    def test_branch_below_threshold_fails(self):
        ok,_=pc.coverage_ok(self.summary(cov_file('/src/app/src/greeting.c',80,80,16,13),cov_file('/src/app/src/main.c',20,20,4,3)),self.FILES,90,85)
        self.assertFalse(ok)
    def test_missing_project_file_fails(self):
        ok,details=pc.coverage_ok(self.summary(cov_file('/src/app/src/greeting.c',80,80,16,16)),self.FILES,90,85)
        self.assertFalse(ok);self.assertEqual(details['missing'],['app/src/main.c'])
    def test_zero_counts_fail(self):
        ok,_=pc.coverage_ok(self.summary(cov_file('/src/app/src/greeting.c',0,0,0,0),cov_file('/src/app/src/main.c',0,0,0,0)),self.FILES,90,85)
        self.assertFalse(ok)
    def test_malformed_summary_fails(self):
        for value in [{},{'data':'x'},{'data':[{'files':[{'filename':'/src/app/src/main.c'}]}]},[]]:
            ok,_=pc.coverage_ok(value,self.FILES,90,85);self.assertFalse(ok)

class CtestTests(unittest.TestCase):
    def test_names_in_order(self):
        text=json.dumps({'kind':'ctestInfo','version':{'major':1},'tests':[{'name':'project.greeting.test_greeting','properties':[]},{'name':'project.run.hello'}]})
        self.assertEqual(pc.parse_ctest_names(text),['project.greeting.test_greeting','project.run.hello'])
    def test_empty_inventory(self):
        self.assertEqual(pc.parse_ctest_names(json.dumps({'tests':[]})),[])
    def test_invalid_output_rejected(self):
        for text in ['','not json','{"tests":{}}','{"tests":[{"x":1}]}','[]','{"tests":[{"name":""}]}']:
            with self.assertRaises(GateError):pc.parse_ctest_names(text)
    def test_expected_tests_follow_project_json(self):
        self.assertEqual(pc.expected_tests(PROJECT),{'unit':['project.greeting.test_greeting'],'integration':['project.run.hello']})

class InventoryTests(unittest.TestCase):
    def test_clean_project_passes(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t);make(d);project=pm.load_project(d,'.',framework_root=ROOT)
            self.assertEqual(pc.inventory_gate(d,'.',project,ROOT)['status'],'PASS')
    def test_weakening_attempts_fail_inventory(self):
        for rel,text in [('src/greeting.c','int x; /* NOLINT */'),('include/greeting.h','#pragma clang diagnostic ignored "-Wall"\nint x;'),
                         ('tests/project/test_greeting.c','#pragma GCC diagnostic ignored "-Wconversion"\nint main(void){return 0;}'),
                         ('src/main.c','__attribute__((no_sanitize("address"))) int main(void){return 0;}'),
                         ('fuzz/project/greeting_fuzz.c','__attribute__((optimize("O0"))) int y;')]:
            with self.subTest(rel=rel), tempfile.TemporaryDirectory() as t:
                d=Path(t);make(d,{rel:text});project=pm.load_project(d,'.',framework_root=ROOT)
                row=pc.inventory_gate(d,'.',project,ROOT)
                self.assertEqual(row['status'],'FAIL');self.assertIn('forbidden text',row['details']['reason'])

class ReviewTests(unittest.TestCase):
    def check(self,value):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t);make(d,{'review/ledger.json':json.dumps(value) if value is not None else '{'})
            return pc.review_gate(d,'.',ROOT)
    def test_rejected_or_verified_high_passes(self):
        self.assertEqual(self.check(ledger(finding('REJECTED','high'),finding('VERIFIED','high')))['status'],'PASS')
    def test_open_unresolved_blocked_high_fails(self):
        for state in ['OPEN','UNRESOLVED','BLOCKED']:
            for severity in ['high','High: buffer overrun','critical']:
                with self.subTest(state=state,severity=severity):self.assertEqual(self.check(ledger(finding(state,severity)))['status'],'FAIL')
    def test_open_low_passes(self):
        self.assertEqual(self.check(ledger(finding('OPEN','low')))['status'],'PASS')
    def test_invalid_or_missing_ledger_fails(self):
        self.assertEqual(self.check(None)['status'],'FAIL')
        self.assertEqual(self.check({'schema_version':1})['status'],'FAIL')
        with tempfile.TemporaryDirectory() as t:
            d=Path(t);make(d);(d/'review/ledger.json').unlink()
            self.assertEqual(pc.review_gate(d,'.',ROOT)['status'],'FAIL')

class PlanTests(unittest.TestCase):
    def test_path_with_space_loads_and_plans(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t);make(d/'my app');project=pm.load_project(d,'my app',framework_root=ROOT)
            self.assertEqual(pc.inventory_gate(d,'my app',project,ROOT)['status'],'PASS')
            builds=pc.build_plan('my app')
            self.assertEqual([b['gate'] for b in builds],['gcc-O0','gcc-O2','clang-O0','clang-O2','hardened','asan','ubsan','integer','msan','tsan','coverage'])
            configure=builds[0]['configure']
            self.assertIn('-DSAFE_C_PROJECT_DIR=/src/my app',configure)
            self.assertEqual(configure[:3],['cmake','-S','/src'])
            self.assertIn('/work/project/strict-gcc-O0',configure)
            for flag in ['-DSAFETY_PROFILE=strict','-DCMAKE_C_COMPILER=gcc','-DCMAKE_C_FLAGS=-O0','-DSAFETY_CASE=NONE','-DSAFETY_VARIANT=both',
                         '-DFOUNDATION_CASE=NONE','-DFOUNDATION_MUTANT=NONE','-DFOUNDATION_DISABLED_GUARDS=']:self.assertIn(flag,configure)
            self.assertIn('-DCMAKE_C_FLAGS=-O2',builds[4]['configure']);self.assertIn('-DCMAKE_C_COMPILER=clang',builds[4]['configure'])
            sources=pc.project_c_files('my app',project)
            self.assertIn('my app/src/greeting.c',sources)
            self.assertEqual(pc.audit_sources('my app',project),['my app/src/greeting.c','my app/tests/project/test_greeting.c','my app/src/main.c'])
            fuzz=pc.fuzz_build_argv('my app',project['modules'][0]['fuzz'][0],project['modules'][0])
            self.assertEqual(fuzz,['bash','/src/container/project-fuzz-build.sh','my app','greeting','fuzz/project/greeting_fuzz.c','src/greeting.c'])
            self.assertEqual(pc.analyzer_argv('ast','my app/src/greeting.c',0,'my app')[-2:],['--include','/src/my app/include'])
            self.assertIn('-I/src/my app/include',pc.analyzer_argv('tidy','my app/src/greeting.c',0,'my app'))
    def test_root_project_uses_src_directly(self):
        self.assertIn('-DSAFE_C_PROJECT_DIR=/src',pc.build_plan('.')[0]['configure'])
        self.assertEqual(pc.audit_sources('.',PROJECT)[0],'src/greeting.c')

class ParseTests(unittest.TestCase):
    def test_hardened_elf(self):
        good='Type: DYN (Position-Independent Executable file)\n GNU_STACK 0x0 RW 0x10\n GNU_RELRO 0x1\n (FLAGS) BIND_NOW\n'
        self.assertTrue(pc.elf_hardened(good)[0])
        for bad in [good.replace('DYN','EXEC'),good.replace('GNU_RELRO','X'),good.replace('BIND_NOW','LAZY'),good.replace(' RW ',' RWE ')]:
            self.assertFalse(pc.elf_hardened(bad)[0])
    def test_fuzz_stats(self):
        text='#2 INITED cov: 7 ft: 8 corp: 1/1b\n#1000 NEW cov: 12 ft: 20\nDone 1234 runs in 30 second(s)\n#1234 DONE cov: 12 ft: 20 corp: 3/9b\n'
        self.assertEqual(pc.fuzz_stats(text),{'executions':1234,'coverage_edges':12,'features':20})
        self.assertEqual(pc.fuzz_stats('nothing'),{'executions':0,'coverage_edges':0,'features':0})

    def test_failed_tests_and_diagnostics(self):
        text='50% tests passed\nThe following tests FAILED:\n\t  1 - project.greeting.test_greeting (Failed)\n\t  2 - project.run.hello (Timeout)\nErrors while running CTest\n'
        self.assertEqual(pc.parse_failed_tests(text),[{'name':'project.greeting.test_greeting','reason':'Failed'},{'name':'project.run.hello','reason':'Timeout'}])
        self.assertEqual(pc.parse_failed_tests('100% tests passed'),[])
        rows=pc.diagnostics('/src/my app/src/greeting.c:12:5: error: unused variable [-Werror,-Wunused-variable]\nnoise\n')
        self.assertEqual(rows,[{'file':'my app/src/greeting.c','line':12,'kind':'error','check':'-Werror,-Wunused-variable'}])

class VerdictTests(unittest.TestCase):
    def rows(self,*statuses):return [{'name':str(i),'status':s} for i,s in enumerate(statuses)]
    def test_verdicts(self):
        self.assertEqual(pc.verdict(self.rows('PASS','PASS'),'PASS',[],False),('PASS',0))
        self.assertEqual(pc.verdict(self.rows('PASS','FAIL','BLOCKED'),'BLOCKED',[],False),('FAIL',1))
        self.assertEqual(pc.verdict(self.rows('PASS','BLOCKED'),'BLOCKED',[],False),('BLOCKED',2))
        self.assertEqual(pc.verdict(self.rows('PASS'),'FAIL',[],False),('FAIL',1))
        self.assertEqual(pc.verdict(self.rows('PASS'),'PASS',['changed: tools/cli.py'],True),('PASS_UNQUALIFIED_FRAMEWORK',3))
        self.assertEqual(pc.verdict(self.rows('PASS'),'PASS',['changed: tools/cli.py'],False),('BLOCKED',2))
        self.assertEqual(pc.verdict(self.rows('FAIL'),'BLOCKED',['changed: tools/cli.py'],True),('FAIL',1))
    def test_framework_differences_block_without_development(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t);make(d)
            self.assertEqual(pc.framework_differences(d,ROOT,'sha256:'+'a'*64),['missing: framework-manifest.json'])

if __name__=='__main__':
    unittest.main()
