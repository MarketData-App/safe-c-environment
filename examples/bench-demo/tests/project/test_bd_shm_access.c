#define _GNU_SOURCE

#include "bd_wire.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* shm route descriptor tests derived from specs/project/bd_wire.md: a pipe,
 * a closed descriptor and a pipe output (IO_ERROR, result 4), steps above
 * the limit (KERNEL_FAILURE, result 3), and read-only and write-only regions
 * (result 4). The regions are ISO C temporary files or files in the current
 * directory. REQUIRE stays active under NDEBUG and has no side effects of
 * its own. */

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

static void descriptors_and_kernel(void) {
    FILE *in = make_region(IN_MAX);
    FILE *out = make_region(OUT_MAX);
    REQUIRE(put_records(in, 0U, 2U, 0U));
    int ends[2] = {-1, -1};
    REQUIRE(pipe(ends) == 0);
    /* A pipe or a closed descriptor is no region: IO_ERROR, result 4. */
    const struct bd_shm_descriptor two = descriptor(0U, 24U, 0U, 32U);
    struct shm_result r = serve_one(*ends, fileno(out), 2U, two);
    REQUIRE(r.rc == 4 && reply_is(&r, BD_FRAME_ERROR, BD_PROTO_IO_ERROR));
    r = serve_one(fileno(in), *(ends + 1), 2U, two);
    REQUIRE(r.rc == 4);
    r = serve_one(fileno(in), -1, 2U, two);
    REQUIRE(r.rc == 4);
    REQUIRE(close(*ends) == 0 && close(*(ends + 1)) == 0);
    /* Steps above the limit in the region: KERNEL_FAILURE, result 3. */
    unsigned char record[BD_RECORD_IN_BYTES] = {0};
    (void)bd_encode_record(record, 1U, 1000001U);
    REQUIRE(bd_pwrite_all(fileno(in), record, 12U, 12U) == BD_IO_OK);
    r = serve_one(fileno(in), fileno(out), 2U, two);
    REQUIRE(r.rc == 3 && reply_is(&r, BD_FRAME_ERROR, BD_PROTO_KERNEL_FAILURE));
    REQUIRE(region_is(out, 0U, 0U));
    REQUIRE(fclose(in) == 0 && fclose(out) == 0);
}

/* Read-only and write-only regions: the positioned read or write fails. */
static void access_modes(void) {
    static const char in_path[] = "bd-shm-test-input.bin";
    static const char out_path[] = "bd-shm-test-output.bin";
    FILE *make_in = fopen(in_path, "wb");
    REQUIRE(make_in != NULL);
    REQUIRE(ftruncate(fileno(make_in), IN_MAX) == 0 && fclose(make_in) == 0);
    FILE *make_out = fopen(out_path, "wb");
    REQUIRE(make_out != NULL);
    REQUIRE(ftruncate(fileno(make_out), OUT_MAX) == 0 && fclose(make_out) == 0);
    FILE *in = make_region(IN_MAX);
    FILE *out = make_region(OUT_MAX);
    REQUIRE(put_records(in, 0U, 2U, 0U));
    FILE *read_only = fopen(out_path, "rb");
    FILE *write_only = fopen(in_path, "ab");
    REQUIRE(read_only != NULL && write_only != NULL);
    const struct bd_shm_descriptor two = descriptor(0U, 24U, 0U, 32U);
    struct shm_result r = serve_one(fileno(in), fileno(read_only), 2U, two);
    REQUIRE(r.rc == 4 && reply_is(&r, BD_FRAME_ERROR, BD_PROTO_IO_ERROR));
    r = serve_one(fileno(write_only), fileno(out), 2U, two);
    REQUIRE(r.rc == 4 && reply_is(&r, BD_FRAME_ERROR, BD_PROTO_IO_ERROR));
    REQUIRE(region_is(out, 0U, 0U));
    REQUIRE(fclose(read_only) == 0 && fclose(write_only) == 0);
    REQUIRE(fclose(in) == 0 && fclose(out) == 0);
    REQUIRE(remove(in_path) == 0 && remove(out_path) == 0);
}

int main(void) {
    fill_records();
    descriptors_and_kernel();
    access_modes();
    return 0;
}
