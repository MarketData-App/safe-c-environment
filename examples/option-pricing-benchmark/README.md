# Option-pricing benchmark example project

This example is the reference implementation of a registered workload for the
benchmarking framework. It shows how a project uses the framework.

The workload is the option-chain Greeks comparison (`option-chain-greeks`). For
each contract of one option chain, it finds the implied volatility from the mid
price. Then it calculates the price and five greeks for three models:
Black-Scholes-Merton, Bjerksund-Stensland 1993 and a CRR binomial tree with
100 steps. The definitions are the QuantLib 1.43 engines (spec Amendment B):
`AnalyticEuropeanEngine`, `BjerksundStenslandApproximationEngine` and
`BinomialVanillaEngine` with Cox-Ross-Rubinstein. The IV solver is QuantLib
`Brent`. `NOTICE-QuantLib.md` lists the transcribed files and the license
record.

The example compares these variants:

- Phase 1: `py-reference`, `py-optimized` and `py-library`.
- Phase 2: the C pricer (`c-serial`).

All rows are single-threaded (owner decision 2026-10-16). The example has no pool variant.

## Layout

All workload files are in `benchmarks/project/`:

- `bench.json`: the project declaration. It names the case ids and the
  declared checks only. It sets no flag, limit, deadline or budget.
- `cases/option-chain-greeks.json`: the case manifest (parameters, variants,
  scopes, sizes and measurement points).
- `cases/option-chain-greeks.opportunity.json`: the opportunity record. A C
  variant needs an approved record before it can run.
- `python/optionlab/`: the workload package. The adapter is in `adapter.py`.
  The declared checks are in `checks.py`. The models, the solver, the reference
  evaluation, the agreement rules, the synthetic chain generator and the oracle
  code are in the other modules.
- `python/tests/`: the workload tests. The framework runs them in the bench
  container.

The approver-locked protocol data lives in the protected protocol directory
`benchmarks/project/protocol/`: `protocol.json` holds the models, the
tolerances, the solver settings, the planning shares, the required checks, the
decision policy, the stubs and the panel rule. `oracle.json` holds the oracle
set, the calibration, the ALO table and the dated SOFR constant.
`aggregate.schema.json` holds the summary schema of a local aggregate. The file
`bench.json` binds `protocol.json` by sha256, and `protocol.json` binds the
other two files by sha256. `optionlab.protocol` reads them.

The third-party wheels and sources live in the protected directory
`benchmarks/project/third_party/` (EX-5). `lock.json` pins the wheels
QuantLib 1.43 (row `quantlib`), SciPy 1.16.2 and mpmath 1.3.0 (`wheels/`),
the QuantLib 1.43 source release (`sources/QuantLib-1.43.tar.gz`) and the
eight retained Boost 1.90.0 files (`sources/boost-1.90.0/`). Each row binds
its provenance record (`provenance/`), its notice (`notices/`) and a license
record (review status APPROVED for the QuantLib source release, PENDING for
the other rows; see the section License). The QuantLib row declares its two members
above 32 MiB (`host_members`) and its license member in the wheel data
directory (`notice_member`). `bench.json` binds the lock by sha256. The
framework builds the project bench image from these wheels offline; every
bench job of this project runs in that image, with the wheels under
`/opt/project-python`. The wheels came from the one approved online step
(`artifacts/approvals/ex-option-T14-online/verdict.md`); their bytes equal
the perf-lab files.

## License

The files that this project wrote are under the MIT license of the repository ([LICENSE](../../LICENSE)). The MIT
license covers only those files. Third-party files keep their own licenses:

- `benchmarks/project/third_party/` holds the QuantLib 1.43 wheel and source release (BSD-3-Clause, the QuantLib
  license), the SciPy 1.16.2 wheel (BSD-3-Clause; its bundled libraries keep their own licenses), the mpmath 1.3.0
  wheel (BSD-3-Clause) and eight Boost 1.90.0 files (BSL-1.0). `lock.json`, `provenance/` and `notices/` record each
  one.
- [NOTICE-QuantLib.md](NOTICE-QuantLib.md) lists the Python and C files that transcribe QuantLib 1.43 or Boost 1.90.0
  code. Their transcribed parts stay under the QuantLib license or the Boost Software License 1.0. NOTICE-QuantLib.md
  holds the copyright notices and the license texts.
