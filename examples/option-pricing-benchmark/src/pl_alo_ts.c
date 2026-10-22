/* Transcribed from QuantLib 1.43 (QL_VERSION 1.43; retained source
 * benchmarks/project/third_party/sources/QuantLib-1.43.tar.gz, sha256
 * b41206ccc4ba39b5e86bdc940d51138222b352f79d2c6fc68649f9c9bbe58701), via optionlab/alo.py
 * lines 207-243, 303-330 (merged G-ALO2 part B, commit 567f6c4): ql/math/integrals/
 * tanhsinhintegral.hpp 41-70, ql/math/integrals/integral.cpp 76-86 (spec Appendix I-ALO R2).
 * QuantLib license (BSD-3-Clause): the copyright notices, conditions and disclaimer are in
 * NOTICE-QuantLib.md of this example (LR-EX 2026-10-18). */
/* Transcribed from Boost 1.90.0 (retained sources under benchmarks/project/third_party/sources/,
 * provenance benchmarks/project/third_party/provenance/boost-source.json): boost/math/quadrature/
 * tanh_sinh.hpp and its listed include closure, via optionlab/alo.py lines 207-243, 303-330:
 * boost/math/quadrature/tanh_sinh.hpp 155-223 (integrate for finite a < b, the integrand map),
 * boost/math/quadrature/detail/tanh_sinh_detail.hpp 190-325 (row 0 and the ends),
 * boost/math/special_functions/next.hpp (float_next, float_prior), boost/math/tools/precision.hpp
 * (epsilon, min_value), boost/math/constants/constants.hpp 274 (half_pi),
 * boost/math/policies/policy.hpp and boost/math/policies/error_handling.hpp (evaluation_error).
 * Copyright lines: tanh_sinh.hpp, tanh_sinh_detail.hpp: Copyright Nick Thompson, 2017. next.hpp:
 * (C) Copyright John Maddock 2008. precision.hpp: Copyright John Maddock 2005-2006. constants.hpp:
 * Copyright John Maddock 2005-2006, 2011. Copyright Paul A. Bristow 2006-2011. Copyright Matt
 * Borland 2024. policy.hpp: Copyright John Maddock 2007. Copyright Matt Borland 2021.
 * error_handling.hpp: Copyright John Maddock 2007. Copyright Paul A. Bristow 2007. Copyright Matt
 * Borland 2024. Boost Software License 1.0 (the text is in
 * examples/option-pricing-benchmark/NOTICE-QuantLib.md and in the retained LICENSE_1_0.txt).
 * License review: LR-EX 2026-10-18 (agent engineering review). */
#include "pl_alo.h"
#include "pl_alo_step.h"
#include "pl_ieee.h"
#include "pl_types.h"
#include <float.h>
#include <math.h>
#include <stddef.h>
#include <stdint.h>

/* The final integral of the ALO engine (specs/project/models.md "ALO (Amendment I)"):
 * Integrator::operator() and TanhSinhIntegral::integrate (0 for a == b; the error is stored and
 * never checked) over Boost tanh_sinh<double>::integrate, copied from optionlab.alo
 * (tanh_sinh_integrate and TanhSinhDetail.integrate) statement by statement. Row 0 is in
 * src/pl_alo_ts_row0.c and the level loop in src/pl_alo_ts_level.c. A Boost evaluation_error is
 * PL_ENGINE_QL_ERROR (order 5, record R8); the integrand's own run defects end the integral at
 * once. An index outside a row (a Python IndexError, unreachable) is a Python raise. Every loop is
 * bounded by a row length or by the level cap. */

/* tanh_sinh_detail: t_max / initial row length = 6.0 / 6. */
#define PL_ALO_TS_T_MAX 6.0
#define PL_ALO_TS_INITIAL_ROW_LENGTH 6

/* g(x) of alo.tanh_sinh_integrate (alo.py:308-309): the count, then the integrand. */
static double ts_g(struct pl_alo_ts_map *m, double x) {
    m->n += 1u;
    return pl_alo_addon_value(m->g, x);
}

