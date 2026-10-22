/* Transcribed from QuantLib 1.43 (QL_VERSION 1.43; retained source
 * benchmarks/project/third_party/sources/QuantLib-1.43.tar.gz, sha256
 * b41206ccc4ba39b5e86bdc940d51138222b352f79d2c6fc68649f9c9bbe58701), via optionlab/reference.py
 * lines 178-218, 253-257 (merged G-ALO2 part A, commit 490dce1), optionlab/mapping.py lines
 * 16-38 and optionlab/models.py lines 528-542: the ALO greeks over
 * ql/pricingengines/vanilla/qdfpamericanengine.cpp 429-516 (the engine through pl_alo.c; spec
 * Appendix I-ALO R6, R9). QuantLib license (BSD-3-Clause): the copyright notices, conditions and
 * disclaimer are in NOTICE-QuantLib.md of this example (LR-EX 2026-10-18). */
#include "pl_alo.h"
#include "pl_alo_equation.h"
#include "pl_alo_step.h"
#include "pl_black.h"
#include "pl_crr.h"
#include "pl_evaluate.h"
#include "pl_ieee.h"
#include "pl_solver.h"
#include "pl_types.h"
#include <stddef.h>
#include <stdint.h>

/* The ALO greek step (specs/project/models.md "ALO (Amendment I)"), copied from
 * optionlab.reference.alo_greeks statement by statement (record R6, I2.6): the same point order,
 * the same counter (H17: each greek point that passes the pre check), the segment rule of rho and
 * theta with at most PL_ALO_HALVINGS halvings (the rho and theta stencils are src/pl_alo_stencil.c,
 * opaque calls here: the fixed GCC analyzer budget). The stencil divisions are plain Python
 * divisions (pl_py_div: a zero divisor is ZeroDivisionError, the defect output); the divisions of
 * mapping.greeks_from_unit divide by 365.0. */

/* Python min(a, b): b only when b < a. */
static double py_min(double a, double b) { return (b < a) ? b : a; }

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

/* reference.alo_greeks (reference.py:178-218) at iv with the checked price p: the S, vega, rho
 * and theta stencils, mapping.greeks_from_unit and the finiteness of the seven values. values is
 * written only on PL_GREEKS_OK. */
static int alo_greeks(struct pl_objective *o, double iv, double p, double *values,
                      uint32_t *engine_evals) {
    const struct pl_row *w = &o->row;
    struct pl_alo_step c;
    c.o = o;
    c.iv = iv;
    c.p = p;
    c.evals = engine_evals;
    int zero = 0;
    const double h_s = py_min(1e-3, 0.1 * iv * pl_sqrt(w->T)) * w->S;
    double up = 0.0;
    double dn = 0.0;
    const double xs[4] = {w->S + h_s, w->T, w->r, iv};
    const double ys[4] = {w->S - h_s, w->T, w->r, iv};
    int st = two_values(&c, xs, ys, &up, &dn);
    if (st != PL_GREEKS_OK) {
        return st;
    }
    const double delta = pl_py_div(up - dn, 2.0 * h_s, &zero);
    const double gamma = pl_py_div(up - 2.0 * p + dn, h_s * h_s, &zero);
    if (zero != 0) {
        return PL_GREEKS_DEFECT;
    }
    const double h = o->params->h_sigma;
    const double lo = pl_sigma_lo(PL_MODEL_ALO, w->side, w->T, w->r, w->q, o->params);
    double vega = 0.0;
    if (iv - h < lo) {
        double v1 = 0.0;
        st = pl_alo_point_value(&c, w->S, w->T, w->r, iv + h, &v1);
        if (st != PL_GREEKS_OK) {
            return st;
        }
        vega = pl_py_div(v1 - p, h, &zero);
    } else {
        double v1 = 0.0;
        double v2 = 0.0;
        const double xv[4] = {w->S, w->T, w->r, iv + h};
        const double yv[4] = {w->S, w->T, w->r, iv - h};
        st = two_values(&c, xv, yv, &v1, &v2);
        if (st != PL_GREEKS_OK) {
            return st;
        }
        vega = pl_py_div(v1 - v2, 2.0 * h, &zero);
    }
    if (zero != 0) {
        return PL_GREEKS_DEFECT;
    }
    double r1 = 0.0;
    double q1 = 0.0;
    double s1 = 0.0;
    pl_unit(w->T, w->r, w->q, 1.0, &r1, &q1, &s1);
    pl_alo_segment(w->side, r1, q1, &c.seg);
    if (c.seg.defect != 0) {
        return PL_GREEKS_DEFECT;
    }
    double rho = 0.0;
    int rho_switched = 0;
    st = pl_alo_rho_stencil(&c, &rho, &rho_switched); /* src/pl_alo_stencil.c */
    if (st != PL_GREEKS_OK) {
        return st;
    }
    double theta = 0.0;
    int theta_switched = 0;
    st = pl_alo_theta_stencil(&c, &theta, &theta_switched);
    if (st != PL_GREEKS_OK) {
        return st;
    }
    const double theta_out = theta / 365.0;
    const double vega_out = vega * 0.01;
    const double rho_out = rho * 0.01;
    const int finite = pl_is_finite(iv) & pl_is_finite(p) & pl_is_finite(delta);
    const int more = pl_is_finite(gamma) & pl_is_finite(theta_out) & pl_is_finite(vega_out);
    if ((finite & more & pl_is_finite(rho_out)) == 0) {
        return PL_GREEKS_DOMAIN;
    }
    if (rho_switched || theta_switched) {
        o->flags = (uint8_t)(o->flags | PL_FLAG_STENCIL_SWITCHED);
    }
    *(values + PL_IV) = iv;
    *(values + PL_PRICE) = p;
    *(values + PL_DELTA) = delta;
    *(values + PL_GAMMA) = gamma;
    *(values + PL_THETA) = theta_out;
    *(values + PL_VEGA) = vega_out;
    *(values + PL_RHO) = rho_out;
    return PL_GREEKS_OK;
}

