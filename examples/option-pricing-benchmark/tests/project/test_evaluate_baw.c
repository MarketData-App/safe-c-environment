#include "pl_baw.h"
#include "pl_crr.h"
#include "pl_evaluate.h"
#include "pl_ieee.h"
#include "pl_types.h"
#include "pl_vec_evaluate_baw.h"
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

/* Bit-exact test of pl_evaluate for PL_MODEL_BAW against reference.evaluate
 * (specs/project/models.md "Row evaluation" and "BAW (Amendment G)"): every row of part
 * evaluate and the BAW rows (row, Brent and bump exclusions, the stencil near S*, the
 * exercise-side root, sigma_lo(BAW) >= 5.0 at its bound, the forced-cap and planted run
 * defects). Equal status, flags (16, 32, 64 included) and engine-evaluation count, the seven
 * values as equal bits or both NaN, and PL_EVAL_DEFECT exactly where Python raised. A test file
 * of its own: the AST dump size limit of the source-policy gate (Task 11 review M3).
 * REQUIRE-style: the first failed check prints "FAIL <group> <index>" and exits 1. */

#define D(x) pl_bits_double(x)
#define SAME(g, w) ((pl_double_bits(g) == (w)) | (pl_is_nan(g) & pl_is_nan(D(w))))
#define FAIL(group, i) (printf("FAIL %s %zu\n", group, (size_t)(i)), exit(1))
#define CHECK(group, i, ok) ((ok) ? (void)0 : FAIL(group, i))

static int same_values(const double *g, const struct pl_vec_evaluate_baw *v) {
    const int a = SAME(*(g + 0), v->iv) & SAME(*(g + 1), v->price) & SAME(*(g + 2), v->delta);
    const int b = SAME(*(g + 3), v->gamma) & SAME(*(g + 4), v->theta) & SAME(*(g + 5), v->vega);
    return a & b & SAME(*(g + 6), v->rho);
}

static int all_nan(const double *g) {
    const int a = pl_is_nan(*(g + 0)) & pl_is_nan(*(g + 1)) & pl_is_nan(*(g + 2));
    const int b = pl_is_nan(*(g + 3)) & pl_is_nan(*(g + 4)) & pl_is_nan(*(g + 5));
    return a & b & pl_is_nan(*(g + 6));
}

struct tally {
    size_t defects, ok, switched, unresolved, excluded[4];
};

static void evaluate_row(size_t i, const struct pl_vec_evaluate_baw *v, struct tally *t) {
    struct pl_params p;
    pl_case_params(&p);
    p.sigma_hi = D(v->sigma_hi);
    p.kappa_cap = D(v->kappa_cap);
    p.baw_newton_max = v->newton_max;
    p.baw_plant_nonfinite_sstar = v->plant;
    struct pl_row row;
    row.side = v->side;
    row.S = D(v->S);
    row.K = D(v->K);
    row.T = D(v->T);
    row.bid = D(v->bid);
    row.ask = D(v->ask);
    row.r = D(v->r);
    row.q = D(v->q);
    struct pl_model_result out;
    uint32_t evals = 7u;
    const enum pl_eval_error e = pl_evaluate(&row, PL_MODEL_BAW, &p, &out, &evals);
    const int raised = (e == PL_EVAL_DEFECT) & (out.status == PL_INVALID_INPUT) & (out.flags == 0u);
    const int defect_ok = raised & (evals == 0u) & all_nan(out.values);
    const int same = (e == PL_EVAL_OK) & (out.status == v->status) & (out.flags == v->flags);
    const int row_ok = same & (evals == (uint32_t)v->engine_evals) & same_values(out.values, v);
    CHECK("evaluate-baw", i, (v->defect != 0) ? defect_ok : row_ok);
    const unsigned w = (unsigned)(v->defect == 0);
    t->defects += 1u - w;
    t->ok += (size_t)(w & (unsigned)(v->status == PL_OK));
    t->switched += (size_t)(w & (unsigned)((v->flags & 32) != 0));
    t->unresolved += (size_t)(w & (unsigned)((v->flags & 16) != 0));
    if ((v->flags & 64) != 0 && v->admit_reason >= 0 && v->admit_reason <= 3) {
        *(t->excluded + v->admit_reason) += 1u; /* C reports no reason (AG4-02); coverage only */
    }
}

/* The C contract of baw_newton_max (0 to PL_BAW_NEWTON_MAX, for every model; moved here from
 * test_evaluate.c, which is at the AST dump size limit). */
static void newton_max_contract(void) {
    struct pl_params p;
    pl_case_params(&p);
    const struct pl_row row = {0, 100.0, 100.0, 1.0, 10.0, 11.0, 0.04, 0.012};
    struct pl_model_result out;
    uint32_t n = 9u;
    struct pl_params bad = p;
    bad.baw_newton_max = -1;
    CHECK("contract", 0u, pl_evaluate(&row, PL_MODEL_BSM, &bad, &out, &n) == PL_EVAL_DEFECT);
    bad.baw_newton_max = PL_BAW_NEWTON_MAX + 1;
    CHECK("contract", 1u, pl_evaluate(&row, PL_MODEL_BAW, &bad, &out, &n) == PL_EVAL_DEFECT);
    bad.baw_newton_max = 0;
    CHECK("contract", 2u, pl_evaluate(&row, PL_MODEL_BSM, &bad, &out, &n) == PL_EVAL_OK);
}

/* The wired ALO slot since Task 10b (ruling 46): PL_MASK_WIRED is MODELS5, an expired ALO row is
 * EXPIRED (no stub defect), NULL arguments are the C contract defect; pl_price of ALO gives the
 * engine value (test_evaluate_alo.c holds the ALO rows); pl_price of BAW with a refused point. */
