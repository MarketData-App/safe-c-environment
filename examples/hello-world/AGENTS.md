# Project agent rules

These rules apply to every agent that changes this project. The framework
rules in the repository `AGENTS.md` also apply.

## Order of work

1. Write or update the module specification in `specs/project/` first. State
   the inputs, limits, nullable parameters, ownership, borrowed lifetimes,
   invariants, outputs, failure behaviour and concurrency.
2. Derive boundary and error tests in `tests/project/` from the specification:
   zero, one, the exact limit, one past the limit, signed-negative values and
   the representable maximum. Use REQUIRE-style checks that stay active under
   `NDEBUG`. Never put side effects inside `assert`.
3. Declare every source, header, test, program and fuzz target in
   `project.json`. A module that reads external input needs a fuzz target in
   `fuzz/project/` with a non-empty seed corpus.
4. Implement in `src/` and `include/`. Keep each change small.
5. Run `./tools/safety project check`. All 23 gates must pass.

## Review and findings

- Record every finding in `review/ledger.json` (schema `schemas/ledger.json`,
  accounting by `tools/ledger.py`): stable ID, origin, source identity,
  location, property, severity rationale, reproducer, state history, attempts
  and verification.
- Each review unit lists its questions, and each answer cites actual source
  lines. Keep rejected and duplicate findings with their reasons.
- A behavioural repair needs a regression that fails before the change and
  passes after it, with the same inputs. Save fuzz reproducers in
  `fuzz/project/regressions/<target>/`.
- At most five attempts per finding. Three identical unresolved attempts stop
  the work and become a blocker.
- One adversarial reviewer with a fresh context approves each change. The
  implementer never approves its own change.

## Never weaken a gate

- Never remove tests, shrink input domains, lower budgets or coverage
  thresholds, or change expected outputs to match a defect.
- Never add warning or analyzer suppressions, sanitizer exclusions,
  optimization attributes or diagnostic pragmas. `project.json` holds no flags.
- Never edit framework files. The framework manifest check stops on any change.
- Report a failure truthfully. Propose a specification change to the owner
  when the specification is wrong.
