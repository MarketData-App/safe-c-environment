# Module `protocol` specification

Status: Phase 2 Task 13. The SCPL wire codec of protocol version 2 in the
five-block form (Amendment F item 5 as changed by Amendment G items G4.4-G4.5
and Amendment I item I5), the canonical result writer `ocg-v1`/`ocg-v1m`
(Amendment G item G5, Amendment I item I6) and exact-length descriptor I/O.
The module evaluates no model. Write and review this file before any module
source changes.

## Files

| File | Contents |
|---|---|
| `include/pl_protocol.h`, `src/pl_protocol.c` | header, request and response records, trailer, error payload, shm descriptor |
| `src/pl_wire16.c`, `src/pl_wire.c` | the byte helpers (`pl_load_*`, `pl_store_*`): u16 in `pl_wire16.c`; u32, u64, binary64 and the unchecked model-part copies `pl_load_part`/`pl_store_part` in `pl_wire.c` |
| `include/pl_canonical.h`, `src/pl_canonical.c` | canonical writer |
| `src/pl_sink.c`, `src/pl_sink_format.c` | byte sink: `pl_sink_byte`, `pl_sink_flush` and the digest `pl_sink_fnv`; `pl_sink_text`, `pl_sink_uint`, `pl_sink_hex_bits` and the FNV-1a 64 product `pl_fnv1a_mul` (an opaque call in `pl_sink.c`: the fixed GCC analyzer budget) |
| `include/pl_io.h`, `src/pl_io.c` | exact-length reads and writes, file read, SIGPIPE, clocks |
| `include/pl_vec_canonical.h` | generated vectors (`optionlab.cvectors` part `canonical`) |
| `tests/project/test_protocol.c` | groups `bytes`, `headers`, `masks`, `flag-rule`, `records`, `full-response`, `shm`, `errors` |
| `tests/project/test_canonical.c` | groups `texts`, `shared-digest` (the mask-7 kernel digest shared with tests/test_light_native_codec.py), `descriptor` |
| `tests/project/test_canonical_sink.c` | groups `sink`, `digest` (FNV-1a 64 known answers), `statuses`, `refusals` (a second file: the fixed GCC analyzer budget) |
| `tests/project/test_io.c` | groups `pipes`, `closed`, `files`, `partial` (an EINTR read, a short write and an EINTR write, through a SIGALRM handler without `SA_RESTART`), `clocks` |
| `fuzz/project/protocol_fuzz.c` | fuzz target `protocol` |
| `fuzz/project/corpus/protocol/` | generated seeds (`optionlab.cvectors.corpus_files`) |
| `fuzz/project/regressions/protocol/` | replayed regression inputs (empty at Task 13) |

Uses: module `models` (`pl_types.h`, `pl_ieee.h`).

The byte helpers and the sink are separate translation units, so that each call inside a loop
of `pl_protocol.c`, `pl_canonical.c` and `pl_sink_format.c` is opaque to the GCC analyzer (the
fixed analyzer budget of the framework; the same reason as in `batch.md`).

## Ownership and lifetimes

Every buffer, record, result, sink buffer and path is caller-owned and
borrowed for the duration of one call. No function keeps a pointer after it
returns, allocates memory or closes a descriptor that the caller passed. A
`struct pl_sink` borrows its `buf` for as long as the caller uses the sink.
No function has global state except `pl_ignore_sigpipe`, which changes the
process SIGPIPE disposition. Every function may run on any thread when its
arguments are not shared with another thread.

Nullable arguments: `pl_trailer_encode` takes `sizes` and `wall_ns` as `NULL`
when `k` is 0; `pl_canonical_write` takes `rows` as `NULL` when `n` is 0.
Every other pointer argument is non-`NULL` and points to the stated number of
readable or writable bytes.

## Wire format (version 2)

All multi-byte values are little-endian and are read and written byte by byte
through `pl_load_u16/u32/u64/f64` and `pl_store_u16/u32/u64/f64` (no `memcpy`,
no typed casts of wire storage; the binary64 fields are not 8-byte aligned).

Header, 28 bytes, `<4sHHQIHHI>`:

