#pragma once
#include "pl_batch_core.h"
#include <sc-parallel.h>
#include <stdint.h>

/* The batch run with the sc_parallel trace (specs/project/batch.md "Batch"); every type and
 * the other functions of the batch are in pl_batch_core.h, which this header includes. */

/* One request (specs/project/batch.md "Batch"): threads 0 is the serial loop; threads 1-4 run
 * one sc_parallel task per Amendment E chunk of request_index with the window 2 threads.
 * PL_BATCH_ARGUMENT before any write; PL_BATCH_DEFECT at a run defect of a selected model;
 * PL_BATCH_POOL for any other adapter failure. trace is nullable. */
int pl_batch_run(const struct pl_input *in, const struct pl_params *p, int echo, uint16_t models,
                 unsigned threads, uint64_t request_index, const struct pl_batch_scratch *scratch,
                 const struct pl_output *out, struct pl_batch_stats *stats, ScParallelTrace *trace);
