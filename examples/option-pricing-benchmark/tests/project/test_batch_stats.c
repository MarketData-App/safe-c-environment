#include "pl_batch.h"
#include "pl_test_batch.h"

/* The statistics and the trace of pl_batch_run (specs/project/batch.md "Batch"): two requests
 * append their chunks (4 + 4 = 8 entries), the counters of the pooled requests equal the serial
 * counters, the trace holds one entry per task, and request index 1 gives the same bytes. A file
 * of its own (it includes GLib through pl_batch.h, test_batch.c includes the large generated
 * vector header: the AST dump size). The 48 rows are synthetic. REQUIRE stays active under
 * NDEBUG. */

static struct pl_batch_stats wired;

/* Two requests append their chunks; request index 1 gives the same output; the trace. */
static void stats(void) {
    struct pl_params p;
    pl_case_params(&p);
    struct pl_batch_scratch s = {tb_perm, tb_mark, tb_idx, PL_TB_N};
    struct pl_output out = pl_tb_pooled_output();
    struct pl_batch_stats st = {0};
    ScParallelTraceEntry entries[PL_MAX_CHUNKS];
    pl_poison_results(tb_pooled, PL_TB_N);
    for (size_t r = 0; r < 2u; r++) {
        struct pl_input in = pl_tb_rows_input(r * (PL_TB_N / 2u), PL_TB_N / 2u);
        out.base = r * (PL_TB_N / 2u);
        ScParallelTrace trace = {entries + st.chunks, PL_MAX_CHUNKS - st.chunks, 0u};
        const int rc = pl_batch_run(&in, &p, 0, PL_TB_MASK_FULL, 4u, r, &s, &out, &st, &trace);
        CHECK("stats", r, (rc == PL_BATCH_OK) & (trace.used == 4u));
    }
    REQUIRE(st.chunks == PL_MAX_CHUNKS && pl_tb_same_results(tb_serial, tb_pooled, PL_TB_N));
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
    REQUIRE(ok && total == PL_TB_N);
    /* Request index 1: other chunks, same bytes. */
    struct pl_input all = pl_tb_rows_input(0u, PL_TB_N);
    struct pl_batch_stats s1 = {0};
    out.base = 0u;
    pl_poison_results(tb_pooled, PL_TB_N);
    const int r1 = pl_batch_run_untraced(&all, &p, 0, PL_TB_MASK_FULL, 4u, 1u, &s, &out, &s1);
    REQUIRE(r1 == PL_BATCH_OK);
    REQUIRE(pl_tb_same_results(tb_serial, tb_pooled, PL_TB_N));
    puts("PASS stats");
}

int main(void) {
    pl_tb_load_synthetic();
    pl_tb_baseline(&wired);
    stats();
    return 0;
}
