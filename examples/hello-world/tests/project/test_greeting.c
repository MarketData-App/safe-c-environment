#include "greeting.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Boundary and error tests derived from specs/project/greeting.md.
 * REQUIRE stays active under NDEBUG and has no side effects of its own.
 * The greeting_format cases are one table and one loop, so the analyzers see
 * one call site instead of one per case. tests/project/test_greeting_main.c
 * tests greeting_main in a separate translation unit, so each analyzer run
 * stays within its fixed budget. */

/* REQUIRE is an expression: one branch at the use site, and the failure path
 * calls only library functions, so GCC -fanalyzer does not re-analyze a helper
 * function for every use. */
#define REQUIRE_FAIL(c) (fprintf(stderr, "%s:%d: REQUIRE %s\n", __FILE__, __LINE__, #c), exit(1))
#define REQUIRE(c) ((c) ? (void)0 : REQUIRE_FAIL(c))

/* GREETING_NAME_MAX + 1 = 65 bytes of 'a'. */
static const char max_name[] = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

struct format_case {
    const char *name;
    size_t len;
    size_t cap;
    enum greeting_status want;
};

static const struct format_case format_cases[] = {
    /* Brief cases: NULL, empty, one byte, exact limit, one past, maximum. */
    {.name = NULL, .len = 1U, .cap = 64U, .want = GREETING_NULL_ARGUMENT},
    {.name = "", .len = 0U, .cap = 64U, .want = GREETING_EMPTY_NAME},
    {.name = "w", .len = 1U, .cap = 64U, .want = GREETING_OK},
    {.name = max_name, .len = 64U, .cap = 128U, .want = GREETING_OK},
    {.name = max_name, .len = 65U, .cap = 128U, .want = GREETING_NAME_TOO_LONG},
    {.name = max_name, .len = SIZE_MAX, .cap = 128U, .want = GREETING_NAME_TOO_LONG},
    {.name = "\377", .len = 1U, .cap = 64U, .want = GREETING_INVALID_UTF8},
    {.name = "\303", .len = 1U, .cap = 64U, .want = GREETING_INVALID_UTF8},
    {.name = "a\tb", .len = 3U, .cap = 64U, .want = GREETING_NOT_PRINTABLE},
    {.name = "\302\205", .len = 2U, .cap = 64U, .want = GREETING_NOT_PRINTABLE},
    {.name = "Gr\303\274\303\237e", .len = 7U, .cap = 64U, .want = GREETING_OK},
    {.name = "world", .len = 5U, .cap = 14U, .want = GREETING_OK},
    {.name = "world", .len = 5U, .cap = 13U, .want = GREETING_BUFFER_TOO_SMALL},
    {.name = "world", .len = 5U, .cap = 0U, .want = GREETING_BUFFER_TOO_SMALL},
    /* Valid two-, three- and four-byte sequences, U+E000 and U+10FFFF. */
    {.name = "\302\240", .len = 2U, .cap = 64U, .want = GREETING_OK},
    {.name = "\342\202\254", .len = 3U, .cap = 64U, .want = GREETING_OK},
    {.name = "\356\200\200", .len = 3U, .cap = 64U, .want = GREETING_OK},
    {.name = "\360\237\230\200", .len = 4U, .cap = 64U, .want = GREETING_OK},
    {.name = "\364\217\277\277", .len = 4U, .cap = 64U, .want = GREETING_OK},
    /* Invalid lead bytes, truncation and bad continuation bytes. */
    {.name = "\200", .len = 1U, .cap = 64U, .want = GREETING_INVALID_UTF8},
    {.name = "\300\257", .len = 2U, .cap = 64U, .want = GREETING_INVALID_UTF8},
    {.name = "\365\200\200\200", .len = 4U, .cap = 64U, .want = GREETING_INVALID_UTF8},
    {.name = "\342\202", .len = 2U, .cap = 64U, .want = GREETING_INVALID_UTF8},
    {.name = "\303(", .len = 2U, .cap = 64U, .want = GREETING_INVALID_UTF8},
    {.name = "\342\202(", .len = 3U, .cap = 64U, .want = GREETING_INVALID_UTF8},
    {.name = "\342\202\300", .len = 3U, .cap = 64U, .want = GREETING_INVALID_UTF8},
    {.name = "\360\237\230(", .len = 4U, .cap = 64U, .want = GREETING_INVALID_UTF8},
    /* Overlong, surrogate and above-U+10FFFF sequences. */
    {.name = "\340\200\200", .len = 3U, .cap = 64U, .want = GREETING_INVALID_UTF8},
    {.name = "\360\200\200\200", .len = 4U, .cap = 64U, .want = GREETING_INVALID_UTF8},
    {.name = "\355\240\200", .len = 3U, .cap = 64U, .want = GREETING_INVALID_UTF8},
    {.name = "\355\277\277", .len = 3U, .cap = 64U, .want = GREETING_INVALID_UTF8},
    {.name = "\364\220\200\200", .len = 4U, .cap = 64U, .want = GREETING_INVALID_UTF8},
    /* Printable boundaries; invalid UTF-8 after a control byte wins. */
    {.name = "\037", .len = 1U, .cap = 64U, .want = GREETING_NOT_PRINTABLE},
    {.name = " ", .len = 1U, .cap = 64U, .want = GREETING_OK},
    {.name = "~", .len = 1U, .cap = 64U, .want = GREETING_OK},
    {.name = "\177", .len = 1U, .cap = 64U, .want = GREETING_NOT_PRINTABLE},
    {.name = "a\000b", .len = 3U, .cap = 64U, .want = GREETING_NOT_PRINTABLE},
    {.name = "\302\200", .len = 2U, .cap = 64U, .want = GREETING_NOT_PRINTABLE},
    {.name = "\302\237", .len = 2U, .cap = 64U, .want = GREETING_NOT_PRINTABLE},
    {.name = "\t\377", .len = 2U, .cap = 64U, .want = GREETING_INVALID_UTF8},
    /* Capacity boundaries; earlier failures win over a capacity failure. */
    {.name = "world", .len = 5U, .cap = 1U, .want = GREETING_BUFFER_TOO_SMALL},
    {.name = max_name, .len = 64U, .cap = 73U, .want = GREETING_OK},
    {.name = max_name, .len = 64U, .cap = 72U, .want = GREETING_BUFFER_TOO_SMALL},
    {.name = "", .len = 0U, .cap = 0U, .want = GREETING_EMPTY_NAME},
    {.name = max_name, .len = 65U, .cap = 0U, .want = GREETING_NAME_TOO_LONG},
    {.name = "\377", .len = 1U, .cap = 0U, .want = GREETING_INVALID_UTF8},
    {.name = "\t", .len = 1U, .cap = 0U, .want = GREETING_NOT_PRINTABLE},
};

