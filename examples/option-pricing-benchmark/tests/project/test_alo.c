#include "pl_alo.h"
#include "pl_alo_equation.h"
#include "pl_black.h"
#include "pl_crr.h"
#include "pl_ieee.h"
#include "pl_types.h"
#include "pl_vec_alo.h"
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Bit-exact tests of the ALO engine (specs/project/models.md "ALO (Amendment I)") against the
 * optionlab vectors (cvectors part alo): the case parameters and the alo_scheme constants against
 * the case manifest key (params), sigma_lo(ALO) of record R9 (params), every engine row with its
 * status, statistics and value bits under the case, planted and forced parameter sets (engine),
 * the loop caps of record R3 (bounded) and the structural invariants of I4.4 (invariants). Groups
 * print "PASS <group>" and counts; main returns 0 only when no check failed (REQUIRE-style,
 * active under NDEBUG). */

/* The first failed check prints "FAIL <group> <index>" and exits 1. The checks are macros, not
 * functions, so that the GCC analyzer explores each check at its own place (the fixed analyzer
 * budget, as test_crr.c). same: equal bits, or both NaN. */
#define require(group, index, ok)                                                                  \
    ((ok) ? (void)0 : (void)(printf("FAIL %s %zu\n", group, (size_t)(index)), exit(1)))
#define same(group, index, got, want)                                                              \
    require(group, index,                                                                          \
            (pl_double_bits(got) == (want)) | (pl_is_nan(got) & pl_is_nan(pl_bits_double(want))))

static const char *verdict(int ok) { return ok ? "PASS" : "FAIL"; }

#define D(x) pl_bits_double(x)
/* An opaque zero (pl_double_bits of another translation unit): the table loops start from it, so
 * that the GCC analyzer widens them instead of unrolling them over constant data. */
#define OPAQUE_ZERO ((size_t)pl_double_bits(0.0))

/* The case parameters with the test-only pair of a vector row. */
static struct pl_params row_params(int site, int force) {
    struct pl_params p;
    pl_case_params(&p);
    p.alo_plant_site = site;
    p.alo_force = force;
    return p;
}

/* The case parameters, the alo_scheme constants, sigma_lo(ALO) and the C contract. */
static void params(void) {
    struct pl_params p;
    pl_case_params(&p);
    require("params", 0u, (p.alo_plant_site == 0) & (p.alo_force == 0));
    require("params", 1u, PL_ALO_GL_ORDER == PL_VEC_ALO_SCHEME_L);
    require("params", 2u, PL_ALO_FP_STEPS == PL_VEC_ALO_SCHEME_M);
    require("params", 3u, PL_ALO_CHEB_N == PL_VEC_ALO_SCHEME_N);
    require("params", 4u, pl_double_bits(PL_ALO_TS_EPS) == PL_VEC_ALO_SCHEME_EPS);
    require("params", 5u, PL_VEC_ALO_SCHEME_AUTO == 1);
    require("params", 6u, strcmp(PL_ALO_SCHEME_NAME, PL_VEC_ALO_SCHEME_NAME) == 0);
    require("params", 7u, strcmp(PL_ALO_FP_EQUATION, PL_VEC_ALO_SCHEME_FP_EQUATION) == 0);
    require("params", 8u, PL_ALO_PLANT_SITES == PL_VEC_ALO_PLANT_SITES);
    require("params", 9u, PL_ALO_FORCES == PL_VEC_ALO_FORCES);
    require("params", 10u, pl_double_bits(PL_ALO_QDP_EPS) == PL_VEC_ALO_SCHEME_EPS);
    size_t defects = 0u;
    for (size_t i = OPAQUE_ZERO; i < PL_VEC_ALO_LO_COUNT; i++) {
        const struct pl_vec_alo_lo *v = PL_VEC_ALO_LO + i;
        const double lo = pl_sigma_lo(v->model, v->side, D(v->T), D(v->r), D(v->q), &p);
        same("alo-lo", i, lo, v->sigma_lo);
        struct pl_alo_rates rates;
        pl_alo_equation(D(v->r) * D(v->T), D(v->q) * D(v->T), &rates);
        require("alo-lo-defect", i, rates.defect == v->defect);
        defects += (v->defect != 0) ? 1u : 0u;
    }
    struct pl_alo_trace tr;
    double value = 0.0;
    struct pl_params bad = row_params(PL_ALO_PLANT_SITES + 1, 0);
    int st = (int)pl_alo_result(1, 100.0, 100.0, 1.0, 0.04, 0.012, 0.3, &bad, &tr, &value);
    require("contract", 0u, (st == PL_ENGINE_PY_DEFECT) & pl_is_nan(value));
    bad = row_params(0, PL_ALO_FORCES + 1);
    st = (int)pl_alo_result(1, 100.0, 100.0, 1.0, 0.04, 0.012, 0.3, &bad, &tr, &value);
    require("contract", 1u, st == PL_ENGINE_PY_DEFECT);
    bad = row_params(-1, 0);
    st = (int)pl_alo_result(1, 100.0, 100.0, 1.0, 0.04, 0.012, 0.3, &bad, &tr, &value);
    require("contract", 2u, st == PL_ENGINE_PY_DEFECT);
    st = (int)pl_alo_result(2, 100.0, 100.0, 1.0, 0.04, 0.012, 0.3, &p, &tr, &value);
    require("contract", 3u, (st == PL_ENGINE_PY_DEFECT) & (tr.equation == -1));
    st = (int)pl_alo_result(1, 100.0, 100.0, -1.0, 0.04, 0.012, 0.3, &p, &tr, &value);
    require("contract", 4u, (st == PL_ENGINE_PY_DEFECT) & (tr.equation == -1));
    st = (int)pl_alo_result(1, 100.0, 100.0, 1.0, -800.0, 0.012, 0.3, &p, &tr, &value);
    require("contract", 5u, (st == PL_ENGINE_PY_DEFECT) & (tr.equation == -1));
    const int ok = PL_VEC_ALO_LO_COUNT > 0u && defects > 0u;
    require("params-coverage", 0u, ok);
    printf("%s params alo-lo %zu defects %zu\n", verdict(ok), PL_VEC_ALO_LO_COUNT, defects);
}

