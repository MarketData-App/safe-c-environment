#define PL_TEST_VECTOR_ROWS
#include "pl_test_batch.h"
#include "pl_vec_batch_rows.h"

/* The input kinds of the batch (specs/project/batch.md "Batch"): rows, wire and columns give the
 * same wire bytes, serial and with two workers, on the 48 rows of test_batch.c (the synthetic
 * prefix of PL_VEC_EVALUATE, with its INVALID_INPUT and EXPIRED rows); the column side values.
 * A file of its own: the AST dump size limit of the ast gate (each file with the generated
 * evaluate header). REQUIRE stays active under NDEBUG. */

static uint8_t wire_serial[PL_TB_N * PL_RESPONSE_RECORD_BYTES];
static uint8_t wire_out[PL_TB_N * PL_RESPONSE_RECORD_BYTES];

/* A column side value decodes like the wire side: 0.0 and -0.0 -> 0, 1.0 -> 1, else -1. */
static void column_sides(void) {
    const double sides[5] = {0.0, 1.0, 2.0, -0.0, pl_nan()};
    const int want[5] = {0, 1, -1, 0, -1};
    const double one[1] = {1.0};
    int ok = 1;
    for (size_t k = 0; k < 5u; k++) {
        const double side_column[1] = {*(sides + k)};
        struct pl_input c1 = {PL_INPUT_COLUMNS, 0u, 1u, NULL, NULL, {NULL}};
        *(c1.columns + 0) = side_column;
        *(c1.columns + 1) = one;
        *(c1.columns + 2) = one;
        *(c1.columns + 3) = one;
        *(c1.columns + 4) = one;
        *(c1.columns + 5) = one;
        *(c1.columns + 6) = one;
        *(c1.columns + 7) = one;
        struct pl_row row;
        pl_input_row(&c1, 0u, &row);
        ok &= (row.side == *(want + k)) & (row.S == 1.0) & (row.q == 1.0);
    }
    REQUIRE(ok);
}

static void every_input_kind_gives_the_same_wire_bytes(void) {
    struct pl_params p;
    pl_case_params(&p);
    struct pl_input rows_in = {PL_INPUT_ROWS, 0u, PL_TB_N, tb_rows, NULL, {NULL}};
    struct pl_input wire = {PL_INPUT_WIRE, 0u, PL_TB_N, NULL, tb_wire_in, {NULL}};
    struct pl_input columns = {PL_INPUT_COLUMNS, 0u, PL_TB_N, NULL, NULL, {NULL}};
    pl_tb_set_columns(&columns);
    struct pl_output ws = {PL_OUTPUT_WIRE, 0u, NULL, wire_serial};
    struct pl_output wo = {PL_OUTPUT_WIRE, 0u, NULL, wire_out};
    struct pl_batch_stats st = {0};
    REQUIRE(pl_tb_run(&rows_in, &p, 0, PL_TB_MASK_FULL, 0u, &ws, &st) == PL_BATCH_OK);
    const struct pl_input *kinds[2] = {&wire, &columns};
    for (size_t k = 0; k < 2u; k++) {
        for (unsigned t = 0u; t <= 2u; t += 2u) {
            struct pl_batch_stats s2 = {0};
            int ok = pl_tb_run(*(kinds + k), &p, 0, PL_TB_MASK_FULL, t, &wo, &s2) == PL_BATCH_OK;
            ok &= memcmp(wire_out, wire_serial, sizeof wire_out) == 0;
            CHECK("input-kinds", 4u * k + t, ok);
        }
    }
    column_sides();
    puts("PASS input-kinds");
}

int main(void) {
    PL_TB_LOAD_VECTOR_ROWS();
    every_input_kind_gives_the_same_wire_bytes();
    return 0;
}
