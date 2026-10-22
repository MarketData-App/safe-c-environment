#include "pl_crr.h"
#include "pl_ieee.h"
#include "pl_solver.h"
#include "pl_vec_solver.h"
#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

/* Bit-exact tests of pl_solver.c against the optionlab vectors (specs/project/models.md "Brent"):
 * status, evaluation count, and root, f_lo and f_hi as equal bits or both NaN. Table solver holds
 * the brief rows (guess (lo + hi) / 2, PL_BRENT_ACCURACY); table solver_edge holds the exact bound
 * rows with their own guess, accuracy and max_evaluations (status 5 is a Python ValueError).
 * REQUIRE-style: the first failed check prints "FAIL <group> <index>" and exits 1 (active under
 * NDEBUG). */

#define D(x) pl_bits_double(x)
/* 1 when the double g has the bits w, or both are NaN; g is a variable or a member. */
#define SAME(g, w) ((pl_double_bits(g) == (w)) | (pl_is_nan(g) & pl_is_nan(D(w))))
#define FAIL(group, i) (printf("FAIL %s %zu\n", group, (size_t)(i)), exit(1))
#define CHECK(group, i, ok) ((ok) ? (void)0 : FAIL(group, i))

_Static_assert(PL_BRENT_N_MAX == PL_BRENT_MAX_EVALUATIONS + 1, "spec 3.5: N_MAX = 201");

/* The expected result of one solve (vector status, count and bits). */
struct want {
    int status, evaluations;
    uint64_t root, f_lo, f_hi;
};

static void cubic(struct pl_objective *o, double c0, double c1, double c2, double c3) {
    o->kind = PL_OBJECTIVE_CUBIC;
    *(o->cubic + 0) = c0;
    *(o->cubic + 1) = c1;
    *(o->cubic + 2) = c2;
    *(o->cubic + 3) = c3;
}

static void expect(const char *group, size_t i, const struct pl_brent_result *r, struct want w) {
    CHECK(group, i, (r->status == w.status) & (r->evaluations == w.evaluations));
    CHECK(group, i, SAME(r->root, w.root));
    CHECK(group, i, SAME(r->f_lo, w.f_lo));
    CHECK(group, i, SAME(r->f_hi, w.f_hi));
}

/* The brief rows: every count is at most N_MAX. */
static void brief_rows(void) {
    for (size_t i = 0; i < PL_VEC_SOLVER_COUNT; i++) {
        const struct pl_vec_solver *v = PL_VEC_SOLVER + i;
        struct pl_objective o = {0};
        struct pl_brent_result r;
        const double lo = D(v->lo);
        const double hi = D(v->hi);
        cubic(&o, D(v->c0), D(v->c1), D(v->c2), D(v->c3));
        pl_brent(&o, lo, hi, (lo + hi) / 2.0, PL_BRENT_ACCURACY, v->max_evaluations, &r);
        const struct want w = {v->status, v->evaluations, v->root, v->f_lo, v->f_hi};
        expect("solver", i, &r, w);
        CHECK("n-max", i, r.evaluations <= PL_BRENT_N_MAX);
    }
}

/* The bound rows: at most max(max_evaluations, 2) + 1 calls. */
static void edge_rows(void) {
    for (size_t i = 0; i < PL_VEC_SOLVER_EDGE_COUNT; i++) {
        const struct pl_vec_solver_edge *v = PL_VEC_SOLVER_EDGE + i;
        struct pl_objective o = {0};
        struct pl_brent_result r;
        cubic(&o, D(v->c0), D(v->c1), D(v->c2), D(v->c3));
        pl_brent(&o, D(v->lo), D(v->hi), D(v->guess), D(v->accuracy), v->max_evaluations, &r);
        const struct want w = {v->status, v->evaluations, v->root, v->f_lo, v->f_hi};
        expect("edge", i, &r, w);
        CHECK("edge-n", i, (r.evaluations <= 3) | (r.evaluations <= v->max_evaluations + 1));
    }
}

/* The brief's three ValueError cases, the C contract, the model objective without parameters
 * (C contract: py_defect at the first call), the ALO slot and an unknown kind (py_defect at the
 * first call), a BAW point that baw_admit refuses (domain with bit 64 at the first call), and the
 * stop rules for py_defect and domain. */
