/* Transcribed from QuantLib 1.43 (QL_VERSION 1.43; retained source
 * benchmarks/project/third_party/sources/QuantLib-1.43.tar.gz, sha256
 * b41206ccc4ba39b5e86bdc940d51138222b352f79d2c6fc68649f9c9bbe58701), via optionlab/reference.py
 * lines 109-143: one attempt of each BAW stencil over
 * ql/pricingengines/vanilla/baroneadesiwhaleyengine.cpp 140-236 (the engine through pl_baw.c).
 * QuantLib license (BSD-3-Clause): the copyright notices, conditions and disclaimer are in
 * NOTICE-QuantLib.md of this example (LR-EX 2026-10-18). */
#include "pl_baw_step.h"
#include "pl_evaluate.h"
#include "pl_ieee.h"
#include "pl_types.h"
#include <stddef.h>
#include <stdint.h>

/* One attempt (one step size) of each stencil of reference.baw_greeks (specs/project/models.md
 * "BAW (Amendment G)"), copied statement by statement: the side tests with the Python
 * short-circuit, then the point values in Python order. The halving loops are in
 * pl_baw_greeks.c; this translation unit has no loop (the fixed GCC analyzer budget). The
 * stencil divisions are plain Python divisions: pl_py_div, a zero divisor is the defect. */

/* The status of an attempt whose points were evaluated: the value status first (Python raises in
 * E before the division), then a zero divisor. */
static int finish(int st, int zd) {
    if (st != PL_GREEKS_OK) {
        return st;
    }
    return (zd != 0) ? PL_GREEKS_DEFECT : PL_GREEKS_OK;
}

int pl_baw_s_try(const struct pl_baw_step *c, double h, int *form, double *delta, double *gamma) {
    const struct pl_row *w = &c->o->row;
    const double S = w->S;
    const double T = w->T;
    const double r = w->r;
    const double iv = c->iv;
    *form = 0;
    int st = PL_GREEKS_OK;
    int both = pl_baw_on_row(c, S - h, T, r, iv, &st);
    if (st == PL_GREEKS_OK && both) {
        both = pl_baw_on_row(c, S + h, T, r, iv, &st);
    }
    if (st != PL_GREEKS_OK) {
        return st;
    }
    int zd = 0;
    double a = 0.0;
    double b = 0.0;
    if (both) {
        const double lo[4] = {S - h, T, r, iv};
        const double hi[4] = {S + h, T, r, iv};
        st = pl_baw_two_values(c, lo, hi, &a, &b);
        *delta = pl_py_div(b - a, 2.0 * h, &zd);
        *gamma = pl_py_div(b - 2.0 * c->p + a, h * h, &zd);
        *form = 1;
        return finish(st, zd);
    }
    const double sgn = (w->side == 0) ? -1.0 : 1.0;
    const double s1 = S + sgn * h;
    const double s2 = S + sgn * (2.0 * h);
    both = pl_baw_on_row(c, s1, T, r, iv, &st);
    if (st == PL_GREEKS_OK && both) {
        both = pl_baw_on_row(c, s2, T, r, iv, &st);
    }
    if (st != PL_GREEKS_OK || !both) {
        return st;
    }
    const double x1[4] = {s1, T, r, iv};
    const double x2[4] = {s2, T, r, iv};
    st = pl_baw_two_values(c, x1, x2, &a, &b);
    const double num = 3.0 * c->p - 4.0 * a + b;
    const double half = pl_py_div(num, 2.0 * h, &zd);
    *delta = (w->side == 0) ? half : -half;
    *gamma = pl_py_div(c->p - 2.0 * a + b, h * h, &zd);
    *form = 2;
    return finish(st, zd);
}

/* One point of two_point: the row point with sigma (variable 0) or r (variable 1) moved to x. */
static void moved(const struct pl_baw_step *c, int variable, double x, double *point) {
    const struct pl_row *w = &c->o->row;
    *(point + 0) = w->S;
    *(point + 1) = w->T;
    *(point + 2) = (variable == 0) ? w->r : x;
    *(point + 3) = (variable == 0) ? x : c->iv;
}

int pl_baw_two_point_try(const struct pl_baw_step *c, int variable, double step, double lo,
                         int *form, double *out) {
    const double base = (variable == 0) ? c->iv : c->o->row.r;
    double up[4];
    double down[4];
    moved(c, variable, base + step, up);
    moved(c, variable, base - step, down);
    *form = 0;
    int st = PL_GREEKS_OK;
    const int u = pl_baw_on_row(c, *(up + 0), *(up + 1), *(up + 2), *(up + 3), &st);
    if (st != PL_GREEKS_OK) {
        return st;
    }
    const int allowed = (variable == 0) ? (c->iv - step >= lo) : (c->o->row.r - step >= 0.0);
    int d = 0;
    if (allowed) {
        d = pl_baw_on_row(c, *(down + 0), *(down + 1), *(down + 2), *(down + 3), &st);
        if (st != PL_GREEKS_OK) {
            return st;
        }
    }
    int zd = 0;
    double vu = 0.0;
    double vd = 0.0;
    if (u && d) {
        st = pl_baw_two_values(c, up, down, &vu, &vd);
        *out = pl_py_div(vu - vd, 2.0 * step, &zd);
        *form = 1;
    } else if (u) {
        st = pl_baw_point_value(c, *(up + 0), *(up + 1), *(up + 2), *(up + 3), &vu);
        *out = pl_py_div(vu - c->p, step, &zd);
        *form = 2;
    } else if (d) {
        st = pl_baw_point_value(c, *(down + 0), *(down + 1), *(down + 2), *(down + 3), &vd);
        *out = pl_py_div(c->p - vd, step, &zd);
        *form = 3;
    }
    return finish(st, zd);
}

int pl_baw_t_try(const struct pl_baw_step *c, double d, int *form, double *theta) {
    const struct pl_row *w = &c->o->row;
    const double T = w->T;
    *form = 0;
    int st = PL_GREEKS_OK;
    int zd = 0;
    double v = 0.0;
    if (pl_baw_on_row(c, w->S, T - d, w->r, c->iv, &st)) {
        st = pl_baw_point_value(c, w->S, T - d, w->r, c->iv, &v);
        *theta = pl_py_div(v - c->p, d, &zd);
        *form = 1;
        return finish(st, zd);
    }
    if (st != PL_GREEKS_OK) {
        return st;
    }
    if (pl_baw_on_row(c, w->S, T + d, w->r, c->iv, &st)) {
        st = pl_baw_point_value(c, w->S, T + d, w->r, c->iv, &v);
        *theta = pl_py_div(c->p - v, d, &zd);
        *form = 2;
        return finish(st, zd);
    }
    return st;
}

double pl_baw_halve(double step) { return step * 0.5; }
