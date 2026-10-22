/* Transcribed from QuantLib 1.43 (QL_VERSION 1.43; retained source
 * benchmarks/project/third_party/sources/QuantLib-1.43.tar.gz, sha256
 * b41206ccc4ba39b5e86bdc940d51138222b352f79d2c6fc68649f9c9bbe58701), via optionlab/models.py lines
 * 357-371, 397-428, 450-456, 481-496, 528-542 (the ALO sigma_lo of Appendix I-ALO R9, E-ALO-1;
 * Task 10b) and optionlab/params.py: ql/pricingengines/vanilla/
 * binomialengine.hpp 74-172, ql/methods/lattices/binomialtree.hpp 42-47, 84-101,
 * ql/methods/lattices/binomialtree.cpp 37-48, ql/methods/lattices/bsmlattice.hpp 71-87,
 * ql/processes/blackscholesprocess.cpp 74-82, 108-129,
 * ql/pricingengines/vanilla/discretizedvanillaoption.cpp 47-77, ql/pricingengines/greeks.cpp
 * 25-35. QuantLib license (BSD-3-Clause): the copyright notices, conditions and disclaimer are in
 * NOTICE-QuantLib.md of this example (LR-EX 2026-10-18). */
#include "pl_crr.h"
#include "pl_alo_equation.h"
#include "pl_baw.h"
#include "pl_black.h"
#include "pl_ieee.h"
#include "pl_types.h"
#include <math.h>

/* The CRR engine, sigma_lo and the CRR domain check (specs/project/models.md "CRR", "sigma_lo and
 * the CRR domain" and "Case parameters"). Each function copies the cited optionlab function
 * statement by statement (spec 3.4; Amendment F item 8). A Python integer literal is the equal
 * double literal. The divisions of crr_mapped_tree are Python divisions (pl_py_div sets the
 * defect at a zero divisor); every division of the engine is models._div, which is IEEE C
 * division. The lattice is a struct pl_crr_lattice on the caller's stack (arrays of
 * 2 * PL_CRR_MAX_STEPS + 1 and PL_CRR_MAX_STEPS + 1 doubles); its loops are in
 * pl_crr_lattice.c, which checks steps and i before it forms any position. */

/* yieldtermstructure.cpp:30 dt = 0.0001 (models.RATE_DT). */
static const double PL_CRR_RATE_DT = 0x1.a36e2eb1c432dp-14;
/* The Python literals 1e-4 and 1.001 of models.sigma_lo (models.py:486-489). */
static const double PL_CRR_SIGMA_MIN = 0x1.a36e2eb1c432dp-14;
static const double PL_CRR_SIGMA_FACTOR = 0x1.004189374bc6ap+0;

/* Every member pl_nan(). */
static void all_nan(struct pl_engine_result *out) {
    const double nan = pl_nan();
    out->value = nan;
    out->delta = nan;
    out->gamma = nan;
    out->theta = nan;
    out->vega = nan;
    out->rho = nan;
    out->dividend_rho = nan;
    out->strike_sensitivity = nan;
    out->strike_gamma = nan;
}

/* models.crr_mapped_tree (models.py:358-371). Python stops at its first raise; C evaluates every
 * statement, and each raise point sets the same defect flag, so the flag equals "Python raises". */
void pl_crr_mapped_tree(double T, double r, double q, double sigma, int steps,
                        struct pl_crr_tree *out, int *defect) {
    int raised = 0;
    double r1;
    double q1;
    double s1;
    if (T < 0.0) {
        raised = 1; /* mapping.unit: math.sqrt(T) raises ValueError (models.py:361) */
    }
    pl_unit(T, r, q, sigma, &r1, &q1, &s1);
    const double v = s1;
    const double d_r = pl_discount(r1, 1.0, &raised);
    const double rz = pl_implied_rate(pl_py_div(1.0, d_r, &raised), 1.0);
    const double d_q = pl_discount(q1, 1.0, &raised);
    const double qz = pl_implied_rate(pl_py_div(1.0, d_q, &raised), 1.0);
    const double maturity = 1.0;
    const double dt = pl_py_div(maturity, (double)steps, &raised);
    const double forward_r = pl_forward_rate(rz, 0.0, 0.0 + PL_CRR_RATE_DT, &raised);
    const double forward_q = pl_forward_rate(qz, 0.0, 0.0 + PL_CRR_RATE_DT, &raised);
    const double drift = forward_r - forward_q - 0.5 * v * v;
    const double drift_per_step = drift * dt;
    const double dx = pl_sqrt(v * v * (0.0 + dt) - v * v * 0.0);
    const double disc = pl_exp(-rz * dt);
    const double theta_r = pl_zero_rate(r1, 0.0, &raised);
    const double theta_q = pl_zero_rate(q1, 0.0, &raised);
    if (raised != 0) {
        const double nan = pl_nan();
        out->dx = nan;
        out->drift_per_step = nan;
        out->disc = nan;
        out->theta_r = nan;
        out->theta_q = nan;
        out->theta_v = nan;
        *defect = 1;
        return;
    }
    out->dx = dx;
    out->drift_per_step = drift_per_step;
    out->disc = disc;
    out->theta_r = theta_r;
    out->theta_q = theta_q;
    out->theta_v = s1;
}

