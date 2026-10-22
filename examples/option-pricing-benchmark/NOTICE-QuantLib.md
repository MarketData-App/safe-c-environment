# QuantLib notice (option-pricing-benchmark example)

The Python pricer of this example (`benchmarks/project/python/optionlab/`) and the C pricer (`src/`, through the Python transcription) transcribe algorithms of QuantLib 1.43
(QL_VERSION 1.43). The retained source release is
`benchmarks/project/third_party/sources/QuantLib-1.43.tar.gz` (sha256
`b41206ccc4ba39b5e86bdc940d51138222b352f79d2c6fc68649f9c9bbe58701`, tag v1.43, commit
`6b57206e04598f092efee66e3b367efc84771995`; lock `benchmarks/project/third_party/lock.json`, row `QuantLib-source`). The
`py-library` variant calls the QuantLib-Python 1.43 wheel of the project bench image (lock row `quantlib`, under
`/opt/project-python`). Until FR4 these files were framework files under `third_party/developer/`.

## Transcribed QuantLib files

| Our file | QuantLib 1.43 source files (paths below `ql/`) |
|---|---|
| `optionlab/normal.py` | `math/errorfunction.cpp`, `math/distributions/normaldistribution.hpp`, `math/distributions/normaldistribution.cpp`, `mathconstants.hpp`, `qldefines.hpp` |
| `optionlab/models.py` | `pricingengines/blackcalculator.cpp`, `pricingengines/vanilla/analyticeuropeanengine.cpp`, `pricingengines/vanilla/bjerksundstenslandengine.hpp`, `pricingengines/vanilla/bjerksundstenslandengine.cpp`, `pricingengines/vanilla/binomialengine.hpp`, `methods/lattices/binomialtree.hpp`, `methods/lattices/binomialtree.cpp`, `methods/lattices/bsmlattice.hpp`, `pricingengines/vanilla/discretizedvanillaoption.cpp`, `pricingengines/greeks.cpp`, `processes/blackscholesprocess.cpp`, `termstructures/yieldtermstructure.cpp`, `termstructures/yield/flatforward.hpp`, `interestrate.hpp`, `interestrate.cpp`, `termstructures/volatility/equityfx/blackvoltermstructure.hpp`, `math/comparison.hpp` |
| `optionlab/baw.py` | `pricingengines/vanilla/baroneadesiwhaleyengine.hpp`, `pricingengines/vanilla/baroneadesiwhaleyengine.cpp`, `pricingengines/blackcalculator.cpp`, `instruments/oneassetoption.cpp` (greek availability) |
| `optionlab/baw_admit.py` | `pricingengines/vanilla/baroneadesiwhaleyengine.cpp`, `pricingengines/blackformula.hpp`, `pricingengines/blackformula.cpp`, `math/comparison.hpp`, `termstructures/yield/flatforward.hpp`, `interestrate.hpp`, `interestrate.cpp`, `termstructures/yieldtermstructure.hpp`, `termstructure.hpp`, `time/daycounters/actual365fixed.hpp` (spec Appendix G-BAW) |
| `optionlab/alo.py` | `pricingengines/vanilla/qdfpamericanengine.hpp`, `pricingengines/vanilla/qdfpamericanengine.cpp`, `pricingengines/vanilla/qdplusamericanengine.hpp`, `pricingengines/vanilla/qdplusamericanengine.cpp`, `math/interpolations/chebyshevinterpolation.hpp`, `math/interpolations/chebyshevinterpolation.cpp`, `math/interpolations/lagrangeinterpolation.hpp`, `math/interpolation.hpp`, `math/integrals/gaussianquadratures.hpp`, `math/integrals/gaussianquadratures.cpp` (the frozen table), `math/integrals/tanhsinhintegral.hpp`, `math/integrals/integral.cpp`, `math/comparison.hpp`, `math/solvers1d/brent.hpp`, `math/solver1d.hpp`, `pricingengines/blackcalculator.cpp`; Boost 1.90.0 `boost/math/quadrature/tanh_sinh.hpp`, `boost/math/quadrature/detail/tanh_sinh_detail.hpp`, `boost/math/special_functions/next.hpp`, `boost/math/tools/precision.hpp`, `boost/math/constants/constants.hpp`, `boost/math/policies/policy.hpp`, `boost/math/policies/error_handling.hpp` (copyright lines in its file header and in the Boost section below; spec Appendix I-ALO) |
| `optionlab/alo_tables.py` | Boost 1.90.0 `boost/math/quadrature/detail/tanh_sinh_detail.hpp:701-723` (the tabulated rows 0-7, copied as text) |
| `optionlab/alo_equation.py` | `termstructures/yield/flatforward.hpp`, `interestrate.cpp`, `pricingengines/vanilla/qdplusamericanengine.cpp`, `pricingengines/vanilla/qdfpamericanengine.cpp` (spec Appendix I-ALO R4) |
| `optionlab/optimized.py` | the files of the rows `optionlab/normal.py`, `optionlab/models.py`, `optionlab/solver.py` and `optionlab/baw.py` (vectorized), and for ALO (Task A5) the files of the row `optionlab/alo.py`, Boost 1.90.0 included (copyright lines in its file header and in the Boost section below) |
| `optionlab/solver.py` | `math/solvers1d/brent.hpp`, `math/solver1d.hpp`, `math/comparison.hpp` |
| `optionlab/mapping.py` | the unit-maturity problem of spec Amendment B item 3 (no QuantLib code) |
| `src/pl_ieee.c` (C, via `optionlab/models.py` lines 88-93) | `math/comparison.hpp` lines 59-76 (`close`, as `pl_close`); the Python-semantics helpers `pl_exp`, `pl_log`, `pl_sqrt`, `pl_pow`, `pl_erfc`, `pl_sq` (models.py lines 70-86) are optionlab code, no QuantLib source |
| `src/pl_normal.c` (C, via `optionlab/normal.py` lines 1-96) | `math/errorfunction.cpp` lines 196-246 (`ErrorFunction`, as `pl_erf`), `math/distributions/normaldistribution.hpp` lines 262-281, 296-299 (`NormalDistribution`, as `pl_norm_pdf`), `math/distributions/normaldistribution.cpp` lines 33-53 (`CumulativeNormalDistribution`, as `pl_norm_cdf`), `mathconstants.hpp` lines 85-87, 97-99, `qldefines.hpp` line 179 |
| `src/pl_black.c` (C, via `optionlab/models.py` lines 95-190 and `optionlab/mapping.py` lines 9-14) | `termstructures/yield/flatforward.hpp` lines 102-104, `interestrate.cpp` lines 53-54, 91-92, `termstructures/yieldtermstructure.cpp` lines 30, 118-127, 154-171 (discount, zero and forward rates), `termstructures/volatility/equityfx/blackvoltermstructure.hpp` lines 304-308 (Black variance), `pricingengines/blackcalculator.cpp` lines 65-428 (`BlackCalculator`); `pl_py_div`, `pl_sum3` and `pl_sum4` in `src/pl_ieee.c` are optionlab code, no QuantLib source |
| `src/pl_bsm.c` (C, via `optionlab/models.py` lines 195-202, 448) | `pricingengines/vanilla/analyticeuropeanengine.cpp` lines 45-114 (`AnalyticEuropeanEngine`) |
| `src/pl_bjs_phi.c` (C, via `optionlab/models.py` lines 204-244) | `pricingengines/vanilla/bjerksundstenslandengine.cpp` lines 37-48 (phi) and 50-110 (its analytic derivatives), `pricingengines/vanilla/bjerksundstenslandengine.hpp` line 33 (the 1993 method) |
| `src/pl_bjs.c` (C, via `optionlab/models.py` lines 39, 246-355, 449) | `pricingengines/vanilla/bjerksundstenslandengine.cpp` lines 115-175 (European and immediate-exercise results), 177-429 (`americanCallApproximation`), 432-506 (`BjerksundStenslandApproximationEngine::calculate`), `pricingengines/vanilla/bjerksundstenslandengine.hpp` line 33; `pl_sum2` in `src/pl_ieee.c` is optionlab code, no QuantLib source |
| `src/pl_crr.c` (C, via `optionlab/models.py` lines 357-371, 397-428, 450-456, 481-496 and `optionlab/params.py`) | `pricingengines/vanilla/binomialengine.hpp` lines 74-172 (`BinomialVanillaEngine`), `methods/lattices/binomialtree.hpp` lines 42-47, 84-101 and `methods/lattices/binomialtree.cpp` lines 37-48 (`CoxRossRubinstein`), `methods/lattices/bsmlattice.hpp` lines 71-87 (`BlackScholesLattice`), `processes/blackscholesprocess.cpp` lines 74-82, 108-129 (drift and diffusion), `pricingengines/vanilla/discretizedvanillaoption.cpp` lines 47-77 (exercise), `pricingengines/greeks.cpp` lines 25-35 (`blackScholesTheta`); `pl_sigma_lo`, `pl_crr_domain_ok` and `pl_case_params` are optionlab code, no QuantLib source |
| `src/pl_crr_lattice.c` (C, via `optionlab/models.py` lines 406-414) | `methods/lattices/binomialtree.hpp` lines 84-101 (`CoxRossRubinstein` underlying values), `methods/lattices/bsmlattice.hpp` lines 71-87 (`BlackScholesLattice` rollback), `pricingengines/vanilla/discretizedvanillaoption.cpp` lines 47-77 (exercise) |
| `src/pl_solver.c` (C, via `optionlab/solver.py` lines 1-88) | `math/solver1d.hpp` lines 162-211 (`Solver1D::solve` with the `xMin`/`xMax` bracket), `math/solvers1d/brent.hpp` lines 39-137 (`Brent::solveImpl` and `Brent::sign`), `math/comparison.hpp` lines 59-76 (`close`, through `pl_close` in `src/pl_ieee.c`); `pl_objective_value` (the cubic test objective and the row objective of `optionlab/reference.py` lines 97-99) is optionlab code, no QuantLib source |
| `src/pl_greeks.c` (C, via `optionlab/reference.py` lines 45-64 and `optionlab/mapping.py` lines 16-38) | the engine greeks through `pl_bsm_result`, `pl_bjs_result` and `pl_crr_result` (`pricingengines/vanilla/analyticeuropeanengine.cpp` lines 45-114, `pricingengines/vanilla/bjerksundstenslandengine.cpp` lines 432-506, `pricingengines/vanilla/binomialengine.hpp` lines 74-172); the CRR bumps, the chain rule and the order-5 checks are optionlab code (spec 3.6, Amendment B item 3), no QuantLib source |
| `src/pl_evaluate.c` (C, via `optionlab/reference.py` lines 20-109, `optionlab/mapping.py` lines 16-38 and `optionlab/models.py` lines 465-470) | the implied-volatility solve through `pl_brent` (`math/solver1d.hpp` lines 162-211, `math/solvers1d/brent.hpp` lines 39-137, `math/comparison.hpp` lines 59-76); τ_V, the order-5 check, the status order, the flags, the chain-rule greeks and the evaluation count are optionlab code (spec 3.3, 3.6, Amendment B item 3), no QuantLib source |
| `src/pl_baw_map.c` (C, via `optionlab/baw_admit.py` lines 40-125) | `pricingengines/vanilla/baroneadesiwhaleyengine.cpp` lines 39-138 (`criticalPrice`: seed 50-74, map 79-96 and 113-118, updates 98 and 120, stop test 97 and 119), `pricingengines/blackformula.cpp` lines 40-54, 59-98 and `pricingengines/blackformula.hpp` lines 46-51 (`blackFormula`), `math/comparison.hpp` lines 78-90 (`close(x, y, n)`), `termstructures/yield/flatforward.hpp` lines 102-105, `interestrate.hpp` lines 69-71, `interestrate.cpp` lines 53-54 (the discounts at t = 1.0) |
| `src/pl_baw_cert.c` (C, via `optionlab/baw_admit.py` lines 155-210) | the certificate of spec Appendix G-BAW item R4 over the map of `pricingengines/vanilla/baroneadesiwhaleyengine.cpp` lines 79-131; the certificate itself is optionlab code (the approved record), no QuantLib source |
| `src/pl_baw_admit.c` (C, via `optionlab/baw_admit.py` lines 212-248) | the replay of `pricingengines/vanilla/baroneadesiwhaleyengine.cpp` lines 39-138 and the branch gate of line 167, with the discounts at t = 1.0 from `termstructures/yield/flatforward.hpp` lines 102-105, `interestrate.hpp` lines 69-71 and `interestrate.cpp` lines 53-54; `baw_admit` is optionlab code (spec Appendix G-BAW item R4), no further QuantLib source |
| `src/pl_baw.c` (C, via `optionlab/baw.py` lines 22-63, `optionlab/baw_admit.py` lines 127-153, `optionlab/models.py` lines 478-483 and `optionlab/reference.py` lines 54-69) | `pricingengines/vanilla/baroneadesiwhaleyengine.hpp` lines 43-48, `pricingengines/vanilla/baroneadesiwhaleyengine.cpp` lines 39-236 (`criticalPrice`, `calculate`), `pricingengines/blackcalculator.cpp` lines 65-75 (checks; value and greeks through `src/pl_black.c`); the cap, the planted S* and `pl_baw_price` are optionlab code |
| `src/pl_baw_points.c` (C, via `optionlab/reference.py` lines 63-79, 96-98) | the engine and S* through `src/pl_baw.c` (`pricingengines/vanilla/baroneadesiwhaleyengine.cpp` lines 140-236); the side test is optionlab code (spec Appendix G-BAW item R7), no further QuantLib source |
| `src/pl_baw_stencil.c` (C, via `optionlab/reference.py` lines 109-143) | the engine through `src/pl_baw.c` (`pricingengines/vanilla/baroneadesiwhaleyengine.cpp` lines 140-236); the stencils are optionlab code (spec Appendix G-BAW items R6, R7), no further QuantLib source |
| `src/pl_baw_greeks.c` (C, via `optionlab/reference.py` lines 83-147, 177-185 and `optionlab/mapping.py` lines 16-38) | the engine greeks of the European branch through `src/pl_baw.c` and `src/pl_black.c` (`pricingengines/vanilla/baroneadesiwhaleyengine.cpp` lines 167-191); the greek table, the halving loops and the chain rule are optionlab code (spec Appendix G-BAW item R6, Amendment B item 3), no further QuantLib source |
| `src/pl_alo_equation.c` (C, via `optionlab/alo_equation.py` lines 33-69) | `termstructures/yield/flatforward.hpp` lines 102-104, `interestrate.cpp` lines 53-54, `pricingengines/vanilla/qdplusamericanengine.cpp` lines 182-183, 190-193, 207, 231-251, `pricingengines/vanilla/qdfpamericanengine.cpp` lines 432, 455-463 (spec Appendix I-ALO R4) |
| `src/pl_alo.c` (C, via `optionlab/alo.py` lines 469-477, 553-693 and `optionlab/alo_equation.py` lines 27-40) | `pricingengines/vanilla/qdplusamericanengine.cpp` lines 132-158, 167-228, 346-362, `pricingengines/vanilla/qdfpamericanengine.cpp` lines 429-516, `pricingengines/blackcalculator.cpp` lines 65-75 (checks; value through `src/pl_black.c`), `math/comparison.hpp` lines 59-76; the pre check, the planted-defect hooks and the caps are optionlab code (spec Appendix I-ALO R7, R8, I4.1) |
| `src/pl_alo_run.c` (C, via `optionlab/alo.py` lines 131-162) | `math/comparison.hpp` lines 92-107 (`close_enough`); the shared NaN check, the guards and the loop caps are optionlab code (spec Appendix I-ALO R3, R7, R8) |
| `src/pl_alo_cheb.c` (C, via `optionlab/alo.py` lines 333-356) | `math/interpolations/chebyshevinterpolation.cpp` lines 33-81, `math/interpolations/lagrangeinterpolation.hpp` lines 42-134, `math/interpolation.hpp` lines 122-125 |
| `src/pl_alo_qdplus.c` (C, via `optionlab/alo.py` lines 359-368, 417-467) | `pricingengines/vanilla/qdplusamericanengine.cpp` lines 231-251, 262-344; `math/solvers1d/brent.hpp` and `math/solver1d.hpp` through `src/pl_solver.c` |
| `src/pl_alo_edge.c` (C, via `optionlab/alo.py` lines 638-647) | `pricingengines/vanilla/qdplusamericanengine.cpp` lines 214-221 (the `close(volatility, 0.0)` branch of `calculatePutWithEdgeCases`) |
| `src/pl_alo_qdeval.c` (C, via `optionlab/alo.py` lines 370-415) | `pricingengines/vanilla/qdplusamericanengine.cpp` lines 41-122 (`QdPlusBoundaryEvaluator`) |
| `src/pl_alo_sweep.c` (C, via `optionlab/alo.py` lines 579-596) | `pricingengines/vanilla/qdfpamericanengine.cpp` lines 429-516 (one sweep over the nodes, then `updateY`) |
| `src/pl_alo_node.c` (C, via `optionlab/alo.py` lines 469-477, 575-595) | `pricingengines/vanilla/qdplusamericanengine.cpp` lines 346-362 (one boundary node), `pricingengines/vanilla/qdfpamericanengine.cpp` lines 429-516 (the node update of the sweeps) |
| `src/pl_alo_fp.c` (C, via `optionlab/alo.py` lines 480-551, 569-574) | `pricingengines/vanilla/qdfpamericanengine.cpp` lines 119-158, 198-400, 444-450, `mathconstants.hpp` lines 74, 86, 94, 98 |
| `src/pl_alo_tables.c` (C, via `optionlab/alo.py` lines 68-98, 164-206 and `optionlab/alo_tables.py` lines 13-34) | `math/integrals/gaussianquadratures.hpp` lines 172-176, 230-246 and `math/integrals/gaussianquadratures.cpp` lines 34-61 (the frozen table of spec Appendix I-ALO R5), `math/integrals/tanhsinhintegral.hpp` lines 41-70; Boost 1.90.0 `boost/math/quadrature/detail/tanh_sinh_detail.hpp` (rows 0-7 as decimal literals, rows 8-15, t_crossover) and `boost/math/constants/constants.hpp` (copyright lines in its file header and in the Boost section below) |
| `src/pl_alo_ts.c` (C, via `optionlab/alo.py` lines 207-243, 303-330) | `math/integrals/tanhsinhintegral.hpp` lines 41-70, `math/integrals/integral.cpp` lines 76-86; Boost 1.90.0 `boost/math/quadrature/tanh_sinh.hpp`, `boost/math/quadrature/detail/tanh_sinh_detail.hpp`, `boost/math/special_functions/next.hpp`, `boost/math/tools/precision.hpp`, `boost/math/constants/constants.hpp`, `boost/math/policies/policy.hpp`, `boost/math/policies/error_handling.hpp` (copyright lines in its file header and in the Boost section below) |
| `src/pl_alo_ts_level.c` (C, via `optionlab/alo.py` lines 243-301) | `math/integrals/tanhsinhintegral.hpp` lines 53-65; Boost 1.90.0 `boost/math/quadrature/detail/tanh_sinh_detail.hpp`, `boost/math/tools/precision.hpp`, `boost/math/policies/policy.hpp`, `boost/math/policies/error_handling.hpp` (copyright lines in its file header and in the Boost section below) |
| `src/pl_alo_ts_ends.c` (C, via `optionlab/alo.py` lines 253-265, 290-297) | `math/integrals/tanhsinhintegral.hpp` lines 53-65; Boost 1.90.0 `boost/math/quadrature/detail/tanh_sinh_detail.hpp` lines 370-400, 509-530, `boost/math/policies/policy.hpp`, `boost/math/policies/error_handling.hpp` (copyright lines in its file header and in the Boost section below) |
| `src/pl_alo_ts_row0.c` (C, via `optionlab/alo.py` lines 211-242) | `math/integrals/tanhsinhintegral.hpp` lines 53-65; Boost 1.90.0 `boost/math/quadrature/detail/tanh_sinh_detail.hpp` lines 208-310, `boost/math/constants/constants.hpp`, `boost/math/tools/precision.hpp` (copyright lines in its file header and in the Boost section below) |
| `src/pl_alo_ts_sum.c` (C, via `optionlab/alo.py` lines 270-277) | `math/integrals/tanhsinhintegral.hpp` lines 53-65; Boost 1.90.0 `boost/math/quadrature/detail/tanh_sinh_detail.hpp` lines 417-449 (copyright lines in its file header and in the Boost section below) |
| `src/pl_alo_points.c` (C, via `optionlab/reference.py` lines 159-163, 186-190, 198-211 and `optionlab/mapping.py` lines 9-14) | the engine through `src/pl_alo.c` (`pricingengines/vanilla/qdplusamericanengine.cpp` lines 167-228 and `pricingengines/vanilla/qdfpamericanengine.cpp` lines 429-516); the greek points and the segment test are optionlab code (spec Appendix I-ALO R6, I2.6), no further QuantLib source |
| `src/pl_alo_greeks.c` (C, via `optionlab/reference.py` lines 178-218, 253-257, `optionlab/mapping.py` lines 16-38 and `optionlab/models.py` lines 528-542) | the engine through `src/pl_alo.c` (`pricingengines/vanilla/qdfpamericanengine.cpp` lines 429-516); the greek table, the halving loops and the chain rule are optionlab code (spec Appendix I-ALO R6, I2.6, Amendment B item 3), no further QuantLib source |
| `src/pl_alo_stencil.c` (C, via `optionlab/reference.py` lines 198-214) | the engine through `src/pl_alo.c` (`pricingengines/vanilla/qdfpamericanengine.cpp` lines 429-516); the rho and theta stencils with their halving loops are optionlab code (spec Appendix I-ALO R6, I2.6), no further QuantLib source |
| `optionlab/library.py` | calls QuantLib-Python (`QdFpAmericanEngine` with `accurateScheme()` and `Auto` for ALO since Task A5); exception texts of `math/solver1d.hpp` and `math/solvers1d/brent.hpp` |
| `optionlab/checks.py` | calls QuantLib-Python (`BaroneAdesiWhaleyApproximationEngine`) for the BAW alignment checks |

