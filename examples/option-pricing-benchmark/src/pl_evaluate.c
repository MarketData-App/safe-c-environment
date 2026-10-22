/* Transcribed from QuantLib 1.43 (QL_VERSION 1.43; retained source
 * benchmarks/project/third_party/sources/QuantLib-1.43.tar.gz, sha256
 * b41206ccc4ba39b5e86bdc940d51138222b352f79d2c6fc68649f9c9bbe58701), via optionlab/reference.py
 * lines 20-109, 205-242, optionlab/mapping.py lines 16-38 and optionlab/models.py lines 485-492:
 * ql/math/solver1d.hpp 162-211, ql/math/solvers1d/brent.hpp 39-137, ql/math/comparison.hpp
 * 59-76 (the implied-volatility solve through pl_brent). QuantLib license (BSD-3-Clause): the
 * copyright notices, conditions and disclaimer are in NOTICE-QuantLib.md of this example (LR-EX
 * 2026-10-18). */
#include "pl_evaluate.h"
#include "pl_alo.h"
#include "pl_alo_equation.h"
#include "pl_baw.h"
#include "pl_bjs.h"
#include "pl_black.h"
#include "pl_crr.h"
#include "pl_ieee.h"
#include "pl_solver.h"
#include "pl_types.h"
#include <stddef.h>
#include <stdint.h>

/* The row evaluation (specs/project/models.md "Row evaluation"). Each function copies the cited
 * optionlab statements in order, with the same association; Python max is pl_max (argument
 * order kept), abs is pl_fabs, math.sqrt of a positive T is pl_sqrt. A Python raise point gives a
 * defect output, never a status (controller ruling H1). */

double pl_tau_v(double S, double K, double T, double r, double q, int *defect) {
    if (T < 0.0) {
        *defect = 1; /* mapping.unit: math.sqrt(T) raises ValueError */
        return pl_nan();
    }
    double r1 = 0.0;
    double q1 = 0.0;
    double s1 = 0.0;
    pl_unit(T, r, q, 1.0, &r1, &q1, &s1);
    const double d_r = pl_discount(r1, 1.0, defect);
    const double d_q = pl_discount(q1, 1.0, defect);
    const double f = pl_py_div(S * d_q, d_r, defect);
    return ((4.0 * PL_QL_EPSILON) * d_r) * pl_max(f, K);
}

int pl_check_value(struct pl_objective *o, double v) {
    if (o == NULL) {
        return 1;
    }
    if (pl_is_finite(v) == 0 || v < -o->tau) {
        o->domain = 1;
        return 1;
    }
    if (v < 0.0) {
        o->band = 1;
    }
    return 0;
}

enum pl_engine_status pl_price(int model, int side, double S, double K, double T, double r,
                               double q, double sigma, const struct pl_params *p, double *value,
                               uint8_t *flags) {
    if (value == NULL || flags == NULL || p == NULL) {
        if (value != NULL) {
            *value = pl_nan();
        }
        return PL_ENGINE_PY_DEFECT;
    }
    struct pl_engine_result e;
    enum pl_engine_status st;
    switch (model) {
    case PL_MODEL_BSM:
        st = pl_bsm_result(side, S, K, T, r, q, sigma, 0, &e);
        break;
    case PL_MODEL_BJS:
        st = pl_bjs_result(side, S, K, T, r, q, sigma, 0, &e);
        break;
    case PL_MODEL_CRR:
        st = pl_crr_result(side, S, K, T, r, q, sigma, p->crr_steps, 1, 0, &e);
        break;
    case PL_MODEL_BAW:
        return pl_baw_price(side, S, K, T, r, q, sigma, p, value, flags);
    case PL_MODEL_ALO: {
        struct pl_alo_trace trace;
        return pl_alo_result(side, S, K, T, r, q, sigma, p, &trace, value); /* alo.price */
    }
    default:
        /* any other model: models.price raises ValueError */
        *value = pl_nan();
        return PL_ENGINE_PY_DEFECT;
    }
    *value = pl_nan();
    if (st == PL_ENGINE_OK) {
        *value = e.value;
    }
    return st;
}

