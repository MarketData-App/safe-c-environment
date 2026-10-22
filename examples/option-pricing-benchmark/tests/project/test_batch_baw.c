#define PL_TEST_VECTOR_ROWS
#include "pl_baw.h"
#include "pl_test_batch.h"
#include "pl_vec_evaluate_baw.h"

/* The BAW part of the batch (specs/project/batch.md "Batch"; G1.6, G4.8): rows 0-47 of
 * PL_VEC_EVALUATE_BAW are the 48 synthetic rows of test_batch.c. For every mask within
 * PL_TB_MASK_FULL that selects baw, serial and with two workers: the baw part equals the vector
 * entry (status, flags, value bits), calls[baw] = 48 and evals[baw] = the sum of the vector
 * engine_evals (H17). The masks with baw and the ALO bit run on the ALO subset in
 * test_batch_masks_alo3.c and test_batch_masks_alo4.c (controller ruling R-10b-B1: the baw part
 * keeps the full 48 rows here). A file of its own: the AST dump size limit of the source-policy
 * gate (one generated evaluate header per test file, Task 11 review M3). REQUIRE stays active
 * under NDEBUG. */

static uint64_t want_evals;

static void load_rows(void) {
    REQUIRE(PL_VEC_EVALUATE_BAW_COUNT >= PL_TB_N);
    for (size_t i = 0; i < PL_TB_N; i++) {
        const struct pl_vec_evaluate_baw *v = PL_VEC_EVALUATE_BAW + i;
        CHECK("load", i, (v->newton_max == PL_BAW_NEWTON_MAX) & (v->plant == 0) & (v->defect == 0));
        const struct pl_row r = PL_TB_VEC_ROW(v);
        pl_tb_store_row(i, &r);
        want_evals += (uint64_t)v->engine_evals;
    }
}

static void baw_mask(const struct pl_params *p, unsigned mask, unsigned threads) {
    const struct pl_input in = pl_tb_rows_input(0u, PL_TB_N);
    const struct pl_output out = {PL_OUTPUT_RESULTS, 0u, tb_pooled, NULL};
    struct pl_batch_stats st = {0};
    pl_poison_results(tb_pooled, PL_TB_N);
    const int rc = pl_tb_run(&in, p, 0, mask, threads, &out, &st);
    CHECK("baw-run", 4u * mask + threads, rc == PL_BATCH_OK);
    for (size_t i = 0; i < PL_TB_N; i++) { /* one CHECK per row (the GCC analyzer budget) */
        const struct pl_vec_evaluate_baw *v = PL_VEC_EVALUATE_BAW + i;
        CHECK("baw-parts", i, PL_TB_SAME_AS_VECTOR((tb_pooled + i)->model + PL_MODEL_BAW, v));
    }
    const uint64_t *calls = st.calls, *evals = st.evals;
    const int calls_ok = *(calls + PL_MODEL_BAW) == PL_TB_N;
    const int counts = calls_ok & (*(evals + PL_MODEL_BAW) == want_evals);
    CHECK("baw-counts", 4u * mask + threads, counts);
}

int main(void) {
    load_rows();
    struct pl_params p;
    pl_case_params(&p);
    size_t checked = 0u;
    for (unsigned mask = 1u; mask <= PL_MASK_MODELS5; mask++) {
        const unsigned baw = (mask >> PL_MODEL_BAW) & 1u;
        if (baw != 0u && (mask & ~PL_TB_MASK_FULL) == 0u) {
            baw_mask(&p, mask, 0u);
            baw_mask(&p, mask, 2u);
            checked++;
        }
    }
    REQUIRE(checked >= 8u);
    puts("PASS baw-parts");
    return 0;
}