## License record

An agent engineering license review (LR-EX, task T25 of the benchmark-readiness goal, 2026-10-18) reviewed the
QuantLib 1.43 and Boost 1.90.0 material of this example. It is not legal advice. Result: QuantLib 1.43 is under the
QuantLib license (BSD-3-Clause; text below). Boost 1.90.0 is under the Boost Software License 1.0 (text below). Both
licenses allow the transcriptions listed above and their redistribution in source form, on these conditions:

- this file keeps the QuantLib copyright notices, the license conditions and the disclaimer, and the Boost license
  text;
- each transcribed file keeps its attribution header;
- nobody uses the names of the QuantLib copyright holders, the QuantLib Group, the Boost authors, the University of
  Chicago or Argonne National Laboratory to endorse or promote this example.

The first-party code of this example is under the MIT license of the repository (`LICENSE`). The MIT license does not
replace the QuantLib or Boost terms for the transcribed parts.

Legal-team confirmation received 2026-10-19 for QuantLib: QuantLib is licensed under the BSD 3-Clause License (also
called the Modified BSD License), a permissive, non-copyleft open-source license that explicitly permits commercial and
proprietary use. The lock sets `review_status` APPROVED for the row `QuantLib-source` (the QuantLib 1.43 source release).
The row `quantlib` (the QuantLib-Python 1.43 wheel) stays PENDING: the wheel also holds compiled Boost 1.90.0 code
(BSL-1.0), which the confirmation does not name. The Boost 1.90.0 material (BSL-1.0), SciPy and mpmath have no separate
legal-team statement; their rows stay PENDING. Reports and readiness show no legal clearance for a PENDING row.

