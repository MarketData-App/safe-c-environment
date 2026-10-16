#define _GNU_SOURCE

#include "bd_wire.h"

#include <stdint.h>
#include <sys/stat.h>
#include <sys/types.h>

/* The bd-worker serve loop (specs/project/bd_wire.md): SCPL v2 frames over a
 * descriptor pair, route stdio (REQUEST) or shm (SHM_REQUEST with two
 * regular-file regions, for example sealed memfds). No allocation, no global
 * mutable state; the buffers live on the stack of bd_serve. */

enum { BD_ERROR_FRAME_BYTES = BD_HEADER_BYTES + BD_ERROR_PAYLOAD_BYTES };

/* Writes one ERROR frame with selector mask 0 and returns rc, or 4 when the
 * write fails. */
static int reply_error(int out_fd, uint64_t request_id, enum bd_proto code, int rc) {
    unsigned char frame[BD_ERROR_FRAME_BYTES] = {0};
    const struct bd_header h = {BD_PROTOCOL_VERSION, BD_FRAME_ERROR, request_id, 0U, 0U, 0U, 4U};
    bd_header_encode(&h, frame);
    bd_error_encode(code, frame + BD_HEADER_BYTES);
    return bd_write_all(out_fd, frame, sizeof frame) == BD_IO_OK ? rc : 4;
}

/* The serve result of a failed step: 4 for IO_ERROR, 3 for KERNEL_FAILURE,
 * else 1. */
static int result_of(enum bd_proto code) {
    if (code == BD_PROTO_IO_ERROR) {
        return 4;
    }
    return code == BD_PROTO_KERNEL_FAILURE ? 3 : 1;
}

/* 1 when the route accepts a frame of this type besides SHUTDOWN. */
static int route_accepts(const struct bd_serve_options *o, uint16_t type) {
    if (o->route == BD_ROUTE_STDIO) {
        return type == BD_FRAME_REQUEST;
    }
    return type == BD_FRAME_SHM_REQUEST;
}

/* Stores the region size of fd in *size and returns 1. Returns 0 (and
 * *size 0) for a descriptor that is no regular file or cannot be inspected. */
static int region_size(int fd, uint64_t *size) {
    struct stat st;
    *size = 0U;
    if (fstat(fd, &st) != 0 || S_ISREG(st.st_mode) == 0 || st.st_size < 0) {
        return 0;
    }
    *size = (uint64_t)st.st_size;
    return 1;
}

enum bd_proto bd_shm_request(const struct bd_serve_options *o, const struct bd_header *h,
                             const unsigned char *payload, unsigned char *input,
                             unsigned char *output, size_t *written) {
    *written = 0U;
    uint64_t in_size = 0U;
    uint64_t out_size = 0U;
    const int in_ok = region_size(o->shm_in_fd, &in_size);
    const int out_ok = region_size(o->shm_out_fd, &out_size);
    if (in_ok == 0 || out_ok == 0) {
        return BD_PROTO_IO_ERROR;
    }
    struct bd_shm_descriptor d = {0U, 0U, 0U, 0U};
    bd_shm_descriptor_decode(payload, &d);
    const enum bd_proto checked = bd_shm_descriptor_check(&d, h->record_count, in_size, out_size);
    if (checked != BD_PROTO_OK || h->record_count == 0U) {
        return checked;
    }
    /* The check bounds in_length by BD_SHM_INPUT_BYTES, so the casts keep
     * the value. The copy is a private snapshot: a later change of the region
     * cannot change the records the digest reads. */
    const size_t length = (size_t)d.in_length;
    const enum bd_io in_io = bd_pread_exact(o->shm_in_fd, input, length, d.in_offset);
    if (in_io != BD_IO_OK) {
        return in_io == BD_IO_TRUNCATED ? BD_PROTO_TRUNCATED : BD_PROTO_IO_ERROR;
    }
    size_t produced = 0U;
    const size_t room = (size_t)BD_SHM_OUTPUT_BYTES;
    if (bd_digest_request(input, length, output, room, &produced) != BD_OK) {
        return BD_PROTO_KERNEL_FAILURE;
    }
    if (bd_pwrite_all(o->shm_out_fd, output, produced, d.out_offset) != BD_IO_OK) {
        return BD_PROTO_IO_ERROR;
    }
    *written = produced;
    return BD_PROTO_OK;
}

