/* Transcribed from QuantLib 1.43 (QL_VERSION 1.43; retained source
 * benchmarks/project/third_party/sources/QuantLib-1.43.tar.gz, sha256
 * b41206ccc4ba39b5e86bdc940d51138222b352f79d2c6fc68649f9c9bbe58701), via optionlab/alo.py
 * lines 469-477, 553-693 (merged G-ALO2 part B, commit 567f6c4) and optionlab/alo_equation.py
 * lines 27-40 (commit 490dce1): ql/pricingengines/vanilla/qdplusamericanengine.cpp 132-158
 * (QdPlusAddOnValue), 167-196 (QdPutCallParityEngine::calculate), 198-228
 * (calculatePutWithEdgeCases), 346-362 (getPutExerciseBoundary, 14 points);
 * ql/pricingengines/vanilla/qdfpamericanengine.cpp 429-516 (calculatePut: the boundary, one
 * Jacobi-Newton sweep and four naive sweeps, the add-on integral, the value);
 * ql/pricingengines/blackcalculator.cpp 65-75 (the BlackCalculator checks; its value through
 * pl_black.c); ql/math/comparison.hpp 59-76 (close) (spec Appendix I-ALO R2-R8). QuantLib license
 * (BSD-3-Clause): the copyright notices, conditions and disclaimer are in NOTICE-QuantLib.md of
 * this example (LR-EX 2026-10-18). */
#include "pl_alo.h"
#include "pl_alo_equation.h"
#include "pl_alo_step.h"
#include "pl_black.h"
#include "pl_ieee.h"
#include "pl_normal.h"
#include "pl_types.h"
#include <float.h>
#include <stddef.h>
#include <stdint.h>

/* The ALO engine evaluation (specs/project/models.md "ALO (Amendment I)"), copied from
 * optionlab.alo statement by statement: the pre check, the engine checks, the edge cases, the
 * double-boundary QL_FAIL, the QD+ boundary interpolation, the fixed-point sweeps, the add-on
 * integral and value = max(European, 0) + max(0, addOn). Each check site of the shared NaN check
 * runs at its place, before the comparison it protects; a failed check ends the evaluation as a
 * run defect (PL_ENGINE_PY_DEFECT), an exception of QuantLib or Boost as PL_ENGINE_QL_ERROR.
 * Divisions are models._div (IEEE C division). */

/* alo._black (alo.py:553-559): the BlackCalculator checks (QuantLib's texts: order 5), then
 * Black(1, K, F, sd, disc).value(). */
static double black_put(double K, double F, double sd, double disc, struct pl_alo_run *run) {
    if (!(K >= 0.0) || !(F > 0.0) || !(sd >= 0.0) || !(disc > 0.0)) {
        pl_alo_fail(run, PL_ENGINE_QL_ERROR);
        return pl_nan();
    }
    struct pl_black b;
    pl_black_init(&b, 1, K, F, sd, disc);
    return pl_black_value(&b);
}

