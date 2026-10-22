# Module `batch` specification

Status: Phase 2 Task 1 part (the `pl-kernel` command line), Task 12 (the
partition of Amendment E) and Task 14 (the serial and pooled batches with the
model mask, the per-model reduction and evaluation counters, the echo kernel,
the record-scan kernel, the probe mode and the full `pl-kernel` command line;
Amendment G items G1.5, G4.4, G4.6-G4.8; Amendment I items I5.8, I13.3).
Write and review this file before any module source changes.

## Files

| File | Contents |
|---|---|
| `include/pl_batch_core.h` | every batch type and function except `pl_batch_run`, plus `pl_batch_run_untraced` (`pl_batch_run` without a trace); no GLib, so that the source-policy step of the `ast` gate stays within its memory (only `pl_batch.c`, `pl_kernel_run.c`, `pl_kernel_loop.c` and `test_batch_stats.c` include GLib) |
| `include/pl_batch.h`, `src/pl_batch.c` | `pl_batch_run`: argument checks, the serial loop, the pooled chunks through `sc_parallel_run` (section "Batch") |
| `src/pl_batch_row.c` | `pl_input_row`, `pl_output_store`, `pl_evaluate_contract`, `pl_evaluate_contract_echo`, `pl_batch_one` (one row of a request), `pl_poison_results`, `pl_reduce` (sections "Batch", "Reduction", "Echo") |
| `src/pl_batch_part.c` | `pl_echo_part`, `pl_add_counters`, `pl_reduce_row`: the part-level helpers that the loops call |
| `include/pl_scan.h`, `src/pl_scan.c` | `pl_scan`, the record-scan kernel (section "Record-scan") |
| `include/pl_kernel_cli.h`, `src/pl_kernel_cli.c` | `pl_kernel_main` and the argument parser of `pl-kernel` |
| `src/pl_kernel_opts.c` | the option table and the value parsers |
| `include/pl_kernel_run.h` | the run parts (buffers, run state, one loop); the only kernel header that includes GLib |
| `src/pl_kernel_run.c` | the static buffers, the input, the timed loops, the output files, the trace and the `PLK1` line |
| `src/pl_kernel_loop.c` | one loop of a case (`pl_kernel_loop`: the option requests r = 0, 1, the record-scan, the probe records) |
| `src/pl_kernel_probe.c` | the probe records (`pl_probe_check`, `pl_probe_record`) |
| `src/pl_kernel_self.c` | `--self-check` and `--print-params` |
| `src/pl_kernel.c` | `main`, which only calls `pl_kernel_main` |
| `include/pl_test_batch.h` | test code only (no source includes it): the shared `static inline` helpers of the batch and pl-kernel tests (REQUIRE/CHECK, the 48 test rows in their three input forms, the run and comparison helpers, the pl-kernel run and file helpers, `PL_VEC_EVALUATE_PER_ROW`, `PL_TB_MASK_FULL`, the mask check `pl_tb_masks` and the ALO subset loader and baseline) |
| `tests/project/test_batch.c` | group `serial-pooled` (workers 1, 2, 3 and 4) |
| `tests/project/test_batch_echo.c` | group `echo-reduce-arguments` (the same 48 vector rows; a file of its own for the AST dump size) |
| `tests/project/test_batch_kinds.c` | group `input-kinds` (the same 48 vector rows; a file of its own for the AST dump size) |
| `tests/project/test_batch_stats.c` | group `stats`: two requests append their chunks, the trace (the only test that includes GLib) |
| `tests/project/test_batch_limits.c` | group `limits`: every argument refusal writes nothing |
| `tests/project/test_batch_sizes.c` | groups `sizes` (the chunk-count bound) and `tie` (synthetic results; out of `test_batch.c` for its AST dump size) |
| `tests/project/test_batch_small.c`, `test_batch_threads.c`, `test_batch_wide.c` | groups `small`, `threads`, `wide`: n = 0, 1 and 48 with threads 0-1, 2-3 and 4 |
| `tests/project/test_batch_helpers.c` | group `helpers`: n = 14,336 and 14,337, the NULL and unknown arguments of the row helpers |
| `tests/project/test_batch_trap.c` | group `trap` |
| `tests/project/test_batch_masks.c`, `test_batch_masks_b.c`, `test_batch_masks_c.c` | group `masks` on the 48 rows: masks 1-5, 6-10 and 11-15 (`PL_TB_MASK_FULL`), by `pl_tb_masks` (`PL_TEST_BATCH_MASKS` of `pl_test_batch.h`); split in three for the 10 s test timeout of the coverage build (T9-A01) |
| `tests/project/test_batch_masks_alo1.c` to `test_batch_masks_alo4.c` | group `masks-alo`: masks 16-19, 20-23, 24-27 and 28-31 on the ALO subset (controller ruling R-10b-B1; four files for the 10 s test timeout, ruling (g)) |
| `tests/project/test_batch_alo.c`, `test_batch_alo_kinds.c`, `test_batch_alo_stats.c` | groups `alo-serial`, `alo-pooled`, `alo-reduction`, `alo-input-kinds`, `alo-stats`, `alo-one-row` on the ALO subset under `PL_MASK_WIRED` (ruling R-10b-B1) |
| `include/pl_vec_batch_alo.h` | generated (check `c-vectors`, part `batch_alo`): the ALO subset of ruling R-10b-B1, 13 named oracle ALO edge rows (`cvectors.BATCH_ALO_ROWS`) with the `reference.evaluate` ALO outcome under the case parameters; never edited by hand |
| `include/pl_vec_batch_rows.h` | generated (check `c-vectors`, part `batch_rows`): the 48 synthetic input rows of the batch tests (the rows of the first 144 entries of table `evaluate`; `test_batch_trap.c` checks that they are equal), so that the tests that need no expected values do not include the large `pl_vec_evaluate.h` (the memory of the source-policy step of the `ast` gate); never edited by hand |
| `tests/project/test_batch_baw.c` | group `baw-parts` (one generated evaluate header per test file, the AST dump size) |
| `tests/project/test_scan.c` | groups `scan`, `scan-errors` |
| `tests/project/test_kernel_cli.c` | modes and usage errors (groups `kernel-cli`, `option-usage`) |
| `tests/project/test_kernel_run.c` | the option case serially and with two workers, the PLK1 `digest=` of the canonical file, the trace (group `option-case`) |
| `tests/project/test_kernel_masks.c` | one-model masks, echo (`digest=none`), `--echo --canonical` refused (group `option-masks`) |
| `tests/project/test_kernel_io.c` | input and I/O failures, two requests (groups `input-io`, `requests`) |
| `tests/project/test_kernel_modes.c` | probe and record-scan (groups `probe`, `record-scan`) |
| `tests/project/test_kernel_handshake.c` | the handshake through pipes in a forked child (group `handshake`) |
| `include/pl_partition.h`, `src/pl_partition.c` | the Amendment E partition (section "Partition") |
| `src/pl_partition_arith.c` | `pl_mul_64` and `pl_add_64`, the exact arithmetic modulo 2^64 |
| `src/pl_splitmix.c` | `pl_random_init` and `pl_random_next`, the SplitMix64 step and the test script |
| `include/pl_vec_partition.h` | generated vectors (`optionlab.cvectors` part `partition`) |
| `tests/project/test_partition.c` | partition tests |

