#include "pl_canonical.h"
#include "pl_ieee.h"
#include <stddef.h>
#include <stdint.h>

/* Text, decimal and hex-bits writers of the byte sink (specs/project/protocol.md "Sink"); each
 * byte goes through pl_sink_byte of pl_sink.c. The FNV-1a 64 step of the sink digest is here, so
 * that pl_sink_byte sees an opaque call (the fixed GCC analyzer budget). */

#define PL_FNV_LOW32 UINT64_C(0xffffffff)
#define PL_FNV_PRIME_HIGH UINT64_C(0x100)
#define PL_FNV_PRIME_LOW UINT64_C(0x1b3)

/* x 0x100000001b3 mod 2^64, from the 32-bit halves x1, x0 of x and the halves 0x100, 0x1b3 of the
 * prime: the low word is the low half of x0 0x1b3; the high word is
 * (x0 0x1b3 / 2^32 + x0 0x100 + x1 0x1b3) mod 2^32 (x1 0x100 2^64 vanishes). Each partial product
 * is below 2^41 and mid below 3 2^32, so no step wraps (the integer sanitizer profile rejects an
 * unsigned wrap). */
uint64_t pl_fnv1a_mul(uint64_t x) {
    const uint64_t x0 = x & PL_FNV_LOW32;
    const uint64_t x1 = x >> 32;
    const uint64_t p00 = x0 * PL_FNV_PRIME_LOW;
    const uint64_t mid = (p00 >> 32) + ((x0 * PL_FNV_PRIME_HIGH) & PL_FNV_LOW32) +
                         ((x1 * PL_FNV_PRIME_LOW) & PL_FNV_LOW32);
    return ((mid & PL_FNV_LOW32) << 32) | (p00 & PL_FNV_LOW32);
}

void pl_sink_text(struct pl_sink *s, const char *text) {
    for (const char *c = text; *c != '\0'; c++) {
        pl_sink_byte(s, (uint8_t)*c);
    }
}

void pl_sink_uint(struct pl_sink *s, uint64_t v) {
    uint8_t digits[20];
    size_t n = 0u;
    do {
        *(digits + n) = (uint8_t)('0' + (int)(v % 10u));
        n += 1u;
        v /= 10u;
    } while (v != 0u && n < sizeof digits);
    while (n > 0u) {
        n -= 1u;
        pl_sink_byte(s, *(digits + n));
    }
}

void pl_sink_hex_bits(struct pl_sink *s, double v) {
    static const char hex[] = "0123456789abcdef";
    const uint64_t bits = v == 0.0 ? UINT64_C(0) : pl_double_bits(v);
    for (unsigned shift = 64u; shift > 0u;) {
        shift -= 4u;
        pl_sink_byte(s, (uint8_t)*(hex + ((bits >> shift) & 0xFu)));
    }
}
