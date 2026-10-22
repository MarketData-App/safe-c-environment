#pragma once
#include "pl_black.h"
#include "pl_types.h"
#include <stddef.h>
#include <stdint.h>

/* QuantLib 1.43 BaroneAdesiWhaleyApproximationEngine as optionlab.baw, optionlab.baw_admit and
 * the BAW lines of optionlab.reference compute it (specs/project/models.md "BAW (Amendment G)";
 * spec Appendix G-BAW). One C function per Python function, with the same operation order,
 * association and constants (Amendment F item 8). Pure functions; the only memory they touch is
 * the caller's output objects. Side 0 is a call, any other side a put (the Python code tests
 * side == CALL). */

/* baw_admit.NEWTON_MAX: the protected case parameter baw_newton_max (Appendix G-BAW R3; the case
 * manifest value, which the c-vectors part baw reads from optionlab.params.CASE). baw_admit
 * always uses this cap; a test parameter set changes only the cap of critical_price. */
#define PL_BAW_NEWTON_MAX 40
/* reference.HALVINGS: at most 4 halvings of a stencil step (record R7). */
#define PL_BAW_HALVINGS 4

/* The intermediates of one baw_admit call, in the order of cvectors.ADMIT_FIELDS: the locals
 * of optionlab.baw_admit.baw_admit when it returns. j is the replay index, x the last iterate,
 * LHS, RHS and bi the last map result, NC the last certificate result (-1.0 for None), exit
 * the position of the return statement in baw_admit (1 to 13). A quantity that the call did not
 * compute is pl_nan(). */
enum pl_baw_admit_field {
    PL_BAW_A_DR = 0,
    PL_BAW_A_DQ,
    PL_BAW_A_N,
    PL_BAW_A_M,
    PL_BAW_A_BT,
    PL_BAW_A_QU,
    PL_BAW_A_SU,
    PL_BAW_A_H,
    PL_BAW_A_SI,
    PL_BAW_A_KC,
    PL_BAW_A_Q,
    PL_BAW_A_J,
    PL_BAW_A_X,
    PL_BAW_A_LHS,
    PL_BAW_A_RHS,
    PL_BAW_A_BI,
    PL_BAW_A_NC,
    PL_BAW_A_EXIT
};
#define PL_BAW_ADMIT_FIELDS 18u
#define PL_BAW_ADMIT_MAX_FIELDS 32u

/* The result of pl_baw_admit. defect is 1 where the Python function raises (a ZeroDivisionError
 * of a plain division in certificate); the result then fails closed: in_scope 1 and admitted 0
 * (never "European branch, admitted"), and every caller treats it as a run defect first. */
struct pl_baw_admit {
    int in_scope;
    int admitted;
    int defect;
    size_t count;
    double values[PL_BAW_ADMIT_MAX_FIELDS];
};

/* The intermediates of one certificate call, in the order of cvectors.CERT_FIELDS (the locals
 * of baw_admit.certificate when it returns; exit is the position of its return statement, 1 to
 * 11). */
#define PL_BAW_CERT_FIELDS 33u

/* The seed of baroneadesiwhaleyengine.cpp:51-70 (baw_admit._seed). */
struct pl_baw_seed {
    double n, m, bT, qu, Su, h, Si;
};

/* baw_admit.discounts (baw_admit.py:40-42): D_r = 1.0 / exp(r1 * 1.0), D_q = 1.0 / exp(q1 * 1.0)
 * with IEEE division (models._div). */
void pl_baw_discounts(double r1, double q1, double *d_r, double *d_q);
/* baw_admit.close_n (baw_admit.py:44-49), QuantLib close(x, y, n). */
int pl_baw_close_n(double x, double y, double n);
/* baw_admit.black_formula (baw_admit.py:53-73) with discount 1.0 and displacement 0.0. Returns 0
 * with *value, or 1 where Python raises ModelDefect (a QuantLib check; order 5), *value then
 * unchanged. */
int pl_baw_black_formula(int side, double strike, double forward, double std_dev, double *value);
/* baw_admit._seed (baw_admit.py:75-90). */
void pl_baw_seed(int side, double K, double d_r, double d_q, double variance,
                 struct pl_baw_seed *out);
/* baw_admit._kcoef (baw_admit.py:92-95). */
double pl_baw_kcoef(double d_r, double variance);
/* baw_admit._qexp (baw_admit.py:97-100). */
double pl_baw_qexp(int side, double n, double kc);
/* baw_admit._map (baw_admit.py:102-116): (LHS, RHS, bi) at si. Returns 0, or 1 where
 * black_formula raises ModelDefect; the outputs are written only on 0. */
int pl_baw_map(int side, double si, double K, double d_r, double d_q, double variance, double Q,
               double *lhs, double *rhs, double *bi);
/* baw_admit._stop (baw_admit.py:118-120): 1 when not (|LHS - RHS| / K > 1e-6). */
int pl_baw_stop(double lhs, double rhs, double K);
/* baw_admit._update (baw_admit.py:122-125). */
double pl_baw_update(int side, double si, double K, double rhs, double bi);
/* baw_admit.certificate (baw_admit.py:167-210; record R4 item 4) at the iterate x0 with the map
 * result there and the cap. Returns N_C (0 to cap) or -1 for None; trace (PL_BAW_CERT_FIELDS
 * doubles) receives the intermediates (pl_nan() where not computed). *defect is set to 1 where
 * Python raises ZeroDivisionError (a plain division by zero); the return value is then -1.
 * cap >= 0. */
int pl_baw_certificate(int side, double x0, double K, double d_r, double d_q, double v, double Q,
                       double lhs, double rhs, double bi, int cap, double trace[PL_BAW_CERT_FIELDS],
                       int *defect);
