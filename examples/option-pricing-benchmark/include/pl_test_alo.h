#pragma once
#include "pl_alo.h"
#include "pl_crr.h"
#include "pl_evaluate.h"
#include "pl_ieee.h"
#include "pl_types.h"
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

/* The shared helpers of the sliced ALO vector tests (tests/project/test_alo_greeks*.c and
 * test_evaluate_alo*.c; specs/project/models.md "ALO (Amendment I)"). Test code only: no source
 * file includes this header. Ruling (g) and controller ruling R-10b-B1: the whole vector table
 * stays in the tests, split by row (row i belongs to slice i % slices) only where one file would
 * come near the 10 s test timeout (measured: tables alo_greeks and evaluate_alo each fit in one
 * file). Each file checks the coverage counts of the whole table (vector fields only, no engine
 * call) and evaluates the rows of its slice. A test file defines exactly one of the section macros
 * PL_TEST_ALO_GREEKS and PL_TEST_EVALUATE_ALO before the include (one generated header per file:
 * the AST dump size limit). REQUIRE-style: the first failed check prints "FAIL <group> <index>"
 * and exits 1 (active under NDEBUG). */

#define PL_TA_D(x) pl_bits_double(x)
/* An opaque zero (pl_double_bits of another translation unit): the table loops start from it, so
 * that the GCC analyzer widens them instead of unrolling them over constant data (as ZERO of
 * pl_test_batch.h). */
#define PL_TA_ZERO ((size_t)pl_double_bits(0.0))
#define PL_TA_SAME(g, w) ((pl_double_bits(g) == (w)) | (pl_is_nan(g) & pl_is_nan(PL_TA_D(w))))
#define FAIL(group, i) (printf("FAIL %s %zu\n", group, (size_t)(i)), exit(1))
#define CHECK(group, i, ok) ((ok) ? (void)0 : FAIL(group, i))

#ifdef PL_TEST_ALO_GREEKS
#include "pl_vec_alo_greeks.h"

/* The file test_alo_greeks.c alone (about 4.3 s in gcc-O0, 5.5 s in tsan, 4.5 s in coverage; more
 * files exceed the memory of the source-policy step of the ast gate). */
#define PL_TA_GREEKS_SLICES 1u

/* 1 when every value has the bits of the row, or both are NaN. */
static inline int pl_ta_greeks_values(const double *g, const struct pl_vec_alo_greeks *v) {
    const int a = PL_TA_SAME(*(g + 0), v->iv) & PL_TA_SAME(*(g + 1), v->price);
    const int b = PL_TA_SAME(*(g + 2), v->delta) & PL_TA_SAME(*(g + 3), v->gamma);
    const int c = PL_TA_SAME(*(g + 4), v->theta) & PL_TA_SAME(*(g + 5), v->vega);
    return a & b & c & PL_TA_SAME(*(g + 6), v->rho);
}

/* The coverage counts of the table (by the stencil forms that reference.alo_greeks chose; the C
 * forms show in the count and in the value bits): flag 32 from a rho pair and from a theta pair,
 * a halved stencil, a forward vega, a one-sided rho, a forward theta, every stencil central (7
 * points); flag 16 rows; defect rows; order-5 rows of a European-edge put with r < 0 < q whose
 * stencil points were counted, without flag 16 (black_domain: the BlackCalculator F > 0 check
 * fails at a rho point after the row point passed, cvectors.alo_greek_point_rows, ruling
 * R-10c-2). */
struct pl_ta_greeks_tally {
    size_t rho_switched, theta_switched, halved, forward_vega, one_sided, forward_theta, seven;
    size_t unresolved, ok, defects, black_domain;
};

/* The stencil points of the chosen forms (ruling 45): S 2; vega 2 central or 1 forward; rho 2
 * central or 1 one-sided; theta 1. */
static inline uint32_t pl_ta_greeks_points(const struct pl_vec_alo_greeks *v) {
    const uint32_t vega = 1u + (uint32_t)(v->vega_form == 1); /* branch-free */
    const uint32_t rho = 1u + (uint32_t)(v->rho_form == 1);
    return 2u + vega + rho + 1u;
}

