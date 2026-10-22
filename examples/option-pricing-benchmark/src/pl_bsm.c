/* Transcribed from QuantLib 1.43 (QL_VERSION 1.43; retained source
 * benchmarks/project/third_party/sources/QuantLib-1.43.tar.gz, sha256
 * b41206ccc4ba39b5e86bdc940d51138222b352f79d2c6fc68649f9c9bbe58701), via optionlab/models.py lines
 * 195-202, 448: ql/pricingengines/vanilla/analyticeuropeanengine.cpp 45-114. QuantLib license
 * (BSD-3-Clause): the copyright notices, conditions and disclaimer are in NOTICE-QuantLib.md of
 * this example (LR-EX 2026-10-18). */
#include "pl_black.h"
#include "pl_ieee.h"

/* The BSM engine (specs/project/models.md "Term structure, mapping and BSM"). A translation
 * unit of its own: the BlackCalculator functions of pl_black.c are opaque calls here, which
 * keeps the GCC analyzer path count of each file within its fixed budget. Every division is
 * IEEE C division (models._guard; see pl_black.c). */

/* models.bsm_engine (models.py:195-202), AnalyticEuropeanEngine::calculate
 * (analyticeuropeanengine.cpp:45-114) at t = 1. */
void pl_bsm_engine(int side, double S, double K, double d_r, double d_q, double variance,
                   int greeks, struct pl_engine_result *out) {
    const double forward_price = S * d_q / d_r;
    struct pl_black black;
    pl_black_init(&black, side, K, forward_price, pl_sqrt(variance), d_r);
    const double nan = pl_nan();
    out->value = pl_black_value(&black);
    out->delta = nan;
    out->gamma = nan;
    out->theta = nan;
    out->vega = nan;
    out->rho = nan;
    out->dividend_rho = nan;
    out->strike_sensitivity = nan;
    out->strike_gamma = nan;
    if (greeks == 0) {
        return;
    }
    out->delta = pl_black_delta(&black, S);
    out->gamma = pl_black_gamma(&black, S);
    out->rho = pl_black_rho(&black, 1.0);
    out->dividend_rho = pl_black_dividend_rho(&black, 1.0);
    out->vega = pl_black_vega(&black, 1.0);
    out->theta = pl_black_theta(&black, S, 1.0);
}

/* models.bsm_result (models.py:448): mapped_inputs runs before models._guard, so its raise
 * points are Python defects. */
enum pl_engine_status pl_bsm_result(int side, double S, double K, double T, double r, double q,
                                    double sigma, int greeks, struct pl_engine_result *out) {
    double d_r;
    double d_q;
    double variance;
    int defect = 0;
    pl_mapped_inputs(T, r, q, sigma, &d_r, &d_q, &variance, &defect);
    if (defect != 0) {
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
        return PL_ENGINE_PY_DEFECT;
    }
    pl_bsm_engine(side, S, K, d_r, d_q, variance, greeks, out);
    return PL_ENGINE_OK;
}
