#define PL_TEST_VECTOR_ROWS
#include "pl_test_batch.h"
#include "pl_vec_batch_rows.h"
#include "pl_vec_evaluate.h"

/* Tests of pl_batch.c and pl_batch_row.c (specs/project/batch.md "Batch"; Amendment G items G1.5,
 * G4.8): the serial results of the 48 rows equal the vector entries, and the pooled results with 1,
 * 2, 3 and 4 workers are byte-identical to them. The 48 rows are the synthetic prefix of
 * PL_VEC_EVALUATE (three entries per row: bsm, bjs, crr). The input kinds are checked in
 * test_batch_kinds.c, echo, reduction and argument refusals in test_batch_echo.c (each a file of
 * its own: the AST dump size of a file with the generated evaluate header), the BAW entries in
 * test_batch_baw.c, the masks and the trap row in test_batch_masks.c and test_batch_trap.c, the
 * limits in test_batch_limits.c and the five files after it, the trace in test_batch_stats.c, the
 * tie rule of pl_reduce in test_batch_sizes.c. REQUIRE stays active under NDEBUG. */

static uint64_t wired_calls[PL_MODELS], wired_evals[PL_MODELS];

/* The serial results equal the vector entries; the counters equal the vector counts (H17). */
static void serial_matches_vectors(const struct pl_batch_stats *st) {
    uint64_t e0 = 0u, e1 = 0u, e2 = 0u;
    int ok = 1;
    for (size_t i = ZERO; i < PL_TB_N; i++) { /* ZERO: a long loop */
        const struct pl_vec_evaluate *v = PL_VEC_EVALUATE + PL_VEC_EVALUATE_PER_ROW * i;
        const struct pl_model_result *r = (tb_serial + i)->model;
        ok &= PL_TB_SAME_AS_VECTOR(r, v) & PL_TB_SAME_AS_VECTOR(r + 1, v + 1);
        ok &= PL_TB_SAME_AS_VECTOR(r + 2, v + 2);
        e0 += (uint64_t)v->engine_evals;
        e1 += (uint64_t)(v + 1)->engine_evals;
        e2 += (uint64_t)(v + 2)->engine_evals;
    }
    REQUIRE(ok);
    REQUIRE(*(st->evals + 0) == e0 && *(st->evals + 1) == e1 && *(st->evals + 2) == e2);
    for (size_t m = 0; m < PL_MODELS; m++) {
        const uint64_t wired = (PL_TB_MASK_FULL >> m) & 1u;
        ok &= *(st->calls + m) == wired * PL_TB_N;
        *(wired_calls + m) = *(st->calls + m);
        *(wired_evals + m) = *(st->evals + m);
    }
    REQUIRE(ok);
}

static void serial_and_pooled_agree(void) {
    struct pl_params p;
    pl_case_params(&p);
    struct pl_input in = {PL_INPUT_ROWS, 0u, PL_TB_N, tb_rows, NULL, {NULL}};
    struct pl_output out = {PL_OUTPUT_RESULTS, 0u, tb_serial, NULL};
    struct pl_batch_stats st = {0};
    const int rc = pl_tb_run(&in, &p, 0, PL_TB_MASK_FULL, 0u, &out, &st);
    REQUIRE(rc == PL_BATCH_OK && st.chunks == 0u);
    serial_matches_vectors(&st);
    const unsigned workers[4] = {1u, 2u, 3u, 4u};
    for (size_t w = ZERO; w < 4u; w++) { /* ZERO: the GCC analyzer budget */
        const unsigned t = *(workers + w);
        struct pl_output po = {PL_OUTPUT_RESULTS, 0u, tb_pooled, NULL};
        struct pl_batch_stats ps = {0};
        pl_poison_results(tb_pooled, PL_TB_N);
        int ok = pl_tb_run(&in, &p, 0, PL_TB_MASK_FULL, t, &po, &ps) == PL_BATCH_OK;
        ok &= (ps.chunks == t) & pl_tb_same_results(tb_serial, tb_pooled, PL_TB_N);
        size_t total = 0u;
        for (size_t k = 0; k < ps.chunks && k < PL_MAX_CHUNKS; k++) {
            total += *(ps.chunk_sizes + k);
            ok &= *(ps.chunk_wall_ns + k) > 0u;
        }
        ok &= (total == PL_TB_N) & (ps.max_inflight <= 2u * t);
        ok &= (ps.threads_observed >= 1u) & (ps.threads_observed <= t);
        for (size_t m = ZERO; m < PL_MODELS; m++) {
            ok &= *(ps.calls + m) == *(wired_calls + m);
            ok &= *(ps.evals + m) == *(wired_evals + m);
        }
        CHECK("serial-pooled", t, ok);
    }
    puts("PASS serial-pooled");
}

int main(void) {
    PL_TB_LOAD_VECTOR_ROWS();
    serial_and_pooled_agree();
    return 0;
}
