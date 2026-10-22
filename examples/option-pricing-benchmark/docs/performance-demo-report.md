# Performance demo report: option-chain-greeks

**Label: demo, not a decision run.** This run applies only the three rule policies of the framework (`owner`,
`demo-latency-2x` and `demo-cpu-40`). It does not apply the project rule `unit-200ms-and-20pct`, it uses the synthetic
large chain only (never the owner chain), and it gives no unit verdict. The owner decision runs (EX-24 and EX-25) come
later and apply the project rule.

Owner rules for this report:

- Every row is single-threaded: no pool variant, no thread variant and no concurrent client.
- The decision rule of the project applies to each route separately. C wins on a route only if Python adds at least
  200 ms per request AND C is consistently more than 20 % faster end to end on that route. Otherwise the answer is
  Python. This demo run does not apply that rule.
- QuantLib 1.43 is the correctness baseline.
- This report holds no market-rate diagnostics. The owner will supply dividend projections later.
- The report shows the measured numbers also where C is slower.

## Run identity

- Run ID: `337732f4ff06461ab936c8268445980f`. Status: VALID, 1,836 observations, 0 reasons.
- Plan: plan_id `820c901f4bea0f7221c1e4b1966fcbd6`, plan version v1-split, plan file `artifacts/bench/1b7fd3f866a346b683997e155865edb6/plan.json` (sha256 `424b7ee5b59355d87b719ddc287aa00fe671fff56961cdf1bc8522a3842a9683`).
- Plan estimate: 24,803.8 s (6.89 h). The decision cap is 28,800 s.
- Calibration: the smoke run `6b82b62c5e6c49548104b0123bb1ebf1` (the measured walls of each variant, selector and call class).
- Source identity: `54050c20c3ab`. Protocol sha256: `cac199578bc8`.
- Date: 2026-10-21. Start 2026-10-21T07:32:39Z (the run command), end 2026-10-21T14:19:36Z (run.json). Wall time: 6 h 46 min 57 s.
- Envelope: 4 CPUs, cpuset [0, 1, 2, 3], reduced false, multicore PASS.
- Dataset: synthetic large, 13,230 rows, seed 20261007; the one-contract units use the six panel rows of `synthetic:large#panel`.
- Native agreement: PASS (C = py-reference byte for byte before the timed trials).
- B17 matrix (`bench_phase3.matrix_complete`): no problem. All 21 cells of the case are observed. The cell `caller cold c-serial direct [inproc]` is not-applicable (the library load is the startup phase).
- compare.json sha256: `28ded84a8e0c3d219307069147862c92776c847e628e3c33e05be417348e8571`.

## Sessions: actual wall against the estimate

The actual wall is the `seconds` of the timing job of each session. The plan sizes each session from the measured walls of the calibration smoke.

| session | trials | estimate (s) | actual (s) | actual / estimate |
|---|---|---|---|---|
| baseline-s00 | 143 | 1,035.9 | 782.4 | 0.76 |
| full-dataset-s01 | 117 | 1,530.6 | 1,213.7 | 0.79 |
| language-only-s02 | 39 | 418.1 | 1,398.3 | 3.34 |
| crossover-tiny-s03 | 56 | 112.2 | 45.1 | 0.40 |
| crossover-small-s04 | 56 | 210.9 | 146.6 | 0.69 |
| unit-bsm-full-s05 | 117 | 346.4 | 149.7 | 0.43 |
| unit-bjs-full-s06 | 117 | 475.4 | 180.3 | 0.38 |
| unit-crr-full-s07 | 117 | 1,208.1 | 977.2 | 0.81 |
| unit-baw-full-s08 | 117 | 1,699.8 | 1,476.8 | 0.87 |
| unit-alo-full-s09 | 90 | 10,631.2 | 6,764.6 | 0.64 |
| unit-alo-full-s10 | 36 | 4,252.5 | 2,719.4 | 0.64 |
| unit-bsm-one-s11 | 143 | 325.9 | 74.7 | 0.23 |
| unit-bjs-one-s12 | 143 | 328.2 | 80.4 | 0.24 |
| unit-crr-one-s13 | 143 | 332.6 | 87.8 | 0.26 |
| unit-baw-one-s14 | 143 | 326.7 | 80.9 | 0.25 |
| unit-alo-one-s15 | 143 | 903.3 | 661.5 | 0.73 |
| all timing sessions | 1,720 | 24,137.7 | 16,839.5 | 0.70 |

Other jobs of the run: before-run checks 10 job(s), 916.5 s; capacity 1 job(s), 49.2 s; memory trials 35 job(s), 1,579.5 s; reference 1 job(s), 4,303.3 s.

Only one session ran longer than its estimate: `language-only-s02`. Its rows are kernel rows. The planner keeps the family rate for kernel trials, because the measured walls cover caller-scope rows only. Every other session ran shorter than its estimate, because a multi-row wall measured on the small tier is an upper bound of the cost per record of a larger call.

## Decision outcome (demo, not a decision run)

| policy | rule outcome | adoption outcome | reason |
|---|---|---|---|
| owner | INCONCLUSIVE | INCONCLUSIVE - Python retained pending evidence | policy objective missing: the owner template is not filled |
| demo-latency-2x | INCONCLUSIVE | INCONCLUSIVE - Python retained pending evidence | required evidence missing: c-serial xdirect [inproc]: inproc cold: not-applicable (library load is the startup phase) |
| demo-cpu-40 | INCONCLUSIVE | INCONCLUSIVE - Python retained pending evidence | required evidence missing: c-serial xdirect [inproc]: inproc cold: not-applicable (library load is the startup phase) |

