#include "bd_digest.h"
#include "bd_inproc.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* In-process entry tests derived from specs/project/bd_inproc.md: the ABI
 * version, the echo of the received arguments, every refusal in its order
 * (scratch, records 0, 1, 14,336 and 14,337, length, threads, selector 0, 1,
 * 2 and 31), the statuses passed on from bd_digest_request, and that a
 * refusal changes no output byte. REQUIRE stays active under NDEBUG and has
 * no side effects of its own. */

#define REQUIRE_FAIL(c) (fprintf(stderr, "%s:%d: REQUIRE %s\n", __FILE__, __LINE__, #c), exit(1))
#define REQUIRE(c) ((c) ? (void)0 : REQUIRE_FAIL(c))

/* A comparison result (0 or 1) as unsigned int. */
#define AS_BIT(condition) ((unsigned int)(condition))

static unsigned char request[BD_REQUEST_MAX_BYTES + BD_RECORD_IN_BYTES];
static unsigned char out[BD_OUTPUT_MAX_BYTES + 1];
static unsigned char expect_bytes[BD_OUTPUT_MAX_BYTES];

static void fill(size_t n) {
    for (size_t index = 0U; index < n; ++index) {
        const uint32_t steps = (uint32_t)(index % 9U);
        (void)bd_encode_record(request + index * 12U, (uint64_t)index, steps);
    }
}

static uint64_t word(const unsigned char *bytes) {
    uint64_t value = 0U;
    for (unsigned int index = 8U; index > 0U; --index) {
        value = (value << 8U) | (uint64_t)*(bytes + index - 1U);
    }
    return value;
}

static void abi_and_echo(void) {
    REQUIRE(bd_inproc_abi_version() == 2U);
    unsigned char scratch[64] = {0};
    fill(4U);
    int rc = bd_inproc_digest(request, 48U, 4U, 0U, 77U, 1U, out, 64U, scratch, sizeof scratch);
    REQUIRE(rc == BD_INPROC_OK);
    const unsigned char *echo = scratch + 16;
    REQUIRE(word(echo) == 4U && word(echo + 8) == 48U && word(echo + 16) == 0U);
    REQUIRE(word(echo + 24) == 77U && word(echo + 32) == 1U && word(echo + 40) == 64U);
    REQUIRE(*scratch == 0U && *(scratch + 15) == 0U);
    size_t written = 0U;
    REQUIRE(bd_digest_request(request, 48U, expect_bytes, sizeof expect_bytes, &written) == BD_OK);
    REQUIRE(memcmp(out, expect_bytes, 64U) == 0);
    /* The echo is written also for a refused call. */
    unsigned char exact[48] = {0};
    rc = bd_inproc_digest(request, 48U, 4U, 3U, UINT32_MAX, 31U, out, 64U, exact, sizeof exact);
    REQUIRE(rc == BD_INPROC_BAD_THREADS);
    REQUIRE(word(exact + 16) == 3U && word(exact + 24) == UINT32_MAX && word(exact + 32) == 31U);
}

struct refusal {
    size_t length;
    size_t n;
    uint32_t threads;
    uint32_t selector;
    size_t capacity;
    size_t scratch_len;
    int want;
};

static void refusals(void) {
    const struct refusal cases[] = {
        {12U, 1U, 0U, 1U, 16U, 47U, BD_INPROC_BAD_SCRATCH},
        {12U, 1U, 0U, 1U, 16U, 0U, BD_INPROC_BAD_SCRATCH},
        {0U, 0U, 0U, 1U, 16U, 48U, BD_INPROC_BAD_RECORDS},
        {172044U, 14337U, 0U, 1U, 229392U, 48U, BD_INPROC_BAD_RECORDS},
        {SIZE_MAX, SIZE_MAX, 0U, 1U, 16U, 48U, BD_INPROC_BAD_RECORDS},
        {11U, 1U, 0U, 1U, 16U, 48U, BD_INPROC_BAD_LENGTH},
        {24U, 1U, 0U, 1U, 16U, 48U, BD_INPROC_BAD_LENGTH},
        {12U, 1U, 1U, 1U, 16U, 48U, BD_INPROC_BAD_THREADS},
        {12U, 1U, 4U, 1U, 16U, 48U, BD_INPROC_BAD_THREADS},
        {12U, 1U, 0U, 0U, 16U, 48U, BD_INPROC_BAD_SELECTOR},
        {12U, 1U, 0U, 2U, 16U, 48U, BD_INPROC_BAD_SELECTOR},
        {12U, 1U, 0U, 31U, 16U, 48U, BD_INPROC_BAD_SELECTOR},
        {12U, 1U, 0U, UINT32_MAX, 16U, 48U, BD_INPROC_BAD_SELECTOR},
        {12U, 1U, 0U, 1U, 15U, 48U, BD_BUFFER_TOO_SMALL},
        {12U, 1U, 0U, 1U, 0U, 48U, BD_BUFFER_TOO_SMALL},
    };
    unsigned char scratch[48] = {0};
    fill(2U);
    unsigned int ok = 1U;
    for (size_t index = 0U; index < sizeof cases / sizeof *cases; ++index) {
        const struct refusal *c = cases + index;
        *out = 0xA5U;
        const int got = bd_inproc_digest(request, c->length, c->n, c->threads, 0U, c->selector, out,
                                         c->capacity, scratch, c->scratch_len);
        ok &= AS_BIT(got == c->want) & AS_BIT(*out == 0xA5U);
    }
    REQUIRE(ok);
    int rc = bd_inproc_digest(request, 12U, 1U, 0U, 0U, 1U, out, 16U, NULL, 48U);
    REQUIRE(rc == BD_INPROC_BAD_SCRATCH);
    rc = bd_inproc_digest(NULL, 12U, 1U, 0U, 0U, 1U, out, 16U, scratch, 48U);
    REQUIRE(rc == BD_NULL_ARGUMENT);
    rc = bd_inproc_digest(request, 12U, 1U, 0U, 0U, 1U, NULL, 16U, scratch, 48U);
    REQUIRE(rc == BD_NULL_ARGUMENT);
    REQUIRE(bd_encode_record(request + 12, 1U, 1000001U) == BD_OK);
    rc = bd_inproc_digest(request, 24U, 2U, 0U, 0U, 1U, out, 32U, scratch, 48U);
    REQUIRE(rc == BD_STEPS_TOO_LARGE);
    REQUIRE(*out == 0xA5U);
    fill(2U);
    rc = bd_inproc_digest(request, 24U, 2U, 0U, 0U, 1U, request + 4, 32U, scratch, 48U);
    REQUIRE(rc == BD_OVERLAP);
}

static void bounds(void) {
    unsigned char scratch[48] = {0};
    fill(14336U);
    size_t written = 0U;
    const size_t room = sizeof expect_bytes;
    REQUIRE(bd_digest_request(request, 172032U, expect_bytes, room, &written) == BD_OK);
    *(out + 229376) = 0xA5U;
    int rc = bd_inproc_digest(request, 172032U, 14336U, 0U, 0U, 1U, out, 229376U, scratch, 48U);
    REQUIRE(rc == BD_INPROC_OK);
    REQUIRE(memcmp(out, expect_bytes, 229376U) == 0 && *(out + 229376) == 0xA5U);
    rc = bd_inproc_digest(request, 12U, 1U, 0U, 0U, 1U, out, 16U, scratch, 48U);
    REQUIRE(rc == BD_INPROC_OK);
    REQUIRE(memcmp(out, expect_bytes, 16U) == 0);
}

int main(void) {
    abi_and_echo();
    refusals();
    bounds();
    return 0;
}
