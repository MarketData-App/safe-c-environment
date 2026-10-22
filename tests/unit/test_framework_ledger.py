import json, re, sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from schema_check import validate

LEDGER='safety/framework-ledger.json'
# FR3 (FS1 F11): the framework findings that moved out of the example ledger, and the open FS1 framework findings.
EXPECTED={'P2-T13-FETCH-01':'REJECTED','P2-T14-TSAN-01':'UNRESOLVED','P3-T15-CHILD-BUDGET-01':'VERIFIED',
          'S1-T14T-ANALYZER-FD-01':'VERIFIED','P3-T15-REAPED-FLAKY-01':'VERIFIED','P2-MUTANT-TEARDOWN-FLAKY-01':'VERIFIED',
          'P3-DD-UNIT-TMPFS-01':'OPEN','S4-01':'VERIFIED','A4R-04':'OPEN','FW-CONSTRUCTION-GUARD-01':'OPEN',   # FR12: S4-01 fixed
          'FR3-13':'VERIFIED','FR3-14':'VERIFIED','FR3-15':'VERIFIED',      # FR3c: the approval conditions of verdict round 2
          'FR3-16':'VERIFIED',                                              # FR3d: verdict round 3 reopened FR3-15 (FR3-16)
          'FR3-17':'VERIFIED',                                              # FR3e: verdict round 4 (one fail-closed boundary)
          'FR3-19':'VERIFIED',                                                  # FR3f: ruling FR3-R9 (every capped host parse)
          'FR3-20':'VERIFIED','FR3-21':'VERIFIED','FR3-22':'VERIFIED',
          'FR4-IMG-BOUND-01':'OPEN','FR4-A01':'VERIFIED','FR4-A03':'OPEN',          # FR4: the LOW findings of verdict round 5
          'FR6-N3-A04':'DUPLICATE','FR6-N3-A05':'OPEN','FR6-N3-A06':'REJECTED','FR6-N3-A08':'REJECTED',   # FR6 N3b: ruling FR6-R4
          'FR6-N3-A01':'VERIFIED','FR6-N3b-A03':'OPEN','FR6-N3b-A04':'OPEN',                          # FR6 N4 Step 0: re-review N3b
          'P2-B2-SRCPOL-MEM-01':'VERIFIED','P2-B2-STEPFAIL-01':'VERIFIED',                            # FR7a: the ported B2 framework fixes
          'FR6-N4-A02':'VERIFIED','FR6-N4-A03':'VERIFIED','FR6-N4-A04':'VERIFIED','FR6-N4-A05':'VERIFIED',   # FR7b: verdict FR6 N4
          'FR6-N4-A06':'OPEN','FR6-N4-A07':'REJECTED','FR6-N4-A08':'REJECTED','FR6-N4-A09':'VERIFIED','FR6-N4-A10':'VERIFIED',
          'P2-COV-ATOMIC-01':'REJECTED','FR7a-M1':'REJECTED',                                           # FR7b: coverage counters (FR7b-A03); FR7-R1
                                                                                                        # FR12: P2-COV-ATOMIC-01 closed by the owner decision of 2026-10-16
                                                                                                        # FR10: FR7a-M1 closed by the owner decision of 2026-10-15
          'FR7b-A01':'VERIFIED','FR7b-A02':'VERIFIED','FR7b-PROCESS-01':'REJECTED',                       # FR7b fix round 1: ruling FR7-R2
          'FR7b-SWAP-TICK-01':'VERIFIED',                                                                 # FR7b: ruling FR7-R3
          'FR7b-IDENTITY-RULE-01':'VERIFIED',                                                             # FR7b: ruling FR7-R4; FR12: owner rule
          'FR5D-02':'OPEN',                                                                               # FR5 fix round 4: guard limit
          'FR10-PUSH-CHECKS-01':'VERIFIED',                                                               # FR10: the re-download check after the upload (FR10-R2)
                                                                                                          # INT1 (verdict M1, M1-A04): closed, the re-download matched
          'EX1-01':'OPEN','EX1-A02':'VERIFIED',                                              # T6 item 3: EX1-A02 repaired
          'EX13-B11-STANDALONE-01':'OPEN','EX13-B13ECHO-01':'DUPLICATE','EX13-P16-SELECTOR-01':'DUPLICATE',   # T6: amendment E C5
          'EX17-B17-CMULTI-01':'OPEN',                                                                    # EX-17: the B17 dimension no framework control declares
          'EX17-A04':'VERIFIED',                                                                          # EX-18b: the unit smoke job runs in bench selftest
          'EX18b-CONTROL-CASE-01':'DUPLICATE',                                                                # EX-18b: a control pair of another case
          'MERGE1-CONFIRM-PATH-01':'VERIFIED',                                                            # the merge of Release 1: confirm_verified path
          'FWSCOPE-01':'VERIFIED',                                                                        # T3 FW-SCOPE: standalone examples leave the framework scope
          'FW-HOOK-01':'VERIFIED',                                                                        # FW-HOOK: the project lock route of the privacy hook (F14)
          'EX18b-A05':'OPEN','EX18b-A08':'VERIFIED',                                                      # EX-18c: the deferred EX-18b approver findings
                                                                                                          # EX-19: A08 closed, local window attempts recorded
          'EX18c-CHAIN-DIGEST-01':'VERIFIED',                                                             # EX-18c: a decide never changes a chain digest
          'T3-A01':'VERIFIED','T3-A02':'VERIFIED','T3-A03':'VERIFIED','T3-A04':'VERIFIED',                # FIX1: the T3 approver findings (T3-A05 in T3-A01)
          'T3-A06':'VERIFIED','T3-A07':'VERIFIED','T3-A08':'VERIFIED',
          'EX18c-A02':'VERIFIED','EX18c-A03':'VERIFIED',                                                  # FIX1: the EX-18c approver findings (EX18c-A05 in A03)
          'FW-HOOK-02':'VERIFIED',                                                                        # FIX1 (T4-A09): the fix round 1 of FW-HOOK-01 (T4-A14 in it)
          'EX19-LOCAL-ROWS-01':'VERIFIED',                                                                # EX-19: a local plan without a row count
          'EX19-LOCAL-MEMORY-01':'OPEN','EX19-LOCAL-ESTIMATE-01':'VERIFIED',                              # EX-19: memory trials of a local run; local window estimate
                                                                                                          # T5-R1 (finding T5-A08): the local window estimate repaired
          'T5-A01':'VERIFIED','T5-A02':'VERIFIED','T5-A06':'VERIFIED','T5-A07':'VERIFIED','T5-A11':'VERIFIED',   # T5-R1: the EX-19 approver findings
          'T5-A05':'VERIFIED',                                                                              # T5-R1: the pyperf agreement check at the 1 ms floor
                                                                                                          # T6 item 5: the one-sided rule repaired it
          'FIX1-A02':'VERIFIED','FIX1-A03':'VERIFIED','FIX1-A06':'VERIFIED','FIX1-A07':'VERIFIED',        # T6 item 4: the FIX1 approver findings
          'T9-A10':'VERIFIED',                                                                            # T6 item 6: T9 framework hit 1
          'T6-ZOMBIE-01':'OPEN',                                                                          # T6: zombies of detached processes in a holder
          'T5R1-A01':'VERIFIED','T5R1-A02':'VERIFIED','T5R1-A04':'VERIFIED',                              # T6-R1: the T5-R1 re-review findings (A05 text in EX18b-A08)
          'T6-A02':'OPEN','T6-A03':'OPEN',                                                                # T6-R1: the T6 approver backlog rows (A01, A07 in T5-A05 and T9-A10)
          'FW-HOSTMEM-01':'VERIFIED','T6R1-A02':'VERIFIED','T6R1-A01':'OPEN',                              # T6-R2 (R27, R30): host members; the T6-R1 approver rows
          'FW-HOSTMEM-02':'VERIFIED','T6R2-A03':'VERIFIED','T6R2-A02':'REJECTED',                          # T6-R3 (R33): data directory, notice member; A02 coverage
          'T14-A01':'VERIFIED','FW-AST-WORK-01':'VERIFIED',                                               # T6-R4 (R37, R38): P15 probe; AST work capacity
          'T6R4-A02':'VERIFIED','T6R4-A01':'VERIFIED','FW-TESTSTRENGTH-01':'VERIFIED',      # T6-R5 (R41): P15 native block; AST job paths; test-strength label
          'FW-REFCOVER-01':'VERIFIED','FW-DATASETREF-01':'VERIFIED',      # T6-R6 (R48, R51): the reference of the planned selectors; planned dataset refs
          # T7 (FW-QUAL, C6): the framework backlog rows that the example tasks and their approvers named; all OPEN, none fixed
          **{rid:'OPEN' for rid in ('T7-HIT-A','T7-HIT-B','T7-HIT-C','T7-HIT-D','T7-HIT-E','T7-HIT-F','T14ON-A01','T14ON-A02','T14ON-A03',
                                    'T11T12R1-A08','T6R3-A02','T7-HIT-L','T7-HIT-M','T7-HIT-N','T6R5-A01','T6R5-A02','T6R5-INFO','LREX-N6',
                                    'LREX-N9','T6R6-A01','T6R6-NOTE','T7-HIT-T','T7-HIT-U','T7-HIT-V','T7-HIT-W','T7-HIT-X','T7-HIT-Y',
                                    'T7-HIT-Z','T7-WORKUSE-01')},
          'FW-PLANWALLS-01':'VERIFIED',                                   # T6-R7 (R86, R87): plan every caller trial from measured walls (2 attempts)
          'FW-DECIDE-NAMODE-01':'VERIFIED','FW-WINDOWS-GUARDRAIL-01':'VERIFIED','FW-RUNTIMECACHE-ARGS-01':'OPEN',   # T6-R8 (R93): a blocked row counts in its own modes; guardrail rows are no evidence
          'FW-CASES-B08PROBE-01':'VERIFIED','FW-CASES-STUBREF-01':'VERIFIED','FW-CASES-KERNELWALL-01':'OPEN',   # T6-R9 (R95, R96): panel phases; reference deadline tiers; kernel estimate backlog
          # T6-R7 item 4(b): the framework backlog rows of board item sc-doj (R66, R86); all OPEN, none fixed
          **{rid:'OPEN' for rid in ('T7-HIT-AA','T7-HIT-BB','T7-HIT-CC','T7-HIT-DD','T7-HIT-EE','T7-HIT-FF','ML-A05','T7-HIT-M2','T7-A04',
                                    'M2d-A05','FW-TOPLOCK-01','T20c-A02','FW-CAPNATIVE-01','FW-IMAGEBUDGET-01')}}
