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

/* Checks that a successful call wrote exactly "Hello, " name "!" NUL. */
static void check_success(const char *name, size_t size, const char *out, size_t written) {
    check(size >= 1U && size <= (size_t)GREETING_NAME_MAX);
    check(written == size + 8U);
    for (size_t offset = 0U; offset < 7U; ++offset) {
        check(*(out + offset) == *(fuzz_prefix + offset));
    }
    for (size_t offset = 0U; offset < size; ++offset) {
        const unsigned char byte = (unsigned char)*(name + offset);
        check(byte >= 0x20U && byte != 0x7FU);
        check(*(out + 7U + offset) == *(name + offset));
    }
    check(*(out + 7U + size) == '!');
    check(*(out + written) == '\0');
}

static enum greeting_status run_case(const char *name, size_t size, size_t capacity) {
    char out[FUZZ_OUT_SIZE];
    size_t written = 99U;
    check(capacity <= sizeof out);
    fill(out, sizeof out);
    enum greeting_status status = greeting_format(name, size, out, capacity, &written);
    if (status == GREETING_OK) {
        check_success(name, size, out, written);
        check(capacity >= size + 9U);
    } else {
        check(written == 0U);
        check(capacity == 0U || *out == '\0');
    }
    /* Bytes at and after capacity stay untouched. */
    for (size_t offset = capacity; offset < sizeof out; ++offset) {
        check(*(out + offset) == (char)FUZZ_SENTINEL);
    }
    return status;
}

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    const char *name = (const char *)data;
    const size_t exact = size <= (size_t)GREETING_NAME_MAX ? size + 9U : (size_t)FUZZ_OUT_SIZE;
    const enum greeting_status large = run_case(name, size, (size_t)FUZZ_OUT_SIZE);
    check(large != GREETING_BUFFER_TOO_SMALL);
    const size_t capacities[] = {0U, 1U, exact - 1U, exact};
    for (const size_t *capacity = capacities; capacity != capacities + 4; ++capacity) {
        const enum greeting_status status = run_case(name, size, *capacity);
        if (large != GREETING_OK) {
            check(status == large);
        } else if (*capacity < size + 9U) {
            check(status == GREETING_BUFFER_TOO_SMALL);
        } else {
            check(status == GREETING_OK);
        }
    }
    return 0;
}
