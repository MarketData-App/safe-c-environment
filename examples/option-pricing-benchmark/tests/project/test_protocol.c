#include "pl_ieee.h"
#include "pl_protocol.h"
#include <stdio.h>
#include <stdlib.h>

/* Tests of pl_protocol.c (specs/project/protocol.md): byte helpers, header checks in the
 * Amendment G order, the per-type models rule (G4.4, I5.2), the 290-byte record with the
 * NOT_REQUESTED rule and the flag-byte rule (G4.5, N7, I5.3), the full 14,336-record five-block
 * response (I12, ruling 47), shm descriptors and error payloads. REQUIRE-style checks stay active
 * under NDEBUG; the first failed check prints its line and exits 1. */

#define REQUIRE_FAIL(c) (fprintf(stderr, "%s:%d: REQUIRE %s\n", __FILE__, __LINE__, #c), exit(1))
#define REQUIRE(c) ((c) ? (void)0 : REQUIRE_FAIL(c))

#define NAN_BITS UINT64_C(0x7FF8000000000000)

static struct pl_header header(uint16_t type, uint32_t count, uint16_t threads, uint16_t models,
                               uint32_t payload) {
    struct pl_header h;
    h.version = PL_PROTOCOL_VERSION;
    h.type = type;
    h.request_id = UINT64_C(0x0000000700000001);
    h.record_count = count;
    h.threads = threads;
    h.models = models;
    h.payload_length = payload;
    return h;
}

static enum pl_proto_error decode_one(struct pl_header h) {
    uint8_t buf[PL_HEADER_BYTES];
    pl_header_encode(&h, buf);
    struct pl_header out;
    return pl_header_decode(buf, sizeof buf, &out);
}

struct header_case {
    uint16_t version;
    uint16_t type;
    uint32_t count;
    uint16_t threads;
    uint16_t models;
    uint32_t payload;
    enum pl_proto_error want;
};

/* Header checks of group `headers` with constant fields (version, type, count, threads,
 * models, payload, expected result). */
static const struct header_case HEADERS_CASES[] = {
    /* ping */
    {2u, PL_FRAME_REQUEST, 0u, 0u, 7u, 0u, PL_PROTO_OK},
    {2u, PL_FRAME_REQUEST, 1u, 0u, 7u, 64u, PL_PROTO_OK},
    {2u, PL_FRAME_REQUEST, 14336u, 0u, 31u, 14336u * 64u, PL_PROTO_OK},
    {2u, PL_FRAME_REQUEST, 14337u, 0u, 7u, 14337u * 64u, PL_PROTO_RECORD_LIMIT},
    {2u, PL_FRAME_REQUEST, UINT32_MAX, 0u, 7u, 0u, PL_PROTO_RECORD_LIMIT},
    {2u, PL_FRAME_REQUEST, 1u, 4u, 7u, 64u, PL_PROTO_OK},
    /* threads-above-policy */
    {2u, PL_FRAME_REQUEST, 1u, 5u, 7u, 64u, PL_PROTO_BAD_THREADS},
    {2u, PL_FRAME_REQUEST, 1u, 0u, 7u, 63u, PL_PROTO_LENGTH_MISMATCH},
    {2u, PL_FRAME_REQUEST, 1u, 0u, 7u, 65u, PL_PROTO_LENGTH_MISMATCH},
    {2u, PL_FRAME_REQUEST, 1u, 0u, 7u, UINT32_MAX, PL_PROTO_FRAME_LIMIT},
    /* the frame bound: 28 + payload <= 4,194,304 exactly, one past is FRAME_LIMIT */
    {2u, PL_FRAME_REQUEST, 1u, 0u, 7u, 4194276u, PL_PROTO_LENGTH_MISMATCH},
    {2u, PL_FRAME_REQUEST, 1u, 0u, 7u, 4194277u, PL_PROTO_FRAME_LIMIT},
    {2u, PL_FRAME_RESPONSE, 1u, 5u, 7u, 310u, PL_PROTO_BAD_THREADS},
    {2u, PL_FRAME_ERROR, 0u, 0u, 0u, 4u, PL_PROTO_OK},
    /* G4.4: a nonzero record count on ERROR or SHUTDOWN is RESERVED_NONZERO, at the record
     * count position of the check order (P2-T13-CTRLCOUNT-01) */
    {2u, PL_FRAME_ERROR, 1u, 0u, 0u, 4u, PL_PROTO_RESERVED_NONZERO},
    {2u, PL_FRAME_ERROR, 14337u, 0u, 0u, 4u, PL_PROTO_RESERVED_NONZERO},
    {2u, PL_FRAME_ERROR, UINT32_MAX, 0u, 0u, 4u, PL_PROTO_RESERVED_NONZERO},
    {2u, PL_FRAME_ERROR, 1u, 5u, 7u, UINT32_MAX, PL_PROTO_RESERVED_NONZERO},
    {2u, PL_FRAME_ERROR, 0u, 1u, 0u, 4u, PL_PROTO_RESERVED_NONZERO},
    {2u, PL_FRAME_ERROR, 0u, 0u, 0u, 5u, PL_PROTO_LENGTH_MISMATCH},
    {2u, PL_FRAME_SHUTDOWN, 0u, 0u, 0u, 0u, PL_PROTO_OK},
    {2u, PL_FRAME_SHUTDOWN, 0u, 1u, 0u, 0u, PL_PROTO_RESERVED_NONZERO},
    {2u, PL_FRAME_SHUTDOWN, 1u, 0u, 0u, 0u, PL_PROTO_RESERVED_NONZERO},
    {2u, PL_FRAME_SHUTDOWN, 14337u, 0u, 0u, 0u, PL_PROTO_RESERVED_NONZERO},
    {2u, PL_FRAME_SHUTDOWN, UINT32_MAX, 0u, 0u, 0u, PL_PROTO_RESERVED_NONZERO},
    {2u, PL_FRAME_SHUTDOWN, 0u, 0u, 0u, 1u, PL_PROTO_LENGTH_MISMATCH},
    {2u, PL_FRAME_SHM_REQUEST, 14336u, 4u, 31u, 32u, PL_PROTO_OK},
    {2u, PL_FRAME_SHM_REQUEST, 1u, 0u, 7u, 31u, PL_PROTO_LENGTH_MISMATCH},
    {2u, PL_FRAME_SHM_REQUEST, 1u, 0u, 7u, 33u, PL_PROTO_LENGTH_MISMATCH},
    {2u, PL_FRAME_SHM_REQUEST, 14337u, 0u, 7u, 32u, PL_PROTO_RECORD_LIMIT},
    {2u, PL_FRAME_SHM_RESPONSE, 1u, 0u, 7u, 8u, PL_PROTO_OK},
    {2u, PL_FRAME_SHM_RESPONSE, 1u, 0u, 7u, 9u, PL_PROTO_LENGTH_MISMATCH},
    {2u, PL_FRAME_SHM_RESPONSE, 1u, 5u, 7u, 8u, PL_PROTO_BAD_THREADS},
};