- The SciPy wheel bundles GCC runtime libraries under GPL-3.0-or-later WITH GCC-exception-3.1 and LGPL-2.1-or-later.
  [SOURCE-OFFER.md](SOURCE-OFFER.md) gives the written offer for their source code.
- License review: the agent engineering license review LR-EX (2026-10-18; not legal advice) found no license conflict
  with the MIT license. The legal team confirmed on 2026-10-19 that QuantLib is under the BSD 3-Clause License, a
  permissive license that permits commercial and proprietary use. `lock.json` therefore sets the row `QuantLib-source`
  (the QuantLib 1.43 source release) APPROVED. The row `quantlib` (the QuantLib-Python wheel) stays PENDING: the wheel
  also holds compiled Boost 1.90.0 code (BSL-1.0), which the confirmation does not name. The Boost, SciPy and mpmath
  rows stay PENDING: they have no separate legal-team statement. The section "License record" of NOTICE-QuantLib.md
  holds the full record.

## The workload contract

The framework uses the workload only through the registered-workload interface
(`benchlab.workload`). The class `optionlab.adapter.OptionChainGreeks`
implements each part of the contract with the method of the same name.

Note: Task 13b adds `adapter.py` and the class `OptionChainGreeks`. Until
then, `bench validate`, `bench plan`, `bench run` and `bench profile` for this
case fail, because the adapter cannot be imported. The unit suite and the
declared checks work now.

| Part | Method | What it does |
|---|---|---|
| Core | `load(spec)` | Reads and checks one chain file (`optionlab.contract`). |
| Core | `prepare(data, variant, workers)` | Makes the input for one variant. |
| Core | `run(prepared, variant, workers)` | Evaluates every contract (the timed call). |
| Core | `work_units(result)` | Counts the contract evaluations. |
| Core | `validate(result, reference, data)` | Compares a result with the reference (`optionlab.agreement`). |
| Trial runner | `synthesize(rows, seed)` | Makes a seeded synthetic chain (`optionlab.synthetic`). |
| Trial runner | `slice(data, n)` | Keeps the first `n` contracts. |
| Trial runner | `slice_result(result, n, data)` | Keeps the result rows of the first `n` contracts. |
| Trial runner | `materialize(raw)` | Turns the raw output into a result. |
| Trial runner | `reference(data)` | Calculates the reference result (`optionlab.reference`). |
| Trial runner | `digest(result)` | Gives the canonical digest of a result. |

The adapter has no pool part. The case manifest declares single-threaded variants only, so the
framework builds a non-pooled adapter. `with_market(items)` copies the adapter with `copy.copy(self)` and keeps
`bench_ref`. Only `benchlab.workload.construct_adapter` builds an adapter, and the construction guard in
`tests/test_construction.py` checks this for the package.

## Commands

Run all commands from the repository root:

```sh
./tools/safety bench validate --project examples/option-pricing-benchmark --case option-chain-greeks
./tools/safety bench check --project examples/option-pricing-benchmark --check b06-prerequisite-oracle
./tools/safety bench plan --project examples/option-pricing-benchmark --case option-chain-greeks
./tools/safety bench run --project examples/option-pricing-benchmark --case option-chain-greeks
./tools/safety bench compare --run-id RUN_ID
./tools/safety bench report --run-id RUN_ID
./tools/safety bench profile --project examples/option-pricing-benchmark --case option-chain-greeks
./tools/safety bench selftest --suite unit --project examples/option-pricing-benchmark
```

- `bench validate` imports the adapter. It sends a small synthetic chain
  through every implemented Python variant and compares the result with the
  reference.
- `bench check` runs one declared check in a bounded container job.
- `bench compare` and `bench report` read the evidence of one run. `RUN_ID`
  is the run id that `bench run` writes.
- `bench selftest --suite unit --project` runs the tests in `python/tests/`.

The declared checks are:

- `b06-prerequisite-oracle` (`before_run`): every oracle item of the Task 9
  oracle set must pass, including item 9 (QuantLib agreement).
- `quantlib-alignment`, `optimized-agreement` and `b06-prerequisite-agreement`
  (`before_run`): the variants must agree with the reference and with QuantLib.
