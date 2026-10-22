# Module `models` specification

Status: Phase 2 Tasks 1, 7, 8, 9, 10, 11, 10a and 10b (IEEE helpers, shared
types, Python-semantics helpers, the QuantLib normal functions, the term
structure, the unit-maturity mapping, BlackCalculator, the BSM engine,
Bjerksund-Stensland 1993, the CRR engine, σ_lo, the CRR domain check, the
case parameters, the Brent solver, the model objective, Barone-Adesi-Whaley,
Andersen-Lake-Offengenden and the row evaluation of the five models of
`MODELS5`; `PL_MASK_WIRED` is `PL_MASK_MODELS5` since Task 10b). Write and
review this file before any module source changes.

## Files

| File | Contents |
|---|---|
| `include/pl_types.h` | shared types and constants of the C pricer |
| `include/pl_ieee.h`, `src/pl_ieee.c` | IEEE-754 binary64 helpers; `pl_close` is transcribed from QuantLib 1.43 (attribution block in the file, row in `NOTICE-QuantLib.md`) |
| `tests/project/test_ieee.c` | boundary tests of the IEEE helpers and the Python-semantics helpers |
| `include/pl_normal.h`, `src/pl_normal.c` | QuantLib 1.43 `ErrorFunction`, `NormalDistribution` and `CumulativeNormalDistribution` (attribution block in the file, row in `NOTICE-QuantLib.md`) |
| `include/pl_vec_helpers.h` | generated vectors of `optionlab.models` `_exp`, `_log`, `_sqrt` (check `c-vectors`, part `helpers`); never edited by hand |
| `include/pl_vec_normal.h` | generated vectors of `optionlab.normal` (check `c-vectors`, part `normal`); never edited by hand |
| `tests/project/test_normal.c` | bit-exact comparison of `pl_normal.c` with the vectors |
| `include/pl_black.h`, `src/pl_black.c`, `src/pl_bsm.c` | QuantLib 1.43 term-structure arithmetic, the unit-maturity mapping and `BlackCalculator` (`pl_black.c`), and `AnalyticEuropeanEngine` (`pl_bsm.c`) (attribution block in each file, rows in `NOTICE-QuantLib.md`) |
| `include/pl_vec_black.h` | generated vectors of `optionlab.models` (tables `black` and `black_calc`; check `c-vectors`, part `black`); never edited by hand |
| `tests/project/test_black.c` | bit-exact comparison of `pl_black.c` with the vectors |
| `include/pl_bjs.h`, `src/pl_bjs_phi.c`, `src/pl_bjs.c` | QuantLib 1.43 `BjerksundStenslandApproximationEngine` (Bjerksund-Stensland 1993): phi and its analytic derivatives (`pl_bjs_phi.c`), the European and immediate-exercise results, `americanCallApproximation` and the engine (`pl_bjs.c`) (attribution block in each file, rows in `NOTICE-QuantLib.md`) |
| `include/pl_vec_bjs.h` | generated vectors of `optionlab.models` (tables `bjs`, `bjs_phi` and `bjs_immediate`; check `c-vectors`, part `bjs`); never edited by hand |
| `tests/project/test_bjs.c` | bit-exact comparison of `pl_bjs_phi.c` and `pl_bjs.c` with the vectors |
| `include/pl_crr.h`, `src/pl_crr.c`, `src/pl_crr_lattice.c` | QuantLib 1.43 `BinomialVanillaEngine<CoxRossRubinstein>` for the mapped problem: the tree, the engine checks and greeks, σ_lo, the CRR domain check and the case parameters (`pl_crr.c`), and the lattice reset and rollback step (`pl_crr_lattice.c`) (attribution block in each file, rows in `NOTICE-QuantLib.md`) |
| `include/pl_vec_crr.h` | generated vectors of `optionlab.models` (tables `crr`, `crr_lo`, `crr_engine` and `crr_tree`; check `c-vectors`, part `crr`); never edited by hand |
| `tests/project/test_crr.c` | bit-exact comparison of `pl_crr.c` with the vectors |
| `include/pl_solver.h`, `src/pl_solver.c`, `src/pl_objective.c` | QuantLib 1.43 `Solver1D::solve` with `Brent::solveImpl` (`pl_solver.c`; attribution block in the file, row in `NOTICE-QuantLib.md`) and the objective dispatch (`pl_objective.c`, optionlab code; its own translation unit since Task 10b for the fixed GCC analyzer budget) |
| `include/pl_vec_solver.h` | generated vectors of `optionlab.solver` (tables `solver` and `solver_edge`; check `c-vectors`, part `solver`); never edited by hand |
| `tests/project/test_solver.c` | bit-exact comparison of `pl_solver.c` with the vectors, and the defect, contract and stop rules |
| `include/pl_evaluate.h`, `src/pl_evaluate.c`, `src/pl_greeks.c` | τ_V, the order-5 check, the price dispatch and the spec 3.3 row evaluation of `optionlab.reference` (`pl_evaluate.c`), and the greek step `pl_greeks_at` (`pl_greeks.c`, its own translation unit: together they exceed the fixed GCC analyzer budget) (attribution block in each file, rows in `NOTICE-QuantLib.md`) |
| `include/pl_vec_evaluate.h` | generated vectors of `optionlab.reference` (tables `evaluate`, `evaluate_check`, `evaluate_tau` and `evaluate_greeks`; check `c-vectors`, part `evaluate`); never edited by hand |
| `tests/project/test_evaluate.c` | bit-exact comparison of `pl_evaluate.c` with the vectors, the C contract, the ALO slot and a fresh objective per row |
| `include/pl_baw.h`, `include/pl_baw_step.h`, `src/pl_baw_map.c`, `src/pl_baw_cert.c`, `src/pl_baw_admit.c`, `src/pl_baw.c`, `src/pl_baw_points.c`, `src/pl_baw_stencil.c`, `src/pl_baw_greeks.c` | QuantLib 1.43 `BaroneAdesiWhaleyApproximationEngine` and the shared `baw_admit` of spec Appendix G-BAW: the map of the critical-price iteration (`pl_baw_map.c`), the certificate (`pl_baw_cert.c`), `baw_admit` (`pl_baw_admit.c`), the critical price, S*, the engine and the admitted price (`pl_baw.c`), the greek points (`pl_baw_points.c`), one attempt of each stencil (`pl_baw_stencil.c`) and the greek step (`pl_baw_greeks.c`); seven translation units for the fixed GCC analyzer budget (attribution block in each file, rows in `NOTICE-QuantLib.md`) |
| `include/pl_vec_baw_admit.h`, `include/pl_vec_baw_cert.h`, `include/pl_vec_baw.h`, `include/pl_vec_baw_greeks.h`, `include/pl_vec_evaluate_baw.h` | generated vectors (check `c-vectors`, parts `baw_admit`, `baw_cert`, `baw`, `baw_greeks`, `evaluate_baw`); never edited by hand |
| `tests/project/test_baw_admit.c`, `test_baw_cert.c`, `test_baw.c`, `test_baw_greeks.c`, `test_evaluate_baw.c` | bit-exact comparison of the BAW files with the vectors; one test file per header (the 32 MiB AST dump limit of the source-policy gate) |
| `include/pl_alo.h`, `include/pl_alo_equation.h`, `include/pl_alo_step.h`, `src/pl_alo_equation.c`, `src/pl_alo.c`, `src/pl_alo_run.c`, `src/pl_alo_cheb.c`, `src/pl_alo_qdeval.c`, `src/pl_alo_qdplus.c`, `src/pl_alo_fp.c`, `src/pl_alo_sweep.c`, `src/pl_alo_node.c`, `src/pl_alo_tables.c`, `src/pl_alo_ts.c`, `src/pl_alo_ts_row0.c`, `src/pl_alo_ts_level.c`, `src/pl_alo_ts_ends.c`, `src/pl_alo_ts_sum.c`, `src/pl_alo_points.c`, `src/pl_alo_stencil.c`, `src/pl_alo_greeks.c`, `src/pl_alo_edge.c` | QuantLib 1.43 `QdFpAmericanEngine` with accurateScheme (Andersen-Lake-Offengenden, spec Amendment I and Appendix I-ALO): the shared `alo_equation` and `alo_segment` (`pl_alo_equation.c`), the engine (`pl_alo.c`), the run state, NaN check, guards and caps (`pl_alo_run.c`), the Chebyshev interpolation (`pl_alo_cheb.c`), the QD+ evaluator and boundary (`pl_alo_qdeval.c`, `pl_alo_qdplus.c`), the fixed-point equations, one sweep and its node update (`pl_alo_fp.c`, `pl_alo_sweep.c`, `pl_alo_node.c`), the frozen tables (`pl_alo_tables.c`), the tanh-sinh integral (`pl_alo_ts.c`, row 0 `pl_alo_ts_row0.c`, the level `pl_alo_ts_level.c`, its ends `pl_alo_ts_ends.c` and row sum `pl_alo_ts_sum.c`), the greek points, the ALO solver objective, the rho and theta stencils and the greek step (`pl_alo_points.c`, `pl_alo_stencil.c`, `pl_alo_greeks.c`), the zero-volatility edge case (`pl_alo_edge.c`); nineteen translation units for the fixed GCC analyzer budget (opaque calls between them; running sums through `pl_sum2` and halvings through `pl_py_div`, the same bits); `pl_alo_step.h` is internal to the module (attribution block in each file, the Boost file-scope header in the three tanh-sinh files, rows in `NOTICE-QuantLib.md`) |
| `include/pl_vec_alo.h`, `include/pl_vec_alo_equation.h`, `include/pl_vec_alo_tables.h`, `include/pl_vec_alo_greeks.h`, `include/pl_vec_evaluate_alo.h` | generated vectors (check `c-vectors`, parts `alo`, `alo_equation`, `alo_tables`, `alo_greeks`, `evaluate_alo`); never edited by hand |
| `tests/project/test_alo.c`, `test_alo_equation.c`, `test_alo_greeks.c`, `test_evaluate_alo.c`, `include/pl_test_alo.h` | bit-exact comparison of the ALO files with the vectors; one generated header per test file (the 32 MiB AST dump limit); the shared row and coverage-count helpers of the table tests (`pl_test_alo.h`, a row-slice mechanism for ruling (g)); measured, each table fits in one file (alo_greeks about 4.3 s in gcc-O0, 5.5 s in tsan; evaluate_alo 2.4 s, 2.9 s), and more files exceed the memory of the source-policy step of the `ast` gate (each file preprocesses its large vector header in every configuration) |
| `include/pl_vec_evaluate_census.h`, `tests/project/test_evaluate_census.c` | the census raising rows of table `evaluate` (part `evaluate_census`, Task 10b: the census over `MODELS5` took `test_evaluate.c`, `test_batch_masks.c` and `test_batch_echo.c` past the AST dump limit) and their bsm, bjs and crr test |
| `benchmarks/project/python/optionlab/census_rows.json` | the distinct raising rows of the raise census (written by the check `c-census-generate`, before_run false; compared by the gate `c-census`, before_run true, which fails when the file is absent, not a file, unreadable or different), read by part `evaluate`; never edited by hand |

## Numeric model

- `double` is IEEE-754 binary64 (`sizeof(double) == 8`) and the compiler
  evaluates without excess precision. `test_ieee.c` checks the size at
  compile time and the precision at run time (`(1 + 2^-53) - 1 == 0`). A
  compile-time check of `FLT_EVAL_METHOD` is not possible: the source-policy
  step rejects it as a build macro whose value differs between build
  configurations (see "Probe result (Task 1)").
- The framework compiles project code with `-ffp-contract=off` (spec
  Amendment F item 3), so no multiply-add is fused.
- The Python package `optionlab` is the definition of every result (Amendment
  F item 8). Each helper returns the binary64 value that the cited Python
  expression returns, with the same sign of zero and the same NaN or infinity.

## Shared types (`pl_types.h`)

- `enum pl_model` (`MODELS5` order, mask bit `1 << model`; Amendment G13.3 and
  I1.3, the change of Task 1 content that Task 10a lands): `PL_MODEL_BSM` 0,
  `PL_MODEL_BJS` 1, `PL_MODEL_CRR` 2, `PL_MODEL_BAW` 3, `PL_MODEL_ALO` 4 (a run
  defect until Task 10b); `PL_MODELS` 5u (the result blocks);
  `PL_MASK_ALL3` 7u, `PL_MASK_MODELS4` 15u, `PL_MASK_MODELS5` 31u.
- `enum pl_status`, in the status order of spec 3.3: `PL_INVALID_INPUT` 0,
  `PL_EXPIRED` 1, `PL_NO_BID` 2, `PL_CROSSED` 3, `PL_MODEL_DOMAIN` 4,
  `PL_BELOW_MIN` 5, `PL_ABOVE_MAX` 6, `PL_NOT_CONVERGED` 7, `PL_OK` 8;
  `PL_NOT_REQUESTED` 254 (an unselected model part) and `PL_ECHO` 255 (a
  record of the echo kernel) are wire-only.
- Flags: `PL_FLAG_BELOW_INTRINSIC` 1, `PL_FLAG_BOUNDARY_AMBIGUOUS` 2,
  `PL_FLAG_FLAT_VEGA` 4, `PL_FLAG_ROUNDING_BAND` 8; `PL_FLAG_STENCIL_UNRESOLVED`
  16 and `PL_FLAG_STENCIL_SWITCHED` 32 (the `baw` and `alo` parts),
  `PL_FLAG_ADMIT_EXCLUDED` 64 (the `baw` part only).
- `enum pl_field`: `PL_IV`, `PL_PRICE`, `PL_DELTA`, `PL_GAMMA`, `PL_THETA`,
  `PL_VEGA`, `PL_RHO` (0 to 6); `PL_FIELDS` 7.
- `struct pl_params` (`crr_steps`, `sigma_hi`, `kappa_cap`, `h_r`, `h_sigma`,
  then `baw_newton_max`, the protected case parameter of record R3, and
  `baw_plant_nonfinite_sstar`, test-only, 0 in every production set),
  `struct pl_row` (`side`, `S`, `K`, `T`, `bid`, `ask`, `r`, `q`),
  `struct pl_model_result` (`status`, `flags`, `values[PL_FIELDS]`) and
  `struct pl_contract_result` (`model[PL_MODELS]`, five blocks in `MODELS5`
  order). The tasks that use them
  specify their limits.
- `PL_CRR_MAX_STEPS` 100; `enum pl_eval_error` (`PL_EVAL_OK` 0,
  `PL_EVAL_DEFECT` 1); `PL_QL_EPSILON` = 2^-52 (`0x1p-52`), QuantLib
  `QL_EPSILON`.

## IEEE helpers

All helpers are pure functions. They take values only, keep no state, read
no memory through a pointer and never fail. They are safe to call from any
thread. Every `double` input is allowed, including both zeros, subnormal
values, both infinities and every NaN bit pattern.

