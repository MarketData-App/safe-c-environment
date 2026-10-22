/* Transcribed from QuantLib 1.43 (QL_VERSION 1.43; retained source
 * benchmarks/project/third_party/sources/QuantLib-1.43.tar.gz, sha256
 * b41206ccc4ba39b5e86bdc940d51138222b352f79d2c6fc68649f9c9bbe58701), via optionlab/alo.py
 * lines 270-277 (merged G-ALO2 part B, commit 567f6c4): ql/math/integrals/tanhsinhintegral.hpp
 * 53-65 (the Boost integrator that TanhSinhIntegral wraps; spec Appendix I-ALO R2). QuantLib
 * license (BSD-3-Clause): the copyright notices, conditions and disclaimer are in
 * NOTICE-QuantLib.md of this example (LR-EX 2026-10-18). */
/* Transcribed from Boost 1.90.0 (retained sources under benchmarks/project/third_party/sources/,
 * provenance benchmarks/project/third_party/provenance/boost-source.json): boost/math/quadrature/
 * tanh_sinh.hpp and its listed include closure, via optionlab/alo.py lines 270-277:
 * boost/math/quadrature/detail/tanh_sinh_detail.hpp 417-449 (the row sum of the level loop).
 * Copyright lines: tanh_sinh_detail.hpp: Copyright Nick Thompson, 2017. Boost Software License 1.0
 * (the text is in examples/option-pricing-benchmark/NOTICE-QuantLib.md and in the retained
 * LICENSE_1_0.txt). License review: LR-EX 2026-10-18 (agent engineering review). */
#include "pl_alo.h"
#include "pl_alo_step.h"
#include "pl_ieee.h"
#include "pl_types.h"

/* The row sum of one level of tanh_sinh_detail::integrate (specs/project/models.md "ALO
 * (Amendment I)"), copied from optionlab.alo.TanhSinhDetail.integrate statement by statement.
 * Its own translation unit, called from src/pl_alo_ts_level.c as an opaque function, and each
 * running sum is pl_sum2 (s + t: the same bits as s += t, an opaque result) for the fixed GCC
 * analyzer budget. The loop is bounded by the row length. */

int pl_alo_ts_row_sum(struct pl_alo_ts_state *s, int level, int length, int fc, int mli, int mri,
                      double *sum, double *absum) {
    struct pl_alo_run *run = s->run;
    for (int j = 0; j < length; j++) {
        if (j >= mli && j >= mri) {
            break;
        }
        double x = 0.0;
        double w = 0.0;
        if (pl_alo_ts_entry_with(level, j, s->crossover, &x, &w) != 0) {
            return pl_alo_fail(run, PL_ENGINE_PY_DEFECT); /* IndexError */
        }
        double xc = x;
        if (j >= fc) {
            x = 1.0 + xc;
        } else {
            xc = x - 1.0;
        }
        double yp = 0.0;
        double ym = 0.0;
        if (!(j >= mri)) {
            yp = pl_alo_ts_u(s->map, x, -xc);
            if (run->status != PL_ENGINE_OK) {
                return 1;
            }
        }
        if (!(j >= mli)) {
            ym = pl_alo_ts_u(s->map, -x, xc);
            if (run->status != PL_ENGINE_OK) {
                return 1;
            }
        }
        *sum = pl_sum2(*sum, (yp + ym) * w);
        *absum = pl_sum2(*absum, (pl_fabs(yp) + pl_fabs(ym)) * w);
    }
    return 0;
}
