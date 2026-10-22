/* Amendment E partition; must equal benchlab.pools. Original code of this project, written from
 * spec Amendment E item 1 (docs/superpowers/specs/2026-10-07-performance-lab-design.md) with
 * benchmarks/performance/python/benchlab/pools.py lines 19-61 as the reference text. It is not a
 * QuantLib transcription. */
#include "pl_partition.h"

/* specs/project/batch.md "Partition". Every function checks its arguments before its first
 * write. The arithmetic modulo 2^64 never wraps in C (the integer sanitizer profile rejects an
 * unsigned wrap): pl_add_64 for sums, the low word of pl_mul_64 for products. Those two
 * (pl_partition_arith.c) and the generator step (pl_splitmix.c) are separate translation units,
 * so that every call inside the loops of this file is opaque to the GCC analyzer (its fixed
 * budget). */

#define BOUND_MAX (UINT64_C(1) << 32)

/* (a b) mod 2^64. */
static uint64_t mul_mod(uint64_t a, uint64_t b) {
    uint64_t hi = 0u;
    uint64_t lo = 0u;
    pl_mul_64(a, b, &hi, &lo);
    return lo;
}

/* SplitMix64.bounded (pools.py:31-38) for t in [1, 2^32]: Lemire's multiply-high draw with
 * rejection. The result hi = floor(x t / 2^64) is below t, because x < 2^64. The loop also stops
 * when a test script runs out (pl_random_bounded then refuses the draw). */
static uint64_t lemire(struct pl_random *g, uint64_t t) {
    uint64_t hi = 0u;
    uint64_t lo = 0u;
    pl_mul_64(pl_random_next(g), t, &hi, &lo);
    if (lo < t) {
        const uint64_t threshold = (UINT64_MAX - t + 1u) % t;
        while (lo < threshold && g->script_overrun == 0) {
            pl_mul_64(pl_random_next(g), t, &hi, &lo);
        }
    }
    return hi;
}

int pl_random_bounded(struct pl_random *g, uint64_t t, uint64_t *out) {
    if (g == NULL || out == NULL || t < 1u || t > BOUND_MAX) {
        return -1;
    }
    const uint64_t v = lemire(g, t);
    if (g->script_overrun != 0) {
        return -1;
    }
    *out = v;
    return 0;
}

/* permutation (pools.py:40-45): Fisher-Yates in Durstenfeld order, i = m - 1 down to 1,
 * j = bounded(i + 1) < i + 1 <= m. */
int pl_permutation(size_t m, uint64_t r, uint32_t *perm, size_t cap) {
    if (m > cap || m > PL_REQUEST_LIMIT || (perm == NULL && m > 0u)) {
        return -1;
    }
    for (size_t i = 0u; i < m; i++) {
        *(perm + i) = (uint32_t)i;
    }
    struct pl_random g;
    pl_random_init(&g, pl_add_64(PL_PARTITION_SEED, r));
    for (size_t i = m; i > 1u; i--) {
        const size_t top = i - 1u;
        const size_t j = (size_t)lemire(&g, (uint64_t)i);
        const uint32_t swap = *(perm + top);
        *(perm + top) = *(perm + j);
        *(perm + j) = swap;
    }
    return 0;
}

/* chunk_bounds (pools.py:47-52). Chunk k covers the permutation positions [k m / w, (k + 1) m / w)
 * (k <= 4 and m <= PL_REQUEST_LIMIT = 14,336, so k m <= 57,344 cannot overflow). mark[P[p]] = k for
 * each position p of chunk k; as P is a permutation of 0 .. m-1, every mark[i] with i < m is then
 * a chunk below w. One ascending scan appends i to chunk mark[i]: fill[k] stays in
 * [offset_k, offset_k + count_k], so each chunk is sorted and every write is below m <= cap. */
int pl_request_chunks(size_t m, unsigned workers, uint64_t r, uint32_t *perm, uint8_t *mark,
                      uint32_t *indices, size_t cap, struct pl_chunk *chunks, size_t *chunk_count) {
    if (workers < 1u || workers > PL_MAX_WORKERS) {
        return -1;
    }
    if (perm == NULL || mark == NULL || indices == NULL || chunks == NULL || chunk_count == NULL) {
        return -1;
    }
    if (m == 0u) {
        *chunk_count = 0u;
        return 0;
    }
    if (pl_permutation(m, r, perm, cap) != 0) {
        return -1;
    }
    const size_t w = (m < (size_t)workers) ? m : (size_t)workers;
    size_t fill[PL_MAX_WORKERS] = {0u, 0u, 0u, 0u};
    for (size_t k = 0u; k < w; k++) {
        const size_t begin = k * m / w;
        const size_t end = (k + 1u) * m / w;
        (chunks + k)->offset = begin;
        (chunks + k)->count = end - begin;
        *(fill + k) = begin;
        for (size_t p = begin; p < end; p++) {
            *(mark + *(perm + p)) = (uint8_t)k;
        }
    }
    for (size_t i = 0u; i < m; i++) {
        size_t *slot = fill + *(mark + i);
        *(indices + *slot) = (uint32_t)i;
        *slot += 1u;
    }
    *chunk_count = w;
    return 0;
}

size_t pl_request_count(size_t n) {
    return n / PL_REQUEST_LIMIT + ((n % PL_REQUEST_LIMIT != 0u) ? (size_t)1 : (size_t)0);
}

uint64_t pl_fnv1a64_u32(uint64_t h, uint32_t v) {
    for (unsigned s = 0u; s < 32u; s += 8u) {
        h = mul_mod(h ^ ((v >> s) & 0xffu), UINT64_C(0x100000001b3));
    }
    return h;
}
