# Developer handoff

Read `AGENTS.md` and `docs/agent-development-quickstart.md` in full. Preserve the
protected contracts, fixtures, inventories, locks, and evaluator. Define inputs,
limits, ownership, lifetimes, invariants, outputs, and failure behavior in the
task's specification before implementation. Application development is still
unauthorized unless the owner and independent authority separately approve it.

Use `tools/safety dev` to discover actual targets and tests, prepare the selected
profile, navigate saved source semantically, run a selected test, inspect matching
coverage, diagnose and replay retained failures, and perform bounded debugging.
All native execution belongs in the existing protected Docker boundary.

Edit only the task's designated implementation files. Frozen independent tests
remain authoritative. Preserve real failure outcomes and original evidence.
Treat missing tools, images, symbols, tracing, inputs, or incomplete capture as
blockers. Never install packages ad hoc, add Docker flags, use a host fallback,
change an expected output to fit a defect, or label partial feedback acceptance.

Report the actual commands, run IDs, source and demo identities, observations,
repairs, verification, and limitations. Keep raw native and sanitizer evidence
out of the agent context using the repository's diagnostic summaries.
