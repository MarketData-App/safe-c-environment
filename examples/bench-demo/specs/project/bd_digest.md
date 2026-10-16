# Module `bd_digest` specification

Status: example specification for the bench-demo project (plan amendment FR6,
tasks N1 and N2). Write and review this file before any module source changes.

## Files

| File | Contents |
|---|---|
| `include/bd_digest.h` | public interface and limits |
| `src/bd_digest.c` | `bd_digest_record`, `bd_decode_record`, `bd_encode_record`, `bd_decode_output`, `bd_check_request`, `bd_digest_request`, `bd_status_name` |
| `src/bd_main.c` | `bd_main`, the program logic of `bd-digest` |
| `src/main.c` | `main`, which only calls `bd_main` |
| `src/bd_kernel.c` | `bd_check_vectors`, `bd_kernel_report`, `bd_kernel_main`, the program logic of `bd-kernel` |
| `src/kernel_main.c` | `main` of `bd-kernel`; since N3 it calls `bd_kernel_cli_main` (module `bd_wire`, specs/project/bd_wire.md), which calls `bd_kernel_main` for `--self-check` |

The module has three translation units, and its tests have five, so that each
GCC `-fanalyzer` run stays within the framework's fixed analysis budget. The
tests use no raw memory function except `memcmp` (`memset` and `memcpy` are
outside the project API policy); a sentinel buffer starts as a struct copy.

## Purpose

The bench-demo workload is a tiny integer kernel: xorshift64 steps folded
into an FNV-1a 64 checksum per record. It has three versions that must give
byte-identical output for the same request:

1. native Python: `benchmarks/project/python/benchdemo/reference.py`, the
   reference and the generator of the C test vectors;
2. native C: this module, timed with no Python in the path (task N3/N4);
3. Python calling this module over stdio, shared memory and in-process
   routes (task N3/N4).

A request comes from outside the module (a worker reads it from a pipe or a
shared region), so the request bytes are external input.

Route entry (N1-A02): `bd_digest_request` is the only route entry. It
validates the whole request, including k <= 1,000,000 for every record,
before it computes any output. The lower-level functions
`bd_digest_record` and `bd_decode_record` do not check the step limit: their
caller checked it. The N3 routes (`bd-worker` over stdio and shared memory,
`libbd_inproc.so` in process) and the native kernel `bd-kernel` call
`bd_digest_request` (or `bd_check_vectors`, which calls it); they never call
`bd_digest_record` on request bytes directly.

## Workload definition

- Request: n records of 12 bytes. A record is one u64 seed (8 bytes,
  little-endian) and then one u32 step count `k` (4 bytes, little-endian).
- Limits: 1 <= n <= `BD_RECORDS_MAX` (14,336); 0 <= k <= `BD_STEPS_MAX`
  (1,000,000). The request length is therefore 12 to 172,032 bytes
  (`BD_REQUEST_MAX_BYTES`).
- Seed 0 is allowed. It maps to `BD_ZERO_SEED` (0x9E3779B97F4A7C15) before
  stepping, because xorshift64 has a zero fixed point.
- Per record: `x` = seed (or the constant). The checksum `h` starts at the
  FNV-1a 64 offset basis 0xcbf29ce484222325 for each record. Repeat k times:
  `x ^= x << 13; x ^= x >> 7; x ^= x << 17` (all modulo 2^64), then fold the
  8 bytes of `x`, least significant byte first, into `h`: for each byte `b`,
  `h = (h ^ b) * 0x100000001b3` modulo 2^64.
- Output record: `h` (8 bytes, little-endian), then the final `x` (8 bytes,
  little-endian): 16 bytes. The output of n records is 16n bytes, in input
  order.
- k = 0 gives `h` = the offset basis and `x` = the (mapped) seed.

## Arithmetic

All arithmetic is unsigned 64-bit and modulo 2^64. The left shifts drop the
high bits (defined for unsigned operands; the shift counts 13, 17, 7 and the
byte shifts are below 64). The FNV-1a product is computed with
`__builtin_mul_overflow`, which stores the product modulo 2^64; its overflow
result is ignored on purpose, because the wrap is the definition of FNV-1a.
A plain `*` would be the same value but traps the integer gate's
`unsigned-integer-overflow` check. No signed arithmetic, no floating point.

