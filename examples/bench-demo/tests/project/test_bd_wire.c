#include "bd_wire.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Frame codec tests derived from specs/project/bd_wire.md: the header layout,
 * every header check in its order with exact bounds and one-past values, the
 * per-type payload lengths, the shm descriptor checks with wrapping offsets,
 * the in-memory REQUEST answer and the code names. REQUIRE stays active under
 * NDEBUG and has no side effects of its own. */

#define REQUIRE_FAIL(c) (fprintf(stderr, "%s:%d: REQUIRE %s\n", __FILE__, __LINE__, #c), exit(1))
#define REQUIRE(c) ((c) ? (void)0 : REQUIRE_FAIL(c))

/* A comparison result (0 or 1) as unsigned int. */
#define AS_BIT(condition) ((unsigned int)(condition))

static struct bd_header header(uint16_t type, uint32_t count, uint16_t threads, uint16_t mask,
                               uint32_t length) {
    const uint64_t id = UINT64_C(0x0102030405060708);
    const struct bd_header h = {BD_PROTOCOL_VERSION, type, id, count, threads, mask, length};
    return h;
}

static enum bd_proto decode_one(struct bd_header h) {
    unsigned char raw[BD_HEADER_BYTES] = {0};
    struct bd_header got = {0U, 0U, 0U, 0U, 0U, 0U, 0U};
    bd_header_encode(&h, raw);
    return bd_header_decode(raw, sizeof raw, &got);
}

static void layout(void) {
    unsigned char raw[BD_HEADER_BYTES + 1] = {0};
    *(raw + BD_HEADER_BYTES) = 0xA5U;
    const uint64_t id = UINT64_C(0x0807060504030201);
    const struct bd_header h = {2U, 1U, id, 0x0D0C0B0AU, 0U, 1U, 0x14131211U};
    bd_header_encode(&h, raw);
    REQUIRE(memcmp(raw, "SCPL", 4U) == 0);
    REQUIRE(bd_load_le(raw + 4, 2U) == 2U && bd_load_le(raw + 6, 2U) == 1U);
    REQUIRE(*(raw + 8) == 1U && *(raw + 15) == 8U && bd_load_le(raw + 8, 8U) == id);
    REQUIRE(*(raw + 16) == 0x0AU && bd_load_le(raw + 16, 4U) == 0x0D0C0B0AU);
    REQUIRE(bd_load_le(raw + 20, 2U) == 0U && bd_load_le(raw + 22, 2U) == 1U);
    REQUIRE(*(raw + 24) == 0x11U && bd_load_le(raw + 24, 4U) == 0x14131211U);
    REQUIRE(*(raw + BD_HEADER_BYTES) == 0xA5U);
    struct bd_header got = {0U, 0U, 0U, 0U, 0U, 0U, 0U};
    REQUIRE(bd_header_decode(raw, BD_HEADER_BYTES, &got) == BD_PROTO_RECORD_LIMIT);
    REQUIRE(got.request_id == UINT64_C(0x0807060504030201) && got.record_count == 0x0D0C0B0AU);
    REQUIRE(got.payload_length == 0x14131211U && got.selector_mask == 1U);
    REQUIRE(got.type == 1U && got.version == 2U);
    unsigned char word[9] = {0};
    bd_store_le(word, UINT64_C(0x0102030405060708), 8U);
    REQUIRE(*word == 8U && *(word + 7) == 1U && *(word + 8) == 0U);
    REQUIRE(bd_load_le(word, 8U) == UINT64_C(0x0102030405060708));
    REQUIRE(bd_load_le(word, 2U) == 0x0708U);
    REQUIRE(bd_load_le(word, 0U) == 0U);
    bd_store_le(word, UINT64_MAX, 9U);
    REQUIRE(*(word + 8) == 0U);
}

static void truncated(void) {
    unsigned char raw[BD_HEADER_BYTES] = {0};
    struct bd_header got = {1U, 1U, 1U, 1U, 1U, 1U, 1U};
    const struct bd_header h = header(BD_FRAME_REQUEST, 1U, 0U, 1U, 12U);
    bd_header_encode(&h, raw);
    REQUIRE(bd_header_decode(raw, BD_HEADER_BYTES - 1U, &got) == BD_PROTO_TRUNCATED);
    REQUIRE(got.request_id == 0U && got.type == 0U);
    REQUIRE(got.version == 0U && got.payload_length == 0U);
    REQUIRE(bd_header_decode(raw, 0U, &got) == BD_PROTO_TRUNCATED);
    REQUIRE(bd_header_decode(raw, BD_HEADER_BYTES, &got) == BD_PROTO_OK);
}

