#include "bd_wire.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* bd-kernel option tests derived from specs/project/bd_wire.md: the
 * --self-check dispatch, twenty-one usage errors (counts 0, one-past, bad
 * digits, another order, repeats, missing values, extra arguments, a NULL
 * argv) and a failed summary write. Files are written in the current
 * directory and removed at the end. REQUIRE stays active under NDEBUG and has
 * no side effects of its own; the checks combine without branches, so GCC
 * -fanalyzer explores few paths. */

#define REQUIRE_FAIL(c) (fprintf(stderr, "%s:%d: REQUIRE %s\n", __FILE__, __LINE__, #c), exit(1))
#define REQUIRE(c) ((c) ? (void)0 : REQUIRE_FAIL(c))

/* A comparison result (0 or 1) as unsigned int. */
#define AS_BIT(condition) ((unsigned int)(condition))

enum { TEXT_SIZE = 512 };

static const char input_path[] = "bd-kernel-test-input.bin";
static unsigned char request[BD_REQUEST_MAX_BYTES];

/* The default record i: seed 0x0123456789abcdef ^ i, steps i % 5. The
 * encoder cannot fail for a pointer into request. */
static void default_record(size_t index) {
    const uint64_t seed = UINT64_C(0x0123456789abcdef) ^ (uint64_t)index;
    (void)bd_encode_record(request + index * 12U, seed, (uint32_t)(index % 5U));
}

static void fill_request(void) {
    for (size_t index = 0U; index < (size_t)BD_RECORDS_MAX; ++index) {
        default_record(index);
    }
}

/* Sets record n - 1 to seed 0x0123456789abcdef and last_steps, then writes
 * the first n records (1 <= n <= BD_RECORDS_MAX) and extra more bytes of
 * request to the input file. */
static void write_input(size_t n, uint32_t last_steps, size_t extra) {
    unsigned char *last = request + (n - 1U) * 12U;
    (void)bd_encode_record(last, UINT64_C(0x0123456789abcdef), last_steps);
    FILE *file = fopen(input_path, "wb");
    REQUIRE(file != NULL);
    const size_t length = n * 12U + extra;
    const size_t put = fwrite(request, 1U, length, file);
    REQUIRE(fclose(file) == 0 && put == length);
}

static const char usage_text[] =
    "usage: bd-kernel --self-check | --input F --records N --loops L [--handshake] [--output F]\n";
static const char usage_line[] = "PLK1 status=FAIL reason=usage\n";

/* 1 when the stream holds exactly count copies of text. */
static unsigned int repeated(FILE *stream, const char *text, size_t count) {
    char got[4096] = {0};
    const size_t length = strlen(text);
    const int start = fseek(stream, 0L, SEEK_SET);
    const size_t read_count = fread(got, 1U, sizeof got - 1U, stream);
    unsigned int ok = AS_BIT(start == 0) & AS_BIT(read_count == count * length);
    for (size_t index = 0U; index < count; ++index) {
        ok &= AS_BIT(memcmp(got + index * length, text, length) == 0);
    }
    return ok;
}

static void self_check(void) {
    char prog[] = "bd-kernel";
    char self[] = "--self-check";
    char *self_check_argv[] = {prog, self, NULL};
    FILE *in = tmpfile();
    FILE *out = tmpfile();
    FILE *err = tmpfile();
    REQUIRE(in != NULL && out != NULL && err != NULL);
    REQUIRE(bd_kernel_cli_main(2, self_check_argv, in, out, err) == 0);
    REQUIRE(repeated(out, "bd-kernel: self-check PASS 19 vectors\n", 1U) && repeated(err, "", 0U));
    REQUIRE(fclose(in) == 0 && fclose(out) == 0 && fclose(err) == 0);
}

/* Every usage error gives 2, the PLK1 usage line on out and the usage text
 * on err; the streams are shared, and the texts are checked at the end. */