/* models.crr_engine (models.py:397-428). The lattice (growth, reset and each rollback step) is
 * in pl_crr_lattice.c; this function keeps the Python order of the checks, the rollback loop, the
 * copies va2 (after i == 2) and va1 (after i == 1) and the greeks. */
enum pl_engine_status pl_crr_engine(int side, double S, double K, const struct pl_crr_tree *tree,
                                    int steps, int american, int with_theta, int greeks,
                                    struct pl_engine_result *out) {
    struct pl_crr_lattice lat;
    double va2[3] = {0.0, 0.0, 0.0};
    double va1[2] = {0.0, 0.0};
    int va2_set = 0;
    int refused = 0;
    all_nan(out);
    if (steps < 2) {
        return PL_ENGINE_QL_ERROR; /* "Expect 3 nodes in grid at second step" */
    }
    const double dx = tree->dx;
    const double pu = 0.5 + 0.5 * tree->drift_per_step / dx;
    const double pd = 1.0 - pu;
    if (!(pu <= 1.0)) {
        return PL_ENGINE_QL_ERROR; /* "negative probability" */
    }
    if (!(pu >= 0.0)) {
        return PL_ENGINE_QL_ERROR; /* "negative probability" */
    }
    lat.side = side;
    lat.steps = steps;
    lat.american = american;
    lat.S = S;
    lat.K = K;
    lat.dx = dx;
    lat.pu = pu;
    lat.pd = pd;
    lat.disc = tree->disc;
    if (pl_crr_lattice_reset(&lat) != 0) {
        return PL_ENGINE_QL_ERROR; /* steps > PL_CRR_MAX_STEPS: the stack scratch bound */
    }
    for (int i = steps - 1; i >= 0; i--) {
        refused |= pl_crr_lattice_step(&lat, i);
        if (i == 2) {
            *va2 = *lat.values;
            *(va2 + 1) = *(lat.values + 1);
            *(va2 + 2) = *(lat.values + 2);
            va2_set = 1;
        } else if (i == 1) {
            *va1 = *lat.values;
            *(va1 + 1) = *(lat.values + 1);
        }
    }
    if (refused != 0) {
        return PL_ENGINE_QL_ERROR; /* unreachable: 2 <= steps <= PL_CRR_MAX_STEPS and 0 <= i */
    }
    const double p0 = *lat.values;
    if (greeks == 0) {
        out->value = p0;
        return PL_ENGINE_OK;
    }
    if (va2_set == 0) {
        return PL_ENGINE_PY_DEFECT; /* steps == 2: va2 is None, va2[2] raises TypeError */
    }
    /* growth position steps + k holds Python growth[k]; 2 <= steps here, so k = -2 ... 2 is in
     * [0, 2 * steps]. */
    const double *growth = lat.growth + steps;
    const double p2u = *(va2 + 2);
    const double p2m = *(va2 + 1);
    const double p2d = *va2;
    const double s2u = *(growth + 2);
    const double s2m = *growth;
    const double s2d = *(growth - 2);
    const double delta2u = (p2u - p2m) / (s2u - s2m);
    const double delta2d = (p2m - p2d) / (s2m - s2d);
    const double gamma = (delta2u - delta2d) / ((s2u - s2d) / 2.0);
    const double p1u = *(va1 + 1);
    const double p1d = *va1;
    const double s1u = *(growth + 1);
    const double s1d = *(growth - 1);
    const double delta = (p1u - p1d) / (s1u - s1d);
    out->value = p0;
    out->delta = delta;
    out->gamma = gamma;
    if (with_theta != 0) {
        const double r = tree->theta_r;
        const double q = tree->theta_q;
        const double v = tree->theta_v;
        const double u = S;
        out->theta = r * p0 - (r - q) * u * delta - 0.5 * v * v * u * u * gamma;
    }
    return PL_ENGINE_OK;
}

/* models.crr_result (models.py:450-452): the tree before models._guard; the engine never raises
 * ZeroDivisionError (every engine division is models._div), so _guard never runs it again. */
