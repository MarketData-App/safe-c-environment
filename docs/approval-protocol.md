# Review and approval protocol

Status: owner decision, binding for this repository. It extends AGENTS.md and will
be folded into AGENTS.md with the next change that already requires a new developer
live trial (AGENTS.md is part of the developer tooling identity).

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
