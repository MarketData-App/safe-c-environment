#include "pl_baw.h"
#include "pl_black.h"
#include "pl_crr.h"
#include "pl_ieee.h"
#include "pl_types.h"
#include "pl_vec_baw.h"
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

/* Bit-exact tests of pl_baw.c against optionlab.baw and optionlab.baw_admit
 * (specs/project/models.md "BAW (Amendment G)"). Group params: the case parameters. Group engine
 * (table baw): pl_baw_result with every greek and with the value only, for the case, the
 * forced-cap (baw_newton_max 1) and the planted non-finite S* parameter sets; the status, the
 * iteration count, every engine member and S* as equal bits or both NaN. Group critical (table
 * baw_critical): pl_baw_critical_price at the exact count, one less, 0, 1, 2 and the case cap.
 * Group bounded: no call returns more iterations than its newton_max. Group params also checks
 * sigma_lo(BAW) on table baw_lo. REQUIRE-style: the first
 * failed check prints "FAIL <group> <index>" and exits 1. */

#define D(x) pl_bits_double(x)
#define SAME(g, w) ((pl_double_bits(g) == (w)) | (pl_is_nan(g) & pl_is_nan(D(w))))
#define FAIL(group, i) (printf("FAIL %s %zu\n", group, (size_t)(i)), exit(1))
#define CHECK(group, i, ok) ((ok) ? (void)0 : FAIL(group, i))

/* The parameter set of a vector row: 0 case, 1 baw_newton_max 1, 2 planted non-finite S*. */
static struct pl_params params_of(int kind) {
    struct pl_params p;
    pl_case_params(&p);
    if (kind == 1) {
        p.baw_newton_max = 1;
    }
    p.baw_plant_nonfinite_sstar = (kind == 2) ? 1 : 0;
    return p;
}

/* 1 when every engine member has the bits of the row (equal bits or both NaN). */
static int same_engine(const struct pl_engine_result *e, const struct pl_vec_baw *v) {
    const int a = SAME(e->value, v->value) & SAME(e->delta, v->delta) & SAME(e->gamma, v->gamma);
    const int b = SAME(e->theta, v->theta) & SAME(e->vega, v->vega) & SAME(e->rho, v->rho);
    return a & b & SAME(e->dividend_rho, v->dividendrho) & pl_is_nan(e->strike_sensitivity);
}

/* 1 when every greek of a European-branch result is finite. */
static int finite_greeks(const struct pl_engine_result *e) {
    const int a = pl_is_finite(e->value) & pl_is_finite(e->delta) & pl_is_finite(e->gamma);
    const int b = pl_is_finite(e->theta) & pl_is_finite(e->vega) & pl_is_finite(e->rho);
    return a & b & pl_is_finite(e->dividend_rho);
}

struct tally {
    size_t eu_dq, eu_dr, continuation, exercise, defect_cap, defect_plant, ql;
};

/* One row of table baw. */
static void engine_row(size_t i, const struct pl_vec_baw *v, struct tally *t) {
    const struct pl_params p = params_of(v->params);
    struct pl_engine_result e;
    struct pl_engine_result value_only;
    int it = -1;
    int it2 = -1;
    const double S = D(v->S);
    const double K = D(v->K);
    const double T = D(v->T);
    const double r = D(v->r);
    const double q = D(v->q);
    const double s = D(v->sigma);
    const int st = (int)pl_baw_result(v->side, S, K, T, r, q, s, 1, &p, &e, &it);
    const int st2 = (int)pl_baw_result(v->side, S, K, T, r, q, s, 0, &p, &value_only, &it2);
    CHECK("engine", i, (st == v->status) & (st2 == v->status));
    CHECK("engine-count", i, (v->status != 0) | ((it == v->iterations) & (it2 == v->iterations)));
    CHECK("engine-values", i, same_engine(&e, v));
    CHECK("engine-value-only", i, SAME(value_only.value, v->value) & pl_is_nan(value_only.delta));
    if (v->status == 0 && v->where != 0) {
        double d_r = 0.0;
        double d_q = 0.0;
        double var = 0.0;
        int defect = 0;
        pl_mapped_inputs(T, r, q, s, &d_r, &d_q, &var, &defect);
        double sk = 0.0;
        int n = 0;
        const int sst = (int)pl_baw_sstar(v->side, K, d_r, d_q, var, p.baw_newton_max,
                                          p.baw_plant_nonfinite_sstar, &sk, &n);
        CHECK("sstar", i, (defect == 0) & (sst == 0) & SAME(sk, v->sstar) & (n == v->iterations));
    }
    const unsigned ok = (unsigned)(v->status == 0);
    const unsigned eu = ok & (unsigned)(v->where == 0) & (unsigned)finite_greeks(&e);
    t->eu_dq += (size_t)(eu & (unsigned)(q <= 0.0));
    t->eu_dr += (size_t)(eu & (unsigned)(r < 0.0));
    t->continuation += (size_t)(ok & (unsigned)(v->where == 1));
    t->exercise += (size_t)(ok & (unsigned)(v->where == 2));
    t->defect_cap += (size_t)((v->status == 2) & (v->params == 1));
    t->defect_plant += (size_t)((v->status == 2) & (v->params == 2));
    t->ql += (size_t)(v->status == 1);
}

