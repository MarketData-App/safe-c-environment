/* Amendment E partition; must equal benchlab.pools. Original code of this project, written from
 * spec Amendment E item 1 (docs/superpowers/specs/2026-10-07-performance-lab-design.md) with
 * benchmarks/performance/python/benchlab/pools.py lines 24-30 as the reference text: the
 * SplitMix64 generator step. It is not a QuantLib transcription. */
#include "pl_partition.h"

/* specs/project/batch.md "Partition". A separate translation unit, so that these functions are
 * opaque calls inside the loops of pl_partition.c, and pl_add_64 and pl_mul_64 are opaque calls
 * here (the fixed GCC analyzer budget of the framework). */

/* (a b) mod 2^64. */
static uint64_t mul_mod(uint64_t a, uint64_t b) {
    uint64_t hi = 0u;
    uint64_t lo = 0u;
    pl_mul_64(a, b, &hi, &lo);
    return lo;
}

void pl_random_init(struct pl_random *g, uint64_t state) {
    if (g == NULL) {
        return;
    }
    g->state = state;
    g->script = NULL;
    g->script_len = 0u;
    g->script_pos = 0u;
    g->calls = 0u;
    g->script_overrun = 0;
}

/* SplitMix64.next (pools.py:27-30), or the test script. */
uint64_t pl_random_next(struct pl_random *g) {
    if (g == NULL) {
        return 0u;
    }
    g->calls++;
    if (g->script != NULL) {
        if (g->script_pos >= g->script_len) {
            g->script_overrun = 1;
            return 0u;
        }
        const uint64_t v = *(g->script + g->script_pos);
        g->script_pos++;
        return v;
    }
    g->state = pl_add_64(g->state, UINT64_C(0x9E3779B97F4A7C15));
    uint64_t z = g->state;
    z = mul_mod(z ^ (z >> 30), UINT64_C(0xBF58476D1CE4E5B9));
    z = mul_mod(z ^ (z >> 27), UINT64_C(0x94D049BB133111EB));
    return z ^ (z >> 31);
}
