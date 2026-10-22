#pragma once
#include "pl_alo_equation.h"
#include "pl_black.h"
#include "pl_types.h"
#include <stddef.h>
#include <stdint.h>

/* QuantLib 1.43 QdFpAmericanEngine with accurateScheme = QdFpLegendreTanhSinhScheme(25, 5, 13,
 * 1e-8) and the fixed-point equation Auto (Andersen-Lake-Offengenden), as optionlab.alo and the
 * ALO lines of optionlab.reference compute it (specs/project/models.md "ALO (Amendment I)"; spec
 * Amendment I items I2, I3, I4.1, I13.3 and the approved record Appendix I-ALO with the errata
 * E-ALO-1 to E-ALO-6). One C function per Python function, with the same operation order,
 * association and constants (Amendment F item 8). Every function is pure: an engine evaluation
 * keeps its state on the caller's stack (no static mutable storage, no allocation), so the
 * functions are safe in concurrent batch workers. Side 0 is a call, side 1 a put. */

/* accurateScheme (qdfpamericanengine.cpp:417-421; Amendment I item I2.2; the protected case key
 * alo_scheme, which test_alo.c compares with the c-vectors macros PL_VEC_ALO_SCHEME_*). */
#define PL_ALO_SCHEME_NAME "accurateScheme"
#define PL_ALO_FP_EQUATION "Auto"
#define PL_ALO_GL_ORDER 25
#define PL_ALO_FP_STEPS 5
#define PL_ALO_CHEB_N 13
#define PL_ALO_CHEB_NODES 14
#define PL_ALO_TS_EPS 1e-8
/* QdPlusAmericanEngine(process, 14, Halley, 1e-8) with maxIter_ 10 (qdfpamericanengine.cpp:438-441,
 * qdplusamericanengine.cpp:262-265); the inner Brent has maxEvaluations 10 * maxIter_ = 100. */
#define PL_ALO_QDP_EPS 1e-8
#define PL_ALO_QDP_MAX_ITER 10
#define PL_ALO_QDP_BRENT_MAX 100
/* The tanh-sinh level cap (tanh_sinh_detail max_refinements 15; record R2). */
#define PL_ALO_TS_MAX_REFINEMENTS 15
/* The xMin factor of the QD+ evaluator: QL_EPSILON * 1e4 (qdplusamericanengine.cpp:56). */
#define PL_ALO_QDP_XMIN_FACTOR (PL_QL_EPSILON * 1e4)
/* At most 4 halvings of a rho or theta stencil step (record R6, the BAW erratum F4 form). */
#define PL_ALO_HALVINGS 4

/* The loop caps of record R3 (alo.CAPS): a count above its cap is a run defect (record R8). */
#define PL_ALO_CAP_HALLEY_MAX 10
#define PL_ALO_CAP_DOUBLING_MAX 1
#define PL_ALO_CAP_BRENT_MAX 101
#define PL_ALO_CAP_SWEEP_F_MAX 65
#define PL_ALO_CAP_SWEEP_NDD_MAX 13
#define PL_ALO_CAP_LEVELS_MAX 15
#define PL_ALO_CAP_INTEGRAND_MAX 196695u
#define PL_ALO_CAP_QD_CALLS_MAX 1469u
/* Record R3 bounds that no Python counter checks: 10 + 2 + 101 evaluator calls per node and
 * 5 x 13 x 25 = 1,625 Legendre points per engine evaluation that reaches the sweeps. */
#define PL_ALO_NODE_CALLS_MAX 113
#define PL_ALO_LEGENDRE_POINTS 1625u

/* The tanh-sinh rows of tanh_sinh_detail<double> (record R2): rows 0-7 are the tabulated Boost
 * literals (769 entries), rows 8-15 are computed (row k: 3 * 2^k entries). */
#define PL_ALO_TS_TABLE_ROWS 8
#define PL_ALO_TS_ROWS 16
#define PL_ALO_TS_TABLE_ENTRIES 769

/* The planted sites of pl_params.alo_plant_site (alo.VALUE_MASK_SITES, alo.EUROPEAN_MASK_SITES,
 * then the persistent QD+ evaluator NaN of AI3-02; cvectors.alo_plant_sites). A planted NaN
 * replaces the value at its site at the first occurrence in each engine evaluation; the
 * persistent site replaces the QD+ evaluator value (qdplus:66) at every occurrence. */
