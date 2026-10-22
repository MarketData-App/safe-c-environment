/* Transcribed from QuantLib 1.43 (QL_VERSION 1.43; retained source
 * benchmarks/project/third_party/sources/QuantLib-1.43.tar.gz, sha256
 * b41206ccc4ba39b5e86bdc940d51138222b352f79d2c6fc68649f9c9bbe58701), via optionlab/baw_admit.py
 * lines 212-248: the replay of ql/pricingengines/vanilla/baroneadesiwhaleyengine.cpp 39-138
 * (the seed 50-74, the map 79-96 and 113-118, the updates 98 and 120) with the certificate of
 * spec Appendix G-BAW item R4, ql/termstructures/yield/flatforward.hpp 102-105,
 * ql/interestrate.hpp 69-71, ql/interestrate.cpp 53-54 (the discounts at t = 1.0). QuantLib license
 * (BSD-3-Clause): the copyright notices, conditions and disclaimer are in NOTICE-QuantLib.md of
 * this example (LR-EX 2026-10-18). */
#include "pl_baw.h"
#include "pl_ieee.h"
#include "pl_types.h"
#include <stddef.h>

/* The shared BAW pre-check baw_admit and its rate part (specs/project/models.md "BAW (Amendment
 * G)"), copied from optionlab.baw_admit statement by statement (Amendment F item 8, N1a). The
 * map, the seed and the certificate are opaque calls into pl_baw_map.c and pl_baw_cert.c (the
 * GCC analyzer budget of one translation unit). The replay makes at most PL_BAW_NEWTON_MAX
 * updates. */

int pl_baw_admit_rates(int side, double r1, double q1, int *admitted) {
    double d_r = 0.0;
    double d_q = 0.0;
    pl_baw_discounts(r1, q1, &d_r, &d_q);
    *admitted = 1;
    if (d_q >= 1.0 && side == 0) {
        return 0;
    }
    const int finite = pl_is_finite(d_r) & pl_is_finite(d_q);
    if (!(finite && d_r > 0.0 && d_q > 0.0) || !(d_r <= 1.0)) {
        *admitted = 0;
    }
    return 1;
}

/* The end of one baw_admit call: the locals into out->values and the exit position. */
static void admit_exit(struct pl_baw_admit *out, const double *loc, int exit_position, int in_scope,
                       int admitted) {
    double *w = out->values;
    *(w + PL_BAW_A_DR) = *(loc + PL_BAW_A_DR);
    *(w + PL_BAW_A_DQ) = *(loc + PL_BAW_A_DQ);
    *(w + PL_BAW_A_N) = *(loc + PL_BAW_A_N);
    *(w + PL_BAW_A_M) = *(loc + PL_BAW_A_M);
    *(w + PL_BAW_A_BT) = *(loc + PL_BAW_A_BT);
    *(w + PL_BAW_A_QU) = *(loc + PL_BAW_A_QU);
    *(w + PL_BAW_A_SU) = *(loc + PL_BAW_A_SU);
    *(w + PL_BAW_A_H) = *(loc + PL_BAW_A_H);
    *(w + PL_BAW_A_SI) = *(loc + PL_BAW_A_SI);
    *(w + PL_BAW_A_KC) = *(loc + PL_BAW_A_KC);
    *(w + PL_BAW_A_Q) = *(loc + PL_BAW_A_Q);
    *(w + PL_BAW_A_J) = *(loc + PL_BAW_A_J);
    *(w + PL_BAW_A_X) = *(loc + PL_BAW_A_X);
    *(w + PL_BAW_A_LHS) = *(loc + PL_BAW_A_LHS);
    *(w + PL_BAW_A_RHS) = *(loc + PL_BAW_A_RHS);
    *(w + PL_BAW_A_BI) = *(loc + PL_BAW_A_BI);
    *(w + PL_BAW_A_NC) = *(loc + PL_BAW_A_NC);
    *(w + PL_BAW_A_EXIT) = (double)exit_position;
    out->in_scope = in_scope;
    out->admitted = admitted;
}

/* The seed checks 2c-2e of record R4 item 2 (baw_admit.py:232-234): 0 when they pass, else the
 * exit position (4, 5 or 6). */
static int seed_checks(int side, double K, const struct pl_baw_seed *s) {
    const int a = pl_is_finite(s->n) & pl_is_finite(s->m) & pl_is_finite(s->bT);
    const int b = pl_is_finite(s->qu) & pl_is_finite(s->Su) & pl_is_finite(s->h);
    if ((a & b & pl_is_finite(s->Si)) == 0) {
        return 4;
    }
    const int bracket = (side == 0) ? (s->Su > K) : (0.0 < s->Su && s->Su < K);
    if (!bracket) {
        return 5;
    }
    if (!(s->Si > 0.0)) {
        return 6;
    }
    return 0;
}