/* One row of table baw_critical, and the bounded check at newton_max 1, 2 and the case cap.
 * Returns 1 for a row whose count equals its newton_max (status 0), 2 for a cap hit, else 0. */
static int critical_row(size_t i, const struct pl_vec_baw_critical *v) {
    int it = -1;
    int cap = 0;
    int ql = 0;
    const double K = D(v->K);
    const double d_r = D(v->d_r);
    const double d_q = D(v->d_q);
    const double var = D(v->variance);
    const int nmax = v->newton_max;
    const double sk = pl_baw_critical_price(v->side, K, d_r, d_q, var, nmax, &it, &cap, &ql);
    const int st = (ql != 0) ? 1 : ((cap != 0) ? 2 : 0);
    const int ok_row = (v->status != 0) | ((it == v->iterations) & SAME(sk, v->sstar));
    CHECK("critical", i, (st == v->status) & ok_row & (it <= v->newton_max) & (it >= 0));
    const int caps[3] = {1, 2, PL_BAW_NEWTON_MAX};
    for (size_t k = 0; k < 3u; k++) {
        int n = -1;
        int c = 0;
        int e = 0;
        const int m = *(caps + k);
        (void)pl_baw_critical_price(v->side, K, d_r, d_q, var, m, &n, &c, &e);
        CHECK("bounded", i, (n >= 0) & (n <= m));
    }
    if (st == 0 && v->iterations == v->newton_max && v->newton_max > 0) {
        return 1;
    }
    return (st == 2) ? 2 : 0;
}

int main(void) {
    struct pl_params p;
    pl_case_params(&p);
    const int cap = p.baw_newton_max;
    CHECK("params", 0u, (cap == PL_VEC_BAW_NEWTON_MAX) & (cap == PL_BAW_NEWTON_MAX));
    CHECK("params", 1u, p.baw_plant_nonfinite_sstar == 0);
    /* sigma_lo(BAW) of Appendix G-BAW R9 and F3 (table baw_lo: the crr_lo grid for model 3) */
    for (size_t i = 0; i < PL_VEC_BAW_LO_COUNT; i++) {
        const struct pl_vec_baw_lo *v = PL_VEC_BAW_LO + i;
        const double lo = pl_sigma_lo(v->model, v->side, D(v->T), D(v->r), D(v->q), &p);
        CHECK("sigma-lo", i, SAME(lo, v->sigma_lo) & (v->model == PL_MODEL_BAW));
    }
    printf("PASS params sigma-lo %zu\n", PL_VEC_BAW_LO_COUNT);
    struct tally t = {0u, 0u, 0u, 0u, 0u, 0u, 0u};
    for (size_t i = 0; i < PL_VEC_BAW_COUNT; i++) {
        engine_row(i, PL_VEC_BAW + i, &t);
    }
    printf("PASS engine %zu eu-dq %zu eu-dr %zu\n", PL_VEC_BAW_COUNT, t.eu_dq, t.eu_dr);
    printf("PASS engine-sides continuation %zu exercise %zu\n", t.continuation, t.exercise);
    printf("PASS engine-errors ql %zu defects %zu %zu\n", t.ql, t.defect_cap, t.defect_plant);
    CHECK("coverage", 0u, (t.eu_dq > 0u) & (t.eu_dr > 0u));
    CHECK("coverage", 3u, (t.continuation > 0u) & (t.exercise > 0u));
    CHECK("coverage", 1u, (t.defect_cap > 0u) & (t.defect_plant > 0u) & (t.ql > 0u));
    size_t exact = 0u;
    size_t hits = 0u;
    for (size_t i = 0; i < PL_VEC_BAW_CRITICAL_COUNT; i++) {
        const int c = critical_row(i, PL_VEC_BAW_CRITICAL + i);
        exact += (size_t)(c == 1);
        hits += (size_t)(c == 2);
    }
    printf("PASS critical %zu exact-count %zu\n", PL_VEC_BAW_CRITICAL_COUNT, exact);
    printf("PASS critical cap-hits %zu\n", hits);
    puts("PASS bounded");
    CHECK("coverage", 2u, (exact > 0u) & (hits > 0u));
    return 0;
}