From decision.md (the same lines in the three policy records):

- best python: py-optimized xdirect @unit-bsm-full/warm: median 5947 ns/unit; no baseline row for an interval
- best c: c-serial xdirect [inproc] @unit-bsm-full/warm: median 3915 ns/unit; no baseline row for an interval (route label: in-process shared library: native code shares the interpreter address space; a C defect can corrupt the interpreter (fast route, least safe))
- cpu tradeoff: C/Python CPU ratio 0.658 [0.655, 0.667]

History: the framework rule defect behind the reason "required evidence missing: c-serial xdirect [inproc]" (a not-applicable cell counted as missing evidence) is fixed in the framework (FW-DECIDE-NAMODE-01). A new `bench decide` of this run under the fixed framework was refused with the reason code `reused-source-report` (the run belongs to another source identity), so the table above stays the first derivation, made at 1d0ae25 (source identity 54050c20c3ab0fee64010fcb55da17b43d8190fe27c5b66c468713eb1ca1239d, the source of the run; framework a498749). It is not a result of the fixed rule. The row EX20-DECIDE-INPROC-NA-01 stays OPEN.

All three policies give INCONCLUSIVE, so Python is retained. The `owner` policy has no objective (its template is not filled). The two demonstration policies require a row for every planned cell, and they count the not-applicable cell `c-serial` inproc cold as missing evidence. These are the actual outcomes of the framework rules; no measurement is repeated to change them.

## Rows of every point

Values from compare.json. Per-unit values divide by the completed work units of the eligible non-warmup trials. The ratios are 95 % paired-block intervals (10,000 resamples, seed 20261007). The routes of the C rows:

- route inproc: in-process shared library: native code shares the interpreter address space; a C defect can corrupt the interpreter (fast route, least safe) (compare rows: 12)
- route shm: separate process; shared memfd regions, bounded and validated control frames, copy-in snapshot (compare rows: 24)
- route stdio: separate process; copied, bounded, validated frames over pipes (safest) (compare rows: 28)

