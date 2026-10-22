#include "pl_crr.h"
#include "pl_evaluate.h"
#include "pl_ieee.h"
#include "pl_types.h"
#include "pl_vec_evaluate_census.h"
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

/* Bit-exact test of pl_evaluate for bsm, bjs and crr on the census raising rows of table
 * evaluate_census (specs/project/models.md "Row evaluation"): the rows of part evaluate whose
 * first occurrence is a census raising row, in a file of their own since Task 10b (the census
 * over MODELS5 took test_evaluate.c past the AST dump size limit of the source-policy gate).
 * Equal status, flags and G3.7 engine-evaluation count, the seven values as equal bits or both
 * NaN, and PL_EVAL_DEFECT exactly where Python raised (defect 1). REQUIRE-style: the first failed
 * check prints "FAIL <group> <index>" and exits 1 (active under NDEBUG). */

#define D(x) pl_bits_double(x)
#define SAME(g, w) ((pl_double_bits(g) == (w)) | (pl_is_nan(g) & pl_is_nan(D(w))))
#define FAIL(group, i) (printf("FAIL %s %zu\n", group, (size_t)(i)), exit(1))
#define CHECK(group, i, ok) ((ok) ? (void)0 : FAIL(group, i))

static int all_nan(const double *g) {
    const int a = pl_is_nan(*(g + 0)) & pl_is_nan(*(g + 1)) & pl_is_nan(*(g + 2));
    const int b = pl_is_nan(*(g + 3)) & pl_is_nan(*(g + 4)) & pl_is_nan(*(g + 5));
    return a & b & pl_is_nan(*(g + 6));
}

static int same_values(const double *g, const struct pl_vec_evaluate_census *v) {
    const int a = SAME(*(g + 0), v->iv) & SAME(*(g + 1), v->price) & SAME(*(g + 2), v->delta);
    const int b = SAME(*(g + 3), v->gamma) & SAME(*(g + 4), v->theta) & SAME(*(g + 5), v->vega);
    return a & b & SAME(*(g + 6), v->rho);
}

/* One row: a defect row gives PL_EVAL_DEFECT with the defect result; every other row the vector
 * status, flags, count and value bits. Returns 1 for a defect row. */
static unsigned census_row(size_t i, const struct pl_vec_evaluate_census *v) {
    struct pl_params p;
    pl_case_params(&p);
    p.sigma_hi = D(v->sigma_hi);
    p.kappa_cap = D(v->kappa_cap);
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
    const enum pl_eval_error e = pl_evaluate(&row, v->model, &p, &out, &evals);
    const int raised = (e == PL_EVAL_DEFECT) & (out.status == PL_INVALID_INPUT) & (out.flags == 0u);
    const int defect_ok = raised & (evals == 0u) & all_nan(out.values);
    const int same = (e == PL_EVAL_OK) & (out.status == v->status) & (out.flags == v->flags);
    const int row_ok = same & (evals == (uint32_t)v->engine_evals) & same_values(out.values, v);
    CHECK("evaluate-census", i, (v->defect != 0) ? defect_ok : row_ok);
    return (unsigned)(v->defect != 0);
}

int main(void) {
    size_t defects = 0u;
    for (size_t i = 0; i < PL_VEC_EVALUATE_CENSUS_COUNT; i++) {
        defects += census_row(i, PL_VEC_EVALUATE_CENSUS + i);
    }
    printf("PASS evaluate-census %zu defects %zu\n", PL_VEC_EVALUATE_CENSUS_COUNT, defects);
    CHECK("coverage", 0u, (PL_VEC_EVALUATE_CENSUS_COUNT > 0u) & (defects > 0u));
    return 0;
}
