#include "pl_black.h"
#include "pl_ieee.h"
#include "pl_vec_black.h"
#include <stdio.h>
#include <stdlib.h>

/* Bit-exact tests of pl_black.c and pl_bsm.c against the optionlab vectors
 * (specs/project/models.md "Term structure, mapping and BSM"): equal bits, or both NaN.
 * REQUIRE-style: the first failed check prints "FAIL <group> <index>" and exits 1 (active under
 * NDEBUG). The checks are macros, not functions, and one loop drives each table, so the GCC
 * analyzer explores each check once (the fixed analyzer budget of the framework). */

#define D(x) pl_bits_double(x)
#define QNAN UINT64_C(0x7ff8000000000000)
/* 1 when the double g has the bits w, or both are NaN; g is a variable or a member. */
#define SAME(g, w) ((pl_double_bits(g) == (w)) | (pl_is_nan(g) & pl_is_nan(D(w))))
#define FAIL(group, i) (printf("FAIL %s %zu\n", group, i), exit(1))
#define CHECK(group, i, ok) ((ok) ? (void)0 : FAIL(group, i))

/* One row of table black: the defect of pl_mapped_inputs; the engine status (PL_ENGINE_PY_DEFECT
 * and only NaN for a raising row); for a row that returns: d_r, d_q and variance, the price-only
 * value with NaN greeks, value and greeks, NaN strike members, one defect bit per term-structure
 * helper and the helper value where that helper returns (a raising row has no helper values:
 * Python raised before them). */
static void engine_row(size_t i, const struct pl_vec_black *v) {
    double d_r;
    double d_q;
    double variance;
    int defect = 0;
    pl_mapped_inputs(D(v->T), D(v->r), D(v->q), D(v->sigma), &d_r, &d_q, &variance, &defect);
    CHECK("defect", i, defect == v->defect);
    struct pl_engine_result e;
    struct pl_engine_result p;
    const enum pl_engine_status se =
        pl_bsm_result(v->side, D(v->S), D(v->K), D(v->T), D(v->r), D(v->q), D(v->sigma), 1, &e);
    const enum pl_engine_status sp =
        pl_bsm_result(v->side, D(v->S), D(v->K), D(v->T), D(v->r), D(v->q), D(v->sigma), 0, &p);
    const enum pl_engine_status want = defect != 0 ? PL_ENGINE_PY_DEFECT : PL_ENGINE_OK;
    CHECK("status", i, (se == want) & (sp == want));
    CHECK("price-only", i, SAME(p.value, v->price));
    CHECK("value", i, SAME(e.value, v->value));
    CHECK("delta", i, SAME(e.delta, v->delta));
    CHECK("gamma", i, SAME(e.gamma, v->gamma));
    CHECK("theta", i, SAME(e.theta, v->theta));
    CHECK("vega", i, SAME(e.vega, v->vega));
    CHECK("rho", i, SAME(e.rho, v->rho));
    CHECK("dividend-rho", i, SAME(e.dividend_rho, v->dividendrho));
    /* NaN members: both strike members always; every greek of the price-only call. */
    CHECK("strike-nan", i, SAME(e.strike_sensitivity, QNAN) & SAME(e.strike_gamma, QNAN));
    CHECK("strike-nan", i, SAME(p.strike_sensitivity, QNAN) & SAME(p.strike_gamma, QNAN));
    CHECK("price-only-nan", i, SAME(p.delta, QNAN) & SAME(p.gamma, QNAN) & SAME(p.theta, QNAN));
    CHECK("price-only-nan", i, SAME(p.vega, QNAN) & SAME(p.rho, QNAN));
    CHECK("price-only-nan", i, SAME(p.dividend_rho, QNAN));
    if (defect != 0) {
        return; /* Python raised: no mapped values and no helper values to compare */
    }
    CHECK("d_r", i, SAME(d_r, v->d_r));
    CHECK("d_q", i, SAME(d_q, v->d_q));
    CHECK("variance", i, SAME(variance, v->variance));
    const double r1 = D(v->r) * D(v->T);
    int dd = 0;
    int dz = 0;
    int df = 0; /* one defect flag per call, as Python raises per call */
    const double disc = pl_discount(r1, 1.0, &dd);
    const double zero = pl_zero_rate(r1, 0.0, &dz);
    const double fwd = pl_forward_rate(r1, 0.0, 0.0001, &df);
    CHECK("helper-defect", i, dd == v->defect_discount);
    CHECK("helper-defect", i, dz == v->defect_zero_rate);
    CHECK("helper-defect", i, df == v->defect_forward_rate);
    CHECK("discount", i, dd | SAME(disc, v->discount));
    CHECK("zero-rate", i, dz | SAME(zero, v->zero_rate));
    CHECK("forward-rate", i, df | SAME(fwd, v->forward_rate));
    /* zero_rate replaces t == 0.0 (both zeros) by 0.0001, so t = 0.0001 and t = -0.0 give the
     * bits and the defect of t = 0.0 (the branch t != 0.0 runs for t = 0.0001). */
    int dz_dt = 0;
    int dz_minus = 0;
    const uint64_t zero_bits = pl_double_bits(zero);
    const double zero_dt = pl_zero_rate(r1, 0.0001, &dz_dt);
    const double zero_minus = pl_zero_rate(r1, -0.0, &dz_minus);
    CHECK("zero-rate-dt", i, (dz_dt == dz) & (dz | SAME(zero_dt, zero_bits)));
    CHECK("zero-rate-minus", i, (dz_minus == dz) & (dz | SAME(zero_minus, zero_bits)));
}

