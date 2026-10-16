#include "bd_wire.h"

/* The SCPL v2 frame codec of the bench-demo peers (specs/project/bd_wire.md).
 * No allocation, no global mutable state, no I/O. */

uint64_t bd_load_le(const unsigned char *bytes, unsigned int count) {
    uint64_t value = 0U;
    for (unsigned int index = 0U; index < count && index < 8U; ++index) {
        const uint64_t byte = *(bytes + index);
        value |= byte << (8U * index);
    }
    return value;
}

void bd_store_le(unsigned char *bytes, uint64_t value, unsigned int count) {
    for (unsigned int index = 0U; index < count && index < 8U; ++index) {
        *(bytes + index) = (unsigned char)((value >> (8U * index)) & UINT64_C(0xff));
    }
}

void bd_header_encode(const struct bd_header *h, unsigned char *out) {
    *out = (unsigned char)'S';
    *(out + 1) = (unsigned char)'C';
    *(out + 2) = (unsigned char)'P';
    *(out + 3) = (unsigned char)'L';
    bd_store_le(out + 4, h->version, 2U);
    bd_store_le(out + 6, h->type, 2U);
    bd_store_le(out + 8, h->request_id, 8U);
    bd_store_le(out + 16, h->record_count, 4U);
    bd_store_le(out + 20, h->threads, 2U);
    bd_store_le(out + 22, h->selector_mask, 2U);
    bd_store_le(out + 24, h->payload_length, 4U);
}

static int is_selected(uint16_t type) {
    const int stdio_type = (type == BD_FRAME_REQUEST) | (type == BD_FRAME_RESPONSE);
    const int shm_type = (type == BD_FRAME_SHM_REQUEST) | (type == BD_FRAME_SHM_RESPONSE);
    return stdio_type | shm_type;
}

/* The payload length a header of type, count and threads must carry. Only
 * called after the record count is at most BD_RECORDS_MAX, so no product
 * wraps. ERROR and SHUTDOWN also need count 0 and threads 0. */
static int length_matches(const struct bd_header *h) {
    const uint64_t count = h->record_count;
    const uint64_t length = h->payload_length;
    switch (h->type) {
    case BD_FRAME_REQUEST:
        return length == count * (uint64_t)BD_RECORD_IN_BYTES;
    case BD_FRAME_RESPONSE:
        return length == count * (uint64_t)BD_RECORD_OUT_BYTES;
    case BD_FRAME_ERROR:
        return (length == (uint64_t)BD_ERROR_PAYLOAD_BYTES) & (count == 0U) & (h->threads == 0U);
    case BD_FRAME_SHUTDOWN:
        return (length == 0U) & (count == 0U) & (h->threads == 0U);
    case BD_FRAME_SHM_REQUEST:
        return length == (uint64_t)BD_SHM_REQUEST_BYTES;
    default:
        return length == (uint64_t)BD_SHM_RESPONSE_BYTES;
    }
}

enum bd_proto bd_header_decode(const unsigned char *buf, size_t len, struct bd_header *out) {
    const struct bd_header zero = {0U, 0U, 0U, 0U, 0U, 0U, 0U};
    *out = zero;
    if (len < (size_t)BD_HEADER_BYTES) {
        return BD_PROTO_TRUNCATED;
    }
    out->version = (uint16_t)bd_load_le(buf + 4, 2U);
    out->type = (uint16_t)bd_load_le(buf + 6, 2U);
    out->request_id = bd_load_le(buf + 8, 8U);
    out->record_count = (uint32_t)bd_load_le(buf + 16, 4U);
    out->threads = (uint16_t)bd_load_le(buf + 20, 2U);
    out->selector_mask = (uint16_t)bd_load_le(buf + 22, 2U);
    out->payload_length = (uint32_t)bd_load_le(buf + 24, 4U);
    const int first = (*buf == 'S') & (*(buf + 1) == 'C');
    const int magic = first & (*(buf + 2) == 'P') & (*(buf + 3) == 'L');
    if (magic == 0) {
        return BD_PROTO_BAD_MAGIC;
    }
    if (out->version != BD_PROTOCOL_VERSION) {
        return BD_PROTO_BAD_VERSION;
    }
    if (out->type < BD_FRAME_REQUEST || out->type > BD_FRAME_SHM_RESPONSE) {
        return BD_PROTO_BAD_TYPE;
    }
    if (out->record_count > (uint32_t)BD_RECORDS_MAX) {
        return BD_PROTO_RECORD_LIMIT;
    }
    const int selected = is_selected(out->type);
    /* The framework bound is 4 threads; the bench-demo codec has no pool, so
     * a selected frame needs threads 0. */
    if (out->threads > BD_MAX_THREADS || (selected != 0 && out->threads != 0U)) {
        return BD_PROTO_BAD_THREADS;
    }
    if (selected != 0 && out->selector_mask != BD_SELECTOR_DIGEST) {
        return BD_PROTO_BAD_SELECTOR;
    }
    if (selected == 0 && out->selector_mask != 0U) {
        return BD_PROTO_RESERVED_NONZERO;
    }
    if ((uint64_t)out->payload_length > (uint64_t)BD_MAX_FRAME_BYTES - (uint64_t)BD_HEADER_BYTES) {
        return BD_PROTO_FRAME_LIMIT;
    }
    if (length_matches(out) == 0) {
        return BD_PROTO_LENGTH_MISMATCH;
    }
    return BD_PROTO_OK;
}