static void checks(void) {
    /* Good frames at the exact bounds. */
    REQUIRE(decode_one(header(BD_FRAME_REQUEST, 1U, 0U, 1U, 12U)) == BD_PROTO_OK);
    REQUIRE(decode_one(header(BD_FRAME_REQUEST, 0U, 0U, 1U, 0U)) == BD_PROTO_OK);
    REQUIRE(decode_one(header(BD_FRAME_REQUEST, 14336U, 0U, 1U, 172032U)) == BD_PROTO_OK);
    REQUIRE(decode_one(header(BD_FRAME_RESPONSE, 14336U, 0U, 1U, 229376U)) == BD_PROTO_OK);
    REQUIRE(decode_one(header(BD_FRAME_ERROR, 0U, 0U, 0U, 4U)) == BD_PROTO_OK);
    REQUIRE(decode_one(header(BD_FRAME_SHUTDOWN, 0U, 0U, 0U, 0U)) == BD_PROTO_OK);
    REQUIRE(decode_one(header(BD_FRAME_SHM_REQUEST, 14336U, 0U, 1U, 32U)) == BD_PROTO_OK);
    REQUIRE(decode_one(header(BD_FRAME_SHM_RESPONSE, 1U, 0U, 1U, 8U)) == BD_PROTO_OK);
    /* Magic and version. */
    unsigned char raw[BD_HEADER_BYTES] = {0};
    struct bd_header got = {0U, 0U, 0U, 0U, 0U, 0U, 0U};
    const struct bd_header good = header(BD_FRAME_REQUEST, 1U, 0U, 1U, 12U);
    unsigned int bad_magic = 1U;
    for (unsigned int at = 0U; at < 4U; ++at) {
        bd_header_encode(&good, raw);
        *(raw + at) ^= 0x20U;
        bad_magic &= AS_BIT(bd_header_decode(raw, sizeof raw, &got) == BD_PROTO_BAD_MAGIC);
    }
    REQUIRE(bad_magic);
    struct bd_header v = good;
    v.version = 1U;
    REQUIRE(decode_one(v) == BD_PROTO_BAD_VERSION);
    v.version = 3U;
    REQUIRE(decode_one(v) == BD_PROTO_BAD_VERSION);
    /* Type, count, threads, selector. */
    REQUIRE(decode_one(header(0U, 0U, 0U, 0U, 0U)) == BD_PROTO_BAD_TYPE);
    REQUIRE(decode_one(header(7U, 0U, 0U, 0U, 0U)) == BD_PROTO_BAD_TYPE);
    REQUIRE(decode_one(header(UINT16_MAX, 0U, 0U, 0U, 0U)) == BD_PROTO_BAD_TYPE);
    REQUIRE(decode_one(header(BD_FRAME_REQUEST, 14337U, 0U, 1U, 172044U)) == BD_PROTO_RECORD_LIMIT);
    const struct bd_header all_bad = header(BD_FRAME_REQUEST, UINT32_MAX, 9U, 0U, UINT32_MAX);
    REQUIRE(decode_one(all_bad) == BD_PROTO_RECORD_LIMIT);
    REQUIRE(decode_one(header(BD_FRAME_REQUEST, 1U, 1U, 1U, 12U)) == BD_PROTO_BAD_THREADS);
    REQUIRE(decode_one(header(BD_FRAME_REQUEST, 1U, 4U, 1U, 12U)) == BD_PROTO_BAD_THREADS);
    REQUIRE(decode_one(header(BD_FRAME_REQUEST, 1U, 5U, 0U, UINT32_MAX)) == BD_PROTO_BAD_THREADS);
    REQUIRE(decode_one(header(BD_FRAME_SHUTDOWN, 0U, 5U, 0U, 0U)) == BD_PROTO_BAD_THREADS);
    REQUIRE(decode_one(header(BD_FRAME_REQUEST, 1U, 0U, 0U, UINT32_MAX)) == BD_PROTO_BAD_SELECTOR);
    REQUIRE(decode_one(header(BD_FRAME_REQUEST, 1U, 0U, 2U, 12U)) == BD_PROTO_BAD_SELECTOR);
    REQUIRE(decode_one(header(BD_FRAME_REQUEST, 1U, 0U, 31U, 12U)) == BD_PROTO_BAD_SELECTOR);
    REQUIRE(decode_one(header(BD_FRAME_REQUEST, 1U, 0U, 32U, 12U)) == BD_PROTO_BAD_SELECTOR);
    REQUIRE(decode_one(header(BD_FRAME_SHM_RESPONSE, 1U, 0U, 0U, 8U)) == BD_PROTO_BAD_SELECTOR);
    REQUIRE(decode_one(header(BD_FRAME_ERROR, 0U, 0U, 7U, 4U)) == BD_PROTO_RESERVED_NONZERO);
    REQUIRE(decode_one(header(BD_FRAME_SHUTDOWN, 0U, 0U, 1U, 0U)) == BD_PROTO_RESERVED_NONZERO);
    /* Frame size, then the per-type payload length. */
    const uint32_t largest = 4194304U - 28U;
    REQUIRE(decode_one(header(BD_FRAME_REQUEST, 1U, 0U, 1U, largest + 1U)) == BD_PROTO_FRAME_LIMIT);
    REQUIRE(decode_one(header(BD_FRAME_REQUEST, 1U, 0U, 1U, UINT32_MAX)) == BD_PROTO_FRAME_LIMIT);
    REQUIRE(decode_one(header(BD_FRAME_REQUEST, 1U, 0U, 1U, largest)) == BD_PROTO_LENGTH_MISMATCH);
    REQUIRE(decode_one(header(BD_FRAME_REQUEST, 1U, 0U, 1U, 11U)) == BD_PROTO_LENGTH_MISMATCH);
    REQUIRE(decode_one(header(BD_FRAME_REQUEST, 1U, 0U, 1U, 13U)) == BD_PROTO_LENGTH_MISMATCH);
    REQUIRE(decode_one(header(BD_FRAME_RESPONSE, 1U, 0U, 1U, 15U)) == BD_PROTO_LENGTH_MISMATCH);
    REQUIRE(decode_one(header(BD_FRAME_ERROR, 0U, 0U, 0U, 3U)) == BD_PROTO_LENGTH_MISMATCH);
    REQUIRE(decode_one(header(BD_FRAME_ERROR, 1U, 0U, 0U, 4U)) == BD_PROTO_LENGTH_MISMATCH);
    REQUIRE(decode_one(header(BD_FRAME_ERROR, 0U, 1U, 0U, 4U)) == BD_PROTO_LENGTH_MISMATCH);
    REQUIRE(decode_one(header(BD_FRAME_SHUTDOWN, 0U, 0U, 0U, 1U)) == BD_PROTO_LENGTH_MISMATCH);
    REQUIRE(decode_one(header(BD_FRAME_SHUTDOWN, 1U, 0U, 0U, 0U)) == BD_PROTO_LENGTH_MISMATCH);
    REQUIRE(decode_one(header(BD_FRAME_SHUTDOWN, 0U, 4U, 0U, 0U)) == BD_PROTO_LENGTH_MISMATCH);
    REQUIRE(decode_one(header(BD_FRAME_SHM_REQUEST, 1U, 0U, 1U, 31U)) == BD_PROTO_LENGTH_MISMATCH);
    REQUIRE(decode_one(header(BD_FRAME_SHM_REQUEST, 1U, 0U, 1U, 33U)) == BD_PROTO_LENGTH_MISMATCH);
    REQUIRE(decode_one(header(BD_FRAME_SHM_RESPONSE, 1U, 0U, 1U, 7U)) == BD_PROTO_LENGTH_MISMATCH);
}

