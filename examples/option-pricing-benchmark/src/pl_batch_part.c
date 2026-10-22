#include "pl_batch_core.h"
#include "pl_ieee.h"
#include "pl_types.h"
#include <stddef.h>
#include <stdint.h>

/* Part-level helpers of the batch loops (specs/project/batch.md "Batch", "Reduction", "Echo"):
 * a translation unit of their own, so that each call inside a loop of pl_batch.c and
 * pl_batch_row.c is opaque to the GCC analyzer. Straight-line code. */

void pl_echo_part(struct pl_model_result *part) {
    part->status = PL_ECHO;
    part->flags = 0u;
    *(part->values + 0) = pl_nan();
    *(part->values + 1) = pl_nan();
    *(part->values + 2) = pl_nan();
    *(part->values + 3) = pl_nan();
    *(part->values + 4) = pl_nan();
    *(part->values + 5) = pl_nan();
    *(part->values + 6) = pl_nan();
}

void pl_add_counters(uint64_t sum[PL_MODELS], const uint64_t add[PL_MODELS]) {
    *(sum + 0) += *(add + 0);
    *(sum + 1) += *(add + 1);
    *(sum + 2) += *(add + 2);
    *(sum + 3) += *(add + 3);
    *(sum + 4) += *(add + 4);
}

void pl_reduce_row(const struct pl_model_result *part, size_t i, uint64_t counts[9], int64_t *best,
                   double *best_iv) {
    const uint8_t s = part->status;
    if (s <= PL_OK) {
        *(counts + s) += 1u;
    }
    const double iv = *(part->values + PL_IV);
    if (s == PL_OK && (*best < 0 || iv > *best_iv)) {
        *best = (int64_t)i;
        *best_iv = iv;
    }
}

enum pl_eval_error pl_batch_chunk(const struct pl_input *in, const struct pl_params *p, int echo,
                                  uint16_t models, const struct pl_output *out,
                                  const uint32_t *indices, size_t count, uint64_t calls[PL_MODELS],
                                  uint64_t evals[PL_MODELS]) {
    for (size_t j = 0; j < count; j++) {
        const size_t i = (size_t)*(indices + j);
        if (pl_batch_one(in, p, echo, models, out, i, calls, evals) != PL_EVAL_OK) {
            return PL_EVAL_DEFECT;
        }
    }
    return PL_EVAL_OK;
}
