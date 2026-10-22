#define _GNU_SOURCE
#include "pl_test_serve.h"

/* Test derived from specs/project/serve.md "Static buffers and ownership": the representable
 * maximum through pl_serve on the stdio route: 14,336 records, threads 4, mask 1, a 917,504-byte
 * payload and a 4,157,536-byte response frame. Group: maximum. REQUIRE stays active under
 * NDEBUG. */

#define RECORDS 14336u
#define PAYLOAD (RECORDS * 64u)
#define FRAME_BYTES (28u + RECORDS * 290u + 4u + 64u)

static FILE *in_f;
static FILE *out_f;
/* 512 bytes (the eight rows) as a struct, so that a copy is an assignment (the AST policy refuses
 * memcpy in project code). */
struct blk {
    uint8_t b[512];
};

static struct blk rows_blk;
static struct blk payload[PAYLOAD / 512u];
static uint8_t head_in[PL_HEADER_BYTES];
static uint8_t big_out[FRAME_BYTES + 16u];
static uint8_t want[PL_TS_RECORD_BYTES];

static void maximum(void) {
    uint64_t requests = 0u;
    const struct pl_serve_options o = ts_options(PL_ROUTE_STDIO, 0);
    struct pl_header h;
    h.version = PL_PROTOCOL_VERSION;
    h.type = PL_FRAME_REQUEST;
    h.request_id = 0x900000001u;
    h.record_count = RECORDS;
    h.threads = 4u;
    h.models = 1u;
    h.payload_length = PAYLOAD;
    pl_header_encode(&h, head_in);
    for (size_t j = ZERO; j < 512u; j++) {
        *(rows_blk.b + j) = *(ts_wire + j);
    }
    for (size_t i = ZERO; i < PAYLOAD / 512u; i++) {
        *(payload + i) = rows_blk;
    }
    for (size_t i = ZERO; i < PL_TS_ROWS; i++) {
        ts_expect_record(i, 1u, 0, want + i * PL_RESPONSE_RECORD_BYTES);
    }
    REQUIRE(ftruncate(fileno(in_f), 0) == 0 && lseek(fileno(in_f), 0, SEEK_SET) == 0);
    REQUIRE(pl_write_all(fileno(in_f), head_in, sizeof head_in) == PL_IO_OK);
    REQUIRE(pl_write_all(fileno(in_f), payload->b, PAYLOAD) == PL_IO_OK);
    REQUIRE(lseek(fileno(in_f), 0, SEEK_SET) == 0);
    REQUIRE(ftruncate(fileno(out_f), 0) == 0 && lseek(fileno(out_f), 0, SEEK_SET) == 0);
    REQUIRE(pl_serve(fileno(in_f), fileno(out_f), &o, &requests) == 0 && requests == 1u);
    REQUIRE(lseek(fileno(out_f), 0, SEEK_END) == (off_t)FRAME_BYTES);
    REQUIRE(pl_pread_exact(fileno(out_f), big_out, FRAME_BYTES, 0u) == PL_IO_OK);
    REQUIRE(pl_header_decode(big_out, PL_HEADER_BYTES, &h) == PL_PROTO_OK);
    REQUIRE(h.type == PL_FRAME_RESPONSE && h.request_id == 0x900000001u);
    REQUIRE(h.record_count == RECORDS && h.threads == 4u && h.models == 1u);
    REQUIRE(h.payload_length == FRAME_BYTES - PL_HEADER_BYTES);
    for (size_t r = ZERO; r < RECORDS; r++) {
        const uint8_t *rec = big_out + PL_HEADER_BYTES + r * PL_RESPONSE_RECORD_BYTES;
        REQUIRE(memcmp(rec, want + (r & 7u) * PL_RESPONSE_RECORD_BYTES, 290u) == 0);
    }
    const uint8_t *trailer = big_out + PL_HEADER_BYTES + RECORDS * PL_RESPONSE_RECORD_BYTES;
    REQUIRE(pl_load_u32(trailer) == 4u && pl_load_u32(trailer + 4) == RECORDS / 4u);
    REQUIRE(pl_load_u32(trailer + 20) == RECORDS / 4u && pl_load_u32(trailer + 36) == RECORDS / 4u);
    REQUIRE(pl_load_u32(trailer + 52) == RECORDS / 4u);
    puts("PASS maximum");
}

int main(void) {
    in_f = ts_tmpfile();
    out_f = ts_tmpfile();
    ts_fill_rows();
    maximum();
    REQUIRE(fclose(in_f) == 0 && fclose(out_f) == 0);
    return 0;
}
