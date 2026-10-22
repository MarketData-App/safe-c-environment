#include "pl_batch_core.h"
#include "pl_evaluate.h"
#include "pl_ieee.h"
#include "pl_protocol.h"
#include <stddef.h>
#include <stdint.h>

/* The row helpers of the batch (specs/project/batch.md "Batch", "Reduction", "Echo"). */

/* A column side value decodes like the wire side (pl_request_decode). */
static int pl_side_of(double v) {
    if (v == 0.0) {
        return 0;
    }
    return v == 1.0 ? 1 : -1;
}

static void pl_row_unknown(struct pl_row *out) {
    out->side = -1;
    out->S = pl_nan();
    out->K = pl_nan();
    out->T = pl_nan();
    out->bid = pl_nan();
    out->ask = pl_nan();
    out->r = pl_nan();
    out->q = pl_nan();
}

static void pl_row_of_columns(const struct pl_input *in, size_t at, struct pl_row *out) {
    out->side = pl_side_of(*(*(in->columns + 0) + at));
    out->S = *(*(in->columns + 1) + at);
    out->K = *(*(in->columns + 2) + at);
    out->T = *(*(in->columns + 3) + at);
    out->bid = *(*(in->columns + 4) + at);
    out->ask = *(*(in->columns + 5) + at);
    out->r = *(*(in->columns + 6) + at);
    out->q = *(*(in->columns + 7) + at);
}

void pl_input_row(const struct pl_input *in, size_t i, struct pl_row *out) {
    if (out == NULL) {
        return;
    }
    if (in == NULL) {
        pl_row_unknown(out);
        return;
    }
    const size_t at = in->base + i;
    if (in->kind == PL_INPUT_ROWS) {
        *out = *(in->rows + at);
    } else if (in->kind == PL_INPUT_WIRE) {
        pl_request_decode(in->wire + at * PL_REQUEST_RECORD_BYTES, out);
    } else if (in->kind == PL_INPUT_COLUMNS) {
        pl_row_of_columns(in, at, out);
    } else {
        pl_row_unknown(out);
    }
}

void pl_output_store(const struct pl_output *out, size_t i, const struct pl_contract_result *r) {
    if (out == NULL || r == NULL) {
        return;
    }
    const size_t at = out->base + i;
    if (out->kind == PL_OUTPUT_RESULTS) {
        *(out->results + at) = *r;
    } else if (out->kind == PL_OUTPUT_WIRE) {
        pl_response_encode(r, out->wire + at * PL_RESPONSE_RECORD_BYTES);
    }
}

void pl_evaluate_contract_echo(uint16_t models, struct pl_contract_result *out) {
    if (out == NULL) {
        return;
    }
    for (size_t m = 0; m < PL_MODELS; m++) {
        if (((unsigned)models >> m) & 1u) {
            pl_echo_part(out->model + m);
        } else {
            pl_result_not_requested(out->model + m);
        }
    }
}

enum pl_eval_error pl_evaluate_contract(const struct pl_row *row, const struct pl_params *p,
                                        uint16_t models, struct pl_contract_result *out,
                                        uint64_t calls[PL_MODELS], uint64_t evals[PL_MODELS]) {
    if (row == NULL || p == NULL || out == NULL || calls == NULL || evals == NULL) {
        return PL_EVAL_DEFECT;
    }
    if (models == 0u || models > PL_MASK_MODELS5) {
        return PL_EVAL_DEFECT;
    }
    for (size_t m = 0; m < PL_MODELS; m++) {
        pl_result_not_requested(out->model + m);
    }
    for (size_t m = 0; m < PL_MODELS; m++) {
        if ((((unsigned)models >> m) & 1u) == 0u) {
            continue; /* an unselected model is never evaluated (G1, G4.8) */
        }
        uint32_t e = 0u;
        *(calls + m) += 1u;
        const enum pl_eval_error rc = pl_evaluate(row, (int)m, p, out->model + m, &e);
        *(evals + m) += e;
        if (rc != PL_EVAL_OK) {
            return PL_EVAL_DEFECT;
        }
    }
    return PL_EVAL_OK;
}

enum pl_eval_error pl_batch_one(const struct pl_input *in, const struct pl_params *p, int echo,
                                uint16_t models, const struct pl_output *out, size_t i,
                                uint64_t calls[PL_MODELS], uint64_t evals[PL_MODELS]) {
    struct pl_row row;
    struct pl_contract_result r;
    pl_input_row(in, i, &row);
    if (echo) {
        pl_evaluate_contract_echo(models, &r);
    } else if (pl_evaluate_contract(&row, p, models, &r, calls, evals) != PL_EVAL_OK) {
        return PL_EVAL_DEFECT;
    }
    pl_output_store(out, i, &r);
    return PL_EVAL_OK;
}

void pl_poison_results(struct pl_contract_result *r, size_t n) {
    if (r == NULL) {
        return;
    }
    for (size_t i = 0; i < n; i++) {
        struct pl_model_result *part = (r + i)->model;
        pl_result_not_requested(part + 0);
        pl_result_not_requested(part + 1);
        pl_result_not_requested(part + 2);
        pl_result_not_requested(part + 3);
        pl_result_not_requested(part + 4);
    }
}

/* reference.reduction (reference.py:279-297) of model m: the status counts (0-8) and the lowest
 * index of the largest OK IV (pl_reduce_row). */
static void pl_reduce_model(const struct pl_contract_result *r, size_t n, size_t m,
                            struct pl_reduction *red) {
    int64_t best = -1;
    double best_iv = pl_nan();
    for (size_t i = 0; i < n; i++) {
        pl_reduce_row((r + i)->model + m, i, *(red->counts + m), &best, &best_iv);
    }
    *(red->max_iv_index + m) = best;
    *(red->max_iv + m) = best_iv;
}

void pl_reduce(const struct pl_contract_result *r, size_t n, uint16_t models,
               struct pl_reduction *red) {
    if (red == NULL) {
        return;
    }
    const struct pl_reduction zero = {0};
    *red = zero;
    const size_t rows = r == NULL ? 0u : n;
    red->models = (uint16_t)(models & PL_MASK_MODELS5);
    for (size_t m = 0; m < PL_MODELS; m++) {
        if (((unsigned)red->models >> m) & 1u) {
            pl_reduce_model(r, rows, m, red);
        }
    }
}