static void direct(void) {
    struct pl_objective o = {0};
    struct pl_brent_result r;
    cubic(&o, 0.0, 0.0, 1.0, -1.5);
    pl_brent(&o, 1.0, 1.0, 1.0, PL_BRENT_ACCURACY, 200, &r); /* invalid range */
    CHECK("defect", 0u, (r.status == PL_BRENT_DEFECT) & (r.evaluations == 0));
    pl_brent(&o, 1.0, 2.0, 1.5, 0.0, 200, &r); /* accuracy not positive */
    CHECK("defect", 1u, (r.status == PL_BRENT_DEFECT) & (r.evaluations == 0));
    pl_brent(&o, 1.0, 2.0, 2.0, PL_BRENT_ACCURACY, 200, &r); /* guess not strictly inside */
    CHECK("defect", 2u, (r.status == PL_BRENT_DEFECT) & (r.evaluations == 2) & pl_is_nan(r.root));
    pl_brent(NULL, 1.0, 2.0, 1.5, PL_BRENT_ACCURACY, 200, &r);
    CHECK("contract", 0u, (r.status == PL_BRENT_DEFECT) & (r.evaluations == 0));
    pl_brent(&o, 1.0, 2.0, 1.25, PL_BRENT_ACCURACY, INT_MAX, &r);
    CHECK("contract", 1u, (r.status == PL_BRENT_DEFECT) & (r.evaluations == 0));
    pl_brent(&o, 1.0, 2.0, 1.25, PL_BRENT_ACCURACY, INT_MAX - 1, &r);
    CHECK("contract", 2u, (r.status == PL_BRENT_OK) & (r.evaluations == 5));
    pl_brent(&o, 1.0, 2.0, 1.25, PL_BRENT_ACCURACY, 200, NULL);
    CHECK("contract", 3u, pl_is_nan(pl_objective_value(NULL, 1.0)));
    struct pl_objective m = {0};
    m.kind = PL_OBJECTIVE_MODEL;
    pl_brent(&m, 1.0, 2.0, 1.5, PL_BRENT_ACCURACY, 200, &r);
    CHECK("model", 0u, (r.status == PL_BRENT_DEFECT) & (r.evaluations == 1) & (m.py_defect == 1));
    CHECK("model", 1u, pl_is_nan(r.root) & pl_is_nan(r.f_lo) & pl_is_nan(r.f_hi));
    struct pl_params p;
    pl_case_params(&p);
    struct pl_objective alo = {0};
    alo.kind = PL_OBJECTIVE_MODEL;
    alo.model = PL_MODEL_ALO;
    alo.params = &p;
    alo.row = (struct pl_row){0, 100.0, 100.0, 1.0, 10.0, 11.0, 0.04, 0.012};
    alo.mid = 10.5; /* (bid + ask) / 2 of the row: f(sigma) = V(sigma) - mid */
    alo.last_sigma = pl_nan();
    alo.last_value = pl_nan();
    pl_brent(&alo, 0.0001, 5.0, 2.50005, PL_BRENT_ACCURACY, 200, &r);
    const int solved = (r.status == PL_BRENT_OK) & (alo.py_defect == 0) & (alo.domain == 0);
    const uint64_t root_bits = pl_double_bits(r.root);
    const int last = (alo.uncounted == 0u) & (pl_double_bits(alo.last_sigma) == root_bits);
    CHECK("model", 2u, solved & last); /* Task 10b: the ALO slot is wired; the IV-call fact */
    struct pl_objective boundary = {0};
    boundary.kind = PL_OBJECTIVE_ALO_BOUNDARY;
    const double bv = pl_objective_value(&boundary, 1.0);
    CHECK("model", 5u, pl_is_nan(bv) & (boundary.py_defect == 1)); /* no evaluator: C contract */
    struct pl_objective baw = {0};
    baw.kind = PL_OBJECTIVE_MODEL;
    baw.model = PL_MODEL_BAW;
    baw.params = &p;
    baw.row = (struct pl_row){1, 100.0, 100.0, 1.0, 10.0, 11.0, -0.05, 0.0};
    pl_brent(&baw, 0.0001, 5.0, 2.50005, PL_BRENT_ACCURACY, 200, &r);
    const int refused = (baw.flags == PL_FLAG_ADMIT_EXCLUDED) & (baw.domain == 1);
    CHECK("model", 4u, (r.status == PL_BRENT_DOMAIN) & (r.evaluations == 1) & refused);
    struct pl_objective unknown = {0};
    unknown.kind = 7;
    CHECK("model", 3u, pl_is_nan(pl_objective_value(&unknown, 1.0)) & (unknown.py_defect == 1));
    o.domain = 1;
    pl_brent(&o, 1.0, 2.0, 1.5, PL_BRENT_ACCURACY, 200, &r);
    CHECK("domain", 0u, (r.status == PL_BRENT_DOMAIN) & (r.evaluations == 1) & pl_is_nan(r.f_lo));
    o.py_defect = 1;
    pl_brent(&o, 1.0, 2.0, 1.5, PL_BRENT_ACCURACY, 200, &r);
    CHECK("domain", 1u, (r.status == PL_BRENT_DEFECT) & (r.evaluations == 1));
}

int main(void) {
    brief_rows();
    edge_rows();
    direct();
    puts("PASS solver");
    return 0;
}