/* The coverage counts of one row (vector fields only). */
static inline void pl_ta_greeks_count(struct pl_ta_greeks_tally *t,
                                      const struct pl_vec_alo_greeks *v) {
    /* branch-free: every OK-row count is masked by ok */
    const int ok = v->status == 0;
    const int switched = ok & ((v->flags & 32) != 0);
    t->ok += (size_t)ok;
    t->rho_switched += (size_t)(switched & ((v->rho_form != 1) | (v->rho_halved != 0)));
    t->theta_switched += (size_t)(switched & ((v->theta_form != 1) | (v->theta_halved != 0)));
    t->halved += (size_t)(ok & ((v->rho_halved != 0) | (v->theta_halved != 0)));
    t->forward_vega += (size_t)(ok & (v->vega_form == 2));
    t->one_sided += (size_t)(ok & (v->rho_form != 1));
    t->forward_theta += (size_t)(ok & (v->theta_form == 2));
    t->seven += (size_t)(ok & (v->stencil_points == 7));
    t->defects += (size_t)(v->status == 2);
    t->unresolved += (size_t)((v->status == 1) & ((v->flags & 16) != 0));
    const int rates = (int)(PL_TA_D(v->r) < 0.0) & (int)(PL_TA_D(v->q) > 0.0);
    const int counted = (v->status == 1) & (v->engine_evals > 0) & ((v->flags & 16) == 0);
    const int plain = (v->side == 1) & (v->plant_site == 0) & (v->force == 0);
    t->black_domain += (size_t)(counted & rates & plain);
}

/* The parameters p and the row of the vector row v (bid and ask are not read). A macro, not a
 * function: each loop of the slice has its own copy (the fixed GCC analyzer budget). */
#define PL_TA_GREEKS_INPUT(v, p, row)                                                              \
    do {                                                                                           \
        pl_case_params(&(p));                                                                      \
        (p).alo_plant_site = (v)->plant_site;                                                      \
        (p).alo_force = (v)->force;                                                                \
        (row).side = (v)->side;                                                                    \
        (row).S = PL_TA_D((v)->S);                                                                 \
        (row).K = PL_TA_D((v)->K);                                                                 \
        (row).T = PL_TA_D((v)->T);                                                                 \
        (row).bid = 1.0;                                                                           \
        (row).ask = 1.0;                                                                           \
        (row).r = PL_TA_D((v)->r);                                                                 \
        (row).q = PL_TA_D((v)->q);                                                                 \
    } while (0)

/* One row through pl_alo_price_and_greeks: status, band, flags, count, values and the points. */
static inline void pl_ta_greeks_row(size_t i, const struct pl_vec_alo_greeks *v) {
    struct pl_params p;
    struct pl_row row;
    PL_TA_GREEKS_INPUT(v, p, row);
    double values[PL_FIELDS];
    int band = 7;
    uint8_t flags = 0u;
    uint32_t evals = 0u;
    int defect = 0;
    const double s = PL_TA_D(v->sigma);
    const int st = pl_alo_price_and_greeks(&row, s, &p, values, &band, &flags, &evals, &defect);
    const int status = st + (defect != 0) * (2 - st); /* 2 for a defect (branch-free) */
    const int raised = v->status == 2;
    const int same = (flags == v->flags) & (band == v->band) & (evals == (uint32_t)v->engine_evals);
    CHECK("greeks", i, (status == v->status) & (raised | (same & pl_ta_greeks_values(values, v))));
    const uint32_t points = pl_ta_greeks_points(v);
    const int chosen = ((uint32_t)v->stencil_points == evals) & (points == evals);
    CHECK("greeks-points", i, (v->status != 0) | chosen);
}

/* One row through the Task 11 interface pl_price_and_greeks: the same status, flags and count as
 * the vector row (pl_ta_greeks_row checks that pl_alo_price_and_greeks gives them; a loop of its
 * own, one engine path per loop body for the fixed GCC analyzer budget). */
