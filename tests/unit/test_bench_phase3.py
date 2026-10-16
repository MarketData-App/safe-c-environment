import json, sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import bench_model as bm, bench_phase3
P10=['reused-source-report', 'reused-runner-report', 'reused-dataset-report', 'reused-scope-report', 'rewritten-raw-samples', 'post-hoc-policy-change', 'parent-results-in-child'];P15=['lowered-threshold', 'removed-safety-check', 'exceeded-resource-budget', 'shipped-bench-assets', 'recommendation-deploys', 'owner-threshold-altered', 'verdict-from-cold-row']

class Phase3InventoryTests(unittest.TestCase):
    def test_b_cases(self):
        rows={b['id']:b['name'] for b in bm.load_fixtures(ROOT)['b_cases'] if b['phase']==3 and b['id']!='B17'}
        self.assertEqual(rows,{'B12':'resource-and-topology-guardrails','B14':'python-first-decision-engine','B15':'evidence-integrity-and-work-accounting',
                               'B18':'starter-child-and-normal-workflow-integration'})
    def test_p_subcases(self):
        rows={(r['parent'],r['name']):r['variants'] for r in bm.load_fixtures(ROOT)['pipeline_subcases'] if r['parent'] in ('P10','P15')}
        self.assertEqual(rows,{('P10','bench-stale-or-rewritten-evidence'):P10,('P15','bench-policy-or-runtime-downgrade'):P15})
    def test_contract_lists_them(self):
        names={(s['parent'],s['name']) for s in json.loads((ROOT/'safety/contract.json').read_text())['subcases']}
        self.assertIn(('P10','bench-stale-or-rewritten-evidence'),names);self.assertIn(('P15','bench-policy-or-runtime-downgrade'),names)
    def test_every_inventoried_variant_runs(self):
        inv={(r['parent'],v) for r in bm.load_fixtures(ROOT)['pipeline_subcases'] if r['parent'] in ('P10','P15') for v in r['variants']}
        self.assertEqual(set(bench_phase3.ALL_VARIANTS),inv)
    def test_host_additions_reject_their_mutations_with_passing_controls(self):
        adds=bench_phase3.host_additions(ROOT)
        self.assertEqual({(a['parent'],a['variant']) for a in adds},set(bench_phase3.HOST_VARIANTS))
        self.assertTrue(all(a['status']=='PASS' and a['control']=='PASS' for a in adds))
    def test_selftest_hook(self):
        self.assertIn('bench_phase3.phase3_cases(',(ROOT/'tools/bench.py').read_text())

# Behavior tests beside the brief's tests (Task 29 implementer).
class Phase3BehaviorTests(unittest.TestCase):
    def test_host_additions_have_one_row_each_with_a_reason(self):
        adds=bench_phase3.host_additions(ROOT)
        self.assertEqual(len(adds),len(bench_phase3.HOST_VARIANTS))
        self.assertTrue(all(a['reason'] and a['name']==bench_phase3.NAMES[a['parent']] for a in adds),[a['variant'] for a in adds if not a['reason']])
    def test_qualification_rows_come_from_the_real_chain_as_in_the_truth_table(self):
        # B14 unit cases: the project_check of each named truth-table row equals the test fixture's (same real producer chain)
        sys.path.insert(0,str(ROOT/'tests/unit'));import test_bench_qualification as tq
        for row in bench_phase3.QUALIFICATION_ROWS:
            with self.subTest(row=row):self.assertEqual(bench_phase3.qualification_check(ROOT,row),tq.qualified(row))
        with self.assertRaises(KeyError):bench_phase3.qualification_check(ROOT,'Q99')
    def test_b14_reads_no_example_project(self):
        # FR1 (FS1 F2): B14 uses the synthetic QUALIFICATION_PROJECT string and never bench.example_projects
        sys.path.insert(0,str(ROOT/'tests/unit'));import test_bench_qualification as tq, bench
        from unittest import mock
        with mock.patch.object(bench,'example_projects',side_effect=AssertionError('B14 read an example project')):
            for row in bench_phase3.QUALIFICATION_ROWS:
                with self.subTest(row=row):self.assertEqual(bench_phase3.qualification_check(ROOT,row),tq.qualified(row))
        self.assertEqual(bench_phase3.QUALIFICATION_PROJECT,tq.PROJECT)
    def test_every_unit_case_gives_its_expected_verdict_through_the_b14_evidence(self):
        cases=bench_phase3._decision_cases(ROOT)['unit_cases']        # the same validated fixture rows, read once
        self.assertEqual(bench_phase3.unit_case_problems(ROOT,cases),[])
        bad=json.loads(json.dumps(cases[0]));bad['expect']['verdict']='PREFER_C' if bad['expect']['verdict']!='PREFER_C' else 'KEEP_PYTHON'
        self.assertEqual(len(bench_phase3.unit_case_problems(ROOT,[bad])),1)       # a wrong expectation is named, never passed
    def test_without_a_smoke_run_the_real_evidence_parts_fail(self):
        self.assertEqual(bench_phase3.b12_suite(ROOT,None,None)['status'],'FAIL')
        self.assertEqual(bench_phase3.b15_suite(ROOT,None,None)['status'],'FAIL')
        row=bench_phase3.rewritten_raw_samples(ROOT,None)
        self.assertEqual((row['parent'],row['variant'],row['status']),('P10','rewritten-raw-samples','FAIL'))

