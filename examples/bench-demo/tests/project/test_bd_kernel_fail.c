#include "bd_wire.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* bd-kernel failure tests derived from specs/project/bd_wire.md: a wrong
 * first handshake byte, a missing F, missing, short and long input files, an
 * unwritable output file and steps above the limit. Files are written in the
 * current directory and removed at the end. REQUIRE stays active under
 * NDEBUG and has no side effects of its own. */

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

static const char output_path[] = "bd-kernel-test-output.bin";

/* Every failed run appends its PLK1 line to one shared out stream; the
 * handshake bytes of the two handshake runs come from one shared in stream
 * ("X", then "G" and EOF). The text is checked once at the end. */
static void failures(void) {
    char prog[] = "bd-kernel";
    char input[] = "--input";
    char records[] = "--records";
    char loops[] = "--loops";
    char hs[] = "--handshake";
    char output[] = "--output";
    char in_name[] = "bd-kernel-test-input.bin";
    char missing[] = "bd-kernel-test-missing.bin";
    char no_dir[] = "bd-kernel-test-no-dir/out.bin";
    char two[] = "2";
    char three[] = "3";
    char four[] = "4";
    char *hand[] = {prog, input, in_name, records, three, loops, two, hs, NULL};
    char *missing_in[] = {prog, input, missing, records, three, loops, two, NULL};
    char *more[] = {prog, input, in_name, records, four, loops, two, NULL};
    char *fewer[] = {prog, input, in_name, records, two, loops, two, NULL};
    char *steps[] = {prog, input, in_name, records, three, loops, two, NULL};
    char *bad_output[] = {prog, input, in_name, records, three, loops, two, output, no_dir, NULL};
    FILE *in = tmpfile();
    FILE *out = tmpfile();
    FILE *err = tmpfile();
    REQUIRE(in != NULL && out != NULL && err != NULL);
    REQUIRE(fputs("XG", in) >= 0 && fseek(in, 0L, SEEK_SET) == 0);
    write_input(3U, 7U, 0U);
    unsigned int ok = AS_BIT(bd_kernel_cli_main(8, hand, in, out, err) == 4);
    ok &= AS_BIT(bd_kernel_cli_main(8, hand, in, out, err) == 4);
    ok &= AS_BIT(bd_kernel_cli_main(7, missing_in, in, out, err) == 2);
    ok &= AS_BIT(bd_kernel_cli_main(7, more, in, out, err) == 2);
    ok &= AS_BIT(bd_kernel_cli_main(7, fewer, in, out, err) == 2);
    ok &= AS_BIT(bd_kernel_cli_main(9, bad_output, in, out, err) == 4);
    write_input(3U, 1000001U, 0U);
    ok &= AS_BIT(bd_kernel_cli_main(7, steps, in, out, err) == 2);
    static const char want[] = "BPLK1 status=FAIL reason=io\n"
                               "BEPLK1 status=FAIL reason=io\n"
                               "PLK1 status=FAIL reason=input\n"
                               "PLK1 status=FAIL reason=input\n"
                               "PLK1 status=FAIL reason=input\n"
                               "PLK1 status=FAIL reason=io\n"
                               "PLK1 status=FAIL reason=input\n";
    char got[sizeof want + 16] = {0};
    const int start = fseek(out, 0L, SEEK_SET);
    const size_t count = fread(got, 1U, sizeof got - 1U, out);
    ok &= AS_BIT(start == 0) & AS_BIT(count == sizeof want - 1U) & AS_BIT(strcmp(got, want) == 0);
    REQUIRE(ok);
    REQUIRE(fclose(in) == 0 && fclose(out) == 0 && fclose(err) == 0);
    REQUIRE(remove(input_path) == 0);
    REQUIRE(remove(output_path) != 0);
}

int main(void) {
    fill_request();
    failures();
    return 0;
}
