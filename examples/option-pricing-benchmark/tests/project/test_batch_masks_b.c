#define PL_TEST_VECTOR_ROWS
#define PL_TEST_BATCH_MASKS
#include "pl_test_batch.h"
#include "pl_vec_batch_rows.h"

/* The masks 6-10 of the batch on the 48 rows, serial and with two workers, by pl_tb_masks (the mask
 * group of test_batch_masks.c, split for the 10 s test timeout of the coverage build: T9-A01). The
 * baseline rows and their status checks are the same as in test_batch_masks.c. REQUIRE stays
 * active under NDEBUG. */

static struct pl_batch_stats wired;

int main(void) {
    PL_TB_LOAD_VECTOR_ROWS();
    pl_tb_baseline(&wired);
    REQUIRE((tb_serial + 7)->model->status == PL_INVALID_INPUT);
    REQUIRE((tb_serial + 23)->model->status == PL_EXPIRED);
    pl_tb_masks(PL_TB_N, 6u, 10u, &wired);
    puts("PASS masks 6-10");
    return 0;
}
