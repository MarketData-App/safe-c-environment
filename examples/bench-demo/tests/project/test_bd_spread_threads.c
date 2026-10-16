#include "bd_spread.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

/* Threaded fixture tests derived from specs/project/bd_spread.md: the same result for workers 1 to
 * 4 as for the caller thread (workers 0), with the extra out word unchanged, and the hot threaded
 * run (64 tasks of 20,000 steps on 4 workers, twice) against the serial run. The hot run is the
 * coverage fixture of finding P2-COV-ATOMIC-01. REQUIRE stays active under NDEBUG and has no side
 * effects of its own. */

#define REQUIRE_FAIL(c) (fprintf(stderr, "%s:%d: REQUIRE %s\n", __FILE__, __LINE__, #c), exit(1))
#define REQUIRE(c) ((c) ? (void)0 : REQUIRE_FAIL(c))

/* A comparison result (0 or 1) as unsigned int: results are combined without branches, so GCC
 * -fanalyzer explores one path per loop. */
#define AS_BIT(condition) ((unsigned int)(condition))

enum { WORDS = BD_SPREAD_MAX_TASKS + 1 };

static uint64_t got[WORDS];
static uint64_t serial[WORDS];

static const uint64_t MARK = UINT64_C(0x5a5a5a5a5a5a5a5a);

static void mark(uint64_t *words) {
    for (unsigned int index = 0U; index < (unsigned int)WORDS; ++index) {
        *(words + index) = MARK;
    }
}

struct thread_case {
    uint64_t seed;
    uint32_t tasks;
    uint32_t steps;
    uint32_t workers;
};

/* Each workers value 1 to 4 on one task, on the zero-state seed and on 64 tasks; 1,000,000 steps;
 * then the hot run twice. */
static const struct thread_case cases[] = {
    {7U, 1U, 1U, 1U},
    {0U, 5U, 4U, 1U},
    {UINT64_MAX, BD_SPREAD_MAX_TASKS, 3U, 1U},
    {7U, 1U, 1U, 2U},
    {0U, 5U, 4U, 2U},
    {UINT64_MAX, BD_SPREAD_MAX_TASKS, 3U, 2U},
    {7U, 1U, 1U, 3U},
    {0U, 5U, 4U, 3U},
    {UINT64_MAX, BD_SPREAD_MAX_TASKS, 3U, 3U},
    {7U, 1U, 1U, 4U},
    {0U, 5U, 4U, 4U},
    {UINT64_MAX, BD_SPREAD_MAX_TASKS, 3U, 4U},
    {11U, 1U, BD_SPREAD_MAX_STEPS, 2U},
    {3U, BD_SPREAD_MAX_TASKS, 20000U, BD_SPREAD_MAX_WORKERS},
    {3U, BD_SPREAD_MAX_TASKS, 20000U, BD_SPREAD_MAX_WORKERS},
};

int main(void) {
    unsigned int ok = 1U;
    const size_t count = sizeof cases / sizeof *cases;
    for (size_t index = 0U; index < count; ++index) {
        const struct thread_case *c = cases + index;
        mark(serial);
        mark(got);
        const int serial_rc = bd_spread_run(c->seed, c->tasks, c->steps, 0U, serial, WORDS);
        const int rc = bd_spread_run(c->seed, c->tasks, c->steps, c->workers, got, WORDS);
        ok &= AS_BIT(serial_rc == BD_SPREAD_OK) & AS_BIT(rc == BD_SPREAD_OK);
        for (unsigned int word = 0U; word < (unsigned int)WORDS; ++word) {
            ok &= AS_BIT(*(got + word) == *(serial + word));
        }
        ok &= AS_BIT(*(got + c->tasks) == MARK);
    }
    REQUIRE(ok);
    puts("PASS bd_spread threads");
    return 0;
}
