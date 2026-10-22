#include "pl_crr.h"
#include "pl_ieee.h"
#include "pl_vec_crr.h"
#include <stdio.h>
#include <stdlib.h>

/* Bit-exact tests of pl_crr.c against the optionlab vectors (specs/project/models.md "CRR",
 * "sigma_lo and the CRR domain" and "Case parameters"): equal bits, or both NaN. REQUIRE-style:
 * the first failed check prints "FAIL <group> <index>" and exits 1 (active under NDEBUG). The
 * checks are macros, not functions, and one loop drives each table, so the GCC analyzer explores
 * each check once (the fixed analyzer budget of the framework). */

#define D(x) pl_bits_double(x)
/* 1 when the double g has the bits w, or both are NaN; g is a variable or a member. */
#define SAME(g, w) ((pl_double_bits(g) == (w)) | (pl_is_nan(g) & pl_is_nan(D(w))))
#define FAIL(group, i) (printf("FAIL %s %zu\n", group, i), exit(1))
#define CHECK(group, i, ok) ((ok) ? (void)0 : FAIL(group, i))
/* The members that pl_crr_engine never computes are NaN. */
#define NAN3(e) (pl_is_nan((e).vega) & pl_is_nan((e).rho) & pl_is_nan((e).dividend_rho))
#define OTHERS_NAN(e) (NAN3(e) & pl_is_nan((e).strike_sensitivity) & pl_is_nan((e).strike_gamma))
#define FLAGS(v) (v)->steps, (v)->american, (v)->with_theta, (v)->greeks
#define ROW(v) (v)->side, D((v)->S), D((v)->K), D((v)->T), D((v)->r), D((v)->q), D((v)->sigma)

/* One row of table crr: the tree and its defect bit; the status of pl_crr_result with and
 * without greeks (vector defect 1 is PL_ENGINE_PY_DEFECT, status 1 is PL_ENGINE_QL_ERROR); the
 * price-only value, value, delta, gamma and theta (NaN for a status other than 0). */
static void crr_row(size_t i, const struct pl_vec_crr *v, const struct pl_params *p) {
    struct pl_crr_tree t;
    struct pl_engine_result e;
    struct pl_engine_result pv;
    int defect = 0;
    pl_crr_mapped_tree(D(v->T), D(v->r), D(v->q), D(v->sigma), p->crr_steps, &t, &defect);
    CHECK("defect", i, defect == v->defect);
    CHECK("dx", i, SAME(t.dx, v->dx));
    CHECK("drift", i, SAME(t.drift_per_step, v->drift_per_step));
    CHECK("disc", i, SAME(t.disc, v->disc));
    CHECK("theta-r", i, SAME(t.theta_r, v->theta_r));
    CHECK("theta-q", i, SAME(t.theta_q, v->theta_q));
    CHECK("theta-v", i, SAME(t.theta_v, v->theta_v));
    const int want = (v->defect != 0) ? (int)PL_ENGINE_PY_DEFECT : v->status;
    const int status = (int)pl_crr_result(ROW(v), p->crr_steps, v->american, 1, &e);
    const int status_p = (int)pl_crr_result(ROW(v), p->crr_steps, v->american, 0, &pv);
    CHECK("status", i, (status == want) & (status_p == want));
    CHECK("price-only", i, SAME(pv.value, v->value) & pl_is_nan(pv.delta) & pl_is_nan(pv.theta));
    CHECK("value", i, SAME(e.value, v->value));
    CHECK("delta", i, SAME(e.delta, v->delta));
    CHECK("gamma", i, SAME(e.gamma, v->gamma));
    CHECK("theta", i, SAME(e.theta, v->theta));
    CHECK("others-nan", i, OTHERS_NAN(e) & OTHERS_NAN(pv));
}

/* One row of table crr_engine: the status and the four members of a direct pl_crr_engine call. */
static void engine_row(size_t i, const struct pl_vec_crr_engine *v) {
    struct pl_crr_tree t;
    struct pl_engine_result e;
    t.dx = D(v->dx);
    t.drift_per_step = D(v->drift_per_step);
    t.disc = D(v->disc);
    t.theta_r = D(v->theta_r);
    t.theta_q = D(v->theta_q);
    t.theta_v = D(v->theta_v);
    const int status = (int)pl_crr_engine(v->side, D(v->S), D(v->K), &t, FLAGS(v), &e);
    CHECK("engine-status", i, status == v->status);
    CHECK("engine-value", i, SAME(e.value, v->value));
    CHECK("engine-delta", i, SAME(e.delta, v->delta));
    CHECK("engine-gamma", i, SAME(e.gamma, v->gamma));
    CHECK("engine-theta", i, SAME(e.theta, v->theta));
    CHECK("engine-others-nan", i, OTHERS_NAN(e));
}

/* One row of table crr_tree: pl_crr_mapped_tree at another step count. */
static void tree_row(size_t i, const struct pl_vec_crr_tree *v) {
    struct pl_crr_tree t;
    int defect = 0;
    pl_crr_mapped_tree(D(v->T), D(v->r), D(v->q), D(v->sigma), v->steps, &t, &defect);
    CHECK("tree-defect", i, defect == v->defect);
    CHECK("tree-dx", i, SAME(t.dx, v->dx));
    CHECK("tree-drift", i, SAME(t.drift_per_step, v->drift_per_step));
    CHECK("tree-disc", i, SAME(t.disc, v->disc));
    CHECK("tree-theta-r", i, SAME(t.theta_r, v->theta_r));
    CHECK("tree-theta-q", i, SAME(t.theta_q, v->theta_q));
    CHECK("tree-theta-v", i, SAME(t.theta_v, v->theta_v));
}