- `oracle-generate` and `oracle-calibrate` (`before_run: false`): they make
  the oracle set and the calibration. The framework driver
  `tools/bench_oracle.py` and the protected fixture file are gone. The oracle
  data now lives in `benchmarks/project/protocol/oracle.json`, which the
  protocol binds by sha256. A change of that directory needs approval.
  - Run them with `bench check --long`, one part per call:
    `./tools/safety bench check --project examples/option-pricing-benchmark
    --check oracle-generate --long --arg <part>`. The parts are `bsm`, `bjs`,
    `lattice`, `greeks`, `monotonicity`, `edges`, `lnphi`, `baw` and `alo`.
    `oracle-calibrate` takes no argument:
    `bench check ... --check oracle-calibrate --long`.
  - `--long` selects the framework job deadline `long_check` (10,800 s). It is
    the old `oracle_part` deadline. Without `--long`, the check gets the
    `smoke` deadline (600 s) and a long part fails on time.
  - The selftest does not run them. `bench selftest --suite unit --project`
    runs only the unit groups. `bench selftest --suite project --project` runs
    the unit groups and every `before_run: true` check, and skips
    `before_run: false` checks.

## Mandatory gate

This example is framework content. The framework qualifies it with the
framework. The `bench-selftest` gate of `./tools/safety ci` finds each
directory `examples/<name>` that holds `benchmarks/project/bench.json`. For
each one, the gate runs the bench unit suite (`python/tests/`) and every check
marked `before_run` (here the four checks above). A failure of the suite or
of a check fails the gate. `check-fast` and `check-full` run no bench suites.

## Rules

- Correctness comes first. Every check marked `before_run` must pass before a
  timing run measures the cases of this project.
- A CI smoke number never fails or approves a change.
- The owner's chain file enters only through `--dataset local:PATH`. It never
  enters git, a committed artifact or an export.

## First smoke run

Label: `smoke-exploratory`. These numbers are not decision evidence. No
decision rule is applied to them.

- Run id: `2bb6d10ed2d9473aad9f99a953cd4224`. Status: VALID, 67 observations,
  0 reasons.
- Command: `./tools/safety bench run --project examples/option-pricing-benchmark
  --case option-chain-greeks --mode smoke --dataset synthetic:small`.
- The dataset is synthetic. It has 256 contracts per call.
- The run executes the four `before_run` checks first. They took 117 s of the
  312 s run.
- The report labels the `py-library` rows "C++ library through SWIG".

Warm caller, wall time per call (median of 2 repetitions, 256 contracts):

| variant | workers | ms per call |
|---|---|---|
| py-reference | direct | 6330 |
| py-library | direct | 533 |
| py-optimized | direct | 190 |

That run also measured two pool rows. They left the example (owner decision 2026-10-16: single-threaded rows only).

The profile run `b3cf3153288a4f679590f5815356be05` (1024 contracts) shows
that the CRR binomial engine holds most of the time. In `py-reference`,
`crr_engine` holds 43.9 s of the 87.1 s profiled wall time as exclusive time
(about 50 %) and 83.3 s as inclusive time (about 96 %). In `py-optimized`,
`crr_engine` holds 0.278 s of 0.44 s as exclusive time (about 63 %). The
profile is diagnostic only.

The opportunity record holds the `py-reference` footprint of this run. The
time fields are medians of 2 repetitions. The memory fields
(`ready_state_bytes` and `group_peak_bytes`) come from a single trial
(n = 1).

## Market parameters for the owner chain

This section applies only to `local:` runs on the owner chain (spec
Amendment C). CI, the tests, the synthetic chain, the oracle and every export
keep the labeled assumptions r = 0.0400 and q = 0.0120.

There is no network step (EX-6). The framework market step and the commands
`bench market-rate` and `--market` left the framework in FR3. The adapter
`load` does the market step inside the container. A dataset is synthetic only
when it is not empty, every `optionSymbol` fullmatches the generator form
(`SYN`, the expiration digits, `C` or `P`, five strike digits) and
`underlying` is `SYN` on every row (what `optionlab.synthetic` writes). A root
such as `SYNA` is not synthetic. `load` prices every other dataset with the
SOFR constant of the protocol and the per-expiry q of the chain. It never
takes the case assumptions for such a dataset, and it never runs without a
rate. When the protocol SOFR day is not the SOFR date of the snapshot, `load`
raises a `ValueError` whose message starts with `market_date_mismatch`, before
any trial. In a local job, `load` first runs in the reference child process,
whose output goes to no log. So the aggregate records the exception type
`Other` (not `ValueError`), the aggregate status is `INVALID_EXPERIMENT`, the
job status is `FAIL`, and no reason text is kept. `load` marks the
origin of the chain, and `panel_inputs` refuses a chain that is not
synthetic. Tests: `OwnerChainFailClosedTests`
and `ProtocolRateTests` in `tests/test_market.py`.

