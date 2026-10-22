#pragma once
#include "pl_types.h"
#include <stddef.h>
#include <stdint.h>

/* SCPL wire codec, protocol version 2 (specs/project/protocol.md; Amendment F item 5 as changed
 * by Amendment G items G4.4-G4.5 and Amendment I item I5). Every function reads and writes
 * caller-owned buffers only and keeps no pointer. All multi-byte values are little-endian and
 * are read and written byte by byte (no memcpy, no typed casts of wire storage). */

#define PL_HEADER_BYTES 28u
#define PL_REQUEST_RECORD_BYTES 64u
#define PL_RESPONSE_RECORD_BYTES 290u
#define PL_ERROR_PAYLOAD_BYTES 4u
#define PL_SHM_REQUEST_BYTES 32u
#define PL_SHM_RESPONSE_BYTES 8u
#define PL_PROTOCOL_VERSION 2u
#define PL_MAX_REQUEST_RECORDS 14336u
#define PL_MAX_FRAME_BYTES 4194304u
#define PL_MAX_THREADS 4u
#define PL_SHM_INPUT_BYTES 917504u
#define PL_SHM_OUTPUT_BYTES 4157508u

enum pl_frame_type {
    PL_FRAME_REQUEST = 1,
    PL_FRAME_RESPONSE = 2,
    PL_FRAME_ERROR = 3,
    PL_FRAME_SHUTDOWN = 4,
    PL_FRAME_SHM_REQUEST = 5,
    PL_FRAME_SHM_RESPONSE = 6
};

enum pl_proto_error {
    PL_PROTO_OK = 0,
    PL_PROTO_BAD_MAGIC = 1,
    PL_PROTO_BAD_VERSION = 2,
    PL_PROTO_BAD_TYPE = 3,
    PL_PROTO_RECORD_LIMIT = 4,
    PL_PROTO_FRAME_LIMIT = 5,
    PL_PROTO_LENGTH_MISMATCH = 6,
    PL_PROTO_TRUNCATED = 7,
    PL_PROTO_BAD_THREADS = 8,
    PL_PROTO_KERNEL_FAILURE = 9,
    PL_PROTO_IO_ERROR = 10,
    PL_PROTO_RESERVED_NONZERO = 11,
    PL_PROTO_BAD_MODELS = 12
};

/* Wire offsets: 0 magic "SCPL", 4 version, 6 type, 8 request ID, 16 record count, 20 threads,
 * 22 models, 24 payload length. */
struct pl_header {
    uint16_t version, type;
    uint64_t request_id;
    uint32_t record_count;
    uint16_t threads;
    uint16_t models;
    uint32_t payload_length;
};

/* SHM_REQUEST payload: u64 input offset, input length, output offset, output capacity. */
struct pl_shm_descriptor {
    uint64_t in_offset, in_length, out_offset, out_capacity;
};

/* Little-endian byte helpers; p points to at least 2, 4 or 8 readable (writable) bytes. */
uint16_t pl_load_u16(const uint8_t *p);
uint32_t pl_load_u32(const uint8_t *p);
uint64_t pl_load_u64(const uint8_t *p);
double pl_load_f64(const uint8_t *p);
void pl_store_u16(uint8_t *p, uint16_t v);
void pl_store_u32(uint8_t *p, uint32_t v);
void pl_store_u64(uint8_t *p, uint64_t v);
void pl_store_f64(uint8_t *p, double v);

/* Model part k (0-4) of a 290-byte response record: status byte k, flag byte 5 + k and the
 * seven fields at 10 + 56 * k + 8 * j, copied as they are (no check). */
void pl_store_part(uint8_t *rec, size_t k, const struct pl_model_result *m);
void pl_load_part(const uint8_t *rec, size_t k, struct pl_model_result *m);

/* count * 290 + 4 + 16 * k, k = 0 when threads = 0, else min(threads, count). */
size_t pl_response_payload(uint32_t count, uint16_t threads);

void pl_header_encode(const struct pl_header *h, uint8_t out[PL_HEADER_BYTES]);

/* Reads at most PL_HEADER_BYTES of buf (len readable bytes); checks magic, version, type,
 * record count, threads, models, frame size and payload length in this order. len < 28 gives
 * PL_PROTO_TRUNCATED and a zeroed *out; otherwise *out holds the decoded fields. */
enum pl_proto_error pl_header_decode(const uint8_t *buf, size_t len, struct pl_header *out);

/* rec: 64 bytes. Side 0.0 -> 0, 1.0 -> 1, any other value (NaN included) -> -1. */
void pl_request_decode(const uint8_t *rec, struct pl_row *row);
void pl_request_encode(const struct pl_row *row, uint8_t *rec);

/* Status PL_NOT_REQUESTED, flags 0, every field the bits 0x7FF8000000000000. */
void pl_result_not_requested(struct pl_model_result *m);

/* rec: 290 bytes: status bytes 0-4, flag bytes 5-9 (MODELS5 order), model k field j at
 * 10 + 56 * k + 8 * j. */
void pl_response_encode(const struct pl_contract_result *r, uint8_t *rec);

/* Decodes all five parts into *r, then applies the record rule of protocol.md: models outside
 * 1-31 -> PL_PROTO_BAD_MODELS; a selected part needs status 0-8 or 255 and allowed flag bits; an
 * unselected part needs exactly status 254, flags 0 and seven NaN bit patterns 0x7FF8000000000000;
 * any other content -> PL_PROTO_RESERVED_NONZERO. */
enum pl_proto_error pl_response_decode(const uint8_t *rec, uint16_t models,
                                       struct pl_contract_result *r);

/* p: 4 + 16 * k writable bytes; sizes and wall_ns: k entries each (may be NULL when k = 0). */
void pl_trailer_encode(uint8_t *p, size_t k, const size_t *sizes, const uint64_t *wall_ns);

void pl_error_encode(enum pl_proto_error code, uint8_t out[PL_ERROR_PAYLOAD_BYTES]);

/* p: 4 bytes. *code receives the u16 code; a nonzero reserved u16 -> PL_PROTO_RESERVED_NONZERO. */
enum pl_proto_error pl_error_decode(const uint8_t *p, uint16_t *code);

/* p: 32 bytes. */
void pl_shm_descriptor_decode(const uint8_t *p, struct pl_shm_descriptor *d);

/* Amendment F item 10: in_length == count * 64; out_capacity >= pl_response_payload(count,
 * threads); offset + length <= size for both regions (checked, no wrap); else
 * PL_PROTO_LENGTH_MISMATCH. Then in_size <= PL_SHM_INPUT_BYTES and out_size <=
 * PL_SHM_OUTPUT_BYTES, else PL_PROTO_FRAME_LIMIT. */
enum pl_proto_error pl_shm_descriptor_check(const struct pl_shm_descriptor *d, uint32_t count,
                                            uint16_t threads, uint64_t in_size, uint64_t out_size);