| point | variant | route | scope | mode | size | units | reps | wall ns/unit (median) | CPU ns/unit (median) | vs py-reference [95 %] | vs best Python [95 %] | correctness | evidence |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline | c-serial | shm | caller | cold | medium | 12,288 | 12 | 3.685e+05 | 3.691e+05 | FASTER 0.0153 [0.0152, 0.0154] | INCONCLUSIVE 0.945 [0.936, 0.956] | 12/12 eligible | decision |
| baseline | c-serial | stdio | caller | cold | medium | 12,288 | 12 | 3.683e+05 | 3.691e+05 | FASTER 0.0153 [0.0152, 0.0153] | INCONCLUSIVE 0.944 [0.938, 0.954] | 12/12 eligible | decision |
| baseline | py-library | none | caller | cold | medium | 12,288 | 12 | 2.081e+06 | 2.08e+06 | FASTER 0.0863 [0.0854, 0.0869] | n/a | 12/12 eligible | decision |
| baseline | py-optimized | none | caller | cold | medium | 12,288 | 12 | 3.901e+05 | 3.896e+05 | FASTER 0.0162 [0.0161, 0.0163] | n/a | 12/12 eligible | decision |
| baseline | py-reference | none | caller | cold | medium | 12,288 | 12 | 2.41e+07 | 2.41e+07 | n/a | n/a | 12/12 eligible | decision |
| baseline | c-serial | inproc | caller | warm | medium | 12,288 | 12 | 3.044e+05 | 3.04e+05 | FASTER 0.0127 [0.0126, 0.0127] | FASTER 0.782 [0.777, 0.787] | 12/12 eligible | decision |
| baseline | c-serial | shm | caller | warm | medium | 12,288 | 12 | 3.657e+05 | 3.655e+05 | FASTER 0.0152 [0.0151, 0.0153] | FASTER 0.939 [0.931, 0.945] | 12/12 eligible | decision |
| baseline | c-serial | stdio | caller | warm | medium | 12,288 | 12 | 3.658e+05 | 3.656e+05 | FASTER 0.0152 [0.0152, 0.0152] | FASTER 0.94 [0.932, 0.944] | 12/12 eligible | decision |
| baseline | py-library | none | caller | warm | medium | 12,288 | 12 | 2.082e+06 | 2.081e+06 | FASTER 0.0865 [0.0859, 0.0872] | n/a | 12/12 eligible | decision |
| baseline | py-optimized | none | caller | warm | medium | 12,288 | 12 | 3.893e+05 | 3.89e+05 | FASTER 0.0162 [0.0161, 0.0163] | n/a | 12/12 eligible | decision |
| baseline | py-reference | none | caller | warm | medium | 12,288 | 12 | 2.406e+07 | 2.405e+07 | n/a | n/a | 12/12 eligible | decision |
| crossover-small | c-serial | stdio | caller | cold | small | 1,536 | 6 | 3.833e+05 | 3.863e+05 | FASTER 0.0158 [0.0158, 0.0163] | FASTER 0.515 [0.511, 0.527] | 6/6 eligible | decision |
| crossover-small | py-library | none | caller | cold | small | 1,536 | 6 | 2.079e+06 | 2.078e+06 | FASTER 0.0859 [0.0855, 0.0863] | n/a | 6/6 eligible | decision |
| crossover-small | py-optimized | none | caller | cold | small | 1,536 | 6 | 7.449e+05 | 7.442e+05 | FASTER 0.0308 [0.0305, 0.0309] | n/a | 6/6 eligible | decision |
| crossover-small | py-reference | none | caller | cold | small | 1,536 | 6 | 2.422e+07 | 2.421e+07 | n/a | n/a | 6/6 eligible | decision |
| crossover-small | c-serial | stdio | caller | warm | small | 1,536 | 6 | 3.741e+05 | 3.734e+05 | FASTER 0.0148 [0.0147, 0.0149] | FASTER 0.504 [0.496, 0.509] | 6/6 eligible | decision |
| crossover-small | py-library | none | caller | warm | small | 1,536 | 6 | 2.102e+06 | 2.1e+06 | FASTER 0.0833 [0.0822, 0.0842] | n/a | 6/6 eligible | decision |
| crossover-small | py-optimized | none | caller | warm | small | 1,536 | 6 | 7.428e+05 | 7.425e+05 | FASTER 0.0294 [0.0292, 0.0297] | n/a | 6/6 eligible | decision |
| crossover-small | py-reference | none | caller | warm | small | 1,536 | 6 | 2.522e+07 | 2.522e+07 | n/a | n/a | 6/6 eligible | decision |
| crossover-tiny | c-serial | stdio | caller | cold | tiny | 6 | 6 | 2.631e+06 | 3.093e+06 | FASTER 0.729 [0.689, 0.79] | SLOWER 1.87 [1.74, 2.01] | 6/6 eligible | decision |
| crossover-tiny | py-library | none | caller | cold | tiny | 6 | 6 | 1.405e+06 | 1.394e+06 | FASTER 0.389 [0.355, 0.448] | n/a | 6/6 eligible | decision |
| crossover-tiny | py-optimized | none | caller | cold | tiny | 6 | 6 | 6.373e+06 | 6.346e+06 | SLOWER 1.76 [1.7, 1.78] | n/a | 6/6 eligible | decision |
| crossover-tiny | py-reference | none | caller | cold | tiny | 6 | 6 | 3.611e+06 | 3.591e+06 | n/a | n/a | 6/6 eligible | decision |
| crossover-tiny | c-serial | stdio | caller | warm | tiny | 6 | 6 | 9.598e+05 | 9.39e+05 | FASTER 0.261 [0.255, 0.287] | FASTER 0.77 [0.755, 0.815] | 6/6 eligible | decision |
| crossover-tiny | py-library | none | caller | warm | tiny | 6 | 6 | 1.247e+06 | 1.222e+06 | FASTER 0.339 [0.334, 0.352] | n/a | 6/6 eligible | decision |
| crossover-tiny | py-optimized | none | caller | warm | tiny | 6 | 6 | 6.372e+06 | 6.365e+06 | SLOWER 1.73 [1.6, 1.74] | n/a | 6/6 eligible | decision |
| crossover-tiny | py-reference | none | caller | warm | tiny | 6 | 6 | 3.681e+06 | 3.662e+06 | n/a | n/a | 6/6 eligible | decision |
| full-dataset | c-serial | shm | caller | cold | large | 158,760 | 12 | 3.692e+05 | 3.692e+05 | n/a | SLOWER 1.33 [1.31, 1.34] | 12/12 eligible | decision |
| full-dataset | c-serial | stdio | caller | cold | large | 158,760 | 12 | 3.7e+05 | 3.699e+05 | n/a | SLOWER 1.33 [1.31, 1.34] | 12/12 eligible | decision |
| full-dataset | py-library | none | caller | cold | large | 158,760 | 12 | 2.068e+06 | 2.068e+06 | n/a | n/a | 12/12 eligible | decision |
| full-dataset | py-optimized | none | caller | cold | large | 158,760 | 12 | 2.782e+05 | 2.781e+05 | n/a | n/a | 12/12 eligible | decision |
| full-dataset | c-serial | inproc | caller | warm | large | 158,760 | 12 | 3.064e+05 | 3.063e+05 | n/a | SLOWER 1.11 [1.1, 1.12] | 12/12 eligible | decision |
| full-dataset | c-serial | shm | caller | warm | large | 158,760 | 12 | 3.689e+05 | 3.688e+05 | n/a | SLOWER 1.34 [1.32, 1.34] | 12/12 eligible | decision |
| full-dataset | c-serial | stdio | caller | warm | large | 158,760 | 12 | 3.697e+05 | 3.696e+05 | n/a | SLOWER 1.34 [1.33, 1.35] | 12/12 eligible | decision |
| full-dataset | py-library | none | caller | warm | large | 158,760 | 12 | 2.075e+06 | 2.074e+06 | n/a | n/a | 12/12 eligible | decision |
| full-dataset | py-optimized | none | caller | warm | large | 158,760 | 12 | 2.76e+05 | 2.759e+05 | n/a | n/a | 12/12 eligible | decision |
| language-only | c-serial | none | kernel | direct | medium | 12,288 | 12 | 3.023e+05 | 3.021e+05 | FASTER 0.0125 [0.0125, 0.0126] | FASTER 0.773 [0.761, 0.78] | 12/12 eligible | decision |
| language-only | py-optimized | none | kernel | direct | medium | 36,864 | 12 | 3.913e+05 | 3.91e+05 | FASTER 0.0162 [0.0161, 0.0164] | n/a | 12/12 eligible | decision |
| language-only | py-reference | none | kernel | direct | medium | 36,864 | 12 | 2.414e+07 | 2.413e+07 | n/a | n/a | 12/12 eligible | decision |
| unit-alo-full | c-serial | shm | caller | cold | large | 158,760 | 12 | 5.228e+06 | 5.226e+06 | n/a | EQUAL 1.03 [1.03, 1.03] | 12/12 eligible | decision |
| unit-alo-full | c-serial | stdio | caller | cold | large | 158,760 | 12 | 5.229e+06 | 5.228e+06 | n/a | EQUAL 1.03 [1.03, 1.03] | 12/12 eligible | decision |
| unit-alo-full | py-library | none | caller | cold | large | 158,760 | 12 | 5.091e+06 | 5.09e+06 | n/a | n/a | 12/12 eligible | decision |
| unit-alo-full | py-optimized | none | caller | cold | large | 158,760 | 12 | 7.092e+06 | 7.088e+06 | n/a | n/a | 12/12 eligible | decision |
| unit-alo-full | c-serial | inproc | caller | warm | large | 158,760 | 12 | 5.24e+06 | 5.24e+06 | n/a | EQUAL 1.03 [1.03, 1.03] | 12/12 eligible | decision |
| unit-alo-full | c-serial | shm | caller | warm | large | 158,760 | 12 | 5.224e+06 | 5.223e+06 | n/a | EQUAL 1.03 [1.02, 1.03] | 12/12 eligible | decision |
| unit-alo-full | c-serial | stdio | caller | warm | large | 158,760 | 12 | 5.23e+06 | 5.228e+06 | n/a | EQUAL 1.03 [1.03, 1.03] | 12/12 eligible | decision |
| unit-alo-full | py-library | none | caller | warm | large | 158,760 | 12 | 5.085e+06 | 5.084e+06 | n/a | n/a | 12/12 eligible | decision |
| unit-alo-full | py-optimized | none | caller | warm | large | 158,760 | 12 | 7.119e+06 | 7.115e+06 | n/a | n/a | 12/12 eligible | decision |
| unit-alo-one | c-serial | shm | caller | cold | tiny | 72 | 12 | 9.251e+06 | 9.021e+06 | FASTER 0.0289 [0.0282, 0.0293] | SLOWER 1.59 [1.55, 1.61] | 12/12 eligible | decision |
| unit-alo-one | c-serial | stdio | caller | cold | tiny | 72 | 12 | 9.102e+06 | 8.897e+06 | FASTER 0.0285 [0.0281, 0.0288] | SLOWER 1.56 [1.53, 1.58] | 12/12 eligible | decision |
| unit-alo-one | py-library | none | caller | cold | tiny | 72 | 12 | 5.83e+06 | 5.822e+06 | FASTER 0.0182 [0.018, 0.0186] | n/a | 12/12 eligible | decision |
| unit-alo-one | py-optimized | none | caller | cold | tiny | 72 | 12 | 9.374e+08 | 9.371e+08 | SLOWER 2.93 [2.91, 2.94] | n/a | 12/12 eligible | decision |
| unit-alo-one | py-reference | none | caller | cold | tiny | 72 | 12 | 3.196e+08 | 3.195e+08 | n/a | n/a | 12/12 eligible | decision |
| unit-alo-one | c-serial | inproc | caller | warm | tiny | 936 | 12 | 5.785e+06 | 5.78e+06 | FASTER 0.0182 [0.0182, 0.0183] | EQUAL 1.03 [1.03, 1.04] | 12/12 eligible | decision |
| unit-alo-one | c-serial | shm | caller | warm | tiny | 936 | 12 | 5.939e+06 | 5.924e+06 | FASTER 0.0187 [0.0185, 0.0188] | INCONCLUSIVE 1.06 [1.05, 1.06] | 12/12 eligible | decision |
| unit-alo-one | c-serial | stdio | caller | warm | tiny | 936 | 12 | 5.926e+06 | 5.913e+06 | FASTER 0.0187 [0.0186, 0.0187] | INCONCLUSIVE 1.06 [1.05, 1.06] | 12/12 eligible | decision |
| unit-alo-one | py-library | none | caller | warm | tiny | 1,080 | 12 | 5.61e+06 | 5.608e+06 | FASTER 0.0177 [0.0176, 0.0177] | n/a | 12/12 eligible | decision |
| unit-alo-one | py-optimized | none | caller | warm | tiny | 360 | 12 | 9.371e+08 | 9.368e+08 | SLOWER 2.95 [2.94, 2.96] | n/a | 12/12 eligible | decision |
| unit-alo-one | py-reference | none | caller | warm | tiny | 360 | 12 | 3.174e+08 | 3.173e+08 | n/a | n/a | 12/12 eligible | decision |
| unit-baw-full | c-serial | shm | caller | cold | large | 158,760 | 12 | 4.652e+04 | 4.657e+04 | n/a | FASTER 0.0244 [0.0243, 0.0246] | 12/12 eligible | decision |
| unit-baw-full | c-serial | stdio | caller | cold | large | 158,760 | 12 | 4.685e+04 | 4.688e+04 | n/a | FASTER 0.0246 [0.0245, 0.0247] | 12/12 eligible | decision |
| unit-baw-full | py-library | none | caller | cold | large | 158,760 | 12 | 1.904e+06 | 1.903e+06 | n/a | n/a | 12/12 eligible | decision |
| unit-baw-full | py-optimized | none | caller | cold | large | 158,760 | 12 | 2.092e+06 | 2.092e+06 | n/a | n/a | 12/12 eligible | decision |
| unit-baw-full | c-serial | inproc | caller | warm | large | 158,760 | 12 | 4.579e+04 | 4.577e+04 | n/a | FASTER 0.0241 [0.024, 0.0242] | 12/12 eligible | decision |
| unit-baw-full | c-serial | shm | caller | warm | large | 158,760 | 12 | 4.622e+04 | 4.618e+04 | n/a | FASTER 0.0243 [0.0242, 0.0245] | 12/12 eligible | decision |
| unit-baw-full | c-serial | stdio | caller | warm | large | 158,760 | 12 | 4.661e+04 | 4.661e+04 | n/a | FASTER 0.0245 [0.0245, 0.0247] | 12/12 eligible | decision |
| unit-baw-full | py-library | none | caller | warm | large | 158,760 | 12 | 1.9e+06 | 1.899e+06 | n/a | n/a | 12/12 eligible | decision |
| unit-baw-full | py-optimized | none | caller | warm | large | 158,760 | 12 | 2.088e+06 | 2.087e+06 | n/a | n/a | 12/12 eligible | decision |
| unit-baw-one | c-serial | shm | caller | cold | tiny | 72 | 12 | 3.755e+06 | 3.524e+06 | SLOWER 1.39 [1.33, 1.43] | SLOWER 1.73 [1.65, 1.78] | 12/12 eligible | decision |
| unit-baw-one | c-serial | stdio | caller | cold | tiny | 72 | 12 | 3.395e+06 | 3.144e+06 | SLOWER 1.26 [1.24, 1.31] | SLOWER 1.56 [1.53, 1.63] | 12/12 eligible | decision |
| unit-baw-one | py-library | none | caller | cold | tiny | 72 | 12 | 2.171e+06 | 2.166e+06 | FASTER 0.804 [0.797, 0.815] | n/a | 12/12 eligible | decision |
| unit-baw-one | py-optimized | none | caller | cold | tiny | 72 | 12 | 1.049e+07 | 1.046e+07 | SLOWER 3.88 [3.85, 3.92] | n/a | 12/12 eligible | decision |
| unit-baw-one | py-reference | none | caller | cold | tiny | 72 | 12 | 2.7e+06 | 2.682e+06 | n/a | n/a | 12/12 eligible | decision |
| unit-baw-one | c-serial | inproc | caller | warm | tiny | 13,032 | 12 | 2.713e+05 | 2.711e+05 | FASTER 0.107 [0.107, 0.108] | FASTER 0.141 [0.141, 0.142] | 12/12 eligible | decision |
| unit-baw-one | c-serial | shm | caller | warm | tiny | 13,032 | 12 | 3.563e+05 | 3.487e+05 | FASTER 0.141 [0.137, 0.143] | FASTER 0.186 [0.181, 0.187] | 12/12 eligible | decision |
| unit-baw-one | c-serial | stdio | caller | warm | tiny | 13,032 | 12 | 3.485e+05 | 3.408e+05 | FASTER 0.138 [0.136, 0.14] | FASTER 0.181 [0.179, 0.184] | 12/12 eligible | decision |
| unit-baw-one | py-library | none | caller | warm | tiny | 2,952 | 12 | 1.92e+06 | 1.919e+06 | FASTER 0.76 [0.758, 0.764] | n/a | 12/12 eligible | decision |
| unit-baw-one | py-optimized | none | caller | warm | tiny | 576 | 12 | 1.011e+07 | 1.01e+07 | SLOWER 4 [3.98, 4.02] | n/a | 12/12 eligible | decision |
| unit-baw-one | py-reference | none | caller | warm | tiny | 2,304 | 12 | 2.527e+06 | 2.524e+06 | n/a | n/a | 12/12 eligible | decision |
| unit-bjs-full | c-serial | shm | caller | cold | large | 158,760 | 12 | 1.689e+04 | 1.696e+04 | n/a | FASTER 0.574 [0.567, 0.579] | 12/12 eligible | decision |
| unit-bjs-full | c-serial | stdio | caller | cold | large | 158,760 | 12 | 1.695e+04 | 1.703e+04 | n/a | FASTER 0.576 [0.567, 0.581] | 12/12 eligible | decision |
| unit-bjs-full | py-library | none | caller | cold | large | 158,760 | 12 | 2.674e+05 | 2.673e+05 | n/a | n/a | 12/12 eligible | decision |
| unit-bjs-full | py-optimized | none | caller | cold | large | 158,760 | 12 | 2.941e+04 | 2.939e+04 | n/a | n/a | 12/12 eligible | decision |
| unit-bjs-full | c-serial | inproc | caller | warm | large | 158,760 | 12 | 1.621e+04 | 1.62e+04 | n/a | FASTER 0.552 [0.547, 0.555] | 12/12 eligible | decision |
| unit-bjs-full | c-serial | shm | caller | warm | large | 158,760 | 12 | 1.649e+04 | 1.649e+04 | n/a | FASTER 0.562 [0.557, 0.564] | 12/12 eligible | decision |
| unit-bjs-full | c-serial | stdio | caller | warm | large | 158,760 | 12 | 1.669e+04 | 1.674e+04 | n/a | FASTER 0.568 [0.563, 0.573] | 12/12 eligible | decision |
| unit-bjs-full | py-library | none | caller | warm | large | 158,760 | 12 | 2.645e+05 | 2.644e+05 | n/a | n/a | 12/12 eligible | decision |
| unit-bjs-full | py-optimized | none | caller | warm | large | 158,760 | 12 | 2.936e+04 | 2.933e+04 | n/a | n/a | 12/12 eligible | decision |
| unit-bjs-one | c-serial | shm | caller | cold | tiny | 72 | 12 | 3.77e+06 | 3.624e+06 | SLOWER 3.55 [3.34, 3.71] | SLOWER 6.05 [5.61, 6.39] | 12/12 eligible | decision |
| unit-bjs-one | c-serial | stdio | caller | cold | tiny | 72 | 12 | 3.618e+06 | 3.398e+06 | SLOWER 3.41 [3.24, 3.51] | SLOWER 5.81 [5.38, 6] | 12/12 eligible | decision |
| unit-bjs-one | py-library | none | caller | cold | tiny | 72 | 12 | 6.227e+05 | 6.147e+05 | FASTER 0.587 [0.563, 0.616] | n/a | 12/12 eligible | decision |
| unit-bjs-one | py-optimized | none | caller | cold | tiny | 72 | 12 | 2.03e+07 | 2.03e+07 | SLOWER 19.1 [18.7, 19.5] | n/a | 12/12 eligible | decision |
| unit-bjs-one | py-reference | none | caller | cold | tiny | 72 | 12 | 1.061e+06 | 1.05e+06 | n/a | n/a | 12/12 eligible | decision |
| unit-bjs-one | c-serial | inproc | caller | warm | tiny | 13,320 | 12 | 2.476e+05 | 2.474e+05 | FASTER 0.29 [0.287, 0.296] | FASTER 0.628 [0.618, 0.643] | 12/12 eligible | decision |
| unit-bjs-one | c-serial | shm | caller | warm | tiny | 13,320 | 12 | 3.363e+05 | 3.275e+05 | FASTER 0.394 [0.387, 0.398] | FASTER 0.852 [0.836, 0.862] | 12/12 eligible | decision |
| unit-bjs-one | c-serial | stdio | caller | warm | tiny | 13,320 | 12 | 3.286e+05 | 3.212e+05 | FASTER 0.385 [0.377, 0.393] | FASTER 0.833 [0.816, 0.851] | 12/12 eligible | decision |
| unit-bjs-one | py-library | none | caller | warm | tiny | 10,872 | 12 | 3.946e+05 | 3.934e+05 | FASTER 0.462 [0.459, 0.467] | n/a | 12/12 eligible | decision |
| unit-bjs-one | py-optimized | none | caller | warm | tiny | 360 | 12 | 1.996e+07 | 1.995e+07 | SLOWER 23.4 [23.2, 23.5] | n/a | 12/12 eligible | decision |
| unit-bjs-one | py-reference | none | caller | warm | tiny | 6,048 | 12 | 8.543e+05 | 8.536e+05 | n/a | n/a | 12/12 eligible | decision |
| unit-bsm-full | c-serial | shm | caller | cold | large | 158,760 | 12 | 4658 | 4719 | n/a | FASTER 0.781 [0.761, 0.799] | 12/12 eligible | decision |
| unit-bsm-full | c-serial | stdio | caller | cold | large | 158,760 | 12 | 4649 | 4675 | n/a | FASTER 0.779 [0.766, 0.788] | 12/12 eligible | decision |
| unit-bsm-full | py-library | none | caller | cold | large | 158,760 | 12 | 2.286e+05 | 2.285e+05 | n/a | n/a | 12/12 eligible | decision |
| unit-bsm-full | py-optimized | none | caller | cold | large | 158,760 | 12 | 5964 | 5957 | n/a | n/a | 12/12 eligible | decision |
| unit-bsm-full | c-serial | inproc | caller | warm | large | 158,760 | 12 | 3915 | 3910 | n/a | FASTER 0.658 [0.655, 0.667] | 12/12 eligible | decision |
| unit-bsm-full | c-serial | shm | caller | warm | large | 158,760 | 12 | 4247 | 4238 | n/a | FASTER 0.714 [0.706, 0.727] | 12/12 eligible | decision |
| unit-bsm-full | c-serial | stdio | caller | warm | large | 158,760 | 12 | 4393 | 4379 | n/a | FASTER 0.739 [0.73, 0.747] | 12/12 eligible | decision |
| unit-bsm-full | py-library | none | caller | warm | large | 158,760 | 12 | 2.318e+05 | 2.317e+05 | n/a | n/a | 12/12 eligible | decision |
| unit-bsm-full | py-optimized | none | caller | warm | large | 158,760 | 12 | 5947 | 5944 | n/a | n/a | 12/12 eligible | decision |
| unit-bsm-one | c-serial | shm | caller | cold | tiny | 72 | 12 | 3.474e+06 | 3.196e+06 | SLOWER 9.45 [8.96, 9.78] | SLOWER 9.45 [8.96, 9.78] | 12/12 eligible | decision |
| unit-bsm-one | c-serial | stdio | caller | cold | tiny | 72 | 12 | 3.382e+06 | 3.112e+06 | SLOWER 9.2 [8.81, 9.65] | SLOWER 9.2 [8.81, 9.65] | 12/12 eligible | decision |
| unit-bsm-one | py-library | none | caller | cold | tiny | 72 | 12 | 5.674e+05 | 5.568e+05 | SLOWER 1.54 [1.43, 1.64] | n/a | 12/12 eligible | decision |
| unit-bsm-one | py-optimized | none | caller | cold | tiny | 72 | 12 | 4.426e+06 | 4.416e+06 | SLOWER 12 [11.4, 12.5] | n/a | 12/12 eligible | decision |
| unit-bsm-one | py-reference | none | caller | cold | tiny | 72 | 12 | 3.675e+05 | 3.628e+05 | n/a | n/a | 12/12 eligible | decision |
| unit-bsm-one | c-serial | inproc | caller | warm | tiny | 13,464 | 12 | 2.321e+05 | 2.318e+05 | SLOWER 1.19 [1.18, 1.21] | SLOWER 1.19 [1.18, 1.21] | 12/12 eligible | decision |
| unit-bsm-one | c-serial | shm | caller | warm | tiny | 13,464 | 12 | 3.124e+05 | 3.058e+05 | SLOWER 1.61 [1.58, 1.63] | SLOWER 1.61 [1.58, 1.63] | 12/12 eligible | decision |
| unit-bsm-one | c-serial | stdio | caller | warm | tiny | 13,464 | 12 | 3.037e+05 | 2.979e+05 | SLOWER 1.56 [1.54, 1.61] | SLOWER 1.56 [1.54, 1.61] | 12/12 eligible | decision |
| unit-bsm-one | py-library | none | caller | warm | tiny | 12,600 | 12 | 3.301e+05 | 3.298e+05 | SLOWER 1.7 [1.69, 1.71] | n/a | 12/12 eligible | decision |
| unit-bsm-one | py-optimized | none | caller | warm | tiny | 1,440 | 12 | 4.139e+06 | 4.135e+06 | SLOWER 21.3 [21.2, 21.4] | n/a | 12/12 eligible | decision |
| unit-bsm-one | py-reference | none | caller | warm | tiny | 17,856 | 12 | 1.944e+05 | 1.942e+05 | n/a | n/a | 12/12 eligible | decision |
| unit-crr-full | c-serial | shm | caller | cold | large | 158,760 | 12 | 3.505e+05 | 3.505e+05 | n/a | SLOWER 1.43 [1.43, 1.44] | 12/12 eligible | decision |
| unit-crr-full | c-serial | stdio | caller | cold | large | 158,760 | 12 | 3.514e+05 | 3.513e+05 | n/a | SLOWER 1.44 [1.43, 1.44] | 12/12 eligible | decision |
| unit-crr-full | py-library | none | caller | cold | large | 158,760 | 12 | 1.566e+06 | 1.565e+06 | n/a | n/a | 12/12 eligible | decision |
| unit-crr-full | py-optimized | none | caller | cold | large | 158,760 | 12 | 2.445e+05 | 2.444e+05 | n/a | n/a | 12/12 eligible | decision |
| unit-crr-full | c-serial | inproc | caller | warm | large | 158,760 | 12 | 2.884e+05 | 2.883e+05 | n/a | SLOWER 1.18 [1.17, 1.19] | 12/12 eligible | decision |
| unit-crr-full | c-serial | shm | caller | warm | large | 158,760 | 12 | 3.501e+05 | 3.5e+05 | n/a | SLOWER 1.43 [1.43, 1.44] | 12/12 eligible | decision |
| unit-crr-full | c-serial | stdio | caller | warm | large | 158,760 | 12 | 3.502e+05 | 3.501e+05 | n/a | SLOWER 1.43 [1.42, 1.44] | 12/12 eligible | decision |
| unit-crr-full | py-library | none | caller | warm | large | 158,760 | 12 | 1.565e+06 | 1.564e+06 | n/a | n/a | 12/12 eligible | decision |
| unit-crr-full | py-optimized | none | caller | warm | large | 158,760 | 12 | 2.444e+05 | 2.443e+05 | n/a | n/a | 12/12 eligible | decision |
| unit-crr-one | c-serial | shm | caller | cold | tiny | 72 | 12 | 3.946e+06 | 3.725e+06 | FASTER 0.155 [0.151, 0.16] | SLOWER 1.89 [1.83, 1.96] | 12/12 eligible | decision |
| unit-crr-one | c-serial | stdio | caller | cold | tiny | 72 | 12 | 3.753e+06 | 3.474e+06 | FASTER 0.147 [0.145, 0.151] | SLOWER 1.8 [1.78, 1.83] | 12/12 eligible | decision |
| unit-crr-one | py-library | none | caller | cold | tiny | 72 | 12 | 2.082e+06 | 2.07e+06 | FASTER 0.0817 [0.0809, 0.0829] | n/a | 12/12 eligible | decision |
| unit-crr-one | py-optimized | none | caller | cold | tiny | 72 | 12 | 1.708e+07 | 1.706e+07 | FASTER 0.67 [0.666, 0.675] | n/a | 12/12 eligible | decision |
| unit-crr-one | py-reference | none | caller | cold | tiny | 72 | 12 | 2.549e+07 | 2.546e+07 | n/a | n/a | 12/12 eligible | decision |
| unit-crr-one | c-serial | inproc | caller | warm | tiny | 6,912 | 12 | 5.374e+05 | 5.37e+05 | FASTER 0.0211 [0.021, 0.0212] | FASTER 0.293 [0.291, 0.295] | 12/12 eligible | decision |
| unit-crr-one | c-serial | shm | caller | warm | tiny | 6,912 | 12 | 6.862e+05 | 6.801e+05 | FASTER 0.0269 [0.0268, 0.0272] | FASTER 0.374 [0.372, 0.378] | 12/12 eligible | decision |
| unit-crr-one | c-serial | stdio | caller | warm | tiny | 6,912 | 12 | 6.816e+05 | 6.739e+05 | FASTER 0.0268 [0.0267, 0.0269] | FASTER 0.372 [0.369, 0.374] | 12/12 eligible | decision |
| unit-crr-one | py-library | none | caller | warm | tiny | 3,096 | 12 | 1.833e+06 | 1.832e+06 | FASTER 0.0719 [0.0717, 0.0726] | n/a | 12/12 eligible | decision |
| unit-crr-one | py-optimized | none | caller | warm | tiny | 360 | 12 | 1.73e+07 | 1.729e+07 | FASTER 0.679 [0.678, 0.682] | n/a | 12/12 eligible | decision |
| unit-crr-one | py-reference | none | caller | warm | tiny | 360 | 12 | 2.548e+07 | 2.546e+07 | n/a | n/a | 12/12 eligible | decision |