/* Answers one SHM_REQUEST: SHM_RESPONSE with the 8-byte written count, or an
 * ERROR frame. Returns -1 to keep serving, else the serve result. */
static int serve_shm(int out_fd, const struct bd_serve_options *o, const struct bd_header *h,
                     const unsigned char *payload, unsigned char *input, unsigned char *output) {
    size_t written = 0U;
    const enum bd_proto st = bd_shm_request(o, h, payload, input, output, &written);
    if (st != BD_PROTO_OK) {
        return reply_error(out_fd, h->request_id, st, result_of(st));
    }
    unsigned char frame[BD_HEADER_BYTES + BD_SHM_RESPONSE_BYTES] = {0};
    struct bd_header response = *h;
    response.type = BD_FRAME_SHM_RESPONSE;
    response.threads = 0U;
    response.payload_length = BD_SHM_RESPONSE_BYTES;
    bd_header_encode(&response, frame);
    bd_store_le(frame + BD_HEADER_BYTES, (uint64_t)written, 8U);
    return bd_write_all(out_fd, frame, sizeof frame) == BD_IO_OK ? -1 : 4;
}

/* Answers one REQUEST with a RESPONSE frame, or ERROR KERNEL_FAILURE.
 * Returns -1 to keep serving, else the serve result. */
static int serve_stdio(int out_fd, const struct bd_header *h, const unsigned char *payload,
                       unsigned char *frame, size_t capacity) {
    size_t length = 0U;
    const enum bd_proto st = bd_answer_request(h, payload, frame, capacity, &length);
    if (st != BD_PROTO_OK) {
        return reply_error(out_fd, h->request_id, st, 3);
    }
    return bd_write_all(out_fd, frame, length) == BD_IO_OK ? -1 : 4;
}

int bd_serve(int in_fd, int out_fd, const struct bd_serve_options *o, uint64_t *requests) {
    if (requests != NULL) {
        *requests = 0U;
    }
    if (o == NULL || requests == NULL || (o->route != BD_ROUTE_STDIO && o->route != BD_ROUTE_SHM)) {
        return 2;
    }
    unsigned char payload[BD_REQUEST_MAX_BYTES] = {0};
    unsigned char input[BD_SHM_INPUT_BYTES] = {0};
    unsigned char frame[BD_HEADER_BYTES + BD_OUTPUT_MAX_BYTES] = {0};
    for (;;) {
        unsigned char raw[BD_HEADER_BYTES] = {0};
        const enum bd_io head_io = bd_read_exact(in_fd, raw, sizeof raw);
        if (head_io == BD_IO_EOF) {
            return 0;
        }
        if (head_io != BD_IO_OK) {
            return head_io == BD_IO_TRUNCATED ? reply_error(out_fd, 0U, BD_PROTO_TRUNCATED, 1) : 4;
        }
        struct bd_header h = {0U, 0U, 0U, 0U, 0U, 0U, 0U};
        enum bd_proto st = bd_header_decode(raw, sizeof raw, &h);
        if (st == BD_PROTO_OK && h.type == BD_FRAME_SHUTDOWN) {
            return 0;
        }
        if (st == BD_PROTO_OK && route_accepts(o, h.type) == 0) {
            st = BD_PROTO_BAD_TYPE;
        }
        if (st != BD_PROTO_OK) {
            return reply_error(out_fd, h.request_id, st, 1);
        }
        /* An accepted REQUEST carries at most BD_REQUEST_MAX_BYTES and a
         * SHM_REQUEST exactly BD_SHM_REQUEST_BYTES (bd_header_decode). */
        const enum bd_io body_io = bd_read_exact(in_fd, payload, h.payload_length);
        if (body_io == BD_IO_ERROR) {
            return 4;
        }
        if (body_io != BD_IO_OK) {
            return reply_error(out_fd, h.request_id, BD_PROTO_TRUNCATED, 1);
        }
        int rc = -1;
        if (h.type == BD_FRAME_REQUEST) {
            rc = serve_stdio(out_fd, &h, payload, frame, sizeof frame);
        } else {
            rc = serve_shm(out_fd, o, &h, payload, input, frame);
        }
        if (rc >= 0) {
            return rc;
        }
        *requests += 1U;
    }
}
