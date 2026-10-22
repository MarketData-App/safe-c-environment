/* Transcribed from QuantLib 1.43 (QL_VERSION 1.43; retained source
 * benchmarks/project/third_party/sources/QuantLib-1.43.tar.gz, sha256
 * b41206ccc4ba39b5e86bdc940d51138222b352f79d2c6fc68649f9c9bbe58701), via optionlab/alo.py
 * lines 480-551, 569-574 (merged G-ALO2 part B, commit 567f6c4): ql/pricingengines/vanilla/
 * qdfpamericanengine.cpp 119-158 (DqFpEquation, d), 198-309 (FP-A f and NDd, Legendre path),
 * 311-400 (FP-B f and NDd, Legendre path), 444-450 (B(tau)); ql/mathconstants.hpp 74, 86, 94, 98
 * (spec Appendix I-ALO R2, R5, R7). QuantLib license (BSD-3-Clause): the copyright notices,
 * conditions and disclaimer are in NOTICE-QuantLib.md of this example (LR-EX 2026-10-18). */
#include "pl_alo.h"
#include "pl_alo_step.h"
#include "pl_ieee.h"
#include "pl_normal.h"
#include "pl_types.h"
#include <stddef.h>

/* The fixed-point equations FP-A and FP-B on the frozen 25-point Gauss-Legendre table
 * (specs/project/models.md "ALO (Amendment I)"), copied from optionlab.alo.FpEquation statement
 * by statement. Both Legendre sums run in reverse node order, i = 24 down to 0
 * (qdfpamericanengine.cpp:221, 337; record R2, ALO1-07). Every division is models._div (IEEE C
 * division). The tiny-tau branches (tau < QL_EPSILON^2) are kept with QuantLib's semantics; record
 * R7 shows that no node time reaches them on the mapped problem. */

/* Guard-only branches (ruling R-10c, T10B-COV-FP-01). No input of the engine domain reaches them;
 * none is excluded from coverage:
 * - each tau < QL_EPSILON^2 branch of fp_a, fp_b and pl_alo_fp_ndd, and sign_of_q. The engine
 *   solves the mapped problem at T' = 1.0 (pl_alo_engine has no T input). pl_alo_fp_f and
 *   pl_alo_fp_ndd run only from node_value (src/pl_alo_node.c) at the node times x_i^2, x_i =
 *   0.5 (1 + z_i), z_i = -cos(i pi / 13), i = 1 ... 13 (the sweep skips node 0). The smallest
 *   node time is about 2.1e-4.
 * - the status test in the Legendre loops of fp_a and fp_b, and the status test after them in
 *   pl_alo_fp_f. There pl_alo_fp_boundary fails only for a non-finite interpolant value. The
 *   sweep checks that every node value is finite, and the argument lies in [-1, 1]. A planted
 *   NaN at cpp:448 fires at the first boundary call of the evaluation, which is in node_value,
 *   before any Legendre point.
 * - the second check of pl_alo_fp_boundary: b = xmax exp(-sqrt(max(0, iv))) with a finite iv,
 *   and 0 <= xmax <= K (xMax), with K finite (the pre check). */

/* mathconstants.hpp M_SQRT2 (94) and M_SQRTPI (74) as alo.py writes them; M_1_SQRTPI and
 * M_SQRT_2 are PL_M_1_SQRTPI and PL_M_SQRT_2 of pl_types.h. */
#define PL_ALO_M_SQRT2 1.41421356237309504880
#define PL_ALO_M_SQRTPI 1.77245385090551602792981

/* FpEquation.d (alo.py:484-486): (m, m - v) with v = vol sqrt(t). */
static void fp_d(const struct pl_alo_fp *e, double t, double z, double *d1, double *d2) {
    const double v = e->vol * pl_sqrt(t);
    const double m = (pl_log(z) + (e->r - e->q) * t) / v + 0.5 * v;
    *d1 = m;
    *d2 = m - v;
}

