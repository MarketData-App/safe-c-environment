#include "pl_protocol.h"
#include <stdint.h>

/* The u16 wire helpers (specs/project/protocol.md "Wire format"), a translation unit of their
 * own: every caller sees an opaque call, so the GCC analyzer keeps the symbols of the wider
 * loads small (the fixed analyzer budget of the framework). */

uint16_t pl_load_u16(const uint8_t *p) {
    return (uint16_t)((unsigned)*p | (unsigned)*(p + 1) << 8);
}

void pl_store_u16(uint8_t *p, uint16_t v) {
    *p = (uint8_t)(v & 0xFFu);
    *(p + 1) = (uint8_t)(v >> 8);
}
