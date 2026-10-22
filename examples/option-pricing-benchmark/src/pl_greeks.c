/* Transcribed from QuantLib 1.43 (QL_VERSION 1.43; retained source
 * benchmarks/project/third_party/sources/QuantLib-1.43.tar.gz, sha256
 * b41206ccc4ba39b5e86bdc940d51138222b352f79d2c6fc68649f9c9bbe58701), via optionlab/reference.py
 * lines 45-64 and optionlab/mapping.py lines 16-38: ql/pricingengines/vanilla/
 * analyticeuropeanengine.cpp 45-114, ql/pricingengines/vanilla/bjerksundstenslandengine.cpp
 * 432-506, ql/pricingengines/vanilla/binomialengine.hpp 74-172 (the engine greeks through
 * pl_bsm_result, pl_bjs_result and pl_crr_result). QuantLib license (BSD-3-Clause): the copyright
 * notices, conditions and disclaimer are in NOTICE-QuantLib.md of this example (LR-EX 2026-10-18).
 * */
#include "pl_bjs.h"
#include "pl_black.h"
#include "pl_crr.h"
#include "pl_evaluate.h"
#include "pl_ieee.h"
#include "pl_solver.h"
#include "pl_types.h"
#include <stddef.h>
#include <stdint.h>

/* The greek step of the row evaluation (specs/project/models.md "Row evaluation"), in its own
 * translation unit: the bump chain and the row evaluation together exceed the fixed GCC analyzer
 * budget (analyzer-too-complex). */

/* The engine with greeks at sigma (reference.py:48-50): BSM and BjS with greeks; CRR American
 * with greeks and theta. Any other model: PL_ENGINE_PY_DEFECT (BAW and ALO never come here:
 * pl_greeks_at dispatches them to pl_baw_greeks_at and pl_alo_greeks_at). */
static enum pl_engine_status engine_greeks(const struct pl_objective *o, double sigma,
                                           struct pl_engine_result *e) {
    const struct pl_row *w = &o->row;
    const int steps = o->params->crr_steps;
    switch (o->model) {
    case PL_MODEL_BSM:
        return pl_bsm_result(w->side, w->S, w->K, w->T, w->r, w->q, sigma, 1, e);
    case PL_MODEL_BJS:
        return pl_bjs_result(w->side, w->S, w->K, w->T, w->r, w->q, sigma, 1, e);
    case PL_MODEL_CRR:
        return pl_crr_result(w->side, w->S, w->K, w->T, w->r, w->q, sigma, steps, 1, 1, e);
    default:
        return PL_ENGINE_PY_DEFECT;
    }
}

/* One checked CRR bump evaluation V(s, rr) of _engine_greeks (reference.py:56-58): counted
 * before the call; returns PL_GREEKS_OK with *v, or the status that stops the greek step. */
static int bump_value(struct pl_objective *o, double s, double rr, double *v,
                      uint32_t *engine_evals) {
    const struct pl_row *w = &o->row;
    uint8_t f = 0u;
    *engine_evals += 1u;
    const struct pl_params *p = o->params;
    const int st = (int)pl_price(PL_MODEL_CRR, w->side, w->S, w->K, w->T, rr, w->q, s, p, v, &f);
    o->flags = (uint8_t)(o->flags | f);
    if (st == PL_ENGINE_PY_DEFECT) {
        return PL_GREEKS_DEFECT;
    }
    if (st != PL_ENGINE_OK || pl_check_value(o, *v) != 0) {
        return PL_GREEKS_DOMAIN;
    }
    return PL_GREEKS_OK;
}

/* The CRR vega and rho bumps in the original variables (reference.py:55-60): one-sided vega when
 * iv - h < sigma_lo(CRR), central otherwise; central rho. Python evaluates the left operand of
 * each difference first. */