/* baw_admit.baw_admit_rates (baw_admit.py:212-220): returns in_scope; *admitted receives the
 * second result. */
int pl_baw_admit_rates(int side, double r1, double q1, int *admitted);
/* baw_admit.baw_admit (baw_admit.py:222-248; record R4 with the errata F5): the branch gate,
 * the checks 2a-2f and the replay with certificate, cap PL_BAW_NEWTON_MAX. S is not read (the
 * Python function does not read it). out->count is PL_BAW_ADMIT_FIELDS. */
void pl_baw_admit(int side, double S, double K, double r1, double q1, double v,
                  struct pl_baw_admit *out);

/* baw_admit.critical_price (baw_admit.py:129-144; engine lines 39-138, record R3 and F6): S* and
 * the count of updates. *ql_error = 1 where Python raises ModelDefect (D_r > 1.0 or a QuantLib
 * check of the map; order 5); *cap_hit = 1 where the stop test still fails after newton_max
 * updates (BawRunDefect 'baw-cap'). Both return pl_nan(). The loop makes at most newton_max
 * updates; newton_max >= 0. *iterations receives the count of updates made. */
double pl_baw_critical_price(int side, double K, double d_r, double d_q, double variance,
                             int newton_max, int *iterations, int *cap_hit, int *ql_error);
/* baw_admit.sstar (baw_admit.py:146-153): the critical price, then plant != 0 replaces S* by
 * pl_nan(), then a non-finite S* is BawRunDefect 'baw-nonfinite-sstar'. PL_ENGINE_QL_ERROR for a
 * ModelDefect, PL_ENGINE_PY_DEFECT for a run defect (cap hit or non-finite S*), else
 * PL_ENGINE_OK with *sstar. */
enum pl_engine_status pl_baw_sstar(int side, double K, double d_r, double d_q, double variance,
                                   int newton_max, int plant, double *sstar, int *iterations);
/* baw.engine (baw.py:29-63; engine calculate, lines 140-236) of the mapped problem with
 * newton_max = p->baw_newton_max and the planted S* of p->baw_plant_nonfinite_sstar. European
 * branch (d_q >= 1.0 and a call, line 167): value and, with greeks != 0, delta, gamma, theta,
 * vega, rho and dividend_rho of the BlackCalculator. American branch: value only. Every member
 * that is not computed is pl_nan(). PL_ENGINE_QL_ERROR for a QuantLib check (S <= 0.0, the
 * BlackCalculator checks, D_r > 1.0 and the map checks of the critical price), PL_ENGINE_PY_DEFECT
 * for a run defect; every member is then pl_nan(). *iterations receives the count of updates of
 * the critical price (0 in the European branch and before the critical price). */
enum pl_engine_status pl_baw_engine(int side, double S, double K, double d_r, double d_q,
                                    double variance, int greeks, const struct pl_params *p,
                                    struct pl_engine_result *out, int *iterations);
/* models.baw_result (models.py:478-482): pl_mapped_inputs, then the engine. PL_ENGINE_PY_DEFECT
 * (every member pl_nan()) where mapped_inputs raises. */
enum pl_engine_status pl_baw_result(int side, double S, double K, double T, double r, double q,
                                    double sigma, int greeks, const struct pl_params *p,
                                    struct pl_engine_result *out, int *iterations);
/* reference.price_function('baw') (reference.py:54-61): baw_admit at the mapped point
 * (reference.baw_admitted), then the engine value (models.price). A point in scope and not
 * admitted sets PL_FLAG_ADMIT_EXCLUDED in *flags and gives PL_ENGINE_QL_ERROR (order 5);
 * a raise of baw_admit or of the engine gives PL_ENGINE_PY_DEFECT. *value is pl_nan() unless
 * PL_ENGINE_OK. */
enum pl_engine_status pl_baw_price(int side, double S, double K, double T, double r, double q,
                                   double sigma, const struct pl_params *p, double *value,
                                   uint8_t *flags);

/* The BAW branch of reference.price_and_greeks (reference.py:177-185) with the counter of
 * reference.evaluate: tau_V of the row, then reference.baw_greeks at sigma (record R6 greek
 * table, R7 stencil rule, errata F4 and R(a)-R(c)). Returns 0 OK (values written: sigma, price,
 * delta, gamma, theta, vega, rho) or 1 order 5 (values pl_nan()). *flags receives bit 32 on OK
 * when a stencil is one-sided, forward or backward where the default is another form, or
 * halved; bit 64 when baw_admit refuses a greek point; bit 16 when no row-side stencil exists
 * after PL_BAW_HALVINGS halvings. *band receives the Checker band. *engine_evals is increased by
 * 1 for the row point and 1 per greek point (G3.7). *defect = 1 (and the return value 1) where
 * Python raises on the row path (T > 0.0): tau_v, a cap hit or a non-finite S* (BawRunDefect), a
 * zero division of a stencil or of mapped_inputs, a raise of baw_admit. Precondition for that
 * claim: row->T > 0.0 (reference.evaluate gives EXPIRED first); a direct call with T == 0.0 gives
 * order 5 where mapping.greeks_from_unit would raise ZeroDivisionError (as pl_greeks_at does for
 * the other models). row->bid and row->ask are not read. Every
 * pointer is not NULL (C contract: a NULL argument gives 1 with *defect = 1 when defect is not
 * NULL). */
int pl_baw_price_and_greeks(const struct pl_row *row, double sigma, const struct pl_params *p,
                            double values[PL_FIELDS], int *band, uint8_t *flags,
                            uint32_t *engine_evals, int *defect);
