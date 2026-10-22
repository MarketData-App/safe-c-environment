# Review and approval protocol

Status: owner decision, binding for this repository. AGENTS.md holds a short
summary. This file is the detailed reference.

Approver amendment (owner decision, 2026-10-05): the independent authority for
reviews and approvals is a fresh-context adversarial agent approver, not a human.
The implementing agent launches it with an explicit brief to prove the change
flawed, AGENTS.md hygiene rules, read-only repository access and one assigned
output area. The implementer never writes, edits or summarizes away a verdict;
record it verbatim with approver model, brief digest, source identity and
findings. An unresolved high-severity finding, missing evidence or an approver
that edited source is a rejection. One approver is enough for every change,
including protected policy, fixture, toolchain and runner changes (owner decision
2026-10-06: "one reviewer is ok"; this replaces an earlier two-approver rule). Repair
findings through the ledger and launch new approvers for the repaired source;
an approval binds only the exact source identity it reviewed. Agent approval is
model judgement, not proof; trusted tools still decide deterministic results.

Owner decision, quoted: "let's use that workflow for reviews/approvals from here
on out. use adversarial agent approvers, not human ones." The implementing agent
recorded this quotation; the repository cannot verify it independently.

Briefs: a brief lists every changed path since the last approved state, including
untracked source inputs, and the exact source identity. Approvers may examine
anything beyond the brief and must report scope gaps. A brief that omits a changed
path voids the approval for that path.

Records: each round keeps the full brief, every verdict verbatim and a record with
digests, approver model, head commit and source identity under
`artifacts/approvals/<round>-<head>/`. That directory is untracked because
verdicts can contain local paths; the commit that lands approved work names the
round and its outcome.

Ledger closure classes (rulings R41, T16R1-A01 and T16R1-A02): a finding closes
VERIFIED in one of two ways.

1. Behavioral repair. The same regression fails before the fix and passes after
   it, under identical relevant inputs (`Ledger.repair`, `before_failed` true).
   `Ledger.repair` never verifies a row with `before_failed` false.
2. Test-strength evidence. The finding is that a test or a specification is too
   weak, and the fix adds assertions or text only. Three conditions apply:
   (1) the code under test is unchanged by the fix commits (else the fix is a
   behavioral repair and needs a failing run); (2) the history entry carries the
   exact label `TEST-STRENGTH EVIDENCE` (`Ledger.verify_test_strength` writes it
   in the field `label`, with `before_failed` false); (3) an independent approver
   verifies the added assertions against the finding. The review-protocol gate of
   `./tools/safety project check` (`tools/project_check.py`, `review_gate`) fails
   a VERIFIED row with `before_failed` false that carries no label. A row written
   before the `label` field holds the exact text in the row.

Order for a HIGH finding: record the row once, after its GREEN run, so that the
row is VERIFIED when it first enters the ledger. A HIGH row that is OPEN,
UNRESOLVED or BLOCKED fails the review-protocol gate, so the GREEN run of its
repair cannot pass the gate while the row is recorded OPEN. Never remove a
recorded row to make a gate pass. Keep a rejected or duplicate row with its
reason.
