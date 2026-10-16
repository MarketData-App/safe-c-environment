# Performance laboratory

The performance laboratory measures whether a Python workload needs a faster
implementation. It compares Python variants and C rows of one registered
workload under a fixed container profile and records the result as bound
evidence. The C rows run the project's own C code over one of three routes
(section "Native C rows"). A decision
is a review recommendation only. It authorizes no adoption and no deployment.
Python stays the default: "Python retained pending evidence".

All operations run as `./tools/safety bench <operation>`. Every timed job runs
in a disposable container through the protected launcher. No host fallback
exists. Add `--format json` to read results by exit code, status and path.
Exit codes: 0 PASS, 1 FAIL, 2 BLOCKED. An INVALID_EXPERIMENT result exits 1.
Exit code 3 occurs only inside the container coordinator (a refused job); a
`bench` operation reports it as a failed or invalid job, never as its own exit
code.

## What the laboratory measures

- Wall time and CPU time per unit and per request, for the scopes `kernel`,
  `caller` and `capacity` that a case declares.
- Whole-workload CPU and memory of the container cgroup, including child
  processes and short-lived workers (B02, B03, B05).
- Warm and cold modes, randomized blocks of trials, and the statistics of
  `tools/bench_stats.py` and `tools/bench_units.py` over recorded values only.
- Python variants: `py-reference`, `py-optimized`, `py-library`, `py-threads`
  and `py-processes`. A variant that a case marks `same-as-reference` or
  `planned-*` is not timed.
- C rows: the variants `c-serial` and `c-threads` (language `c`). In the
  `caller` scope, a C row is the Python caller plus the project's C code over
  one route that the case variant lists (`routes`). In the `kernel` scope, a C
  row times the pure C kernel program; the kernel reports its own wall and CPU
  time, and `bench run` refuses a row whose self-timing differs from the
  bracket wall by more than the `native_timing` limits of
  `safety/performance-policy.json`.

## Cases and projects

- Framework control cases live in `benchmarks/performance/cases/`:
  `bench-control-spin` (CPU spin, the GIL stays held), `bench-control-wait`
  (finite wait, the GIL is released), `bench-control-touch` (memory) and
  `record-scan` (filter and sum of packed records). They exercise the
  laboratory itself and never decide an application question.
- A project registers its own workloads in
  `<project>/benchmarks/project/bench.json`: case ids and declared checks only.
  The framework imports a project module only through the registered-workload
  interface (`benchmarks/performance/python/benchlab/workload.py`). Every
  adapter is built by `benchlab.workload.construct_adapter`, the one
  construction path.
- A check with `"before_run": true` must PASS before any timing run of the
  project's cases.
- `examples/bench-demo` is the reference project: case `demo-digest`
  (xorshift64 steps folded into an FNV-1a 64 checksum per seed, in native
  Python and in C; specs/project/bd_digest.md) and check `demo-agreement`,
  which its protocol file makes a required `before_run` check. Its C program
  `bd-kernel --self-check` is the smoke of `bench native-build`.

## Native C rows

- Routes. Each route has a fixed label in `safety/performance-policy.json`
  (`routes`), and every C row records its route and label:
  - `stdio`: a separate worker process; copied, bounded and validated frames
    over pipes. This is the safest route and the default.
  - `shm`: a separate worker process; shared memfd regions with bounded and
    validated control frames, and a copy-in snapshot.
  - `inproc`: an in-process shared library. The native code shares the
    interpreter address space, so a C defect can corrupt the interpreter.
    This is the fast route and the least safe one.
- The `native` block of `bench.json` declares the kernel program and its
  argument template (`{input}`, `{records}`, `{loops}`, `{output}`) and names
  the `agreement` check of the native build.
- `bench native-build --project DIR` builds the project's declared programs
  and libraries in one bench container with the hardened clang `-O2` profile
  (`-ffp-contract=off`, no sanitizer, coverage or fast-math flag), runs the
  project's `run` entry once as a smoke, and writes `native.json` with the
  sha256 of each binary. Later jobs restore the binaries by sha256, and the
  coordinator verifies each file before a child can use it.
- `bench check --check NAME --native --project DIR` makes its own native
  build in the same run and runs a declared check with it. `bench run` of a
  case with C rows runs the
  `agreement` check with the run's own native build before any timing.
