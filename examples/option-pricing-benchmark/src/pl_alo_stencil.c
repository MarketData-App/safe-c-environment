/* Transcribed from QuantLib 1.43 (QL_VERSION 1.43; retained source
 * benchmarks/project/third_party/sources/QuantLib-1.43.tar.gz, sha256
 * b41206ccc4ba39b5e86bdc940d51138222b352f79d2c6fc68649f9c9bbe58701), via optionlab/reference.py
 * lines 198-214 (merged G-ALO2 part A, commit 490dce1): the rho and theta stencils of the ALO
 * greeks over ql/pricingengines/vanilla/qdfpamericanengine.cpp 429-516 (the engine through
 * pl_alo.c; spec Appendix I-ALO R6). QuantLib license (BSD-3-Clause): the copyright notices,
 * conditions and disclaimer are in NOTICE-QuantLib.md of this example (LR-EX 2026-10-18). */
#include "pl_alo.h"
#include "pl_alo_step.h"
#include "pl_evaluate.h"
#include "pl_ieee.h"
#include "pl_solver.h"
#include "pl_types.h"
#include <stdint.h>

/* The rho and theta stencils of the ALO greek step (specs/project/models.md "ALO (Amendment I)"),
 * copied from optionlab.reference.alo_greeks statement by statement (record R6, I2.6): the
 * segment rule with at most PL_ALO_HALVINGS halvings. Their own translation unit: called from
 * src/pl_alo_greeks.c as opaque functions (the fixed GCC analyzer budget, as pl_baw_stencil.c).
 * The stencil divisions are plain Python divisions (pl_py_div: a zero divisor is
 * ZeroDivisionError, the defect output); hr / 2 and d / 2 halve exactly. */

/* Python min(a, b): b only when b < a. */
static double py_min(double a, double b) { return (b < a) ? b : a; }

/* x / 2.0 (the stencil halvings) through pl_py_div of another translation unit: the same bits
 * (the divisor is never 0.0), and an opaque result that keeps the GCC analyzer within its fixed
 * symbolic-depth budget over the halving loops. */
static double halve(double x) {
    int never = 0;
    return pl_py_div(x, 2.0, &never);
}

/* Two point values in Python order (the left operand of a difference first). */
static int two_values(const struct pl_alo_step *c, const double *x, const double *y, double *vx,
                      double *vy) {
    int st = pl_alo_point_value(c, *(x + 0), *(x + 1), *(x + 2), *(x + 3), vx);
    if (st != PL_GREEKS_OK) {
        return st;
    }
    st = pl_alo_point_value(c, *(y + 0), *(y + 1), *(y + 2), *(y + 3), vy);
    return st;
}

int pl_alo_rho_stencil(const struct pl_alo_step *c, double *out, int *switched) {
    struct pl_objective *const o = c->o; /* read once (the GCC analyzer budget) */
    const struct pl_row *w = &o->row;
    double hr = o->params->h_r;
    for (int k = 0; k <= PL_ALO_HALVINGS; k++) {
        int defect = 0;
        const int sp = pl_alo_same_segment(c, w->T, w->r + hr, &defect);
        const int sm = (defect == 0) ? pl_alo_same_segment(c, w->T, w->r - hr, &defect) : 0;
        if (defect != 0) {
            return PL_GREEKS_DEFECT;
        }
        int zero = 0;
        int form = 0;
        double up = 0.0;
        double down = 0.0;
        if (sp && sm) {
            const double x[4] = {w->S, w->T, w->r + hr, c->iv};
            const double y[4] = {w->S, w->T, w->r - hr, c->iv};
            const int st = two_values(c, x, y, &up, &down);
            if (st != PL_GREEKS_OK) {
                return st;
            }
            *out = pl_py_div(up - down, 2.0 * hr, &zero);
            form = 1;
        } else if (sp) {
            const int st = pl_alo_point_value(c, w->S, w->T, w->r + hr, c->iv, &up);
            if (st != PL_GREEKS_OK) {
                return st;
            }
            *out = pl_py_div(up - c->p, hr, &zero);
            form = 2;
        } else if (sm) {
            const int st = pl_alo_point_value(c, w->S, w->T, w->r - hr, c->iv, &down);
            if (st != PL_GREEKS_OK) {
                return st;
            }
            *out = pl_py_div(c->p - down, hr, &zero);
            form = 3;
        } else {
            hr = halve(hr);
            continue;
        }
        if (zero != 0) {
            return PL_GREEKS_DEFECT;
        }
        *switched = (form != 1) || (k > 0);
        return PL_GREEKS_OK;
    }
    o->flags = (uint8_t)(o->flags | PL_FLAG_STENCIL_UNRESOLVED);
    return PL_GREEKS_DOMAIN;
}

int pl_alo_theta_stencil(const struct pl_alo_step *c, double *theta, int *switched) {
    struct pl_objective *const o = c->o; /* read once (the GCC analyzer budget) */
    const struct pl_row *w = &o->row;
    double d = py_min(1.0 / 365.0, w->T / 2.0);
    for (int k = 0; k <= PL_ALO_HALVINGS; k++) {
        int defect = 0;
        int zero = 0;
        double v = 0.0;
        const int back = pl_alo_same_segment(c, w->T - d, w->r, &defect);
        if (defect != 0) {
            return PL_GREEKS_DEFECT;
        }
        if (back) {
            const int st = pl_alo_point_value(c, w->S, w->T - d, w->r, c->iv, &v);
            if (st != PL_GREEKS_OK) {
                return st;
            }
            *theta = pl_py_div(v - c->p, d, &zero);
            *switched = (k > 0);
            return (zero != 0) ? PL_GREEKS_DEFECT : PL_GREEKS_OK;
        }
        const int fwd = pl_alo_same_segment(c, w->T + d, w->r, &defect);
        if (defect != 0) {
            return PL_GREEKS_DEFECT;
        }
        if (fwd) {
            const int st = pl_alo_point_value(c, w->S, w->T + d, w->r, c->iv, &v);
            if (st != PL_GREEKS_OK) {
                return st;
            }
            *theta = pl_py_div(c->p - v, d, &zero);
            *switched = 1;
            return (zero != 0) ? PL_GREEKS_DEFECT : PL_GREEKS_OK;
        }
        d = halve(d);
    }
    o->flags = (uint8_t)(o->flags | PL_FLAG_STENCIL_UNRESOLVED);
    return PL_GREEKS_DOMAIN;
}
