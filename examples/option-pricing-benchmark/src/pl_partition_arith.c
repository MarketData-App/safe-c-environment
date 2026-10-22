/* Amendment E partition; must equal benchlab.pools. Original code of this project, written from
 * spec Amendment E item 1 (docs/superpowers/specs/2026-10-07-performance-lab-design.md): the exact
 * arithmetic modulo 2^64 of SplitMix64 and of the Lemire draw. It is not a QuantLib
 * transcription. */
#include "pl_partition.h"

/* specs/project/batch.md "Partition". A separate translation unit, so that these functions are
 * opaque calls in pl_splitmix.c and pl_partition.c (the fixed GCC analyzer budget of the
 * framework). No step wraps in C (the integer sanitizer profile rejects an unsigned wrap). */

#define LOW32 UINT64_C(0xffffffff)

/* When a + b >= 2^64 the result is a - (2^64 - b) = a - (UINT64_MAX - b) - 1, and
 * a > UINT64_MAX - b keeps every step in range. */
uint64_t pl_add_64(uint64_t a, uint64_t b) {
    if (a <= UINT64_MAX - b) {
        return a + b;
    }
    return a - (UINT64_MAX - b) - 1u;
}

/* a b = p11 2^64 + (p01 + p10) 2^32 + p00 with 32-bit halves; each partial product is below
 * 2^64. mid < 3 2^32 holds bits 32-63 and their carry. The sum for hi never exceeds the exact
 * high word floor(a b / 2^64) < 2^64, so no step wraps. */
void pl_mul_64(uint64_t a, uint64_t b, uint64_t *hi, uint64_t *lo) {
    if (hi == NULL || lo == NULL) {
        return;
    }
    const uint64_t a0 = a & LOW32;
    const uint64_t a1 = a >> 32;
    const uint64_t b0 = b & LOW32;
    const uint64_t b1 = b >> 32;
    const uint64_t p00 = a0 * b0;
    const uint64_t p01 = a0 * b1;
    const uint64_t p10 = a1 * b0;
    const uint64_t p11 = a1 * b1;
    const uint64_t mid = (p00 >> 32) + (p01 & LOW32) + (p10 & LOW32);
    *hi = p11 + (p01 >> 32) + (p10 >> 32) + (mid >> 32);
    *lo = ((mid & LOW32) << 32) | (p00 & LOW32);
}