## Interface

```c
struct bd_result bd_digest_record(uint64_t seed, uint32_t steps);
enum bd_status bd_decode_record(const unsigned char *record, uint64_t *seed, uint32_t *steps);
enum bd_status bd_encode_record(unsigned char *record, uint64_t seed, uint32_t steps);
enum bd_status bd_decode_output(const unsigned char *output, struct bd_result *result);
enum bd_status bd_check_request(const unsigned char *request, size_t length, size_t *records);
enum bd_status bd_digest_request(const unsigned char *request, size_t length,
                                 unsigned char *out, size_t capacity, size_t *written);
const char *bd_status_name(enum bd_status status);
int bd_main(int argc, char **argv, FILE *out, FILE *err);
enum bd_status bd_check_vectors(const struct bd_check_vector *vectors, size_t count,
                                size_t *mismatches);
int bd_kernel_report(const struct bd_check_vector *vectors, size_t count, FILE *out, FILE *err);
int bd_kernel_main(int argc, char **argv, FILE *out, FILE *err);
```

`BD_OVERLAP` (8) is the status of an overlapping request and output (see
`bd_digest_request`). `BD_CHECK_VECTORS_MAX` (32) bounds `bd_check_vectors`.

## `bd_digest_record`

Inputs: any u64 `seed` and any u32 `steps`. It has no failure. Its time is
linear in `steps`; a request refuses `steps` above `BD_STEPS_MAX` before it
calls this function, and the tests use steps up to `BD_STEPS_MAX` only.
Output: `checksum` = `h`, `state` = the final `x`.

Precondition: the caller checked `steps <= BD_STEPS_MAX` (this function is
not a route entry). The Python reference `digest_record` differs here: it
refuses steps above `STEPS_MAX` with `ValueError('BD_STEPS_TOO_LARGE')`,
where the C function computes any u32 value.

## `bd_decode_record`

| Parameter | Nullable | Domain | Result outside the domain |
|---|---|---|---|
| `record` | yes | readable for 12 bytes | `NULL` → `BD_NULL_ARGUMENT` |
| `seed` | yes | writable `uint64_t` | `NULL` → `BD_NULL_ARGUMENT` |
| `steps` | yes | writable `uint32_t` | `NULL` → `BD_NULL_ARGUMENT` |

On `BD_OK`, `*seed` is bytes 0..7 and `*steps` is bytes 8..11, both
little-endian. It does not check the step limit: the caller checks it
(`bd_check_request`). On `BD_NULL_ARGUMENT`, each non-`NULL` output is 0.

## `bd_encode_record` and `bd_decode_output`

`bd_encode_record(record, seed, steps)` writes exactly 12 bytes at `record`
(writable for 12 bytes): the seed bytes 0..7 and the steps bytes 8..11,
little-endian, the layout that `bd_decode_record` reads. A `NULL` `record`
gives `BD_NULL_ARGUMENT` and nothing is written.

`bd_decode_output(output, result)` reads one 16-byte output record at
`output` (readable for 16 bytes): `result->checksum` from bytes 0..7 and
`result->state` from bytes 8..15, little-endian. A `NULL` `output` or
`result` gives `BD_NULL_ARGUMENT`; a non-`NULL` `result` is then all zero.

Callers (the program, the tests and the later workers) use these two
functions instead of their own byte code.

## `bd_check_request`

| Parameter | Nullable | Domain | Result outside the domain |
|---|---|---|---|
| `request` | yes | readable for `length` bytes | `NULL` → `BD_NULL_ARGUMENT` |
| `length` | n/a | 12 to 172,032, a multiple of 12 | 0 → `BD_EMPTY_REQUEST`; above 172,032 (to `SIZE_MAX`) → `BD_TOO_MANY_RECORDS`; else not a multiple of 12 → `BD_PARTIAL_RECORD` |
| step fields | n/a | each 0 to 1,000,000 | above → `BD_STEPS_TOO_LARGE` |
| `records` | yes | writable `size_t` | `NULL` → `BD_NULL_ARGUMENT` |

Validation order (the first failure is returned):