Rate (`optionlab.market`, Amendment C item 2):

- The snapshot date is the America/New_York date of the largest `updated`
  value of the chain. `market_parameters` (not called by a run, because the
  aggregate has no market block) counts the rows of another New York date
  (`updated_other_date`). These rows keep the same rate.
- The expected SOFR record is the business date of the snapshot date: the
  snapshot date, or the previous business day. Weekends, Federal Reserve
  holidays and SIFMA closures are not business days. The example holds the
  rule of the removed `tools/bench_market.py`, and `HolidayCalendarTests` pins
  its calendar.
- The SOFR record is the dated constant of the protocol, read only through
  `optionlab.protocol.sofr()` (`oracle.json`, `market_constants.sofr`: day
  2026-10-05, percent 3.89, source and URL). No environment variable, argument
  or file changes it. A change is a change of the protected protocol
  directory and needs a new approval.
- SOFR is an overnight simple rate R on ACT/360. The model rate is the
  continuous ACT/365 rate r = 365 · ln(1 + R / 360) with R = percent / 100,
  that is r = 0.0394381 for 3.89 percent. The protocol field `rate` (0.0389)
  is the simple rate R. It is not the model rate. A test pins the converted
  value. One overnight rate for every maturity is an approximation. No term
  structure is used.
- A snapshot whose expected SOFR date is not the protocol day stops the run
  before any trial: `load` raises `ValueError` with the message
  `market_date_mismatch`. In a local job the aggregate records the exception
  type `Other`, the aggregate status `INVALID_EXPERIMENT` and the job status
  `FAIL`. No reason text is kept.

Dividend yield per expiry (Amendment C item 3):

- Only rows that pass the status orders 1-4 are eligible. A `NO_BID` row
  never enters a pair.
- A pair is one call and one put with the same expiration, strike, `updated`
  and `underlyingPrice`. Both quotes must be quotable (mid ≥ 0.05, ask − bid ≤
  max(0.05, 0.10 · mid)), and T ≥ 7/365. A pair whose rows differ in
  `updated` or `underlyingPrice` is skipped and counted.
- Only strikes with F · e^{−0.05} ≤ K ≤ F are used (F = S · e^{rT}). There,
  the bias from early exercise is smallest.
- Each pair gives q_i = −ln((C − P + K·e^{−rT}) / S) / T. A pair whose
  argument is not positive is dropped and counted.
- The estimate is the median of q_i over at least 3 pairs, with the median
  absolute deviation. T_e is the median T of the accepted pairs.
- An estimate outside [−0.05, 0.15] is rejected and counted. An expiry of at
  most 30 days whose estimate is above 0.15, or more than 0.05 above both
  neighbouring estimates, gets the flag `ex_dividend_suspect`. The
  neighbouring estimates are the nearest estimated expiries on each side in
  T_e.
- An expiry without an estimate takes q of the nearest estimated expiry in
  T_e (method `nearest`). When no expiry has an estimate, every expiry takes
  the labeled assumption 0.0120 (method `assumption`).
- Parity identifies the carry b = r − q. An error of the overnight SOFR
  against the term rate of the expiry goes one-for-one into q_e. Thus q_e is a
  carry-implied value.
- The reference, every variant and the provider cross-check price each row
  with r and the q_e of its expiry.

American exercise (Amendment C item 4): SPY options are American, so the
parity estimate has an upward bias when r > q. The CRR(800) sizes of the spec
are +0.0018 at 7 days, +0.0026 at 0.25 years and +0.0038 at 2 years at the
money, and +0.018 at 7 days for an in-the-money put (K = 1.05 · S). The run
reports per expiry the median of (e_P − e_C)/S and the median and maximum of
δq = (e_P − e_C)/(S·T·e^{−q_e T}), from the BjS implied volatility of each
side. BjS is a lower bound on the American price, so these numbers are lower
bounds. The estimator is not corrected in Phase 1.

