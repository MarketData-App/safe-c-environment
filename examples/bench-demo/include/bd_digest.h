#ifndef BD_DIGEST_H
#define BD_DIGEST_H
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
/* The bench-demo workload: xorshift64 steps folded into an FNV-1a 64 checksum
 * per record. The full contract is specs/project/bd_digest.md. */
enum bd_status {
    BD_OK = 0,
    BD_NULL_ARGUMENT = 1,
    BD_EMPTY_REQUEST = 2,
    BD_TOO_MANY_RECORDS = 3,
    BD_PARTIAL_RECORD = 4,
    BD_STEPS_TOO_LARGE = 5,
    BD_BUFFER_TOO_SMALL = 6,
    BD_INVALID_NUMBER = 7,
    BD_OVERLAP = 8
};
enum {
    BD_RECORD_IN_BYTES = 12,
    BD_RECORD_OUT_BYTES = 16,
    BD_RECORDS_MAX = 14336,
    BD_REQUEST_MAX_BYTES = BD_RECORDS_MAX * BD_RECORD_IN_BYTES,
    BD_OUTPUT_MAX_BYTES = BD_RECORDS_MAX * BD_RECORD_OUT_BYTES,
    BD_STEPS_MAX = 1000000,
    BD_CHECK_VECTORS_MAX = 32
};
/* Seed 0 maps to this value before stepping: xorshift64 has a zero fixed point. */
#define BD_ZERO_SEED UINT64_C(0x9e3779b97f4a7c15)
#define BD_FNV_OFFSET UINT64_C(0xcbf29ce484222325)
#define BD_FNV_PRIME UINT64_C(0x100000001b3)
struct bd_result {
    uint64_t checksum;
    uint64_t state;
};
/* The checksum and final state of one record after exactly steps steps. Any
 * u32 steps value is defined. This is not a route entry: the caller checks
 * steps <= BD_STEPS_MAX first (bd_digest_request does). */
struct bd_result bd_digest_record(uint64_t seed, uint32_t steps);
/* Decodes the 12 bytes at record: seed (u64) and steps (u32), little-endian.
 * BD_NULL_ARGUMENT for a NULL pointer; *seed and *steps are 0 on failure. It
 * does not check the step limit: the caller checks it (bd_check_request). */
enum bd_status bd_decode_record(const unsigned char *record, uint64_t *seed, uint32_t *steps);
/* Writes the 12 bytes of one request record at record: seed, then steps,
 * little-endian. BD_NULL_ARGUMENT for a NULL record. */
enum bd_status bd_encode_record(unsigned char *record, uint64_t seed, uint32_t steps);
/* Reads the 16 bytes of one output record: checksum, then state,
 * little-endian. BD_NULL_ARGUMENT for a NULL pointer; *result is all zero on
 * failure when result is not NULL. */
enum bd_status bd_decode_output(const unsigned char *output, struct bd_result *result);
/* Validates a request of length bytes; *records is the record count on BD_OK
 * and 0 on any other status. */
enum bd_status bd_check_request(const unsigned char *request, size_t length, size_t *records);
/* The only route entry. Writes BD_RECORD_OUT_BYTES per record of a valid
 * request into out. BD_OVERLAP when the request bytes and the output bytes
 * that the call would write share a byte. On any failure *written is 0 and
 * no byte of out changes. */
enum bd_status bd_digest_request(const unsigned char *request, size_t length, unsigned char *out,
                                 size_t capacity, size_t *written);
/* Returns a static name such as "BD_OK"; "BD_UNKNOWN" for other values. */
const char *bd_status_name(enum bd_status status);
/* Program logic of bd-digest SEED STEPS: prints the checksum and the final
 * state in hex. Returns 0 on success, 1 on an argument or write error, 2 on a
 * usage error. */
int bd_main(int argc, char **argv, FILE *out, FILE *err);
/* One self-check vector: the input record and its expected output. */
struct bd_check_vector {
    uint64_t seed;
    uint32_t steps;
    uint64_t checksum;
    uint64_t state;
};
/* Runs count vectors as one request through bd_digest_request and counts the
 * vectors whose output record differs. *mismatches is 0 on any status other
 * than BD_OK. */
enum bd_status bd_check_vectors(const struct bd_check_vector *vectors, size_t count,
                                size_t *mismatches);
/* Runs bd_check_vectors and writes one result line: PASS on out (returns 0),
 * or FAIL or a status name on err (returns 1). A failed write on out
 * returns 1. */
int bd_kernel_report(const struct bd_check_vector *vectors, size_t count, FILE *out, FILE *err);
/* Program logic of bd-kernel --self-check: runs the built-in vectors.
 * Returns bd_kernel_report's result, or 2 on a usage error. */
int bd_kernel_main(int argc, char **argv, FILE *out, FILE *err);
#endif
