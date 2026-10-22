#include "pl_test_batch.h"

/* The argument limits of pl_batch_run (specs/project/batch.md "Batch"): every argument refusal
 * writes nothing. The batch limit tests are six files (test_batch_limits.c, test_batch_sizes.c,
 * test_batch_small.c, test_batch_threads.c, test_batch_wide.c, test_batch_helpers.c): the fixed
 * GCC analyzer budget of one translation unit. The 48 rows are synthetic. REQUIRE stays active
 * under NDEBUG. */

/* 1 when the 290-byte record of r equals the poisoned record (every part NOT_REQUESTED). */
static int untouched_row(const struct pl_contract_result *r) {
    struct pl_contract_result poisoned;
    uint8_t a[PL_RESPONSE_RECORD_BYTES], b[PL_RESPONSE_RECORD_BYTES];
    pl_poison_results(&poisoned, 1u);
    pl_response_encode(r, a);
    pl_response_encode(&poisoned, b);
    return memcmp(a, b, sizeof a) == 0;
}

/* No output part was written (every part still poisoned) and the stats are all zero. One CHECK
 * per row (the GCC analyzer budget). */
static void require_untouched(const struct pl_batch_stats *st) {
    for (size_t i = 0; i < PL_TB_N; i++) {
        CHECK("untouched", i, untouched_row(tb_pooled + i));
    }
    const int pool = (st->threads_observed == 0u) & (st->max_inflight == 0u);
    CHECK("untouched-stats", 9u, (st->chunks == 0u) & pool);
    for (size_t m = 0; m < PL_MODELS; m++) {
        CHECK("untouched-stats", m, (*(st->calls + m) == 0u) & (*(st->evals + m) == 0u));
    }
}

/* Input refusals (each writes nothing). */
static void input_refusals(const struct pl_params *p, const struct pl_output *out,
                           struct pl_batch_stats *st) {
    struct pl_input in = pl_tb_rows_input(0u, PL_TB_N);
    REQUIRE(pl_tb_run(NULL, p, 0, 7u, 0u, out, st) == PL_BATCH_ARGUMENT);
    REQUIRE(pl_tb_run(&in, NULL, 1, 7u, 0u, out, st) == PL_BATCH_ARGUMENT);
    REQUIRE(pl_tb_run(&in, p, 0, 7u, 0u, NULL, st) == PL_BATCH_ARGUMENT);
    REQUIRE(pl_tb_run(&in, p, 0, 7u, 0u, out, NULL) == PL_BATCH_ARGUMENT);
    REQUIRE(pl_tb_run(&in, p, 0, 7u, UINT32_MAX, out, st) == PL_BATCH_ARGUMENT);
    struct pl_input bad = in;
    bad.rows = NULL;
    REQUIRE(pl_tb_run(&bad, p, 0, 7u, 0u, out, st) == PL_BATCH_ARGUMENT);
    bad.kind = PL_INPUT_WIRE;
    REQUIRE(pl_tb_run(&bad, p, 0, 7u, 0u, out, st) == PL_BATCH_ARGUMENT);
    struct pl_input c = {PL_INPUT_COLUMNS, 0u, PL_TB_N, NULL, NULL, {NULL}};
    pl_tb_set_columns(&c);
    *(c.columns + 7) = NULL;
    REQUIRE(pl_tb_run(&c, p, 0, 7u, 0u, out, st) == PL_BATCH_ARGUMENT);
    bad = in;
    bad.kind = 3;
    REQUIRE(pl_tb_run(&bad, p, 0, 7u, 0u, out, st) == PL_BATCH_ARGUMENT);
    bad.kind = -1;
    REQUIRE(pl_tb_run(&bad, p, 0, 7u, 0u, out, st) == PL_BATCH_ARGUMENT);
    bad = in;
    bad.base = PL_TB_BASE_MAX - PL_TB_N + 1u;
    REQUIRE(pl_tb_run(&bad, p, 0, 7u, 0u, out, st) == PL_BATCH_ARGUMENT);
}

