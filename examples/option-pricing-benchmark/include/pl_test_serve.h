#pragma once
#include "pl_batch_core.h"
#include "pl_crr.h"
#include "pl_evaluate.h"
#include "pl_io.h"
#include "pl_partition.h"
#include "pl_protocol.h"
#include "pl_serve.h"
#include "pl_types.h"
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* The shared helpers of the serve tests (tests/project/test_serve*.c, test_shm*.c and
 * test_worker*.c; specs/project/serve.md). Test code only: no source file includes this header.
 * Every helper is static inline, has no loop and is small: the fixed GCC analyzer budget of one
 * translation unit (exploded nodes per supernode) counts every loop and branch of a helper again
 * at each call site. A request file is built with ts_put, written with ts_flush, served through its
 * descriptor with ts_serve, and the frames that the server wrote are read one by one with
 * ts_frame into ts_head, ts_len and ts_at. The caller defines _GNU_SOURCE before the first
 * include. REQUIRE stays active under NDEBUG. */

#define REQUIRE_FAIL(c) (fprintf(stderr, "%s:%d: REQUIRE %s\n", __FILE__, __LINE__, #c), exit(1))
#define REQUIRE(c) ((c) ? (void)0 : REQUIRE_FAIL(c))

/* An opaque zero (pl_request_count(0) in another translation unit): the loops start from it, so
 * that the GCC analyzer widens them instead of unrolling them over constant bounds. */
#define ZERO pl_request_count(0u)

#define PL_TS_ROWS 8u
#define PL_TS_RECORD_BYTES (PL_TS_ROWS * PL_RESPONSE_RECORD_BYTES)
#define PL_TS_FRAMES 8u
#define PL_TS_PAY_BYTES 65536u
#define PL_TS_IN_BYTES 4096u

/* One request frame: the header fields, then payload bytes from data (ts_wire when NULL). patch 1
 * writes a wrong magic, 2 a wrong version, 3 only the first 10 header bytes. */
struct ts_req {
    uint16_t type;
    uint64_t id;
    uint32_t count;
    uint16_t threads;
    uint16_t models;
    uint32_t length;
    uint32_t payload;
    const uint8_t *data;
    unsigned patch;
};

/* type, id, count, threads, models, length, payload. */
#define TS_REQ(t, i, c, th, m, l, p) {t, i, c, th, m, l, p, NULL, 0u}

/* The payload of frame k read by ts_frame. */
#define TS_PAY(k) (ts_pay + *(ts_at + (k)))

static uint8_t ts_wire[PL_TS_ROWS * PL_REQUEST_RECORD_BYTES];
static uint8_t ts_in[PL_TS_IN_BYTES];
static uint8_t ts_pay[PL_TS_PAY_BYTES];
static size_t ts_size;
static struct pl_header ts_head[PL_TS_FRAMES];
static size_t ts_len[PL_TS_FRAMES];
static size_t ts_at[PL_TS_FRAMES];

/* Eight valid option rows (calls and puts, eight strikes) as 64-byte request records. */
static inline void ts_fill_rows(void) {
    const struct pl_row r0 = {0, 100.0, 80.0, 0.5, 23.9, 24.1, 0.04, 0.012};
    const struct pl_row r1 = {1, 100.0, 85.0, 0.5, 18.9, 19.1, 0.04, 0.012};
    const struct pl_row r2 = {0, 100.0, 90.0, 0.5, 13.9, 14.1, 0.04, 0.012};
    const struct pl_row r3 = {1, 100.0, 95.0, 0.5, 8.9, 9.1, 0.04, 0.012};
    const struct pl_row r4 = {0, 100.0, 100.0, 0.5, 3.9, 4.1, 0.04, 0.012};
    const struct pl_row r5 = {1, 100.0, 105.0, 0.5, 3.9, 4.1, 0.04, 0.012};
    const struct pl_row r6 = {0, 100.0, 110.0, 0.5, 3.9, 4.1, 0.04, 0.012};
    const struct pl_row r7 = {1, 100.0, 115.0, 0.5, 3.9, 4.1, 0.04, 0.012};
    pl_request_encode(&r0, ts_wire);
    pl_request_encode(&r1, ts_wire + 64);
    pl_request_encode(&r2, ts_wire + 128);
    pl_request_encode(&r3, ts_wire + 192);
    pl_request_encode(&r4, ts_wire + 256);
    pl_request_encode(&r5, ts_wire + 320);
    pl_request_encode(&r6, ts_wire + 384);
    pl_request_encode(&r7, ts_wire + 448);
}

