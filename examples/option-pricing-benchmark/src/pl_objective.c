#include "pl_alo.h"
#include "pl_alo_step.h"
#include "pl_evaluate.h"
#include "pl_ieee.h"
#include "pl_solver.h"
#include "pl_types.h"
#include <stddef.h>
#include <stdint.h>

/* The objective of pl_brent (specs/project/models.md "Brent" and "Row evaluation"): the cubic test
 * objective, the row objective of optionlab.reference and the objective of the inner QD+ Brent of
 * the ALO engine. Its own translation unit since Task 10b: pl_brent of src/pl_solver.c calls it
 * as an opaque function (the fixed GCC analyzer budget). optionlab code (reference.py:97-99,
 * 297-305), no QuantLib source. */

/* The row objective f(sigma) = check(price(sigma)) - mid of reference.py:97-99: the engine value
 * of o->model through pl_price, then the order-5 check (pl_check_value). A Python raise in the
 * engine (PL_ENGINE_PY_DEFECT) or params == NULL (C contract) sets py_defect; a QuantLib error
 * (ModelDefect) or a failed check sets domain; both return pl_nan(). The BAW flag bits of the
 * evaluation (Task 10a) collect in o->flags. */
static double model_value(struct pl_objective *o, double sigma) {
    if (o->params == NULL) {
        o->py_defect = 1;
        return pl_nan();
    }
    double v = pl_nan();
    uint8_t f = 0u;
    const struct pl_row *w = &o->row;
    const struct pl_params *p = o->params;
    int st;
    if (o->model == PL_MODEL_ALO) {
        /* reference.py:304: alo_pre first (a refused point raises before ev += 1, counted in
         * o->uncounted), then the engine value (src/pl_alo_points.c: an opaque call for the
         * fixed GCC analyzer budget) */
        st = (int)pl_alo_objective_price(o, sigma, &v);
    } else {
        st = (int)pl_price(o->model, w->side, w->S, w->K, w->T, w->r, w->q, sigma, p, &v, &f);
    }
    o->flags = (uint8_t)(o->flags | f);
    if (st == PL_ENGINE_PY_DEFECT) {
        o->py_defect = 1;
        return pl_nan();
    }
    if (st != PL_ENGINE_OK) {
        o->domain = 1;
        return pl_nan();
    }
    if (pl_check_value(o, v) != 0) {
        return pl_nan();
    }
    o->last_sigma = sigma;
    o->last_value = v;
    return v - o->mid;
}

double pl_objective_value(struct pl_objective *o, double sigma) {
    if (o == NULL) {
        return pl_nan();
    }
    switch (o->kind) {
    case PL_OBJECTIVE_CUBIC: {
        const double c0 = *(o->cubic + 0);
        const double c1 = *(o->cubic + 1);
        const double c2 = *(o->cubic + 2);
        const double c3 = *(o->cubic + 3);
        return ((c0 * sigma + c1) * sigma + c2) * sigma + c3;
    }
    case PL_OBJECTIVE_MODEL:
        return model_value(o, sigma);
    case PL_OBJECTIVE_ALO_BOUNDARY:
        if (o->alo == NULL) {
            o->py_defect = 1; /* C contract: no evaluator */
            return pl_nan();
        }
        return pl_alo_boundary_value(o->alo, sigma, &o->py_defect);
    default:
        /* An unknown kind: a run defect. */
        o->py_defect = 1;
        return pl_nan();
    }
}