/* Output and scratch refusals (each writes nothing). */
static void output_refusals(const struct pl_params *p, const struct pl_output *out,
                            struct pl_batch_stats *st) {
    struct pl_input in = pl_tb_rows_input(0u, PL_TB_N);
    struct pl_output ob = *out;
    ob.results = NULL;
    REQUIRE(pl_tb_run(&in, p, 0, 7u, 0u, &ob, st) == PL_BATCH_ARGUMENT);
    ob.kind = PL_OUTPUT_WIRE;
    REQUIRE(pl_tb_run(&in, p, 0, 7u, 0u, &ob, st) == PL_BATCH_ARGUMENT);
    ob = *out;
    ob.kind = 2;
    REQUIRE(pl_tb_run(&in, p, 0, 7u, 0u, &ob, st) == PL_BATCH_ARGUMENT);
    ob = *out;
    ob.base = PL_TB_BASE_MAX - PL_TB_N + 1u;
    REQUIRE(pl_tb_run(&in, p, 0, 7u, 0u, &ob, st) == PL_BATCH_ARGUMENT);
    const struct pl_batch_scratch s = {tb_perm, tb_mark, tb_idx, PL_TB_N};
    REQUIRE(pl_batch_run_untraced(&in, p, 0, 7u, 2u, 0u, NULL, out, st) == PL_BATCH_ARGUMENT);
    struct pl_batch_scratch sb = s;
    sb.perm = NULL;
    REQUIRE(pl_batch_run_untraced(&in, p, 0, 7u, 2u, 0u, &sb, out, st) == PL_BATCH_ARGUMENT);
    sb = s;
    sb.mark = NULL;
    REQUIRE(pl_batch_run_untraced(&in, p, 0, 7u, 2u, 0u, &sb, out, st) == PL_BATCH_ARGUMENT);
    sb = s;
    sb.indices = NULL;
    REQUIRE(pl_batch_run_untraced(&in, p, 0, 7u, 2u, 0u, &sb, out, st) == PL_BATCH_ARGUMENT);
}

/* Every argument refusal writes nothing; the exact base bound is accepted. */
static void refusals(const struct pl_params *p) {
    struct pl_output out = {PL_OUTPUT_RESULTS, 0u, tb_pooled, NULL};
    struct pl_batch_stats st = {0};
    pl_poison_results(tb_pooled, PL_TB_N);
    input_refusals(p, &out, &st);
    output_refusals(p, &out, &st);
    require_untouched(&st);
    /* n = 0 reads and writes nothing. */
    struct pl_input edge = pl_tb_rows_input(PL_TB_BASE_MAX, 0u);
    struct pl_output oe = out;
    oe.base = PL_TB_BASE_MAX;
    REQUIRE(pl_tb_run(&edge, p, 0, 7u, 0u, &oe, &st) == PL_BATCH_OK);
    struct pl_batch_scratch none = {NULL, NULL, NULL, 0u}; /* the serial loop reads no scratch */
    struct pl_input one = pl_tb_rows_input(1u, 1u);
    struct pl_output o1 = out;
    pl_poison_results(tb_pooled, PL_TB_N);
    REQUIRE(pl_batch_run_untraced(&one, p, 1, 7u, 0u, 0u, &none, &o1, &st) == PL_BATCH_OK);
    REQUIRE(pl_batch_run_untraced(&one, p, 1, 7u, 0u, 0u, NULL, &o1, &st) == PL_BATCH_OK);
    REQUIRE(tb_pooled->model->status == PL_ECHO && pl_tb_not_requested((tb_pooled + 1)->model));
}

int main(void) {
    pl_tb_load_synthetic();
    struct pl_params p;
    pl_case_params(&p);
    refusals(&p);
    puts("PASS limits");
    return 0;
}