/* Amendment G item G4.4 and Amendment I item I5.2: per-type models checks, in the header check
 * order (group `masks`). */
static const struct header_case MASKS_CASES[] = {
    {2u, PL_FRAME_REQUEST, 1u, 0u, 0u, 64u, PL_PROTO_BAD_MODELS},
    {2u, PL_FRAME_REQUEST, 1u, 0u, 32u, 64u, PL_PROTO_BAD_MODELS},
    {2u, PL_FRAME_REQUEST, 1u, 0u, UINT16_MAX, 64u, PL_PROTO_BAD_MODELS},
    /* a ping carries a mask too */
    {2u, PL_FRAME_REQUEST, 0u, 0u, 0u, 0u, PL_PROTO_BAD_MODELS},
    {2u, PL_FRAME_SHM_REQUEST, 1u, 0u, 32u, 32u, PL_PROTO_BAD_MODELS},
    {2u, PL_FRAME_SHM_REQUEST, 1u, 0u, 0u, 32u, PL_PROTO_BAD_MODELS},
    {2u, PL_FRAME_SHM_RESPONSE, 1u, 0u, 0u, 8u, PL_PROTO_BAD_MODELS},
    {2u, PL_FRAME_SHM_RESPONSE, 1u, 0u, 32u, 8u, PL_PROTO_BAD_MODELS},
    {2u, PL_FRAME_ERROR, 0u, 0u, 7u, 4u, PL_PROTO_RESERVED_NONZERO},
    {2u, PL_FRAME_SHUTDOWN, 0u, 0u, 7u, 0u, PL_PROTO_RESERVED_NONZERO},
    {2u, PL_FRAME_ERROR, 0u, 0u, 32u, 4u, PL_PROTO_RESERVED_NONZERO},
    /* threads before models */
    {2u, PL_FRAME_REQUEST, 1u, 5u, 0u, 63u, PL_PROTO_BAD_THREADS},
    /* models before the frame size and the length */
    {2u, PL_FRAME_REQUEST, 1u, 0u, 0u, 63u, PL_PROTO_BAD_MODELS},
    {2u, PL_FRAME_REQUEST, 1u, 0u, 32u, UINT32_MAX, PL_PROTO_BAD_MODELS},
    /* the record limit before models */
    {2u, PL_FRAME_REQUEST, 14337u, 0u, 0u, 64u, PL_PROTO_RECORD_LIMIT},
};

