#define _GNU_SOURCE
#include "pl_test_serve.h"

/* Test derived from specs/project/serve.md "Results": SHUTDOWN ends the loop and a bad argument
 * list is refused before any read. Group: shutdown. REQUIRE stays active under NDEBUG. */

static FILE *in_f;
static FILE *out_f;

static void shutdown_frame(void) {
    uint64_t requests = 0u;
    const struct pl_serve_options o = ts_options(PL_ROUTE_STDIO, 0);
    const struct ts_req r0 = TS_REQ(PL_FRAME_REQUEST, 1u, 1u, 0u, 7u, 64u, 64u);
    const struct ts_req r1 = TS_REQ(PL_FRAME_SHUTDOWN, 0u, 0u, 0u, 0u, 0u, 0u);
    const struct ts_req r2 = TS_REQ(PL_FRAME_REQUEST, 2u, 1u, 0u, 7u, 64u, 64u);
    size_t at = ts_put(0u, &r0);
    at = ts_put(at, &r1);
    at = ts_put(at, &r2); /* the request after SHUTDOWN is never read */
    ts_flush(in_f, at);
    REQUIRE(ts_serve(in_f, out_f, &o, &requests) == 0 && requests == 1u);
    REQUIRE(ts_frame(0u, 0u) == ts_size);
    REQUIRE(lseek(fileno(in_f), 0, SEEK_CUR) == (off_t)(2u * PL_HEADER_BYTES + 64u));
    /* a bad argument list is refused before any read */
    REQUIRE(pl_serve(0, 1, NULL, &requests) == 2 && requests == 0u);
    REQUIRE(pl_serve(0, 1, &o, NULL) == 2);
    puts("PASS shutdown");
}

int main(void) {
    in_f = ts_tmpfile();
    out_f = ts_tmpfile();
    ts_fill_rows();
    shutdown_frame();
    REQUIRE(fclose(in_f) == 0 && fclose(out_f) == 0);
    return 0;
}
