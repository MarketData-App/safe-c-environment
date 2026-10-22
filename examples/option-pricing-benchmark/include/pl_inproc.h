#pragma once
#include "pl_batch_core.h"
#include <stddef.h>
#include <stdint.h>

/* The in-process entry point of libpl_inproc.so (specs/project/inproc.md; ABI 2, Amendment G
 * G4.4 and Amendment I item I5.7). Every pointer is borrowed for the call only and nothing is
 * retained; no allocation and no static mutable state: the scratch is the caller's. This header
 * has no GLib (pl_batch_core.h has none either). */

#define PL_INPROC_ABI 2u

enum pl_inproc_status {
    PL_INPROC_OK = 0,
    PL_INPROC_ARGUMENT = 1,
    PL_INPROC_DEFECT = 2,
    PL_INPROC_POOL = 3
};

/* Returns PL_INPROC_ABI (2). Exported. */
uint32_t pl_inproc_abi_version(void);

/* pl_response_payload(n, threads): n * 290 + 4 + 16 k, k = 0 for threads 0, else min(threads, n).
 * Not exported. */
size_t pl_inproc_out_len(size_t n, uint32_t threads);

/* 9 n + 64: the partition scratch (perm 4 n bytes, indices 4 n bytes, mark n bytes), then the
 * 64-byte argument echo. Saturates at SIZE_MAX for n above (SIZE_MAX - 64) / 9. Not exported. */
size_t pl_inproc_scratch_len(size_t n);

/* The argument contract (src/pl_inproc_args.c). PL_INPROC_ARGUMENT for a NULL pointer, a column
 * or buffer address that is not a multiple of 8, n outside 1-14,336, threads above 4, models 0 or
 * above 31, out_len other than pl_inproc_out_len(n, threads), scratch_len other than 9 n + 64, or
 * any overlap between out, scratch and a column range (address intervals as uintptr_t with
 * overflow-checked ends; two columns may overlap each other, they are read only). Otherwise
 * PL_INPROC_OK. Nothing is read through a pointer and nothing is written. Not exported. */
int pl_inproc_check(const double *const *columns, size_t n, uint32_t threads, uint32_t models,
                    const uint8_t *out, size_t out_len, const uint8_t *scratch, size_t scratch_len);

/* ABI 2, 16 arguments. pl_inproc_check first (nothing written on PL_INPROC_ARGUMENT); then one
 * batch over the eight columns in place (side, S, K, T, bid, ask, r, q; a side value 0.0 is a
 * call, 1.0 a put, any other value is invalid) for the models mask with the wire output into out,
 * then the trailer after the n records. On success the eight column addresses are written as u64
 * little-endian into the last 64 bytes of scratch. Returns PL_INPROC_OK, PL_INPROC_ARGUMENT,
 * PL_INPROC_DEFECT (a run defect of a selected model, or a chunk count other than the trailer's)
 * or PL_INPROC_POOL. Every pool task has finished before the call returns. Exported. */
int pl_inproc_price(const double *side, const double *S, const double *K, const double *T,
                    const double *bid, const double *ask, const double *r, const double *q,
                    size_t n, uint32_t threads, uint32_t request_index, uint32_t models,
                    uint8_t *out, size_t out_len, uint8_t *scratch, size_t scratch_len);

/* The test hook of ruling 31: pl_inproc_price with the G4.8 counters of the batch in *stats
 * (nullable). Not exported; pl_inproc_price wraps it. */
int pl_inproc_price_stats(const double *side, const double *S, const double *K, const double *T,
                          const double *bid, const double *ask, const double *r, const double *q,
                          size_t n, uint32_t threads, uint32_t request_index, uint32_t models,
                          uint8_t *out, size_t out_len, uint8_t *scratch, size_t scratch_len,
                          struct pl_batch_stats *stats);
