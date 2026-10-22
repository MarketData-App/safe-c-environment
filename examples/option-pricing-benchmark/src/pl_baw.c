/* Transcribed from QuantLib 1.43 (QL_VERSION 1.43; retained source
 * benchmarks/project/third_party/sources/QuantLib-1.43.tar.gz, sha256
 * b41206ccc4ba39b5e86bdc940d51138222b352f79d2c6fc68649f9c9bbe58701), via optionlab/baw.py lines
 * 22-63, optionlab/baw_admit.py lines 127-153, optionlab/models.py lines 478-483 and
 * optionlab/reference.py lines 54-69: ql/pricingengines/vanilla/baroneadesiwhaleyengine.hpp
 * 43-48, ql/pricingengines/vanilla/baroneadesiwhaleyengine.cpp 39-236,
 * ql/pricingengines/blackcalculator.cpp 65-75 (the BlackCalculator checks; its value and greeks
 * through pl_black.c). QuantLib license (BSD-3-Clause): the copyright notices, conditions and
 * disclaimer are in NOTICE-QuantLib.md of this example (LR-EX 2026-10-18). */
#include "pl_baw.h"
#include "pl_black.h"
#include "pl_ieee.h"
#include "pl_normal.h"
#include "pl_types.h"
#include <stddef.h>
#include <stdint.h>

/* The BAW critical price, S*, the engine and the admitted price (specs/project/models.md "BAW
 * (Amendment G)"). Each function copies the cited optionlab function statement by statement
 * (Amendment F item 8). Every division of the engine is models._div or a division inside
 * models._guard, which is IEEE C division. The critical-price loop makes at most newton_max
 * updates; QuantLib has no cap, and the cap hit is the run defect of record R3 (F6). */

double pl_baw_critical_price(int side, double K, double d_r, double d_q, double variance,
                             int newton_max, int *iterations, int *cap_hit, int *ql_error) {
    *iterations = 0;
    if (!(d_r <= 1.0)) {
        *ql_error = 1; /* QL_REQUIRE of lines 45-48 */
        return pl_nan();
    }
    struct pl_baw_seed s;
    pl_baw_seed(side, K, d_r, d_q, variance, &s);
    const double q = pl_baw_qexp(side, s.n, pl_baw_kcoef(d_r, variance));
    double si = s.Si;
    double lhs = 0.0;
    double rhs = 0.0;
    double bi = 0.0;
    if (pl_baw_map(side, si, K, d_r, d_q, variance, q, &lhs, &rhs, &bi) != 0) {
        *ql_error = 1; /* blackFormula check at line 87 */
        return pl_nan();
    }
    for (int count = 0; !pl_baw_stop(lhs, rhs, K); count++) {
        if (count >= newton_max) {
            *cap_hit = 1; /* BawRunDefect('baw-cap') */
            return pl_nan();
        }
        si = pl_baw_update(side, si, K, rhs, bi);
        *iterations = count + 1;
        if (pl_baw_map(side, si, K, d_r, d_q, variance, q, &lhs, &rhs, &bi) != 0) {
            *ql_error = 1; /* blackFormula check at line 103 or 125 */
            return pl_nan();
        }
    }
    return si;
}

enum pl_engine_status pl_baw_sstar(int side, double K, double d_r, double d_q, double variance,
                                   int newton_max, int plant, double *sstar, int *iterations) {
    int cap_hit = 0;
    int ql_error = 0;
    double sk = pl_baw_critical_price(side, K, d_r, d_q, variance, newton_max, iterations, &cap_hit,
                                      &ql_error);
    *sstar = pl_nan();
    if (ql_error != 0) {
        return PL_ENGINE_QL_ERROR;
    }
    if (cap_hit != 0) {
        return PL_ENGINE_PY_DEFECT;
    }
    if (plant != 0) {
        sk = pl_nan(); /* the test-only planted non-finite S* (G2.3, AG3-08) */
    }
    if (!pl_is_finite(sk)) {
        return PL_ENGINE_PY_DEFECT; /* BawRunDefect('baw-nonfinite-sstar') */
    }
    *sstar = sk;
    return PL_ENGINE_OK;
}

/* Every member pl_nan(). */
static void all_nan(struct pl_engine_result *out) {
    const double nan = pl_nan();
    out->value = nan;
    out->delta = nan;
    out->gamma = nan;
    out->theta = nan;
    out->vega = nan;
    out->rho = nan;
    out->dividend_rho = nan;
    out->strike_sensitivity = nan;
    out->strike_gamma = nan;
}

/* The checks of line 162 and of BlackCalculator::initialize (baw.py:39, 22-27): 1 when one
 * fails (ModelDefect, order 5). */
static int engine_checks(double S, double K, double forward, double sd, double d_r) {
    if (!(S > 0.0)) {
        return 1; /* "negative or null underlying given" */
    }
    if (!(K >= 0.0) || !(forward > 0.0)) {
        return 1;
    }
    return !(sd >= 0.0) || !(d_r > 0.0);
}

