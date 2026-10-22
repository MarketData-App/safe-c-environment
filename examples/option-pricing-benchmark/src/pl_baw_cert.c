/* Transcribed from QuantLib 1.43 (QL_VERSION 1.43; retained source
 * benchmarks/project/third_party/sources/QuantLib-1.43.tar.gz, sha256
 * b41206ccc4ba39b5e86bdc940d51138222b352f79d2c6fc68649f9c9bbe58701), via optionlab/baw_admit.py
 * lines 155-210: the certificate of spec Appendix G-BAW item R4 over the map of
 * ql/pricingengines/vanilla/baroneadesiwhaleyengine.cpp 79-131. QuantLib license (BSD-3-Clause):
 * the copyright notices, conditions and disclaimer are in NOTICE-QuantLib.md of this example (LR-EX
 * 2026-10-18). */
#include "pl_baw.h"
#include "pl_ieee.h"
#include "pl_types.h"
#include <stddef.h>

/* The closed-form certificate C(x0) of record R4 item 4 (specs/project/models.md "BAW
 * (Amendment G)"), copied from optionlab.baw_admit.certificate and _sups statement by statement
 * (Amendment F item 8, N1a); its own translation unit for the GCC analyzer budget. The plain
 * Python divisions whose divisor is not guarded by an earlier test are pl_py_div: a zero divisor
 * is a Python ZeroDivisionError (the defect output). The guarded ones (gh / dh with dh != 0.0,
 * / dlow and / m after the tests > 0.0) are IEEE C division. Python sums are pl_sum2, pl_sum3
 * and pl_sum4 (left to right; a - b as pl_sum2(a, -b), the same bits), opaque results that keep
 * the GCC analyzer within its fixed symbolic-depth budget. */

/* baw_admit.U, NBAR, NBAR1 and TOL; the factors 1 + 2^-40, 1 + 2^-30 and 0.5 (1 - 2^-20). */
static const double PL_BAW_U = 0x1p-53;
static const double PL_BAW_NBAR = 0x1.9884533d43651p-2;
static const double PL_BAW_NBAR1 = 0x1.ef8e58e331739p-3;
static const double PL_BAW_CERT_TOL = 0x1.0c6f7a0b5ed8dp-20;
static const double PL_BAW_UP40 = 0x1.0000000001p+0;
static const double PL_BAW_UP30 = 0x1.00000004p+0;
static const double PL_BAW_RHO_MAX = 0x1.ffffep-2;

/* Positions of cvectors.CERT_FIELDS. */
enum cert_field {
    C_SIG = 0,
    C_AQ,
    C_GH,
    C_DH,
    C_BHAT,
    C_W,
    C_R,
    C_XLO,
    C_XHI,
    C_SIGB,
    C_GAM,
    C_NU,
    C_CR,
    C_DG,
    C_DB,
    C_DLOW,
    C_BETA,
    C_LLO,
    C_LHI,
    C_DLO,
    C_DHI,
    C_DELTA,
    C_SN,
    C_SDN,
    C_L,
    C_M,
    C_MM,
    C_ETA,
    C_TARGET,
    C_RHO,
    C_B,
    C_K,
    C_EXIT
};

/* Python min(a, b): b only when b < a. */
static double py_min(double a, double b) { return (b < a) ? b : a; }

/* baw_admit._sups (baw_admit.py:155-165). */
static void sups(double dlo, double dhi, double *s_n, double *s_dn) {
    const double dmin = (dlo <= 0.0 && 0.0 <= dhi) ? 0.0 : py_min(pl_fabs(dlo), pl_fabs(dhi));
    if (dmin >= 37.5) {
        *s_n = 0x1.ac9a7b3b7302fp-994; /* 1e-299 */
        *s_dn = 0x1.ac9a7b3b7302fp-994;
        return;
    }
    *s_n = PL_BAW_NBAR * pl_exp(-(dmin * dmin) / 2.0) * PL_BAW_UP40;
    if ((dlo <= 1.0 && 1.0 <= dhi) || (dlo <= -1.0 && -1.0 <= dhi)) {
        *s_dn = PL_BAW_NBAR1;
        return;
    }
    const double end_lo = pl_fabs(dlo) * (PL_BAW_NBAR * pl_exp(-(dlo * dlo) / 2.0));
    const double end_hi = pl_fabs(dhi) * (PL_BAW_NBAR * pl_exp(-(dhi * dhi) / 2.0));
    *s_dn = pl_max(end_lo, end_hi) * PL_BAW_UP40;
}

