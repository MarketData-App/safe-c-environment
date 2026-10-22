#pragma once
#include "pl_batch_core.h"
#include "pl_crr.h"
#include "pl_evaluate.h"
#include "pl_ieee.h"
#include "pl_inproc.h"
#include "pl_partition.h"
#include "pl_protocol.h"
#include "pl_types.h"
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* The helpers of the in-process entry test (tests/project/test_inproc.c; specs/project/inproc.md).
 * Test code only: no source file includes this header. Three framework limits shape it, as they
 * shaped the batch and serve tests. (1) The fixed GCC analyzer budget of one translation unit
 * (exploded nodes per supernode) counts a helper function again at each call site, and a loop
 * whose body calls only library functions (and ti_call) is cheap, so the test repeats a step in a
 * loop over a table and keeps its helpers few and small. (2) The AST policy (the ast gate)
 * refuses array subscripts and memset/memcpy outside inventoried boundaries: an element is read as
 * *(p + i) and a buffer is copied or cleared by assigning a struct. (3) The AST dump of a project
 * translation unit has a size limit, and a macro expansion costs far more AST than a plain
 * statement, so a macro holds only the failure branch. The rows are synthetic. */

#define TI_N 8u
#define TI_OUT_CAP 2400u
#define TI_SCRATCH_CAP 136u
#define TI_OUT_SENTINEL 0xA5u
#define TI_SCRATCH_SENTINEL 0x5Au
#define TI_INDEX 7u

/* An opaque zero (pl_request_count(0) in another translation unit): the loops start from it, so
 * that the GCC analyzer widens them instead of unrolling them over constant bounds. */
#define ZERO pl_request_count(0u)

/* REQUIRE stays active under NDEBUG: a failed condition prints the line and the condition text and
 * ends the test. CASE does the same for a case i of a table or a loop. The failure path calls
 * library functions only. */