Qualification domain (Amendment C item 5): local runs use carries b in about
[−0.11, 0.10]. The derivations of sections 3.3-3.4 and the oracle grid do not
qualify this domain. The oracle edge rows `local-domain-*` (each model, an
at-the-money put, T = 30 days, at b = −0.10, b = +0.09 and q = −0.02) are a
spot check only. Their names use `m010`, `p009` and `m002` because the fixture
name pattern allows no `.` and no `+`.

Privacy: the market step logs and exports no record value. The messages of
`load` hold fixed text only. The market block of the earlier aggregate (the
SOFR record, the snapshot date and per expiry the date, T_e, q_e, the method,
the flag, the counts, the MAD and the bias numbers) is not written now: the
aggregate schema of the protocol has no `market` block, and its grammar allows
no date string. `optionlab.market.public` and `adapter.market_parameters` keep
the rule (a value computed from fewer than 5 pairs is null) for a later
protocol change. The aggregate gate of the framework is the control until then.

Command (local only, never in CI):

```sh
./tools/safety bench run --project examples/option-pricing-benchmark --case option-chain-greeks \
  --mode smoke --dataset local:PATH
```

`load` estimates q over every row of the chain. A smoke run then prices the
first 256 rows with these values.

Owner fixture, local run, aggregate (run `d4537c9715f84d0c9440e06e6dede3e5`,
status VALID, 256 rows). The table holds only chain-level counts. The
per-expiry values stay in the local aggregate.

| item | value |
|---|---|
| SOFR effective date (= snapshot business date) | 2026-10-05 |
| SOFR percent rate | 3.89 |
| `updated_other_date` | 0 |
| expiries | 33 |
| method `parity-median` / `nearest` / `assumption` | 28 / 5 / 0 |
| `ex_dividend_suspect` expiries | 0 |
| accepted pairs, total | 673 |
| skipped / dropped pairs, rejected estimates | 0 / 0 / 0 |
| expiries with withheld bias values (fewer than 5 bias pairs) | 5 |

A first run with the 2026-10-06 record stopped before any trial with the
reason `market_date_mismatch` (run `bba8facb4d1b4275b36957786029789c`). Both
runs used the framework market step, before EX-6. A run of the current code
writes no market block into the aggregate. In a local job a date mismatch is
recorded as the exception type `Other`, with the aggregate status
`INVALID_EXPERIMENT` and the job status `FAIL`; no reason text is kept.

## Phase 2

Phase 2 adds the C pricer to this example: `project.json`, `specs/project/`,
`src/`, `include/`, `tests/project/` and `fuzz/project/`. This command checks
it with all project gates:

```sh
./tools/safety project check --project examples/option-pricing-benchmark --development
```

`project.json` declares the modules `models` (`src/pl_ieee.c`: IEEE-754
binary64 helpers; `include/pl_types.h`: shared types) and `batch`
(`src/pl_kernel_cli.c`: the `pl-kernel` command line), and the program
`pl-kernel` (main `src/pl_kernel.c`, modules `models` and `batch`). The run
entry is `pl-kernel --self-check` with exit code 0. Later Phase 2 tasks add the
modules `protocol`, `serve` and `inproc` and the program `pl-worker`. While the
framework differs from `framework-manifest.json`, the command exits with code
3 (`PASS_UNQUALIFIED_FRAMEWORK`), which is the expected pass.

## Phase 3

Phase 3 adds the decision commands, the capacity rows and the B17 demo matrix.
These owner rules apply to every Phase 3 text and report of this example:

- Every row is single-threaded: no pool variant, no thread variant and no
  concurrent client (owner decisions of 2026-10-16 and 2026-10-20).
- The decision rule of the project applies to each route separately. C wins on
  a route only if Python adds at least 200 ms per request AND C is consistently
  more than 20 % faster end to end on that route. Otherwise the answer is
  Python. The protocol holds this rule as the unit-threshold policy
  `unit-200ms-and-20pct`: ten units, the five models BSM, Bjerksund-Stensland,
  CRR, BAW and ALO, each on the full chain and on one contract.
