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
- A Python kernel row records pyperf's own value (`pyperf_wall_ns`) next to
  the bracket wall. The bracket nests the timed loops: the coordinator takes
  the begin sample before it acknowledges the begin marker, and the worker
  reads its clock only after that acknowledgement. So the self-timing is
  `forged self-timing` (B15) only in these cases: it is longer than the
  bracket by more than `pyperf.clock_tolerance_ns`; the bracket is longer than
  it by more than `max(pyperf.agreement_abs_ns, pyperf.agreement_rel x wall)`;
  or one of the two values is not a non-negative integer. The honest overhead
  (the cgroup read of the begin sample and two wake-ups) was 0.49 to 1.66 ms
  in 212 distinct trials (424 recorded rows: each kernel row is stored in its
  job's observations.jsonl and in the merged run file); the largest,
  1,661,031 ns, was on a 274.8 ms wall. `agreement_abs_ns` (5 ms) is three
  times the largest.

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
- The run reference (spec 4, R48). One reference job of a synthetic run
  computes the reference outside timing. Each timing and capacity job
  restores it and checks its digest. When the plan holds a selector other
  than `all`, the reference job gets the sorted selectors of the planned
  session trials (`all` included when planned, and `all` for capacity
  trials) as `reference_selectors`. An adapter can declare the optional hook
  `reference_cover(data, selectors)`. It returns one reference from which
  the adapter of each listed selector validates its results, so the
  reference work grows only by the models of the planned selectors. The
  reference job then reports the covered list, the host binds it beside the
  digest, and a job that holds a trial of another selector is refused. An
  adapter without the hook computes `reference(data)` of its reference
  selector, as before, and a plan of selector `all` only sends no list.
  The reference covers the largest tier of the session, memory and capacity
  trials of the plan (`bench_deadline.reference_tiers`), and the call
  deadline of the reference job takes the rows of that same tier. So a stub
  plan, which keeps the capacity trials of the case's smoke plan, gives its
  reference job the deadline of the capacity tier.
- A check with `"before_run": true` must PASS before any timing run of the
  project's cases.
- Framework example rule (rule S, amendment E): a directory `examples/<name>`
  is a framework example only when `starter-export.json` lists
  `examples/<name>/project.json`. Then its files are framework files (manifest,
  export, source inventory), and the framework ci runs its bench suites when it
  holds `benchmarks/project/bench.json`. An `examples/<name>` that holds
  `project.json` and is not listed is a standalone example: the framework
  inventory, the framework manifest, B18 and every framework bench suite leave
  it out, and its own `./tools/safety project check --project examples/<name>`
  checks it. Its bench suites run only with an explicit project:
  `./tools/safety bench selftest --suite cases --project examples/<name>`,
  `--suite project --project examples/<name>` and
  `./tools/safety dev readiness --project examples/<name>`. An
  `examples/<name>` without `project.json` stays framework content (fail
  closed). The framework names no example; the data in `starter-export.json`
  selects the scope.
- `examples/bench-demo` is the reference project: case `demo-digest`
  (xorshift64 steps folded into an FNV-1a 64 checksum per seed, in native
  Python and in C; specs/project/bd_digest.md) and check `demo-agreement`,
  which its protocol file makes a required `before_run` check. Its C program
  `bd-kernel --self-check` is the smoke of `bench native-build`.

## Project wheels

The framework developer image holds only the wheels that framework code
imports (numpy, pyperf, psutil). A project brings its own third-party
Python wheels and source archives in a protected lock file.

- The lock is `<project>/benchmarks/project/third_party/lock.json`
  (`schemas/project-third-party.json`). `bench.json` binds it with
  `"third_party": {"file": "third_party/lock.json", "sha256": ...}`.
  The directory is in `project_protected` of `safety/protected-paths.json`,
  so a change needs the approver.
- Each wheel row gives name, version, filename, tag, top-level modules,
  sha256, bytes (at most 64 MiB), parts (each at most 32 MiB), origin,
  a provenance record, a notice and a license record (SPDX tags from a
  fixed list, owner, review status). A source-archive row has the same
  fields without tag and modules. Every path lies under `third_party/`.
- `bench_model` refuses an unbound or edited lock, a path that resolves
  outside the project, a wheel tag that the bench interpreter cannot load,
  and a module that shadows the standard library, a framework wheel, a
  framework package, another wheel or a project package.
- `./tools/safety bench image --project DIR` builds the project bench image,
  or reuses it. The build is offline and uses only the pinned local files:
  an extraction job (`container/project-wheels.py`, dependency-build profile)
  unpacks the wheels as data, the host verifies every byte, and a data-only
  image build adds one layer under `/opt/project-python` to the qualified
  developer image. The lock notice of each wheel must equal the license file
  in the wheel. Source archives never enter an image.
- Host members (T6-R2): no file of a container can be larger than the
  container file bound (33554432 bytes, `common.file_bytes` of
  `safety/container-policy.json`). A wheel row of tracked parts can declare
  `host_members`: at most 4 members of that wheel, each with its path inside
  the wheel (`member`), `bytes` and `sha256`. Each declared member must be
  above the file bound and at most 50331648 bytes (`HOST_MEMBER_MAX_BYTES` of
  `tools/project_third_party.py`). A first-party fixture wheel declares none.
- The extraction job reads a declared member in 1 MiB pieces and hashes it.
  It never writes the member. It refuses an undeclared member above the file
  bound, a declared member that is not above the file bound or is above the
  member bound, a declared member that the wheel does not hold or that the
  layer leaves out, a member declared twice or held twice in the zip, and a
  size or sha256 that differs from the declaration. The manifest lists each
  host member under `host_members`, not in an archive.
- The host checks that record against the lock. Then it streams each host
  member from the sha256-verified wheel parts into the layer in 1 MiB pieces,
  with a refusal above the member bound and a size and sha256 check. A
  refused member leaves no file. The layer bounds (192 MiB, 3072 files), the
  ELF record and the added-bytes rule of the image count host members. The
  lock sha256 binds the declarations, so the image key binds them too.
  `fetch-project` does not write `host_members`; the project adds them to
  its lock row.
- Wheel data directory (T6-R3): a wheel can hold `<dist>.data/` with the
  scheme `data` only (`<dist>.data/data/...`). Its name must be the lock name
  and version, as the dist-info name (without case). Its files are no import
  files: the extraction job does not extract them, they do not count in the
  layer bounds, and the manifest counts them per wheel (`data_files`). Every
  member bound still applies to them: the entry count, path safety, the
  special-type check and the file bound. The job refuses every other scheme
  (`purelib`, `platlib`, `scripts`, `headers`, an unknown one) and every
  other entry of the data directory. A data directory is never a module.
- Notice member (T6-R3): by default the job searches the dist-info directory
  for a file whose name starts with `LICENSE`, `LICENCE` or `COPYING`. A
  wheel row can declare `notice_member`, the exact member path of its license
  file below its dist-info directory or below `<dist>.data/data/`. The job
  then reads exactly that member: once in the zip, a regular file, at most
  1 MiB. The lock notice sha256 must equal its bytes. `check_lock` refuses a
  control character in a notice member and in a host member path.
- Every bench job of a project with wheels runs in that image. The
  coordinator checks the exact dist-info set and puts `/opt/project-python`
  after `/opt/bench-python` on the import path.
- The image is a cache kind, as the project runtime image is.
  `max_owned_images` counts both kinds together, and
  `tools/runtime_cache.py` evicts unused images of both kinds.
- The only online step is the explicit, owner-approved
  `tools/acquire_bench_wheels.py fetch-project --project DIR --name N --version V`.
  It keeps the wheel parts and writes a candidate lock row under
  `artifacts/third-party/`. Checks never run it.
- The repository admits no first-party archive (the privacy hook). A
  first-party wheel row (origin `first-party-fixture`) names `source_dir`
  instead of parts; the framework builds the wheel from that tracked
  directory by one deterministic rule, and the lock sha256 binds the result.
  Only a framework fixture project under `tests/fixtures/` may use this
  origin, and a `source_dir` holds source text only (no compiled object by
  name or by ELF, Mach-O, PE or archive magic, no NUL, UTF-8 only).
- The privacy hook accepts a third-party wheel part under
  `<project>/benchmarks/project/third_party/wheels/` only when the project
  lock at the same revision lists its exact path, sha256 and size under a
  wheel row with a `files.pythonhosted.org` URL that names the wheel file.
- A `retained` row binds upstream files that the project keeps without their
  upstream archive (for example selected headers). The `files` list of a
  wheel or source row binds more upstream files of that row (for example
  license texts). A provenance or notice record can bind its `bytes`.
  `verify_files` checks every byte. No row can bind the lock itself.
- The privacy hook skips the content of another file under
  `<project>/benchmarks/project/third_party/` only when the project lock at
  the same revision binds its exact path, sha256 and size in a row whose
  origin URL is on the upstream allowlist (`$defs.exempt_origin_url` of the
  schema: PyPI files, GitHub release downloads and archives, Boost release
  archives). A source part, a retained file, and a provenance or notice
  record with its size can be exempt. The lock counts only in a project root
  of the same revision: the repository root or `examples/<name>/`, with a
  `project.json`. The hook always checks file names. A path that the lock
  binds to other bytes is a finding (`project-lock-mismatch`), and so is a
  symbolic link in that directory (`project-third-party-symlink`). The lock
  itself, every unbound file and every other archive get every rule.
- No first-party C build sees the project wheels: the `native-build` job
  always runs in the developer image, and the coordinator refuses
  `project_wheels` for it. Native code inside a third-party wheel runs only
  in bench containers (ledger row EX1-A02). A host member is native code of
  the same kind: the extraction job records it in `elf_files` by its first
  bytes, the trusted host writes it as data and runs no part of it, and it
  runs only in bench containers.
- `tests/fixtures/wheel-project` is the framework control: one first-party
  wheel built from tracked source. `bench selftest --suite project` runs its
  unit suite in its project image (`project-image:tests/fixtures/wheel-project`).

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
- Optional `native.trace` (EX-13, case B04): a declared program that takes no
  argument and prints the pool trace (`tools/bench_phase2.parse_trace`): one
  line `# workers=0 result=R` for the serial run, then per worker count one
  header line and one span line per task (`thread start_ns end_ns task
  cpu_ns`). The `native-overlap` job runs it from its verified binary.
  bench-demo declares `bd-spread` (1, 2 and 4 workers on the foundation pool).
- Optional protocol keys (EX-13): `agreement_mutations` (project mutations that
  the `agreement-controls` job applies through the adapter hook
  `agreement_mutation(name, result, data)`, beside the generic mutations of
  `benchlab.agreement`) and `echo_case` (the case whose C rows are the
  echo-control rows of B13-echo).

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
  That control copies each project's `bench.json` into a probe project
  without its `protocol` and `third_party` bindings: the probe holds no
  project file, and the control reads only the cases and the checks
  (T14-A01).
- `decision_policies` holds the project's unit-threshold policies. `bench
  decide --policy NAME` loads one from the run's project. The statistics
  constants are pinned in the schema. A project policy is filled only when the
  protocol approval is `APPROVED`; otherwise it gives INCONCLUSIVE.
- A unit-threshold policy can add `margin_rule` (the two-condition rule,
  `bench_units.margin_unit`): `base_variants` (Python variants),
  `candidate_variants` (C variants), `routes` and `margin` (above 0 and below
  1). The project declares every value; the framework names none. Each
  declared route of a unit is judged separately. The route gives PREFER_C only
  when both conditions are decided true:
  1. Base: the warm wall per request of the base family is at or above
     `threshold_ns_per_request` (met when L_Pi is at or above it; not met when
     H_Pi is below it; a straddle or an unattainable bound is undecided).
  2. Candidate: a candidate row on the route is faster than the base row P by
     more than the margin, end to end (the caller-scope rows hold the transfer
     of the route). The upper order-statistic bound of the median of the
     per-block ratios candidate/P, at alpha divided by every measured candidate
     row of the unit, must be below 1 - margin. A lower bound at or above
     1 - margin is not met; anything between is undecided.

  The G9.4 conditions (project gates, framework qualification, approved
  opportunity) still apply. Every other outcome is KEEP_PYTHON with a reason
  that names the condition: `base-under-threshold`,
  `base-threshold-undecided`, `base-not-measured`, `candidate-not-measured`,
  `candidate-margin-not-met`, `candidate-margin-undecided` or
  `candidate-not-eligible`. A unit without a measured candidate row is always
  `candidate-not-measured`. The unit verdict is PREFER_C
  (`both-conditions-met`) when a route gives PREFER_C; the safe-route verdict
  uses the safe routes only. The unit record holds `margin_rule`: the base
  decision with L_Pi and H_Pi, and per route the ratio interval, the decision,
  the verdict and the reasons. A run that is not valid stays
  INVALID_EXPERIMENT.

  Missing rows (EX18a-A01): a route and the base are judged on the verdict
  mode only. A row that the plan blocks in another mode is no missing row of
  the verdict. The plan blocks the inproc cold cell by design (not-applicable:
  the library load is the startup phase), so a measured inproc warm row gives
  a real met or not-met decision for the route. A blocked row of the verdict
  mode, and a blocked row without a mode, is a missing row. The
  single-condition rule reads the blocked rows the same way. A rule policy
  reads them the same way (FW-DECIDE-NAMODE-01): a blocked row counts as
  required evidence missing only in the modes the policy decides, a row whose
  mode is neither warm nor cold always counts, and a not-applicable cell (the
  inproc cold cell) never counts, in any mode. The plan-time
  guardrail rows of a plan version (`guardrail: true`) are warnings, not
  decision evidence; the window evidence of a decision drops them
  (FW-WINDOWS-GUARDRAIL-01).

  Declaration check (EX18a-A04): at protocol load, every base variant of a
  `margin_rule` must be planned at every case point of a policy unit, or be a
  blocked row of the plan with a reason (a `planned-phase-2` variant). The plan
  never measures `py-reference` at the large size (the G8.2 guard estimates
  it there), so `py-reference` may be absent from a large unit point. Any other
  base variant without a row (for example a `same-as-reference` variant, or a
  variant that the point does not list) refuses the protocol with the stable
  reason `margin-base-not-planned` (GateError, exit 2), so every plan of the
  project is refused.

  Coverage at the margin bound (EX18a-A02): the B09 coverage job checks the
  false-claim rate of the candidate claim at the ratio bound 1.0 (`h_pi`,
  `l_pi` and `qualifies`). The candidate condition uses the same
  order-statistic bound at the ratio bound 1 - m. The coverage holds there too,
  by the scale invariance of the order statistic: the bound U of the median of
  the per-block ratios r_b is an order statistic of the values r_b, and
  dividing every r_b by the constant 1 - m divides U by 1 - m without a change
  of rank. So U(r) < 1 - m holds exactly when U(r/(1 - m)) < 1. When the true
  median ratio is 1 - m, the ratios r_b/(1 - m) have the median 1.0, so the
  rate of a false claim at 1 - m equals the rate that B09 certifies at 1.0, at
  the same level alpha/k. B09 does not run margin_unit, _base_condition or
  _route_condition: the unit tests in `tests/unit/test_bench_margin_rule.py`
  check that code path, and B09 checks the statistic that it uses.
- A unit-threshold policy can add `windows` (the window plan of its decision
  runs, `tools/bench_windows.py`; section "Window plans"). The project
  declares every value; the framework names none.
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

### Tolerance calibration

`./tools/safety bench tolerance --spread PATH --project DIR` checks the
project's current tolerances against recorded spreads
(`tools/bench_tolerance.py`). It runs on the host and reads JSON only.

- A project check writes the spread file
  (`schemas/bench-tolerance-spread.json`). Each field is the dotted path of a
  number in the protocol `tolerances`: `abs`, `<block>.abs` or
  `<block>.<group>.<name>`. Each field holds its oracle error bound and, per
  variant, the largest absolute spread (`max_abs`) and the sample count
  (`samples`, 1 to 2^53). The framework names no field and no variant.
- The rule, per field: `measured` is the largest spread over all variants.
  `proposed` is the current value when
  `measured < current < oracle_error`. For a field in a locked selector block
  the rule is `measured < current`. The tool does not check the oracle bound
  for a locked field, so its `margin_high` can be 1 or less. In all other
  cases `proposed` is null with a reason. `margin_low` is
  `proposed / measured` (null for a zero spread). `margin_high` is
  `oracle_error / proposed` (null when it is not finite).
- A lock exists only inside a selector block, with an approval reference.
  The protocol grammar refuses a top-level `state` that starts with `locked`
  (GateError, exit 2). The tool refuses a block state outside
  `provisional-<name>` and `locked-<name>`, a locked block without a valid
  approval reference, and a lock below a selector block. A top-level number
  is never locked. The approved locked selector blocks of the protocol are
  the only source of a lock: `calibrate` takes no lock from its caller.
- The tool never proposes a wider value, and it never edits the protocol. A
  zero current value is never kept.
- The tool writes `artifacts/bench/<run>/tolerance-proposal.json`
  (`schemas/bench-tolerance-proposal.json`). Exit 0 when every field has a
  proposed value, 1 when a field has none, 2 for a malformed input.
- With `--approval REF` (and `--label NAME`, default `calibrated`) and a full
  proposal, the tool also writes `tolerance-lock.json`. This is the protocol
  `tolerances` object with `state: locked-<NAME>` and `approval: REF` on each
  selector block that holds a proposed field. The tool checks it against the
  protocol grammar. The bare state `locked` is refused. A proposal with a
  top-level field gets no lock record (GateError, exit 2): move the value into
  a selector block. The lock record never drops a proposed value: a field
  `<block>.state` or `<block>.approval`, a field that is a path prefix of
  another field and a block approval that is not a string are refused
  (GateError, exit 2). A project copies the lock record into its protected
  protocol after an approval. `require_locked_selectors` then enforces each
  locked block.
- The spread file is project data. It passes the capped boundary (4 MiB,
  strict UTF-8, depth cap, no duplicate key, no NaN or infinity), the schema
  and the tool's own checks: at most 256 fields and 32 variants per field. A
  symbolic link is refused. Each failure gives GateError (exit 2), never a
  Python exception.

## Workflow

| Step | Command | Result |
|---|---|---|
| plan | `bench plan --case ID [--project DIR] [--mode smoke\|decision] [--matrix python\|full]` | The trial design: rows, randomized blocks, budget and session caps. A plan never shrinks a dataset, a trial count or a row. `--matrix python` plans the Python rows only (no C row, C memory trial or C capacity trial, so no native build); the default `full` plans every row. Only a python plan records `matrix`, so a full plan keeps its plan id. |
| run | `bench run --case ID [--project DIR] --mode smoke\|decision [--matrix python\|full]` | A new run directory `artifacts/bench/<run-id>/` with `plan.json`, `observations.jsonl`, `phases.jsonl` and `run.json`. With `--plan`, the written plan keeps its matrix; an explicit `--matrix` that differs from it is refused. |
| compare | `bench compare --run-id ID` | `compare.json`: each variant against `py-reference` (FASTER, SLOWER, EQUAL or INCONCLUSIVE). |
| report | `bench report --run-id ID` | `summary.md` and `summary.csv`. A row with failed trials gets an investigation section in `summary.md` (see below). |
| window | `bench plan --policy NAME --mode decision --calibrate ID`, `bench run --plan PATH --window ID`, `bench run --extend RUN_ID` | A window plan of a unit-threshold policy that declares `windows` (section "Window plans"). |
| decide | `bench decide --run-id ID [--policy NAME] [--final]` | A decision record per policy: one of KEEP_PYTHON, OPTIMIZE_PYTHON_FIRST, USE_EXISTING_PYTHON_LIBRARY, CONSIDER_PYTHON_CONCURRENCY, C_CANDIDATE_FOR_REVIEW, INCONCLUSIVE, INVALID_EXPERIMENT, with the adoption outcome and the evidence quality. |
| replay | `bench replay --run-id ID` | Runs the recorded plan again while its profile is authorized. It gives a new run identity and new observations, and never copies old numbers. |
| capacity | part of `bench run` when the case declares the `capacity` scope | One exploratory capacity session after the memory trials, in the `compare` and `report` output. It never decides. |
| readiness | `./tools/safety dev readiness` | The `performance` key: readiness axes that read only evidence of the current source identity. |

## Plan sizing and calibration

`bench plan --mode decision --calibrate SMOKE_RUN_ID` sizes a decision plan
from a smoke run of the case (`tools/bench_plan.py`, design `I9.3`). Without a
calibration (a smoke plan), each trial uses the planning rate of its family
(`budgets.estimate_seconds_per_record`) times the approved share of its
selector.

- Call classes. A call of one row (a single-record panel call, or a call of a
  tier with one row) is the `one-row` class. A call of more rows is the
  `multi-row` class. A variant with a fixed cost per call pays that cost on
  every one-row call. Thus a rate per row of multi-row calls never sizes a
  one-row call.
- The calibration of a run (`calibration_inputs`) holds the family rates
  (the median wall per record of the `all` rows of each Python family; C
  keeps the policy rate) and `walls`: the measured wall of each variant,
  selector and call class (`measured_walls`). The walls come from the
  eligible timed caller-scope rows of direct and 1-worker rows. A one-row
  wall is the seconds of one call (a panel trial: its wall divided by
  6 x L). A multi-row wall is the seconds per record of the calls of the
  smallest multi-row tier that the run measured. A larger call shares its
  fixed cost over more rows, so this wall is an upper bound of its cost per
  record. A pool row uses the wall of its variant.
- Every caller-scope timing trial of a calibrated plan uses the measured
  wall of its class: the passes L of a single-record trial (the smallest
  L >= 5 with 6 x L x the one-row wall >= 0.5 s), its expected wall, the
  input e of its call deadline (d = min(max(floor_seconds, factor x e), the
  remaining session deadline)), the session estimates and the session
  packing, the memory trials and, in a window plan, every session, group,
  window and control term. The jobs (reference, panel, check, validate)
  keep the planning rate x share as their deadline input. Kernel trials keep
  the family rate.
- A planned class without a measured wall refuses the plan:
  `wall-not-measured` (exit 1, no container). The refusal names the variant,
  the selector and the class. No wall is taken from another class, selector
  or variant.
- The smoke plan measures every class that a decision plan of the case can
  hold. The `smoke-caller` point measures selector `all` on multi-row calls
  of every caller row. For each other selector and class of the caller
  points of the case, a probe point `probe-<selector>-<class>` runs one
  short warm trial of each variant of those points (1 block) on the first
  direct or 1-worker row of the variant and the first allowed route of a C
  variant. A multi-row probe runs at the small tier. A one-row probe runs
  on the panel of the first such point (L = 1 pass of six one-row calls) or
  at its one-row tier. A selector whose tolerance block is not locked, or
  whose required share has no approved value, gets no probe (its plans
  refuse for that reason first). The probe points come after
  `smoke-kernel`, so the first two session ids stay.
- A probe measures a steady wall (ruling R87). A new trial child pays a
  one-time cost on one of its first calls (the call is not always the
  first). Thus each probe session starts with one untimed warmup trial of
  the same shape per variant (the same tier, panel, passes, selector and
  route, so the same trial child), and only the timed trial after it gives
  the wall.
- The size of a smoke plan: every session stays within the smoke job
  deadline (600 s; a block above it is refused, and the blocks of a point
  are split into sessions as before). A smoke plan without probe points
  must fit the smoke job deadline in all, as before. A smoke plan with
  probe points may take up to `PROBE_SMOKE_CAP_SECONDS` (1,200 s,
  `tools/bench_plan.py`) in all; above that bound the plan is refused. The
  unit smoke jobs of a window policy keep their own 600 s rule.
- The plan binds its calibration (`calibration` with its `walls`, and
  `calibration_source`). `bench run --plan` derives both again from the
  recorded calibration run and refuses a plan that differs. A plan that an
  earlier framework wrote has no walls, so `bench run --plan` refuses it:
  plan it again from a new smoke run.

## Window plans

A unit-threshold policy that declares `windows` in the project protocol runs
its decision in windows (`tools/bench_windows.py`; Phase 3 addendum Tasks A8
and A9). The declaration:

- `window_seconds`: the longest window with its control rows (at most
  86,400 s, the 24-hour split rule).
- `cap_headroom` and `cap_step_seconds`: the proposed cap of a dataset is
  `cap_step_seconds x ceil(cap_headroom x the largest window estimate /
  cap_step_seconds)`.
- `caps_seconds` (optional): the approved caps `{synthetic, local}`. A
  window estimate above the cap of its dataset refuses the plan
  (`owner-cap-exceeded`).
- `controls.base` and `controls.candidate`: the base A/A pair (two identical
  rows of a Python variant) and the candidate control pair (two identical
  rows of a C variant on one route). Each is a row of a caller point of the
  policy's case with the warm mode. Protocol load refuses a control that is
  not such a row. A control pair from another case is not possible yet
  (ledger row EX18b-CONTROL-CASE-01).
- `calibration_deadline_seconds` (optional, 600 to 10,800 s): the stated
  deadline of the smoke calibration plan (command 1). Without it, the whole
  plan must fit the 600 s smoke job deadline. With it, the whole plan must
  fit the stated deadline, and each session job of the plan (the control
  session too) must still fit the 600 s smoke job deadline.

The commands:

1. `bench run --policy NAME --mode smoke` runs the smoke calibration plan:
   the `smoke-caller` point, the unit points (the full-dataset points at the
   small tier, the single-record points on their panel, 2 blocks, warm), the
   slow-row diagnostics (`unit-<selector>-slowest`, 1 block), one control
   session (12 paired blocks of each control pair) and, for each
   full-dataset unit whose own points list no `py-reference` row, the point
   `reference-<selector>` (`py-reference` at the small tier and the unit's
   selector, warm, 1 block). The `py-reference` rows of these points measure
   the reference batch wall of each full-dataset unit, and the `py-reference`
   panel rows measure the reference panel wall of each panel point. This
   plan has no probe points: its unit points, its diagnostics and its control
   session measure every call class of the window plan (section "Plan sizing
   and calibration").
2. `bench plan --policy NAME --mode decision --calibrate SMOKE_RUN_ID` writes
   the plan version. It keeps the unit and diagnostic points. It has no
   memory or capacity trial (they never decide under a unit policy). Each
   trial and each control trial is estimated with the measured wall of its
   variant, selector and call class (section "Plan sizing and calibration";
   a missing wall refuses the plan, `wall-not-measured`), except the two
   reference terms: the reference batch of a
   full-dataset unit is the dataset rows times the measured reference batch
   wall of its selector, and a `py-reference` panel trial uses the measured
   panel wall of its point (`measured_reference` in the plan; a missing
   measured wall refuses the plan, `reference-not-measured`). The sessions are
   packed by the same estimate that every session check reads: a session
   holds the most blocks that keep it, with the control trials that one
   session can hold at most (12 blocks and one warmup of each control row),
   within the 10,800 s session cap; the block count never changes. The groups
   are each full-dataset unit with its reference batch, the single-record
   units, and the diagnostics.
   The split is deterministic: a group above the group limit (the window
   length minus E_ctrl, the control cost of a window) is cut into parts of
   whole sessions; the parts go largest first to the least-loaded window.
   The plan records `windows`, `look2` (the extension worst case of each
   window), `e_ctrl`, `caps_proposed`, `measured_reference` and
   `calibration_report` (the trip rate of the pressure test per row, and per
   control pair the expected non-EQUAL rate, the paired blocks
   `control_blocks`, their log-ratios `control_log_ratios` and their standard
   deviation `control_sd`; never a pass condition). The report is part of the
   plan id: `bench run --plan` re-derives the measured walls and the report
   from the bound calibration run and refuses a plan that differs.
   Refusals (exit 1, no container): `window-cap-infeasible`,
   `session-cap-infeasible` (also with the control trials of the session),
   `owner-cap-exceeded` and `control-fail-unrepaired` (a new plan version
   after a `window-control-fail` needs `--repair LEDGER_ID:COMMIT` of a
   closed ledger finding). A plan never shrinks a block count, a row or a
   dataset.
3. `bench run --plan PATH --window ID` runs one attempt of one look-1 window
   (`1a`, `1b`, ...). The run plan holds the window's sessions with one
   warmup per control row and the control blocks interleaved. The run
   records `window`, `attempt`, `window_plan_id`, `extends` (the chain digest
   of the nearest earlier final position: the run record digest without the
   decision digests that a later `decide` binds, so a `decide` never changes
   a chain link), `attempt_outcome` and `envelope_identity`. The outcome is PASS, BLOCKED `window-pressure` (an
   unreadable pressure value, a control pair that is not EQUAL with pressure
   evidence, or a pressure block of another row), BLOCKED
   `window-control-noise` (a control pair that is not EQUAL without pressure
   evidence), or FAIL `run-invalid` (the run is INVALID_EXPERIMENT). A
   BLOCKED attempt exits 2; run the window again. At most 3 attempts: a
   window with 3 BLOCKED attempts is exhausted; 3 `window-control-noise`
   attempts are FAIL `window-control-fail`. A final attempt (PASS or FAIL)
   is never run again, and the windows run in plan order.
4. `bench decide --run-id ID --policy NAME --sensitivity-confirmation PATH`
   decides over the chain of the plan version of the run. It checks the
   chain (positions, attempts, superseded records, plan order, `extends`),
   every chain run with the checks of `decide`, and every run plan against
   the plan version. A refused chain gives every unit INVALID_EXPERIMENT
   (`window-chain`). The units of an exhausted window get `window-pressure`,
   of a FAIL position `window-run-invalid`, and a pooled unit whose windows
   differ in their envelope identity `window-envelope-mismatch`.
   `window-control-fail` refuses the decision (no record). The record holds
   the `windows` object.
5. `bench run --case ID [--project DIR] --extend RUN_ID` runs one attempt of
   the extension window (`2a` for `1a`) of a final PASS look-1 run. Its units
   are the triggered units of the look-1 decision record. The order: after
   the last look-1 window, run `decide` on RUN_ID (the look-1 record is bound
   in that run), then `--extend RUN_ID`. The first extension attempt of the
   plan version copies the record as `look1-decision.json`, and every later
   extension attempt (a rerun after a BLOCKED attempt, or the extension of
   another window) uses that copy. A later `decide` on any run of the chain
   therefore changes neither the triggered units nor a chain link. Each
   block b of a triggered unit is repeated as block b + 12. `decide` pools a unit at look 2 only when every
   look-1 window of the unit has a PASS extension; an exhausted extension
   keeps the look-1 verdict (`extension-exhausted`). `decide --final` gives
   every other unit at look 1 the note `extension-not-run`.

The unit smoke jobs (G10.4, `bench_phase3.unit_smoke_plan`,
`unit_smoke_suite`): `bench selftest --suite cases` runs the unit points of
every unit-threshold policy of every example project (small tier, panel, 2
blocks) as smoke jobs within the 600 s smoke deadline, through `bench run
--plan`. The suite `unit-smoke` passes when every run is VALID, no decision
record exists and `bench decide` refuses the smoke run. bench-demo declares
the policy `example-window-units` with one unit and a window declaration: it
is the framework control of the window logic.

Rows that a plan removed (`bench_plan.excluded_rows`): `bench decide` compares
the rows of the declared case with the plan. A row that the plan neither plans
nor blocks (`--matrix python` removes every C row) is missing evidence. A rule
policy then gives INCONCLUSIVE (rule 2, "required evidence missing: ...:
excluded by --matrix python"). Under a unit-threshold policy the row is a
missing row of every unit. A unit without a measured C row while a C row is
missing is never a plain KEEP_PYTHON: INCONCLUSIVE `c-evidence-missing`, or
KEEP_PYTHON `candidate-not-measured` under `margin_rule`.

Other operations: `bench doctor`, `bench list`, `bench new` (scaffold a case),
`bench validate`, `bench check --check NAME` (one declared check), `bench
profile` (cProfile on synthetic data; never enters a comparison) and `bench
panel`.

Failed-row investigation (spec 13, `bench_decide.investigation_lines`): for
each compare row with failed trials, `summary.md` gets a heading and three
labeled steps. Step 1 checks correctness: a C row names `bench check --project
DIR --native --check NAME`, where NAME is the check that the project's
`bench.json` `native.agreement` names (a project without that declaration gets
no invented name); a Python row names `bench validate --case ID`. Step 2 names
`dev test --id <test id>`, then `dev diagnose --run-id <failed dev run id>`
and `dev replay --run-id <failed dev run id> --snapshot original`. A `local:`
run has no input-replay artifact, so step 2 asks for a synthetic reproducer
(spec 12) instead of the replay. Step 3 names `dev debug --recipe crash` and
`bench sanitizer-evidence --project DIR`. Every step is investigation only:
nothing timed under GDB or a sanitizer is a release measurement.

The framework rule policies are data in `safety/performance-policy.json`:
`owner` (a template in the state `owner-must-fill`) and the two
demonstration-only `demo-*` policies. A template gives INCONCLUSIVE until a
project owner fills and approves it. A project's unit-threshold policies are
in its protocol file (section "Protocol data"). A missing objective or
approval never authorizes a migration.

## Local decision runs

A decision run on a private dataset (`bench run --project DIR --case ID
--mode decision --dataset local:PATH`, or a window attempt of a local plan
version: `bench plan ... --dataset local:PATH`, then `bench run --plan PATH
--window ID --dataset local:PATH` and `bench run --extend RUN_ID --dataset
local:PATH`) runs through `tools/bench_local_decision.py` (spec 12,
Amendment H10, H15.2). The project is the explicit `--project`; the tool
never selects a project by its layout.

- Each timing session of the plan is one job in its own redacted container.
  The job runs the session's trials on the private dataset and computes its
  own reference over its rows (the largest tier of its trials that read the
  dataset) inside the container, with the adapter of its reference selector:
  the one selector of all its trials, else `all`. A job whose trials hold
  more than one selector also gets their sorted list as
  `reference_selectors` (R48, ruling R51), so an adapter with the
  `reference_cover` hook computes one reference for every selector of the
  job. Every trial's result is checked against that reference inside the
  container. A single-record
  (panel) trial measures synthetic panel rows (the `dataset_ref` dataset of
  the plan), never private rows.
- Whole-run outputs only (spec 12, Round-4 L4: "a digest of one row or of a
  subset of rows is not a field"). The run's rows are the largest job rows of
  the plan. A job with fewer rows is partial: its aggregate holds
  `partial: true`, `rows` 0, no summary, the zero digests and no reference
  count block. Only a whole-run job computes the project summary and exports
  the digests and the count blocks. A run of one row has no whole-run job.
  The first whole-run job also measures the reference overhead of the planned
  selectors on synthetic rows. The aggregate schema refuses a partial
  aggregate with a digest, a summary, a row count or a count block, and the
  host deletes such an aggregate (problem `partial-slice`). The merged
  document holds null rows and digests for a partial job.
- Only the closed aggregate leaves a job
  (`schemas/bench-local-aggregate.json`). A timing row holds, per block, the
  per-unit wall and CPU values, the block eligibility, `cpu_pressure_total`,
  the records of one request and, for a panel row, the per-cell medians. The
  job adds its cgroup inode, whether every trial child started isolated,
  `partial`, the rule counts below and (a whole-run job) the reference count
  blocks.
- The host accepts each aggregate with the Phase 1 gate, requires every
  timing row to be a planned row of its job (key, trial count, blocks, panel
  cells), checks the cgroup identity of each job and merges everything into
  `local-merged.json` (`schemas/bench-local-merged.json`: numbers, enums,
  digests and patterned names only). Its `problems` codes give the status.
  Each job's artifact-directory check keeps its own launcher record
  (`local-check-<job>`).
- `reference_evals` merges per key over the whole-run jobs (equal values).
  `reference_admit_excluded` must be equal between the whole-run jobs of one
  selector; jobs of different selectors may report different blocks, because
  each selector's adapter computes its own reference. The run's block is the
  block of selector `all`, else of the first selector (sorted) that reports
  one. A project whose adapter reports admission exclusions for more than one
  selector without an `all` job gets that first selector's block in the run
  record.

### The rule set of a local decision job

The observations and phases of a local job never leave its container, so the
host cannot apply the synthetic run checks to them. Each decision job applies
the same predicates to its own trials and writes, per rule, the number of
trials that break it (`rules`). A count above zero makes the job and the run
`INVALID_EXPERIMENT` (problem `rules-failed`; the run reasons name the rule
and the count). The same evidence therefore gives the same validity as a
synthetic run.

| Synthetic run check | Local job rule | Notes |
|---|---|---|
| `bench.deadline_reasons` (G2.6), a warmup trial too | `call-deadline` | applied |
| `bench_plan.check_trial_design` (B09) | `trial-design` | applied |
| `bench.check_completeness` (P07) | `missing-trial`, `work-count`, `rows-dropped` | applied: the planned work units of the trial (the rows of its tier, the rows that the job slices; a single-record trial: its panel rows x L) |
| `bench_evidence.check_integrity` (B15, P10) | `missing-trial`, `duplicate-rows`, `unplanned-row`, `cross-run`, `work-count`, `pyperf-agreement` | applied (`pyperf-agreement` is the `forged self-timing` check) |
| `bench.check_perturbation` (B13) | `control-zero`, `timed-launch`, `memory-in-timing` | applied |
| `bench.check_metrics` (mandatory metrics) | `metrics` | applied |
| `bench.check_caller_semantics` (B10/B13) | `caller-semantics` | applied |
| `bench.check_concurrency_identity` (B10) | `pool-identity` | applied, with the tier rows of the trial (a local plan records no row count); one row for each call of a single-record trial |
| `bench.check_native_timing` (FR6 N4) | `native-timing` | applied; the trial is also ineligible |
| `bench_guardrails.orphan_reasons` (B12) | `orphans` | applied |
| ineligible required rows | row `eligible` | applied (the existing aggregate check) |
| bench-observation schema, FR5 verdict count names | none | replaced: the observations never leave the container; the host validates the closed aggregate and requires every row to be a planned row |
| `bench_accounting.reconcile` CPU inequalities (B15) | none | replaced by the cgroup identity check of each job (the redacted job reports no coordinator window; Task 31 P3R5-01) |
| memory eligibility | none | not applicable: a local decision run runs no memory trial (ledger EX19-LOCAL-MEMORY-01) |
| dataset identity | none | replaced by the host merge (`dataset-differs`) and the fixture digest check of the coordinator |

The planned work of a trial has one definition,
`container/bench_trial_work.py`, which the host rules (P07, B15
`wrong work count`, B10) and the job rules (`work-count`, `pool-identity`)
both use. A single-record (panel) trial makes L passes of one one-row call
per panel row, so its planned work is the number of panel rows x L (6 x L),
never the rows of its tier; each of its pooled calls holds one row, so its
pool identity has one chunk of one row. Every other trial has the rows of
its tier (a capacity trial: for every request of every client).
The caller interval of a single-record trial reports the same phases as
every other caller trial: prepare, work and materialize (and the pool start
of a cold pool) are the sums over its 6 x L timed calls, and the transport
of a C trial is the sum of the transport time that the codec reports for
each call. A call that reports no transport time leaves the transport
unknown, and B08 then refuses the row. So the one-row probe points of a
smoke plan, which are single-record trials, meet the B08 phase rule.
The case rule binds the two forms (T6R1-A02, `bench_model.selector_rules`):
a point with a `panel` and a `unit` must name a `<selector>/single-record`
unit, and a point with a `/single-record` unit must have a `panel`. So a
`/full-dataset` verdict never rests on the one-row calls of a panel point.

### The window estimate of a local plan

A local window has no shared reference batch: each session job computes its
own reference over its rows with its reference selector, and a whole-run job
also its summary. The window estimate of a local plan therefore counts two
reference batches in every session (the reference and a summary of one
reference batch, as the framework control's `local_summary` computes; an
upper bound, because a partial job computes no summary) and no group
reference. The job's rows and selector include the control rows that each
window session holds. The reference of such a job covers the selector of
its unit trials and the selectors of its control trials through the
`reference_cover` hook (R48, ruling R51); without the hook it is the
reference of `all`. The packing of a local plan's sessions reserves the
same reference work, so every session with its controls and its reference
work stays within the session cap. A project whose `local_summary` costs more
than one reference batch must keep the session estimates below the cap
with that margin.
- Memory and capacity trials of a local plan are not run. The merged
  document lists them in `not_run`; they decide nothing (a missing memory peak
  is missing evidence).
- A window attempt records `window`, `attempt`, `window_plan_id`, `extends`,
  `attempt_outcome` (from the control pairs of the merged document) and
  `envelope_identity`, as a synthetic attempt does. The window chain and
  `bench decide` read a local attempt through its merged document.
- `bench decide` re-derives the status of a local run from its recorded
  aggregates (a merged document that differs from the merge of its
  aggregates is INVALID_EXPERIMENT) and decides from the per-block values of
  the merged document with the same code as a synthetic run. A record of a
  local run has `local: true` and the quality `owner fixture, local run,
  aggregate`.
- A window smoke calibration (`--policy NAME --mode smoke`) runs on a
  synthetic dataset only: a local run records no observations.

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
  container; the privacy suite checks that stderr keeps a byte count only. A
  local decision run merges one closed aggregate per job (section "Local
  decision runs").

## Selftests

`bench selftest --suite unit|controls|privacy|cases|project|all`:

- `unit`: the framework unit tests of the bench tools and `benchlab` in the
  container (with `--project DIR`, the project's declared unit groups).
- `controls`: the CPU and memory controls.
- `privacy`: the redacted stderr probe.
- `cases`: B01 (tools and wheels), B02, B03, B05 (controls), B09, B10, B13
  (real smoke and decision runs of `bench-control-spin` and
  `bench-control-wait`), B12, B14, B15, B18, the `call-deadline` control, the
  P01, P07, P10, P11, P15 subcases (mutations that each gate must reject),
  the Phase 2 cases B04, B06, B07, B08, B11, B13-echo and B16 with the P02,
  P04 and P16 subcases (`tools/bench_phase2.py`: one real smoke run of each
  native example project, the coordinator jobs `native-overlap`,
  `agreement-controls` and `failure-controls`), and
  the `stub-run-<reason>` and `stub-check-<reason>` suites of each stub that a
  project protocol declares (recorded under `not_run` when none is declared).
- Phase 2 rules (ruling EX13-R4): a case or subcase either tests the real path
  and can fail, or is listed in `cases.json` `not_run` with its reason and a
  framework-ledger row. B04 is not run for a native project without the
  optional `native.trace`. The real B13-echo rows are not run until an example
  declares `echo_case`. The P16 subcases `selector-overcompute` and
  `selector-no-op` are not run until an example has per-selector counters.
  B11 is BLOCKED without a foundation qualification report of the current
  source (foundation selftest or ci; check-fast replaces it) and without a
  current sanitizer-evidence report of every native example project
  (`artifacts/project-sanitizers/<project>.json`, written by
  `bench sanitizer-evidence --project DIR` or by the ci step before the bench
  gates). A full ci writes both, parent and fresh child alike. Four PASS gate
  rows are not enough: B11 is BLOCKED when a report has a verdict other than
  PASS or FAIL or holds a blocker, and FAIL when its verdict is FAIL. B11 checks
  each report against `schemas/project-sanitizer-report.json` when it reads
  it: a report that is no JSON or fails the schema (for example one without
  the `blockers` list) is BLOCKED, never read as "no blocker".
- `bench sanitizer-evidence --project DIR` runs the ubsan, asan, msan and tsan
  gate builds of the project check (same builds, tests and sanitizer banner
  rule) on an immutable snapshot and writes the project's own report; it is no
  project check and never writes `artifacts/project-report.json`. Measured for
  bench-demo: see the EX-13 report (about one minute).
- Phase 2 cost: each native example project adds one smoke run and its jobs to
  the `cases` suite. Measured for bench-demo: about 70 s (one smoke run and the
  jobs `native-overlap` and `agreement-controls`) plus a few seconds for
  `failure-controls`; `cases.json` records the measured `seconds` per project.
  Bound: every job has the `smoke` deadline (600 s) and the run has its own
  deadlines. An example with a slower case adds its own time.
- B17 (real complete demo matrix, `tools/bench_phase3.py` `b17_suite`): the
  public commands `bench run --mode smoke --dataset synthetic:small --matrix
  full`, `bench compare` and `bench report` on the framework control case
  `bench-control-spin` and on the first C case of every native example
  project. Each run must be VALID and current, observe every cell of its
  case's matrix (`matrix_complete`: every implemented variant, worker count and
  route in warm and cold caller rows, one memory trial each, the kernel rows of
  the direct Python and C variants, every capacity configuration; the inproc
  cold cell is not-applicable), and its report must hold every row with its
  numbers (C rows with their comparison against the best Python row, whatever
  the outcome). The suite also needs each dimension of the brief's property
  (Python and C with one and with several workers, the three scopes, warm and
  cold caller rows, memory trials, the three routes) in a passing run. No
  framework control declares a C variant with several workers, so
  `c-multiple-workers` is in `cases.json` `not_run` with ledger row
  EX17-B17-CMULTI-01, a framework backlog item: a framework control that
  declares an implemented C variant with several workers fills it (the
  standalone examples are outside the framework scope). Any
  other missing dimension is a FAIL. On the reduced envelope that the policy
  allows (2 CPUs), the cells beyond the envelope cannot run: the target and the
  suite are BLOCKED with the reason, never FAIL; any other problem is a FAIL.
  The ci gate `bench-selftest` records the `not_run` entries in its details,
  and `dev readiness` never reports `demo_experiment_execution` COMPLETE while
  a B17 entry is open or the list is unknown. The G10.4 unit smoke job is not
  implemented yet (ledger row EX17-A04). Cost: about two smoke runs; `seconds`
  records the measured time.
- `project`: for each example project, its bench unit suite and every declared
  `before_run` check.
- Scope: the framework ci and `bench selftest` without `--project` run the
  example parts of `cases` and `project` on the framework examples. With
  `--project DIR`, the stub suites, the Phase 2 native cases and B11, the B17
  example targets, the unit smoke jobs, the P15 `removed-safety-check` entries
  and the `project` suite run on DIR instead; B18 and the sanitizer evidence step
  of the ci stay framework scope. B11 then needs DIR's own report
  (`bench sanitizer-evidence --project DIR`).

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
  `bench run` derives the expected identity of each `dataset_ref` from the
  points that the plan holds (`bench.planned_points`, R48), so a unit point
  of a window smoke plan keeps its `dataset_ref`; a different identity is
  run-invalid.
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
  of the entries; overlapping selectors are refused (tests only). `I9.3`:
  after calibration the deadline input is the calibrated wall of the call;
  the measured walls and the smoke probe points (section "Plan sizing and
  calibration"). `I9.4`: the stub selftests (now from the protocol `stubs`).
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
  review findings. `R48` and `R51`: the run reference of the planned
  selectors (`reference_cover`, also for a local job of more than one
  selector) and the dataset identity of the planned points.
- `FS1 Fn` and `FRn`: the framework release work items.
- `brief section N`, `Task N` and review IDs (`T17-APP-01`, `P1-R1-10`):
  history labels only.

## Concurrent sessions

A bench session holds exclusive admission for its whole duration: the ci
bench gates take about 17 min, and a decision run can take hours. While it
holds the lock, every other container admission of the same uid waits 60 s
and then BLOCKS. A job that
already waits for memory headroom BLOCKS at once when a bench session takes exclusive admission during that wait.
Before a long run, hold the launcher lock
(`flock /tmp/safe-c-launcher.lock`) and tell the other session first.
Run `tools/runtime_cache.py` directly, never under that lock: it takes the
launcher lock itself, so an outer `flock` makes it wait and then refuse.
