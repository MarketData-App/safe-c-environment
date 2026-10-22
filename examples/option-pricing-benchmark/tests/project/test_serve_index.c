#define _GNU_SOURCE
#include "pl_test_serve.h"

/* Test derived from specs/project/serve.md "Request: route stdio": the partition request index is
 * the low word of the request ID; it changes only the order of work. Group: request-index. REQUIRE
 * stays active under NDEBUG. */

static FILE *in_f;
static FILE *out_f;
static uint8_t want[PL_TS_RECORD_BYTES];

static void request_index(void) {
    uint64_t requests = 0u;
    const struct pl_serve_options o = ts_options(PL_ROUTE_STDIO, 0);
    const struct ts_req r0 = TS_REQ(PL_FRAME_REQUEST, 0x500000001u, 8u, 2u, 7u, 512u, 512u);
    const struct ts_req r1 = TS_REQ(PL_FRAME_REQUEST, 0x500000000u, 8u, 2u, 7u, 512u, 512u);
    for (size_t i = ZERO; i < PL_TS_ROWS; i++) {
        ts_expect_record(i, PL_MASK_ALL3, 0, want + i * PL_RESPONSE_RECORD_BYTES);
    }
    size_t at = ts_put(0u, &r0);
    at = ts_put(at, &r1);
    ts_flush(in_f, at);
    REQUIRE(ts_serve(in_f, out_f, &o, &requests) == 0 && requests == 2u);
    at = 0u;
    for (size_t r = ZERO; r < 2u; r++) {
        at = ts_frame(at, r);
        REQUIRE(*(ts_len + r) == PL_TS_RECORD_BYTES + 4u + 32u);
        REQUIRE(memcmp(TS_PAY(r), want, PL_TS_RECORD_BYTES) == 0);
        REQUIRE(pl_load_u32(TS_PAY(r) + PL_TS_RECORD_BYTES) == 2u);
        REQUIRE(pl_load_u32(TS_PAY(r) + PL_TS_RECORD_BYTES + 4) == 4u);
        REQUIRE(pl_load_u32(TS_PAY(r) + PL_TS_RECORD_BYTES + 20) == 4u);
    }
    REQUIRE(at == ts_size);
    puts("PASS request-index");
}

int main(void) {
    in_f = ts_tmpfile();
    out_f = ts_tmpfile();
    ts_fill_rows();
    request_index();
    REQUIRE(fclose(in_f) == 0 && fclose(out_f) == 0);
    return 0;
}
