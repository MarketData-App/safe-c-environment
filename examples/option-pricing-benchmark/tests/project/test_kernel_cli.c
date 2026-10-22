#define _GNU_SOURCE
#define PL_TEST_KERNEL
#include "pl_test_batch.h"

/* Tests derived from specs/project/batch.md "pl-kernel command line": the modes and the usage
 * errors. The commands are texts of space-separated arguments after the program name (the word
 * EMPTY is an empty argument), split once at the start. The pl-kernel tests are three files
 * (test_kernel_cli.c, test_kernel_run.c, test_kernel_modes.c): the fixed GCC analyzer budget of
 * one translation unit. REQUIRE stays active under NDEBUG. */

#define INPUT "pl-kernel-cli-test-input.bin"
#define OUT_A "pl-kernel-cli-test-a.bin"
#define CANON_A "pl-kernel-cli-test-ca.bin"
#define TRACE "pl-kernel-cli-test-trace.bin"
#define OPT "--case option-chain-greeks --input " INPUT " --records "
#define SCAN "--case record-scan --input " INPUT " --records "
#define WINDOW " --dte-min 7 --dte-max 60 --moneyness-lo 0.9 --moneyness-hi "
#define ARGS_CAP 32u
#define LINE_CAP 200u

/* Command 0 and 1: the parameters; commands 2 and later: usage errors (each one value or option
 * wrong). */
static char texts[][LINE_CAP] = {
    "--print-params",
    "--print-params --self-check",
    OPT "20001",
    OPT "0",
    OPT "EMPTY",
    OPT "+8",
    OPT "8x",
    OPT "00000008",
    OPT "-8",
    OPT,
    "--case option-chain-greeks --input " INPUT,
    "--case option-chain-greeks --records 8",
    "--input " INPUT " --records 8",
    "--case chain --input " INPUT " --records 8",
    "--case EMPTY --input " INPUT " --records 8",
    OPT "8 --threads 5",
    OPT "8 --threads 4294967296",
    OPT "8 --models 0",
    OPT "8 --models 32",
    OPT "8 --loops 0",
    OPT "8 --loops 1000001",
    OPT "8 --records 8",
    OPT "8 --echo --echo",
    OPT "8 --dte-min 7",
    OPT "8 --output",
    OPT "8 --bogus",
    SCAN "8 --echo" WINDOW "1.1",
    SCAN "8 --models 1" WINDOW "1.1",
    SCAN "8 --output " OUT_A WINDOW "1.1",
    SCAN "8",
    SCAN "8 --dte-min 7 --dte-max 60 --moneyness-lo 0.9",
    SCAN "8" WINDOW "x",
    SCAN "8" WINDOW "inf",
    SCAN "8" WINDOW "nan",
    SCAN "8" WINDOW "1.1x",
    SCAN "8" WINDOW "EMPTY",
    SCAN "8" WINDOW "1.1 --threads 1",
    SCAN "8 --dte-min --7 --dte-max 60 --moneyness-lo 0.9 --moneyness-hi 1.1",
    SCAN "8 --dte-min 9223372036854775808 --dte-max 60 --moneyness-lo 0.9 --moneyness-hi 1.1",
    SCAN "8 --dte-min - --dte-max 60 --moneyness-lo 0.9 --moneyness-hi 1.1",
    "--case probe --input " INPUT " --records 8 --threads 1",
    "--case probe --input " INPUT " --records 8 --canonical " CANON_A,
    "--case probe --input " INPUT " --records 8 --trace " TRACE,
    "--case probe --input " INPUT " --records 8 --echo",
};
#define NCMD (sizeof texts / sizeof *texts)

static char name[] = "pl-kernel";
static char *argvs[NCMD][ARGS_CAP];
static int argcs[NCMD];

/* Splits every command text at its spaces (strtok_r, in place) into argvs, once at the start; a
 * word EMPTY becomes an empty argument. One call site: the GCC analyzer budget. */
