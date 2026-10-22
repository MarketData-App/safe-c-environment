#pragma once
#include "pl_partition.h"
#include "pl_types.h"
#include <stddef.h>
#include <stdint.h>

/* The batch core of the C pricer (specs/project/batch.md "Batch", "Reduction", "Echo"): one
 * request of at most PL_REQUEST_LIMIT rows from rows, wire records or columns, evaluated for the
 * models of a mask, serially or in one sc_parallel task per Amendment E chunk, into results or
 * wire records. No allocation and no global state: the caller owns every array. This header has
 * no GLib: pl_batch.h includes it and adds pl_batch_run with its ScParallelTrace argument; every
 * other translation unit includes this header only (the memory of the source-policy step of the
 * ast gate). */

enum pl_input_kind { PL_INPUT_ROWS = 0, PL_INPUT_WIRE = 1, PL_INPUT_COLUMNS = 2 };

/* Row i of the request is input position base + i. columns: side, S, K, T, bid, ask, r, q; a
 * column side value decodes like the wire side (0.0 -> 0, 1.0 -> 1, any other value -> -1). */
struct pl_input {
    int kind;
    size_t base;
    size_t n;
    const struct pl_row *rows;
    const uint8_t *wire;
    const double *columns[8];
};

enum pl_output_kind { PL_OUTPUT_RESULTS = 0, PL_OUTPUT_WIRE = 1 };

/* Row i of the request is stored at output position base + i. */
struct pl_output {
    int kind;
    size_t base;
    struct pl_contract_result *results;
    uint8_t *wire;
};

/* The partition scratch of a pooled run: perm, mark and indices hold cap elements each. */
struct pl_batch_scratch {
    uint32_t *perm;
    uint8_t *mark;
    uint32_t *indices;
    size_t cap;
};

/* Appended by every pooled request (chunks, chunk_sizes, chunk_wall_ns, threads_observed,
 * max_inflight) and by every request (calls: calls of pl_evaluate per model; evals: the sum of
 * its engine_evals per model; both 0 for an unselected model; G4.8, ruling 31). */
struct pl_batch_stats {
    size_t chunks;
    size_t chunk_sizes[PL_MAX_CHUNKS];
    uint64_t chunk_wall_ns[PL_MAX_CHUNKS];
    unsigned threads_observed;
    size_t max_inflight;
    uint64_t calls[PL_MODELS];
    uint64_t evals[PL_MODELS];
};

enum pl_batch_error {
    PL_BATCH_OK = 0,
    PL_BATCH_ARGUMENT = 1,
    PL_BATCH_DEFECT = 2,
    PL_BATCH_POOL = 3
};

/* *out = the row at input position in->base + i. A NULL argument or an unknown kind gives side
 * -1 and NaN fields (when out is not NULL). */
void pl_input_row(const struct pl_input *in, size_t i, struct pl_row *out);

/* Stores *r at output position out->base + i (a result or a 290-byte wire record). A NULL
 * argument or an unknown kind writes nothing. */
void pl_output_store(const struct pl_output *out, size_t i, const struct pl_contract_result *r);

/* G4.6: status 255, flags 0 and NaN values in each selected part (models & 31); the
 * NOT_REQUESTED content in each unselected part. A NULL out writes nothing. */
void pl_evaluate_contract_echo(uint16_t models, struct pl_contract_result *out);

/* Every part of *out gets the NOT_REQUESTED content; then each selected model in MODELS5 order:
 * calls[m] += 1, pl_evaluate, evals[m] += engine_evals. pl_evaluate is never called for an
 * unselected model. PL_EVAL_DEFECT at the first defect of a selected model (the later ones are
 * not evaluated), or with no write for a NULL argument or models outside 1-31. */
enum pl_eval_error pl_evaluate_contract(const struct pl_row *row, const struct pl_params *p,
                                        uint16_t models, struct pl_contract_result *out,
                                        uint64_t calls[PL_MODELS], uint64_t evals[PL_MODELS]);

/* Status 254, flags 0 and seven 0x7FF8000000000000 values in every part of r[0 .. n-1]: the
 * NOT_REQUESTED content. A NULL r writes nothing. */
void pl_poison_results(struct pl_contract_result *r, size_t n);

/* reference.reduction for each selected model of models & 31 (G1.5): status counts 0-8, the
 * largest IV of an OK row and its lowest index (-1 and NaN without an OK row). The entries of an
 * unselected model are 0. */
struct pl_reduction {
    uint16_t models;
    uint64_t counts[PL_MODELS][9];
    double max_iv[PL_MODELS];
    int64_t max_iv_index[PL_MODELS];
};

void pl_reduce(const struct pl_contract_result *r, size_t n, uint16_t models,
               struct pl_reduction *red);

/* Helpers of the batch loops in their own translation units, so that each call inside a loop is
 * opaque to the GCC analyzer (the fixed analyzer budget of the framework). */

/* Row i of a request: pl_input_row, then the echo parts or pl_evaluate_contract with the counters
 * calls and evals, then pl_output_store. PL_EVAL_DEFECT at a run defect (nothing stored). */
enum pl_eval_error pl_batch_one(const struct pl_input *in, const struct pl_params *p, int echo,
                                uint16_t models, const struct pl_output *out, size_t i,
                                uint64_t calls[PL_MODELS], uint64_t evals[PL_MODELS]);

/* The rows indices[0 .. count-1] of a request through pl_batch_one, in this order
 * (src/pl_batch_part.c). PL_EVAL_DEFECT at the first run defect (the later rows are not
 * evaluated). */
enum pl_eval_error pl_batch_chunk(const struct pl_input *in, const struct pl_params *p, int echo,
                                  uint16_t models, const struct pl_output *out,
                                  const uint32_t *indices, size_t count, uint64_t calls[PL_MODELS],
                                  uint64_t evals[PL_MODELS]);

/* Status 255, flags 0 and seven NaN values (src/pl_batch_part.c). */
void pl_echo_part(struct pl_model_result *part);

/* sum[m] += add[m] for the five models (src/pl_batch_part.c). */
void pl_add_counters(uint64_t sum[PL_MODELS], const uint64_t add[PL_MODELS]);

/* One row of reference.reduction for one model (src/pl_batch_part.c): counts[status] += 1 for a
 * status 0-8; an OK part replaces (*best, *best_iv) when *best < 0 or its IV is strictly greater
 * (the lowest index wins a tie). */
void pl_reduce_row(const struct pl_model_result *part, size_t i, uint64_t counts[9], int64_t *best,
                   double *best_iv);

/* pl_batch_run (pl_batch.h) without a trace: the same checks and results. */
int pl_batch_run_untraced(const struct pl_input *in, const struct pl_params *p, int echo,
                          uint16_t models, unsigned threads, uint64_t request_index,
                          const struct pl_batch_scratch *scratch, const struct pl_output *out,
                          struct pl_batch_stats *stats);
