#include "pl_baw.h"
#include "pl_ieee.h"
#include "pl_types.h"
#include "pl_vec_baw_admit.h"
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

/* Bit-exact test of pl_baw_admit against the shared Python baw_admit (N1a, N8;
 * specs/project/models.md "BAW (Amendment G)"). Table baw_admit: the N8 cross-test grid
 * (q' = 0, +-1e-300, +-5e-324, the neighbours of +-2^-53; call and put; three strikes, four r',
 * three v). Per row: in_scope,
 * admitted, defect and every intermediate (D_r and D_q first) as equal bits or both NaN.
 * REQUIRE-style: the first failed check prints "FAIL <group> <index>" and exits 1. */

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

struct tally {
    size_t zero_q, tiny_q, european, admitted, refused, compared;
};

/* One row of table baw_admit (S = 100.0; baw_admit does not read S). */
static void admit_row(size_t i, const struct pl_vec_baw_admit *v, struct tally *t) {
    struct pl_baw_admit a;
    pl_baw_admit(v->side, 100.0, D(v->K), D(v->r1), D(v->q1), D(v->v), &a);
    const int bools = (a.in_scope == v->in_scope) & (a.admitted == v->admitted);
    const int defect = (a.defect == v->defect) & (a.count == PL_VEC_BAW_ADMIT_FIELDS);
    const int values = (v->defect != 0) | same_values(a.values, v->values, PL_VEC_BAW_ADMIT_FIELDS);
    CHECK("baw-admit", i, bools & defect & values);
    const double q1 = D(v->q1);
    const unsigned w = (unsigned)(v->defect == 0);
    t->zero_q += (size_t)(q1 == 0.0);
    t->tiny_q += (size_t)((q1 != 0.0) & (pl_fabs(q1) <= 0x1p-52));
    t->european += (size_t)(w & (unsigned)(v->in_scope == 0));
    t->admitted += (size_t)(w & (unsigned)((v->in_scope != 0) & (v->admitted != 0)));
    t->refused += (size_t)(w & (unsigned)((v->in_scope != 0) & (v->admitted == 0)));
    t->compared += (size_t)w * PL_VEC_BAW_ADMIT_FIELDS;
}

int main(void) {
    CHECK("field-count", 0u, PL_VEC_BAW_ADMIT_FIELDS == PL_BAW_ADMIT_FIELDS);
    CHECK("field-count", 1u, PL_BAW_ADMIT_FIELDS <= PL_BAW_ADMIT_MAX_FIELDS);
    struct tally t = {0u, 0u, 0u, 0u, 0u, 0u};
    for (size_t i = 0; i < PL_VEC_BAW_ADMIT_COUNT; i++) {
        admit_row(i, PL_VEC_BAW_ADMIT + i, &t);
    }
    printf("PASS baw-admit %zu\n", PL_VEC_BAW_ADMIT_COUNT);
    printf("PASS baw-admit zero-q %zu tiny-q %zu\n", t.zero_q, t.tiny_q);
    printf("PASS baw-admit european %zu admitted %zu\n", t.european, t.admitted);
    printf("PASS baw-admit refused %zu compared %zu\n", t.refused, t.compared);
    CHECK("coverage", 0u, (t.zero_q > 0u) & (t.tiny_q > 0u) & (t.european > 0u));
    CHECK("coverage", 1u, (t.admitted > 0u) & (t.refused > 0u));
    CHECK("coverage", 2u, t.compared == PL_VEC_BAW_ADMIT_COUNT * PL_VEC_BAW_ADMIT_FIELDS);
    return 0;
}