static struct bd_shm_descriptor descriptor(uint64_t in_offset, uint64_t in_length,
                                           uint64_t out_offset, uint64_t out_capacity) {
    const struct bd_shm_descriptor d = {in_offset, in_length, out_offset, out_capacity};
    return d;
}

static void shm_descriptor(void) {
    unsigned char raw[BD_SHM_REQUEST_BYTES] = {0};
    bd_store_le(raw, UINT64_C(0x0807060504030201), 8U);
    bd_store_le(raw + 8, UINT64_C(0x100F0E0D0C0B0A09), 8U);
    bd_store_le(raw + 16, UINT64_C(0x1817161514131211), 8U);
    bd_store_le(raw + 24, UINT64_C(0x201F1E1D1C1B1A19), 8U);
    struct bd_shm_descriptor d = descriptor(0U, 0U, 0U, 0U);
    bd_shm_descriptor_decode(raw, &d);
    REQUIRE(d.in_offset == UINT64_C(0x0807060504030201));
    REQUIRE(d.in_length == UINT64_C(0x100F0E0D0C0B0A09));
    REQUIRE(d.out_offset == UINT64_C(0x1817161514131211));
    REQUIRE(d.out_capacity == UINT64_C(0x201F1E1D1C1B1A19));
    const uint64_t in = BD_SHM_INPUT_BYTES;
    const uint64_t out = BD_SHM_OUTPUT_BYTES;
    d = descriptor(0U, 24U, 0U, 32U);
    REQUIRE(bd_shm_descriptor_check(&d, 2U, in, out) == BD_PROTO_OK);
    REQUIRE(bd_shm_descriptor_check(&d, 2U, 24U, 32U) == BD_PROTO_OK);
    REQUIRE(bd_shm_descriptor_check(&d, 2U, 23U, 32U) == BD_PROTO_LENGTH_MISMATCH);
    REQUIRE(bd_shm_descriptor_check(&d, 2U, 24U, 31U) == BD_PROTO_LENGTH_MISMATCH);
    REQUIRE(bd_shm_descriptor_check(&d, 1U, in, out) == BD_PROTO_LENGTH_MISMATCH);
    REQUIRE(bd_shm_descriptor_check(&d, 3U, in, out) == BD_PROTO_LENGTH_MISMATCH);
    REQUIRE(bd_shm_descriptor_check(&d, 2U, in + 1U, out) == BD_PROTO_FRAME_LIMIT);
    REQUIRE(bd_shm_descriptor_check(&d, 2U, in, out + 1U) == BD_PROTO_FRAME_LIMIT);
    d = descriptor(0U, 24U, 0U, 33U);
    REQUIRE(bd_shm_descriptor_check(&d, 2U, in, out) == BD_PROTO_OK);
    d = descriptor(0U, 24U, 0U, 31U);
    REQUIRE(bd_shm_descriptor_check(&d, 2U, in, out) == BD_PROTO_LENGTH_MISMATCH);
    d = descriptor(UINT64_MAX - 8U, 24U, 0U, 32U);
    REQUIRE(bd_shm_descriptor_check(&d, 2U, in, out) == BD_PROTO_LENGTH_MISMATCH);
    d = descriptor(0U, 24U, UINT64_MAX - 8U, 32U);
    REQUIRE(bd_shm_descriptor_check(&d, 2U, in, out) == BD_PROTO_LENGTH_MISMATCH);
    d = descriptor(in - 24U, 24U, out - 32U, 32U);
    REQUIRE(bd_shm_descriptor_check(&d, 2U, in, out) == BD_PROTO_OK);
    d = descriptor(in - 23U, 24U, out - 32U, 32U);
    REQUIRE(bd_shm_descriptor_check(&d, 2U, in, out) == BD_PROTO_LENGTH_MISMATCH);
    d = descriptor(0U, 0U, 0U, 0U);
    REQUIRE(bd_shm_descriptor_check(&d, 0U, 0U, 0U) == BD_PROTO_OK);
    d = descriptor(0U, 172032U, 0U, 229376U);
    REQUIRE(bd_shm_descriptor_check(&d, 14336U, in, out) == BD_PROTO_OK);
}

