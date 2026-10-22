#pragma once
#include "pl_black.h"
#include "pl_types.h"

/* QuantLib 1.43 BinomialVanillaEngine<CoxRossRubinstein> for the unit-maturity problem, the
 * Brent lower end sigma_lo, the CRR domain check and the case parameters, as optionlab.models
 * and optionlab.params compute them (specs/project/models.md "CRR", "sigma_lo and the CRR
 * domain" and "Case parameters"). Pure functions; the only memory they touch is the caller's
 * output objects and the stack scratch of pl_crr_engine. */

/* The tree constants of models.crr_mapped_tree (dx, driftPerStep, disc) and its theta_rates
 * (zero rates of r' and q' at t = 0, and sigma'). */
struct pl_crr_tree {
    double dx, drift_per_step, disc, theta_r, theta_q, theta_v;
};

/* models.crr_mapped_tree (models.py:357-371). Sets *defect = 1 where Python raises: a
 * ZeroDivisionError of discount, zero_rate, forward_rate or maturity / steps, and the ValueError
 * of math.sqrt in mapping.unit (T < 0.0). With the defect set every member of *out is pl_nan().
 * *defect is only set, never cleared. */
void pl_crr_mapped_tree(double T, double r, double q, double sigma, int steps,
                        struct pl_crr_tree *out, int *defect);

/* The lattice of one pl_crr_engine call: stack scratch of the caller (no allocation). growth
 * position j + steps holds Python growth[j] = S * exp(j * dx) for j = -steps ... steps; values
 * position j holds Python values[j]. */
struct pl_crr_lattice {
    int side, steps, american;
    double S, K, dx, pu, pd, disc;
    double growth[2 * PL_CRR_MAX_STEPS + 1];
    double values[PL_CRR_MAX_STEPS + 1];
};

/* models.crr_engine growth and reset (models.py:406-408), in pl_crr_lattice.c: every growth
 * position in increasing j, then values[j] = max(0.0, payoff(growth[2j - steps])) for j = 0 ...
 * steps. Returns 0, or 1 without writing when steps is outside [2, PL_CRR_MAX_STEPS]. */
int pl_crr_lattice_reset(struct pl_crr_lattice *l);

/* One rollback step i of models.crr_engine (models.py:410-414), in pl_crr_lattice.c: values[j] =
 * (pd values[j] + pu values[j + 1]) disc for j = 0 ... i, then with american the maximum with
 * payoff(growth[2j - i]). Returns 0, or 1 without writing unless 2 <= steps <=
 * PL_CRR_MAX_STEPS and 0 <= i < steps. */
int pl_crr_lattice_step(struct pl_crr_lattice *l, int i);

/* models.crr_engine (models.py:397-428) with theta_rates = tree theta members when with_theta
 * != 0, else None. steps < 2 (ModelDefect) and steps > PL_CRR_MAX_STEPS (the stack scratch
 * bound) give PL_ENGINE_QL_ERROR, and so do !(pu <= 1.0) and !(pu >= 0.0) ("negative
 * probability"). greeks != 0 with steps == 2 gives PL_ENGINE_PY_DEFECT (Python raises TypeError:
 * va2 is never set). greeks == 0 sets only value; with greeks, value, delta and gamma, and
 * theta when with_theta != 0. Every other member is pl_nan(), and every member is pl_nan() for
 * a status other than PL_ENGINE_OK. */
enum pl_engine_status pl_crr_engine(int side, double S, double K, const struct pl_crr_tree *tree,
                                    int steps, int american, int with_theta, int greeks,
                                    struct pl_engine_result *out);

/* models.crr_result (models.py:450-452): PL_ENGINE_PY_DEFECT (every member pl_nan()) when the
 * tree sets the defect, else the engine with the tree's theta rates. */
enum pl_engine_status pl_crr_result(int side, double S, double K, double T, double r, double q,
                                    double sigma, int steps, int american, int greeks,
                                    struct pl_engine_result *out);

/* models.sigma_lo (models.py:528-549): model PL_MODEL_BSM 1e-4; PL_MODEL_CRR
 * max(1e-4, 1.001 (|r - q| + h_r) sqrt(T / N)); PL_MODEL_BAW max(1e-4, sigma_trig) (Appendix
 * G-BAW R9, erratum F3); PL_MODEL_ALO max(1e-4, (C_e max(0, d_e + h_r)) sqrt(T)) with
 * e = alo_equation(r T, q T), C_A = 0.75, d_A = rho - delta, C_B = 0.003, d_B = delta - rho and
 * (rho, delta) = (r, q) for a put, (q, r) for a call (Appendix I-ALO R9, E-ALO-1; pl_nan() where
 * the read-back of alo_equation raises); any other model the BjS rule max(1e-4, sigma_trig,
 * sigma_carry). T >= 0.0 or NaN (Python raises ValueError for T < 0.0; the row path passes only
 * T > 0.0). */
double pl_sigma_lo(int model, int side, double T, double r, double q, const struct pl_params *p);

/* models.crr_domain_ok (models.py:491-496): 1 when g(sigma) = sigma - (sigma^2 / 2 + |r - q| +
 * h_r) sqrt(T / N) >= 0.0 at sigma_lo(CRR) and at sigma_hi + h_sigma, else 0. T as for
 * pl_sigma_lo. */
int pl_crr_domain_ok(double T, double r, double q, const struct pl_params *p);

/* optionlab.params.CASE (case version 1): crr_steps 100, sigma_hi 5.0, kappa_cap 50.0,
 * h_r 1e-4, h_sigma 1e-3, baw_newton_max PL_BAW_NEWTON_MAX (40, the case manifest value),
 * baw_plant_nonfinite_sstar 0, and the test-only alo_plant_site 0 and alo_force 0 (Task 10b). */
void pl_case_params(struct pl_params *p);