double pl_alo_fp_boundary(struct pl_alo_fp *e, double tau) {
    struct pl_alo_run *run = e->run;
    const double zz = 2.0 * pl_sqrt(pl_fabs(tau) / e->T) - 1.0;
    double iv = pl_alo_cheb_value(e->interp, zz, run);
    iv = pl_alo_mask(run, PL_ALO_SITE_CPP_448, iv);
    if (pl_alo_check(run, PL_ALO_CHECK_POST_BOUNDARY, &iv, 1u) != 0) {
        return pl_nan();
    }
    double b = e->xmax * pl_exp(-pl_sqrt(pl_max(0.0, iv)));
    if (pl_alo_check(run, PL_ALO_CHECK_POST_BOUNDARY, &b, 1u) != 0) {
        return pl_nan();
    }
    return b;
}

/* The sign factor of the tiny-tau fv (alo.py:507, 527): -1.0 for q < 0, else 1.0. */
static double sign_of_q(double q) { return (q < 0.0) ? -1.0 : 1.0; }

/* FP-A f (alo.py:489-509). */
static void fp_a(struct pl_alo_fp *e, double tau, double b, double *N, double *D, double *fv) {
    const double K = e->K;
    const double r = e->r;
    const double q = e->q;
    const double v = e->vol * pl_sqrt(tau);
    if (tau < PL_QL_EPSILON * PL_QL_EPSILON) {
        if (pl_alo_close_enough(b, K)) {
            *N = 1.0 / (PL_ALO_M_SQRT2 * PL_ALO_M_SQRTPI * v);
            *D = *N + 0.5;
        } else {
            *N = 0.0;
            *D = (b > K) ? 1.0 : 0.0;
        }
    } else {
        const double stv = pl_sqrt(tau) / e->vol;
        double k12 = 0.0;
        double k3 = 0.0;
        for (int i = PL_ALO_GL_ORDER - 1; i >= 0; i--) {
            const double y = pl_alo_gl_node(i);
            const double m = 0.25 * tau * ((1.0 + y) * (1.0 + y));
            const double bb = pl_alo_fp_boundary(e, tau - m);
            if (e->run->status != PL_ENGINE_OK) {
                return;
            }
            e->run->trace->legendre_points += 1u;
            double d1 = 0.0;
            double d2 = 0.0;
            fp_d(e, m, b / bb, &d1, &d2);
            const double w = pl_alo_gl_weight(i);
            const double part = 0.5 * tau * (y + 1.0) * pl_norm_cdf(d1) + stv * pl_norm_pdf(d1);
            k12 += w * pl_exp(q * tau - q * m) * part;
            k3 += w * stv * pl_exp(r * tau - r * m) * pl_norm_pdf(d2);
        }
        double d1 = 0.0;
        double d2 = 0.0;
        fp_d(e, tau, b / K, &d1, &d2);
        *N = pl_norm_pdf(d2) / v + r * k3;
        *D = pl_norm_pdf(d1) / v + pl_norm_cdf(d1) + q * k12;
    }
    const double alpha = K * pl_exp(-(r - q) * tau);
    if (tau < PL_QL_EPSILON * PL_QL_EPSILON) {
        if (pl_alo_close_enough(b, K)) {
            *fv = alpha;
        } else if (b > K) {
            *fv = 0.0;
        } else if (pl_alo_close_enough(q, 0.0)) {
            *fv = alpha * r * sign_of_q(q) / PL_QL_EPSILON;
        } else {
            *fv = alpha * r / q;
        }
    } else {
        *fv = alpha * *N / *D;
    }
}

