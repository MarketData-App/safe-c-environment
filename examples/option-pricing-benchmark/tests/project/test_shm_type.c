#define _GNU_SOURCE
#define PL_TS_SHM
#include "pl_test_serve.h"

/* Test derived from specs/project/serve.md "Request: route shm": the REQUEST type on route shm is
 * refused before any payload byte. Group: wrong-type. REQUIRE stays active under NDEBUG. */

/* The output region is unchanged and frame 0 is the ERROR code of request 21. */
static void refused(enum pl_proto_error code) {
    REQUIRE(ts_frame(0u, 0u) == ts_size && ts_is_error(0u, 21u, code));
    REQUIRE(ts_region_unchanged());
}

/* The REQUEST type on route shm: BAD_TYPE before any payload byte. */
static void wrong_type(void) {
    uint64_t requests = 0u;
    const struct ts_req req = TS_REQ(PL_FRAME_REQUEST, 21u, 1u, 0u, 1u, 64u, 0u);
    regions();
    read_region(reg_out, before, PL_SHM_OUTPUT_BYTES);
    const struct pl_serve_options o = shm_options(fileno(reg_in), fileno(reg_out));
    ts_flush(in_f, ts_put(0u, &req));
    REQUIRE(ts_serve(in_f, out_f, &o, &requests) == 1 && requests == 0u);
    REQUIRE(lseek(fileno(in_f), 0, SEEK_CUR) == (off_t)PL_HEADER_BYTES);
    refused(PL_PROTO_BAD_TYPE);
    puts("PASS wrong-type");
}

int main(void) {
    in_f = ts_tmpfile();
    out_f = ts_tmpfile();
    ts_fill_rows();
    wrong_type();
    REQUIRE(fclose(in_f) == 0 && fclose(out_f) == 0);
    REQUIRE(fclose(reg_in) == 0 && fclose(reg_out) == 0);
    return 0;
}
