#include "pl_canonical.h"
#include "pl_io.h"
#include <stddef.h>
#include <stdint.h>

/* The byte sink (specs/project/protocol.md "Sink"): one byte in, the flush and the FNV-1a 64
 * digest of the bytes. A translation unit of its own, so that the loops of pl_sink_format.c see
 * opaque calls, and the FNV step of pl_sink_format.c is an opaque call here (the fixed analyzer
 * budget of the framework). */

#define PL_FNV_OFFSET UINT64_C(0xcbf29ce484222325)

/* One byte into the sink (protocol.md "Sink"). */
void pl_sink_byte(struct pl_sink *s, uint8_t b) {
    s->total += 1u;
    s->fnv = pl_fnv1a_mul(s->fnv ^ PL_FNV_OFFSET ^ (uint64_t)b) ^ PL_FNV_OFFSET;
    if (s->failed || (s->fd < 0 && s->buf == NULL)) {
        return;
    }
    if (s->len == s->cap && s->fd >= 0) {
        (void)pl_sink_flush(s);
    }
    if (s->failed || s->len == s->cap) {
        s->failed = 1;
        return;
    }
    *(s->buf + s->len) = b;
    s->len += 1u;
}

uint64_t pl_sink_fnv(const struct pl_sink *s) { return s->fnv ^ PL_FNV_OFFSET; }

int pl_sink_flush(struct pl_sink *s) {
    if (s->failed) {
        return -1;
    }
    if (s->fd < 0) {
        return 0;
    }
    if (pl_write_all(s->fd, s->buf, s->len) != PL_IO_OK) {
        s->failed = 1;
        return -1;
    }
    s->len = 0u;
    return 0;
}
