#include "bd_digest.h"

/* Contract: specs/project/bd_digest.md. No allocation, no global mutable
 * state, no I/O. */

/* FNV-1a 64 of one byte. The product is the defined FNV-1a product modulo
 * 2^64: __builtin_mul_overflow stores the wrapped value, and its overflow flag
 * is not an error here. A plain multiplication would trap the integer gate's
 * unsigned-integer-overflow check. */
static uint64_t fold_byte(uint64_t hash, uint64_t byte) {
    uint64_t product = 0U;
    (void)__builtin_mul_overflow(hash ^ byte, BD_FNV_PRIME, &product);
    return product;
}

/* Folds the 8 bytes of value, least significant first. */
static uint64_t fold_word(uint64_t hash, uint64_t value) {
    uint64_t folded = hash;
    for (unsigned int shift = 0U; shift < 64U; shift += 8U) {
        folded = fold_byte(folded, (value >> shift) & UINT64_C(0xff));
    }
    return folded;
}

struct bd_result bd_digest_record(uint64_t seed, uint32_t steps) {
    uint64_t state = seed == 0U ? BD_ZERO_SEED : seed;
    uint64_t checksum = BD_FNV_OFFSET;
    for (uint32_t step = 0U; step < steps; ++step) {
        /* Unsigned shifts drop the high bits: the shift is modulo 2^64. */
        state ^= state << 13U;
        state ^= state >> 7U;
        state ^= state << 17U;
        checksum = fold_word(checksum, state);
    }
    const struct bd_result result = {.checksum = checksum, .state = state};
    return result;
}

static uint64_t read_le(const unsigned char *bytes, unsigned int count) {
    uint64_t value = 0U;
    for (unsigned int index = 0U; index < count; ++index) {
        const uint64_t byte = *(bytes + index);
        value |= byte << (8U * index);
    }
    return value;
}

static void write_le(unsigned char *bytes, uint64_t value, unsigned int count) {
    for (unsigned int index = 0U; index < count; ++index) {
        *(bytes + index) = (unsigned char)((value >> (8U * index)) & UINT64_C(0xff));
    }
}

enum bd_status bd_encode_record(unsigned char *record, uint64_t seed, uint32_t steps) {
    if (record == NULL) {
        return BD_NULL_ARGUMENT;
    }
    write_le(record, seed, 8U);
    write_le(record + 8U, steps, 4U);
    return BD_OK;
}

enum bd_status bd_decode_output(const unsigned char *output, struct bd_result *result) {
    if (result != NULL) {
        result->checksum = 0U;
        result->state = 0U;
    }
    if (output == NULL || result == NULL) {
        return BD_NULL_ARGUMENT;
    }
    result->checksum = read_le(output, 8U);
    result->state = read_le(output + 8U, 8U);
    return BD_OK;
}

enum bd_status bd_decode_record(const unsigned char *record, uint64_t *seed, uint32_t *steps) {
    if (seed != NULL) {
        *seed = 0U;
    }
    if (steps != NULL) {
        *steps = 0U;
    }
    if (record == NULL || seed == NULL || steps == NULL) {
        return BD_NULL_ARGUMENT;
    }
    *seed = read_le(record, 8U);
    *steps = (uint32_t)read_le(record + 8U, 4U);
    return BD_OK;
}

enum bd_status bd_check_request(const unsigned char *request, size_t length, size_t *records) {
    if (records != NULL) {
        *records = 0U;
    }
    if (request == NULL || records == NULL) {
        return BD_NULL_ARGUMENT;
    }
    if (length == 0U) {
        return BD_EMPTY_REQUEST;
    }
    /* Checked before any byte is read: length can exceed the request buffer. */
    if (length > (size_t)BD_REQUEST_MAX_BYTES) {
        return BD_TOO_MANY_RECORDS;
    }
    if (length % (size_t)BD_RECORD_IN_BYTES != 0U) {
        return BD_PARTIAL_RECORD;
    }
    const size_t count = length / (size_t)BD_RECORD_IN_BYTES;
    for (size_t index = 0U; index < count; ++index) {
        const uint64_t steps = read_le(request + index * (size_t)BD_RECORD_IN_BYTES + 8U, 4U);
        if (steps > (uint64_t)BD_STEPS_MAX) {
            return BD_STEPS_TOO_LARGE;
        }
    }
    *records = count;
    return BD_OK;
}

/* 1 when pointer equals base + i for some i < size, else 0. Only equality
 * comparisons are used: they are defined for pointers into different objects,
 * and no pointer becomes an integer. base + i stays inside the size bytes that
 * the caller declared for base. */
static int points_into(const unsigned char *pointer, const unsigned char *base, size_t size) {
    for (size_t index = 0U; index < size; ++index) {
        if (pointer == base + index) {
            return 1;
        }
    }
    return 0;
}

enum bd_status bd_digest_request(const unsigned char *request, size_t length, unsigned char *out,
                                 size_t capacity, size_t *written) {
    if (written != NULL) {
        *written = 0U;
    }
    if (request == NULL || out == NULL || written == NULL) {
        return BD_NULL_ARGUMENT;
    }
    size_t count = 0U;
    const enum bd_status status = bd_check_request(request, length, &count);
    if (status != BD_OK) {
        return status;
    }
    /* count <= BD_RECORDS_MAX, so the product cannot wrap. */
    const size_t needed = count * (size_t)BD_RECORD_OUT_BYTES;
    if (capacity < needed) {
        return BD_BUFFER_TOO_SMALL;
    }
    /* Record i + 1 is read after output record i is written, so an
     * overlapping pair would give wrong output. */
    if (points_into(out, request, length) || points_into(request, out, needed)) {
        return BD_OVERLAP;
    }
    for (size_t index = 0U; index < count; ++index) {
        const unsigned char *record = request + index * (size_t)BD_RECORD_IN_BYTES;
        const uint64_t seed = read_le(record, 8U);
        const uint32_t steps = (uint32_t)read_le(record + 8U, 4U);
        const struct bd_result result = bd_digest_record(seed, steps);
        unsigned char *target = out + index * (size_t)BD_RECORD_OUT_BYTES;
        write_le(target, result.checksum, 8U);
        write_le(target + 8U, result.state, 8U);
    }
    *written = needed;
    return BD_OK;
}

const char *bd_status_name(enum bd_status status) {
    switch (status) {
    case BD_OK:
        return "BD_OK";
    case BD_NULL_ARGUMENT:
        return "BD_NULL_ARGUMENT";
    case BD_EMPTY_REQUEST:
        return "BD_EMPTY_REQUEST";
    case BD_TOO_MANY_RECORDS:
        return "BD_TOO_MANY_RECORDS";
    case BD_PARTIAL_RECORD:
        return "BD_PARTIAL_RECORD";
    case BD_STEPS_TOO_LARGE:
        return "BD_STEPS_TOO_LARGE";
    case BD_BUFFER_TOO_SMALL:
        return "BD_BUFFER_TOO_SMALL";
    case BD_INVALID_NUMBER:
        return "BD_INVALID_NUMBER";
    case BD_OVERLAP:
        return "BD_OVERLAP";
    }
    return "BD_UNKNOWN";
}
