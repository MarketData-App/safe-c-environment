#include "pl_protocol.h"
#include "pl_ieee.h"
#include "pl_types.h"
#include <stddef.h>
#include <stdint.h>

/* SCPL protocol version 2 (specs/project/protocol.md). Every multi-byte value is read and
 * written byte by byte, little-endian; no function keeps a pointer. */

#define PL_NAN_BITS UINT64_C(0x7FF8000000000000)

size_t pl_response_payload(uint32_t count, uint16_t threads) {
    size_t k = 0u;
    if (threads != 0u) {
        k = threads < count ? (size_t)threads : (size_t)count;
    }
    return (size_t)count * PL_RESPONSE_RECORD_BYTES + 4u + 16u * k;
}

void pl_header_encode(const struct pl_header *h, uint8_t out[PL_HEADER_BYTES]) {
    *out = (uint8_t)'S';
    *(out + 1) = (uint8_t)'C';
    *(out + 2) = (uint8_t)'P';
    *(out + 3) = (uint8_t)'L';
    pl_store_u16(out + 4, h->version);
    pl_store_u16(out + 6, h->type);
    pl_store_u64(out + 8, h->request_id);
    pl_store_u32(out + 16, h->record_count);
    pl_store_u16(out + 20, h->threads);
    pl_store_u16(out + 22, h->models);
    pl_store_u32(out + 24, h->payload_length);
}

/* ERROR and SHUTDOWN carry no records, no threads and no models. */
static int pl_control_type(uint16_t type) {
    return type == PL_FRAME_ERROR || type == PL_FRAME_SHUTDOWN;
}

/* The payload length of a frame whose header passed steps 1-8 (protocol.md). */
static uint64_t pl_expected_payload(const struct pl_header *h) {
    switch (h->type) {
    case PL_FRAME_REQUEST:
        return (uint64_t)h->record_count * PL_REQUEST_RECORD_BYTES;
    case PL_FRAME_RESPONSE:
        return (uint64_t)pl_response_payload(h->record_count, h->threads);
    case PL_FRAME_ERROR:
        return PL_ERROR_PAYLOAD_BYTES;
    case PL_FRAME_SHM_REQUEST:
        return PL_SHM_REQUEST_BYTES;
    case PL_FRAME_SHM_RESPONSE:
        return PL_SHM_RESPONSE_BYTES;
    default:
        return 0u;
    }
}

enum pl_proto_error pl_header_decode(const uint8_t *buf, size_t len, struct pl_header *out) {
    out->version = 0u;
    out->type = 0u;
    out->request_id = 0u;
    out->record_count = 0u;
    out->threads = 0u;
    out->models = 0u;
    out->payload_length = 0u;
    if (len < PL_HEADER_BYTES) {
        return PL_PROTO_TRUNCATED;
    }
    out->version = pl_load_u16(buf + 4);
    out->type = pl_load_u16(buf + 6);
    out->request_id = pl_load_u64(buf + 8);
    out->record_count = pl_load_u32(buf + 16);
    out->threads = pl_load_u16(buf + 20);
    out->models = pl_load_u16(buf + 22);
    out->payload_length = pl_load_u32(buf + 24);
    if (*buf != 'S' || *(buf + 1) != 'C' || *(buf + 2) != 'P' || *(buf + 3) != 'L') {
        return PL_PROTO_BAD_MAGIC;
    }
    if (out->version != PL_PROTOCOL_VERSION) {
        return PL_PROTO_BAD_VERSION;
    }
    if (out->type < PL_FRAME_REQUEST || out->type > PL_FRAME_SHM_RESPONSE) {
        return PL_PROTO_BAD_TYPE;
    }
    /* G4.4: ERROR and SHUTDOWN carry record count 0, else RESERVED_NONZERO (this position). */
    const int control = pl_control_type(out->type);
    if (control && out->record_count != 0u) {
        return PL_PROTO_RESERVED_NONZERO;
    }
    if (out->record_count > PL_MAX_REQUEST_RECORDS) {
        return PL_PROTO_RECORD_LIMIT;
    }
    if (control && out->threads != 0u) {
        return PL_PROTO_RESERVED_NONZERO;
    }
    if (!control && out->threads > PL_MAX_THREADS) {
        return PL_PROTO_BAD_THREADS;
    }
    if (control && out->models != 0u) {
        return PL_PROTO_RESERVED_NONZERO;
    }
    if (!control && (out->models == 0u || out->models > PL_MASK_MODELS5)) {
        return PL_PROTO_BAD_MODELS;
    }
    if (out->payload_length > PL_MAX_FRAME_BYTES - PL_HEADER_BYTES) {
        return PL_PROTO_FRAME_LIMIT;
    }
    if (out->payload_length != pl_expected_payload(out)) {
        return PL_PROTO_LENGTH_MISMATCH;
    }
    return PL_PROTO_OK;
}

void pl_request_decode(const uint8_t *rec, struct pl_row *row) {
    const double side = pl_load_f64(rec);
    row->side = side == 0.0 ? 0 : (side == 1.0 ? 1 : -1);
    row->S = pl_load_f64(rec + 8);
    row->K = pl_load_f64(rec + 16);
    row->T = pl_load_f64(rec + 24);
    row->bid = pl_load_f64(rec + 32);
    row->ask = pl_load_f64(rec + 40);
    row->r = pl_load_f64(rec + 48);
    row->q = pl_load_f64(rec + 56);
}

