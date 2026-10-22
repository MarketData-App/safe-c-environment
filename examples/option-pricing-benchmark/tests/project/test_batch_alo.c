#define PL_TEST_VECTOR_ROWS
#define PL_TEST_BATCH_ALO
#include "pl_test_batch.h"

/* The ALO part of the batch (specs/project/batch.md "Batch"; controller ruling R-10b-B1) on the
 * representative ALO subset of PL_VEC_BATCH_ALO: the PL_MASK_WIRED serial results (each ALO part
 * equals its vector entry, the ALO counters equal the vector counts), the pooled results with 1,
 * 2, 3 and 4 workers byte-identical to them with the same counters, and the reduction of the
 * serial results under PL_MASK_WIRED. The input kinds are in test_batch_alo_kinds.c and the trace
 * in test_batch_alo_stats.c (ruling (g): the 10 s test timeout of the coverage build). REQUIRE
 * stays active under NDEBUG. */

static struct pl_batch_stats wired;

static void pooled(void) {
    struct pl_params p;
    pl_case_params(&p);
    const struct pl_input in = pl_tb_rows_input(0u, PL_TB_ALO_N);
    for (unsigned t = 1u; t <= 4u; t++) {
        struct pl_output po = pl_tb_pooled_output();
        struct pl_batch_stats ps = {0};
        pl_poison_results(tb_pooled, PL_TB_N);
        int ok = pl_tb_run(&in, &p, 0, PL_MASK_WIRED, t, &po, &ps) == PL_BATCH_OK;
        ok &= (ps.chunks == t) & pl_tb_same_results(tb_serial, tb_pooled, PL_TB_ALO_N);
        const int calls = memcmp(ps.calls, wired.calls, sizeof ps.calls) == 0;
        const int evals = memcmp(ps.evals, wired.evals, sizeof ps.evals) == 0;
        CHECK("alo-pooled", t, ok & calls & evals);
    }
    puts("PASS alo-pooled");
}

static void reduction(void) {
    struct pl_reduction red;
    pl_reduce(tb_serial, PL_TB_ALO_N, PL_MASK_WIRED, &red);
    uint64_t total = 0u;
    for (size_t sidx = 0; sidx < 9u; sidx++) {
        total += *(*(red.counts + PL_MODEL_ALO) + sidx);
    }
    REQUIRE((red.models == PL_MASK_WIRED) & (total == (uint64_t)PL_TB_ALO_N));
    uint64_t ok_rows = 0u;
    for (size_t k = 0; k < PL_TB_ALO_N; k++) {
        ok_rows += (uint64_t)((PL_VEC_BATCH_ALO + k)->status == PL_OK);
    }
    REQUIRE(*(*(red.counts + PL_MODEL_ALO) + PL_OK) == ok_rows);
    REQUIRE(*(red.max_iv_index + PL_MODEL_ALO) >= 0);
    puts("PASS alo-reduction");
}

int main(void) {
    pl_tb_load_alo_rows();
    pl_tb_alo_baseline(&wired);
    puts("PASS alo-serial");
    pooled();
    reduction();
    return 0;
}
