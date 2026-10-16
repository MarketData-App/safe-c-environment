#include "bd_digest.h"

#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>

/* Program logic of bd-digest (specs/project/bd_digest.md). This file is a
 * separate translation unit so that each analyzer run stays within its fixed
 * budget. */

/* The longest accepted decimal text: UINT64_MAX has 20 digits. */
enum { BD_DECIMAL_MAX_DIGITS = 20 };

/* Parses a NUL-terminated decimal text of 1 to 20 digits with a value of at
 * most limit. Reads at most 21 bytes. BD_INVALID_NUMBER for NULL, empty, a
 * non-digit byte, more than 20 digits, a value above UINT64_MAX or above
 * limit; *value is 0 then. */
static enum bd_status parse_decimal(const char *text, uint64_t limit, uint64_t *value) {
    *value = 0U;
    if (text == NULL || *text == '\0') {
        return BD_INVALID_NUMBER;
    }
    uint64_t total = 0U;
    for (unsigned int index = 0U; *(text + index) != '\0'; ++index) {
        const char digit = *(text + index);
        if (index >= (unsigned int)BD_DECIMAL_MAX_DIGITS || digit < '0' || digit > '9') {
            return BD_INVALID_NUMBER;
        }
        uint64_t scaled = 0U;
        uint64_t next = 0U;
        const uint64_t value_of_digit = (uint64_t)(digit - '0');
        const int mul_wrapped = __builtin_mul_overflow(total, UINT64_C(10), &scaled);
        const int add_wrapped = __builtin_add_overflow(scaled, value_of_digit, &next);
        if (mul_wrapped || add_wrapped || next > limit) {
            return BD_INVALID_NUMBER;
        }
        total = next;
    }
    *value = total;
    return BD_OK;
}

/* Writes the line, then flushes. Returns 0 on success and 1 when either step
 * fails. Both steps always run. */
static int write_result(FILE *stream, uint64_t checksum, uint64_t state) {
    const int text = fprintf(stream, "%016" PRIx64 " %016" PRIx64 "\n", checksum, state);
    const int flush = fflush(stream);
    return (text < 0) | (flush == EOF);
}

static int report(FILE *err, enum bd_status status) {
    (void)fprintf(err, "bd-digest: %s\n", bd_status_name(status));
    return 1;
}

int bd_main(int argc, char **argv, FILE *out, FILE *err) {
    if (argc != 3) {
        (void)fputs("usage: bd-digest SEED STEPS\n", err);
        return 2;
    }
    uint64_t seed = 0U;
    uint64_t steps = 0U;
    enum bd_status status = parse_decimal(*(argv + 1), UINT64_MAX, &seed);
    if (status != BD_OK) {
        return report(err, status);
    }
    status = parse_decimal(*(argv + 2), UINT64_C(0xffffffff), &steps);
    if (status != BD_OK) {
        return report(err, status);
    }
    unsigned char record[BD_RECORD_IN_BYTES] = {0};
    unsigned char output[BD_RECORD_OUT_BYTES] = {0};
    size_t written = 0U;
    struct bd_result result = {.checksum = 0U, .state = 0U};
    /* Both pointers are local arrays and objects, so neither call can fail. */
    (void)bd_encode_record(record, seed, (uint32_t)steps);
    status = bd_digest_request(record, sizeof record, output, sizeof output, &written);
    if (status != BD_OK) {
        return report(err, status);
    }
    (void)bd_decode_output(output, &result);
    return write_result(out, result.checksum, result.state);
}
