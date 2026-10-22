#pragma once
#include "pl_batch.h"
#include "pl_kernel_cli.h"
#include "pl_scan.h"
#include "pl_types.h"
#include <sc-parallel.h>
#include <stddef.h>
#include <stdint.h>

/* The run parts of pl-kernel (specs/project/batch.md "pl-kernel command line"): the buffers, the
 * run state and one loop. A header of its own, so that the parser and the
 * command-line tests do not include GLib (the memory of the source-policy step of the ast
 * gate). */

/* The static buffers of pl-kernel (owned by src/pl_kernel_run.c; borrowed by the loop). */
struct pl_kernel_bufs {
    uint8_t *input;
    struct pl_contract_result *results;
    uint8_t *probe_out;
    uint32_t *perm;
    uint8_t *mark;
    uint32_t *indices;
    ScParallelTraceEntry *trace;
};

/* The measured state of one run. */
struct pl_kernel_state {
    struct pl_batch_stats stats;
    struct pl_scan_totals scan;
    size_t trace_used;
    uint64_t mono_ns;
    uint64_t cpu_ns;
    size_t copied;
};

/* One loop of the case (src/pl_kernel_loop.c): option case (poison, reset, requests r = 0, 1),
 * record-scan or probe. Returns an enum pl_kernel_reason. */
int pl_kernel_loop(const struct pl_kernel_args *a, const struct pl_params *p,
                   const struct pl_kernel_bufs *b, struct pl_kernel_state *s);
