# Module `entry` specification

Status: framework fixture. This project qualifies the closed `libraries` field of
`project.json` (spec Amendment F item 3) in every gate build. It is not an
application.

## Files

| File | Contents |
|---|---|
| `include/entry.h` | public interface |
| `src/entry.c` | `fixture_entry` (the exported library entry point) and `fixture_run` |
| `src/main.c` | `main` of `fixture-run`, which only calls `fixture_run` |

The library `fixture_entry` (`libfixture_entry.so`) holds the whole module and
exports only the symbol `fixture_entry`. Every other symbol is local.

## `fixture_entry`

```c
int fixture_entry(const double *x, size_t n, double *out);
```

- Inputs: `x` points to at least `n` readable `double` values that the caller
  owns; `out` points to one writable `double` that the caller owns. Both are
  borrowed for the call only. `x` and `out` may be NULL; the call then fails.
- Limits: `n` is in [1, `FIXTURE_ENTRY_MAX`] = [1, 64].
- Output: on success, `*out` is the binary64 sum of `x[0]` .. `x[n - 1]`, added
  in index order from `0.0`, and the result is 0.
- Failure: the result is 1 when `x` is NULL, `out` is NULL, `n` is 0 or
  `n` > 64. Then the call reads no element of `x` and does not write `*out`.
- Invariants: no static mutable state, no allocation, no I/O. Overflow to an
  infinity and NaN inputs follow IEEE 754 addition; they are not errors.

## `fixture_run`

```c
int fixture_run(int argc, char **argv);
```

- Returns 2 unless `argc` is 2, `argv` is not NULL and `argv[1]` is not NULL and
  equals `--self-check` exactly. The comparison stops at the first differing
  byte, so it never reads past the end of a shorter argument.
- Otherwise it calls `fixture_entry` with {1.0, 2.0, 3.5} and returns 0 when the
  call succeeds with the sum 6.5, else 1.

## Tests

`tests/project/test_entry.c` covers NULL `x` and `out`, `n` = 0, 1, 2, 64, 65
and `SIZE_MAX`, an unchanged `*out` after each refusal, a signed sum, and the
argument lists: exact, missing, extra, NULL argv, NULL argument, prefix, longer
and empty argument. The fuzz target `entry` calls `fixture_entry` with every
input length, including lengths above 64 with a 64-value buffer, and with NULL
pointers.
