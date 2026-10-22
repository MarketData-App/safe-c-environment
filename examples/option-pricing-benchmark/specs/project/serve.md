# Module `serve` specification

Status: Phase 2 Task 15 as adapted by EX-8 (the standalone example). The persistent worker
`pl-worker` for the routes `stdio` and `shm` on SCPL protocol version 2 (specs/project/protocol.md
and the framework transport `benchlab.native_worker` / `benchlab.native_shm`). The module reads
frames, answers each with the batch (specs/project/batch.md) and keeps no state between requests
except the request count and the optional counter totals. Write and review this file before any
module source changes.

## Files

| File | Contents |
|---|---|
| `include/pl_serve.h`, `src/pl_serve.c` | `pl_serve` (the frame loop) |
| `src/pl_serve_run.c` | `pl_serve_compute` (the batch of one request into records and trailer; its own translation unit for the GCC analyzer budget) |
| `src/pl_shm.c` | `pl_shm_request` (the `shm` route: descriptor check, snapshot, batch, positioned write) |
| `include/pl_worker_cli.h`, `src/pl_worker_cli.c`, `src/pl_worker_opts.c` | `pl_worker_main` (command line, `--files`, exit codes) and `pl_worker_option` (one option; its own translation unit) |
| `src/pl_worker.c` | `main`: `return pl_worker_main(argc, argv, stderr);` |
| `include/pl_test_serve.h` | test helpers (frames in tmpfiles, shm regions with `PL_TS_SHM`); no source includes it |
| `tests/project/test_serve.c` | group `ping` |
| `tests/project/test_serve_rows.c` | group `rows` |
| `tests/project/test_serve_index.c` | group `request-index` |
| `tests/project/test_serve_io.c` | group `io-errors` (result 2 for an unknown route; result 4 for a read error at and after the header, and for a RESPONSE and an ERROR write failure) |
| `tests/project/test_serve_shutdown.c` | group `shutdown` |
| `tests/project/test_serve_limits.c` | group `limits` |
| `tests/project/test_serve_cut.c` | group `truncated` |
| `tests/project/test_serve_echo.c` | group `echo` |
| `tests/project/test_serve_masks.c` | group `masks` |
| `tests/project/test_serve_max.c` | group `maximum` (14,336 records, threads 4, mask 1: 917,504-byte payload, 4,157,536-byte frame) |
| `tests/project/test_serve_counters.c` | group `counters` (the `--counters` totals) |
| `tests/project/test_shm.c` | group `round-trip` (all models, 2 threads) |
| `tests/project/test_shm_one.c` | group `round-trip-one` (model 1, no threads) |
| `tests/project/test_shm_ping.c` | group `ping` |
| `tests/project/test_shm_snapshot.c` | group `snapshot` |
| `tests/project/test_shm_hostile.c` | group `hostile` |
| `tests/project/test_shm_max.c` | group `maximum` (the same through `pl_serve` on shm and through `pl_shm_request`: 917,504-byte snapshot, 4,157,508-byte output) |
| `tests/project/test_shm_type.c` | group `wrong-type` |
| `tests/project/test_shm_access.c` | group `access` |
| `tests/project/test_worker_cli.c` | group `usage` |
| `tests/project/test_worker_std.c` | group `standard-stream` (always runs: fd 0 and fd 1 are redirected onto files; 8 rows and SHUTDOWN) |
| `tests/project/test_worker_files.c` | group `files` (`--files` and `--echo`) |
| `tests/project/test_worker_fail.c` | group `failures` (a protocol error, the shm option numbers, a missing input) |

Each test file holds one group, because of the fixed GCC analyzer budget of one translation unit.

Uses: module `batch` (and through it `models` and `protocol`). `reads_external_input` is false:
every byte that the worker reads passes through the `protocol` decoders (`pl_header_decode`,
`pl_shm_descriptor_decode`, `pl_request_decode`), which own the fuzz target.

## Routes

The route is fixed for the process. `pl_serve(in_fd, out_fd, o, requests)` reads frames from
`in_fd` and writes frames to `out_fd` until SHUTDOWN or EOF.

| Route | Accepted types | Refused with `BAD_TYPE` |
|---|---|---|
| `PL_ROUTE_STDIO` | `REQUEST`, `SHUTDOWN` | `SHM_REQUEST`, `RESPONSE`, `ERROR`, `SHM_RESPONSE` |
| `PL_ROUTE_SHM` | `SHM_REQUEST`, `SHUTDOWN` | `REQUEST`, `RESPONSE`, `ERROR`, `SHM_RESPONSE` |

`struct pl_serve_options { int route; int echo; int shm_in_fd; int shm_out_fd; uint64_t *calls;
uint64_t *evals; }`. `calls` and `evals` are nullable; when set they point to `PL_MODELS`
counters to which every request adds the totals of its `struct pl_batch_stats` (the `--counters`
test option). `echo` selects the echo records (batch.md "Echo").

## Check order (header before payload)

1. `pl_read_exact(in_fd, header, 28)`: EOF before the first byte ends the loop with result 0 and no
   frame; a short header or a read after the first byte gives `ERROR PROTOCOL_TRUNCATED` with
   request ID 0, result 1; a read error gives result 4.
2. `pl_header_decode` (magic, version, type, record count, threads, models, frame size, payload
   length, in this order). SHUTDOWN ends the loop with result 0.
