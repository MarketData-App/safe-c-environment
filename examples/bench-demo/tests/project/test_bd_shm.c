#define _GNU_SOURCE

#include "bd_wire.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* Serve loop tests of the shm route derived from specs/project/bd_wire.md:
 * round trips at offsets 24 and 16, a larger capacity, a ping, the largest
 * request filling both regions, and the input snapshot. The regions are ISO
 * C temporary files sized with ftruncate: a regular file behaves like a
 * memfd for fstat, pread and pwrite. REQUIRE stays active under NDEBUG and
 * has no side effects of its own. The helpers combine their checks without
 * branches into one result bit, so GCC -fanalyzer explores few paths. */

#define REQUIRE_FAIL(c) (fprintf(stderr, "%s:%d: REQUIRE %s\n", __FILE__, __LINE__, #c), exit(1))
#define REQUIRE(c) ((c) ? (void)0 : REQUIRE_FAIL(c))

/* A comparison result (0 or 1) as unsigned int. */
#define AS_BIT(condition) ((unsigned int)(condition))

enum { FRAMES_MAX = 4 * (BD_HEADER_BYTES + BD_SHM_REQUEST_BYTES) };
enum { IN_MAX = BD_SHM_INPUT_BYTES, OUT_MAX = BD_SHM_OUTPUT_BYTES };

/* records holds 2 * BD_RECORDS_MAX records: seed i and steps i % 7. */
static unsigned char records[2 * BD_SHM_INPUT_BYTES];
static unsigned char region[BD_SHM_OUTPUT_BYTES + 1];
static unsigned char expect_bytes[BD_SHM_OUTPUT_BYTES];
static const unsigned char zeros[BD_SHM_OUTPUT_BYTES + 1];

static FILE *make_region(long size) {
    FILE *file = tmpfile();
    REQUIRE(file != NULL);
    REQUIRE(ftruncate(fileno(file), (off_t)size) == 0);
    return file;
}

static void fill_records(void) {
    for (size_t index = 0U; index < 2U * (size_t)BD_RECORDS_MAX; ++index) {
        (void)bd_encode_record(records + index * 12U, (uint64_t)index, (uint32_t)(index % 7U));
    }
}

/* Writes the n records from first at offset at of the input region. */
static unsigned int put_records(FILE *in_region, size_t first, size_t n, uint64_t at) {
    const unsigned char *bytes = records + first * 12U;
    return AS_BIT(bd_pwrite_all(fileno(in_region), bytes, n * 12U, at) == BD_IO_OK);
}

struct shm_result {
    int rc;
    unsigned int ok;
    uint64_t requests;
    unsigned char reply[BD_HEADER_BYTES + BD_SHM_REQUEST_BYTES];
    size_t reply_length;
};

static struct bd_shm_descriptor descriptor(uint64_t in_offset, uint64_t in_length,
                                           uint64_t out_offset, uint64_t out_capacity) {
    const struct bd_shm_descriptor d = {in_offset, in_length, out_offset, out_capacity};
    return d;
}

/* One SHM_REQUEST (count, descriptor) through bd_serve with the given
 * region descriptors, then SHUTDOWN. r.ok is 1 when every file step
 * succeeded. */
static struct shm_result serve_one(int in_fd, int out_fd, uint32_t count,
                                   struct bd_shm_descriptor d) {
    unsigned char frames[FRAMES_MAX] = {0};
    const struct bd_header h = {BD_PROTOCOL_VERSION, BD_FRAME_SHM_REQUEST, 77U, count, 0U, 1U, 32U};
    const struct bd_header stop = {BD_PROTOCOL_VERSION, BD_FRAME_SHUTDOWN, 0U, 0U, 0U, 0U, 0U};
    bd_header_encode(&h, frames);
    bd_store_le(frames + 28, d.in_offset, 8U);
    bd_store_le(frames + 36, d.in_length, 8U);
    bd_store_le(frames + 44, d.out_offset, 8U);
    bd_store_le(frames + 52, d.out_capacity, 8U);
    bd_header_encode(&stop, frames + 60);
    FILE *in = tmpfile();
    FILE *out = tmpfile();
    REQUIRE(in != NULL && out != NULL);
    const enum bd_io put = bd_write_all(fileno(in), frames, 88U);
    const off_t start = lseek(fileno(in), 0, SEEK_SET);
    const struct bd_serve_options o = {BD_ROUTE_SHM, in_fd, out_fd};
    struct shm_result r = {0, 0U, 0U, {0}, 0U};
    r.rc = bd_serve(fileno(in), fileno(out), &o, &r.requests);
    const off_t out_start = lseek(fileno(out), 0, SEEK_SET);
    const ssize_t got = read(fileno(out), r.reply, sizeof r.reply);
    const int in_closed = fclose(in);
    const int out_closed = fclose(out);
    r.reply_length = (size_t)(got < 0 ? 0 : got);
    r.ok = AS_BIT(put == BD_IO_OK) & AS_BIT(start == 0) & AS_BIT(out_start == 0);
    r.ok &= AS_BIT(got >= 0) & AS_BIT(in_closed == 0) & AS_BIT(out_closed == 0);
    return r;
}

/* The reply is one frame of type (ERROR or SHM_RESPONSE) whose payload value
 * is value. */
