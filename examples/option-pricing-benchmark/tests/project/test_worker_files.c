#define _GNU_SOURCE
#include "pl_io.h"
#include "pl_test_serve.h"
#include "pl_worker_cli.h"

/* Test derived from specs/project/serve.md "Command line": the --files run with the PLW1 line and
 * --echo. Group: files. REQUIRE stays active under NDEBUG. */

#define IN_PATH "pl-worker-test-in.bin"
#define OUT_PATH "pl-worker-test-out.bin"

static char nm[] = "pl-worker";
static char err_text[512];
static uint8_t out_bytes[PL_HEADER_BYTES + PL_TS_RECORD_BYTES + 64u];
static FILE *err_f;

static const struct ts_req PING = TS_REQ(PL_FRAME_REQUEST, 1u, 0u, 0u, 1u, 0u, 0u);
static const struct ts_req ECHO8 = TS_REQ(PL_FRAME_REQUEST, 2u, 8u, 0u, PL_MASK_ALL3, 512u, 512u);
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

/* The bytes of OUT_PATH in out_bytes; their number. */
static size_t read_out(void) {
    size_t length = 0u;
    REQUIRE(pl_read_file(OUT_PATH, out_bytes, sizeof out_bytes, &length) == PL_IO_OK);
    return length;
}

static void files_run(void) {
    char flag[] = "--files", in[] = IN_PATH, out[] = OUT_PATH, echo[] = "--echo";
    char *plain[] = {nm, flag, in, out, NULL};
    char *with_echo[] = {nm, echo, flag, in, out, NULL};
    FILE *f = fopen(IN_PATH, "wb");
    REQUIRE(f != NULL);
    size_t at = ts_put(0u, &PING);
    at = ts_put(at, &QUIT);
    ts_flush(f, at);
    REQUIRE(run(4, plain) == 0 && has("PLW1 exit=0 requests=1\n") && !has("calls="));
    REQUIRE(read_out() == 32u && *(out_bytes + 6) == PL_FRAME_RESPONSE);
    ts_flush(f, ts_put(0u, &ECHO8));
    REQUIRE(run(5, with_echo) == 0 && has("PLW1 exit=0 requests=1\n"));
    REQUIRE(read_out() == PL_HEADER_BYTES + PL_TS_RECORD_BYTES + 4u);
    const uint8_t *rec = out_bytes + PL_HEADER_BYTES;
    REQUIRE(*rec == PL_ECHO && *(rec + 1) == PL_ECHO && *(rec + 2) == PL_ECHO);
    REQUIRE(*(rec + 3) == PL_NOT_REQUESTED && *(rec + 4) == PL_NOT_REQUESTED);
    REQUIRE(fclose(f) == 0 && remove(IN_PATH) == 0 && remove(OUT_PATH) == 0);
    puts("PASS files");
}

int main(void) {
    err_f = tmpfile();
    REQUIRE(err_f != NULL);
    ts_fill_rows();
    files_run();
    REQUIRE(fclose(err_f) == 0);
    return 0;
}
