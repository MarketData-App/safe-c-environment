#include "pl_partition.h"
#include "pl_vec_partition.h"
#include <stdio.h>
#include <stdlib.h>

/* Tests of pl_partition.c and pl_partition_arith.c (specs/project/batch.md "Partition"): the
 * Amendment E known answers, exact 128-bit products, the forced Lemire rejection path (the Phase 1
 * stub test), the explicit chunk lists and the fingerprints of benchlab.pools.request_chunks for
 * every size tier and the request-limit sizes with workers 1, 2 and 4 (the binding C pool check
 * of Amendment E item 3), the limits, the request limit 14,336 and the write extent.
 * REQUIRE-style: the first failed check prints "FAIL <group> <index>" and exits 1 (active under
 * NDEBUG). The checks are macros, so the GCC analyzer explores each check once (the fixed analyzer
 * budget of the framework). */

#define FAIL(group, i) (printf("FAIL %s %zu\n", group, (size_t)(i)), exit(1))
#define CHECK(group, i, ok) ((ok) ? (void)0 : FAIL(group, i))

#define CAP 20000u
static uint32_t perm[CAP];
static uint8_t mark[CAP];
static uint32_t indices[CAP];

/* FNV-1a 64 over each request in order and each chunk in order: the chunk size, then each
 * absolute index (optionlab.cvectors.partition_fingerprint). */
static uint64_t fingerprint(size_t n, unsigned w) {
    uint64_t h = UINT64_C(0xcbf29ce484222325);
    for (size_t r = 0; r < pl_request_count(n); r++) {
        const size_t a = r * PL_REQUEST_LIMIT;
        const size_t m = n - a < PL_REQUEST_LIMIT ? n - a : PL_REQUEST_LIMIT;
        struct pl_chunk chunks[PL_MAX_WORKERS];
        size_t count = 0u;
        const int rc = pl_request_chunks(m, w, r, perm, mark, indices, CAP, chunks, &count);
        CHECK("fingerprint-rc", r, rc == 0);
        for (size_t k = 0; k < count; k++) {
            const struct pl_chunk *c = chunks + k;
            h = pl_fnv1a64_u32(h, (uint32_t)c->count);
            for (size_t j = 0; j < c->count; j++) {
                h = pl_fnv1a64_u32(h, (uint32_t)(a + *(indices + c->offset + j)));
            }
        }
    }
    return h;
}

static void known_answers(void) {
    static const uint64_t first[3] = PL_VEC_SPLITMIX_FIRST;
    struct pl_random g;
    pl_random_init(&g, PL_PARTITION_SEED);
    for (size_t i = 0; i < 3u; i++) {
        CHECK("splitmix", i, pl_random_next(&g) == *(first + i));
    }
    CHECK("spec-splitmix", 0u, *(first + 0) == UINT64_C(0xae58eab7f35199e4));
    CHECK("spec-splitmix", 1u, *(first + 1) == UINT64_C(0xa16951b663213f43));
    CHECK("spec-splitmix", 2u, *(first + 2) == UINT64_C(0xcc4ea8b7bd8207bd));
    static const uint32_t p0[10] = PL_VEC_PERM10_R0, p1[10] = PL_VEC_PERM10_R1;
    static const uint32_t spec0[10] = {0, 3, 1, 4, 8, 2, 7, 9, 5, 6};
    static const uint32_t spec1[10] = {9, 6, 2, 7, 8, 5, 1, 3, 4, 0};
    CHECK("perm0", 10u, pl_permutation(10u, 0u, perm, CAP) == 0);
    for (size_t i = 0; i < 10u; i++) {
        CHECK("perm0", i, *(perm + i) == *(p0 + i));
        CHECK("spec-perm0", i, *(p0 + i) == *(spec0 + i));
    }
    CHECK("perm1", 10u, pl_permutation(10u, 1u, perm, CAP) == 0);
    for (size_t i = 0; i < 10u; i++) {
        CHECK("perm1", i, *(perm + i) == *(p1 + i));
        CHECK("spec-perm1", i, *(p1 + i) == *(spec1 + i));
    }
    /* r = 2^64 - 1: the state PL_PARTITION_SEED + r wraps modulo 2^64. */
    static const uint32_t pmax[10] = PL_VEC_PERM10_RMAX;
    CHECK("perm-rmax", 10u, pl_permutation(10u, UINT64_MAX, perm, CAP) == 0);
    for (size_t i = 0; i < 10u; i++) {
        CHECK("perm-rmax", i, *(perm + i) == *(pmax + i));
    }
    /* Spec chunks for m = 10, w = 4, r = 0: [0, 3], [1, 4, 8], [2, 7], [5, 6, 9]. */
    static const uint32_t spec_chunks[10] = {0, 3, 1, 4, 8, 2, 7, 5, 6, 9};
    static const size_t spec_sizes[4] = {2u, 3u, 2u, 3u};
    struct pl_chunk chunks[PL_MAX_WORKERS];
    size_t count = 0u;
    const int rc = pl_request_chunks(10u, 4u, 0u, perm, mark, indices, CAP, chunks, &count);
    CHECK("spec-chunks", 10u, rc == 0 && count == 4u);
    size_t at = 0u;
    for (size_t k = 0; k < 4u; k++) {
        CHECK("spec-sizes", k, (chunks + k)->count == *(spec_sizes + k));
        CHECK("spec-offsets", k, (chunks + k)->offset == at);
        at += *(spec_sizes + k);
    }
    for (size_t i = 0; i < 10u; i++) {
        CHECK("spec-chunks", i, *(indices + i) == *(spec_chunks + i));
    }
}