3. The route check (`BAD_TYPE`).
4. Only then the payload is read (`payload_length` bytes, at most 917,504). EOF or a short read
   gives `ERROR PROTOCOL_TRUNCATED`, result 1.

A failed step 2 or 3 writes an `ERROR` frame with the request ID of the header, record count 0,
threads 0, **models 0** and the 4-byte payload (code `u16`, reserved `u16` = 0), and returns 1.
No payload and no region byte has been read at that point.

## Results

`pl_serve` returns 0 (SHUTDOWN, or EOF before a header), 1 (protocol error; an `ERROR` frame was
written), 3 (kernel failure; `ERROR KERNEL_FAILURE` written), 4 (I/O failure; for a region that
fails the `IO_ERROR` check an `ERROR IO_ERROR` frame is written first) and 2 for a NULL `o` or
`requests` or an unknown route (nothing read or written). `*requests` counts the requests that
were answered with a `RESPONSE` or `SHM_RESPONSE`.

## Request: route stdio

A `REQUEST` with `n` records (0 to 14,336) holds `n * 64` payload bytes. The answer is a
`RESPONSE` with the request's request ID, record count, threads and **models** (the mask is
repeated exactly), and the payload `n * 290` record bytes followed by the trailer
(`pl_trailer_encode`: `u32 k`, then `k` entries of `u32 size`, `u32 0`, `u64 wall_ns`). `k` is 0
when threads is 0, else `min(threads, n)`. A request with 0 records is a **ping**: the payload is
the 4-byte trailer with `k = 0`.

The batch runs `pl_batch_run_untraced` over the payload (`PL_INPUT_WIRE`) with the request's mask
(`models`), threads and partition request index `(uint32_t)request_id` (the low word of the
request ID; Amendment E: the chunk rule). The partition changes only the order of work: the record
bytes do not depend on threads or on the request index. A batch failure (a run defect of a
selected model, a model outside `PL_MASK_WIRED`, a pool failure, or a chunk count that differs
from `k`) gives `ERROR KERNEL_FAILURE` (models 0) and result 3. Responses keep the order of the
request records.

## Request: route shm

A `SHM_REQUEST` carries the 32-byte descriptor `{in_offset, in_length, out_offset, out_capacity}`
(`u64` each) and the same count, threads and models fields. `pl_shm_request`:

1. `fstat` both descriptors; a descriptor that is not a regular file, or that `fstat` refuses, is
   `IO_ERROR` (before any region read).
2. `pl_shm_descriptor_check` with the current region sizes: `in_length == n * 64`;
   `out_capacity >= n * 290 + 4 + 16 k`; both ranges inside their regions without a wrap
   (`LENGTH_MISMATCH`); then input region at most 917,504 and output region at most 4,157,508
   bytes (`FRAME_LIMIT`).
3. `pl_pread_exact` of the input range into the private `input` buffer (the **snapshot**: the
   batch reads only this copy, so a later change of the region cannot change the records that the
   batch reads). A short read is `PROTOCOL_TRUNCATED`; another failure is `IO_ERROR`.
4. The batch over the copy into the private `output` buffer (records and trailer).
5. `pl_pwrite_all` of the records and the trailer at `out_offset`; `*written` is the byte count
   (`n * 290 + 4 + 16 k`; 4 for a ping). On any failure before step 5 the output region is not
   touched, and `*written` is 0.

The answer is a `SHM_RESPONSE` with the request's request ID, count, threads and models and the
8-byte payload `written` (`u64`). The caller owns both region descriptors; the worker never
closes them.

## Counters

`--counters` is a test option (G4.8). `calls` and `evals` are the totals over all requests of the
run, in `MODELS5` order; a model outside every request mask stays 0.

## Command line

`pl-worker [--echo] [--counters] [--shm-in FD --shm-out FD] [--files IN OUT]`

- Without `--shm-in`, the route is `stdio` on descriptors 0 and 1.
- `--shm-in FD --shm-out FD`: both or neither; each FD is a decimal of one to four digits in
  3-1023; the two differ. The route is `shm`; the frames use descriptors 0 and 1.
- `--files IN OUT`: frames are read from the file IN and written to the file OUT (tests); the
  line `PLW1 exit=<code> requests=<n>` is printed to stderr at exit.
- `--echo`: echo records (status 255 for the selected models, `NOT_REQUESTED` for the others).
- `--counters`: adds ` calls=<model>:<u64>,... evals=<model>:<u64>,...` (models `bsm,bjs,crr,baw,
  alo`) to the `PLW1` line, which is then printed also without `--files`.
- Any other argument, a repeated option or an option without its value is a usage error: exit 2,
  one usage line on stderr.

Exit codes are the results of `pl_serve`, and 2 for usage. A missing or unwritable `--files`
file gives 4. `SIGPIPE` is ignored at start, so a write to a closed pipe is an I/O failure.

## Static buffers and ownership

`pl_serve` uses static buffers (one call at a time, one thread): one request payload (917,504
bytes = 14,336 * 64), one response frame (28 + 4,157,508 = 4,157,536 bytes), one shm input
snapshot (917,504 bytes) and the partition scratch for 14,336 rows. No allocation. Every pointer
argument is borrowed for the call.

## Differences from the plan text

SCPL v2 follows `benchlab.native_worker`: the framework names code 12 `BAD_SELECTOR`, this
codec `PL_PROTO_BAD_MODELS` (same number). The `serve` options gain the nullable `calls` and
`evals` pointers for the `--counters` totals. The two `--shm` descriptors must differ.
