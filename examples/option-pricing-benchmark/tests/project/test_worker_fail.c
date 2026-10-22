#define _GNU_SOURCE
#include "pl_io.h"
#include "pl_test_serve.h"
#include "pl_worker_cli.h"

/* Test derived from specs/project/serve.md "Command line": a protocol error (exit 1), the shm
 * option numbers 3 and 1023, and a missing input file (exit 4). Group: failures. REQUIRE stays
 * active under NDEBUG. */

#define IN_PATH "pl-worker-test-in.bin"
#define OUT_PATH "pl-worker-test-out.bin"

static char nm[] = "pl-worker";
static char err_text[512];
static FILE *err_f;

static const struct ts_req BAD = TS_REQ(PL_FRAME_REQUEST, 3u, 1u, 9u, 1u, 64u, 0u);
static const struct ts_req QUIT = TS_REQ(PL_FRAME_SHUTDOWN, 0u, 0u, 0u, 0u, 0u, 0u);

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

static void failures(void) {
    char flag[] = "--files", in[] = IN_PATH, out[] = OUT_PATH;
    char shm_in[] = "--shm-in", shm_out[] = "--shm-out", low[] = "3", top[] = "1023";
    char *plain[] = {nm, flag, in, out, NULL};
    /* the numbers 3 and 1023 select the shm route; an immediate SHUTDOWN needs no region */
    char *shm_files[] = {nm, shm_in, low, shm_out, top, flag, in, out, NULL};
    FILE *f = fopen(IN_PATH, "wb");
    REQUIRE(f != NULL);
    ts_flush(f, ts_put(0u, &BAD));
    REQUIRE(run(4, plain) == 1 && has("PLW1 exit=1 requests=0\n"));
    ts_flush(f, ts_put(0u, &QUIT));
    REQUIRE(run(8, shm_files) == 0 && has("PLW1 exit=0 requests=0\n"));
    REQUIRE(fclose(f) == 0 && remove(IN_PATH) == 0);
    REQUIRE(run(4, plain) == 4 && has("PLW1 exit=4 requests=0\n")); /* the input is missing */
    REQUIRE(remove(OUT_PATH) == 0);
    puts("PASS failures");
}

int main(void) {
    err_f = tmpfile();
    REQUIRE(err_f != NULL);
    ts_fill_rows();
    failures();
    REQUIRE(fclose(err_f) == 0);
    return 0;
}
