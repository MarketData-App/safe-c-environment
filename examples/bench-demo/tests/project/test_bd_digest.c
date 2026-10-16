#include "bd_digest.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

/* Vector, anchor and maximum-request tests derived from
 * specs/project/bd_digest.md. REQUIRE stays active under NDEBUG and has no
 * side effects of its own. The expected values come from the Python reference
 * (benchdemo.vectors). The project unit test
 * benchmarks/project/python/tests/test_demo.py checks that the block below is
 * the generated block byte for byte. The request-bound tests are in
 * tests/project/test_bd_request.c and the bd_main tests in
 * tests/project/test_bd_main.c, separate translation units, so each analyzer
 * run stays within its fixed budget. */

/* REQUIRE is an expression: one branch at the use site, and the failure path
 * calls only library functions, so GCC -fanalyzer does not re-analyze a helper
 * function for every use. */
#define REQUIRE_FAIL(c) (fprintf(stderr, "%s:%d: REQUIRE %s\n", __FILE__, __LINE__, #c), exit(1))
#define REQUIRE(c) ((c) ? (void)0 : REQUIRE_FAIL(c))

/* BEGIN GENERATED VECTORS: benchdemo.vectors; regenerate, never edit by hand */
struct bd_vector {
    uint64_t seed;
    uint32_t steps;
    uint64_t checksum;
    uint64_t state;
};

/* seed, steps, FNV-1a checksum, final state */
static const struct bd_vector bd_vectors[] = {
    {0x0000000000000000U, 0U, 0xcbf29ce484222325U, 0x9e3779b97f4a7c15U},
    {0x0000000000000000U, 1U, 0x9e44ffe67972dc6dU, 0xdc1b77ae0bf34dadU},
    {0x0000000000000000U, 2U, 0xd1beeb107f8ec798U, 0x64f0eeb9026e6076U},
    {0x0000000000000000U, 1000000U, 0xcc7c912f60df17abU, 0x3e746a84b0b86f03U},
    {0x9e3779b97f4a7c15U, 0U, 0xcbf29ce484222325U, 0x9e3779b97f4a7c15U},
    {0x9e3779b97f4a7c15U, 1U, 0x9e44ffe67972dc6dU, 0xdc1b77ae0bf34dadU},
    {0x0000000000000001U, 0U, 0xcbf29ce484222325U, 0x0000000000000001U},
    {0x0000000000000001U, 1U, 0x37e2fbafd55e2536U, 0x0000000040822041U},
    {0x0000000000000001U, 2U, 0xea443c57c075a843U, 0x100041060c011441U},
    {0x0000000000000001U, 3U, 0x6f423fe00d993980U, 0x9b1e842f6e862629U},
    {0x0000000000000002U, 64U, 0x298a07e8400f6f8cU, 0xaa83d55440673596U},
    {0x000000000135288fU, 64U, 0xc370523f1bfa3fe7U, 0x106c4bf21edae149U},
    {0x0123456789abcdefU, 4096U, 0xcb34fef79bb6833aU, 0x32744d2ca7ad39ddU},
    {0x8000000000000000U, 13U, 0x46ebb398af5cf94dU, 0x4d70a82913179aa9U},
    {0x7fffffffffffffffU, 7U, 0x4ccea6f64fe03e7dU, 0xe9443e112b5303f1U},
    {0xffffffffffffffffU, 0U, 0xcbf29ce484222325U, 0xffffffffffffffffU},
    {0xffffffffffffffffU, 1U, 0x6a1c4a26425994ddU, 0x000000003f801fc0U},
    {0xffffffffffffffffU, 999999U, 0xa9a7f838dff92ec8U, 0xe9c0d662fb69e645U},
    {0xdeadbeefcafef00dU, 1000000U, 0x1d7b49e45b2eebfeU, 0x36c853cbd9325819U},
};

