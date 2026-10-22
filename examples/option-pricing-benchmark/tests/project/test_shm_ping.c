#define _GNU_SOURCE
#define PL_TS_SHM
#include "pl_test_serve.h"

/* Test derived from specs/project/serve.md "Request: route shm": a ping writes the 4-byte trailer
 * at the output offset. Group: ping. REQUIRE stays active under NDEBUG. */

static void ping(void) {
    uint64_t requests = 0u;
    struct ts_req req = TS_REQ(PL_FRAME_SHM_REQUEST, 23u, 0u, 4u, 3u, 32u, 32u);
    regions();
    const struct pl_serve_options o = shm_options(fileno(reg_in), fileno(reg_out));
    ts_describe(0u, 0u, 100u, 4u);
    req.data = ts_desc;
    ts_flush(in_f, ts_put(0u, &req));
    REQUIRE(ts_serve(in_f, out_f, &o, &requests) == 0 && ts_frame(0u, 0u) == ts_size);
    REQUIRE(*ts_len == 8u && pl_load_u64(TS_PAY(0)) == 4u);
    read_region(reg_out, after, 104u);
    REQUIRE(pl_load_u32(after + 100) == 0u);
    puts("PASS ping");
}

int main(void) {
    in_f = ts_tmpfile();
    out_f = ts_tmpfile();
    ts_fill_rows();
    ping();
    REQUIRE(fclose(in_f) == 0 && fclose(out_f) == 0);
    REQUIRE(fclose(reg_in) == 0 && fclose(reg_out) == 0);
    return 0;
}
