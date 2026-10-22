/* Transcribed from QuantLib 1.43 (QL_VERSION 1.43; retained source
 * benchmarks/project/third_party/sources/QuantLib-1.43.tar.gz, sha256
 * b41206ccc4ba39b5e86bdc940d51138222b352f79d2c6fc68649f9c9bbe58701), via optionlab/alo.py
 * lines 243-301 (merged G-ALO2 part B, commit 567f6c4): ql/math/integrals/tanhsinhintegral.hpp
 * 53-65 (the Boost integrator that TanhSinhIntegral wraps; spec Appendix I-ALO R2). QuantLib
 * license (BSD-3-Clause): the copyright notices, conditions and disclaimer are in
 * NOTICE-QuantLib.md of this example (LR-EX 2026-10-18). */
/* Transcribed from Boost 1.90.0 (retained sources under benchmarks/project/third_party/sources/,
 * provenance benchmarks/project/third_party/provenance/boost-source.json): boost/math/quadrature/
 * tanh_sinh.hpp and its listed include closure, via optionlab/alo.py lines 243-301:
 * boost/math/quadrature/detail/tanh_sinh_detail.hpp 326-558 (the level loop, the end retreat, the
 * thrash rule, the stop test and the end sanity check), boost/math/tools/precision.hpp 276-279
 * (root_epsilon), boost/math/policies/policy.hpp and boost/math/policies/error_handling.hpp
 * (evaluation_error). Copyright lines: tanh_sinh_detail.hpp: Copyright Nick Thompson, 2017.
 * precision.hpp: Copyright John Maddock 2005-2006. policy.hpp: Copyright John Maddock 2007.
 * Copyright Matt Borland 2021. error_handling.hpp: Copyright John Maddock 2007. Copyright Paul A.
 * Bristow 2007. Copyright Matt Borland 2024. Boost Software License 1.0 (the text is in
 * examples/option-pricing-benchmark/NOTICE-QuantLib.md and in the retained LICENSE_1_0.txt).
 * License review: LR-EX 2026-10-18 (agent engineering review). */
#include "pl_alo.h"
#include "pl_alo_step.h"
#include "pl_ieee.h"
#include "pl_types.h"
#include <stddef.h>

/* One pass of the level loop of tanh_sinh_detail::integrate (specs/project/models.md "ALO
 * (Amendment I)"), copied from optionlab.alo.TanhSinhDetail.integrate statement by statement:
 * halve, double the end positions, retreat over non-finite end values, sum the row, the error,
 * the thrash rule, the stop test with the end sanity check, the end truncation. Each retreat loop
 * is bounded by the row length; a Boost evaluation_error is PL_ENGINE_QL_ERROR. */

/* boost tools::root_epsilon<double>() (precision.hpp:276-279; alo.ROOT_EPS). */
#define PL_ALO_ROOT_EPS 0.1490116119384765625e-7

/* The row entries, the end retreat and the end sanity check are src/pl_alo_ts_ends.c (opaque
 * calls here: the fixed GCC analyzer budget). */

/* The thrash rule (alo.py:281-288): 1 when the previous level's value is returned. */
static int thrash(struct pl_alo_ts_state *s, double last_err, double endpoint_error, double sum) {
    if (!(s->err * 1.5 > last_err && s->k > 4)) {
        return 0;
    }
    int terminate = 0;
    s->thrash_count += 1;
    if (s->thrash_count > 1 && last_err < 1e-3) {
        terminate = 1;
    } else if (s->thrash_count > 2) {
        terminate = 1;
    } else if (last_err < PL_ALO_ROOT_EPS) {
        terminate = 1;
    } else if (pl_fabs(endpoint_error / sum) > s->err) {
        terminate = 1;
    }
    if (terminate) {
        s->I1 = s->I0;
        s->L1_I1 = s->L1_I0;
        s->k -= 1;
        s->err = last_err + endpoint_error;
    }
    return terminate;
}

void pl_alo_ts_level(struct pl_alo_ts_state *s) {
    struct pl_alo_run *run = s->run;
    s->I0 = s->I1;
    s->L1_I0 = s->L1_I1;
    s->I1 = 0.5 * s->I0;
    s->L1_I1 = 0.5 * s->L1_I0;
    s->h *= 0.5;
    double sum = 0.0;
    double absum = 0.0;
    struct pl_alo_ts_row row;
    row.level = s->k;
    row.crossover = s->crossover;
    if (pl_alo_ts_row_with(row.level, row.crossover, &row.length, &row.fc) != 0) {
        pl_alo_fail(run, PL_ENGINE_PY_DEFECT);
        return;
    }
    int mli = s->max_left_position - 1;
    s->max_left_position *= 2;
    int mri = s->max_right_position - 1;
    s->max_right_position *= 2;
    if (row.length > mli + 1 && pl_fabs(pl_alo_ts_abscissa(&row, mli + 1)) > s->lmc) {
        s->max_left_position += 1;
        mli += 1;
    }
    if (row.length > mri + 1 && pl_fabs(pl_alo_ts_abscissa(&row, mri + 1)) > s->rmc) {
        s->max_right_position += 1;
        mri += 1;
    }
    double yp = 0.0;
    double ym = 0.0;
    if (pl_alo_ts_retreat(s, &row, 0, &s->max_left_position, &mli, &yp) != 0) {
        return;
    }
    const double tail = pl_fabs(s->L1_I1 * s->tail_tolerance);
    const int truncate_left = tail > pl_fabs(yp * pl_alo_ts_weight(&row, mli));
    if (pl_alo_ts_retreat(s, &row, 1, &s->max_right_position, &mri, &ym) != 0) {
        return;
    }
    const int truncate_right = tail > pl_fabs(ym * pl_alo_ts_weight(&row, mri));
    sum += yp * pl_alo_ts_weight(&row, mli) + ym * pl_alo_ts_weight(&row, mri);
    absum += pl_fabs(yp * pl_alo_ts_weight(&row, mli)) + pl_fabs(ym * pl_alo_ts_weight(&row, mri));
    const double endpoint_error = absum;
    /* the row sum (alo.py:270-277; src/pl_alo_ts_sum.c) */
    if (pl_alo_ts_row_sum(s, row.level, row.length, row.fc, mli, mri, &sum, &absum) != 0) {
        return;
    }
    s->I1 += sum * s->h;
    s->L1_I1 += absum * s->h;
    s->k += 1;
    const double last_err = s->err;
    s->err = pl_fabs(s->I0 - s->I1);
    if (!pl_is_finite(s->I1)) {
        pl_alo_fail(run, PL_ENGINE_QL_ERROR); /* singular point (tsd:457-460) */
        return;
    }
    if (thrash(s, last_err, endpoint_error, sum)) {
        s->done = 1;
        return;
    }
    if (s->err <= pl_fabs(s->tolerance * s->L1_I1) && s->k >= 4) {
        if (pl_alo_ts_sanity(s, &row, 0, mli) != 0 || pl_alo_ts_sanity(s, &row, 1, mri) != 0) {
            return;
        }
        s->err += endpoint_error;
        s->done = 1;
        return;
    }
    if (truncate_left && s->max_left_position > 1) {
        s->max_left_position -= 1;
    }
    if (truncate_right && s->max_right_position > 1) {
        s->max_right_position -= 1;
    }
}