| Function | Inputs | Output | NaN | Signed zero |
|---|---|---|---|---|
| `uint64_t pl_double_bits(double x)` | any `x` | the 64 bits of `x` (sign bit 63, exponent bits 52-62, fraction bits 0-51) | the exact NaN bits, sign and payload kept | `-0.0` gives `0x8000000000000000`, `0.0` gives `0` |
| `double pl_bits_double(uint64_t bits)` | any `bits` | the binary64 value with these bits; `pl_double_bits(pl_bits_double(b)) == b` for every non-NaN `b` | a NaN pattern gives a NaN | `0x8000000000000000` gives `-0.0` |
| `double pl_inf(void)` | none | `+inf`, bits `0x7ff0000000000000` (Python `math.inf`) | not applicable | not applicable |
| `double pl_nan(void)` | none | the quiet NaN with bits `0x7ff8000000000000` (Python `math.nan`) | always NaN | not applicable |
| `int pl_is_nan(double x)` | any `x` | 1 when `x != x`, else 0 | 1 for every NaN | 0 for both zeros |
| `int pl_is_finite(double x)` | any `x` | 1 when `x >= -DBL_MAX && x <= DBL_MAX`, else 0 (Python `math.isfinite`) | 0 | 1 for both zeros |
| `double pl_fabs(double x)` | any `x` | `x` with bit 63 cleared (Python `math.fabs` and `abs`) | a NaN keeps its payload; the sign bit is cleared | `-0.0` gives `0.0` |
| `double pl_max(double a, double b)` | any `a`, `b` | `(a < b) ? b : a` (Python `max(a, b)`, `optionlab` `_max`, `std::max`) | a NaN `a` gives `a`; a NaN `b` gives `a` | a tie (`0.0`, `-0.0`) keeps `a` |
| `int pl_close(double x, double y)` | any `x`, `y` | QuantLib `close(x, y)` as `models.close` (models.py:88-93): 1 when `x == y`; else with `diff = |x - y|` and `tolerance = 42.0 * QL_EPSILON`: when `x == 0.0` or `y == 0.0`, `diff < tolerance * tolerance`; otherwise `diff <= tolerance * |x|` and `diff <= tolerance * |y|` | 0 when either is NaN | `close(0.0, -0.0)` is 1 |

The helpers of this section use no libm function and no compiler builtin: the project AST
gate rejects the C classification macros (see "Probe result (Task 1)").
Bit access goes through `union { uint64_t u; double d; }`, which C17 defines
(6.5.2.3, footnote 97). `pl_fabs` clears the sign bit through the bits; it
gives the same result as `fabs` without libm.

Error behavior: none. No helper reports an error.

Tests (`tests/project/test_ieee.c`): no excess precision; bit patterns of `1.0`, `-0.0`, `5.0`,
`+inf`, NaN and the smallest subnormal; classification of NaN, `+-inf`,
`+-0.0`, `+-DBL_MAX`, `DBL_MIN` and the smallest subnormal; `pl_fabs` of
`-0.0`, `-2.5`, `-inf` and a negative NaN; `pl_max` order, both tie orders
and both NaN positions; `pl_close` for equal values, the zero branch on each
side at `1e-29` (inside) and `1e-28` (outside), relative differences of 4 and
64 `QL_EPSILON`, the asymmetric case `2.0` against `2.0 - 84 QL_EPSILON` in both
argument orders (within `tolerance * |x|`, outside `tolerance * |y|`), negative
values, opposite signs and NaN.

## Python-semantics helpers

`optionlab.models` wraps four `math` functions (models.py:70-86) so that they
return the IEEE-754 result where Python raises. The C helpers return the same
binary64 values. They are pure functions with the properties of the IEEE
helpers above (no state, no pointer, any thread, every `double` input,
including both zeros, subnormal values, both infinities and every NaN). They
call glibc libm (`exp`, `log`, `sqrt`, `pow`, `erfc`), which the project links
(Amendment F item 3). No helper reports an error; `errno` is not read.

| Function | Python | Output | NaN | Infinity and signed zero |
|---|---|---|---|---|
| `double pl_exp(double x)` | `_exp` (70-72) | `exp(x)` | NaN for a NaN `x` | `+inf` on overflow (Python raises `OverflowError`; `_exp` gives `inf`); `exp(-inf) = 0.0`; underflow gives `0.0` or a subnormal value as in Python |
| `double pl_log(double x)` | `_log` (79-82) | `log(x)` when `x > 0.0` | NaN (bits `0x7ff8000000000000`) when `x < 0.0`, `x = -inf` or `x` is NaN | `-inf` when `x == 0.0` (both zeros); `log(+inf) = +inf` |
| `double pl_sqrt(double x)` | `_sqrt` (83-85) | `sqrt(x)` when `x >= 0.0` | NaN (bits `0x7ff8000000000000`) when `x < 0.0` or `x` is NaN | `sqrt(-0.0) = -0.0`; `sqrt(+inf) = +inf` |
| `double pl_pow(double a, double b)` | `_pow` (73-78) | `+inf` when `a == 0.0 && b < 0.0` (both zeros: Python raises `ValueError`, `_pow` gives `+inf`; glibc would give `-inf` for `-0.0` and an odd negative integer `b`); else `pow(a, b)` | the glibc NaN for a finite negative `a` and a non-integer finite `b` (Python: `ValueError`, `_pow` gives NaN); `pow(NaN, 0.0) = 1.0`, `pow(1.0, NaN) = 1.0` | overflow gives `-inf` for a negative `a` and an odd integer `b`, else `+inf` (the `OverflowError` branch of `_pow`) |
| `double pl_erfc(double x)` | `math.erfc` | glibc `erfc(x)` (spec 3.4: `math.erfc` in Python, glibc `erfc` in C) | NaN for a NaN `x` | `erfc(+inf) = 0.0`, `erfc(-inf) = 2.0` |
| `double pl_sq(double x)` | `_sq` (86) | `x * x` | NaN for a NaN `x` | overflow gives `+inf`; `pl_sq(-0.0) = 0.0` |
| `double pl_sum2(double a, double b)`, `double pl_sum3(double a, double b, double c)`, `double pl_sum4(double a, double b, double c, double d)` | the Python sums `a + b`, `a + b + c`, `a + b + c + d`; a Python `a - b` is `pl_sum2(a, -b)` (IEEE-754 defines `a - b` as `a + (-b)`; equal bits, signed zeros included, except the sign of a NaN result, which no path reads) | `a + b`, `(a + b) + c` and `((a + b) + c) + d` (left to right) | NaN as the IEEE sum | IEEE sums (`-0.0 + -0.0 = -0.0`, `0.0 + -0.0 = 0.0`) |
| `double pl_py_div(double a, double b, int *defect)` | a Python float division `a / b` outside `models._guard` | the IEEE-754 `a / b`; sets `*defect = 1` when `b == 0.0` (Python raises `ZeroDivisionError`); never clears `*defect` | a NaN `a` over a zero `b` sets the defect too (Python raises for every numerator) | `±0.0` divisors both set the defect; the smallest subnormal divisor does not |

A NaN result is compared as "both NaN": the sign and payload of a NaN are not
part of the contract (the digest writes NaN as `null`), except where the
table names the bits. The check `c-vectors` part `erfc` compares CPython
`math.erfc` with glibc `erfc` bit for bit on 1,100,016 inputs (the edge
values `ERFC_EDGE_X` and seeded random values that reach every glibc `erfc`
interval) in the bench container.

Tests (`tests/project/test_ieee.c` group `helpers`): `pl_exp` overflow,
underflow, `0.0` and NaN; `pl_log` of both zeros, `-1.0`, `-inf`, NaN, `+inf`
and `1.0`; `pl_sqrt` of `4.0`, `-0.0`, `-1.0`, `-inf`, NaN and `+inf`;
`pl_pow` with a zero base (both signs) and the exponents `-1.0`, `-2.0`,
`-inf` and `2.0`, overflow with both signs, a negative base with a
non-integer exponent and the NaN rules; `pl_erfc` of `0.0` and both
infinities; `pl_sq` of `-3.0` and an overflow. Group `py-div`: `pl_py_div`
sets the defect for `0.0` and `-0.0` divisors with the numerators `1.0`,
`-1.0`, `0.0`, `+inf` and NaN, and not for the divisors `±5e-324` (one past
zero), `4.0`, `+inf` and NaN; the quotient is the IEEE result (`±inf`, NaN
for `0.0 / 0.0`) and a set defect stays set. Group `sums`: with
`h = 2^-53`, `pl_sum3(1.0, h, h)` and `pl_sum4(1.0, h, h, h)` are `1.0` (left
to right; the other association gives `1 + 2^-52`), `pl_sum3(h, h, 1.0)` is
`1 + 2^-52`, `pl_sum4(h, h, h, 1.0)` is `1 + 2^-51` (a tie to even),
`inf - inf` gives NaN and four `-0.0` give `-0.0`; `pl_sum2(1.0, h)` and
`pl_sum2(h, 1.0)` are `1.0` (a tie to even), `pl_sum2(1.0, 2h) > 1.0`,
`pl_sum2(-0.0, -0.0)` is `-0.0`, `pl_sum2(0.0, -0.0)` is `+0.0` (the bits of
`0.0 - 0.0`), `pl_sum2(inf, -inf)` is NaN. Group `helper-vectors`:
`pl_exp`, `pl_log` and `pl_sqrt` give the bits of `_exp`, `_log` and `_sqrt`
(or NaN where the vector is NaN) on every row of `PL_VEC_HELPERS` (22
inputs): the subnormal inputs `±5e-324`, `±1e-310` and `±2.2250738585072009e-308`,
the smallest normal value, exp arguments with a subnormal result (`-740.0`,
`-745.0`), an underflow to `0.0` (`-745.2`) and an overflow to `+inf`
(`709.79`, `710.0`) next to the largest finite result (`709.78`), both zeros,
both infinities, NaN and negative values.

## Normal distribution

`include/pl_normal.h`, `src/pl_normal.c`: the QuantLib 1.43 functions of spec
3.4 "Normal distribution", copied statement by statement from
`optionlab.normal` (normal.py:40-96; Amendment F item 8). Each function takes
one `double` (any binary64 value, including both zeros, subnormal values,
both infinities and every NaN), returns one `double`, keeps no state, reads
no memory through a pointer, may run on any thread and never fails.

| Function | Python | Output | NaN | Infinity and signed zero |
|---|---|---|---|---|
| `double pl_erf(double x)` | `erf` (40-69), `ErrorFunction::operator()` | the fdlibm-derived branches of normal.py in the same order: `|x| < 0.84375` (with the `|x| < 3.7252902984e-09` and `|x| < DBL_MIN * 16.0` sub-branches), `< 1.25`, `>= 6.0` (`±(1.0 - QL_EPSILON)`), `< 2.85714285714285` (tables RA, SA) and the rest (RB, SB) | the input NaN itself | `erf(+inf) = 1.0`, `erf(-inf) = -1.0`; `erf(-0.0) = -0.0` (the `0.125 * (8.0 * x + EFX8 * x)` branch keeps the sign) |
| `double pl_norm_pdf(double x)` | `norm_pdf` (72-76) | `deltax = x - 0.0`; `exponent = -(deltax * deltax) / 2.0`; `0.0` when `exponent <= -690.0`, else `0x1.9884533d43651p-2 * exp(exponent)` | NaN | `0.0` for both infinities |
| `double pl_norm_cdf(double z)` | `norm_cdf` (78-96) | `z = (z - 0.0) / 1.0`; `result = 0.5 * (1.0 + pl_erf(z * M_SQRT_2))`; when `result <= 1e-8` the Abramowitz-Stegun 26.2.12 series of spec 3.4 replaces it and `result = ((-pl_norm_pdf(z)) / z) * sum` | NaN | `N(-inf) = 0.0` (the series stops after one term), `N(+inf) = 1.0` |

The series loop is `for (;;)` with the Python stop rule `!(lasta > a && a >=
|sum * QL_EPSILON|)`. It always stops: `a` must fall strictly on each pass
(a NaN `a` stops it at once), and the vectors include rows where each of the
two conditions ends the loop.

Constants: every constant is the hex-float literal of the Python value
(`M_SQRT_2 = 0x1.6a09e667f3bcdp-1`; normalization
`M_SQRT_2 * M_1_SQRTPI / 1.0 = 0x1.9884533d43651p-2` with
`M_1_SQRTPI = 0x1.20dd750429b6dp-1`; `1e-8`, `3.7252902984e-09`,
`2.85714285714285`, `ERX`, `EFX`, `EFX8` and the tables `PP`, `QQ`, `PA`,
`QA`, `RA`, `SA`, `RB`, `SB`, each element with its Python decimal literal as a
comment). `QL_EPSILON` is `PL_QL_EPSILON`, `QL_MAX_REAL` is `DBL_MAX`, `TINY`
is `QL_EPSILON` and `ONE` is `1.0`. A nested Horner expression
`c[0] + s * (c[1] + s * (... + s * c[n-1]))` of normal.py is evaluated by the
static function `nested`: `t = c[n-1]`, then `t = c[k-1] + s * t` for `k = n-1`
down to `1`. Python evaluates the nested expression innermost first and
rounds each operation to binary64, so the operations, their order and their
association are the same; `ONE + s * (...)` is `ONE + s * nested(...)`.

Tests (`tests/project/test_normal.c`): every row of `PL_VEC_NORMAL` (83
inputs) gives the bits of `erf`, `norm_pdf` and `norm_cdf`, or NaN where the
vector is NaN. The inputs reach every `pl_erf` branch (NaN, both infinities,
the two tiny branches, the `PP`/`QQ` branch, and both signs of the `ERX`,
saturated, `RA`/`SA` and `RB`/`SB` branches). For each `|x|` bound of
`pl_erf` as normal.py writes it, `DBL_MIN * 16.0`, `3.7252902984e-09`,
`0.84375`, `1.25`, `2.85714285714285` (`0x1.6db6db6db6da7p+1`, the QuantLib
literal; the fdlibm value `1/0.35` = `2.857142857142857` is 16 ulps higher and
is an ordinary `RB`/`SB` input) and `6.0`, the inputs hold the exact bound
(the lower end of the half-open upper interval), its predecessor toward zero
(one past, in the lower interval) and both negatives, and every double of
`[2.85714285714285, 2.857142857142857)` with both signs (32 values). The
inputs also hold
both paths of `norm_cdf` (`-5.6` and `-5.7` are on the two sides of `1e-8`;
the series stops through `lasta > a` at `-5.7` and through the epsilon test
at `-10.0` and `-inf`) and both paths of the `norm_pdf` cutoff (`|x|` = `37.1`
and `37.2`).

The light test `test_light_cvectors.py` asserts this coverage on the Python
side by exact membership, and it checks each changed bound against the
vectors (mutants of `normal.erf`). A change of `<` to `<=` (or `>=` to `>`)
moves only `x = ±bound` to the other branch, so the change is detectable
exactly when the two branches give other bits at `±bound`:

- `>` for `>=` at `6.0`: detected (`erf` gives other bits on an input, so
  `test_normal.c` fails on the same change in C).