double pl_alo_addon_value(const struct pl_alo_addon *g, double zv) {
    struct pl_alo_run *run = g->run;
    const double t = zv * zv;
    const double a = g->T - t;
    pl_alo_guard(run, a);
    double qv = pl_alo_cheb_value(g->interp, 2.0 * pl_sqrt(pl_max(0.0, a) / g->T) - 1.0, run);
    qv = pl_alo_mask(run, PL_ALO_SITE_QDPLUS_135, qv);
    double b_t = g->xmax * pl_exp(-pl_sqrt(pl_max(0.0, qv)));
    const double dr = pl_exp(-g->r * t);
    const double dq = pl_exp(-g->q * t);
    double v = g->vol * pl_sqrt(t);
    v = pl_alo_mask(run, PL_ALO_SITE_QDPLUS_142, v);
    b_t = pl_alo_mask(run, PL_ALO_SITE_QDPLUS_143, b_t);
    double vals[6];
    *(vals + 0) = t;
    *(vals + 1) = v;
    *(vals + 2) = b_t;
    *(vals + 3) = dr;
    *(vals + 4) = dq;
    *(vals + 5) = qv;
    if (pl_alo_check(run, PL_ALO_CHECK_INTEGRAND, vals, 6u) != 0) {
        return pl_nan();
    }
    const double S = g->S;
    const double K = g->K;
    const double r = g->r;
    const double q = g->q;
    double res = 0.0;
    if (v >= PL_QL_EPSILON) {
        if (b_t > PL_QL_EPSILON) {
            const double dp = pl_log((S * dq) / (b_t * dr)) / v + 0.5 * v;
            res = 2.0 * zv * (r * K * dr * pl_norm_cdf(-dp + v) - q * S * dq * pl_norm_cdf(-dp));
        } else {
            res = 0.0;
        }
    } else if (pl_alo_close_enough(S * dq, b_t * dr)) {
        res = zv * (r * K * dr - q * S * dq);
    } else if (b_t * dr > S * dq) {
        res = 2.0 * zv * (r * K * dr - q * S * dq);
    } else {
        res = 0.0;
    }
    res = pl_alo_mask(run, PL_ALO_SITE_QDPLUS_150, res);
    if (pl_alo_check(run, PL_ALO_CHECK_INTEGRAND_VALUE, &res, 1u) != 0) {
        return pl_nan();
    }
    return res;
}

/* alo.qd_boundary_interp (alo.py:469-477): the 14 node values of getPutExerciseBoundary. */
static void boundary_interp(struct pl_alo_cheb *interp, double S, double K, double r, double q,
                            double vol, double T, struct pl_alo_run *run) {
    const double xmax = pl_alo_xmax(K, r, q, run);
    pl_alo_cheb_init(interp);
    if (run->status != PL_ENGINE_OK) {
        return;
    }
    const double put[6] = {S, K, r, q, vol, T};
    for (int i = 0; i < PL_ALO_CHEB_NODES; i++) {
        pl_alo_boundary_node(interp, i, put, xmax, run); /* y[i], src/pl_alo_node.c */
        if (run->status != PL_ENGINE_OK) {
            return;
        }
    }
}

