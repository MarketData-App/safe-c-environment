#define PL_TEST_VECTOR_ROWS
#include "pl_test_batch.h"
#include "pl_vec_batch_rows.h"

/* Echo, reduction and argument refusals of the batch (specs/project/batch.md "Batch", "Reduction",
 * "Echo"; Amendment G item G4.6) on the 48 rows of test_batch.c (the synthetic prefix of
 * PL_VEC_EVALUATE): the echo content and counters, echo with an unwired mask, the threads, mask and
 * scratch refusals, and the reduction of the PL_TB_MASK_FULL serial results. A file of its own: the
 * AST dump size limit of the ast gate (each file with the generated evaluate header). REQUIRE stays
 * active under NDEBUG. */

static void echo_reduce_and_arguments(void) {
    struct pl_params p;
    pl_case_params(&p);
    struct pl_batch_scratch s = {tb_perm, tb_mark, tb_idx, PL_TB_N};
    struct pl_input in = {PL_INPUT_ROWS, 0u, PL_TB_N, tb_rows, NULL, {NULL}};
    struct pl_output out = {PL_OUTPUT_RESULTS, 0u, tb_pooled, NULL};
    struct pl_batch_stats st = {0};
    REQUIRE(pl_batch_run_untraced(&in, &p, 1, PL_MASK_ALL3, 2u, 0u, &s, &out, &st) == PL_BATCH_OK);
    const struct pl_contract_result *r7 = tb_pooled + 7;
    REQUIRE((r7->model + 2)->status == PL_ECHO && pl_is_nan(*((r7->model + 2)->values)));
    REQUIRE((r7->model + 3)->status == PL_NOT_REQUESTED); /* G4.6 */
    REQUIRE((r7->model + 4)->status == PL_NOT_REQUESTED);
    REQUIRE(pl_tb_not_requested(r7->model + 3) && pl_tb_not_requested(r7->model + 4));
    REQUIRE((r7->model + 0)->flags == 0u && pl_is_nan(*((r7->model + 0)->values + 6)));
    for (size_t m = 0; m < PL_MODELS; m++) { /* echo evaluates no model */
        REQUIRE(*(st.calls + m) == 0u && *(st.evals + m) == 0u);
    }
    struct pl_batch_stats se = {0}; /* echo needs no wired model: mask 31 succeeds */
    REQUIRE(pl_tb_run(&in, &p, 1, PL_MASK_MODELS5, 0u, &out, &se) == PL_BATCH_OK);
    REQUIRE(((tb_pooled + 3)->model + 4)->status == PL_ECHO);
    REQUIRE(pl_tb_run(&in, &p, 0, PL_TB_MASK_FULL, 5u, &out, &st) == PL_BATCH_ARGUMENT);
    REQUIRE(pl_batch_run_untraced(&in, &p, 0, 0u, 0u, 0u, &s, &out, &st) == PL_BATCH_ARGUMENT);
    REQUIRE(pl_batch_run_untraced(&in, &p, 0, 32u, 0u, 0u, &s, &out, &st) == PL_BATCH_ARGUMENT);
    struct pl_batch_scratch small = {tb_perm, tb_mark, tb_idx, PL_TB_N - 1u};
    const int rc = pl_batch_run_untraced(&in, &p, 0, PL_TB_MASK_FULL, 2u, 0u, &small, &out, &st);
    REQUIRE(rc == PL_BATCH_ARGUMENT);
    struct pl_reduction red;
    pl_reduce(tb_serial, PL_TB_N, PL_TB_MASK_FULL, &red);
    uint64_t total = 0u;
    for (size_t sidx = 0; sidx < 9u; sidx++) {
        total += *(*(red.counts) + sidx);
    }
    REQUIRE(total == PL_TB_N && *(red.max_iv_index) >= -1);
    REQUIRE(red.models == PL_TB_MASK_FULL && *(*(red.counts) + PL_OK) == 40u);
    pl_reduce(tb_serial, 0u, PL_TB_MASK_FULL, &red);
    REQUIRE(*(red.max_iv_index) == -1 && pl_is_nan(*(red.max_iv)));
    puts("PASS echo-reduce-arguments");
}

int main(void) {
    PL_TB_LOAD_VECTOR_ROWS();
    pl_tb_baseline(NULL);
    echo_reduce_and_arguments();
    return 0;
}
