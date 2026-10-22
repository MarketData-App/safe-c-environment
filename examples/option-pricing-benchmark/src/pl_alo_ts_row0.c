/* Transcribed from QuantLib 1.43 (QL_VERSION 1.43; retained source
 * benchmarks/project/third_party/sources/QuantLib-1.43.tar.gz, sha256
 * b41206ccc4ba39b5e86bdc940d51138222b352f79d2c6fc68649f9c9bbe58701), via optionlab/alo.py
 * lines 211-242 (merged G-ALO2 part B, commit 567f6c4): ql/math/integrals/tanhsinhintegral.hpp
 * 53-65 (the Boost integrator that TanhSinhIntegral wraps; spec Appendix I-ALO R2). QuantLib
 * license (BSD-3-Clause): the copyright notices, conditions and disclaimer are in
 * NOTICE-QuantLib.md of this example (LR-EX 2026-10-18). */
/* Transcribed from Boost 1.90.0 (retained sources under benchmarks/project/third_party/sources/,
 * provenance benchmarks/project/third_party/provenance/boost-source.json): boost/math/quadrature/
 * tanh_sinh.hpp and its listed include closure, via optionlab/alo.py lines 211-242:
 * boost/math/quadrature/detail/tanh_sinh_detail.hpp 208-310 (row 0: the end trims, the inward
 * steps and the row sum), boost/math/constants/constants.hpp 274 (half_pi), boost/math/tools/
 * precision.hpp (epsilon). Copyright lines: tanh_sinh_detail.hpp: Copyright Nick Thompson, 2017.
 * constants.hpp: Copyright John Maddock 2005-2006, 2011. Copyright Paul A. Bristow 2006-2011.
 * Copyright Matt Borland 2024. precision.hpp: Copyright John Maddock 2005-2006. Boost Software
 * License 1.0 (the text is in examples/option-pricing-benchmark/NOTICE-QuantLib.md and in the
 * retained LICENSE_1_0.txt). License review: LR-EX 2026-10-18 (agent engineering review). */
#include "pl_alo.h"
#include "pl_alo_step.h"
#include "pl_ieee.h"
#include "pl_types.h"
#include <stdint.h>

/* Row 0 of tanh_sinh_detail::integrate (specs/project/models.md "ALO (Amendment I)"), copied from
 * optionlab.alo.TanhSinhDetail.integrate statement by statement. Its own translation unit, called
 * from src/pl_alo_ts.c as an opaque function, and each running sum of the row loop is pl_sum2
 * (s + t: the same bits as s += t, an opaque result) for the fixed GCC analyzer budget. An index
 * outside the row (a Python IndexError, unreachable) is a Python raise. Every loop is bounded by
 * the row length. */

#define PL_ALO_HALF_PI 1.570796326794896619231321691639751442e+00
/* boost tools::epsilon<double>() (alo.BOOST_EPS = 2**-52). */
#define PL_ALO_BOOST_EPS 0x1p-52

/* One integrand value at row 0 entry `pos` (alo.py:217, 221, 224): the left end
 * f(-1 - A0[pos], A0[pos]) or the right end f(1 + A0[pos], -A0[pos]). Returns 1 on a failure. */
static int end_value(struct pl_alo_ts_state *s, int right, int pos, double *y) {
    double a = 0.0;
    double w = 0.0;
    if (pl_alo_ts_entry_with(0, pos, s->crossover, &a, &w) != 0) {
        return pl_alo_fail(s->run, PL_ENGINE_PY_DEFECT); /* IndexError */
    }
    *y = right ? pl_alo_ts_u(s->map, 1.0 + a, -a) : pl_alo_ts_u(s->map, -1.0 - a, a);
    return s->run->status != PL_ENGINE_OK;
}

/* The weight of row 0 entry pos (NaN outside the row, never reached). */
static double w0(const struct pl_alo_ts_state *s, int pos) {
    double a = 0.0;
    double w = pl_nan();
    if (pl_alo_ts_entry_with(0, pos, s->crossover, &a, &w) != 0) {
        return pl_nan();
    }
    return w;
}

