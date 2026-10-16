#include "bd_wire.h"

#include <stddef.h>
#include <stdint.h>

/* libFuzzer target for the bd-worker frame decoder: the input bytes are one
 * frame (header and payload). An independent oracle predicts the magic and
 * version results and the record bound; a decoded header re-encodes to the
 * same 28 bytes. A REQUEST with its payload present is answered in memory
 * (when its total step count is small) and the answer must agree with
 * bd_check_request and decode as a RESPONSE of 16n bytes. A SHM_REQUEST takes
 * its region sizes from the next 16 input bytes; an accepted descriptor lies
 * inside both regions. A violated property traps. */

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size);

#define CHECK(c) ((c) ? (void)0 : __builtin_trap())

enum { FUZZ_STEP_BUDGET = 65536 };

static unsigned char fuzz_frame[BD_HEADER_BYTES + BD_OUTPUT_MAX_BYTES];

static uint64_t field(const uint8_t *bytes, unsigned int count) {
    uint64_t value = 0U;
    for (unsigned int index = count; index > 0U; --index) {
        value = (value << 8U) | (uint64_t)*(bytes + index - 1U);
    }
    return value;
}

/* The total steps of n records, or UINT64_MAX when one is above the limit. */
static uint64_t total_steps(const uint8_t *records, size_t n) {
    uint64_t total = 0U;
    for (size_t index = 0U; index < n; ++index) {
        const uint64_t steps = field(records + index * 12U + 8U, 4U);
        if (steps > 1000000U) {
            return UINT64_MAX;
        }
        total += steps;
    }
    return total;
}

static void check_request(const struct bd_header *h, const uint8_t *payload) {
    const size_t n = h->record_count;
    const uint64_t total = total_steps(payload, n);
    if (total != UINT64_MAX && total > (uint64_t)FUZZ_STEP_BUDGET) {
        return;
    }
    size_t length = 99U;
    const enum bd_proto got = bd_answer_request(h, payload, fuzz_frame, sizeof fuzz_frame, &length);
    size_t count = 0U;
    const int valid = n == 0U || bd_check_request(payload, n * 12U, &count) == BD_OK;
    CHECK((got == BD_PROTO_OK) == (valid != 0));
    CHECK(got == BD_PROTO_OK || got == BD_PROTO_KERNEL_FAILURE);
    CHECK(got == BD_PROTO_OK ? length == 28U + 16U * n : length == 0U);
    if (got == BD_PROTO_OK) {
        struct bd_header r = {0U, 0U, 0U, 0U, 0U, 0U, 0U};
        CHECK(bd_header_decode(fuzz_frame, length, &r) == BD_PROTO_OK);
        CHECK(r.type == BD_FRAME_RESPONSE && r.request_id == h->request_id);
        CHECK(r.record_count == h->record_count);
        CHECK(r.selector_mask == h->selector_mask && r.payload_length == 16U * n);
    }
}

static void check_shm(const struct bd_header *h, const uint8_t *payload) {
    struct bd_shm_descriptor d = {0U, 0U, 0U, 0U};
    bd_shm_descriptor_decode(payload, &d);
    CHECK(d.in_offset == field(payload, 8U) && d.out_capacity == field(payload + 24, 8U));
    const uint64_t in_size = field(payload + 32, 8U);
    const uint64_t out_size = field(payload + 40, 8U);
    const enum bd_proto got = bd_shm_descriptor_check(&d, h->record_count, in_size, out_size);
    if (in_size > (uint64_t)BD_SHM_INPUT_BYTES || out_size > (uint64_t)BD_SHM_OUTPUT_BYTES) {
        CHECK(got == BD_PROTO_FRAME_LIMIT);
        return;
    }
    if (got == BD_PROTO_OK) {
        const uint64_t count = h->record_count;
        CHECK(d.in_length == 12U * count && d.out_capacity >= 16U * count);
        CHECK(d.in_offset <= in_size && d.in_length <= in_size - d.in_offset);
        CHECK(d.out_offset <= out_size && d.out_capacity <= out_size - d.out_offset);
    } else {
        CHECK(got == BD_PROTO_LENGTH_MISMATCH);
    }
}

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    struct bd_header h = {0U, 0U, 0U, 0U, 0U, 0U, 0U};
    const enum bd_proto got = bd_header_decode(data, size, &h);
    if (size < 28U) {
        CHECK(got == BD_PROTO_TRUNCATED && h.request_id == 0U);
        return 0;
    }
    const int first = (*data == 'S') & (*(data + 1) == 'C');
    const int magic = first & (*(data + 2) == 'P') & (*(data + 3) == 'L');
    CHECK(magic != 0 || got == BD_PROTO_BAD_MAGIC);
    CHECK(magic == 0 || field(data + 4, 2U) == 2U || got == BD_PROTO_BAD_VERSION);
    CHECK(h.request_id == field(data + 8, 8U) && h.payload_length == field(data + 24, 4U));
    if (got != BD_PROTO_OK) {
        return 0;
    }
    CHECK(h.record_count <= 14336U && h.payload_length <= 4194304U - 28U);
    unsigned char again[BD_HEADER_BYTES] = {0};
    bd_header_encode(&h, again);
    for (unsigned int index = 0U; index < 28U; ++index) {
        CHECK(*(again + index) == *(data + index));
    }
    const size_t rest = size - 28U;
    if (h.type == BD_FRAME_REQUEST && rest >= h.payload_length) {
        check_request(&h, data + 28);
    }
    if (h.type == BD_FRAME_SHM_REQUEST && rest >= 48U) {
        check_shm(&h, data + 28);
    }
    return 0;
}
