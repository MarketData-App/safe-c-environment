#include "bd_digest.h"
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Tests of bd_main, the program logic of bd-digest, derived from
 * specs/project/bd_digest.md. REQUIRE stays active under NDEBUG and has no
 * side effects of its own. Output is captured in ISO C temporary files. */

/* REQUIRE is an expression: one branch at the use site, and the failure path
 * calls only library functions, so GCC -fanalyzer does not re-analyze a helper
 * function for every use. */
#define REQUIRE_FAIL(c) (fprintf(stderr, "%s:%d: REQUIRE %s\n", __FILE__, __LINE__, #c), exit(1))
#define REQUIRE(c) ((c) ? (void)0 : REQUIRE_FAIL(c))

/* A comparison result (0 or 1) as unsigned int. */
#define AS_BIT(condition) ((unsigned int)(condition))

enum { TEXT_SIZE = 128 };

struct main_case {
    char *seed;
    char *steps;
    int want;
    const char *out;
    const char *err;
};

/* Runs bd_main with the program name, the two texts and the streams out and
 * err, two temporary files that stay open for all cases. It reads back only
 * the text this case appended and returns 1 when the exit status and both
 * texts match. The buffers start zeroed and fread reads at most size - 1
 * bytes, so each text is NUL-terminated and fully initialized. All results
 * are combined without branches, so GCC -fanalyzer explores one path per
 * case. */
static unsigned int run_case(const struct main_case *test, FILE *out, FILE *err) {
    char program[] = "bd-digest";
    char *argv[] = {program, test->seed, test->steps, NULL};
    char out_text[TEXT_SIZE] = {0};
    char err_text[TEXT_SIZE] = {0};
    const long out_start = ftell(out);
    const long err_start = ftell(err);
    const int got = bd_main(3, argv, out, err);
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

/* The expected output line of bd_digest_record(seed, steps). */
static void expected_line(char *line, size_t size, uint64_t seed, uint32_t steps) {
    const struct bd_result r = bd_digest_record(seed, steps);
    const int n = snprintf(line, size, "%016" PRIx64 " %016" PRIx64 "\n", r.checksum, r.state);
    REQUIRE(n == 34);
}

/* argc other than 3 is a usage error; argv is not read. */
static void usage(FILE *out, FILE *err) {
    char program[] = "bd-digest";
    char one[] = "1";
    char *argv[] = {program, one, one, one, NULL};
    const long start = ftell(err);
    REQUIRE(start >= 0L);
    REQUIRE(bd_main(1, argv, out, err) == 2);
    REQUIRE(bd_main(2, argv, out, err) == 2);
    REQUIRE(bd_main(4, argv, out, err) == 2);
    char text[TEXT_SIZE] = {0};
    REQUIRE(fseek(err, start, SEEK_SET) == 0);
    const size_t count = fread(text, 1U, sizeof text - 1U, err);
    REQUIRE(fseek(err, 0L, SEEK_END) == 0);
    const char *line = "usage: bd-digest SEED STEPS\n";
    REQUIRE(count == 3U * strlen(line));
    REQUIRE(strncmp(text, line, strlen(line)) == 0);
}

static void program_paths(FILE *out, FILE *err) {
    char zero[] = "0";
    char one[] = "1";
    char seed[] = "20261007";
    char steps[] = "64";
    char u64_max[] = "18446744073709551615";
    char add_wraps[] = "18446744073709551616";
    char mul_wraps[] = "99999999999999999999";
    char too_long[] = "000000000000000000001";
    char empty[] = "";
    char minus[] = "-1";
    char plus[] = "+1";
    char space[] = " 1";
    char letter[] = "1x";
    char slash[] = "1/";
    char colon[] = "1:";
    char k_max[] = "1000000";
    char k_past[] = "1000001";
    char u32_max[] = "4294967295";
    char u32_past[] = "4294967296";
    char line_seed[TEXT_SIZE];
    char line_max[TEXT_SIZE];
    char line_k_max[TEXT_SIZE];
    expected_line(line_seed, sizeof line_seed, 20261007U, 64U);
    expected_line(line_max, sizeof line_max, UINT64_MAX, 1U);
    expected_line(line_k_max, sizeof line_k_max, 1U, 1000000U);
    const char *invalid = "bd-digest: BD_INVALID_NUMBER\n";
    const char *too_large = "bd-digest: BD_STEPS_TOO_LARGE\n";
    const struct main_case cases[] = {
        /* seed, steps, exit status, stdout text, stderr text */
        {zero, zero, 0, "cbf29ce484222325 9e3779b97f4a7c15\n", ""},
        {seed, steps, 0, line_seed, ""},
        {u64_max, one, 0, line_max, ""},
        {one, k_max, 0, line_k_max, ""},
        {one, k_past, 1, "", too_large},
        {one, u32_max, 1, "", too_large},
        {one, u32_past, 1, "", invalid},
        {add_wraps, one, 1, "", invalid},
        {mul_wraps, one, 1, "", invalid},
        {too_long, one, 1, "", invalid},
        {empty, one, 1, "", invalid},
        {minus, one, 1, "", invalid},
        {plus, one, 1, "", invalid},
        {space, one, 1, "", invalid},
        {letter, one, 1, "", invalid},
        {slash, one, 1, "", invalid},
        {one, colon, 1, "", invalid},
        {NULL, one, 1, "", invalid},
        {one, NULL, 1, "", invalid},
    };
    /* One call per case instead of a loop: GCC -fanalyzer then analyzes each
     * case once, and a failure names the line of its case. */
    REQUIRE(run_case(cases, out, err));
    REQUIRE(run_case(cases + 1, out, err));
    REQUIRE(run_case(cases + 2, out, err));
    REQUIRE(run_case(cases + 3, out, err));
    REQUIRE(run_case(cases + 4, out, err));
    REQUIRE(run_case(cases + 5, out, err));
    REQUIRE(run_case(cases + 6, out, err));
    REQUIRE(run_case(cases + 7, out, err));
    REQUIRE(run_case(cases + 8, out, err));
    REQUIRE(run_case(cases + 9, out, err));
    REQUIRE(run_case(cases + 10, out, err));
    REQUIRE(run_case(cases + 11, out, err));
    REQUIRE(run_case(cases + 12, out, err));
    REQUIRE(run_case(cases + 13, out, err));
    REQUIRE(run_case(cases + 14, out, err));
    REQUIRE(run_case(cases + 15, out, err));
    REQUIRE(run_case(cases + 16, out, err));
    REQUIRE(run_case(cases + 17, out, err));
    REQUIRE(run_case(cases + 18, out, err));
}

/* A stream opened for reading rejects every write: exit status 1. */
static void rejected_write(void) {
    char program[] = "bd-digest";
    char one[] = "1";
    char *argv[] = {program, one, one, NULL};
    FILE *read_only = fopen("/dev/null", "r");
    if (read_only == NULL) {
        (void)fputs("fopen /dev/null failed\n", stderr);
        exit(1);
    }
    const int got = bd_main(3, argv, read_only, stderr);
    REQUIRE(fclose(read_only) == 0);
    REQUIRE(got == 1);
}

int main(void) {
    FILE *out = tmpfile();
    FILE *err = tmpfile();
    REQUIRE(out != NULL);
    REQUIRE(err != NULL);
    usage(out, err);
    program_paths(out, err);
    REQUIRE(fclose(out) == 0);
    REQUIRE(fclose(err) == 0);
    rejected_write();
    return 0;
}
