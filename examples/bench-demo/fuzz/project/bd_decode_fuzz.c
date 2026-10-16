#include "bd_digest.h"

#include <stddef.h>
#include <stdint.h>

/* libFuzzer target for the request decoder: the input bytes are a request.
 * An independent oracle predicts the status of bd_check_request from the
 * length and the step fields. For a valid request each record decodes to the
 * oracle's fields, and when the total step count is small the digest output
 * is checked: the capacities 0, exact - 1 and exact, *written, the per-record
 * digest and that no other output byte changes. A violated property traps. */

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size);

/* Traps when a property fails. A macro, not a function, so GCC -fanalyzer
 * does not analyze a helper body again for every use. */
#define CHECK(c) ((c) ? (void)0 : __builtin_trap())

/* The digest runs only when the steps of the whole request are at most this
 * total, so one input stays fast. */
enum { FUZZ_STEP_BUDGET = 65536 };

static unsigned char fuzz_out[BD_OUTPUT_MAX_BYTES + 1];

/* Little-endian field of count bytes, assembled with a multiply-free sum. */
static uint64_t oracle_field(const uint8_t *bytes, unsigned int count) {
    uint64_t value = 0U;
    for (unsigned int index = count; index > 0U; --index) {
        const uint64_t byte = *(bytes + index - 1U);
        value = (value << 8U) | byte;
    }
    return value;
}

/* The oracle status of a request of size bytes, in the specified order. */
static enum bd_status oracle_status(const uint8_t *data, size_t size, uint64_t *total) {
    *total = 0U;
    if (size == 0U) {
        return BD_EMPTY_REQUEST;
    }
    if (size > (size_t)BD_RECORDS_MAX * 12U) {
        return BD_TOO_MANY_RECORDS;
    }
    if (size % 12U != 0U) {
        return BD_PARTIAL_RECORD;
    }
    for (size_t offset = 0U; offset < size; offset += 12U) {
        const uint64_t steps = oracle_field(data + offset + 8U, 4U);
        if (steps > 1000000U) {
            *total = 0U;
            return BD_STEPS_TOO_LARGE;
        }
        *total += steps;
    }
    return BD_OK;
}

/* Runs bd_digest_request with capacity cap. The first byte and the byte just
 * after the expected output start as 0xA5 sentinels. Returns the status;
 * checks *written and the sentinel after the kept output. */
static enum bd_status digest_with(const uint8_t *data, size_t size, size_t cap, size_t needed) {
    size_t written = 99U;
    *fuzz_out = 0xA5U;
    *(fuzz_out + needed) = 0xA5U;
    const enum bd_status got = bd_digest_request(data, size, fuzz_out, cap, &written);
    const size_t kept = got == BD_OK ? needed : 0U;
    CHECK(written == kept);
    CHECK(*(fuzz_out + kept) == 0xA5U);
    CHECK(kept == 0U || (written == needed && needed <= cap));
    return got;
}

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    uint64_t total = 0U;
    const enum bd_status want = oracle_status(data, size, &total);
    size_t count = 99U;
    const enum bd_status got = bd_check_request(data, size, &count);
    CHECK(got == want);
    CHECK(count == (want == BD_OK ? size / 12U : 0U));
    if (want != BD_OK) {
        CHECK(digest_with(data, size, sizeof fuzz_out, 0U) == want);
        return 0;
    }
    for (size_t index = 0U; index < count; ++index) {
        uint64_t seed = 0U;
        uint32_t steps = 0U;
        CHECK(bd_decode_record(data + index * 12U, &seed, &steps) == BD_OK);
        CHECK(seed == oracle_field(data + index * 12U, 8U));
        CHECK(steps == oracle_field(data + index * 12U + 8U, 4U));
    }
    if (total > (uint64_t)FUZZ_STEP_BUDGET) {
        return 0;
    }
    const size_t needed = count * 16U;
    CHECK(digest_with(data, size, 0U, needed) == BD_BUFFER_TOO_SMALL);
    CHECK(digest_with(data, size, needed - 1U, needed) == BD_BUFFER_TOO_SMALL);
    CHECK(digest_with(data, size, needed, needed) == BD_OK);
    for (size_t index = 0U; index < count; ++index) {
        uint64_t seed = 0U;
        uint32_t steps = 0U;
        (void)bd_decode_record(data + index * 12U, &seed, &steps);
        const struct bd_result result = bd_digest_record(seed, steps);
        CHECK(oracle_field(fuzz_out + index * 16U, 8U) == result.checksum);
        CHECK(oracle_field(fuzz_out + index * 16U + 8U, 8U) == result.state);
    }
    return 0;
}