/* One loop, so that the GCC analyzer explores the header check once (the fixed analyzer
 * budget of the framework). */
static void run_cases(const struct header_case *c, size_t n) {
    for (size_t i = 0; i < n; i++) {
        const struct header_case *x = c + i;
        struct pl_header h = header(x->type, x->count, x->threads, x->models, x->payload);
        h.version = x->version;
        if (decode_one(h) != x->want) {
            fprintf(stderr, "FAIL header-case %zu\n", i);
            exit(1);
        }
    }
}

static void bytes(void) {
    uint8_t b[8];
    pl_store_u16(b, 0x0102u);
    REQUIRE(*b == 0x02u && *(b + 1) == 0x01u && pl_load_u16(b) == 0x0102u);
    pl_store_u32(b, UINT32_C(0x01020304));
    REQUIRE(*b == 0x04u && *(b + 3) == 0x01u && pl_load_u32(b) == UINT32_C(0x01020304));
    pl_store_u64(b, UINT64_C(0x0102030405060708));
    REQUIRE(*b == 0x08u && *(b + 7) == 0x01u && pl_load_u64(b) == UINT64_C(0x0102030405060708));
    pl_store_f64(b, -0.0);
    REQUIRE(*(b + 7) == 0x80u && pl_double_bits(pl_load_f64(b)) == UINT64_C(0x8000000000000000));
    pl_store_u64(b, NAN_BITS + 1u);
    REQUIRE(pl_double_bits(pl_load_f64(b)) == NAN_BITS + 1u);
    puts("PASS bytes");
}

static void headers(void) {
    const uint32_t three = 3u * PL_REQUEST_RECORD_BYTES;
    struct pl_header h = header(PL_FRAME_REQUEST, 3u, 2u, PL_MASK_ALL3, three);
    uint8_t buf[PL_HEADER_BYTES];
    pl_header_encode(&h, buf);
    struct pl_header out;
    REQUIRE(pl_header_decode(buf, sizeof buf, &out) == PL_PROTO_OK);
    REQUIRE(out.request_id == UINT64_C(0x0000000700000001) && out.record_count == 3u);
    REQUIRE(out.threads == 2u && out.models == 7u && out.payload_length == 192u);
    REQUIRE(*buf == 'S' && *(buf + 1) == 'C' && *(buf + 2) == 'P' && *(buf + 3) == 'L');
    REQUIRE(*(buf + 4) == 2u && *(buf + 5) == 0u && *(buf + 6) == 1u && *(buf + 8) == 1u);
    REQUIRE(*(buf + 12) == 7u && *(buf + 16) == 3u && *(buf + 20) == 2u);
    REQUIRE(*(buf + 22) == 7u && *(buf + 23) == 0u && *(buf + 24) == 192u && *(buf + 25) == 0u);
    REQUIRE(pl_header_decode(buf, PL_HEADER_BYTES - 1u, &out) == PL_PROTO_TRUNCATED);
    REQUIRE(out.version == 0u && out.record_count == 0u && out.payload_length == 0u);
    REQUIRE(pl_header_decode(buf, 0u, &out) == PL_PROTO_TRUNCATED);
    *buf = 'X';
    REQUIRE(pl_header_decode(buf, sizeof buf, &out) == PL_PROTO_BAD_MAGIC);
    *buf = 'S';
    *(buf + 3) = 'M';
    REQUIRE(pl_header_decode(buf, sizeof buf, &out) == PL_PROTO_BAD_MAGIC);
    struct pl_header v = h;
    v.version = 1u;
    /* a version-1 header followed by more bytes */
    REQUIRE(decode_one(v) == PL_PROTO_BAD_VERSION);
    v.version = 3u;
    REQUIRE(decode_one(v) == PL_PROTO_BAD_VERSION);
    v.version = 1u;
    pl_header_encode(&v, buf);
    /* a 26-byte version-1 frame at EOF */
    REQUIRE(pl_header_decode(buf, 26u, &out) == PL_PROTO_TRUNCATED);
    REQUIRE(decode_one(header(0u, 0u, 0u, 7u, 0u)) == PL_PROTO_BAD_TYPE);
    REQUIRE(decode_one(header(7u, 0u, 0u, 7u, 0u)) == PL_PROTO_BAD_TYPE);
    run_cases(HEADERS_CASES, sizeof HEADERS_CASES / sizeof *HEADERS_CASES);
    const uint32_t big = (uint32_t)pl_response_payload(14336u, 4u);
    REQUIRE(decode_one(header(PL_FRAME_RESPONSE, 14336u, 4u, 31u, big)) == PL_PROTO_OK);
    REQUIRE(decode_one(header(PL_FRAME_RESPONSE, 14336u, 4u, 31u, big + 1u)) ==
            PL_PROTO_LENGTH_MISMATCH);
    REQUIRE(pl_response_payload(14336u, 4u) == 4157508u && pl_response_payload(0u, 4u) == 4u);
    REQUIRE(pl_response_payload(2u, 4u) == 616u && pl_response_payload(8u, 2u) == 2356u);
    REQUIRE(pl_response_payload(1u, 4u) == 310u && pl_response_payload(1u, 0u) == 294u);
    REQUIRE(pl_response_payload(UINT32_MAX, 0u) == (size_t)UINT32_MAX * 290u + 4u);
    REQUIRE(PL_HEADER_BYTES + pl_response_payload(14336u, 4u) == 4157536u);
    REQUIRE(4157536u <= PL_MAX_FRAME_BYTES);
    /* count 14,337 is refused by the record limit first, so no frame-size bound for it is
     * required (I5.6) */
    puts("PASS headers");
}

