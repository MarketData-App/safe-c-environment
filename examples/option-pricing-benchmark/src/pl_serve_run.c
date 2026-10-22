#define _GNU_SOURCE

#include "pl_batch_core.h"
#include "pl_crr.h"
#include "pl_partition.h"
#include "pl_protocol.h"
#include "pl_serve.h"
#include "pl_types.h"
#include <stddef.h>
#include <stdint.h>

/* The batch of one request of pl-worker (specs/project/serve.md "Request: route stdio"): a
 * translation unit of its own, so that the call inside the serve loop is opaque to the GCC
 * analyzer (the fixed analyzer budget of the framework; the same reason as in batch.md). The
 * partition scratch is static: one call at a time. */

static uint32_t pl_perm[PL_REQUEST_LIMIT];
static uint32_t pl_indices[PL_REQUEST_LIMIT];
static uint8_t pl_mark[PL_REQUEST_LIMIT];

/* The chunk count k of a request: 0 when threads is 0, else min(threads, count). */
static size_t pl_chunk_count(uint32_t count, uint16_t threads) {
    if (threads == 0u) {
        return 0u;
    }
    return threads < count ? (size_t)threads : (size_t)count;
}

enum pl_proto_error pl_serve_compute(const struct pl_serve_options *o, const struct pl_header *h,
                                     const uint8_t *wire, uint8_t *out, size_t *produced) {
    *produced = 0u;
    const size_t n = h->record_count;
    const size_t k = pl_chunk_count(h->record_count, h->threads);
    struct pl_batch_stats stats = {0};
    if (n > 0u) {
        struct pl_params p;
        pl_case_params(&p);
        const struct pl_input in = {PL_INPUT_WIRE, 0u, n, NULL, wire, {NULL}};
        const struct pl_output so = {PL_OUTPUT_WIRE, 0u, NULL, out};
        const struct pl_batch_scratch sc = {pl_perm, pl_mark, pl_indices, PL_REQUEST_LIMIT};
        const uint64_t request_index = (uint32_t)h->request_id;
        const int rc = pl_batch_run_untraced(&in, &p, o->echo, h->models, h->threads, request_index,
                                             &sc, &so, &stats);
        if (rc != PL_BATCH_OK || stats.chunks != k) {
            return PL_PROTO_KERNEL_FAILURE;
        }
    }
    pl_trailer_encode(out + n * PL_RESPONSE_RECORD_BYTES, k, stats.chunk_sizes,
                      stats.chunk_wall_ns);
    if (o->calls != NULL && o->evals != NULL) {
        pl_add_counters(o->calls, stats.calls);
        pl_add_counters(o->evals, stats.evals);
    }
    *produced = pl_response_payload(h->record_count, h->threads);
    return PL_PROTO_OK;
}
