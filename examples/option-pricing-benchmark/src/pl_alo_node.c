/* Transcribed from QuantLib 1.43 (QL_VERSION 1.43; retained source
 * benchmarks/project/third_party/sources/QuantLib-1.43.tar.gz, sha256
 * b41206ccc4ba39b5e86bdc940d51138222b352f79d2c6fc68649f9c9bbe58701), via optionlab/alo.py
 * lines 469-477, 575-595 (merged G-ALO2 part B, commit 567f6c4): ql/pricingengines/vanilla/
 * qdplusamericanengine.cpp 346-362 (getPutExerciseBoundary: one of the 14 nodes),
 * ql/pricingengines/vanilla/qdfpamericanengine.cpp 429-516 (calculatePut: the node update of the
 * Jacobi-Newton sweep and of the naive sweeps) (spec Appendix I-ALO R2-R7). QuantLib license
 * (BSD-3-Clause): the copyright notices, conditions and disclaimer are in NOTICE-QuantLib.md of
 * this example (LR-EX 2026-10-18). */
#include "pl_alo.h"
#include "pl_alo_step.h"
#include "pl_ieee.h"
#include "pl_types.h"

/* One node of the QD+ boundary interpolation and the node update of one sweep of
 * alo.calculate_put (specs/project/models.md "ALO (Amendment I)"), copied statement by statement.
 * Their own translation unit: the node loops of src/pl_alo.c and src/pl_alo_sweep.c call them as
 * opaque functions (the fixed GCC analyzer budget). Divisions are models._div (IEEE
 * C division). */

/* h(fv) of alo.calculate_put (alo.py:575-576): log(fv / xmax)^2. */
static double h_of(double fv, double xmax) {
    const double l = pl_log(fv / xmax);
    return l * l;
}

/* The new h value of the node with time tau, or pl_nan() after a failure. */
static double node_value(struct pl_alo_fp *eqn, double tau, int jacobi) {
    struct pl_alo_run *run = eqn->run;
    const double b = pl_alo_fp_boundary(eqn, tau);
    if (run->status != PL_ENGINE_OK) {
        return pl_nan();
    }
    double N = 0.0;
    double D = 0.0;
    double fv = 0.0;
    pl_alo_fp_f(eqn, tau, b, &N, &D, &fv);
    if (run->status != PL_ENGINE_OK) {
        return pl_nan();
    }
    if (!jacobi || tau < PL_QL_EPSILON) {
        return h_of(fv, eqn->xmax);
    }
    double Nd = 0.0;
    double Dd = 0.0;
    pl_alo_fp_ndd(eqn, tau, b, &Nd, &Dd);
    if (run->status != PL_ENGINE_OK) {
        return pl_nan();
    }
    const double fd = eqn->K * pl_exp(-(eqn->r - eqn->q) * tau) * (Nd / D - Dd * N / (D * D));
    return h_of(b - (fv - b) / (fd - 1.0), eqn->xmax);
}

void pl_alo_boundary_node(struct pl_alo_cheb *interp, int i, const double *put, double xmax,
                          struct pl_alo_run *run) {
    const double z = *(interp->x + i);
    const double T = *(put + 5);
    const double x_sq = 0.25 * T * ((1.0 + z) * (1.0 + z));
    const double b = pl_alo_boundary_at_tau(*(put + 0), *(put + 1), *(put + 2), *(put + 3),
                                            *(put + 4), x_sq, run);
    if (run->status != PL_ENGINE_OK) {
        return;
    }
    double y = h_of(b, xmax);
    if (x_sq >= PL_QL_EPSILON) {
        y = pl_alo_mask(run, PL_ALO_SITE_CPP_441, y);
    }
    *(interp->y + i) = y;
}

void pl_alo_fp_node(struct pl_alo_fp *eqn, const double *x, double *y, int i, int jacobi) {
    const double tau = *(x + i) * *(x + i);
    const double yi = node_value(eqn, tau, jacobi);
    if (eqn->run->status != PL_ENGINE_OK) {
        return;
    }
    *(y + i) = pl_alo_mask(eqn->run, jacobi ? PL_ALO_SITE_CPP_492 : PL_ALO_SITE_CPP_503, yi);
}
