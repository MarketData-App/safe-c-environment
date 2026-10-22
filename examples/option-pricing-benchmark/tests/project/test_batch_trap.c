#define PL_TEST_VECTOR_ROWS
#include "pl_test_batch.h"
#include "pl_vec_batch_rows.h"
#include "pl_vec_evaluate.h"

/* The trap row of the batch (specs/project/batch.md "Batch"; Amendment G item G4.8): the row
 * RAISE_ROWS[5] (bsm entry without a defect, crr entry a run defect) succeeds with mask 1 and
 * fails with masks 4 and 7, serial and with two workers. Also: table batch_rows (the rows of the
 * batch tests) holds the rows of the first 144 entries of table evaluate. A file of its own: the
 * fixed GCC analyzer budget of one translation unit. REQUIRE stays active under NDEBUG. */

/* 1 when the row b has the side and the seven field bit patterns of the vector entry v (integer
 * comparisons of the table fields, branch-free: the fixed GCC analyzer budget). */
static int same_row(const struct pl_vec_batch_rows *b, const struct pl_vec_evaluate *v) {
    const int s = (b->side == v->side) & (b->S == v->S) & (b->K == v->K) & (b->T == v->T);
    return s & (b->bid == v->bid) & (b->ask == v->ask) & (b->r == v->r) & (b->q == v->q);
}

/* Row k of PL_VEC_BATCH_ROWS is the row of entries 3k, 3k + 1 and 3k + 2 of PL_VEC_EVALUATE, which
 * are bsm, bjs and crr without a defect (the synthetic prefix). */
static void prefix(void) {
    REQUIRE(PL_VEC_EVALUATE_COUNT >= PL_VEC_EVALUATE_PER_ROW * PL_VEC_BATCH_ROWS_COUNT);
    int ok = 1;
    for (size_t k = ZERO; k < PL_VEC_BATCH_ROWS_COUNT; k++) {
        const struct pl_vec_batch_rows *b = PL_VEC_BATCH_ROWS + k;
        const struct pl_vec_evaluate *v = PL_VEC_EVALUATE + PL_VEC_EVALUATE_PER_ROW * k;
        const int rows = same_row(b, v) & same_row(b, v + 1) & same_row(b, v + 2);
        const int models = (v->model == 0) & ((v + 1)->model == 1) & ((v + 2)->model == 2);
        const int defects = (v->defect == 0) & ((v + 1)->defect == 0) & ((v + 2)->defect == 0);
        ok &= rows & models & defects;
    }
    REQUIRE(ok);
    puts("PASS prefix");
}

/* The trap rows with t workers: mask 1 succeeds without a crr call, masks 4 and 7 fail. */
static void trap_once(const struct pl_input *in, const struct pl_params *p,
                      const struct pl_vec_evaluate *v, unsigned t) {
    struct pl_output out = {PL_OUTPUT_RESULTS, 0u, tb_pooled, NULL};
    struct pl_batch_stats st = {0};
    REQUIRE(pl_tb_run(in, p, 0, 1u, t, &out, &st) == PL_BATCH_OK);
    REQUIRE(*(st.calls + 2) == 0u && *(st.calls + 0) == 3u && *(st.evals + 2) == 0u);
    REQUIRE(PL_TB_SAME_AS_VECTOR((tb_pooled + 1)->model, v));
    REQUIRE(pl_tb_not_requested((tb_pooled + 1)->model + 2));
    struct pl_batch_stats s4 = {0}, s7 = {0};
    REQUIRE(pl_tb_run(in, p, 0, 4u, t, &out, &s4) == PL_BATCH_DEFECT);
    REQUIRE(pl_tb_run(in, p, 0, 7u, t, &out, &s7) == PL_BATCH_DEFECT);
    REQUIRE(*(s4.calls + 2) >= 1u && *(s4.calls + 0) == 0u);
}

/* The trap row (RAISE_ROWS[5]): bsm entry without a defect, crr entry a run defect. */
static void trap(void) {
    size_t found = PL_VEC_EVALUATE_COUNT;
    for (size_t i = ZERO; i + 2u < PL_VEC_EVALUATE_COUNT; i += PL_VEC_EVALUATE_PER_ROW) {
        const struct pl_vec_evaluate *w = PL_VEC_EVALUATE + i;
        if (w->defect == 0 && (w + 2)->defect == 1) {
            found = i; /* the first trap row ends the search */
            break;
        }
    }
    REQUIRE(found < PL_VEC_EVALUATE_COUNT);
    const struct pl_vec_evaluate *v = PL_VEC_EVALUATE + found;
    const struct pl_row three[3] = {*(tb_rows + 1), PL_TB_VEC_ROW(v), *(tb_rows + 2)};
    struct pl_params p;
    pl_case_params(&p);
    struct pl_input in = {PL_INPUT_ROWS, 0u, 3u, three, NULL, {NULL}};
    trap_once(&in, &p, v, 0u);
    trap_once(&in, &p, v, 2u);
    puts("PASS trap");
}

int main(void) {
    prefix();
    PL_TB_LOAD_VECTOR_ROWS();
    trap();
    return 0;
}
