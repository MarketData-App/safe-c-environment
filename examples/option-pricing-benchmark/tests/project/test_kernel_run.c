#define _GNU_SOURCE
#define PL_TEST_KERNEL
#include "pl_canonical.h"
#include "pl_test_batch.h"
#include <inttypes.h>

/* Tests derived from specs/project/batch.md "pl-kernel command line" and "Kernel digest": the
 * option case serially and with two workers (equal outputs and canonical bytes), the PLK1
 * digest= of the canonical bytes, and the trace. The input and output files are written under
 * the current directory and removed at the end. REQUIRE stays active under NDEBUG. */

#define INPUT "pl-kernel-run-test-input.bin"
#define OUT_A "pl-kernel-run-test-a.bin"
#define OUT_B "pl-kernel-run-test-b.bin"
#define CANON_A "pl-kernel-run-test-ca.bin"
#define CANON_B "pl-kernel-run-test-cb.bin"
#define TRACE "pl-kernel-run-test-trace.bin"
#define TRACE_S "pl-kernel-run-test-trace-serial.bin"

static char nm[] = "pl-kernel";

/* The argument words of the commands (mutable arrays: argv is char **). */
static char ka[] = "--case";
static char kb[] = "option-chain-greeks";
static char kc[] = "--input";
static char kd[] = "pl-kernel-run-test-input.bin";
static char ke[] = "--records";
static char kf[] = "8";
static char kg[] = "--threads";
static char kh[] = "0";
static char ki[] = "--output";
static char kj[] = "pl-kernel-run-test-a.bin";
static char kk[] = "--canonical";
static char kl[] = "pl-kernel-run-test-ca.bin";
static char km[] = "--loops";
static char kn[] = "2";
static char ko[] = "pl-kernel-run-test-b.bin";
static char kp[] = "pl-kernel-run-test-cb.bin";
static char kq[] = "--trace";
static char kr[] = "pl-kernel-run-test-trace.bin";
static char ks[] = "pl-kernel-run-test-trace-serial.bin";

/* The commands (argv lists after the program name nm). */
static char *c_serial[] = {nm, ka, kb, kc, kd, ke, kf, kg, kh, ki, kj, kk, kl, km, kn, NULL};
static char *c_pooled[] = {nm, ka, kb, kc, kd, ke, kf, kg, kn, ki, ko, kk, kp, NULL};
static char *c_trace[] = {nm, ka, kb, kc, kd, ke, kf, kg, kn, kq, kr, NULL};
static char *c_trace_serial[] = {nm, ka, kb, kc, kd, ke, kf, kg, kh, kq, ks, NULL};

/* 1 when the file holds exactly three lines (three newlines, the last one the last byte):
 * memchr, no loop (the GCC analyzer budget). */
static int three_lines(const char *path) {
    const size_t n = pl_tk_read_file(path, tk_a);
    const uint8_t *end = tk_a + n;
    const uint8_t *a = memchr(tk_a, '\n', n);
    const uint8_t *b = a == NULL ? NULL : memchr(a + 1, '\n', (size_t)(end - (a + 1)));
    const uint8_t *c = b == NULL ? NULL : memchr(b + 1, '\n', (size_t)(end - (b + 1)));
    return c != NULL && c + 1 == end;
}

/* 1 when the out text of the last run holds " digest=<16 hex>" with the FNV-1a 64 of the bytes of
 * the canonical file at path: the text is NUL-terminated in tk_a and goes through pl_sink_text
 * into a digest sink (no loop here: the GCC analyzer budget). */
static int digest_matches(const char *path) {
    const size_t n = pl_tk_read_file(path, tk_a);
    if (n == 0u || n >= PL_TK_FILE_CAP) {
        return 0;
    }
    *(tk_a + n) = 0u;
    struct pl_sink d = {-1, NULL, 0u, 0u, 0, 0u, 0u};
    pl_sink_text(&d, (const char *)tk_a);
    char want[32];
    const int w = snprintf(want, sizeof want, " digest=%016" PRIx64, pl_sink_fnv(&d));
    return w == 24 && d.total == n && pl_tk_has(want);
}

/* The option case on eight rows: serial and two workers give equal outputs and canonical bytes;
 * the PLK1 digest= is the digest of the canonical file. */
static void option_case(void) {
    pl_tk_write_option_input(INPUT);
    REQUIRE(PL_TK_CMD(c_serial) == 0);
    REQUIRE(digest_matches(CANON_A) && !pl_tk_has("digest=none"));
    REQUIRE(pl_tk_has("PLK1 status=OK case=option-chain-greeks records=8 loops=2 threads=0 "));
    REQUIRE(pl_tk_has(" chunks=0 chunk_sizes= chunk_wall_ns= ") && !pl_tk_has(";baw:"));
    REQUIRE(PL_TK_CMD(c_pooled) == 0);
    REQUIRE(pl_tk_has(" chunks=2 chunk_sizes=4,4 chunk_wall_ns="));
    REQUIRE(pl_tk_has(" copied_bytes=512 models=7 evals=bsm:") && !pl_tk_has(",baw:"));
    REQUIRE(PL_TK_CMD(c_trace) == 0 && pl_tk_has(" red=bsm:") && pl_tk_has(";crr:"));
    REQUIRE(PL_TK_CMD(c_trace_serial) == 0 && pl_tk_read_file(TRACE_S, tk_a) > 0u);
    REQUIRE(pl_tk_same_files(OUT_A, OUT_B) && pl_tk_same_files(CANON_A, CANON_B));
    REQUIRE(pl_tk_read_file(OUT_A, tk_a) == 8u * PL_RESPONSE_RECORD_BYTES);
    REQUIRE(pl_tk_file_starts(CANON_A, "{\"digest_form\":\"ocg-v1\",\"models\":{\"bjs\":"));
    /* The trace: a header line and two task lines. */
    REQUIRE(pl_tk_file_starts(TRACE, "# workers=") && three_lines(TRACE));
    puts("PASS option-case");
}

int main(void) {
    pl_tk_setup();
    option_case();
    pl_tk_teardown();
    REQUIRE(remove(INPUT) == 0 && remove(OUT_A) == 0 && remove(OUT_B) == 0);
    REQUIRE(remove(CANON_A) == 0 && remove(CANON_B) == 0);
    REQUIRE(remove(TRACE) == 0 && remove(TRACE_S) == 0);
    return 0;
}
