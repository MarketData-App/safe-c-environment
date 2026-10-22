#include "pl_crr.h"
#include "pl_evaluate.h"
#include "pl_ieee.h"
#include "pl_solver.h"
#include "pl_types.h"
#include "pl_vec_evaluate.h"
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

/* Bit-exact tests of pl_evaluate.c against the optionlab vectors (specs/project/models.md "Row
 * evaluation"). Table evaluate: reference.evaluate of bsm, bjs and crr on the synthetic prefix,
 * the oracle edge rows, EDGE_ROWS, RAISE_ROWS, the census raising rows and the bound rows; equal
 * status, flags and G3.7 engine-evaluation count, the seven values as equal bits or both NaN,
 * and PL_EVAL_DEFECT exactly where Python raised (defect 1). Tables evaluate_check,
 * evaluate_tau and evaluate_greeks: the Checker, tau_v and the greek step alone. REQUIRE-style:
 * the first failed check prints "FAIL <group> <index>" and exits 1 (active under NDEBUG). */

#define D(x) pl_bits_double(x)
/* 1 when the double g has the bits w, or both are NaN; g is a variable or a member. */
#define SAME(g, w) ((pl_double_bits(g) == (w)) | (pl_is_nan(g) & pl_is_nan(D(w))))
#define FAIL(group, i) (printf("FAIL %s %zu\n", group, (size_t)(i)), exit(1))
#define CHECK(group, i, ok) ((ok) ? (void)0 : FAIL(group, i))

/* 1 when every value is NaN (the values of a non-OK result). */
static int all_nan(const double *values) {
    const int a = pl_is_nan(*(values + 0)) & pl_is_nan(*(values + 1)) & pl_is_nan(*(values + 2));
    const int b = pl_is_nan(*(values + 3)) & pl_is_nan(*(values + 4)) & pl_is_nan(*(values + 5));
    return a & b & pl_is_nan(*(values + 6));
}

/* 1 when every value has the bits of want, or both are NaN (straight-line code: a loop here
 * exceeds the fixed GCC analyzer budget). */
static int same_values(const double *values, const uint64_t *want) {
    const int a = SAME(*(values + 0), *(want + 0)) & SAME(*(values + 1), *(want + 1));
    const int b = SAME(*(values + 2), *(want + 2)) & SAME(*(values + 3), *(want + 3));
    const int c = SAME(*(values + 4), *(want + 4)) & SAME(*(values + 5), *(want + 5));
    return a & b & c & SAME(*(values + 6), *(want + 6));
}

/* The row of one vector row. */
static struct pl_row row_of(const struct pl_vec_evaluate *v) {
    struct pl_row r;
    r.side = v->side;
    r.S = D(v->S);
    r.K = D(v->K);
    r.T = D(v->T);
    r.bid = D(v->bid);
    r.ask = D(v->ask);
    r.r = D(v->r);
    r.q = D(v->q);
    return r;
}

/* The expected values iv, price, delta, gamma, theta, vega and rho of one evaluate row. */
static void want_of(const struct pl_vec_evaluate *v, uint64_t *w) {
    *(w + 0) = v->iv;
    *(w + 1) = v->price;
    *(w + 2) = v->delta;
    *(w + 3) = v->gamma;
    *(w + 4) = v->theta;
    *(w + 5) = v->vega;
    *(w + 6) = v->rho;
}

/* The expected values of one evaluate_greeks row. */
static void greeks_want_of(const struct pl_vec_evaluate_greeks *v, uint64_t *w) {
    *(w + 0) = v->iv;
    *(w + 1) = v->price;
    *(w + 2) = v->delta;
    *(w + 3) = v->gamma;
    *(w + 4) = v->theta;
    *(w + 5) = v->vega;
    *(w + 6) = v->rho;
}

/* The parameters of one vector row. */
static struct pl_params params_of(const struct pl_vec_evaluate *v) {
    struct pl_params p;
    pl_case_params(&p); /* crr_steps, h_r and h_sigma: the case values in every row */
    p.sigma_hi = D(v->sigma_hi);
    p.kappa_cap = D(v->kappa_cap);
    return p;
}

/* Counts of the evaluate table that the coverage rules require. */
struct tally {
    size_t nonfinite_rates, defects, ok, stop_hi, stop_guess, stop_loop;
    size_t flag[4];
};

/* Adds one row of the evaluate table to the tally; w is 1 for a row without a defect, else 0.
 * Branch-free sums: each branch here multiplies the GCC analyzer paths of the table loop. */