/* One return of certificate: the exit position, then -1 with *defect = 1 when a plain division
 * raised before this return, else result. */
static int cert_exit(double *trace, int exit_position, int result, int zd, int *defect) {
    *(trace + C_EXIT) = (double)exit_position;
    if (zd != 0) {
        *defect = 1;
        return -1;
    }
    return result;
}

/* The rate part of certificate (baw_admit.py:207-210): the least k in 1 ... cap with
 * M max((2 rho)^(2^k) m / L, 2 eta) <= target, else -1. */
static int rate(double *trace, double rho, double M, double m, double L, double eta, double target,
                int cap) {
    double b = 2.0 * rho;
    *(trace + C_B) = b;
    for (int k = 1; k <= cap; k++) {
        b = b * b;
        *(trace + C_B) = b;
        *(trace + C_K) = (double)k;
        if (M * pl_max(b * m / L, 2.0 * eta) <= target) {
            *(trace + C_EXIT) = 10.0;
            return k;
        }
    }
    *(trace + C_EXIT) = 11.0;
    return -1;
}

int pl_baw_certificate(int side, double x0, double K, double d_r, double d_q, double v, double Q,
                       double lhs, double rhs, double bi, int cap, double trace[PL_BAW_CERT_FIELDS],
                       int *defect) {
    const double nan = pl_nan();
    for (size_t f = 0; f < PL_BAW_CERT_FIELDS; f++) {
        *(trace + f) = nan;
    }
    int zd = 0;
    const double sig = pl_sqrt(v);
    const double aq = pl_fabs(Q);
    const double gh = lhs - rhs;
    const double dh = (side == 0) ? (1.0 - bi) : (-1.0 - bi);
    *(trace + C_SIG) = sig;
    *(trace + C_AQ) = aq;
    *(trace + C_GH) = gh;
    *(trace + C_DH) = dh;
    if (!(pl_is_finite(gh) && pl_is_finite(dh)) || dh == 0.0) {
        return cert_exit(trace, 1, -1, zd, defect);
    }
    const double bhat = pl_fabs(gh / dh);
    const double w = 0x1p-24 * (x0 + K);
    const double R = 8.0 * bhat + w;
    const double xlo = x0 - R;
    const double xhi = x0 + R;
    *(trace + C_BHAT) = bhat;
    *(trace + C_W) = w;
    *(trace + C_R) = R;
    *(trace + C_XLO) = xlo;
    *(trace + C_XHI) = xhi;
    if (!(xlo > 0.0) || !pl_is_finite(xhi)) {
        return cert_exit(trace, 2, -1, zd, defect);
    }
    const double sigb_a = d_q * pl_fabs(1.0 - pl_py_div(1.0, Q, &zd));
    const double sigb_b = pl_py_div(1.0 + pl_py_div(PL_BAW_NBAR * d_q, sig, &zd), aq, &zd);
    const double sigb = pl_sum2(sigb_a, sigb_b);
    const double gam = pl_sum3(d_q * xhi, d_r * K, pl_py_div((1.0 + d_q) * xhi, aq, &zd));
    const double nu = pl_sum2(pl_py_div(2.0 * (1.0 + 1.5 * v), sig, &zd), 6.0);
    const double cr = 8.0 * PL_BAW_U * (nu + 4.0);
    const double dg = cr * pl_sum3(gam, xhi, K);
    const double db = pl_sum2(cr * sigb, PL_BAW_U * d_q * sig);
    const double dlow = pl_sum2(pl_fabs(dh) * (1.0 - PL_BAW_U), -db);
    *(trace + C_SIGB) = sigb;
    *(trace + C_GAM) = gam;
    *(trace + C_NU) = nu;
    *(trace + C_CR) = cr;
    *(trace + C_DG) = dg;
    *(trace + C_DB) = db;
    *(trace + C_DLOW) = dlow;
    if (!(dlow > 0.0)) {
        return cert_exit(trace, 3, -1, zd, defect);
    }
    const double beta = pl_sum2(pl_fabs(gh), dg) / dlow;
    const double llo = pl_log(pl_py_div(pl_py_div(xlo * d_q, d_r, &zd), K, &zd));
    const double lhi = pl_log(pl_py_div(pl_py_div(xhi * d_q, d_r, &zd), K, &zd));
    const double dlo = pl_py_div(llo + v / 2.0, sig, &zd);
    const double dhi = pl_py_div(lhi + v / 2.0, sig, &zd);
    const double spread = pl_fabs(pl_sum2(pl_py_div(v, sig, &zd), -sig)) / 2.0;
    const double logs = pl_sum4(1.0, pl_fabs(llo), pl_fabs(lhi), v);
    const double delta = pl_sum3(spread, pl_py_div(16.0 * PL_BAW_U * logs, sig, &zd),
                                 16.0 * PL_BAW_U * pl_sum2(pl_fabs(dlo), pl_fabs(dhi)));
    *(trace + C_BETA) = beta;
    *(trace + C_LLO) = llo;
    *(trace + C_LHI) = lhi;
    *(trace + C_DLO) = dlo;
    *(trace + C_DHI) = dhi;
    *(trace + C_DELTA) = delta;
    double s_n = 0.0;
    double s_dn = 0.0;
    sups(dlo - delta, dhi + delta, &s_n, &s_dn);
    const double front = pl_py_div(d_q, xlo * sig, &zd);
    const double sum = pl_sum3(s_n, pl_py_div(s_n, aq, &zd), pl_py_div(s_dn, sig * aq, &zd));
    const double L = front * sum * PL_BAW_UP30;
    const double M = pl_sum3(pl_fabs(dh) * (1.0 + PL_BAW_U), db, L * R);
    const double m = pl_sum2(dlow, -(L * R));
    *(trace + C_SN) = s_n;
    *(trace + C_SDN) = s_dn;
    *(trace + C_L) = L;
    *(trace + C_M) = M;
    *(trace + C_MM) = m;
    if (!(m > 0.0)) {
        return cert_exit(trace, 4, -1, zd, defect);
    }
    if (!(pl_sum2(db, PL_BAW_U * (1.0 + sigb)) <= m / 2.0)) {
        return cert_exit(trace, 5, -1, zd, defect);
    }
    const double inner = pl_sum4(cr * gam, 3.0 * PL_BAW_U * pl_sum3(K, gam, sigb * xhi),
                                 2.0 * xhi * db, PL_BAW_U * xhi * (1.0 + sigb));
    const double eta = pl_sum2(2.0 * inner / m, 2.0 * PL_BAW_U * xhi);
    *(trace + C_ETA) = eta;
    const double reach = pl_sum3(4.0 * beta, 2.0 * eta, 4.0 * PL_BAW_U * xhi);
    if (!(reach <= R && 2.0 * eta <= w)) {
        return cert_exit(trace, 6, -1, zd, defect);
    }
    const double target = 0.25 * PL_BAW_CERT_TOL * K;
    *(trace + C_TARGET) = target;
    if (!(pl_sum2(M * 2.0 * eta, dg) <= target)) {
        return cert_exit(trace, 7, -1, zd, defect);
    }
    const double rho = L * pl_sum2(beta, eta) / m;
    *(trace + C_RHO) = rho;
    if (!(rho <= PL_BAW_RHO_MAX)) {
        return cert_exit(trace, 8, -1, zd, defect);
    }
    if (M * 2.0 * pl_sum2(beta, eta) <= target) {
        return cert_exit(trace, 9, 0, zd, defect);
    }
    const int k = rate(trace, rho, M, m, L, eta, target, cap);
    return cert_exit(trace, (k >= 0) ? 10 : 11, k, zd, defect);
}
