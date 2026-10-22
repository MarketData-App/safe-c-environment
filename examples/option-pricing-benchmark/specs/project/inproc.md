# Module `inproc` specification

Status: Phase 2 Task 16 as adapted by EX-9 (the standalone example). The in-process entry point
`libpl_inproc.so`, ABI 2 (Amendment G items G4.4 and G13.3, Amendment I item I5.7). A Python
caller loads the library with `ctypes.CDLL` and passes borrowed buffers; the module prices them
with the batch (specs/project/batch.md) and keeps nothing. Write and review this file before any
module source changes.

**Safety label (Amendment F item 10):** in-process shared library: native code shares the
interpreter address space; a C defect can corrupt the interpreter.

## Files

| File | Contents |
|---|---|
| `include/pl_inproc.h` | the ABI 2 declarations (no GLib) |
| `src/pl_inproc.c` | `pl_inproc_abi_version`, `pl_inproc_out_len`, `pl_inproc_scratch_len`, `pl_inproc_price`, `pl_inproc_price_stats` |
| `src/pl_inproc_args.c` | `pl_inproc_check` (the argument contract; its own translation unit for the GCC analyzer budget) |
| `include/pl_test_inproc.h` | test helpers (static columns, buffers, sentinels, the reference run); no source includes it |
| `tests/project/test_inproc.c` | groups `abi`, `same-bytes`, `arguments`, `checks`, `defect`, `echo`, `in-place`, `masks`, `reentrant` and `stats` (threads 0, 1, 2 and 4; the stats group has four plain copies, one per threads value, and every other group one function) |
| `fuzz/project/inproc_fuzz.c` | the fuzz target `inproc` |
| `fuzz/project/corpus/inproc/` | generated seeds (`optionlab.cvectors.corpus_files`, entries named `inproc-<name>`) |
| `fuzz/project/regressions/inproc/` | fuzz regression inputs |

The in-process test is one translation unit. Two framework limits decide it (EX-9): the AST dump
of each project translation unit stays in the fixed 2 GiB `/work` space of the project container,
so the example has room for only a few more units; and the GCC analyzer budget counts a helper
function again at each call, so a repeated test step is a loop over a table or a plain copy. The AST policy also refuses
array subscripts and `memset`/`memcpy` in project code: an element is read as `*(p + i)` and a
buffer is cleared or copied by struct assignment.

Uses: module `batch` (and through it `models`, `protocol` and the `glib-parallel` foundation).
`reads_external_input` is true: the entry reads caller memory. The library `pl_inproc` is built
from this module and its `uses` closure; its exports are exactly `pl_inproc_abi_version` and
`pl_inproc_price` (the hardened gate checks them; no `Py` symbol).

## ABI 2

`pl_inproc_abi_version()` returns 2 (`PL_INPROC_ABI`). The Amendment G form of ABI 2 (232-byte
records, models at most 15, n at most 16,384) was never built, so ABI 2 has only this meaning.

`pl_inproc_price(side, S, K, T, bid, ask, r, q, n, threads, request_index, models, out, out_len,
scratch, scratch_len)` has 16 arguments; `models` follows `request_index`. Return codes:
`PL_INPROC_OK` 0, `PL_INPROC_ARGUMENT` 1, `PL_INPROC_DEFECT` 2, `PL_INPROC_POOL` 3.

* The eight columns are `const double *`, n values each, in place (never copied by the caller or
  by the module). A `side` value 0.0 is a call, 1.0 a put, any other value an invalid row
  (protocol.md `pl_request_decode`; optionlab.contract side code 0 = call).
* `out` holds `out_len = pl_inproc_out_len(n, threads)` bytes: n records of 290 bytes (the wire
  records of protocol.md for the mask `models`), then the trailer of 4 + 16 k bytes
  (k = 0 for threads 0, else min(threads, n)). The largest value is 4,157,508 (n = 14,336,
  threads 4).
* `scratch` holds `scratch_len = 9 n + 64` bytes (largest 129,088; `pl_inproc_scratch_len`
  saturates at `SIZE_MAX` for n above (SIZE_MAX - 64) / 9, like `pl_inproc_out_len`, and a call with
  such an n is refused by the n check): the partition scratch, then a
  64-byte argument echo. The partition scratch follows controller ruling A41 (partition.h): perm
  (4 n bytes) first, indices (4 n bytes), then mark (n bytes), so that every uint32 array is
  4-byte aligned for every n.
* `request_index` is the partition request index of the batch (batch.md "Partition").
* The echo: after a successful call the eight column addresses it received are stored as u64
  little-endian in the last 64 bytes of `scratch` (Amendment F item 10 (c)); after a refused call
  those bytes are unchanged.

### Argument contract (`pl_inproc_check`)

`PL_INPROC_ARGUMENT` is returned, before the first read through any pointer and before the first
write, for each of:

1. a NULL column, `out` or `scratch`;
2. a column, `out` or `scratch` address that is not a multiple of 8 (`(uintptr_t)p % 8u`);
3. n outside 1-14,336;
4. threads above 4;
5. models 0 or above 31 (the domain of `models` is the u32 argument; `PL_MASK_WIRED` is 31, so the
   masks 16 and 31 are identity checks and every mask of 32 and above is refused);