enum pl_alo_site {
    PL_ALO_SITE_NONE = 0,
    PL_ALO_SITE_QDPLUS_66 = 1,
    PL_ALO_SITE_QDPLUS_329 = 2,
    PL_ALO_SITE_QDPLUS_277 = 3,
    PL_ALO_SITE_QDPLUS_BRENT = 4,
    PL_ALO_SITE_CPP_441 = 5,
    PL_ALO_SITE_CPP_448 = 6,
    PL_ALO_SITE_CPP_N = 7,
    PL_ALO_SITE_CPP_D = 8,
    PL_ALO_SITE_CPP_FV = 9,
    PL_ALO_SITE_CPP_NDD = 10,
    PL_ALO_SITE_CPP_492 = 11,
    PL_ALO_SITE_CPP_503 = 12,
    PL_ALO_SITE_QDPLUS_135 = 13,
    PL_ALO_SITE_QDPLUS_142 = 14,
    PL_ALO_SITE_QDPLUS_143 = 15,
    PL_ALO_SITE_QDPLUS_150 = 16,
    PL_ALO_SITE_CPP_515 = 17,
    PL_ALO_SITE_CPP_EURO = 18,
    PL_ALO_SITE_QDPLUS_208 = 19,
    PL_ALO_SITE_PERSISTENT_QDPLUS_66 = 20
};
#define PL_ALO_PLANT_SITES 20

/* The loops of record R3 in the order of alo.CAPS. pl_params.alo_force 1 + cap takes the cap of
 * that loop as 0, so its first count check is an excess (alo.force_cap_excess). */
enum pl_alo_cap {
    PL_ALO_CAP_NONE = 0,
    PL_ALO_CAP_HALLEY = 1,
    PL_ALO_CAP_DOUBLING = 2,
    PL_ALO_CAP_BRENT = 3,
    PL_ALO_CAP_SWEEP_F = 4,
    PL_ALO_CAP_SWEEP_NDD = 5,
    PL_ALO_CAP_LEVELS = 6,
    PL_ALO_CAP_INTEGRAND = 7,
    PL_ALO_CAP_QD_CALLS = 8
};
#define PL_ALO_CAPS 8
/* pl_params.alo_force 1: every node solve takes the inner Brent fallback, whose bracket check
 * then fails (alo.force_inner_bracket_error); 2 to PL_ALO_FORCES: the cap excess of loop
 * alo_force - 1. */
#define PL_ALO_FORCE_BRACKET 1
#define PL_ALO_FORCES 9

/* The check sites of the shared NaN check in the record's order (record R7 item 3, E-ALO-4;
 * cvectors.ALO_CHECK_SITES): the pre check (order 5), then the run-defect classes. */
enum pl_alo_check {
    PL_ALO_CHECK_NONE = 0,
    PL_ALO_CHECK_PRE = 1,
    PL_ALO_CHECK_QDPLUS_SOLVER = 2,
    PL_ALO_CHECK_POST_BOUNDARY = 3,
    PL_ALO_CHECK_POST_SWEEP = 4,
    PL_ALO_CHECK_INTEGRAND = 5,
    PL_ALO_CHECK_INTEGRAND_VALUE = 6,
    PL_ALO_CHECK_POST_INTEGRAL = 7,
    PL_ALO_CHECK_POST_EUROPEAN = 8
};

/* The statistics of one engine evaluation (alo.Stats and the AloRunDefect site; never part of a
 * result). equation: PL_ALO_FP_A or PL_ALO_FP_B of the mapped point, -1 when the mapping raised.
 * qd_calls, halley_max, fallback_nodes, fallback_max, levels, integrand and nan_guarded are the
 * alo.Stats members qd_calls, halley_max, fallback_nodes, fallback_max, levels, integrand and
 * guarded, updated at the same statements. failed_check: enum pl_alo_check of a failed check
 * (PL_ALO_CHECK_PRE for the order-5 pre check), failed_cap: enum pl_alo_cap of a cap excess.
 * sweep_f, sweep_ndd and legendre_points count the fixed-point f and NDd calls and the Legendre
 * points of the evaluation (C only; record R3 fixes them at 65, 13 and 1,625). */
struct pl_alo_trace {
    int equation;
    uint32_t qd_calls;
    int halley_max;
    int fallback_nodes;
    int fallback_max;
    int levels;
    uint32_t integrand;
    uint32_t nan_guarded;
    int failed_check;
    int failed_cap;
    int sweep_f;
    int sweep_ndd;
    uint32_t legendre_points;
};

/* The engine evaluation of the mapped problem (T' = 1): engine calculate with
 * calculatePutWithEdgeCases and calculatePut (alo.engine, alo.put_with_edge_cases,
 * alo.calculate_put; qdplusamericanengine.cpp:167-228, qdfpamericanengine.cpp:429-516), preceded by
 * the pre check of alo.pre_check. d_r and d_q are the discounts 1.0 / exp(r' * 1.0) and
 * 1.0 / exp(q' * 1.0); the engine reads the rates back (r_e = -log(d_r) / 1.0, q_e =
 * -log(d_q) / 1.0) and uses only r_e and q_e, with the equation pl_alo_equation_of(r_e, q_e). A put
 * (side 1) is calculatePutWithEdgeCases(S, K, r_e, q_e, vol, 1.0), every other side the call as the
 * put with spot, strike and rates exchanged (qdplusamericanengine.cpp:190-193). Results:
 * PL_ENGINE_OK with *value; PL_ENGINE_QL_ERROR for a failed pre check (trace->failed_check
 * PL_ALO_CHECK_PRE, before any engine arithmetic), a QuantLib or Boost error and an inner QD+
 * Brent error (order 5, record R8); PL_ENGINE_PY_DEFECT for a failed check of the shared NaN check
 * (trace->failed_check), a loop count above its cap (trace->failed_cap), a Python raise of the
 * transcription (the division by v = 0.0 of QdPlusEval.pre) and a test-only parameter outside its
 * range (C contract). *value is pl_nan() unless PL_ENGINE_OK. p->alo_plant_site and p->alo_force
 * drive the planted-defect hooks of I4.1. p, trace and value are not NULL. */
