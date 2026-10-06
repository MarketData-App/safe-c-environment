# Hello-world example project

This example shows the full safe-C chain on a small program:

- a specification with input limits: `specs/project/greeting.md`;
- a public interface: `include/greeting.h`;
- the implementation: `src/greeting.c`, `src/greeting_text.c` (with the
  internal header `include/greeting_text.h`), `src/greeting_main.c` and the
  program `src/main.c`;
- boundary and error tests: `tests/project/test_greeting.c` and
  `tests/project/test_greeting_main.c`;
- a libFuzzer target with a seed corpus: `fuzz/project/greeting_fuzz.c`;
- a review ledger: `review/ledger.json`. Its finding GREETING-0001 is an
  illustrative example entry, not a record of a real external review;
- the project declaration: `project.json` (targets only, no flags).

`./tools/safety instantiate` copies these files into a new project as the
starting code.

## Run the checks

From the repository root:

```sh
./tools/safety project check --project examples/hello-world --development
```

This command builds the example: the project command sets
`SAFE_C_PROJECT_DIR`, and only then does the framework root `CMakeLists.txt`
read `project.json` and build the project targets. The example has no
`CMakeLists.txt` of its own. In an instantiated project, run
`./tools/safety project check` from the project root. The command runs every
gate in one SDK container, then starts `hello world` once in the runtime image
and requires exit status 0.

Expected output: one line per gate with `PASS`, then the verdict. The report is
`artifacts/project-report.json`. The target time for a full run of this example
on a GitHub-hosted Linux x86-64 runner is 6 to 10 minutes, including 30 seconds
of fuzz exploration. This is a design target; it is not measured yet. A failure
stops the run with a non-zero exit status and names the gate and the evidence
file.

Run the program directly after a build:

```sh
hello world      # prints "Hello, world!", exit status 0
hello            # usage on stderr, exit status 2
hello $'\t'      # "hello: GREETING_NOT_PRINTABLE" on stderr, exit status 1
```

## The 23 gates

| Gate | What it checks |
|---|---|
| `format` | Every project `.c` and `.h` file matches the repository `.clang-format`. |
| `gcc-O0` | GCC build at `-O0` with the full `cmake/Safety.cmake` warning set as errors; all tests pass. |
| `gcc-O2` | The same with GCC at `-O2`. |
| `clang-O0` | The same with Clang at `-O0`. |
| `clang-O2` | The same with Clang at `-O2`. |
| `hardened` | Build with `_FORTIFY_SOURCE=3`, strong stack protector and stack-clash protection; all tests pass. |
| `tidy` | `clang-tidy` with the repository `.clang-tidy`, warnings as errors. |
| `csa` | Clang Static Analyzer reports no warning. |
| `gcc-analyzer` | GCC `-fanalyzer` reports no warning. |
| `ast` | API policy gate from `safety/foundation-api-policy.json`: no banned calls (`gets`, `strcpy`, `strcat`, `sprintf`, `atoi`, `system`, `popen`, `alloca`), no raw memory functions, no raw array indexing, no indirect calls, no inline assembly or sanitizer exclusions. |
| `asan` | All tests under AddressSanitizer, no recovery. |
| `ubsan` | All tests under UndefinedBehaviorSanitizer, no recovery. |
| `integer` | All tests under the integer sanitizer (unsigned wrap and implicit conversions), no recovery. |
| `msan` | All tests under MemorySanitizer (uninitialized reads), no recovery. |
| `tsan` | All tests under ThreadSanitizer, no recovery. |
| `unit` | The module tests in `tests/project/` pass. |
| `integration` | The program runs with the `run.args` from `project.json` and exits with status 0. |
| `coverage` | Project code reaches at least 90% line and 85% branch coverage (`safety/contract.json`). |
| `fuzz-replay` | Every seed and saved regression input runs without a crash. |
| `fuzz-exploration` | Each fuzz target runs for a bounded time (30 seconds, never lower) without a crash. |
| `clusterfuzzlite` | Builds each fuzz target with the ClusterFuzzLite build contract and audits sanitizer and coverage instrumentation. |
| `inventory` | Every project file is declared in `project.json`, every module has a spec and tests, and every module that reads external input has a fuzz target. |
| `review-protocol` | `review/ledger.json` is schema-valid and has no OPEN, UNRESOLVED or BLOCKED high-severity finding. |

## Why the code looks this way

- The tests, the fuzz target and the implementation use pointer arithmetic
  instead of `a[i]`, because the `ast` gate rejects raw indexing in project
  code. The AST policy also rejects `memset` and `memcpy` in non-boundary
  files; `memcmp` and `strncmp` are permitted.
- `greeting_format` checks `name_len` before it reads any name byte, so a
  caller that passes `SIZE_MAX` gets `GREETING_NAME_TOO_LONG` and no read past
  the buffer.
- `hello` reads at most 65 bytes of its argument for the same reason.
- `src/main.c` only calls `greeting_main`. The program logic is in the module,
  so the unit tests reach every branch and the coverage gate measures it.
- The `gcc-analyzer` gate runs GCC `-fanalyzer` with fixed limits that a
  project cannot change. GCC analyzes a same-file function again at every call
  site, so the example splits the module into three files, drives tests from
  tables, writes `REQUIRE` and `CHECK` as macros and avoids byte loops in test
  code. The spec section "Test structure and the analyzer budget" lists the
  rules.
