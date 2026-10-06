#include "greeting.h"

#include <stddef.h>
#include <stdint.h>
#include <string.h>

/* libFuzzer target: the input bytes are the name. Each input runs with the
 * capacities 0, 1, exact - 1, exact and large, and checks the postconditions
 * of specs/project/greeting.md. A violated postcondition traps. */

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size);

enum { FUZZ_OUT_SIZE = 128 };

static const char fuzz_prefix[] = "Hello, ";

/* Traps when a postcondition fails. A macro, not a function, so GCC -fanalyzer
 * does not analyze a helper body again for every use. */
#define CHECK(c) ((c) ? (void)0 : __builtin_trap())

/* A comparison result (0 or 1) as unsigned int. */
#define AS_BIT(condition) ((unsigned int)(condition))

/* The output buffer is a struct so that it can start as a copy of a sentinel
 * block and be compared with memcmp: no byte loops, so GCC -fanalyzer stays
 * within its fixed budget. */
struct fuzz_buffer {
    char bytes[FUZZ_OUT_SIZE + 1];
};

#define FUZZ_Z16 "ZZZZZZZZZZZZZZZZ"
/* FUZZ_OUT_SIZE (128) sentinel bytes 'Z' and a final NUL. */
static const struct fuzz_buffer fuzz_sentinel = {
    FUZZ_Z16 FUZZ_Z16 FUZZ_Z16 FUZZ_Z16 FUZZ_Z16 FUZZ_Z16 FUZZ_Z16 FUZZ_Z16};

/* Independent oracle: a byte-at-a-time automaton for the well-formed UTF-8
 * byte sequences of Unicode Table 3-7, while src/greeting_text.c parses one
 * whole sequence at a time. The state names the bytes still expected. */
enum oracle_state {
    ORACLE_START,   /* expects a lead byte */
    ORACLE_NEED1,   /* expects 80..BF, then a lead byte */
    ORACLE_NEED2,   /* expects 80..BF, then ORACLE_NEED1 */
    ORACLE_NEED3,   /* expects 80..BF, then ORACLE_NEED2 */
    ORACLE_C2,      /* after C2: expects 80..BF; 80..9F is a C1 control */
    ORACLE_E0,      /* after E0: expects A0..BF (no overlong form) */
    ORACLE_ED,      /* after ED: expects 80..9F (no surrogate) */
    ORACLE_F0,      /* after F0: expects 90..BF (no overlong form) */
    ORACLE_F4,      /* after F4: expects 80..8F (nothing above U+10FFFF) */
    ORACLE_INVALID, /* ill-formed input; absorbing */
};

/* The state after a lead byte. */
static enum oracle_state oracle_lead(unsigned char byte) {
    if (byte < 0x80U) {
        return ORACLE_START;
    }
    if (byte == 0xC2U) {
        return ORACLE_C2;
    }
    if (byte >= 0xC3U && byte <= 0xDFU) {
        return ORACLE_NEED1;
    }
    if (byte == 0xE0U) {
        return ORACLE_E0;
    }
    if (byte == 0xEDU) {
        return ORACLE_ED;
    }
    if (byte >= 0xE1U && byte <= 0xEFU) {
        return ORACLE_NEED2;
    }
    if (byte == 0xF0U) {
        return ORACLE_F0;
    }
    if (byte == 0xF4U) {
        return ORACLE_F4;
    }
    if (byte >= 0xF1U && byte <= 0xF3U) {
        return ORACLE_NEED3;
    }
    return ORACLE_INVALID;
}

/* The state after one more byte. */
static enum oracle_state oracle_next(enum oracle_state state, unsigned char byte) {
    unsigned char low = 0x80U;
    unsigned char high = 0xBFU;
    enum oracle_state next = ORACLE_START;
    switch (state) {
    case ORACLE_START:
        return oracle_lead(byte);
    case ORACLE_NEED1:
    case ORACLE_C2:
        next = ORACLE_START;
        break;
    case ORACLE_NEED2:
        next = ORACLE_NEED1;
        break;
    case ORACLE_NEED3:
        next = ORACLE_NEED2;
        break;
    case ORACLE_E0:
        low = 0xA0U;
        next = ORACLE_NEED1;
        break;
    case ORACLE_ED:
        high = 0x9FU;
        next = ORACLE_NEED1;
        break;
    case ORACLE_F0:
        low = 0x90U;
        next = ORACLE_NEED2;
        break;
    case ORACLE_F4:
        high = 0x8FU;
        next = ORACLE_NEED2;
        break;
    case ORACLE_INVALID:
        return ORACLE_INVALID;
    }
    if (byte < low || byte > high) {
        return ORACLE_INVALID;
    }
    return next;
}

