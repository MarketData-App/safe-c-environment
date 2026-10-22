#pragma once
#include "pl_black.h"
#include "pl_solver.h"
#include "pl_types.h"
#include <stdint.h>

/* The spec 3.3 row evaluation of one model (specs/project/models.md "Row evaluation"), as
 * optionlab.reference (reference.py:20-109) and optionlab.mapping (mapping.py:16-38) compute it:
 * tau_V, the order-5 check, the price dispatch, the greek step with the Amendment B3 chain rule,
 * and evaluate with the status order, the flags and the G3.7 engine-evaluation count. Every
 * Python raise point on the row path (the Task 11 audit table) gives a run defect, never a
 * status. Pure functions; the only memory they touch is the caller's objects. */

/* The mask of the models whose C engine is wired (ruling 46): MODELS5 since Task 10b wired ALO
 * (the ALO slot defect stub is gone). */
#define PL_MASK_WIRED PL_MASK_MODELS5

/* reference.tau_v (reference.py:27-31): ((4 QL_EPSILON) D_r) max(F, K) with D_r = discount(r T,
 * 1.0), D_q = discount(q T, 1.0) and F = (S D_q) / D_r. Sets *defect = 1 where Python raises: a
 * zero exponential in either discount (models.py:96), D_r == 0.0 (reference.py:30), T < 0.0
 * (math.sqrt of mapping.unit); the return value is then meaningless. *defect is only set. */
double pl_tau_v(double S, double K, double T, double r, double q, int *defect);

/* reference.Checker.__call__ (reference.py:36-39) with tau = o->tau: returns 1 and sets
 * o->domain = 1 when v is not finite or v < -tau; otherwise sets o->band = 1 when v < 0.0 (-0.0
 * is not negative) and returns 0. o is not NULL (C contract: NULL returns 1 and changes
 * nothing). */
int pl_check_value(struct pl_objective *o, double v);

/* models.price (models.py:485-492) and, for BAW, reference.price_function (reference.py:54-61):
 * the engine value of the model through the unit-maturity mapping, value only. PL_MODEL_BSM,
 * PL_MODEL_BJS: the engine with greeks off; PL_MODEL_CRR: the American CRR engine with
 * p->crr_steps steps; PL_MODEL_BAW: pl_baw_price (baw_admit first; a point in scope and not
 * admitted sets PL_FLAG_ADMIT_EXCLUDED in *flags and gives PL_ENGINE_QL_ERROR); PL_MODEL_ALO:
 * pl_alo_result (alo.price: the pre check, then the engine; Task 10b). PL_ENGINE_QL_ERROR for a
 * QuantLib error (ModelDefect, the ALO pre check included), PL_ENGINE_PY_DEFECT where Python
 * raises (a zero discount, a BAW or ALO run defect, and any other model). *value is pl_nan()
 * unless PL_ENGINE_OK. Only PL_MODEL_BAW sets *flags. p, value and flags are not NULL (C contract:
 * NULL gives PL_ENGINE_PY_DEFECT and writes only the non-NULL outputs). */
enum pl_engine_status pl_price(int model, int side, double S, double K, double T, double r,
                               double q, double sigma, const struct pl_params *p, double *value,
                               uint8_t *flags);

/* Results of pl_price_and_greeks. */
enum pl_greeks_status { PL_GREEKS_OK = 0, PL_GREEKS_DOMAIN = 1, PL_GREEKS_DEFECT = 2 };

/* reference.price_and_greeks (reference.py:66-70, 45-64; mapping.greeks_from_unit): tau_V of
 * the row, then the engine with greeks at sigma (BSM and BjS: vega and rho from the engine; CRR:
 * vega and rho by the declared bumps; BAW: pl_baw_greeks_at; ALO: pl_alo_price_and_greeks, Task
 * 10b), theta = theta_U / T / 365, vega and rho per point. values (PL_FIELDS doubles: sigma,
 * price, delta, gamma, theta, vega, rho) is pl_nan() in every field unless PL_GREEKS_OK.
 * PL_GREEKS_DOMAIN: an engine value fails the order-5 check, an engine reports a QuantLib error,
 * a result field is not finite, or (BAW) baw_admit refuses a point or (BAW, ALO) no row-side or
 * row-segment stencil exists. PL_GREEKS_DEFECT: a Python raise point (tau_v, a zero discount in
 * the engine or a bump, a BAW or ALO run defect), an unknown model, or a NULL argument (C
 * contract). *band receives the Checker band, *flags the BAW bits 16, 32 and 64 or the ALO bits
 * 16 and 32, and *engine_evals is increased by 1 for the engine greek call and 1 per bump or
 * stencil evaluation, the call that stops included; for ALO only the stencil points count (H17:
 * the price at sigma is not counted). row->bid and row->ask are not read. */
int pl_price_and_greeks(int model, const struct pl_row *row, double sigma,
                        const struct pl_params *p, double values[PL_FIELDS], int *band,
                        uint8_t *flags, uint32_t *engine_evals);

