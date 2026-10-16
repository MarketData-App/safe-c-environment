#define _GNU_SOURCE

#include "bd_wire.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* Serve loop tests of the stdio route derived from specs/project/bd_wire.md:
 * ping, rows, SHUTDOWN (the frame after it is not read), EOF before a header,
 * NULL arguments and routes outside the enum, I/O failures, and the largest
 * request. The refusals are in tests/project/test_bd_serve_limits.c. Frames
 * are written piece by piece into ISO C temporary files; the records come
 * from one table filled once. REQUIRE stays active under NDEBUG and has no
 * side effects of its own. The helpers have no loops and combine their
 * checks without branches, so GCC -fanalyzer explores few paths. */

#define REQUIRE_FAIL(c) (fprintf(stderr, "%s:%d: REQUIRE %s\n", __FILE__, __LINE__, #c), exit(1))
#define REQUIRE(c) ((c) ? (void)0 : REQUIRE_FAIL(c))

/* A comparison result (0 or 1) as unsigned int. */
#define AS_BIT(condition) ((unsigned int)(condition))

enum { STREAM_MAX = 2 * (BD_HEADER_BYTES + BD_OUTPUT_MAX_BYTES) };

/* records holds BD_RECORDS_MAX + 2 records: seed 0x9e3779b97f4a7c15 + i and
 * steps i % 7. */
static unsigned char records[(BD_RECORDS_MAX + 2) * BD_RECORD_IN_BYTES];
static unsigned char out_bytes[STREAM_MAX];
static unsigned char expect_bytes[BD_OUTPUT_MAX_BYTES];

static void fill_records(void) {
    for (size_t index = 0U; index < (size_t)BD_RECORDS_MAX + 2U; ++index) {
        const uint64_t seed = UINT64_C(0x9e3779b97f4a7c15) + (uint64_t)index;
        (void)bd_encode_record(records + index * 12U, seed, (uint32_t)(index % 7U));
    }
}

struct stream {
    FILE *file;
    unsigned int ok;
};

static struct stream begin(void) {
    struct stream s = {tmpfile(), 1U};
    REQUIRE(s.file != NULL);
    return s;
}

static void put_bytes(struct stream *s, const unsigned char *bytes, size_t length) {
    s->ok &= AS_BIT(fwrite(bytes, 1U, length, s->file) == length);
}

/* Writes one 28-byte header. */
static void put_header(struct stream *s, uint16_t type, uint64_t id, uint32_t count,
                       uint16_t threads, uint16_t mask, uint32_t length) {
    unsigned char raw[BD_HEADER_BYTES] = {0};
    const struct bd_header h = {BD_PROTOCOL_VERSION, type, id, count, threads, mask, length};
    bd_header_encode(&h, raw);
    put_bytes(s, raw, sizeof raw);
}

static void put_records(struct stream *s, size_t first, size_t n) {
    put_bytes(s, records + first * 12U, n * 12U);
}

struct run_result {
    int rc;
    unsigned int ok;
    uint64_t requests;
    size_t out_length;
    off_t in_offset;
};

/* Serves the stream with the route and reads the frames it wrote into
 * out_bytes. r.ok is 1 when every file step succeeded. */
static struct run_result finish(struct stream *s, int route) {
    FILE *out = tmpfile();
    REQUIRE(out != NULL);
    const int flushed = fflush(s->file);
    const off_t start = lseek(fileno(s->file), 0, SEEK_SET);
    const struct bd_serve_options o = {route, -1, -1};
    struct run_result r = {0, 0U, 0U, 0U, 0};
    r.rc = bd_serve(fileno(s->file), fileno(out), &o, &r.requests);
    r.in_offset = lseek(fileno(s->file), 0, SEEK_CUR);
    const off_t out_start = lseek(fileno(out), 0, SEEK_SET);
    const ssize_t got = read(fileno(out), out_bytes, sizeof out_bytes);
    const int in_closed = fclose(s->file);
    const int out_closed = fclose(out);
    r.out_length = (size_t)(got < 0 ? 0 : got);
    r.ok = s->ok & AS_BIT(flushed == 0) & AS_BIT(start == 0) & AS_BIT(got >= 0);
    r.ok &= AS_BIT(out_start == 0) & AS_BIT(in_closed == 0) & AS_BIT(out_closed == 0);
    return r;
}

static unsigned int header_is(size_t at, uint16_t type, uint64_t id, uint32_t count, uint16_t mask,
                              uint32_t length) {
    struct bd_header h = {0U, 0U, 0U, 0U, 0U, 0U, 0U};
    const enum bd_proto st = bd_header_decode(out_bytes + at, BD_HEADER_BYTES, &h);
    unsigned int ok = AS_BIT(st == BD_PROTO_OK) & AS_BIT(h.type == type);
    ok &= AS_BIT(h.request_id == id) & AS_BIT(h.record_count == count);
    ok &= AS_BIT(h.selector_mask == mask) & AS_BIT(h.payload_length == length);
    return ok & AS_BIT(h.threads == 0U);
}

