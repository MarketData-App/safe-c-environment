#define PL_TEST_VECTOR_ROWS
#define PL_TEST_BATCH_ALO
#include "pl_test_batch.h"

/* The input kinds of the batch with the ALO part (specs/project/batch.md "Batch"; controller
 * ruling R-10b-B1): on the representative ALO subset of PL_VEC_BATCH_ALO, rows, wire and columns
 * give the same wire bytes under PL_MASK_WIRED, serial and with two workers (test_batch_kinds.c
 * checks the 48 rows under PL_TB_MASK_FULL; ruling (g): a file of its own for the 10 s test
 * timeout of the coverage build). REQUIRE stays active under NDEBUG. */

static uint8_t wire_serial[PL_TB_N * PL_RESPONSE_RECORD_BYTES];
static uint8_t wire_out[PL_TB_N * PL_RESPONSE_RECORD_BYTES];

int main(void) {
    pl_tb_load_alo_rows();
    pl_tb_alo_baseline(NULL);
    struct pl_params p;
    pl_case_params(&p);
    const size_t n = PL_TB_ALO_N;
    struct pl_input rows_in = {PL_INPUT_ROWS, 0u, n, tb_rows, NULL, {NULL}};
    struct pl_input wire = {PL_INPUT_WIRE, 0u, n, NULL, tb_wire_in, {NULL}};
    struct pl_input columns = {PL_INPUT_COLUMNS, 0u, n, NULL, NULL, {NULL}};
    pl_tb_set_columns(&columns);
    struct pl_output ws = {PL_OUTPUT_WIRE, 0u, NULL, wire_serial};
    struct pl_output wo = {PL_OUTPUT_WIRE, 0u, NULL, wire_out};
    struct pl_batch_stats st = {0};
    REQUIRE(pl_tb_run(&rows_in, &p, 0, PL_MASK_WIRED, 0u, &ws, &st) == PL_BATCH_OK);
    uint8_t rec[PL_RESPONSE_RECORD_BYTES];
    int same = 1;
    for (size_t k = 0; k < n; k++) { /* the serial wire bytes are the serial results */
        pl_response_encode(tb_serial + k, rec);
        same &= memcmp(rec, wire_serial + k * PL_RESPONSE_RECORD_BYTES, sizeof rec) == 0;
    }
    REQUIRE(same);
    const struct pl_input *kinds[2] = {&wire, &columns};
    const size_t bytes = n * PL_RESPONSE_RECORD_BYTES;
    for (size_t k = 0; k < 2u; k++) {
        for (unsigned t = 0u; t <= 2u; t += 2u) {
            struct pl_batch_stats s2 = {0};
            int ok = pl_tb_run(*(kinds + k), &p, 0, PL_MASK_WIRED, t, &wo, &s2) == PL_BATCH_OK;
            ok &= memcmp(wire_out, wire_serial, bytes) == 0;
            CHECK("alo-input-kinds", 4u * k + t, ok);
        }
    }
    puts("PASS alo-input-kinds");
    return 0;
}
