/* Transcribed from QuantLib 1.43 (QL_VERSION 1.43; retained source
 * benchmarks/project/third_party/sources/QuantLib-1.43.tar.gz, sha256
 * b41206ccc4ba39b5e86bdc940d51138222b352f79d2c6fc68649f9c9bbe58701), via optionlab/baw_admit.py
 * lines 40-125: ql/pricingengines/vanilla/baroneadesiwhaleyengine.cpp 39-138,
 * ql/pricingengines/blackformula.cpp 40-54, 59-98, ql/pricingengines/blackformula.hpp 46-51,
 * ql/math/comparison.hpp 78-90, ql/termstructures/yield/flatforward.hpp 102-105,
 * ql/interestrate.hpp 69-71, ql/interestrate.cpp 53-54. QuantLib license (BSD-3-Clause): the
 * copyright notices, conditions and disclaimer are in NOTICE-QuantLib.md of this example (LR-EX
 * 2026-10-18). */
#include "pl_baw.h"
#include "pl_ieee.h"
#include "pl_normal.h"
#include "pl_types.h"
#include <stddef.h>

/* The map of the BAW critical-price iteration and its parts: the discounts, close(x, y, n),
 * blackFormula, the seed, the coefficient K, Q, the stop test and the update
 * (specs/project/models.md "BAW (Amendment G)"). Each function copies the cited optionlab
 * function statement by statement (Amendment F item 8, N1a). Every division is models._div,
 * which is IEEE C division; a Python integer literal is the equal double literal. Its own
 * translation unit: baw_admit (pl_baw_admit.c) and the certificate (pl_baw_cert.c) call these
 * functions as opaque calls, which keeps each file within the fixed GCC analyzer budget. */

/* baw_admit.TOL: the tolerance 1e-6 of baroneadesiwhaleyengine.cpp:198. */
static const double PL_BAW_TOL = 0x1.0c6f7a0b5ed8dp-20;

void pl_baw_discounts(double r1, double q1, double *d_r, double *d_q) {
    *d_r = 1.0 / pl_exp(r1 * 1.0);
    *d_q = 1.0 / pl_exp(q1 * 1.0);
}

int pl_baw_close_n(double x, double y, double n) {
    if (x == y) {
        return 1;
    }
    const double diff = pl_fabs(x - y);
    const double tolerance = n * PL_QL_EPSILON;
    if (x == 0.0 || y == 0.0) {
        return diff < (tolerance * tolerance);
    }
    return diff <= tolerance * pl_fabs(x) && diff <= tolerance * pl_fabs(y);
}

/* The checks of displacement (0.0 >= 0.0) and discount (1.0 > 0.0) always pass and are left
 * out; the others keep the Python order. */
int pl_baw_black_formula(int side, double strike, double forward, double std_dev, double *value) {
    const double displacement = 0.0;
    const double discount = 1.0;
    if (!(strike + displacement >= 0.0)) {
        return 1;
    }
    if (!(forward + displacement > 0.0)) {
        return 1;
    }
    if (!(std_dev >= 0.0)) {
        return 1;
    }
    const double sign = (side == 0) ? 1.0 : -1.0;
    if (std_dev == 0.0) {
        *value = pl_max((forward - strike) * sign, 0.0) * discount;
        return 0;
    }
    forward = forward + displacement;
    strike = strike + displacement;
    if (strike == 0.0) {
        *value = (side == 0) ? forward * discount : 0.0;
        return 0;
    }
    const double d1 = pl_log(forward / strike) / std_dev + 0.5 * std_dev;
    const double d2 = d1 - std_dev;
    const double nd1 = pl_norm_cdf(sign * d1);
    const double nd2 = pl_norm_cdf(sign * d2);
    const double result = (discount * sign) * (forward * nd1 - strike * nd2);
    if (!(result >= 0.0)) {
        return 1; /* QL_ENSURE "negative value", blackformula.cpp:91-96 */
    }
    *value = result;
    return 0;
}

void pl_baw_seed(int side, double K, double d_r, double d_q, double variance,
                 struct pl_baw_seed *out) {
    const double n = 2.0 * pl_log(d_q / d_r) / variance;
    const double m = -2.0 * pl_log(d_r) / variance;
    const double bt = pl_log(d_q / d_r);
    out->n = n;
    out->m = m;
    out->bT = bt;
    if (side == 0) {
        const double qu = (-(n - 1.0) + pl_sqrt(((n - 1.0) * (n - 1.0)) + 4.0 * m)) / 2.0;
        const double su = K / (1.0 - 1.0 / qu);
        const double h = -(bt + 2.0 * pl_sqrt(variance)) * K / (su - K);
        out->qu = qu;
        out->Su = su;
        out->h = h;
        out->Si = K + (su - K) * (1.0 - pl_exp(h));
        return;
    }
    const double qu = (-(n - 1.0) - pl_sqrt(((n - 1.0) * (n - 1.0)) + 4.0 * m)) / 2.0;
    const double su = K / (1.0 - 1.0 / qu);
    const double h = (bt - 2.0 * pl_sqrt(variance)) * K / (K - su);
    out->qu = qu;
    out->Su = su;
    out->h = h;
    out->Si = su + (K - su) * pl_exp(h);
}

double pl_baw_kcoef(double d_r, double variance) {
    if (!pl_baw_close_n(d_r, 1.0, 1000.0)) {
        return -2.0 * pl_log(d_r) / (variance * (1.0 - d_r));
    }
    return 2.0 / variance;
}

double pl_baw_qexp(int side, double n, double kc) {
    if (side == 0) {
        return (-(n - 1.0) + pl_sqrt(((n - 1.0) * (n - 1.0)) + 4.0 * kc)) / 2.0;
    }
    return (-(n - 1.0) - pl_sqrt(((n - 1.0) * (n - 1.0)) + 4.0 * kc)) / 2.0;
}

int pl_baw_map(int side, double si, double K, double d_r, double d_q, double variance, double Q,
               double *lhs, double *rhs, double *bi) {
    const double forward_si = si * d_q / d_r;
    const double sd = pl_sqrt(variance);
    const double d1 = (pl_log(forward_si / K) + 0.5 * variance) / sd;
    double black = 0.0;
    if (pl_baw_black_formula(side, K, forward_si, sd, &black) != 0) {
        return 1; /* raised before LHS, RHS and bi are assigned (record R2) */
    }
    const double temp = black * d_r;
    if (side == 0) {
        const double nd1 = pl_norm_cdf(d1);
        *lhs = si - K;
        *rhs = temp + (1.0 - d_q * nd1) * si / Q;
        *bi = d_q * nd1 * (1.0 - 1.0 / Q) + (1.0 - d_q * pl_norm_pdf(d1) / sd) / Q;
        return 0;
    }
    const double nd1 = pl_norm_cdf(-d1);
    *lhs = K - si;
    *rhs = temp - (1.0 - d_q * nd1) * si / Q;
    *bi = (-d_q) * nd1 * (1.0 - 1.0 / Q) - (1.0 + d_q * pl_norm_pdf(-d1) / sd) / Q;
    return 0;
}

int pl_baw_stop(double lhs, double rhs, double K) { return !(pl_fabs(lhs - rhs) / K > PL_BAW_TOL); }

double pl_baw_update(int side, double si, double K, double rhs, double bi) {
    if (side == 0) {
        return (K + rhs - bi * si) / (1.0 - bi);
    }
    return (K - rhs + bi * si) / (1.0 + bi);
}
