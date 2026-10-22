#define _GNU_SOURCE
#include "pl_canonical.h"
#include "pl_ieee.h"
#include "pl_io.h"
#include "pl_protocol.h"
#include "pl_vec_canonical.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* Tests of pl_canonical.c (specs/project/protocol.md "Canonical form"): the bytes of
 * optionlab.reference.canonical_result for every mask of cvectors.CANON_MASKS (ocg-v1 for mask
 * 7, ocg-v1m otherwise; Amendment G item G5, Amendment I item I6), the empty result, the exact
 * sink capacity, the kernel digest of the mask-7 bytes shared with the Python codec tests (EX-10)
 * and the descriptor sink. test_canonical_sink.c holds the sink, status-name and
 * refusal groups (a second file: the fixed GCC analyzer budget of the framework). REQUIRE-style
 * checks stay active under NDEBUG; the first failed check prints its line and exits 1. */

#define REQUIRE_FAIL(c) (fprintf(stderr, "%s:%d: REQUIRE %s\n", __FILE__, __LINE__, #c), exit(1))
#define REQUIRE(c) ((c) ? (void)0 : REQUIRE_FAIL(c))

static struct pl_contract_result rows[2];
static uint8_t records[2u * PL_RESPONSE_RECORD_BYTES];
static uint8_t mem[8192];

static void load_rows(void) {
    for (size_t i = 0; i < PL_VEC_CANONICAL_COUNT; i++) {
        const struct pl_vec_canonical *v = PL_VEC_CANONICAL + i;
        REQUIRE(v->row >= 0 && v->row < 2 && v->model >= 0 && v->model < (int)PL_MODELS);
        struct pl_model_result *m = (rows + v->row)->model + v->model;
        m->status = (uint8_t)v->status;
        m->flags = (uint8_t)v->flags;
        *(m->values + PL_IV) = pl_bits_double(v->iv);
        *(m->values + PL_PRICE) = pl_bits_double(v->price);
        *(m->values + PL_DELTA) = pl_bits_double(v->delta);
        *(m->values + PL_GAMMA) = pl_bits_double(v->gamma);
        *(m->values + PL_THETA) = pl_bits_double(v->theta);
        *(m->values + PL_VEGA) = pl_bits_double(v->vega);
        *(m->values + PL_RHO) = pl_bits_double(v->rho);
    }
    REQUIRE(PL_VEC_CANONICAL_COUNT == 2u * PL_MODELS);
    pl_response_encode(rows, records);
    pl_response_encode(rows + 1, records + PL_RESPONSE_RECORD_BYTES);
}

/* rows = the vector rows (kept as two response records by load_rows) with the unselected parts
 * of mask NOT_REQUESTED. The rows are restored with the record decoder, so that the GCC analyzer
 * stays within the fixed analyzer budget of the framework. */
static void select_rows(unsigned mask) {
    REQUIRE(pl_response_decode(records, PL_MASK_MODELS5, rows) == PL_PROTO_OK);
    const uint8_t *second = records + PL_RESPONSE_RECORD_BYTES;
    REQUIRE(pl_response_decode(second, PL_MASK_MODELS5, rows + 1) == PL_PROTO_OK);
    for (size_t e = 0; e < 2u * PL_MODELS; e++) {
        const size_t m = e % PL_MODELS;
        if (((mask >> m) & 1u) == 0u) {
            pl_result_not_requested((rows + e / PL_MODELS)->model + m);
        }
    }
}

static struct pl_sink memory_sink(size_t cap) {
    struct pl_sink s = {-1, mem, cap, 0u, 0, 0u, 0u};
    return s;
}

/* The kernel digest (specs/project/batch.md "Kernel digest"): the FNV-1a 64 of the ocg-v1 bytes of
 * the vector rows (mask 7) in a digest sink. tests/test_light_native_codec.py holds the same
 * literals for the Python side (cvectors.canonical_case(), mask 7: 801 bytes). */
#define SHARED_BYTES 801u
#define SHARED_DIGEST UINT64_C(0xb15cff783c8bac90)
#define EMPTY_DIGEST UINT64_C(0x528a621ba8b587ff)