Uses: modules `models` (row evaluation, case parameters) and `protocol` (wire
records, canonical writer, I/O, clocks). Foundation: `glib-parallel` (the
`sc_parallel` adapter, `foundation/parallel/sc-parallel.h`, included with
angle brackets).

The source and test files are separate translation units (accepted, ruling (f)), so that each
call inside a loop is opaque to the GCC analyzer (the fixed analyzer budget of the
framework): the partition, the products of `pl_random_next`, the batch run, its
row helpers and its part helpers, and the six parts of `pl-kernel`. For the same
reason the test predicates are straight-line code and the test loops collect
their checks into one result per iteration.

## Ownership and lifetimes

Every input, output, scratch, statistics, trace and result array is
caller-owned and borrowed for one call. No function keeps a pointer after it
returns, allocates memory or has global state, except `pl-kernel`, which owns
static buffers (section "pl-kernel command line"). During a pooled
`pl_batch_run`, the pool tasks read the input and the parameters (shared,
immutable for the call) and each task writes only the output positions of its
own chunk and its own per-chunk slots (wall time, defect flag, counter rows).
`sc_parallel_run` returns only after every task has ended, so no task touches
caller memory after the return. The caller must not change or free any
argument during the call and must not share the output, the scratch or the
statistics with another thread during the call.

## Batch

```c
enum pl_input_kind { PL_INPUT_ROWS = 0, PL_INPUT_WIRE = 1, PL_INPUT_COLUMNS = 2 };
struct pl_input { int kind; size_t base; size_t n; const struct pl_row *rows;
                  const uint8_t *wire; const double *columns[8]; };
enum pl_output_kind { PL_OUTPUT_RESULTS = 0, PL_OUTPUT_WIRE = 1 };
struct pl_output { int kind; size_t base; struct pl_contract_result *results; uint8_t *wire; };
struct pl_batch_scratch { uint32_t *perm; uint8_t *mark; uint32_t *indices; size_t cap; };
struct pl_batch_stats { size_t chunks; size_t chunk_sizes[PL_MAX_CHUNKS];
                        uint64_t chunk_wall_ns[PL_MAX_CHUNKS]; unsigned threads_observed;
                        size_t max_inflight; uint64_t calls[PL_MODELS]; uint64_t evals[PL_MODELS]; };
enum pl_batch_error { PL_BATCH_OK = 0, PL_BATCH_ARGUMENT = 1, PL_BATCH_DEFECT = 2, PL_BATCH_POOL = 3 };
```

Input and output positions: row i of a request (0 ≤ i < n) is input position
`in->base + i` and output position `out->base + i`.