- QuantLib 1.43 is the correctness baseline.
- No report holds market-rate diagnostics. The owner will supply dividend
  projections later.

Decision commands (run from the repository root):

```sh
./tools/safety bench run --project examples/option-pricing-benchmark --case option-chain-greeks --mode smoke
./tools/safety bench plan --project examples/option-pricing-benchmark --case option-chain-greeks --mode decision --dataset synthetic:large --calibrate SMOKE_RUN_ID
./tools/safety bench run --project examples/option-pricing-benchmark --case option-chain-greeks --plan PLAN_PATH
./tools/safety bench compare --run-id RUN_ID
./tools/safety bench report --run-id RUN_ID
./tools/safety bench decide --run-id RUN_ID
```

- The smoke run is the calibration source of the plan (`SMOKE_RUN_ID`).
- `bench plan --mode decision` writes the plan and its estimate
  (`estimate_seconds`). The planner refuses a plan above the 8 h decision cap.
  The owner or the approver then chooses a fallback as a new plan version.
  Nobody shrinks the plan.
- `bench decide --run-id RUN_ID` applies the three rule policies of the
  framework (`owner`, `demo-latency-2x` and `demo-cpu-40` in
  `safety/performance-policy.json`). A decision with these policies is a
  demonstration. It gives no unit verdict of this project.
- `bench decide --run-id RUN_ID --policy unit-200ms-and-20pct` applies the
  project rule. Only the owner decision runs use it. They also need the
  evidence options `--ci-run-id`, `--approval` and `--sensitivity-confirmation`.
  This policy decides only window runs: `bench decide` refuses any other run
  (`not-a-window-run`). An owner run therefore needs the window plan of this
  policy, `bench plan --policy unit-200ms-and-20pct --mode decision
  --calibrate SMOKE_RUN_ID`, run with `bench run --plan PATH --window ID`. The
  plain `--mode decision` plan without `--policy` is not enough.
- `bench decide` reads only the caller rows. Kernel rows and capacity rows
  never decide.

Owner-run preparation (EX-22, Phase 3 addendum Task A10):

- The panel pre-flight (`bench check --check panel-preflight`) passed with 0
  replacements for the Python rows. The `native-routes` check runs the six
  panel rows on each route of the C row.
- The owner smoke calibration is run `9582b6735b6441d694047c489e883dbf`
  (`bench run --case option-chain-greeks --mode smoke --policy
  unit-200ms-and-20pct`, VALID). It is the calibration source of the owner
  window plans and of the owner decision runs.
- The synthetic window plan (`--dataset synthetic:large --calibrate
  9582b6735b6441d694047c489e883dbf`) has one window `1a` with the ten units.
  Its estimate is 25,270.7 s (about 7 h), with 237.3 s of control trials.
  The proposed cap is 600 x ceil(1.2 x 25,270.7 / 600) = 30,600 s. The
  protocol records it as `windows.caps_seconds.synthetic`.
- The local window plan (`--dataset local:PATH --calibrate
  9582b6735b6441d694047c489e883dbf`) is made, and its cap is recorded, before
  the freeze (ruling R103). The estimates use the tier rows of the policy, not
  a count of the dataset. Each local session job computes its own reference,
  so the plan has two windows: `1a` (85,333.1 s) and `1b` (86,063.1 s), each
  with 257.9 s of control trials. At the provisional cap of 79,200 s the plan
  refused (`owner-cap-exceeded`). The local cap is
  600 x ceil(1.2 x 86,063.1 / 600) = 103,800 s. The protocol records it as
  `windows.caps_seconds.local`, and the plan passes at this cap.
- At the owner's go, the decision task makes the synthetic and the local
  window plans again from the same smoke calibration.
- The aggregate schema of the protocol lists the five models as optional
  properties, so the summary of a per-unit local run (one model) passes the
  host gate. The example code refuses an `all` summary without one of its
  three models.

The demo decision run on the synthetic large chain, with the three rule
policies of the framework, is in
[docs/performance-demo-report.md](docs/performance-demo-report.md). It is a
demo, not a decision run: it gives no unit verdict of this project.