## QuantLib license text (LICENSE.TXT of the release, also `benchmarks/project/third_party/notices/QuantLib-source/LICENSE.TXT`)

```text

Copyright (C) 2000, 2001, 2002, 2003 RiskMap srl

Copyright (C) 2001, 2002, 2003 Nicolas Di Césaré
Copyright (C) 2001, 2002, 2003 Sadruddin Rejeb

Copyright (C) 2002, 2003, 2004 Decillion Pty(Ltd)
Copyright (C) 2002, 2003, 2004, 2005, 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2014, 2015 Ferdinando Ametrano

Copyright (C) 2003 Kawanishi Tomoya
Copyright (C) 2003 Niels Elken Sønderby
Copyright (C) 2003, 2004 Roman Gitlin
Copyright (C) 2003, 2004, 2005, 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021 StatPro Italia srl
Copyright (C) 2003, 2004, 2007 Neil Firth

Copyright (C) 2004 FIMAT Group
Copyright (C) 2004 Gianni Piolanti
Copyright (C) 2004 Jeff Yu
Copyright (C) 2004 M-Dimension Consulting Inc.
Copyright (C) 2004 Mike Parker
Copyright (C) 2004 Walter Penschke
Copyright (C) 2004, 2005, 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025 Klaus Spanderen

Copyright (C) 2005 Charles Whitmore
Copyright (C) 2005 Sercan Atalik
Copyright (C) 2005, 2006 Theo Boafo
Copyright (C) 2005, 2006, 2007 Joseph Wang
Copyright (C) 2005, 2006, 2007, 2009 Piter Dias
Copyright (C) 2005, 2006, 2008 Toyin Akin
Copyright (C) 2005, 2013 Gary Kennedy

Copyright (C) 2006 Richard Gould
Copyright (C) 2006 Silvia Frasson
Copyright (C) 2006 Warren Chou
Copyright (C) 2006 Yiping Chen
Copyright (C) 2006, 2007 Banca Profilo S.p.A.
Copyright (C) 2006, 2007 Chiara Fornarola
Copyright (C) 2006, 2007 Cristina Duminuco
Copyright (C) 2006, 2007 François du Vignaud
Copyright (C) 2006, 2007 Giorgio Facchinetti
Copyright (C) 2006, 2007 Katiuscia Manzoni
Copyright (C) 2006, 2007 Marco Bianchetti
Copyright (C) 2006, 2007 Mario Pucci
Copyright (C) 2006, 2007, 2008 Allen Kuo
Copyright (C) 2006, 2007, 2008, 2009, 2010 Mark Joshi
Copyright (C) 2006, 2007, 2008, 2009, 2012 Roland Lichters

Copyright (C) 2007 Affine Group Limited
Copyright (C) 2007 Gang Liang
Copyright (C) 2007 Richard Gomes
Copyright (C) 2007, 2008 Laurent Hoffmann
Copyright (C) 2007, 2008, 2009, 2010, 2011 Chris Kenyon

Copyright (C) 2008 Florent Grenier
Copyright (C) 2008 Francesca Mariani
Copyright (C) 2008 Francesco Zirilli
Copyright (C) 2008 Frank Hövermann
Copyright (C) 2008 J. Erik Radmall
Copyright (C) 2008 John Maiden
Copyright (C) 2008 Lorella Fatone
Copyright (C) 2008 Marek Glowacki
Copyright (C) 2008 Maria Cristina Recchioni
Copyright (C) 2008 Paul Farrington
Copyright (C) 2008 Piero Del Boca
Copyright (C) 2008 Roland Stamm
Copyright (C) 2008 Simon Ibbotson
Copyright (C) 2008 Yee Man Chan
Copyright (C) 2008, 2009 Andrea Odetti
Copyright (C) 2008, 2009 Andreas Gaida
Copyright (C) 2008, 2009, 2010, 2011, 2012, 2014 Master IMAFA - Polytech'Nice Sophia - Université de Nice Sophia Antipolis
Copyright (C) 2008, 2009, 2012, 2014 Ralph Schreyer
Copyright (C) 2008, 2009, 2014, 2015, 2016 Jose Aparicio
Copyright (C) 2008, 2011 Charles Chongseok Hyun

Copyright (C) 2009 Bernd Engelmann
Copyright (C) 2009 Bojan Nikolic
Copyright (C) 2009 Frédéric Degraeve
Copyright (C) 2009 Nathan Abbott
Copyright (C) 2009 Sun Xiuxin
Copyright (C) 2009 Sylvain Bertrand
Copyright (C) 2009, 2010 Dimitri Reiswich
Copyright (C) 2009, 2010, 2012 Liquidnet Holdings, Inc.
Copyright (C) 2009, 2024 Dirk Eddelbuettel

Copyright (C) 2010 Adrian O' Neill
Copyright (C) 2010 Alessandro Roveda
Copyright (C) 2010 DeriveXperts SAS
Copyright (C) 2010 Hachemi Benyahia
Copyright (C) 2010 Kakhkhor Abdijalilov
Copyright (C) 2010 Manas Bhatt
Copyright (C) 2010 Michael Heckl
Copyright (C) 2010 Robert Philipp
Copyright (C) 2010 Slava Mazur
Copyright (C) 2010 SunTrust Bank
Copyright (C) 2010, 2011, 2012, 2013, 2023 Andre Miemiec
Copyright (C) 2010, 2014 Cavit Hafizoglu

Copyright (C) 2011, 2013, 2014 Fabien Le Floc'h

Copyright (C) 2012 Mateusz Kapturski
Copyright (C) 2012 Samuel Tebege
Copyright (C) 2012 Simon Shakeshaft
Copyright (C) 2012 Édouard Tallent
Copyright (C) 2012, 2013 Grzegorz Andruszkiewicz
Copyright (C) 2012, 2013, 2014, 2015, 2016, 2017, 2018, 2023, 2024, 2025 Peter Caspers

Copyright (C) 2013 BGC Partners L.P.
Copyright (C) 2013 Chris Higgs
Copyright (C) 2013 Yue Tian
Copyright (C) 2013, 2014, 2015 Cheng Li

Copyright (C) 2014 Michal Kaut
Copyright (C) 2014, 2015 Bernd Lewerenz
Copyright (C) 2014, 2015 Johannes Göttker-Schnetmann
Copyright (C) 2014, 2015 Thema Consulting SA
Copyright (C) 2014, 2015, 2016 Michael von den Driesch
Copyright (C) 2014, 2015, 2016 Paolo Mazzocchi
Copyright (C) 2014, 2017, 2024 Francois Botha

Copyright (C) 2015 CompatibL
Copyright (C) 2015 Dmitri Nesteruk
Copyright (C) 2015 Maddalena Zanzi
Copyright (C) 2015 Riccardo Barone
Copyright (C) 2015, 2016 Andres Hernandez

Copyright (C) 2016 Nicholas Bertocchi
Copyright (C) 2016 Stefano Fondi
Copyright (C) 2016, 2017 Fabrice Lecuyer
Copyright (C) 2016, 2018, 2019, 2020, 2022 Quaternion Risk Management Ltd
Copyright (C) 2016, 2019, 2020 Eisuke Tani

Copyright (C) 2017 BN Algorithms Ltd
Copyright (C) 2017 Joseph Jeisman
Copyright (C) 2017 Paul Giltinan
Copyright (C) 2017 Werner Kuerzinger
Copyright (C) 2017, 2022 Oleg Kulkov

Copyright (C) 2018 Alexey Indiryakov
Copyright (C) 2018 Jose Garcia
Copyright (C) 2018 Matthias Groncki
Copyright (C) 2018 Matthias Lungwitz
Copyright (C) 2018 Roy Zywina
Copyright (C) 2018 Sebastian Schlenkrich
Copyright (C) 2018 Tom Anderson

Copyright (C) 2019 Aprexo Limited
Copyright (C) 2019 SoftSolutions! S.r.l.
Copyright (C) 2019 Wojciech Ślusarski

Copyright (C) 2020 Kline s.r.l.
Copyright (C) 2020 Leonardo Arcari
Copyright (C) 2020 Piotr Siejda
Copyright (C) 2020, 2021 Jack Gillett
Copyright (C) 2020, 2021 Lew Wei Hao
Copyright (C) 2020, 2021, 2022, 2023, 2024 Skandinaviska Enskilda Banken AB (publ)
Copyright (C) 2020, 2021, 2022, 2023, 2025 Marcin Rybacki

Copyright (C) 2021 Anubhav Pandey
Copyright (C) 2021 Magnus Mencke
Copyright (C) 2021, 2022, 2023, 2024 Ralf Konrad Eckel

Copyright (C) 2022, 2023 Ignacio Anguita
Copyright (C) 2022, 2023 Jonghee Lee

Copyright (C) 2023 Aditya Narayan Das
Copyright (C) 2023 Andrea Pellegatta
Copyright (C) 2023 Jonathan Sweemer
Copyright (C) 2023 Nathaniel Brough
Copyright (C) 2023 Paul Xi Cao

Copyright (C) 2024 Jacques du Toit
Copyright (C) 2024 Jongbong An

Copyright (C) 2025 AcadiaSoft Inc.
Copyright (C) 2025 Hiroto Ogawa
Copyright (C) 2025 Kareem Fareed
Copyright (C) 2025 Shubham Gaur
Copyright (C) 2025 Sotirios Papathanasopoulos
Copyright (C) 2025 Uzair Beg
Copyright (C) 2025 William Day
Copyright (C) 2025, 2026 Eugene Toder
Copyright (C) 2025, 2026 Paolo D'Elia

Copyright (C) 2026 Aaditya Panikath
Copyright (C) 2026 Chirag Desai
Copyright (C) 2026 Colin Alberts
Copyright (C) 2026 David Korczynski
Copyright (C) 2026 Junjie Guo
Copyright (C) 2026 Pratyush Patel
Copyright (C) 2026 Richard Amaya
Copyright (C) 2026 SoftSolution srl
Copyright (C) 2026 Yassine Idyiahia
Copyright (C) 2026 Zain Mughal

QuantLib includes code taken from Peter Jäckel's book "Monte Carlo
Methods in Finance".

QuantLib includes software developed by the University of Chicago,
as Operator of Argonne National Laboratory.

QuantLib includes a set of numbers provided by Stephen Joe and Frances
Kuo under a BSD-style license.


Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

    Redistributions of source code must retain the above copyright notice,
    this list of conditions and the following disclaimer.

    Redistributions in binary form must reproduce the above copyright notice,
    this list of conditions and the following disclaimer in the documentation
    and/or other materials provided with the distribution.

    Neither the names of the copyright holders nor the names of the QuantLib
    Group and its contributors may be used to endorse or promote products
    derived from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND
CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES,
INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF
MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDERS OR
CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF
USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED
AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE.
```