- The reference project `examples/bench-demo` holds three versions of one
  workload: the native Python version, the C kernel `bd-kernel`, and the
  Python bridge to the C code over each route (`bd-worker` over `stdio` and
  `shm`, `libbd_inproc.so` for `inproc`). Its `demo-native` check computes a
  fixed set of requests (boundary requests included) with every version and
  passes only when every output is byte-identical. It writes the sha256 of
  each output per request to `native-agreement.json`.

## Protocol data

The framework holds no project data: no oracle, no model names, no
tolerances, no owner decision policy and no owner thresholds. A project brings
them in its protected protocol file
`<project>/benchmarks/project/protocol/protocol.json`
(schema `schemas/bench-protocol.json`).

- `bench.json` binds the file: `"protocol": {"file": "protocol/protocol.json",
  "sha256": ...}`. The protocol binds each file that it names (`oracle`,
  `aggregate_schema`) by sha256 in the same directory. `tools/bench_model.py`
  refuses an unbound, edited or schema-invalid protocol, a case that is not in
  `bench.json`, and a selector or model name that the protocol does not
  declare.
- `safety/protected-paths.json` (`project_protected`) makes the protocol
  directory of every project protected. A change needs the approver.
- An `APPROVED` protocol also needs its approval record
  `protocol/approval.json` (schema `schemas/bench-protocol-approval.json`):
  the sha256 of the protocol file, the approval reference, the verdict
  `APPROVE` and the approver `fresh-context-agent`. A missing, malformed or
  other-digest record BLOCKS every plan, run, check and decide of the project
  (exit 2). The project's own `APPROVED` state is never enough.
- The binding is tamper-evident, not tamper-proof. The record is unsigned: an
  agent that rewrites the protocol, `bench.json` and the record together is
  found only by review of the protected directory. Review is the control.
- One fail-closed boundary reads all project-controlled JSON
  (`evidence.load_project_json`, FR3-17). This covers the protocol file, its
  approval record, its `aggregate_schema` and `oracle` files and the local
  aggregate. It also covers `bench.json`, project case manifests and
  opportunity records, panel pre-flight and reference records, `project.json`,
  `review/ledger.json` and the owner confirmation. The boundary does these
  checks in this order:
  1. A size cap on the bytes. The protocol file, `bench.json`, case
     manifests, opportunity and pre-flight records, `project.json` and the
     owner confirmation have 4 MiB. The protocol data files, panel references
     and the review ledger have 16 MiB. The approval record has 4096 bytes.
     The local aggregate has 256 KiB. The largest valid file today is about
     4 KiB, so each cap leaves room for growth and still bounds the host
     memory.
  2. Strict UTF-8.
  3. At most 64 nesting levels of arrays and objects. An iterative scan of
     the raw text checks this before the parse, so the parse can never
     recurse too deep. Brackets inside strings do not count. The deepest
     valid project file has about 20 levels.
  4. The parse. It refuses a duplicate key and a `NaN`, `Infinity` or
     `-Infinity` literal.
  5. The validation of the entry point (schema, grammar, cross checks). It
     runs inside the boundary.

  A refusal is GateError (exit 2) with the stable problem name
  `project-data-invalid:<kind>:<reason>`. The reasons are `too-large`,
  `unreadable`, `not-utf-8`, `too-deep`, `not-json`, `duplicate-key`,
  `non-finite-literal` and `exception`. `non-finite-literal` covers the
  tokens NaN, Infinity and -Infinity, and a number that parses to an infinity,
  for example 1e400 (FR3-20). Only the type name of the original
  exception goes into the text, never data. Entry points that return a refusal
  keep their record. The aggregate gate rejects the run as
  INVALID_EXPERIMENT and deletes the document. The review gate gives FAIL. The
  owner confirmation is refused. The readiness scan skips a malformed example.
