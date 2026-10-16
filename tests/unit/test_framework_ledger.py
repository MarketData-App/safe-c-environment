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
          'FR6-N3-A04':'OPEN','FR6-N3-A05':'OPEN','FR6-N3-A06':'REJECTED','FR6-N3-A08':'REJECTED',   # FR6 N3b: ruling FR6-R4
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
          'FR10-PUSH-CHECKS-01':'OPEN'}                                                                   # FR10: the re-download check after the upload (FR10-R2)
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
                    self.assertTrue(attempts and attempts[-1]['before_failed'] and attempts[-1]['after_passed'])
                    self.assertEqual(row['verification'],attempts[-1])
                else:self.assertIsNone(row['verification'])
                if row['state']=='OPEN':self.assertEqual(row['history'],[])
                if row['state']=='REJECTED':self.assertTrue(any(h.get('reason') for h in row['history']))
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
                                                 'never into the tree')}.items():
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
