/* Transcribed from QuantLib 1.43 (QL_VERSION 1.43; retained source
 * benchmarks/project/third_party/sources/QuantLib-1.43.tar.gz, sha256
 * b41206ccc4ba39b5e86bdc940d51138222b352f79d2c6fc68649f9c9bbe58701), via optionlab/alo.py
 * lines 370-415 (merged G-ALO2 part B, commit 567f6c4): ql/pricingengines/vanilla/
 * qdplusamericanengine.cpp 41-122 (QdPlusBoundaryEvaluator: the constants, the cached point,
 * operator(), derivative, fprime2) (spec Appendix I-ALO R7). QuantLib license (BSD-3-Clause): the
 * copyright notices, conditions and disclaimer are in NOTICE-QuantLib.md of this example (LR-EX
 * 2026-10-18). */
#include "pl_alo.h"
#include "pl_alo_step.h"
#include "pl_ieee.h"
#include "pl_normal.h"
#include "pl_types.h"

/* The QD+ boundary evaluator of one node (specs/project/models.md "ALO (Amendment I)"), copied
 * from optionlab.alo.QdPlusEval statement by statement. Its own translation unit: the Halley loop
 * and the inner Brent of src/pl_alo_qdplus.c call it as opaque functions (the fixed GCC analyzer
 * budget). Every division is models._div (IEEE C division) except the plain Python division by v
 * of QdPlusEval.pre, which raises ZeroDivisionError for v = 0.0 (the run defect output). */

void pl_alo_qdplus_init(struct pl_alo_qdplus *ev, double S, double strike, double rf, double dy,
                        double vol, double t, struct pl_alo_run *run) {
    const double nan = pl_nan();
    ev->run = run;
    ev->tau = t;
    ev->K = strike;
    ev->sigma = vol;
    ev->sigma2 = ev->sigma * ev->sigma;
    ev->v = ev->sigma * pl_sqrt(ev->tau);
    ev->r = rf;
    ev->q = dy;
    const double r = ev->r;
    const double q = ev->q;
    const double tau = ev->tau;
    const double sigma2 = ev->sigma2;
    ev->dr = pl_exp(-r * tau);
    ev->dq = pl_exp(-q * tau);
    pl_alo_guard(run, r * tau);
    double ddr = 0.0;
    if (pl_fabs(r * tau) > 1e-5) {
        ddr = r / (1.0 - ev->dr);
    } else {
        ddr = 1.0 / (tau * (1.0 - 0.5 * r * tau * (1.0 - r * tau / 3.0)));
    }
    ev->ddr = ddr;
    const double omega = 2.0 * (r - q) / sigma2;
    ev->omega = omega;
    const double root = pl_sqrt((omega - 1.0) * (omega - 1.0) + 8.0 * ddr / sigma2);
    const double lam = 0.5 * (-(omega - 1.0) - root);
    ev->lam = lam;
    const double lp = 2.0 * ddr * ddr / (sigma2 * root);
    const double alpha = 2.0 * ev->dr / (sigma2 * (2.0 * lam + omega - 1.0));
    ev->alpha = alpha;
    ev->beta = alpha * (ddr + lp / (2.0 * lam + omega - 1.0)) - lam;
    ev->xmax = pl_alo_xmax(strike, r, q, run);
    ev->xmin = nan;
    if (run->status == PL_ENGINE_OK) { /* xmax_fn raises before the guard of qdplus:56 */
        const double a = 0.5 * (strike + S);
        pl_alo_guard(run, a);
        pl_alo_guard(run, ev->xmax);
        ev->xmin = PL_ALO_QDP_XMIN_FACTOR * pl_alo_min(a, ev->xmax);
    }
    ev->sc = nan;
    ev->dp = nan;
    ev->dm = nan;
    ev->Phi_dp = nan;
    ev->Phi_dm = nan;
    ev->phi_dp = nan;
    ev->npv = nan;
    ev->theta = nan;
    ev->charm = nan;
    ev->n = 0;
}

/* QdPlusEval.pre (alo.py:389-396). */
static void pre(struct pl_alo_qdplus *ev, double S) {
    pl_alo_guard(ev->run, S);
    S = pl_max(PL_QL_EPSILON, S);
    ev->sc = S;
    const double v = ev->v;
    const double K = ev->K;
    const double dq = ev->dq;
    const double dr = ev->dr;
    if (v == 0.0) {
        pl_alo_fail(ev->run, PL_ENGINE_PY_DEFECT); /* lg(...) / v: ZeroDivisionError */
        return;
    }
    const double dp = pl_log((S * dq) / (K * dr)) / v + 0.5 * v;
    const double dm = dp - v;
    ev->dp = dp;
    ev->dm = dm;
    ev->Phi_dp = pl_norm_cdf(-dp);
    ev->Phi_dm = pl_norm_cdf(-dm);
    ev->phi_dp = pl_norm_pdf(dp);
    ev->npv = dr * K * ev->Phi_dm - S * dq * ev->Phi_dp;
    const double t1 = ev->r * K * dr * ev->Phi_dm - ev->q * S * dq * ev->Phi_dp;
    ev->theta = t1 - ev->sigma2 * S / (2.0 * v) * dq * ev->phi_dp;
    const double inner = ev->phi_dp * ((ev->r - ev->q) / v - dm / (2.0 * ev->tau));
    ev->charm = -dq * (inner + ev->q * ev->Phi_dp);
}

double pl_alo_qdplus_value(struct pl_alo_qdplus *ev, double S) {
    ev->n += 1;
    ev->run->trace->qd_calls += 1u;
    pl_alo_guard(ev->run, S);
    if (S != ev->sc) {
        pre(ev, S);
        if (ev->run->status != PL_ENGINE_OK) {
            return pl_nan();
        }
    }
    const double npv = pl_alo_mask(ev->run, PL_ALO_SITE_QDPLUS_66, ev->npv);
    const double first = (1.0 - ev->dq * ev->Phi_dp) * S;
    if (pl_alo_close_enough(ev->K - S, npv)) {
        return first + ev->alpha * ev->theta / ev->dr;
    }
    const double c0 = -ev->beta - ev->lam + ev->alpha * ev->theta / (ev->dr * (ev->K - S - npv));
    return first + (ev->lam + c0) * (ev->K - S - npv);
}

double pl_alo_qdplus_derivative(struct pl_alo_qdplus *ev, double S) {
    if (S != ev->sc) {
        pre(ev, S);
        if (ev->run->status != PL_ENGINE_OK) {
            return pl_nan();
        }
    }
    const double dq = ev->dq;
    const double a = 1.0 - dq * ev->Phi_dp + dq / ev->v * ev->phi_dp;
    return a + ev->beta * (1.0 - dq * ev->Phi_dp) + ev->alpha / ev->dr * ev->charm;
}

double pl_alo_qdplus_fprime2(struct pl_alo_qdplus *ev, double S) {
    if (S != ev->sc) {
        pre(ev, S);
        if (ev->run->status != PL_ENGINE_OK) {
            return pl_nan();
        }
    }
    const double v = ev->v;
    const double dq = ev->dq;
    const double dp = ev->dp;
    const double gamma = ev->phi_dp * dq / (v * S);
    const double c = ev->q + (ev->r - ev->q) * dp / v + (1.0 - dp * ev->dm) / (2.0 * ev->tau);
    const double colour = gamma * c;
    const double a = dq * (ev->phi_dp / (S * v) - ev->phi_dp * dp / (S * v * v));
    return a + ev->beta * gamma + ev->alpha / ev->dr * colour;
}