/* alo.calculate_put (alo.py:561-624): QdFpAmericanEngine::calculatePut with accurateScheme. */
static double calculate_put(double S, double K, double r, double q, double vol, double T, int kind,
                            struct pl_alo_run *run) {
    if (r < 0.0 && q < r) {
        pl_alo_fail(run, PL_ENGINE_QL_ERROR); /* double-boundary case q<r<0 (cpp:432-433) */
        return pl_nan();
    }
    const double xmax = pl_alo_xmax(K, r, q, run);
    if (run->status != PL_ENGINE_OK) {
        return pl_nan();
    }
    struct pl_alo_cheb interp;
    boundary_interp(&interp, S, K, r, q, vol, T, run);
    if (run->status != PL_ENGINE_OK ||
        pl_alo_check(run, PL_ALO_CHECK_POST_BOUNDARY, interp.y, (size_t)PL_ALO_CHEB_NODES) != 0) {
        return pl_nan();
    }
    const double sT = pl_sqrt(T);
    double x[PL_ALO_CHEB_NODES];
    double y[PL_ALO_CHEB_NODES];
    for (int i = 0; i < PL_ALO_CHEB_NODES; i++) {
        *(x + i) = 0.5 * sT * (1.0 + *(interp.x + i));
        *(y + i) = 0.0;
    }
    struct pl_alo_fp eqn;
    eqn.kind = kind;
    eqn.K = K;
    eqn.r = r;
    eqn.q = q;
    eqn.vol = vol;
    eqn.xmax = xmax;
    eqn.T = T;
    eqn.interp = &interp;
    eqn.run = run;
    eqn.f_calls = 0;
    eqn.ndd_calls = 0;
    /* SCHEME_M - 4 = 1 Jacobi-Newton sweep (cpp:465-493), then 4 naive sweeps (cpp:495-504) */
    for (int k = 0; k < PL_ALO_FP_STEPS; k++) {
        if (pl_alo_sweep(&eqn, &interp, x, y, k == 0) != 0) { /* src/pl_alo_sweep.c */
            return pl_nan();
        }
    }
    if (pl_alo_cap(run, PL_ALO_CAP_SWEEP_F, (uint32_t)eqn.f_calls) != 0 ||
        pl_alo_cap(run, PL_ALO_CAP_SWEEP_NDD, (uint32_t)eqn.ndd_calls) != 0) {
        return pl_nan();
    }
    struct pl_alo_addon g;
    g.S = S;
    g.K = K;
    g.r = r;
    g.q = q;
    g.vol = vol;
    g.T = T;
    g.xmax = xmax;
    g.interp = &interp;
    g.run = run;
    int levels = 0;
    uint32_t nev = 0u;
    double add_on = pl_alo_ts_integrate(&g, 0.0, sT, PL_ALO_TS_EPS, &levels, &nev);
    if (run->status != PL_ENGINE_OK) {
        return pl_nan();
    }
    struct pl_alo_trace *tr = run->trace;
    tr->levels = levels;
    tr->integrand = nev;
    if (pl_alo_cap(run, PL_ALO_CAP_LEVELS, (uint32_t)levels) != 0 ||
        pl_alo_cap(run, PL_ALO_CAP_INTEGRAND, nev) != 0 ||
        pl_alo_cap(run, PL_ALO_CAP_QD_CALLS, tr->qd_calls) != 0) {
        return pl_nan();
    }
    double european = black_put(K, S * pl_exp((r - q) * T), vol * sT, pl_exp(-r * T), run);
    if (run->status != PL_ENGINE_OK) {
        return pl_nan();
    }
    add_on = pl_alo_mask(run, PL_ALO_SITE_CPP_515, add_on);
    european = pl_alo_mask(run, PL_ALO_SITE_CPP_EURO, european);
    double vals[2];
    *(vals + 0) = add_on;
    *(vals + 1) = european;
    if (pl_alo_check(run, PL_ALO_CHECK_POST_INTEGRAL, vals, 2u) != 0) {
        return pl_nan();
    }
    return pl_max(european, 0.0) + pl_max(0.0, add_on);
}

/* alo.put_with_edge_cases (alo.py:626-648): calculatePutWithEdgeCases. */
static double put_with_edge_cases(double S, double K, double r, double q, double vol, double T,
                                  int kind, struct pl_alo_run *run) {
    pl_alo_guard(run, S);
    pl_alo_guard(run, K);
    pl_alo_guard(run, r);
    pl_alo_guard(run, q);
    pl_alo_guard(run, vol);
    if (pl_close(K, 0.0)) {
        return 0.0;
    }
    if (pl_close(S, 0.0)) {
        return pl_max(K, K * pl_exp(-r * T));
    }
    if (r <= 0.0 && r <= q) {
        double bv = black_put(K, S * pl_exp((r - q) * T), vol * pl_sqrt(T), pl_exp(-r * T), run);
        if (run->status != PL_ENGINE_OK) {
            return pl_nan();
        }
        bv = pl_alo_mask(run, PL_ALO_SITE_QDPLUS_208, bv);
        if (pl_alo_check(run, PL_ALO_CHECK_POST_EUROPEAN, &bv, 1u) != 0) {
            return pl_nan();
        }
        return pl_max(0.0, bv);
    }
    if (pl_close(vol, 0.0)) {
        return pl_alo_zero_vol(S, K, r, q, T); /* src/pl_alo_edge.c */
    }
    return calculate_put(S, K, r, q, vol, T, kind, run);
}

