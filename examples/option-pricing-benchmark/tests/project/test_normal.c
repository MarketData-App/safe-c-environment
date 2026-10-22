#include "pl_ieee.h"
#include "pl_normal.h"
#include "pl_vec_normal.h"
#include <stdio.h>

/* Bit-exact comparison with optionlab.normal (specs/project/models.md "Normal distribution"). */
static size_t failures;

static void same(const char *group, size_t index, double got, uint64_t want) {
    int both_nan = pl_is_nan(got) && pl_is_nan(pl_bits_double(want));
    if (pl_double_bits(got) != want && !both_nan) {
        if (failures < 8u) {
            printf("FAIL %s %zu\n", group, index);
        }
        failures++;
    }
}

int main(void) {
    for (size_t i = 0; i < PL_VEC_NORMAL_COUNT; i++) {
        const struct pl_vec_normal *v = PL_VEC_NORMAL + i;
        double x = pl_bits_double(v->x);
        same("erf", i, pl_erf(x), v->erf);
        same("pdf", i, pl_norm_pdf(x), v->pdf);
        same("cdf", i, pl_norm_cdf(x), v->cdf);
    }
    printf("%s normal %zu\n", failures == 0u ? "PASS" : "FAIL", failures);
    return failures == 0u ? 0 : 1;
}