/* One row of table black_calc: every member that pl_black_init sets and every result function
 * of BlackCalculator. */
static void calculator_row(size_t i, const struct pl_vec_black_calc *v) {
    struct pl_black b;
    pl_black_init(&b, v->side, D(v->strike), D(v->forward), D(v->std_dev), D(v->discount));
    const double spot = D(v->spot);
    const double maturity = D(v->maturity);
    CHECK("calc-variance", i, SAME(b.variance, v->variance));
    CHECK("calc-d1", i, SAME(b.d1, v->d1));
    CHECK("calc-d2", i, SAME(b.d2, v->d2));
    CHECK("calc-alpha", i, SAME(b.alpha, v->alpha));
    CHECK("calc-dalpha", i, SAME(b.dalpha_dd1, v->dalphadd1));
    CHECK("calc-beta", i, SAME(b.beta, v->beta));
    CHECK("calc-dbeta", i, SAME(b.dbeta_dd2, v->dbetadd2));
    const double value = pl_black_value(&b);
    const double delta = pl_black_delta(&b, spot);
    const double delta_forward = pl_black_delta_forward(&b);
    const double gamma = pl_black_gamma(&b, spot);
    const double theta = pl_black_theta(&b, spot, maturity);
    const double vega = pl_black_vega(&b, maturity);
    const double rho = pl_black_rho(&b, maturity);
    const double dividend_rho = pl_black_dividend_rho(&b, maturity);
    const double strike = pl_black_strike_sensitivity(&b);
    CHECK("calc-value", i, SAME(value, v->value));
    CHECK("calc-delta", i, SAME(delta, v->delta));
    CHECK("calc-delta-forward", i, SAME(delta_forward, v->deltaforward));
    CHECK("calc-gamma", i, SAME(gamma, v->gamma));
    CHECK("calc-theta", i, SAME(theta, v->theta));
    CHECK("calc-vega", i, SAME(vega, v->vega));
    CHECK("calc-rho", i, SAME(rho, v->rho));
    CHECK("calc-dividend-rho", i, SAME(dividend_rho, v->dividendrho));
    CHECK("calc-strike-sensitivity", i, SAME(strike, v->strikesensitivity));
}

int main(void) {
    for (size_t i = 0; i < PL_VEC_BLACK_COUNT; i++) {
        engine_row(i, PL_VEC_BLACK + i);
    }
    puts("PASS black-engine");
    for (size_t i = 0; i < PL_VEC_BLACK_CALC_COUNT; i++) {
        calculator_row(i, PL_VEC_BLACK_CALC + i);
    }
    puts("PASS black-calc");
    return 0;
}
