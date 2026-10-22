#define _GNU_SOURCE
#define PL_TS_SHM
#include "pl_test_serve.h"

/* Test derived from specs/project/serve.md "Request: route shm": the shm route gives the same
 * records as the stdio route (all models, 2 threads). Group: round-trip. REQUIRE stays active
 * under NDEBUG. */

#define THREADS 2u
#define MODELS PL_MASK_WIRED
#define WRITTEN DESC_BYTES

static void round_trip(void) {
    uint64_t requests = 0u;
    uint64_t shm_requests = 0u;
    const struct pl_serve_options so = ts_options(PL_ROUTE_STDIO, 0);
    struct ts_req shm = TS_REQ(PL_FRAME_SHM_REQUEST, 21u, 8u, THREADS, MODELS, 32u, 32u);
    const struct ts_req req = TS_REQ(PL_FRAME_REQUEST, 22u, 8u, THREADS, MODELS, 512u, 512u);
    regions();
    const struct pl_serve_options o = shm_options(fileno(reg_in), fileno(reg_out));
    ts_describe(0u, 512u, 0u, WRITTEN);
    shm.data = ts_desc;
    ts_flush(in_f, ts_put(0u, &shm));
    REQUIRE(ts_serve(in_f, out_f, &o, &shm_requests) == 0 && ts_frame(0u, 0u) == ts_size);
    REQUIRE(ts_head->type == PL_FRAME_SHM_RESPONSE && ts_head->request_id == 21u);
    REQUIRE(ts_head->models == MODELS && ts_head->threads == THREADS);
    REQUIRE(ts_head->record_count == 8u);
    REQUIRE(*ts_len == 8u && pl_load_u64(TS_PAY(0)) == WRITTEN);
    read_region(reg_out, before, WRITTEN);
    ts_flush(in_f, ts_put(0u, &req));
    REQUIRE(ts_serve(in_f, out_f, &so, &requests) == 0 && ts_frame(0u, 0u) == ts_size);
    REQUIRE(*ts_len == WRITTEN && memcmp(TS_PAY(0), before, PL_TS_RECORD_BYTES) == 0);
    REQUIRE(pl_load_u32(before + PL_TS_RECORD_BYTES) == THREADS);
    REQUIRE(pl_load_u32(before + PL_TS_RECORD_BYTES + 4) == 4u); /* two chunks of 4 rows */
    REQUIRE(pl_load_u32(before + PL_TS_RECORD_BYTES + 20) == 4u);
    puts("PASS round-trip");
}

int main(void) {
    in_f = ts_tmpfile();
    out_f = ts_tmpfile();
    ts_fill_rows();
    round_trip();
    REQUIRE(fclose(in_f) == 0 && fclose(out_f) == 0);
    REQUIRE(fclose(reg_in) == 0 && fclose(reg_out) == 0);
    return 0;
}