/* FP-B f (alo.py:510-529). */
static void fp_b(struct pl_alo_fp *e, double tau, double b, double *N, double *D, double *fv) {
    const double K = e->K;
    const double r = e->r;
    const double q = e->q;
    if (tau < PL_QL_EPSILON * PL_QL_EPSILON) {
        if (pl_alo_close_enough(b, K)) {
            *N = 0.5;
            *D = 0.5;
        } else if (b < K) {
            *N = 0.0;
            *D = 0.0;
        } else {
            *N = 1.0;
            *D = 1.0;
        }
    } else {
        const double c = 0.5 * tau;
        double ni = 0.0;
        double di = 0.0;
        for (int i = PL_ALO_GL_ORDER - 1; i >= 0; i--) {
            const double u = c * pl_alo_gl_node(i) + c;
            const double bb = pl_alo_fp_boundary(e, u);
            if (e->run->status != PL_ENGINE_OK) {
                return;
            }
            e->run->trace->legendre_points += 1u;
            double d1 = 0.0;
            double d2 = 0.0;
            fp_d(e, tau - u, b / bb, &d1, &d2);
            const double w = pl_alo_gl_weight(i);
            ni += w * pl_exp(r * u) * pl_norm_cdf(d2);
            di += w * pl_exp(q * u) * pl_norm_cdf(d1);
        }
        ni *= c;
        di *= c;
        double d1 = 0.0;
        double d2 = 0.0;
        fp_d(e, tau, b / K, &d1, &d2);
        *N = pl_norm_cdf(d2) + r * ni;
        *D = pl_norm_cdf(d1) + q * di;
    }
    const double alpha = K * pl_exp(-(r - q) * tau);
    if (tau < PL_QL_EPSILON * PL_QL_EPSILON) {
        if (pl_alo_close_enough(b, K) || b > K) {
            *fv = alpha;
        } else if (pl_alo_close_enough(q, 0.0)) {
            *fv = alpha * r * sign_of_q(q) / PL_QL_EPSILON;
        } else {
            *fv = alpha * r / q;
        }
    } else {
        *fv = alpha * *N / *D;
    }
}

void pl_alo_fp_f(struct pl_alo_fp *e, double tau, double b, double *N, double *D, double *fv) {
    struct pl_alo_run *run = e->run;
    e->f_calls += 1;
    run->trace->sweep_f += 1;
    const double nan = pl_nan();
    *N = nan;
    *D = nan;
    *fv = nan;
    if (e->kind == PL_ALO_FP_A) {
        fp_a(e, tau, b, N, D, fv);
    } else {
        fp_b(e, tau, b, N, D, fv);
    }
    if (run->status != PL_ENGINE_OK) {
        return;
    }
    double vals[3];
    *(vals + 0) = pl_alo_mask(run, PL_ALO_SITE_CPP_N, *N);
    *(vals + 1) = pl_alo_mask(run, PL_ALO_SITE_CPP_D, *D);
    *(vals + 2) = pl_alo_mask(run, PL_ALO_SITE_CPP_FV, *fv);
    *N = *(vals + 0);
    *D = *(vals + 1);
    *fv = *(vals + 2);
    pl_alo_check(run, PL_ALO_CHECK_POST_SWEEP, vals, 3u);
}

void pl_alo_fp_ndd(struct pl_alo_fp *e, double tau, double b, double *Nd, double *Dd) {
    struct pl_alo_run *run = e->run;
    e->ndd_calls += 1;
    run->trace->sweep_ndd += 1;
    const double K = e->K;
    const double vol = e->vol;
    double d1 = 0.0;
    double d2 = 0.0;
    if (e->kind == PL_ALO_FP_A) {
        if (tau < PL_QL_EPSILON * PL_QL_EPSILON) {
            if (pl_alo_close_enough(b, K)) {
                const double sq_tau = pl_sqrt(tau);
                const double vol2 = vol * vol;
                const double den = b * vol * vol2 * sq_tau;
                const double c = PL_M_1_SQRTPI * PL_M_SQRT_2;
                *Dd = c * (-(0.5 * vol2 + e->r - e->q) / den + 1.0 / (b * vol * sq_tau));
                *Nd = c * (-0.5 * vol2 + e->r - e->q) / den;
            } else {
                *Dd = 0.0;
                *Nd = 0.0;
            }
        } else {
            fp_d(e, tau, b / K, &d1, &d2);
            const double phi1 = pl_norm_pdf(d1);
            *Dd = -phi1 * d1 / (b * vol * vol * tau) + phi1 / (b * vol * pl_sqrt(tau));
            *Nd = -pl_norm_pdf(d2) * d2 / (b * vol * vol * tau);
        }
    } else {
        fp_d(e, tau, b / K, &d1, &d2);
        *Nd = pl_norm_pdf(d2) / (b * vol * pl_sqrt(tau));
        *Dd = pl_norm_pdf(d1) / (b * vol * pl_sqrt(tau));
    }
    double vals[2];
    *(vals + 0) = pl_alo_mask(run, PL_ALO_SITE_CPP_NDD, *Nd);
    *(vals + 1) = *Dd;
    *Nd = *(vals + 0);
    pl_alo_check(run, PL_ALO_CHECK_POST_SWEEP, vals, 2u);
}
