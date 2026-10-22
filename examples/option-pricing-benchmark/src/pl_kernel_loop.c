#include "pl_batch.h"
#include "pl_kernel_cli.h"
#include "pl_kernel_run.h"
#include "pl_partition.h"
#include "pl_protocol.h"
#include "pl_scan.h"
#include <sc-parallel.h>
#include <stddef.h>
#include <stdint.h>

/* One timed loop of pl-kernel (specs/project/batch.md "pl-kernel command line"): a translation
 * unit of its own, so that the call inside the loop of src/pl_kernel_run.c is opaque to the GCC
 * analyzer. */

/* Request r of the option case: rows [r 14,336, min(n, (r + 1) 14,336)). */
static int pl_option_request(const struct pl_kernel_args *a, const struct pl_params *p,
                             const struct pl_kernel_bufs *b, struct pl_kernel_state *s, size_t r) {
    const struct pl_batch_scratch sc = {b->perm, b->mark, b->indices, PL_REQUEST_LIMIT};
    const size_t base = r * PL_REQUEST_LIMIT;
    const size_t left = a->records - base;
    const size_t m = left < PL_REQUEST_LIMIT ? left : PL_REQUEST_LIMIT;
    const struct pl_input in = {PL_INPUT_WIRE, base, m, NULL, b->input, {NULL}};
    const struct pl_output out = {PL_OUTPUT_RESULTS, base, b->results, NULL};
    const size_t at = s->stats.chunks;
    ScParallelTrace trace = {b->trace + at, PL_MAX_CHUNKS - at, 0u};
    ScParallelTrace *t = a->threads > 0u ? &trace : NULL;
    struct pl_batch_stats *st = &s->stats;
    const int rc = pl_batch_run(&in, p, a->echo, a->models, a->threads, r, &sc, &out, st, t);
    s->trace_used += trace.used;
    return rc == PL_BATCH_OK ? PL_REASON_OK : PL_REASON_KERNEL;
}

/* One loop of the option case: poison, reset, then requests r = 0, 1. */
static int pl_option_loop(const struct pl_kernel_args *a, const struct pl_params *p,
                          const struct pl_kernel_bufs *b, struct pl_kernel_state *s) {
    const struct pl_batch_stats zero = {0};
    pl_poison_results(b->results, a->records);
    s->stats = zero;
    s->trace_used = 0u;
    int reason = pl_option_request(a, p, b, s, 0u);
    if (reason == PL_REASON_OK && a->records > PL_REQUEST_LIMIT) {
        reason = pl_option_request(a, p, b, s, 1u);
    }
    return reason;
}

int pl_kernel_loop(const struct pl_kernel_args *a, const struct pl_params *p,
                   const struct pl_kernel_bufs *b, struct pl_kernel_state *s) {
    if (a->kase == PL_CASE_OPTION) {
        return pl_option_loop(a, p, b, s);
    }
    if (a->kase == PL_CASE_SCAN) {
        const size_t len = a->records * PL_SCAN_RECORD_BYTES;
        const int rc = pl_scan(b->input, len, a->dte_min, a->dte_max, a->lo, a->hi, &s->scan);
        return rc == 0 ? PL_REASON_OK : PL_REASON_KERNEL;
    }
    for (size_t i = 0; i < a->records; i++) {
        const uint8_t *rec = b->input + i * PL_PROBE_IN_BYTES;
        pl_probe_record(rec, p, b->probe_out + i * PL_PROBE_OUT_BYTES);
    }
    return PL_REASON_OK;
}
