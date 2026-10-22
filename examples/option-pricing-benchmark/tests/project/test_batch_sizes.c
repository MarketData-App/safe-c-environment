#include "pl_test_batch.h"

/* The chunk-count bound of pl_batch_run (specs/project/batch.md "Batch"): stats->chunks + w <=
 * PL_MAX_CHUNKS; and the tie rule of pl_reduce ("Reduction", group tie: synthetic results, moved
 * from test_batch.c for the AST dump size of that file). A file of its own: the fixed GCC
 * analyzer budget of one translation unit. The 48 rows are synthetic. REQUIRE stays active under
 * NDEBUG. */

/* The chunk-count bound: stats->chunks + w <= PL_MAX_CHUNKS. */
static void chunk_bound(const struct pl_params *p) {
    struct pl_input in = pl_tb_rows_input(0u, 4u);
    struct pl_output out = pl_tb_pooled_output();
    struct pl_batch_stats st = {0};
    st.chunks = PL_MAX_CHUNKS;
    REQUIRE(pl_tb_run(&in, p, 1, 7u, 1u, &out, &st) == PL_BATCH_ARGUMENT);
    REQUIRE(pl_tb_run(&in, p, 1, 7u, 0u, &out, &st) == PL_BATCH_OK);
    st.chunks = PL_MAX_CHUNKS + 1u;
    REQUIRE(pl_tb_run(&in, p, 1, 7u, 0u, &out, &st) == PL_BATCH_ARGUMENT);
    st.chunks = PL_MAX_CHUNKS - 3u; /* 5 + 4 = 9 */
    REQUIRE(pl_tb_run(&in, p, 1, 7u, 4u, &out, &st) == PL_BATCH_ARGUMENT);
    st.chunks = PL_MAX_CHUNKS - 4u; /* 4 + 4 = 8 */
    REQUIRE(pl_tb_run(&in, p, 1, 7u, 4u, &out, &st) == PL_BATCH_OK);
    REQUIRE(st.chunks == PL_MAX_CHUNKS);
    st.chunks = PL_MAX_CHUNKS - 1u; /* n = 1: w = 1, 7 + 1 = 8 */
    struct pl_input one = pl_tb_rows_input(0u, 1u);
    REQUIRE(pl_tb_run(&one, p, 1, 7u, 4u, &out, &st) == PL_BATCH_OK);
    REQUIRE(st.chunks == PL_MAX_CHUNKS && *(st.chunk_sizes + PL_MAX_CHUNKS - 1u) == 1u);
}

/* 1 when the nine status counts are 0 (early return: the GCC analyzer budget). */
static int zero_counts(const uint64_t *c) {
    for (size_t k = 0; k < 9u; k++) {
        if (*(c + k) != 0u) {
            return 0;
        }
    }
    return 1;
}

/* Sets part m of result i to status OK with the IV iv. */
static void set_ok(struct pl_contract_result *r, size_t i, size_t m, double iv) {
    ((r + i)->model + m)->status = PL_OK;
    *(((r + i)->model + m)->values) = iv;
}

static void tie(void) {
    struct pl_contract_result r[4];
    pl_poison_results(r, 4u);
    set_ok(r, 0u, 0u, 0.25);
    set_ok(r, 1u, 0u, 0.5);
    set_ok(r, 3u, 0u, 0.5); /* equal IV: the lower index 1 wins */
    set_ok(r, 1u, 1u, 0.5);
    set_ok(r, 2u, 1u, 0x1.0000000000001p-1); /* one ulp above: the later index wins */
    struct pl_reduction red;
    pl_reduce(r, 4u, 3u, &red);
    REQUIRE(*(red.max_iv_index + 0) == 1 && *(red.max_iv + 0) == 0.5);
    REQUIRE(*(red.max_iv_index + 1) == 2 && *(red.max_iv + 1) == 0x1.0000000000001p-1);
    REQUIRE(*(*(red.counts + 0) + PL_OK) == 3u && *(*(red.counts + 1) + PL_OK) == 2u);
    /* Status 254 is not counted; the unselected models stay zero. */
    REQUIRE(*(*(red.counts + 0) + PL_INVALID_INPUT) == 0u);
    int ok = 1;
    for (size_t m = 2u; m < PL_MODELS; m++) {
        ok &= zero_counts(*(red.counts + m));
        ok &= *(red.max_iv_index + m) == 0;
        ok &= pl_double_bits(*(red.max_iv + m)) == 0u;
    }
    REQUIRE(ok);
    puts("PASS tie");
}

int main(void) {
    pl_tb_load_synthetic();
    struct pl_params p;
    pl_case_params(&p);
    chunk_bound(&p);
    puts("PASS sizes");
    tie();
    return 0;
}
