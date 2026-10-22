#define _GNU_SOURCE
#define PL_TS_SHM
#include "pl_test_serve.h"
#include <fcntl.h>

/* Test derived from specs/project/serve.md "Request: route shm": descriptors that are no regions
 * or cannot be read or written. Group: access. REQUIRE stays active under NDEBUG. */

#define RO_FILE "pl-shm-test-readonly.bin"

/* The output region is unchanged and frame 0 is the ERROR code of request 21. */
static void refused(enum pl_proto_error code) {
    REQUIRE(ts_frame(0u, 0u) == ts_size && ts_is_error(0u, 21u, code));
    REQUIRE(ts_region_unchanged());
}

/* Descriptors that are no regions (a pipe, a device, a closed descriptor) or that cannot be read
 * or written (a write-only input, a read-only output): ERROR IO_ERROR and return 4. */
static void access_errors(void) {
    int p[2];
    regions();
    REQUIRE(pipe(p) == 0);
    FILE *ro = fopen(RO_FILE, "wb");
    REQUIRE(ro != NULL);
    REQUIRE(fclose(ro) == 0 && truncate(RO_FILE, (off_t)PL_SHM_INPUT_BYTES) == 0);
    const int dev = open("/dev/null", O_RDWR);
    const int rd = open(RO_FILE, O_RDONLY);
    const int wr = open(RO_FILE, O_WRONLY);
    REQUIRE(dev >= 0 && rd >= 0 && wr >= 0);
    const int ins[5] = {*p, fileno(reg_in), -1, wr, fileno(reg_in)};
    const int outs[5] = {fileno(reg_out), dev, fileno(reg_out), fileno(reg_out), rd};
    read_region(reg_out, before, PL_SHM_OUTPUT_BYTES);
    ts_describe(0u, 512u, 0u, DESC_BYTES);
    for (size_t k = ZERO; k < 5u; k++) {
        uint64_t requests = 0u;
        struct ts_req req = TS_REQ(PL_FRAME_SHM_REQUEST, 21u, 8u, 2u, 7u, 32u, 32u);
        const struct pl_serve_options o = shm_options(*(ins + k), *(outs + k));
        req.data = ts_desc;
        ts_flush(in_f, ts_put(0u, &req));
        REQUIRE(ts_serve(in_f, out_f, &o, &requests) == 4 && requests == 0u);
        refused(PL_PROTO_IO_ERROR);
    }
    REQUIRE(close(*p) == 0 && close(*(p + 1)) == 0 && close(dev) == 0);
    REQUIRE(close(rd) == 0 && close(wr) == 0 && remove(RO_FILE) == 0);
    puts("PASS access");
}

int main(void) {
    in_f = ts_tmpfile();
    out_f = ts_tmpfile();
    ts_fill_rows();
    access_errors();
    REQUIRE(fclose(in_f) == 0 && fclose(out_f) == 0);
    REQUIRE(fclose(reg_in) == 0 && fclose(reg_out) == 0);
    return 0;
}
