/* Transcribed from QuantLib 1.43 (QL_VERSION 1.43; retained source
 * benchmarks/project/third_party/sources/QuantLib-1.43.tar.gz, sha256
 * b41206ccc4ba39b5e86bdc940d51138222b352f79d2c6fc68649f9c9bbe58701), via optionlab/solver.py lines
 * 1-88: ql/math/solver1d.hpp 162-211, ql/math/solvers1d/brent.hpp 39-137,
 * ql/math/comparison.hpp 59-76. QuantLib license (BSD-3-Clause): the copyright notices, conditions
 * and disclaimer are in NOTICE-QuantLib.md of this example (LR-EX 2026-10-18). */
#include "pl_solver.h"
#include "pl_black.h"
#include "pl_evaluate.h"
#include "pl_ieee.h"
#include "pl_types.h"
#include <limits.h>
#include <stddef.h>
#include <stdint.h>

/* Brent through Solver1D::solve (specs/project/models.md "Brent"). pl_brent copies
 * optionlab.solver.brent statement by statement (spec 3.4, 3.5; Amendment F item 8): the same
 * operation order and association, Python math.fabs as pl_fabs, max as pl_max, close as
 * pl_close, a Python integer literal as the equal double literal. Every division is IEEE C
 * division and equals the Python division: no divisor can be 0.0 (fxMin and fxMax are values
 * that close() has refused, so they are nonzero, and p / q is taken only when 2p < |e q|, so
 * q != 0.0). The Python tuple returns become members of out. */

/* solver.py:19 _sign(a, b): |a| when b >= 0.0, else -|a|. */
static double sign_of(double a, double b) { return (b >= 0.0) ? pl_fabs(a) : -pl_fabs(a); }

/* pl_objective_value (the cubic, row and QD+ objectives) is src/pl_objective.c: an opaque call
 * here (the fixed GCC analyzer budget). */

/* One objective call f(x) into *fx, counted in out->evaluations. Returns 1 and sets the status
 * when the call stops the solve: PL_BRENT_DEFECT when py_defect is set (a Python raise inside f
 * propagates), else PL_BRENT_DOMAIN when domain is set; returns 0 otherwise. */
static int evaluate(struct pl_objective *o, double x, double *fx, struct pl_brent_result *out) {
    *fx = pl_objective_value(o, x);
    out->evaluations += 1;
    if (o->py_defect != 0) {
        out->status = PL_BRENT_DEFECT;
        return 1;
    }
    if (o->domain != 0) {
        out->status = PL_BRENT_DOMAIN;
        return 1;
    }
    return 0;
}

void pl_brent(struct pl_objective *o, double lo, double hi, double guess, double accuracy,
              int max_evaluations, struct pl_brent_result *out) {
    if (out == NULL) {
        return;
    }
    const double nan = pl_nan();
    out->status = PL_BRENT_DEFECT;
    out->root = nan;
    out->f_lo = nan;
    out->f_hi = nan;
    out->evaluations = 0;
    if (o == NULL || max_evaluations == INT_MAX) {
        return; /* C contract: no objective, or a count that could overflow an int */
    }
    if (!(accuracy > 0.0)) {
        return; /* solver.py:23 ValueError */
    }
    accuracy = pl_max(accuracy, PL_QL_EPSILON);
    double x_min = lo;
    double x_max = hi;
    if (!(x_min < x_max)) {
        return; /* solver.py:26 ValueError */
    }
    double fx_min = nan;
    double fx_max = nan;
    if (evaluate(o, x_min, &fx_min, out) != 0) {
        return;
    }
    out->f_lo = fx_min;
    if (pl_close(fx_min, 0.0) != 0) {
        out->status = PL_BRENT_OK;
        out->root = x_min;
        return;
    }
    if (evaluate(o, x_max, &fx_max, out) != 0) {
        return;
    }
    out->f_hi = fx_max;
    if (pl_close(fx_max, 0.0) != 0) {
        out->status = PL_BRENT_OK;
        out->root = x_max;
        return;
    }
    int evaluation_number = 2;
    if (!(fx_min * fx_max < 0.0)) {
        out->status = (fx_min > 0.0) ? PL_BRENT_BELOW_MIN : PL_BRENT_ABOVE_MAX;
        return;
    }
    if (!(guess > x_min) || !(guess < x_max)) {
        return; /* solver.py:35 ValueError */
    }
    double root = guess;
    /* Brent::solveImpl */
    double froot = nan;
    if (evaluate(o, root, &froot, out) != 0) {
        return;
    }
    evaluation_number += 1;
    if (froot * fx_min < 0.0) {
        x_max = x_min;
        fx_max = fx_min;
    } else {
        x_min = x_max;
        fx_min = fx_max;
    }
    double d = root - x_max;
    double e = d;
    while (evaluation_number <= max_evaluations) {
        if ((froot > 0.0 && fx_max > 0.0) || (froot < 0.0 && fx_max < 0.0)) {
            x_max = x_min;
            fx_max = fx_min;
            d = root - x_min;
            e = d;
        }
        if (pl_fabs(fx_max) < pl_fabs(froot)) {
            x_min = root;
            root = x_max;
            x_max = x_min;
            fx_min = froot;
            froot = fx_max;
            fx_max = fx_min;
        }
        const double x_acc1 = 2.0 * PL_QL_EPSILON * pl_fabs(root) + 0.5 * accuracy;
        const double x_mid = (x_max - root) / 2.0;
        if (pl_fabs(x_mid) <= x_acc1 || pl_close(froot, 0.0) != 0) {
            double f_final = nan;
            if (evaluate(o, root, &f_final, out) != 0) {
                return;
            }
            /* solver.py:57 increments evaluationNumber; the value is never read again. */
            out->status = PL_BRENT_OK;
            out->root = root;
            return;
        }
        if (pl_fabs(e) >= x_acc1 && pl_fabs(fx_min) > pl_fabs(froot)) {
            const double s = froot / fx_min;
            double p;
            double q;
            if (pl_close(x_min, x_max) != 0) {
                p = 2.0 * x_mid * s;
                q = 1.0 - s;
            } else {
                q = fx_min / fx_max;
                const double r = froot / fx_max;
                p = s * (2.0 * x_mid * q * (q - r) - (root - x_min) * (r - 1.0));
                q = (q - 1.0) * (r - 1.0) * (s - 1.0);
            }
            if (p > 0.0) {
                q = -q;
            }
            p = pl_fabs(p);
            const double min1 = 3.0 * x_mid * q - pl_fabs(x_acc1 * q);
            const double min2 = pl_fabs(e * q);
            if (2.0 * p < ((min1 < min2) ? min1 : min2)) {
                e = d;
                d = p / q;
            } else {
                d = x_mid;
                e = d;
            }
        } else {
            d = x_mid;
            e = d;
        }
        x_min = root;
        fx_min = froot;
        if (pl_fabs(d) > x_acc1) {
            root += d;
        } else {
            root += sign_of(x_acc1, x_mid);
        }
        if (evaluate(o, root, &froot, out) != 0) {
            return;
        }
        evaluation_number += 1;
    }
    out->status = PL_BRENT_NOT_CONVERGED;
}
