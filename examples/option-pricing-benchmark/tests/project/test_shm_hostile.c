#define _GNU_SOURCE
#define PL_TS_SHM
#include "pl_test_serve.h"
#include <fcntl.h>

/* Test derived from specs/project/serve.md "Request: route shm" (Review Focus 3): a region whose
 * size or offsets disagree with its descriptor. The output region is unchanged. Group: hostile.
 * REQUIRE stays active under NDEBUG. */

/* What happens to the regions before the request: 1 shrinks the input region to 32 bytes, 2 grows
 * it by one byte, 3 grows the output region by one byte. */
struct bad_region {
    unsigned action;
    uint64_t in_off, in_len, out_off, out_cap;
    enum pl_proto_error code;
};

/* The output region is unchanged and frame 0 is the ERROR code of request 21. */
static void refused(enum pl_proto_error code) {
    REQUIRE(ts_frame(0u, 0u) == ts_size && ts_is_error(0u, 21u, code));
    REQUIRE(ts_region_unchanged());
}

static void hostile(void) {
    const uint64_t wrap = UINT64_MAX - 8u;
    const struct bad_region cases[] = {
        {1u, 0u, 512u, 0u, DESC_BYTES, PL_PROTO_LENGTH_MISMATCH},
        {0u, wrap, 512u, 0u, DESC_BYTES, PL_PROTO_LENGTH_MISMATCH},
        {0u, 0u, 512u, 0u, DESC_BYTES - 1u, PL_PROTO_LENGTH_MISMATCH},
        {0u, 0u, 511u, 0u, DESC_BYTES, PL_PROTO_LENGTH_MISMATCH},
        {2u, 0u, 512u, 0u, DESC_BYTES, PL_PROTO_FRAME_LIMIT},
        {3u, 0u, 512u, 0u, DESC_BYTES, PL_PROTO_FRAME_LIMIT},
    };
    for (size_t k = ZERO; k < 6u; k++) {
        const struct bad_region *c = cases + k;
        uint64_t requests = 0u;
        struct ts_req req = TS_REQ(PL_FRAME_SHM_REQUEST, 21u, 8u, 2u, 7u, 32u, 32u);
        regions();
        if (c->action == 1u) {
            REQUIRE(ftruncate(fileno(reg_in), 32) == 0);
        }
        if (c->action == 2u) {
            REQUIRE(ftruncate(fileno(reg_in), (off_t)PL_SHM_INPUT_BYTES + 1) == 0);
        }
        if (c->action == 3u) {
            REQUIRE(ftruncate(fileno(reg_out), (off_t)PL_SHM_OUTPUT_BYTES + 1) == 0);
        }
        read_region(reg_out, before, PL_SHM_OUTPUT_BYTES);
        const struct pl_serve_options o = shm_options(fileno(reg_in), fileno(reg_out));
        ts_describe(c->in_off, c->in_len, c->out_off, c->out_cap);
        req.data = ts_desc;
        ts_flush(in_f, ts_put(0u, &req));
        REQUIRE(ts_serve(in_f, out_f, &o, &requests) == 1 && requests == 0u);
        refused(c->code);
    }
    puts("PASS hostile");
}

int main(void) {
    in_f = ts_tmpfile();
    out_f = ts_tmpfile();
    ts_fill_rows();
    hostile();
    REQUIRE(fclose(in_f) == 0 && fclose(out_f) == 0);
    REQUIRE(fclose(reg_in) == 0 && fclose(reg_out) == 0);
    return 0;
}