1. `request` or `records` is `NULL` → `BD_NULL_ARGUMENT`.
2. `length == 0` → `BD_EMPTY_REQUEST`.
3. `length > 172,032` → `BD_TOO_MANY_RECORDS`. This check happens before any
   byte is read, so a `length` larger than the buffer (for example
   `SIZE_MAX`) is safe.
4. `length % 12 != 0` → `BD_PARTIAL_RECORD`.
5. Any record with k > 1,000,000 → `BD_STEPS_TOO_LARGE`.

On `BD_OK`, `*records` is `length / 12`. On any other status, `*records` is 0
when `records` is not `NULL`.

## `bd_digest_request`

| Parameter | Nullable | Domain | Result outside the domain |
|---|---|---|---|
| `request`, `length` | as `bd_check_request` | | as `bd_check_request` |
| `out` | yes | writable for `capacity` bytes | `NULL` → `BD_NULL_ARGUMENT` |
| `capacity` | n/a | at least 16n | smaller → `BD_BUFFER_TOO_SMALL` |
| `written` | yes | writable `size_t` | `NULL` → `BD_NULL_ARGUMENT` |

Validation order: `request`, `out` or `written` `NULL` →
`BD_NULL_ARGUMENT`; then the `bd_check_request` order 2 to 5; then
`capacity < 16n` → `BD_BUFFER_TOO_SMALL`; then an overlap → `BD_OVERLAP`.
The function validates the whole request before it writes any output byte.

Overlap (N1-A01): the request bytes `request[0 .. length)` and the output
bytes that the call writes, `out[0 .. 16n)`, must not share a byte. The
function writes output record i before it reads request record i + 1, so an
in-place or overlapping call (for example one shared memory region) would
give wrong output. The function refuses such a pair with `BD_OVERLAP`, and it
writes nothing. Adjacent regions in either order are not an overlap, and
output capacity after `16n` may cover the request bytes. The check uses only
pointer equality (`p == base + i` within one declared region), which C
defines for pointers into different objects; no pointer becomes an integer.
It runs after the length and capacity checks, so it reads no byte and
forms no pointer outside the declared regions.

On `BD_OK`: `out[0 .. 16n)` holds the output records, `*written` is 16n, and
the bytes `out[16n .. capacity)` do not change. On any other status:
`*written` is 0 when `written` is not `NULL`, and no byte of `out` changes.

## `bd_status_name`

Returns a pointer to a static, immutable string that is the enumerator name
(for example `"BD_STEPS_TOO_LARGE"`). Any value outside the enumeration
returns `"BD_UNKNOWN"`. The caller must not free or modify the string.

## `bd_main` and the program `bd-digest`

`src/main.c` only calls `bd_main(argc, argv, stdout, stderr)`.

Inputs:

- `argc` is the argument count; `argv` holds at least `argc` readable
  pointers, and it is read only when `argc == 3`.
- `argv[1]` is SEED and `argv[2]` is STEPS: decimal texts of 1 to 20 ASCII
  digits, no sign, no space. SEED is at most 18,446,744,073,709,551,615 and
  STEPS at most 4,294,967,295. A `NULL` text, an empty text, a non-digit byte,
  more than 20 digits or a larger value gives `BD_INVALID_NUMBER`. The parser
  reads at most 21 bytes of a text.
- STEPS in 1,000,001 to 4,294,967,295 parses, and the request then gives
  `BD_STEPS_TOO_LARGE`.
- `out` and `err` are valid streams, borrowed for the call. A stream that
  rejects writes is a defined input.

| Condition | Writes | Returns |
|---|---|---|
| `argc != 3` | `usage: bd-digest SEED STEPS` and a newline on `err` | 2 |
| SEED or STEPS invalid, or the request fails | `bd-digest: <STATUS_NAME>` and a newline on `err` | 1 |
| success, and the write and flush on `out` succeed | `<checksum> <state>` as two 16-digit lower-case hex numbers and a newline on `out` | 0 |
| success, but the write or flush on `out` fails | as much as the stream accepts | 1 |

`bd_main` encodes the one record with `bd_encode_record`, calls
`bd_digest_request` and reads the result with `bd_decode_output`, so the
program path is the request path. It allocates no memory.

## `bd_check_vectors`, `bd_kernel_report` and the program `bd-kernel`

