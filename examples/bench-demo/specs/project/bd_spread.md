# Module `bd_spread` specification

Status: example specification for the bench-demo project (framework finding
P2-COV-ATOMIC-01). Write and review this file before any module source
changes. The module is a threaded exercise of the coverage build: its tests
run one hot loop in several worker threads at once. Non-atomic profile
counters can lose updates under threads. This module did not reproduce that
loss at the level of the coverage gate: two runs without the flag gave the
same per-file coverage, because the gate records covered lines and branches,
not counts. The coverage profile of `cmake/Safety.cmake` uses
`-fprofile-update=atomic`, so the counter updates are atomic.
The module uses the foundation (`"foundation": "glib-parallel"`). The
program `bd-spread` links it (framework task EX-13, bench case B04): it runs
one fixed job through the pool with 1, 2 and 4 workers and prints the pool
trace, so that the framework bench check of actual C concurrency
(`native-overlap`) has a real threaded C program. No library of bench-demo
links the module.

## Files

| File | Contents |
|---|---|
| `include/bd_spread.h` | the limits, the return values and `bd_spread_run` |
| `src/bd_spread.c` | `bd_spread_run`, `bd_spread_trace` and the task function |
| `src/bd_spread_cli.c` | `bd_spread_cli_main`, the program logic of `bd-spread` |
| `src/spread_main.c` | `main` of `bd-spread` |

## `bd_spread_run`

`int bd_spread_run(uint64_t seed, uint32_t tasks, uint32_t steps, uint32_t
workers, uint64_t *out, size_t out_len)`

Checks, in this order, before any output word is written. Any failed check
returns 1 `BD_SPREAD_BAD_ARGUMENT`:

| Check | Refused values |
|---|---|
| `out` | `NULL` |
| `tasks` | 0, and 65 (`BD_SPREAD_MAX_TASKS` + 1) to `UINT32_MAX` |
| `steps` | 0, and 1,000,001 (`BD_SPREAD_MAX_STEPS` + 1) to `UINT32_MAX` |
| `workers` | 5 (`BD_SPREAD_MAX_WORKERS` + 1) to `UINT32_MAX` |
| `out_len` | below `tasks` |

On return 0 `BD_SPREAD_OK`, `out[t]` for each task `t` in `[0, tasks)`
holds `D(seed, t, steps)` and no other word of `out` changes. Return 2
`BD_SPREAD_POOL` means that `sc_parallel_run` failed (pool creation or
push); the words of `out` are then unspecified within `[0, tasks)`. A
failure of the pool cannot be caused through the arguments, so no test
reaches return 2.

`workers` 0 runs the tasks in the caller thread, in task order. `workers` 1
to 4 runs them through `sc_parallel_run` with `worker_count` = `workers`
and `max_inflight` = 2 · `workers`. The result is the same for every
`workers` value.

## `bd_spread_trace`

`int bd_spread_trace(uint64_t seed, uint32_t tasks, uint32_t steps, uint32_t
workers, uint64_t *out, size_t out_len, struct bd_spread_span *spans, size_t
span_len, struct bd_spread_report *report)`

The same job as `bd_spread_run`, always through `sc_parallel_run`, with the
pool trace of each task. Checks, in this order, before any output word,
span or report field is written. Any failed check returns 1
`BD_SPREAD_BAD_ARGUMENT`:

| Check | Refused values |
|---|---|
| `out`, `tasks`, `steps`, `out_len` | as for `bd_spread_run` |
| `workers` | 0, and 5 to `UINT32_MAX` (the trace needs the pool) |
| `spans` | `NULL` |
| `span_len` | below `tasks` |
| `report` | `NULL` |

On return 0 `BD_SPREAD_OK`:

- `out[t]` holds `D(seed, t, steps)` for each task `t` in `[0, tasks)`, as
  for `bd_spread_run`; no other word of `out` changes.
- `spans[i]` for `i` in `[0, tasks)` is the trace entry `i` of the pool:
  `thread` (the pool thread tag, `[0, workers)`), `start_ns` and `end_ns`
  (`CLOCK_MONOTONIC` around the task, `start_ns` ≤ `end_ns`), `cpu_ns`
  (`CLOCK_THREAD_CPUTIME_ID` of the pool thread during the task) and `task`
  (the task index, `[0, tasks)`). Each task index appears exactly once. No
  span at `tasks` or later changes.
- `report` holds the pool report: `submitted` and `executed` (both `tasks`),
  `threads` (the distinct pool threads that ran a task, 1 to `workers`) and
  `max_inflight` (the largest number of submitted and not completed tasks,
  at most 2 · `workers`).

Return 2 `BD_SPREAD_POOL` means that `sc_parallel_run` failed, or that its
trace or report is not complete in the sense above (an entry that did not
run, a value out of range, a repeated task index, or a count that differs).
The words of `out` and the spans are then unspecified within `[0, tasks)`,
and the report is unspecified. A pool failure cannot be caused through the
arguments, so no test reaches return 2.

## Program `bd-spread` (`bd_spread_cli_main`)

`int bd_spread_cli_main(int argc, char **argv, FILE *out, FILE *err)`.
`bd-spread` takes no argument and reads no input: `argc` other than 1 (or
`argv` `NULL`) writes `usage: bd-spread` and a newline to `err` and returns
2, with nothing written to `out`.

