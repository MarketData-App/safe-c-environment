#include "pl_test_batch.h"

/* The request limit and the row helpers (specs/project/batch.md "Batch"): n = 14,336 (four
 * chunks of 3,584) and 14,337 (refused); the NULL and unknown arguments of pl_evaluate_contract
 * and the row helpers. A file of its own: the fixed GCC analyzer budget of one translation unit.
 * The 48 rows are synthetic. REQUIRE stays active under NDEBUG. */

#define BIG 14336u

static struct pl_contract_result big_out[BIG + 1u];
static uint8_t big_wire[(BIG + 1u) * PL_REQUEST_RECORD_BYTES];
static uint32_t big_perm[BIG], big_idx[BIG];
static uint8_t big_mark[BIG];

/* n = 14,336 (four chunks of 3,584) and 14,337 (refused). */
static void request_limit(const struct pl_params *p) {
    struct pl_batch_scratch big = {big_perm, big_mark, big_idx, BIG};
    struct pl_input in = {PL_INPUT_WIRE, 0u, BIG, NULL, big_wire, {NULL}};
    struct pl_output bo = {PL_OUTPUT_RESULTS, 0u, big_out, NULL};
    struct pl_batch_stats st = {0};
    pl_poison_results(big_out, BIG + 1u);
    REQUIRE(pl_batch_run_untraced(&in, p, 1, 7u, 4u, 0u, &big, &bo, &st) == PL_BATCH_OK);
    const size_t *z = st.chunk_sizes;
    REQUIRE(st.chunks == 4u && *z == 3584u && *(z + 1) == 3584u);
    REQUIRE(*(z + 2) == 3584u && *(z + 3) == 3584u);
    int echo = 1;
    for (size_t i = ZERO; i < BIG; i++) { /* ZERO: a long loop */
        echo &= ((big_out + i)->model + 2)->status == PL_ECHO;
    }
    REQUIRE(echo);
    REQUIRE(pl_tb_not_requested((big_out + BIG)->model + 2)); /* position 14,336 is not written */
    in.n = BIG + 1u;
    struct pl_batch_stats s2 = {0};
    REQUIRE(pl_batch_run_untraced(&in, p, 1, 7u, 0u, 0u, &big, &bo, &s2) == PL_BATCH_ARGUMENT);
}

/* pl_evaluate_contract with NULL arguments and masks 0 and 32. */
static void contract_arguments(const struct pl_params *p) {
    struct pl_contract_result r;
    uint64_t calls[PL_MODELS] = {0u, 0u, 0u, 0u, 0u};
    uint64_t evals[PL_MODELS] = {0u, 0u, 0u, 0u, 0u};
    REQUIRE(pl_evaluate_contract(tb_rows, p, 0u, &r, calls, evals) == PL_EVAL_DEFECT);
    REQUIRE(pl_evaluate_contract(tb_rows, p, 32u, &r, calls, evals) == PL_EVAL_DEFECT);
    REQUIRE(pl_evaluate_contract(NULL, p, 1u, &r, calls, evals) == PL_EVAL_DEFECT);
    REQUIRE(pl_evaluate_contract(tb_rows, NULL, 1u, &r, calls, evals) == PL_EVAL_DEFECT);
    REQUIRE(pl_evaluate_contract(tb_rows, p, 1u, NULL, calls, evals) == PL_EVAL_DEFECT);
    REQUIRE(pl_evaluate_contract(tb_rows, p, 1u, &r, NULL, evals) == PL_EVAL_DEFECT);
    REQUIRE(pl_evaluate_contract(tb_rows, p, 1u, &r, calls, NULL) == PL_EVAL_DEFECT);
    REQUIRE(*(calls + 0) == 0u && *(evals + 0) == 0u);
    REQUIRE(pl_evaluate_contract(tb_rows + 1, p, 1u, &r, calls, evals) == PL_EVAL_OK);
    REQUIRE(*(calls + 0) == 1u && *(calls + 1) == 0u);
    struct pl_model_result direct;
    uint32_t direct_evals = 0u;
    REQUIRE(pl_evaluate(tb_rows + 1, PL_MODEL_BSM, p, &direct, &direct_evals) == PL_EVAL_OK);
    REQUIRE(*(evals + 0) == (uint64_t)direct_evals); /* the evaluator's own count */
    REQUIRE(pl_tb_not_requested(r.model + 1) && pl_tb_not_requested(r.model + 4));
}

/* The row helpers with NULL and unknown arguments. */
static void helpers(void) {
    struct pl_row row = {0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0};
    pl_input_row(NULL, 0u, &row);
    REQUIRE(row.side == -1 && pl_is_nan(row.S) && pl_is_nan(row.q));
    struct pl_input unknown = pl_tb_rows_input(0u, 1u);
    unknown.kind = 7;
    row.side = 0;
    pl_input_row(&unknown, 0u, &row);
    REQUIRE(row.side == -1 && pl_is_nan(row.K));
    pl_input_row(&unknown, 0u, NULL);
    pl_poison_results(tb_pooled, 1u);
    struct pl_output out = {PL_OUTPUT_RESULTS, 0u, tb_pooled, NULL};
    pl_output_store(&out, 0u, NULL);
    pl_output_store(NULL, 0u, tb_serial);
    out.kind = 9;
    pl_output_store(&out, 0u, tb_serial);
    REQUIRE(pl_tb_not_requested(tb_pooled->model));
    pl_poison_results(NULL, 3u);
    struct pl_contract_result r;
    pl_evaluate_contract_echo(1u, NULL);
    pl_evaluate_contract_echo(0u, &r);
    REQUIRE(pl_tb_not_requested(r.model + 0) && pl_tb_not_requested(r.model + 4));
    struct pl_reduction red;
    pl_reduce(NULL, 3u, 1u, &red);
    REQUIRE(*(red.max_iv_index) == -1 && **red.counts == 0u);
    pl_reduce(tb_serial, PL_TB_N, 1u, NULL);
}

int main(void) {
    pl_tb_load_synthetic();
    pl_tb_baseline(NULL);
    struct pl_params p;
    pl_case_params(&p);
    request_limit(&p);
    contract_arguments(&p);
    helpers();
    puts("PASS helpers");
    return 0;
}
