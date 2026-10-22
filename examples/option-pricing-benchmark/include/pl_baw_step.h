#pragma once
#include "pl_solver.h"
#include "pl_types.h"
#include <stdint.h>

/* One BAW greek step and its points (specs/project/models.md "BAW (Amendment G)"): the side test
 * and the checked engine value of one greek point of reference.baw_greeks, in
 * src/pl_baw_points.c; the stencils of src/pl_baw_greeks.c call them as opaque calls (the fixed
 * GCC analyzer budget of one translation unit). Internal to the models module. */

/* The side of a point (reference.baw_point_side): a European-branch point, the continuation side
 * or the exercise side. */
enum pl_baw_side { PL_BAW_EUROPEAN = 0, PL_BAW_CONTINUATION = 1, PL_BAW_EXERCISE = 2 };

/* The row of one greek step: the objective (row, parameters, Checker state, flags), the implied
 * volatility, the checked price p at the row point, the row side and the counter. */
struct pl_baw_step {
    struct pl_objective *o;
    double iv;
    double p;
    int row;
    uint32_t *evals;
};

/* reference.baw_point_side (reference.py:71-79) at (S, T, r, s) with the row's side, K and q:
 * baw_admit (reason bump), then the shared S* transcription. Returns PL_GREEKS_OK with *where,
 * PL_GREEKS_DOMAIN for AdmitExcluded (bit 64 into c->o->flags) or a ModelDefect of the S*, and
 * PL_GREEKS_DEFECT for a raise (BawRunDefect, a raise of baw_admit or of mapped_inputs). */
int pl_baw_point_side(const struct pl_baw_step *c, double S, double T, double r, double s,
                      int *where);
/* 1 when the point is on the row side (side test OK and its side equal to c->row); *st receives
 * the status of the side test. */
int pl_baw_on_row(const struct pl_baw_step *c, double S, double T, double r, double s, int *st);
/* E of reference.baw_greeks (reference.py:96-98): *c->evals + 1, then the engine value
 * (models.price) and the order-5 check. PL_GREEKS_OK with *value, PL_GREEKS_DOMAIN or
 * PL_GREEKS_DEFECT. */
int pl_baw_point_value(const struct pl_baw_step *c, double S, double T, double r, double s,
                       double *value);
/* Two checked point values in Python order (x then y, each four doubles S, T, r, sigma); the
 * first status that stops. */
int pl_baw_two_values(const struct pl_baw_step *c, const double *x, const double *y, double *vx,
                      double *vy);

/* One attempt of each stencil of reference.baw_greeks at one step (in src/pl_baw_stencil.c).
 * Each returns the status of its side tests and point values (PL_GREEKS_OK, PL_GREEKS_DOMAIN or
 * PL_GREEKS_DEFECT; a zero stencil divisor is PL_GREEKS_DEFECT) and *form: 0 when no form has
 * the row side (the caller halves the step), else the form used. */
/* The S stencil with step h (reference.py:111-116): *form 1 central, 2 one-sided three-point. */
int pl_baw_s_try(const struct pl_baw_step *c, double h, int *form, double *delta, double *gamma);
/* two_point (reference.py:124-130) for sigma (variable 0, down allowed when iv - step >= lo) or r
 * (variable 1, down allowed when r - step >= 0.0): *form 1 central, 2 forward, 3 backward. */
int pl_baw_two_point_try(const struct pl_baw_step *c, int variable, double step, double lo,
                         int *form, double *out);
/* The T stencil with step d (reference.py:139-140): *form 1 backward (T - d), 2 forward (T + d). */
int pl_baw_t_try(const struct pl_baw_step *c, double d, int *form, double *theta);

/* One halving of a stencil step, step * 0.5 (reference.py:117, 130, 141), an opaque call for the
 * GCC analyzer (its symbolic depth over the halving loops). */
double pl_baw_halve(double step);