/* A tmpfile that only its descriptor is used on (the frames pass only the descriptor). */
static inline FILE *ts_tmpfile(void) {
    FILE *f = tmpfile();
    REQUIRE(f != NULL);
    return f;
}

/* Appends the request q to ts_in at offset at; returns the new offset. */
static inline size_t ts_put(size_t at, const struct ts_req *q) {
    struct pl_header h;
    h.version = PL_PROTOCOL_VERSION;
    h.type = q->type;
    h.request_id = q->id;
    h.record_count = q->count;
    h.threads = q->threads;
    h.models = q->models;
    h.payload_length = q->length;
    REQUIRE(at + PL_HEADER_BYTES + q->payload <= sizeof ts_in);
    pl_header_encode(&h, ts_in + at);
    if (q->patch == 1u) {
        *(ts_in + at) = (uint8_t)'X';
    }
    if (q->patch == 2u) {
        pl_store_u16(ts_in + at + 4, 1u);
    }
    const size_t head = q->patch == 3u ? 10u : PL_HEADER_BYTES;
    memcpy(ts_in + at + head, q->data == NULL ? ts_wire : q->data, q->payload);
    return at + head + q->payload;
}

/* Truncates f and writes the first len bytes of ts_in through its descriptor. */
static inline void ts_flush(FILE *f, size_t len) {
    REQUIRE(ftruncate(fileno(f), 0) == 0 && lseek(fileno(f), 0, SEEK_SET) == 0);
    REQUIRE(pl_write_all(fileno(f), ts_in, len) == PL_IO_OK);
}

/* Serves the frames in in (from its start) into out, reads out into ts_pay (ts_size bytes);
 * returns the pl_serve result. */
static inline int ts_serve(FILE *in, FILE *out, const struct pl_serve_options *o,
                           uint64_t *requests) {
    REQUIRE(lseek(fileno(in), 0, SEEK_SET) == 0);
    REQUIRE(ftruncate(fileno(out), 0) == 0 && lseek(fileno(out), 0, SEEK_SET) == 0);
    const int rc = pl_serve(fileno(in), fileno(out), o, requests);
    const off_t end = lseek(fileno(out), 0, SEEK_END);
    REQUIRE(end >= 0 && (size_t)end <= sizeof ts_pay);
    ts_size = (size_t)end;
    REQUIRE(pl_pread_exact(fileno(out), ts_pay, ts_size, 0u) == PL_IO_OK);
    return rc;
}

/* Decodes frame k at offset at of ts_pay into ts_head, ts_len and ts_at; returns the offset of
 * the next frame. A frame that does not decode or does not fit fails the test. */
static inline size_t ts_frame(size_t at, size_t k) {
    struct pl_header *h = ts_head + k;
    REQUIRE(k < PL_TS_FRAMES && at <= ts_size && ts_size - at >= PL_HEADER_BYTES);
    REQUIRE(pl_header_decode(ts_pay + at, PL_HEADER_BYTES, h) == PL_PROTO_OK);
    REQUIRE(h->payload_length <= ts_size - at - PL_HEADER_BYTES);
    *(ts_len + k) = h->payload_length;
    *(ts_at + k) = at + PL_HEADER_BYTES;
    return at + PL_HEADER_BYTES + h->payload_length;
}

