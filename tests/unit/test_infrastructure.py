import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools'))
from evidence import GateError, bounded, environment_gate, read_json, atomic_json
from policy import exact_ids, C_IDS, P_IDS, validate_fresh_report, lit_accounting, build_audit, gate_accounting
from qualification import ast_banned_calls
from ledger import Ledger
from schema_check import validate
ROOT=Path(__file__).resolve().parents[2]

def finding(identifier='F1',source='a'*64):
    return {'id':identifier,'origin':'simulated-reviewer','source_identity':source,'location':'C33/main:10','property':'exact-bound','severity':'major','rationale':'Concrete exact-capacity counterexample','reproducer':'C33 length=4 capacity=4','state':'OPEN','attempts':0,'history':[],'verification':None}

class EvidenceTests(unittest.TestCase):
    def test_real_process_failure_is_preserved(self):
        r=bounded([sys.executable,'-c','print("failure"); raise SystemExit(7)'])
        self.assertEqual(r['exit_code'],7);self.assertIsNone(r['failure'])
    def test_timeout_is_not_success(self):
        r=bounded([sys.executable,'-c','import time; time.sleep(2)'],timeout=.1)
        self.assertEqual(r['failure'],'TIMEOUT');self.assertNotEqual(r['exit_code'],0)
    def test_output_limit_is_not_success(self):
        r=bounded([sys.executable,'-c','print("x"*10000)'],limit=32)
        self.assertEqual(r['failure'],'OUTPUT_LIMIT')
    def test_duplicate_json_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.json';p.write_text('{"id":1,"id":2}')
            with self.assertRaises(GateError):read_json(p)
    def test_atomic_json_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.json';atomic_json(p,{'a':[1,2]});self.assertEqual(read_json(p),{'a':[1,2]})
    def test_inherited_options_are_rejected(self):
        for name in ['LIT_OPTS','ASAN_OPTIONS','FILECHECK_OPTS','CFLAGS']:
            with self.assertRaises(GateError):environment_gate({name:'--no-execute'})
        environment_gate({})

class AccountingTests(unittest.TestCase):
    def test_mandatory_gate_reconciliation(self):
        gate_accounting([{'name':'compile'},{'name':'run'}],['compile','run'])
        for rows in [[{'name':'compile'}],[{'name':'compile'},{'name':'run'},{'name':'run'}]]:
            with self.assertRaises(GateError):gate_accounting(rows,['compile','run'])
    def test_all_fixed_ids(self):
        exact_ids([{'id':i} for i in C_IDS],C_IDS)
        for ids in [C_IDS[:-1],C_IDS+[C_IDS[0]],[]]:
            with self.assertRaises(GateError):exact_ids([{'id':i} for i in ids],C_IDS)
    def test_wrong_source_report(self):
        r={'source_identity':'a','image_id':'image','policy_identity':'policy','cases':[{'id':i} for i in C_IDS],'sabotage':[{'id':i} for i in P_IDS]}
        validate_fresh_report(r,'a','image','policy')
        for fields in [('b','image','policy'),('a','other','policy'),('a','image','other')]:
            with self.assertRaises(GateError):validate_fresh_report(r,*fields)
    def test_lit_status_and_inventory(self):
        v={'tests':[{'name':'Suite :: '+i+'.test','code':'PASS'} for i in C_IDS]};lit_accounting(v,C_IDS)
        for status in ['XFAIL','XPASS','UNSUPPORTED','UNRESOLVED','TIMEOUT','EXCLUDED','PASS_AFTER_RETRY']:
            broken=copy.deepcopy(v);broken['tests'][0]['code']=status
            with self.assertRaises(GateError):lit_accounting(broken,C_IDS)
        with self.assertRaises(GateError):lit_accounting({'tests':[]},C_IDS)
    def test_missing_object_instrumentation(self):
        commands=[{'file':'/src/safety/qualification/C01/bad.c','arguments':['clang','-std=c17','-fsanitize=address,undefined','-c','/src/safety/qualification/C01/bad.c']}]
        build_audit(commands,['safety/qualification/C01/bad.c'],'asan')
        commands[0]['arguments'].remove('-fsanitize=address,undefined')
        with self.assertRaises(GateError):build_audit(commands,['safety/qualification/C01/bad.c'],'asan')
    def test_manifests_reject_unknown_fields_and_wrong_types(self):
        for kind,relative in [('contract','safety/contract.json'),('toolchain','toolchain.lock.json'),('upstream','upstream.lock.json'),('source-inventory','safety/source-inventory.json'),('starter-export','starter-export.json'),('benchmark','safety/benchmark-manifest.json')]:
            value=read_json(ROOT/relative);validate(ROOT,kind,value)
            broken=copy.deepcopy(value);broken['unknown']=True
            with self.assertRaises(GateError):validate(ROOT,kind,broken)
            broken=copy.deepcopy(value);broken['schema_version']='1'
            with self.assertRaises(GateError):validate(ROOT,kind,broken)
    def test_ast_uses_callee_not_comment(self):
        self.assertEqual(ast_banned_calls({'kind':'StringLiteral','value':'strcpy'}),[])
        self.assertEqual(ast_banned_calls({'kind':'CallExpr','inner':[{'kind':'DeclRefExpr','referencedDecl':{'name':'strcpy'}}]}),['strcpy'])
    def test_fixture_schema_rejects_missing_and_wrong_types(self):
        value=read_json(ROOT/'safety/fixtures.json');validate(ROOT,'fixtures',value)
        for mode in ['missing','type','unknown']:
            broken=copy.deepcopy(value)
            if mode=='missing':broken['cases'].pop()
            elif mode=='type':broken['cases'][0]['timeout_seconds']='10'
            else:broken['unexpected']=True
            with self.assertRaises(GateError):validate(ROOT,'fixtures',broken)
    def test_empty_report_is_rejected(self):
        with self.assertRaises(GateError):validate(ROOT,'report',{})

