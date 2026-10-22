#pragma once
#include "pl_alo.h"
#include "pl_solver.h"
#include "pl_types.h"
#include <stddef.h>
#include <stdint.h>

/* The steps of one ALO engine evaluation (specs/project/models.md "ALO (Amendment I)"),
 * internal to the models module: the run state, the shared NaN check and the test-only hooks
 * (src/pl_alo_run.c), the Chebyshev boundary interpolation (src/pl_alo_cheb.c), the QD+ evaluator
 * and boundary (src/pl_alo_qdeval.c, src/pl_alo_qdplus.c), the fixed-point equations and the node
 * update of a sweep (src/pl_alo_fp.c, src/pl_alo_sweep.c), the add-on integrand and the tanh-sinh
 * integral (src/pl_alo_ts.c, src/pl_alo_ts_row0.c, src/pl_alo_ts_level.c, src/pl_alo_ts_sum.c),
 * the greek points and the ALO objective of the solver (src/pl_alo_points.c). The translation
 * units call each other as opaque calls: one translation unit with the whole engine exceeds the
 * fixed GCC analyzer budget (the Task 8-10 precedent).
 * Every function returns at once when run->status is not PL_ENGINE_OK, so the first failure of an
 * evaluation ends it as the Python exception does. */

/* The state of one engine evaluation (alo.Stats and the test-only state of the merged hooks):
 * plant (enum pl_alo_site) and force (pl_params.alo_force) of the parameter set, fired (the
 * planted NaN of this evaluation has fired, alo.Stats.fired), status (PL_ENGINE_OK until the first
 * failure: PL_ENGINE_QL_ERROR for a ModelDefect, PL_ENGINE_PY_DEFECT for a run defect or a Python
 * raise) and the trace that receives the counts. */
struct pl_alo_run {
    int plant;
    int force;
    int fired;
    int status;
    struct pl_alo_trace *trace;
};

/* alo._m (alo.py:133-138): pl_nan() at the planted site (the first occurrence per evaluation, or
 * every occurrence of qdplus:66 for the persistent site), else x. */
double pl_alo_mask(struct pl_alo_run *run, int site, double x);
/* alo.nan_check (alo.py:140-143) of n values at check site `site` (enum pl_alo_check): returns 1
 * and records the run defect (status PL_ENGINE_PY_DEFECT, trace->failed_check) at the first value
 * that is not finite, else 0. */
int pl_alo_check(struct pl_alo_run *run, int site, const double *xs, size_t n);
/* alo._guard (alo.py:145-148) for one value: a NaN increments trace->nan_guarded. */
void pl_alo_guard(struct pl_alo_run *run, double x);
/* alo._cap (alo.py:150-152): returns 1 and records the run defect (trace->failed_cap) when count
 * is above the cap of loop `cap` (0 when p->alo_force is 1 + cap), else 0. */
int pl_alo_cap(struct pl_alo_run *run, int cap, uint32_t count);
/* The first failure of the evaluation: status (PL_ENGINE_QL_ERROR or PL_ENGINE_PY_DEFECT) when
 * run->status is PL_ENGINE_OK. Returns 1. */
int pl_alo_fail(struct pl_alo_run *run, int status);
/* alo.close_enough (alo.py:157-162), QuantLib close_enough(x, y). */
int pl_alo_close_enough(double x, double y);
/* alo.smin (std::min): b when b < a, else a. */
double pl_alo_min(double a, double b);

/* ChebyshevInterpolation(14, f, SecondKind) over LagrangeInterpolationImpl (alo.Cheb): nodes x,
 * values y and barycentric weights lam. */
struct pl_alo_cheb {
    double x[PL_ALO_CHEB_NODES];
    double y[PL_ALO_CHEB_NODES];
    double lam[PL_ALO_CHEB_NODES];
};
/* alo.Cheb.__init__ without the values (alo.py:336-345): the nodes -cos(i M_PI / 13) and the
 * barycentric weights; every y is 0.0. */