static unsigned char frame_buffer[BD_HEADER_BYTES + BD_OUTPUT_MAX_BYTES + 1];

static void answer(void) {
    unsigned char request[2 * BD_RECORD_IN_BYTES] = {0};
    REQUIRE(bd_encode_record(request, 1U, 1U) == BD_OK);
    REQUIRE(bd_encode_record(request + BD_RECORD_IN_BYTES, 0U, 0U) == BD_OK);
    size_t length = 99U;
    const struct bd_header h = header(BD_FRAME_REQUEST, 2U, 0U, 1U, 24U);
    const size_t room = sizeof frame_buffer;
    REQUIRE(bd_answer_request(&h, request, frame_buffer, room, &length) == BD_PROTO_OK);
    REQUIRE(length == 28U + 32U);
    struct bd_header got = {0U, 0U, 0U, 0U, 0U, 0U, 0U};
    REQUIRE(bd_header_decode(frame_buffer, length, &got) == BD_PROTO_OK);
    REQUIRE(got.type == BD_FRAME_RESPONSE && got.request_id == h.request_id);
    REQUIRE(got.record_count == 2U);
    REQUIRE(got.selector_mask == 1U && got.threads == 0U && got.payload_length == 32U);
    struct bd_result r = {0U, 0U};
    REQUIRE(bd_decode_output(frame_buffer + 28, &r) == BD_OK);
    REQUIRE(r.checksum == UINT64_C(0x37e2fbafd55e2536) && r.state == UINT64_C(0x40822041));
    REQUIRE(bd_decode_output(frame_buffer + 44, &r) == BD_OK);
    REQUIRE(r.checksum == BD_FNV_OFFSET && r.state == BD_ZERO_SEED);
    /* A ping: no records, an empty RESPONSE. */
    const struct bd_header ping = header(BD_FRAME_REQUEST, 0U, 0U, 1U, 0U);
    REQUIRE(bd_answer_request(&ping, request, frame_buffer, room, &length) == BD_PROTO_OK);
    REQUIRE(length == 28U && bd_header_decode(frame_buffer, length, &got) == BD_PROTO_OK);
    REQUIRE(got.record_count == 0U);
    /* The capacity is exact or one short; steps above the limit. */
    REQUIRE(bd_answer_request(&h, request, frame_buffer, 60U, &length) == BD_PROTO_OK);
    REQUIRE(length == 60U);
    REQUIRE(bd_answer_request(&h, request, frame_buffer, 59U, &length) == BD_PROTO_KERNEL_FAILURE);
    REQUIRE(length == 0U);
    REQUIRE(bd_encode_record(request + BD_RECORD_IN_BYTES, 0U, 1000001U) == BD_OK);
    REQUIRE(bd_answer_request(&h, request, frame_buffer, room, &length) == BD_PROTO_KERNEL_FAILURE);
    REQUIRE(length == 0U);
}