enum pl_engine_status pl_crr_result(int side, double S, double K, double T, double r, double q,
                                    double sigma, int steps, int american, int greeks,
                                    struct pl_engine_result *out) {
    struct pl_crr_tree tree;
    int defect = 0;
    pl_crr_mapped_tree(T, r, q, sigma, steps, &tree, &defect);
    if (defect != 0) {
        all_nan(out);
        return PL_ENGINE_PY_DEFECT;
    }
    return pl_crr_engine(side, S, K, &tree, steps, american, 1, greeks, out);
}

/* models.sigma_lo (models.py:506-518). Python max(a, b) and max(a, b, c) are pl_max(a, b) and
 * pl_max(pl_max(a, b), c) (the first maximal argument; a NaN later argument never wins). */
double pl_sigma_lo(int model, int side, double T, double r, double q, const struct pl_params *p) {
    const double hr = p->h_r;
    if (model == PL_MODEL_BSM) {
        return PL_CRR_SIGMA_MIN;
    }
    if (model == PL_MODEL_CRR) {
        const double sdt = sqrt(T / (double)p->crr_steps);
        const double crr = PL_CRR_SIGMA_FACTOR * (pl_fabs(r - q) + hr) * sdt;
        return pl_max(PL_CRR_SIGMA_MIN, crr);
    }
    if (model == PL_MODEL_ALO) {
        /* Appendix I-ALO R9 and R12 E-ALO-1 (models.py:536-542): (rho, delta) = (r, q) for a put,
         * (q, r) for a call; e = alo_equation(r T, q T); FP-A: C 0.75, d = rho - delta; FP-B:
         * C 0.003, d = delta - rho; max(1e-4, (C max(0, d + h_r)) sqrt(T)). A read-back that
         * raises (pl_evaluate checks it first) gives pl_nan(). */
        const double rho = (side == 1) ? r : q;
        const double dl = (side == 1) ? q : r;
        double r1 = 0.0;
        double q1 = 0.0;
        double s1 = 0.0;
        pl_unit(T, r, q, 1.0, &r1, &q1, &s1);
        struct pl_alo_rates rates;
        pl_alo_equation(r1, q1, &rates);
        if (rates.defect != 0) {
            return pl_nan();
        }
        const int fp_a = rates.equation == PL_ALO_FP_A;
        const double c = fp_a ? 0.75 : 0.003;
        const double d = fp_a ? rho - dl : dl - rho;
        return pl_max(PL_CRR_SIGMA_MIN, (c * pl_max(0.0, d + hr)) * sqrt(T));
    }
    const double b = (side == 0) ? (r - q) : (q - r);
    double trig = 0.0;
    if (b < 0.0) {
        trig = PL_CRR_SIGMA_FACTOR * (pl_fabs(b) + hr) * sqrt(T) / 2.0;
    }
    if (model == PL_MODEL_BAW) {
        /* Appendix G-BAW R9 and erratum F3 (models.py:512-514): max(1e-4, sigma_trig) */
        return pl_max(PL_CRR_SIGMA_MIN, trig);
    }
    const double carry = sqrt(2.0 * (pl_fabs(b) + hr) / p->kappa_cap);
    return pl_max(pl_max(PL_CRR_SIGMA_MIN, trig), carry);
}

/* The lambda g of models.crr_domain_ok (models.py:494). */
static double crr_g(double s, double b, double sdt) { return s - (s * s / 2.0 + b) * sdt; }

/* models.crr_domain_ok (models.py:491-496). */
int pl_crr_domain_ok(double T, double r, double q, const struct pl_params *p) {
    const double sdt = sqrt(T / (double)p->crr_steps);
    const double b = pl_fabs(r - q) + p->h_r;
    if (!(crr_g(pl_sigma_lo(PL_MODEL_CRR, 0, T, r, q, p), b, sdt) >= 0.0)) {
        return 0; /* Python `and`: the second end is not evaluated */
    }
    return crr_g(p->sigma_hi + p->h_sigma, b, sdt) >= 0.0;
}

/* optionlab.params.CASE = CaseParams(0.04, 0.012, 100, baw_newton_max=MANIFEST_NEWTON_MAX) with
 * the defaults sigma_hi 5.0, kappa_cap 50.0, h_r 1e-4, h_sigma 1e-3 and the test-only planted
 * S* off (params.py:78-91); baw_newton_max is the case manifest value 40 (PL_BAW_NEWTON_MAX). */
void pl_case_params(struct pl_params *p) {
    p->crr_steps = 100;
    p->sigma_hi = 5.0;
    p->kappa_cap = 50.0;
    p->h_r = 0x1.a36e2eb1c432dp-14;
    p->h_sigma = 0x1.0624dd2f1a9fcp-10;
    p->baw_newton_max = PL_BAW_NEWTON_MAX;
    p->baw_plant_nonfinite_sstar = 0;
    p->alo_plant_site = 0;
    p->alo_force = 0;
}