static void split_all(void) {
    for (size_t k = ZERO; k < NCMD; k++) {
        char **a = *(argvs + k);
        *a = name;
        size_t n = ZERO + 1u;
        char *save = NULL;
        char *word = strtok_r(*(texts + k), " ", &save);
        while (word != NULL && n + 1u < ARGS_CAP) {
            const unsigned keep = (unsigned)(strcmp(word, "EMPTY") != 0);
            *word = (char)((unsigned)(unsigned char)*word * keep); /* EMPTY -> "" (branch-free) */
            *(a + n) = word;
            n++;
            word = strtok_r(NULL, " ", &save);
        }
        *(a + n) = NULL;
        *(argcs + k) = (int)n;
    }
}

/* Command k of texts. */
static int cmd(size_t k) { return pl_tk_run(*(argcs + k), *(argvs + k)); }

static char self[] = "--self-check", bad[] = "--unknown";
static char prefix[] = "--self-chec", longer[] = "--self-check2";
static char *ok_args[] = {name, self, NULL};
static char *bad_args[] = {name, bad, NULL};
static char *none_args[] = {name, NULL};
static char *null_args[] = {name, NULL, NULL};
static char *prefix_args[] = {name, prefix, NULL};
static char *longer_args[] = {name, longer, NULL};
static char *extra_args[] = {name, self, self, NULL};

/* argv lists with argc: --self-check (0); an unknown option, no argument, argc 0, a NULL
 * argv[1], a NULL argv, a one-byte-short prefix, a one-byte extension, two arguments and argc -1
 * (2). */
static const int usage_argc[] = {2, 2, 1, 0, 2, 2, 2, 2, 3, -1};
static const int usage_code[] = {0, 2, 2, 2, 2, 2, 2, 2, 2, 2};

static void usage(void) {
    char **usage_argv[10];
    *(usage_argv + 0) = ok_args;
    *(usage_argv + 1) = bad_args;
    *(usage_argv + 2) = none_args;
    *(usage_argv + 3) = none_args;
    *(usage_argv + 4) = null_args;
    *(usage_argv + 5) = NULL;
    *(usage_argv + 6) = prefix_args;
    *(usage_argv + 7) = longer_args;
    *(usage_argv + 8) = extra_args;
    *(usage_argv + 9) = none_args;
    for (size_t k = ZERO; k < 10u; k++) {
        const int code = pl_tk_run(*(usage_argc + k), *(usage_argv + k));
        CHECK("kernel-cli", k, code == *(usage_code + k));
    }
    REQUIRE(pl_tk_run(2, ok_args) == 0 && pl_tk_has("PLK1 status=OK self_check=4\n"));
    REQUIRE(pl_tk_run(2, bad_args) == 2 && pl_tk_has("PLK1 status=FAIL reason=usage\n"));
    REQUIRE(pl_tk_run_full(2, ok_args) == 4);
    /* The alo_scheme values of spec Amendment I item I2.2 (accurateScheme 25, 5, 13, 1e-8, Auto):
     * --print-params prints the C ALO constants of pl_alo.h (Task 10b), and test_alo.c compares
     * those constants with the case-version-3 manifest key alo_scheme (PL_VEC_ALO_SCHEME_*), so
     * this line matches the manifest (ruling (b)). */
    REQUIRE(cmd(0u) == 0);
    REQUIRE(strcmp(tk_text, "PLPARAMS crr_steps=100 alo_scheme=accurateScheme l=25 m=5 n=13 "
                            "eps=0x1.5798ee2308c3ap-27 fp_equation=Auto\n") == 0);
    REQUIRE(pl_tk_run_full(*argcs, *argvs) == 4);
    REQUIRE(cmd(1u) == 2);
    puts("PASS kernel-cli");
}

static void option_usage(void) {
    for (size_t k = ZERO + 2u; k < NCMD; k++) {
        const int code = cmd(k);
        CHECK("option-usage", k, (code == 2) & pl_tk_has("PLK1 status=FAIL reason=usage\n"));
    }
    puts("PASS option-usage");
}

int main(void) {
    pl_tk_setup();
    split_all();
    usage();
    option_usage();
    pl_tk_teardown();
    return 0;
}
