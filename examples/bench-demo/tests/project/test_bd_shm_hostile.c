#define _GNU_SOURCE

#include "bd_wire.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* Hostile shm route tests derived from specs/project/bd_wire.md: eight
 * descriptor and region-size cases, each refused before any region byte is
 * read. The cases share one frame file, one OUT file and the two regions;
 * the output region only grows between cases (100, 229,376, then 229,377
 * bytes), so a byte written by any case would still be there at the end,
 * where the whole region must be zero. REQUIRE stays active under NDEBUG and
 * has no side effects of its own; the checks combine without branches, so
 * GCC -fanalyzer explores few paths. */

#define REQUIRE_FAIL(c) (fprintf(stderr, "%s:%d: REQUIRE %s\n", __FILE__, __LINE__, #c), exit(1))
#define REQUIRE(c) ((c) ? (void)0 : REQUIRE_FAIL(c))

/* A comparison result (0 or 1) as unsigned int. */
#define AS_BIT(condition) ((unsigned int)(condition))

enum { CASES = 8, FRAME = BD_HEADER_BYTES + BD_SHM_REQUEST_BYTES };
enum { IN_MAX = BD_SHM_INPUT_BYTES, OUT_MAX = BD_SHM_OUTPUT_BYTES };

struct hostile {
    long in_size;
    long out_size;
    struct bd_shm_descriptor d;
    enum bd_proto want;
};

static const struct hostile cases[CASES] = {
    {IN_MAX, 100L, {0U, 96U, 0U, 128U}, BD_PROTO_LENGTH_MISMATCH},
    {32L, OUT_MAX, {0U, 96U, 0U, 128U}, BD_PROTO_LENGTH_MISMATCH},
    {IN_MAX, OUT_MAX, {UINT64_MAX - 8U, 96U, 0U, 128U}, BD_PROTO_LENGTH_MISMATCH},
    {IN_MAX, OUT_MAX, {0U, 96U, UINT64_MAX - 8U, 128U}, BD_PROTO_LENGTH_MISMATCH},
    {IN_MAX, OUT_MAX, {0U, 96U, 0U, 127U}, BD_PROTO_LENGTH_MISMATCH},
    {IN_MAX, OUT_MAX, {0U, 95U, 0U, 128U}, BD_PROTO_LENGTH_MISMATCH},
    {IN_MAX + 1L, OUT_MAX, {0U, 96U, 0U, 128U}, BD_PROTO_FRAME_LIMIT},
    {IN_MAX, OUT_MAX + 1L, {0U, 96U, 0U, 128U}, BD_PROTO_FRAME_LIMIT},
};

static unsigned char records[8 * BD_RECORD_IN_BYTES];
static unsigned char region[OUT_MAX + 1];
static const unsigned char zeros[OUT_MAX + 1];

/* Frame i: SHM_REQUEST with request ID 200 + i, count 8 and descriptor i. */
static void write_frames(FILE *frames) {
    for (size_t index = 0U; index < (size_t)CASES; ++index) {
        const struct bd_shm_descriptor *d = &(cases + index)->d;
        unsigned char frame[FRAME] = {0};
        struct bd_header h = {BD_PROTOCOL_VERSION, BD_FRAME_SHM_REQUEST, 0U, 8U, 0U, 1U, 32U};
        h.request_id = 200U + index;
        bd_header_encode(&h, frame);
        bd_store_le(frame + 28, d->in_offset, 8U);
        bd_store_le(frame + 36, d->in_length, 8U);
        bd_store_le(frame + 44, d->out_offset, 8U);
        bd_store_le(frame + 52, d->out_capacity, 8U);
        REQUIRE(fwrite(frame, 1U, sizeof frame, frames) == sizeof frame);
    }
    REQUIRE(fflush(frames) == 0);
}

static void hostile(void) {
    FILE *frames = tmpfile();
    FILE *out = tmpfile();
    FILE *in_region = tmpfile();
    FILE *out_region = tmpfile();
    REQUIRE(frames != NULL && out != NULL && in_region != NULL && out_region != NULL);
    write_frames(frames);
    for (size_t index = 0U; index < 8U; ++index) {
        (void)bd_encode_record(records + index * 12U, (uint64_t)index, (uint32_t)index);
    }
    REQUIRE(bd_pwrite_all(fileno(in_region), records, sizeof records, 0U) == BD_IO_OK);
    const struct bd_serve_options o = {BD_ROUTE_SHM, fileno(in_region), fileno(out_region)};
    unsigned int ok = 1U;
    for (size_t index = 0U; index < (size_t)CASES; ++index) {
        const struct hostile *c = cases + index;
        const off_t start = (off_t)(index * (size_t)FRAME);
        const int in_sized = ftruncate(fileno(in_region), (off_t)c->in_size);
        const int out_sized = ftruncate(fileno(out_region), (off_t)c->out_size);
        const off_t at = lseek(fileno(frames), start, SEEK_SET);
        uint64_t requests = 9U;
        const int rc = bd_serve(fileno(frames), fileno(out), &o, &requests);
        ok &= AS_BIT(in_sized == 0) & AS_BIT(out_sized == 0) & AS_BIT(at == start);
        ok &= AS_BIT(rc == 1) & AS_BIT(requests == 0U);
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
        ok &= AS_BIT(h.request_id == 200U + index);
        ok &= AS_BIT(bd_load_le(frame + 28, 4U) == (uint64_t)(cases + index)->want);
    }
    const enum bd_io read_back = bd_pread_exact(fileno(out_region), region, sizeof region, 0U);
    ok &= AS_BIT(read_back == BD_IO_OK) & AS_BIT(memcmp(region, zeros, sizeof region) == 0);
    REQUIRE(ok);
    REQUIRE(fclose(frames) == 0 && fclose(out) == 0);
    REQUIRE(fclose(in_region) == 0 && fclose(out_region) == 0);
}

int main(void) {
    hostile();
    return 0;
}