/* Amendment G item G4.4 and Amendment I item I5.2: per-type models checks, in the header check
 * order. */
static void masks(void) {
    run_cases(MASKS_CASES, sizeof MASKS_CASES / sizeof *MASKS_CASES);
    const uint32_t one = (uint32_t)pl_response_payload(1u, 0u);
    /* 16 (alo only) and 31 (all five) included */
    for (uint16_t m = 1u; m <= 31u; m++) {
        REQUIRE(decode_one(header(PL_FRAME_REQUEST, 1u, 0u, m, 64u)) == PL_PROTO_OK);
        REQUIRE(decode_one(header(PL_FRAME_RESPONSE, 1u, 0u, m, one)) == PL_PROTO_OK);
        REQUIRE(decode_one(header(PL_FRAME_SHM_REQUEST, 1u, 0u, m, 32u)) == PL_PROTO_OK);
        REQUIRE(decode_one(header(PL_FRAME_SHM_RESPONSE, 1u, 0u, m, 8u)) == PL_PROTO_OK);
        REQUIRE(decode_one(header(PL_FRAME_ERROR, 0u, 0u, m, 4u)) == PL_PROTO_RESERVED_NONZERO);
        REQUIRE(decode_one(header(PL_FRAME_SHUTDOWN, 0u, 0u, m, 0u)) == PL_PROTO_RESERVED_NONZERO);
    }
    REQUIRE(decode_one(header(PL_FRAME_RESPONSE, 1u, 0u, 0u, one)) == PL_PROTO_BAD_MODELS);
    REQUIRE(decode_one(header(PL_FRAME_RESPONSE, 1u, 0u, 32u, one)) == PL_PROTO_BAD_MODELS);
    puts("PASS masks");
}

static void set_part(struct pl_contract_result *r, size_t m, uint8_t status, uint8_t flags,
                     int nan_values) {
    struct pl_model_result *x = r->model + m;
    x->status = status;
    x->flags = flags;
    for (size_t f = 0; f < PL_FIELDS; f++) {
        *(x->values + f) = nan_values ? pl_nan() : (double)f - 0.5;
    }
}

/* The flag bits allowed in the flag byte of model k (I5.3): 1, 2, 4, 8 everywhere; 16 and 32
 * in baw and alo; 64 in baw only; 128 never. */
static unsigned allowed_flags(size_t k) {
    if (k == PL_MODEL_BAW) {
        return 0x7Fu;
    }
    return k == PL_MODEL_ALO ? 0x3Fu : 0x0Fu;
}

static void flag_rule(void) {
    struct pl_contract_result r, back;
    for (size_t m = 0; m < PL_MODELS; m++) {
        set_part(&r, m, PL_OK, 0u, 0);
    }
    uint8_t out[PL_RESPONSE_RECORD_BYTES];
    pl_response_encode(&r, out);
    for (size_t k = 0; k < PL_MODELS; k++) {
        for (unsigned bit = 1u; bit <= 128u; bit <<= 1) {
            *(out + 5u + k) = (uint8_t)bit;
            const enum pl_proto_error e = pl_response_decode(out, PL_MASK_MODELS5, &back);
            const int ok = (allowed_flags(k) & bit) != 0u;
            REQUIRE(e == (ok ? PL_PROTO_OK : PL_PROTO_RESERVED_NONZERO));
            REQUIRE(!ok || (back.model + k)->flags == bit);
        }
        *(out + 5u + k) = (uint8_t)allowed_flags(k);
        REQUIRE(pl_response_decode(out, PL_MASK_MODELS5, &back) == PL_PROTO_OK);
        *(out + 5u + k) = 0u;
    }
    puts("PASS flag-rule");
}

