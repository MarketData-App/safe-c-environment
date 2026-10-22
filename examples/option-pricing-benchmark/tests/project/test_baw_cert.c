#include "pl_baw.h"
#include "pl_ieee.h"
#include "pl_types.h"
#include "pl_vec_baw_cert.h"
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

/* Bit-exact tests of pl_baw_admit on the record R4 boundary vectors and of pl_baw_certificate
 * (specs/project/models.md "BAW (Amendment G)"). Table baw_bound: baw_admit on both sides of
 * each boundary (q' at +-2^-54, v at 0, 5e-324, NaN, inf, r' at the D_r <= 1 flip and the
 * overflow bound, the close_n flip of the coefficient K) and rows of every exit position that
 * a search finds. Table baw_cert: certificate calls of the replays, the rate loop with cap 0, 1
 * and 2, and crafted calls where a plain Python division raises (the defect output). Equal bits
 * or both NaN for every intermediate. REQUIRE-style: the first failed check prints
 * "FAIL <group> <index>" and exits 1. */

#define D(x) pl_bits_double(x)
#define SAME(g, w) ((pl_double_bits(g) == (w)) | (pl_is_nan(g) & pl_is_nan(D(w))))
#define FAIL(group, i) (printf("FAIL %s %zu\n", group, (size_t)(i)), exit(1))
#define CHECK(group, i, ok) ((ok) ? (void)0 : FAIL(group, i))

/* 1 when each of the n values has the bits of want, or both are NaN. */
static int same_values(const double *got, const uint64_t *want, size_t n) {
    int ok = 1;
    for (size_t f = 0; f < n; f++) {
        ok &= SAME(*(got + f), *(want + f));
    }
    return ok;
}

/* The exit position of a vector row as a bit (bits 0 to 15; positions outside give 0). */
static unsigned exit_bit(uint64_t bits) {
    const double e = D(bits);
    if (!(e >= 0.0 && e < 16.0)) {
        return 0u;
    }
    return 1u << (unsigned)e;
}

/* One row of table baw_bound (S = 100.0). Returns the bit of its exit position. */
static unsigned bound_row(size_t i, const struct pl_vec_baw_bound *v) {
    struct pl_baw_admit a;
    pl_baw_admit(v->side, 100.0, D(v->K), D(v->r1), D(v->q1), D(v->v), &a);
    const int bools = (a.in_scope == v->in_scope) & (a.admitted == v->admitted);
    const int defect = (a.defect == v->defect) & (a.count == PL_BAW_ADMIT_FIELDS);
    const int values = (v->defect != 0) | same_values(a.values, v->values, PL_BAW_ADMIT_FIELDS);
    CHECK("baw-bound", i, bools & defect & values);
    return (v->defect != 0) ? 0u : exit_bit(*(v->values + PL_BAW_A_EXIT));
}

/* One row of table baw_cert. Returns 1 for a defect row, else 0. */
static int cert_row(size_t i, const struct pl_vec_baw_cert *v, unsigned *exits) {
    double trace[PL_BAW_CERT_FIELDS];
    int defect = 0;
    const double x0 = D(v->x0);
    const double K = D(v->K);
    const double d_r = D(v->D_r);
    const double d_q = D(v->D_q);
    const double var = D(v->v);
    const double Q = D(v->Q);
    const double lhs = D(v->LHS);
    const double rhs = D(v->RHS);
    const double bi = D(v->bi);
    const int side = v->side;
    const int cap = v->cap;
    const int nc =
        pl_baw_certificate(side, x0, K, d_r, d_q, var, Q, lhs, rhs, bi, cap, trace, &defect);
    const int values = (v->defect != 0) | same_values(trace, v->values, PL_BAW_CERT_FIELDS);
    CHECK("baw-cert", i, (nc == v->nc) & (defect == v->defect) & values);
    if (v->defect == 0) {
        *exits |= exit_bit(*(v->values + PL_BAW_CERT_FIELDS - 1u));
    }
    return v->defect != 0;
}

int main(void) {
    CHECK("field-count", 0u, PL_VEC_BAW_CERT_FIELDS == PL_BAW_CERT_FIELDS);
    unsigned bound_exits = 0u;
    for (size_t i = 0; i < PL_VEC_BAW_BOUND_COUNT; i++) {
        bound_exits |= bound_row(i, PL_VEC_BAW_BOUND + i);
    }
    printf("PASS baw-bound %zu exits 0x%x\n", PL_VEC_BAW_BOUND_COUNT, bound_exits);
    unsigned cert_exits = 0u;
    size_t defects = 0u;
    for (size_t i = 0; i < PL_VEC_BAW_CERT_COUNT; i++) {
        defects += (size_t)cert_row(i, PL_VEC_BAW_CERT + i, &cert_exits);
    }
    printf("PASS baw-cert %zu defects %zu\n", PL_VEC_BAW_CERT_COUNT, defects);
    printf("PASS baw-cert exits 0x%x\n", cert_exits);
    /* bound exits: 1 branch gate, 2 check 2a, 3 check 2b, 4 check 2c, 5 check 2d, 11 stop test,
     * 12 certificate; certificate exits: 1 (dh) and 2 to 8 (each check at its exact bound or one
     * past it), 9 (N_C = 0), 10 (rate loop), 11 (no k) */
    const unsigned need_bound = (1u << 1u) | (1u << 2u) | (1u << 3u) | (1u << 4u) | (1u << 5u);
    CHECK("coverage", 0u, (bound_exits & need_bound) == need_bound);
    const unsigned need_replay = (1u << 11u) | (1u << 12u);
    CHECK("coverage", 1u, (bound_exits & need_replay) == need_replay);
    const unsigned low_a = (1u << 1u) | (1u << 2u) | (1u << 3u) | (1u << 4u);
    const unsigned need_low = low_a | (1u << 5u) | (1u << 6u) | (1u << 7u) | (1u << 8u);
    CHECK("coverage", 3u, (cert_exits & need_low) == need_low);
    const unsigned need_cert = (1u << 9u) | (1u << 10u) | (1u << 11u);
    CHECK("coverage", 2u, ((cert_exits & need_cert) == need_cert) & (defects >= 2u));
    return 0;
}