void pl_alo_cheb_init(struct pl_alo_cheb *c);
/* alo.Cheb.update_y (alo.py:346): the 14 values y (borrowed, 14 doubles). */
void pl_alo_cheb_update(struct pl_alo_cheb *c, const double *y);
/* alo.Cheb.__call__ (alo.py:347-356) at x, with the guard lagrange:116. */
double pl_alo_cheb_value(const struct pl_alo_cheb *c, double x, struct pl_alo_run *run);

/* QdPlusBoundaryEvaluator (alo.QdPlusEval, qdplusamericanengine.cpp:41-122): the constants of
 * the node (tau, K, sigma, sigma2, v, r, q, dr, dq, ddr, omega, lam, alpha, beta, xmax, xmin),
 * the cached point sc (pl_nan() before the first call) with its derived values, the call count n
 * and the run. */
struct pl_alo_qdplus {
    double tau, K, sigma, sigma2, v, r, q, dr, dq, ddr, omega, lam, alpha, beta, xmax, xmin;
    double sc, dp, dm, Phi_dp, Phi_dm, phi_dp, npv, theta, charm;
    int n;
    struct pl_alo_run *run;
};
/* alo.xmax_fn (alo.py:359-368): QdPlusAmericanEngine::xMax; its QL_FAIL("internal error") is
 * PL_ENGINE_QL_ERROR. */
double pl_alo_xmax(double K, double r, double q, struct pl_alo_run *run);
/* alo.QdPlusEval.__init__ (alo.py:372-388). */
void pl_alo_qdplus_init(struct pl_alo_qdplus *ev, double S, double strike, double rf, double dy,
                        double vol, double t, struct pl_alo_run *run);
/* alo.QdPlusEval.__call__ (alo.py:397-405): one evaluator call (n and trace->qd_calls + 1). */
double pl_alo_qdplus_value(struct pl_alo_qdplus *ev, double S);
/* alo.QdPlusEval.derivative (alo.py:406-409) and fprime2 (alo.py:410-415); pl_nan() after a
 * failure of the cached point (run->status). The evaluator is src/pl_alo_qdeval.c. */
double pl_alo_qdplus_derivative(struct pl_alo_qdplus *ev, double S);
double pl_alo_qdplus_fprime2(struct pl_alo_qdplus *ev, double S);
/* The objective of the inner QD+ Brent (alo._qd_brent.f, alo.py:458-461): the evaluator value
 * with the planted site qdplus:brent and the QD+ solver check. A failed check or a Python raise
 * sets *py_defect = 1 (pl_brent then stops) and returns pl_nan(). */
double pl_alo_boundary_value(struct pl_alo_qdplus *ev, double x, int *py_defect);
/* alo.qd_boundary_at_tau (alo.py:417-438): putExerciseBoundaryAtTau with Halley and the inner
 * Brent fallback. */
double pl_alo_boundary_at_tau(double S, double K, double r, double q, double vol, double tau,
                              struct pl_alo_run *run);

/* DqFpEquation_A or _B (alo.FpEquation, qdfpamericanengine.cpp:119-400) on the boundary
 * interpolation interp (borrowed) with xmax and T (the B(tau) of alo.calculate_put); f_calls and
 * ndd_calls count the f and NDd calls. */
struct pl_alo_fp {
    int kind;
    double K, r, q, vol, xmax, T;
    const struct pl_alo_cheb *interp;
    struct pl_alo_run *run;
    int f_calls;
    int ndd_calls;
};
/* B(tau) of alo.calculate_put (alo.py:569-574). */
double pl_alo_fp_boundary(struct pl_alo_fp *e, double tau);
/* FpEquation.f (alo.py:487-532): N, D and fv. */
void pl_alo_fp_f(struct pl_alo_fp *e, double tau, double b, double *N, double *D, double *fv);
/* FpEquation.NDd (alo.py:533-551): Nd and Dd. */
void pl_alo_fp_ndd(struct pl_alo_fp *e, double tau, double b, double *Nd, double *Dd);
/* Node i of qd_boundary_interp (alo.py:469-477, getPutExerciseBoundary; src/pl_alo_node.c): tau
 * = 0.25 T (1 + x_i)^2, the QD+ boundary at tau of the put put = {S, K, r, q, vol, T}, then
 * interp->y[i] = h(b) through the planted site cpp:441 when tau >= QL_EPSILON. After a failure
 * (run->status) y[i] is unchanged. */
