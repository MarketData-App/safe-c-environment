/* Transcribed from QuantLib 1.43 (QL_VERSION 1.43; retained source
 * benchmarks/project/third_party/sources/QuantLib-1.43.tar.gz, sha256
 * b41206ccc4ba39b5e86bdc940d51138222b352f79d2c6fc68649f9c9bbe58701), via optionlab/alo.py
 * lines 638-647 (merged G-ALO2 part B, commit 567f6c4): ql/pricingengines/vanilla/
 * qdplusamericanengine.cpp 214-221 (the close(volatility, 0.0) branch of
 * calculatePutWithEdgeCases) (spec Appendix I-ALO R7). QuantLib license (BSD-3-Clause): the
 * copyright notices, conditions and disclaimer are in NOTICE-QuantLib.md of this example (LR-EX
 * 2026-10-18). */
#include "pl_alo.h"
#include "pl_alo_step.h"
#include "pl_ieee.h"
#include "pl_types.h"
#include <float.h>

/* The zero-volatility value of calculatePutWithEdgeCases (specs/project/models.md "ALO
 * (Amendment I)"), copied from optionlab.alo.put_with_edge_cases statement by statement, with the
 * std semantics. Record R7 ALO1-06 calls it unreachable on an admitted point. The engine input
 * domain of pl_alo_engine and pl_alo_result reaches it (sigma' = 1e-300: the 7 zero-volatility
 * engine rows of cvectors.alo_zero_vol_rows, ruling R-10b-E). pl_evaluate has sigma >= sigma_lo
 * >= 1e-4, so it reaches it only when sigma' = sigma sqrt(T) is below (42 QL_EPSILON)^2 (T below
 * about 7.6e-49) and the read-back rates skip the European edge (for example a put at T = 1e-49,
 * r = 3e33, q = 6e33); no evaluate vector holds such a row. Its own translation unit: an opaque
 * call from src/pl_alo.c (the fixed GCC analyzer budget). */

/* intrinsic(t) of the close(vol, 0.0) branch (alo.py:639): max(0, K e^(-r t) - S e^(-q t)). */
static double intrinsic(double S, double K, double r, double q, double t) {
    return pl_max(0.0, K * pl_exp(-r * t) - S * pl_exp(-q * t));
}

double pl_alo_zero_vol(double S, double K, double r, double q, double T) {
    const double npv0 = intrinsic(S, K, r, q, 0.0);
    const double npv_t = intrinsic(S, K, r, q, T);
    double extrem_t = DBL_MAX; /* QL_MAX_REAL when close_enough(r, q) */
    if (!pl_alo_close_enough(r, q)) {
        extrem_t = pl_log((r * K) / (q * S)) / (r - q);
    }
    if (extrem_t > 0.0 && extrem_t < T) {
        double m = npv0;
        const double c1 = npv_t;
        const double c2 = intrinsic(S, K, r, q, extrem_t);
        if (m < c1) {
            m = c1;
        }
        if (m < c2) {
            m = c2;
        }
        return m;
    }
    return pl_max(npv0, npv_t);
}
