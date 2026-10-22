#pragma once
#include "pl_types.h"
#include <stdint.h>

/* QuantLib Brent through Solver1D::solve (spec 3.5; specs/project/models.md "Brent"), as
 * optionlab.solver.brent (solver.py:21-88) transliterates it. */

/* Spec 3.5: accuracy 1e-10, maxEvaluations 200, and N_MAX = 201 evaluations at most for a
 * solve with maxEvaluations = 200 (2 bracket calls, the guess call, at most 198 loop calls). */
#define PL_BRENT_ACCURACY 1e-10
#define PL_BRENT_MAX_EVALUATIONS 200
#define PL_BRENT_N_MAX 201

/* The objective kind. PL_OBJECTIVE_CUBIC evaluates ((c0 s + c1) s + c2) s + c3 (the Brent test
 * objective). PL_OBJECTIVE_MODEL is the row objective of reference.py:97-99: the checked engine
 * value of the model minus mid (pl_price and pl_check_value of pl_evaluate.h).
 * PL_OBJECTIVE_ALO_BOUNDARY (Task 10b) is the objective of the inner QD+ Brent of the ALO engine
 * (optionlab.alo._qd_brent.f): the QD+ evaluator value of o->alo with its planted site and its
 * NaN check (pl_alo_boundary_value of pl_alo_step.h). */
enum pl_objective_kind {
    PL_OBJECTIVE_MODEL = 0,
    PL_OBJECTIVE_CUBIC = 1,
    PL_OBJECTIVE_ALO_BOUNDARY = 2
};

/* The QD+ boundary evaluator of the ALO engine (pl_alo_step.h). */
struct pl_alo_qdplus;

/* One objective. kind selects the dispatch (a switch, never a function pointer). The members
 * model, row, mid, params, tau, band and flags belong to the model objective; cubic holds c0..c3
 * of the cubic objective. domain, py_defect, band and flags are outputs: an evaluation sets
 * domain for a domain result of the model objective (a QuantLib error, a value that is not
 * finite or below -tau), py_defect where Python raises inside the objective, band for a value
 * in -tau <= v < 0.0, and flags collects the BAW bits (Task 10a). pl_brent stops at the first
 * evaluation after which domain or py_defect is nonzero and never clears them, so each solve
 * needs a fresh objective. params is borrowed; it may be NULL for the cubic objective (the
 * model objective then sets py_defect). alo (borrowed) is the evaluator of the ALO boundary
 * objective. last_sigma and last_value (model objective) receive sigma and the checked engine
 * value of the last evaluation that passed the order-5 check (reference.py:304, last[0] and
 * last[1] for ALO: record IV-call fact, H17); uncounted counts the ALO evaluations that the pre
 * check refused (not engine evaluations, reference.py:304). */
struct pl_objective {
    int kind;
    int model;
    struct pl_row row;
    double mid;
    const struct pl_params *params;
    double tau;
    int band;
    int domain;
    int py_defect;
    uint8_t flags;
    double cubic[4];
    struct pl_alo_qdplus *alo;
    double last_sigma;
    double last_value;
    uint32_t uncounted;
};

/* The objective at sigma. Cubic: ((c0 sigma + c1) sigma + c2) sigma + c3 in this order (IEEE
 * operations, no contraction). Model: pl_price of o->model at sigma; PL_ENGINE_PY_DEFECT (or
 * params NULL) sets o->py_defect, PL_ENGINE_QL_ERROR sets o->domain, then pl_check_value; on
 * any of these pl_nan(), else the value minus o->mid (and o->last_sigma, o->last_value); for
 * PL_MODEL_ALO a point that the pre check refuses also increases o->uncounted. ALO boundary:
 * pl_alo_boundary_value of o->alo (o->alo == NULL sets o->py_defect). Any other kind: sets
 * o->py_defect = 1 and returns pl_nan(). o == NULL: returns pl_nan() and changes nothing. */
double pl_objective_value(struct pl_objective *o, double sigma);

/* Statuses 0-3 are the Python statuses 'OK', 'BELOW_MIN', 'ABOVE_MAX', 'NOT_CONVERGED'. */
enum pl_brent_status {
    PL_BRENT_OK = 0,
    PL_BRENT_BELOW_MIN = 1,
    PL_BRENT_ABOVE_MAX = 2,
    PL_BRENT_NOT_CONVERGED = 3,
    PL_BRENT_DOMAIN = 4,
    PL_BRENT_DEFECT = 5
};

/* status: enum pl_brent_status. root: the root for PL_BRENT_OK, else NaN. f_lo: f(lo) when
 * evaluated, else NaN. f_hi: f(hi) when evaluated, else NaN. evaluations: the number of
 * objective calls made, including a call that stopped the solve. */
struct pl_brent_result {
    int status;
    double root, f_lo, f_hi;
    int evaluations;
};

/* solver.py:21-88 (Solver1D::solve with the bracket [lo, hi], then Brent::solveImpl), one
 * statement after another. out receives the result; out == NULL: nothing happens. Failures:
 * PL_BRENT_DEFECT where Python raises ValueError (accuracy not > 0.0, not lo < hi, guess not
 * strictly inside (lo, hi); NaN arguments included) and as soon as an evaluation sets
 * o->py_defect; PL_BRENT_DOMAIN as soon as an evaluation sets o->domain (py_defect first). C
 * contract (no Python counterpart): o == NULL or max_evaluations == INT_MAX gives
 * PL_BRENT_DEFECT with no evaluation (the count then cannot overflow an int). Any other
 * max_evaluations is accepted as Python accepts it: below 3, the loop never runs
 * (PL_BRENT_NOT_CONVERGED after 3 calls). At most max(max_evaluations, 2) + 1 calls
 * (PL_BRENT_N_MAX for PL_BRENT_MAX_EVALUATIONS). */
void pl_brent(struct pl_objective *o, double lo, double hi, double guess, double accuracy,
              int max_evaluations, struct pl_brent_result *out);