static void records(void) {
    struct pl_row row = {1, 600.0, 610.0, 0.25, 12.5, 12.75, 0.04, 0.012}, back;
    uint8_t rec[PL_REQUEST_RECORD_BYTES];
    pl_request_encode(&row, rec);
    pl_request_decode(rec, &back);
    REQUIRE(back.side == 1 && back.S == 600.0 && back.K == 610.0 && back.T == 0.25);
    REQUIRE(back.bid == 12.5 && back.ask == 12.75 && back.r == 0.04 && back.q == 0.012);
    REQUIRE(pl_double_bits(pl_load_f64(rec + 56u)) == pl_double_bits(0.012));
    pl_store_f64(rec, 2.0);
    pl_request_decode(rec, &back);
    REQUIRE(back.side == -1);
    pl_store_f64(rec, pl_nan());
    pl_request_decode(rec, &back);
    REQUIRE(back.side == -1);
    pl_store_f64(rec, -0.0);
    pl_request_decode(rec, &back);
    /* -0.0 == 0.0, as Python's 0 in (0, 1) */
    REQUIRE(back.side == 0);
    pl_store_f64(rec, 0x1.0000000000001p0);
    pl_request_decode(rec, &back);
    REQUIRE(back.side == -1);
    row.side = 0;
    pl_request_encode(&row, rec);
    REQUIRE(pl_load_u64(rec) == UINT64_C(0));
    struct pl_contract_result r, r2;
    set_part(&r, 0u, PL_OK, 0u, 0);
    set_part(&r, 1u, PL_BELOW_MIN, 9u, 1);
    set_part(&r, 2u, PL_BELOW_MIN, 0u, 1);
    const uint8_t baw_flags = (uint8_t)(PL_FLAG_STENCIL_SWITCHED | PL_FLAG_ADMIT_EXCLUDED);
    set_part(&r, 3u, PL_MODEL_DOMAIN, baw_flags, 1);
    /* the alo part (Amendment I) */
    set_part(&r, 4u, PL_OK, PL_FLAG_STENCIL_SWITCHED, 0);
    uint8_t out[PL_RESPONSE_RECORD_BYTES];
    pl_response_encode(&r, out);
    REQUIRE(pl_response_decode(out, PL_MASK_MODELS5, &r2) == PL_PROTO_OK);
    REQUIRE((r2.model + 0)->status == PL_OK && (r2.model + 1)->flags == 9u);
    REQUIRE((r2.model + 3)->flags == 96u && (r2.model + 4)->flags == 32u);
    REQUIRE(*(out + 3) == PL_MODEL_DOMAIN && *(out + 8) == 96u && *(out + 9) == 32u);
    REQUIRE(pl_double_bits(pl_load_f64(out + 10u + 3u * 8u)) == pl_double_bits(2.5));
    REQUIRE(pl_is_nan(pl_load_f64(out + 10u + 56u * 2u)));
    REQUIRE(pl_is_nan(*((r2.model + 3)->values + 6)));
    /* alo block at offset 234, field 1 */
    REQUIRE(pl_double_bits(pl_load_f64(out + 234u + 8u)) == pl_double_bits(0.5));
    REQUIRE(pl_double_bits(pl_load_f64(out + 282u)) == pl_double_bits(5.5));
    REQUIRE(pl_double_bits(*((r2.model + 4)->values + 6)) == pl_double_bits(5.5));
    /* N7, I5.3: bits 16, 32, 64 are refused in the bsm, bjs and crr flag bytes */
    for (size_t k = 0; k < 3u; k++) {
        uint8_t keep = *(out + 5u + k);
        for (unsigned bit = 16u; bit <= 64u; bit <<= 1) {
            *(out + 5u + k) = (uint8_t)(keep | bit);
            REQUIRE(pl_response_decode(out, PL_MASK_MODELS5, &r2) == PL_PROTO_RESERVED_NONZERO);
        }
        *(out + 5u + k) = keep;
    }
    /* I5.3: bit 64 is refused in the alo flag byte */
    *(out + 9) = (uint8_t)(32u | PL_FLAG_ADMIT_EXCLUDED);
    REQUIRE(pl_response_decode(out, PL_MASK_MODELS5, &r2) == PL_PROTO_RESERVED_NONZERO);
    /* bits 16 and 32 are valid there */
    *(out + 9) = (uint8_t)(PL_FLAG_STENCIL_UNRESOLVED | PL_FLAG_STENCIL_SWITCHED);
    REQUIRE(pl_response_decode(out, PL_MASK_MODELS5, &r2) == PL_PROTO_OK);
    REQUIRE((r2.model + 4)->flags == 48u);
    /* bit 128 is never valid */
    *(out + 9) = (uint8_t)(*(out + 9) | 128u);
    REQUIRE(pl_response_decode(out, PL_MASK_MODELS5, &r2) == PL_PROTO_RESERVED_NONZERO);
    *(out + 9) = 32u;
    *(out + 8) = (uint8_t)(*(out + 8) | 128u);
    REQUIRE(pl_response_decode(out, PL_MASK_MODELS5, &r2) == PL_PROTO_RESERVED_NONZERO);
    *(out + 8) = 96u;
    *out = 9u;
    REQUIRE(pl_response_decode(out, PL_MASK_MODELS5, &r2) == PL_PROTO_RESERVED_NONZERO);
    *out = 253u;
    REQUIRE(pl_response_decode(out, PL_MASK_MODELS5, &r2) == PL_PROTO_RESERVED_NONZERO);
    /* a selected model never has 254 */
    *out = PL_NOT_REQUESTED;
    REQUIRE(pl_response_decode(out, PL_MASK_MODELS5, &r2) == PL_PROTO_RESERVED_NONZERO);
    *out = 255u;
    REQUIRE(pl_response_decode(out, PL_MASK_MODELS5, &r2) == PL_PROTO_OK);
    *out = 8u;
    REQUIRE(pl_response_decode(out, PL_MASK_MODELS5, &r2) == PL_PROTO_OK);
    *out = 0u;
    REQUIRE(pl_response_decode(out, PL_MASK_MODELS5, &r2) == PL_PROTO_OK);
    /* the response record decoder refuses a mask outside 1-31 */
    REQUIRE(pl_response_decode(out, 0u, &r2) == PL_PROTO_BAD_MODELS);
    REQUIRE(pl_response_decode(out, 32u, &r2) == PL_PROTO_BAD_MODELS);
    /* mask 1: bsm selected, the other parts NOT_REQUESTED */
    struct pl_contract_result one;
    set_part(&one, 0u, PL_OK, 0u, 0);
    for (size_t m = 1u; m < PL_MODELS; m++) {
        pl_result_not_requested(one.model + m);
    }
    REQUIRE((one.model + 4)->status == PL_NOT_REQUESTED && (one.model + 4)->flags == 0u);
    REQUIRE(pl_double_bits(*((one.model + 4)->values + 3)) == NAN_BITS);
    pl_response_encode(&one, out);
    REQUIRE(pl_response_decode(out, 1u, &r2) == PL_PROTO_OK);
    REQUIRE((r2.model + 3)->status == PL_NOT_REQUESTED);
    REQUIRE((r2.model + 4)->status == PL_NOT_REQUESTED);
    REQUIRE(*(out + 1) == 254u && *(out + 4) == 254u && *(out + 6) == 0u);
    REQUIRE(pl_load_u64(out + 10u + 56u * 4u + 48u) == NAN_BITS);
    /* bjs selected but NOT_REQUESTED */
    REQUIRE(pl_response_decode(out, 3u, &r2) == PL_PROTO_RESERVED_NONZERO);
    /* alo selected but NOT_REQUESTED */
    REQUIRE(pl_response_decode(out, 17u, &r2) == PL_PROTO_RESERVED_NONZERO);
    /* unselected flags */
    *(out + 6) = 1u;
    REQUIRE(pl_response_decode(out, 1u, &r2) == PL_PROTO_RESERVED_NONZERO);
    *(out + 6) = 0u;
    /* unselected alo flags */
    *(out + 9) = PL_FLAG_STENCIL_SWITCHED;
    REQUIRE(pl_response_decode(out, 1u, &r2) == PL_PROTO_RESERVED_NONZERO);
    *(out + 9) = 0u;
    /* unselected status */
    *(out + 2) = PL_OK;
    REQUIRE(pl_response_decode(out, 1u, &r2) == PL_PROTO_RESERVED_NONZERO);
    *(out + 2) = PL_NOT_REQUESTED;
    *(out + 4) = 255u;
    REQUIRE(pl_response_decode(out, 1u, &r2) == PL_PROTO_RESERVED_NONZERO);
    *(out + 4) = PL_NOT_REQUESTED;
    const uint64_t not_exact[3] = {UINT64_C(0xFFF8000000000000), UINT64_C(0x7FF8000000000001),
                                   UINT64_C(0)};
    /* the unselected fields must be exactly 0x7FF8000000000000 */
    for (size_t i = 0; i < 3u; i++) {
        pl_store_u64(out + 10u + 56u * 3u, *(not_exact + i));
        REQUIRE(pl_response_decode(out, 1u, &r2) == PL_PROTO_RESERVED_NONZERO);
    }
    pl_store_u64(out + 10u + 56u * 3u, NAN_BITS);
    REQUIRE(pl_response_decode(out, 1u, &r2) == PL_PROTO_OK);
    /* every field of every unselected part, the alo part included */
    for (size_t k = 1u; k < PL_MODELS; k++) {
        for (size_t j = 0; j < PL_FIELDS; j++) {
            uint8_t *field = out + 10u + 56u * k + 8u * j;
            pl_store_u64(field, NAN_BITS + 1u);
            REQUIRE(pl_response_decode(out, 1u, &r2) == PL_PROTO_RESERVED_NONZERO);
            pl_store_u64(field, NAN_BITS);
        }
    }
    REQUIRE(pl_response_decode(out, 1u, &r2) == PL_PROTO_OK);
    puts("PASS records");
}

