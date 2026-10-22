#define _GNU_SOURCE
#include "pl_test_serve.h"

/* Test derived from specs/project/serve.md "Request: route stdio": the mask rule (the selected
 * parts equal the PL_MASK_WIRED parts, the others are NOT_REQUESTED). Group: masks. REQUIRE stays
 * active under NDEBUG. */

static FILE *in_f;
static FILE *out_f;
static uint8_t full[PL_TS_RECORD_BYTES];
static uint8_t expect[PL_RESPONSE_RECORD_BYTES];

static void masks(void) {
    const uint16_t list[4] = {1u, 8u, 16u, 31u};
    uint64_t requests = 0u;
    const struct pl_serve_options o = ts_options(PL_ROUTE_STDIO, 0);
    for (size_t i = ZERO; i < PL_TS_ROWS; i++) {
        ts_expect_record(i, PL_MASK_WIRED, 0, full + i * PL_RESPONSE_RECORD_BYTES);
    }
    for (size_t m = ZERO; m < 4u; m++) {
        const uint16_t mask = *(list + m);
        const struct ts_req req = TS_REQ(PL_FRAME_REQUEST, 50u + m, 8u, 2u, mask, 512u, 512u);
        ts_flush(in_f, ts_put(0u, &req));
        const int rc = ts_serve(in_f, out_f, &o, &requests);
        REQUIRE(ts_frame(0u, 0u) == ts_size);
        if ((mask & ~PL_MASK_WIRED) != 0u) { /* a model that is not wired: ERROR, models 0 */
            REQUIRE(rc == 3 && ts_is_error(0u, 50u + m, PL_PROTO_KERNEL_FAILURE));
            continue;
        }
        REQUIRE(rc == 0 && *ts_len == PL_TS_RECORD_BYTES + 4u + 32u);
        REQUIRE(ts_head->type == PL_FRAME_RESPONSE && ts_head->models == mask);
        /* the expected records: the wired records with the other models NOT_REQUESTED */
        for (size_t i = ZERO; i < PL_TS_ROWS; i++) {
            struct pl_contract_result r;
            const uint8_t *wired = full + i * PL_RESPONSE_RECORD_BYTES;
            REQUIRE(pl_response_decode(wired, PL_MASK_MODELS5, &r) == PL_PROTO_OK);
            for (size_t k = ZERO; k < PL_MODELS; k++) {
                if (((unsigned)mask >> k & 1u) == 0u) {
                    pl_result_not_requested(r.model + k);
                }
            }
            pl_response_encode(&r, expect);
            REQUIRE(memcmp(expect, TS_PAY(0) + i * PL_RESPONSE_RECORD_BYTES, 290u) == 0);
        }
    }
    puts("PASS masks");
}

int main(void) {
    in_f = ts_tmpfile();
    out_f = ts_tmpfile();
    ts_fill_rows();
    masks();
    REQUIRE(fclose(in_f) == 0 && fclose(out_f) == 0);
    return 0;
}
