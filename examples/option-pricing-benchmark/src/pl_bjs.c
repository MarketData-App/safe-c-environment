/* Transcribed from QuantLib 1.43 (QL_VERSION 1.43; retained source
 * benchmarks/project/third_party/sources/QuantLib-1.43.tar.gz, sha256
 * b41206ccc4ba39b5e86bdc940d51138222b352f79d2c6fc68649f9c9bbe58701), via optionlab/models.py lines
 * 39, 246-355, 449: ql/pricingengines/vanilla/bjerksundstenslandengine.cpp 115-506,
 * ql/pricingengines/vanilla/bjerksundstenslandengine.hpp 33. QuantLib license (BSD-3-Clause): the
 * copyright notices, conditions and disclaimer are in NOTICE-QuantLib.md of this example (LR-EX
 * 2026-10-18). */
#include "pl_bjs.h"
#include "pl_black.h"
#include "pl_ieee.h"
#include "pl_types.h"

/* The Bjerksund-Stensland 1993 engine (specs/project/models.md "Bjerksund-Stensland 1993"). Each
 * function copies the cited optionlab function statement by statement (spec 3.4; Amendment F
 * item 8); the phi functions are in pl_bjs_phi.c and BlackCalculator is in pl_black.c (opaque
 * calls here). A Python integer literal is the equal double literal; a dict copy is a struct
 * assignment. A Python sum of terms that would pass the GCC analyzer's fixed symbolic-depth
 * budget goes through pl_sum2, pl_sum3 or pl_sum4 (left to right; a - b as a + (-b), which
 * IEEE-754 defines as the same operation). Every division is IEEE C division: models._guard runs
 * the engine again with IEEE division when the plain run raises ZeroDivisionError, and every
 * engine division has an argument-derived operand in that run. */

/* Actual365Fixed yearFraction(d0, d0 + 365) - yearFraction(d0 + 1, d0 + 365) (models.DT_DAY,
 * models.py:39), computed as Python computes it. */
static const double PL_DT_DAY = 1.0 - 364.0 / 365.0;

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

/* models._european_call (models.py:246-253), europeanCallResults (cpp:115-149) with t = 1.0. */
void pl_bjs_european_call(double S, double X, double rf_d, double d_d, double variance,
                          struct pl_engine_result *out) {
    const double t = 1.0;
    const double forward_price = S * d_d / rf_d;
    struct pl_black black;
    pl_black_init(&black, 0, X, forward_price, pl_sqrt(variance), rf_d);
    out->value = pl_black_value(&black);
    out->delta = pl_black_delta(&black, S);
    out->gamma = pl_black_gamma(&black, S);
    out->rho = pl_black_rho(&black, t);
    out->dividend_rho = pl_black_dividend_rho(&black, t);
    out->vega = pl_black_vega(&black, t);
    out->theta = pl_black_theta(&black, S, t);
    out->strike_sensitivity = pl_black_strike_sensitivity(&black);
    out->strike_gamma = out->gamma * pl_sq(S / X);
}

/* models._immediate (models.py:255-259), immediateExercise (cpp:152-175). */
void pl_bjs_immediate(double S, double X, struct pl_engine_result *out) {
    double delta;
    if (S >= X) {
        delta = 1.0;
    } else {
        delta = 0.0;
    }
    out->value = pl_max(0.0, S - X);
    out->delta = delta;
    out->gamma = 0.0;
    out->rho = 0.0;
    out->dividend_rho = 0.0;
    out->vega = 0.0;
    out->theta = 0.0;
    out->strike_sensitivity = -delta;
    out->strike_gamma = 0.0;
}

/* models._american_call (models.py:261-340), americanCallApproximation (cpp:177-429) with
 * tq = tr = tv = 1.0. Python evaluates sqrt((bT / v - 0.5)^2 + 2 rT / v) in beta (268), as root
 * (287), in beta again (316) and in betaDv (318), and _exp(ht), bT + 2 sqrt(v) and BInfinity - B0
 * several times, always with the same operands; C computes each once (root, exp_ht, bt_2sv,
 * bi_b0). */