static void arithmetic(void) {
    for (size_t i = 0; i < PL_VEC_PARTITION_MUL_COUNT; i++) {
        const struct pl_vec_partition_mul *v = PL_VEC_PARTITION_MUL + i;
        uint64_t hi = 0u;
        uint64_t lo = 0u;
        pl_mul_64(v->a, v->b, &hi, &lo);
        CHECK("mul", i, hi == v->hi && lo == v->lo);
    }
    uint64_t hi = 5u;
    pl_mul_64(2u, 3u, &hi, NULL);
    pl_mul_64(2u, 3u, NULL, &hi);
    CHECK("mul-null", 0u, hi == 5u);
    CHECK("add", 0u, pl_add_64(1u, 2u) == 3u);
    CHECK("add", 1u, pl_add_64(0u, UINT64_MAX) == UINT64_MAX);
    CHECK("add", 2u, pl_add_64(UINT64_MAX, 1u) == 0u);
    CHECK("add", 3u, pl_add_64(UINT64_MAX, UINT64_MAX) == UINT64_MAX - 1u);
    CHECK("add", 4u, pl_add_64(PL_PARTITION_SEED, UINT64_MAX) == PL_PARTITION_SEED - 1u);
}

/* One scripted draw: the result, the number of generator calls and no script overrun. */
static void draw_case(size_t i, const uint64_t *script, size_t len, uint64_t t, uint64_t want,
                      size_t calls) {
    struct pl_random g;
    pl_random_init(&g, 0u);
    g.script = script;
    g.script_len = len;
    uint64_t got = 0u;
    const int rc = pl_random_bounded(&g, t, &got);
    CHECK("rejection", i, rc == 0 && got == want && g.calls == calls && g.script_overrun == 0);
}

/* A script that runs out during the draw: -1, nothing written, the overrun flag set. */
static void overrun_case(size_t i, const uint64_t *script, size_t len, size_t calls) {
    struct pl_random g;
    pl_random_init(&g, 0u);
    g.script = script;
    g.script_len = len;
    uint64_t got = 7u;
    const int rc = pl_random_bounded(&g, 3u, &got);
    CHECK("overrun", i, rc == -1 && got == 7u && g.calls == calls && g.script_overrun == 1);
}

static void forced_rejection(void) {
    /* Mirrors tests/unit/test_bench_pools.py test_bounded_draw_rejection_path (Phase 1). t = 3:
     * threshold 1; t = 2^32 and t = 1: threshold 0; t = 2^32 - 1: threshold 1. */
    static const uint64_t one[2] = {0u, UINT64_C(1) << 63};
    static const uint64_t three[4] = {0u, 0u, 0u, UINT64_MAX};
    static const uint64_t inv3[1] = {UINT64_C(0xaaaaaaaaaaaaaaab)};
    static const uint64_t top[1] = {UINT64_MAX};
    static const uint64_t zero[1] = {0u};
    const uint64_t t32 = UINT64_C(1) << 32;
    draw_case(0u, one, 2u, 3u, 1u, 2u);
    draw_case(1u, three, 4u, 3u, 2u, 4u);
    draw_case(2u, inv3, 1u, 3u, 2u, 1u);
    draw_case(3u, top, 1u, t32, UINT32_MAX, 1u);
    draw_case(4u, zero, 1u, t32, 0u, 1u);
    draw_case(5u, zero, 1u, 1u, 0u, 1u);
    draw_case(6u, top, 1u, 1u, 0u, 1u);
    draw_case(7u, one, 2u, t32 - 1u, UINT64_C(0x7fffffff), 2u);
    overrun_case(0u, zero, 0u, 1u);
    overrun_case(1u, zero, 1u, 2u);
    struct pl_random g;
    pl_random_init(&g, 0u);
    uint64_t got = 7u;
    CHECK("bounds", 0u, pl_random_bounded(&g, 0u, &got) == -1);
    CHECK("bounds", 1u, pl_random_bounded(&g, t32 + 1u, &got) == -1);
    CHECK("bounds", 2u, pl_random_bounded(NULL, 3u, &got) == -1);
    CHECK("bounds", 3u, pl_random_bounded(&g, 3u, NULL) == -1);
    CHECK("bounds", 4u, got == 7u && g.calls == 0u);
    CHECK("bounds", 5u, pl_random_bounded(&g, t32, &got) == 0 && got < t32 && g.calls == 1u);
    CHECK("bounds", 6u, pl_random_bounded(&g, 1u, &got) == 0 && got == 0u);
    CHECK("null", 0u, pl_random_next(NULL) == 0u);
    pl_random_init(NULL, 1u);
}