The integration recipe for a service is the section
[Calling the pricer from a service](#calling-the-pricer-from-a-service) below.

### Capacity (exploratory; capacity rows never decide)

The case capacity block has one configuration: `serial-workers` with the
Python variant `py-optimized` (direct), one client, 8 requests per client and
the tier `small` (256 contracts). One client sends one request at a time, so no
two capacity requests run at the same time (owner answer of 2026-10-20: single
thread only). The framework schema accepts the client list `[1]`. The
configurations `threaded-worker` and `python-pool` and the client counts 2 and 4
of the plan are not used. A decision plan holds 3 capacity trials (one per
block); a smoke plan holds 1.

The lab has no C capacity number. The framework capacity job
(`container/bench_capacity_job.py`) starts its child process without the native
environment (`SAFE_C_BENCH_NATIVE`) that the timing and memory jobs give their
children, so a `c-serial` capacity call cannot find the restored `pl-worker`.
The smoke run 176b4bab9b6d4f67b493d8829189b46c with the earlier `c-serial`
configuration was therefore INVALID_EXPERIMENT ("capacity session did not
complete"). The open ledger row EX20-CAPACITY-CNATIVE-01 records this framework
defect (owner: framework release coordinator). Read every capacity number with
these facts:

- For `serial-workers`, the plan sets one server slot for each CPU of the
  envelope. A direct Python variant starts no server, so a slot holds nothing.
  With one client, only one slot is in use at a time.
- Each capacity request runs `prepare`, `run` and `materialize` of
  `py-optimized` in the capacity child process.
- The capacity loop calls `adapter.validate` inside the measured loop.
  `validate` builds the canonical form of every eligible result (T22-A03), so a
  capacity latency also includes that Python serialization.
- A latency percentile needs 20 (p50), 100 (p90) or 1000 (p99) samples. A
  decision plan gives 24 samples (3 trials of 8 requests): p50 only. A smoke
  plan gives 8 samples: no percentile.
- The capacity CPU numbers are not reconciled with the cgroup accounting (B15).

### B17: the complete demo matrix

`bench selftest --suite cases --project examples/option-pricing-benchmark` runs
B17 on this case: a smoke run on the synthetic small chain with the full
matrix, then `bench compare` and `bench report` on that run. The matrix of this
case has 21 cells:

- `py-reference`, `py-optimized` and `py-library` on direct workers: a warm and
  a cold caller row and one memory trial each, and a kernel row for
  `py-reference` and `py-optimized` (a library-backed variant has no kernel row);
- `c-serial` on the routes `stdio`, `shm` and `inproc`: a warm and a cold
  caller row and one memory trial per route (the `inproc` cold cell is
  not-applicable: the library load is the startup phase), and one kernel row;
- the capacity cell `serial-workers` (`py-optimized`, direct).

The case has no multiple-worker cell (owner rule). B17 therefore keeps the
dimension `c-multiple-workers` NOT_RUN with the framework ledger row
EX17-B17-CMULTI-01. The dimension `python-multiple-workers` comes from the
framework control case `bench-control-spin`. `CapacityAndMatrixTests` in
`tests/test_light_manifests.py` pins the cells and the capacity trials.

## Calling the pricer from a service

Status: this recipe is untested against the real application. The example tests
the function below with synthetic chains only.

A Django view, a service or a management command prices one chain with one call:

```python
from optionlab.api import price_chain
from optionlab.contract import load_chain, with_rates

chain = with_rates(load_chain(decoded_market_data_json), r_per_row, q_per_row)
result = price_chain(chain, models=("bsm", "bjs", "crr"), backend="python")
```

`price_chain(chain, *, models=("bsm", "bjs", "crr"), backend="python", workers=None)`
returns the `optionlab.reference.run` shape: `{"n": n, "models": {model: columns}}`.
Each model holds the columns `status`, `flags`, `iv`, `price`, `delta`, `gamma`,
`theta`, `vega` and `rho`, one value per row. The `python` backend also returns
columns that the `c-worker` backend does not return: `engine_evals` for each
model, `admit_reason` for `baw`, and `alo_equation` and `alo_nan_guarded` for
`alo`. The result digest of the lab ignores these columns, so the agreement
checks compare the same columns on both backends.

- `chain` is the decoded columnar chain. It must hold a per-row `r` and `q`
  column. The function never reads a scalar rate. A chain without both columns
  raises `ValueError`. Each of the columns `side`, `S`, `K`, `T`, `bid`, `ask`,
  `r` and `q` must hold `n` values, else the call raises `ValueError`.
- The function checks every value of the chain before it prices a row, with the
  same rules on both backends. A refused value raises `ValueError`, and the
  message names the row index and the field:
  - `side` must be an `int`: 0 is a call and 1 is a put. Any other `int` code
    gives the `INVALID_INPUT` row for that contract, as in `load_chain`, the
    reference and the C decode; the call continues. A `bool`, `None`, text or
    a `float` side raises `ValueError`.
  - `S`, `K`, `T`, `bid` and `ask` must be real numbers (`int` or `float`, not
    `bool`). `None` or text raises `ValueError`. A non-finite value gives the
    `INVALID_INPUT` row. An `int` beyond the binary64 range becomes `+inf` or
    `-inf`, so it also gives the `INVALID_INPUT` row.
  - `r` and `q` must be finite numbers. `None`, text, a `bool`, a non-finite
    value or an `int` beyond the binary64 range raises `ValueError`.
  - The value check takes about 27 ms for a chain of 20,000 rows (a host
    measurement of the check loop, T20b-A11). Both backends add this time to
    each call.
- `models` is a non-empty subset of `bsm`, `bjs`, `crr`, `baw`, `alo`. The
  function computes the selected models and nothing else. A repeated or unknown
  name raises `ValueError`.
- `backend` is `python` (the `py-reference` code, in the caller process) or
  `c-worker` (the C pricer, route `stdio`). Any other value raises `ValueError`.
- `workers` must stay `None`. Any other value raises `ValueError`.

The integration steps for the real application:

1. Vendor or install the `optionlab` package (`benchmarks/project/python/`) and
   pin the Python version and the dependency versions of the lab. The code also
   needs these items at run time:
   - the framework package `benchlab` (`benchmarks/performance/python/benchlab/`
     of the repository): `price_chain` builds its adapter through
     `benchlab.workload.construct_adapter` on both backends;
   - the request limit: the environment variable `SAFE_C_BENCH_REQUEST_LIMIT`,
     or the framework file `safety/performance-policy.json` (`pools.request_limit`)
     of the repository that holds `benchlab`. When both are present, they must
     hold the same value;
   - the case file `benchmarks/project/cases/option-chain-greeks.json`
     (`optionlab.params.CASE_FILE`): `price_chain` reads the case parameters there;
   - for `backend="c-worker"` only: NumPy, and the environment variable
     `SAFE_C_BENCH_NATIVE` set to the directory that holds the verified
     `pl-worker` and its `sha256.json` (`benchlab.native_worker`).
2. Call `price_chain` from the service layer, with a chain that the service
   decoded and gave per-row rates.
3. Keep the C worker as a child process. The `c-worker` backend starts one
   `pl-worker` for each call, and shuts it down and reaps it before the call
   returns. A defect of the C code ends the worker, never the caller. The worker
   file must be the one that the build restored and verified by sha256
   (`benchlab.native_worker`); no other file starts.
4. Keep database work outside the timed call. Read and write rows before and
   after `price_chain`.
5. Run the lab case again with the real interpreter and the real chains before
   you trust a timing result. The lab numbers do not transfer by themselves.
   The lab rows do not time `price_chain`: the caller-scope rows call the case
   adapter (`optionlab.adapter`), so the lab timings do not include the argument
   checks of `price_chain`.

Why the API keeps the `stdio` route: a service call must be the safest route. The
`shm` route shares memory with a writable region, and the `inproc` route loads the
C library into the caller process, where a C defect ends the caller. Both routes
are benchmark rows of the lab. A service call does not use them. The `inproc`
route also cannot run cold.

Why the API runs single-threaded rows: the owner decided on 2026-10-16 that the
example has no pool and no thread variant. The `python-processes` backend of the
plan and the `c-threads` worker counts are therefore not offered. The lab tested
one call at a time per process. No test covers two calls at the same time in one
process: the module state (the cached adapter of `optionlab.api` and
`benchlab.native_worker.LAST_STATS`) has no lock. Call `price_chain` one call at a
time in each process.

The light tests run in the unit suite (`test_light_api`). The tests with the real
worker are the check `api-native`:

```sh
flock /tmp/safe-c-launcher.lock ./tools/safety bench check --project examples/option-pricing-benchmark --check api-native --native
```