static inline void pl_ta_greeks_interface(size_t i, const struct pl_vec_alo_greeks *v) {
    struct pl_params p;
    struct pl_row row;
    PL_TA_GREEKS_INPUT(v, p, row);
    double w[PL_FIELDS];
    int b2 = 0;
    uint8_t f2 = 0u;
    uint32_t n2 = 0u;
    const double s = PL_TA_D(v->sigma);
    const int st2 = pl_price_and_greeks(PL_MODEL_ALO, &row, s, &p, w, &b2, &f2, &n2);
    const int same = (f2 == (uint8_t)v->flags) & (n2 == (uint32_t)v->engine_evals);
    CHECK("price-and-greeks", i, (st2 == v->status) & ((v->status == 2) | same));
}

/* The coverage counts of the whole table, then the rows of the slice. Returns 0. */
static inline int pl_ta_greeks_slice(unsigned slice) {
    CHECK("slice", slice, slice < PL_TA_GREEKS_SLICES);
    struct pl_ta_greeks_tally t = {0};
    for (size_t i = PL_TA_ZERO; i < PL_VEC_ALO_GREEKS_COUNT; i++) {
        pl_ta_greeks_count(&t, PL_VEC_ALO_GREEKS + i);
    }
    CHECK("coverage", 0u, (t.ok > 0u) & (t.seven > 0u) & (t.defects > 0u));
    CHECK("coverage", 1u, (t.rho_switched > 0u) & (t.theta_switched > 0u) & (t.halved > 0u));
    CHECK("coverage", 2u, (t.forward_vega > 0u) & (t.one_sided > 0u) & (t.forward_theta > 0u));
    CHECK("coverage", 3u, t.unresolved > 0u);
    CHECK("coverage", 4u, t.black_domain >= 2u);
    for (size_t i = PL_TA_ZERO + slice; i < PL_VEC_ALO_GREEKS_COUNT; i += PL_TA_GREEKS_SLICES) {
        pl_ta_greeks_row(i, PL_VEC_ALO_GREEKS + i);
    }
    for (size_t i = PL_TA_ZERO + slice; i < PL_VEC_ALO_GREEKS_COUNT; i += PL_TA_GREEKS_SLICES) {
        pl_ta_greeks_interface(i, PL_VEC_ALO_GREEKS + i);
    }
    /* every row (one slice) */
    const size_t rows = PL_VEC_ALO_GREEKS_COUNT - slice;
    printf("PASS alo-greeks slice %u of %u rows %zu (table %zu ok %zu seven %zu)\n", slice,
           PL_TA_GREEKS_SLICES, rows, PL_VEC_ALO_GREEKS_COUNT, t.ok, t.seven);
    printf("PASS alo-greeks switched rho %zu theta %zu halved %zu forward-vega %zu\n",
           t.rho_switched, t.theta_switched, t.halved, t.forward_vega);
    printf("PASS alo-greeks one-sided-rho %zu forward-theta %zu unresolved %zu defects %zu\n",
           t.one_sided, t.forward_theta, t.unresolved, t.defects);
    return 0;
}
#endif

#ifdef PL_TEST_EVALUATE_ALO
#include "pl_vec_evaluate_alo.h"

/* The file test_evaluate_alo.c alone (about 2.4 s in gcc-O0, 2.9 s in tsan, 2.5 s in coverage). */
#define PL_TA_EVALUATE_SLICES 1u

static inline int pl_ta_evaluate_values(const double *g, const struct pl_vec_evaluate_alo *v) {
    const int a = PL_TA_SAME(*(g + 0), v->iv) & PL_TA_SAME(*(g + 1), v->price);
    const int b = PL_TA_SAME(*(g + 2), v->delta) & PL_TA_SAME(*(g + 3), v->gamma);
    const int c = PL_TA_SAME(*(g + 4), v->theta) & PL_TA_SAME(*(g + 5), v->vega);
    return a & b & c & PL_TA_SAME(*(g + 6), v->rho);
}

