#define _GNU_SOURCE
#include "pl_test_serve.h"
#include "pl_worker_cli.h"

/* Test derived from specs/project/serve.md "Command line": usage errors. The default stdio run is
 * in test_worker_std.c and the --files runs in test_worker_files.c. Group: usage. REQUIRE stays
 * active under NDEBUG. */

#define IN_PATH "pl-worker-test-in.bin"

static char nm[] = "pl-worker";
static char err_text[512];
static FILE *err_f;

/* Runs pl_worker_main over argv (argc words) and keeps the stderr text. */
static int run(int argc, char **argv) {
    REQUIRE(ftruncate(fileno(err_f), 0) == 0 && fseek(err_f, 0L, SEEK_SET) == 0);
    const int rc = pl_worker_main(argc, argv, err_f);
    REQUIRE(fflush(err_f) == 0);
    const ssize_t n = pread(fileno(err_f), err_text, sizeof err_text - 1u, 0);
    REQUIRE(n >= 0);
    *(err_text + n) = '\0';
    return rc;
}

static int has(const char *part) { return strstr(err_text, part) != NULL; }

/* One argument list that must be a usage error (exit 2 and the usage line). */
struct ucase {
    int argc;
    char **argv;
    const char *why;
};

static void usage(void) {
    char shm_in[] = "--shm-in", shm_out[] = "--shm-out", three[] = "3", four[] = "4", two[] = "2";
    char big[] = "1024", text[] = "abc", long_text[] = "00003";
    char echo[] = "--echo", files_word[] = "--files", bad[] = "--bogus";
    char a_path[] = IN_PATH;
    char *only_in[] = {nm, shm_in, three, NULL};
    char *only_out[] = {nm, shm_out, three, NULL};
    char *fd_two[] = {nm, shm_in, two, shm_out, four, NULL};
    char *same[] = {nm, shm_in, three, shm_out, three, NULL};
    char *too_big[] = {nm, shm_in, big, shm_out, four, NULL};
    char *not_number[] = {nm, shm_in, text, shm_out, four, NULL};
    char *too_long[] = {nm, shm_in, long_text, shm_out, four, NULL};
    char *unknown[] = {nm, bad, NULL};
    char *repeated[] = {nm, echo, echo, NULL};
    char *one_file[] = {nm, files_word, a_path, NULL};
    char *missing_value[] = {nm, shm_in, NULL};
    char *null_word[] = {nm, NULL, echo, NULL};
    const struct ucase cases[] = {
        {3, only_in, "the option --shm-in without its partner --shm-out"},
        {3, only_out, "the option --shm-out without its partner --shm-in"},
        {5, fd_two, "a descriptor number below the lowest allowed one (3)"},
        {5, same, "the same descriptor number for both regions"},
        {5, too_big, "a descriptor number above the highest allowed one (1023)"},
        {5, not_number, "a descriptor text that is no decimal number"},
        {5, too_long, "a descriptor text of more than four digits"},
        {2, unknown, "an option that pl-worker does not have"},
        {3, repeated, "an option that is given twice on the line"},
        {3, one_file, "--files with one path where two are required"},
        {2, missing_value, "an option at the end of the line without its value"},
        {3, null_word, "a NULL word in the middle of the argument list"},
    };
    for (size_t k = ZERO; k < 12u; k++) {
        const struct ucase *c = cases + k;
        const int rc = run(c->argc, c->argv);
        if (rc != 2) {
            (void)fprintf(stderr, "not a usage error: %s\n", c->why);
        }
        REQUIRE(rc == 2 && has("usage: pl-worker"));
    }
    REQUIRE(run(1, NULL) == 2);
    puts("PASS usage");
}

int main(void) {
    err_f = tmpfile();
    REQUIRE(err_f != NULL);
    ts_fill_rows();
    usage();
    REQUIRE(fclose(err_f) == 0);
    return 0;
}
