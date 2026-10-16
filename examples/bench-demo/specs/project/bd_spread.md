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
The module uses the foundation (`"foundation": "glib-parallel"`); no program
and no library of bench-demo links it.

## Files

| File | Contents |
|---|---|
| `include/bd_spread.h` | the limits, the return values and `bd_spread_run` |
| `src/bd_spread.c` | `bd_spread_run` and its task function |

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
