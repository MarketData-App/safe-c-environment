#define _GNU_SOURCE

#include "bd_wire.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* Serve loop refusal tests derived from specs/project/bd_wire.md: twelve
 * header refusals, a bad magic, a REQUEST on the shm route and a kernel
 * failure, each answered with one ERROR frame and no payload byte read (the
 * IN offset grows by 28, or by the whole frame for the kernel failure), and
 * a truncated payload and header. The refused frames share one IN file and
 * one OUT file, and bd_serve starts at each frame in turn. REQUIRE stays
 * active under NDEBUG and has no side effects of its own; the checks combine
 * without branches, so GCC -fanalyzer explores few paths. */

#define REQUIRE_FAIL(c) (fprintf(stderr, "%s:%d: REQUIRE %s\n", __FILE__, __LINE__, #c), exit(1))
#define REQUIRE(c) ((c) ? (void)0 : REQUIRE_FAIL(c))

/* A comparison result (0 or 1) as unsigned int. */
#define AS_BIT(condition) ((unsigned int)(condition))

enum { CASES = 15, FRAME_STEP = BD_HEADER_BYTES + 2 * BD_RECORD_IN_BYTES };

/* One refused frame: header fields, the route, the expected result, code and
 * IN offset growth. */
struct refusal {
    uint16_t type;
    uint32_t count;
    uint16_t threads;
    uint16_t mask;
    uint32_t length;
    int route;
    int rc;
    enum bd_proto code;
    long consumed;
};

static const struct refusal cases[CASES] = {
    {BD_FRAME_REQUEST, 14337U, 0U, 1U, 172044U, BD_ROUTE_STDIO, 1, BD_PROTO_RECORD_LIMIT, 28L},
    {BD_FRAME_REQUEST, 1U, 0U, 0U, 12U, BD_ROUTE_STDIO, 1, BD_PROTO_BAD_SELECTOR, 28L},
    {BD_FRAME_REQUEST, 1U, 0U, 2U, 12U, BD_ROUTE_STDIO, 1, BD_PROTO_BAD_SELECTOR, 28L},
    {BD_FRAME_REQUEST, 1U, 1U, 1U, 12U, BD_ROUTE_STDIO, 1, BD_PROTO_BAD_THREADS, 28L},
    {BD_FRAME_REQUEST, 1U, 5U, 1U, 12U, BD_ROUTE_STDIO, 1, BD_PROTO_BAD_THREADS, 28L},
    {BD_FRAME_REQUEST, 1U, 0U, 1U, 11U, BD_ROUTE_STDIO, 1, BD_PROTO_LENGTH_MISMATCH, 28L},
    {BD_FRAME_REQUEST, 1U, 0U, 1U, 4194304U, BD_ROUTE_STDIO, 1, BD_PROTO_FRAME_LIMIT, 28L},
    {BD_FRAME_SHM_REQUEST, 1U, 0U, 1U, 32U, BD_ROUTE_STDIO, 1, BD_PROTO_BAD_TYPE, 28L},
    {BD_FRAME_RESPONSE, 1U, 0U, 1U, 16U, BD_ROUTE_STDIO, 1, BD_PROTO_BAD_TYPE, 28L},
    {BD_FRAME_ERROR, 0U, 0U, 0U, 4U, BD_ROUTE_STDIO, 1, BD_PROTO_BAD_TYPE, 28L},
    {BD_FRAME_SHM_RESPONSE, 1U, 0U, 1U, 8U, BD_ROUTE_STDIO, 1, BD_PROTO_BAD_TYPE, 28L},
    {9U, 0U, 0U, 0U, 0U, BD_ROUTE_STDIO, 1, BD_PROTO_BAD_TYPE, 28L},
    {BD_FRAME_REQUEST, 1U, 0U, 1U, 12U, BD_ROUTE_SHM, 1, BD_PROTO_BAD_TYPE, 28L},
    {BD_FRAME_REQUEST, 1U, 0U, 1U, 12U, BD_ROUTE_STDIO, 1, BD_PROTO_BAD_MAGIC, 28L},
    {BD_FRAME_REQUEST, 1U, 0U, 1U, 12U, BD_ROUTE_STDIO, 3, BD_PROTO_KERNEL_FAILURE, 40L},
};

/* Frame i is the header of case i (request ID 100 + i; case 13 with the
 * magic XCPL) and two records; case 14 has steps 1,000,001. */
static void write_cases(FILE *in) {
    for (size_t index = 0U; index < (size_t)CASES; ++index) {
        const struct refusal *c = cases + index;
        unsigned char frame[FRAME_STEP] = {0};
        struct bd_header h = {BD_PROTOCOL_VERSION, 0U, 0U, 0U, 0U, 0U, 0U};
        h.type = c->type;
        h.request_id = 100U + index;
        h.record_count = c->count;
        h.threads = c->threads;
        h.selector_mask = c->mask;
        h.payload_length = c->length;
        bd_header_encode(&h, frame);
        (void)bd_encode_record(frame + 28, 1U, 1U);
        (void)bd_encode_record(frame + 40, 2U, 2U);
        *frame = index == 13U ? (unsigned char)'X' : *frame;
        *(frame + 36) = index == 14U ? 0x41U : *(frame + 36);
        *(frame + 37) = index == 14U ? 0x42U : *(frame + 37);
        *(frame + 38) = index == 14U ? 0x0FU : *(frame + 38);
        REQUIRE(fwrite(frame, 1U, sizeof frame, in) == sizeof frame);
    }
    REQUIRE(fflush(in) == 0);
}