int pl_alo_greeks_at(struct pl_objective *o, double iv, double *values, uint32_t *engine_evals) {
    return alo_greeks(o, iv, o->last_value, values, engine_evals);
}

/* Every field NaN. */
static void set_nan(double *values) {
    for (size_t f = 0; f < PL_FIELDS; f++) {
        *(values + f) = pl_nan();
    }
}

int pl_alo_price_and_greeks(const struct pl_row *row, double sigma, const struct pl_params *p,
                            double values[PL_FIELDS], int *band, uint8_t *flags,
                            uint32_t *engine_evals, int *defect) {
    if (values == NULL || row == NULL || p == NULL || band == NULL || flags == NULL ||
        engine_evals == NULL || defect == NULL) {
        if (values != NULL) {
            set_nan(values);
        }
        if (defect != NULL) {
            *defect = 1;
        }
        return 1;
    }
    set_nan(values);
    *band = 0;
    int raised = 0;
    const double tau = pl_tau_v(row->S, row->K, row->T, row->r, row->q, &raised);
    if (raised != 0) {
        *defect = 1;
        return 1;
    }
    struct pl_objective o = {0};
    o.kind = PL_OBJECTIVE_MODEL;
    o.model = PL_MODEL_ALO;
    o.row = *row;
    o.params = p;
    o.tau = tau;
    o.last_sigma = pl_nan();
    o.last_value = pl_nan();
    /* reference.price_and_greeks (reference.py:254-255): alo_pre, then p = check(value(sigma)),
     * not counted */
    struct pl_alo_trace trace;
    double v = pl_nan();
    const enum pl_engine_status est =
        pl_alo_result(row->side, row->S, row->K, row->T, row->r, row->q, sigma, p, &trace, &v);
    int st = PL_GREEKS_OK;
    if (est == PL_ENGINE_PY_DEFECT) {
        st = PL_GREEKS_DEFECT;
    } else if (est != PL_ENGINE_OK || pl_check_value(&o, v) != 0) {
        st = PL_GREEKS_DOMAIN;
    } else {
        st = alo_greeks(&o, sigma, v, values, engine_evals);
    }
    *band = o.band;
    *flags = (uint8_t)(*flags | o.flags);
    if (st == PL_GREEKS_DEFECT) {
        *defect = 1;
        set_nan(values);
        return 1;
    }
    return (st == PL_GREEKS_OK) ? 0 : 1;
}