/* The request of BD_RECORDS_MAX records: record i has seed i * 0x9e3779b97f4a7c15 (mod 2^64)
 * and steps i % 31. The value is FNV-1a 64 over its whole output. */
enum { BD_MAX_STEP_CYCLE = 31 };
static const uint64_t bd_max_request_output_fnv = 0x7829d1ed6fb374dcU;
/* END GENERATED VECTORS */

/* Room for BD_RECORDS_MAX + 1 request records and BD_RECORDS_MAX + 1 output
 * records. Static storage: the test allocates no memory. */
static unsigned char big_request[BD_REQUEST_MAX_BYTES + BD_RECORD_IN_BYTES];
static unsigned char big_output[BD_OUTPUT_MAX_BYTES + BD_RECORD_OUT_BYTES];

/* An independent FNV-1a 64 over bytes, one byte at a time. */
static uint64_t test_fnv(const unsigned char *bytes, size_t length) {
    uint64_t hash = BD_FNV_OFFSET;
    for (size_t index = 0U; index < length; ++index) {
        const uint64_t byte = *(bytes + index);
        uint64_t product = 0U;
        (void)__builtin_mul_overflow(hash ^ byte, BD_FNV_PRIME, &product);
        hash = product;
    }
    return hash;
}

/* A comparison result (0 or 1) as unsigned int. */
#define AS_BIT(condition) ((unsigned int)(condition))

enum { VECTOR_COUNT = sizeof bd_vectors / sizeof *bd_vectors };

/* Every vector through bd_digest_record, then all vectors as one request.
 * The records are written and read with bd_encode_record and
 * bd_decode_output (their byte layouts are tested in test_bd_request.c).
 * Results are combined without branches, so GCC -fanalyzer explores one path
 * per loop. */
static void vector_table(void) {
    unsigned char req[VECTOR_COUNT * BD_RECORD_IN_BYTES] = {0};
    unsigned char out[VECTOR_COUNT * BD_RECORD_OUT_BYTES] = {0};
    unsigned int ok = 1U;
    for (size_t index = 0U; index < (size_t)VECTOR_COUNT; ++index) {
        const struct bd_vector *vector = bd_vectors + index;
        const struct bd_result got = bd_digest_record(vector->seed, vector->steps);
        ok &= AS_BIT(got.checksum == vector->checksum) & AS_BIT(got.state == vector->state);
        unsigned char *record = req + index * BD_RECORD_IN_BYTES;
        ok &= AS_BIT(bd_encode_record(record, vector->seed, vector->steps) == BD_OK);
    }
    REQUIRE(ok);
    size_t w = 0U;
    const enum bd_status st = bd_digest_request(req, sizeof req, out, sizeof out, &w);
    REQUIRE(AS_BIT(st == BD_OK) & AS_BIT(w == sizeof out));
    for (size_t index = 0U; index < (size_t)VECTOR_COUNT; ++index) {
        struct bd_result got = {.checksum = 0U, .state = 0U};
        ok &= AS_BIT(bd_decode_output(out + index * BD_RECORD_OUT_BYTES, &got) == BD_OK);
        ok &= AS_BIT(got.checksum == (bd_vectors + index)->checksum);
        ok &= AS_BIT(got.state == (bd_vectors + index)->state);
    }
    REQUIRE(ok);
}

/* Fills big_request with count records of the generated rule: record i has
 * seed i * BD_ZERO_SEED (mod 2^64) and steps i % BD_MAX_STEP_CYCLE. Returns 1
 * when every record was written. */
static unsigned int fill_big_request(size_t count) {
    unsigned int ok = 1U;
    for (size_t index = 0U; index < count; ++index) {
        uint64_t seed = 0U;
        (void)__builtin_mul_overflow((uint64_t)index, BD_ZERO_SEED, &seed);
        const uint32_t steps = (uint32_t)(index % (size_t)BD_MAX_STEP_CYCLE);
        unsigned char *record = big_request + index * BD_RECORD_IN_BYTES;
        ok &= AS_BIT(bd_encode_record(record, seed, steps) == BD_OK);
    }
    return ok;
}