static int crr_bumps(struct pl_objective *o, double iv, double p, double *vega_bump,
                     double *rho_bump, uint32_t *engine_evals) {
    const struct pl_row *w = &o->row;
    const double lo = pl_sigma_lo(PL_MODEL_CRR, w->side, w->T, w->r, w->q, o->params);
    const double h = o->params->h_sigma;
    const double hr = o->params->h_r;
    double up = 0.0;
    double down = 0.0;
    int st = bump_value(o, iv + h, w->r, &up, engine_evals);
    if (st != PL_GREEKS_OK) {
        return st;
    }
    /* Python divisions: h_sigma or h_r == 0.0 raises ZeroDivisionError (reference.py:59-60) */
    int zero = 0;
    if (iv - h < lo) {
        *vega_bump = pl_py_div(up - p, h, &zero);
    } else {
        st = bump_value(o, iv - h, w->r, &down, engine_evals);
        if (st != PL_GREEKS_OK) {
            return st;
        }
        *vega_bump = pl_py_div(up - down, 2.0 * h, &zero);
    }
    if (zero != 0) {
        return PL_GREEKS_DEFECT;
    }
    st = bump_value(o, iv, w->r + hr, &up, engine_evals);
    if (st != PL_GREEKS_OK) {
        return st;
    }
    st = bump_value(o, iv, w->r - hr, &down, engine_evals);
    if (st != PL_GREEKS_OK) {
        return st;
    }
    *rho_bump = pl_py_div(up - down, 2.0 * hr, &zero);
    return (zero != 0) ? PL_GREEKS_DEFECT : PL_GREEKS_OK;
}

/* reference._engine_greeks (reference.py:45-64) with mapping.greeks_from_unit (mapping.py:16-38):
 * theta_U is present for every model, so theta = theta_U / T (case (a)); vega and rho from the
 * engine for BSM and BjS, from the bumps for CRR; the order-5 check on the engine value and every
 * bump, and the final finiteness test of the seven values. values is written only on
 * PL_GREEKS_OK. */
int pl_greeks_at(struct pl_objective *o, double iv, double *values, uint32_t *engine_evals) {
    if (o->model == PL_MODEL_BAW) {
        return pl_baw_greeks_at(o, iv, values, engine_evals); /* reference.py:232-233 */
    }
    if (o->model == PL_MODEL_ALO) {
        return pl_alo_greeks_at(o, iv, values, engine_evals); /* reference.py:316-320 */
    }
    const struct pl_row *w = &o->row;
    struct pl_engine_result e;
    *engine_evals += 1u;
    const enum pl_engine_status st = engine_greeks(o, iv, &e);
    if (st == PL_ENGINE_PY_DEFECT) {
        return PL_GREEKS_DEFECT;
    }
    if (st != PL_ENGINE_OK || pl_check_value(o, e.value) != 0) {
        return PL_GREEKS_DOMAIN; /* ModelDefect or EngineDomain */
    }
    const double p = e.value;
    const double sq = pl_sqrt(w->T);
    double vega = 0.0;
    double rho = 0.0;
    if (o->model == PL_MODEL_CRR) {
        double vega_bump = 0.0;
        double rho_bump = 0.0;
        const int b = crr_bumps(o, iv, p, &vega_bump, &rho_bump, engine_evals);
        if (b != PL_GREEKS_OK) {
            return b;
        }
        vega = vega_bump * 0.01;
        rho = rho_bump * 0.01;
    } else {
        vega = (sq * e.vega) * 0.01;
        rho = (w->T * e.rho) * 0.01;
    }
    const double theta = (e.theta / w->T) / 365.0;
    const int finite = pl_is_finite(iv) & pl_is_finite(p) & pl_is_finite(e.delta);
    const int finite_more = pl_is_finite(e.gamma) & pl_is_finite(theta) & pl_is_finite(vega);
    if ((finite & finite_more & pl_is_finite(rho)) == 0) {
        return PL_GREEKS_DOMAIN;
    }
    *(values + PL_IV) = iv;
    *(values + PL_PRICE) = p;
    *(values + PL_DELTA) = e.delta;
    *(values + PL_GAMMA) = e.gamma;
    *(values + PL_THETA) = theta;
    *(values + PL_VEGA) = vega;
    *(values + PL_RHO) = rho;
    return PL_GREEKS_OK;
}
