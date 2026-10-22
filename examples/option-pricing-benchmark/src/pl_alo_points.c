/* Transcribed from QuantLib 1.43 (QL_VERSION 1.43; retained source
 * benchmarks/project/third_party/sources/QuantLib-1.43.tar.gz, sha256
 * b41206ccc4ba39b5e86bdc940d51138222b352f79d2c6fc68649f9c9bbe58701), via optionlab/reference.py
 * lines 159-163, 186-190, 198-211 (merged G-ALO2 part A, commit 490dce1) and
 * optionlab/mapping.py lines 9-14: ql/pricingengines/vanilla/qdplusamericanengine.cpp 167-228 and
 * ql/pricingengines/vanilla/qdfpamericanengine.cpp 429-516 (the engine through pl_alo.c; spec
 * Appendix I-ALO R6). QuantLib license (BSD-3-Clause): the copyright notices, conditions and
 * disclaimer are in NOTICE-QuantLib.md of this example (LR-EX 2026-10-18). */
#include "pl_alo.h"
#include "pl_alo_equation.h"
#include "pl_alo_step.h"
#include "pl_black.h"
#include "pl_evaluate.h"
#include "pl_ieee.h"
#include "pl_solver.h"
#include "pl_types.h"
#include <stddef.h>
#include <stdint.h>

/* The greek points of the ALO greek step (specs/project/models.md "ALO (Amendment I)"): E of
 * reference.alo_greeks (alo_pre, then the count, then the checked engine value) and the segment
 * test of a rho or theta point (alo_segment of unit(T, r, q, 1.0) against the row's segment), in
 * a translation unit of their own (the fixed GCC analyzer budget). */

/* Branches that no generator row reaches (rulings R-10c and R-10c-2; none is excluded from
 * coverage). The rows of cvectors.alo_greek_point_rows and alo_greek_plant_rows reach the others,
 * among them an order-5 engine error other than the pre check at a stencil point (QL_ERROR with
 * another failed check, then st != PL_ENGINE_OK): the BlackCalculator F > 0 check of the European
 * edge at a rho point whose forward underflows to 0.0 (puts at T = 1e6, q = 7e-4).
 * - pl_alo_point_value, a mapping raise (PL_ENGINE_PY_DEFECT with trace.equation < 0): guard
 *   only. The S and sigma points have the row's T, r and q, which the row point mapped already.
 *   pl_alo_same_segment maps each rho and theta point first and stops at a raise.
 * - pl_alo_same_segment, T < 0.0: guard only. A theta point is T - d with d <= T / 2, or T + d.
 * Other order-5 errors can also occur at a stencil point: the inner QD+ solver ("root not
 * bracketed", seen at extreme inputs on the Python side) and the Boost end-narrowing error of
 * src/pl_alo_ts_ends.c. */

enum pl_engine_status pl_alo_objective_price(struct pl_objective *o, double sigma, double *value) {
    const struct pl_row *w = &o->row;
    struct pl_alo_trace trace;
    const enum pl_engine_status st =
        pl_alo_result(w->side, w->S, w->K, w->T, w->r, w->q, sigma, o->params, &trace, value);
    if (st == PL_ENGINE_QL_ERROR && trace.failed_check == PL_ALO_CHECK_PRE) {
        o->uncounted += 1u; /* reference.py:304: alo_pre raises before ev += 1 */
    }
    return st;
}

int pl_alo_point_value(const struct pl_alo_step *c, double S, double T, double r, double s,
                       double *value) {
    struct pl_objective *o = c->o;
    const struct pl_row *w = &o->row;
    struct pl_alo_trace trace;
    double v = pl_nan();
    const enum pl_engine_status st =
        pl_alo_result(w->side, S, w->K, T, r, w->q, s, o->params, &trace, &v);
    if (st == PL_ENGINE_QL_ERROR && trace.failed_check == PL_ALO_CHECK_PRE) {
        return PL_GREEKS_DOMAIN; /* AloPreCheck before ev += 1: not counted */
    }
    if (st == PL_ENGINE_PY_DEFECT && trace.equation < 0) {
        return PL_GREEKS_DEFECT; /* the mapping of alo_pre raises: not counted */
    }
    *c->evals += 1u;
    if (st == PL_ENGINE_PY_DEFECT) {
        return PL_GREEKS_DEFECT;
    }
    if (st != PL_ENGINE_OK || pl_check_value(o, v) != 0) {
        return PL_GREEKS_DOMAIN;
    }
    *value = v;
    return PL_GREEKS_OK;
}

int pl_alo_same_segment(const struct pl_alo_step *c, double T, double r, int *defect) {
    const struct pl_row *w = &c->o->row;
    if (T < 0.0) {
        *defect = 1; /* mapping.unit: math.sqrt(T) raises ValueError */
        return 0;
    }
    double r1 = 0.0;
    double q1 = 0.0;
    double s1 = 0.0;
    pl_unit(T, r, w->q, 1.0, &r1, &q1, &s1);
    struct pl_alo_segment seg;
    pl_alo_segment(w->side, r1, q1, &seg);
    if (seg.defect != 0) {
        *defect = 1;
        return 0;
    }
    return pl_alo_segment_equal(&seg, &c->seg);
}