void pl_bjs_american_call(double S, double X, double rf_d, double d_d, double variance, int greeks,
                          struct pl_engine_result *out) {
    const double tq = 1.0;
    const double tr = 1.0;
    const double tv = 1.0;
    const double dtq = PL_DT_DAY;
    const double dtr = PL_DT_DAY;
    const double dtv = PL_DT_DAY;
    struct pl_engine_result european;
    pl_bjs_european_call(S, X, rf_d, d_d, variance, &european);
    const double bT = pl_log(d_d / rf_d);
    const double rT = pl_log(1.0 / rf_d);
    const double root = pl_sqrt(pl_sq(bT / variance - 0.5) + 2.0 * rT / variance);
    const double beta = pl_sum2(0.5 - bT / variance, root);
    const double b_infinity = beta / (beta - 1.0) * X;
    double B0;
    if (bT == rT) {
        B0 = X;
    } else {
        B0 = pl_max(X, rT / (rT - bT) * X);
    }
    const double bt_2sv = bT + 2.0 * pl_sqrt(variance);
    const double bi_b0 = b_infinity - B0;
    const double ht = -bt_2sv * B0 / bi_b0;
    const double exp_ht = pl_exp(ht);
    const double I = pl_sum2(B0, bi_b0 * (1.0 - exp_ht));
    const double fwd = S * d_d / rf_d;
    const double q = pl_log(I / fwd) / pl_sqrt(variance);
    struct pl_engine_result results;
    if (S >= I) {
        pl_bjs_immediate(S, X, &results);
    } else if (q > 12.5) {
        results = european;
    } else {
        const double p_sb = pl_bjs_phi(S, beta, I, I, rT, bT, variance);
        const double p_s1ii = pl_bjs_phi(S, 1.0, I, I, rT, bT, variance);
        const double p_s1xi = pl_bjs_phi(S, 1.0, X, I, rT, bT, variance);
        const double p_s0ii = pl_bjs_phi(S, 0.0, I, I, rT, bT, variance);
        const double p_s0xi = pl_bjs_phi(S, 0.0, X, I, rT, bT, variance);
        const double powb = pl_pow(S / I, beta);
        const double value3 = pl_sum3((I - X) * powb * (1.0 - p_sb), S * p_s1ii, -(S * p_s1xi));
        results.value = pl_sum3(value3, -(X * p_s0ii), X * p_s0xi);
        if (greeks == 0) {
            const double nan = pl_nan();
            results.delta = nan;
            results.gamma = nan;
            results.rho = nan;
            results.dividend_rho = nan;
            results.vega = nan;
            results.theta = nan;
            results.strike_sensitivity = nan;
            results.strike_gamma = nan;
        } else {
            /* delta (models.py:284-286) */
            const double s_sb = pl_bjs_phi_s(S, beta, I, I, rT, bT, variance);
            const double s_s1ii = pl_bjs_phi_s(S, 1.0, I, I, rT, bT, variance);
            const double s_s1xi = pl_bjs_phi_s(S, 1.0, X, I, rT, bT, variance);
            const double s_s0ii = pl_bjs_phi_s(S, 0.0, I, I, rT, bT, variance);
            const double s_s0xi = pl_bjs_phi_s(S, 0.0, X, I, rT, bT, variance);
            const double d1 = (I - X) * pl_pow(S / I, beta - 1.0) * beta / I * (1.0 - p_sb);
            const double d2 = (I - X) * powb * s_sb;
            const double delta4 = pl_sum4(d1, -d2, p_s1ii, S * s_s1ii);
            const double delta7 = pl_sum4(delta4, -p_s1xi, -(S * s_s1xi), -(X * s_s0ii));
            results.delta = delta7 + X * s_s0xi;
            /* dividendRho (models.py:287-304) */
            const double beta_dq_in = 1.0 / (2.0 * root) * 2.0 * (bT / variance - 0.5) / variance;
            const double beta_dq = tq * pl_sum2(1.0 / variance, -beta_dq_in);
            const double b_infinity_dq = -X / pl_sq(beta - 1.0) * beta_dq;
            double B0_dq;
            if (d_d <= rf_d) {
                B0_dq = 0.0;
            } else {
                B0_dq = X * pl_log(rf_d) / pl_sq(pl_log(d_d)) * tq;
            }
            const double ht_dq_in = pl_sum2(B0_dq * bi_b0, -(B0 * (b_infinity_dq - B0_dq)));
            const double ht_dq = pl_sum2(tq * B0 / bi_b0, -(bt_2sv * ht_dq_in / pl_sq(bi_b0)));
            const double I_dq_a = (b_infinity_dq - B0_dq) * (1.0 - exp_ht);
            const double I_dq = pl_sum3(B0_dq, I_dq_a, -(bi_b0 * exp_ht * ht_dq));
            const double hb = pl_bjs_phi_h(S, beta, I, I, rT, bT, variance);
            const double ib = pl_bjs_phi_i(S, beta, I, I, rT, bT, variance);
            const double gb = pl_bjs_phi_gamma(S, beta, I, I, rT, bT, variance);
            const double btb = pl_bjs_phi_bt(S, beta, I, I, rT, bT, variance);
            const double h1 = pl_bjs_phi_h(S, 1.0, I, I, rT, bT, variance);
            const double i1 = pl_bjs_phi_i(S, 1.0, I, I, rT, bT, variance);
            const double bt1 = pl_bjs_phi_bt(S, 1.0, I, I, rT, bT, variance);
            const double i1x = pl_bjs_phi_i(S, 1.0, X, I, rT, bT, variance);
            const double bt1x = pl_bjs_phi_bt(S, 1.0, X, I, rT, bT, variance);
            const double h0 = pl_bjs_phi_h(S, 0.0, I, I, rT, bT, variance);
            const double i0 = pl_bjs_phi_i(S, 0.0, I, I, rT, bT, variance);
            const double bt0 = pl_bjs_phi_bt(S, 0.0, I, I, rT, bT, variance);
            const double i0x = pl_bjs_phi_i(S, 0.0, X, I, rT, bT, variance);
            const double bt0x = pl_bjs_phi_bt(S, 0.0, X, I, rT, bT, variance);
            const double q1_in = beta_dq * pl_log(S / I) - beta * 1.0 / I * I_dq;
            const double q1 = (I_dq * powb + (I - X) * powb * q1_in) * (1.0 - p_sb);
            const double q2 = (I - X) * powb * (hb * I_dq + ib * I_dq + gb * beta_dq - btb * tq);
            const double q3 = S * (h1 * I_dq + i1 * I_dq - bt1 * tq);
            const double q4 = S * (i1x * I_dq - bt1x * tq);
            const double q5 = X * (h0 * I_dq + i0 * I_dq - bt0 * tq);
            const double q6 = X * (i0x * I_dq - bt0x * tq);
            results.dividend_rho = pl_sum4(pl_sum3(q1, -q2, q3), -q4, -q5, q6);
            /* rho (models.py:305-315) */
            const double beta_dr_b = (bT / variance - 0.5) / variance + 1.0 / variance;
            const double beta_dr_c = 1.0 / (2.0 * root) * 2.0 * beta_dr_b;
            const double beta_dr = tr * pl_sum2(-1.0 / variance, beta_dr_c);
            const double b_infinity_dr = -X / pl_sq(beta - 1.0) * beta_dr;
            double B0_dr;
            if (d_d <= rf_d) {
                B0_dr = 0.0;
            } else {
                B0_dr = -X * tr / pl_log(d_d);
            }
            const double ht_dr_in = pl_sum2(B0_dr * bi_b0, -(B0 * (b_infinity_dr - B0_dr)));
            const double ht_dr = pl_sum2(-tr * B0 / bi_b0, -(bt_2sv * ht_dr_in / pl_sq(bi_b0)));
            const double I_dr_a = (b_infinity_dr - B0_dr) * (1.0 - exp_ht);
            const double I_dr = pl_sum3(B0_dr, I_dr_a, -(bi_b0 * exp_ht * ht_dr));
            const double rtb = pl_bjs_phi_rt(S, beta, I, I, rT, bT, variance);
            const double rt1 = pl_bjs_phi_rt(S, 1.0, I, I, rT, bT, variance);
            const double rt1x = pl_bjs_phi_rt(S, 1.0, X, I, rT, bT, variance);
            const double rt0 = pl_bjs_phi_rt(S, 0.0, I, I, rT, bT, variance);
            const double rt0x = pl_bjs_phi_rt(S, 0.0, X, I, rT, bT, variance);
            const double r1_in = beta_dr * pl_log(S / I) - beta / I * I_dr;
            const double r1 = (I_dr * powb + (I - X) * powb * r1_in) * (1.0 - p_sb);
            const double r2_in = hb * I_dr + ib * I_dr + gb * beta_dr + rtb * tr + btb * tr;
            const double r2 = (I - X) * powb * r2_in;
            const double r3 = S * (h1 * I_dr + i1 * I_dr + rt1 * tr + bt1 * tr);
            const double r4 = S * (i1x * I_dr + rt1x * tr + bt1x * tr);
            const double r5 = X * (h0 * I_dr + i0 * I_dr + rt0 * tr + bt0 * tr);
            const double r6 = X * (i0x * I_dr + rt0x * tr + bt0x * tr);
            results.rho = pl_sum4(pl_sum3(r1, -r2, r3), -r4, -r5, r6);
            /* vega (models.py:316-327) */
            const double variance_dv = 2.0 * pl_sqrt(variance * tv);
            const double sq_v = pl_sq(variance);
            const double beta_dv_a = bT / sq_v * variance_dv;
            const double beta_dv_b = 2.0 * (bT / variance - 0.5) * bT * variance_dv / sq_v;
            const double beta_dv_c = 2.0 * rT / sq_v * variance_dv;
            const double beta_dv_d = -1.0 / (2.0 * root) * pl_sum2(beta_dv_b, beta_dv_c);
            const double beta_dv = pl_sum2(beta_dv_a, beta_dv_d);
            const double b_infinity_dv = -X / pl_sq(beta - 1.0) * beta_dv;
            const double ht_dv_a = -1.0 / pl_sqrt(variance) * variance_dv * B0 / bi_b0;
            const double ht_dv_b = bt_2sv * B0 / pl_sq(bi_b0) * b_infinity_dv;
            const double ht_dv = pl_sum2(ht_dv_a, ht_dv_b);
            const double I_dv = pl_sum2(b_infinity_dv * (1.0 - exp_ht), -(bi_b0 * exp_ht * ht_dv));
            const double vb = pl_bjs_phi_v(S, beta, I, I, rT, bT, variance);
            const double v1 = pl_bjs_phi_v(S, 1.0, I, I, rT, bT, variance);
            const double v1x = pl_bjs_phi_v(S, 1.0, X, I, rT, bT, variance);
            const double v0 = pl_bjs_phi_v(S, 0.0, I, I, rT, bT, variance);
            const double v0x = pl_bjs_phi_v(S, 0.0, X, I, rT, bT, variance);
            const double w1_in = beta_dv * pl_log(S / I) - beta / I * I_dv;
            const double w1 = (I_dv * powb + (I - X) * powb * w1_in) * (1.0 - p_sb);
            const double w2_in = hb * I_dv + ib * I_dv + gb * beta_dv + vb * variance_dv;
            const double w2 = (I - X) * powb * w2_in;
            const double w3 = S * (h1 * I_dv + i1 * I_dv + v1 * variance_dv);
            const double w4 = S * (i1x * I_dv + v1x * variance_dv);
            const double w5 = X * (h0 * I_dv + i0 * I_dv + v0 * variance_dv);
            const double w6 = X * (i0x * I_dv + v0x * variance_dv);
            results.vega = pl_sum4(pl_sum3(w1, -w2, w3), -w4, -w5, w6);
            /* gamma (models.py:328-333) */
            const double ssb = pl_bjs_phi_ss(S, beta, I, I, rT, bT, variance);
            const double ss1 = pl_bjs_phi_ss(S, 1.0, I, I, rT, bT, variance);
            const double ss1x = pl_bjs_phi_ss(S, 1.0, X, I, rT, bT, variance);
            const double ss0 = pl_bjs_phi_ss(S, 0.0, I, I, rT, bT, variance);
            const double ss0x = pl_bjs_phi_ss(S, 0.0, X, I, rT, bT, variance);
            const double pb2 = pl_pow(S / I, beta - 2.0);
            const double g1 = (I - X) * pb2 * beta * (beta - 1.0) / pl_sq(I) * (1.0 - p_sb);
            const double g2 = 2.0 * (I - X) * pl_pow(S / I, beta - 1.0) * beta / I * s_sb;
            const double g3 = (I - X) * powb * ssb;
            const double gamma4 = pl_sum4(g1, -g2, -g3, 2.0 * s_s1ii);
            const double gamma7 = pl_sum4(gamma4, S * ss1, -(2.0 * s_s1xi), -(S * ss1x));
            results.gamma = gamma7 - X * ss0 + X * ss0x;
            /* theta, strike sensitivity and strike gamma (models.py:334-338) */
            const double vol = pl_sqrt(variance / tv);
            const double theta_a = 0.5 * results.vega * vol / tv * dtv;
            const double theta_b = results.rho * rT / (tr * tr) * dtr;
            const double theta_c = results.dividend_rho * (rT - bT) / (tq * tq) * dtq;
            const double theta_per_day = -pl_sum3(theta_a, theta_b, theta_c);
            results.theta = 365.0 * theta_per_day;
            results.strike_sensitivity = results.value / X - S / X * results.delta;
            results.strike_gamma = results.gamma * pl_sq(S / X);
        }
    }
    if (results.value < european.value) {
        results = european;
    }
    *out = results;
}