/* 1 when frame k is an ERROR with request ID id and code, models 0. */
static inline int ts_is_error(size_t k, uint64_t id, enum pl_proto_error code) {
    const struct pl_header *h = ts_head + k;
    const uint8_t *p = TS_PAY(k);
    const int sized = *(ts_len + k) == PL_ERROR_PAYLOAD_BYTES && h->type == PL_FRAME_ERROR;
    const int zero = h->models == 0u && h->threads == 0u && h->record_count == 0u;
    return sized && zero && h->request_id == id && pl_load_u16(p) == (uint16_t)code &&
           pl_load_u16(p + 2) == 0u;
}

/* The pl_serve options of a stdio or shm route; the counters are optional. */
static inline struct pl_serve_options ts_options(int route, int echo) {
    const struct pl_serve_options o = {route, echo, -1, -1, NULL, NULL};
    return o;
}

/* The expected record of row i for models: the wired parts of pl_evaluate_contract, or the echo
 * parts, encoded as one 290-byte record. */
static inline void ts_expect_record(size_t i, uint16_t models, int echo, uint8_t *rec) {
    struct pl_row row;
    struct pl_params p;
    struct pl_contract_result r;
    uint64_t calls[PL_MODELS] = {0u};
    uint64_t evals[PL_MODELS] = {0u};
    pl_case_params(&p);
    pl_request_decode(ts_wire + i * PL_REQUEST_RECORD_BYTES, &row);
    if (echo) {
        pl_evaluate_contract_echo(models, &r);
    } else {
        REQUIRE(pl_evaluate_contract(&row, &p, models, &r, calls, evals) == PL_EVAL_OK);
    }
    pl_response_encode(&r, rec);
}

#ifdef PL_TS_SHM

/* The shm tests (test_shm*.c): the frame files and the two regions. */
#define DESC_BYTES 2356u /* 8 * 290 + 4 + 32 */

static FILE *in_f, *out_f, *reg_in, *reg_out;
static uint8_t before[PL_SHM_OUTPUT_BYTES];
static uint8_t after[PL_SHM_OUTPUT_BYTES];
static uint8_t ts_desc[PL_SHM_REQUEST_BYTES];

/* Two fresh regions (the same two tmpfiles, emptied and sized again): the input holds the eight
 * rows at offset 0. */
static inline void regions(void) {
    reg_in = reg_in == NULL ? tmpfile() : reg_in;
    reg_out = reg_out == NULL ? tmpfile() : reg_out;
    REQUIRE(reg_in != NULL && reg_out != NULL);
    REQUIRE(ftruncate(fileno(reg_in), 0) == 0 && ftruncate(fileno(reg_out), 0) == 0);
    REQUIRE(ftruncate(fileno(reg_in), (off_t)PL_SHM_INPUT_BYTES) == 0);
    REQUIRE(ftruncate(fileno(reg_out), (off_t)PL_SHM_OUTPUT_BYTES) == 0);
    REQUIRE(pl_pwrite_all(fileno(reg_in), ts_wire, sizeof ts_wire, 0u) == PL_IO_OK);
}

/* The 32-byte descriptor of an SHM_REQUEST in ts_desc. */
static inline void ts_describe(uint64_t in_off, uint64_t in_len, uint64_t out_off,
                               uint64_t out_cap) {
    pl_store_u64(ts_desc, in_off);
    pl_store_u64(ts_desc + 8, in_len);
    pl_store_u64(ts_desc + 16, out_off);
    pl_store_u64(ts_desc + 24, out_cap);
}

static inline struct pl_serve_options shm_options(int in_fd, int out_fd) {
    struct pl_serve_options o = ts_options(PL_ROUTE_SHM, 0);
    o.shm_in_fd = in_fd;
    o.shm_out_fd = out_fd;
    return o;
}

static inline void read_region(FILE *f, uint8_t *buf, size_t n) {
    REQUIRE(pl_pread_exact(fileno(f), buf, n, 0u) == PL_IO_OK);
}

/* 1 when the output region still holds the bytes that were saved in before. */
static inline int ts_region_unchanged(void) {
    read_region(reg_out, after, PL_SHM_OUTPUT_BYTES);
    return memcmp(before, after, PL_SHM_OUTPUT_BYTES) == 0;
}
#endif