void pl_request_encode(const struct pl_row *row, uint8_t *rec) {
    pl_store_f64(rec, (double)row->side);
    pl_store_f64(rec + 8, row->S);
    pl_store_f64(rec + 16, row->K);
    pl_store_f64(rec + 24, row->T);
    pl_store_f64(rec + 32, row->bid);
    pl_store_f64(rec + 40, row->ask);
    pl_store_f64(rec + 48, row->r);
    pl_store_f64(rec + 56, row->q);
}

void pl_result_not_requested(struct pl_model_result *m) {
    m->status = PL_NOT_REQUESTED;
    m->flags = 0u;
    for (size_t j = 0; j < PL_FIELDS; j++) {
        *(m->values + j) = pl_bits_double(PL_NAN_BITS);
    }
}

/* The offset of field j of model k in a response record. */
static size_t pl_field_offset(size_t k, size_t j) { return 10u + 56u * k + 8u * j; }

void pl_response_encode(const struct pl_contract_result *r, uint8_t *rec) {
    for (size_t k = 0; k < PL_MODELS; k++) {
        pl_store_part(rec, k, r->model + k);
    }
}

/* The flag bits allowed in the flag byte of model k (I5.3): 1, 2, 4, 8 in every byte; 16 and 32
 * in the baw and alo bytes; 64 in the baw byte only; 128 never. */
static unsigned pl_allowed_flags(size_t k) {
    if (k == PL_MODEL_BAW) {
        return 0x7Fu;
    }
    return k == PL_MODEL_ALO ? 0x3Fu : 0x0Fu;
}

/* 1 when the part of model k in rec is valid for its selection (protocol.md "Response record
 * rule"), else 0. */
static int pl_part_valid(const uint8_t *rec, size_t k, int selected) {
    const unsigned status = *(rec + k);
    const unsigned flags = *(rec + PL_MODELS + k);
    if (selected) {
        const int status_ok = status <= PL_OK || status == PL_ECHO;
        return status_ok && (flags & ~pl_allowed_flags(k)) == 0u;
    }
    if (status != PL_NOT_REQUESTED || flags != 0u) {
        return 0;
    }
    for (size_t j = 0; j < PL_FIELDS; j++) {
        if (pl_load_u64(rec + pl_field_offset(k, j)) != PL_NAN_BITS) {
            return 0;
        }
    }
    return 1;
}

enum pl_proto_error pl_response_decode(const uint8_t *rec, uint16_t models,
                                       struct pl_contract_result *r) {
    for (size_t k = 0; k < PL_MODELS; k++) {
        pl_load_part(rec, k, r->model + k);
    }
    if (models == 0u || models > PL_MASK_MODELS5) {
        return PL_PROTO_BAD_MODELS;
    }
    int valid = 1;
    for (size_t k = 0; k < PL_MODELS; k++) {
        valid = valid && pl_part_valid(rec, k, ((unsigned)models >> k & 1u) != 0u);
    }
    return valid ? PL_PROTO_OK : PL_PROTO_RESERVED_NONZERO;
}

void pl_trailer_encode(uint8_t *p, size_t k, const size_t *sizes, const uint64_t *wall_ns) {
    pl_store_u32(p, (uint32_t)k);
    for (size_t i = 0; i < k; i++) {
        uint8_t *chunk = p + 4u + 16u * i;
        pl_store_u32(chunk, (uint32_t)*(sizes + i));
        pl_store_u32(chunk + 4, 0u);
        pl_store_u64(chunk + 8, *(wall_ns + i));
    }
}

void pl_error_encode(enum pl_proto_error code, uint8_t out[PL_ERROR_PAYLOAD_BYTES]) {
    pl_store_u16(out, (uint16_t)code);
    pl_store_u16(out + 2, 0u);
}

enum pl_proto_error pl_error_decode(const uint8_t *p, uint16_t *code) {
    *code = pl_load_u16(p);
    return pl_load_u16(p + 2) != 0u ? PL_PROTO_RESERVED_NONZERO : PL_PROTO_OK;
}

void pl_shm_descriptor_decode(const uint8_t *p, struct pl_shm_descriptor *d) {
    d->in_offset = pl_load_u64(p);
    d->in_length = pl_load_u64(p + 8);
    d->out_offset = pl_load_u64(p + 16);
    d->out_capacity = pl_load_u64(p + 24);
}

/* 1 when offset + length <= size without a wrap. */
static int pl_range_fits(uint64_t offset, uint64_t length, uint64_t size) {
    return offset <= size && length <= size - offset;
}

enum pl_proto_error pl_shm_descriptor_check(const struct pl_shm_descriptor *d, uint32_t count,
                                            uint16_t threads, uint64_t in_size, uint64_t out_size) {
    if (d->in_length != (uint64_t)count * PL_REQUEST_RECORD_BYTES) {
        return PL_PROTO_LENGTH_MISMATCH;
    }
    if (d->out_capacity < (uint64_t)pl_response_payload(count, threads)) {
        return PL_PROTO_LENGTH_MISMATCH;
    }
    if (!pl_range_fits(d->in_offset, d->in_length, in_size)) {
        return PL_PROTO_LENGTH_MISMATCH;
    }
    if (!pl_range_fits(d->out_offset, d->out_capacity, out_size)) {
        return PL_PROTO_LENGTH_MISMATCH;
    }
    if (in_size > PL_SHM_INPUT_BYTES || out_size > PL_SHM_OUTPUT_BYTES) {
        return PL_PROTO_FRAME_LIMIT;
    }
    return PL_PROTO_OK;
}
