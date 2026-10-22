#define PL_TEST_VECTOR_ROWS
#define PL_TEST_BATCH_MASKS
#include "pl_test_batch.h"
#include "pl_vec_batch_rows.h"

/* The mask group of the batch on the 48 rows (specs/project/batch.md "Batch"; Amendment G items
 * G1.6, G4.8; Amendment I item I13.3 Task 14; ruling 46): every mask within PL_TB_MASK_FULL (1-15),
 * serial and with two workers, by pl_tb_masks (the trap row is in test_batch_trap.c). The 48 rows
 * are the synthetic prefix of PL_VEC_EVALUATE. The masks 1-15 are split over test_batch_masks.c
 * (1-5), test_batch_masks_b.c (6-10) and test_batch_masks_c.c (11-15): the coverage build runs the
 * group about 1.9 times slower with atomic profile updates and the 10 s test timeout failed in
 * three runs (T9-A01); the assertions and the mask range are unchanged. The masks with the ALO bit
 * (16-31) run on the subset of PL_VEC_BATCH_ALO in test_batch_masks_alo1.c to
 * test_batch_masks_alo4.c (controller ruling R-10b-B1: one ALO run of the 48 rows takes about 5 s
 * in the coverage build; ruling (g): four files for the 10 s test timeout). REQUIRE stays active
 * under NDEBUG. */

static struct pl_batch_stats wired;

int main(void) {
    PL_TB_LOAD_VECTOR_ROWS();
    pl_tb_baseline(&wired);
    REQUIRE((tb_serial + 7)->model->status == PL_INVALID_INPUT);
    REQUIRE((tb_serial + 23)->model->status == PL_EXPIRED);
    pl_tb_masks(PL_TB_N, 1u, 5u, &wired);
    puts("PASS masks 1-5");
    return 0;
}
