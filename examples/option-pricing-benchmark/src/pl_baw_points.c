/* Transcribed from QuantLib 1.43 (QL_VERSION 1.43; retained source
 * benchmarks/project/third_party/sources/QuantLib-1.43.tar.gz, sha256
 * b41206ccc4ba39b5e86bdc940d51138222b352f79d2c6fc68649f9c9bbe58701), via optionlab/reference.py
 * lines 63-79, 96-98: the side test and the value of one BAW greek point over
 * ql/pricingengines/vanilla/baroneadesiwhaleyengine.cpp 140-236 (the engine and S* through
 * pl_baw.c). QuantLib license (BSD-3-Clause): the copyright notices, conditions and disclaimer are
 * in NOTICE-QuantLib.md of this example (LR-EX 2026-10-18). */
#include "pl_baw.h"
#include "pl_baw_step.h"
#include "pl_black.h"
#include "pl_evaluate.h"
#include "pl_ieee.h"
#include "pl_solver.h"
#include "pl_types.h"
#include <stddef.h>
#include <stdint.h>

/* The points of the BAW greek step (specs/project/models.md "BAW (Amendment G)"), copied from
 * reference.baw_point_side and the E of reference.baw_greeks statement by statement. */

/* reference.baw_point_side (reference.py:71-79) at (S, T, r, s) with the row's side, K and q:
 * baw_admit (reason bump), then the shared S* transcription. Returns PL_GREEKS_OK with *where,
 * PL_GREEKS_DOMAIN for AdmitExcluded (bit 64 into o->flags) or a ModelDefect of the S*, and
 * PL_GREEKS_DEFECT for a raise (BawRunDefect, a raise of baw_admit or of mapped_inputs). */
int pl_baw_point_side(const struct pl_baw_step *c, double S, double T, double r, double s,
                      int *where) {
    const struct pl_row *w = &c->o->row;
    const struct pl_params *p = c->o->params;
    double r1 = 0.0;
    double q1 = 0.0;
    double s1 = 0.0;
    pl_unit(T, r, w->q, s, &r1, &q1, &s1);
    struct pl_baw_admit a;
    pl_baw_admit(w->side, S, w->K, r1, q1, s1 * s1 * 1.0, &a);
    if (a.defect != 0) {
        return PL_GREEKS_DEFECT;
    }
    if (a.in_scope == 0) {
        *where = PL_BAW_EUROPEAN;
        return PL_GREEKS_OK;
    }
    if (a.admitted == 0) {
        c->o->flags = (uint8_t)(c->o->flags | PL_FLAG_ADMIT_EXCLUDED);
        return PL_GREEKS_DOMAIN;
    }
    double d_r = 0.0;
    double d_q = 0.0;
    double v = 0.0;
    int defect = 0;
    pl_mapped_inputs(T, r, w->q, s, &d_r, &d_q, &v, &defect);
    if (defect != 0) {
        return PL_GREEKS_DEFECT;
    }
    double sk = 0.0;
    int iterations = 0;
    const enum pl_engine_status st = pl_baw_sstar(w->side, w->K, d_r, d_q, v, p->baw_newton_max,
                                                  p->baw_plant_nonfinite_sstar, &sk, &iterations);
    if (st == PL_ENGINE_PY_DEFECT) {
        return PL_GREEKS_DEFECT;
    }
    if (st != PL_ENGINE_OK) {
        return PL_GREEKS_DOMAIN;
    }
    const int continuation = (w->side == 0) ? (S < sk) : (S > sk);
    *where = continuation ? PL_BAW_CONTINUATION : PL_BAW_EXERCISE;
    return PL_GREEKS_OK;
}

/* 1 when the point is on the row side; *st receives the status of the side test. */
int pl_baw_on_row(const struct pl_baw_step *c, double S, double T, double r, double s, int *st) {
    int where = PL_BAW_EUROPEAN;
    *st = pl_baw_point_side(c, S, T, r, s, &where);
    return (*st == PL_GREEKS_OK) && (where == c->row);
}

/* E of reference.baw_greeks (reference.py:96-98): counted, then the engine value (models.price)
 * and the order-5 check. */
int pl_baw_point_value(const struct pl_baw_step *c, double S, double T, double r, double s,
                       double *value) {
    const struct pl_row *w = &c->o->row;
    *c->evals += 1u;
    struct pl_engine_result e;
    int iterations = 0;
    const enum pl_engine_status st =
        pl_baw_result(w->side, S, w->K, T, r, w->q, s, 0, c->o->params, &e, &iterations);
    if (st == PL_ENGINE_PY_DEFECT) {
        return PL_GREEKS_DEFECT;
    }
    if (st != PL_ENGINE_OK || pl_check_value(c->o, e.value) != 0) {
        return PL_GREEKS_DOMAIN;
    }
    *value = e.value;
    return PL_GREEKS_OK;
}

/* Two checked point values in Python order; the first status that stops. */
int pl_baw_two_values(const struct pl_baw_step *c, const double *x, const double *y, double *vx,
                      double *vy) {
    const int st = pl_baw_point_value(c, *(x + 0), *(x + 1), *(x + 2), *(x + 3), vx);
    if (st != PL_GREEKS_OK) {
        return st;
    }
    return pl_baw_point_value(c, *(y + 0), *(y + 1), *(y + 2), *(y + 3), vy);
}