/* The output at out_at is the digest of the n records from first. */
static unsigned int digest_is(size_t first, size_t n, size_t out_at) {
    size_t written = 0U;
    const unsigned char *request = records + first * 12U;
    const size_t room = sizeof expect_bytes;
    const enum bd_status st = bd_digest_request(request, n * 12U, expect_bytes, room, &written);
    const int same = memcmp(out_bytes + out_at, expect_bytes, n * 16U);
    return AS_BIT(st == BD_OK) & AS_BIT(written == n * 16U) & AS_BIT(same == 0);
}

static void ping_rows_shutdown(void) {
    struct stream s = begin();
    put_header(&s, BD_FRAME_REQUEST, 7U, 0U, 0U, 1U, 0U);
    struct run_result r = finish(&s, BD_ROUTE_STDIO);
    REQUIRE(r.ok && r.rc == 0 && r.requests == 1U && r.out_length == 28U);
    REQUIRE(header_is(0U, BD_FRAME_RESPONSE, 7U, 0U, 1U, 0U));
    s = begin();
    put_header(&s, BD_FRAME_REQUEST, UINT64_MAX, 3U, 0U, 1U, 36U);
    put_records(&s, 0U, 3U);
    put_header(&s, BD_FRAME_REQUEST, 9U, 1U, 0U, 1U, 12U);
    put_records(&s, 40U, 1U);
    put_header(&s, BD_FRAME_SHUTDOWN, 0U, 0U, 0U, 0U, 0U);
    put_header(&s, BD_FRAME_REQUEST, 10U, 0U, 0U, 1U, 0U);
    r = finish(&s, BD_ROUTE_STDIO);
    REQUIRE(r.ok && r.rc == 0 && r.requests == 2U && r.out_length == 28U + 48U + 28U + 16U);
    REQUIRE(r.in_offset == 28 + 36 + 28 + 12 + 28);
    REQUIRE(header_is(0U, BD_FRAME_RESPONSE, UINT64_MAX, 3U, 1U, 48U) && digest_is(0U, 3U, 28U));
    REQUIRE(header_is(76U, BD_FRAME_RESPONSE, 9U, 1U, 1U, 16U) && digest_is(40U, 1U, 104U));
    /* EOF before any header: no frame. */
    s = begin();
    r = finish(&s, BD_ROUTE_STDIO);
    REQUIRE(r.ok && r.rc == 0 && r.requests == 0U && r.out_length == 0U);
}

static void arguments_and_io(void) {
    uint64_t requests = 9U;
    const struct bd_serve_options good = {BD_ROUTE_STDIO, -1, -1};
    const struct bd_serve_options bad_route = {7, -1, -1};
    const struct bd_serve_options negative_route = {-1, -1, -1};
    REQUIRE(bd_serve(0, 1, NULL, &requests) == 2 && requests == 0U);
    REQUIRE(bd_serve(0, 1, &good, NULL) == 2);
    REQUIRE(bd_serve(0, 1, &bad_route, &requests) == 2);
    REQUIRE(bd_serve(0, 1, &negative_route, &requests) == 2);
    REQUIRE(bd_serve(-1, 1, &good, &requests) == 4);
    struct stream s = begin();
    put_header(&s, BD_FRAME_REQUEST, 1U, 1U, 0U, 1U, 12U);
    put_records(&s, 0U, 1U);
    put_header(&s, BD_FRAME_REQUEST, 2U, 1U, 0U, 9U, 12U);
    REQUIRE(s.ok && fflush(s.file) == 0);
    /* The answer cannot be written: I/O failure. */
    REQUIRE(lseek(fileno(s.file), 0, SEEK_SET) == 0);
    REQUIRE(bd_serve(fileno(s.file), -1, &good, &requests) == 4);
    /* The ERROR frame cannot be written: I/O failure. */
    REQUIRE(lseek(fileno(s.file), 40, SEEK_SET) == 40);
    REQUIRE(bd_serve(fileno(s.file), -1, &good, &requests) == 4);
    REQUIRE(fclose(s.file) == 0);
}

static void largest_request(void) {
    struct stream s = begin();
    put_header(&s, BD_FRAME_REQUEST, 3U, 14336U, 0U, 1U, 172032U);
    put_records(&s, 0U, 14336U);
    const struct run_result r = finish(&s, BD_ROUTE_STDIO);
    REQUIRE(r.ok && r.rc == 0 && r.requests == 1U && r.out_length == 28U + 229376U);
    REQUIRE(header_is(0U, BD_FRAME_RESPONSE, 3U, 14336U, 1U, 229376U));
    REQUIRE(digest_is(0U, 14336U, 28U));
}

int main(void) {
    fill_records();
    ping_rows_shutdown();
    arguments_and_io();
    largest_request();
    return 0;
}
