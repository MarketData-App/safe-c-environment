#define _GNU_SOURCE
#include "pl_test_serve.h"
#include "pl_worker_cli.h"

/* Test derived from specs/project/serve.md "Counters": the --counters totals through
 * pl_worker_main; the models outside the mask are never called. Group: counters. REQUIRE stays
 * active under NDEBUG. */

#define FILES_IN "pl-serve-test-in.bin"
#define FILES_OUT "pl-serve-test-out.bin"

static FILE *err_f;
static char err_text[1024];

/* One pl-worker --counters --files run of the models mask; the stderr text in err_text. */
static int run_counters(FILE *file, uint16_t models) {
    char a1[] = "pl-worker", a2[] = "--counters", a3[] = "--files", a4[] = FILES_IN;
    char a5[] = FILES_OUT;
    char *argv[] = {a1, a2, a3, a4, a5, NULL};
    const struct ts_req req = TS_REQ(PL_FRAME_REQUEST, 8u, 8u, 2u, models, 512u, 512u);
    ts_flush(file, ts_put(0u, &req));
    REQUIRE(ftruncate(fileno(err_f), 0) == 0 && fseek(err_f, 0L, SEEK_SET) == 0);
    const int rc = pl_worker_main(5, argv, err_f);
    REQUIRE(fflush(err_f) == 0);
    const ssize_t n = pread(fileno(err_f), err_text, sizeof err_text - 1u, 0);
    REQUIRE(n >= 0);
    *(err_text + n) = '\0';
    return rc;
}

/* The counters: the models outside the mask are never called. */
static void counters(void) {
    const uint16_t list[2] = {1u, 16u};
    const char *const heads[2] = {
        "bsm:8,bjs:0,crr:0,baw:0,alo:0 evals=bsm:",
        "bsm:0,bjs:0,crr:0,baw:0,alo:8 evals=bsm:0,bjs:0,crr:0,baw:0,alo:",
    };
    const char *const tails[2] = {",bjs:0,crr:0,baw:0,alo:0\n", "\n"};
    FILE *file = fopen(FILES_IN, "wb");
    REQUIRE(file != NULL);
    for (size_t k = ZERO; k < 2u; k++) {
        REQUIRE(run_counters(file, *(list + k)) == 0);
        REQUIRE(strstr(err_text, "PLW1 exit=0 requests=1 calls=") != NULL);
        REQUIRE(strstr(err_text, *(heads + k)) != NULL);
        REQUIRE(strstr(err_text, *(tails + k)) != NULL);
    }
    REQUIRE(fclose(file) == 0);
    REQUIRE(remove(FILES_IN) == 0 && remove(FILES_OUT) == 0);
    puts("PASS counters");
}

int main(void) {
    err_f = tmpfile();
    REQUIRE(err_f != NULL);
    ts_fill_rows();
    counters();
    REQUIRE(fclose(err_f) == 0);
    return 0;
}
