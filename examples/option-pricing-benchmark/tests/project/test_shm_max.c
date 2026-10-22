#define _GNU_SOURCE
#define PL_TS_SHM
#include "pl_test_serve.h"

/* Test derived from specs/project/serve.md "Request: route shm": the representable maximum through
 * pl_serve (shm route) and pl_shm_request: 14,336 records, threads 4, mask 1, a 917,504-byte input
 * snapshot and a 4,157,508-byte output. Group: maximum. REQUIRE stays active under NDEBUG. */

#define RECORDS 14336u
#define INPUT (RECORDS * 64u)
#define OUTPUT (RECORDS * 290u + 4u + 64u)

/* 512 bytes (the eight rows) as a struct, so that a copy is an assignment (the AST policy refuses
 * memcpy in project code). */
struct blk {
    uint8_t b[512];
};

static struct blk rows_blk;
static struct blk big[INPUT / 512u];
static uint8_t input_copy[PL_SHM_INPUT_BYTES];
static uint8_t output_copy[PL_SHM_OUTPUT_BYTES];
static uint8_t want[PL_TS_RECORD_BYTES];

static void maximum(void) {
    uint64_t requests = 0u;
    size_t written = 0u;
    struct ts_req req = TS_REQ(PL_FRAME_SHM_REQUEST, 31u, RECORDS, 4u, 1u, 32u, 32u);
    struct pl_header h;
    for (size_t j = ZERO; j < 512u; j++) {
        *(rows_blk.b + j) = *(ts_wire + j);
    }
    for (size_t i = ZERO; i < INPUT / 512u; i++) {
        *(big + i) = rows_blk;
    }
    for (size_t i = ZERO; i < PL_TS_ROWS; i++) {
        ts_expect_record(i, 1u, 0, want + i * PL_RESPONSE_RECORD_BYTES);
    }
    regions();
    REQUIRE(pl_pwrite_all(fileno(reg_in), big->b, INPUT, 0u) == PL_IO_OK);
    const struct pl_serve_options o = shm_options(fileno(reg_in), fileno(reg_out));
    ts_describe(0u, INPUT, 0u, OUTPUT);
    req.data = ts_desc;
    ts_flush(in_f, ts_put(0u, &req));
    REQUIRE(ts_serve(in_f, out_f, &o, &requests) == 0 && ts_frame(0u, 0u) == ts_size);
    REQUIRE(ts_head->type == PL_FRAME_SHM_RESPONSE && pl_load_u64(TS_PAY(0)) == OUTPUT);
    REQUIRE(OUTPUT == PL_SHM_OUTPUT_BYTES);
    read_region(reg_out, before, OUTPUT);
    for (size_t r = ZERO; r < RECORDS; r++) {
        const uint8_t *rec = before + r * PL_RESPONSE_RECORD_BYTES;
        REQUIRE(memcmp(rec, want + (r & 7u) * PL_RESPONSE_RECORD_BYTES, 290u) == 0);
    }
    REQUIRE(pl_load_u32(before + RECORDS * PL_RESPONSE_RECORD_BYTES) == 4u);
    REQUIRE(pl_load_u32(before + RECORDS * PL_RESPONSE_RECORD_BYTES + 4) == RECORDS / 4u);
    /* the same request through pl_shm_request: the snapshot holds all 917,504 bytes */
    h.version = PL_PROTOCOL_VERSION;
    h.type = PL_FRAME_SHM_REQUEST;
    h.request_id = 31u;
    h.record_count = RECORDS;
    h.threads = 4u;
    h.models = 1u;
    h.payload_length = PL_SHM_REQUEST_BYTES;
    REQUIRE(pl_shm_request(&o, &h, ts_desc, input_copy, output_copy, &written) == PL_PROTO_OK);
    REQUIRE(written == OUTPUT && memcmp(input_copy, big->b, INPUT) == 0);
    REQUIRE(memcmp(output_copy, before, RECORDS * PL_RESPONSE_RECORD_BYTES) == 0);
    puts("PASS maximum");
}

int main(void) {
    in_f = ts_tmpfile();
    out_f = ts_tmpfile();
    ts_fill_rows();
    maximum();
    REQUIRE(fclose(in_f) == 0 && fclose(out_f) == 0);
    REQUIRE(fclose(reg_in) == 0 && fclose(reg_out) == 0);
    return 0;
}