class SimulatedProtocolTests(unittest.TestCase):
    def ledger(self):return Ledger('a'*64,{'C33/main':['bounds','returns']})
    def test_genuine_finding_fix_requires_before_and_after(self):
        ledger=self.ledger();ledger.add(finding())
        self.assertEqual(ledger.repair('F1',before_failed=True,after_passed=True,regression_identity='exact-bound-input',source_identity='b'*64),'VERIFIED')
    def test_plausible_wrong_finding_is_retained(self):
        ledger=self.ledger();ledger.add(finding());ledger.reject('F1','Concrete control accepts exact capacity safely')
        self.assertIn('F1',ledger.findings);self.assertEqual(ledger.findings['F1']['state'],'REJECTED')
    def test_claimed_fix_that_still_fails_stays_open(self):
        ledger=self.ledger();ledger.add(finding())
        self.assertEqual(ledger.repair('F1',before_failed=True,after_passed=False,regression_identity='exact-bound-input',source_identity='b'*64),'UNRESOLVED')
    def test_repeated_failure_stops(self):
        ledger=self.ledger();ledger.add(finding())
        for i in range(3):state=ledger.repair('F1',before_failed=True,after_passed=False,regression_identity='exact-bound-input',source_identity='a'*64)
        self.assertEqual(state,'BLOCKED')
    def test_five_attempt_budget_stops(self):
        ledger=self.ledger();ledger.add(finding())
        for i in range(5):state=ledger.repair('F1',before_failed=True,after_passed=False,regression_identity='exact-bound-input',source_identity=str(i)*64)
        self.assertEqual(state,'BLOCKED')
    def test_oscillation_and_terminal_blocker(self):
        ledger=self.ledger();ledger.add(finding())
        for source in ['a','b','a','b']:
            state=ledger.repair('F1',before_failed=True,after_passed=False,regression_identity='same-bound',source_identity=source*64)
        self.assertEqual(state,'BLOCKED')
        with self.assertRaises(GateError):ledger.repair('F1',before_failed=True,after_passed=True,regression_identity='same-bound',source_identity='c'*64)
    def test_invalid_attempt_does_not_consume_budget(self):
        ledger=self.ledger();ledger.add(finding())
        with self.assertRaises(GateError):ledger.repair('F1',before_failed='yes',after_passed=True,regression_identity='same-bound',source_identity='b'*64)
        self.assertEqual(ledger.findings['F1']['attempts'],0)
    def test_duplicate_and_source_mismatch(self):
        ledger=self.ledger();ledger.add(finding())
        with self.assertRaises(GateError):ledger.add(finding())
        with self.assertRaises(GateError):ledger.add(finding('F2','other'))
    def test_full_units_questions_and_source_fingerprint(self):
        ledger=self.ledger();rows=[{'unit':'C33/main','question':x,'locations':[10]} for x in ['bounds','returns']]
        ledger.account(rows,'a'*64)
        for broken in [rows[:1],rows+[rows[0]],[{'unit':'unknown','question':'bounds','locations':[10]}]]:
            with self.assertRaises(GateError):ledger.account(broken,'a'*64)
        with self.assertRaises(GateError):ledger.account(rows,'b'*64)
    def test_ledger_schema_rejects_invalid_types(self):
        value={'schema_version':1,'source_identity':'a'*64,'units':{'C33/main':['bounds']},'findings':[finding()],'review':[{'unit':'C33/main','question':'bounds','locations':[10]}]}
        validate(ROOT,'ledger',value);value['findings'][0]['attempts']='five'
        with self.assertRaises(GateError):validate(ROOT,'ledger',value)

if __name__=='__main__':unittest.main()
