#include "greeting.h"

#include <stddef.h>
#include <stdint.h>

/* libFuzzer target: the input bytes are the name. Each input runs with the
 * capacities 0, 1, exact - 1, exact and large, and checks the postconditions
 * of specs/project/greeting.md. A violated postcondition traps. */

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size);

enum { FUZZ_OUT_SIZE = 128, FUZZ_SENTINEL = 0x5A };

static const char fuzz_prefix[] = "Hello, ";

static void check(int condition) {
    if (!condition) {
        __builtin_trap();
    }
}

static void fill(char *buffer, size_t size) {
    for (size_t offset = 0U; offset < size; ++offset) {
        *(buffer + offset) = (char)FUZZ_SENTINEL;
    }
}

/* Independent oracle: the well-formed byte sequences of Unicode Table 3-7.
 * Returns the sequence length, or 0 for an ill-formed or truncated sequence. */
static size_t oracle_sequence(const unsigned char *bytes, size_t remaining) {
    const unsigned char lead = *bytes;
    unsigned char low = 0x80U;
    unsigned char high = 0xBFU;
    size_t length = 0U;
    if (lead <= 0x7FU) {
        return 1U;
    }
    if (lead >= 0xC2U && lead <= 0xDFU) {
        length = 2U;
    } else if (lead >= 0xE0U && lead <= 0xEFU) {
        length = 3U;
        if (lead == 0xE0U) {
            low = 0xA0U;
        }
        if (lead == 0xEDU) {
            high = 0x9FU;
        }
    } else if (lead >= 0xF0U && lead <= 0xF4U) {
        length = 4U;
        if (lead == 0xF0U) {
            low = 0x90U;
        }
        if (lead == 0xF4U) {
            high = 0x8FU;
        }
    } else {
        return 0U;
    }
    if (remaining < length) {
        return 0U;
    }
    const unsigned char second = *(bytes + 1);
    if (second < low || second > high) {
        return 0U;
    }
    for (size_t offset = 2U; offset < length; ++offset) {
        const unsigned char next = *(bytes + offset);
        if (next < 0x80U || next > 0xBFU) {
            return 0U;
        }
    }
    return length;
}

/* C0 controls and DEL are one-byte sequences; C1 controls are 0xC2 0x80..0x9F. */
static int oracle_printable(const unsigned char *bytes, size_t length) {
    const unsigned char lead = *bytes;
    if (length == 1U) {
        return lead >= 0x20U && lead != 0x7FU;
    }
    return length != 2U || lead != 0xC2U || *(bytes + 1) >= 0xA0U;
}

static enum greeting_status oracle_status(const unsigned char *bytes, size_t size) {
    int printable = 1;
    size_t offset = 0U;
    while (offset < size) {
        const size_t length = oracle_sequence(bytes + offset, size - offset);
        if (length == 0U) {
            return GREETING_INVALID_UTF8;
        }
        if (!oracle_printable(bytes + offset, length)) {
            printable = 0;
        }
        offset += length;
    }
    return printable ? GREETING_OK : GREETING_NOT_PRINTABLE;
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

/* Checks that a successful call wrote exactly "Hello, " name "!" NUL. */
static void check_success(const char *name, size_t size, const char *out, size_t written) {
    check(size >= 1U && size <= (size_t)GREETING_NAME_MAX);
    check(written == size + 8U);
    for (size_t offset = 0U; offset < 7U; ++offset) {
        check(*(out + offset) == *(fuzz_prefix + offset));
    }
    for (size_t offset = 0U; offset < size; ++offset) {
        check(*(out + 7U + offset) == *(name + offset));
    }
    check(*(out + 7U + size) == '!');
    check(*(out + written) == '\0');
}

static enum greeting_status run_case(const char *name, size_t size, size_t capacity) {
    char out[FUZZ_OUT_SIZE];
    size_t written = 99U;
    size_t untouched = 0U;
    check(capacity <= sizeof out);
    fill(out, sizeof out);
    enum greeting_status status = greeting_format(name, size, out, capacity, &written);
    if (status == GREETING_OK) {
        check_success(name, size, out, written);
        check(capacity >= size + 9U);
        untouched = written + 1U;
    } else {
        check(written == 0U);
        check(capacity == 0U || *out == '\0');
        untouched = capacity > 0U ? 1U : 0U;
    }
    /* Only the documented bytes change: the greeting and its NUL on success,
     * out[0] on failure. */
    for (size_t offset = untouched; offset < sizeof out; ++offset) {
        check(*(out + offset) == (char)FUZZ_SENTINEL);
    }
    return status;
}

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    const char *name = (const char *)data;
    const size_t exact = size <= (size_t)GREETING_NAME_MAX ? size + 9U : (size_t)FUZZ_OUT_SIZE;
    const enum greeting_status large = run_case(name, size, (size_t)FUZZ_OUT_SIZE);
    check(large == expected_status(data, size));
    const size_t capacities[] = {0U, 1U, exact - 1U, exact};
    const size_t capacity_count = sizeof capacities / sizeof *capacities;
    for (size_t item = 0U; item < capacity_count; ++item) {
        const size_t capacity = *(capacities + item);
        const enum greeting_status status = run_case(name, size, capacity);
        if (large != GREETING_OK) {
            check(status == large);
        } else if (capacity < size + 9U) {
            check(status == GREETING_BUFFER_TOO_SMALL);
        } else {
            check(status == GREETING_OK);
        }
    }
    return 0;
}
