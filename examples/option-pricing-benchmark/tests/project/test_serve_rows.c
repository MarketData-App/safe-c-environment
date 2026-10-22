#define _GNU_SOURCE
#include "pl_test_serve.h"

/* Test derived from specs/project/serve.md "Request: route stdio": eight rows at threads 0, 1, 2
 * and 4 give the same records and a trailer of k equal chunks. Group: rows. REQUIRE stays active
 * under NDEBUG. */

static FILE *in_f;
static FILE *out_f;
static uint8_t want[PL_TS_RECORD_BYTES];

static void rows(void) {
    const uint16_t threads[4] = {0u, 1u, 2u, 4u};
    uint64_t requests = 0u;
    const struct pl_serve_options o = ts_options(PL_ROUTE_STDIO, 0);
    const struct ts_req r0 = TS_REQ(PL_FRAME_REQUEST, 100u, 8u, 0u, PL_MASK_ALL3, 512u, 512u);
    const struct ts_req r1 = TS_REQ(PL_FRAME_REQUEST, 101u, 8u, 1u, PL_MASK_ALL3, 512u, 512u);
    const struct ts_req r2 = TS_REQ(PL_FRAME_REQUEST, 102u, 8u, 2u, PL_MASK_ALL3, 512u, 512u);
    const struct ts_req r3 = TS_REQ(PL_FRAME_REQUEST, 103u, 8u, 4u, PL_MASK_ALL3, 512u, 512u);
    for (size_t i = ZERO; i < PL_TS_ROWS; i++) {
        ts_expect_record(i, PL_MASK_ALL3, 0, want + i * PL_RESPONSE_RECORD_BYTES);
    }
    size_t at = ts_put(0u, &r0);
    at = ts_put(at, &r1);
    at = ts_put(at, &r2);
    at = ts_put(at, &r3);
    ts_flush(in_f, at);
    REQUIRE(ts_serve(in_f, out_f, &o, &requests) == 0 && requests == 4u);
    at = 0u;
    for (size_t t = ZERO; t < 4u; t++) {
        at = ts_frame(at, t);
        const struct pl_header *h = ts_head + t;
        const size_t k = *(threads + t);
        REQUIRE(*(ts_len + t) == PL_TS_RECORD_BYTES + 4u + 16u * k);
        REQUIRE(h->type == PL_FRAME_RESPONSE && h->request_id == 100u + t);
        REQUIRE(h->record_count == PL_TS_ROWS && h->threads == k && h->models == PL_MASK_ALL3);
        REQUIRE(memcmp(TS_PAY(t), want, PL_TS_RECORD_BYTES) == 0);
        REQUIRE(pl_load_u32(TS_PAY(t) + PL_TS_RECORD_BYTES) == k);
        for (size_t c = ZERO; c < k; c++) { /* eight rows in k equal chunks (k is 1, 2 or 4) */
            REQUIRE(pl_load_u32(TS_PAY(t) + PL_TS_RECORD_BYTES + 4u + 16u * c) == PL_TS_ROWS / k);
        }
    }
    REQUIRE(at == ts_size);
    puts("PASS rows");
}

int main(void) {
    in_f = ts_tmpfile();
    out_f = ts_tmpfile();
    ts_fill_rows();
    rows();
    REQUIRE(fclose(in_f) == 0 && fclose(out_f) == 0);
    return 0;
}
