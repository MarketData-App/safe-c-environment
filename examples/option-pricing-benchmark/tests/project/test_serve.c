#define _GNU_SOURCE
#include "pl_test_serve.h"

/* Test derived from specs/project/serve.md "Request: route stdio": a request with 0 records is a
 * ping. Group: ping. REQUIRE stays active under NDEBUG. */

static FILE *in_f;
static FILE *out_f;

static void ping(void) {
    uint64_t requests = 9u;
    const struct pl_serve_options o = ts_options(PL_ROUTE_STDIO, 0);
    const struct ts_req r0 = TS_REQ(PL_FRAME_REQUEST, 77u, 0u, 0u, PL_MASK_WIRED, 0u, 0u);
    const struct ts_req r1 = TS_REQ(PL_FRAME_REQUEST, 78u, 0u, 4u, 1u, 0u, 0u);
    const struct ts_req r2 = TS_REQ(PL_FRAME_SHUTDOWN, 0u, 0u, 0u, 0u, 0u, 0u);
    size_t at = ts_put(0u, &r0);
    at = ts_put(at, &r1);
    at = ts_put(at, &r2);
    ts_flush(in_f, at);
    REQUIRE(ts_serve(in_f, out_f, &o, &requests) == 0 && requests == 2u);
    at = ts_frame(0u, 0u);
    at = ts_frame(at, 1u);
    REQUIRE(at == ts_size);
    REQUIRE(*ts_len == 4u && *(ts_len + 1) == 4u);
    REQUIRE(ts_head->type == PL_FRAME_RESPONSE && (ts_head + 1)->type == PL_FRAME_RESPONSE);
    REQUIRE(ts_head->request_id == 77u && (ts_head + 1)->request_id == 78u);
    REQUIRE(ts_head->models == PL_MASK_WIRED && (ts_head + 1)->models == 1u);
    REQUIRE(ts_head->threads == 0u && (ts_head + 1)->threads == 4u);
    REQUIRE(ts_head->record_count == 0u && (ts_head + 1)->record_count == 0u);
    REQUIRE(pl_load_u32(TS_PAY(0)) == 0u && pl_load_u32(TS_PAY(1)) == 0u);
    puts("PASS ping");
}

int main(void) {
    in_f = ts_tmpfile();
    out_f = ts_tmpfile();
    ts_fill_rows();
    ping();
    REQUIRE(fclose(in_f) == 0 && fclose(out_f) == 0);
    return 0;
}
