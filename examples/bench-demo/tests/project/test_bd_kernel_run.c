#include "bd_wire.h"
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* bd-kernel run tests derived from specs/project/bd_wire.md: runs with and
 * without the handshake (the PLK1 line and the output file) and the largest
 * request. Files are written in the current directory and removed at the
 * end. REQUIRE stays active under NDEBUG and has no side effects of its own;
 * the helpers combine their checks without branches, so GCC -fanalyzer
 * explores few paths. */

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
struct kernel_run {
    int rc;
    unsigned int ok;
    char out[TEXT_SIZE];
    char err[TEXT_SIZE];
};

/* Runs bd_kernel_cli_main with in holding the bytes of handshake_in. r.ok is
 * 1 when every file step succeeded. Both texts are NUL-terminated. */
static struct kernel_run run(int argc, char **argv, const char *handshake_in) {
    struct kernel_run r = {0, 0U, {0}, {0}};
    FILE *in = tmpfile();
    FILE *out = tmpfile();
    FILE *err = tmpfile();
    REQUIRE(in != NULL && out != NULL && err != NULL);
    const int put = fputs(handshake_in, in);
    const int start = fseek(in, 0L, SEEK_SET);
    r.rc = bd_kernel_cli_main(argc, argv, in, out, err);
    const int out_start = fseek(out, 0L, SEEK_SET);
    const int err_start = fseek(err, 0L, SEEK_SET);
    (void)fread(r.out, 1U, sizeof r.out - 1U, out);
    (void)fread(r.err, 1U, sizeof r.err - 1U, err);
    const int in_closed = fclose(in);
    const int out_closed = fclose(out);
    const int err_closed = fclose(err);
    r.ok = AS_BIT(put >= 0) & AS_BIT(start == 0) & AS_BIT(out_start == 0) & AS_BIT(err_start == 0);
    r.ok &= AS_BIT(in_closed == 0) & AS_BIT(out_closed == 0) & AS_BIT(err_closed == 0);
    return r;
}

static const char output_path[] = "bd-kernel-test-output.bin";
static unsigned char expect_bytes[BD_OUTPUT_MAX_BYTES];
static unsigned char got_bytes[BD_OUTPUT_MAX_BYTES + 1];

static uint64_t fnv(const unsigned char *bytes, size_t length) {
    uint64_t hash = BD_FNV_OFFSET;
    for (size_t index = 0U; index < length; ++index) {
        uint64_t product = 0U;
        (void)__builtin_mul_overflow(hash ^ (uint64_t)*(bytes + index), BD_FNV_PRIME, &product);
        hash = product;
    }
    return hash;
}

/* The run wrote prefix and then the PLK1 OK line for n records and L loops,
 * and the output file holds the digest of the request. */
static unsigned int run_ok(const struct kernel_run *r, const char *prefix, size_t n,
                           unsigned int loops) {
    size_t written = 0U;
    const size_t room = sizeof expect_bytes;
    const enum bd_status st = bd_digest_request(request, n * 12U, expect_bytes, room, &written);
    char counts[TEXT_SIZE] = {0};
    char tail[TEXT_SIZE] = {0};
    const char *line = r->out + strlen(prefix);
    unsigned int ok = r->ok & AS_BIT(st == BD_OK) & AS_BIT(r->rc == 0);
    ok &= AS_BIT(strncmp(r->out, prefix, strlen(prefix)) == 0);
    ok &= AS_BIT(strncmp(line, "PLK1 status=OK case=bd-digest ", 30U) == 0);
    const int made = snprintf(counts, sizeof counts, "records=%zu loops=%u threads=0 ", n, loops);
    ok &= AS_BIT(made > 0) & AS_BIT(strncmp(line + 30, counts, strlen(counts)) == 0);
    ok &= AS_BIT(strstr(line, " threads=0 mono_ns=") != NULL);
    ok &= AS_BIT(strstr(line, " cpu_ns=") != NULL);
    ok &= AS_BIT(strstr(line, " chunks=0 chunk_sizes= chunk_wall_ns= copied_bytes=") != NULL);
    const uint64_t digest = fnv(expect_bytes, written);
    const size_t bytes = n * 12U;
    const int made_tail =
        snprintf(tail, sizeof tail, "=%zu digest=%016" PRIx64 "\n", bytes, digest);
    const size_t out_length = strlen(r->out);
    const size_t tail_length = strlen(tail);
    ok &= AS_BIT(made_tail > 0) & AS_BIT(out_length > tail_length);
    ok &= AS_BIT(strcmp(r->out + out_length - tail_length, tail) == 0);
    FILE *file = fopen(output_path, "rb");
    REQUIRE(file != NULL);
    const size_t got = fread(got_bytes, 1U, sizeof got_bytes, file);
    const int closed = fclose(file);
    const int same = memcmp(got_bytes, expect_bytes, written);
    return ok & AS_BIT(closed == 0) & AS_BIT(got == written) & AS_BIT(same == 0);
}

static void runs(void) {
    char prog[] = "bd-kernel";
    char input[] = "--input";
    char records[] = "--records";
    char loops[] = "--loops";
    char hs[] = "--handshake";
    char output[] = "--output";
    char in_name[] = "bd-kernel-test-input.bin";
    char out_name[] = "bd-kernel-test-output.bin";
    char one[] = "1";
    char two[] = "2";
    char three[] = "3";
    char max[] = "14336";
    char *plain[] = {prog, input, in_name, records, three, loops, two, output, out_name, NULL};
    char *hand[] = {prog, input, in_name, records, three, loops, two, hs, output, out_name, NULL};
    write_input(3U, 1000000U, 0U);
    struct kernel_run r = run(9, plain, "");
    REQUIRE(run_ok(&r, "", 3U, 2U));
    r = run(10, hand, "GF");
    REQUIRE(run_ok(&r, "BE", 3U, 2U));
    /* The largest request, one loop. */
    write_input(14336U, 1000U, 0U);
    char *largest[] = {prog, input, in_name, records, max, loops, one, output, out_name, NULL};
    r = run(9, largest, "");
    REQUIRE(run_ok(&r, "", 14336U, 1U));
    REQUIRE(remove(input_path) == 0 && remove(output_path) == 0);
}

int main(void) {
    fill_request();
    runs();
    return 0;
}
