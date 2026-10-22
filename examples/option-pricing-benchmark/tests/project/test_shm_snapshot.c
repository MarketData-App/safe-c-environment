#define _GNU_SOURCE
#define PL_TS_SHM
#include "pl_test_serve.h"

/* Test derived from specs/project/serve.md "Request: route shm": the batch reads a private copy of
 * the input range. Group: snapshot. REQUIRE stays active under NDEBUG. */

static uint8_t input_copy[PL_SHM_INPUT_BYTES];
static uint8_t output_copy[PL_SHM_OUTPUT_BYTES];

static void snapshot(void) {
    regions();
    const struct pl_serve_options o = shm_options(fileno(reg_in), fileno(reg_out));
    const struct pl_header h = {PL_PROTOCOL_VERSION, PL_FRAME_SHM_REQUEST, 5u, 8u, 2u, 7u, 32u};
    size_t written = 0u;
    ts_describe(0u, 512u, 0u, DESC_BYTES);
    REQUIRE(pl_shm_request(&o, &h, ts_desc, input_copy, output_copy, &written) == PL_PROTO_OK);
    REQUIRE(written == DESC_BYTES);
    read_region(reg_out, before, DESC_BYTES);
    /* the region changes after the call: the private copy and the response keep the old rows */
    static uint8_t zeros[PL_TS_ROWS * PL_REQUEST_RECORD_BYTES];
    REQUIRE(pl_pwrite_all(fileno(reg_in), zeros, sizeof zeros, 0u) == PL_IO_OK);
    REQUIRE(memcmp(input_copy, ts_wire, sizeof ts_wire) == 0);
    read_region(reg_out, after, DESC_BYTES);
    REQUIRE(memcmp(before, after, DESC_BYTES) == 0);
    REQUIRE(memcmp(output_copy, before, DESC_BYTES) == 0);
    /* a bad descriptor leaves written 0 */
    ts_describe(0u, 511u, 0u, DESC_BYTES);
    written = 9u;
    REQUIRE(pl_shm_request(&o, &h, ts_desc, input_copy, output_copy, &written) ==
            PL_PROTO_LENGTH_MISMATCH);
    REQUIRE(written == 0u);
    puts("PASS snapshot");
}

int main(void) {
    in_f = ts_tmpfile();
    out_f = ts_tmpfile();
    ts_fill_rows();
    snapshot();
    REQUIRE(fclose(in_f) == 0 && fclose(out_f) == 0);
    REQUIRE(fclose(reg_in) == 0 && fclose(reg_out) == 0);
    return 0;
}