static void shared_digest(void) {
    select_rows(PL_MASK_ALL3);
    struct pl_sink d = {-1, NULL, 0u, 0u, 0, 0u, 0u};
    REQUIRE(pl_canonical_write(&d, rows, 2u, PL_MASK_ALL3) == 0);
    REQUIRE(d.total == SHARED_BYTES && d.len == 0u && pl_sink_fnv(&d) == SHARED_DIGEST);
    struct pl_sink e = {-1, NULL, 0u, 0u, 0, 0u, 0u};
    REQUIRE(pl_canonical_write(&e, NULL, 0u, PL_MASK_ALL3) == 0 && pl_sink_fnv(&e) == EMPTY_DIGEST);
    puts("PASS shared-digest");
}

static int same_text(const struct pl_sink *s, const char *text) {
    const size_t n = strlen(text);
    if (s->len != n || s->total != n || s->failed != 0) {
        return 0;
    }
    return memcmp(s->buf, text, n) == 0;
}

static int starts_with(const char *text, const char *prefix) {
    return strncmp(text, prefix, strlen(prefix)) == 0;
}

static void texts(void) {
    for (size_t t = 0; t < PL_VEC_CANONICAL_TEXT_COUNT; t++) {
        const struct pl_vec_canonical_text *v = PL_VEC_CANONICAL_TEXT + t;
        const uint16_t mask = (uint16_t)v->mask;
        if (mask == PL_MASK_ALL3) {
            REQUIRE(starts_with(v->text, "{\"digest_form\":\"ocg-v1\",\"models\":"));
        } else {
            REQUIRE(starts_with(v->text, "{\"digest_form\":\"ocg-v1m\",\"mask\":"));
        }
        select_rows(mask);
        struct pl_sink s = memory_sink(sizeof mem);
        REQUIRE(pl_canonical_write(&s, rows, 2u, mask) == 0);
        REQUIRE(same_text(&s, v->text));
        struct pl_sink e = memory_sink(sizeof mem);
        REQUIRE(pl_canonical_write(&e, NULL, 0u, mask) == 0);
        REQUIRE(same_text(&e, v->empty));
        /* the exact capacity holds the text; one byte less fails */
        const size_t n = strlen(v->text);
        struct pl_sink exact = memory_sink(n);
        REQUIRE(pl_canonical_write(&exact, rows, 2u, mask) == 0 && exact.len == n);
        struct pl_sink short_sink = memory_sink(n - 1u);
        REQUIRE(pl_canonical_write(&short_sink, rows, 2u, mask) == -2);
    }
    puts("PASS texts");
}

static void descriptor(void) {
    const size_t last = PL_VEC_CANONICAL_TEXT_COUNT - 1u;
    const struct pl_vec_canonical_text *v = PL_VEC_CANONICAL_TEXT + last;
    const size_t n = strlen(v->text);
    select_rows((unsigned)v->mask);
    FILE *f = tmpfile();
    REQUIRE(f != NULL);
    const int fd = fileno(f);
    uint8_t buf[7];
    struct pl_sink s = {fd, buf, sizeof buf, 0u, 0, 0u, 0u};
    const int rc = pl_canonical_write(&s, rows, 2u, (uint16_t)v->mask);
    const int got = pl_pread_exact(fd, mem, n, 0u) == PL_IO_OK;
    const int past = pl_pread_exact(fd, mem + n, 1u, n) == PL_IO_TRUNCATED;
    REQUIRE(fclose(f) == 0);
    REQUIRE(rc == 0 && s.total == n && s.len == 0u && got && past);
    REQUIRE(memcmp(mem, v->text, n) == 0);
    /* a descriptor that is not open: the flush fails, the write returns -2 */
    const int closed = dup(1);
    REQUIRE(closed >= 0 && close(closed) == 0);
    struct pl_sink bad = {closed, buf, sizeof buf, 0u, 0, 0u, 0u};
    REQUIRE(pl_canonical_write(&bad, rows, 2u, (uint16_t)v->mask) == -2 && bad.failed == 1);
    REQUIRE(pl_sink_flush(&bad) == -1);
    struct pl_sink zero_cap = {1, buf, 0u, 0u, 0, 0u, 0u};
    pl_sink_text(&zero_cap, "x");
    REQUIRE(zero_cap.failed == 1 && zero_cap.total == 1u);
    puts("PASS descriptor");
}

int main(void) {
    load_rows();
    texts();
    shared_digest();
    descriptor();
    return 0;
}
