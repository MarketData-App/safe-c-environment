#define _GNU_SOURCE
#include "pl_test_serve.h"

/* Test derived from specs/project/serve.md "Request: route stdio": echo records. Group: echo.
 * REQUIRE stays active under NDEBUG. */

static FILE *in_f;
static FILE *out_f;

static void echo(void) {
    uint64_t requests = 0u;
    const struct pl_serve_options o = ts_options(PL_ROUTE_STDIO, 1);
    const struct ts_req req = TS_REQ(PL_FRAME_REQUEST, 3u, 8u, 2u, PL_MASK_ALL3, 512u, 512u);
    ts_flush(in_f, ts_put(0u, &req));
    REQUIRE(ts_serve(in_f, out_f, &o, &requests) == 0 && requests == 1u);
    REQUIRE(ts_frame(0u, 0u) == ts_size && *ts_len == PL_TS_RECORD_BYTES + 4u + 32u);
    for (size_t i = ZERO; i < PL_TS_ROWS; i++) {
        const uint8_t *rec = TS_PAY(0) + i * PL_RESPONSE_RECORD_BYTES;
        struct pl_contract_result r;
        REQUIRE(pl_response_decode(rec, PL_MASK_ALL3, &r) == PL_PROTO_OK);
        REQUIRE(r.model->status == PL_ECHO && (r.model + 1)->status == PL_ECHO);
        REQUIRE((r.model + 2)->status == PL_ECHO && r.model->flags == 0u);
        REQUIRE((r.model + 1)->flags == 0u && (r.model + 2)->flags == 0u);
        REQUIRE((r.model + PL_MODEL_BAW)->flags == 0u && (r.model + PL_MODEL_ALO)->flags == 0u);
        REQUIRE((r.model + PL_MODEL_BAW)->status == PL_NOT_REQUESTED);
        REQUIRE((r.model + PL_MODEL_ALO)->status == PL_NOT_REQUESTED);
    }
    puts("PASS echo");
}

int main(void) {
    in_f = ts_tmpfile();
    out_f = ts_tmpfile();
    ts_fill_rows();
    echo();
    REQUIRE(fclose(in_f) == 0 && fclose(out_f) == 0);
    return 0;
}
