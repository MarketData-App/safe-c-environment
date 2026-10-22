/* Transcribed from QuantLib 1.43 (QL_VERSION 1.43; retained source
 * benchmarks/project/third_party/sources/QuantLib-1.43.tar.gz, sha256
 * b41206ccc4ba39b5e86bdc940d51138222b352f79d2c6fc68649f9c9bbe58701), via optionlab/alo.py
 * lines 359-368, 417-467 (merged G-ALO2 part B, commit 567f6c4): ql/pricingengines/vanilla/
 * qdplusamericanengine.cpp 231-251 (xMax), 262-265, 267-289
 * (buildInSolver with Brent), 291-344 (putExerciseBoundaryAtTau with Halley, eps 1e-8, maxIter
 * 10); ql/math/solvers1d/brent.hpp 39-137 and ql/math/solver1d.hpp 162-211 through pl_brent
 * (spec Appendix I-ALO R3, R7, R8). QuantLib license (BSD-3-Clause): the copyright notices,
 * conditions and disclaimer are in NOTICE-QuantLib.md of this example (LR-EX 2026-10-18). */
#include "pl_alo.h"
#include "pl_alo_step.h"
#include "pl_black.h"
#include "pl_ieee.h"
#include "pl_normal.h"
#include "pl_solver.h"
#include "pl_types.h"
#include <float.h>
#include <math.h>
#include <stddef.h>
#include <stdint.h>

/* The QD+ exercise boundary of one node (specs/project/models.md "ALO (Amendment I)"), copied
 * from optionlab.alo statement by statement: Halley with the stop |x - x_old| < 0.5 eps and
 * x = max(xmin, x - step), and the inner Brent fallback. The evaluator is src/pl_alo_qdeval.c
 * (opaque calls here: the fixed GCC analyzer budget). Divisions are models._div (IEEE C
 * division); the doubling of the bracket is pl_sum2(x, x) (the same bits as x * 2.0). std::max and
 * std::min keep their NaN semantics (pl_max, pl_alo_min). Each loop is bounded by its QuantLib cap:
 * Halley by the evaluator count maxIter_ = 10, the doubling loop by the same count test, the
 * inner Brent by maxEvaluations 100 (at most 101 calls). */

double pl_alo_xmax(double K, double r, double q, struct pl_alo_run *run) {
    if (r > 0.0 && q > 0.0) {
        return K * pl_alo_min(1.0, r / q);
    }
    if (r > 0.0 && q <= 0.0) {
        return K;
    }
    if (r == 0.0 && q < 0.0) {
        return K;
    }
    if (r == 0.0 && q >= 0.0) {
        return 0.0;
    }
    if (r < 0.0 && q >= 0.0) {
        return 0.0;
    }
    if (r < 0.0 && q < r) {
        return K;
    }
    if (r < 0.0 && r <= q && q < 0.0) {
        return 0.0;
    }
    pl_alo_fail(run, PL_ENGINE_QL_ERROR); /* QL_FAIL("internal error") */
    return pl_nan();
}

double pl_alo_boundary_value(struct pl_alo_qdplus *ev, double x, int *py_defect) {
    double v = pl_alo_qdplus_value(ev, x);
    if (ev->run->status == PL_ENGINE_OK) {
        v = pl_alo_mask(ev->run, PL_ALO_SITE_QDPLUS_BRENT, v);
        pl_alo_check(ev->run, PL_ALO_CHECK_QDPLUS_SOLVER, &v, 1u);
    }
    if (ev->run->status != PL_ENGINE_OK) {
        *py_defect = 1; /* the AloRunDefect (or the raise) propagates out of brent */
        return pl_nan();
    }
    return v;
}

/* The inner Brent of the fallback (alo._qd_brent, alo.py:440-467): f(xmin), the doubling loop
 * (its count test uses the member maxIter_, so it never doubles after the Halley calls), the guess
 * clamps, then pl_brent with accuracy eps and max_evals evaluations. Errors of the inner solver are
 * PL_ENGINE_QL_ERROR (AloInnerSolverError, order 5), never orders 6-7. */
