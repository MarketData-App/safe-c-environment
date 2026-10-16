#include "entry.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

/* Tests of fixture_entry and fixture_run, derived from specs/project/entry.md.
 * REQUIRE stays active under NDEBUG and has no side effects of its own. */

#define REQUIRE_FAIL(c) (fprintf(stderr, "%s:%d: REQUIRE %s\n", __FILE__, __LINE__, #c), exit(1))
#define REQUIRE(c) ((c) ? (void)0 : REQUIRE_FAIL(c))

enum { VALUES = FIXTURE_ENTRY_MAX + 1 };

static void test_entry(void) {
    double x[VALUES];
    for (size_t index = 0U; index < (size_t)VALUES; ++index) {
        *(x + index) = 1.0;
    }
    *x = 0.5;
    double out = -7.0;
    /* Refusals: NULL pointers, zero, one past the maximum and SIZE_MAX; out is unchanged. */
    REQUIRE(fixture_entry(NULL, 1U, &out) == 1);
    REQUIRE(fixture_entry(x, 1U, NULL) == 1);
    REQUIRE(fixture_entry(x, 0U, &out) == 1);
    REQUIRE(fixture_entry(x, (size_t)FIXTURE_ENTRY_MAX + 1U, &out) == 1);
    REQUIRE(fixture_entry(x, SIZE_MAX, &out) == 1);
    REQUIRE(out == -7.0);
    /* One element, two elements and the exact maximum. */
    REQUIRE(fixture_entry(x, 1U, &out) == 0);
    REQUIRE(out == 0.5);
    REQUIRE(fixture_entry(x, 2U, &out) == 0);
    REQUIRE(out == 1.5);
    REQUIRE(fixture_entry(x, (size_t)FIXTURE_ENTRY_MAX, &out) == 0);
    REQUIRE(out == 63.5);
    /* Negative values and a signed zero sum keep binary64 addition. */
    *(x + 1) = -0.5;
    REQUIRE(fixture_entry(x, 2U, &out) == 0);
    REQUIRE(out == 0.0);
}

static void test_run(void) {
    static char program[] = "fixture-run";
    static char check[] = "--self-check";
    static char prefix[] = "--self";
    static char longer[] = "--self-checks";
    static char empty[] = "";
    char *good[] = {program, check, NULL};
    char *short_arg[] = {program, prefix, NULL};
    char *long_arg[] = {program, longer, NULL};
    char *empty_arg[] = {program, empty, NULL};
    char *null_arg[] = {program, NULL, NULL};
    char *three[] = {program, check, check, NULL};
    REQUIRE(fixture_run(2, good) == 0);
    REQUIRE(fixture_run(1, good) == 2);
    REQUIRE(fixture_run(3, three) == 2);
    REQUIRE(fixture_run(2, NULL) == 2);
    REQUIRE(fixture_run(2, short_arg) == 2);
    REQUIRE(fixture_run(2, long_arg) == 2);
    REQUIRE(fixture_run(2, empty_arg) == 2);
    REQUIRE(fixture_run(2, null_arg) == 2);
}

int main(void) {
    test_entry();
    test_run();
    (void)puts("PASS entry");
    return 0;
}
