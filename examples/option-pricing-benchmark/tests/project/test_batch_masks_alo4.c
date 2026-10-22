#define PL_TEST_VECTOR_ROWS
#define PL_TEST_BATCH_MASKS
#define PL_TEST_BATCH_ALO
#include "pl_test_batch.h"

/* The masks 28-31 of the batch (the ALO bit with baw and crr) on the representative ALO subset of
 * PL_VEC_BATCH_ALO, serial and with two workers, by pl_tb_masks against the PL_MASK_WIRED serial
 * results of the subset (controller ruling R-10b-B1; ruling (g): the masks 16-31 are split over
 * test_batch_masks_alo1.c to test_batch_masks_alo4.c for the 10 s test timeout of the coverage
 * build). REQUIRE stays active under NDEBUG. */

static struct pl_batch_stats wired;

int main(void) {
    pl_tb_load_alo_rows();
    pl_tb_alo_baseline(&wired);
    pl_tb_masks(PL_TB_ALO_N, 28u, 31u, &wired);
    puts("PASS masks-alo 28-31");
    return 0;
}
