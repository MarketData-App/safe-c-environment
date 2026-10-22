#define _GNU_SOURCE
#include "pl_test_serve.h"

/* Test derived from specs/project/serve.md "Check order": a payload cut short, a header cut short
 * and an empty input. Group: truncated. REQUIRE stays active under NDEBUG. */

static FILE *in_f;
static FILE *out_f;

/* A request that announces more than the file holds, or a header cut short, or nothing. */
struct cut {
    struct ts_req req;
    size_t frames;
    uint64_t id;
};

static void truncated(void) {
    const struct cut cases[] = {
        {TS_REQ(PL_FRAME_REQUEST, 41u, 2u, 0u, 1u, 128u, 64u), 1u, 41u},
        {TS_REQ(PL_FRAME_REQUEST, 42u, 2u, 0u, 1u, 128u, 0u), 1u, 42u},
        {{PL_FRAME_REQUEST, 43u, 2u, 0u, 1u, 128u, 0u, NULL, 3u}, 1u, 0u},
        {TS_REQ(PL_FRAME_REQUEST, 44u, 2u, 0u, 1u, 128u, 0u), 0u, 0u},
    };
    const struct pl_serve_options o = ts_options(PL_ROUTE_STDIO, 0);
    for (size_t k = ZERO; k < 4u; k++) {
        const struct cut *c = cases + k;
        uint64_t requests = 9u;
        ts_flush(in_f, c->frames == 0u ? 0u : ts_put(0u, &c->req));
        const int rc = ts_serve(in_f, out_f, &o, &requests);
        REQUIRE(requests == 0u);
        if (c->frames == 0u) { /* EOF before a header: success and no frame */
            REQUIRE(rc == 0 && ts_size == 0u);
        } else {
            REQUIRE(rc == 1 && ts_frame(0u, 0u) == ts_size);
            REQUIRE(ts_is_error(0u, c->id, PL_PROTO_TRUNCATED));
        }
    }
    puts("PASS truncated");
}

int main(void) {
    in_f = ts_tmpfile();
    out_f = ts_tmpfile();
    ts_fill_rows();
    truncated();
    REQUIRE(fclose(in_f) == 0 && fclose(out_f) == 0);
    return 0;
}