static double qd_brent(struct pl_alo_qdplus *ev, double S, int max_evals, double guess,
                       int max_iter_member, double eps) {
    struct pl_alo_run *run = ev->run;
    const double xmin = ev->xmin;
    double fxmin = pl_alo_qdplus_value(ev, xmin);
    if (run->status != PL_ENGINE_OK ||
        pl_alo_check(run, PL_ALO_CHECK_QDPLUS_SOLVER, &fxmin, 1u) != 0) {
        return pl_nan();
    }
    const double a = 0.5 * (ev->xmax + S);
    pl_alo_guard(run, a);
    double xmax = pl_max(a, ev->xmax);
    uint32_t nd = 0u;
    for (int it = 0; it <= max_iter_member; it++) {
        double fx = pl_alo_qdplus_value(ev, xmax);
        nd += 1u;
        if (run->status != PL_ENGINE_OK) {
            return pl_nan();
        }
        fx = pl_alo_mask(run, PL_ALO_SITE_QDPLUS_277, fx);
        if (pl_alo_check(run, PL_ALO_CHECK_QDPLUS_SOLVER, &fx, 1u) != 0) {
            return pl_nan();
        }
        if (fx * fxmin > 0.0 && ev->n < max_iter_member) {
            xmax = pl_sum2(xmax, xmax); /* xmax *= 2.0: the same bits, an opaque result */
        } else {
            break;
        }
    }
    if (pl_alo_cap(run, PL_ALO_CAP_DOUBLING, nd) != 0) {
        return pl_nan();
    }
    pl_alo_guard(run, guess);
    if (guess >= xmax) {
        guess = nextafter(xmax, -1.0);
    } else if (guess <= xmin) {
        guess = nextafter(xmin, DBL_MAX);
    }
    if (run->force == PL_ALO_FORCE_BRACKET) {
        pl_alo_fail(run, PL_ENGINE_QL_ERROR); /* test-only forced bracket error */
        return pl_nan();
    }
    struct pl_objective o = {0};
    o.kind = PL_OBJECTIVE_ALO_BOUNDARY;
    o.alo = ev;
    o.last_sigma = pl_nan();
    o.last_value = pl_nan();
    struct pl_brent_result br;
    pl_brent(&o, xmin, xmax, guess, eps, max_evals, &br);
    if (br.status == PL_BRENT_DEFECT || br.status == PL_BRENT_DOMAIN) {
        if (run->status == PL_ENGINE_OK) {
            pl_alo_fail(run, PL_ENGINE_QL_ERROR); /* solver.py ValueError -> AloInnerSolverError */
        }
        return pl_nan();
    }
    if (pl_alo_cap(run, PL_ALO_CAP_BRENT, (uint32_t)br.evaluations) != 0) {
        return pl_nan();
    }
    if (br.status == PL_BRENT_OK) {
        return br.root;
    }
    pl_alo_fail(run, PL_ENGINE_QL_ERROR); /* not bracketed or more than 100 evaluations */
    return pl_nan();
}

double pl_alo_boundary_at_tau(double S, double K, double r, double q, double vol, double tau,
                              struct pl_alo_run *run) {
    if (tau < PL_QL_EPSILON) {
        return pl_alo_xmax(K, r, q, run);
    }
    struct pl_alo_qdplus ev;
    pl_alo_qdplus_init(&ev, S, K, r, q, vol, tau, run);
    if (run->status != PL_ENGINE_OK) {
        return pl_nan();
    }
    const double eps = PL_ALO_QDP_EPS;
    const int max_iter = PL_ALO_QDP_MAX_ITER;
    double x = ev.xmax;
    const double xmin = ev.xmin;
    double fx = pl_nan();
    int close_ok = 0;
    for (int it = 0; it < max_iter; it++) { /* ev.n == it + 1 after the evaluator call */
        const double x_old = x;
        double vals[5];
        fx = pl_alo_qdplus_value(&ev, x);
        const double f_prime =
            (run->status == PL_ENGINE_OK) ? pl_alo_qdplus_derivative(&ev, x) : pl_nan();
        const double f2 = (run->status == PL_ENGINE_OK) ? pl_alo_qdplus_fprime2(&ev, x) : pl_nan();
        if (run->status != PL_ENGINE_OK) {
            return pl_nan();
        }
        const double lf = fx * f2 / (f_prime * f_prime);
        double step = 1.0 / (1.0 - 0.5 * lf) * fx / f_prime;
        step = pl_alo_mask(run, PL_ALO_SITE_QDPLUS_329, step);
        *(vals + 0) = fx;
        *(vals + 1) = f_prime;
        *(vals + 2) = f2;
        *(vals + 3) = lf;
        *(vals + 4) = step;
        if (pl_alo_check(run, PL_ALO_CHECK_QDPLUS_SOLVER, vals, 5u) != 0) {
            return pl_nan();
        }
        x = pl_max(xmin, x - step);
        close_ok = pl_fabs(x - x_old) < 0.5 * eps;
        if (close_ok || !(ev.n < max_iter)) {
            break;
        }
    }
    if (pl_alo_cap(run, PL_ALO_CAP_HALLEY, (uint32_t)ev.n) != 0) {
        return pl_nan();
    }
    struct pl_alo_trace *tr = run->trace;
    if ((!close_ok && !pl_close(pl_fabs(fx), 0.0)) || run->force == PL_ALO_FORCE_BRACKET) {
        const int n0 = ev.n;
        x = qd_brent(&ev, S, 10 * max_iter, x, max_iter, eps);
        if (run->status != PL_ENGINE_OK) {
            return pl_nan();
        }
        tr->fallback_nodes += 1;
        tr->fallback_max = (ev.n - n0 > tr->fallback_max) ? ev.n - n0 : tr->fallback_max;
    } else {
        tr->halley_max = (ev.n > tr->halley_max) ? ev.n : tr->halley_max;
    }
    return x;
}
