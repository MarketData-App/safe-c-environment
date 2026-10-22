/* Transcribed from QuantLib 1.43 (QL_VERSION 1.43; retained source
 * benchmarks/project/third_party/sources/QuantLib-1.43.tar.gz, sha256
 * b41206ccc4ba39b5e86bdc940d51138222b352f79d2c6fc68649f9c9bbe58701), via optionlab/alo.py
 * lines 131-162 (merged G-ALO2 part B, commit 567f6c4): ql/math/comparison.hpp 92-107
 * (close_enough); the shared NaN check, the guards and the loop caps of spec Appendix I-ALO R3,
 * R7 and R8 (optionlab code; no QuantLib source). QuantLib license (BSD-3-Clause): the copyright
 * notices, conditions and disclaimer are in NOTICE-QuantLib.md of this example (LR-EX 2026-10-18).
 * */
#include "pl_alo.h"
#include "pl_alo_step.h"
#include "pl_black.h"
#include "pl_ieee.h"
#include "pl_types.h"
#include <stddef.h>
#include <stdint.h>

/* The run state of one ALO engine evaluation (specs/project/models.md "ALO (Amendment I)"):
 * the planted-defect hooks of I4.1, the shared NaN check, the guard count and the loop caps, as
 * the module-level helpers of optionlab.alo. The Python module globals become members of the
 * caller's run object, so concurrent evaluations never share them. */

double pl_alo_mask(struct pl_alo_run *run, int site, double x) {
    const int persistent = run->plant == PL_ALO_SITE_PERSISTENT_QDPLUS_66;
    const int target = persistent ? PL_ALO_SITE_QDPLUS_66 : run->plant;
    if (target != PL_ALO_SITE_NONE && target == site && (persistent || run->fired == 0)) {
        run->fired = 1;
        return pl_nan();
    }
    return x;
}

int pl_alo_fail(struct pl_alo_run *run, int status) {
    if (run->status == PL_ENGINE_OK) {
        run->status = status;
    }
    return 1;
}

int pl_alo_check(struct pl_alo_run *run, int site, const double *xs, size_t n) {
    for (size_t i = 0; i < n; i++) {
        if (pl_is_finite(*(xs + i)) == 0) {
            if (run->status == PL_ENGINE_OK) {
                run->trace->failed_check = site; /* AloRunDefect('alo-nan', site) */
            }
            return pl_alo_fail(run, PL_ENGINE_PY_DEFECT);
        }
    }
    return 0;
}

void pl_alo_guard(struct pl_alo_run *run, double x) {
    if (pl_is_nan(x)) {
        run->trace->nan_guarded += 1u;
    }
}

/* The cap of loop `cap` (alo.CAPS); 0 for an unknown loop (never passed). */
static uint32_t cap_of(int cap) {
    switch (cap) {
    case PL_ALO_CAP_HALLEY:
        return (uint32_t)PL_ALO_CAP_HALLEY_MAX;
    case PL_ALO_CAP_DOUBLING:
        return (uint32_t)PL_ALO_CAP_DOUBLING_MAX;
    case PL_ALO_CAP_BRENT:
        return (uint32_t)PL_ALO_CAP_BRENT_MAX;
    case PL_ALO_CAP_SWEEP_F:
        return (uint32_t)PL_ALO_CAP_SWEEP_F_MAX;
    case PL_ALO_CAP_SWEEP_NDD:
        return (uint32_t)PL_ALO_CAP_SWEEP_NDD_MAX;
    case PL_ALO_CAP_LEVELS:
        return (uint32_t)PL_ALO_CAP_LEVELS_MAX;
    case PL_ALO_CAP_INTEGRAND:
        return PL_ALO_CAP_INTEGRAND_MAX;
    case PL_ALO_CAP_QD_CALLS:
        return PL_ALO_CAP_QD_CALLS_MAX;
    default:
        return 0u;
    }
}

int pl_alo_cap(struct pl_alo_run *run, int cap, uint32_t count) {
    const uint32_t limit = (run->force == 1 + cap) ? 0u : cap_of(cap);
    if (count > limit) {
        if (run->status == PL_ENGINE_OK) {
            run->trace->failed_cap = cap; /* AloRunDefect('alo-cap', name) */
        }
        return pl_alo_fail(run, PL_ENGINE_PY_DEFECT);
    }
    return 0;
}

int pl_alo_close_enough(double x, double y) {
    if (x == y) {
        return 1;
    }
    const double diff = pl_fabs(x - y);
    const double tolerance = 42.0 * PL_QL_EPSILON;
    if (x == 0.0 || y == 0.0) {
        return diff < (tolerance * tolerance);
    }
    return diff <= tolerance * pl_fabs(x) || diff <= tolerance * pl_fabs(y);
}

double pl_alo_min(double a, double b) { return (b < a) ? b : a; }