void pl_alo_boundary_node(struct pl_alo_cheb *interp, int i, const double *put, double xmax,
                          struct pl_alo_run *run);
/* One sweep of alo.calculate_put (alo.py:579-596, src/pl_alo_sweep.c): the Jacobi-Newton sweep
 * (jacobi != 0) or a naive sweep, nodes 1-13 from the previous interpolation, then updateY and the
 * post-boundary check. Returns 1 on a failure (run->status), else 0. */
int pl_alo_sweep(struct pl_alo_fp *eqn, struct pl_alo_cheb *interp, const double *x, double *y,
                 int jacobi);
/* The update of node i of one sweep of alo.calculate_put (alo.py:579-595, src/pl_alo_node.c):
 * tau = x[i]^2, B(tau), f and, for the Jacobi-Newton sweep (jacobi != 0) with tau >= QL_EPSILON,
 * NDd; y[i] receives the new h value through the planted site cpp:492 or cpp:503. After a failure
 * (run->status) y[i] is unchanged. */
void pl_alo_fp_node(struct pl_alo_fp *eqn, const double *x, double *y, int i, int jacobi);

/* The close(vol, 0.0) branch of calculatePutWithEdgeCases (alo.py:638-647, src/pl_alo_edge.c):
 * the largest intrinsic value at 0, T and the extremum time (record R7 ALO1-06: unreachable on an
 * admitted point). */
double pl_alo_zero_vol(double S, double K, double r, double q, double T);

/* QdPlusAddOnValue (the aov of alo.calculate_put, qdplusamericanengine.cpp:132-158) on the final
 * boundary interpolation interp (borrowed). */
struct pl_alo_addon {
    double S, K, r, q, vol, T, xmax;
    const struct pl_alo_cheb *interp;
    struct pl_alo_run *run;
};
/* aov(zv) (alo.py:599-617). */
double pl_alo_addon_value(const struct pl_alo_addon *g, double zv);

/* The integrand map of tanh_sinh::integrate (the u and g of alo.tanh_sinh_integrate,
 * tanh_sinh.hpp:188-208) with the evaluation count n. */
struct pl_alo_ts_map {
    const struct pl_alo_addon *g;
    double a, b, avg, diff, avg_over_diff_m1, avg_over_diff_p1;
    int have_small_left, have_small_right;
    uint32_t n;
};
/* u(z, zc) (alo.py:320-328). */
double pl_alo_ts_u(struct pl_alo_ts_map *m, double z, double zc);

/* The state of tanh_sinh_detail::integrate (alo.TanhSinhDetail.integrate, alo.py:207-301)
 * between levels; run is map->g->run (a direct member: the pointer chain exceeds the symbolic-depth
 * budget of the GCC analyzer). */
struct pl_alo_ts_state {
    struct pl_alo_ts_map *map;
    struct pl_alo_run *run;
    double lmc, rmc, tolerance, tail_tolerance, crossover, h;
    double I0, I1, L1_I0, L1_I1, err;
    int max_left_position, max_right_position, k, thrash_count, done;
};
/* One pass of the level loop (alo.py:244-300) at level s->k; s->done = 1 when the loop ends. */
void pl_alo_ts_level(struct pl_alo_ts_state *s);
/* The row of one level: the level, its length, the first complement index and the crossover. */
struct pl_alo_ts_row {
    int level;
    int length;
    int fc;
    double crossover;
};
/* The abscissa (or its complement) and the weight of entry j of the row (src/pl_alo_ts_ends.c);
 * pl_nan() outside the row. */
