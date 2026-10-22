#include "pl_canonical.h"
#include "pl_ieee.h"
#include "pl_protocol.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Tests of pl_sink.c, pl_sink_format.c and pl_canonical.c (specs/project/protocol.md "Canonical
 * form"): the sink writers, the FNV-1a 64 digest of the sink (known answers), every status name,
 * the refusals (-1) and sink failures (-2). The
 * vector texts are in test_canonical.c. REQUIRE-style checks stay active under NDEBUG; the first
 * failed check prints its line and exits 1. */

#define REQUIRE_FAIL(c) (fprintf(stderr, "%s:%d: REQUIRE %s\n", __FILE__, __LINE__, #c), exit(1))
#define REQUIRE(c) ((c) ? (void)0 : REQUIRE_FAIL(c))

static struct pl_contract_result rows[2];
static uint8_t mem[8192];

static struct pl_sink memory_sink(size_t cap) {
    struct pl_sink s = {-1, mem, cap, 0u, 0, 0u, 0u};
    return s;
}

/* A digest sink (fd < 0, buf NULL): no byte kept, never failed. */
static struct pl_sink digest_sink(void) {
    struct pl_sink s = {-1, NULL, 0u, 0u, 0, 0u, 0u};
    return s;
}

/* FNV-1a 64 known answers (offset basis 0xcbf29ce484222325, prime 0x100000001b3): "" and "a"
 * and "foobar" in a digest sink; a memory sink that fails after its capacity still digests every
 * byte given to it, as total counts it (protocol.md "Sink"). */
static void digest(void) {
    struct pl_sink d = digest_sink();
    REQUIRE(pl_sink_fnv(&d) == UINT64_C(0xcbf29ce484222325) && d.total == 0u);
    pl_sink_text(&d, "a");
    REQUIRE(pl_sink_fnv(&d) == UINT64_C(0xaf63dc4c8601ec8c));
    REQUIRE(d.total == 1u && d.len == 0u && d.failed == 0 && pl_sink_flush(&d) == 0);
    d = digest_sink();
    pl_sink_text(&d, "foobar");
    REQUIRE(pl_sink_fnv(&d) == UINT64_C(0x85944171f73967e8) && d.total == 6u && d.failed == 0);
    struct pl_sink m = memory_sink(3u);
    pl_sink_text(&m, "foobar");
    REQUIRE(m.failed == 1 && m.len == 3u && pl_sink_fnv(&m) == UINT64_C(0x85944171f73967e8));
    /* the product at zero, one, the 32-bit half maxima and UINT64_MAX (no wrap: integer gate) */
    REQUIRE(pl_fnv1a_mul(0u) == 0u && pl_fnv1a_mul(1u) == UINT64_C(0x00000100000001b3));
    REQUIRE(pl_fnv1a_mul(UINT64_C(0xffffffff)) == UINT64_C(0x000000b2fffffe4d));
    REQUIRE(pl_fnv1a_mul(UINT64_C(0xffffffff00000000)) == UINT64_C(0xfffffe4d00000000));
    REQUIRE(pl_fnv1a_mul(UINT64_MAX) == UINT64_C(0xfffffefffffffe4d));
    puts("PASS digest");
}

static int same_text(const struct pl_sink *s, const char *text) {
    const size_t n = strlen(text);
    if (s->len != n || s->total != n || s->failed != 0) {
        return 0;
    }
    return memcmp(s->buf, text, n) == 0;
}

static uint8_t record[PL_RESPONSE_RECORD_BYTES];

/* Once: a response record whose five parts are status OK, flags 0 and NaN values. */
static void build_record(void) {
    struct pl_contract_result r;
    for (size_t m = 0; m < PL_MODELS; m++) {
        pl_result_not_requested(r.model + m);
        (r.model + m)->status = PL_OK;
    }
    pl_response_encode(&r, record);
}

/* Two rows equal to that record, restored with the record decoder (the fixed GCC analyzer budget
 * of the framework). */
static void ok_rows(void) {
    REQUIRE(pl_response_decode(record, PL_MASK_MODELS5, rows) == PL_PROTO_OK);
    REQUIRE(pl_response_decode(record, PL_MASK_MODELS5, rows + 1) == PL_PROTO_OK);
}

static void sink(void) {
    struct pl_sink s = memory_sink(sizeof mem);
    pl_sink_uint(&s, 0u);
    pl_sink_text(&s, ",");
    pl_sink_uint(&s, UINT64_MAX);
    REQUIRE(pl_sink_flush(&s) == 0);
    REQUIRE(same_text(&s, "0,18446744073709551615"));
    s = memory_sink(sizeof mem);
    pl_sink_hex_bits(&s, -0.0);
    pl_sink_text(&s, ",");
    pl_sink_hex_bits(&s, -0.25);
    pl_sink_text(&s, ",");
    pl_sink_hex_bits(&s, 0x1.23456789abcdfp-1000);
    REQUIRE(same_text(&s, "0000000000000000,bfd0000000000000,01723456789abcdf"));
    struct pl_sink small = memory_sink(3u);
    pl_sink_text(&small, "abc");
    REQUIRE(small.failed == 0 && small.len == 3u && pl_sink_flush(&small) == 0);
    pl_sink_text(&small, "d");
    REQUIRE(small.failed == 1 && small.len == 3u && small.total == 4u);
    REQUIRE(pl_sink_flush(&small) == -1);
    struct pl_sink none = memory_sink(0u);
    pl_sink_uint(&none, 7u);
    REQUIRE(none.failed == 1 && none.len == 0u && none.total == 1u);
    puts("PASS sink");
}

