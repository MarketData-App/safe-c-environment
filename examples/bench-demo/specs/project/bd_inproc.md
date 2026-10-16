# Module `bd_inproc` specification

Status: example specification for the bench-demo project (plan amendment
FR6, task N3, ruling FR6-R3 item 2). Write and review this file before any
module source changes. The module uses `bd_digest` and is the only module
of the shared library `libbd_inproc.so` (project.json `libraries`), which
exports exactly `bd_inproc_abi_version` and `bd_inproc_digest`.

## Files

| File | Contents |
|---|---|
| `include/bd_inproc.h` | the ABI version, the return values and the two exports |
| `src/bd_inproc.c` | `bd_inproc_abi_version`, `bd_inproc_digest` |

## Purpose

The framework loader `benchlab.native_inproc` loads the library in a bench
caller child after it verified the file's sha256, checks that
`bd_inproc_abi_version()` returns 2 (`ABI`), and calls `bd_inproc_digest`
through ctypes with the GIL released. The Python codec
(`benchdemo.native`) passes the request and output buffers. The framework
fixes the ABI version (2) and checks `n`, `threads` and `selector_mask`
before the call; the codec names the argument list (`ARGTYPES`). The
bench-demo list passes the request bytes and their length as one buffer;
it passes no float64 input columns (`check_column`).

## `bd_inproc_digest`

`int bd_inproc_digest(const unsigned char *request, size_t length, size_t n,
uint32_t threads, uint32_t request_index, uint32_t selector_mask, unsigned
char *out, size_t capacity, unsigned char *scratch, size_t scratch_len)`

Checks, in this order, before any output byte is written:

| Check | Return |
|---|---|
| `scratch` `NULL` or `scratch_len` < 48 | 24 `BD_INPROC_BAD_SCRATCH` |
| (then the echo is written, see below) | |
| `n` = 0 or `n` > 14,336 (to `SIZE_MAX`) | 20 `BD_INPROC_BAD_RECORDS` |
| `length` ≠ 12·n | 21 `BD_INPROC_BAD_LENGTH` |
| `threads` ≠ 0 (the codec has no pool) | 22 `BD_INPROC_BAD_THREADS` |
| `selector_mask` ≠ 1 (the only selector the codec defines) | 23 `BD_INPROC_BAD_SELECTOR` |
| `bd_digest_request(request, length, out, capacity, &written)` | its `bd_status` value: 0 OK, 1 `NULL` request or out, 5 steps above 1,000,000, 6 capacity below 16·n, 8 overlap |

Echo: after the scratch check, the last 48 bytes of `scratch` receive six
little-endian u64 values: `n`, `length`, `threads`, `request_index`,
`selector_mask`, `capacity` (the arguments as received). `request_index`
has no other effect. On OK, `out[0, 16n)` holds the output records and no
other byte of `out` changes; on any other return no byte of `out` changes.

`bd_inproc_abi_version()` returns 2.

## Ownership, lifetimes and concurrency

- Every pointer is borrowed for the call only. The caller keeps `request`,
  `out` and `scratch` alive and unchanged by others until the call returns
  (the framework `call` holds a reference to every buffer).
- `scratch` must not overlap `request` or `out` (caller obligation; the
  framework passes three distinct bytearrays). `request` and `out` must not
  overlap (refused with 8 `BD_OVERLAP`).
- No allocation, no global mutable state, no I/O. The function is
  reentrant; calls on distinct buffers may run on different threads.

## Derived tests

`tests/project/test_bd_inproc.c`: the ABI version; four records with the
echo values, the untouched scratch bytes before the echo and the output
equal to `bd_digest_request`; the echo of a refused call with an exact
48-byte scratch; fifteen refusals in order (scratch 47 and 0, records 0,
14,337 and `SIZE_MAX`, length 11 and 24, threads 1 and 4, selectors 0, 2,
31 and `UINT32_MAX`, capacity 15 and 0) with the first output byte
unchanged; `NULL` scratch, request and out; steps 1,000,001; an
overlapping output; the largest request (14,336 records) with the byte
after the output unchanged; one record.

`fuzz/project/bd_inproc_fuzz.c`: arbitrary threads, selector, record-count
and capacity offsets and scratch lengths around a fuzzed request; an
independent oracle predicts the return value; the echo, the unchanged
output on a refusal and the output against `bd_digest_request` on success.
