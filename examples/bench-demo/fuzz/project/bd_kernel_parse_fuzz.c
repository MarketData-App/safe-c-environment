#include "bd_wire.h"

#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

/* libFuzzer target for the bd-kernel option parser (N3-A07): the input bytes
 * are the arguments after the program name, separated by NUL bytes (an input
 * of k NUL bytes gives k + 1 arguments). An independent oracle states the
 * grammar: argc 7 to 10, the fixed order --input PATH --records N --loops L,
 * then optionally --handshake, then optionally --output PATH; N and L are
 * decimal texts of 1 to 7 digits with a value in [1, BD_RECORDS_MAX] and
 * [1, BD_LOOPS_MAX]; the oracle judges the range lexically (leading zeros
 * removed, then length and text against the limit text), not by the value.
 * bd_kernel_parse must return the oracle's result. On
 * success every option field must equal the oracle's value and the paths must
 * point at the argument texts; on failure every field must be NULL or 0. A
 * violated property traps. */

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size);

#define CHECK(c) ((c) ? (void)0 : __builtin_trap())

_Static_assert(BD_RECORDS_MAX == 14336, "the oracle limit text is 14336");
_Static_assert(BD_LOOPS_MAX == 1000000, "the oracle limit text is 1000000");

enum {
    FUZZ_TEXT_MAX = 512, /* longer inputs are ignored */
    FUZZ_ARGS_MAX = 12   /* arguments after the program name; more are ignored */
};

static char fuzz_program[] = "bd-kernel";
static char fuzz_text[FUZZ_TEXT_MAX + 1];
static char *fuzz_argv[FUZZ_ARGS_MAX + 2];

/* 1 when the NUL-terminated texts a and b are equal, else 0. */
static int oracle_equal(const char *a, const char *b) { return strcmp(a, b) == 0; }

/* 1 when text is 1 to 7 bytes, each a decimal digit. */
static int oracle_digits(const char *text) {
    size_t length = 0U;
    while (length < 8U && *(text + length) != '\0') {
        ++length;
    }
    if (length == 0U || length == 8U) {
        return 0;
    }
    for (size_t index = 0U; index < length; ++index) {
        const char digit = *(text + index);
        if (digit < '0' || digit > '9') {
            return 0;
        }
    }
    return 1;
}

/* 1 and the value when text is 1 to 7 decimal digits with a value in
 * [1, limit], where limit is the decimal text of the bound (no leading
 * zero); else 0 and value 0. The range check compares texts. */
static int oracle_count(const char *text, const char *limit, uint64_t *value) {
    *value = 0U;
    if (oracle_digits(text) == 0) {
        return 0;
    }
    const char *digits = text + strspn(text, "0");
    const size_t length = strlen(digits);
    const size_t bound = strlen(limit);
    if (length == 0U || length > bound || (length == bound && strcmp(digits, limit) > 0)) {
        return 0;
    }
    *value = (uint64_t)strtoull(text, NULL, 10);
    return 1;
}

/* The oracle result for argc arguments (argv[0] included). On success it
 * fills want with the expected option fields. */
static int oracle_parse(int argc, char **argv, struct bd_kernel_options *want) {
    if (argc < 7 || argc > 10) {
        return 0;
    }
    if (oracle_equal(*(argv + 1), "--input") == 0 || oracle_equal(*(argv + 3), "--records") == 0 ||
        oracle_equal(*(argv + 5), "--loops") == 0) {
        return 0;
    }
    /* The texts of BD_RECORDS_MAX (14,336) and BD_LOOPS_MAX (1,000,000); the
     * seeds seed-records-max and seed-loops-max hold them. */
    if (oracle_count(*(argv + 4), "14336", &want->records) == 0 ||
        oracle_count(*(argv + 6), "1000000", &want->loops) == 0) {
        return 0;
    }
    want->input = *(argv + 2);
    want->output = NULL;
    want->handshake = 0;
    /* The tail after the loops: (), (--handshake), (--output X) or
     * (--handshake --output X). */
    const int tail = argc - 7;
    if (tail == 0) {
        return 1;
    }
    if (tail == 1) {
        want->handshake = 1;
        return oracle_equal(*(argv + 7), "--handshake");
    }
    if (tail == 2) {
        want->output = *(argv + 8);
        return oracle_equal(*(argv + 7), "--output");
    }
    want->handshake = 1;
    want->output = *(argv + 9);
    return oracle_equal(*(argv + 7), "--handshake") & oracle_equal(*(argv + 8), "--output");
}

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    if (size > (size_t)FUZZ_TEXT_MAX) {
        return 0;
    }
    int argc = 1;
    *fuzz_argv = fuzz_program;
    *(fuzz_argv + 1) = fuzz_text;
    for (size_t index = 0U; index < size; ++index) {
        const char byte = (char)*(data + index);
        *(fuzz_text + index) = byte;
        if (byte == '\0') {
            if (argc == FUZZ_ARGS_MAX) {
                return 0;
            }
            ++argc;
            *(fuzz_argv + argc) = fuzz_text + index + 1U;
        }
    }
    *(fuzz_text + size) = '\0';
    ++argc;
    *(fuzz_argv + argc) = NULL;

    struct bd_kernel_options want = {NULL, NULL, 0U, 0U, 0};
    const int expected = oracle_parse(argc, fuzz_argv, &want);
    struct bd_kernel_options got = {fuzz_text, fuzz_text, 99U, 99U, 99};
    const int result = bd_kernel_parse(argc, fuzz_argv, &got);
    CHECK(result == expected);
    if (expected == 0) {
        CHECK(got.input == NULL && got.output == NULL);
        CHECK(got.records == 0U && got.loops == 0U && got.handshake == 0);
    } else {
        CHECK(got.input == want.input && got.output == want.output);
        CHECK(got.records == want.records && got.loops == want.loops);
        CHECK(got.handshake == want.handshake);
    }
    struct bd_kernel_options none = {fuzz_text, fuzz_text, 99U, 99U, 99};
    CHECK(bd_kernel_parse(argc, NULL, &none) == 0);
    CHECK(none.input == NULL && none.output == NULL);
    CHECK(none.records == 0U && none.loops == 0U && none.handshake == 0);
    return 0;
}