static void chunk_lists(void) {
    for (size_t i = 0; i < PL_VEC_PARTITION_CHUNK_COUNT; i++) {
        const struct pl_vec_partition_chunk *v = PL_VEC_PARTITION_CHUNK + i;
        struct pl_chunk chunks[PL_MAX_WORKERS];
        size_t count = 0u;
        const size_t n = (size_t)v->n;
        const unsigned w = (unsigned)v->workers;
        const size_t k = (size_t)v->chunk;
        const int rc = pl_request_chunks(n, w, 0u, perm, mark, indices, CAP, chunks, &count);
        CHECK("chunk", i, rc == 0 && k < count && k < PL_MAX_WORKERS);
        CHECK("chunk-count", i, (chunks + k)->count == (size_t)v->count);
        for (size_t j = 0; j < (size_t)v->count; j++) {
            CHECK("chunk-index", i, *(indices + (chunks + k)->offset + j) == *(v->index + j));
        }
    }
}

static void fingerprints(void) {
    for (size_t i = 0; i < PL_VEC_PARTITION_FP_COUNT; i++) {
        const struct pl_vec_partition_fp *v = PL_VEC_PARTITION_FP + i;
        const uint64_t h = fingerprint((size_t)v->n, (unsigned)v->workers);
        CHECK("fingerprints", i, h == v->fingerprint);
    }
}

static int refused(size_t m, unsigned w, uint32_t *p, uint8_t *k, uint32_t *x, size_t cap,
                   struct pl_chunk *c, size_t *count) {
    return pl_request_chunks(m, w, 0u, p, k, x, cap, c, count) == -1 && *count == 9u;
}

static void limits(void) {
    struct pl_chunk c[PL_MAX_WORKERS];
    size_t count = 9u;
    CHECK("limits", 0u, refused(10u, 0u, perm, mark, indices, CAP, c, &count));
    CHECK("limits", 1u, refused(10u, 5u, perm, mark, indices, CAP, c, &count));
    CHECK("limits", 2u, refused(0u, 0u, perm, mark, indices, CAP, c, &count));
    CHECK("limits", 3u, refused(11u, 2u, perm, mark, indices, 10u, c, &count));
    CHECK("limits", 4u, refused(PL_REQUEST_LIMIT + 1u, 2u, perm, mark, indices, CAP, c, &count));
    CHECK("limits", 5u, refused(10u, 2u, NULL, mark, indices, CAP, c, &count));
    CHECK("limits", 6u, refused(10u, 2u, perm, NULL, indices, CAP, c, &count));
    CHECK("limits", 7u, refused(10u, 2u, perm, mark, NULL, CAP, c, &count));
    CHECK("limits", 8u, refused(10u, 2u, perm, mark, indices, CAP, NULL, &count));
    CHECK("limits", 9u, pl_request_chunks(10u, 2u, 0u, perm, mark, indices, CAP, c, NULL) == -1);
    CHECK("limits", 10u, pl_request_chunks(0u, 4u, 0u, perm, mark, indices, CAP, c, &count) == 0);
    CHECK("limits", 11u, count == 0u);
    CHECK("limits", 12u, pl_request_chunks(3u, 4u, 0u, perm, mark, indices, CAP, c, &count) == 0);
    CHECK("limits", 13u, count == 3u);
    CHECK("perm-limits", 0u, pl_permutation(PL_REQUEST_LIMIT + 1u, 0u, perm, CAP) == -1);
    CHECK("perm-limits", 1u, pl_permutation(11u, 0u, perm, 10u) == -1);
    CHECK("perm-limits", 2u, pl_permutation(1u, 0u, NULL, CAP) == -1);
    CHECK("perm-limits", 3u, pl_permutation(0u, 0u, NULL, CAP) == 0);
    CHECK("perm-limits", 4u, pl_permutation(PL_REQUEST_LIMIT, 0u, perm, PL_REQUEST_LIMIT) == 0);
    CHECK("count", 0u, pl_request_count(0u) == 0u);
    CHECK("count", 1u, pl_request_count(1u) == 1u);
    CHECK("count", 2u, pl_request_count(PL_REQUEST_LIMIT) == 1u);
    CHECK("count", 3u, pl_request_count(PL_REQUEST_LIMIT + 1u) == 2u);
    CHECK("count", 4u, pl_request_count(20000u) == 2u);
    CHECK("count", 5u, pl_request_count(2u * PL_REQUEST_LIMIT + 1u) == 3u);
}

