#include "bd_digest.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Request, decode and status-name tests derived from
 * specs/project/bd_digest.md: length, steps and capacity bounds, the
 * validation order, the output postconditions and NULL arguments. REQUIRE
 * stays active under NDEBUG and has no side effects of its own. The vector
 * tests are in tests/project/test_bd_digest.c, a separate translation unit,
 * so each analyzer run stays within its fixed budget. */

/* REQUIRE is an expression: one branch at the use site, and the failure path
 * calls only library functions, so GCC -fanalyzer does not re-analyze a helper
 * function for every use. */
#define REQUIRE_FAIL(c) (fprintf(stderr, "%s:%d: REQUIRE %s\n", __FILE__, __LINE__, #c), exit(1))
#define REQUIRE(c) ((c) ? (void)0 : REQUIRE_FAIL(c))

/* A comparison result (0 or 1) as unsigned int. */
#define AS_BIT(condition) ((unsigned int)(condition))

/* n records in the request (the last has steps last), len bytes passed, cap
 * bytes of output capacity passed. */
struct request_case {
    size_t n;
    uint32_t last;
    size_t len;
    size_t cap;
    enum bd_status want;
};

static const struct request_case request_cases[] = {
    /* Length: zero, partial, one record, one past, two records. */
    {.n = 1U, .last = 0U, .len = 0U, .cap = 64U, .want = BD_EMPTY_REQUEST},
    {.n = 1U, .last = 0U, .len = 1U, .cap = 64U, .want = BD_PARTIAL_RECORD},
    {.n = 1U, .last = 0U, .len = 11U, .cap = 64U, .want = BD_PARTIAL_RECORD},
    {.n = 1U, .last = 0U, .len = 12U, .cap = 64U, .want = BD_OK},
    {.n = 2U, .last = 0U, .len = 13U, .cap = 64U, .want = BD_PARTIAL_RECORD},
    {.n = 2U, .last = 0U, .len = 23U, .cap = 64U, .want = BD_PARTIAL_RECORD},
    {.n = 2U, .last = 0U, .len = 24U, .cap = 64U, .want = BD_OK},
    /* Steps: one, the exact limit, one past, the u32 maximum, a later record. */
    {.n = 1U, .last = 1U, .len = 12U, .cap = 16U, .want = BD_OK},
    {.n = 1U, .last = 1000000U, .len = 12U, .cap = 16U, .want = BD_OK},
    {.n = 1U, .last = 1000001U, .len = 12U, .cap = 16U, .want = BD_STEPS_TOO_LARGE},
    {.n = 1U, .last = UINT32_MAX, .len = 12U, .cap = 16U, .want = BD_STEPS_TOO_LARGE},
    {.n = 3U, .last = 1000001U, .len = 36U, .cap = 64U, .want = BD_STEPS_TOO_LARGE},
    /* Capacity: zero, one, exact - 1, exact, for one and two records. */
    {.n = 1U, .last = 5U, .len = 12U, .cap = 0U, .want = BD_BUFFER_TOO_SMALL},
    {.n = 1U, .last = 5U, .len = 12U, .cap = 1U, .want = BD_BUFFER_TOO_SMALL},
    {.n = 1U, .last = 5U, .len = 12U, .cap = 15U, .want = BD_BUFFER_TOO_SMALL},
    {.n = 1U, .last = 5U, .len = 12U, .cap = 16U, .want = BD_OK},
    {.n = 2U, .last = 5U, .len = 24U, .cap = 31U, .want = BD_BUFFER_TOO_SMALL},
    {.n = 2U, .last = 5U, .len = 24U, .cap = 32U, .want = BD_OK},
    /* Order: an earlier failure wins over a later one. */
    {.n = 1U, .last = 1000001U, .len = 0U, .cap = 0U, .want = BD_EMPTY_REQUEST},
    {.n = 2U, .last = 1000001U, .len = 13U, .cap = 0U, .want = BD_PARTIAL_RECORD},
    {.n = 1U, .last = 1000001U, .len = 12U, .cap = 0U, .want = BD_STEPS_TOO_LARGE},
};

enum { CASE_RECORDS = 3, CASE_BUFFER = 64 };

/* The output buffer is a struct so that it can start as a copy of a sentinel
 * block (the raw memory functions are outside the project API policy). */
