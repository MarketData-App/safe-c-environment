# Module `greeting` specification

Status: example specification for the hello-world project. Write and review
this file before `src/greeting.c` changes.

## Purpose

`greeting_format` writes the text `Hello, <name>!` and a terminating NUL byte
into a buffer that the caller owns. The program `hello` calls it with its one
command-line argument, so `name` is external input.

## Interface

```c
enum greeting_status greeting_format(const char *name, size_t name_len, char *out,
                                     size_t capacity, size_t *written);
```

`GREETING_NAME_MAX` is 64.

## Inputs and limits

| Parameter | Nullable | Domain | Result outside the domain |
|---|---|---|---|
| `name` | yes | readable for `name_len` bytes; need not be NUL-terminated | `NULL` → `GREETING_NULL_ARGUMENT` |
| `name_len` | n/a | 1 to `GREETING_NAME_MAX` (64) | 0 → `GREETING_EMPTY_NAME`; 65 to `SIZE_MAX` → `GREETING_NAME_TOO_LONG` |
| name bytes | n/a | complete, shortest-form UTF-8; code points U+0000..U+D7FF and U+E000..U+10FFFF | invalid → `GREETING_INVALID_UTF8` |
| code points | n/a | printable: no C0 control (U+0000..U+001F), no DEL (U+007F), no C1 control (U+0080..U+009F) | → `GREETING_NOT_PRINTABLE` |
| `out` | yes | writable for `capacity` bytes | `NULL` → `GREETING_NULL_ARGUMENT` |
| `capacity` | n/a | at least `8 + name_len + 1` bytes | smaller → `GREETING_BUFFER_TOO_SMALL` |
| `written` | yes | writable `size_t` | `NULL` → `GREETING_NULL_ARGUMENT` |

Invalid UTF-8 includes: a lead byte 0x80..0xC1 or 0xF5..0xFF, a sequence cut
off by `name_len`, a continuation byte outside 0x80..0xBF, an overlong form, a
UTF-16 surrogate (U+D800..U+DFFF) and a code point above U+10FFFF.

## Validation order

The function checks the conditions in this order and returns the first failure:

1. `name`, `out` or `written` is `NULL` → `GREETING_NULL_ARGUMENT`.
2. `name_len == 0` → `GREETING_EMPTY_NAME`.
3. `name_len > GREETING_NAME_MAX` → `GREETING_NAME_TOO_LONG`. This check
   happens before the function reads any name byte, so a `name_len` larger
   than the readable name buffer (for example `SIZE_MAX`) is safe.
4. Any invalid UTF-8 in the whole name → `GREETING_INVALID_UTF8`. Invalid
   UTF-8 wins over an earlier non-printable code point.
5. Any non-printable code point → `GREETING_NOT_PRINTABLE`.
6. `capacity < 8 + name_len + 1` → `GREETING_BUFFER_TOO_SMALL`.

## Ownership and lifetimes

- `name`, `out` and `written` are borrowed for the duration of the call only.
  The function keeps no pointer after it returns.
- `greeting_format` allocates no memory, uses no global mutable state and does
  no I/O.

## Output

On `GREETING_OK`:

- `out[0 .. 8 + name_len]` holds `Hello, `, the `name_len` name bytes, `!` and
  NUL, in that order;
- `*written` is `8 + name_len`, the byte count before the NUL;
- bytes at `out[8 + name_len + 1 .. capacity)` are unchanged.

## Failure behaviour

On any other status:

- `out[0]` is NUL when `out` is not `NULL` and `capacity > 0`;
- `*written` is 0 when `written` is not `NULL`;
- no other byte of `out` changes.

## Concurrency

The function is reentrant. Calls on different buffers can run at the same
time on different threads. Calls that share an `out` or `written` object need
external synchronization.

## Invariants

- The function never reads past `name + name_len` and never writes past
  `out + capacity`.
- All size arithmetic happens after `name_len <= 64`, so it cannot wrap.

## `greeting_status_name`

```c
const char *greeting_status_name(enum greeting_status status);
```

Returns a pointer to a static, immutable string that is the enumerator name
(for example `"GREETING_NOT_PRINTABLE"`). Any value outside the enumeration
returns `"GREETING_UNKNOWN"`. The caller must not free or modify the string.
The function has no side effects and is reentrant.

## `greeting_main` and the program `hello`

```c
int greeting_main(int argc, char **argv, FILE *out, FILE *err);
```

`src/main.c` only calls `greeting_main(argc, argv, stdout, stderr)`, so all
program behaviour is in the module and the unit tests reach every path.

Inputs:

- `argc` is the argument count. `argv` must hold at least `argc` readable
  pointers; it is read only when `argc == 2`.
- `argv[1]` is nullable. A `NULL` name gives `GREETING_NULL_ARGUMENT`.
- `argv[1]`, when not `NULL`, is NUL-terminated. `greeting_main` reads at
  most `GREETING_NAME_MAX + 1` bytes of it, so a longer argument gives
  `GREETING_NAME_TOO_LONG` without a scan of the whole argument.
- `out` and `err` are valid streams open for writing, borrowed for the call.

Behaviour:

| Condition | Writes | Returns |
|---|---|---|
| `argc != 2` | `usage: hello NAME` and a newline on `err` | 2 |
| `greeting_format` fails | `hello: <STATUS_NAME>` and a newline on `err` | 1 |
| success, and the write, newline and flush on `out` all succeed | the greeting and a newline on `out` | 0 |
| success, but a write, newline or flush on `out` fails | as much as the stream accepts | 1 |

`greeting_main` always attempts the write, the newline and the flush, then
reports one combined result. Write errors on `err` are ignored, because no
other channel is left to report them. `greeting_main` allocates no memory.
Calls are reentrant when they use different streams.

## Derived tests

`tests/project/test_greeting.c` holds one check for each row below. The
boundary rows are zero, one, the exact limit, one past the limit and the
representable maximum.

| Assertion | Cases |
|---|---|
| NULL arguments | `name`, `out`, `written` each `NULL`; all `NULL` with `capacity` 0 |
| Length bounds | 0, 1, 64, 65, `SIZE_MAX` |
| UTF-8 | valid 2-, 3- and 4-byte forms; U+10FFFF; U+E000; lone 0x80; 0xC0 0xAF; 0xF5 lead; 0xFF; truncated 2- and 3-byte forms; bad continuation; overlong 3- and 4-byte forms; U+D800; U+DFFF; U+110000 |
| Printable | U+001F, U+0020, U+007E, U+007F, NUL inside the name, tab, U+0080, U+0085, U+009F, U+00A0 |
| Order | control byte then invalid UTF-8 → `GREETING_INVALID_UTF8`; each earlier failure with `capacity` 0 |
| Capacity | 0, 1, exact − 1 (13 for `world`, 72 for 64 bytes), exact (14, 73), large (128) |
| Status names | every enumerator; the value 7 → `GREETING_UNKNOWN` |
| `greeting_main` | `argc` 1 and 3 → 2; `world` → 0 and `Hello, world!`; tab name, `NULL` name and a 70-byte name → 1 and the status name; a read-only `out` stream → 1 |

`fuzz/project/greeting_fuzz.c` checks the output and failure postconditions for
arbitrary names with the capacities 0, 1, exact − 1, exact and 128: the exact
greeting bytes, `*written`, `out[0]` on failure, and that no other byte of the
buffer changes. An independent oracle (the well-formed sequences of Unicode
Table 3-7 plus the C0, DEL and C1 rules) predicts the status of every input.