static void usage(void) {
    char prog[] = "bd-kernel";
    char self[] = "--self-check";
    char input[] = "--input";
    char records[] = "--records";
    char loops[] = "--loops";
    char hs[] = "--handshake";
    char output[] = "--output";
    char path[] = "bd-kernel-test-input.bin";
    char one[] = "1";
    char zero[] = "0";
    char past[] = "14337";
    char loops_past[] = "1000001";
    char eight[] = "00000001";
    char bad[] = "1x";
    char empty[] = "";
    char bogus[] = "--bogus";
    char *only[] = {prog, NULL};
    char *self_extra[] = {prog, self, one, NULL};
    char *unknown[] = {prog, bogus, NULL};
    char *records_zero[] = {prog, input, path, records, zero, loops, one, NULL};
    char *records_past[] = {prog, input, path, records, past, loops, one, NULL};
    char *loops_zero[] = {prog, input, path, records, one, loops, zero, NULL};
    char *loops_high[] = {prog, input, path, records, one, loops, loops_past, NULL};
    char *eight_digits[] = {prog, input, path, records, eight, loops, one, NULL};
    char *bad_digit[] = {prog, input, path, records, bad, loops, one, NULL};
    char *empty_value[] = {prog, input, path, records, empty, loops, one, NULL};
    char *no_input[] = {prog, records, one, loops, one, NULL};
    char *no_loops[] = {prog, input, path, records, one, NULL};
    char *order[] = {prog, records, one, input, path, loops, one, NULL};
    char *two_inputs[] = {prog, input, path, input, path, records, one, loops, one, NULL};
    char *two_handshakes[] = {prog, input, path, records, one, loops, one, hs, hs, NULL};
    char *early_handshake[] = {prog, hs, input, path, records, one, loops, one, NULL};
    char *no_output[] = {prog, input, path, records, one, loops, one, output, NULL};
    char *after_output[] = {prog, input, path, records, one, loops, one, output, path, one, NULL};
    char *trailing[] = {prog, input, path, records, one, loops, one, bogus, NULL};
    char *too_many[] = {prog, input, path, records, one, loops, one, hs, output, path, one, NULL};
    FILE *in = tmpfile();
    FILE *out = tmpfile();
    FILE *err = tmpfile();
    REQUIRE(in != NULL && out != NULL && err != NULL);
    REQUIRE(bd_kernel_cli_main(1, only, in, out, err) == 2);
    REQUIRE(bd_kernel_cli_main(3, self_extra, in, out, err) == 2);
    REQUIRE(bd_kernel_cli_main(2, unknown, in, out, err) == 2);
    REQUIRE(bd_kernel_cli_main(7, records_zero, in, out, err) == 2);
    REQUIRE(bd_kernel_cli_main(7, records_past, in, out, err) == 2);
    REQUIRE(bd_kernel_cli_main(7, loops_zero, in, out, err) == 2);
    REQUIRE(bd_kernel_cli_main(7, loops_high, in, out, err) == 2);
    REQUIRE(bd_kernel_cli_main(7, eight_digits, in, out, err) == 2);
    REQUIRE(bd_kernel_cli_main(7, bad_digit, in, out, err) == 2);
    REQUIRE(bd_kernel_cli_main(7, empty_value, in, out, err) == 2);
    REQUIRE(bd_kernel_cli_main(5, no_input, in, out, err) == 2);
    REQUIRE(bd_kernel_cli_main(5, no_loops, in, out, err) == 2);
    REQUIRE(bd_kernel_cli_main(7, order, in, out, err) == 2);
    REQUIRE(bd_kernel_cli_main(9, two_inputs, in, out, err) == 2);
    REQUIRE(bd_kernel_cli_main(9, two_handshakes, in, out, err) == 2);
    REQUIRE(bd_kernel_cli_main(8, early_handshake, in, out, err) == 2);
    REQUIRE(bd_kernel_cli_main(8, no_output, in, out, err) == 2);
    REQUIRE(bd_kernel_cli_main(10, after_output, in, out, err) == 2);
    REQUIRE(bd_kernel_cli_main(8, trailing, in, out, err) == 2);
    REQUIRE(bd_kernel_cli_main(11, too_many, in, out, err) == 2);
    REQUIRE(bd_kernel_cli_main(0, NULL, in, out, err) == 2);
    REQUIRE(repeated(out, usage_line, 21U) && repeated(err, usage_text, 21U));
    REQUIRE(fclose(in) == 0 && fclose(out) == 0 && fclose(err) == 0);
}

/* The summary line cannot be written: out is opened only for reading. */
static void summary_write_error(void) {
    char prog[] = "bd-kernel";
    char input[] = "--input";
    char records[] = "--records";
    char loops[] = "--loops";
    char in_name[] = "bd-kernel-test-input.bin";
    char one[] = "1";
    write_input(1U, 3U, 0U);
    char *plain[] = {prog, input, in_name, records, one, loops, one, NULL};
    FILE *in = tmpfile();
    FILE *out = fopen(input_path, "rb");
    FILE *err = tmpfile();
    REQUIRE(in != NULL && out != NULL && err != NULL);
    REQUIRE(bd_kernel_cli_main(7, plain, in, out, err) == 4);
    REQUIRE(fclose(in) == 0 && fclose(out) == 0 && fclose(err) == 0);
    REQUIRE(remove(input_path) == 0);
}

int main(void) {
    fill_request();
    self_check();
    usage();
    summary_write_error();
    return 0;
}