/* The coverage counts of the engine group. */
struct tally {
    size_t ok_a, ok_b, edge_put, call_ok, double_boundary, bracket, persistent, zero_vol;
    size_t qd_natural;
    size_t planted[PL_ALO_PLANT_SITES + 1];
    size_t capped[PL_ALO_FORCES + 1];
};

/* 1 when the trace equals the statistics of the vector row. */
static int same_trace(const struct pl_alo_trace *t, const struct pl_vec_alo *v) {
    const int a = (t->equation == v->equation) & ((int)t->qd_calls == v->qd_calls);
    const int b = (t->halley_max == v->halley_max) & (t->fallback_nodes == v->fallback_nodes);
    const int c = (t->fallback_max == v->fallback_max) & (t->levels == v->levels);
    const int d = ((int)t->integrand == v->integrand) & ((int)t->nan_guarded == v->guarded);
    const int e = (t->failed_check == v->failed_check) & (t->failed_cap == v->failed_cap);
    return a & b & c & d & e;
}

/* The coverage of one engine row. */
static void count(struct tally *t, const struct pl_vec_alo *v, const struct pl_alo_trace *tr) {
    /* branch-free counts (the fixed GCC analyzer budget): each condition is 0 or 1 */
    const int plain = (v->plant_site == 0) & (v->force == 0);
    const double r = D(v->r);
    const double q = D(v->q);
    const int ok = plain & (v->status == 0);
    t->ok_a += (size_t)(ok & (v->equation == PL_ALO_FP_A));
    t->ok_b += (size_t)(ok & (v->equation == PL_ALO_FP_B));
    t->edge_put += (size_t)(ok & (v->side == 1) & (r <= 0.0) & (r <= q));
    /* the close(vol, 0.0) rows (cvectors.alo_zero_vol_rows, src/pl_alo_edge.c): no QD+ call */
    t->zero_vol += (size_t)(ok & (D(v->sigma) < 1e-200) & (v->qd_calls == 0) & (v->levels == 0));
    t->call_ok += (size_t)(ok & (v->side == 0) & (v->levels > 0));
    const int db = (v->status == 1) & (v->side == 1) & (r < 0.0) & (q < r);
    t->double_boundary += (size_t)(plain & db);
    t->bracket += (size_t)((v->force == PL_ALO_FORCE_BRACKET) & (v->status == 1));
    /* the natural inner QD+ Brent error (cvectors.alo_qd_natural_rows, src/pl_alo_qdplus.c "not
     * bracketed"; ruling R-10d): order 5 with no test-only parameter and no failed check, after
     * QD+ calls and before the integral */
    const int qd_error = (v->status == 1) & (v->qd_calls > 0) & (v->levels == 0);
    t->qd_natural += (size_t)(plain & qd_error & (v->failed_check == 0) & (v->failed_cap == 0));
    const int site = (v->plant_site > 0) & (v->plant_site <= PL_ALO_PLANT_SITES);
    const int planted = (v->status == 2) & site;
    *(t->planted + (size_t)(v->plant_site * planted)) += (size_t)planted;
    const int force = (v->force > PL_ALO_FORCE_BRACKET) & (v->force <= PL_ALO_FORCES);
    const int capped = (v->status == 2) & force;
    const int cap_hit = capped & (tr->failed_cap == v->force - 1);
    *(t->capped + (size_t)(v->force * capped)) += (size_t)cap_hit;
    /* a defect at the first Halley step, never a node at x = xMin */
    const int persistent = (v->plant_site == PL_ALO_SITE_PERSISTENT_QDPLUS_66) & (v->status == 2);
    const int first = (tr->qd_calls == 1u) & (tr->failed_check == PL_ALO_CHECK_QDPLUS_SOLVER);
    t->persistent += (size_t)(persistent & first);
}

