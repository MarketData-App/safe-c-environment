#include "pl_test_batch.h"

/* The small sizes of pl_batch_run (specs/project/batch.md "Batch"): n = 0, 1 and 48 with
 * threads 2 and 3 (threads 0 and 1 in test_batch_small.c, 4 in test_batch_wide.c). A file of its
 * own: the fixed GCC analyzer budget of one translation unit. The 48 rows are synthetic. REQUIRE
 * stays active under NDEBUG. */

int main(void) {
    pl_tb_load_synthetic();
    pl_tb_baseline(NULL);
    struct pl_params p;
    pl_case_params(&p);
    pl_tb_small_size(&p, 2u);
    pl_tb_small_size(&p, 3u);
    puts("PASS threads");
    return 0;
}