enum pl_engine_status pl_alo_engine(int side, double S, double K, double d_r, double d_q,
                                    double vol, const struct pl_params *p,
                                    struct pl_alo_trace *trace, double *value);

/* alo.price (alo.py:676-693): side 0 or 1 (alo_equation.side_index; another side raises
 * ValueError), the unit-maturity mapping r' = r T, q' = q T, sigma' = sigma sqrt(T) (a T < 0.0
 * raises ValueError in math.sqrt), the discounts of read_back (a zero exponential raises
 * ZeroDivisionError), then pl_alo_engine. A Python raise of the mapping is PL_ENGINE_PY_DEFECT with
 * trace->equation -1. */
enum pl_engine_status pl_alo_result(int side, double S, double K, double T, double r, double q,
                                    double sigma, const struct pl_params *p,
                                    struct pl_alo_trace *trace, double *value);

/* The ALO branch of reference.price_and_greeks (reference.py:253-257) with the counter of
 * reference.evaluate: tau_V of the row, the pre check and the checked price at sigma (not counted:
 * H17, the price of a row is the last Brent value), then reference.alo_greeks (record R6, I2.6):
 * delta and gamma from the central S stencil, h_S = min(1e-3, 0.1 sigma sqrt T) S; vega with
 * h_sigma, central, forward when sigma - h_sigma < sigma_lo(ALO); rho with h_r and q fixed, central
 * when both points have the row's segment, else the one-sided difference whose point has it, else
 * h_r halved (at most PL_ALO_HALVINGS times); theta case (c) (V(T - d) - V(T)) / d, d = min(1/365,
 * T/2), when T - d has the row's segment, else (V(T) - V(T + d)) / d, else d halved (at most
 * PL_ALO_HALVINGS times). Returns 0 OK (values: sigma, price, delta, gamma, theta, vega, rho) or 1
 * order 5 (values pl_nan()): a failed pre check, an engine QuantLib error, a value that fails the
 * order-5 check, a non-finite result, or no row-segment stencil after the halvings (flag 16
 * stencil_unresolved into *flags). On OK *flags receives flag 32 stencil_switched when a rho or
 * theta stencil is switched or halved. *band receives the Checker band. *engine_evals is increased
 * by 1 per stencil point that passes the pre check (S 2; vega 2 central or 1 forward; rho 2 central
 * or 1 one-sided; theta 1: 7 when every stencil is central; a halving re-tests segments only).
 * *defect = 1 (and the return value 1) where Python raises: tau_v, a run defect of an engine
 * evaluation, a Python raise of the mapping or of alo_segment, a stencil division by 0.0. row->bid
 * and row->ask are not read. Every pointer is not NULL (C contract: a NULL argument gives 1 with
 * *defect = 1 when defect is not NULL). */
int pl_alo_price_and_greeks(const struct pl_row *row, double sigma, const struct pl_params *p,
                            double values[PL_FIELDS], int *band, uint8_t *flags,
                            uint32_t *engine_evals, int *defect);

/* The frozen 25-point Gauss-Legendre table of record R5 (alo.GL_X, alo.GL_W in x() order,
 * descending nodes): entry i for 0 <= i < 25, pl_nan() otherwise. */
double pl_alo_gl_node(int i);
double pl_alo_gl_weight(int i);

/* The 14 Chebyshev nodes of the second kind -cos(i M_PI / 13) and their barycentric weights
 * (alo.Cheb with n = 14; chebyshevinterpolation.cpp:66-68, lagrangeinterpolation.hpp:57-70) into
 * nodes[14] and lambda[14]. */
void pl_alo_cheb_nodes(double *nodes, double *lambda);

/* t_crossover = t_from_abscissa_complement(0.5) of tanh_sinh_detail (alo.T_CROSSOVER;
 * tanh_sinh_detail.hpp:167-174). */
double pl_alo_ts_crossover(void);

/* Row level (0 to PL_ALO_TS_ROWS - 1) of tanh_sinh_detail<double>: *length and the first
 * complement index *first_complement. Returns 0, or 1 for another level (outputs unchanged). */
int pl_alo_ts_row(int level, int *length, int *first_complement);

/* Entry index of row level: the abscissa (or its complement) and the weight, rows 0-7 from the
 * tabulated literals, rows 8-15 computed in Boost's operation order (tanh_sinh_detail.hpp:103-166,
 * alo.TanhSinhDetail.extend_refinements). Returns 0, or 1 for an index outside the row. */
int pl_alo_ts_entry(int level, int index, double *abscissa, double *weight);
