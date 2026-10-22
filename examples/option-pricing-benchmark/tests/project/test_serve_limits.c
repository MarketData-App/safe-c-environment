#define _GNU_SOURCE
#include "pl_test_serve.h"

/* Test derived from specs/project/serve.md "Check order": the refusals of pl_serve before any
 * payload byte. Group: limits. REQUIRE stays active under NDEBUG. */

static FILE *in_f;
static FILE *out_f;

/* A header-only request that must fail with code. */
struct refusal {
    struct ts_req req;
    enum pl_proto_error code;
};

static void limits(void) {
    const uint32_t over = (uint32_t)(PL_MAX_REQUEST_RECORDS + 1u);
    const struct refusal cases[] = {
        {TS_REQ(PL_FRAME_REQUEST, 31u, over, 0u, 1u, over * 64u, 0u), PL_PROTO_RECORD_LIMIT},
        {TS_REQ(PL_FRAME_REQUEST, 31u, 1u, 0u, 0u, 64u, 0u), PL_PROTO_BAD_MODELS},
        {TS_REQ(PL_FRAME_REQUEST, 31u, 1u, 0u, 32u, 64u, 0u), PL_PROTO_BAD_MODELS},
        {TS_REQ(PL_FRAME_REQUEST, 31u, 1u, 5u, 1u, 64u, 0u), PL_PROTO_BAD_THREADS},
        {TS_REQ(PL_FRAME_SHM_REQUEST, 31u, 1u, 0u, 1u, 32u, 0u), PL_PROTO_BAD_TYPE},
        {TS_REQ(PL_FRAME_RESPONSE, 31u, 0u, 0u, 1u, 4u, 0u), PL_PROTO_BAD_TYPE},
        {TS_REQ(PL_FRAME_REQUEST, 31u, 1u, 0u, 1u, 63u, 0u), PL_PROTO_LENGTH_MISMATCH},
        {TS_REQ(PL_FRAME_SHUTDOWN, 31u, 0u, 0u, 7u, 0u, 0u), PL_PROTO_RESERVED_NONZERO},
        {{PL_FRAME_REQUEST, 31u, 1u, 0u, 1u, 64u, 0u, NULL, 1u}, PL_PROTO_BAD_MAGIC},
        {{PL_FRAME_REQUEST, 31u, 1u, 0u, 1u, 64u, 0u, NULL, 2u}, PL_PROTO_BAD_VERSION},
    };
    const struct pl_serve_options o = ts_options(PL_ROUTE_STDIO, 0);
    for (size_t k = ZERO; k < 10u; k++) {
        const struct refusal *c = cases + k;
        uint64_t requests = 0u;
        ts_flush(in_f, ts_put(0u, &c->req));
        REQUIRE(ts_serve(in_f, out_f, &o, &requests) == 1 && requests == 0u);
        REQUIRE(lseek(fileno(in_f), 0, SEEK_CUR) == (off_t)PL_HEADER_BYTES);
        REQUIRE(ts_frame(0u, 0u) == ts_size && ts_is_error(0u, 31u, c->code));
    }
    puts("PASS limits");
}

int main(void) {
    in_f = ts_tmpfile();
    out_f = ts_tmpfile();
    ts_fill_rows();
    limits();
    REQUIRE(fclose(in_f) == 0 && fclose(out_f) == 0);
    return 0;
}