/* I12: the full five-block response as a unit-test vector (ruling 47) */
static uint8_t full[PL_HEADER_BYTES + 4157508u];

static void full_response(void) {
    struct pl_contract_result r, back;
    for (size_t m = 0; m < PL_MODELS; m++) {
        set_part(&r, m, PL_OK, 0u, 0);
    }
    const uint32_t payload = (uint32_t)pl_response_payload(14336u, 4u);
    struct pl_header h = header(PL_FRAME_RESPONSE, 14336u, 4u, PL_MASK_MODELS5, payload);
    pl_header_encode(&h, full);
    for (size_t i = 0; i < 14336u; i++) {
        pl_response_encode(&r, full + PL_HEADER_BYTES + i * PL_RESPONSE_RECORD_BYTES);
    }
    const size_t sizes[4] = {3584u, 3584u, 3584u, 3584u};
    const uint64_t wall[4] = {1u, 1u, 1u, 1u};
    uint8_t *trailer = full + PL_HEADER_BYTES + 14336u * PL_RESPONSE_RECORD_BYTES;
    pl_trailer_encode(trailer, 4u, sizes, wall);
    REQUIRE(pl_load_u32(trailer) == 4u && pl_load_u32(trailer + 4u) == 3584u);
    REQUIRE(pl_load_u32(trailer + 8u) == 0u && pl_load_u64(trailer + 12u) == 1u);
    REQUIRE(pl_load_u32(trailer + 52u) == 3584u && pl_load_u64(trailer + 60u) == 1u);
    REQUIRE(trailer + 68u == full + sizeof full);
    struct pl_header out;
    REQUIRE(sizeof full == 4157536u && pl_header_decode(full, sizeof full, &out) == PL_PROTO_OK);
    REQUIRE(out.record_count == 14336u && out.models == 31u && out.payload_length == 4157508u);
    for (size_t i = 0; i < 14336u; i++) {
        const uint8_t *rec = full + PL_HEADER_BYTES + i * PL_RESPONSE_RECORD_BYTES;
        REQUIRE(pl_response_decode(rec, out.models, &back) == PL_PROTO_OK);
    }
    REQUIRE(pl_double_bits(*((back.model + 4)->values + 6)) == pl_double_bits(5.5));
    uint8_t zero[4];
    pl_trailer_encode(zero, 0u, NULL, NULL);
    REQUIRE(pl_load_u32(zero) == 0u);
    puts("PASS full-response");
}

