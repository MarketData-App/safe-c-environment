# Module `bd_wire` specification

Status: example specification for the bench-demo project (plan amendment
FR6, task N3, ruling FR6-R3). Write and review this file before any module
source changes. The module uses `bd_digest`; every route computes through
the route entry `bd_digest_request` (specs/project/bd_digest.md).

## Files

| File | Contents |
|---|---|
| `include/bd_wire.h` | public interface, limits and codes |
| `src/bd_wire.c` | byte helpers, header and descriptor codec, `bd_answer_request`, `bd_proto_name` |
| `src/bd_io.c` | `bd_read_exact`, `bd_write_all`, `bd_pread_exact`, `bd_pwrite_all` |
| `src/bd_serve.c` | `bd_serve`, `bd_shm_request` |
| `src/bd_worker_cli.c` | `bd_worker_main`, the program logic of `bd-worker` |
| `src/bd_kernel_args.c` | `bd_kernel_parse`, the option parser of `bd-kernel` |
| `src/bd_kernel_cli.c` | `bd_kernel_cli_main`, the program logic of `bd-kernel` |
| `src/worker_main.c` | `main` of `bd-worker`, which only calls `bd_worker_main` on fds 0 and 1 |
| `src/kernel_main.c` | `main` of `bd-kernel`, which only calls `bd_kernel_cli_main` with stdin, stdout and stderr |

The I/O units define `_GNU_SOURCE` (empty, before the first include: the
form the framework AST scan recognizes for its precompiled header) for the
POSIX declarations `read`, `write`, `pread`, `pwrite`, `fstat`, `fileno`
and `clock_gettime`. The code uses no GNU language extension. Frames, regions
and request files come from another process, so all of their bytes are
external input.

## Protocol (framework values, SCPL v2)

Header 28 bytes, little-endian `<4sHHQIHHI`: magic `SCPL` (offset 0),
version 2 (4), type (6), request ID (8), record count (16), threads (20),
selector mask (22), payload length (24). Types: `REQUEST` 1, `RESPONSE` 2,
`ERROR` 3, `SHUTDOWN` 4, `SHM_REQUEST` 5, `SHM_RESPONSE` 6. Codes: 1
`BAD_MAGIC`, 2 `BAD_VERSION`, 3 `BAD_TYPE`, 4 `RECORD_LIMIT`, 5
`FRAME_LIMIT`, 6 `LENGTH_MISMATCH`, 7 `PROTOCOL_TRUNCATED`, 8
`BAD_THREADS`, 9 `KERNEL_FAILURE`, 10 `IO_ERROR`, 11 `RESERVED_NONZERO`, 12
`BAD_SELECTOR`. Limits: 14,336 records per request; 4 MiB (4,194,304
bytes) per frame, header included; at most 4 threads.

Bench-demo codec values (FR6-R3 item 1): request record 12 bytes, response
record 16 bytes; the only defined selector value is 1 (`BD_SELECTOR_DIGEST`,
the digest); the codec has no pool, so a selected frame needs threads 0;
the shm input region is at most 172,032 bytes (14,336 × 12) and the output
region at most 229,376 bytes (14,336 × 16).

## `bd_header_decode(buf, len, out)`

| Check (in this order) | Result |
|---|---|
| `len < 28` | `PROTOCOL_TRUNCATED`; `*out` all zero |
| magic is not `SCPL` | `BAD_MAGIC` |
| version ≠ 2 | `BAD_VERSION` |
| type outside 1–6 | `BAD_TYPE` |
| record count > 14,336 | `RECORD_LIMIT` |
| threads > 4, or threads ≠ 0 on types 1, 2, 5, 6 | `BAD_THREADS` |
| types 1, 2, 5, 6: mask ≠ 1 (the framework range 1–31 narrowed by the codec) | `BAD_SELECTOR` |
| types 3, 4: mask ≠ 0 | `RESERVED_NONZERO` |
| 28 + payload length > 4,194,304 | `FRAME_LIMIT` |
| payload length per type: REQUEST 12·count; RESPONSE 16·count; ERROR 4 with count 0 and threads 0; SHUTDOWN 0 with count 0 and threads 0; SHM_REQUEST 32; SHM_RESPONSE 8 | `LENGTH_MISMATCH` |