static inline int pl_ta_all_nan(const double *g) {
    const int a = pl_is_nan(*(g + 0)) & pl_is_nan(*(g + 1)) & pl_is_nan(*(g + 2));
    const int b = pl_is_nan(*(g + 3)) & pl_is_nan(*(g + 4)) & pl_is_nan(*(g + 5));
    return a & b & pl_is_nan(*(g + 6));
}

/* The coverage counts of the table: defect rows, planted or forced defect rows, OK rows, flag 32
 * and flag 16 rows. */
struct pl_ta_evaluate_tally {
    size_t defects, planted_defects, ok, switched, unresolved;
};

/* The rows of side side at T <= PL_TA_EDGE_T with r T and q T at least PL_TA_EDGE_RATE and no
 * test-only parameter: sigma sqrt(T) < (42 QL_EPSILON)^2 = 8.7e-29 for every sigma <= 5, and the
 * mapped rates survive the read-back as positive values, so pl_evaluate reaches the
 * zero-volatility branch of src/pl_alo_edge.c (cvectors.evaluate_alo_edge_rows, ruling R-10c-2).
 * A loop of its own with plain branches (the fixed GCC analyzer budget). */
#define PL_TA_EDGE_T 1e-48
#define PL_TA_EDGE_RATE 1e-16
static inline size_t pl_ta_evaluate_edges(int side) {
    size_t n = 0u;
    for (size_t i = PL_TA_ZERO; i < PL_VEC_EVALUATE_ALO_COUNT; i++) {
        const struct pl_vec_evaluate_alo *v = PL_VEC_EVALUATE_ALO + i;
        if (v->side != side || v->plant_site != 0 || v->force != 0) {
            continue;
        }
        const double T = PL_TA_D(v->T);
        if (!(T <= PL_TA_EDGE_T)) {
            continue;
        }
        if (PL_TA_D(v->r) * T >= PL_TA_EDGE_RATE && PL_TA_D(v->q) * T >= PL_TA_EDGE_RATE) {
            n++;
        }
    }
    return n;
}

/* The rows of side side at T <= PL_TA_QD_T, with S / K or K / S at least PL_TA_QD_RATIO and no
 * test-only parameter, that end in MODEL_DOMAIN after exactly 1 engine evaluation with flags 0:
 * the first IV Brent point sigma_lo = 1e-4 maps to sigma' = 1e-10, and the inner QD+ Brent of
 * src/pl_alo_qdplus.c finds no bracket ("root not bracketed", order 5;
 * cvectors.evaluate_alo_qd_rows, ruling R-10d). A loop of its own with plain branches. */
#define PL_TA_QD_T 1e-12
#define PL_TA_QD_RATIO 1e6
static inline size_t pl_ta_evaluate_qd(int side) {
    size_t n = 0u;
    for (size_t i = PL_TA_ZERO; i < PL_VEC_EVALUATE_ALO_COUNT; i++) {
        const struct pl_vec_evaluate_alo *v = PL_VEC_EVALUATE_ALO + i;
        if (v->side != side || v->plant_site != 0 || v->force != 0 || v->defect != 0) {
            continue;
        }
        if (v->status != PL_MODEL_DOMAIN || v->engine_evals != 1 || v->flags != 0) {
            continue;
        }
        const double S = PL_TA_D(v->S);
        const double K = PL_TA_D(v->K);
        if (!(PL_TA_D(v->T) <= PL_TA_QD_T)) {
            continue;
        }
        if (S >= PL_TA_QD_RATIO * K || K >= PL_TA_QD_RATIO * S) {
            n++;
        }
    }
    return n;
}