`bd-kernel` is the native C kernel program of the bench-demo project (task
N2; N3 adds the framework kernel handshake for timing with no Python in the
path, in module `bd_wire`: specs/project/bd_wire.md). It is the project's `run` program, `bd-kernel --self-check`, and the
smoke of `./tools/safety bench native-build`.

`bd_check_vectors(vectors, count, mismatches)`:

| Parameter | Nullable | Domain | Result outside the domain |
|---|---|---|---|
| `vectors` | yes | readable for `count` vectors | `NULL` → `BD_NULL_ARGUMENT` |
| `count` | n/a | 1 to 32 (`BD_CHECK_VECTORS_MAX`) | 0 → `BD_EMPTY_REQUEST`; above 32 (to `SIZE_MAX`) → `BD_TOO_MANY_RECORDS`, checked before any vector is read |
| vector steps | n/a | each 0 to 1,000,000 | above → `BD_STEPS_TOO_LARGE` (from `bd_digest_request`) |
| `mismatches` | yes | writable `size_t` | `NULL` → `BD_NULL_ARGUMENT` |

It encodes the vectors as one request in a local buffer, calls
`bd_digest_request` (the route entry) into a local output buffer and counts
the vectors whose output checksum or state differs. On `BD_OK`,
`*mismatches` is that count; on any other status it is 0 when `mismatches`
is not `NULL`. It allocates no memory.

`bd_kernel_report(vectors, count, out, err)` returns 0 after it writes
`bd-kernel: self-check PASS <count> vectors` and a newline on `out` and the
write and flush succeed. It returns 1 and writes `bd-kernel: <STATUS_NAME>`
on `err` for a status other than `BD_OK`, `bd-kernel: self-check FAIL <m> of
<count> differ` on `err` for m > 0 mismatches, or nothing more when the
write or flush on `out` fails.

`bd_kernel_main(argc, argv, out, err)`: with `argc == 2` and `argv[1]` equal
to `--self-check` it returns `bd_kernel_report` of the 19 built-in vectors.
The built-in rows are the generated rows of `tests/project/test_bd_digest.c`
in the same order; `benchmarks/project/python/tests/test_demo.py` checks
that they equal the generator output. Any other `argc`, a `NULL`, empty or
different `argv[1]` writes `usage: bd-kernel --self-check` and a newline on
`err` and returns 2. `argv` is read only when `argc == 2`.

## Ownership, lifetimes and concurrency

- Every pointer argument is borrowed for the duration of the call only. No
  function keeps a pointer after it returns.
- The module allocates no memory, uses no global mutable state and does no
  I/O except `bd_main`, `bd_kernel_report` and `bd_kernel_main` on their
  two streams.
- `request` and `out` of `bd_digest_request` are distinct, non-overlapping
  regions (refused with `BD_OVERLAP` otherwise).
- Every function is reentrant. Calls on different buffers can run at the same
  time on different threads. Calls that share an output object need external
  synchronization.

## Invariants

- No function reads past `request + length` or `record + 12`, or writes past
  `out + capacity`.
- All size arithmetic happens after `length <= 172,032`, so `16n` cannot
  wrap.

## Test vectors

The Python reference generates the expected values
(`benchdemo/vectors.py`). The bench check `demo-vectors` writes the block in
a bench container, and the block is copied into `tests/project/test_bd_digest.c`
between the BEGIN and END lines. The project unit test
`benchmarks/project/python/tests/test_demo.py` compares that block with the
generator output byte for byte. A vector never changes to match the C code.

## Derived tests

`tests/project/test_bd_digest.c`:

| Assertion | Cases |
|---|---|
| Vectors | 19 (seed, k) records through `bd_digest_record` and as one request: seed 0, seed `BD_ZERO_SEED`, seed 1, seed `UINT64_MAX`, high-bit seeds; k 0, 1, 2, 3, small, 999,999 and 1,000,000 |
| Anchors | k = 0 gives the offset basis and the mapped seed; one hand-computed step from seed 1 (state 0x40822041; checksum 0x37e2fbafd55e2536, the FNV-1a 64 of its 8 bytes computed outside the module); seed 0 equals seed `BD_ZERO_SEED` |
| Maximum request | exactly 14,336 records (seed i × 0x9E3779B97F4A7C15, k = i mod 31): the FNV-1a of the whole 229,376-byte output (by an independent byte loop) equals the generated value, and the byte after it does not change; capacity exact and exact − 1; 14,337 records, 172,033 bytes and `SIZE_MAX` → `BD_TOO_MANY_RECORDS` without a read |

