/* Transcribed from QuantLib 1.43 (QL_VERSION 1.43; retained source
 * benchmarks/project/third_party/sources/QuantLib-1.43.tar.gz, sha256
 * b41206ccc4ba39b5e86bdc940d51138222b352f79d2c6fc68649f9c9bbe58701), via optionlab/alo.py
 * lines 333-356 (merged G-ALO2 part B, commit 567f6c4): ql/math/interpolations/
 * chebyshevinterpolation.cpp 33-81, ql/math/interpolations/lagrangeinterpolation.hpp 42-134,
 * ql/math/interpolation.hpp 122-125 (spec Appendix I-ALO R5). QuantLib license
 * (BSD-3-Clause): the copyright notices, conditions and disclaimer are in NOTICE-QuantLib.md of
 * this example (LR-EX 2026-10-18). */
#include "pl_alo.h"
#include "pl_alo_step.h"
#include "pl_ieee.h"
#include "pl_types.h"
#include <math.h>
#include <stddef.h>

/* The Chebyshev interpolation of the exercise boundary (specs/project/models.md "ALO
 * (Amendment I)"): the 14 nodes of the second kind -cos(i M_PI / 13), evaluated (i M_PI) / 13
 * with i as a double and glibc cos (Python math.cos), and the barycentric Lagrange evaluation with
 * its exact-node branch and no range check. M_PI is the glibc literal (alo.M_PI). */

#define PL_ALO_M_PI 3.14159265358979323846

void pl_alo_cheb_init(struct pl_alo_cheb *c) {
    for (int i = 0; i < PL_ALO_CHEB_NODES; i++) {
        *(c->x + i) = -cos(((double)i * PL_ALO_M_PI) / (double)(PL_ALO_CHEB_NODES - 1));
        *(c->y + i) = 0.0;
    }
    const double cm1 = 4.0 / (*(c->x + PL_ALO_CHEB_NODES - 1) - *(c->x));
    for (int i = 0; i < PL_ALO_CHEB_NODES; i++) {
        double li = 1.0;
        const double xi = *(c->x + i);
        for (int j = 0; j < PL_ALO_CHEB_NODES; j++) {
            if (i != j) {
                li *= cm1 * (xi - *(c->x + j));
            }
        }
        *(c->lam + i) = 1.0 / li;
    }
}

void pl_alo_cheb_update(struct pl_alo_cheb *c, const double *y) {
    for (int i = 0; i < PL_ALO_CHEB_NODES; i++) {
        *(c->y + i) = *(y + i);
    }
}

void pl_alo_cheb_nodes(double *nodes, double *lambda) {
    struct pl_alo_cheb c;
    pl_alo_cheb_init(&c);
    for (int i = 0; i < PL_ALO_CHEB_NODES; i++) {
        *(nodes + i) = *(c.x + i);
        *(lambda + i) = *(c.lam + i);
    }
}

double pl_alo_cheb_value(const struct pl_alo_cheb *c, double x, struct pl_alo_run *run) {
    const double eps = (10.0 * PL_QL_EPSILON) * pl_fabs(x);
    const double t = x - eps;
    pl_alo_guard(run, t);
    int lo = 0;
    while (lo < PL_ALO_CHEB_NODES && *(c->x + lo) < t) { /* std::lower_bound */
        lo++;
    }
    if (lo != PL_ALO_CHEB_NODES && *(c->x + lo) - x < eps) {
        return *(c->y + lo);
    }
    double n = 0.0;
    double d = 0.0;
    for (int i = 0; i < PL_ALO_CHEB_NODES; i++) {
        const double alpha = *(c->lam + i) / (x - *(c->x + i));
        n += alpha * *(c->y + i);
        d += alpha;
    }
    return n / d;
}
