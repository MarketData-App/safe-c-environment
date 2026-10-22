#include "pl_canonical.h"
#include "pl_protocol.h"
#include <stddef.h>
#include <stdint.h>

/* libFuzzer target `protocol` (specs/project/protocol.md "Fuzz target"): the input is a frame
 * stream. Each frame header is decoded; a frame whose payload is complete has its request
 * records, response records (with the frame's models), error payload or shm descriptor (checked
 * against region sizes taken from the next 16 input bytes) decoded. Nothing reads past the input
 * length. */

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size);

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    size_t at = 0u;
    while (size - at >= PL_HEADER_BYTES) {
        struct pl_header h;
        if (pl_header_decode(data + at, size - at, &h) != PL_PROTO_OK) {
            return 0;
        }
        at += PL_HEADER_BYTES;
        if ((size_t)h.payload_length > size - at) {
            return 0; /* truncated: never read past the input */
        }
        const uint8_t *p = data + at;
        if (h.type == PL_FRAME_REQUEST) {
            for (uint32_t i = 0; i < h.record_count; i++) {
                struct pl_row row;
                pl_request_decode(p + (size_t)i * PL_REQUEST_RECORD_BYTES, &row);
            }
        } else if (h.type == PL_FRAME_RESPONSE) {
            for (uint32_t i = 0; i < h.record_count; i++) {
                struct pl_contract_result r;
                (void)pl_response_decode(p + (size_t)i * PL_RESPONSE_RECORD_BYTES, h.models, &r);
            }
        } else if (h.type == PL_FRAME_ERROR) {
            uint16_t code;
            (void)pl_error_decode(p, &code);
        } else if (h.type == PL_FRAME_SHM_REQUEST && size - at - h.payload_length >= 16u) {
            struct pl_shm_descriptor d;
            pl_shm_descriptor_decode(p, &d);
            const uint8_t *sizes = p + h.payload_length;
            (void)pl_shm_descriptor_check(&d, h.record_count, h.threads, pl_load_u64(sizes),
                                          pl_load_u64(sizes + 8));
            at += 16u;
        }
        at += h.payload_length;
    }
    return 0;
}
