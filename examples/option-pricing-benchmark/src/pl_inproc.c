#define _GNU_SOURCE

#include "pl_inproc.h"
#include "pl_batch_core.h"
#include "pl_crr.h"
#include "pl_partition.h"
#include "pl_protocol.h"
#include "pl_types.h"
#include <stddef.h>
#include <stdint.h>

/* The in-process entry of libpl_inproc.so (specs/project/inproc.md): the argument contract
 * (src/pl_inproc_args.c), one batch over the caller's columns in place, the trailer and the
 * argument echo. No allocation and no static mutable state: the scratch is the caller's (perm 4 n
 * bytes, indices 4 n bytes, mark n bytes, in this order, then the 64-byte echo). The AST policy
 * refuses array subscripts, so an element is read as *(p + i). */

/* The chunk count k of the trailer: 0 when threads is 0, else min(threads, n). */
static size_t pl_inproc_chunks(size_t n, uint32_t threads) {
    if (threads == 0u) {
        return 0u;
    }
    return (size_t)threads < n ? (size_t)threads : n;
}

/* The address of a column as the u64 of the argument echo. */
static uint64_t pl_inproc_address(const double *p) { return (uint64_t)(uintptr_t)p; }

/* Stores the eight column addresses as u64 little-endian at echo (64 writable bytes). */
static void pl_inproc_echo(uint8_t *echo, const double *const *columns) {
    pl_store_u64(echo, pl_inproc_address(*(columns + 0)));
    pl_store_u64(echo + 8, pl_inproc_address(*(columns + 1)));
    pl_store_u64(echo + 16, pl_inproc_address(*(columns + 2)));
    pl_store_u64(echo + 24, pl_inproc_address(*(columns + 3)));
    pl_store_u64(echo + 32, pl_inproc_address(*(columns + 4)));
    pl_store_u64(echo + 40, pl_inproc_address(*(columns + 5)));
    pl_store_u64(echo + 48, pl_inproc_address(*(columns + 6)));
    pl_store_u64(echo + 56, pl_inproc_address(*(columns + 7)));
}

/* The batch over the eight columns into out; the scratch arrays are carved from scratch (8-byte
 * aligned by the check, so every uint32 array is 4-byte aligned). Returns the batch result. */
static int pl_inproc_batch(const double *const *columns, size_t n, uint32_t threads,
                           uint32_t request_index, uint32_t models, uint8_t *out, uint8_t *scratch,
                           struct pl_batch_stats *stats) {
    struct pl_params p;
    pl_case_params(&p);
    struct pl_input in = {PL_INPUT_COLUMNS, 0u, n, NULL, NULL, {NULL}};
    *(in.columns + 0) = *(columns + 0);
    *(in.columns + 1) = *(columns + 1);
    *(in.columns + 2) = *(columns + 2);
    *(in.columns + 3) = *(columns + 3);
    *(in.columns + 4) = *(columns + 4);
    *(in.columns + 5) = *(columns + 5);
    *(in.columns + 6) = *(columns + 6);
    *(in.columns + 7) = *(columns + 7);
    const struct pl_output so = {PL_OUTPUT_WIRE, 0u, NULL, out};
    void *perm = scratch;
    void *indices = scratch + 4u * n;
    const struct pl_batch_scratch sc = {perm, scratch + 8u * n, indices, n};
    return pl_batch_run_untraced(&in, &p, 0, (uint16_t)models, threads, request_index, &sc, &so,
                                 stats);
}

int pl_inproc_price_stats(const double *side, const double *S, const double *K, const double *T,
                          const double *bid, const double *ask, const double *r, const double *q,
                          size_t n, uint32_t threads, uint32_t request_index, uint32_t models,
                          uint8_t *out, size_t out_len, uint8_t *scratch, size_t scratch_len,
                          struct pl_batch_stats *stats) {
    const double *const columns[8] = {side, S, K, T, bid, ask, r, q};
    if (pl_inproc_check(columns, n, threads, models, out, out_len, scratch, scratch_len) !=
        PL_INPROC_OK) {
        return PL_INPROC_ARGUMENT;
    }
    struct pl_batch_stats local;
    struct pl_batch_stats *st = stats != NULL ? stats : &local;
    const struct pl_batch_stats zero = {0};
    *st = zero;
    const int rc = pl_inproc_batch(columns, n, threads, request_index, models, out, scratch, st);
    const size_t k = pl_inproc_chunks(n, threads);
    if (rc != PL_BATCH_OK) {
        return rc;
    }
    if (st->chunks != k) {
        return PL_INPROC_DEFECT;
    }
    pl_trailer_encode(out + n * PL_RESPONSE_RECORD_BYTES, k, st->chunk_sizes, st->chunk_wall_ns);
    pl_inproc_echo(scratch + 9u * n, columns);
    return PL_INPROC_OK;
}

int pl_inproc_price(const double *side, const double *S, const double *K, const double *T,
                    const double *bid, const double *ask, const double *r, const double *q,
                    size_t n, uint32_t threads, uint32_t request_index, uint32_t models,
                    uint8_t *out, size_t out_len, uint8_t *scratch, size_t scratch_len) {
    return pl_inproc_price_stats(side, S, K, T, bid, ask, r, q, n, threads, request_index, models,
                                 out, out_len, scratch, scratch_len, NULL);
}