| Function | Inputs and limits | Output | Failure |
|---|---|---|---|
| `pl_input_row(in, i, out)` | `in` valid for the kind (checked by `pl_batch_run`), i < `in->n` | `*out` = row `in->base + i`: `PL_INPUT_ROWS` copies `rows[base + i]`; `PL_INPUT_WIRE` decodes the 64-byte record at `wire + 64·(base + i)` (`pl_request_decode`); `PL_INPUT_COLUMNS` reads `columns[c][base + i]` in the order side, S, K, T, bid, ask, r, q, and the side value decodes like the wire side (0.0 → 0, 1.0 → 1, any other value, NaN included, → −1) | a `NULL` argument or an unknown kind: `*out` (when not `NULL`) gets side −1 and NaN fields |
| `pl_output_store(out, i, r)` | `out` valid for the kind | `PL_OUTPUT_RESULTS`: `results[base + i] = *r`; `PL_OUTPUT_WIRE`: the 290-byte record at `wire + 290·(base + i)` (`pl_response_encode`) | a `NULL` argument or an unknown kind: no write |
| `pl_evaluate_contract(row, p, models, out, calls, evals)` | `models` 1–31 | first every part of `*out` gets the `NOT_REQUESTED` content (`pl_result_not_requested`); then the selected models in `MODELS5` order (bsm, bjs, crr, baw, alo): `calls[m] += 1`, `pl_evaluate(row, m, p, &out->model[m], &e)`, `evals[m] += e`; returns `PL_EVAL_OK` | `PL_EVAL_DEFECT` at the first defect of a selected model (the later selected models are not evaluated; their parts keep the `NOT_REQUESTED` content); `PL_EVAL_DEFECT` and no write for a `NULL` argument or `models` outside 1–31. `pl_evaluate` is never called for an unselected model |
| `pl_evaluate_contract_echo(models, out)` | any `models` | each selected part (bit set in `models & 31`): status 255 (`PL_ECHO`), flags 0, seven NaN values (`pl_nan()`); each unselected part: the `NOT_REQUESTED` content (G4.6) | `NULL` `out`: no write |
| `pl_poison_results(r, n)` | `r` holds n results | every part of every result gets status 254, flags 0 and seven `0x7FF8000000000000` values: the `NOT_REQUESTED` content | `r` `NULL`: no write |
| `pl_batch_run(in, p, echo, models, threads, request_index, scratch, out, stats, trace)` | one request; see the checks below | `PL_BATCH_OK`; every output position `out->base + i`, i < n, holds the contract result of row i | `PL_BATCH_ARGUMENT` (no write to `out`, `stats` or `trace`), `PL_BATCH_DEFECT`, `PL_BATCH_POOL` |

`pl_batch_run` argument checks, in this order (any failure gives
`PL_BATCH_ARGUMENT` before any write):

1. `in`, `p`, `out` and `stats` are not `NULL` (`p` is required also when
   `echo` is set).
2. `models` is in 1–31.
3. `in->n` ≤ `PL_REQUEST_LIMIT` (14,336).
4. `threads` ≤ 4 (`PL_MAX_WORKERS`).
5. `in->kind` is one of the three kinds and its data pointer is not `NULL`
   (`rows`, `wire`, or all eight `columns`); `out->kind` is one of the two
   kinds and its data pointer is not `NULL` (`results` or `wire`).
6. `in->base` and `out->base` are at most `SIZE_MAX / 290 − n`, so that
   every byte offset `290·(base + i)` is representable.
7. `stats->chunks` ≤ `PL_MAX_CHUNKS` (8).
8. When `threads` ≥ 1: `scratch` and its three arrays are not `NULL`,
   `scratch->cap` ≥ n, and `stats->chunks` + w ≤ `PL_MAX_CHUNKS` with
   w = min(`threads`, n). The scratch is not read when `threads` is 0.

Behavior:

- `echo` nonzero: each row gets `pl_evaluate_contract_echo(models)`; no model
  is evaluated, `p` is not read, and every mask 1–31 succeeds (also a mask with
  a model that is not wired). `echo` 0: each row gets `pl_evaluate_contract`.
- `threads` 0, the serial loop: rows 0 … n − 1 in order; the counters are added
  directly to `stats->calls` and `stats->evals`. At the first defect the run
  stops and returns `PL_BATCH_DEFECT`; the rows before it are stored, the
  defect row and the later rows are not. `stats->chunks`,
  `threads_observed` and `max_inflight` are unchanged.