/* Every field NaN (straight-line code: a loop here exceeds the fixed GCC analyzer budget). */
static void set_nan(double *values) {
    const double nan = pl_nan();
    *(values + PL_IV) = nan;
    *(values + PL_PRICE) = nan;
    *(values + PL_DELTA) = nan;
    *(values + PL_GAMMA) = nan;
    *(values + PL_THETA) = nan;
    *(values + PL_VEGA) = nan;
    *(values + PL_RHO) = nan;
}

/* A model objective for the row (reference.py:94, 97-98): tau, band 0, domain 0, py_defect 0,
 * flags 0. */
static void model_objective(struct pl_objective *o, int model, const struct pl_row *row, double mid,
                            const struct pl_params *p, double tau) {
    o->kind = PL_OBJECTIVE_MODEL;
    o->model = model;
    o->row = *row;
    o->mid = mid;
    o->params = p;
    o->tau = tau;
    o->band = 0;
    o->domain = 0;
    o->py_defect = 0;
    o->flags = 0u;
    *(o->cubic + 0) = 0.0;
    *(o->cubic + 1) = 0.0;
    *(o->cubic + 2) = 0.0;
    *(o->cubic + 3) = 0.0;
    o->alo = NULL;
    o->last_sigma = pl_nan();
    o->last_value = pl_nan();
    o->uncounted = 0u;
}

int pl_price_and_greeks(int model, const struct pl_row *row, double sigma,
                        const struct pl_params *p, double values[PL_FIELDS], int *band,
                        uint8_t *flags, uint32_t *engine_evals) {
    if (values == NULL) {
        return PL_GREEKS_DEFECT;
    }
    set_nan(values);
    if (row == NULL || p == NULL || band == NULL || flags == NULL || engine_evals == NULL) {
        return PL_GREEKS_DEFECT;
    }
    *band = 0;
    if (model == PL_MODEL_ALO) { /* reference.price_and_greeks, ALO branch (reference.py:253-257) */
        int raised = 0;
        const int st =
            pl_alo_price_and_greeks(row, sigma, p, values, band, flags, engine_evals, &raised);
        if (raised != 0) {
            return PL_GREEKS_DEFECT;
        }
        return (st == 0) ? PL_GREEKS_OK : PL_GREEKS_DOMAIN;
    }
    int defect = 0;
    const double tau = pl_tau_v(row->S, row->K, row->T, row->r, row->q, &defect);
    if (defect != 0) {
        return PL_GREEKS_DEFECT;
    }
    struct pl_objective o;
    model_objective(&o, model, row, 0.0, p, tau);
    const int st = pl_greeks_at(&o, sigma, values, engine_evals);
    *band = o.band;
    *flags = (uint8_t)(*flags | o.flags);
    return st;
}

/* Orders 1-4 of spec 3.3 (reference.py:87-90): the status, or PL_OK when the row passes. */
static uint8_t input_status(const struct pl_row *w) {
    const int bad_side = w->side != 0 && w->side != 1;
    const int finite = pl_is_finite(w->S) & pl_is_finite(w->K) & pl_is_finite(w->T);
    const int finite_quote = pl_is_finite(w->bid) & pl_is_finite(w->ask);
    if (bad_side || (finite & finite_quote) == 0 || w->S <= 0.0 || w->K <= 0.0) {
        return PL_INVALID_INPUT;
    }
    if (w->T <= 0.0) {
        return PL_EXPIRED;
    }
    if (w->bid <= 0.0) {
        return PL_NO_BID;
    }
    if (w->ask < w->bid) {
        return PL_CROSSED;
    }
    return PL_OK;
}

/* A result without values: status and flags, pl_nan() in every field. */
static void finish(struct pl_model_result *out, uint8_t status, uint8_t flags) {
    out->status = status;
    out->flags = flags;
    set_nan(out->values);
}

/* The rounding_band flag of the row (reference.py:95). */
static uint8_t band_flags(const struct pl_objective *o) {
    return (o->band != 0) ? (uint8_t)PL_FLAG_ROUNDING_BAND : 0u;
}

static uint8_t brent_status(int status) {
    switch (status) {
    case PL_BRENT_BELOW_MIN:
        return PL_BELOW_MIN;
    case PL_BRENT_ABOVE_MAX:
        return PL_ABOVE_MAX;
    default:
        return PL_NOT_CONVERGED;
    }
}

