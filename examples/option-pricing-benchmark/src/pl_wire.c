#include "pl_ieee.h"
#include "pl_protocol.h"
#include "pl_types.h"
#include <stddef.h>
#include <stdint.h>

/* The u32, u64, binary64 and model-part wire helpers (specs/project/protocol.md "Wire
 * format"): built on the u16 helpers of pl_wire16.c, little-endian, byte by byte. A translation
 * unit of its own, so that pl_protocol.c sees opaque calls (the fixed analyzer budget of the
 * framework). */

uint32_t pl_load_u32(const uint8_t *p) {
    return (uint32_t)pl_load_u16(p) | (uint32_t)pl_load_u16(p + 2) << 16;
}

uint64_t pl_load_u64(const uint8_t *p) {
    return (uint64_t)pl_load_u32(p) | (uint64_t)pl_load_u32(p + 4) << 32;
}

double pl_load_f64(const uint8_t *p) { return pl_bits_double(pl_load_u64(p)); }

void pl_store_u32(uint8_t *p, uint32_t v) {
    pl_store_u16(p, (uint16_t)(v & 0xFFFFu));
    pl_store_u16(p + 2, (uint16_t)(v >> 16));
}

void pl_store_u64(uint8_t *p, uint64_t v) {
    pl_store_u32(p, (uint32_t)(v & UINT64_C(0xFFFFFFFF)));
    pl_store_u32(p + 4, (uint32_t)(v >> 32));
}

void pl_store_f64(uint8_t *p, double v) { pl_store_u64(p, pl_double_bits(v)); }

/* The offset of field j of model k in a response record. */
static size_t pl_part_field(size_t k, size_t j) { return 10u + 56u * k + 8u * j; }

void pl_store_part(uint8_t *rec, size_t k, const struct pl_model_result *m) {
    *(rec + k) = m->status;
    *(rec + PL_MODELS + k) = m->flags;
    for (size_t j = 0; j < PL_FIELDS; j++) {
        pl_store_f64(rec + pl_part_field(k, j), *(m->values + j));
    }
}

void pl_load_part(const uint8_t *rec, size_t k, struct pl_model_result *m) {
    m->status = *(rec + k);
    m->flags = *(rec + PL_MODELS + k);
    for (size_t j = 0; j < PL_FIELDS; j++) {
        *(m->values + j) = pl_load_f64(rec + pl_part_field(k, j));
    }
}