`py-library` is the C++ QuantLib library through SWIG; its rows include the cost of the per-evaluation Python callback.

## Memory

Independent memory trials: 35, all eligible (5 per variant and route on the medium tier, and 1 on the large tier for every row except py-reference, which has no large row). Values from compare.json: the median group peak of the cgroup and the median ready state, in bytes, over the trials of the variant and route.

| variant | route | group peak bytes (median) | trials | ready state bytes (median) |
|---|---|---|---|---|
| c-serial | inproc | 60,155,904 | 6 | 53,919,744 |
| c-serial | shm | 62,320,640 | 6 | 54,290,432 |
| c-serial | stdio | 62,005,248 | 6 | 54,206,464 |
| py-library | none | 139,837,440 | 6 | 53,260,288 |
| py-optimized | none | 77,750,272 | 6 | 53,483,520 |
| py-reference | none | 59,609,088 | 5 | 53,334,016 |

## Capacity (exploratory; capacity rows never decide)

- serial-workers, 1 client, variant py-optimized, route none: 3 trials (0 ineligible), throughput median 929.5 units/s, CPU median 1.076e+06 ns/unit (not reconciled (B15)), latency p50 196,444,505 ns from 24 samples; p90 and p99: n/a (too few samples (24 < 100); too few samples (24 < 1000)).