static void count(struct tally *t, const struct pl_row *row, const struct pl_model_result *out,
                  uint32_t evals, unsigned w) {
    const unsigned domain = w & (unsigned)(out->status == PL_MODEL_DOMAIN);
    t->nonfinite_rates += w & (unsigned)(1 - (pl_is_finite(row->r) & pl_is_finite(row->q)));
    t->defects += 1u - w;
    *(t->flag + 0) += (out->flags & 1u);
    *(t->flag + 1) += ((out->flags >> 1u) & 1u);
    *(t->flag + 2) += ((out->flags >> 2u) & 1u);
    *(t->flag + 3) += ((out->flags >> 3u) & 1u);
    /* the count includes the call that stopped the solve */
    t->stop_hi += domain & (unsigned)(evals == 2u);
    t->stop_guess += domain & (unsigned)(evals == 3u);
    t->stop_loop += domain & (unsigned)(evals > 3u);
    t->ok += (size_t)(out->status == PL_OK);
}

/* One row of table evaluate. Defect rows (Python raised): PL_EVAL_DEFECT, status
 * PL_INVALID_INPUT, flags 0, count 0 and NaN values. Other rows: PL_EVAL_OK, equal status,
 * flags and count, and equal value bits. One CHECK per row (the GCC analyzer budget). */
static void evaluate_row(size_t i, const struct pl_vec_evaluate *v, struct tally *t) {
    const struct pl_params p = params_of(v);
    const struct pl_row row = row_of(v);
    struct pl_model_result out;
    uint32_t evals = 7u;
    uint64_t want[PL_FIELDS];
    want_of(v, want);
    const enum pl_eval_error e = pl_evaluate(&row, v->model, &p, &out, &evals);
    const unsigned w = (unsigned)(v->defect == 0);
    const int raised = (e == PL_EVAL_DEFECT) & (out.status == PL_INVALID_INPUT) & (out.flags == 0u);
    const int defect_ok = raised & (evals == 0u) & all_nan(out.values);
    const int same = (e == PL_EVAL_OK) & (out.status == v->status) & (out.flags == v->flags);
    const int row_ok = same & (evals == (uint32_t)v->engine_evals) & same_values(out.values, want);
    CHECK("evaluate", i, (w != 0u) ? row_ok : defect_ok);
    count(t, &row, &out, evals, w);
}

static void evaluate_rows(struct tally *t) {
    for (size_t i = 0; i < PL_VEC_EVALUATE_COUNT; i++) {
        evaluate_row(i, PL_VEC_EVALUATE + i, t);
    }
}

/* reference.Checker on (tau, v): the domain return, o->domain and o->band. */
static void check_rows(void) {
    for (size_t i = 0; i < PL_VEC_EVALUATE_CHECK_COUNT; i++) {
        const struct pl_vec_evaluate_check *v = PL_VEC_EVALUATE_CHECK + i;
        struct pl_objective o;
        o.tau = D(v->tau);
        o.domain = 0;
        o.band = 0;
        const int r = pl_check_value(&o, D(v->v));
        CHECK("check", i, (r == v->domain) & (o.domain == v->domain) & (o.band == v->band));
    }
    CHECK("check-null", 0u, pl_check_value(NULL, 0.0) == 1);
}

static void tau_rows(void) {
    for (size_t i = 0; i < PL_VEC_EVALUATE_TAU_COUNT; i++) {
        const struct pl_vec_evaluate_tau *v = PL_VEC_EVALUATE_TAU + i;
        int defect = 0;
        const double tau = pl_tau_v(D(v->S), D(v->K), D(v->T), D(v->r), D(v->q), &defect);
        CHECK("tau", i, (defect == v->defect) & ((v->defect != 0) | SAME(tau, v->tau)));
    }
}

static void greeks_rows(void) {
    struct pl_params p;
    pl_case_params(&p);
    for (size_t i = 0; i < PL_VEC_EVALUATE_GREEKS_COUNT; i++) {
        const struct pl_vec_evaluate_greeks *v = PL_VEC_EVALUATE_GREEKS + i;
        const struct pl_row row = {v->side, D(v->S), D(v->K), D(v->T), 1.0, 1.0, D(v->r), D(v->q)};
        uint64_t want[PL_FIELDS];
        greeks_want_of(v, want);
        double values[PL_FIELDS];
        int band = 5;
        uint8_t flags = 0u;
        uint32_t evals = 0u;
        const double s = D(v->sigma);
        const int st = pl_price_and_greeks(v->model, &row, s, &p, values, &band, &flags, &evals);
        const int same = (st == v->status) & (evals == (uint32_t)v->engine_evals) & (flags == 0u);
        const int band_ok = (v->status == PL_GREEKS_DEFECT) | (band == v->band);
        CHECK("greeks", i, same & band_ok & same_values(values, want));
    }
}

