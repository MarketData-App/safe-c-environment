#include "bd_digest.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Tests of bd_kernel_report and bd_kernel_main, the program logic of
 * bd-kernel --self-check, derived from specs/project/bd_digest.md. REQUIRE
 * stays active under NDEBUG and has no side effects of its own. Output is
 * captured in ISO C temporary files. */

/* REQUIRE is an expression: one branch at the use site, and the failure path
 * calls only library functions, so GCC -fanalyzer does not re-analyze a helper
 * function for every use. */
#define REQUIRE_FAIL(c) (fprintf(stderr, "%s:%d: REQUIRE %s\n", __FILE__, __LINE__, #c), exit(1))
#define REQUIRE(c) ((c) ? (void)0 : REQUIRE_FAIL(c))

/* A comparison result (0 or 1) as unsigned int. */
#define AS_BIT(condition) ((unsigned int)(condition))

enum { TEXT_SIZE = 128, GOOD_COUNT = 3 };

/* Three rows of the generated vectors of tests/project/test_bd_digest.c. */
static const struct bd_check_vector good[GOOD_COUNT] = {
    {0x0000000000000000U, 0U, 0xcbf29ce484222325U, 0x9e3779b97f4a7c15U},
    {0x0000000000000001U, 1U, 0x37e2fbafd55e2536U, 0x0000000040822041U},
    {0xffffffffffffffffU, 999999U, 0xa9a7f838dff92ec8U, 0xe9c0d662fb69e645U},
};

/* With argv NULL the case calls bd_kernel_report(vectors, count); otherwise
 * bd_kernel_main(argc, argv). */
struct kernel_case {
    int argc;
    char **argv;
    const struct bd_check_vector *vectors;
    size_t count;
    int want;
    const char *out;
    const char *err;
};

/* Runs one case with the streams out and err, two temporary files that stay
 * open for all cases. It reads back only the text this case appended and
 * returns 1 when the result and both texts match. The buffers start zeroed
 * and fread reads at most size - 1 bytes, so each text is NUL-terminated and
 * fully initialized. All results are combined without branches, so GCC
 * -fanalyzer explores few paths per case. */
static unsigned int run_case(const struct kernel_case *test, FILE *out, FILE *err) {
    char out_text[TEXT_SIZE] = {0};
    char err_text[TEXT_SIZE] = {0};
    const long out_start = ftell(out);
    const long err_start = ftell(err);
    int got = 0;
    if (test->argv == NULL) {
        got = bd_kernel_report(test->vectors, test->count, out, err);
    } else {
        got = bd_kernel_main(test->argc, test->argv, out, err);
    }
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

/* bd_kernel_report: PASS, one mismatch, a status failure and NULL vectors. */
static void report(FILE *out, FILE *err) {
    struct bd_check_vector bad[GOOD_COUNT] = {*good, *(good + 1), *(good + 2)};
    bad->state ^= 1U;
    const struct kernel_case cases[] = {
        {0, NULL, good, GOOD_COUNT, 0, "bd-kernel: self-check PASS 3 vectors\n", ""},
        {0, NULL, bad, GOOD_COUNT, 1, "", "bd-kernel: self-check FAIL 1 of 3 differ\n"},
        {0, NULL, good, 0U, 1, "", "bd-kernel: BD_EMPTY_REQUEST\n"},
        {0, NULL, NULL, GOOD_COUNT, 1, "", "bd-kernel: BD_NULL_ARGUMENT\n"},
    };
    REQUIRE(run_case(cases, out, err));
    REQUIRE(run_case(cases + 1, out, err));
    REQUIRE(run_case(cases + 2, out, err));
    REQUIRE(run_case(cases + 3, out, err));
}

/* bd_kernel_main: the exact flag runs the 19 built-in vectors; any other
 * argc or argument is a usage error. */
static void program(FILE *out, FILE *err) {
    char name[] = "bd-kernel";
    char check[] = "--self-check";
    char near[] = "--self-chec";
    char longer[] = "--self-check2";
    char empty[] = "";
    char *with_check[] = {name, check, NULL};
    char *with_near[] = {name, near, NULL};
    char *with_longer[] = {name, longer, NULL};
    char *with_empty[] = {name, empty, NULL};
    char *with_null[] = {name, NULL, NULL};
    char *two[] = {name, check, check, NULL};
    const struct kernel_case cases[] = {
        {2, with_check, NULL, 0U, 0, "bd-kernel: self-check PASS 19 vectors\n", ""},
        {1, with_check, NULL, 0U, 2, "", "usage: bd-kernel --self-check\n"},
        {3, two, NULL, 0U, 2, "", "usage: bd-kernel --self-check\n"},
        {2, with_near, NULL, 0U, 2, "", "usage: bd-kernel --self-check\n"},
        {2, with_longer, NULL, 0U, 2, "", "usage: bd-kernel --self-check\n"},
        {2, with_empty, NULL, 0U, 2, "", "usage: bd-kernel --self-check\n"},
        {2, with_null, NULL, 0U, 2, "", "usage: bd-kernel --self-check\n"},
    };
    REQUIRE(run_case(cases, out, err));
    REQUIRE(run_case(cases + 1, out, err));
    REQUIRE(run_case(cases + 2, out, err));
    REQUIRE(run_case(cases + 3, out, err));
    REQUIRE(run_case(cases + 4, out, err));
    REQUIRE(run_case(cases + 5, out, err));
    REQUIRE(run_case(cases + 6, out, err));
}

int main(void) {
    FILE *out = tmpfile();
    FILE *err = tmpfile();
    REQUIRE(out != NULL);
    REQUIRE(err != NULL);
    report(out, err);
    program(out, err);
    REQUIRE(fclose(out) == 0);
    REQUIRE(fclose(err) == 0);
    return 0;
}