/* The American branch value of lines 201-229 (baw.py:49-63) at S* sk. */
static double american_value(int side, double S, double K, double d_r, double d_q, double variance,
                             double sk, const struct pl_black *black) {
    const double forward_sk = sk * d_q / d_r;
    const double d1 = (pl_log(forward_sk / K) + 0.5 * variance) / pl_sqrt(variance);
    const double n = 2.0 * pl_log(d_q / d_r) / variance;
    const double kc = pl_baw_kcoef(d_r, variance);
    if (side == 0) {
        const double q = (-(n - 1.0) + pl_sqrt(((n - 1.0) * (n - 1.0)) + 4.0 * kc)) / 2.0;
        const double a = sk / q * (1.0 - d_q * pl_norm_cdf(d1));
        if (S < sk) {
            return pl_black_value(black) + a * pl_pow(S / sk, q);
        }
        return S - K;
    }
    const double q = (-(n - 1.0) - pl_sqrt(((n - 1.0) * (n - 1.0)) + 4.0 * kc)) / 2.0;
    const double a = -(sk / q) * (1.0 - d_q * pl_norm_cdf(-d1));
    if (S > sk) {
        return pl_black_value(black) + a * pl_pow(S / sk, q);
    }
    return K - S;
}

enum pl_engine_status pl_baw_engine(int side, double S, double K, double d_r, double d_q,
                                    double variance, int greeks, const struct pl_params *p,
                                    struct pl_engine_result *out, int *iterations) {
    all_nan(out);
    *iterations = 0;
    const double forward_price = S * d_q / d_r;
    const double sd = pl_sqrt(variance);
    if (engine_checks(S, K, forward_price, sd, d_r) != 0) {
        return PL_ENGINE_QL_ERROR;
    }
    struct pl_black black;
    pl_black_init(&black, side, K, forward_price, sd, d_r);
    if (d_q >= 1.0 && side == 0) { /* line 167: the European results of lines 169-191 */
        out->value = pl_black_value(&black);
        if (greeks != 0) {
            out->delta = pl_black_delta(&black, S);
            out->gamma = pl_black_gamma(&black, S);
            out->rho = pl_black_rho(&black, 1.0);
            out->dividend_rho = pl_black_dividend_rho(&black, 1.0);
            out->vega = pl_black_vega(&black, 1.0);
            out->theta = pl_black_theta(&black, S, 1.0);
        }
        return PL_ENGINE_OK;
    }
    double sk = 0.0;
    const enum pl_engine_status st = pl_baw_sstar(side, K, d_r, d_q, variance, p->baw_newton_max,
                                                  p->baw_plant_nonfinite_sstar, &sk, iterations);
    if (st != PL_ENGINE_OK) {
        return st;
    }
    out->value = american_value(side, S, K, d_r, d_q, variance, sk, &black);
    return PL_ENGINE_OK;
}

enum pl_engine_status pl_baw_result(int side, double S, double K, double T, double r, double q,
                                    double sigma, int greeks, const struct pl_params *p,
                                    struct pl_engine_result *out, int *iterations) {
    double d_r = 0.0;
    double d_q = 0.0;
    double variance = 0.0;
    int defect = 0;
    pl_mapped_inputs(T, r, q, sigma, &d_r, &d_q, &variance, &defect);
    if (defect != 0) {
        all_nan(out);
        *iterations = 0;
        return PL_ENGINE_PY_DEFECT; /* mapped_inputs runs before models._guard */
    }
    return pl_baw_engine(side, S, K, d_r, d_q, variance, greeks, p, out, iterations);
}

enum pl_engine_status pl_baw_price(int side, double S, double K, double T, double r, double q,
                                   double sigma, const struct pl_params *p, double *value,
                                   uint8_t *flags) {
    *value = pl_nan();
    double r1 = 0.0;
    double q1 = 0.0;
    double s1 = 0.0;
    pl_unit(T, r, q, sigma, &r1, &q1, &s1);
    struct pl_baw_admit a;
    pl_baw_admit(side, S, K, r1, q1, s1 * s1 * 1.0, &a);
    if (a.defect != 0) {
        return PL_ENGINE_PY_DEFECT;
    }
    if (a.in_scope != 0 && a.admitted == 0) {
        *flags = (uint8_t)(*flags | PL_FLAG_ADMIT_EXCLUDED); /* AdmitExcluded: order 5, bit 64 */
        return PL_ENGINE_QL_ERROR;
    }
    struct pl_engine_result e;
    int iterations = 0;
    const enum pl_engine_status st =
        pl_baw_result(side, S, K, T, r, q, sigma, 0, p, &e, &iterations);
    if (st == PL_ENGINE_OK) {
        *value = e.value;
    }
    return st;
}