/* The C contract of pl_evaluate: NULL arguments, models outside 0..PL_MODEL_ALO, parameters
 * outside the case domain; each is PL_EVAL_DEFECT with no result. */
static void contract(void) {
    struct pl_params p;
    pl_case_params(&p);
    const struct pl_row row = {0, 100.0, 100.0, 1.0, 10.0, 11.0, 0.04, 0.012};
    struct pl_model_result out;
    uint32_t n = 9u;
    CHECK("contract", 0u, pl_evaluate(&row, PL_MODEL_BSM, &p, NULL, &n) == PL_EVAL_DEFECT);
    CHECK("contract", 1u, pl_evaluate(&row, PL_MODEL_BSM, &p, &out, NULL) == PL_EVAL_DEFECT);
    CHECK("contract", 2u, (out.status == PL_INVALID_INPUT) & all_nan(out.values));
    CHECK("contract", 3u, pl_evaluate(NULL, PL_MODEL_BSM, &p, &out, &n) == PL_EVAL_DEFECT);
    CHECK("contract", 4u, pl_evaluate(&row, PL_MODEL_BSM, NULL, &out, &n) == PL_EVAL_DEFECT);
    CHECK("contract", 5u, pl_evaluate(&row, -1, &p, &out, &n) == PL_EVAL_DEFECT);
    CHECK("contract", 6u, pl_evaluate(&row, PL_MODEL_ALO + 1, &p, &out, &n) == PL_EVAL_DEFECT);
    struct pl_params bad = p;
    bad.crr_steps = 0;
    CHECK("contract", 7u, pl_evaluate(&row, PL_MODEL_BSM, &bad, &out, &n) == PL_EVAL_DEFECT);
    bad.crr_steps = PL_CRR_MAX_STEPS + 1;
    CHECK("contract", 8u, pl_evaluate(&row, PL_MODEL_BSM, &bad, &out, &n) == PL_EVAL_DEFECT);
    bad = p;
    bad.kappa_cap = 0.0;
    CHECK("contract", 9u, pl_evaluate(&row, PL_MODEL_BSM, &bad, &out, &n) == PL_EVAL_DEFECT);
    bad = p;
    bad.h_r = -1e-4;
    CHECK("contract", 10u, pl_evaluate(&row, PL_MODEL_BSM, &bad, &out, &n) == PL_EVAL_DEFECT);
    CHECK("contract", 11u, (n == 0u) & (out.status == PL_INVALID_INPUT) & (out.flags == 0u));
    /* h_r == 0.0 and h_sigma == 0.0 are in the contract: BSM never divides by them, CRR raises in
     * Python at the bump divisions (reference.py:59-60; light test BumpStepTests) */
    bad.h_r = 0.0;
    CHECK("contract", 12u, pl_evaluate(&row, PL_MODEL_BSM, &bad, &out, &n) == PL_EVAL_OK);
    CHECK("contract", 13u, pl_evaluate(&row, PL_MODEL_CRR, &bad, &out, &n) == PL_EVAL_DEFECT);
    bad = p;
    bad.h_sigma = 0.0;
    CHECK("contract", 14u, pl_evaluate(&row, PL_MODEL_BSM, &bad, &out, &n) == PL_EVAL_OK);
    CHECK("contract", 15u, pl_evaluate(&row, PL_MODEL_CRR, &bad, &out, &n) == PL_EVAL_DEFECT);
    CHECK("contract", 16u, (n == 0u) & (out.status == PL_INVALID_INPUT));
}

/* pl_price_and_greeks outside the table: the wired ALO slot (Task 10b: every stencil central,
 * 7 stencil points, the price at sigma not counted) and the C contract (NULL arguments). */