6. `out_len` other than `pl_inproc_out_len(n, threads)`;
7. `scratch_len` other than `9 n + 64`;
8. any overlap between `out`, `scratch` and a column range (a column range is
   `[p, p + 8 n)`; address intervals are compared as `uintptr_t` with overflow-checked ends, and
   an interval whose end wraps is an overlap). Two columns may overlap each other: they are read
   only.

Otherwise `PL_INPROC_OK`. After the check, one batch runs over the columns
(`pl_batch_run_untraced` with `PL_INPUT_COLUMNS` and `PL_OUTPUT_WIRE`, echo off) and the trailer
is encoded after the records. The result of the batch maps one to one (`PL_BATCH_DEFECT` is
`PL_INPROC_DEFECT`, `PL_BATCH_POOL` is `PL_INPROC_POOL`); a chunk count that differs from k is
`PL_INPROC_DEFECT`.

### Failure behavior of `out` and `scratch`

After `PL_INPROC_ARGUMENT` nothing is written (out, scratch and the echo are unchanged). After
`PL_INPROC_DEFECT` or `PL_INPROC_POOL` (the batch ran): `out` holds the records of the rows that
were stored before the failure (a serial run stores rows in order and stops at the first defect;
a pooled run stores each chunk's rows until that chunk fails, so any subset), the other bytes of
the record area are unchanged, the trailer is not written, `scratch` holds the partition scratch
(perm, indices, mark; unchanged for threads 0) and the 64-byte echo at its end is not written.
The caller must treat the contents of `out` as unspecified after a nonzero return. Test: group
`defect` (a CRR run-defect row, serial and pooled).

## Ownership, lifetime and threads

* Every pointer is borrowed for the duration of the call only. Nothing is retained, there is no
  static mutable state and no allocation; two calls with different buffers may run in any order.
* Python and the GIL: the caller's `ctypes.CDLL` call releases the GIL; the C code never touches
  Python (no `Py` symbol is undefined or exported).
* `c-threads`: the pool lives only inside the call. Every pool task has finished before the call
  returns (`sc_parallel_run`), so no thread touches a caller buffer after the return. Idle GLib
  workers named `pool-<n>` may remain for up to GLib's 15 s idle limit; they run no caller code.
* A caller must keep the columns, `out` and `scratch` alive and unmoved during the call and must
  not write them from another thread.

## Counters (test hook, ruling 31)

`pl_inproc_price_stats` takes the 16 arguments and a nullable `struct pl_batch_stats *`. It is
declared in `pl_inproc.h`, defined in `src/pl_inproc.c`, not exported (the version script exports
exactly two names), and `pl_inproc_price` wraps it. Its counters are the G4.8 counters of the
batch: `calls[m]` and `evals[m]` are 0 for an unselected model.

## Differences from the plan text (EX-9)

* The batch call is `pl_batch_run_untraced`, the same checks and results as `pl_batch_run` without
  the `ScParallelTrace`, so that `pl_inproc.h` and `pl_inproc.c` include no GLib header.
* The scratch order is perm, indices, mark (ruling A41), not the plan's perm, mark, indices.
* ALO is wired (`PL_MASK_WIRED` is 31): the masks 16 and 31 are identity checks, not defects.

## Fuzz target `inproc`

The harness builds n of 0-4 rows, the threads value (a byte, so 5 and above occur), the models
value (a u16, so 0, 32 and above occur) and the request index from the input. It places the eight
columns, `out` and `scratch` in a static 8-byte aligned arena at offsets taken from the input
(a skew byte per pointer, the length of each buffer within one of the exact value, one less or one
more), so that misaligned, overlapping and short buffers occur, and calls `pl_inproc_price`. A
refused call (return 1) must leave the arena unchanged; a call outside the contract (n = 0, threads
above 4, models 0 or above 31) must be refused; a valid call's records are decoded with
`pl_response_decode` and the call's mask. No pointer range leaves the arena (a static assertion).
The code has no loop and no short-circuit helper chain, because of the fixed GCC analyzer budget.

Input layout: byte 0 n (modulo 5), byte 1 threads, bytes 2-3 models (little-endian), byte 4 request
index, byte 5 out length delta, byte 6 scratch length delta, bytes 7-8 reserved, bytes 9-18 ten slot
bytes (pointer i is at arena offset 64 x slot; pointers 0-7 the columns, 8 `out`, 9 `scratch`),
bytes 19-28 ten skew bytes (bit 0 set: the pointer is 4 bytes further), bytes 29-284 the row values
(column c at 29 + 32 c: four doubles). A length delta byte d changes the exact length by -1 for
d modulo 4 = 1, by +1 for 3 and not at all otherwise. An input shorter than 285 bytes is ignored.
The corpus seeds are valid calls (2 rows), a misaligned column, overlapping buffers, a short
output, the masks 0, 1, 15, 16, 31 and 32, the BAW `baw_admit` boundary rows (G2.5) and the ALO
rows at the switch and at sigma_lo (I4.4).