/* models.bjs_engine (models.py:342-355), calculate (cpp:432-506) with tr = tq = 1.0. */
enum pl_engine_status pl_bjs_engine(int side, double S, double K, double d_r, double d_q,
                                    double variance, int greeks, struct pl_engine_result *out) {
    double spot = S;
    double strike = K;
    double risk_free_discount = d_r;
    double dividend_discount = d_q;
    if (side == 1) {
        spot = K;
        strike = S;
        risk_free_discount = d_q;
        dividend_discount = d_r;
    }
    if (dividend_discount > 1.0 && risk_free_discount > dividend_discount) {
        all_nan(out);
        return PL_ENGINE_QL_ERROR;
    }
    struct pl_engine_result res;
    if (dividend_discount >= 1.0 && dividend_discount >= risk_free_discount) {
        pl_bjs_european_call(spot, strike, risk_free_discount, dividend_discount, variance, &res);
    } else {
        pl_bjs_american_call(spot, strike, risk_free_discount, dividend_discount, variance, greeks,
                             &res);
    }
    if (res.value < (spot - strike) * (1.0 + 10.0 * PL_QL_EPSILON)) {
        pl_bjs_immediate(spot, strike, &res);
    }
    if (side == 1) {
        const double tr = 1.0;
        const double tq = 1.0;
        const double delta = res.delta;
        const double gamma = res.gamma;
        const double rho = res.rho;
        res.delta = res.strike_sensitivity;
        res.strike_sensitivity = delta;
        res.gamma = res.strike_gamma;
        res.strike_gamma = gamma;
        res.rho = res.dividend_rho;
        res.dividend_rho = rho;
        res.rho = res.rho * (tr / tq);
        res.dividend_rho = res.dividend_rho * (tq / tr);
    }
    *out = res;
    return PL_ENGINE_OK;
}

/* models.bjs_result (models.py:449): mapped_inputs runs before models._guard, so its raise
 * points are Python defects. */
enum pl_engine_status pl_bjs_result(int side, double S, double K, double T, double r, double q,
                                    double sigma, int greeks, struct pl_engine_result *out) {
    double d_r;
    double d_q;
    double variance;
    int defect = 0;
    pl_mapped_inputs(T, r, q, sigma, &d_r, &d_q, &variance, &defect);
    if (defect != 0) {
        all_nan(out);
        return PL_ENGINE_PY_DEFECT;
    }
    return pl_bjs_engine(side, S, K, d_r, d_q, variance, greeks, out);
}