static void expect(const struct format_case *test) {
    char out[128];
    size_t written = 99U;
    REQUIRE(test->cap <= sizeof out);
    enum greeting_status got = greeting_format(test->name, test->len, out, test->cap, &written);
    REQUIRE(got == test->want);
    if (test->want == GREETING_OK) {
        /* Exactly "Hello, ", the name bytes, "!" and NUL. */
        REQUIRE(written == test->len + 8U);
        REQUIRE(strncmp(out, "Hello, ", 7U) == 0);
        REQUIRE(memcmp(out + 7U, test->name, test->len) == 0);
        REQUIRE(*(out + 7U + test->len) == '!');
        REQUIRE(*(out + written) == '\0');
    } else {
        REQUIRE(written == 0U);
        REQUIRE(test->cap == 0U || *out == '\0');
    }
}

static void format_table(void) {
    const size_t count = sizeof format_cases / sizeof *format_cases;
    for (size_t item = 0U; item < count; ++item) {
        expect(format_cases + item);
    }
}

static void null_arguments(void) {
    {
        size_t w = 0U;
        REQUIRE(greeting_format("w", 1U, NULL, 8U, &w) == GREETING_NULL_ARGUMENT);
        REQUIRE(w == 0U);
    }
    {
        char o[16];
        REQUIRE(greeting_format("w", 1U, o, sizeof o, NULL) == GREETING_NULL_ARGUMENT);
        REQUIRE(*o == '\0');
    }
    {
        size_t w = 99U;
        REQUIRE(greeting_format(NULL, 0U, NULL, 0U, &w) == GREETING_NULL_ARGUMENT);
        REQUIRE(w == 0U);
    }
}

static void expect_name(enum greeting_status status, const char *want) {
    REQUIRE(strcmp(greeting_status_name(status), want) == 0);
}

static void status_names(void) {
    expect_name(GREETING_OK, "GREETING_OK");
    expect_name(GREETING_NULL_ARGUMENT, "GREETING_NULL_ARGUMENT");
    expect_name(GREETING_EMPTY_NAME, "GREETING_EMPTY_NAME");
    expect_name(GREETING_NAME_TOO_LONG, "GREETING_NAME_TOO_LONG");
    expect_name(GREETING_INVALID_UTF8, "GREETING_INVALID_UTF8");
    expect_name(GREETING_NOT_PRINTABLE, "GREETING_NOT_PRINTABLE");
    expect_name(GREETING_BUFFER_TOO_SMALL, "GREETING_BUFFER_TOO_SMALL");
    expect_name((enum greeting_status)7, "GREETING_UNKNOWN");
}

int main(void) {
    format_table();
    null_arguments();
    status_names();
    return 0;
}