static inline void pl_ta_evaluate_count(struct pl_ta_evaluate_tally *t,
                                        const struct pl_vec_evaluate_alo *v) {
    const unsigned w = (unsigned)(v->defect == 0);
    const unsigned test_only = (unsigned)((v->plant_site != 0) | (v->force != 0));
    t->defects += 1u - w;
    t->planted_defects += (size_t)((1u - w) & test_only);
    t->ok += (size_t)(w & (unsigned)(v->status == PL_OK));
    t->switched += (size_t)(w & (unsigned)((v->flags & 32) != 0));
    t->unresolved += (size_t)(w & (unsigned)((v->flags & 16) != 0));
}

/* One row: pl_evaluate of ALO with the row's parameters; PL_EVAL_DEFECT exactly where Python
 * raised. */
static inline void pl_ta_evaluate_row(size_t i, const struct pl_vec_evaluate_alo *v) {
    struct pl_params p;
    pl_case_params(&p);
    p.sigma_hi = PL_TA_D(v->sigma_hi);
    p.kappa_cap = PL_TA_D(v->kappa_cap);
    p.alo_plant_site = v->plant_site;
    p.alo_force = v->force;
    struct pl_row row;
    row.side = v->side;
    row.S = PL_TA_D(v->S);
    row.K = PL_TA_D(v->K);
    row.T = PL_TA_D(v->T);
    row.bid = PL_TA_D(v->bid);
    row.ask = PL_TA_D(v->ask);
    row.r = PL_TA_D(v->r);
    row.q = PL_TA_D(v->q);
    struct pl_model_result out;
    uint32_t evals = 7u;
    const enum pl_eval_error e = pl_evaluate(&row, PL_MODEL_ALO, &p, &out, &evals);
    const int raised = (e == PL_EVAL_DEFECT) & (out.status == PL_INVALID_INPUT) & (out.flags == 0u);
    const int defect_ok = raised & (evals == 0u) & pl_ta_all_nan(out.values);
    const int same = (e == PL_EVAL_OK) & (out.status == v->status) & (out.flags == v->flags);
    const int counted = evals == (uint32_t)v->engine_evals;
    const int row_ok = same & counted & pl_ta_evaluate_values(out.values, v);
    CHECK("evaluate-alo", i, (v->defect != 0) ? defect_ok : row_ok);
}

/* The coverage counts of the whole table, then the rows of the slice. Returns 0. */
static inline int pl_ta_evaluate_slice(unsigned slice) {
    CHECK("slice", slice, slice < PL_TA_EVALUATE_SLICES);
    struct pl_ta_evaluate_tally t = {0u, 0u, 0u, 0u, 0u};
    for (size_t i = PL_TA_ZERO; i < PL_VEC_EVALUATE_ALO_COUNT; i++) {
        pl_ta_evaluate_count(&t, PL_VEC_EVALUATE_ALO + i);
    }
    CHECK("coverage", 0u, (t.ok > 0u) & (t.defects > 0u) & (t.planted_defects > 0u));
    CHECK("coverage", 1u, (t.switched > 0u) & (t.unresolved > 0u));
    CHECK("coverage", 2u, pl_ta_evaluate_edges(1) >= 3u);
    CHECK("coverage", 3u, pl_ta_evaluate_edges(0) >= 3u);
    CHECK("coverage", 4u, (pl_ta_evaluate_qd(0) >= 1u) & (pl_ta_evaluate_qd(1) >= 1u));
    for (size_t i = PL_TA_ZERO + slice; i < PL_VEC_EVALUATE_ALO_COUNT; i += PL_TA_EVALUATE_SLICES) {
        pl_ta_evaluate_row(i, PL_VEC_EVALUATE_ALO + i);
    }
    /* every row (one slice) */
    const size_t rows = PL_VEC_EVALUATE_ALO_COUNT - slice;
    printf("PASS evaluate-alo slice %u of %u rows %zu (table %zu ok %zu defects %zu)\n", slice,
           PL_TA_EVALUATE_SLICES, rows, PL_VEC_EVALUATE_ALO_COUNT, t.ok, t.defects);
    printf("PASS evaluate-alo planted %zu switched %zu unresolved %zu\n", t.planted_defects,
           t.switched, t.unresolved);
    return 0;
}
#endif
