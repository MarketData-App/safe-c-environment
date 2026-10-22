#pragma once
#include "pl_types.h"
#include <stddef.h>
#include <stdint.h>

/* Canonical result bytes "ocg-v1" (mask 7) and "ocg-v1m" (every other mask 1-31), the
 * optionlab.reference.canonical_result form (specs/project/protocol.md "Canonical form";
 * Amendment G item G5, Amendment I item I6). */

/* A byte sink. fd < 0 and buf NULL: a digest sink; no byte is kept and the sink never fails.
 * Any other fd < 0: a memory sink; the bytes stay in buf, and failed is set when more than cap
 * bytes arrive. fd >= 0: buf (cap bytes) buffers the bytes, which go to fd with pl_write_all
 * when buf is full and on pl_sink_flush; a failed write sets failed. total counts every byte
 * given to the sink, and fnv holds the FNV-1a 64 state of those bytes XOR the offset basis, so a
 * zeroed field is the state before the first byte (pl_sink_fnv reads the digest). buf is
 * borrowed: it stays valid and unaliased while the sink is used; the sink keeps no other
 * pointer. */
struct pl_sink {
    int fd;
    uint8_t *buf;
    size_t cap;
    size_t len;
    int failed;
    uint64_t total;
    uint64_t fnv;
};

/* One byte b into the sink (the rule above). */
void pl_sink_byte(struct pl_sink *s, uint8_t b);
/* The FNV-1a 64 digest (offset basis 0xcbf29ce484222325, prime 0x100000001b3) of every byte
 * given to the sink; the offset basis before the first byte. */
uint64_t pl_sink_fnv(const struct pl_sink *s);
/* The FNV-1a 64 product x 0x100000001b3 mod 2^64 for any x, with no unsigned wrap; one step of
 * the digest is pl_fnv1a_mul(h ^ b) (src/pl_sink_format.c: an opaque call in pl_sink.c, the fixed
 * GCC analyzer budget). */
uint64_t pl_fnv1a_mul(uint64_t x);
/* text: a NUL-terminated text. */
void pl_sink_text(struct pl_sink *s, const char *text);
/* The decimal digits of v. */
void pl_sink_uint(struct pl_sink *s, uint64_t v);
/* 16 lowercase hex digits of the big-endian bits of v; -0.0 is written as 0.0. */
void pl_sink_hex_bits(struct pl_sink *s, double v);
/* fd sink: writes the buffered bytes; memory sink: no effect. 0 ok, -1 when failed. */
int pl_sink_flush(struct pl_sink *s);

/* Writes the canonical bytes of rows[0..n) for the models of the mask and flushes the sink.
 * rows may be NULL when n is 0. Returns 0; -1 (nothing written) for a mask outside 1-31, a
 * selected status outside 0-8 or an infinity in a selected field; -2 when the sink failed. */
int pl_canonical_write(struct pl_sink *s, const struct pl_contract_result *rows, size_t n,
                       uint16_t models);