static void greeks_direct(void) {
    struct pl_params p;
    pl_case_params(&p);
    const struct pl_row row = {0, 100.0, 100.0, 1.0, 10.0, 11.0, 0.04, 0.012};
    double w[PL_FIELDS];
    int b = 0;
    uint8_t f = 0u;
    uint32_t n = 0u;
    int st = pl_price_and_greeks(PL_MODEL_ALO, &row, 0.2, &p, w, &b, &f, &n);
    CHECK("greeks-direct", 0u, (st == PL_GREEKS_OK) & (n == 7u) & (f == 0u) & !all_nan(w));
    st = pl_price_and_greeks(PL_MODEL_BSM, &row, 0.2, &p, NULL, &b, &f, &n);
    CHECK("greeks-direct", 1u, st == PL_GREEKS_DEFECT);
    st = pl_price_and_greeks(PL_MODEL_BSM, NULL, 0.2, &p, w, &b, &f, &n);
    CHECK("greeks-direct", 2u, (st == PL_GREEKS_DEFECT) & all_nan(w));
    st = pl_price_and_greeks(PL_MODEL_BSM, &row, 0.2, NULL, w, &b, &f, &n);
    CHECK("greeks-direct", 3u, st == PL_GREEKS_DEFECT);
    st = pl_price_and_greeks(PL_MODEL_BSM, &row, 0.2, &p, w, NULL, &f, &n);
    CHECK("greeks-direct", 4u, st == PL_GREEKS_DEFECT);
    st = pl_price_and_greeks(PL_MODEL_BSM, &row, 0.2, &p, w, &b, NULL, &n);
    CHECK("greeks-direct", 5u, st == PL_GREEKS_DEFECT);
    st = pl_price_and_greeks(PL_MODEL_BSM, &row, 0.2, &p, w, &b, &f, NULL);
    CHECK("greeks-direct", 6u, st == PL_GREEKS_DEFECT);
}

/* A fresh objective per row: one row gives the same result before and after every row of the
 * table that stops with MODEL_DOMAIN or raises. */
static void fresh(void) {
    struct pl_params p;
    pl_case_params(&p);
    const struct pl_row row = {0, 100.0, 100.0, 1.0, 10.0, 11.0, 0.04, 0.012};
    struct pl_model_result first;
    struct pl_model_result again;
    struct pl_model_result out;
    uint32_t n1 = 0u;
    uint32_t n2 = 0u;
    uint32_t n = 0u;
    CHECK("fresh", 0u, pl_evaluate(&row, PL_MODEL_CRR, &p, &first, &n1) == PL_EVAL_OK);
    for (size_t i = 0; i < PL_VEC_EVALUATE_COUNT; i++) {
        const struct pl_vec_evaluate *v = PL_VEC_EVALUATE + i;
        const struct pl_params q = params_of(v);
        const struct pl_row other = row_of(v);
        if ((v->defect != 0) | (v->status == PL_MODEL_DOMAIN)) {
            (void)pl_evaluate(&other, v->model, &q, &out, &n);
        }
    }
    CHECK("fresh", 1u, pl_evaluate(&row, PL_MODEL_CRR, &p, &again, &n2) == PL_EVAL_OK);
    CHECK("fresh", 2u, (first.status == PL_OK) & (again.status == PL_OK) & (n1 == n2));
    const double *v = first.values;
    const uint64_t want[PL_FIELDS] = {pl_double_bits(*(v + 0)), pl_double_bits(*(v + 1)),
                                      pl_double_bits(*(v + 2)), pl_double_bits(*(v + 3)),
                                      pl_double_bits(*(v + 4)), pl_double_bits(*(v + 5)),
                                      pl_double_bits(*(v + 6))};
    CHECK("fresh", 3u, (again.flags == first.flags) & same_values(again.values, want));
}

int main(void) {
    struct tally t = {0};
    evaluate_rows(&t);
    check_rows();
    tau_rows();
    greeks_rows();
    contract();
    greeks_direct();
    fresh();
    printf("PASS rates %zu defects %zu ok %zu\n", t.nonfinite_rates, t.defects, t.ok);
    const size_t *fl = t.flag;
    printf("PASS flags %zu %zu %zu %zu\n", *(fl + 0), *(fl + 1), *(fl + 2), *(fl + 3));
    printf("PASS brent-stops %zu %zu %zu\n", t.stop_hi, t.stop_guess, t.stop_loop);
    CHECK("coverage", 0u, (t.nonfinite_rates > 0u) & (t.defects >= 8u) & (t.ok > 0u));
    CHECK("coverage", 1u, (*(t.flag + 0) > 0u) & (*(t.flag + 1) > 0u));
    CHECK("coverage", 2u, (*(t.flag + 2) > 0u) & (*(t.flag + 3) > 0u));
    CHECK("coverage", 3u, (t.stop_hi > 0u) & (t.stop_guess > 0u) & (t.stop_loop > 0u));
    puts("PASS evaluate");
    return 0;
}