void bd_error_encode(enum bd_proto code, unsigned char *out) {
    bd_store_le(out, (uint64_t)code, 4U);
}

void bd_shm_descriptor_decode(const unsigned char *bytes, struct bd_shm_descriptor *d) {
    d->in_offset = bd_load_le(bytes, 8U);
    d->in_length = bd_load_le(bytes + 8, 8U);
    d->out_offset = bd_load_le(bytes + 16, 8U);
    d->out_capacity = bd_load_le(bytes + 24, 8U);
}

enum bd_proto bd_shm_descriptor_check(const struct bd_shm_descriptor *d, uint32_t count,
                                      uint64_t in_size, uint64_t out_size) {
    if (in_size > (uint64_t)BD_SHM_INPUT_BYTES || out_size > (uint64_t)BD_SHM_OUTPUT_BYTES) {
        return BD_PROTO_FRAME_LIMIT;
    }
    uint64_t in_end = 0U;
    uint64_t out_end = 0U;
    const int in_wraps = __builtin_add_overflow(d->in_offset, d->in_length, &in_end);
    const int out_wraps = __builtin_add_overflow(d->out_offset, d->out_capacity, &out_end);
    /* count <= BD_RECORDS_MAX is checked by bd_header_decode; the products
     * are below 2^18 in any case. */
    const uint64_t in_need = (uint64_t)count * (uint64_t)BD_RECORD_IN_BYTES;
    const uint64_t out_need = (uint64_t)count * (uint64_t)BD_RECORD_OUT_BYTES;
    if (in_wraps != 0 || out_wraps != 0 || d->in_length != in_need || d->out_capacity < out_need ||
        in_end > in_size || out_end > out_size) {
        return BD_PROTO_LENGTH_MISMATCH;
    }
    return BD_PROTO_OK;
}

const char *bd_proto_name(enum bd_proto code) {
    switch (code) {
    case BD_PROTO_OK:
        return "OK";
    case BD_PROTO_BAD_MAGIC:
        return "BAD_MAGIC";
    case BD_PROTO_BAD_VERSION:
        return "BAD_VERSION";
    case BD_PROTO_BAD_TYPE:
        return "BAD_TYPE";
    case BD_PROTO_RECORD_LIMIT:
        return "RECORD_LIMIT";
    case BD_PROTO_FRAME_LIMIT:
        return "FRAME_LIMIT";
    case BD_PROTO_LENGTH_MISMATCH:
        return "LENGTH_MISMATCH";
    case BD_PROTO_TRUNCATED:
        return "PROTOCOL_TRUNCATED";
    case BD_PROTO_BAD_THREADS:
        return "BAD_THREADS";
    case BD_PROTO_KERNEL_FAILURE:
        return "KERNEL_FAILURE";
    case BD_PROTO_IO_ERROR:
        return "IO_ERROR";
    case BD_PROTO_RESERVED_NONZERO:
        return "RESERVED_NONZERO";
    case BD_PROTO_BAD_SELECTOR:
        return "BAD_SELECTOR";
    }
    return "UNKNOWN";
}

enum bd_proto bd_answer_request(const struct bd_header *h, const unsigned char *payload,
                                unsigned char *frame, size_t capacity, size_t *frame_length) {
    *frame_length = 0U;
    /* h passed bd_header_decode, so record_count <= BD_RECORDS_MAX and the
     * response fits in BD_HEADER_BYTES + BD_OUTPUT_MAX_BYTES. */
    const size_t out_bytes = (size_t)h->record_count * (size_t)BD_RECORD_OUT_BYTES;
    if (capacity < (size_t)BD_HEADER_BYTES + out_bytes) {
        return BD_PROTO_KERNEL_FAILURE;
    }
    size_t written = 0U;
    if (h->record_count != 0U) {
        const size_t in_bytes = (size_t)h->record_count * (size_t)BD_RECORD_IN_BYTES;
        unsigned char *records = frame + BD_HEADER_BYTES;
        const size_t room = capacity - (size_t)BD_HEADER_BYTES;
        if (bd_digest_request(payload, in_bytes, records, room, &written) != BD_OK) {
            return BD_PROTO_KERNEL_FAILURE;
        }
    }
    struct bd_header response = *h;
    response.type = BD_FRAME_RESPONSE;
    response.threads = 0U;
    response.payload_length = (uint32_t)written;
    bd_header_encode(&response, frame);
    *frame_length = (size_t)BD_HEADER_BYTES + written;
    return BD_PROTO_OK;
}