/* 1 when the sink bytes at *at start with piece; then *at moves past it. */
static int has_piece(const struct pl_sink *s, size_t *at, const char *piece) {
    const size_t n = strlen(piece);
    if (*at > s->len || n > s->len - *at || memcmp(s->buf + *at, piece, n) != 0) {
        return 0;
    }
    *at += n;
    return 1;
}

/* A one-row mask-1 result with status `status`, flags 0 and NaN values: the canonical_result
 * form of protocol.md with the JSON string of the status. */
static void status_case(uint8_t status, const char *name) {
    struct pl_contract_result one;
    for (size_t m = 0; m < PL_MODELS; m++) {
        pl_result_not_requested(one.model + m);
    }
    one.model->status = status;
    struct pl_sink s = memory_sink(sizeof mem);
    REQUIRE(pl_canonical_write(&s, &one, 1u, 1u) == 0);
    size_t at = 0u;
    REQUIRE(has_piece(&s, &at, "{\"digest_form\":\"ocg-v1m\",\"mask\":1,\"models\":{\"bsm\":{"));
    REQUIRE(has_piece(&s, &at, "\"delta\":[null],\"flags\":[0],\"gamma\":[null],\"iv\":[null],"));
    REQUIRE(has_piece(&s, &at, "\"price\":[null],\"rho\":[null],\"status\":[\""));
    REQUIRE(has_piece(&s, &at, name));
    REQUIRE(has_piece(&s, &at, "\"],\"theta\":[null],\"vega\":[null]}},\"n\":1}"));
    REQUIRE(at == s.len && s.total == s.len);
}

/* The status names of spec 3.3, written independently of pl_canonical.c. */
static const char *status_name(unsigned status) {
    switch (status) {
    case PL_INVALID_INPUT:
        return "INVALID_INPUT";
    case PL_EXPIRED:
        return "EXPIRED";
    case PL_NO_BID:
        return "NO_BID";
    case PL_CROSSED:
        return "CROSSED";
    case PL_MODEL_DOMAIN:
        return "MODEL_DOMAIN";
    case PL_BELOW_MIN:
        return "BELOW_MIN";
    case PL_ABOVE_MAX:
        return "ABOVE_MAX";
    case PL_NOT_CONVERGED:
        return "NOT_CONVERGED";
    default:
        return "OK";
    }
}

/* Every status name of spec 3.3 (one loop: the fixed analyzer budget of the framework). */
static void statuses(void) {
    for (unsigned status = PL_INVALID_INPUT; status <= PL_OK; status++) {
        status_case((uint8_t)status, status_name(status));
    }
    puts("PASS statuses");
}

static void refusals(void) {
    ok_rows();
    struct pl_sink s = memory_sink(sizeof mem);
    *((rows + 1)->model->values + PL_PRICE) = pl_inf();
    REQUIRE(pl_canonical_write(&s, rows, 2u, PL_MASK_MODELS5) == -1);
    REQUIRE(s.len == 0u && s.total == 0u);
    *((rows + 1)->model->values + PL_PRICE) = -pl_inf();
    REQUIRE(pl_canonical_write(&s, rows, 2u, PL_MASK_MODELS5) == -1);
    /* an unselected part never enters the bytes, whatever it holds */
    REQUIRE(pl_canonical_write(&s, rows, 2u, 30u) == 0);
    ok_rows();
    ((rows + 0)->model + 2)->status = 9u;
    s = memory_sink(sizeof mem);
    REQUIRE(pl_canonical_write(&s, rows, 2u, PL_MASK_MODELS5) == -1 && s.total == 0u);
    REQUIRE(pl_canonical_write(&s, rows, 2u, 27u) == 0);
    ((rows + 0)->model + 2)->status = PL_NOT_REQUESTED;
    s = memory_sink(sizeof mem);
    REQUIRE(pl_canonical_write(&s, rows, 2u, PL_MASK_MODELS5) == -1);
    ((rows + 0)->model + 2)->status = PL_ECHO;
    REQUIRE(pl_canonical_write(&s, rows, 2u, PL_MASK_MODELS5) == -1);
    ((rows + 0)->model + 2)->status = PL_OK;
    REQUIRE(pl_canonical_write(&s, rows, 2u, PL_MASK_MODELS5) == 0);
    s = memory_sink(sizeof mem);
    REQUIRE(pl_canonical_write(&s, rows, 2u, 0u) == -1);
    REQUIRE(pl_canonical_write(&s, rows, 2u, 32u) == -1);
    REQUIRE(pl_canonical_write(&s, rows, 2u, UINT16_MAX) == -1 && s.total == 0u);
    REQUIRE(pl_canonical_write(&s, rows, 2u, 1u) == 0);
    struct pl_sink tiny = memory_sink(16u);
    REQUIRE(pl_canonical_write(&tiny, rows, 2u, PL_MASK_ALL3) == -2);
    puts("PASS refusals");
}

int main(void) {
    build_record();
    sink();
    digest();
    statuses();
    refusals();
    return 0;
}