# Task 29 approval follow-ups (Task 33 implementer).
class Phase3ApprovalFollowUpTests(unittest.TestCase):
    def pending(self):
        fix=bench_phase3._decision_cases(ROOT);cand=next(c for c in fix['cases'] if c['name']=='c-candidate')
        opp=json.loads(json.dumps(cand['opportunity']));opp['approval']={'state':'PENDING'}
        return opp,[fix['policy']]+[bm.load_decision_policy(ROOT,n) for n in ('demo-latency-2x','demo-cpu-40')]

    def test_missing_approval_check_needs_a_decided_rule_outcome(self):
        # T29-APP-05: bench_decide.adoption returns INCONCLUSIVE and INVALID_EXPERIMENT unchanged, so with such a rule outcome
        # the B14 missing-approval check would pass without testing the approval rule; it must fail instead
        opp,policies=self.pending()
        holds=lambda outcome,o=opp,control=True:bench_phase3.missing_approval_holds({'outcome':outcome},o,policies,control)
        self.assertTrue(holds('KEEP_PYTHON'))
        for vacuous in ('INCONCLUSIVE','INVALID_EXPERIMENT'):
            with self.subTest(outcome=vacuous):self.assertFalse(holds(vacuous))
        self.assertFalse(holds('C_CANDIDATE_FOR_REVIEW'))
        approved=json.loads(json.dumps(opp));approved['approval']={'state':'APPROVED','reference':'r','baseline_variant':'py-reference'}
        self.assertFalse(holds('KEEP_PYTHON',o=approved))          # the approval rule is what the check tests: an approved record adopts
        self.assertFalse(holds('KEEP_PYTHON',control=False))

    def h7_input(self):
        import bench_evidence as be
        a0={'session':'s00','host_total_usec':1000,'window_usec':900,'trial_sum_usec':850,'trials':2,'launcher_cgroup_inode':7,'job_cgroup_inode':7,'status':'PASS'}
        rows=[{'cpu_usage_usec':400},{'cpu_usage_usec':450}];run={'run_id':'0'*32,'status':'VALID','accounting':[dict(a0)]}
        run[be.RECORD_KEY]=be.run_record_sha256(run)
        return {'accounting':{'resolution_usec':1}},a0,rows,run

    def test_h7_directions_give_invalid_experiment_or_fail(self):
        # T29-APP-06: spec H1 B15 (H7): a missing host total and a host total below the trial deltas are reconcile reasons
        # (bench run: INVALID_EXPERIMENT); a changed run.json record fails verify_record (compare and decide: FAIL)
        policy,a0,rows,run=self.h7_input()
        self.assertEqual(bench_phase3.h7_checks(policy,a0,rows,run),{'missing-host-total':True,'host-total-below-trial-deltas':True,'changed-run-record':True})

    def test_h7_checks_fail_when_the_enforcement_is_absent(self):
        from unittest import mock
        import bench_accounting as ba, bench_evidence as be
        policy,a0,rows,run=self.h7_input()
        with mock.patch.object(ba,'check_session',lambda *a,**k:[]):
            got=bench_phase3.h7_checks(policy,a0,rows,run)
        self.assertEqual((got['missing-host-total'],got['host-total-below-trial-deltas']),(False,False))
        with mock.patch.object(be,'verify_record',lambda run:[]):self.assertFalse(bench_phase3.h7_checks(policy,a0,rows,run)['changed-run-record'])
        broken=dict(run,status='INVALID_EXPERIMENT')        # the control: an unbound record never passes the changed-record check
        self.assertFalse(bench_phase3.h7_checks(policy,a0,rows,broken)['changed-run-record'])
        tiny=[{'cpu_usage_usec':1}]                         # no host total below the deltas can be built: the check fails, never passes
        self.assertFalse(bench_phase3.h7_checks(policy,dict(a0,window_usec=1,host_total_usec=1),tiny,run)['host-total-below-trial-deltas'])

if __name__=='__main__':unittest.main()