/* The request limit 14,336 of Amendment I item I5.5 (Task 12b): the request counts, the permutation
 * and chunk bounds at 14,336 and 14,337, and the second request of n = 20,000 (offset 14,336,
 * 5,664 rows) as the fingerprint helper splits it. */
static void request_limit(void) {
    struct pl_chunk c[PL_MAX_WORKERS];
    size_t count = 9u;
    CHECK("request-limit", 0u, PL_REQUEST_LIMIT == 14336u);
    CHECK("request-limit", 1u, pl_request_count(0u) == 0u);
    CHECK("request-limit", 2u, pl_request_count(1u) == 1u);
    CHECK("request-limit", 3u, pl_request_count(14336u) == 1u);
    CHECK("request-limit", 4u, pl_request_count(14337u) == 2u);
    CHECK("request-limit", 5u, pl_request_count(16384u) == 2u);
    CHECK("request-limit", 6u, pl_request_count(20000u) == 2u);
    CHECK("request-limit", 7u, pl_request_count(28673u) == 3u);
    CHECK("request-limit", 8u, pl_permutation(14337u, 0u, perm, CAP) == -1);
    CHECK("request-limit", 9u, pl_permutation(14336u, 0u, perm, CAP) == 0);
    CHECK("request-limit", 10u, refused(14337u, 2u, perm, mark, indices, CAP, c, &count));
    const int full = pl_request_chunks(14336u, 4u, 0u, perm, mark, indices, CAP, c, &count);
    CHECK("request-limit", 11u, full == 0);
    CHECK("request-limit", 12u, count == 4u);
    for (size_t k = 0; k < 4u; k++) {
        CHECK("request-limit-sizes", k, (c + k)->count == 3584u);
    }
    const size_t a = 1u * PL_REQUEST_LIMIT;
    const size_t m = 20000u - a < PL_REQUEST_LIMIT ? 20000u - a : PL_REQUEST_LIMIT;
    CHECK("request-limit", 13u, a == 14336u && m == 5664u);
    const int tail = pl_request_chunks(m, 4u, 1u, perm, mark, indices, CAP, c, &count);
    CHECK("request-limit", 14u, tail == 0);
    CHECK("request-limit", 15u, count == 4u);
    for (size_t k = 0; k < 4u; k++) {
        CHECK("request-limit-tail", k, (c + k)->count == 1416u);
    }
    printf("PASS request-limit\n");
}

/* With cap = m, no write reaches position m of perm, mark or indices. */
static void extent(void) {
    const size_t m = 1000u;
    *(perm + m) = UINT32_MAX;
    *(mark + m) = 0xA5u;
    *(indices + m) = UINT32_MAX;
    struct pl_chunk c[PL_MAX_WORKERS];
    size_t count = 0u;
    CHECK("extent", 0u, pl_request_chunks(m, 4u, 1u, perm, mark, indices, m, c, &count) == 0);
    CHECK("extent", 1u, *(perm + m) == UINT32_MAX && *(mark + m) == 0xA5u);
    CHECK("extent", 2u, *(indices + m) == UINT32_MAX && count == 4u);
    size_t total = 0u;
    for (size_t k = 0; k < 4u; k++) {
        CHECK("extent-offset", k, (c + k)->offset == total);
        total += (c + k)->count;
    }
    CHECK("extent", 3u, total == m);
}

int main(void) {
    known_answers();
    arithmetic();
    forced_rejection();
    chunk_lists();
    request_limit();
    fingerprints();
    limits();
    extent();
    printf("PASS partition\n");
    return 0;
}
