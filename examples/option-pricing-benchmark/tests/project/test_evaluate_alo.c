#define PL_TEST_EVALUATE_ALO
#include "pl_test_alo.h"

/* Bit-exact test of pl_evaluate for PL_MODEL_ALO against reference.evaluate
 * (specs/project/models.md "Row evaluation" and "ALO (Amendment I)"; cvectors part evaluate_alo):
 * every row of part evaluate, the oracle ALO edge rows with their test-only parameters, and three
 * rows under every planted site and forced defect. Equal status, flags (16 and 32 included) and
 * engine-evaluation count (H17: the Brent evaluations that pass the pre check plus the stencil
 * points; no separate call at the IV), the seven values as equal bits or both NaN, and
 * PL_EVAL_DEFECT exactly where Python raised (an ALO run defect: never a status). The wiring
 * checks, then every row of the table (pl_test_alo.h, one slice). */

/* The wiring of Task 10b: PL_MASK_WIRED is MODELS5; pl_price and pl_price_and_greeks of ALO give
 * the engine values; the C contract of the test-only parameters. */
static void wiring(void) {
    struct pl_params p;
    pl_case_params(&p);
    CHECK("wired", 0u, PL_MASK_WIRED == PL_MASK_MODELS5);
    const struct pl_row row = {0, 100.0, 100.0, 1.0, 10.0, 11.0, 0.04, 0.012};
    const struct pl_row expired = {0, 100.0, 100.0, 0.0, 10.0, 11.0, 0.04, 0.012};
    struct pl_model_result out;
    uint32_t n = 9u;
    CHECK("wired", 1u, pl_evaluate(&expired, PL_MODEL_ALO, &p, &out, &n) == PL_EVAL_OK);
    CHECK("wired", 2u, (out.status == PL_EXPIRED) & (n == 0u));
    double v = 0.0;
    uint8_t f = 0u;
    int st = (int)pl_price(PL_MODEL_ALO, 0, 100.0, 100.0, 1.0, 0.04, 0.012, 0.2, &p, &v, &f);
    CHECK("price", 0u, (st == PL_ENGINE_OK) & pl_is_finite(v) & (f == 0u));
    struct pl_alo_trace tr;
    double w = 0.0;
    st = (int)pl_alo_result(0, 100.0, 100.0, 1.0, 0.04, 0.012, 0.2, &p, &tr, &w);
    CHECK("price", 1u, (st == PL_ENGINE_OK) & (pl_double_bits(v) == pl_double_bits(w)));
    st = (int)pl_price(PL_MODEL_ALO, 0, 100.0, 100.0, 1.0, 0.04, 0.012, -0.2, &p, &v, &f);
    CHECK("price", 2u, (st == PL_ENGINE_QL_ERROR) & pl_is_nan(v));
    struct pl_params bad = p;
    bad.alo_plant_site = PL_ALO_PLANT_SITES + 1;
    CHECK("contract", 0u, pl_evaluate(&row, PL_MODEL_ALO, &bad, &out, &n) == PL_EVAL_DEFECT);
    CHECK("contract", 1u, (out.status == PL_INVALID_INPUT) & (n == 0u) & pl_ta_all_nan(out.values));
    bad = p;
    bad.alo_force = -1;
    CHECK("contract", 2u, pl_evaluate(&row, PL_MODEL_BSM, &bad, &out, &n) == PL_EVAL_DEFECT);
    bad.alo_force = PL_ALO_FORCES;
    CHECK("contract", 3u, pl_evaluate(&row, PL_MODEL_BSM, &bad, &out, &n) == PL_EVAL_OK);
    double values[PL_FIELDS];
    int band = 0;
    uint32_t evals = 0u;
    int defect = 0;
    st = pl_alo_price_and_greeks(NULL, 0.2, &p, values, &band, &f, &evals, &defect);
    CHECK("contract", 4u, (st == 1) & (defect == 1) & pl_ta_all_nan(values));
    st = pl_alo_price_and_greeks(&row, 0.2, &p, values, &band, &f, &evals, NULL);
    CHECK("contract", 5u, (st == 1) & pl_ta_all_nan(values));
}

int main(void) {
    wiring();
    puts("PASS wiring");
    return pl_ta_evaluate_slice(0u);
}