/* Every engine row: status, statistics and value bits. */
static void engine(void) {
    struct tally t = {0};
    for (size_t i = OPAQUE_ZERO; i < PL_VEC_ALO_COUNT; i++) {
        const struct pl_vec_alo *v = PL_VEC_ALO + i;
        const struct pl_params p = row_params(v->plant_site, v->force);
        struct pl_alo_trace tr;
        double value = 0.0;
        const double s = D(v->sigma);
        const int st = (int)pl_alo_result(v->side, D(v->S), D(v->K), D(v->T), D(v->r), D(v->q), s,
                                          &p, &tr, &value);
        require("engine", i, (st == v->status) & same_trace(&tr, v));
        /* branch-free: the value bits on an OK row, NaN on every other row */
        const int bits = (pl_double_bits(value) == v->value);
        const int nan_want = pl_is_nan(value) & pl_is_nan(D(v->value));
        require("engine-value", i, (v->status != 0) | bits | nan_want);
        require("engine-nan", i, (v->status == 0) | pl_is_nan(value));
        count(&t, v, &tr);
    }
    int all = 1;
    for (size_t k = OPAQUE_ZERO + 1u; k <= (size_t)PL_ALO_PLANT_SITES; k++) {
        all &= *(t.planted + k) > 0u;
    }
    for (size_t k = OPAQUE_ZERO + PL_ALO_FORCE_BRACKET + 1u; k <= (size_t)PL_ALO_FORCES; k++) {
        all &= *(t.capped + k) > 0u;
    }
    const int rows = t.ok_a > 0u && t.ok_b > 0u && t.edge_put > 0u && t.call_ok > 0u;
    const int zero_vol = t.zero_vol >= 7u; /* the 7 rows of cvectors.alo_zero_vol_rows */
    /* the 4 rows of cvectors.alo_qd_natural_rows */
    const int qd_natural = t.qd_natural >= 4u;
    const int found = zero_vol && qd_natural;
    const int ok =
        rows && t.double_boundary > 0u && t.bracket > 0u && t.persistent > 0u && all && found;
    require("engine-coverage", 0u, ok);
    printf("%s engine %zu fp-a %zu fp-b %zu edge %zu zero-vol %zu\n", verdict(ok), PL_VEC_ALO_COUNT,
           t.ok_a, t.ok_b, t.edge_put, t.zero_vol);
}

/* Record R3: every count within its QuantLib or Boost cap; 65 f calls, 13 NDd calls and 1,625
 * Legendre points on every evaluation that reaches the integral; a forced excess is a defect. */
