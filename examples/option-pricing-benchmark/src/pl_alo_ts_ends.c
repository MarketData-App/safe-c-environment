/* Transcribed from QuantLib 1.43 (QL_VERSION 1.43; retained source
 * benchmarks/project/third_party/sources/QuantLib-1.43.tar.gz, sha256
 * b41206ccc4ba39b5e86bdc940d51138222b352f79d2c6fc68649f9c9bbe58701), via optionlab/alo.py
 * lines 253-265, 290-297 (merged G-ALO2 part B, commit 567f6c4): ql/math/integrals/
 * tanhsinhintegral.hpp 53-65 (the Boost integrator that TanhSinhIntegral wraps; spec Appendix
 * I-ALO R2). QuantLib license (BSD-3-Clause): see NOTICE-QuantLib.md (LR-EX 2026-10-18). */
/* Transcribed from Boost 1.90.0 (retained sources under benchmarks/project/third_party/sources/,
 * provenance benchmarks/project/third_party/provenance/boost-source.json): boost/math/quadrature/
 * tanh_sinh.hpp and its listed include closure, via optionlab/alo.py lines 253-265, 290-297:
 * boost/math/quadrature/detail/tanh_sinh_detail.hpp 370-400 (the end retreat of a level) and
 * 509-530 (the end sanity check), boost/math/policies/policy.hpp and
 * boost/math/policies/error_handling.hpp (evaluation_error). Copyright lines:
 * tanh_sinh_detail.hpp: Copyright Nick Thompson, 2017. policy.hpp: Copyright John Maddock 2007.
 * Copyright Matt Borland 2021. error_handling.hpp: Copyright John Maddock 2007. Copyright Paul A.
 * Bristow 2007. Copyright Matt Borland 2024. Boost Software License 1.0 (the text is in
 * examples/option-pricing-benchmark/NOTICE-QuantLib.md and in the retained LICENSE_1_0.txt).
 * License review: LR-EX 2026-10-18 (agent engineering review). */
#include "pl_alo.h"
#include "pl_alo_step.h"
#include "pl_ieee.h"
#include "pl_types.h"

/* The ends of one level of tanh_sinh_detail::integrate (specs/project/models.md "ALO
 * (Amendment I)"), copied from optionlab.alo.TanhSinhDetail.integrate statement by statement:
 * the row entries, the integrand at an end, the retreat over non-finite end values and the end
 * sanity check. Their own translation unit: opaque calls from src/pl_alo_ts_level.c (the fixed
 * GCC analyzer budget). Each retreat loop is bounded by the row length; a Boost evaluation_error
 * is PL_ENGINE_QL_ERROR. */

/* Entry j of the row: 0 with *a and *w, or 1 (an IndexError: a Python raise, never reached). */
static int entry(const struct pl_alo_ts_row *row, int j, double *a, double *w) {
    return pl_alo_ts_entry_with(row->level, j, row->crossover, a, w);
}

double pl_alo_ts_abscissa(const struct pl_alo_ts_row *row, int j) {
    double a = pl_nan();
    double w = 0.0;
    if (entry(row, j, &a, &w) != 0) {
        return pl_nan();
    }
    return a;
}

double pl_alo_ts_weight(const struct pl_alo_ts_row *row, int j) {
    double a = 0.0;
    double w = pl_nan();
    if (entry(row, j, &a, &w) != 0) {
        return pl_nan();
    }
    return w;
}

/* The integrand at the end index of one side (alo.py:254, 261, 291-297): the left end
 * f(-1 - a, a), the right end f(1 + a, -a). Returns 1 on a failure. */
static int end_at(struct pl_alo_ts_state *s, const struct pl_alo_ts_row *row, int right, int index,
                  double *y) {
    double a = 0.0;
    double w = 0.0;
    if (entry(row, index, &a, &w) != 0) {
        return pl_alo_fail(s->run, PL_ENGINE_PY_DEFECT); /* IndexError */
    }
    *y = right ? pl_alo_ts_u(s->map, 1.0 + a, -a) : pl_alo_ts_u(s->map, -1.0 - a, a);
    return s->run->status != PL_ENGINE_OK;
}

int pl_alo_ts_retreat(struct pl_alo_ts_state *s, const struct pl_alo_ts_row *row, int right,
                      int *position, int *index, double *y) {
    const int position0 = *position;
    const int index0 = *index;
    for (int g = 0; g <= row->length; g++) {
        const int idx = index0 - g;
        const int pos = position0 - 2 * g;
        if (end_at(s, row, right, idx, y) != 0) {
            return 1;
        }
        if (pl_is_finite(*y)) {
            return 0;
        }
        if (pos <= 2) {
            return pl_alo_fail(s->run, PL_ENGINE_QL_ERROR); /* non-finite everywhere */
        }
        *position = pos - 2;
        *index = idx - 1;
        if (!(pl_alo_ts_abscissa(row, idx - 1) < 0.0)) {
            return 0;
        }
    }
    return pl_alo_fail(s->run, PL_ENGINE_PY_DEFECT); /* unreachable: bounded by the row */
}

int pl_alo_ts_sanity(struct pl_alo_ts_state *s, const struct pl_alo_ts_row *row, int right,
                     int index) {
    const double mc = right ? s->rmc : s->lmc;
    const int inner = (index != 0) && (index < row->length - 1);
    if (!(inner && pl_fabs(pl_alo_ts_abscissa(row, index + 1)) > mc)) {
        return 0;
    }
    double yp = 0.0;
    double ym = 0.0;
    if (end_at(s, row, right, index, &yp) != 0) {
        return 1;
    }
    yp = yp * pl_alo_ts_weight(row, index);
    if (end_at(s, row, right, index - 1, &ym) != 0) {
        return 1;
    }
    ym = ym * pl_alo_ts_weight(row, index - 1);
    if (pl_fabs(yp) > pl_fabs(ym)) {
        return pl_alo_fail(s->run, PL_ENGINE_QL_ERROR); /* increasing at the new end */
    }
    return 0;
}
