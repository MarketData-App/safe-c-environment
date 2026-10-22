#define PL_TEST_VECTOR_ROWS
#define PL_TEST_BATCH_ALO
#include "pl_batch.h"
#include "pl_test_batch.h"

/* The statistics and the trace of pl_batch_run with the ALO part (specs/project/batch.md "Batch";
 * controller ruling R-10b-B1) on the representative ALO subset of PL_VEC_BATCH_ALO under
 * PL_MASK_WIRED: two requests append their chunks (4 + 4 = 8 entries), their counters equal the
 * serial counters, the trace holds one entry per task, request index 1 gives the same bytes, and
 * one row (alo-put-ok, row 2) with two workers equals its serial record (test_batch_stats.c checks
 * the 48 rows under PL_TB_MASK_FULL; ruling (g): a file of its own for the 10 s test timeout of
 * the coverage build). REQUIRE stays active under NDEBUG. */

static struct pl_batch_stats wired;

static void stats(void) {
    struct pl_params p;
    pl_case_params(&p);
    const size_t n = PL_TB_ALO_N;
    const size_t half = n / 2u;
    struct pl_batch_scratch s = {tb_perm, tb_mark, tb_idx, PL_TB_N};
    struct pl_output out = pl_tb_pooled_output();
    struct pl_batch_stats st = {0};
    ScParallelTraceEntry entries[PL_MAX_CHUNKS];
    pl_poison_results(tb_pooled, PL_TB_N);
    for (size_t r = 0; r < 2u; r++) {
        const size_t base = r * half;
        struct pl_input in = pl_tb_rows_input(base, (r == 0u) ? half : n - half);
        out.base = base;
        ScParallelTrace trace = {entries + st.chunks, PL_MAX_CHUNKS - st.chunks, 0u};
        const int rc = pl_batch_run(&in, &p, 0, PL_MASK_WIRED, 4u, r, &s, &out, &st, &trace);
        CHECK("alo-stats", r, (rc == PL_BATCH_OK) & (trace.used == 4u));
    }
    REQUIRE(st.chunks == PL_MAX_CHUNKS && pl_tb_same_results(tb_serial, tb_pooled, n));
    size_t total = 0u;
    int ok = 1;
    for (size_t k = 0; k < PL_MAX_CHUNKS; k++) {
        const ScParallelTraceEntry *e = entries + k;
        total += *(st.chunk_sizes + k);
        ok &= (e->thread_tag < 4u) & (e->start_ns >= 0) & (e->end_ns >= e->start_ns);
    }
    for (size_t m = 0; m < PL_MODELS; m++) {
        ok &= (*(st.calls + m) == *(wired.calls + m)) & (*(st.evals + m) == *(wired.evals + m));
    }
    REQUIRE(ok && total == n);
    struct pl_input all = pl_tb_rows_input(0u, n);
    struct pl_batch_stats s1 = {0};
    out.base = 0u;
    pl_poison_results(tb_pooled, PL_TB_N);
    const int r1 = pl_batch_run_untraced(&all, &p, 0, PL_MASK_WIRED, 4u, 1u, &s, &out, &s1);
    REQUIRE(r1 == PL_BATCH_OK);
    REQUIRE(pl_tb_same_results(tb_serial, tb_pooled, n));
    puts("PASS alo-stats");
}

/* One row with two workers: the record equals the serial record; its neighbours stay poisoned. */
static void one_row(void) {
    struct pl_params p;
    pl_case_params(&p);
    struct pl_input one = pl_tb_rows_input(2u, 1u);
    struct pl_output o2 = {PL_OUTPUT_RESULTS, 2u, tb_pooled, NULL};
    struct pl_batch_stats s1 = {0};
    pl_poison_results(tb_pooled, PL_TB_N);
    REQUIRE(pl_tb_run(&one, &p, 0, PL_MASK_WIRED, 2u, &o2, &s1) == PL_BATCH_OK);
    REQUIRE((s1.chunks == 1u) & pl_tb_same_results(tb_serial + 2, tb_pooled + 2, 1u));
    REQUIRE(*(s1.calls + PL_MODEL_ALO) == 1u);
    REQUIRE(*(s1.evals + PL_MODEL_ALO) == (uint64_t)(PL_VEC_BATCH_ALO + 2)->engine_evals);
    REQUIRE(pl_tb_not_requested((tb_pooled + 1)->model));
    REQUIRE(pl_tb_not_requested((tb_pooled + 3)->model));
    puts("PASS alo-one-row");
}

int main(void) {
    pl_tb_load_alo_rows();
    pl_tb_alo_baseline(&wired);
    stats();
    one_row();
    return 0;
}
