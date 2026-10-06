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
that edited source is a rejection. Protected policy, fixture, toolchain and
runner changes need two separately launched approvers that both approve. Repair
findings through the ledger and launch new approvers for the repaired source;
an approval binds only the exact source identity it reviewed. Agent approval is
model judgement, not proof; trusted tools still decide deterministic results.