/* The replay with certificate of record R4 item 3 (baw_admit.py:237-248) from x = S_i. Returns
 * the exit position (8 to 13), or 0 where the certificate raises (out->defect set). */
static int replay(int side, double K, double d_r, double d_q, double v, double Q, double *loc,
                  struct pl_baw_admit *out) {
    const int cap = PL_BAW_NEWTON_MAX;
    double x = *(loc + PL_BAW_A_SI);
    double trace[PL_BAW_CERT_FIELDS];
    for (int j = 0; j <= cap; j++) {
        *(loc + PL_BAW_A_J) = (double)j;
        *(loc + PL_BAW_A_X) = x;
        if (!(pl_is_finite(x) && x > 0.0)) {
            return 8;
        }
        double lhs = 0.0;
        double rhs = 0.0;
        double bi = 0.0;
        if (pl_baw_map(side, x, K, d_r, d_q, v, Q, &lhs, &rhs, &bi) != 0) {
            return 9;
        }
        *(loc + PL_BAW_A_LHS) = lhs;
        *(loc + PL_BAW_A_RHS) = rhs;
        *(loc + PL_BAW_A_BI) = bi;
        if ((pl_is_finite(lhs) & pl_is_finite(rhs) & pl_is_finite(bi)) == 0) {
            return 10;
        }
        if (pl_baw_stop(lhs, rhs, K)) {
            return 11;
        }
        if (j < cap) {
            int zd = 0;
            const int nc =
                pl_baw_certificate(side, x, K, d_r, d_q, v, Q, lhs, rhs, bi, cap, trace, &zd);
            if (zd != 0) {
                out->defect = 1;
                return 0;
            }
            *(loc + PL_BAW_A_NC) = (double)nc; /* -1.0 for None */
            if (nc >= 0 && j + nc <= cap) {
                return 12;
            }
            x = pl_baw_update(side, x, K, rhs, bi);
        }
    }
    *(loc + PL_BAW_A_X) = x;
    return 13;
}

void pl_baw_admit(int side, double S, double K, double r1, double q1, double v,
                  struct pl_baw_admit *out) {
    (void)S;
    double loc[PL_BAW_ADMIT_FIELDS];
    const double nan = pl_nan();
    for (size_t f = 0; f < PL_BAW_ADMIT_FIELDS; f++) {
        *(loc + f) = nan;
    }
    out->count = PL_BAW_ADMIT_FIELDS;
    out->defect = 0;
    double d_r = 0.0;
    double d_q = 0.0;
    pl_baw_discounts(r1, q1, &d_r, &d_q);
    *(loc + PL_BAW_A_DR) = d_r;
    *(loc + PL_BAW_A_DQ) = d_q;
    if (d_q >= 1.0 && side == 0) {
        admit_exit(out, loc, 1, 0, 1); /* 1. branch gate (line 167) */
        return;
    }
    const int finite = pl_is_finite(d_r) & pl_is_finite(d_q) & pl_is_finite(v);
    if (!(finite && d_r > 0.0 && d_q > 0.0 && v > 0.0)) {
        admit_exit(out, loc, 2, 1, 0); /* 2a */
        return;
    }
    if (!(d_r <= 1.0)) {
        admit_exit(out, loc, 3, 1, 0); /* 2b (lines 45-48) */
        return;
    }
    struct pl_baw_seed s;
    pl_baw_seed(side, K, d_r, d_q, v, &s);
    *(loc + PL_BAW_A_N) = s.n;
    *(loc + PL_BAW_A_M) = s.m;
    *(loc + PL_BAW_A_BT) = s.bT;
    *(loc + PL_BAW_A_QU) = s.qu;
    *(loc + PL_BAW_A_SU) = s.Su;
    *(loc + PL_BAW_A_H) = s.h;
    *(loc + PL_BAW_A_SI) = s.Si;
    const int seed_exit = seed_checks(side, K, &s);
    if (seed_exit != 0) {
        admit_exit(out, loc, seed_exit, 1, 0); /* 2c, 2d, 2e */
        return;
    }
    const double kc = pl_baw_kcoef(d_r, v);
    const double q = pl_baw_qexp(side, s.n, kc);
    *(loc + PL_BAW_A_KC) = kc;
    *(loc + PL_BAW_A_Q) = q;
    if (!(pl_is_finite(kc) && pl_is_finite(q)) || q == 0.0) {
        admit_exit(out, loc, 7, 1, 0); /* 2f */
        return;
    }
    const int exit_position = replay(side, K, d_r, d_q, v, q, loc, out);
    if (exit_position == 0) {
        admit_exit(out, loc, 0, 1, 0); /* the certificate raised: a Python defect (fail closed) */
        return;
    }
    admit_exit(out, loc, exit_position, 1, exit_position == 11 || exit_position == 12);
}