- `threads` 1–4, the pooled run: n = 0 returns `PL_BATCH_OK` with no task and
  no change. Otherwise `pl_request_chunks(n, threads, request_index, ...)`
  gives w = min(`threads`, n) chunks (Amendment E: one chunk per worker; sorted
  request-local indices). `sc_parallel_run` runs one task per chunk with
  `ScParallelConfig {threads, 2·threads}` (window `max_inflight` = 2·workers).
  Task k evaluates the rows of chunk k in ascending order, writes only their
  output positions, adds its counters to its own counter row k, measures its
  own wall time with `CLOCK_MONOTONIC` (`pl_clock_ns`) into its own slot k, and
  at a defect sets its own defect flag k and returns `FALSE` without a
  `GError`; the adapter records the failure under its own lock ("task failed
  without an error") and skips the tasks that have not started. No pool thread
  creates a `GError`: two concurrent `sc_parallel_set_task_error` calls race
  inside GLib's error-domain lock initialization under `tsan`
  (P2-T14-TSAN-01). After `sc_parallel_run` returns, `pl_batch_run` adds
  the counter rows into `stats->calls` and `stats->evals`, appends the chunk
  sizes and wall times at `stats->chunks` (a second request continues after
  the first), raises `threads_observed` and `max_inflight` to the adapter's
  observed values when they are larger, and frees the `GError`
  (`g_clear_error`). A set defect flag gives `PL_BATCH_DEFECT`; any other
  adapter failure gives `PL_BATCH_POOL`. The statistics are appended also on
  a failure (the wall time of a chunk that did not finish is 0). No shared
  counter and no atomic operation exists.
- `trace` (nullable): passed to the adapter as `ScParallelReport.trace` in the
  pooled run; it receives one entry per submitted task (up to its capacity).
  The serial loop does not touch it.
- Model mask (Amendment G item G1, ruling 46): only the selected models are
  computed, in the serial loop and in every pooled task; each unselected part
  holds the `NOT_REQUESTED` content. A mask with a bit outside
  `PL_MASK_WIRED` (bit 16 until Task 10b) gives `PL_BATCH_DEFECT` (the ALO
  stub of `pl_evaluate`), also when every row stops before the engine.
  Exception: an echo run (`echo` = 1) evaluates no model, so a mask with an
  unwired bit (for example 31) returns `PL_BATCH_OK` with the echo content in
  every selected part. An echo run makes no digest, and `pl-kernel --echo
  --canonical` is refused (section "Echo"), so no echo result reaches a
  canonical file.
- Counters (G4.8, ruling 31): `stats->calls[m]` counts the calls of
  `pl_evaluate` for model m and `stats->evals[m]` the sum of its
  `engine_evals`. Both stay 0 for every unselected model. They are
  caller-owned fields; the counters cost two additions per evaluation in every
  build (no test-only build exists in project mode).
- The output of a pooled run is byte-identical to the serial output for every
  worker count, input kind and request index: each row's result depends only
  on the row, the parameters and the mask.

A poisoned *selected* part (status 254) is rejected by `pl_response_decode` and
`pl_canonical_write`, so a row that a run skipped stays detectable.

## Reduction

```c
struct pl_reduction { uint16_t models; uint64_t counts[PL_MODELS][9];
                      double max_iv[PL_MODELS]; int64_t max_iv_index[PL_MODELS]; };
void pl_reduce(const struct pl_contract_result *r, size_t n, uint16_t models,
               struct pl_reduction *red);
```

`reference.reduction` (reference.py:279-297, spec 3.2) for each selected model
of `models & 31` only (G1.5): `counts[m][s]` counts the rows with status s
(0–8; a status outside 0–8, such as 255 of an echo run, is not counted);
`max_iv_index[m]` is the lowest index of an OK row with the largest IV (a
later row replaces the best only when its IV is strictly greater) and
`max_iv[m]` its IV; with no OK row, `max_iv_index[m]` is −1 and `max_iv[m]`
NaN. `red->models` = `models & 31`. Every entry of an unselected model is 0
(and is never printed). `red` `NULL`: no write; `r` `NULL` counts as n = 0.

## Echo

The echo kernel (G4.6, `pl-kernel --echo`) writes status 255, flags 0 and
seven NaN values in each selected part and the `NOT_REQUESTED` content in each
unselected part. It evaluates no model, so its counters stay 0. The canonical
writer refuses status 255, so `pl-kernel --echo --canonical PATH` fails closed:
a usage error (exit 2, `reason=usage`), and nothing is written to PATH
(controller ruling (c), 2026-10-11).

## Record-scan

```c
#define PL_SCAN_RECORD_BYTES 49u
struct pl_scan_totals { uint64_t count; int64_t open_interest; uint64_t records; };
int pl_scan(const uint8_t *packed, size_t len, int64_t dte_min, int64_t dte_max, double lo,
            double hi, struct pl_scan_totals *out);
```

A transliteration of `benchlab.recordscan` `whole_days`, `_keep` and
`scan_reference` (recordscan.py:23-39). Record (49 bytes, little-endian,
`<Bdddddq`): side u8 at 0, S at 1, K at 9, T at 17, bid at 25, ask at 33,
binary64; open interest i64 at 41 (−1 when missing). A record is kept when
oi ≥ 0, S > 0.0, T is finite, days = T·365.0 + 0.5 is finite, dte_min ≤
floor(days) ≤ dte_max (an exact comparison of the integral double with the
int64 bounds; a value outside the int64 range is outside every window) and
lo ≤ K/S ≤ hi (IEEE binary64; a NaN fails). `count` counts the kept records,
`open_interest` sums their oi with `__builtin_add_overflow`, `records` counts
all records. Returns 0 and writes `*out`; −1 (no write) when `len` is not a
multiple of 49, `out` is `NULL` or `packed` is `NULL` with `len` > 0; −2 (no
write) when the sum overflows int64. Pure; reads `len` bytes of `packed`.

## pl-kernel command line

```c
int pl_kernel_main(int argc, char **argv, FILE *out, FILE *err);
```

Inputs: `argc` any `int`; `argv` borrowed, may be `NULL`; when `argc` ≥ 1 and
`argv` is not `NULL`, `argv` holds `argc` readable pointers, any of which may
be `NULL` (a `NULL` argument is a usage error); each non-`NULL` argument is a
NUL-terminated text. `out` and `err` are borrowed, open, writable streams; the
function never closes them. `pl_kernel_main` uses static buffers, so only one
call may run at a time (one call per process in `pl-kernel`).

Modes (`argv[0]` is the program name and is not read):

| Arguments | Behavior |
|---|---|
| exactly `--self-check` | the self-check (below); `PLK1 status=OK self_check=4` |
| exactly `--print-params` | `PLPARAMS crr_steps=100 alo_scheme=accurateScheme l=25 m=5 n=13 eps=0x1.5798ee2308c3ap-27 fp_equation=Auto` (I5.8: `crr_steps` from `pl_case_params`; the `alo_scheme` values of spec I2.2, eps = 1e-8 printed with `%a`) |
| run options (below) | one run of a case |

Run options; each at most once, in any order:

| Option | Value | Cases |
|---|---|---|
| `--case C` | `option-chain-greeks`, `record-scan` or `probe`; required | all |
| `--input PATH` | required | all |
| `--records N` | 1–20,000; required | all |
| `--loops L` | 1–1,000,000; default 1 | all |
| `--threads T` | 0–4; default 0 | option case; record-scan and probe accept only 0 |
| `--echo` | none | option case |
| `--models MASK` | 1–31; default 7 | option case |
| `--output PATH` | none | option case (290-byte records of the last loop), probe (64-byte records of the last loop) |
| `--canonical PATH` | none | option case (`ocg-v1` bytes for mask 7, `ocg-v1m` for every other mask, of the last loop); a usage error together with `--echo` |
| `--trace PATH` | none | option case |
| `--handshake` | none | all |
| `--dte-min D`, `--dte-max D`, `--moneyness-lo X`, `--moneyness-hi X` | D: int64 decimal (an optional leading `-`); X: a finite binary64 (`strtod`, the whole text); all four required | record-scan |

An unsigned value is one to seven decimal digits without a sign. Any other
argument list (an unknown option, a missing or repeated option, a missing
value, a value outside its range, an option of another case) is a usage error.

Input (`--input`): the file holds packed records from its start: 64-byte
request records (option case), 49-byte record-scan records, or 72-byte probe
records (nine binary64: model, side, S, K, T, r, q, σ, zero). The kernel reads
exactly N records (`pl_read_exact`); a longer file is read only up to N
records (a run with `--records` below the planned rows does less work and is
detected by the bench as incomplete). `copied_bytes` is the byte count read.
A probe record needs a model value of exactly 0.0, 1.0, 2.0, 3.0 or 4.0 and a
zero field with the bits 0.

Run: with `--handshake`, the kernel flushes `out`, writes the byte `B` to fd
1 and reads one byte, which must be `G`, from fd 0, before the timed loops,
and writes `E` and reads `F` after them. The clocks (`pl_clock_ns`,
`CLOCK_MONOTONIC` and `CLOCK_PROCESS_CPUTIME_ID`) are read before the first
and after the last loop. Each loop:

- option case: `pl_poison_results` over the N results, then the statistics
  are reset, then the requests r = 0, 1 (N above 14,336 gives two requests:
  rows [0, 14,336) and [14,336, N), Amendment E) run through `pl_batch_run`
  with the wire input, base r·14,336 and request index r;
- record-scan: `pl_scan` over the N records;
- probe: each record through `pl_price_and_greeks` with the case parameters:
  output record u32 status (0 `PL_GREEKS_OK`, 1 `PL_GREEKS_DOMAIN`, 2
  `PL_GREEKS_DEFECT`), u32 rounding band (0 or 1), seven binary64.

After the loops, the output files are written in the order `--output`,
`--canonical`, `--trace` (`open` with `O_WRONLY | O_CREAT | O_TRUNC`, mode
0644). Trace file: the line `# workers=W threads=N max_inflight=M submitted=S
executed=E` (W the observed pool threads, N `--threads`, M the observed
largest window, S the submitted tasks, E the executed tasks) and one line
`<tag> <start_ns> <end_ns> <index> <cpu_ns>` per task of the last loop
(`index` counts the chunks of the loop from 0; tag 4294967295 and −1 times
for a task that did not run). With `--threads 0` the trace has the header
line only.

Last stdout line on success:

`PLK1 status=OK case=<case> records=<n> loops=<L> threads=<T> mono_ns=<u64> cpu_ns=<u64> chunks=<k> chunk_sizes=<a,b,...> chunk_wall_ns=<a,b,...> copied_bytes=<u64>`
followed by
- option case: ` models=<mask> evals=<model>:<u64>,... red=<part>;<part>... digest=<16 hex|none>`:
  `evals=` lists the engine evaluations of the last loop of each selected
  model in `MODELS5` order; `red=` holds exactly one part per selected model
  in `MODELS5` order, each `<model>:<c0>,...,<c8>:<16 hex|null>:<index>` (the
  status counts, the big-endian bits of `max_iv` as 16 lowercase hex digits or
  `null`, and `max_iv_index`, −1 with `null`); an unselected model is absent;
  `digest=` is the kernel digest below;
- record-scan: ` count=<u64> open_interest=<i64>`;
- probe: ` probe_records=<n>`.

`chunks`, `chunk_sizes` and `chunk_wall_ns` describe the last loop (`chunks=0`
and empty lists for the serial loop, the record-scan and the probe).

Kernel digest (EX-10, ruling R43 item d): after the loops and the output
files, pl-kernel writes the canonical bytes of the last loop's results for the
`--models` mask (`pl_canonical_write`, ocg-v1 for mask 7, ocg-v1m otherwise;
protocol.md "Canonical form") into a digest sink (protocol.md "Sink": no byte
kept) and prints `digest=` with the FNV-1a 64 of those bytes as 16 lowercase
hex digits, or `digest=none` when the writer refuses the results (the echo
status 255 of `--echo`, a selected status outside 0-8, an infinity). The
digest is outside the timed loops and does not depend on `--canonical`. The
bench framework marks a kernel row eligible only when this value equals the
example adapter's `native_reference_digest(reference)`
(optionlab.native_codec.canonical_digest: the same FNV-1a 64 over the
`optionlab.reference.canonical_result` bytes of the selected reference
models), so a kernel row passes only with the reference bytes bit for bit.
Shared vector: the 801 bytes of `cvectors.canonical_case()` for mask 7 give
0xb15cff783c8bac90 and the empty mask-7 document gives 0x528a621ba8b587ff
(tests/project/test_canonical.c and tests/test_light_native_codec.py).

Exit codes and failure lines (on `out`, `PLK1 status=FAIL reason=<reason>`):

| Exit | Reason | Cause |
|---|---|---|
| 0 | | success |
| 2 | `usage` | usage error; `err` also gets one usage line |
| 2 | `input` | the input file cannot be opened or read, holds fewer than N records, or holds an invalid probe record |
| 3 | `kernel` | `pl_batch_run` fails (a run defect, for example a mask with a model that is not wired), a clock fails, the canonical writer refuses the results, or the self-check fails |
| 4 | `io` | the handshake fails, an output file cannot be opened, written or closed, or `out` cannot be written or flushed |

Partial files: pl-kernel does not remove a file that it created. An I/O
failure (exit 4) while it writes the `--output`, `--canonical` or `--trace`
file can leave a partial file at that path; a caller treats every output file
of a run that did not exit 0 as invalid. (Fix round 1 of Task 14, review M-5:
documented instead of a removal on failure, because a removal is a second
I/O operation that can fail too and would need its own failure tests.)

Static buffers (one set per process): input 1,440,000 bytes (20,000 records
of the largest record, 72 bytes; the option case uses 1,280,000 bytes),
20,000 contract results, 20,000 probe output records, the partition scratch
for 14,336 rows, 8 trace entries and an output write buffer of 64 records.

Self-check (`PLK1 status=OK self_check=4` and exit 0 when all four pass; exit
3 with `reason=kernel` otherwise):

1. Partition known answers: the first three SplitMix64 outputs from
   `PL_PARTITION_SEED`, P(10, r = 0) and the chunks of m = 10, w = 4, r = 0.
2. One embedded synthetic row (row 0 of `PL_VEC_EVALUATE`, model bsm): status,
   flags, engine evaluations and the seven result bits equal constants copied
   from the vector.
3. Eight embedded rows (rows 0-7 of `PL_VEC_EVALUATE`): the serial and the
   two-worker wire outputs with mask `PL_MASK_WIRED` are byte-identical.
4. One row per wired model: the embedded row with each one-model mask of
   `PL_MASK_WIRED` (1, 2, 4, 8; 16 after Task 10b) gives that model's part of
   its `PL_MASK_WIRED` result bit for bit and the `NOT_REQUESTED` content in
   the other four parts.

The project run entry is `pl-kernel --self-check` with expected exit code 0.

## Partition

Spec Amendment E item 1. The C partition must give the same index sets as
`benchlab.pools` (`SplitMix64`, `permutation`, `chunk_bounds`,
`request_chunks`) for every request, worker count and row count (Amendment E
item 3). A threaded C route would use it; the example declares no threaded
row (owner 2026-10-16: single-threaded rows only). The code is original to
this project (not a QuantLib transcription).

Constants: `PL_PARTITION_SEED` = `0x5AFEC0DE20261007`, `PL_REQUEST_LIMIT` =
14,336 records per request (Amendment I item I5.5, Task 12b; one value for every
route, the C worker, the framework transport, the Python pools and this partition),
`PL_MAX_WORKERS` = 4, `PL_MAX_CHUNKS` = 8 (two requests of at most four chunks each,
for at most 20,000 input records).

### Functions

| Function | Inputs and limits | Output | Failure |
|---|---|---|---|
| `pl_random_init(g, state)` | `g` writable; `NULL` is ignored | state, no script, counters 0 | none |
| `pl_random_next(g)` | `g` initialized; `NULL` gives 0 | SplitMix64 output (increment `0x9E3779B97F4A7C15`, multipliers `0xBF58476D1CE4E5B9`, `0x94D049BB133111EB`, shifts 30, 27, 31, all modulo 2^64), or the next scripted value | exhausted script: `script_overrun = 1`, returns 0 |
| `pl_mul_64(a, b, hi, lo)` | any `a`, `b`; `hi`, `lo` writable | exact a·b = hi·2^64 + lo from four 32×32 products | a `NULL` output: writes nothing |
| `pl_add_64(a, b)` | any | (a + b) mod 2^64, with no unsigned wrap in C | none |
| `pl_random_bounded(g, t, out)` | t in [1, 2^32] | 0, `*out` = ⌊x·t / 2^64⌋ after Lemire rejection | −1, `*out` unchanged: t outside [1, 2^32], `g` or `out` `NULL`, the script runs out |
| `pl_permutation(m, r, perm, cap)` | m ≤ cap, m ≤ 14,336; `perm` holds `cap` elements | 0, `perm[0 .. m-1]` = P of request r | −1, nothing written: m > cap, m > 14,336, `perm` `NULL` with m > 0 |
| `pl_request_chunks(m, workers, r, perm, mark, indices, cap, chunks, chunk_count)` | workers in [1, 4]; m ≤ cap, m ≤ 14,336; `perm`, `indices` hold `cap` `uint32_t`, `mark` holds `cap` bytes, `chunks` holds 4 elements | 0; w = min(workers, m) chunks; m = 0 gives `*chunk_count = 0` | −1, nothing written: workers outside [1, 4] (checked first, as `chunk_bounds`), any `NULL` pointer, m > cap, m > 14,336 |
| `pl_request_count(n)` | any n | ⌈n / 14,336⌉ | none |
| `pl_fnv1a64_u32(h, v)` | any | FNV-1a 64 of h over the four little-endian bytes of v (prime `0x100000001b3`; start value `0xcbf29ce484222325`) | none |

Rules (Amendment E item 1):

- Bounded draw: x = next(); p = x·t; l = p mod 2^64; if l < t, then with
  threshold = (2^64 − t) mod t (in `uint64_t` arithmetic
  `(UINT64_MAX − t + 1) % t`, which does not wrap for t ≥ 1),
  while l < threshold: x = next(), p = x·t, l = p mod 2^64. The result is
  ⌊p / 2^64⌋ < t, because x < 2^64. Without a script the loop ends: a
  rejection needs l < threshold < t ≤ 2^32, and the SplitMix64 outputs over
  one period are all 2^64 values.
- Permutation: P = [0, …, m − 1]; for i = m − 1 down to 1: j = bounded(i + 1),
  swap P[i] and P[j]. The state starts at (`PL_PARTITION_SEED` + r) mod 2^64.
- Chunks: chunk k (0 ≤ k < w) holds P[⌊k·m/w⌋ .. ⌊(k+1)·m/w⌋ − 1], sorted
  ascending. `chunks[k].offset` = ⌊k·m/w⌋ and `chunks[k].count` =
  ⌊(k+1)·m/w⌋ − ⌊k·m/w⌋; the indices are `indices[offset .. offset + count − 1]`.
  The sort is O(m): `mark[P[p]]` = k for each position p of chunk k, then one
  ascending scan over i = 0 … m − 1 appends i to the chunk `mark[i]`.
- Arithmetic modulo 2^64 never wraps in C (the `integer` sanitizer profile
  rejects an unsigned wrap): sums use `pl_add_64`, products the low word of
  `pl_mul_64`.
- Size arithmetic: k ≤ 4 and m ≤ 14,336, so k·m ≤ 57,344 cannot overflow;
  every position written is below m ≤ cap (P is a permutation of 0 … m − 1,
  j < i + 1 ≤ m, and the chunk fill positions stay inside their chunk).
- Recombination (scatter back): the caller writes the result of local index
  `indices[offset + j]` of request [a, b) to absolute position a + that index,
  so the output order equals the direct run (Task 14 applies it).
- Scratch layout (controller ruling A41): a caller that carves the scratch of
  m rows from one buffer places `perm` (4·m bytes), then `indices` (4·m
  bytes), then `mark` (m bytes), so each `uint32_t` array starts 4-byte
  aligned for every m (Tasks 14 and 16).

Test hook: a test sets `script` and `script_len` of a `struct pl_random` after
`pl_random_init`. `pl_random_next` then returns the scripted values in order
and counts each call in `calls`. This feeds fixed outputs through the same
Lemire loop (the Phase 1 stub test). Production code never sets `script`.

Ownership: the caller owns every array and the generator; the functions keep
no state and allocate nothing.

Tests (`tests/project/test_partition.c`, vectors from `benchlab.pools`):

- `splitmix`, `spec-splitmix`: the first three outputs from
  `PL_PARTITION_SEED`, generated and as the spec literals.
- `perm0`, `perm1`, `spec-perm0`, `spec-perm1`: P(10) for r = 0 and r = 1;
  `perm-rmax`: P(10) for r = 2^64 − 1 (the seed sum wraps).
- `spec-chunks`, `spec-sizes`, `spec-offsets`: m = 10, w = 4, r = 0.
- `mul`: 113 exact products (all pairs of nine 32-bit-half edge values, then 32
  seeded pairs); `mul-null`; `add`: sums with and without the wrap.
- `rejection`: the Phase 1 stub cases (t = 3 with one and three rejections,
  low < t above the threshold, t = 2^32 with threshold 0), t = 1, t = 2^32
  with output 0 and t = 2^32 − 1 with one rejection; `overrun`: a script that
  runs out; `bounds`: t = 0, 2^32 + 1, `NULL` arguments, nothing written.
- `chunk`, `chunk-index`: the explicit chunk lists of n = 1, 10, 256 and 1,024
  for workers 1, 2 and 4 (request 0).
- `fingerprints`: FNV-1a over the chunk sizes and absolute indices of every
  request for n = 1, 2, 3, 10, 256, 1,024, 13,230, 14,336, 14,337, 16,384 and
  20,000
  and workers 1, 2 and 4 (every size tier and the request-limit sizes).
- `limits`, `perm-limits`, `count`: each refusal (with `*chunk_count`
  unchanged), m = 0, workers > m, m = cap = 14,336, the request counts.
- `request-limit` (Task 12b): `PL_REQUEST_LIMIT` = 14,336; the request counts of
  0, 1, 14,336, 14,337, 16,384, 20,000 and 28,673 (0, 1, 1, 2, 2, 2, 3); the
  permutation and chunk refusal at 14,337 and acceptance at 14,336 (four chunks of
  3,584); the second request of n = 20,000 (offset 14,336, 5,664 rows, four chunks
  of 1,416).
- `extent`: with cap = m, position m of `perm`, `mark` and `indices` is not
  written, and the chunk offsets are the running sums of the counts.

## Tests of the batch, the scan and the command line (Task 14)

`tests/project/test_batch.c`, `test_batch_kinds.c`, `test_batch_echo.c`, `test_batch_masks.c` (groups `masks` and
`trap`) and `test_batch_baw.c` (group `baw-parts`) (48 synthetic rows: the first 48 rows of
`PL_VEC_EVALUATE`, three entries per row, bsm, bjs and crr; the BAW entries
of the same rows are rows 0-47 of `PL_VEC_EVALUATE_BAW`):

- `serial-pooled`: the serial batch equals the vector statuses; the pooled
  batch with 1, 2, 3 and 4 workers is byte-identical to the serial batch, has one
  chunk per worker, chunk sizes that sum to n and a window of at most
  2·workers.
- `input-kinds`: rows, wire and columns give the same wire bytes, serial and
  with two workers; the column side values 0.0, 1.0 and 2.0 decode to 0, 1
  and −1.
- `echo-reduce-arguments`: the echo parts (G4.6); threads 5, models 0 and 32,
  a scratch one row short (refused, nothing written); the reduction totals and
  the empty reduction.
- `tie`: two OK rows with equal IV: `max_iv_index` is the lower index.
- ALO subset (controller ruling R-10b-B1, Task 10b): one ALO run of the 48
  rows takes about 5 s in the coverage build, so the batch tests evaluate
  `PL_TB_MASK_FULL` (every wired model but ALO) on the 48 rows, and the ALO
  part on the 13 rows of `PL_VEC_BATCH_ALO`: the row checks (invalid,
  expired), FP-B put and call, FP-A put and call, the European edge of a put
  and a call, the double boundary, the Brent fallback, `stencil_unresolved`,
  the forward vega and `BELOW_MIN` next to σ_lo. The BSM, BjS, CRR and BAW
  parts keep the full 48 rows; the full-domain ALO proof is the whole vector
  set of `test_alo*.c` and the `alo-agreement` checks.
- `masks`: every mask, serial and two workers: masks 1–15 on the 48 rows
  against the `PL_TB_MASK_FULL` serial results, masks 16–31 on the ALO subset
  against its `PL_MASK_WIRED` serial results (`pl_tb_masks`): each selected
  part bit-identical to the serial result, each unselected part exactly the
  `NOT_REQUESTED` content, `calls` and `evals` 0 for each unselected model and
  equal to the serial values for each selected model; `pl_reduce` fills only
  the selected models. Since `PL_MASK_WIRED` is 31 no mask is unwired (the
  unwired-defect check of Task 14 has no case left).
- `alo-serial`, `alo-pooled`, `alo-reduction`, `alo-input-kinds`,
  `alo-stats`, `alo-one-row`: on the ALO subset under `PL_MASK_WIRED`, each
  ALO part equals its vector entry and the ALO counters equal the vector
  counts; pooled runs with 1–4 workers, the input kinds, the two-request trace,
  request index 1 and one row with two workers give the serial bytes.
- `trap`: the trap row (`RAISE_ROWS[5]`: bsm entry `defect` 0, crr entry
  `defect` 1) succeeds with mask 1 (`calls[2]` 0) and fails with masks 4 and
  7, serial and with two workers.
- `limits` (`test_batch_limits.c`, a file of its own: the analyzer budget): n = 0 (serial and pooled: OK, no chunk), n = 1 (one chunk with 4
  workers), n = 14,336 (echo, 4 workers: four chunks of 3,584) and 14,337
  (refused); threads 0–4 accepted and 5 refused; `stats->chunks` = 8 refused
  for a pooled run and accepted for the serial loop, `stats->chunks` + w = 9
  refused; each `NULL` pointer, unknown kinds and a base beyond the limit
  refused with nothing written; request index 1 (the chunks of request 1).
- `stats`: two requests append their chunks (4 + 4 = 8 entries); the counter
  sums of a serial and a pooled run are equal; the trace holds one entry per
  task.

`tests/project/test_scan.c`: `scan`: six records packed with `pl_store_*`
(dte 6.9 days → 7 kept, 60.5 days → 61 dropped, K/S 0.9 and 1.1 kept at the
band ends, oi −1 skipped, S = 0 skipped, T NaN skipped) and the totals; the
int64 window bounds; `scan-errors`: a length of 48 bytes → −1, a `NULL`
output → −1, two records with oi = `INT64_MAX` → −2 (nothing written), zero
records → all totals 0.

`tests/project/test_kernel_cli.c`, `test_kernel_run.c` and `test_kernel_modes.c`
(three files: the fixed GCC analyzer budget of one translation unit; input files
under the current directory, `pl-kernel-<file>-test-input.bin` and the output
files `pl-kernel-<file>-test-*.bin`, removed at the end with `remove`): the option case with `--threads 0` and
`--threads 2`: equal `--canonical` and `--output` bytes; `--models 1
--canonical` starts with `{"digest_form":"ocg-v1m","mask":1,` and its `PLK1`
line holds `models=1`, `evals=bsm:<n>` only and one `red=` part; `--models 16
--canonical` exits 3 with `PLK1 status=FAIL reason=kernel` while
`PL_MASK_WIRED` lacks bit 16 (after Task 10b: `{"digest_form":"ocg-v1m",
"mask":16,"models":{"alo":` and `evals=alo:<n>` only); 14,337 and 20,000
records with `--echo` (two requests; chunk sizes 7,168, 7,168, 1 and 3,584 ×
4, 1,416 × 4); `--records 20001`, `--threads 5`, `--models 0`, `--models 32`
and the other usage errors → 2; a missing input file and a short input file →
2; `--case probe` on two records; record-scan on 3 records; `--print-params`;
`--self-check` → 0; `--output /proc/forbidden` → 4; `/dev/full` as `out` →
4; the handshake through pipes on fds 0 and 1.
