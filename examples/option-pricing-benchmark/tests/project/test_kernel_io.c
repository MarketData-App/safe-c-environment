#define _GNU_SOURCE
#define PL_TEST_KERNEL
#include "pl_test_batch.h"

/* Tests derived from specs/project/batch.md "pl-kernel command line": the input and I/O
 * failures and two requests (14,337 and 20,000 echo records). A file of its own: the fixed GCC
 * analyzer budget of one translation unit. The input and output files are written under the
 * current directory and removed at the end. REQUIRE stays active under NDEBUG. */

#define INPUT "pl-kernel-io-test-input.bin"
#define OUT_A "pl-kernel-io-test-a.bin"
#define OUT_B "pl-kernel-io-test-b.bin"

static char nm[] = "pl-kernel";

/* The argument words of the commands (mutable arrays: argv is char **). */
static char ka[] = "--case";
static char kb[] = "option-chain-greeks";
static char kc[] = "--input";
static char kd[] = "pl-kernel-io-test-input.bin";
static char ke[] = "--records";
static char kf[] = "8";
static char kg[] = "--threads";
static char kh[] = "0";
static char ki[] = "--output";
static char kj[] = "pl-kernel-io-test-a.bin";
static char kk[] = "--canonical";
static char kn[] = "2";
static char ko[] = "pl-kernel-io-test-b.bin";
static char kq[] = "--trace";
static char ku[] = "1";
static char kz[] = "--echo";
static char kbb[] = "4";
static char kbc[] = "/proc/forbidden";
static char kbd[] = "/dev/full";
static char kbe[] = "pl-kernel-io-test-missing.bin";
static char kbf[] = "14337";
static char kbg[] = "20000";

static char *c_four[] = {nm, ka, kb, kc, kd, ke, kbb, NULL};
static char *c_eight[] = {nm, ka, kb, kc, kd, ke, kf, NULL};
static char *c_proc_output[] = {nm, ka, kb, kc, kd, ke, kf, ki, kbc, NULL};
static char *c_proc_canonical[] = {nm, ka, kb, kc, kd, ke, kf, kk, kbc, NULL};
static char *c_proc_trace[] = {nm, ka, kb, kc, kd, ke, kf, kq, kbc, NULL};
static char *c_full_output[] = {nm, ka, kb, kc, kd, ke, kf, ki, kbd, NULL};
static char *c_full_canonical[] = {nm, ka, kb, kc, kd, ke, kf, kk, kbd, NULL};
static char *c_missing[] = {nm, ka, kb, kc, kbe, ke, kf, NULL};
static char *c_r14337_serial[] = {nm, ka, kb, kc, kd, ke, kbf, kz, kg, kh, ki, kj, NULL};
static char *c_r14337_pooled[] = {nm, ka, kb, kc, kd, ke, kbf, kz, kg, kn, ki, ko, NULL};
static char *c_r20000[] = {nm, ka, kb, kc, kd, ke, kbg, kz, kg, kbb, NULL};
static char *c_r1[] = {nm, ka, kb, kc, kd, ke, ku, kz, kg, kbb, NULL};

static uint8_t zeros[20000u * PL_REQUEST_RECORD_BYTES];

/* Input and I/O failures. */
static void input_and_io(void) {
    REQUIRE(PL_TK_CMD(c_four) == 0 && pl_tk_has(" records=4 "));
    REQUIRE(pl_tk_has(" copied_bytes=256 "));
    REQUIRE(PL_TK_CMD(c_proc_output) == 4 && pl_tk_has("PLK1 status=FAIL reason=io\n"));
    REQUIRE(PL_TK_CMD(c_proc_canonical) == 4 && PL_TK_CMD(c_proc_trace) == 4);
    REQUIRE(PL_TK_CMD(c_full_output) == 4 && PL_TK_CMD(c_full_canonical) == 4);
    REQUIRE(pl_tk_run_full((int)(sizeof c_eight / sizeof *c_eight) - 1, c_eight) == 4);
    REQUIRE(PL_TK_CMD(c_missing) == 2 && pl_tk_has("PLK1 status=FAIL reason=input\n"));
    pl_tk_write_file(INPUT, zeros, 7u * PL_REQUEST_RECORD_BYTES); /* a short input file */
    REQUIRE(PL_TK_CMD(c_eight) == 2 && pl_tk_has("PLK1 status=FAIL reason=input\n"));
    puts("PASS input-io");
}

/* Two requests: 14,337 and 20,000 echo records. */
static void requests(void) {
    pl_tk_write_file(INPUT, zeros, sizeof zeros);
    REQUIRE(PL_TK_CMD(c_r14337_serial) == 0);
    REQUIRE(pl_tk_has(" chunks=0 chunk_sizes= chunk_wall_ns= "));
    REQUIRE(PL_TK_CMD(c_r14337_pooled) == 0);
    REQUIRE(pl_tk_has(" chunks=3 chunk_sizes=7168,7168,1 "));
    REQUIRE(pl_tk_same_files(OUT_A, OUT_B) && pl_tk_read_file(OUT_A, tk_a) == 14337u * 290u);
    REQUIRE(PL_TK_CMD(c_r20000) == 0 && pl_tk_has(" copied_bytes=1280000 "));
    REQUIRE(pl_tk_has(" chunk_sizes=3584,3584,3584,3584,1416,1416,1416,1416 "));
    REQUIRE(PL_TK_CMD(c_r1) == 0 && pl_tk_has(" chunks=1 chunk_sizes=1 "));
    puts("PASS requests");
}

int main(void) {
    pl_tk_setup();
    pl_tk_write_option_input(INPUT);
    input_and_io();
    requests();
    pl_tk_teardown();
    REQUIRE(remove(INPUT) == 0 && remove(OUT_A) == 0 && remove(OUT_B) == 0);
    return 0;
}
