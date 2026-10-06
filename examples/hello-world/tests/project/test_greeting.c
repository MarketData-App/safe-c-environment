#include "greeting.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Boundary and error tests derived from specs/project/greeting.md.
 * REQUIRE stays active under NDEBUG and has no side effects of its own. */

static void require(int condition, int line, const char *text) {
    if (!condition) {
        (void)fprintf(stderr, "REQUIRE failed: %s:%d: %s\n", __FILE__, line, text);
        exit(1);
    }
}

#define REQUIRE(c) require((c) != 0, __LINE__, #c)

static const char max_greeting[] =
    "Hello, aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa!";

static void fill(char *buffer, size_t size, char value) {
    for (size_t offset = 0U; offset < size; ++offset) {
        *(buffer + offset) = value;
    }
}

static void expect(const char *name, size_t len, size_t cap, enum greeting_status want,
                   const char *text) {
    char out[128];
    size_t written = 99U;
    REQUIRE(cap <= sizeof out);
    enum greeting_status got = greeting_format(name, len, out, cap, &written);
    REQUIRE(got == want);
    if (want == GREETING_OK) {
        REQUIRE(strcmp(out, text) == 0);
        REQUIRE(written == strlen(text));
    } else {
        REQUIRE(written == 0U);
        if (cap > 0U) {
            REQUIRE(*out == '\0');
        }
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

static void utf8_boundaries(void) {
    /* Valid two-, three- and four-byte sequences. */
    expect("\302\240", 2U, 64U, GREETING_OK, "Hello, \302\240!");
    expect("\342\202\254", 3U, 64U, GREETING_OK, "Hello, \342\202\254!");
    expect("\356\200\200", 3U, 64U, GREETING_OK, "Hello, \356\200\200!");
    expect("\360\237\230\200", 4U, 64U, GREETING_OK, "Hello, \360\237\230\200!");
    expect("\364\217\277\277", 4U, 64U, GREETING_OK, "Hello, \364\217\277\277!");
    /* Invalid lead bytes, truncation and bad continuation bytes. */
    expect("\200", 1U, 64U, GREETING_INVALID_UTF8, "");
    expect("\300\257", 2U, 64U, GREETING_INVALID_UTF8, "");
    expect("\365\200\200\200", 4U, 64U, GREETING_INVALID_UTF8, "");
    expect("\342\202", 2U, 64U, GREETING_INVALID_UTF8, "");
    expect("\303(", 2U, 64U, GREETING_INVALID_UTF8, "");
    /* Overlong, surrogate and above-U+10FFFF sequences. */
    expect("\340\200\200", 3U, 64U, GREETING_INVALID_UTF8, "");
    expect("\360\200\200\200", 4U, 64U, GREETING_INVALID_UTF8, "");
    expect("\355\240\200", 3U, 64U, GREETING_INVALID_UTF8, "");
    expect("\355\277\277", 3U, 64U, GREETING_INVALID_UTF8, "");
    expect("\364\220\200\200", 4U, 64U, GREETING_INVALID_UTF8, "");
}

static void printable_boundaries(void) {
    expect("\037", 1U, 64U, GREETING_NOT_PRINTABLE, "");
    expect(" ", 1U, 64U, GREETING_OK, "Hello,  !");
    expect("~", 1U, 64U, GREETING_OK, "Hello, ~!");
    expect("\177", 1U, 64U, GREETING_NOT_PRINTABLE, "");
    expect("a\000b", 3U, 64U, GREETING_NOT_PRINTABLE, "");
    expect("\302\200", 2U, 64U, GREETING_NOT_PRINTABLE, "");
    expect("\302\237", 2U, 64U, GREETING_NOT_PRINTABLE, "");
    /* Invalid UTF-8 after a control byte reports the earlier check in the order. */
    expect("\t\377", 2U, 64U, GREETING_INVALID_UTF8, "");
}

static void capacity_boundaries(const char *max) {
    expect("world", 5U, 1U, GREETING_BUFFER_TOO_SMALL, "");
    expect(max, GREETING_NAME_MAX, 73U, GREETING_OK, max_greeting);
    expect(max, GREETING_NAME_MAX, 72U, GREETING_BUFFER_TOO_SMALL, "");
    /* Earlier failures win over a capacity failure. */
    expect("", 0U, 0U, GREETING_EMPTY_NAME, "");
    expect(max, GREETING_NAME_MAX + 1U, 0U, GREETING_NAME_TOO_LONG, "");
    expect("\377", 1U, 0U, GREETING_INVALID_UTF8, "");
    expect("\t", 1U, 0U, GREETING_NOT_PRINTABLE, "");
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

/* Opens an ISO C temporary file that captures one output stream. */
static FILE *open_capture(void) {
    FILE *stream = tmpfile();
    if (stream == NULL) {
        (void)fputs("tmpfile failed\n", stderr);
        exit(1);
    }
    return stream;
}

/* Reads the captured text back and closes the stream. The buffer starts zeroed
 * and at most size - 1 bytes are read, so the text is always NUL-terminated and
 * every byte is initialized for MemorySanitizer. */
static void read_capture(FILE *stream, char *buffer, size_t size) {
    rewind(stream);
    const size_t count = fread(buffer, 1U, size - 1U, stream);
    *(buffer + count) = '\0';
    REQUIRE(ferror(stream) == 0);
    REQUIRE(fclose(stream) == 0);
}

/* Runs greeting_main with captured streams and checks the exit status and the
 * complete text written to each stream. */
static void expect_main(int argc, char **argv, int want, const char *want_out,
                        const char *want_err) {
    char out_text[128] = {0};
    char err_text[128] = {0};
    FILE *out = open_capture();
    FILE *err = open_capture();
    const int got = greeting_main(argc, argv, out, err);
    read_capture(out, out_text, sizeof out_text);
    read_capture(err, err_text, sizeof err_text);
    REQUIRE(got == want);
    REQUIRE(strcmp(out_text, want_out) == 0);
    REQUIRE(strcmp(err_text, want_err) == 0);
}

static void program_paths(void) {
    char program[] = "hello";
    char world[] = "world";
    char control[] = "a\tb";
    char long_name[GREETING_NAME_MAX + 7];
    fill(long_name, sizeof long_name - 1U, 'a');
    *(long_name + sizeof long_name - 1U) = '\0';
    char *only_program[] = {program, NULL};
    char *one_name[] = {program, world, NULL};
    char *two_names[] = {program, world, world, NULL};
    char *control_name[] = {program, control, NULL};
    char *null_name[] = {program, NULL, NULL};
    char *too_long[] = {program, long_name, NULL};
    expect_main(1, only_program, 2, "", "usage: hello NAME\n");
    expect_main(3, two_names, 2, "", "usage: hello NAME\n");
    expect_main(2, one_name, 0, "Hello, world!\n", "");
    expect_main(2, control_name, 1, "", "hello: GREETING_NOT_PRINTABLE\n");
    expect_main(2, null_name, 1, "", "hello: GREETING_NULL_ARGUMENT\n");
    expect_main(2, too_long, 1, "", "hello: GREETING_NAME_TOO_LONG\n");
    /* A stream opened for reading rejects every write: exit status 1. */
    FILE *read_only = fopen("/dev/null", "r");
    if (read_only == NULL) {
        (void)fputs("fopen /dev/null failed\n", stderr);
        exit(1);
    }
    const int got = greeting_main(2, one_name, read_only, stderr);
    REQUIRE(fclose(read_only) == 0);
    REQUIRE(got == 1);
}

int main(void) {
    char max[GREETING_NAME_MAX + 1];
    fill(max, sizeof max, 'a');
    expect(NULL, 1U, 64U, GREETING_NULL_ARGUMENT, "");
    expect("", 0U, 64U, GREETING_EMPTY_NAME, "");
    expect("w", 1U, 64U, GREETING_OK, "Hello, w!");
    expect(max, GREETING_NAME_MAX, 128U, GREETING_OK, max_greeting);
    expect(max, GREETING_NAME_MAX + 1U, 128U, GREETING_NAME_TOO_LONG, "");
    expect(max, SIZE_MAX, 128U, GREETING_NAME_TOO_LONG, "");
    expect("\377", 1U, 64U, GREETING_INVALID_UTF8, "");
    expect("\303", 1U, 64U, GREETING_INVALID_UTF8, "");
    expect("a\tb", 3U, 64U, GREETING_NOT_PRINTABLE, "");
    expect("\302\205", 2U, 64U, GREETING_NOT_PRINTABLE, "");
    expect("Gr\303\274\303\237e", 7U, 64U, GREETING_OK, "Hello, Gr\303\274\303\237e!");
    expect("world", 5U, 14U, GREETING_OK, "Hello, world!");
    expect("world", 5U, 13U, GREETING_BUFFER_TOO_SMALL, "");
    expect("world", 5U, 0U, GREETING_BUFFER_TOO_SMALL, "");
    null_arguments();
    utf8_boundaries();
    printable_boundaries();
    capacity_boundaries(max);
    status_names();
    program_paths();
    return 0;
}
