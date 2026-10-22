#include "pl_bjs.h"
#include "pl_ieee.h"
#include "pl_vec_bjs.h"
#include <stdio.h>
#include <stdlib.h>

/* Bit-exact tests of pl_bjs.c and pl_bjs_phi.c against the optionlab vectors
 * (specs/project/models.md "Bjerksund-Stensland 1993"): equal bits, or both NaN. REQUIRE-style:
 * the first failed check prints "FAIL <group> <index>" and exits 1 (active under NDEBUG). The
 * checks are macros, not functions, and one loop drives each table, so the GCC analyzer explores
 * each check once (the fixed analyzer budget of the framework). */

#define D(x) pl_bits_double(x)
/* 1 when the double g has the bits w, or both are NaN; g is a variable or a member. */
#define SAME(g, w) ((pl_double_bits(g) == (w)) | (pl_is_nan(g) & pl_is_nan(D(w))))
#define FAIL(group, i) (printf("FAIL %s %zu\n", group, i), exit(1))
#define CHECK(group, i, ok) ((ok) ? (void)0 : FAIL(group, i))
#define ARGS7(v) D((v)->S), D((v)->gamma), D((v)->H), D((v)->I), D((v)->rT), D((v)->bT), D((v)->v)
#define ROW(v) (v)->side, D((v)->S), D((v)->K), D((v)->T), D((v)->r), D((v)->q), D((v)->sigma)

/* One row of table bjs_phi: phi and its eight analytic derivatives. */
static void phi_row(size_t i, const struct pl_vec_bjs_phi *v) {
    const double phi = pl_bjs_phi(ARGS7(v));
    const double phi_s = pl_bjs_phi_s(ARGS7(v));
    const double phi_ss = pl_bjs_phi_ss(ARGS7(v));
    const double phi_gamma = pl_bjs_phi_gamma(ARGS7(v));
    const double phi_h = pl_bjs_phi_h(ARGS7(v));
    const double phi_i = pl_bjs_phi_i(ARGS7(v));
    const double phi_rt = pl_bjs_phi_rt(ARGS7(v));
    const double phi_bt = pl_bjs_phi_bt(ARGS7(v));
    const double phi_v = pl_bjs_phi_v(ARGS7(v));
    CHECK("phi", i, SAME(phi, v->phi));
    CHECK("phi-s", i, SAME(phi_s, v->phi_s));
    CHECK("phi-ss", i, SAME(phi_ss, v->phi_ss));
    CHECK("phi-gamma", i, SAME(phi_gamma, v->phi_gamma));
    CHECK("phi-h", i, SAME(phi_h, v->phi_h));
    CHECK("phi-i", i, SAME(phi_i, v->phi_i));
    CHECK("phi-rt", i, SAME(phi_rt, v->phi_rt));
    CHECK("phi-bt", i, SAME(phi_bt, v->phi_bt));
    CHECK("phi-v", i, SAME(phi_v, v->phi_v));
}

/* One row of table bjs: the status of both calls (with and without greeks); for status 0 the
 * price-only value, the value and the six greeks; for status 1 (QuantLib error) and 2 (Python
 * defect) every member NaN. */
static void engine_row(size_t i, const struct pl_vec_bjs *v) {
    struct pl_engine_result e;
    struct pl_engine_result p;
    const int status = (int)pl_bjs_result(ROW(v), 1, &e);
    const int status_p = (int)pl_bjs_result(ROW(v), 0, &p);
    CHECK("status", i, (status == v->status) & (status_p == v->status));
    CHECK("price-only", i, SAME(p.value, v->price));
    CHECK("value", i, SAME(e.value, v->value));
    CHECK("delta", i, SAME(e.delta, v->delta));
    CHECK("gamma", i, SAME(e.gamma, v->gamma));
    CHECK("theta", i, SAME(e.theta, v->theta));
    CHECK("vega", i, SAME(e.vega, v->vega));
    CHECK("rho", i, SAME(e.rho, v->rho));
    CHECK("dividend-rho", i, SAME(e.dividend_rho, v->dividendrho));
    if (status == 0) {
        return;
    }
    /* status 1 or 2: the strike members are NaN too (every member of both results) */
    CHECK("error-nan", i, pl_is_nan(e.strike_sensitivity) & pl_is_nan(e.strike_gamma));
    CHECK("error-nan", i, pl_is_nan(p.delta) & pl_is_nan(p.strike_sensitivity));
}

/* One row of table bjs_immediate: every member of pl_bjs_immediate. */
static void immediate_row(size_t i, const struct pl_vec_bjs_immediate *v) {
    struct pl_engine_result r;
    pl_bjs_immediate(D(v->S), D(v->X), &r);
    CHECK("immediate-value", i, SAME(r.value, v->value));
    CHECK("immediate-delta", i, SAME(r.delta, v->delta));
    CHECK("immediate-gamma", i, SAME(r.gamma, v->gamma));
    CHECK("immediate-rho", i, SAME(r.rho, v->rho));
    CHECK("immediate-dividend-rho", i, SAME(r.dividend_rho, v->dividendrho));
    CHECK("immediate-vega", i, SAME(r.vega, v->vega));
    CHECK("immediate-theta", i, SAME(r.theta, v->theta));
    CHECK("immediate-strike", i, SAME(r.strike_sensitivity, v->strikesensitivity));
    CHECK("immediate-strike-gamma", i, SAME(r.strike_gamma, v->strikegamma));
}

int main(void) {
    for (size_t i = 0; i < PL_VEC_BJS_PHI_COUNT; i++) {
        phi_row(i, PL_VEC_BJS_PHI + i);
    }
    puts("PASS bjs-phi");
    for (size_t i = 0; i < PL_VEC_BJS_IMMEDIATE_COUNT; i++) {
        immediate_row(i, PL_VEC_BJS_IMMEDIATE + i);
    }
    puts("PASS bjs-immediate");
    for (size_t i = 0; i < PL_VEC_BJS_COUNT; i++) {
        engine_row(i, PL_VEC_BJS + i);
    }
    puts("PASS bjs-engine");
    return 0;
}
