#include "greeting.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Tests of greeting_main, the program logic of hello, derived from
 * specs/project/greeting.md. REQUIRE stays active under NDEBUG and has no side
 * effects of its own. Output is captured in ISO C temporary files. */

/* REQUIRE is an expression: one branch at the use site, and the failure path
 * calls only library functions, so GCC -fanalyzer does not re-analyze a helper
 * function for every use. */
#define REQUIRE_FAIL(c) (fprintf(stderr, "%s:%d: REQUIRE %s\n", __FILE__, __LINE__, #c), exit(1))
#define REQUIRE(c) ((c) ? (void)0 : REQUIRE_FAIL(c))

static void fill(char *buffer, size_t size, char value) {
    for (size_t offset = 0U; offset < size; ++offset) {
        *(buffer + offset) = value;
    }
}

struct main_case {
    int argc;
    char **argv;
    int want;
    const char *out;
    const char *err;
};

/* A comparison result (0 or 1) as unsigned int. */
#define AS_BIT(condition) ((unsigned int)(condition))

/* Runs greeting_main with out and err, two temporary files that stay open for
 * all cases, reads back only the text this case appended, and returns 1 when
 * the exit status and both texts match. The buffers start zeroed and fread
 * reads at most size - 1 bytes, so each text is NUL-terminated and fully
 * initialized for MemorySanitizer. ftell and fseek report a failure in their
 * result. All results are combined without branches, so GCC -fanalyzer explores
 * one path per case. */
static unsigned int run_main(const struct main_case *test, FILE *out, FILE *err) {
    char out_text[128] = {0};
    char err_text[128] = {0};
    const long out_start = ftell(out);
    const long err_start = ftell(err);
    const int got = greeting_main(test->argc, test->argv, out, err);
    const int out_seek = fseek(out, out_start, SEEK_SET);
    const int err_seek = fseek(err, err_start, SEEK_SET);
    const size_t out_count = fread(out_text, 1U, sizeof out_text - 1U, out);
    const size_t err_count = fread(err_text, 1U, sizeof err_text - 1U, err);
    const int read_error = ferror(out) | ferror(err);
    /* Position both streams at their end before the next case writes. */
    const int out_end = fseek(out, 0L, SEEK_END);
    const int err_end = fseek(err, 0L, SEEK_END);
    unsigned int ok = AS_BIT(out_start >= 0L) & AS_BIT(err_start >= 0L);
    ok &= AS_BIT(out_seek == 0) & AS_BIT(err_seek == 0) & AS_BIT(read_error == 0);
    ok &= AS_BIT(out_end == 0) & AS_BIT(err_end == 0) & AS_BIT(got == test->want);
    ok &= AS_BIT(out_count == strlen(test->out)) & AS_BIT(err_count == strlen(test->err));
    ok &= AS_BIT(strcmp(out_text, test->out) == 0) & AS_BIT(strcmp(err_text, test->err) == 0);
    return ok;
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
    const struct main_case cases[] = {
        /* argc, argv, exit status, stdout text, stderr text */
        {1, only_program, 2, "", "usage: hello NAME\n"},
        {3, two_names, 2, "", "usage: hello NAME\n"},
        {2, one_name, 0, "Hello, world!\n", ""},
        {2, control_name, 1, "", "hello: GREETING_NOT_PRINTABLE\n"},
        {2, null_name, 1, "", "hello: GREETING_NULL_ARGUMENT\n"},
        {2, too_long, 1, "", "hello: GREETING_NAME_TOO_LONG\n"},
    };
    FILE *out = tmpfile();
    FILE *err = tmpfile();
    REQUIRE(out != NULL);
    REQUIRE(err != NULL);
    /* One call per case instead of a loop: GCC -fanalyzer then analyzes each
     * case once, and a failure names the line of its case. */
    REQUIRE(run_main(cases, out, err));
    REQUIRE(run_main(cases + 1, out, err));
    REQUIRE(run_main(cases + 2, out, err));
    REQUIRE(run_main(cases + 3, out, err));
    REQUIRE(run_main(cases + 4, out, err));
    REQUIRE(run_main(cases + 5, out, err));
    REQUIRE(fclose(out) == 0);
    REQUIRE(fclose(err) == 0);
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
    program_paths();
    return 0;
}