## Boost tanh-sinh transcription reference

QuantLib 1.43 `QdFpAmericanEngine` with `accurateScheme()` converts the exercise boundary into the price with
`TanhSinhIntegral`, a wrapper of Boost `boost::math::quadrature::tanh_sinh` (spec Appendix I-ALO, R1a and R2). The
QuantLib-Python 1.43 wheel was built with Boost 1.90.0 (`BOOST_VERSION` 109000). The retained Boost 1.90.0 files below
`benchmarks/project/third_party/sources/boost-1.90.0/` (provenance `benchmarks/project/third_party/provenance/boost-source.json`, lock row `Boost` of `retained`: archive
`boost_1_90_0.tar.bz2`, sha256 `49551aff3b22cbc5c5a9ed3dbc92f0e23ea50a0f7325b0d198b705e8ee3fc305`) are a transcription
and verification reference only: they are never built, linked or put on an include path. Each retained file keeps its
own notice. Each transcribed ALO file (Python and C) carries a file-scope header that names Boost 1.90.0 and the source
files `boost/math/quadrature/tanh_sinh.hpp` and `boost/math/quadrature/detail/tanh_sinh_detail.hpp` next to the
QuantLib attribution.

### Boost copyright notices (spec Appendix I-ALO R1a.4, ALO1-03)