For `len >= 28`, `*out` holds the decoded fields whatever the result, so an
`ERROR` reply repeats the request ID. `buf` and `out` are not `NULL`
(caller obligation). A REQUEST with count 0 is a ping.

## `bd_shm_descriptor_check(d, count, in_size, out_size)`

The 32-byte `SHM_REQUEST` payload is `<4Q`: input offset, input length,
output offset, output capacity. In this order: `in_size > 172,032` or
`out_size > 229,376` → `FRAME_LIMIT`; then any of a wrapping
offset + length (checked addition), input length ≠ 12·count, output
capacity < 16·count, input end > `in_size`, output end > `out_size` →
`LENGTH_MISMATCH`; else OK.

## `bd_answer_request(h, payload, frame, capacity, frame_length)`

`h` passed `bd_header_decode` as a REQUEST. Capacity below 28 + 16·count,
or a refusal of `bd_digest_request` (steps above 1,000,000, overlap) →
`KERNEL_FAILURE` with `*frame_length` 0. Count 0 → a 28-byte RESPONSE with
no payload. Else a RESPONSE header (same request ID, count and mask,
threads 0, payload 16·count) followed by the output records.

## I/O helpers

`bd_read_exact` reads exactly `len` bytes and retries `EINTR`; EOF before
the first byte → `BD_IO_EOF`; EOF after ≥ 1 byte → `BD_IO_TRUNCATED`;
a read error → `BD_IO_ERROR`. `bd_write_all` writes all `len` bytes;
an error or a zero-byte write → `BD_IO_ERROR`. `len` 0 → `BD_IO_OK`
without a call. The positioned forms first refuse an offset + `len` that
wraps or exceeds `INT64_MAX` (`BD_IO_ERROR`); a short positioned read is
`BD_IO_TRUNCATED`; a descriptor without a position (a pipe) is
`BD_IO_ERROR`.

## `bd_serve(in_fd, out_fd, o, requests)`

`*requests` is 0 at the start when `requests` is not `NULL`. `o` or
`requests` `NULL`, or a route other than stdio (0) and shm (1) → 2. The loop
reads a 28-byte header:

- EOF before the header → 0. A truncated header → `ERROR`
  `PROTOCOL_TRUNCATED` with request ID 0, result 1. A read error → 4.
- `SHUTDOWN` → 0.
- A decode failure, or a type the route does not accept (stdio accepts only
  REQUEST, shm only SHM_REQUEST) → `ERROR` with that code (`BAD_TYPE` for
  the route), result 1. No payload byte has been read (the IN offset is 28
  after the first frame).
- The payload is read; EOF inside it → `ERROR` `PROTOCOL_TRUNCATED`,
  result 1; a read error → 4.
- REQUEST: `bd_answer_request`; `KERNEL_FAILURE` → `ERROR`, result 3; else
  the RESPONSE is written.
- SHM_REQUEST: `bd_shm_request`; `IO_ERROR` → `ERROR`, result 4;
  `KERNEL_FAILURE` → `ERROR`, result 3; other failures → `ERROR`, result
  1; else `SHM_RESPONSE` (same request ID, count and mask, threads 0) with
  the 8-byte written count.
- A failed write of any frame → 4. After each answered request
  `*requests` grows by one.

Every `ERROR` frame has count 0, threads 0, mask 0 and the 4-byte code.

## `bd_shm_request(o, h, payload, input, output, written)`

`*written` is 0 on entry. Both region descriptors must be regular files
with a nonnegative size (`fstat`), else `IO_ERROR`. The descriptor is then
checked against the current sizes (`bd_shm_descriptor_check`); a failure
is returned before any region byte is read. Count 0 → OK with 0 bytes. The
input range is copied with `bd_pread_exact` into the private `input`
buffer (a snapshot: a later region change cannot change the digested
records); a short read → `PROTOCOL_TRUNCATED`, an error → `IO_ERROR`.
`bd_digest_request` runs on the copy into `output` (capacity 229,376); a
refusal → `KERNEL_FAILURE`. The records are written with `bd_pwrite_all`
at the output offset; an error → `IO_ERROR`. On every failure the output
region is unchanged.

