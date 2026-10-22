#define _GNU_SOURCE
#include "pl_test_serve.h"
#include "pl_worker_cli.h"
#include <fcntl.h>

/* Test derived from specs/project/serve.md "Command line": the default stdio run on descriptors 0
 * and 1 with a real request. Group: standard-stream. REQUIRE stays active under NDEBUG. */

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

/* The default stdio route on descriptors 0 and 1, run unconditionally: the test redirects both onto
 * files, sends 8 rows and SHUTDOWN, and restores them. The descriptors of the redirect are kept in
 * file-scope statics (the dup2 results are no new descriptors; the saved copies and the files are
 * closed on every path that returns, a failed REQUIRE exits). */
#define IN_PATH "pl-worker-std-in.bin"
#define OUT_PATH "pl-worker-std-out.bin"

static const struct ts_req ROWS8 = TS_REQ(PL_FRAME_REQUEST, 4u, 8u, 1u, PL_MASK_ALL3, 512u, 512u);
static const struct ts_req QUIT = TS_REQ(PL_FRAME_SHUTDOWN, 0u, 0u, 0u, 0u, 0u, 0u);
static int redirected_in, redirected_out, restored_in, restored_out;

static void standard_stream(void) {
    char counters[] = "--counters";
    char *std[] = {nm, counters, NULL};
    FILE *f = fopen(IN_PATH, "wb");
    REQUIRE(f != NULL);
    size_t at = ts_put(0u, &ROWS8);
    at = ts_put(at, &QUIT);
    ts_flush(f, at);
    REQUIRE(fclose(f) == 0);
    const int saved_in = dup(0);
    const int saved_out = dup(1);
    const int in = open(IN_PATH, O_RDONLY);
    const int out = open(OUT_PATH, O_WRONLY | O_CREAT | O_TRUNC, 0600);
    REQUIRE(saved_in >= 0 && saved_out >= 0 && in >= 0 && out >= 0);
    redirected_in = dup2(in, 0);
    redirected_out = dup2(out, 1);
    const int rc = run(2, std);
    restored_in = dup2(saved_in, 0);
    restored_out = dup2(saved_out, 1);
    REQUIRE(redirected_in == 0 && redirected_out == 1 && restored_in == 0 && restored_out == 1);
    REQUIRE(close(in) == 0 && close(out) == 0 && close(saved_in) == 0 && close(saved_out) == 0);
    REQUIRE(rc == 0);
    REQUIRE(has("PLW1 exit=0 requests=1 calls=bsm:8,bjs:8,crr:8,baw:0,alo:0 evals="));
    REQUIRE(remove(IN_PATH) == 0 && remove(OUT_PATH) == 0);
    puts("PASS standard-stream");
}

int main(void) {
    err_f = tmpfile();
    REQUIRE(err_f != NULL);
    ts_fill_rows();
    standard_stream();
    REQUIRE(fclose(err_f) == 0);
    return 0;
}