static void bounded(void) {
    size_t through = 0u;
    for (size_t i = OPAQUE_ZERO; i < PL_VEC_ALO_COUNT; i++) {
        const struct pl_vec_alo *v = PL_VEC_ALO + i;
        const struct pl_params p = row_params(v->plant_site, v->force);
        struct pl_alo_trace tr;
        double value = 0.0;
        const double s = D(v->sigma);
        (void)pl_alo_result(v->side, D(v->S), D(v->K), D(v->T), D(v->r), D(v->q), s, &p, &tr,
                            &value);
        const int halley = tr.halley_max <= PL_ALO_CAP_HALLEY_MAX;
        const int a = halley & (tr.levels <= PL_ALO_CAP_LEVELS_MAX);
        const int b = (tr.fallback_max <= 1 + 1 + PL_ALO_CAP_BRENT_MAX);
        const int c = (tr.integrand <= PL_ALO_CAP_INTEGRAND_MAX);
        const int d = (tr.qd_calls <= PL_ALO_CAP_QD_CALLS_MAX);
        require("bounded", i, a & b & c & d);
        if (tr.levels > 0) {
            const int sweeps = (tr.sweep_f == PL_ALO_CAP_SWEEP_F_MAX);
            const int ndd = (tr.sweep_ndd == PL_ALO_CAP_SWEEP_NDD_MAX);
            require("bounded-sweeps", i, sweeps & ndd & (tr.legendre_points == 1625u));
            through++;
        }
        if (v->force > PL_ALO_FORCE_BRACKET) {
            require("bounded-force", i, (v->status == 2) == (tr.failed_cap == v->force - 1));
        }
    }
    const int ok = through > 0u;
    require("bounded-coverage", 0u, ok);
    printf("%s bounded %zu through-integral %zu\n", verdict(ok), PL_VEC_ALO_COUNT, through);
}

/* The European value of the engine (BlackCalculator of the put; a call is the put with spot,
 * strike and rates exchanged) at the read-back rates of the mapped problem. */
static double european(int side, double S, double K, double r_e, double q_e, double vol) {
    const double strike = (side == 1) ? K : S;
    const double spot = (side == 1) ? S : K;
    const double r = (side == 1) ? r_e : q_e;
    const double q = (side == 1) ? q_e : r_e;
    struct pl_black b;
    pl_black_init(&b, 1, strike, spot * pl_exp((r - q) * 1.0), vol * 1.0, pl_exp(-r * 1.0));
    return pl_black_value(&b);
}

/* I4.4 structural gates on every OK engine row of the case parameters that reaches the add-on
 * integral (calculatePut): value >= max(European, 0); every call equals pl_alo_engine of the put
 * with spot, strike and the rates exchanged. */
static void invariants(void) {
    size_t calls = 0u;
    size_t rows = 0u;
    for (size_t i = OPAQUE_ZERO; i < PL_VEC_ALO_COUNT; i++) {
        const struct pl_vec_alo *v = PL_VEC_ALO + i;
        if (v->status != 0 || v->plant_site != 0 || v->force != 0 || v->levels == 0) {
            continue;
        }
        const struct pl_params p = row_params(0, 0);
        double r1 = 0.0;
        double q1 = 0.0;
        double s1 = 0.0;
        pl_unit(D(v->T), D(v->r), D(v->q), D(v->sigma), &r1, &q1, &s1);
        double d_r = 0.0, d_q = 0.0, r_e = 0.0, q_e = 0.0;
        int defect = 0;
        pl_alo_read_back(r1, q1, &d_r, &d_q, &r_e, &q_e, &defect);
        const double eu = european(v->side, D(v->S), D(v->K), r_e, q_e, s1);
        require("invariant-european", i, D(v->value) >= pl_max(eu, 0.0));
        rows++;
        if (v->side == 0) {
            struct pl_alo_trace tr;
            double put = 0.0;
            const int st = (int)pl_alo_engine(1, D(v->K), D(v->S), d_q, d_r, s1, &p, &tr, &put);
            require("invariant-call", i, (st == PL_ENGINE_OK) & (defect == 0));
            same("invariant-call-bits", i, put, v->value);
            calls++;
        }
    }
    const int ok = rows > 0u && calls > 0u;
    require("invariants-coverage", 0u, ok);
    printf("%s invariants rows %zu calls %zu\n", verdict(ok), rows, calls);
}

int main(void) {
    params();
    engine();
    bounded();
    invariants();
    return 0;
}