## `bd_worker_main(argc, argv, err)` and the program `bd-worker`

Options: `--stdio`, or `--shm-in FD --shm-out FD` (in this order; FD a
decimal text of 1 to 4 digits in 3–1023; the two differ), optionally
followed by `--files IN OUT`. Any other form, a `NULL` `argv` or a `NULL`
argument → `usage: bd-worker --stdio | --shm-in FD --shm-out FD [--files
IN OUT]` and a newline on `err`, result 2. Without `--files` it serves fd 0
to fd 1. With `--files` (a test option) it serves the file IN into the file
OUT (created or truncated); a file that cannot be opened → 4; then it
writes `BDW1 exit=<result> requests=<n>` and a newline on `err`. The result
is `bd_serve`'s.

## `bd_kernel_cli_main(argc, argv, in, out, err)` and the program `bd-kernel`

- `argc == 2` and `argv[1]` = `--self-check` → `bd_kernel_main` (the
  self-check of specs/project/bd_digest.md).
- Else `bd_kernel_parse` reads, in this fixed order, `--input PATH
  --records N --loops L`, then optionally `--handshake`, then optionally
  `--output PATH` (so argc is 7 to 10); N is 1–14,336 and L 1–1,000,000,
  decimal texts of 1 to 7 digits (checked with `strlen`, `strspn` and
  `strtoull`, so seven digits cannot overflow). Another order, an unknown
  or repeated option, a missing or bad value, an extra argument or a `NULL`
  `argv` → `usage: bd-kernel --self-check | --input F --records N --loops L
  [--handshake] [--output F]` and a newline on `err`, `PLK1 status=FAIL
  reason=usage` on `out`, result 2; `*o` is all zero then. The fixed order
  keeps the parser free of a state loop (GCC `-fanalyzer` budget).
- The input file must hold exactly 12·N bytes and pass `bd_check_request`
  (steps ≤ 1,000,000), else `reason=input`, result 2. This happens before
  the handshake and outside the timed loops.
- With `--handshake`: `B` on `out` (flushed), then `G` must come from `in`;
  after the loops `E` on `out`, then `F` from `in`. Any other byte, EOF or
  a failed write → `reason=io`, result 4.
- The timed part reads `CLOCK_MONOTONIC` and `CLOCK_PROCESS_CPUTIME_ID`,
  runs L calls of `bd_digest_request` on the request into a local output
  buffer and reads both clocks again. A failed call or clock →
  `reason=kernel`, result 3.
- `--output PATH` gets the 16·N output bytes of the last loop; a failed
  write → `reason=io`, result 4.
- Last line on `out`: `PLK1 status=OK case=bd-digest records=<N>
  loops=<L> threads=0 mono_ns=<u64> cpu_ns=<u64> chunks=0 chunk_sizes=
  chunk_wall_ns= copied_bytes=<12N> digest=<16 hex>` where `digest` is the
  FNV-1a 64 of the output bytes; a failed write or flush → 4.

## Ownership, lifetimes and concurrency

- Every pointer is borrowed for the call. No function keeps a pointer or a
  descriptor. `bd_serve` does not close descriptors; `bd_worker_main`
  closes only the files it opened.
- Buffers: `bd_serve` keeps one request payload (172,032 bytes), one input
  snapshot (172,032 bytes) and one response frame (229,404 bytes) on its
  stack; `bd_kernel_cli_main` keeps one request and one output buffer. No
  allocation and no global mutable state.
- The functions are reentrant on distinct descriptors and buffers. The
  shm regions are written by the caller before the request and read by the
  caller after the response; the worker reads the input region once.

## Derived tests

