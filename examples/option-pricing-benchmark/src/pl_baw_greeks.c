/* Transcribed from QuantLib 1.43 (QL_VERSION 1.43; retained source
 * benchmarks/project/third_party/sources/QuantLib-1.43.tar.gz, sha256
 * b41206ccc4ba39b5e86bdc940d51138222b352f79d2c6fc68649f9c9bbe58701), via optionlab/reference.py
 * lines 63-147, 177-185 and optionlab/mapping.py lines 16-38: the BAW greeks over
 * ql/pricingengines/vanilla/baroneadesiwhaleyengine.cpp 140-236 (the engine through pl_baw.c).
 * QuantLib license (BSD-3-Clause): the copyright notices, conditions and disclaimer are in
 * NOTICE-QuantLib.md of this example (LR-EX 2026-10-18). */
#include "pl_baw.h"
#include "pl_baw_step.h"
#include "pl_black.h"
#include "pl_crr.h"
#include "pl_evaluate.h"
#include "pl_ieee.h"
#include "pl_solver.h"
#include "pl_types.h"
#include <stddef.h>
#include <stdint.h>

/* The BAW greeks of record R6 and the stencil rule of record R7 with the errata F4 and R(a)-R(c)
 * (specs/project/models.md "BAW (Amendment G)"), copied from optionlab.reference.baw_greeks
 * statement by statement: the same point order, the Python short-circuit of each side test, the
 * same counter. The stencil divisions are plain Python divisions (pl_py_div: a zero divisor is a
 * ZeroDivisionError, the defect output); the divisions of mapping.greeks_from_unit divide by T > 0
 * and 365.0. Every loop runs at most PL_BAW_HALVINGS + 1 times. */

/* Python min(a, b): b only when b < a. */
static double py_min(double a, double b) { return (b < a) ? b : a; }

/* The S stencil (reference.py:109-119): central, else the one-sided three-point stencil on the
 * row side, h halved at most PL_BAW_HALVINGS times; bit 16 into o->flags when none is found. */
static int s_stencil(const struct pl_baw_step *c, double *delta, double *gamma, int *switched) {
    const struct pl_row *w = &c->o->row;
    double h = py_min(0x1.0624dd2f1a9fcp-10, 0x1.999999999999ap-4 * c->iv * pl_sqrt(w->T)) * w->S;
    for (int k = 0; k <= PL_BAW_HALVINGS; k++) {
        int form = 0;
        const int st = pl_baw_s_try(c, h, &form, delta, gamma);
        if (st != PL_GREEKS_OK || form != 0) {
            *switched = (form != 1) || (k > 0);
            return st;
        }
        h = pl_baw_halve(h);
    }
    c->o->flags = (uint8_t)(c->o->flags | PL_FLAG_STENCIL_UNRESOLVED);
    return PL_GREEKS_DOMAIN;
}

/* two_point of reference.baw_greeks (reference.py:120-133) for sigma (variable 0) or r (variable
 * 1): central, forward or backward, the step halved at most PL_BAW_HALVINGS times; bit 16 into
 * o->flags when none is found. */
static int two_point(const struct pl_baw_step *c, int variable, double step, double lo, double *out,
                     int *switched) {
    for (int k = 0; k <= PL_BAW_HALVINGS; k++) {
        int form = 0;
        const int st = pl_baw_two_point_try(c, variable, step, lo, &form, out);
        if (st != PL_GREEKS_OK || form != 0) {
            *switched = (form != 1) || (k > 0);
            return st;
        }
        step = pl_baw_halve(step);
    }
    c->o->flags = (uint8_t)(c->o->flags | PL_FLAG_STENCIL_UNRESOLVED);
    return PL_GREEKS_DOMAIN;
}

/* The T stencil (reference.py:137-143, erratum F4): T - d, then T + d, d = min(1/365, T/2)
 * halved at most PL_BAW_HALVINGS times; bit 16 into o->flags when neither has the row side. */
static int t_stencil(const struct pl_baw_step *c, double *theta, int *switched) {
    double d = py_min(1.0 / 365.0, c->o->row.T / 2.0);
    for (int k = 0; k <= PL_BAW_HALVINGS; k++) {
        int form = 0;
        const int st = pl_baw_t_try(c, d, &form, theta);
        if (st != PL_GREEKS_OK || form != 0) {
            *switched = (form != 1) || (k > 0);
            return st;
        }
        d = pl_baw_halve(d);
    }
    c->o->flags = (uint8_t)(c->o->flags | PL_FLAG_STENCIL_UNRESOLVED);
    return PL_GREEKS_DOMAIN;
}

/* The continuation side (reference.py:108-144): the S stencil, sigma_lo(BAW), the sigma and r
 * stencils and the T stencil, in this order; *g receives delta, gamma, theta (per year), the
 * sigma and r differences, and *switched bit 32 when a stencil switched or halved. */
static int continuation(const struct pl_baw_step *c, double *g, int *switched) {
    const struct pl_row *w = &c->o->row;
    const struct pl_params *p = c->o->params;
    int sw_s = 0;
    int sw_v = 0;
    int sw_r = 0;
    int sw_t = 0;
    int st = s_stencil(c, g + 0, g + 1, &sw_s);
    if (st != PL_GREEKS_OK) {
        return st;
    }
    const double lo = pl_sigma_lo(PL_MODEL_BAW, w->side, w->T, w->r, w->q, p);
    st = two_point(c, 0, p->h_sigma, lo, g + 3, &sw_v);
    if (st != PL_GREEKS_OK) {
        return st;
    }
    st = two_point(c, 1, p->h_r, lo, g + 4, &sw_r);
    if (st != PL_GREEKS_OK) {
        return st;
    }
    st = t_stencil(c, g + 2, &sw_t);
    *switched = sw_s | sw_v | sw_r | sw_t;
    return st;
}