/* The descriptor check for one record, threads 0 and the full region sizes. */
static enum pl_proto_error check1(const struct pl_shm_descriptor *d) {
    return pl_shm_descriptor_check(d, 1u, 0u, PL_SHM_INPUT_BYTES, PL_SHM_OUTPUT_BYTES);
}

static void shm(void) {
    uint8_t raw[PL_SHM_REQUEST_BYTES];
    pl_store_u64(raw, 1u);
    pl_store_u64(raw + 8u, 2u);
    pl_store_u64(raw + 16u, 3u);
    pl_store_u64(raw + 24u, UINT64_MAX);
    struct pl_shm_descriptor got;
    pl_shm_descriptor_decode(raw, &got);
    REQUIRE(got.in_offset == 1u && got.in_length == 2u && got.out_offset == 3u);
    REQUIRE(got.out_capacity == UINT64_MAX);
    struct pl_shm_descriptor d = {0u, 64u, 0u, 294u};
    REQUIRE(check1(&d) == PL_PROTO_OK);
    struct pl_shm_descriptor e = d;
    e.in_length = 63u;
    REQUIRE(check1(&e) == PL_PROTO_LENGTH_MISMATCH);
    e.in_length = 65u;
    REQUIRE(check1(&e) == PL_PROTO_LENGTH_MISMATCH);
    e = d;
    /* offset + length wraps */
    e.in_offset = UINT64_MAX - 8u;
    REQUIRE(check1(&e) == PL_PROTO_LENGTH_MISMATCH);
    e = d;
    /* past the region end; the exact end is accepted */
    e.in_offset = PL_SHM_INPUT_BYTES - 32u;
    REQUIRE(check1(&e) == PL_PROTO_LENGTH_MISMATCH);
    e.in_offset = PL_SHM_INPUT_BYTES - 64u;
    REQUIRE(check1(&e) == PL_PROTO_OK);
    e.in_offset = PL_SHM_INPUT_BYTES - 63u;
    REQUIRE(check1(&e) == PL_PROTO_LENGTH_MISMATCH);
    e = d;
    e.out_capacity = 293u;
    REQUIRE(check1(&e) == PL_PROTO_LENGTH_MISMATCH);
    e = d;
    e.out_offset = PL_SHM_OUTPUT_BYTES - 294u;
    REQUIRE(check1(&e) == PL_PROTO_OK);
    e.out_offset = PL_SHM_OUTPUT_BYTES - 293u;
    REQUIRE(check1(&e) == PL_PROTO_LENGTH_MISMATCH);
    e.out_offset = UINT64_MAX;
    REQUIRE(check1(&e) == PL_PROTO_LENGTH_MISMATCH);
    /* truncated region */
    REQUIRE(pl_shm_descriptor_check(&d, 1u, 0u, 32u, PL_SHM_OUTPUT_BYTES) ==
            PL_PROTO_LENGTH_MISMATCH);
    REQUIRE(pl_shm_descriptor_check(&d, 1u, 0u, 64u, 294u) == PL_PROTO_OK);
    REQUIRE(pl_shm_descriptor_check(&d, 1u, 0u, 64u, 293u) == PL_PROTO_LENGTH_MISMATCH);
    REQUIRE(pl_shm_descriptor_check(&d, 1u, 0u, PL_SHM_INPUT_BYTES + 1u, PL_SHM_OUTPUT_BYTES) ==
            PL_PROTO_FRAME_LIMIT);
    REQUIRE(pl_shm_descriptor_check(&d, 1u, 0u, PL_SHM_INPUT_BYTES, PL_SHM_OUTPUT_BYTES + 1u) ==
            PL_PROTO_FRAME_LIMIT);
    struct pl_shm_descriptor max = {0u, 14336u * 64u, 0u, 4157508u};
    REQUIRE(pl_shm_descriptor_check(&max, 14336u, 4u, PL_SHM_INPUT_BYTES, PL_SHM_OUTPUT_BYTES) ==
            PL_PROTO_OK);
    max.out_capacity = 4157507u;
    REQUIRE(pl_shm_descriptor_check(&max, 14336u, 4u, PL_SHM_INPUT_BYTES, PL_SHM_OUTPUT_BYTES) ==
            PL_PROTO_LENGTH_MISMATCH);
    puts("PASS shm");
}

int main(void) {
    bytes();
    headers();
    masks();
    flag_rule();
    records();
    full_response();
    shm();
    uint8_t e[PL_ERROR_PAYLOAD_BYTES];
    uint16_t code = 0u;
    pl_error_encode(PL_PROTO_KERNEL_FAILURE, e);
    REQUIRE(pl_error_decode(e, &code) == PL_PROTO_OK && code == 9u);
    REQUIRE(*e == 9u && *(e + 1) == 0u && *(e + 2) == 0u && *(e + 3) == 0u);
    *(e + 2) = 1u;
    REQUIRE(pl_error_decode(e, &code) == PL_PROTO_RESERVED_NONZERO);
    *(e + 2) = 0u;
    *(e + 3) = 128u;
    REQUIRE(pl_error_decode(e, &code) == PL_PROTO_RESERVED_NONZERO);
    pl_error_encode(PL_PROTO_BAD_MODELS, e);
    REQUIRE(pl_error_decode(e, &code) == PL_PROTO_OK && code == 12u);
    puts("PASS errors");
    return 0;
}