| Offset | Field | Rule |
|---|---|---|
| 0 | magic | `SCPL` |
| 4 | version | 2 |
| 6 | type | `REQUEST` 1, `RESPONSE` 2, `ERROR` 3, `SHUTDOWN` 4, `SHM_REQUEST` 5, `SHM_RESPONSE` 6 |
| 8 | request ID | u64; bits 0-31 the partition request index, bits 32-63 the call sequence number |
| 16 | record count | at most 14,336 (`PL_MAX_REQUEST_RECORDS`) on types 1, 2, 5, 6; 0 on types 3, 4 |
| 20 | worker threads | 0-4 on types 1, 2, 5, 6; 0 on types 3, 4 |
| 22 | models | 1-31 on types 1, 2, 5, 6 (bit 1 << k in `MODELS5` order: `bsm` 1, `bjs` 2, `crr` 4, `baw` 8, `alo` 16); 0 on types 3, 4 |
| 24 | payload length | per type, below |

Payload length per type: `REQUEST` count × 64; `RESPONSE`
`pl_response_payload(count, threads)` = count × 290 + 4 + 16·k, k = 0 when
threads = 0, else min(threads, count); `ERROR` 4 with count 0; `SHUTDOWN` 0
with count 0; `SHM_REQUEST` 32; `SHM_RESPONSE` 8. A ping is a `REQUEST` with
count 0; it carries a mask in 1-31 too.

Request record, 64 bytes: side, S, K, T, bid, ask, r, q as binary64.
`pl_request_decode` maps side 0.0 (−0.0 included) to 0, 1.0 to 1 and every
other value, NaN included, to −1 (an unknown side, `INVALID_INPUT` for that
row). `pl_request_encode` writes `(double)row->side`.

Response record, 290 bytes, `<5B5B35d>`: status bytes at offsets 0-4 and flag
bytes at 5-9 (order `bsm`, `bjs`, `crr`, `baw`, `alo`), then model k field j
(IV, price, delta, gamma, theta, vega, rho) at 10 + 56·k + 8·j (`bsm` 10, `bjs`
66, `crr` 122, `baw` 178, `alo` 234). No reserved bytes.

Response trailer, 4 + 16·k bytes: u32 k, then k × (u32 chunk size, u32 zero,
u64 chunk wall ns). `pl_trailer_encode` writes it; the sizes are at most
14,336 and are stored as u32.

ERROR payload, 4 bytes: u16 code and a zero u16. `pl_error_decode` returns
the code in `*code`; a nonzero reserved u16 gives `RESERVED_NONZERO`. The code
value is passed through; the caller maps it to a name.

SHM_REQUEST payload, 32 bytes: u64 input offset, input length, output offset,
output capacity. SHM_RESPONSE payload, 8 bytes: u64 bytes written.

Limits: 14,336 records per request; 4,194,304 bytes per frame; largest
response payload 14,336 × 290 + 4 + 16·4 = 4,157,508 bytes, largest frame
4,157,536 bytes; shm input region at most 917,504 bytes, output region at most
4,157,508 bytes.

## Error codes

1 `BAD_MAGIC`, 2 `BAD_VERSION`, 3 `BAD_TYPE`, 4 `RECORD_LIMIT`, 5
`FRAME_LIMIT`, 6 `LENGTH_MISMATCH`, 7 `TRUNCATED` (`PROTOCOL_TRUNCATED`), 8
`BAD_THREADS`, 9 `KERNEL_FAILURE`, 10 `IO_ERROR`, 11 `RESERVED_NONZERO`, 12
`BAD_MODELS` (`BAD_SELECTOR` in framework code). 0 is `PL_PROTO_OK` and is
never sent.

## Header check order

`pl_header_decode(buf, len, out)` reads at most 28 bytes and no payload byte:

1. `len < 28` → `TRUNCATED` and `*out` zeroed. So a 26-byte version-1 frame
   at EOF is `TRUNCATED`. Otherwise every field is decoded into `*out` first.