`tests/project/test_bd_request.c`:

| Assertion | Cases |
|---|---|
| Length | 0, 1, 11, 12, 13, 23, 24 |
| Steps | 1, 1,000,000, 1,000,001, `UINT32_MAX`, an invalid later record |
| Capacity | 0, 1, 15, 16 for one record; 31, 32 for two |
| Order | an earlier failure wins over a later one, also with capacity 0 |
| Postconditions | on success the last output record is the digest of the last request record and the bytes after 16n do not change; on failure no output byte changes and `*written` is 0 |
| NULL arguments | each pointer of `bd_digest_request`, `bd_check_request`, `bd_decode_record`, `bd_encode_record` and `bd_decode_output`, and all at once |
| Layouts | the bytes 08..01 0D..0A decode to seed 0x0102030405060708 and steps 0x0A0B0C0D, and `bd_encode_record` writes exactly these 12 bytes and not the 13th; the output bytes 08..01 10..09 decode to checksum 0x0102030405060708 and state 0x090A0B0C0D0E0F10 |
| Overlap | in one 64-byte area: the output just after or just before the request and capacity after 16n over the request → `BD_OK`; the same start, the output on the last request byte, the request on the last output byte, the request inside the output and the output inside the request → `BD_OVERLAP` with no byte changed; a steps failure and a capacity failure win over an overlap |
| Status names | every enumerator (with `BD_OVERLAP`); the value 9 → `BD_UNKNOWN` |

`tests/project/test_bd_main.c`: `argc` 1, 2 and 4 → 2; SEED 0 STEPS 0 → 0
and the exact text `cbf29ce484222325 9e3779b97f4a7c15`; other valid inputs
compare with `bd_digest_record`; STEPS 1,000,000 → 0; STEPS 1,000,001 and
4,294,967,295 → `BD_STEPS_TOO_LARGE`; STEPS 4,294,967,296, SEED
18,446,744,073,709,551,616 (add wraps), 99,999,999,999,999,999,999 (multiply
wraps), a 21-digit text, an empty text, `-1`, `+1`, ` 1`, `1x`, `/` and `:`
neighbours of the digits and a `NULL` text → `BD_INVALID_NUMBER`; an `out`
stream opened only for reading → 1.

`tests/project/test_bd_kernel.c` (`bd_check_vectors`): three generated rows
→ 0 mismatches; a changed checksum → 1; a changed checksum and a changed
state in two rows → 2; a changed state alone → 1; one vector and exactly 32
vectors → `BD_OK`; 0 → `BD_EMPTY_REQUEST`; 33 and `SIZE_MAX` →
`BD_TOO_MANY_RECORDS`; steps 1,000,001 → `BD_STEPS_TOO_LARGE`; `NULL`
vectors or `NULL` mismatches → `BD_NULL_ARGUMENT`; the mismatch count is 0
on every failure; `bd_kernel_report` with an `out` stream opened only for
reading → 1.

`tests/project/test_bd_kernel_main.c`: `bd_kernel_report` PASS, FAIL (1 of
3), `BD_EMPTY_REQUEST` and `BD_NULL_ARGUMENT` texts and results;
`bd_kernel_main` with `--self-check` → 0 and `bd-kernel: self-check PASS 19
vectors`; `argc` 1 and 3, `--self-chec`, `--self-check2`, an empty text and
a `NULL` `argv[1]` → the usage line and 2.

`fuzz/project/bd_decode_fuzz.c` checks the decoder for arbitrary request
bytes. An independent oracle predicts the `bd_check_request` status and
count from the length and the step fields. For a valid request every record
decodes to the oracle's fields; when the steps of the whole request are at
most 65,536 the target also checks `bd_digest_request` with the capacities
0, exact − 1 and exact: the status, `*written`, the per-record digest and
the unchanged byte after the output.