- `<=` for `<` at `DBL_MIN * 16.0`, `3.7252902984e-09`, `0.84375`, `1.25` and
  `2.85714285714285`: equivalent mutants. Both branches give equal bits at
  `±bound` (the light test asserts it on the vectors' own bound inputs), so
  no input can tell the two forms apart. At `DBL_MIN * 16.0` the tiny
  branches agree for every normal `x` (`EFX8` is `8 * EFX` exactly, and the
  scalings by `8.0` and `0.125` are exact).
- The fdlibm literal `2.857142857142857` for `2.85714285714285`: equivalent
  too. It moves the 32 band values from `RB`/`SB` to `RA`/`SA`, and both
  pieces give equal bits on every one of them (asserted by the light test).

## Term structure, mapping and BSM

`include/pl_black.h`, `src/pl_black.c`, `src/pl_bsm.c`: the term-structure arithmetic of spec
3.4 "Common arithmetic", the unit-maturity mapping of Amendment B item 3, the
QuantLib 1.43 `BlackCalculator` for a plain vanilla payoff and the
`AnalyticEuropeanEngine` at `t = 1`, copied statement by statement from
`optionlab.models` (models.py:95-202, 448) and `optionlab.mapping`
(mapping.py:9-14) (Amendment F item 8). Every function is pure: it keeps no
state, may run on any thread and writes only the output objects that the
caller passes (`*defect`, `*r1`, `*q1`, `*s1`, `*d_r`, `*d_q`, `*variance`,
`*b`, `*out`). Every pointer argument must point to a valid object of its type;
no pointer argument may be NULL (no function checks it). Every `double` input
is allowed (both zeros, subnormal values, both infinities, NaN); no function
allocates or fails with an error code other than the defect below.

Inputs on the row path: `T > 0` finite (the row check returns `EXPIRED`
first), `S > 0` and `K > 0` finite, `r` and `q` any binary64 value (a hostile
wire record can carry NaN or ±inf), `sigma` in `[σ_lo, 5.0]` or a bump of it.
`pl_unit` takes `T >= 0.0` or NaN; Python `math.sqrt` raises `ValueError` for
`T < 0.0`, which the row path never passes (the C function gives NaN there).

| Function | Python | Result | Defect (Python raises) |
|---|---|---|---|
| `pl_discount(rate, t, defect)` | `discount` (96) | `pl_py_div(1.0, pl_exp(rate * t), defect)` | `exp(rate * t)` is `0.0`: `rate * t` at or below the largest double with `exp == 0` (about −745.13; the vectors name it exactly) or `-inf` |
| `pl_implied_rate(compound, t)` | `implied_rate` (97-99) | `0.0` when `compound == 1.0`, else `pl_log(compound) / t` | none: `t` is a nonzero constant at every call (`1.0`, `0.0001` or `t2 - t1 = 0.0001`) |
| `pl_zero_rate(rate, t, defect)` | `zero_rate` (100-103) | `t == 0.0` (both zeros) becomes `0.0001`; `pl_implied_rate(pl_py_div(1.0, pl_discount(rate, t), defect), t)` | the discount raises, or the discount is `0.0` (`rate * t` overflows `exp`) |
| `pl_forward_rate(rate, t1, t2, defect)` | `forward_rate` (104-105) | `pl_implied_rate(pl_py_div(discount(t1), discount(t2), defect), t2 - t1)`; both discounts in this order | either discount raises, or the second discount is `0.0` (a NaN first discount included) |
| `pl_unit(T, r, q, sigma, r1, q1, s1)` | `unit` (mapping.py:9-14) | `r1 = r * T`, `q1 = q * T`, `s1 = sigma * sqrt(T)` | none on the row path |
| `pl_mapped_inputs(T, r, q, sigma, d_r, d_q, variance, defect)` | `mapped_inputs` (187-190) | `d_r = pl_discount(r1, 1.0)`, `d_q = pl_discount(q1, 1.0)`, `variance = s1 * s1 * 1.0` | either discount raises (`r * T` or `q * T` at the `exp == 0` bound or below, or `-inf`) |

Once a defect is set, the other results of that call are not used (Python has
raised; the C values are the IEEE results). `*defect` is only ever set to 1;
the caller initializes it to 0.

`struct pl_black` holds the members of `models.Black` (`side`, `strike`,
`forward`, `std_dev`, `discount`, `variance`, `d1`, `d2`, `x`, `dx_dstrike`,
`dx_ds`, `alpha`, `dalpha_dd1`, `beta`, `dbeta_dd2`). `pl_black_init` copies
`Black.__init__` (110-130): `std_dev >= QL_EPSILON` takes the full branch
(`close(strike, 0.0)` gives `d1 = d2 = DBL_MAX`, else `d1 = log(F / K) / σ + 0.5σ`
with `N` and `n` of Task 7); otherwise the zero-volatility branch:
`close(F, K)` gives `d1 = d2 = 0.0` (the Python integer `0`),
`N = 0.5` and `n = M_SQRT_2 * M_1_SQRTPI` (the Task 7 literals
`0x1.6a09e667f3bcdp-1` and `0x1.20dd750429b6dp-1`); `F > K` gives `DBL_MAX`
(`QL_MAX_REAL`), `N = 1.0`, `n = 0.0`; else `-DBL_MAX` (`QL_MIN_REAL`), `N = 0.0`,
`n = 0.0`. Side 0 is a call (`alpha = N(d1)`, `beta = -N(d2)`); any other side is a
put (`alpha = -1.0 + N(d1)`, `beta = 1.0 - N(d2)`). The result functions
`pl_black_value`, `pl_black_delta`, `pl_black_delta_forward`, `pl_black_gamma`,
`pl_black_theta`, `pl_black_vega`, `pl_black_rho`, `pl_black_dividend_rho` and
`pl_black_strike_sensitivity` copy models.py:131-184. Their zero-volatility
test is `std_dev <= QL_EPSILON` (so `std_dev == QL_EPSILON` takes the full
setup and the zero-volatility greeks, as in QuantLib), and the static
function `flat` copies `Black._flat` (132-135): `close(F, K)`, then `F > K`,
then the rest, each choosing the call value when `alpha >= 0.0`. A
zero-volatility put with `F > K` has `alpha = 0.0` and so takes the call
value, as in Python and QuantLib. `pl_black_theta` returns `0.0` when
`close(maturity, 0.0)`, else `-(sum) / maturity` with the three Python terms
summed in their order.

`pl_bsm_engine(side, S, K, d_r, d_q, variance, greeks, out)` copies
`bsm_engine` (195-202): `forward = S * d_q / d_r`, `Black(side, K, forward,
sqrt(variance), d_r)`; `value`, and with `greeks != 0` also `delta(S)`,
`gamma(S)`, `rho(1.0)`, `dividend_rho(1.0)`, `vega(1.0)` and `theta(S, 1.0)`.
Every other member (all greeks when `greeks == 0`; `strike_sensitivity` and
`strike_gamma` always) is `pl_nan()`. `pl_bsm_result` copies `bsm_result`
(448): `pl_mapped_inputs` first (outside `_guard`), then the engine. It
returns `PL_ENGINE_PY_DEFECT` with every member `pl_nan()` when the mapped
inputs raise, else `PL_ENGINE_OK`. The BSM engine never returns
`PL_ENGINE_QL_ERROR` (the Python `Black` has no `QL_REQUIRE`).

File split and sums (the fixed GCC analyzer budget of the framework, see
`docs/agent-development-quickstart.md` "Staying within the analyzer budget"):
the engine is in `pl_bsm.c`, so the BlackCalculator functions are opaque
calls there and the path count of each file stays small. Two sums go through
`pl_sum4` (the four terms of `gamma`'s `temp2`) and `pl_sum3` (the three terms
of `theta`) in `pl_ieee.c`: each returns `((a + b) + c) + d` or `(a + b) + c`,
the Python left-to-right order, so the operations and their association are
unchanged, and the analyzer sees an opaque value (without it the symbolic
value of `gamma` passes the analyzer's depth limit). Each term is evaluated
as in Python before the sum.

Division inside the engine: every division of `Black` and `bsm_engine` is
plain IEEE C division. Python `models._guard` runs the engine once with
float operands; when that run raises `ZeroDivisionError` (for example
`D_r = 0.0` from `r * T` above about 709.78, `r = +inf`), it runs the engine
again with every float argument as `_IEEEFloat`, whose division gives the
IEEE result and whose other operations give the same binary64 results. Every
engine division has an argument-derived (`_IEEEFloat`) operand in that run,
so the second run never raises (plan audit table, ruling H1), and C gives the
same values without a second run.

Python raise points on the row path in this module (plan audit table, ruling
H1; `PL_ENGINE_PY_DEFECT` here, `PL_EVAL_DEFECT` for the run in Task 11):
`models.py:96` (`discount`, via `mapped_inputs`, `zero_rate`, `forward_rate`),
`models.py:103` (`zero_rate`) and `models.py:105` (`forward_rate`). Each is a
`pl_py_div` at the same point, in the same order.

Tests (`tests/project/test_black.c`, vectors from the check `c-vectors` part
`black`, compared as equal bits or both NaN):

- Table `black` (611 rows): the grid side × S (80, 125) × K (90, 110) × six
  maturities (1 hour to 3 years) × three (r, q) pairs × σ (1e-4, 0.08, 0.9,
  5.0); the edge rows of the brief (T = 1e-12 zero-volatility rows, K = 1e-300,
  S = 1e-6, r = +inf, q = NaN, and the raising rows r = −800, q = −800,
  r = −inf); and the Task 8 edge rows: with T = 1.0, the largest double with
  `exp == 0` (raises) and its one-past value (does not raise; `D = +inf`) as `r`
  and as `q`, the smallest double with `exp == +inf` (`D = 0.0`, the `_guard`
  IEEE path) and its one-past value (`D` subnormal) as `r` and as `q`; σ = QL_EPSILON
  and both neighbours (`std_dev` exactly at and next to the bound); the
  zero-volatility rows for every `flat` result (call and put, F above, below
  and close to K, including the put with F above K at `std_dev == QL_EPSILON`,
  whose `alpha` is below `0.0` because `N(d1)` rounds to `1 - 2^-53`). Per row: the defect of `pl_mapped_inputs`; for a
  raising row, `pl_bsm_result` returns `PL_ENGINE_PY_DEFECT` and only NaN; else
  `PL_ENGINE_OK`, `d_r`, `d_q`, `variance`, the price-only value (its greeks
  NaN), value, delta, gamma, theta, vega, rho and dividend rho, NaN strike
  members, and `pl_discount(r·T, 1.0)`, `pl_zero_rate(r·T, 0.0)` and
  `pl_forward_rate(r·T, 0.0, 0.0001)` with one defect bit each (both outcomes
  of the last two occur; `compound == 1.0` occurs at T = 1e-12); and
  `pl_zero_rate(r·T, 0.0001)` and `pl_zero_rate(r·T, -0.0)` give the bits and
  the defect of `pl_zero_rate(r·T, 0.0)` (the replacement of both zeros by
  0.0001, and the `t != 0.0` path). The test is REQUIRE-style: the first
  failed check prints `FAIL <group> <index>` and exits 1.
- Table `black_calc` (108 rows): `BlackCalculator` directly, every member set
  by `pl_black_init` and every result function, with `std_dev` 0.0,
  QL_EPSILON and both neighbours, 0.25 and NaN; F equal to K, 4e-13 above
  (close), 1e-11 above (not close), below and above; K of 1e-29 and 0.0 (close
  to 0.0) and 1e-28 (not close); theta at maturity 0.0, -0.0, 1e-29 (close) and
  1e-28 (not close); a zero forward and a zero discount. The Python values come
  through `models._guard`, as in the engines.

The light test `test_light_cvectors.py` asserts on the Python side: the exp
bounds are exact (`_exp(zero_at) == 0.0`, `_exp(nextafter(zero_at, 0.0)) ==
5e-324`, `_exp(inf_at) == inf`, the predecessor finite); each bound and its
one-past value is a row as `r` and as `q` with the expected raise outcome;
the rows have `std_dev` exactly QL_EPSILON and both neighbours; the rows reach
every `Black.__init__` branch and all six `flat` results; both outcomes of
each helper defect bit. Bound mutants of `models.Black`: `>` for `>=` at
`stdDev >= QL_EPSILON`, `<` for `<=` at `stdDev <= QL_EPSILON` and `>` for `>=`
at `alpha >= 0` are detected by the `black_calc` vectors (so the same change in
C fails `test_black.c`); `>=` for `>` at the F/K test of `__init__` and of
`_flat` is equivalent for every input (`F == K` is `close(F, K)`, tested first;
NaN compares false both ways), asserted on the vectors. `compound == 1.0` in
`implied_rate` is a shortcut with equal bits: `log(1.0) / t` is `0.0` for the
positive constant `t`.

## Bjerksund-Stensland 1993

`include/pl_bjs.h`, `src/pl_bjs_phi.c`, `src/pl_bjs.c`: the QuantLib 1.43
`BjerksundStenslandApproximationEngine` of spec 3.4 "Bjerksund-Stensland"
(the 1993 one-boundary method; `bjerksundstenslandengine.hpp:33`; no bivariate
normal distribution, so this module has no bivariate regions), copied
statement by statement from `optionlab.models` (models.py:39, 204-355, 449;
Amendment F item 8). Every function is pure: it keeps no state, may run on any
thread and writes only `*out`. `out` must point to a valid
`struct pl_engine_result`; it may not be NULL (no function checks it). Every
`double` input is allowed; no function allocates. Inputs on the row path are
those of "Term structure, mapping and BSM" (`T > 0` finite, `S`, `K > 0`
finite, `r` and `q` any binary64 value, `sigma` in `[σ_lo, 5.0]`).

| Function | Python | Result |
|---|---|---|
| `pl_bjs_phi(S, gamma, H, I, rT, bT, variance)` | `_phi` (205-209) | `e^λ (N(d) - (I/S)^κ N(d - 2 ln(I/S)/√v))` in the Python order |
| `pl_bjs_phi_s`, `_ss`, `_gamma`, `_h`, `_i`, `_rt`, `_bt`, `_v` (same parameters, the last named `v`) | `_phi_S` (211-213), `_phi_SS` (215-219), `_phi_gamma` (221-223), `_phi_H` (225-227), `_phi_I` (229-231), `_phi_rt` (233-235), `_phi_bt` (237-239), `_phi_v` (241-244) | the analytic derivatives of `bjerksundstenslandengine.cpp:50-110`; `math.erfc` is `pl_erfc` (glibc `erfc`, spec 3.4) |
| `pl_bjs_european_call(S, X, rf_d, d_d, variance, out)` | `_european_call` (246-253) | `Black(0, X, S * d_d / rf_d, sqrt(variance), rf_d)`: value, delta(S), gamma(S), rho(1.0), dividend rho(1.0), vega(1.0), theta(S, 1.0), strike sensitivity; `strike_gamma = gamma * (S / X)^2` |
| `pl_bjs_immediate(S, X, out)` | `_immediate` (255-259) | `value = max(0.0, S - X)`, `delta = 1.0` when `S >= X` else `0.0`, `strike_sensitivity = -delta` (so `-0.0` for `S < X`), every other member `0.0` |
| `pl_bjs_american_call(S, X, rf_d, d_d, variance, greeks, out)` | `_american_call` (261-340) | see the branch rules below |
| `pl_bjs_engine(side, S, K, d_r, d_q, variance, greeks, out)` | `bjs_engine` (342-355) | `PL_ENGINE_QL_ERROR` with every member NaN for the double-boundary case, else `PL_ENGINE_OK` |
| `pl_bjs_result(side, S, K, T, r, q, sigma, greeks, out)` | `bjs_result` (449) | `PL_ENGINE_PY_DEFECT` with every member NaN when `pl_mapped_inputs` sets the defect, else the engine |

Branch rules, in the Python order (each condition is copied; a NaN operand
makes a comparison false, as in Python):

1. Engine: side 1 swaps `S` and `K` and swaps `d_r` and `d_q` (models.py:344);
   every other side is a call. `dividendDiscount > 1.0 && riskFreeDiscount >
   dividendDiscount` is the QuantLib error "double-boundary case r<q<0 for a
   call given" (`ModelDefect` in Python; `PL_ENGINE_QL_ERROR`). Else
   `dividendDiscount >= 1.0 && dividendDiscount >= riskFreeDiscount` gives the
   European call results (the spec's "b ≥ r" case: `q′ ≤ 0` and `q′ ≤ r′`),
   else the American call approximation. Then a value below
   `(spot - strike) * (1.0 + 10.0 * QL_EPSILON)` is replaced by
   `pl_bjs_immediate(spot, strike)`. A put then swaps delta with strike
   sensitivity, gamma with strike gamma and rho with dividend rho, and
   multiplies rho by `tr / tq` and dividend rho by `tq / tr` (`tr = tq = 1.0`),
   as written.
2. American call: `bT = log(d_d / rf_d)`, `rT = log(1.0 / rf_d)`, `beta`,
   `BInfinity`, `B0 = X` when `bT == rT` else `max(X, rT / (rT - bT) * X)`,
   `ht`, the trigger `I`, `fwd`, `q_I = log(I / fwd) / sqrt(variance)`. `S >= I`
   gives `pl_bjs_immediate(S, X)`; else `q_I > 12.5` gives the European
   results; else the 1993 formula (models.py:278-280). With `greeks == 0` the
   formula branch computes only the value and sets every other member to NaN
   (as Python, which sets them to `math.nan`); the other branches set every
   member. With greeks: delta, dividend rho (`B0Dq = 0.0` when `d_d <= rf_d`),
   rho (`B0Dr = 0` when `d_d <= rf_d`), vega, gamma, theta
   (`365 * thetaPerDay` with `dt = 1.0 - 364.0 / 365.0`, computed in C as in
   models.py:39), strike sensitivity and strike gamma. Last, a value below the
   European value is replaced by the European results (models.py:339).

Python raise points on this path: `mapped_inputs` (models.py:96 through
`discount`), before `models._guard`: a `ZeroDivisionError` that is not a
`ModelDefect` (controller ruling A30), so `PL_ENGINE_PY_DEFECT` (status 2 in
the vectors; for example r = -800, q = -800, r = -inf and the largest double
with `exp == 0` as `r` or `q`). The double-boundary `ModelDefect`
(models.py:345) is `PL_ENGINE_QL_ERROR` (status 1). Inside the engine every
division is IEEE C division: `models._guard` runs the engine again with every
argument as `_IEEEFloat` when the plain run raises `ZeroDivisionError` (for
example `D_r = 0.0` from r = +inf), and every engine division has an argument-derived operand in
that run, so the second run never raises; C gives the same values without a
second run. The vectors confirm this on every row (a raise in the second run
would be status 2 in Python and status 0 in C).

Repeated Python subexpressions: Python evaluates `sqrt((bT / v - 0.5)^2 +
2 rT / v)` in `beta` (268), as `root` (287), in `beta` again (316) and in
`betaDv` (318), and `_exp(ht)`, `bT + 2 sqrt(v)`, `BInfinity - B0`, `_pow(I/S,
...)` and the phi arguments several times, always with the same operands. C
computes each once (pure functions give equal values). A named C local holds a
Python subexpression with the same operations in the same order; no
operation is moved across a parenthesis of the Python text.

File split and sums (the fixed GCC analyzer budget, as in "Term structure,
mapping and BSM"): phi and its derivatives are in `pl_bjs_phi.c`, so they are
opaque calls in `pl_bjs.c`. With the eight derivatives in `pl_bjs.c`, the
gcc-analyzer gate fails with `analyzer-too-complex` (Task 9 experiment). The
GCC analyzer gives up on a symbolic value deeper than 12 operations
(`-Wanalyzer-symbol-too-complex`). The Python sums
that would pass that depth go through `pl_sum2`, `pl_sum3` or `pl_sum4` of
`pl_ieee.c` (left to right; `a - b` as `pl_sum2(a, -b)`, the same IEEE
operation, with equal bits except the sign of a NaN result; `pl_sum3(pl_sum3(a, b, c), d, e)` is `(((a + b) + c) + d) + e`):
`beta`, `I`, the value, each greek's terms and the inner sums of `betaDq`,
`betaDr`, `betaDv`, `htDq`, `htDr`, `htDv`, `IDq`, `IDr`, `IDv` and theta, and
the bracketed sums of `_phi_S`, `_phi_SS`, `_phi_gamma`, `_phi_bt` and
`_phi_v`. Each term is evaluated as in Python before the sum.

Tests (`tests/project/test_bjs.c`, vectors from the check `c-vectors` part
`bjs`, compared as equal bits or both NaN; REQUIRE-style: the first failed
check prints `FAIL <group> <index>` and exits 1):

- Table `bjs_phi` (72 rows): phi and the eight derivatives on the brief grid
  S (90, 100) × γ (0, 1, 1.75) × (H, I) ((95, 130), (130, 130)) × (rT, bT)
  ((0.04, 0.028), (0.012, -0.028)) × v (0.0016, 0.09, 1.0).
- Table `bjs_immediate` (7 rows): `pl_bjs_immediate` with S at X, one double
  below and above X, above and below X, and NaN S or X; every member.
- Table `bjs` (511 rows: 499 of status 0, 7 of status 1, 5 of status 2): the
  rows of part `black` with σ ≥ 0.01 (447), the six brief rows, and the 58
  Task 9 edge rows; for each row the status of both
  calls (greeks 1 and 0), the price-only value, the value and the six greeks
  (NaN for status 1 and 2, with NaN strike members too).

Edge rows (`cvectors.bjs_edge_rows`, call form, then each row again as the put
`(1, K, S, T, q, r, σ)`, which prices the same call; T = 1.0, so `r·T = r`):
each bound is an adjacent pair of doubles `(a, b)` from a bisection over the
bit patterns (`cvectors.bjs_bounds`):

- `dividendDiscount > 1.0`: `q = -a` gives `D_q == 1.0`, `q = -b` gives
  `D_q > 1.0`; with r = -0.5 (S = 100 and 50: the American branch with
  `bT == rT`, I near 58, and the QuantLib error), r = 0.04 (European) and, with
  q = 0, r = 0, -a and -b (`D_r` = 1.0, 1.0 and above 1.0: European, European,
  the American branch with `bT == rT`).
- `dividendDiscount >= 1.0`: q = a (`D_q == 1.0`, European) and q = b
  (`D_q < 1.0`, American) with r = 0.04.
- `riskFreeDiscount > dividendDiscount` with q = -0.03: r = -0.03, -a
  (European) and -b (the QuantLib error).
- `dD <= rfD` in the greeks: r = 0.04 with q = 0.04, a (`D_q > D_r`) and b.
- `S >= I`: the call X = 100, r = 0.04, q = 0.08, σ = 0.2 at S = I and one
  double below.
- `q_I > 12.5`: the adjacent S pair of that call.
- The immediate-exercise test of the engine: the adjacent S pair in
  [100, I] of that call.
- The European fallback: the adjacent σ pair of the put S = K = 100, r = 0.04,
  q = 0.012 (σ near σ_trig, where `ht > 0` makes the formula fall below the
  European value).
- `S >= I` with `I < X`: the call X = 100, r = 0.012, q = 0.04 at the largest σ
  of the grid 0.0140, 0.0139, ..., 0.0090 where `0 < I < X` (`ht > 0`) and the
  European value at S = I is exactly 0.0; S = I and one double below.
- Exact equality: the S nearest (in ulps, within 3000) to the `q_I` flip of the
  call X = 100, r = 0.3, q = 0.01, σ = 0.3 with `q_I == 12.5` exactly and the
  formula value above the European value; and the S nearest to the
  immediate-exercise pair with `value == (S - X)(1 + 10 ε)` exactly.

The light test `test_light_cvectors.py` (class `BjsVectorTests`) asserts on
the Python side: each bound pair is adjacent with the stated values; each
bound row and its put form is a row and takes the expected branch; the rows
reach every engine branch (Python defect, QuantLib error, European,
immediate, European by `q_I`, formula) and both outcomes of `bT == rT`,
`dD <= rfD` (in the formula branch), the European fallback and the
immediate-exercise test; statuses 0, 1 and 2 occur exactly at the branches.
Bound mutants of `models.py` detected by the vectors (so the same change in C
fails `test_bjs.c`): `>=` for `>` and `>` for `>=` at each engine condition,
`>` for `>=` at `S >= I` and at `S >= X` of `_immediate`, `<` for `<=` at both
`dD <= rfD`, and `<=` for `<` at the European fallback. At `S == I` every phi
term is exactly 0.0 (`(I/S)^κ = 1` and the two normal arguments are equal), so
the formula value is exactly `I - X`; for `I > X` the engine's immediate test
then gives the immediate results either way. So `>` for `>=` at `S >= I` and
`<=` for `<` at the European fallback change a result bit only at the `I < X`
rows with a zero European value (the immediate results against the European
results, whose signed zeros differ); those rows detect both. `>=` for `>` at
`q_I > 12.5` and `<=` for `<` at the immediate-exercise test are detected by
the exact-equality rows: near each bound one double step in S moves `q_I` or
the value by less than one of its own ulps, so exact equality occurs (approver
finding I1 of Task 9). Every bound mutant is detected.

## CRR

`include/pl_crr.h`, `src/pl_crr.c`, `src/pl_crr_lattice.c`: QuantLib 1.43
`BinomialVanillaEngine<CoxRossRubinstein>` of spec 3.4 "Cox-Ross-Rubinstein
binomial" with `timeSteps` = `crr_steps`, for the unit-maturity problem of
Amendment B item 3, copied statement by statement from `optionlab.models`
(models.py:357-371, 397-428, 450-456; Amendment F item 8). Every function is
pure: it keeps no state, may run on any thread and writes only `*out` and
`*defect`. `out`, `tree` and `defect` must point to valid objects; they may not
be NULL (no function checks them). Every `double` input is allowed. Inputs on
the row path: `T > 0` finite, `S`, `K > 0` finite, `r` and `q` any binary64
value, `sigma` in `[σ_lo, 5.0 + h_σ]`, `steps` = 100.

| Function | Python | Result |
|---|---|---|
| `pl_crr_mapped_tree(T, r, q, sigma, steps, out, defect)` | `crr_mapped_tree` (358-371) | `dx`, `drift_per_step`, `disc` and the theta rates (`zero_rate(r', 0.0)`, `zero_rate(q', 0.0)`, `σ'`); `*defect = 1` where Python raises, then every member NaN |
| `pl_crr_engine(side, S, K, tree, steps, american, with_theta, greeks, out)` | `crr_engine` (397-428), `theta_rates` = the tree's theta members when `with_theta != 0`, else `None` | the status below; value, and with `greeks` delta, gamma and (with `with_theta`) theta; every other member NaN |
| `pl_crr_result(side, S, K, T, r, q, sigma, steps, american, greeks, out)` | `crr_result` (450-452) | `PL_ENGINE_PY_DEFECT` (every member NaN) when the tree sets the defect, else the engine with the theta rates |
| `pl_crr_lattice_reset(l)` | `crr_engine` lines 406-408 | `growth` and the initial `values` of `*l`; 1 without writing when `l->steps` is outside `[2, PL_CRR_MAX_STEPS]`, else 0 |
| `pl_crr_lattice_step(l, i)` | `crr_engine` lines 410-414 | one rollback step `i` on `l->values`; 1 without writing unless `2 <= l->steps <= PL_CRR_MAX_STEPS` and `0 <= i < l->steps`, else 0 |

Tree (`crr_mapped_tree`, in this order): `(r', q', σ') = unit(T, r, q, σ)`
(`pl_unit`), `v = σ'`; `rz = implied_rate(1.0 / discount(r', 1.0), 1.0)`,
`qz` the same for `q'`; `dt = 1.0 / steps`; `drift = forward_rate(rz, 0.0,
0.0 + 0.0001) - forward_rate(qz, 0.0, 0.0 + 0.0001) - 0.5 v v` (QuantLib's
forward-difference drift of Amendment D item 1: the drift is read back from the
zero curves, not taken as `r' - q'`); `driftPerStep = drift dt`; `dx =
sqrt(v v (0.0 + dt) - v v 0.0)` (`pl_sqrt`); `disc = exp(-rz dt)`. Each Python
`/` of this function and of `discount`, `zero_rate` and `forward_rate` is
`pl_py_div` (models.py:363, 364, 365, 366 and 370).

Engine (`crr_engine`, in this order):

1. `steps < 2` is the QuantLib error "Expect 3 nodes in grid at second step"
   (`ModelDefect`; `PL_ENGINE_QL_ERROR`).
2. `pu = 0.5 + (0.5 driftPerStep) / dx` (IEEE division, models._div), `pd =
   1.0 - pu`; `!(pu <= 1.0)`, then `!(pu >= 0.0)`, is the QuantLib error
   "negative probability" (`PL_ENGINE_QL_ERROR`; a NaN `pu` fails the first
   test). Then `steps > PL_CRR_MAX_STEPS` (100) is also `PL_ENGINE_QL_ERROR`
   (`pl_crr_lattice_reset` refuses it): the stack scratch bound of C. Python
   has no such bound; the row path passes 100 only, so this branch is
   unreachable there. Every member is NaN for each error, so the place of this
   check after the probability checks changes no result.
3. `growth` position `j + steps` holds `S * exp((double)j * dx)` for
   `j = -steps ... steps`, computed once per call in increasing `j`.
4. `values[j] = max(0.0, payoff(growth[2j - steps]))` with `payoff(s) =
   max(s - K, 0.0)` for side 0 and `max(K - s, 0.0)` for every other side.
   `max(a, b)` is `pl_max(a, b)` in the Python argument order: a NaN payoff
   gives 0.0 here, and the node maximum below keeps the rolled-back value
   (both are vector rows: `K` NaN).
5. Rollback for `i = steps - 1 ... 0`, `j = 0 ... i`: `next = (pd values[j] +
   pu values[j + 1]) disc`; with `american != 0`, `next = max(next,
   payoff(growth[2j - i]))` (exercise at every step, t = 0 included). C writes
   `values[j]` after it reads `values[j]` and `values[j + 1]`, so the update in
   place equals the Python list comprehensions. After the step `i == 2` C
   copies the three values to `va2`, after `i == 1` the two values to `va1`.
6. `greeks == 0`: only `value = values[0]`. With greeks and `steps == 2`,
   Python raises `TypeError` (the step `i == 2` never runs, so `va2` is
   `None`): `PL_ENGINE_PY_DEFECT`. Else `delta2u = (va2[2] - va2[1]) /
   (growth[2] - growth[0])`, `delta2d = (va2[1] - va2[0]) / (growth[0] -
   growth[-2])`, `gamma = (delta2u - delta2d) / ((growth[2] - growth[-2]) /
   2.0)`, `delta = (va1[1] - va1[0]) / (growth[1] - growth[-1])` (IEEE
   division; a `0 / 0` delta is NaN), and with `with_theta`, `theta = r p0 -
   (r - q) u delta - 0.5 v v u u gamma` with `(r, q, v)` the theta rates and
   `u = S` (`greeks.cpp:25-35`, `blackScholesTheta`).

Memory (no allocation): `struct pl_crr_lattice` holds `growth` (`2
PL_CRR_MAX_STEPS + 1` doubles) and `values` (`PL_CRR_MAX_STEPS + 1`); it and
`va2` (3) and `va1` (2) are on the stack of the calling thread (about 2.5
KiB). `pl_crr_lattice_reset` and `pl_crr_lattice_step` check `2 <= steps <=
PL_CRR_MAX_STEPS` (and `0 <= i < steps`) before they form any position, and
every position is in `[0, 2 steps]` for `growth` (`j + steps` with `|j| <=
steps`, `2j` with `j <= steps`, `2j - i + steps` with `0 <= j <= i <= steps -
1`, and `steps ± 1`, `steps ± 2` in the greeks, where `steps >= 2`) and in
`[0, steps]` for `values`. All access is pointer arithmetic (`*(l->values +
j)`; the AST gate allows no subscript). The step refusal cannot occur from
the engine (it passes `0 <= i < steps` after the reset accepted `steps`); the
engine still checks the result and returns `PL_ENGINE_QL_ERROR`, and
`test_crr.c` calls both functions with each refused argument and at the
bounds.

File split (the fixed GCC analyzer budget, as in "Term structure, mapping and
BSM"): with the lattice loops in `pl_crr.c`, the gcc-analyzer gate fails with
`analyzer-too-complex` at the rollback loop (Task 10 run). In
`pl_crr_lattice.c` they are opaque calls from the engine.

Python raise points on this path, mirrored exactly:

- `crr_mapped_tree` before `models._guard`: `ZeroDivisionError` of a discount
  (`exp == 0.0` or `inf`) or of `maturity / steps` (`steps == 0`), and the
  `ValueError` of `math.sqrt` in `mapping.unit` for `T < 0.0`. `*defect = 1`;
  `pl_crr_result` gives `PL_ENGINE_PY_DEFECT` (vector `defect` 1). The exact
  bounds are `|r T|` or `|q T|` equal to 709.7827128933840 (no raise) and the
  next double (raise), on both signs: above it the exponential is `inf`, below
  minus it `1.0 / discount` is 0.0 and the forward-rate read of the `-inf`
  zero rate divides by a zero discount. (`pl_mapped_inputs`, `pl_sigma_lo` and
  `pl_crr_domain_ok` return values for `T < 0.0` where Python raises `ValueError`.
  The row path cannot reach `T < 0.0`: `reference.py` returns EXPIRED or
  INVALID_INPUT first.)
- `crr_engine`: `ModelDefect` (steps, negative probability) is
  `PL_ENGINE_QL_ERROR` (vector `status` 1); the `TypeError` of `steps == 2`
  with greeks is `PL_ENGINE_PY_DEFECT` (vector `status` 2 in table
  `crr_engine`). Every engine division is `models._div`, so `models._guard`
  never runs the engine again.

Amendment D: the forward-difference drift is the definition (item 1); the CRR
accuracy properties (the q = 0 call equality, the discretization band, the
convergence rule and C_crr) are documented metrics of `optionlab.oracle`, never
gates (item 2). This module computes only the QuantLib arithmetic.

## σ_lo and the CRR domain

| Function | Python | Result |
|---|---|---|
| `pl_sigma_lo(model, side, T, r, q, p)` | `sigma_lo` (506-518) | `PL_MODEL_BSM`: `1e-4`; `PL_MODEL_CRR`: `max(1e-4, 1.001 (|r - q| + h_r) sqrt(T / N))`; `PL_MODEL_BAW`: `max(1e-4, σ_trig)` with the σ_trig below (Appendix G-BAW R9, erratum F3); `PL_MODEL_ALO` (models.py:528-542, Appendix I-ALO R9, E-ALO-1): `pl_max(1e-4, (C max(0.0, d + h_r)) sqrt(T))` with (ρ, δ) = (r, q) for a put and (q, r) for a call; FP_A of `alo_equation(r T, q T)`: C = 0.75, d = ρ - δ; FP_B: C = 0.003, d = δ - ρ; a zero exponential of `read_back` raises (`ZeroDivisionError`, a defect before the solve); every other model (BjS): `b = r - q` for side 0, else `q - r`; `σ_trig = 1.001 (|b| + h_r) sqrt(T) / 2.0` when `b < 0.0`, else 0.0; `max(max(1e-4, σ_trig), sqrt(2.0 (|b| + h_r) / κ_cap))` |
| `pl_crr_domain_ok(T, r, q, p)` | `crr_domain_ok` (491-496) | `g(s) = s - (s s / 2.0 + b) sdt` with `sdt = sqrt(T / N)`, `b = |r - q| + h_r`; 1 when `g(σ_lo(CRR)) >= 0.0` and `g(σ_hi + h_σ) >= 0.0`, else 0 |

Python `max(a, b)` and `max(a, b, c)` are `pl_max(a, b)` and
`pl_max(pl_max(a, b), c)`: the first maximal argument; a NaN after the first
argument never wins (a NaN `r` gives `σ_lo = 1e-4`; an infinite `r` gives
`inf` and a domain result of 0). `abs` is `pl_fabs`, `math.sqrt` is `sqrt`.
`p` must point to valid parameters. `T` is finite and `> 0` on the row path
(`EXPIRED` comes first); Python raises `ValueError` for `T < 0.0`, which no
row reaches. The bounds in the vectors (table `crr_lo`): `g(σ_lo) == 0.0`
exactly at the last `T` before the flip and the next double for each pair of
`RATES` (T near 1.66, 4.98 and 7.10); `g(σ_hi + h_σ) == 0.0` the same, near
T = 15.7 to 16.0, with two pairs of small carry (r = q = 0.04; r = 0.03,
q = 0.02) where `g(σ_lo) >= 0.0` holds, so that the bound changes the
result; `b == 0.0` (r == q) at T = 2000, where `σ_trig` at `b = 0` would exceed
`σ_carry`, and the next `q`, which makes `b` negative for side 0.

## Case parameters

`pl_case_params(p)` sets the constants of `optionlab.params.CASE` (case
version 1, `CaseParams(0.04, 0.012, 100)` with the class defaults):
`crr_steps` 100, `sigma_hi` 5.0, `kappa_cap` 50.0, `h_r` 1e-4, `h_sigma`
1e-3, `baw_newton_max` 40 (`PL_BAW_NEWTON_MAX`, the case manifest value that
`test_baw.c` compares with the generator's `optionlab.params.CASE`) and
`baw_plant_nonfinite_sstar` 0, `alo_plant_site` 0 and `alo_force` 0 (the test-only
ALO hooks of "ALO (Amendment I)"; spec section 14 values; the rate and the dividend yield belong to each
row, so `struct pl_params` has no members for them). `test_crr.c` checks each
value.

Tests (`tests/project/test_crr.c`, vectors from the check `c-vectors` part
`crr`, compared as equal bits or both NaN; REQUIRE-style: the first failed
check prints `FAIL <group> <index>` and exits 1):

- Table `crr` (972 rows): the rows of part `black` with σ ≥ 0.01 (447), the
  six brief rows and 33 edge rows (`cvectors.crr_edge_rows`), each with
  `american` 1 and 0. Per row: the defect bit and the six tree members, the
  status of `pl_crr_result` with and without greeks, the price-only value, the
  value, delta, gamma and theta, and NaN for every other member. Edge rows:
  each raise bound as `r` (q = 0.012, and `q` equal to the no-raise bound, a
  zero carry that prices) and as `q`; the σ pair at `pu == 0.0` exactly and
  `pu < 0.0` (T = 60) and at `pu > 1.0` and `pu == 1.0` exactly (T = 20), both
  sides; `T` = -1.0, -5e-324 (raise), -0.0, 0.0, NaN, inf; σ NaN, inf, 0.0.
- Table `crr_engine` (144 rows): direct engine calls at `steps` -1, 0, 1, 2,
  3, 4 and 100 (every side, exercise, greeks and theta combination); `dx =
  0.1` with `pu == 1.0` and `pu == 0.0` exactly and each adjacent pair;
  `dx = 0.0` (`pu` NaN or ±inf), `dx` NaN, `dx < 0.0`; `disc = inf`, `S = 0.0`,
  `S` NaN and `K` NaN.
- Table `crr_tree` (12 rows): `pl_crr_mapped_tree` at `steps` -1, 0 (raise),
  1, 2, 3 and 100.
- Table `crr_lo` (288 rows): the brief grid (3 models × 2 sides × 6 T × 5 rate
  pairs) and the bound rows above, for every model and side.
- Direct checks: `steps` 1 and `PL_CRR_MAX_STEPS + 1` give
  `PL_ENGINE_QL_ERROR`, `PL_CRR_MAX_STEPS` prices, and a set defect stays set.

The light test `test_light_cvectors.py` (class `CrrVectorTests`) asserts on
the Python side: the brief rows come first; the statuses and defects of the
brief and edge rows; each bound pair is adjacent with the stated values
(`pu`, `g` and the raise outcome); every step outcome. Bound mutants of
`models.py` detected by the vectors (so the same change in C fails
`test_crr.c`): `<=` for `<` at `steps < 2`, `<` for `<=` at `pu <= 1.0`, `>`
for `>=` at `pu >= 0.0`, `<=` for `<` at `b < 0.0` of σ_trig, `>` for `>=` at
both domain conditions, and the swapped argument order of the node maximum and
of the initial maximum. Every bound mutant is detected; at each bound the
computed value is exactly on the bound in a vector row.

## Brent

`pl_solver.h` defines `PL_BRENT_ACCURACY` 1e-10, `PL_BRENT_MAX_EVALUATIONS`
200 and `PL_BRENT_N_MAX` 201 (spec 3.5). `pl_brent` copies
`optionlab.solver.brent` (solver.py:21-88: `Solver1D::solve` with the
`xMin`/`xMax` bracket, then `Brent::solveImpl`) statement by statement:
`math.fabs` is `pl_fabs`, `max(accuracy, QL_EPSILON)` is
`pl_max(accuracy, PL_QL_EPSILON)`, `close` is `pl_close`, `_sign` is a static
helper, `min1 if min1<min2 else min2` is `(min1 < min2) ? min1 : min2`, and
the Python integer literal `0` is `0.0`. Every division is IEEE C division and
equals the Python division, because no divisor can be 0.0: `fxMin` and `fxMax`
are values that `close()` has refused, and `p / q` is taken only when
`2p < |e q|`. The increment of `evaluationNumber` before the converged return
(solver.py:57) is not copied; its value is never read.

| Item | Contract |
|---|---|
| Objective `o` | borrowed, mutable, not NULL (NULL gives `PL_BRENT_DEFECT`); `kind` selects the value by a `switch`. `PL_OBJECTIVE_CUBIC`: `((c0 σ + c1) σ + c2) σ + c3` from `cubic`. `PL_OBJECTIVE_MODEL`: the row objective of "Row evaluation" (`pl_price`, then `pl_check_value`, then minus `mid`; `params` NULL gives `py_defect`). Any other kind: `py_defect = 1` and NaN. `params` may be NULL for the cubic objective. `pl_brent` never clears `domain` or `py_defect`, so each solve uses a fresh objective. |
| `lo`, `hi`, `guess`, `accuracy` | any doubles. Python raises `ValueError` (C `PL_BRENT_DEFECT`, in this order) when `accuracy > 0.0` is false (:23), `lo < hi` is false (:26), or, after the bracket, `lo < guess < hi` is false (:35); NaN makes each test false |
| `max_evaluations` | any `int` but `INT_MAX` (C contract: `INT_MAX` gives `PL_BRENT_DEFECT` with no call, so the count cannot overflow). Below 3 the loop never runs (`PL_BRENT_NOT_CONVERGED` after 3 calls) |
| `out` | written in full on every call; NULL: nothing happens |
| Status | `PL_BRENT_OK` 0, `PL_BRENT_BELOW_MIN` 1 (bracket failure with f(lo) > 0.0), `PL_BRENT_ABOVE_MAX` 2 (other bracket failure, NaN included), `PL_BRENT_NOT_CONVERGED` 3, `PL_BRENT_DOMAIN` 4 (an evaluation set `o->domain`), `PL_BRENT_DEFECT` 5 (a `ValueError` point, the C contract, or an evaluation set `o->py_defect`; `py_defect` is tested before `domain`) |
| `root` | the root for `PL_BRENT_OK` (b of the last pass, or the bracket end whose value is close to 0.0), else NaN |
| `f_lo`, `f_hi` | f(lo) and f(hi) when evaluated by a call that did not stop the solve, else NaN |
| `evaluations` | every objective call made, the call that stopped the solve included; at most `max(max_evaluations, 2) + 1`, so at most `PL_BRENT_N_MAX` for `PL_BRENT_MAX_EVALUATIONS` |

Tests (`tests/project/test_solver.c`, vectors from the check `c-vectors` part
`solver`, compared as equal status and count and equal bits or both NaN;
REQUIRE-style):

- Table `solver` (16 rows): the eight brief cubics with guess (lo + hi)/2,
  accuracy 1e-10 and `max_evaluations` 200 and 4; every count ≤ N_MAX.
- Table `solver_edge` (64 rows, `cvectors.solver_edge_rows`), each with its own
  guess, accuracy and `max_evaluations`: accuracy 0.0, -0.0, 5e-324, negative,
  NaN, QL_EPSILON and 1e-20 (clamped to QL_EPSILON); lo == hi, lo one double
  below hi, lo > hi, NaN; f == 0.0 and -0.0 at an end, f = ±tol² and the
  double below it (tol = 42 QL_EPSILON), roots on each end and on both; NaN and
  infinite ends; the guess at each end, one double inside each end, NaN,
  outside and inf; f(guess) == 0.0 and both sides of `froot*fxMin < 0`;
  `max_evaluations` -1, 0, 2, 3, 13, 14, 15 for a solve that converges at
  `evaluationNumber` 14; a bracket [-2^63, 2^62] that converges at 200
  (`max_evaluations` 199: `NOT_CONVERGED` with 200 calls; 200 and 201: OK with
  201 calls) and a bracket that converges at 201 (200: `NOT_CONVERGED` with
  exactly N_MAX = 201 calls); the ties |fxMax| == |froot|, |xMid| == xAcc1,
  |e| == xAcc1, p == 0.0 (through an infinite f) and 2p == min, and a row
  with |e| < xAcc1.
- Direct checks: the three brief `ValueError` cases, `o` NULL, `INT_MAX` and
  `INT_MAX - 1`, `out` NULL, `pl_objective_value(NULL, ...)`, the model kind
  without parameters and the ALO slot (defect at the first call), a BAW point
  that `baw_admit` refuses (domain with bit 64 at the first call), an unknown
  kind, and a set `domain` (then `py_defect`) that stops the solve at the
  first call.

The light test `test_light_cvectors.py` (class `SolverVectorTests`) asserts the
bound rows and their outcomes on the Python side. Bound mutants of
`solver.py` detected by the vectors (so the same change in C fails
`test_solver.c`): `>=` for `>` at `accuracy > 0.0`, the dropped
`max(accuracy, QL_EPSILON)`, `<=` for `<` at `xMin < xMax`, at both guess
tests, at the loop condition, at the swap and at the acceptance `2p < min`,
`<` for `<=` at the stopping rule, `>` for `>=` at `|e| >= xAcc1`, `>=` for
`>` at `p > 0.0`. Equivalent mutants (no input distinguishes them; the reasons
are in the test file): the argument order of `max(accuracy, QL_EPSILON)`, the
bracket product and `fxMin > 0.0` (close() returns first for |f| < tol²), the
side test `froot*fxMin < 0`, the same-sign reset, `|fxMin| > |froot|`,
`min1 < min2` and its argument order, `|d| > xAcc1` and `_sign`'s `b >= 0.0`.
Coverage: the stop branches after the second objective call (f(hi)), the
guess call and a loop call are reached by the model objective (the
`BRENT_STOP_ROWS` of part `evaluate`, which stop with `MODEL_DOMAIN` after 2,
3, 4 and 5 calls). The stop branch after the final call f(root) is
unreachable: `root` is always a point whose value an earlier call of the same
solve returned without a stop (the guess, a loop iterate, or an end after the
swap), and every objective is a deterministic function of σ, so the final call
returns that value again. A `py_defect` after the first call is unreachable
with the model objective too: every Python raise point of a price evaluation
depends on the rates and T only, never on σ, so it stops the solve at the
first call. The four stop sites share one helper (`evaluate`), whose
`py_defect` and `domain` branches are both covered.

## Row evaluation

`pl_evaluate.h` copies `optionlab.reference` (reference.py:20-109) and
`optionlab.mapping.greeks_from_unit` (mapping.py:16-38) for the models
`bsm`, `bjs`, `crr`, `baw` (Task 10a) and `alo` (Task 10b; the ALO lines of
the merged reference.py, 159-211, 253-257, 297-319). `PL_MASK_WIRED` is
`PL_MASK_MODELS5` (31) since Task 10b; the first statement of `pl_evaluate`
still returns `PL_EVAL_DEFECT` for a model whose bit is not wired (ruling 46,
approver finding L1), which no model of `MODELS5` now reaches.

| Function | Inputs, outputs and failure behavior |
|---|---|
| `pl_tau_v(S, K, T, r, q, defect)` | τ_V = ((4 QL_EPSILON) D_r) max(F, K), D_r = `pl_discount(r T, 1.0)`, D_q = `pl_discount(q T, 1.0)`, F = `pl_py_div(S D_q, D_r)`; `pl_max(F, K)` keeps a NaN F. Sets `*defect` at each Python raise point: a zero exponential in a discount (models.py:96), D_r == 0.0 (reference.py:30), T < 0.0 (`math.sqrt` of `mapping.unit`; the row path never passes it, so `pl_unit` keeps its T ≥ 0.0 precondition). `defect` is not NULL and only set. |
| `pl_check_value(o, v)` | `Checker` (reference.py:36-39) with τ = `o->tau`: 1 and `o->domain = 1` when v is not finite or v < -τ; else `o->band = 1` when v < 0.0 (-0.0 is not negative), and 0. `o` NULL: 1 (C contract). |
| `pl_price(model, side, S, K, T, r, q, σ, p, value, flags)` | `models.price` (models.py:485-492): the engine of the model with greeks off (CRR: American, `p->crr_steps`); BAW: `reference.price_function` (`pl_baw_price`: `baw_admit` first; a refused point sets bit 64 in `*flags` and gives `PL_ENGINE_QL_ERROR`). `PL_ENGINE_QL_ERROR` (`ModelDefect`), `PL_ENGINE_PY_DEFECT` (a zero discount; a BAW run defect; the ALO slot; any other model; NULL `p`, `value` or `flags`), `*value` NaN unless OK. |
| `pl_price_and_greeks(model, row, σ, p, values, band, flags, engine_evals)` | `price_and_greeks` (reference.py:66-70): τ_V of the row, then the greek step at σ. Returns `PL_GREEKS_OK` 0, `PL_GREEKS_DOMAIN` 1 (an engine error, a value outside the order-5 check, a field that is not finite; BAW: a refused point, bit 64, or no row-side stencil, bit 16) or `PL_GREEKS_DEFECT` 2 (a Python raise point, a BAW run defect, the ALO slot, an unknown model, a NULL argument); `*flags` the BAW bits. `values` NaN unless OK; `*band` the Checker band; `*engine_evals` += 1 per engine call. `row->bid` and `row->ask` are not read. |
| `pl_greeks_at(o, iv, values, engine_evals)` | the greek step of a model objective (`o->params` not NULL), below; `PL_GREEKS_OK` writes `values`, `PL_GREEKS_DOMAIN` and `PL_GREEKS_DEFECT` leave them unchanged. |
| `pl_evaluate(row, model, p, out, engine_evals)` | `evaluate` (reference.py:72-109), below. Returns `PL_EVAL_DEFECT` exactly where Python raises, and for the C contract: a model whose bit is not in `PL_MASK_WIRED` (the first statement), a NULL argument, a model outside 0 to `PL_MODEL_ALO`, `p->baw_newton_max` outside 0 to `PL_BAW_NEWTON_MAX`, `p->crr_steps` outside 1 to `PL_CRR_MAX_STEPS` (the stack lattice bound; Python raises for steps < 1 and computes above 100, so a larger value is outside the C contract), `p->kappa_cap` not > 0.0 or `p->h_r` not ≥ 0.0 (Python `sigma_lo` divides by κ_cap and takes the square root of abs(b) + h_r), `p->alo_plant_site` outside 0 to `PL_ALO_PLANT_SITES` or `p->alo_force` outside 0 to `PL_ALO_FORCES`. ALO: the `read_back` of `alo_equation(r T, q T)` runs before σ_lo (`alo_rates_raise`), so a zero exponential is a defect at the same point as in Python; the IV-call fact (the last Brent call is at the root, else `AloRunDefect('alo-iv-call')`) is checked after an OK solve; a run defect of any ALO evaluation is a defect. After a defect `out` holds `PL_INVALID_INPUT`, flags 0 and NaN values, `*engine_evals` 0, and the run fails as a whole (`KERNEL_FAILURE`). |

Status order (spec 3.3, first match wins; reference.py:86-93): side not 0 or 1,
a non-finite S, K, T, bid or ask, S ≤ 0.0 or K ≤ 0.0 → `INVALID_INPUT`; T ≤ 0.0
→ `EXPIRED`; bid ≤ 0.0 → `NO_BID`; ask < bid → `CROSSED` (ask == bid is
priced); σ_lo ≥ σ_hi → `MODEL_DOMAIN`; CRR and not `pl_crr_domain_ok` →
`MODEL_DOMAIN`; BAW and `pl_baw_admit_rates` at r T, q T in scope and not
admitted → `MODEL_DOMAIN` with bit 64 only (reason `row`). Then τ_V (a raise there is a defect: it is outside the Python
`try`), then `pl_brent` on [σ_lo, σ_hi] with the guess (σ_lo + σ_hi)/2.0,
`PL_BRENT_ACCURACY` and `PL_BRENT_MAX_EVALUATIONS`, with a fresh model
objective (f(σ) = checked engine value - mid). Order-5 rule: a
`PL_BRENT_DOMAIN` solve (an engine error, a value that is not finite or below
-τ_V) is `MODEL_DOMAIN` with only the band flag (the Python `except` returns
before the boundary test); `PL_BRENT_DEFECT` is a defect (a raise in an engine
or a solver `ValueError`: :23, :26, :35; σ_lo within 2 ulp below σ_hi makes
the guess not strictly inside). Rounding band: a value in -τ_V ≤ v < 0 is used
as computed and sets `rounding_band`.

Flags, in the Python order: `boundary_ambiguous` (2) when abs(f(lo)) ≤ band or
abs(f(hi)) ≤ band, band = 1e-9 max(1.0, mid) (f(hi) NaN when not evaluated);
for a solve that is not OK, `below_intrinsic` (1) for `BELOW_MIN` with mid <
max(S - K or K - S, 0.0), then the status with the band flag; for OK, the
greek step (a `MODEL_DOMAIN` there keeps the flags so far and the band flag),
then `rounding_band` (8), then `flat_vega` (4) when vega × 100.0 < 1e-12.
Non-OK rows have NaN in every field.

Greek step (reference.py:45-64, mapping.py:16-38, Amendment B3 chain rule):
the engine with greeks at the root (CRR American with theta), the order-5
check of its value; BSM and BjS: vega = (sqrt(T) vega_U) 0.01 and rho =
(T rho_U) 0.01; CRR: the bumps in the original variables, each a checked
`pl_price` of CRR: vega = (V(iv + h_σ) - p)/h_σ when iv - h_σ < σ_lo(CRR), else
(V(iv + h_σ) - V(iv - h_σ))/(2 h_σ); rho = (V(r + h_r) - V(r - h_r))/(2 h_r),
then × 0.01; theta = theta_U / T / 365.0 for every model (theta_U is present);
a field that is not finite gives `MODEL_DOMAIN`. A raise in a bump (the rate
r ± h_r crosses a raise bound of the CRR tree) is a defect, and so is a bump
division by h_σ = 0.0 or h_r = 0.0 (reference.py:59-60, `pl_py_div`; BSM and
BjS never divide by them, so h = 0.0 is in the parameter contract).

Engine-evaluation count (G3.7, controller count rule): every engine price
evaluation counts 1 (each Brent call, the call that stopped the solve
included), the greek call of an OK solve counts 1 and each bump 1; a row
stopped before the engine counts 0; a defect row reports 0 (the run fails).
`*engine_evals` equals the `py-reference` `engine_evals` of the row (the
fourth value of `reference.evaluate`). BAW: a Brent evaluation that
`baw_admit` refuses raises before the Python count, so the solve that it stops
counts its evaluations less one; the greek step counts the row point and each
evaluated stencil point (side tests are not counted).

Raise audit (the census of the check `c-census`, 1,000 hostile rows ×
`EVALUATE_MODELS` = `bsm`, `bjs`, `crr`, `baw`; line numbers of the merged
G-BAW2 code, which moved models.py and reference.py): only `ZeroDivisionError`
at models.py:109 (`discount`, was :96; 98 raises) and reference.py:43 (the F of
τ_V, the brief's reference.py:29; 43 raises) occurred; the 101 distinct raising
rows are unchanged by `baw` (Task 10b adds `alo`: see "ALO (Amendment I)",
raise audit). The other audit-table points (models.py:116, :118,
:376, :377, the former :103, :105, :363, :364; solver.py:23, :26, :35; the BAW
run defects baw_admit.py:140 cap hit and :152 non-finite S*; the plain
divisions of `baw_admit.certificate`, baw_admit.py:181-183, 190-192, 194, and
of the stencils of `reference.baw_greeks`, reference.py:112, 116, 126-128,
139-140) are in the expected list. The vectors reach models.py:109 (τ_V,
`RAISE_ROWS[6]` through :379, a CRR bump r - h_r), reference.py:43,
models.py:376 (a CRR bump r + h_r), models.py:377 (`RAISE_ROWS[5]`),
solver.py:35 (the σ_hi rows), the BAW cap hit and the planted non-finite S*
(the `baw_newton_max` 1 and planted rows) and the certificate divisions at L
and 1.0/Q (crafted rows of table `baw_cert`); no row reaches :116, :118 (their
discounts are of rates times 0.0001), :23 (the accuracy is a constant) or :26
(σ_lo ≥ σ_hi stops first; a NaN σ_lo cannot occur). C mirrors each
with `pl_py_div` or `PL_BRENT_DEFECT`. The trap row `RAISE_ROWS[5]` raises
for `crr` only.

Tests (`tests/project/test_evaluate.c`, vectors from the check `c-vectors`
part `evaluate`; REQUIRE-style): table `evaluate` (each row × `bsm`, `bjs`,
`crr`: the synthetic prefix and rows 101 and 151, the oracle edge rows with
their parameters, `EDGE_ROWS`, `RAISE_ROWS`, the census raising rows and the
bound rows) compares the status, flags, count and value bits, and
`PL_EVAL_DEFECT` exactly at the Python raises; tables `evaluate_check`,
`evaluate_tau` and `evaluate_greeks` compare the Checker, τ_V and the greek
step alone. Table `evaluate_greeks_param` (in `pl_vec_evaluate_baw.h`, tested
by `test_evaluate_baw.c`: `test_evaluate.c` is at the AST dump size limit)
holds the greek-step rows with other h_r and h_σ: the CRR stop at bump 2,
iv - h_σ, with b < 0 (T = 1403.98, r = 0, q = 0.016421027311254225, h_r = 0,
h_σ = 0.1 at iv = 0.1615906653407873 gives order 5 after 3 engine calls). Bound rows (`cvectors.evaluate_bound_rows`): S, K, T, bid at 0.0,
-0.0 and ±5e-324, ask one double below bid, equal and above; f(σ_lo) and
f(σ_hi) exactly ±band and one double each side, per model; mid == S - K and
K - S exactly and one double each side; σ_lo == σ_hi exactly (BjS carry, and
κ_cap 1.405 with σ_hi at σ_lo, the next double, which raises at solver.py:35,
and the double after); the CRR domain bound in T; the Brent stops after 2, 3,
4 and 5 calls; the greek-step stops (a non-finite CRR gamma, a bump outside
the order-5 check, two bump raises); iv - h_σ == σ_lo exactly and
vega × 100 == 1e-12 exactly, each with its flip pair. Direct checks: the C
contract (also `baw_newton_max` -1, 41 and 0), the ALO slot (the defect for
an expired row too; `PL_MASK_WIRED` 15), `pl_price` and
`pl_price_and_greeks` outside the tables, and the same result for one row
before and after every `MODEL_DOMAIN` and defect row of the table (a fresh
objective per row). Bound mutants of reference.py detected by the vectors
(light test `EvaluateVectorTests`): `<` for `<=` at S, K, T and bid; `<=` for
`<` at ask < bid, iv - h < σ_lo, vega × 100 < 1e-12 and mid < max(...); `>`
for `>=` at σ_lo ≥ σ_hi; `<` for `<=` at both band tests; `<=` for `<` at
both Checker tests; the argument order of max(F, K).

## BAW (Amendment G)

QuantLib 1.43 `BaroneAdesiWhaleyApproximationEngine` (spec Amendment G item
G2, Appendix G-BAW with the errata F1-F7 and the rulings R(a)-R(c), which
replace the plan text where they differ). The definition is the merged
G-BAW2 Python code (perf-lab 14747b4, merged at 79deddd); each C function
copies one Python function statement by statement, with the same operation
order, association and constants (Amendment F item 8, N1a).

| Python (file:lines at the merge) | C (file) |
|---|---|
| `baw_admit.discounts` (40-42), `close_n` (44-49), `black_formula` (53-73), `_seed` (75-90), `_kcoef` (92-95), `_qexp` (97-100), `_map` (102-116), `_stop` (118-120), `_update` (122-125) | `pl_baw_discounts`, `pl_baw_close_n`, `pl_baw_black_formula`, `pl_baw_seed`, `pl_baw_kcoef`, `pl_baw_qexp`, `pl_baw_map`, `pl_baw_stop`, `pl_baw_update` (`pl_baw_map.c`) |
| `baw_admit._sups` (155-165), `certificate` (167-210) | `sups` (static), `pl_baw_certificate` (`pl_baw_cert.c`) |
| `baw_admit.baw_admit_rates` (212-220), `baw_admit` (222-248) | `pl_baw_admit_rates`, `pl_baw_admit` (`pl_baw_admit.c`) |
| `baw_admit.critical_price` (129-144), `sstar` (146-153) | `pl_baw_critical_price`, `pl_baw_sstar` (`pl_baw.c`) |
| `baw._black_checks` (22-27), `baw.engine` (29-63) | `engine_checks` (static), `pl_baw_engine` (`pl_baw.c`) |
| `models.baw_result` (478-482) | `pl_baw_result` (`pl_baw.c`) |
| `reference.price_function('baw')` with `baw_admitted` (54-69) | `pl_baw_price` (`pl_baw.c`), the BAW case of `pl_price` |
| `reference.baw_point_side` (71-79), E of `baw_greeks` (96-98) | `pl_baw_point_side`, `pl_baw_on_row`, `pl_baw_point_value`, `pl_baw_two_values` (`pl_baw_points.c`) |
| `reference.baw_greeks` (83-147) | `pl_baw_s_try`, `pl_baw_two_point_try`, `pl_baw_t_try` (one attempt, `pl_baw_stencil.c`); `pl_baw_greeks_at` with the halving loops (`pl_baw_greeks.c`) |
| `reference.price_and_greeks('baw')` (177-185) with the counter of `evaluate` | `pl_baw_price_and_greeks` (`pl_baw_greeks.c`) |
| `reference._evaluate`, BAW lines (214-216, 219-224, 232-237) | `pl_evaluate` (row check, Brent count), `pl_greeks_at` (dispatch) |

Names (adaptation rule of the plan, Task 10a Step 3): the merged code has no
`BOUNDARY_VECTORS`, `ADMIT_FIELDS`, `baw_admit_detail`, `EDGE_ROWS` or
`EXCLUDED_ROWS`, `models.baw_result` returns only the result dict, the test
parameter is `baw_plant_nan_sstar` (C member `baw_plant_nonfinite_sstar`), the
run-defect class is `models.BawRunDefect` (a `ModelDefect` subclass that
`reference.evaluate` re-raises), the exclusion class is `models.AdmitExcluded`
with `reason`, and `price_and_greeks` returns the key `flags`. `cvectors.py`
reads every intermediate as a local of the merged function itself when it
returns (`sys.settrace` on that one frame; `_traced`), with `exit` the
position of the return statement; the iteration count is
`critical_price(...)[1]`; the greek count is the `ev` counter of
`reference.baw_greeks`.

Intermediates of `pl_baw_admit` (`struct pl_baw_admit` `values`, the order of
`cvectors.ADMIT_FIELDS`, `PL_BAW_ADMIT_FIELDS` 18 of
`PL_BAW_ADMIT_MAX_FIELDS` 32): D_r, D_q, n, m, bT, q_u, S_u, h, S_i, 𝒦, Q, j
(replay index), x (last iterate), LHS, RHS, b_i (last map), N_C (last
certificate, -1.0 for None), exit (1 branch gate, 2-7 checks 2a-2f, 8 iterate
not finite or not positive, 9 a map check raised, 10 a map value not finite,
11 stop test, 12 certificate, 13 no admission after 40 updates). A quantity
the call did not compute is NaN. `defect` is 1 where Python raises (a plain
division of the certificate); the result then fails closed (in_scope 1,
admitted 0). The 33
certificate intermediates (`cvectors.CERT_FIELDS`): σ̂, |Q|, ĝ, d̂, β̂, w, R,
x_lo, x_hi, Σ_b, Γ, ν, c_r, δ_g, δ_b, d_low, β, ℓ_lo, ℓ_hi, d_lo, d_hi, Δ, s_n,
s_dn, L, M, m, η, target, ρ, b, k, exit (1-11).

Constants and rules (record items): tolerance 1e-6 relative to K (R3, line
198); `baw_newton_max` = `PL_BAW_NEWTON_MAX` 40, the protected case parameter
(R3; `baw_admit` always uses it, a test parameter set changes only the cap of
the critical price); the run defect only when the stop test still fails after
`baw_newton_max` updates (F6); a NaN iterate raises at the map (F1, order 5);
the branch gate D_q ≥ 1.0 and a call (R5, line 167; with the container glibc
`exp`, q' ≤ 2^-53 gives D_q = 1.0, F2); σ_lo(BAW) = max(1e-4, σ_trig), σ_trig =
1.001 (|b| + h_r) sqrt(T) / 2 when b < 0, b = r - q for a call and q - r for a
put (R9, F3); h_S = min(1e-3, 0.1 σ sqrt(T)) S, h_σ = 1e-3 (forward also when
σ - h_σ < σ_lo), h_r = 1e-4 with q fixed (forward only when r - h_r < 0,
strictly, R(c)), δ = min(1/365, T/2) (T - δ, then T + δ, F4); at most
`PL_BAW_HALVINGS` 4 halvings; a European-branch stencil point is off the
American row side (R(a)).

Greek table (R6): European branch: the engine greeks, theta case (a); American
branch, exercise side: delta ±1, gamma, theta, vega, rho exactly 0, no point;
continuation side: the R7 stencils (S central, else one-sided three-point; σ
and r central, forward or backward; T backward, else forward), each point
through the mapping, `baw_admit` and the S* side test. Flags: 32 on an OK row
whose stencil is one-sided, forward or backward where the default is another
form, or halved; 64 when `baw_admit` refuses a Brent or greek point, or the
row check (reason `row`); 16 when no row-side stencil exists after 4
halvings; an order-5 row never carries 32 (R(b)).

Status mapping (R8): a QuantLib check (S ≤ 0, the BlackCalculator checks,
D_r > 1 at the critical price, a `blackFormula` check of the map) is
`PL_ENGINE_QL_ERROR` (order 5); a refused point is order 5 with bit 64; the
run defects (cap hit, non-finite S* after the iteration, the planted S*, a
zero divisor of the certificate or of a stencil, a zero exponential of
`mapped_inputs`) are `PL_ENGINE_PY_DEFECT` and `PL_EVAL_DEFECT` (the run fails
as a whole, `KERNEL_FAILURE`), never a status or the intrinsic value.

Inputs and limits: side 0 call, else put; `newton_max` ≥ 0 (the C contract of
`pl_evaluate` takes 0 to 40); every loop is bounded (the replay by 41 maps,
the critical price by `newton_max` updates, the certificate rate loop by
`cap`, each stencil by 5 attempts); no allocation; outputs are the caller's
objects only.

Bound mutants (light tests `BawVectorTests` and `BawCertMutantTests`; each
mutant changes a vector result, so the same change in C fails a C test): the
stop test `> 1e-6` as `>=` (row `STOP_TIE_ROW`: put S = 100,
K = 100.00000000331966, T = 1, r = 0.04, q = 0.012, σ = 0.7484764768838362,
where the second iterate gives |LHS - RHS| / K == 1e-6 exactly; the strict test
stops after 2 updates, `>=` makes a third; in tables `baw`, `baw_critical`,
`baw_greeks` and `evaluate_baw`); the certificate checks at an exact bound
(table `baw_cert`, each tie row with a one-past row one double away that gives
the other outcome): x_lo > 0 (x0 = 1, K = 2^24 - 1, ĝ = 0 gives w = R = 1 and
x_lo == 0.0), d_low > 0 (|d̂|(1 - u) == δ_b exactly, b_i = 1 - d̂ exact),
δ_b + u(1 + Σ_b) ≤ m/2 (v = 1e-20, Q = 1e-6, so L is about 1e-281 and
m == d_low, with d̂ set near (2(δ_b + u(1 + Σ_b)) + δ_b)/(1 - u) and moved by
ulps until equal), and m > 0, 4β + 2η + 4u x_hi ≤ R, 2η ≤ w,
M·2η + δ_g ≤ target, ρ ≤ 0.5(1 - 2^-20), M·2(β + η) ≤ target and the rate-loop
test M·max(b m/L, 2η) ≤ target, each constructed on the call family x0 = K =
100, D_r = 0.96, D_q = 0.99, v = 0.04, Q = 2, d̂ = D, ĝ = r D (or on a replay
call): the adjacent pair in ĝ where the check changes, then one of D_r, K,
D_q, x0, v moved by at most 1,500 ulps (arguments that move each side by a few
ulps per step) until both sides are equal, checked on a copy of the merged
`certificate` text (`cvectors.cert_tie_rows`, `_cert_grid_tie`,
`_cert_line_tie`); the r stencil `r - h_r >= 0.0`, the σ stencil
`iv - h_σ >= σ_lo`, the side test strictness, the engine tests `S < S*`,
`S > S*` and `D_q >= 1.0`, and the σ_lo(BAW) carry sign `b < 0.0`. Bit 16 is
reached in table `baw_greeks` (puts with r = 1e-6 < h_r/16 and q = 0, S one
double above S*: no backward r point at any halving and every forward point on
the exercise side). All ten certificate bound mutants (`<=` as `<`, `>` as `>=`) are detected
(ledger P2-T10A-CERTTIE-02, verified).

Result-equivalent (ledger P2-T10A-CAPTIE-01, controller ruling after the
Phase 1 review of a test-only cap, 03524bf): `j + N_C <= cap` as `<` in
`baw_admit` (baw_admit.py:246). The two forms differ only at j + N_C == 40.
There the original admits; the mutant makes the update instead. By record R4
item 5, given a sound certificate, the iterates from x_j stay in J, stay
finite and positive, and pass the stop test after at most N_C updates, at a
replay index ≤ j + N_C = 40, which the replay (j = 0 ... 40) still examines; so
the mutant admits too, and the returned (in_scope, admitted) never changes.
Only N (the number of map calls) and the work change. Python detects the
mutant only through a test-only map-call count; the C port adds no such hook,
and no result kills it. Supporting bounds: N_C ≤ 31 when the certificate
returns k ≥ 1 (ρ ≤ 0.5(1 - 2^-20) gives b_k = fl(b_(k-1)^2) ≤ exp(-2^(k-21)),
so b_31 rounds to 0.0, and the rate test then holds because check 7 held and
(M·2)·η and M·(2η) are the same exact product); j is bounded only by the cap;
the 16 of R13 is a measured maximum and F6 allows N(inputs) = 40.

Tests (vectors of the check `c-vectors`; REQUIRE-style, one test file per
header for the AST dump limit): `test_baw_admit.c` (table `baw_admit`: the N8
grid, 864 rows: booleans, defect and every intermediate bit for bit);
`test_baw_cert.c` (table `baw_bound`: the boundary vectors of R4 and the
search rows of the exits; table `baw_cert`: replay certificate calls, the rate
loop with cap 0, 1, 2, crafted zero divisions); `test_baw.c` (params with the
generator's `PL_VEC_BAW_NEWTON_MAX`, table `baw_lo` for σ_lo(BAW) on the
crr_lo grid, table `baw` for the engine with and without greeks, the
iteration count and S* under the case, forced-cap and planted sets, table
`baw_critical` for the critical price at the exact count, one less, 0, 1, 2
and 40, and the bounded check); `test_baw_greeks.c` (table `baw_greeks`:
status, band, flags, count and values of the greek step at a chosen σ, also
through `pl_price_and_greeks`: exercise side, S* neighbours, the σ_lo + h_σ
bound, r = h_r, puts with r = 1e-6 next to S* (bit 16), the stop-test tie row, calls with q T next to
2^-53); `test_evaluate_baw.c` (table `evaluate_baw`: `pl_evaluate` of `baw` on
every row of part `evaluate` and the BAW rows, including the row, Brent and
bump exclusions and the two run defects).

## ALO (Amendment I)

QuantLib 1.43 `QdFpAmericanEngine` with `accurateScheme` (Andersen-Lake-
Offengenden; spec Amendment I, Appendix I-ALO with the errata E-ALO-1 to
E-ALO-6 and the records R1-R12). The definition is the merged G-ALO2 Python
code: `optionlab/alo.py` (567f6c4), `optionlab/alo_equation.py`,
`optionlab/alo_tables.py` and the ALO lines of `optionlab/reference.py`
(490dce1), and `models.sigma_lo` (models.py:528-542). Each C function copies
one Python function statement by statement, with the same operation order,
association and constants (Amendment F item 8); every result is bit-equal to
`py-reference`.

| Python (file:lines) | C (file) |
|---|---|
| `alo_equation.side_index` (27-31), `read_back` (33-40), `alo_equation` (42-46), `_xmax_case` (48-58), `alo_segment` (60-) | `pl_alo_read_back`, `pl_alo_equation_of`, `pl_alo_equation`, `pl_alo_xmax_case`, `pl_alo_segment`, `pl_alo_segment_equal` (`pl_alo_equation.c`) |
| `alo._m` (133-138), `nan_check` (140-143), `_guard` (145-148), `_cap` (150-152), `smax`, `smin`, `close_enough` (154-163) | `pl_alo_mask`, `pl_alo_check`, `pl_alo_guard`, `pl_alo_cap`, `pl_alo_fail`, `pl_alo_min`, `pl_alo_close_enough` (`pl_alo_run.c`) |
| `alo.Cheb` (333-357) | `pl_alo_cheb_init`, `pl_alo_cheb_nodes`, `pl_alo_cheb_value` (`pl_alo_cheb.c`) |
| `alo.xmax_fn` (359-368), `QdPlusEval` (370-415), `qd_boundary_at_tau` (417-438), `_qd_brent` (440-467), `qd_boundary_interp` (469-478) | `pl_alo_xmax`, `pl_alo_qdplus_init`, `pl_alo_qdplus_value`, `pl_alo_boundary_value`, `pl_alo_boundary_at_tau` (`pl_alo_qdplus.c`) |
| `alo.FpEquation` (480-551) | `pl_alo_fp_boundary`, `pl_alo_fp_f`, `pl_alo_fp_ndd` (`pl_alo_fp.c`) |
| `alo.GL_X`, `GL_W` (85-96), `_t_from_abscissa_complement`, `T_CROSSOVER` (169-173), `TanhSinhDetail.__init__`, `extend_refinements`, `_row` (175-206), `alo_tables` | `pl_alo_gl_node`, `pl_alo_gl_weight`, `pl_alo_ts_crossover`, `pl_alo_ts_row`, `pl_alo_ts_entry` and their `_with` forms (`pl_alo_tables.c`) |
| `TanhSinhDetail.integrate` (207-301), `tanh_sinh_integrate` (303-331) | `pl_alo_ts_level` (one level, `pl_alo_ts_level.c`), `pl_alo_ts_u`, `pl_alo_ts_integrate` (`pl_alo_ts.c`) |
| `alo._black` (553-559), `calculate_put` (561-624) with `aov` (599-624), `put_with_edge_cases` (626-648), `engine` (650-659), `pre_check` (661-664), `mapped_point` (670-674), `price` (676-693) | `pl_alo_addon_value`, `pl_alo_engine`, `pl_alo_result` (`pl_alo.c`) |
| `reference.alo_pre` (159-163), the E of `alo_greeks` (165-176) | `pl_alo_point_value`, `pl_alo_same_segment` (`pl_alo_points.c`) |
| `reference.alo_greeks` (178-211), `price_and_greeks('alo')` (253-257) with the counter of `evaluate` | `pl_alo_greeks_at`, `pl_alo_price_and_greeks` (`pl_alo_greeks.c`) |
| `reference._evaluate`, ALO lines (297-319) | `pl_evaluate` (read-back raise, Brent count, IV-call fact), `pl_brent` objective (`pl_solver.c`: the pre check before the count) |

Adaptation (plan names to the merged code): the statistics are `alo.Stats`
(`qd_calls`, `halley_max`, `fallback_nodes`, `fallback_max`, `levels`,
`integrand`, `guarded`), the C `struct pl_alo_trace` holds the same members
with the failed check and the failed cap; the run defect is
`models.AloRunDefect` with the site in `args[0]` (`alo-nan`, `alo-cap`,
`alo-iv-call`); `AloEngineError`, `AloInnerSolverError` and `AloPreCheck` are
`ModelDefect` subclasses (order 5). `struct pl_alo_rates` and
`struct pl_alo_segment` hold a `defect` member for the `ZeroDivisionError` of
`read_back`. `cvectors.py` reads each intermediate as a local of the merged
function when it returns (`_alo_trace`, `alo_equation_detail`,
`alo_segment_detail`).

Constants (the protected case key `alo_scheme`, case manifest v3; each macro is
compared with the generator's `optionlab.params.CASE.alo_scheme` in
`test_alo.c`, and `--print-params` prints the macros): scheme
`accurateScheme`, fixed-point equation `Auto` (switch `|r_e - q_e| < 0.001`,
`PL_ALO_AUTO_THRESHOLD`), l = 25 (`PL_ALO_GL_ORDER`), m = 5
(`PL_ALO_FP_STEPS`), n = 13 (`PL_ALO_CHEB_N`, 14 nodes), tanh-sinh tolerance
1e-8 (`PL_ALO_TS_EPS`), QD+ ε 1e-8, Halley at most 10 iterations, inner Brent
at most 100 evaluations, tanh-sinh at most 15 refinements.

Tables: the frozen Gauss-Legendre table of record R5 as hex-float literals
(`alo.GL_X_BITS`, `GL_W_BITS`, x() order, the sums run from i = 24 down to 0,
`GL_REV`); the tanh-sinh rows 0-7 as Boost's decimal literals (769 entries,
the compiler reads each with correct rounding, as Python's `float()` does);
rows 8-14 computed on request in Boost's operation order at the exact
position (2j + 1) 2^-k (the C accepts row 15 too, `PL_ALO_TS_ROWS` 16; the
integral reports at most 15 levels). The computed rows are not stored: their static storage would be
about 3.1 MB, above the 1 MiB rule, and a lazily filled cache would be mutable
shared state. One table entry per line keeps clang-format from packing the
lists. Levels above 7 occur in no vector row (maximum 7). Table `alo_ts`
(2,165 entries) holds every entry of rows 0-7 and sampled entries of rows
8-14 (Boost's 15 refinements, index 0-14); table `alo_ts_rows` holds each
row's length and first complement index, and `PL_VEC_ALO_T_CROSSOVER`
t_crossover. Table `alo_ts_digest` (ruling R-10c, T10B-TS-SAMPLE-01) holds
one digest per row 0-14 over every entry: 64-bit FNV-1a (offset basis
0xcbf29ce484222325, prime 0x100000001b3, modulo 2^64) over the bytes of the
row in entry order, for each index the 8 bytes of the abscissa bits, least
significant byte first, then the 8 bytes of the weight bits
(`cvectors.alo_ts_digest`). `test_alo_equation.c` recomputes each digest from
`pl_alo_ts_entry`, so every one of the 98,305 entries (97,536 in rows 8-14)
has a bit-exact check.

Check sites (record R7 item 3, E-ALO-4; `enum pl_alo_check`, the order of
`cvectors.ALO_CHECK_SITES`): the pre check of the mapped point (order 5,
`AloPreCheck`, not counted as an engine evaluation), then the QD+ solver
values, the boundary after the QD+ interpolation, the boundary after each
sweep, the integrand arguments, the integrand value, the integral and the
European value: a NaN at a run-defect check is `PL_ENGINE_PY_DEFECT`
(`AloRunDefect('alo-nan')`, H19). A guarded NaN (`_guard`) counts in
`nan_guarded` and never changes a result.

Caps (record R3, `alo.CAPS`; `PL_ALO_CAP_*`): Halley 10, doubling 1, inner
Brent 101, sweep f 65, sweep NDd 13, levels 15, integrand 196,695, QD+ calls
1,469. A count above its cap is `AloRunDefect('alo-cap')`, a run defect.

Test-only parameters (I4.1; `struct pl_params` members, 0 in the case):
`alo_plant_site` 1-20 plants a NaN at site k of `cvectors.alo_plant_sites()`
(`alo.VALUE_MASK_SITES`, the 18 sites, then `EUROPEAN_MASK_SITES`
`qdplus:208`, then the persistent `qdplus:66` of AI3-02), at the first
occurrence in each engine evaluation (the persistent site at every
occurrence); `alo_force` 1 forces every node solve into the inner Brent
fallback, whose bracket check then fails (`force_inner_bracket_error`,
order 5), and 2-9 takes the cap of loop `alo_force - 1` (CAPS order) as 0
(`force_cap_excess`). A value outside its range is the C contract
(`PL_ENGINE_PY_DEFECT`, `PL_EVAL_DEFECT`).

Greek step (record R6, I2.6; `pl_alo_price_and_greeks`, contract in
`pl_alo.h`): τ_V, the pre check and the checked price at σ (not counted:
the price of a row is the last Brent value, H17), then delta and gamma from
the central S stencil with h_S = min(1e-3, 0.1 σ sqrt(T)) S; vega with h_σ,
central, forward when σ - h_σ < σ_lo(ALO); rho with h_r and q fixed,
central when both points have the row's `alo_segment`, else the one-sided
difference whose point has it, else h_r halved; theta case (c), backward with
δ = min(1/365, T/2) when T - δ has the row's segment, else forward, else δ
halved; at most `PL_ALO_HALVINGS` 4 halvings. Flags: 32 `stencil_switched`
on an OK row whose rho or theta stencil is switched or halved, 16
`stencil_unresolved` (order 5) when no row-segment stencil exists after the
halvings (a put with r = 0 exactly). The count: each stencil point that passes
the pre check (S 2, vega 2 or 1, rho 2 or 1, theta 1), so `engine_evals` =
n_Brent + 7 with central stencils (H17; `IV_CALL_TERM` 0).

Status mapping (record R8): a QuantLib or Boost error, an inner QD+ Brent
error and a failed pre check are `PL_ENGINE_QL_ERROR` (order 5); a failed
NaN check, a cap excess, the IV-call fact, a zero exponential of `read_back`,
a division by v = 0.0 in `QdPlusEval.pre` and a stencil division by 0.0 are
run defects (`PL_ENGINE_PY_DEFECT`, `PL_EVAL_DEFECT`, the run fails as a
whole), never a status or the intrinsic value. Bit 64 stays illegal in the
`alo` flag byte (no `alo_admit`).

Inputs and limits: side 0 call, else put (a side outside 0 and 1 raises in
`side_index`); every loop is bounded by its cap or by its row; no
allocation; the outputs are the caller's objects only; no static mutable
state (the planted and forced hooks read `p`).

Raise audit (census over `EVALUATE_MODELS` with `alo`, 39 anchors, 122
distinct raising rows; the 101 earlier rows keep their order): new raises
`AloRunDefect` at alo.py:143 (21 rows) and `ZeroDivisionError` at
alo_equation.py:36 and :37 (`read_back`). The anchors also list `_cap`, the
IV-call fact, `QdPlusEval.pre` and the eight divisions of `alo_greeks`, which
no census row reaches. CA-01 (controller ruling R-10b-CA01): the anchors
`if sideof(S-h…)` (reference.py:120), `d=down_allowed…` (:134) and `for k in
range(HALVINGS+1):` (:147) could not be the last frame of a
`ZeroDivisionError`; they are now the division lines :121 (the central delta
and gamma), :137 (`elif d:`, the backward difference) and :149 (the forward
theta). The observed raise set (5 locations, 122 raising rows) and
census_rows.json stayed identical (c-census runs f2704365 before and 351088c8
after).

Tests (vectors of the check `c-vectors`; REQUIRE-style, one test file per
header for the AST dump limit): `test_alo.c` (params and table `alo_lo`:
σ_lo(ALO) on the crr_lo grid, the validity edge, the switching T, d + h_r ==
0.0 with one double on each side, the 1e-4 floor at its exact T and the two
`read_back` raises; table `alo`: 626 engine rows with status, statistics and
value bits under the case, every planted site and forced defect, and the 7
rows of `cvectors.alo_zero_vol_rows` (σ′ = 1e-300 > 0 passes the pre check
and `close(σ′, 0.0)` holds, so the zero-volatility branch of
`put_with_edge_cases`, `src/pl_alo_edge.c`, is reachable from the engine's
input domain; ruling R-10b-E), and the 4 rows of `cvectors.alo_qd_natural_rows`
(the natural inner QD+ Brent error, see "Inner QD+ bracket error" below;
ruling R-10d); the caps;
the structural invariants of I4.4); `test_alo_equation.c` (tables
`alo_equation`, 87 rows, and `alo_segment`, 174 rows, with every
intermediate; at least one Auto tie row, abs_diff bits equal to 0.001, for
r_e > q_e and for r_e < q_e, and the generator raises when a sign has none
(ruling R-10c, T10B-TIE-GUARD-01); the Chebyshev nodes and the tables with
the row digests); `test_alo_greeks.c`
(table `alo_greeks`, 680 rows: status, band, flags, count, stencil forms and
halvings and values, also through `pl_price_and_greeks`; the rows of
`cvectors.alo_greek_point_rows` and `alo_greek_plant_rows` make one stencil
point fail after the row point passed: the pre check at a rho point, a
non-finite rho point value, a `read_back` raise in the segment test of a rho
point, the BlackCalculator F > 0 check at a rho point whose forward
underflows to 0.0 (ruling R-10c-2), and the planted fallback sites and caps
at an S point, ruling R-10c);
`test_evaluate_alo.c` (table `evaluate_alo`, 477 rows: `pl_evaluate` of
`alo` on the rows of part `evaluate` and the ALO rows, the IV-call fact, the
read-back raise before σ_lo, every run defect, and the 6 rows of
`cvectors.evaluate_alo_edge_rows` that reach `src/pl_alo_edge.c` through the
IV solve, T = 1e-60 and 1e-49 with r T and q T near 1e-16, ruling R-10c-2;
the 2 rows of `cvectors.evaluate_alo_qd_rows` that reach the inner QD+ bracket
error at the first IV Brent point, ruling R-10d).

Inner QD+ bracket error (ruling R-10d, T10C-QD-NATURAL-01): the natural
"root not bracketed" path of the inner QD+ Brent (`alo._qd_brent`,
alo.py:467; `src/pl_alo_qdplus.c:135`, `PL_ENGINE_QL_ERROR`, order 5) is
reachable from admitted inputs. Example: a call S = 1e8, K = 100 (the put
S′ = 100, K′ = 1e8 after the exchange), r′ = 0.04, q′ = 0.0399, σ′ = 1e-10.
The Halley steps do not converge at a node, and `brent` (solver.py:33-34)
finds f(xMin) and f(xMax) of one sign. `pl_evaluate` admits the row
(side, S, K, T = 1e-12, bid 99999900, ask 99999901, r = 4e10, q = 3.99e10):
the row checks need only finite S, K, T and quote with S, K, T, bid > 0 and
ask >= bid, and accept any finite r and q; σ_lo(ALO) = 1e-4 (FP_A,
d + h_r < 0) is below σ_hi; the first IV Brent point σ_lo maps to σ′ = 1e-10.
The row ends in MODEL_DOMAIN after 1 engine evaluation, flags 0, in C and in
Python. In the Python search (host, pure reference only; about 1,700 random
points and grids) every input with this error has S / K or K / S of at least
3e4 and σ′ of at most 2e-6. Not vectored: the `pl_alo_fail` call at line 125
(`PL_BRENT_DEFECT` or `PL_BRENT_DOMAIN` with the run still OK: a Python
ValueError in `brent`, but xMin < xMax and the guess clamps keep the guess
inside the bracket) and "maximum number of function evaluations" (Brent
status NOT_CONVERGED); no search input reached them.

Unvectored engine branches (ruling R-10d; none is excluded from coverage):

- `src/pl_alo_ts_ends.c:109`, the Boost end sanity check "increasing at the
  new end" (alo.py:290-297; ledger finding T10C-TS-END-01, OPEN). No input
  found; reachability is open. Search on the host pure Python reference:
  Task 10c, 50,244 random evaluations and a wide random search over extreme
  rates, S and σ, none raised it; with the check instrumented in a scratch
  copy, 25,317 evaluations reached the check 24,170 times, the highest
  |yp| / |ym| was 0.990 (left end) and 0.806 (right end), and two
  hill-climbs reached 0.9954, never above 1. Task 10d, script
  `ts_end_search.py` seed 11: 20,000 puts at T = 1 with r < q (near the
  integrand cancellation that the reviewer named), S / K in [0.1, 5], σ in
  [1e-3, 5], none raised it.
- `src/pl_alo_qdplus.c:125` and the NOT_CONVERGED case of line 135 (see
  "Inner QD+ bracket error").

Coverage counts and threads (ledger finding P2-COV-ATOMIC-01, OPEN, owner
framework): the coverage build has no `-fprofile-update=atomic`, and the
pooled batch tests run the engines on worker threads. Two runs of one tree
differ in 15 files on that path. A lost increment can hide a covered region
or show an uncovered branch as covered, so a per-branch claim in those files
is unconfirmed until the framework fix.

Mutants (Task 10b Step 6; each a scratch edit of the C source in the quiet
worktree, one Procedure P run, then reverted; never committed): every one of the
twelve is detected at the gcc-O0 `unit` gate. (1) `<` as `<=` in the `Auto`
test: undetected at first (no row had |r_e - q_e| == 0.001 exactly; the
read-back rates are quantized near 0.001), then detected by `test_alo_equation`
(`equation`) after `cvectors.alo_switch_tie_rows` found the ties (r1, q1) =
(0x3f4d9f4d37c12fa8, -9.6e-5) and the exchanged pair, each with one double on
each side. (2) FP-B always, (3) forward Legendre order, (6) four sweeps,
(7) the Halley stop with `eps`, (11) nodes with i·π/14: `test_alo` (`engine`,
`engine-value`), `test_alo_greeks`, `test_evaluate_alo` and the batch ALO tests.
(4) post-integral check removed with `fmax`, (5) inner-solver errors as run
defects, (8) the QD+ solver NaN check removed: `test_alo` (`engine`, the
planted and forced rows), `test_alo_greeks`, `test_evaluate_alo`. (9) theta
T + δ first, (10) rho always central, (12) no forward vega: `test_alo_greeks`
(`greeks`), `test_evaluate_alo`, the batch ALO tests (and `test_evaluate`
`greeks-direct` for 9).

## Probe result (Task 1)

Date: 2026-10-08. Method: the scratch file `src/pl_probe_forms.c` (module
`models`, removed after the probe) used the C `<math.h>` forms `isnan`,
`isfinite`, `isinf`, `signbit`, `INFINITY`, `NAN`, `HUGE_VAL` and `fabs`
through `./tools/safety project check --development`.

- Gate `ast` (configuration `ast-scan`, Clang AST): `FAIL`, rule
  `project-builtin` in `src/pl_probe_forms.c` only, names
  `__builtin_huge_val`, `__builtin_inff`, `__builtin_isfinite`,
  `__builtin_isinf_sign`, `__builtin_isnan`, `__builtin_nanf`,
  `__builtin_signbit`. `fabs` is not among the names: it is an ordinary libm
  call.
- The source-policy step of the `ast` gate reported none of these names in
  any configuration (GCC and Clang). It reported one other check,
  `build-macros`: the macro `FLT_EVAL_METHOD` in `tests/project/test_ieee.c`
  differs between the build configurations. The test now checks the same
  property at run time.
- No build gate failed because of a probe form: `format`, the GCC and Clang
  builds, `hardened`, `tidy`, `csa`, `gcc-analyzer`, the sanitizer builds,
  `unit`, `integration` and `coverage` passed before `ast`.

Chosen forms: bit access through `union { uint64_t u; double d; }`,
`pl_is_nan` as `x != x`, `pl_is_finite` as two comparisons with `DBL_MAX`,
`pl_inf` and `pl_nan` from their bit patterns, and `pl_fabs` through the bits.
No project code uses a `<math.h>` classification macro, `INFINITY`, `NAN` or
`HUGE_VAL`; `fabs` is allowed but unused.
