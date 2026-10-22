#define _GNU_SOURCE

#include "pl_serve.h"
#include "pl_io.h"
#include "pl_protocol.h"
#include <stddef.h>
#include <stdint.h>

/* The serve loop of pl-worker (specs/project/serve.md): SCPL v2 frames over a descriptor pair.
 * No allocation and no global mutable state beyond the static buffers below (one call at a
 * time, one thread). The batch of one request is in src/pl_serve_run.c (a translation unit of its
 * own, so that the call is opaque to the GCC analyzer) and the shm route in src/pl_shm.c. */

static uint8_t pl_payload[PL_MAX_REQUEST_RECORDS * PL_REQUEST_RECORD_BYTES];
static uint8_t pl_frame[PL_HEADER_BYTES + PL_SHM_OUTPUT_BYTES];
static uint8_t pl_snapshot[PL_SHM_INPUT_BYTES];

/* Writes one ERROR frame (models 0) and returns rc, or 4 when the write fails. */
static int pl_reply_error(int out_fd, uint64_t id, enum pl_proto_error code, int rc) {
    uint8_t frame[PL_HEADER_BYTES + PL_ERROR_PAYLOAD_BYTES];
    const uint32_t length = PL_ERROR_PAYLOAD_BYTES;
    const struct pl_header h = {PL_PROTOCOL_VERSION, PL_FRAME_ERROR, id, 0u, 0u, 0u, length};
    pl_header_encode(&h, frame);
    pl_error_encode(code, frame + PL_HEADER_BYTES);
    return pl_write_all(out_fd, frame, sizeof frame) == PL_IO_OK ? rc : 4;
}

/* The serve result of a failed step: 4 for IO_ERROR, 3 for KERNEL_FAILURE, else 1. */
static int pl_result_of(enum pl_proto_error code) {
    if (code == PL_PROTO_IO_ERROR) {
        return 4;
    }
    return code == PL_PROTO_KERNEL_FAILURE ? 3 : 1;
}

/* 1 when the route accepts a frame of this type besides SHUTDOWN. */
static int pl_route_accepts(const struct pl_serve_options *o, uint16_t type) {
    if (o->route == PL_ROUTE_STDIO) {
        return type == PL_FRAME_REQUEST;
    }
    return type == PL_FRAME_SHM_REQUEST;
}

/* Answers one REQUEST with a RESPONSE frame, or ERROR KERNEL_FAILURE. Returns -1 to keep
 * serving, else the serve result. */
static int pl_serve_stdio(int out_fd, const struct pl_serve_options *o, const struct pl_header *h) {
    size_t produced = 0u;
    const enum pl_proto_error st =
        pl_serve_compute(o, h, pl_payload, pl_frame + PL_HEADER_BYTES, &produced);
    if (st != PL_PROTO_OK) {
        return pl_reply_error(out_fd, h->request_id, st, pl_result_of(st));
    }
    struct pl_header response = *h;
    response.type = PL_FRAME_RESPONSE;
    response.payload_length = (uint32_t)produced;
    pl_header_encode(&response, pl_frame);
    return pl_write_all(out_fd, pl_frame, PL_HEADER_BYTES + produced) == PL_IO_OK ? -1 : 4;
}

/* Answers one SHM_REQUEST with a SHM_RESPONSE frame (the 8-byte written count), or an ERROR
 * frame. Returns -1 to keep serving, else the serve result. */
static int pl_serve_shm(int out_fd, const struct pl_serve_options *o, const struct pl_header *h) {
    size_t written = 0u;
    const enum pl_proto_error st =
        pl_shm_request(o, h, pl_payload, pl_snapshot, pl_frame + PL_HEADER_BYTES, &written);
    if (st != PL_PROTO_OK) {
        return pl_reply_error(out_fd, h->request_id, st, pl_result_of(st));
    }
    uint8_t frame[PL_HEADER_BYTES + PL_SHM_RESPONSE_BYTES];
    struct pl_header response = *h;
    response.type = PL_FRAME_SHM_RESPONSE;
    response.payload_length = PL_SHM_RESPONSE_BYTES;
    pl_header_encode(&response, frame);
    pl_store_u64(frame + PL_HEADER_BYTES, (uint64_t)written);
    return pl_write_all(out_fd, frame, sizeof frame) == PL_IO_OK ? -1 : 4;
}

/* Reads and checks one header (header before payload). Returns -1 when a request header was
 * accepted into *h, else the serve result (0 for EOF or SHUTDOWN). */
static int pl_next_header(int in_fd, int out_fd, const struct pl_serve_options *o,
                          struct pl_header *h) {
    uint8_t raw[PL_HEADER_BYTES] = {0};
    const enum pl_io io = pl_read_exact(in_fd, raw, sizeof raw);
    if (io == PL_IO_EOF) {
        return 0;
    }
    if (io != PL_IO_OK) {
        return io == PL_IO_TRUNCATED ? pl_reply_error(out_fd, 0u, PL_PROTO_TRUNCATED, 1) : 4;
    }
    enum pl_proto_error st = pl_header_decode(raw, sizeof raw, h);
    if (st == PL_PROTO_OK && h->type == PL_FRAME_SHUTDOWN) {
        return 0;
    }
    if (st == PL_PROTO_OK && !pl_route_accepts(o, h->type)) {
        st = PL_PROTO_BAD_TYPE;
    }
    return st == PL_PROTO_OK ? -1 : pl_reply_error(out_fd, h->request_id, st, 1);
}

int pl_serve(int in_fd, int out_fd, const struct pl_serve_options *o, uint64_t *requests) {
    if (requests != NULL) {
        *requests = 0u;
    }
    if (o == NULL || requests == NULL || (o->route != PL_ROUTE_STDIO && o->route != PL_ROUTE_SHM)) {
        return 2;
    }
    for (;;) {
        struct pl_header h = {0u, 0u, 0u, 0u, 0u, 0u, 0u};
        const int next = pl_next_header(in_fd, out_fd, o, &h);
        if (next >= 0) {
            return next;
        }
        /* An accepted REQUEST carries at most 14,336 * 64 bytes and a SHM_REQUEST exactly 32
         * (pl_header_decode). */
        const enum pl_io body = pl_read_exact(in_fd, pl_payload, h.payload_length);
        if (body == PL_IO_ERROR) {
            return 4;
        }
        if (body != PL_IO_OK) {
            return pl_reply_error(out_fd, h.request_id, PL_PROTO_TRUNCATED, 1);
        }
        const int rc = h.type == PL_FRAME_REQUEST ? pl_serve_stdio(out_fd, o, &h)
                                                  : pl_serve_shm(out_fd, o, &h);
        if (rc >= 0) {
            return rc;
        }
        *requests += 1u;
    }
}
