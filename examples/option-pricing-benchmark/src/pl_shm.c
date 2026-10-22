#define _GNU_SOURCE

#include "pl_io.h"
#include "pl_protocol.h"
#include "pl_serve.h"
#include <stddef.h>
#include <stdint.h>
#include <sys/stat.h>
#include <sys/types.h>

/* The shm route of pl-worker (specs/project/serve.md "Request: route shm"): two regular-file
 * regions (for example sealed memfds). The input range is copied into a private buffer before
 * the batch reads it, so a later change of the region cannot change the records. */

/* Stores the region size of fd in *size and returns 1. Returns 0 (and *size 0) for a descriptor
 * that is no regular file or cannot be inspected. */
static int pl_region_size(int fd, uint64_t *size) {
    struct stat st;
    *size = 0u;
    if (fstat(fd, &st) != 0 || !S_ISREG(st.st_mode) || st.st_size < 0) {
        return 0;
    }
    *size = (uint64_t)st.st_size;
    return 1;
}

enum pl_proto_error pl_shm_request(const struct pl_serve_options *o, const struct pl_header *h,
                                   const uint8_t *payload, uint8_t *input, uint8_t *output,
                                   size_t *written) {
    *written = 0u;
    uint64_t in_size = 0u;
    uint64_t out_size = 0u;
    const int in_ok = pl_region_size(o->shm_in_fd, &in_size);
    const int out_ok = pl_region_size(o->shm_out_fd, &out_size);
    if (!in_ok || !out_ok) {
        return PL_PROTO_IO_ERROR;
    }
    struct pl_shm_descriptor d = {0u, 0u, 0u, 0u};
    pl_shm_descriptor_decode(payload, &d);
    const enum pl_proto_error checked =
        pl_shm_descriptor_check(&d, h->record_count, h->threads, in_size, out_size);
    if (checked != PL_PROTO_OK) {
        return checked;
    }
    /* The check bounds in_length by PL_SHM_INPUT_BYTES, so the cast keeps the value. */
    const enum pl_io in_io = pl_pread_exact(o->shm_in_fd, input, (size_t)d.in_length, d.in_offset);
    if (in_io != PL_IO_OK) {
        return in_io == PL_IO_TRUNCATED ? PL_PROTO_TRUNCATED : PL_PROTO_IO_ERROR;
    }
    size_t produced = 0u;
    const enum pl_proto_error computed = pl_serve_compute(o, h, input, output, &produced);
    if (computed != PL_PROTO_OK) {
        return computed;
    }
    if (pl_pwrite_all(o->shm_out_fd, output, produced, d.out_offset) != PL_IO_OK) {
        return PL_PROTO_IO_ERROR;
    }
    *written = produced;
    return PL_PROTO_OK;
}
