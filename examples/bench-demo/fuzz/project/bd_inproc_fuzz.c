#include "bd_inproc.h"

#include "bd_digest.h"

#include <stddef.h>
#include <stdint.h>
#include <string.h>

/* libFuzzer target for the in-process entry: the first 8 input bytes choose
 * threads (byte 0), the selector mask (byte 1), a record-count offset (byte
 * 2, signed), a capacity offset (byte 3, signed) and the scratch length
 * (byte 4); the rest is the request. An independent oracle predicts the
 * return value in the specified order; an accepted call writes the
 * bd_digest_request output, a refused one changes no output byte, and the
 * echo always holds the received arguments. A violated property traps. */

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size);

#define CHECK(c) ((c) ? (void)0 : __builtin_trap())

enum { FUZZ_STEP_BUDGET = 65536, FUZZ_PREFIX = 8, FUZZ_SCRATCH = 64 };

static unsigned char fuzz_out[BD_OUTPUT_MAX_BYTES + 16];
static unsigned char fuzz_expect[BD_OUTPUT_MAX_BYTES];

/* The u32 step count of one 12-byte record, little-endian (bytes 8 to 11). */
static uint64_t steps_of(const uint8_t *record) {
    const uint64_t b0 = *(record + 8);
    const uint64_t b1 = *(record + 9);
    const uint64_t b2 = *(record + 10);
    const uint64_t b3 = *(record + 11);
    return b0 | (b1 << 8U) | (b2 << 16U) | (b3 << 24U);
}

/* Stores value as 8 little-endian bytes. */
static void store8(unsigned char *bytes, uint64_t value) {
    *bytes = (unsigned char)(value & 0xffU);
    *(bytes + 1) = (unsigned char)((value >> 8U) & 0xffU);
    *(bytes + 2) = (unsigned char)((value >> 16U) & 0xffU);
    *(bytes + 3) = (unsigned char)((value >> 24U) & 0xffU);
    *(bytes + 4) = (unsigned char)((value >> 32U) & 0xffU);
    *(bytes + 5) = (unsigned char)((value >> 40U) & 0xffU);
    *(bytes + 6) = (unsigned char)((value >> 48U) & 0xffU);
    *(bytes + 7) = (unsigned char)(value >> 56U);
}

/* base moved by the signed byte delta, clamped at 0. */
static size_t moved(size_t base, uint8_t delta) {
    const size_t step = delta < 128U ? (size_t)delta : 256U - (size_t)delta;
    if (delta < 128U) {
        return base + step;
    }
    return base > step ? base - step : 0U;
}

static int oracle(size_t length, size_t n, uint32_t threads, uint32_t selector,
                  size_t scratch_len) {
    if (scratch_len < 48U) {
        return BD_INPROC_BAD_SCRATCH;
    }
    if (n == 0U || n > 14336U) {
        return BD_INPROC_BAD_RECORDS;
    }
    if (length != 12U * n) {
        return BD_INPROC_BAD_LENGTH;
    }
    if (threads != 0U) {
        return BD_INPROC_BAD_THREADS;
    }
    return selector != 1U ? BD_INPROC_BAD_SELECTOR : -1;
}

/* -1 when every record has steps within the limit and the total is within
 * the budget; BD_STEPS_TOO_LARGE for a step count above the limit; -2 when
 * the total is above the budget (the input is skipped). */
static int steps_status(const uint8_t *request, size_t n) {
    uint64_t total = 0U;
    unsigned int over = 0U;
    for (size_t index = 0U; index < n; ++index) {
        const uint64_t steps = steps_of(request + index * 12U);
        over |= (unsigned int)(steps > 1000000U);
        total += steps;
    }
    if (over != 0U) {
        return BD_STEPS_TOO_LARGE;
    }
    return total > (uint64_t)FUZZ_STEP_BUDGET ? -2 : -1;
}

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    if (size < (size_t)FUZZ_PREFIX) {
        return 0;
    }
    const uint8_t *request = data + FUZZ_PREFIX;
    const size_t length = size - (size_t)FUZZ_PREFIX;
    /* The step oracle runs first, before any other branch: an accepted call
     * has length == 12 * n, so these are exactly its records. */
    const int steps = steps_status(request, length / 12U);
    const uint32_t threads = *data % 4U == 0U ? 0U : *data;
    const uint32_t selector = *(data + 1) % 4U == 0U ? 1U : *(data + 1);
    const size_t n = moved(length / 12U, *(data + 2));
    const size_t capacity = moved(16U * n, *(data + 3));
    const size_t scratch_len = (size_t)(*(data + 4) % (FUZZ_SCRATCH + 1));
    int want = oracle(length, n, threads, selector, scratch_len);
    if (want == -1) {
        want = steps;
    }
    if (want == -2 || capacity > sizeof fuzz_out) {
        return 0;
    }
    if (want == -1) {
        want = capacity < 16U * n ? BD_BUFFER_TOO_SMALL : BD_INPROC_OK;
    }
    unsigned char scratch[FUZZ_SCRATCH] = {0};
    *fuzz_out = 0xA5U;
    const int got = bd_inproc_digest(request, length, n, threads, 7U, selector, fuzz_out, capacity,
                                     scratch, scratch_len);
    unsigned int ok = (unsigned int)(got == want);
    if (scratch_len >= 48U) {
        unsigned char words[48] = {0};
        store8(words, n);
        store8(words + 8, length);
        store8(words + 16, threads);
        store8(words + 24, 7U);
        store8(words + 32, selector);
        store8(words + 40, capacity);
        ok &= (unsigned int)(memcmp(scratch + scratch_len - 48U, words, sizeof words) == 0);
    }
    if (got == BD_INPROC_OK) {
        size_t written = 0U;
        const size_t room = sizeof fuzz_expect;
        const enum bd_status st = bd_digest_request(request, length, fuzz_expect, room, &written);
        const int same = memcmp(fuzz_out, fuzz_expect, written);
        ok &= (unsigned int)(st == BD_OK) & (unsigned int)(same == 0);
    } else {
        ok &= (unsigned int)(*fuzz_out == 0xA5U);
    }
    CHECK(ok != 0U);
    return 0;
}