int pl_baw_greeks_at(struct pl_objective *o, double iv, double *values, uint32_t *engine_evals) {
    const struct pl_row *w = &o->row;
    struct pl_baw_step c = {o, iv, 0.0, PL_BAW_EUROPEAN, engine_evals};
    int st = pl_baw_point_side(&c, w->S, w->T, w->r, iv, &c.row);
    if (st != PL_GREEKS_OK) {
        return st;
    }
    *engine_evals += 1u;
    struct pl_engine_result e;
    int iterations = 0;
    const enum pl_engine_status es =
        pl_baw_result(w->side, w->S, w->K, w->T, w->r, w->q, iv, 1, o->params, &e, &iterations);
    if (es == PL_ENGINE_PY_DEFECT) {
        return PL_GREEKS_DEFECT;
    }
    if (es != PL_ENGINE_OK || pl_check_value(o, e.value) != 0) {
        return PL_GREEKS_DOMAIN;
    }
    c.p = e.value;
    /* delta, gamma, theta per year, vega and rho per unit (mapping.greeks_from_unit inputs) */
    double g[5] = {e.delta, e.gamma, 0.0, 0.0, 0.0};
    int switched = 0;
    double theta = 0.0;
    double vega = 0.0;
    double rho = 0.0;
    if (c.row == PL_BAW_EUROPEAN) {
        theta = (e.theta / w->T) / 365.0;
        vega = (pl_sqrt(w->T) * e.vega) * 0.01;
        rho = (w->T * e.rho) * 0.01;
    } else if (c.row == PL_BAW_EXERCISE) {
        *(g + 0) = (w->side == 0) ? 1.0 : -1.0;
        *(g + 1) = 0.0;
        theta = 0.0 / 365.0;
        vega = 0.0 * 0.01;
        rho = 0.0 * 0.01;
    } else {
        st = continuation(&c, g, &switched);
        if (st != PL_GREEKS_OK) {
            return st;
        }
        theta = *(g + 2) / 365.0;
        vega = *(g + 3) * 0.01;
        rho = *(g + 4) * 0.01;
    }
    const int f1 = pl_is_finite(iv) & pl_is_finite(c.p) & pl_is_finite(*(g + 0));
    const int f2 = pl_is_finite(*(g + 1)) & pl_is_finite(theta) & pl_is_finite(vega);
    if ((f1 & f2 & pl_is_finite(rho)) == 0) {
        return PL_GREEKS_DOMAIN; /* EngineDomain */
    }
    *(values + PL_IV) = iv;
    *(values + PL_PRICE) = c.p;
    *(values + PL_DELTA) = *(g + 0);
    *(values + PL_GAMMA) = *(g + 1);
    *(values + PL_THETA) = theta;
    *(values + PL_VEGA) = vega;
    *(values + PL_RHO) = rho;
    if (switched != 0) {
        o->flags = (uint8_t)(o->flags | PL_FLAG_STENCIL_SWITCHED);
    }
    return PL_GREEKS_OK;
}

int pl_baw_price_and_greeks(const struct pl_row *row, double sigma, const struct pl_params *p,
                            double values[PL_FIELDS], int *band, uint8_t *flags,
                            uint32_t *engine_evals, int *defect) {
    if (values == NULL || row == NULL || p == NULL || band == NULL || flags == NULL ||
        engine_evals == NULL || defect == NULL) {
        if (defect != NULL) {
            *defect = 1;
        }
        return 1;
    }
    const double nan = pl_nan();
    for (size_t f = 0; f < PL_FIELDS; f++) {
        *(values + f) = nan;
    }
    *band = 0;
    int raised = 0;
    const double tau = pl_tau_v(row->S, row->K, row->T, row->r, row->q, &raised);
    if (raised != 0) {
        *defect = 1;
        return 1;
    }
    struct pl_objective o;
    o.kind = PL_OBJECTIVE_MODEL;
    o.model = PL_MODEL_BAW;
    o.row = *row;
    o.mid = 0.0;
    o.params = p;
    o.tau = tau;
    o.band = 0;
    o.domain = 0;
    o.py_defect = 0;
    o.flags = 0u;
    *(o.cubic + 0) = 0.0;
    *(o.cubic + 1) = 0.0;
    *(o.cubic + 2) = 0.0;
    *(o.cubic + 3) = 0.0;
    o.alo = NULL;
    o.last_sigma = nan;
    o.last_value = nan;
    o.uncounted = 0u;
    const int st = pl_baw_greeks_at(&o, sigma, values, engine_evals);
    *band = o.band;
    *flags = (uint8_t)(*flags | o.flags);
    if (st == PL_GREEKS_DEFECT) {
        *defect = 1;
        for (size_t f = 0; f < PL_FIELDS; f++) {
            *(values + f) = nan;
        }
        return 1;
    }
    return (st == PL_GREEKS_OK) ? 0 : 1;
}