The tests combine their checks into one result bit or run each case with
its own REQUIRE, and batch cases that share streams, so that each GCC
`-fanalyzer` run stays within the framework's fixed budget.

- `tests/project/test_bd_wire.c`: the header byte layout and the decoded
  fields of a refused header; truncation at 0 and 27 bytes; every check in
  order with good frames at the bounds (count 0, 14,336; payload 172,032
  and 229,376) and the one-past values (count 14,337, threads 1, 4 and 5,
  masks 0, 2, 31, 32, types 0, 7, 65,535, frame 4 MiB + 1, every per-type
  length ± 1, ERROR and SHUTDOWN with count or threads); descriptor layout
  and checks (exact, one short, one past, wrapping offsets, sizes above the
  bounds, count 0, 14,336); `bd_answer_request` (two records, ping, exact
  and one-short capacity, steps 1,000,001); every code name and 13 →
  `UNKNOWN`; the ERROR payload bytes.
- `tests/project/test_bd_io.c`: exact reads (0, partial, EOF, truncated),
  complete writes, positioned reads and writes at offsets 5 and 15, the
  `INT64_MAX` bound (exact with length 0, one past, wrapping), an invalid
  descriptor for all four, a pipe (no position, truncated, EOF).
- `tests/project/test_bd_serve.c`: ping; two requests then SHUTDOWN (the
  frame after it is not read); EOF before a header; `NULL` options, `NULL`
  requests, routes 7 and −1 → 2; read and write failures → 4; the largest
  request (14,336 records).
- `tests/project/test_bd_serve_limits.c`: fifteen refused frames in one IN
  file (twelve header refusals, `BAD_MAGIC`, a REQUEST on the shm route,
  steps 1,000,001 → 3), each with its ERROR frame, request ID and IN offset
  (28, or 40 for the kernel failure); a truncated payload and header.
- `tests/project/test_bd_shm.c`: round trip at offsets 24 and 16, a larger
  capacity, a ping, the largest request filling both regions; the snapshot.
- `tests/project/test_bd_shm_hostile.c`: eight hostile descriptor and
  region-size cases, all refused, with the output region zero at the end
  (it only grows between cases).
- `tests/project/test_bd_shm_access.c`: a pipe, a closed descriptor and a
  pipe output → 4; steps 1,000,001 → 3; read-only output and write-only
  input regions → 4.
- `tests/project/test_bd_worker_usage.c`: fifteen usage forms.
- `tests/project/test_bd_worker_cli.c`: `--files` with the stdio route, a
  missing IN file, an unopenable OUT file, the shm route, a protocol error.
- `tests/project/test_bd_kernel_cli.c`: the self-check dispatch; twenty-one
  usage forms (counts 0 and one past, eight digits, a bad digit, an empty
  value, missing options, another order, repeats, a handshake before
  `--input`, a missing `--output` value, extra arguments, eleven arguments,
  a `NULL` `argv`); a failed summary write.
- `tests/project/test_bd_kernel_run.c`: runs with and without the
  handshake (the PLK1 line and the output file); the largest request.
- `tests/project/test_bd_kernel_fail.c`: a wrong first handshake byte, a
  missing F, missing, short and long input files, an unwritable output file
  and steps 1,000,001.
- `fuzz/project/bd_frame_fuzz.c`: arbitrary frames through
  `bd_header_decode` with an independent magic, version and bound oracle,
  the header round trip, `bd_answer_request` against `bd_check_request`,
  and `bd_shm_descriptor_check` against independent range checks.
- `fuzz/project/bd_kernel_parse_fuzz.c` (N3-A07): arbitrary argument lists
  (NUL-separated input bytes, at most 12 arguments after the program name)
  through `bd_kernel_parse` with an independent grammar oracle (argc 7 to
  10, the fixed order, the optional `--handshake` and `--output` tail, 1 to
  7 digits in [1, 14,336] and [1, 1,000,000]); on success every option field
  equals the oracle's and the paths point at the argument texts; on failure
  every field is `NULL` or 0; a `NULL` `argv` is refused.