#define REQUIRE_FAIL(c)                                                                            \
    ((void)fprintf(stderr, "test_inproc.c:%d: REQUIRE %s\n", __LINE__, #c), exit(1))
#define REQUIRE(c) ((c) ? (void)0 : REQUIRE_FAIL(c))
#define CASE_FAIL(i, c)                                                                            \
    ((void)fprintf(stderr, "test_inproc.c:%d: case %zu: %s\n", __LINE__, (size_t)(i), #c), exit(1))
#define CASE(i, c) ((c) ? (void)0 : CASE_FAIL(i, c))

/* Buffers are structs, so that a copy or a clear is an assignment. */
struct ti_out_buf {
    _Alignas(8) uint8_t b[TI_OUT_CAP];
};

struct ti_scratch_buf {
    _Alignas(8) uint8_t b[TI_SCRATCH_CAP];
};

static struct ti_out_buf ti_out_s;
static struct ti_out_buf ti_out2_s;
static struct ti_out_buf ti_ref_s;
static struct ti_scratch_buf ti_scratch_s;
static struct ti_scratch_buf ti_scratch2_s;
static const struct ti_out_buf ti_zero_out = {{0}};
static struct ti_out_buf ti_sentinel_out;
static struct ti_scratch_buf ti_sentinel_scratch;
#define ti_out (ti_out_s.b)
#define ti_out2 (ti_out2_s.b)
#define ti_ref (ti_ref_s.b)
#define ti_scratch (ti_scratch_s.b)
#define ti_scratch2 (ti_scratch2_s.b)

/* The eight columns (column c at ti_cols + c * TI_N), the rows and the batch scratch. */
static double ti_cols[8u * TI_N];
static struct pl_row ti_rows[TI_N];
static uint32_t ti_perm[TI_N];
static uint32_t ti_idx[TI_N];
static uint8_t ti_mark[TI_N];
#define TI_COL(c) (ti_cols + (c) * TI_N)

/* The 16 arguments of pl_inproc_price. */
struct ti_args {
    const double *col[8];
    size_t n;
    uint32_t threads, request, models;
    uint8_t *out;
    size_t out_len;
    uint8_t *scratch;
    size_t scratch_len;
};

/* The sentinel images (every byte of ti_out 0xA5, of ti_scratch 0x5A), written once. */
static inline void ti_init_sentinels(void) {
    for (size_t i = ZERO; i < TI_OUT_CAP; i++) {
        *(ti_sentinel_out.b + i) = (uint8_t)TI_OUT_SENTINEL;
    }
    for (size_t i = ZERO; i < TI_SCRATCH_CAP; i++) {
        *(ti_sentinel_scratch.b + i) = (uint8_t)TI_SCRATCH_SENTINEL;
    }
}

/* Row k: a call or a put, strike 76 + k, maturity (k + 1) / 52, quotes around a plausible price;
 * the eight columns hold the same values (the side as 0.0 or 1.0). */
static inline void ti_row(size_t k) {
    const double x = (double)k;
    struct pl_row r;
    r.side = (int)(k % 2u);
    r.S = 100.0;
    r.K = 76.0 + x;
    r.T = (x + 1.0) / 52.0;
    r.bid = 2.0 + 0.25 * x;
    r.ask = 2.5 + 0.25 * x;
    r.r = 0.04;
    r.q = 0.012;
    *(ti_rows + k) = r;
    *(TI_COL(0u) + k) = (double)r.side;
    *(TI_COL(1u) + k) = r.S;
    *(TI_COL(2u) + k) = r.K;
    *(TI_COL(3u) + k) = r.T;
    *(TI_COL(4u) + k) = r.bid;
    *(TI_COL(5u) + k) = r.ask;
    *(TI_COL(6u) + k) = r.r;
    *(TI_COL(7u) + k) = r.q;
}

static inline void ti_load2(void) {
    ti_row(0u);
    ti_row(1u);
}

static inline void ti_load8(void) {
    ti_load2();
    ti_row(2u);
    ti_row(3u);
    ti_row(4u);
    ti_row(5u);
    ti_row(6u);
    ti_row(7u);
}

/* Sets *a to a valid call of n rows over the eight columns, ti_out and ti_scratch. */
static inline void ti_set_args(struct ti_args *a, size_t n, uint32_t threads, uint32_t models) {
    *(a->col + 0) = TI_COL(0u);
    *(a->col + 1) = TI_COL(1u);
    *(a->col + 2) = TI_COL(2u);
    *(a->col + 3) = TI_COL(3u);
    *(a->col + 4) = TI_COL(4u);
    *(a->col + 5) = TI_COL(5u);
    *(a->col + 6) = TI_COL(6u);
    *(a->col + 7) = TI_COL(7u);
    a->n = n;
    a->threads = threads;
    a->request = TI_INDEX;
    a->models = models;
    a->out = ti_out;
    a->out_len = pl_inproc_out_len(n, threads);
    a->scratch = ti_scratch;
    a->scratch_len = pl_inproc_scratch_len(n);
}

/* pl_inproc_price_stats over the arguments a (stats nullable). */
static inline int ti_call(const struct ti_args *a, struct pl_batch_stats *st) {
    return pl_inproc_price_stats(*(a->col + 0), *(a->col + 1), *(a->col + 2), *(a->col + 3),
                                 *(a->col + 4), *(a->col + 5), *(a->col + 6), *(a->col + 7), a->n,
                                 a->threads, a->request, a->models, a->out, a->out_len, a->scratch,
                                 a->scratch_len, st);
}

/* The reference: pl_batch_run_untraced over the same rows (PL_INPUT_ROWS, PL_OUTPUT_WIRE) into
 * ti_ref (cleared first), then the trailer of k chunks (k = 0 for threads 0, else min(threads, n),
 * written out by the caller). Returns the batch result. */
static inline int ti_reference(size_t n, uint32_t threads, size_t k, uint16_t models,
                               struct pl_batch_stats *st) {
    struct pl_params p;
    pl_case_params(&p);
    const struct pl_input in = {PL_INPUT_ROWS, 0u, n, ti_rows, NULL, {NULL}};
    const struct pl_output out = {PL_OUTPUT_WIRE, 0u, NULL, ti_ref};
    const struct pl_batch_scratch sc = {ti_perm, ti_mark, ti_idx, TI_N};
    ti_ref_s = ti_zero_out;
    const int rc = pl_batch_run_untraced(&in, &p, 0, models, threads, TI_INDEX, &sc, &out, st);
    pl_trailer_encode(ti_ref + n * PL_RESPONSE_RECORD_BYTES, k, st->chunk_sizes, st->chunk_wall_ns);
    return rc;
}

/* The decode of record i of the buffer out under models. */
static inline enum pl_proto_error ti_decode(const uint8_t *out, size_t i, uint16_t models,
                                            struct pl_contract_result *r) {
    return pl_response_decode(out + i * PL_RESPONSE_RECORD_BYTES, models, r);
}