- The same boundary caps every other host parse of JSON that a project or a
  container can write (FR3-19). `evidence.read_json` reads every JSON file
  with at most 64 MiB and 64 levels; it keeps NaN and Infinity, which
  `atomic_json` may write. `evidence.read_jsonl` reads fetched JSON-lines files
  (observations, phases, controls, memory, capacity) with the same caps.
  `evidence.loads_capped` parses container output and fetched records
  (coverage, panel parts, reports). A clang JSON AST may have 400 levels. The
  64 MiB cap is twice the 32 MiB artifact cap. The deepest recorded document
  has 14 levels. A refusal is GateError and also ValueError, so a reader that
  refused a malformed record keeps its refusal. `tests/unit/
  test_capped_json_readers.py` keeps every other `json.load` out of `tools/`.
  Only trusted framework files that no project or container can write keep a
  plain load: `safety/container-policy.json`, `safety/contract.json`, a
  framework copy of `safety/performance-policy.json` and the pinned developer
  image assembly recipe. The inventory also scans the two container files that
  host tools load (`container/build-foundation.py`,
  `container/foundation-policy-probe.py`) and the inline Python of the CI
  workflow files. The workflows read the Docker daemon configuration with a
  1 MiB cap and a depth guard, and `ci/image-bundle.json` (a framework file)
  with a plain load.
- `run.json` records `protocol_sha256`. `compare`, `report`, `decide` and
  `replay` refuse a run whose project protocol changed after the run
  (`post-hoc-protocol-change`).
- Required keys: `schema_version`, `cases`, `approval` (`PENDING` or
  `APPROVED`). Optional keys: `models`, `tolerances`, `solver`, `budgets`,
  `before_run_required`, `decision_policies`, `stubs`, `panel`,
  `verdict_counts`, `library_report`, `local_exceptions`, `oracle`,
  `aggregate_schema`.
- `panel.cell_rule` is the project's single-record panel rule (`bench panel`).
  It is a banded rule over the project's own named row columns: a category
  column with its labels, a position column, a scale column, two level
  ratios, the grid test settings (`grid`: `upper` and `points`, 2 to 4096
  points), the report entries and six cells. Each cell names a category, a
  band on the position (`gt`, `lt` or `abs_le` a bound) and a position and
  scale target. The framework names no cell and no column.
- `verdict_counts` lists the names of the project's own verdict counts. A
  trial child reports them under `verdict.verdict_counts`; `bench run`
  refuses an observation that names another count.
- `before_run_required` names, per case, the checks that must stay declared
  in `bench.json` with `"before_run": true` (P15 `removed-safety-check`).