struct case_buffer {
    unsigned char bytes[CASE_BUFFER];
};

#define CASE_Z16 "ZZZZZZZZZZZZZZZZ"
/* CASE_BUFFER (64) sentinel bytes 'Z'; the array has no room for a NUL. */
static const struct case_buffer case_sentinel = {CASE_Z16 CASE_Z16 CASE_Z16 CASE_Z16};

/* The request holds n records: the records before the last have seeds 7 and
 * 8 and steps 3; the last has seed 0 and steps last. The output buffer starts
 * as sentinel bytes: on success only the output records change, on failure no
 * byte changes. Records are written with bd_encode_record and read with
 * bd_decode_output (their byte layouts are tested below), and the results are
 * combined without branches, so GCC -fanalyzer explores few paths per case. */
static void expect_request(const struct request_case *test) {
    unsigned char request[CASE_RECORDS * BD_RECORD_IN_BYTES] = {0};
    struct case_buffer buffer = case_sentinel;
    unsigned char *out = buffer.bytes;
    const unsigned char *sentinel = case_sentinel.bytes;
    REQUIRE(test->n >= 1U && test->n <= (size_t)CASE_RECORDS);
    REQUIRE(test->cap <= (size_t)CASE_BUFFER);
    unsigned int put = AS_BIT(bd_encode_record(request, 7U, 3U) == BD_OK);
    put &= AS_BIT(bd_encode_record(request + BD_RECORD_IN_BYTES, 8U, 3U) == BD_OK);
    unsigned char *final_record = request + (test->n - 1U) * BD_RECORD_IN_BYTES;
    put &= AS_BIT(bd_encode_record(final_record, 0U, test->last) == BD_OK);
    REQUIRE(put);
    size_t written = 99U;
    const enum bd_status got = bd_digest_request(request, test->len, out, test->cap, &written);
    REQUIRE(got == test->want);
    if (got == BD_OK) {
        const size_t needed = test->len / BD_RECORD_IN_BYTES * BD_RECORD_OUT_BYTES;
        REQUIRE(needed >= 16U && needed <= (size_t)CASE_BUFFER);
        /* The last output record is the digest of the last request record. */
        const struct bd_result last = bd_digest_record(0U, test->last);
        struct bd_result got_last = {.checksum = 0U, .state = 0U};
        unsigned int ok = AS_BIT(written == needed);
        ok &= AS_BIT(bd_decode_output(out + needed - 16U, &got_last) == BD_OK);
        ok &= AS_BIT(got_last.checksum == last.checksum) & AS_BIT(got_last.state == last.state);
        const size_t tail = (size_t)CASE_BUFFER - needed;
        ok &= AS_BIT(memcmp(out + needed, sentinel + needed, tail) == 0);
        REQUIRE(ok);
    } else {
        REQUIRE(AS_BIT(written == 0U) & AS_BIT(memcmp(out, sentinel, (size_t)CASE_BUFFER) == 0));
    }
}

static void request_table(void) {
    const size_t count = sizeof request_cases / sizeof *request_cases;
    for (size_t item = 0U; item < count; ++item) {
        expect_request(request_cases + item);
    }
}

/* One record (seed 7, steps) at area + in_at and the output at area + out_at
 * with capacity cap, all inside one 64-byte area. On BD_OK the output record
 * is the digest of the record; on any other status *written is 0 and no byte
 * of the area changes. Returns 1 when the case holds. */
static unsigned int overlap_case(size_t in_at, size_t out_at, size_t cap, uint32_t steps,
                                 enum bd_status want) {
    const size_t length = BD_RECORD_IN_BYTES;
    const size_t area_size = CASE_BUFFER;
    struct case_buffer area = case_sentinel;
    REQUIRE(in_at + length <= area_size);
    REQUIRE(out_at + cap <= area_size);
    unsigned char *request = area.bytes + in_at;
    unsigned char *out = area.bytes + out_at;
    unsigned int ok = AS_BIT(bd_encode_record(request, 7U, steps) == BD_OK);
    const struct case_buffer before = area;
    size_t written = 99U;
    const enum bd_status got = bd_digest_request(request, length, out, cap, &written);
    ok &= AS_BIT(got == want);
    if (want == BD_OK) {
        const struct bd_result expected = bd_digest_record(7U, steps);
        struct bd_result result = {.checksum = 0U, .state = 0U};
        ok &= AS_BIT(written == (size_t)BD_RECORD_OUT_BYTES);
        ok &= AS_BIT(bd_decode_output(out, &result) == BD_OK);
        ok &= AS_BIT(result.checksum == expected.checksum);
        ok &= AS_BIT(result.state == expected.state);
    } else {
        ok &= AS_BIT(written == 0U);
        ok &= AS_BIT(memcmp(area.bytes, before.bytes, area_size) == 0);
    }
    return ok;
}