/* The trace of an evaluation before the engine runs: every count 0, no failure. */
static void trace_init(struct pl_alo_trace *trace, int equation) {
    trace->equation = equation;
    trace->qd_calls = 0u;
    trace->halley_max = 0;
    trace->fallback_nodes = 0;
    trace->fallback_max = 0;
    trace->levels = 0;
    trace->integrand = 0u;
    trace->nan_guarded = 0u;
    trace->failed_check = PL_ALO_CHECK_NONE;
    trace->failed_cap = PL_ALO_CAP_NONE;
    trace->sweep_f = 0;
    trace->sweep_ndd = 0;
    trace->legendre_points = 0u;
}

enum pl_engine_status pl_alo_engine(int side, double S, double K, double d_r, double d_q,
                                    double vol, const struct pl_params *p,
                                    struct pl_alo_trace *trace, double *value) {
    *value = pl_nan();
    const double r_e = -pl_log(d_r) / 1.0;
    const double q_e = -pl_log(d_q) / 1.0;
    const int kind = pl_alo_equation_of(r_e, q_e);
    trace_init(trace, kind);
    const int plant_ok = p->alo_plant_site >= 0 && p->alo_plant_site <= PL_ALO_PLANT_SITES;
    if (!plant_ok || p->alo_force < 0 || p->alo_force > PL_ALO_FORCES) {
        return PL_ENGINE_PY_DEFECT; /* C contract: test-only parameters out of range */
    }
    /* alo.pre_check (alo.py:661-664): S, K, r_e, q_e, sigma' and T' = 1.0 finite, S > 0, K > 0,
     * sigma' > 0 */
    const int finite = pl_is_finite(S) & pl_is_finite(K) & pl_is_finite(r_e) & pl_is_finite(q_e);
    if ((finite & pl_is_finite(vol)) == 0 || !(S > 0.0 && K > 0.0 && vol > 0.0)) {
        trace->failed_check = PL_ALO_CHECK_PRE;
        return PL_ENGINE_QL_ERROR;
    }
    struct pl_alo_run run;
    run.plant = p->alo_plant_site;
    run.force = p->alo_force;
    run.fired = 0;
    run.status = PL_ENGINE_OK;
    run.trace = trace;
    /* alo.engine (alo.py:650-659) on T = 1.0 */
    if (!(S >= 0.0) || !(K >= 0.0) || !(vol >= 0.0)) {
        return PL_ENGINE_QL_ERROR; /* the QL_REQUIRE texts of qdplus:168-195 */
    }
    double v = 0.0;
    if (side == 1) {
        v = put_with_edge_cases(S, K, r_e, q_e, vol, 1.0, kind, &run);
    } else {
        v = put_with_edge_cases(K, S, q_e, r_e, vol, 1.0, kind, &run);
    }
    if (run.status != PL_ENGINE_OK) {
        return (enum pl_engine_status)run.status;
    }
    *value = v;
    return PL_ENGINE_OK;
}

enum pl_engine_status pl_alo_result(int side, double S, double K, double T, double r, double q,
                                    double sigma, const struct pl_params *p,
                                    struct pl_alo_trace *trace, double *value) {
    *value = pl_nan();
    trace_init(trace, -1);
    if ((side != 0 && side != 1) || T < 0.0) {
        return PL_ENGINE_PY_DEFECT; /* side_index ValueError; math.sqrt(T) ValueError */
    }
    double r1 = 0.0;
    double q1 = 0.0;
    double s1 = 0.0;
    pl_unit(T, r, q, sigma, &r1, &q1, &s1);
    int defect = 0;
    const double d_r = pl_py_div(1.0, pl_exp(r1 * 1.0), &defect);
    const double d_q = pl_py_div(1.0, pl_exp(q1 * 1.0), &defect);
    if (defect != 0) {
        return PL_ENGINE_PY_DEFECT; /* read_back: ZeroDivisionError */
    }
    return pl_alo_engine(side, S, K, d_r, d_q, s1, p, trace, value);
}