/* The abscissa of row 0 entry pos (NaN outside the row, never reached). */
static double a0(const struct pl_alo_ts_state *s, int pos) {
    double a = pl_nan();
    double w = 0.0;
    if (pl_alo_ts_entry_with(0, pos, s->crossover, &a, &w) != 0) {
        return pl_nan();
    }
    return a;
}

/* One end of row 0 (alo.py:215-230): trim inward while the abscissa complement is below the end
 * complement, evaluate, step inward over non-finite values, then over terms with |y w| <=
 * |L1_I0 tail_tolerance|. Returns 1 on a failure; *position receives the end position. */
static int row0_end(struct pl_alo_ts_state *s, int right, int length, int *position, double *y) {
    const double mc = right ? s->rmc : s->lmc;
    int pos = length - 1;
    while (pos > 1 && pl_fabs(a0(s, pos)) < mc) {
        pos--;
    }
    if (end_value(s, right, pos, y) != 0) {
        return 1;
    }
    *position = pos;
    return 0;
}

/* The inward steps of one end of row 0 (alo.py:219-230). Returns 1 on a failure. */
static int row0_retreat(struct pl_alo_ts_state *s, int right, int *position, double *y) {
    int pos = *position;
    while (pos != 0) {
        if (pl_is_finite(*y)) {
            break;
        }
        pos--;
        if (end_value(s, right, pos, y) != 0) {
            return 1;
        }
    }
    while (pos > 1) {
        if (pl_fabs(*y * w0(s, pos)) > pl_fabs(s->L1_I0 * s->tail_tolerance)) {
            break;
        }
        pos--;
        if (end_value(s, right, pos, y) != 0) {
            return 1;
        }
    }
    *position = pos;
    return 0;
}

int pl_alo_ts_row0(struct pl_alo_ts_state *s) {
    struct pl_alo_run *run = s->run;
    int length = 0;
    int fc = 0;
    if (pl_alo_ts_row_with(0, s->crossover, &length, &fc) != 0) {
        return pl_alo_fail(run, PL_ENGINE_PY_DEFECT);
    }
    s->I0 = PL_ALO_HALF_PI * pl_alo_ts_u(s->map, 0.0, 1.0);
    if (run->status != PL_ENGINE_OK) {
        return 1;
    }
    s->L1_I0 = pl_fabs(s->I0);
    double yp = 0.0;
    double ym = 0.0;
    int mlp = 0;
    int mrp = 0;
    if (row0_end(s, 0, length, &mlp, &yp) != 0 || row0_end(s, 1, length, &mrp, &ym) != 0) {
        return 1;
    }
    s->tail_tolerance = pl_max(PL_ALO_BOOST_EPS, s->tolerance * s->tolerance);
    if (row0_retreat(s, 0, &mlp, &yp) != 0 || row0_retreat(s, 1, &mrp, &ym) != 0) {
        return 1;
    }
    if (mlp == 0 || mrp == 0) {
        return pl_alo_fail(run, PL_ENGINE_QL_ERROR); /* non-finite everywhere (tsd:277-280) */
    }
    s->I0 += yp * w0(s, mlp) + ym * w0(s, mrp);
    s->L1_I0 += pl_fabs(yp * w0(s, mlp)) + pl_fabs(ym * w0(s, mrp));
    for (int i = 1; i < length; i++) {
        if (i >= mrp && i >= mlp) {
            break;
        }
        double x = a0(s, i);
        double xc = x;
        const double w = w0(s, i);
        if ((pl_double_bits(x) >> 63u) != 0u) { /* math.copysign(1.0, x) < 0 */
            x = 1.0 + xc;
        } else {
            xc = x - 1.0;
        }
        double yp2 = 0.0;
        double ym2 = 0.0;
        if (i < mrp) {
            yp2 = pl_alo_ts_u(s->map, x, -xc);
            if (run->status != PL_ENGINE_OK) {
                return 1;
            }
        }
        if (i < mlp) {
            ym2 = pl_alo_ts_u(s->map, -x, xc);
            if (run->status != PL_ENGINE_OK) {
                return 1;
            }
        }
        s->I0 = pl_sum2(s->I0, (yp2 + ym2) * w);
        s->L1_I0 = pl_sum2(s->L1_I0, (pl_fabs(yp2) + pl_fabs(ym2)) * w);
    }
    s->max_left_position = mlp;
    s->max_right_position = mrp;
    return 0;
}