/* N1-A01: the request bytes [request, request + length) and the output bytes
 * that the call would write [out, out + 16n) must not share a byte. Adjacent
 * regions in either order are not an overlap, and output capacity after 16n
 * may cover the request. The overlap check comes after the request and
 * capacity checks. */
static void overlap(void) {
    /* Adjacent: the output starts just after the request, or ends just before it. */
    REQUIRE(overlap_case(0U, 12U, 16U, 5U, BD_OK));
    REQUIRE(overlap_case(16U, 0U, 16U, 5U, BD_OK));
    /* The capacity after 16n covers the request: not an overlap. */
    REQUIRE(overlap_case(20U, 0U, 64U, 5U, BD_OK));
    /* Same start; the output starts on the last request byte; the request
     * starts on the last output byte; the request lies inside the output; the
     * output starts inside the request. */
    REQUIRE(overlap_case(0U, 0U, 16U, 5U, BD_OVERLAP));
    REQUIRE(overlap_case(0U, 11U, 16U, 5U, BD_OVERLAP));
    REQUIRE(overlap_case(15U, 0U, 16U, 5U, BD_OVERLAP));
    REQUIRE(overlap_case(2U, 0U, 16U, 5U, BD_OVERLAP));
    REQUIRE(overlap_case(4U, 6U, 16U, 5U, BD_OVERLAP));
    /* Order: a request failure and a capacity failure win over an overlap. */
    REQUIRE(overlap_case(0U, 0U, 16U, 1000001U, BD_STEPS_TOO_LARGE));
    REQUIRE(overlap_case(0U, 0U, 15U, 5U, BD_BUFFER_TOO_SMALL));
}

static void null_arguments(void) {
    unsigned char request[BD_RECORD_IN_BYTES] = {0};
    unsigned char out[BD_RECORD_OUT_BYTES] = {0};
    const size_t in_len = sizeof request;
    const size_t out_len = sizeof out;
    size_t first = 99U;
    size_t second = 99U;
    size_t count = 99U;
    /* All results are combined without branches (one REQUIRE). */
    unsigned int ok = 1U;
    ok &= AS_BIT(bd_digest_request(NULL, in_len, out, out_len, &first) == BD_NULL_ARGUMENT);
    ok &= AS_BIT(bd_digest_request(request, in_len, NULL, out_len, &second) == BD_NULL_ARGUMENT);
    ok &= AS_BIT(bd_digest_request(request, in_len, out, out_len, NULL) == BD_NULL_ARGUMENT);
    ok &= AS_BIT(bd_digest_request(NULL, 0U, NULL, 0U, NULL) == BD_NULL_ARGUMENT);
    ok &= AS_BIT(bd_check_request(NULL, in_len, &count) == BD_NULL_ARGUMENT);
    ok &= AS_BIT(bd_check_request(request, in_len, NULL) == BD_NULL_ARGUMENT);
    ok &= AS_BIT(bd_check_request(NULL, 0U, NULL) == BD_NULL_ARGUMENT);
    ok &= AS_BIT(first == 0U) & AS_BIT(second == 0U) & AS_BIT(count == 0U);
    REQUIRE(ok);
}