/* The solve and the greek step of a row that passed the pre-engine checks (reference.py:94-109).
 * Returns PL_EVAL_DEFECT where Python raises. */
static enum pl_eval_error solve_row(const struct pl_row *w, int model, const struct pl_params *p,
                                    double mid, double lo, struct pl_model_result *out,
                                    uint32_t *engine_evals) {
    int defect = 0;
    const double tau = pl_tau_v(w->S, w->K, w->T, w->r, w->q, &defect);
    if (defect != 0) {
        return PL_EVAL_DEFECT; /* reference.py:94, outside the try */
    }
    struct pl_objective o;
    model_objective(&o, model, w, mid, p, tau);
    uint8_t flags = 0u;
    struct pl_brent_result br;
    pl_brent(&o, lo, p->sigma_hi, (lo + p->sigma_hi) / 2.0, PL_BRENT_ACCURACY,
             PL_BRENT_MAX_EVALUATIONS, &br);
    /* reference.py:224: a BAW evaluation that baw_admit refuses raises before the count; the
     * refusal ends the solve, so it is the last objective call. reference.py:304: an ALO
     * evaluation that the pre check refuses raises before the count (o.uncounted). */
    const uint32_t refused = ((o.flags & PL_FLAG_ADMIT_EXCLUDED) != 0u) ? 1u : 0u;
    *engine_evals += (uint32_t)br.evaluations - refused - o.uncounted;
    if (br.status == PL_BRENT_DEFECT) {
        return PL_EVAL_DEFECT;
    }
    if (br.status == PL_BRENT_DOMAIN) {
        finish(out, PL_MODEL_DOMAIN, (uint8_t)(flags | o.flags | band_flags(&o)));
        return PL_EVAL_OK;
    }
    const double band = 1e-9 * pl_max(1.0, mid);
    if (pl_fabs(br.f_lo) <= band || pl_fabs(br.f_hi) <= band) {
        flags = (uint8_t)(flags | PL_FLAG_BOUNDARY_AMBIGUOUS);
    }
    if (br.status != PL_BRENT_OK) {
        const double intrinsic = (w->side == 0) ? w->S - w->K : w->K - w->S;
        if (br.status == PL_BRENT_BELOW_MIN && mid < pl_max(intrinsic, 0.0)) {
            flags = (uint8_t)(flags | PL_FLAG_BELOW_INTRINSIC);
        }
        finish(out, brent_status(br.status), (uint8_t)(flags | o.flags | band_flags(&o)));
        return PL_EVAL_OK;
    }
    if (model == PL_MODEL_ALO && o.last_sigma != br.root) {
        return PL_EVAL_DEFECT; /* AloRunDefect('alo-iv-call'): the last Brent call is at the root */
    }
    const int g = pl_greeks_at(&o, br.root, out->values, engine_evals);
    if (g == PL_GREEKS_DEFECT) {
        return PL_EVAL_DEFECT;
    }
    if (g == PL_GREEKS_DOMAIN) {
        finish(out, PL_MODEL_DOMAIN, (uint8_t)(flags | o.flags | band_flags(&o)));
        return PL_EVAL_OK;
    }
    flags = (uint8_t)(flags | o.flags | band_flags(&o));
    if (*(out->values + PL_VEGA) * 100.0 < 1e-12) {
        flags = (uint8_t)(flags | PL_FLAG_FLAT_VEGA);
    }
    out->status = PL_OK;
    out->flags = flags;
    return PL_EVAL_OK;
}

/* The C contract of the parameters: crr_steps in [1, PL_CRR_MAX_STEPS] (the stack lattice bound;
 * Python raises for steps < 1 in sigma_lo), kappa_cap > 0.0 and h_r >= 0.0 (Python sigma_lo
 * divides by kappa_cap and takes the square root of |b| + h_r), baw_newton_max in [0,
 * PL_BAW_NEWTON_MAX] (the cap of the critical-price loop; the case value is the maximum). */