static void alo_slot(void) {
    struct pl_params p;
    pl_case_params(&p);
    const struct pl_row expired = {0, 100.0, 100.0, 0.0, 10.0, 11.0, 0.04, 0.012};
    struct pl_model_result out;
    uint32_t n = 9u;
    CHECK("alo", 0u, PL_MASK_WIRED == PL_MASK_MODELS5);
    CHECK("alo", 3u, pl_evaluate(&expired, PL_MODEL_ALO, &p, &out, &n) == PL_EVAL_OK);
    CHECK("alo", 4u, (out.status == PL_EXPIRED) & (n == 0u) & all_nan(out.values));
    CHECK("alo", 5u, pl_evaluate(&expired, PL_MODEL_ALO, NULL, NULL, NULL) == PL_EVAL_DEFECT);
    CHECK("alo", 6u, pl_evaluate(&expired, PL_MODEL_BAW, &p, &out, &n) == PL_EVAL_OK);
    CHECK("alo", 7u, (out.status == PL_EXPIRED) & (n == 0u));
    double v = 0.0;
    uint8_t f = 0u;
    int st = (int)pl_price(PL_MODEL_ALO, 0, 100.0, 100.0, 1.0, 0.04, 0.012, 0.2, &p, &v, &f);
    CHECK("price", 0u, (st == PL_ENGINE_OK) & pl_is_finite(v) & (f == 0u));
    st = (int)pl_price(PL_MODEL_BAW, 1, 100.0, 100.0, 1.0, -0.05, 0.0, 0.2, &p, &v, &f);
    CHECK("price", 5u, (st == PL_ENGINE_QL_ERROR) & pl_is_nan(v) & (f == PL_FLAG_ADMIT_EXCLUDED));
    f = 0u;
    st = (int)pl_price(PL_MODEL_BSM, 0, 100.0, 100.0, 1.0, 0.04, 0.012, 0.2, NULL, &v, &f);
    CHECK("price", 1u, (st == PL_ENGINE_PY_DEFECT) & pl_is_nan(v));
    st = (int)pl_price(PL_MODEL_BSM, 0, 100.0, 100.0, 1.0, 0.04, 0.012, 0.2, &p, NULL, &f);
    CHECK("price", 2u, st == PL_ENGINE_PY_DEFECT);
    st = (int)pl_price(PL_MODEL_BSM, 0, 100.0, 100.0, 1.0, 0.04, 0.012, 0.2, &p, &v, NULL);
    CHECK("price", 3u, (st == PL_ENGINE_PY_DEFECT) & pl_is_nan(v));
    st = (int)pl_price(PL_MODEL_BSM, 0, 100.0, 100.0, 1.0, 0.04, 0.012, 0.2, &p, &v, &f);
    CHECK("price", 4u, (st == PL_ENGINE_OK) & pl_is_finite(v) & (f == 0u));
}

/* Greek-step rows with other h_r and h_sigma (table evaluate_greeks_param): the CRR stop at bump 2
 * (iv - h_sigma) with b < 0 (Task 11 part B review carry). */
static void greeks_param_rows(void) {
    for (size_t i = 0; i < PL_VEC_EVALUATE_GREEKS_PARAM_COUNT; i++) {
        const struct pl_vec_evaluate_greeks_param *v = PL_VEC_EVALUATE_GREEKS_PARAM + i;
        struct pl_params p;
        pl_case_params(&p);
        p.h_r = D(v->h_r);
        p.h_sigma = D(v->h_sigma);
        const struct pl_row row = {v->side, D(v->S), D(v->K), D(v->T), 1.0, 1.0, D(v->r), D(v->q)};
        uint64_t want[PL_FIELDS];
        *(want + 0) = v->iv;
        *(want + 1) = v->price;
        *(want + 2) = v->delta;
        *(want + 3) = v->gamma;
        *(want + 4) = v->theta;
        *(want + 5) = v->vega;
        *(want + 6) = v->rho;
        double values[PL_FIELDS];
        int band = 5;
        uint8_t flags = 0u;
        uint32_t evals = 0u;
        const double s = D(v->sigma);
        const int st = pl_price_and_greeks(v->model, &row, s, &p, values, &band, &flags, &evals);
        const int same = (st == v->status) & (evals == (uint32_t)v->engine_evals);
        int ok = same & (band == v->band);
        for (size_t f = 0; f < PL_FIELDS; f++) {
            ok &= SAME(*(values + f), *(want + f));
        }
        CHECK("greeks-param", i, ok);
    }
    const size_t n = PL_VEC_EVALUATE_GREEKS_PARAM_COUNT;
    CHECK("greeks-param", n, n > 0u);
}

int main(void) {
    greeks_param_rows();
    puts("PASS greeks-param");
    newton_max_contract();
    alo_slot();
    puts("PASS contract");
    struct tally t = {0u, 0u, 0u, 0u, {0u, 0u, 0u, 0u}};
    for (size_t i = 0; i < PL_VEC_EVALUATE_BAW_COUNT; i++) {
        evaluate_row(i, PL_VEC_EVALUATE_BAW + i, &t);
    }
    const size_t *x = t.excluded;
    printf("PASS evaluate-baw %zu ok %zu defects %zu switched %zu unresolved %zu\n",
           PL_VEC_EVALUATE_BAW_COUNT, t.ok, t.defects, t.switched, t.unresolved);
    printf("PASS baw-admit-excluded row %zu brent %zu bump %zu\n", *(x + 1), *(x + 2), *(x + 3));
    CHECK("coverage", 0u, (t.ok > 0u) & (t.defects >= 2u) & (t.switched > 0u));
    CHECK("coverage", 1u, (*(x + 1) > 0u) & (*(x + 2) > 0u) & (*(x + 3) > 0u));
    return 0;
}