double pl_alo_ts_u(struct pl_alo_ts_map *m, double z, double zc) {
    double position = 0.0;
    if (z < -0.5) {
        if (m->have_small_left) {
            return ts_g(m, m->diff * (m->avg_over_diff_m1 - zc));
        }
        position = m->a - m->diff * zc;
    } else if (z > 0.5) {
        if (m->have_small_right) {
            return ts_g(m, m->diff * (m->avg_over_diff_p1 - zc));
        }
        position = m->b - m->diff * zc;
    } else {
        position = m->avg + m->diff * z;
    }
    return ts_g(m, position);
}

double pl_alo_ts_integrate(const struct pl_alo_addon *g, double a, double b, double tolerance,
                           int *levels, uint32_t *evaluations) {
    if (a == b) {
        *levels = 0;
        *evaluations = 0u;
        return 0.0;
    }
    double sign = 1.0;
    if (b < a) { /* tanh_sinh_integrate(f, b, a): -v (the one recursion of alo.py:311-312) */
        const double t = a;
        a = b;
        b = t;
        sign = -1.0;
    }
    struct pl_alo_ts_map m;
    m.g = g;
    m.a = a;
    m.b = b;
    m.avg = (a + b) * 0.5;
    m.diff = (b - a) * 0.5;
    m.avg_over_diff_m1 = a / m.diff;
    m.avg_over_diff_p1 = b / m.diff;
    m.have_small_left = pl_fabs(a) < 0.5;
    m.have_small_right = pl_fabs(b) < 0.5;
    m.n = 0u;
    double left_min_complement = nextafter(m.avg_over_diff_m1, pl_inf()) - m.avg_over_diff_m1;
    const double min_complement_limit = pl_max(DBL_MIN, nextafter(DBL_MIN / m.diff, pl_inf()));
    if (left_min_complement < min_complement_limit) {
        left_min_complement = min_complement_limit;
    }
    double right_min_complement = m.avg_over_diff_p1 - nextafter(m.avg_over_diff_p1, -pl_inf());
    if (right_min_complement < min_complement_limit) {
        right_min_complement = min_complement_limit;
    }
    struct pl_alo_ts_state s;
    s.map = &m;
    s.run = g->run;
    s.lmc = left_min_complement;
    s.rmc = right_min_complement;
    s.tolerance = tolerance;
    s.tail_tolerance = 0.0;
    s.crossover = pl_alo_ts_crossover();
    s.h = PL_ALO_TS_T_MAX / (double)PL_ALO_TS_INITIAL_ROW_LENGTH;
    s.I0 = 0.0;
    s.I1 = 0.0;
    s.L1_I0 = 0.0;
    s.L1_I1 = 0.0;
    s.err = 0.0;
    s.max_left_position = 0;
    s.max_right_position = 0;
    s.k = 1;
    s.thrash_count = 0;
    s.done = 0;
    struct pl_alo_run *run = g->run;
    if (pl_alo_ts_row0(&s) != 0) { /* row 0 (alo.py:211-242; src/pl_alo_ts_row0.c) */
        return pl_nan();
    }
    s.I1 = s.I0;
    s.L1_I1 = s.L1_I0;
    /* while k < 4 or (k < nrows and k < max_refinements): nrows = 16, max_refinements = 15 */
    for (int pass = 0; pass < PL_ALO_TS_MAX_REFINEMENTS; pass++) {
        if (!(s.k < 4 || (s.k < PL_ALO_TS_ROWS && s.k < PL_ALO_TS_MAX_REFINEMENTS))) {
            break;
        }
        pl_alo_ts_level(&s);
        if (run->status != PL_ENGINE_OK) {
            return pl_nan();
        }
        if (s.done) {
            break;
        }
    }
    *levels = s.k;
    *evaluations = m.n;
    return sign * (m.diff * s.I1);
}