With `argc` 1 the program runs the fixed job `seed` = 20261015, `tasks` =
64 (`BD_SPREAD_MAX_TASKS`), `steps` = 100,000 (`BD_SPREAD_TRACE_STEPS`):

1. `bd_spread_run` with `workers` 0 (the serial reference). It writes
   `# workers=0 result=R` and a newline, where `R` is the fold of the 64
   output words as 16 lowercase hexadecimal digits.
2. For `workers` 1, 2 and 4, in this order, `bd_spread_trace`. It writes
   one header line `# workers=W threads=T max_inflight=M submitted=S
   executed=E result=R` (decimal numbers; `R` as above) and then one line
   per span in span order: `thread start_ns end_ns task cpu_ns` (decimal,
   separated by one space).

The fold of the words `w0` to `w63`: `h` = 0xcbf29ce484222325; for each
word in order, `h` = (`h` XOR `w`) · 0x100000001b3 modulo 2^64.

The output is 4 header lines and 3 · 64 span lines. The result `R` is the
same in all four header lines. The return value is 0 after every line is
written and `out` is flushed; 3 when `bd_spread_run` or `bd_spread_trace`
does not return 0 (after a line `# status=FAIL` on `out`); 4 when a write
or the flush fails. Timing values differ from run to run; the result does
not.

## The task digest `D(seed, t, steps)`

All arithmetic is modulo 2^64 on `uint64_t`.

1. `state` = `seed` XOR (`t` · 0x9e3779b97f4a7c15). If `state` is 0, it
   becomes 0x9e3779b97f4a7c15 (xorshift64 has no zero state).
2. `hash` = 0xcbf29ce484222325 (the FNV-1a offset basis).
3. For each step `s` in `[0, steps)`: `state` ^= `state` << 13, `state` ^=
   `state` >> 7, `state` ^= `state` << 17. If `s` is not the last step,
   `hash` = (`hash` XOR `state`) · 0x100000001b3. On the last step, `hash`
   = (`hash` XOR `state` XOR `t`) · 0x100000001b3.
4. `D` = `hash`.

The last-step branch runs once per task, while the other branch runs on
every other step. Its coverage count is derived from the two hot counters
(loop body minus the other branch), so a lost counter update changes it;
with atomic counters it is exactly `tasks` per run.

## Ownership, lifetimes and concurrency

- `out` is borrowed for the call only; the caller keeps it alive and
  unchanged by others until the call returns.
- The job (seed, steps, out) is read-only for the tasks. Each task writes
  only its own word `out[t]`. No task survives the return of
  `bd_spread_run` (`sc_parallel_run` contract).
- No task sets a `GError` (a pool thread never touches the GLib error
  domain). The caller-side `GError` of `sc_parallel_run` is cleared before
  the return.
- No global mutable state, no I/O. Under the default glib-fail-stop
  allocation contract, an allocation failure of the pool stops the process.

## Tests of the trace and the program (`tests/project/test_bd_spread_trace.c`, `tests/project/test_bd_spread_cli.c`)

- Every refused value of `bd_spread_trace` at its bound (`workers` 0, 5 and
  `UINT32_MAX`; `spans` `NULL`; `span_len` `tasks` − 1 and 0; `report`
  `NULL`; `out` `NULL`; `tasks` 0 and 65; `steps` 0 and 1,000,001; `out_len`
  `tasks` − 1) leaves `out`, the spans and the report unchanged.
- One task and 64 tasks on 1, 2 and 4 workers: `out` equals the serial run,
  the extra word and the extra span stay unchanged, every task index
  appears once, every thread tag is below `workers`, `start_ns` ≤ `end_ns`,
  `submitted` = `executed` = `tasks`, `threads` in `[1, workers]` and
  `max_inflight` in `[1, 2 · workers]`.
- Second file (the fixed GCC analyzer budget of one translation unit):
  `bd_spread_cli_main` with `argc` 0 and 2 and with `argv` `NULL` returns 2
  and writes nothing to `out`; with `argc` 1 it returns 0 and writes 196
  lines: 4 header lines that carry the same `result=` text and 192 span
  lines; with an `out` that refuses writes it returns 4.

## Tests (`tests/project/test_bd_spread.c`, `tests/project/test_bd_spread_threads.c`)

Derived from the checks above.

- First file: every refused value at its bound (`tasks` 0, 65 and
  `UINT32_MAX`; `steps` 0, 1,000,001 and `UINT32_MAX`; `workers` 5 and
  `UINT32_MAX`; `out` `NULL`; `out_len` `tasks` − 1 and 0) leaves `out`
  unchanged; one task and 64 tasks, one step, the zero-state seed and the
  largest seed against digests of an independent model of the steps above
  (written apart from the source and kept as constants in the test; one
  case on 2 workers and one on 4); `out_len` larger than `tasks` leaves the extra words
  unchanged; `out_len` equal to `tasks` writes no further word.
- Second file: the same result for `workers` 1 to 4 as for `workers` 0
  (one task, the zero-state seed, 64 tasks), 1,000,000 steps on 2 workers,
  and the hot threaded run (64 tasks of 20,000 steps on 4 workers, twice)
  against the serial run. The size keeps the coverage build (atomic,
  contended counters) inside the 10-second test budget.
- Two files and constant digests: the fixed GCC analyzer budget of one
  translation unit. A model loop in the first file exceeds it.

REQUIRE stays active under NDEBUG.