/* The record layout: seed bytes 0..7 and steps bytes 8..11, little-endian. */
static void decode(void) {
    static const unsigned char record[] = {8, 7, 6, 5, 4, 3, 2, 1, 13, 12, 11, 10};
    REQUIRE(sizeof record == (size_t)BD_RECORD_IN_BYTES);
    uint64_t seed = 99U;
    uint32_t steps = 99U;
    uint64_t null_seed = 99U;
    uint32_t null_steps = 99U;
    uint64_t only_seed = 99U;
    uint32_t only_steps = 99U;
    /* All results are combined without branches (one REQUIRE). */
    unsigned int ok = AS_BIT(bd_decode_record(record, &seed, &steps) == BD_OK);
    ok &= AS_BIT(seed == UINT64_C(0x0102030405060708)) & AS_BIT(steps == UINT32_C(0x0A0B0C0D));
    ok &= AS_BIT(bd_decode_record(NULL, &null_seed, &null_steps) == BD_NULL_ARGUMENT);
    ok &= AS_BIT(null_seed == 0U) & AS_BIT(null_steps == 0U);
    ok &= AS_BIT(bd_decode_record(record, NULL, &only_steps) == BD_NULL_ARGUMENT);
    ok &= AS_BIT(bd_decode_record(record, &only_seed, NULL) == BD_NULL_ARGUMENT);
    ok &= AS_BIT(only_seed == 0U) & AS_BIT(only_steps == 0U);
    ok &= AS_BIT(bd_decode_record(NULL, NULL, NULL) == BD_NULL_ARGUMENT);
    REQUIRE(ok);
}

/* bd_encode_record writes exactly the layout that bd_decode_record reads. */
static void encode(void) {
    static const unsigned char want[] = {8, 7, 6, 5, 4, 3, 2, 1, 13, 12, 11, 10, 0x5A};
    unsigned char record[BD_RECORD_IN_BYTES + 1] = {[BD_RECORD_IN_BYTES] = 0x5A};
    const uint64_t seed = UINT64_C(0x0102030405060708);
    unsigned int ok = AS_BIT(bd_encode_record(record, seed, UINT32_C(0x0A0B0C0D)) == BD_OK);
    /* The byte after the record does not change. */
    ok &= AS_BIT(sizeof want == sizeof record) & AS_BIT(memcmp(record, want, sizeof want) == 0);
    ok &= AS_BIT(bd_encode_record(NULL, seed, 1U) == BD_NULL_ARGUMENT);
    REQUIRE(ok);
}

/* The output layout: checksum bytes 0..7 and state bytes 8..15, little-endian. */
static void decode_output(void) {
    static const unsigned char output[] = {8, 7, 6, 5, 4, 3, 2, 1, 16, 15, 14, 13, 12, 11, 10, 9};
    struct bd_result got = {.checksum = 0U, .state = 0U};
    struct bd_result cleared = {.checksum = 99U, .state = 99U};
    unsigned int ok = AS_BIT(sizeof output == (size_t)BD_RECORD_OUT_BYTES);
    ok &= AS_BIT(bd_decode_output(output, &got) == BD_OK);
    ok &= AS_BIT(got.checksum == UINT64_C(0x0102030405060708));
    ok &= AS_BIT(got.state == UINT64_C(0x090A0B0C0D0E0F10));
    ok &= AS_BIT(bd_decode_output(NULL, &cleared) == BD_NULL_ARGUMENT);
    ok &= AS_BIT(cleared.checksum == 0U) & AS_BIT(cleared.state == 0U);
    ok &= AS_BIT(bd_decode_output(output, NULL) == BD_NULL_ARGUMENT);
    REQUIRE(ok);
}

static void expect_name(enum bd_status status, const char *want) {
    REQUIRE(strcmp(bd_status_name(status), want) == 0);
}

static void status_names(void) {
    expect_name(BD_OK, "BD_OK");
    expect_name(BD_NULL_ARGUMENT, "BD_NULL_ARGUMENT");
    expect_name(BD_EMPTY_REQUEST, "BD_EMPTY_REQUEST");
    expect_name(BD_TOO_MANY_RECORDS, "BD_TOO_MANY_RECORDS");
    expect_name(BD_PARTIAL_RECORD, "BD_PARTIAL_RECORD");
    expect_name(BD_STEPS_TOO_LARGE, "BD_STEPS_TOO_LARGE");
    expect_name(BD_BUFFER_TOO_SMALL, "BD_BUFFER_TOO_SMALL");
    expect_name(BD_INVALID_NUMBER, "BD_INVALID_NUMBER");
    expect_name(BD_OVERLAP, "BD_OVERLAP");
    expect_name((enum bd_status)9, "BD_UNKNOWN");
}

int main(void) {
    request_table();
    overlap();
    null_arguments();
    decode();
    encode();
    decode_output();
    status_names();
    return 0;
}
