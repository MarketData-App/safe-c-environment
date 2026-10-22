#define _GNU_SOURCE
#include "pl_test_serve.h"
#include <fcntl.h>

/* Test derived from specs/project/serve.md "Results": result 2 for an unknown route, result 4 for
 * a read error (at the header and after it) and for a write failure of a RESPONSE and of an ERROR
 * frame. Group: io-errors. REQUIRE stays active under NDEBUG. */

static FILE *in_f;
static FILE *out_f;

static void io_errors(void) {
    uint64_t requests = 9u;
    const struct pl_serve_options o = ts_options(PL_ROUTE_STDIO, 0);
    struct pl_serve_options odd = o;
    const struct ts_req ping = TS_REQ(PL_FRAME_REQUEST, 5u, 0u, 0u, 1u, 0u, 0u);
    const struct ts_req bad = TS_REQ(PL_FRAME_REQUEST, 6u, 1u, 5u, 1u, 64u, 0u);
    const struct ts_req head = TS_REQ(PL_FRAME_REQUEST, 7u, 1u, 0u, 1u, 64u, 0u);
    int p[2];
    odd.route = 7;
    REQUIRE(pl_serve(0, 1, &odd, &requests) == 2 && requests == 0u);
    REQUIRE(pl_serve(-1, fileno(out_f), &o, &requests) == 4 && requests == 0u);
    /* a read error after the header: a header alone in a pipe that does not block */
    REQUIRE(pipe2(p, O_NONBLOCK) == 0);
    REQUIRE(pl_write_all(*(p + 1), ts_in, ts_put(0u, &head)) == PL_IO_OK);
    REQUIRE(pl_serve(*p, fileno(out_f), &o, &requests) == 4 && requests == 0u);
    REQUIRE(close(*p) == 0 && close(*(p + 1)) == 0);
    /* a write failure: the output descriptor is open for reading only */
    const int ro = open("/dev/null", O_RDONLY);
    REQUIRE(ro >= 0);
    ts_flush(in_f, ts_put(0u, &ping));
    REQUIRE(lseek(fileno(in_f), 0, SEEK_SET) == 0);
    REQUIRE(pl_serve(fileno(in_f), ro, &o, &requests) == 4 && requests == 0u);
    ts_flush(in_f, ts_put(0u, &bad));
    REQUIRE(lseek(fileno(in_f), 0, SEEK_SET) == 0);
    REQUIRE(pl_serve(fileno(in_f), ro, &o, &requests) == 4 && requests == 0u);
    REQUIRE(close(ro) == 0);
    puts("PASS io-errors");
}

int main(void) {
    in_f = ts_tmpfile();
    out_f = ts_tmpfile();
    ts_fill_rows();
    io_errors();
    REQUIRE(fclose(in_f) == 0 && fclose(out_f) == 0);
    return 0;
}