/* Returns 1 when byte, read in state, completes a C0 control, DEL or C1
 * control code point. */
static int oracle_control(enum oracle_state state, unsigned char byte) {
    if (state == ORACLE_START) {
        return byte < 0x20U || byte == 0x7FU;
    }
    return state == ORACLE_C2 && byte < 0xA0U;
}

/* GREETING_INVALID_UTF8 for ill-formed UTF-8 anywhere, else
 * GREETING_NOT_PRINTABLE for any control code point, else GREETING_OK. */
static enum greeting_status oracle_status(const unsigned char *bytes, size_t size) {
    enum oracle_state state = ORACLE_START;
    int controls = 0;
    for (size_t offset = 0U; offset < size; ++offset) {
        const unsigned char byte = *(bytes + offset);
        if (oracle_control(state, byte)) {
            controls = 1;
        }
        state = oracle_next(state, byte);
    }
    if (state != ORACLE_START) {
        return GREETING_INVALID_UTF8;
    }
    return controls ? GREETING_NOT_PRINTABLE : GREETING_OK;
}

/* The status for a capacity large enough for every valid name. */
static enum greeting_status expected_status(const uint8_t *data, size_t size) {
    if (data == NULL) {
        return GREETING_NULL_ARGUMENT;
    }
    if (size == 0U) {
        return GREETING_EMPTY_NAME;
    }
    if (size > (size_t)GREETING_NAME_MAX) {
        return GREETING_NAME_TOO_LONG;
    }
    return oracle_status(data, size);
}

/* Returns 1 when a successful call wrote exactly "Hello, " name "!" NUL. */
static unsigned int success_ok(const char *name, size_t size, const char *out, size_t written) {
    if (size < 1U || size > (size_t)GREETING_NAME_MAX || written != size + 8U) {
        return 0U;
    }
    const unsigned int prefix = AS_BIT(memcmp(out, fuzz_prefix, 7U) == 0);
    const unsigned int copied = AS_BIT(memcmp(out + 7U, name, size) == 0);
    return prefix & copied & AS_BIT(*(out + 7U + size) == '!') & AS_BIT(*(out + written) == '\0');
}

/* Returns 1 when a failed call left written 0 and out[0] NUL (capacity > 0). */
static unsigned int failure_ok(size_t capacity, const char *out, size_t written) {
    return AS_BIT(written == 0U) & (AS_BIT(capacity == 0U) | AS_BIT(*out == '\0'));
}

static enum greeting_status run_case(const char *name, size_t size, size_t capacity) {
    struct fuzz_buffer out = fuzz_sentinel;
    size_t written = 99U;
    size_t start = 0U;
    CHECK(AS_BIT(capacity <= (size_t)FUZZ_OUT_SIZE));
    const enum greeting_status status = greeting_format(name, size, out.bytes, capacity, &written);
    if (status == GREETING_OK) {
        CHECK(success_ok(name, size, out.bytes, written) & AS_BIT(capacity >= size + 9U));
        /* Bytes after the NUL stay untouched. */
        start = written + 1U;
    } else {
        CHECK(failure_ok(capacity, out.bytes, written));
        /* Bytes after out[0] stay untouched (all bytes when capacity is 0). */
        start = AS_BIT(capacity > 0U);
    }
    const size_t rest = sizeof out.bytes - start;
    CHECK(AS_BIT(memcmp(out.bytes + start, fuzz_sentinel.bytes + start, rest) == 0));
    return status;
}

/* The status for a smaller capacity follows from the large-capacity status. */
static enum greeting_status capacity_status(enum greeting_status large, size_t size,
                                            size_t capacity) {
    if (large != GREETING_OK) {
        return large;
    }
    return capacity < size + 9U ? GREETING_BUFFER_TOO_SMALL : GREETING_OK;
}

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    const char *name = (const char *)data;
    const size_t exact = size <= (size_t)GREETING_NAME_MAX ? size + 9U : (size_t)FUZZ_OUT_SIZE;
    const enum greeting_status large = run_case(name, size, (size_t)FUZZ_OUT_SIZE);
    CHECK(AS_BIT(large == expected_status(data, size)));
    const size_t capacities[] = {0U, 1U, exact - 1U, exact};
    const size_t capacity_count = sizeof capacities / sizeof *capacities;
    for (size_t item = 0U; item < capacity_count; ++item) {
        const size_t capacity = *(capacities + item);
        CHECK(AS_BIT(run_case(name, size, capacity) == capacity_status(large, size, capacity)));
    }
    return 0;
}
