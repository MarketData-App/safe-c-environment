#include "pl_baw.h"
#include "pl_crr.h"
#include "pl_evaluate.h"
#include "pl_ieee.h"
#include "pl_types.h"
#include "pl_vec_baw_greeks.h"
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

/* Bit-exact test of the BAW greek step (pl_baw_price_and_greeks and the BAW branch of
 * pl_price_and_greeks) against reference.baw_greeks with the counter of reference.evaluate
 * (specs/project/models.md "BAW (Amendment G)"): status (0 OK, 1 order 5, 2 run defect), band,
 * flags 16, 32 and 64, the engine-evaluation count and the seven values as equal bits or both
 * NaN, for the case, the forced-cap and the planted parameter sets. REQUIRE-style: the first
 * failed check prints "FAIL <group> <index>" and exits 1. */

#define D(x) pl_bits_double(x)
#define SAME(g, w) ((pl_double_bits(g) == (w)) | (pl_is_nan(g) & pl_is_nan(D(w))))
#define FAIL(group, i) (printf("FAIL %s %zu\n", group, (size_t)(i)), exit(1))
#define CHECK(group, i, ok) ((ok) ? (void)0 : FAIL(group, i))

/* 1 when every value has the bits of the row, or both are NaN. */
static int same_values(const double *g, const struct pl_vec_baw_greeks *v) {
    const int a = SAME(*(g + 0), v->iv) & SAME(*(g + 1), v->price) & SAME(*(g + 2), v->delta);
    const int b = SAME(*(g + 3), v->gamma) & SAME(*(g + 4), v->theta) & SAME(*(g + 5), v->vega);
    return a & b & SAME(*(g + 6), v->rho);
}

struct tally {
    size_t switched, unresolved, bump, exercise, defect_cap, defect_plant, ok;
};

static void greeks_row(size_t i, const struct pl_vec_baw_greeks *v, struct tally *t) {
    struct pl_params p;
    pl_case_params(&p);
    p.baw_newton_max = (v->params == 1) ? 1 : p.baw_newton_max;
    p.baw_plant_nonfinite_sstar = (v->params == 2) ? 1 : 0;
    const struct pl_row row = {v->side, D(v->S), D(v->K), D(v->T), 1.0, 1.0, D(v->r), D(v->q)};
    double values[PL_FIELDS];
    int band = 7;
    uint8_t flags = 0u;
    uint32_t evals = 0u;
    int defect = 0;
    const double s = D(v->sigma);
    const int st = pl_baw_price_and_greeks(&row, s, &p, values, &band, &flags, &evals, &defect);
    const int status = (defect != 0) ? 2 : st;
    const int raised = v->status == 2;
    const int same = (flags == v->flags) & (band == v->band) & (evals == (uint32_t)v->engine_evals);
    CHECK("greeks", i, (status == v->status) & (raised | (same & same_values(values, v))));
    /* the Task 11 interface: the same status and flags through pl_price_and_greeks */
    double w[PL_FIELDS];
    int b2 = 0;
    uint8_t f2 = 0u;
    uint32_t n2 = 0u;
    const int st2 = pl_price_and_greeks(PL_MODEL_BAW, &row, D(v->sigma), &p, w, &b2, &f2, &n2);
    CHECK("price-and-greeks", i, (st2 == v->status) & (raised | ((f2 == flags) & (n2 == evals))));
    const unsigned ok = (unsigned)(v->status == 0);
    const int exact = (pl_fabs(*(values + 2)) == 1.0) & (*(values + 3) == 0.0) &
                      (*(values + 4) == 0.0) & (*(values + 5) == 0.0) & (*(values + 6) == 0.0);
    t->ok += ok;
    t->switched += (size_t)(ok & (unsigned)((v->flags & 32) != 0));
    t->unresolved += (size_t)((v->flags & 16) != 0);
    t->bump += (size_t)(((v->flags & 64) != 0) & (v->admit_reason == 3));
    t->exercise += (size_t)(ok & (unsigned)exact);
    t->defect_cap += (size_t)(raised & (v->params == 1));
    t->defect_plant += (size_t)(raised & (v->params == 2));
}

int main(void) {
    struct tally t = {0u, 0u, 0u, 0u, 0u, 0u, 0u};
    for (size_t i = 0; i < PL_VEC_BAW_GREEKS_COUNT; i++) {
        greeks_row(i, PL_VEC_BAW_GREEKS + i, &t);
    }
    printf("PASS greeks %zu ok %zu switched %zu\n", PL_VEC_BAW_GREEKS_COUNT, t.ok, t.switched);
    printf("PASS greeks unresolved %zu bump %zu exercise %zu\n", t.unresolved, t.bump, t.exercise);
    printf("PASS greeks defects %zu %zu\n", t.defect_cap, t.defect_plant);
    CHECK("coverage", 0u, (t.switched > 0u) & (t.exercise > 0u) & (t.bump > 0u));
    CHECK("coverage", 2u, t.unresolved > 0u); /* bit 16: puts with r < h_r / 16 next to S* */
    CHECK("coverage", 1u, (t.defect_cap > 0u) & (t.defect_plant > 0u) & (t.ok > 0u));
    return 0;
}