double pl_alo_ts_abscissa(const struct pl_alo_ts_row *row, int j);
double pl_alo_ts_weight(const struct pl_alo_ts_row *row, int j);
/* The retreat of one end (right != 0: the right end) over non-finite end values (alo.py:253-258,
 * 260-265): step g evaluates index0 - g at position0 - 2 g (the Python values after g retreats);
 * *position, *index and *y receive the result. Returns 1 on a failure (run->status), else 0. */
int pl_alo_ts_retreat(struct pl_alo_ts_state *s, const struct pl_alo_ts_row *row, int right,
                      int *position, int *index, double *y);
/* The end sanity check of one side (alo.py:290-297). Returns 1 on a failure, else 0. */
int pl_alo_ts_sanity(struct pl_alo_ts_state *s, const struct pl_alo_ts_row *row, int right,
                     int index);
/* Row 0 of the integral (alo.py:211-242, src/pl_alo_ts_row0.c): I0, L1_I0, tail_tolerance and the
 * end positions. Returns 1 on a failure (run->status), else 0. */
int pl_alo_ts_row0(struct pl_alo_ts_state *s);
/* The row sum of one level (alo.py:270-277, src/pl_alo_ts_sum.c): every index j < length below an
 * end index (mli, mri), each side zero beyond its end, added to *sum and *absum. level, length and
 * fc (the first complement index) describe the row. Returns 1 on a failure, else 0. */
int pl_alo_ts_row_sum(struct pl_alo_ts_state *s, int level, int length, int fc, int mli, int mri,
                      double *sum, double *absum);
/* Row meta and entries for the integrator: pl_alo_ts_row and pl_alo_ts_entry with a known
 * crossover (rows 8-15 compare each position with it). */
int pl_alo_ts_row_with(int level, double crossover, int *length, int *first_complement);
int pl_alo_ts_entry_with(int level, int index, double crossover, double *abscissa, double *weight);
/* alo.tanh_sinh_integrate (alo.py:303-330) of the add-on integrand over [a, b] with relative
 * tolerance `tolerance`: the integral, *levels and *evaluations (set only when it returns
 * normally, as the Python tuple). */
double pl_alo_ts_integrate(const struct pl_alo_addon *g, double a, double b, double tolerance,
                           int *levels, uint32_t *evaluations);

/* The greek points of the ALO greek step (src/pl_alo_points.c): the objective (row, parameters,
 * Checker state), the checked price p, the counter and the row's segment. */
struct pl_alo_step {
    struct pl_objective *o;
    double iv;
    double p;
    uint32_t *evals;
    struct pl_alo_segment seg;
};
/* E of reference.alo_greeks (reference.py:187-190): the pre check (a failure is order 5 and not
 * counted), then *evals + 1 and the checked engine value. Returns PL_GREEKS_OK with *value,
 * PL_GREEKS_DOMAIN or PL_GREEKS_DEFECT. */
int pl_alo_point_value(const struct pl_alo_step *c, double S, double T, double r, double s,
                       double *value);
/* The rho stencil (reference.py:198-207) and the theta stencil (reference.py:208-214) of the ALO
 * greek step (src/pl_alo_stencil.c): the status (PL_GREEKS_OK, PL_GREEKS_DOMAIN with flag 16 in
 * c->o->flags when no row-segment stencil exists after the halvings, PL_GREEKS_DEFECT), *switched
 * (a one-sided or halved stencil) and the difference quotient. */
int pl_alo_rho_stencil(const struct pl_alo_step *c, double *out, int *switched);
int pl_alo_theta_stencil(const struct pl_alo_step *c, double *theta, int *switched);
/* The ALO value of the solver's model objective o (o->params not NULL) at sigma: pl_alo_result of
 * the row; a failed pre check (AloPreCheck, not counted, reference.py:304) increments
 * o->uncounted. Returns the engine status with *value. */
enum pl_engine_status pl_alo_objective_price(struct pl_objective *o, double sigma, double *value);
/* 1 when the segment of (T, r) (alo_segment of unit(T, r, q, 1.0)) equals the row's segment;
 * *defect = 1 when alo_segment raises. */
int pl_alo_same_segment(const struct pl_alo_step *c, double T, double r, int *defect);