Read the capacity numbers with these facts:

- The configuration is `serial-workers` with the Python variant `py-optimized` and one client, so no two capacity requests run at the same time (owner rule: single thread only).
- The lab has no C capacity number. The framework capacity job starts its child process without the native environment, so a `c-serial` capacity call cannot find the restored `pl-worker` (open ledger row EX20-CAPACITY-CNATIVE-01).
- The capacity loop calls `adapter.validate` inside the measured loop. `validate` builds the canonical form of every eligible result (T22-A03), so each capacity latency includes that Python serialization.
- The capacity CPU numbers are not reconciled with the cgroup accounting (B15).

## Controls

- Empty overhead (the handshake, reported and never subtracted): median 8.553e+05 ns, 26 samples.
- No-change controls (A/A, even against odd blocks of py-optimized): baseline/cold EQUAL 1.01 [0.966, 1.02]; baseline/warm EQUAL 1 [0.996, 1.01]; crossover-small/cold EQUAL 1 [0.99, 1.01]; crossover-small/warm EQUAL 0.994 [0.981, 1.01]; crossover-tiny/cold EQUAL 0.994 [0.959, 1.01]; crossover-tiny/warm EQUAL 1 [0.955, 1.01]; full-dataset/cold EQUAL 0.977 [0.96, 0.995]; full-dataset/warm EQUAL 1.01 [0.987, 1.02]; language-only/direct EQUAL 0.999 [0.983, 1.02]; unit-alo-full/cold EQUAL 0.994 [0.974, 1.01]; unit-alo-full/warm EQUAL 1 [0.984, 1.03]; unit-alo-one/cold EQUAL 0.994 [0.99, 1]; unit-alo-one/warm EQUAL 0.997 [0.996, 1]; unit-baw-full/cold EQUAL 1 [1, 1.01]; unit-baw-full/warm EQUAL 0.997 [0.991, 1]; unit-baw-one/cold EQUAL 0.993 [0.973, 1.01]; unit-baw-one/warm EQUAL 0.998 [0.984, 1.01]; unit-bjs-full/cold EQUAL 1.01 [0.984, 1.02]; unit-bjs-full/warm EQUAL 1 [0.993, 1.03]; unit-bjs-one/cold EQUAL 1 [0.991, 1.01]; unit-bjs-one/warm EQUAL 0.997 [0.967, 1]; unit-bsm-full/cold EQUAL 1.01 [0.996, 1.04]; unit-bsm-full/warm EQUAL 1.01 [0.997, 1.03]; unit-bsm-one/cold EQUAL 0.996 [0.973, 1.03]; unit-bsm-one/warm EQUAL 0.999 [0.99, 1.02]; unit-crr-full/cold EQUAL 0.998 [0.991, 1.01]; unit-crr-full/warm EQUAL 1.01 [0.996, 1.03]; unit-crr-one/cold EQUAL 0.998 [0.994, 1.03]; unit-crr-one/warm EQUAL 1 [0.99, 1].
- identity: null
- scaling: []

## Three numbers to re-derive from compare.json

- `baseline` py-reference warm: wall 2.4057e+07 ns/unit (the median over 12 trials).
- `unit-bsm-full` c-serial [stdio] warm against the best Python row (py-optimized): FASTER, ratio 0.738715 [0.730165, 0.746672].
- `unit-alo-full` c-serial [stdio] warm against the best Python row (py-library): EQUAL, ratio 1.02845 [1.02568, 1.03137].

## Notes

- Demo run 1 (`34dc19222b104f21996131a96e8004f5`) was INVALID_EXPERIMENT. At that framework version the planner sized each one-contract trial from a per-row rate of 256-row calls. A py-optimized one-contract ALO call takes about 0.94 s, so 36 warm passes overran the 60 s ALO call deadline. The framework now sizes every trial from the measured walls of the calibration smoke (`docs/performance-laboratory.md`, section "Plan sizing and calibration"). This run is the rerun with that framework.
- The C rows run the verified `pl-worker` (routes `stdio` and `shm`) and `libpl_inproc.so` (route `inproc`) of the native build of the run.