static unsigned int reply_is(const struct shm_result *r, uint16_t type, uint64_t value) {
    struct bd_header h = {0U, 0U, 0U, 0U, 0U, 0U, 0U};
    const unsigned int error = AS_BIT(type == BD_FRAME_ERROR);
    const size_t length = error ? 32U : 36U;
    const enum bd_proto st = bd_header_decode(r->reply, r->reply_length, &h);
    unsigned int ok = r->ok & AS_BIT(r->reply_length == length) & AS_BIT(st == BD_PROTO_OK);
    ok &= AS_BIT(h.type == type) & AS_BIT(h.request_id == 77U);
    ok &= AS_BIT(h.selector_mask == 1U - error);
    return ok & AS_BIT(bd_load_le(r->reply + 28, error ? 4U : 8U) == value);
}

/* The output region holds exactly expect_bytes[0, length) at offset at and
 * zero elsewhere. */
static unsigned int region_is(FILE *out_region, size_t at, size_t length) {
    const enum bd_io got = bd_pread_exact(fileno(out_region), region, BD_SHM_OUTPUT_BYTES, 0U);
    const int before = memcmp(region, zeros, at);
    const int inside = memcmp(region + at, expect_bytes, length);
    const size_t rest = (size_t)BD_SHM_OUTPUT_BYTES - at - length;
    const int after = memcmp(region + at + length, zeros, rest);
    return AS_BIT(got == BD_IO_OK) & AS_BIT(before == 0) & AS_BIT(inside == 0) & AS_BIT(after == 0);
}

static void round_trip(void) {
    FILE *in = make_region(IN_MAX);
    FILE *out = make_region(OUT_MAX);
    REQUIRE(put_records(in, 100U, 8U, 24U));
    size_t written = 0U;
    const size_t room = sizeof expect_bytes;
    REQUIRE(bd_digest_request(records + 1200, 96U, expect_bytes, room, &written) == BD_OK);
    struct shm_result r = serve_one(fileno(in), fileno(out), 8U, descriptor(24U, 96U, 16U, 128U));
    REQUIRE(r.rc == 0 && r.requests == 1U && reply_is(&r, BD_FRAME_SHM_RESPONSE, 128U));
    REQUIRE(region_is(out, 16U, 128U));
    /* A larger capacity: the same 128 bytes. A ping: no bytes. */
    REQUIRE(ftruncate(fileno(out), 0) == 0 && ftruncate(fileno(out), OUT_MAX) == 0);
    r = serve_one(fileno(in), fileno(out), 8U, descriptor(24U, 96U, 0U, OUT_MAX));
    REQUIRE(r.rc == 0 && reply_is(&r, BD_FRAME_SHM_RESPONSE, 128U) && region_is(out, 0U, 128U));
    REQUIRE(ftruncate(fileno(out), 0) == 0 && ftruncate(fileno(out), OUT_MAX) == 0);
    r = serve_one(fileno(in), fileno(out), 0U, descriptor(0U, 0U, 0U, 0U));
    REQUIRE(r.rc == 0 && r.requests == 1U && reply_is(&r, BD_FRAME_SHM_RESPONSE, 0U));
    REQUIRE(region_is(out, 0U, 0U));
    /* The largest request fills both regions exactly. */
    REQUIRE(put_records(in, 1U, 14336U, 0U));
    REQUIRE(bd_digest_request(records + 12, 172032U, expect_bytes, room, &written) == BD_OK);
    r = serve_one(fileno(in), fileno(out), 14336U, descriptor(0U, 172032U, 0U, 229376U));
    REQUIRE(r.rc == 0 && reply_is(&r, BD_FRAME_SHM_RESPONSE, 229376U));
    REQUIRE(region_is(out, 0U, 229376U));
    REQUIRE(fclose(in) == 0 && fclose(out) == 0);
}

/* bd_shm_request copies the input range first: a later change of the region
 * does not change the records already written. */
static void snapshot(void) {
    static unsigned char private_in[BD_SHM_INPUT_BYTES];
    static unsigned char private_out[BD_SHM_OUTPUT_BYTES];
    FILE *in = make_region(IN_MAX);
    FILE *out = make_region(OUT_MAX);
    REQUIRE(put_records(in, 5U, 3U, 0U));
    size_t written = 0U;
    const size_t room = sizeof expect_bytes;
    REQUIRE(bd_digest_request(records + 60, 36U, expect_bytes, room, &written) == BD_OK);
    unsigned char payload[BD_SHM_REQUEST_BYTES] = {0};
    bd_store_le(payload + 8, 36U, 8U);
    bd_store_le(payload + 24, 48U, 8U);
    const struct bd_header h = {BD_PROTOCOL_VERSION, BD_FRAME_SHM_REQUEST, 1U, 3U, 0U, 1U, 32U};
    const struct bd_serve_options o = {BD_ROUTE_SHM, fileno(in), fileno(out)};
    REQUIRE(bd_shm_request(&o, &h, payload, private_in, private_out, &written) == BD_PROTO_OK);
    REQUIRE(written == 48U && put_records(in, 900U, 3U, 0U));
    REQUIRE(memcmp(private_in, records + 60, 36U) == 0 && region_is(out, 0U, 48U));
    REQUIRE(fclose(in) == 0 && fclose(out) == 0);
}

int main(void) {
    fill_records();
    round_trip();
    snapshot();
    return 0;
}