/* reference._engine_greeks (reference.py:45-64) with mapping.greeks_from_unit (mapping.py:16-38)
 * at iv for the model objective o (o->model, o->row, o->params not NULL, o->tau; in
 * src/pl_greeks.c): the engine with greeks, the order-5 check of its value and of each CRR bump
 * (o->band, o->domain), the chain rule, the finiteness of the seven values. Returns
 * PL_GREEKS_OK (values written), PL_GREEKS_DOMAIN or PL_GREEKS_DEFECT (values unchanged), and
 * increases *engine_evals by 1 per engine call, the stopping call included. Model PL_MODEL_BAW
 * dispatches to pl_baw_greeks_at. */
int pl_greeks_at(struct pl_objective *o, double iv, double *values, uint32_t *engine_evals);

/* reference.baw_greeks (reference.py:83-147) at iv for the BAW objective o (in
 * src/pl_baw_greeks.c): the row side, the row point with every engine greek, then the record R6
 * table (European branch: engine greeks, theta case (a); exercise side: exact +-1 and 0;
 * continuation side: the R7 stencils for S, sigma, r and T). Each greek point runs baw_admit
 * and the S* side test first. Returns PL_GREEKS_OK (values written; bit 32 into o->flags when a
 * stencil switched or halved), PL_GREEKS_DOMAIN (bit 64 into o->flags when baw_admit refuses a
 * point, bit 16 when no row-side stencil exists after PL_BAW_HALVINGS halvings; values
 * unchanged) or PL_GREEKS_DEFECT where Python raises. *engine_evals is increased by 1 for the
 * row point and 1 per evaluated greek point. */
int pl_baw_greeks_at(struct pl_objective *o, double iv, double *values, uint32_t *engine_evals);

/* reference.alo_greeks (reference.py:178-218) at iv for the ALO objective o after its Brent solve
 * (in src/pl_alo_greeks.c): the price is o->last_value (record IV-call fact: the last Brent value,
 * no separate call), then the I2.6 stencils (record R6). Returns PL_GREEKS_OK (values written;
 * bit 32 into o->flags when a rho or theta stencil switched or halved), PL_GREEKS_DOMAIN (bit 16
 * into o->flags when no row-segment stencil exists after PL_ALO_HALVINGS halvings; values
 * unchanged) or PL_GREEKS_DEFECT where Python raises. *engine_evals is increased by 1 per greek
 * point that passes the pre check (H17). */
int pl_alo_greeks_at(struct pl_objective *o, double iv, double *values, uint32_t *engine_evals);

/* reference.evaluate (reference.py:72-109) of one row and one model (enum pl_model). out
 * receives the status (spec 3.3 order: invalid input, expired, no bid, crossed, the pre-engine
 * sigma_lo >= sigma_hi, CRR domain and BAW row checks (baw_admit_rates: bit 64), then Brent
 * with guess (lo + hi) / 2 on [sigma_lo, p->sigma_hi], accuracy PL_BRENT_ACCURACY and
 * PL_BRENT_MAX_EVALUATIONS), the flags (1 below_intrinsic, 2 boundary_ambiguous, 4 flat_vega, 8
 * rounding_band, and for BAW 16 stencil_unresolved, 32 stencil_switched, 64 admit_excluded, in
 * the Python order) and the seven values (pl_nan() unless PL_OK). *engine_evals receives the
 * G3.7 count: every engine price evaluation (each Brent call, the call that stops included; a
 * BAW evaluation that baw_admit refuses does not run and is not counted), +1 for the greek call
 * and +1 per bump or stencil evaluation; 0 for a row stopped before the engine.
 * ALO (Task 10b, reference.py:297-320): sigma_lo of record R9 reads the rates back first (a zero
 * exponential raises), an ALO Brent evaluation that the pre check refuses is not counted, the
 * root must be the sigma of the last Brent evaluation (record IV-call fact) and its value is the
 * price, the greek step adds the stencil points (H17), and the ALO bits 16 and 32 follow
 * pl_alo_greeks_at.
 * Returns PL_EVAL_DEFECT exactly where Python raises (pl_tau_v, a zero discount in a price or
 * bump evaluation, a CRR bump division by h_sigma or h_r == 0.0, the solver.py:23, :26, :35
 * ValueError, a BAW run defect: a cap hit or a non-finite S*; an ALO run defect: a failed check
 * of the shared NaN check or a cap excess, the read-back division of alo_equation, a stencil
 * division, the IV-call fact), and for a C contract violation: a NULL argument, a model outside 0
 * to PL_MODEL_ALO, p->crr_steps outside 1 to PL_CRR_MAX_STEPS, p->kappa_cap not > 0.0, p->h_r not
 * >= 0.0, p->baw_newton_max outside 0 to PL_BAW_NEWTON_MAX, p->alo_plant_site outside 0 to
 * PL_ALO_PLANT_SITES or p->alo_force outside 0 to PL_ALO_FORCES; the run then fails as a whole
 * (KERNEL_FAILURE) and out holds status PL_INVALID_INPUT, flags 0 and pl_nan() values,
 * *engine_evals 0. Otherwise PL_EVAL_OK. */
enum pl_eval_error pl_evaluate(const struct pl_row *row, int model, const struct pl_params *p,
                               struct pl_model_result *out, uint32_t *engine_evals);