# FR3-06 (ruling FR3-R3): framework rows use neutral references. The verbatim history stays in the example ledger.
# FR3-14: also the framework release branch names; the generic word "worktree" stays (ruling: restore the source wording).
INTERNAL=re.compile(r'(?i)perf-lab|fw-release|fw-license|t3fix|artifacts/(runs|approvals|instances|bench)/|\.superpowers|/home/|batch-S\d|task-(DD|F1)|alo-reference')

def load():return json.loads((ROOT/LEDGER).read_text())

class FrameworkLedgerTests(unittest.TestCase):
    """FR3 (FS1 F11): the framework keeps its own findings ledger with the history of each finding."""
    def test_ledger_validates(self):
        validate(ROOT,'ledger',load())
    def test_every_framework_finding_is_recorded_once_with_its_state(self):
        rows=load()['findings'];ids=[r['id'] for r in rows]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertEqual({r['id']:r['state'] for r in rows},EXPECTED)
    def test_states_match_the_history(self):
        for row in load()['findings']:
            with self.subTest(id=row['id']):
                attempts=[h for h in row['history'] if 'attempt' in h]
                self.assertEqual(row['attempts'],len(attempts))
                if row['state']=='VERIFIED':
                    self.assertTrue(attempts and attempts[-1]['after_passed'])
                    if not attempts[-1]['before_failed']:self.assertEqual(attempts[-1].get('label'),'TEST-STRENGTH EVIDENCE')    # R41: the labeled class only
                    self.assertEqual(row['verification'],attempts[-1])
                else:self.assertIsNone(row['verification'])
                if row['state']=='OPEN':self.assertEqual(row['history'],[])
                if row['state']=='REJECTED':self.assertTrue(any(h.get('reason') for h in row['history']))
    def test_a_duplicate_row_names_its_reason_and_its_pointer(self):
        """T6 (amendment E C5): a DUPLICATE row went through tools/ledger.py Ledger.reject with duplicate_of; its history
        holds the reason and the row ID that now carries the obligation."""
        rows=[r for r in load()['findings'] if r['state']=='DUPLICATE']
        self.assertEqual(len(rows),4)
        for row in rows:
            with self.subTest(id=row['id']):
                self.assertTrue(any(h.get('reason') and re.fullmatch(r'[A-Z][A-Z0-9-]{2,63}',str(h.get('duplicate_of'))) for h in row['history']))
    def test_rows_use_neutral_references_and_name_their_example_source(self):
        text=(ROOT/LEDGER).read_text()
        self.assertIsNone(INTERNAL.search(text))
        for row in load()['findings']:
            with self.subTest(id=row['id']):
                self.assertRegex(row['origin'],r'(example ledger row [A-Z0-9-]+|new framework row)')
    def test_the_ledger_source_identity_is_a_commit_only(self):
        """FR3-14: the top-level source identity names a commit and no branch."""
        self.assertRegex(load()['source_identity'],r'^commit [0-9a-f]{7,40}\b')
    def test_every_source_identity_names_a_commit(self):
        """FR3-12 (ruling FR3-R5): each row and each attempt names the commit of its source."""
        for row in load()['findings']:
            with self.subTest(id=row['id']):
                self.assertRegex(row['source_identity'],r'\bcommit [0-9a-f]{7,40}\b')
                for h in row['history']:
                    if 'attempt' in h:self.assertRegex(h['source_identity'],r'\bcommit [0-9a-f]{7,40}\b')
    def test_the_neutral_rows_keep_the_evidence(self):
        """FR3-12: run ids, commit ids, "identical inputs" and the caveats stay; only names of internal places go."""
        rows={r['id']:json.dumps(r) for r in load()['findings']}
        for rid,texts in {'P2-MUTANT-TEARDOWN-FLAKY-01':('b0a76e10','9c364e52','7f959d68','0548a819','0eefa219','54a78906','16401ba6','identical inputs',
                                                         'the exit-134 path was not exercised live','F1-POLICY-01','F1-ASANLANE-01'),
                          'P3-T15-REAPED-FLAKY-01':('identical inputs','b0a76e10','9c364e52','b89269ab','b7c614f5','1aaeb1ad','the live run did not exercise a pool row'),
                          'P3-T15-CHILD-BUDGET-01':('no gate weakened','No other worktree ran between 06:50 and 13:25','7d68e75b','c41876a5','5d3b4317','32c34674','4bee96d','f0d258b','400bb5d'),
                          'P2-T14-TSAN-01':('d693674a','ef919376','69b1f80c','ac037963','7163f822','g_rw_lock_get_impl'),
                          'S1-T14T-ANALYZER-FD-01':('ef837a24','04354f30','4554d433'),
                          'P3-DD-UNIT-TMPFS-01':('071d623a','e50f0e5e','883677ce','Not measured'),
                          'P2-B2-SRCPOL-MEM-01':('a3398a2b','40574cf0','45bcb9a5','1776fe53','a1618c94','f7473fcc','89940ada','685240bf',
                                                 '33dc3c80','b53b103c','P3-DD-UNIT-TMPFS-01'),
                          'P2-B2-STEPFAIL-01':('40574cf0','f940b501','3f50bcf0','identical inputs'),
                          'FR6-N4-A10':('64e82ecf','6e1fd481','identical inputs','Not run live'),
                          'P2-COV-ATOMIC-01':('64e82ecf','6e1fd481','15bbf489','0c84e641','did not reproduce the loss','46c39d20','e488644e',
                                              "not reproduced under the gate's covered-line metric in the framework reproducer",
                                              'not reproduced as a defect','the atomic counter hardening stays on','owner decision of 2026-10-16',
                                              'lines 6021 and 6026 of 6349','the gate decision was not at risk'),
                          'FR6-N4-A07':('36 of the moved','12 kept','do not delete it','08874f7c7fb742028f1f1ef924dab269','ff6fb069d99f416eaba15f863a39fef5'),
                          'FR7b-SWAP-TICK-01':('471b2b02','2009af12','cea825b0','5d63b8f4','625b2aff','not a security race','a corrected test expectation'),
                          'FR7b-A01':('3d042a83','db142a31','identical inputs'),
                          'S4-01':('7646594a','7c4c7c41','e87f9864','identical inputs','its assertions are unchanged'),
                          'FR7b-IDENTITY-RULE-01':('a771e287','b2e42262','identical inputs','a replaced file is always refused',
                                                   'never the only signal','the swapped file never runs'),
                          'FR7a-M1':('GFORTRAN_8','Red Hat GCC 10.2.1','no .comment section','FR7b-A08','owner decision of 2026-10-15',
                                     'written offer'),
                          'FR10-PUSH-CHECKS-01':('e8c9c5d2bfb96073965da6c83260a5aa6f7a9703bbf05307c32c41976b51d99f','512,160,947 bytes',
                                                 'images-sdk-developer-v3','snapshot_package_url','131 of 131',
                                                 'openssl 3.5.7-1~deb13u3','linux 6.12.111-1','GitHub release notes',
                                                 'never into the tree'),
                          'MERGE1-CONFIRM-PATH-01':('c95b5e3256e54e65a284b699c3b8bb7f','1eb09e931f8b418baf54ed468aa0e4f4',
                                                    'dfdc7370c15249d5a98d1ed4d51754af','672da38d7e3d44fb91176b6a5e29a2ea',
                                                    '4197290','03cfa84','Identical inputs','failed closed'),
                          'FWSCOPE-01':('705d57df','24aee615','7ea226a','d878174','identical inputs'),
                          # FIX1 (T4-A09): the fix round 1 evidence moved with its attempt to FW-HOOK-02
                          'FW-HOOK-01':('4b39f907','6e86aa01','b90d354','75b301ab','identical inputs','FW-HOOK-02'),
                          'FW-HOOK-02':('5e83d371','85334471','b12ebe0','dea1109','114/114','Identical inputs except one fixture line',
                                        'test_a_linked_lock_is_ignored','FW-HOOK-01','T4-A09','TreeRouteModeTests','TaggedTreeRouteModeTests'),
                          # FIX1: RED run d3917f64 at 21d3f85, GREEN run 77552e1f at 7f8c944
                          'T3-A01':('d3917f64','77552e1f','21d3f85','6dc8aba','identical inputs','T3-A05'),
                          'T3-A02':('d3917f64','77552e1f','21d3f85','e724f51','regression assertions are unchanged'),
                          'T3-A03':('d3917f64','77552e1f','21d3f85','6dc8aba','identical inputs'),
                          'T3-A04':('d3917f64','77552e1f','21d3f85','e724f51','regression assertions are unchanged'),
                          'T3-A06':('d3917f64','77552e1f','21d3f85','6dc8aba','identical inputs'),
                          'T3-A07':('d3917f64','77552e1f','21d3f85','e719047','identical inputs'),
                          'T3-A08':('d3917f64','77552e1f','21d3f85','7c7f9a2','TEXT EVIDENCE'),
                          'EX18c-A02':('d3917f64','77552e1f','21d3f85','7f8c944','TEXT EVIDENCE'),
                          'EX18c-A03':('d3917f64','77552e1f','21d3f85','7f8c944','TEXT EVIDENCE','EX18c-A05'),
                          'EX18c-CHAIN-DIGEST-01':('84727560','625c1ba4','7fd0920d','2d859eb1','646ef63','56e347f','identical inputs',
                                                   # EX18c-A02 (FIX1): the direct RED evidence of the changed digest and the
                                                   # actual RED causes of the two other regressions
                                                   'test_a_final_pass_with_a_bound_triggered_look1_record_extends',
                                                   "AttributeError: bench_windows has no record_digest",
                                                   'no unit of window 1a triggered an extension'),
                          'EX18b-A08':('168c7e0f','645541c4','5cfa9b29','a1b2dc01','039059a','72f9080','identical inputs',
                                        'T5-A04','7a9924e','1 != 0','T5-A03','LocalWindowChainTests','LocalDecideTests',
                                        # T6-R1 (T5R1-A05): the sentence break, text only
                                        'with the same tests. T5-R1 (finding T5-A04)','T5R1-A05'),
                          'EX19-LOCAL-ROWS-01':('168c7e0f','645541c4','039059a','72f9080','identical inputs'),
                          # T5-R1: RED check-fast 822c2ceb at 204eb64 (source f5b9b979), GREEN 4c7f0725 at 77c8afa (source d09f92d0)
                          **{rid:('822c2ceb','4c7f0725','f5b9b979','d09f92d0','204eb64','77c8afa','identical inputs')
                             for rid in ('T5-A01','T5-A02','T5-A06','T5-A07','T5-A11','EX19-LOCAL-ESTIMATE-01')},
                          'T5-A05':('015355da','a631e9bb','31,650,646','30,580,927','1,069,719','1,000,000','d19a62de','forged self-timing',
                                    # T6 item 5: RED check-fast 223e5c97 at fe463c6 (source 9e4c4a4b), GREEN c6ef3f91 at 6bd9539 (source d4816ac7)
                                    '223e5c97','c6ef3f91','9e4c4a4b','d4816ac7','fe463c6','9a66734','490,489','1,661,031',
                                    'SelfTimingTests','test_the_pyperf_rule_is_one_sided_here_and_on_the_host','identical regression tests',
                                    # T6-R1 (T6-A01): 424 recorded rows of 212 distinct trials (was '424 honest' pairs); (T6-A07) the
                                    # below-bracket B15 check
                                    '212 distinct honest','424 recorded rows','274.8 ms wall','T6-A01','T6-A07','forged-pyperf-wall-below'),
                          'EX1-A02':('223e5c97','c6ef3f91','fe463c6','99c1561','ElfRecordTests','WheelPathRuleTests','WheelPathAuditTests',
                                     'project-wheel-path','identical regression tests'),
                          **{rid:('223e5c97','c6ef3f91','fe463c6','91a671f',test,'identical regression tests')
                             for rid,test in (('FIX1-A02','RealTreeListingTests'),('FIX1-A03','PullRequestCountTests'),('FIX1-A07','FrameworkModeTests'))},
                          'FIX1-A06':('223e5c97','c6ef3f91','fe463c6','91a671f','TEXT EVIDENCE','SymbolicLinkTextTests'),
                          'T9-A10':('223e5c97','c6ef3f91','fe463c6','cd337f3','UnitGroupImportTests','identical regression tests',
                                    'T6-A07','test_a_module_that_raises_system_exit_at_import_is_one_failed_id','70690d72','4c181d99'),
                          'T6-ZOMBIE-01':('223e5c97','fe463c6','6bd9539','RuntimeError','Cause inferred','git 2.47.3'),
                          # T6-R1: RED check-fast 70690d72 at f3811ff (source 2ee9880a), GREEN 4c181d99 at 8e34efa (source f94a5413)
                          **{rid:('70690d72','4c181d99','2ee9880a','f94a5413','f3811ff',fix,'identical regression tests',test)
                             for rid,fix,test in (('T5R1-A01','30631ad','test_a_single_record_trial_breaks_no_work_rule_here_and_on_the_host'),
                                                  ('T5R1-A02','30631ad','test_a_local_window_with_a_single_record_unit_decides_from_the_in_job_rules'),
                                                  ('T5R1-A04','db854ef','test_a_failure_of_the_job_fields_keeps_the_partial_flag_of_the_plan'))},
                          **{rid:('framework backlog','Owner: framework release coordinator') for rid in ('T6-A02','T6-A03','T6R1-A01')},
                          # T6-R2: RED check-fast 74d7a922 at 36e75e5 (host members) and 13dcbd55 at 56bb0e8 (T6R1-A02), GREEN 13e4a4c8 at f599db2
                          'FW-HOSTMEM-01':('74d7a922','36e75e5','a8d5328c','13dcbd55','13e4a4c8','c8885b6c','f599db2','80aaa0d','d8a6bef',
                                           'HostMemberRecipeTests','HostMemberHostTests','HostMemberLockTests','ENOSPC','identical regression tests'),
                          'T6R1-A02':('13dcbd55','56bb0e8','8452de31','13e4a4c8','c8885b6c','f599db2','11ed757',
                                      'test_a_panel_point_and_a_single_record_unit_bind_each_other','identical regression tests'),
                          # T6-R3: RED check-fast ea5000d4 at 9bcb4a8, GREEN 05c3cf6a at 74446a0
                          'FW-HOSTMEM-02':('ea5000d4','9bcb4a8','c1cd9e29','05c3cf6a','74446a0','c9828401','0cdc8b0','347c1bd',
                                           'WheelDataTests','NoticeMemberTests','NoticeMemberLockTests','identical regression tests'),
                          'T6R2-A03':('ea5000d4','05c3cf6a','0cdc8b0','test_a_host_member_with_a_control_character_is_refused',
                                      'identical regression tests'),
                          'T6R2-A02':('COVERAGE EVIDENCE','ea5000d4','05c3cf6a','9bcb4a8','74446a0','HostMemberRealConstantTests',
                                      'No RED is claimed'),
                          # T6-R4: RED d74c5b8c at c59d2a2, GREEN 9585f6a9 at 19596e9 (T14-A01); RED 6e8eaded at 9fc7dae,
                          # GREEN 716563ec at 3144936 (FW-AST-WORK-01); full run ids and 64-hex source identities
                          'T14-A01':('d74c5b8ce30f4425b1700cf66336f476','9585f6a96ff24707a16ba33bbe4c038c',
                                     '41b027f349f90972713ebe80a9366890ff39b20d7c9852746e98a364247bac8c',
                                     '1aa40aa2ec584ff72df648ddf455d6ed5e3b88e8c59751ac0dda90b96f721435','36cdb118464347f29cacfa9caba134cb',
                                     '8237a6df2e7b780621b37f42a02417f02b60f933933545c33e2b8684a85d8511','c59d2a2','7bf8395','19596e9',
                                     'ProbeDeclarationTests','third-party lock is missing','identical regression tests'),
                          'FW-AST-WORK-01':('6e8eaded80ad4878a1abb76247c17439','716563ec1800426abb7c115826ad1f88',
                                            '7f750f5ef3427fe7b11b729d13952791e5bf128da7c9365e1fdd503896b307e3',
                                            '04cd8bee22d729f2ea9f2e72ad2d16ed6abd73b96e1807b2633c82fc39c4921d',
                                            'fea8410cf36143a793aa5bbc589700f1',
                                            '5323156c3fc6687ce6fe5b25250410c64e38a4d112116bf7f0f0923f3f976e49',
                                            '9fc7dae','54eb1d7','3144936','AstWorkCapacityTests','identical regression tests'),
                          # T6-R5: RED 0eef6c1d at 67fdcb3, GREEN ae293b2f at 61cd905 (T6R4-A02, FW-TESTSTRENGTH-01); T6R4-A01 is
                          # TEST-STRENGTH EVIDENCE (R41): no RED, the code under test is unchanged
                          'T6R4-A02':('0eef6c1d854d45659a54d4297e9c185c','ae293b2f32764265a89720bb9ea24744',
                                      '71428ba96726e337064b3470003166722b24ac8b99a94f17f6b91877aac39d40',
                                      '3d2551f9fd42184c97dc8f1c4ac7d9b659d814b74af3b3a06058ad5f1978e293','67fdcb3','612db19','61cd905',
                                      'ProbeNativeTests','identical regression tests'),
                          'T6R4-A01':('TEST-STRENGTH EVIDENCE','58f42e9','61cd905','90db95da7d4944b1ae2eb05835507f7e',
                                      'ae293b2f32764265a89720bb9ea24744','AstWorkCapacityTests','no failing run is claimed'),
                          'FW-TESTSTRENGTH-01':('0eef6c1d854d45659a54d4297e9c185c','ae293b2f32764265a89720bb9ea24744','67fdcb3','8fa665b','61cd905',
                                                'EX8-SPEC-01','EX9-TESTS-01','identical regression tests'),
                          # T6-R6: RED e119bec5 at d0c583d, GREEN 68275686 at 1efe765 (FW-REFCOVER-01, FW-DATASETREF-01)
                          **{rid:('e119bec5f60148b486b4c3dd148d9b86','682756868a5a48d99edb7ef4a3c91c2a',
                                  '6a965d530cb61a75546640d55fe4d8f48d128be2408e859b224ba46a41998e22',
                                  '3a9ad99179e4a9421d5ac512d59bbebf719521d08eff0d98a69e53d501279fed','d0c583d','1efe765',
                                  'identical regression tests','d40b67ce' if rid=='FW-REFCOVER-01' else '1dcb3ba',tests)
                             for rid,tests in (('FW-REFCOVER-01','LocalJobReferenceTests'),('FW-DATASETREF-01','PlannedPointDatasetTests'))},
                          # T6-R7: the before and after runs, their source identities and commits, and the demo run of the defect
                          'FW-PLANWALLS-01':('0b36965011d14d6db2d5284c08244fa7','55c9a061fb7840cc8570d7071e930e41',
                                             '4dad65b4778cdcfe82020c79b729b09eb472c77412e48c3b29a66d0223fbb958',
                                             '31438d9c95ad8330255e7b364ac45997e8a5d2014a2c6425f59320518e376f6e','6f709b6','de2fe24',
                                             'identical regression tests','34dc1922','wall-not-measured','NoExtrapolationTests',
                                             # R87: fix 2 (the probe warmup and the 1,200 s bound) and the integration proof
                                             '0f6bebc77faf46bbaa95c6842524c79d','ca51664dcee6484ea136ad1121a5e64d','36c1098','7eaa971',
                                             '52d969fd9f814464b835ad5436bb1d5a','389eebaf25f543b694b906521d66e1a5','PROBE_SMOKE_CAP_SECONDS',
                                             'ProbeBoundTests'),
                          # T6-R8: RED b526e0e3 at 11698af, GREEN a1d98e23 at d1ae3db (R93)
                          **{rid:('b526e0e31e81452b86b1c0f4779c3224','a1d98e23455f4137a5c849e19d5cdfd6',
                                  '248e95618274f2e7e5554dd4b834eda88cae6a1d563d663f4c9a2dcd15d5c3d2',
                                  '43a69fa6c3d0c29379ebe86a4688aa44f8ab07cc27feac9799c1b5c02c45e8bc','11698af','d1ae3db',
                                  'identical regression tests','337732f4' if rid=='FW-DECIDE-NAMODE-01' else 'doctor not run',tests,
                                  *(('19b852c1013241dc834c50976e647cc4','8bc8b3e0a81e447da49e68f845556428','3d3488c','6f7dc80','1d1db6e','d34d927',
                                     '66b825f664431e0e64ae890502b95b47d3e84f2f18efcba80e7ec4db01caeb48',
                                     # T6-R9 (R97): the T6R8-A07 before-run of the final tests over 5a566e8; attempt 3 (T6R8-A10) and T6R8-A08
                                     '40ff7d78183d4000a5455ff09b4f9eda','4a86f13b644e9d0610a052365998e2358974cb2abe4470464538c8dc93e34425',
                                     '5ff24d1a9a8945dc8b2c069ba2149b9c','0b02485cb4db4671982d3e333e13fe55','92e67ea','673c61d',
                                     'T6R8-A07','T6R8-A10','T6R8-A08','TEST-STRENGTH EVIDENCE') if rid=='FW-DECIDE-NAMODE-01' else ()))
                             for rid,tests in (('FW-DECIDE-NAMODE-01','RuleBlockedRowModeTests'),('FW-WINDOWS-GUARDRAIL-01','WindowEvidenceGuardrailRowTests'))},
                          # T6-R8 round 2 (R94): attempt 2 of FW-DECIDE-NAMODE-01, RED 19b852c1 at 3d3488c, GREEN 8bc8b3e0 at d34d927
                          # T6-R9 (R95): RED 5ff24d1a at 92e67ea, GREEN 0b02485c at d0d8196 (FW-CASES-B08PROBE-01, FW-CASES-STUBREF-01)
                          **{rid:('5ff24d1a9a8945dc8b2c069ba2149b9c','0b02485cb4db4671982d3e333e13fe55',
                                  'ac03fc788ff3b00de775c3bb4b7a43d6738f5a28c3273bb874d29aae47138640',
                                  '4bc95631e29c7a7525d25170157a15bf567717f71e48f797819b952553b294c8','92e67ea','d0d8196',fix,
                                  'identical regression tests','389fbba5',run,tests)
                             for rid,fix,run,tests in (('FW-CASES-B08PROBE-01','6afe78a','9c7c4dcd','PanelPhaseTests'),
                                                       ('FW-CASES-STUBREF-01','d0d8196','7c6940c6','StubReferenceDeadlineTests'))},
                          'FW-CASES-KERNELWALL-01':('337732f4','3.34 times','language-only-s02','Owner: framework release coordinator'),
                          # T6 (amendment E C5): the framework rows that only the standalone example can close point to its ledger
                          **{rid:('amendment E C5',exl) for rid,exl in (('FR6-N3-A04','EXL-CODEC-ASSERT-01'),('EX13-B13ECHO-01','EXL-B13ECHO-01'),
                                                                        ('EX13-P16-SELECTOR-01','EXL-P16-SELECTOR-01'),
                                                                        ('EX18b-CONTROL-CASE-01','EXL-CONTROL-CASE-01'))},
                          'EX17-B17-CMULTI-01':('framework backlog','Owner: framework release coordinator','NOT_RUN')}.items():
            for text in texts:
                with self.subTest(id=rid,text=text):self.assertIn(text,rows[rid])
    def test_every_open_row_names_its_owner_and_phase(self):
        """FINAL-02: every OPEN or UNRESOLVED row names its owner (the framework release coordinator, or the owner where
        the decision is the owner's) and its phase in its rationale, in the form `Owner: X. Phase: Y.`."""
        rule=re.compile(r'Owner: (framework release coordinator|owner)\. Phase: [a-z][^.]{2,160}\.')
        for row in load()['findings']:
            if row['state'] in ('OPEN','UNRESOLVED'):
                with self.subTest(id=row['id']):self.assertRegex(row['rationale'],rule)
    def test_rows_name_no_example_source_file(self):
        """FR5 (ruling FR5-R1 item 4): the ledger rule keeps the history of a finding, not the example's file and symbol
        names (FR3-R5: neutral references); the evidence (run ids, commits) stays."""
        self.assertIsNone(re.search(r'(?<![A-Za-z0-9])(?:lib)?pl[-_][a-z]',(ROOT/LEDGER).read_text()))
    def test_ledger_is_protected_and_exported(self):
        self.assertIn('safety/',json.loads((ROOT/'safety/protected-paths.json').read_text())['paths'])
        self.assertIn(LEDGER,json.loads((ROOT/'starter-export.json').read_text())['files'])