/* The exact maximum request, one record past it and the representable
 * maximum length. */
static void maximum_request(void) {
    const size_t max_in = BD_REQUEST_MAX_BYTES;
    const size_t max_out = BD_OUTPUT_MAX_BYTES;
    REQUIRE(fill_big_request((size_t)BD_RECORDS_MAX + 1U));
    size_t w = 99U;
    size_t count = 99U;
    unsigned int ok = AS_BIT(bd_check_request(big_request, max_in, &count) == BD_OK);
    ok &= AS_BIT(count == (size_t)BD_RECORDS_MAX);
    /* A sentinel byte just after the maximum output. */
    *(big_output + max_out) = 0xA5U;
    enum bd_status st = bd_digest_request(big_request, max_in, big_output, sizeof big_output, &w);
    ok &= AS_BIT(st == BD_OK) & AS_BIT(w == max_out);
    ok &= AS_BIT(*(big_output + max_out) == 0xA5U);
    REQUIRE(ok);
    REQUIRE(test_fnv(big_output, max_out) == bd_max_request_output_fnv);
    /* The exact output capacity is enough; one byte less is not. */
    st = bd_digest_request(big_request, max_in, big_output, max_out, &w);
    ok &= AS_BIT(st == BD_OK) & AS_BIT(w == max_out);
    st = bd_digest_request(big_request, max_in, big_output, max_out - 1U, &w);
    ok &= AS_BIT(st == BD_BUFFER_TOO_SMALL) & AS_BIT(w == 0U);
    /* Length checks happen before any byte is read. */
    count = 99U;
    st = bd_check_request(big_request, sizeof big_request, &count);
    ok &= AS_BIT(st == BD_TOO_MANY_RECORDS) & AS_BIT(count == 0U);
    st = bd_check_request(big_request, max_in + 1U, &count);
    ok &= AS_BIT(st == BD_TOO_MANY_RECORDS);
    st = bd_check_request(big_request, SIZE_MAX, &count);
    ok &= AS_BIT(st == BD_TOO_MANY_RECORDS);
    st = bd_digest_request(big_request, SIZE_MAX, big_output, SIZE_MAX, &w);
    ok &= AS_BIT(st == BD_TOO_MANY_RECORDS);
    REQUIRE(ok);
}

/* Definitional anchors, independent of the generated block. */
static void anchors(void) {
    const struct bd_result zero = bd_digest_record(0U, 0U);
    const struct bd_result one = bd_digest_record(1U, 0U);
    const struct bd_result step = bd_digest_record(1U, 1U);
    const struct bd_result mapped = bd_digest_record(BD_ZERO_SEED, 9U);
    const struct bd_result from_zero = bd_digest_record(0U, 9U);
    unsigned int ok = AS_BIT(zero.checksum == BD_FNV_OFFSET) & AS_BIT(zero.state == BD_ZERO_SEED);
    ok &= AS_BIT(one.checksum == BD_FNV_OFFSET) & AS_BIT(one.state == 1U);
    /* x = 1: x ^= x << 13 gives 0x2001; x ^= x >> 7 gives 0x2041;
     * x ^= x << 17 gives 0x40822041. The checksum is FNV-1a 64 of the bytes
     * 41 20 82 40 00 00 00 00, computed outside the module. */
    ok &= AS_BIT(step.state == UINT64_C(0x40822041));
    ok &= AS_BIT(step.checksum == UINT64_C(0x37e2fbafd55e2536));
    ok &= AS_BIT(mapped.checksum == from_zero.checksum) & AS_BIT(mapped.state == from_zero.state);
    REQUIRE(ok);
}

int main(void) {
    anchors();
    vector_table();
    maximum_request();
    return 0;
}