static int params_ok(const struct pl_params *p) {
    const int steps_ok = p->crr_steps >= 1 && p->crr_steps <= PL_CRR_MAX_STEPS;
    const int cap_ok = p->baw_newton_max >= 0 && p->baw_newton_max <= PL_BAW_NEWTON_MAX;
    const int plant_ok = p->alo_plant_site >= 0 && p->alo_plant_site <= PL_ALO_PLANT_SITES;
    const int force_ok = p->alo_force >= 0 && p->alo_force <= PL_ALO_FORCES;
    return steps_ok && cap_ok && plant_ok && force_ok && p->kappa_cap > 0.0 && p->h_r >= 0.0;
}

/* The read-back of the ALO rates before sigma_lo (models.sigma_lo calls alo_equation, whose
 * read_back divides 1.0 by exp(r T) and exp(q T)): 1 when Python raises ZeroDivisionError. */
static int alo_rates_raise(const struct pl_row *row) {
    double r1 = 0.0;
    double q1 = 0.0;
    double s1 = 0.0;
    pl_unit(row->T, row->r, row->q, 1.0, &r1, &q1, &s1);
    struct pl_alo_rates rates;
    pl_alo_equation(r1, q1, &rates);
    return rates.defect;
}

/* The defect result: status PL_INVALID_INPUT, flags 0, pl_nan() values and a count of 0, for the
 * outputs that are not NULL. */
static enum pl_eval_error defect_result(struct pl_model_result *out, uint32_t *engine_evals) {
    if (out != NULL) {
        finish(out, PL_INVALID_INPUT, 0u);
    }
    if (engine_evals != NULL) {
        *engine_evals = 0u;
    }
    return PL_EVAL_DEFECT;
}

/* The BAW pre-engine row check (reference.py:214-216): the volatility-free checks of baw_admit
 * at r' = r T and q' = q T. Returns 1 when the row is in scope and not admitted. */
static int baw_row_excluded(const struct pl_row *row) {
    double r1 = 0.0;
    double q1 = 0.0;
    double s1 = 0.0;
    pl_unit(row->T, row->r, row->q, 1.0, &r1, &q1, &s1);
    int admitted = 0;
    const int in_scope = pl_baw_admit_rates(row->side, r1, q1, &admitted);
    return in_scope != 0 && admitted == 0;
}

enum pl_eval_error pl_evaluate(const struct pl_row *row, int model, const struct pl_params *p,
                               struct pl_model_result *out, uint32_t *engine_evals) {
    if (out == NULL) {
        return PL_EVAL_DEFECT;
    }
    finish(out, PL_INVALID_INPUT, 0u);
    if (engine_evals == NULL) {
        return PL_EVAL_DEFECT;
    }
    *engine_evals = 0u;
    if (row == NULL || p == NULL || model < PL_MODEL_BSM || model > PL_MODEL_ALO) {
        return PL_EVAL_DEFECT;
    }
    if (params_ok(p) == 0) {
        return PL_EVAL_DEFECT;
    }
    const uint8_t first = input_status(row);
    if (first != PL_OK) {
        finish(out, first, 0u);
        return PL_EVAL_OK;
    }
    const double mid = (row->bid + row->ask) / 2.0;
    if (model == PL_MODEL_ALO && alo_rates_raise(row)) {
        return defect_result(out, engine_evals); /* sigma_lo('alo'): read_back raises */
    }
    const double lo = pl_sigma_lo(model, row->side, row->T, row->r, row->q, p);
    if (lo >= p->sigma_hi) {
        finish(out, PL_MODEL_DOMAIN, 0u);
        return PL_EVAL_OK;
    }
    if (model == PL_MODEL_CRR && pl_crr_domain_ok(row->T, row->r, row->q, p) == 0) {
        finish(out, PL_MODEL_DOMAIN, 0u);
        return PL_EVAL_OK;
    }
    if (model == PL_MODEL_BAW && baw_row_excluded(row)) {
        finish(out, PL_MODEL_DOMAIN, (uint8_t)PL_FLAG_ADMIT_EXCLUDED);
        return PL_EVAL_OK;
    }
    const enum pl_eval_error e = solve_row(row, model, p, mid, lo, out, engine_evals);
    if (e != PL_EVAL_OK) {
        finish(out, PL_INVALID_INPUT, 0u);
        *engine_evals = 0u;
    }
    return e;
}