static void expect_name(enum bd_proto code, const char *want) {
    REQUIRE(strcmp(bd_proto_name(code), want) == 0);
}

static void names(void) {
    expect_name(BD_PROTO_OK, "OK");
    expect_name(BD_PROTO_BAD_MAGIC, "BAD_MAGIC");
    expect_name(BD_PROTO_BAD_VERSION, "BAD_VERSION");
    expect_name(BD_PROTO_BAD_TYPE, "BAD_TYPE");
    expect_name(BD_PROTO_RECORD_LIMIT, "RECORD_LIMIT");
    expect_name(BD_PROTO_FRAME_LIMIT, "FRAME_LIMIT");
    expect_name(BD_PROTO_LENGTH_MISMATCH, "LENGTH_MISMATCH");
    expect_name(BD_PROTO_TRUNCATED, "PROTOCOL_TRUNCATED");
    expect_name(BD_PROTO_BAD_THREADS, "BAD_THREADS");
    expect_name(BD_PROTO_KERNEL_FAILURE, "KERNEL_FAILURE");
    expect_name(BD_PROTO_IO_ERROR, "IO_ERROR");
    expect_name(BD_PROTO_RESERVED_NONZERO, "RESERVED_NONZERO");
    expect_name(BD_PROTO_BAD_SELECTOR, "BAD_SELECTOR");
    expect_name((enum bd_proto)13, "UNKNOWN");
    unsigned char payload[BD_ERROR_PAYLOAD_BYTES + 1] = {0};
    *(payload + 4) = 0xA5U;
    bd_error_encode(BD_PROTO_BAD_SELECTOR, payload);
    REQUIRE(*payload == 12U && *(payload + 1) == 0U && *(payload + 3) == 0U);
    REQUIRE(*(payload + 4) == 0xA5U);
}

int main(void) {
    layout();
    truncated();
    checks();
    shm_descriptor();
    answer();
    names();
    return 0;
}