/* One row of table crr_lo: sigma_lo of the row's model and the CRR domain check. */
static void lo_row(size_t i, const struct pl_vec_crr_lo *v, const struct pl_params *p) {
    const double lo = pl_sigma_lo(v->model, v->side, D(v->T), D(v->r), D(v->q), p);
    CHECK("sigma-lo", i, SAME(lo, v->sigma_lo));
    CHECK("domain", i, pl_crr_domain_ok(D(v->T), D(v->r), D(v->q), p) == v->domain_ok);
}

int main(void) {
    struct pl_params p;
    pl_case_params(&p);
    const int steps_ok = (p.crr_steps == 100) & (p.sigma_hi == 5.0) & (p.kappa_cap == 50.0);
    CHECK("params", (size_t)0, steps_ok & (p.h_r == 1e-4) & (p.h_sigma == 1e-3));
    puts("PASS params");
    for (size_t i = 0; i < PL_VEC_CRR_COUNT; i++) {
        crr_row(i, PL_VEC_CRR + i, &p);
    }
    printf("PASS crr %zu\n", PL_VEC_CRR_COUNT);
    for (size_t i = 0; i < PL_VEC_CRR_ENGINE_COUNT; i++) {
        engine_row(i, PL_VEC_CRR_ENGINE + i);
    }
    printf("PASS crr-engine %zu\n", PL_VEC_CRR_ENGINE_COUNT);
    for (size_t i = 0; i < PL_VEC_CRR_TREE_COUNT; i++) {
        tree_row(i, PL_VEC_CRR_TREE + i);
    }
    printf("PASS crr-tree %zu\n", PL_VEC_CRR_TREE_COUNT);
    for (size_t i = 0; i < PL_VEC_CRR_LO_COUNT; i++) {
        lo_row(i, PL_VEC_CRR_LO + i, &p);
    }
    printf("PASS crr-lo %zu\n", PL_VEC_CRR_LO_COUNT);
    /* steps outside [2, PL_CRR_MAX_STEPS]: below, the Python ModelDefect; above, the stack scratch
     * bound (Python has no such bound; the row path uses N = 100). Every member NaN. */
    struct pl_engine_result bad;
    const struct pl_crr_tree t1 = {0.1, 0.0, 1.0, 0.0, 0.0, 0.0};
    const int max = PL_CRR_MAX_STEPS;
    const int below = (int)pl_crr_engine(0, 100.0, 100.0, &t1, 1, 1, 1, 1, &bad);
    CHECK("steps", (size_t)0, (below == (int)PL_ENGINE_QL_ERROR) & pl_is_nan(bad.value));
    const int above = (int)pl_crr_engine(0, 100.0, 100.0, &t1, max + 1, 1, 1, 1, &bad);
    CHECK("steps", (size_t)1, (above == (int)PL_ENGINE_QL_ERROR) & pl_is_nan(bad.value));
    const int at_max = (int)pl_crr_engine(0, 100.0, 100.0, &t1, max, 1, 1, 1, &bad);
    CHECK("steps", (size_t)2, (at_max == (int)PL_ENGINE_OK) & pl_is_finite(bad.value));
    /* the lattice refuses steps outside [2, PL_CRR_MAX_STEPS] and i outside [0, steps) before it
     * forms a position, and accepts the bounds */
    struct pl_crr_lattice lat;
    lat.side = 0;
    lat.american = 1;
    lat.S = 100.0;
    lat.K = 100.0;
    lat.dx = 0.1;
    lat.pu = 0.5;
    lat.pd = 0.5;
    lat.disc = 1.0;
    lat.steps = 1;
    int refused = pl_crr_lattice_reset(&lat) & pl_crr_lattice_step(&lat, 0);
    lat.steps = max + 1;
    refused &= pl_crr_lattice_reset(&lat) & pl_crr_lattice_step(&lat, 0);
    lat.steps = 3;
    refused &= pl_crr_lattice_step(&lat, -1) & pl_crr_lattice_step(&lat, 3);
    const int reset = pl_crr_lattice_reset(&lat);
    const int accepted = (reset == 0) & (pl_crr_lattice_step(&lat, 2) == 0);
    CHECK("lattice", (size_t)0, refused & accepted);
    lat.steps = max;
    const int reset_max = pl_crr_lattice_reset(&lat);
    const int step_max = pl_crr_lattice_step(&lat, max - 1);
    CHECK("lattice", (size_t)1, (reset_max == 0) & (step_max == 0));
    /* the defect is only set, never cleared */
    struct pl_crr_tree t2;
    int kept = 1;
    pl_crr_mapped_tree(1.0, 0.04, 0.012, 0.2, 100, &t2, &kept);
    CHECK("defect-kept", (size_t)0, (kept == 1) & pl_is_finite(t2.dx));
    puts("PASS steps");
    return 0;
}
