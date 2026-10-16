#include "bd_digest.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

/* Tests of bd_check_vectors, derived from specs/project/bd_digest.md.
 * REQUIRE stays active under NDEBUG and has no side effects of its own. The
 * bd_kernel_report and bd_kernel_main tests are in
 * tests/project/test_bd_kernel_main.c, a separate translation unit, so each
 * analyzer run stays within its fixed budget. */

/* REQUIRE is an expression: one branch at the use site, and the failure path
 * calls only library functions, so GCC -fanalyzer does not re-analyze a helper
 * function for every use. */
#define REQUIRE_FAIL(c) (fprintf(stderr, "%s:%d: REQUIRE %s\n", __FILE__, __LINE__, #c), exit(1))
#define REQUIRE(c) ((c) ? (void)0 : REQUIRE_FAIL(c))

/* A comparison result (0 or 1) as unsigned int. */
#define AS_BIT(condition) ((unsigned int)(condition))

enum { GOOD_COUNT = 3 };

/* Three rows of the generated vectors of tests/project/test_bd_digest.c. */
static const struct bd_check_vector good[GOOD_COUNT] = {
    {0x0000000000000000U, 0U, 0xcbf29ce484222325U, 0x9e3779b97f4a7c15U},
    {0x0000000000000001U, 1U, 0x37e2fbafd55e2536U, 0x0000000040822041U},
    {0xffffffffffffffffU, 999999U, 0xa9a7f838dff92ec8U, 0xe9c0d662fb69e645U},
};

/* Room for one more vector than the limit. */
static struct bd_check_vector many[BD_CHECK_VECTORS_MAX + 1];

/* Fills many with count correct vectors: seed i + 1, steps i, the expected
 * values from bd_digest_record. */
static void fill_many(size_t count) {
    for (size_t index = 0U; index < count; ++index) {
        const uint64_t seed = (uint64_t)index + 1U;
        const uint32_t steps = (uint32_t)index;
        const struct bd_result r = bd_digest_record(seed, steps);
        struct bd_check_vector *target = many + index;
        target->seed = seed;
        target->steps = steps;
        target->checksum = r.checksum;
        target->state = r.state;
    }
}

/* Returns 1 when bd_check_vectors gives want and want_mismatches. The
 * mismatch count starts at 99, so the test also sees that it is written. */
static unsigned int expect(const struct bd_check_vector *v, size_t count, enum bd_status want,
                           size_t want_mismatches) {
    size_t mismatches = 99U;
    const enum bd_status got = bd_check_vectors(v, count, &mismatches);
    return AS_BIT(got == want) & AS_BIT(mismatches == want_mismatches);
}

/* The status and the mismatch count of bd_check_vectors. */
static void vectors(void) {
    struct bd_check_vector bad[GOOD_COUNT] = {*good, *(good + 1), *(good + 2)};
    unsigned int ok = expect(good, GOOD_COUNT, BD_OK, 0U);
    /* One checksum differs, then one state differs too: 1, then 2. */
    (bad + 1)->checksum ^= 1U;
    ok &= expect(bad, GOOD_COUNT, BD_OK, 1U);
    (bad + 2)->state ^= UINT64_C(0x8000000000000000);
    ok &= expect(bad, GOOD_COUNT, BD_OK, 2U);
    /* A changed state alone is a mismatch. */
    *(bad + 1) = *(good + 1);
    ok &= expect(bad, GOOD_COUNT, BD_OK, 1U);
    /* One vector, and the exact limit. */
    ok &= expect(good, 1U, BD_OK, 0U);
    fill_many((size_t)BD_CHECK_VECTORS_MAX + 1U);
    ok &= expect(many, BD_CHECK_VECTORS_MAX, BD_OK, 0U);
    REQUIRE(ok);
    /* Zero, one past the limit, the representable maximum and a step count
     * above BD_STEPS_MAX: no comparison, the mismatch count is 0. */
    ok &= expect(good, 0U, BD_EMPTY_REQUEST, 0U);
    ok &= expect(many, (size_t)BD_CHECK_VECTORS_MAX + 1U, BD_TOO_MANY_RECORDS, 0U);
    ok &= expect(good, SIZE_MAX, BD_TOO_MANY_RECORDS, 0U);
    struct bd_check_vector past = *good;
    past.steps = (uint32_t)BD_STEPS_MAX + 1U;
    ok &= expect(&past, 1U, BD_STEPS_TOO_LARGE, 0U);
    /* NULL arguments. */
    ok &= expect(NULL, GOOD_COUNT, BD_NULL_ARGUMENT, 0U);
    ok &= AS_BIT(bd_check_vectors(good, GOOD_COUNT, NULL) == BD_NULL_ARGUMENT);
    REQUIRE(ok);
}

/* A stream opened for reading rejects every write: result 1. */
static void rejected_write(void) {
    FILE *read_only = fopen("/dev/null", "r");
    if (read_only == NULL) {
        (void)fputs("fopen /dev/null failed\n", stderr);
        exit(1);
    }
    const int got = bd_kernel_report(good, GOOD_COUNT, read_only, stderr);
    REQUIRE(fclose(read_only) == 0);
    REQUIRE(got == 1);
}

int main(void) {
    vectors();
    rejected_write();
    return 0;
}
