#define _GNU_SOURCE
#define PL_TEST_KERNEL
#include "pl_test_batch.h"
#include <unistd.h>

/* Tests derived from specs/project/batch.md "pl-kernel command line": one-model masks (mask 1
 * is ocg-v1m with only bsm, mask 16 follows PL_MASK_WIRED) and echo. A file of its own: the fixed
 * GCC analyzer budget of one translation unit. The input and output files are written under the
 * current directory and removed at the end. REQUIRE stays active under NDEBUG. */

#define INPUT "pl-kernel-masks-test-input.bin"
#define CANON_C "pl-kernel-masks-test-cc.bin"
#define CANON_D "pl-kernel-masks-test-cd.bin"
#define CANON_E "pl-kernel-masks-test-ce.bin"

static char nm[] = "pl-kernel";

/* The argument words of the commands (mutable arrays: argv is char **). */
static char ka[] = "--case";
static char kb[] = "option-chain-greeks";
static char kc[] = "--input";
static char kd[] = "pl-kernel-masks-test-input.bin";
static char ke[] = "--records";
static char kf[] = "8";
static char kk[] = "--canonical";
static char kt[] = "--models";
static char ku[] = "1";
static char kv[] = "pl-kernel-masks-test-cc.bin";
static char kw[] = "16";
static char kx[] = "pl-kernel-masks-test-cd.bin";
static char ky[] = "31";
static char kz[] = "--echo";
static char kba[] = "pl-kernel-masks-test-ce.bin";

/* The commands (argv lists after the program name nm). */
static char *c_mask1[] = {nm, ka, kb, kc, kd, ke, kf, kt, ku, kk, kv, NULL};
static char *c_mask16[] = {nm, ka, kb, kc, kd, ke, kf, kt, kw, kk, kx, NULL};
static char *c_echo31[] = {nm, ka, kb, kc, kd, ke, kf, kt, ky, kz, NULL};
static char *c_echo_canonical[] = {nm, ka, kb, kc, kd, ke, kf, kz, kk, kba, NULL};

/* One-model masks and echo: mask 1 is ocg-v1m with only bsm; mask 16 follows PL_MASK_WIRED. */
static void option_masks(void) {
    REQUIRE(PL_TK_CMD(c_mask1) == 0 && pl_tk_has(" models=1 evals=bsm:"));
    REQUIRE(pl_tk_has(" red=bsm:") && pl_tk_has(" digest=") && !pl_tk_has("digest=none"));
    REQUIRE(!pl_tk_has(";") && !pl_tk_has("bjs:")); /* one red= part, no other model */
    REQUIRE(pl_tk_file_starts(CANON_C, "{\"digest_form\":\"ocg-v1m\",\"mask\":1,"));
    const int code = PL_TK_CMD(c_mask16);
    if ((PL_MASK_WIRED & 16u) == 0u) { /* the ALO stub until Task 10b (ruling 46) */
        REQUIRE(code == 3 && pl_tk_has("PLK1 status=FAIL reason=kernel\n"));
    } else {
        REQUIRE(code == 0 && pl_tk_has(" models=16 evals=alo:") && !pl_tk_has("bsm:"));
        const char *head = "{\"digest_form\":\"ocg-v1m\",\"mask\":16,\"models\":{\"alo\":";
        REQUIRE(pl_tk_file_starts(CANON_D, head));
        REQUIRE(remove(CANON_D) == 0);
    }
    REQUIRE(PL_TK_CMD(c_echo31) == 0);
    REQUIRE(pl_tk_has(" evals=bsm:0,bjs:0,crr:0,baw:0,alo:0 red="));
    REQUIRE(pl_tk_has(" red=bsm:0,0,0,0,0,0,0,0,0:null:-1;bjs:"));
    REQUIRE(pl_tk_has(" digest=none\n")); /* the canonical writer refuses the echo status 255 */
    /* --echo with --canonical fails closed: a usage error, nothing written. */
    REQUIRE(PL_TK_CMD(c_echo_canonical) == 2);
    REQUIRE(pl_tk_has("PLK1 status=FAIL reason=usage\n"));
    REQUIRE(access(CANON_E, F_OK) != 0);
    puts("PASS option-masks");
}

int main(void) {
    pl_tk_setup();
    pl_tk_write_option_input(INPUT);
    option_masks();
    pl_tk_teardown();
    REQUIRE(remove(INPUT) == 0 && remove(CANON_C) == 0);
    return 0;
}