2. magic ≠ `SCPL` → `BAD_MAGIC`.
3. version ≠ 2 → `BAD_VERSION` (a version-1 header followed by more bytes).
4. type ∉ 1-6 → `BAD_TYPE`.
5. record count: types 3, 4: ≠ 0 → `RESERVED_NONZERO` (G4.4: "models 0, else
   `RESERVED_NONZERO` (as count and threads)"); types 1, 2, 5, 6: > 14,336 →
   `RECORD_LIMIT`.
6. threads: types 1, 2, 5, 6: > 4 → `BAD_THREADS`; types 3, 4: ≠ 0 →
   `RESERVED_NONZERO`.
7. models: types 1, 2, 5, 6: 0 or > 31 → `BAD_MODELS`; types 3, 4: ≠ 0 →
   `RESERVED_NONZERO`.
8. frame size: 28 + payload length > 4,194,304 → `FRAME_LIMIT`.
9. payload length ≠ the type's value → `LENGTH_MISMATCH`.

On `ERROR` and `SHUTDOWN` a nonzero record count, thread count or mask is
`RESERVED_NONZERO` (steps 5, 6, 7), as spec G4.4 states; the spec is binding
over the plan test, which had `LENGTH_MISMATCH` for the count (controller
ruling P2-T13-CTRLCOUNT-01). A count of 1, 14,337 or `UINT32_MAX` on either type
is `RESERVED_NONZERO`.

## Response record rule (G4.5, N7, I5.3)

`pl_response_decode(rec, models, r)` decodes all five parts into `*r`, then:

- `models` outside 1-31 → `BAD_MODELS` (the header has already refused it;
  the record decoder does not rely on that).
- A selected part (bit k of `models` set): status 0-8 or 255 (`ECHO`); any
  other status, 254 `NOT_REQUESTED` included, → `RESERVED_NONZERO`. Flag
  bits: 1, 2, 4, 8 in any flag byte; 16 and 32 only in the `baw` (byte 8) and
  `alo` (byte 9) flag bytes; 64 only in the `baw` flag byte; 128 never. Any
  other bit → `RESERVED_NONZERO`. (The approved G-ALO1 record defines no
  `alo_admit`, so bit 64 stays illegal in the `alo` byte.)
- An unselected part: exactly status 254, flags 0 and seven fields with the
  bits `0x7FF8000000000000`; any other content (another NaN, −NaN, 0.0, a
  flag, another status) → `RESERVED_NONZERO`.

`pl_result_not_requested(m)` writes that unselected content into a result
block; `pl_response_encode` writes a block as it is.

## shm descriptor rule (Amendment F item 10, I5.6)

`pl_shm_descriptor_check(d, count, threads, in_size, out_size)` runs before
any region byte is read, with overflow-free comparisons (offset ≤ size and
length ≤ size − offset):

1. `in_length` ≠ count × 64 → `LENGTH_MISMATCH`.
2. `out_capacity` < `pl_response_payload(count, threads)` → `LENGTH_MISMATCH`.
3. `in_offset + in_length` > `in_size` (or the sum wraps) → `LENGTH_MISMATCH`.
4. `out_offset + out_capacity` > `out_size` (or the sum wraps) →
   `LENGTH_MISMATCH`.
5. `in_size` > 917,504 or `out_size` > 4,157,508 → `FRAME_LIMIT`.

## Canonical form

`pl_canonical_write(s, rows, n, models)` writes exactly the bytes of
`optionlab.reference.canonical_result` (reference.py:311-348, G5.3 and I6.4)
for the selected models of `rows[0..n)`, then flushes the sink:

- mask 7: `{"digest_form":"ocg-v1","models":{"bjs":{...},"bsm":{...},"crr":{...}},"n":N}`,
  byte-identical to the three-model Phase 2 form;
- every other mask 1-31: `{"digest_form":"ocg-v1m","mask":M,"models":{...},"n":N}`
  with M decimal and exactly the selected models in sorted key order (`alo`,
  `baw`, `bjs`, `bsm`, `crr`); for masks 1-15 the bytes equal the Amendment G
  form (I6.3).

Each model object has the keys `delta, flags, gamma, iv, price, rho, status,
theta, vega` in this order, each a JSON array of n values. A numeric value is
`null` for NaN, else the 16 lowercase hex digits of its big-endian binary64
bits in quotes, −0.0 written as 0.0; flags are decimal integers; statuses are
the JSON strings of spec 3.3 (`INVALID_INPUT` … `OK`). Separators are `,` and
`:` without spaces; no trailing newline. Unselected parts never enter the
bytes, whatever they hold.

Return values: 0; −1, with nothing written, for a mask outside 1-31, a
selected status outside 0-8 (so `NOT_REQUESTED` 254 and `ECHO` 255 never enter
the bytes) or a selected infinite value; −2 when the sink failed.

Sink (`pl_sink_byte` takes one byte; the text, decimal and hex writers call it per byte):
`fd < 0` with `buf` NULL is a digest sink (no byte kept, never `failed`);
any other `fd < 0` is a memory sink (`failed` when more than `cap` bytes
arrive, the first `cap` bytes kept); `fd ≥ 0` buffers at most `cap` bytes and
writes them with `pl_write_all` when the buffer is full and on
`pl_sink_flush`; a write failure, or a zero capacity, sets `failed`. `total`
counts every byte given to the sink, and `fnv` holds the FNV-1a 64 state of
those bytes XOR the offset basis 0xcbf29ce484222325 (a zeroed field is the
state before the first byte). `pl_sink_fnv` returns the digest (offset basis
0xcbf29ce484222325, prime 0x100000001b3; the offset basis before the first
byte); each step uses the 32-bit halves of the state and of the prime, so no
step wraps (EX-10, the kernel digest of batch.md). `pl_sink_flush` returns 0,
or −1 when the sink failed.

## I/O

- `pl_read_exact(fd, buf, len)`: loops until len bytes; `EINTR` retried; EOF
  before any byte → `PL_IO_EOF` (a clean end before a header); EOF after at
  least one byte → `PL_IO_TRUNCATED`; any other read failure → `PL_IO_ERROR`.
- `pl_write_all(fd, buf, len)`: loops until len bytes; `EINTR` retried; a
  failure or a zero-byte write → `PL_IO_ERROR`.
- `pl_pread_exact` and `pl_pwrite_all`: positioned forms; an offset range
  above the `off_t` range → `PL_IO_ERROR`; a short positioned read (EOF) →
  `PL_IO_TRUNCATED` (the shm snapshot rule).
- `pl_read_file(path, buf, cap, len)`: opens read-only (`O_CLOEXEC`), reads
  the whole file; a file larger than cap, or an open, read or close failure
  → `PL_IO_ERROR` with `*len` 0.
- `pl_ignore_sigpipe()`: SIGPIPE ignored, so a write to a closed pipe is
  `PL_IO_ERROR`.
- `pl_clock_ns(mono, cpu)`: `CLOCK_MONOTONIC` and
  `CLOCK_PROCESS_CPUTIME_ID` in nanoseconds; 0, or −1 with both 0.

`pl_io.c` (and `test_io.c`, `test_canonical.c`) defines `_GNU_SOURCE` before its includes,
not the plan's `_POSIX_C_SOURCE 200809L`: the AST scan force-includes `sc-foundation.h`
before the first project line and adds `-D_GNU_SOURCE=` only for a unit that defines
`_GNU_SOURCE` first (container/project-source-policy.py), so a `_POSIX_C_SOURCE` define would
leave `O_CLOEXEC` and the clock macros undefined in that one configuration (source-policy
check `build-macros`; finding P2-T13-FEATURE-01).

## Fuzz target `protocol`

`fuzz/project/protocol_fuzz.c` treats the input as a frame stream: it decodes
each header; for a complete payload it decodes the request records, the
response records with the frame's `models`, the ERROR payload, or the shm
descriptor checked against two u64 region sizes taken from the next 16 input
bytes. It never reads past the input length. The corpus holds the Amendment F
entries in the version-2 form and the Amendment G and I entries (models 0, 32,
16, 31 on `REQUEST`; models 7 and record count 1 on `ERROR` and `SHUTDOWN`; models 0 on
`RESPONSE`; a 26-byte version-1 frame; every unselected-part defect, the
`alo` part included (status, flags, a value of 0.0, a NaN with a payload bit,
−NaN; `alo` selected with 254); one entry per misplaced flag bit; the valid
`alo` bits 16 and 32 and the valid `baw` bits 16, 32 and 64; a 14,337-record request; `baw_admit` boundary rows; `alo` switch
rows). No corpus file exceeds the fuzz `max_len` 4,096 (ruling 47); the full
14,336-record response is the `full-response` unit vector of
`test_protocol.c`.

## Tests

Derived from the rules above, with exact bounds and one-past values: record
count 14,336 / 14,337 and `UINT32_MAX`; threads 4 / 5; models 0 / 1 / 16 / 31 /
32 / 65,535 on every type; payload exact, one less and one more; frame size
4,194,304 / 4,194,305; status 0, 8, 9, 253, 254, 255 in a selected part;
every flag bit of every flag byte; every field of every unselected part with
one bit changed; shm offsets at the exact region end and one past, wrapped
sums, capacities exact and one less, region sizes at and above their bounds;
the canonical text of every mask of `cvectors.CANON_MASKS` and of the empty
result at the exact sink capacity and one byte less; EOF before and after the
first byte; a file one byte larger than the capacity.