The retained Boost 1.90.0 files carry these copyright lines (as written in the first lines of each file):

| Boost 1.90.0 file (below `boost/math/`) | Copyright lines |
|---|---|
| `quadrature/tanh_sinh.hpp` | Copyright Nick Thompson, 2017 |
| `quadrature/detail/tanh_sinh_detail.hpp` | Copyright Nick Thompson, 2017 |
| `special_functions/next.hpp` | (C) Copyright John Maddock 2008. |
| `tools/precision.hpp` | Copyright John Maddock 2005-2006. |
| `constants/constants.hpp` | Copyright John Maddock 2005-2006, 2011. Copyright Paul A. Bristow 2006-2011. Copyright Matt Borland 2024. |
| `policies/policy.hpp` | Copyright John Maddock 2007. Copyright Matt Borland 2021. |
| `policies/error_handling.hpp` | Copyright John Maddock 2007. Copyright Paul A. Bristow 2007. Copyright Matt Borland 2024. |

Rule: each transcribed Python and C file of the example carries, in its file-scope header, the copyright lines of
every Boost file above that it transcribes, plus the Boost Software License 1.0 statement or a pointer to the license
text in this section.

License record: see the section "License record" above (LR-EX, 2026-10-18; not legal advice). The Boost 1.90.0
material has no separate legal-team statement (the confirmation of 2026-10-19 names QuantLib only), so the lock keeps
the `review_status` of the row `Boost` PENDING. Reports and readiness show no legal clearance for it.

### Boost Software License 1.0 (`LICENSE_1_0.txt` of the release)

```text
Boost Software License - Version 1.0 - August 17th, 2003

Permission is hereby granted, free of charge, to any person or organization
obtaining a copy of the software and accompanying documentation covered by
this license (the "Software") to use, reproduce, display, distribute,
execute, and transmit the Software, and to prepare derivative works of the
Software, and to permit third-parties to whom the Software is furnished to
do so, all subject to the following:

The copyright notices in the Software and this entire statement, including
the above license grant, this restriction and the following disclaimer,
must be included in all copies of the Software, in whole or in part, and
all derivative works of the Software, unless such copies or derivative
works are solely in the form of machine-executable object code generated by
a source language processor.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE, TITLE AND NON-INFRINGEMENT. IN NO EVENT
SHALL THE COPYRIGHT HOLDERS OR ANYONE DISTRIBUTING THE SOFTWARE BE LIABLE
FOR ANY DAMAGES OR OTHER LIABILITY, WHETHER IN CONTRACT, TORT OR OTHERWISE,
ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
DEALINGS IN THE SOFTWARE.
```
