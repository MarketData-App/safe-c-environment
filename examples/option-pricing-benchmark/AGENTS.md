# Project agent rules

These rules apply to every agent that changes this example project. The
framework rules in the repository `AGENTS.md` also apply.

## Order of work

1. Specify a workload in its case manifest
   (`benchmarks/project/cases/<case>.json`) first. State the parameters, the
   variants, the work unit, the scopes, the sizes and the measurement points.
2. Write the workload tests in `benchmarks/project/python/tests/` from the
   specification before the adapter. Include zero, one, the exact limit, one
   past the limit, signed-negative values and the representable maximum. Add
   concurrency, allocation, partial-input and cleanup tests when they apply.
   Use checks that stay active under `python -O`. Never put side effects inside
   `assert`.
3. Declare every case and every check in `benchmarks/project/bench.json`.
4. Implement the adapter and the workload code in
   `benchmarks/project/python/optionlab/`. Keep each change small.
5. Run `./tools/safety bench selftest --suite unit --project
   examples/option-pricing-benchmark`, then `bench validate` and every
   `before_run` check. All must pass before a timing run.
6. Phase 2 (C pricer): write the module specification in `specs/project/`,
   then the tests in `tests/project/`, then the code in `src/` and
   `include/`. Run `./tools/safety project check --project
   examples/option-pricing-benchmark --development`. All 23 gates must pass.

## Never change the framework

- A workload never changes framework files, tolerances, budgets, deadlines or
  limits. `bench.json` holds case ids and checks only.
- The tolerances, the solver settings, the oracle set and the calibration stay
  in the protected protocol directory `benchmarks/project/protocol/`. Propose a
  change to the independent approver.
- Never remove tests, shrink input domains or change expected outputs to match
  a defect.

## Review and findings

- Record every finding with `tools/ledger.py` (schema `schemas/ledger.json`):
  stable ID, origin, source identity, location, property, severity rationale,
  reproducer, state history, attempts and verification.
- A behavioural repair needs a regression that fails before the change and
  passes after it, with the same inputs.
- At most five attempts per finding. Three identical unresolved attempts stop
  the work and become a blocker.
- One adversarial reviewer with a fresh context approves each change. The
  implementer never approves its own change.
- Report a failure truthfully.