static void refusals(void) {
    FILE *in = tmpfile();
    FILE *out = tmpfile();
    REQUIRE(in != NULL && out != NULL);
    write_cases(in);
    unsigned int ok = 1U;
    for (size_t index = 0U; index < (size_t)CASES; ++index) {
        const struct refusal *c = cases + index;
        const off_t start = (off_t)(index * (size_t)FRAME_STEP);
        const struct bd_serve_options o = {c->route, -1, -1};
        uint64_t requests = 9U;
        const off_t at = lseek(fileno(in), start, SEEK_SET);
        const int rc = bd_serve(fileno(in), fileno(out), &o, &requests);
        const off_t after = lseek(fileno(in), 0, SEEK_CUR);
        ok &= AS_BIT(at == start) & AS_BIT(rc == c->rc) & AS_BIT(requests == 0U);
        ok &= AS_BIT(after == start + c->consumed);
    }
    unsigned char reply[CASES * 32] = {0};
    const off_t rewound = lseek(fileno(out), 0, SEEK_SET);
    const ssize_t got = read(fileno(out), reply, sizeof reply);
    ok &= AS_BIT(rewound == 0) & AS_BIT(got == (ssize_t)sizeof reply);
    for (size_t index = 0U; index < (size_t)CASES; ++index) {
        struct bd_header h = {0U, 0U, 0U, 0U, 0U, 0U, 0U};
        const unsigned char *frame = reply + index * 32U;
        const enum bd_proto st = bd_header_decode(frame, 32U, &h);
        ok &= AS_BIT(st == BD_PROTO_OK) & AS_BIT(h.type == BD_FRAME_ERROR);
        ok &= AS_BIT(h.request_id == 100U + index) & AS_BIT(h.selector_mask == 0U);
        ok &= AS_BIT(bd_load_le(frame + 28, 4U) == (uint64_t)(cases + index)->code);
    }
    REQUIRE(ok);
    REQUIRE(fclose(in) == 0 && fclose(out) == 0);
}

/* A payload that ends early and a header that ends early: ERROR
 * PROTOCOL_TRUNCATED, result 1; the header case has request ID 0. */
static void truncated(void) {
    unsigned char frame[BD_HEADER_BYTES + BD_RECORD_IN_BYTES] = {0};
    const struct bd_header h = {BD_PROTOCOL_VERSION, BD_FRAME_REQUEST, 8U, 2U, 0U, 1U, 24U};
    bd_header_encode(&h, frame);
    const size_t lengths[2] = {sizeof frame, 10U};
    const uint64_t ids[2] = {8U, 0U};
    unsigned int ok = 1U;
    for (size_t index = 0U; index < 2U; ++index) {
        FILE *in = tmpfile();
        FILE *out = tmpfile();
        REQUIRE(in != NULL && out != NULL);
        const size_t put = fwrite(frame, 1U, *(lengths + index), in);
        const int flushed = fflush(in);
        const off_t start = lseek(fileno(in), 0, SEEK_SET);
        const struct bd_serve_options o = {BD_ROUTE_STDIO, -1, -1};
        uint64_t requests = 9U;
        const int rc = bd_serve(fileno(in), fileno(out), &o, &requests);
        unsigned char reply[40] = {0};
        const off_t rewound = lseek(fileno(out), 0, SEEK_SET);
        const ssize_t got = read(fileno(out), reply, sizeof reply);
        struct bd_header r = {0U, 0U, 0U, 0U, 0U, 0U, 0U};
        const enum bd_proto st = bd_header_decode(reply, 32U, &r);
        ok &= AS_BIT(put == *(lengths + index)) & AS_BIT(flushed == 0) & AS_BIT(start == 0);
        ok &= AS_BIT(rc == 1) & AS_BIT(rewound == 0) & AS_BIT(got == 32);
        ok &= AS_BIT(st == BD_PROTO_OK);
        ok &= AS_BIT(r.request_id == *(ids + index)) & AS_BIT(r.type == BD_FRAME_ERROR);
        ok &= AS_BIT(bd_load_le(reply + 28, 4U) == (uint64_t)BD_PROTO_TRUNCATED);
        const int in_closed = fclose(in);
        const int out_closed = fclose(out);
        ok &= AS_BIT(in_closed == 0) & AS_BIT(out_closed == 0);
    }
    REQUIRE(ok);
}

int main(void) {
    refusals();
    truncated();
    return 0;
}