- `decision_policies` holds the project's unit-threshold policies. `bench
  decide --policy NAME` loads one from the run's project. The statistics
  constants are pinned in the schema. A project policy is filled only when the
  protocol approval is `APPROVED`; otherwise it gives INCONCLUSIVE.
- `stubs` declares test-only call-deadline stubs (reason, check, variant,
  label). `bench selftest --suite cases` runs one stub run and one stub check
  per declared stub (`SAFE_C_TEST_STUB=<reason>`). When no project declares a
  stub, the suites are recorded under `not_run` in `cases.json` with the
  reason.
- `panel`, `library_report`, `local_exceptions` and `aggregate_schema` give the
  panel models and digest form, the selectors of the library report, the
  exception names that a local aggregate may count, and the schema of the
  aggregate `summary` block.
- The aggregate schema follows a framework allowlist grammar
  (`bench_model.summary_schema_problems`). Every node has a `type`. Leaves are
  number, integer or boolean (each may add null), or a string enum of framework
  labels. Objects have `additionalProperties: false` and explicit
  `properties`. Arrays have `items` and a `maxItems` of at most 256. Every other
  keyword (`$ref`, `oneOf`, `anyOf`, `allOf`, `not`, `if`, `patternProperties`,
  `propertyNames`, `dependent*`, `unevaluated*` and others) and `{}` are
  refused. The host gate also refuses a summary string that is not a
  framework label.
- Each numeric keyword (`minimum`, `maximum`, `exclusiveMinimum`,
  `exclusiveMaximum`, `multipleOf`) holds a finite number that an IEEE-754
  double represents. A float must be finite. An integer must be in the range
  `-int(DBL_MAX)` to `int(DBL_MAX)`. The check compares the integer exactly and
  does not convert it to a float. A bool, NaN, an infinity, a string or a
  larger integer is a grammar problem. `multipleOf` must also be above 0.
  `maxItems` and `minItems` are integers in their ranges. A summary integer
  must be in the same double range. Each of these failures gives GateError
  (exit 2), never a Python exception.

## Workflow

| Step | Command | Result |
|---|---|---|
| plan | `bench plan --case ID [--project DIR] [--mode smoke\|decision]` | The trial design: rows, randomized blocks, budget and session caps. A plan never shrinks a dataset, a trial count or a row. |
| run | `bench run --case ID [--project DIR] --mode smoke\|decision` | A new run directory `artifacts/bench/<run-id>/` with `plan.json`, `observations.jsonl`, `phases.jsonl` and `run.json`. |
| compare | `bench compare --run-id ID` | `compare.json`: each variant against `py-reference` (FASTER, SLOWER, EQUAL or INCONCLUSIVE). |
| report | `bench report --run-id ID` | `summary.md` and `summary.csv`. |
| decide | `bench decide --run-id ID [--policy NAME]` | A decision record per policy: one of KEEP_PYTHON, OPTIMIZE_PYTHON_FIRST, USE_EXISTING_PYTHON_LIBRARY, CONSIDER_PYTHON_CONCURRENCY, C_CANDIDATE_FOR_REVIEW, INCONCLUSIVE, INVALID_EXPERIMENT, with the adoption outcome and the evidence quality. |
| replay | `bench replay --run-id ID` | Runs the recorded plan again while its profile is authorized. It gives a new run identity and new observations, and never copies old numbers. |
| capacity | part of `bench run` when the case declares the `capacity` scope | One exploratory capacity session after the memory trials, in the `compare` and `report` output. It never decides. |
| readiness | `./tools/safety dev readiness` | The `performance` key: readiness axes that read only evidence of the current source identity. |

Other operations: `bench doctor`, `bench list`, `bench new` (scaffold a case),
`bench validate`, `bench check --check NAME` (one declared check), `bench
profile` (cProfile on synthetic data; never enters a comparison) and `bench
panel`.

The framework rule policies are data in `safety/performance-policy.json`:
`owner` (a template in the state `owner-must-fill`) and the two
demonstration-only `demo-*` policies. A template gives INCONCLUSIVE until a
project owner fills and approves it. A project's unit-threshold policies are
in its protocol file (section "Protocol data"). A missing objective or
approval never authorizes a migration.

## Guardrails and evidence binding

- Plan-time guardrails (B12, `tools/bench_guardrails.py`) reject a plan or
  BLOCK its multicore rows before any trial: hidden one-CPU availability,
  oversubscription, an unbounded queue, changed nested threads, a missing
  aggregate limit. A rule whose plan key is absent is reported as
  `not_applicable`, never as a pass.
- Pools run one chunk per worker per request over a fixed-seed permutation,
  with a bounded submission window and the `spawn` start method. Each pooled
  observation records the chunk rule, the chunk sizes and the chunk wall times.
- Evidence binding (`tools/bench_evidence.py`): `run.json` records the sha256
  of every raw evidence file and its own record digest, together with the
  source identity, image id, policy and bench-profile digests. `compare`,
  `report` and `decide` recompute them and refuse a mismatch. `decide`
  refuses a stale, unbound or stripped run.
- CPU accounting (B15, `tools/bench_accounting.py`) reconciles trial deltas,
  the coordinator window and the host cgroup totals.
- Missing evidence is BLOCKED, NOT_EXECUTED or INCONCLUSIVE, never a pass.
- `local:` datasets are private. Only a redacted aggregate leaves the
  container; the privacy suite checks that stderr keeps a byte count only.

## Selftests

`bench selftest --suite unit|controls|privacy|cases|project|all`:

- `unit`: the framework unit tests of the bench tools and `benchlab` in the
  container (with `--project DIR`, the project's declared unit groups).
- `controls`: the CPU and memory controls.
- `privacy`: the redacted stderr probe.
- `cases`: B01 (tools and wheels), B02, B03, B05 (controls), B09, B10, B13
  (real smoke and decision runs of `bench-control-spin` and
  `bench-control-wait`), B12, B14, B15, B18, the `call-deadline` control, the
  P01, P07, P10, P11, P15 subcases (mutations that each gate must reject) and
  the `stub-run-<reason>` and `stub-check-<reason>` suites of each stub that a
  project protocol declares (recorded under `not_run` when none is declared).
- `project`: for each example project, its bench unit suite and every declared
  `before_run` check.

## Quickstart

Framework control case (no project needed):

```
./tools/safety bench run --case bench-control-spin --mode smoke --format json
./tools/safety bench compare --run-id <id> --format json
./tools/safety bench decide --run-id <id> --format json
```

Example project:

```
./tools/safety bench check --check demo-agreement --project examples/bench-demo --format json
./tools/safety bench run --case demo-digest --project examples/bench-demo --mode smoke --format json
./tools/safety bench report --run-id <id> --format json
```

Native C rows of the example project (section "Native C rows"):

```
./tools/safety bench native-build --project examples/bench-demo --format json
./tools/safety bench check --check demo-native --native --project examples/bench-demo --format json
```

The first command builds the C kernel, the worker and the in-process library
and records their sha256. The second command builds them again in its own run
and proves that the three versions agree byte for byte over every route.

`<id>` is the run id that `bench run` reports. Read results by exit code,
status, outcome and path. Do not print evidence `output` fields.

## Design labels in code comments

Comments in the bench tools (`tools/bench*.py`, `container/bench-coordinator.py`,
`benchmarks/performance/python/benchlab/`), the bench schemas and the bench
unit tests (`tests/unit/test_bench*.py`, `benchmarks/performance/python/tests/`)
cite labels from the design history. This list covers the code and the tests. The design documents are not part of this
repository. The rule is the code and its test; this list says where to look.

Spec sections (`spec N`):

- `spec 4`: one reference job per run, outside timing; its result is restored
  by digest. `spec 5`: pooled variants (with Amendment E).
- `spec 7`, `spec 8.3`: the caller-scope trial and the plan (rows, randomized
  blocks, budget and session caps; a plan never shrinks a dataset, a trial
  count or a row). `spec 8.2`: CPU accounting (B15). `spec 8.4`: memory
  trials. `spec 8.5`: `bench profile` on synthetic data only.
- `spec 9`: the `record-scan` control case. `spec 10`: the decision engine and
  the closed decision record (`tools/bench_decide.py`,
  `schemas/bench-decision.json`). `spec 11.1`: a C row needs an approved
  opportunity record. `spec 12`: a `local:` replay is refused under CI and in a
  project instance. `spec 13`: evidence binding, replay and readiness.
  `spec 14`: the capacity scope. `spec 16`: redacted stderr of a local job.

Amendments A to F:

- `Amendment A`: the registered-workload interface and declared project checks
  (section "Cases and projects").
- `Amendment B`: a `py-library` variant is a direct Python row with its own
  label (item 5: its decision rule in `tools/bench_decide.py`).
- `Amendment E`: the pool chunk rule (section "Guardrails and evidence
  binding"); item 2: the request-record limit of the protocol.
- `Amendment F`: project builds (item 3: section "Project build rules" of
  `docs/agent-development-quickstart.md`), the `sc_parallel` grant (item 2;
  `specs/foundation-contract.md`), item 9 C3 (a decision-engine rule) and
  item 10 (stdio frames).
- Amendments C (market parameters) and D (model metrics) are no longer cited:
  that content moved to the example project (FR3).

Amendment G (units, deadlines, panel, statistics):

- `G2.3`: the closed reference side data of an adapter: the exclusion counts
  `reference_admit_excluded` (keys `row`, `brent`, `bump`), the library
  overhead per row (`library_overhead_ns_per_row`), and the test-only stub
  variable `SAFE_C_TEST_STUB`.
- `G2.4` with `I4.3`: per-selector tolerance blocks, each a separate block
  of the project protocol `tolerances`; a locked block names its approval
  reference (tests only).
- `G2.6`: the per-trial call deadline of declared selectors
  (`tools/bench_deadline.py`). Each child leads its own process group; the
  coordinator kills the group at the deadline, records a `deadline_kills` row,
  and keeps the failed row with the declared reason.
- `G3.3`, `G3.6`, `G3.7`: the single-record panel reference (`bench panel`,
  `schemas/bench-panel-reference.json`): synthetic datasets only, the
  per-model diagnostic and the opaque `reference_evals` counts.
- `G4.1`, `G4.2`, `G4.3`: selectors are opaque strings. A trial carries its
  point's selector (default `all`); a selector other than `all` reaches the
  adapter factory as the keyword `selector` (selector routing,
  `benchlab/workload.py`, `benchlab/pools.py`). Work units of a per-selector
  row count every part of an `all` request.
- `G6.3`, `G6.5`, `G6.6`: envelope-blocked rows are not planned; kernel rows
  never enter a unit; `plan.datasets` exists only with `dataset_ref` points.
- `G7.1` to `G7.5`: panel trials (at least 5 passes, a warm trial of at least
  0.5 s, six requests), cold values never give PREFER_C (`G7.4`), CPU and
  memory per request reported only (`G7.5`).
- `G8.1` to `G8.4`: paired block values (a missing block makes the pair
  missing), the effective record count, the one-sided median bounds
  (`tools/bench_stats.py`) and the B09 coverage simulation
  (`benchlab/coverage.py`).
- `G9.1` to `G9.9`: unit-threshold policies and unit verdicts
  (`tools/bench_units.py`): the conditions, the qualification object (`G9.4`),
  the safe route (`G9.5`), the closed unit record (`G9.6`, `G9.7`), the review
  note (`G9.8`) and the adoption outcome from the unit verdicts (`G9.9`).
- `G10.4`: a smoke run gives no unit verdict. `G12`: the B09 and B14
  selftests. `G13.4`: the closed set of three framework rule policies.

Amendment H (selftests, decision engine, evidence):

- `H1`: the B-selftest and guardrail rules (B12 hidden one-CPU availability,
  B14, B15). `H2` to `H5`: the decision engine: `H2` benefit is True, False
  or unknown, with the unknowns named; `H3` the smallest median within the
  limits (a pool row needs the CPU guard); `H4` the C-row checklist (item 8:
  the approved baseline variant of the opportunity record); `H5` a
  demonstration policy or an unfilled template never gives an adoption.
- `H6`: capacity. `H7`: B15 accounting directions. `H8`: evidence binding
  (verify before use). `H9`: readiness axes and the handoff-trial receipt.
- `H12`: the A/A host-noise threshold `aa_pressure`.
- `H14`: a confirmed coverage record must certify the current code. `H15.2`:
  the window chain of a plan version; an exhausted window gives
  INVALID_EXPERIMENT. `H16.1`: the decision record's `sensitivity` object (the
  owner confirmation with its ledger id and coverage digest). `H16.2`,
  `H16.3`: the power rows and the measured sensitivity of a unit.
- `H21.2` to `H21.7`: the panel cell rule of `tools/bench_panel.py` (cell
  order, flag bits, empty cells, pre-flight records). It remains in the
  framework as residue (FR3 report).

Amendment I (errata):

- `I2.2`: a structured case parameter value. `I3 R14` with `I10.1`: a
  selector that `budgets.share_required` lists needs an approved planning
  share. `I4.5`, `I8.1` to `I8.3`: unit records in policy order; the
  project's report of a unit's selector (`project_report`). `I7.2`: the panel
  inputs run as row parts in several jobs.
- `I5.5`: the value 14,336 of the request limit `pools.request_limit` (tests
  only).
- `I9.1`: further call-deadline entries (`call_deadlines`). `I9.2`: the union
  of the entries; overlapping selectors are refused (tests only). `I9.4`: the
  stub selftests (now from the protocol `stubs`).
- `I10.2`: the planning shares of the project protocol (`budgets`) and the required-share rule of
  `bench_deadline.expected_seconds`; the example's planning-budget table is example data.
- `I12`, `I14`, `I15`: B14 unit cases, the least favourable coverage
  configurations, and the distribution-free order-statistic bounds of the
  median (`I15.2` k(n, a), `I15.3`, `I15.4`, `I15.5` power report, `I15.6`
  policy constants).
- `I13.1` (`G-ALO-CO`): the one construction path and the request limit
  `pools.request_limit`.

Other labels:

- `B01` to `B18`: bench selftests (section "Selftests"). `P01` to `P16`:
  mutation subcases that a gate must reject. `C1` to `C5` with a task prefix
  (`T12-C5`, `T20-C1`), `D1-R2`, `F1-*`, `R1-08`: controller rulings and
  review findings.
- `FS1 Fn` and `FRn`: the framework release work items.
- `brief section N`, `Task N` and review IDs (`T17-APP-01`, `P1-R1-10`):
  history labels only.

## Concurrent sessions

A bench session holds exclusive admission for its whole duration: the ci
bench gates take about 17 min, and a decision run can take hours. While it
holds the lock, every other container admission of the same uid waits 60 s
and then BLOCKS. Before a long run, hold the launcher lock
(`flock /tmp/safe-c-launcher.lock`) and tell the other session first.
Run `tools/runtime_cache.py` directly, never under that lock: it takes the
launcher lock itself, so an outer `flock` makes it wait and then refuse.
