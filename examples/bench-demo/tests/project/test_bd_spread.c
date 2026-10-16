#include "bd_spread.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Coverage fixture tests derived from specs/project/bd_spread.md: every refused value at its bound
 * leaves out unchanged; one and 64 tasks; one step; the zero-state seed; fixed small digests
 * against an independent model; extra out words stay unchanged. The threaded
 * runs are in test_bd_spread_threads.c (the fixed GCC analyzer budget of one translation unit).
 * REQUIRE stays active under NDEBUG and has no side effects of its own. */

#define REQUIRE_FAIL(c) (fprintf(stderr, "%s:%d: REQUIRE %s\n", __FILE__, __LINE__, #c), exit(1))
#define REQUIRE(c) ((c) ? (void)0 : REQUIRE_FAIL(c))

/* A comparison result (0 or 1) as unsigned int: results are combined without branches, so GCC
 * -fanalyzer explores one path per loop. */
#define AS_BIT(condition) ((unsigned int)(condition))

enum { WORDS = BD_SPREAD_MAX_TASKS + 1 };

/* WORDS copies of the mark word: a struct copy marks the output and memcmp checks it, without a
 * loop in this translation unit (the GCC analyzer budget). */
#define MARK_WORD UINT64_C(0x5a5a5a5a5a5a5a5a)
#define MARK_4 MARK_WORD, MARK_WORD, MARK_WORD, MARK_WORD
#define MARK_16 MARK_4, MARK_4, MARK_4, MARK_4

struct words {
    uint64_t w[WORDS];
};

static const struct words marked = {{MARK_16, MARK_16, MARK_16, MARK_16, MARK_WORD}};
static struct words got;

/* 1 when every word from `from` (at most WORDS) on still holds the mark word. */
static unsigned int marked_from(unsigned int from) {
    const size_t count = (size_t)((unsigned int)WORDS - from);
    return AS_BIT(memcmp(got.w + from, marked.w + from, count * sizeof(uint64_t)) == 0);
}

struct refusal {
    unsigned int null_out;
    uint32_t tasks;
    uint32_t steps;
    uint32_t workers;
    size_t len;
};

/* Every refused value at its bound (specs/project/bd_spread.md); each leaves out unchanged. */
static const struct refusal refusals[] = {
    {1U, 1U, 1U, 0U, WORDS},
    {0U, 0U, 1U, 0U, WORDS},
    {0U, BD_SPREAD_MAX_TASKS + 1U, 1U, 0U, WORDS},
    {0U, UINT32_MAX, 1U, 0U, WORDS},
    {0U, 1U, 0U, 0U, WORDS},
    {0U, 1U, BD_SPREAD_MAX_STEPS + 1U, 0U, WORDS},
    {0U, 1U, UINT32_MAX, 0U, WORDS},
    {0U, 1U, 1U, BD_SPREAD_MAX_WORKERS + 1U, WORDS},
    {0U, 1U, 1U, UINT32_MAX, WORDS},
    {0U, 2U, 1U, 0U, 1U},
    {0U, 1U, 1U, 0U, 0U},
};

static void refusal_table(void) {
    unsigned int ok = 1U;
    const size_t count = sizeof refusals / sizeof *refusals;
    for (size_t index = 0U; index < count; ++index) {
        const struct refusal *r = refusals + index;
        got = marked;
        uint64_t *out = r->null_out != 0U ? NULL : got.w;
        const int rc = bd_spread_run(1U, r->tasks, r->steps, r->workers, out, r->len);
        ok &= AS_BIT(rc == BD_SPREAD_BAD_ARGUMENT) & marked_from(0U);
    }
    REQUIRE(ok);
}

struct run_case {
    uint64_t seed;
    uint32_t tasks;
    uint32_t steps;
    uint32_t workers;
    uint32_t task;
    uint64_t digest;
};

/* D(seed, task, steps) of one task of a run, from an independent model of the spec steps (Python,
 * written apart from src/bd_spread.c): one and 64 tasks, one step, the zero-state seed (task 0 of
 * seed 0), the largest seed, and threaded runs on 2 and 4 workers. 1,000,000 steps is in
 * test_bd_spread_threads.c (serial against threaded): GCC -fanalyzer budget of one unit. */
static const struct run_case runs[] = {
    {7U, 1U, 1U, 0U, 0U, UINT64_C(0x3a037b98ca8f2606)},
    {7U, 3U, 2U, 0U, 0U, UINT64_C(0x50f222135bcabaa6)},
    {7U, 3U, 2U, 0U, 1U, UINT64_C(0x1c6be8b7ba6f3b4a)},
    {7U, 3U, 2U, 0U, 2U, UINT64_C(0xf18bd41e77ab16e6)},
    {7U, 3U, 2U, 2U, 0U, UINT64_C(0x50f222135bcabaa6)},
    {7U, 3U, 2U, 2U, 1U, UINT64_C(0x1c6be8b7ba6f3b4a)},
    {7U, 3U, 2U, 2U, 2U, UINT64_C(0xf18bd41e77ab16e6)},
    {0U, 5U, 4U, 0U, 0U, UINT64_C(0xcf1218a670aecee0)},
    {0U, 5U, 4U, 0U, 1U, UINT64_C(0xcf1219a670aed093)},
    {0U, 5U, 4U, 0U, 4U, UINT64_C(0x7f9f9626f8eee979)},
    {UINT64_MAX, BD_SPREAD_MAX_TASKS, 3U, 0U, 0U, UINT64_C(0xaef662b6a4a975c0)},
    {UINT64_MAX, BD_SPREAD_MAX_TASKS, 3U, 0U, 63U, UINT64_C(0xb5de43393b03d539)},
    {UINT64_MAX, BD_SPREAD_MAX_TASKS, 3U, 4U, 31U, UINT64_C(0xfac625dff1b7fb9b)},
};

static void run_table(void) {
    unsigned int ok = 1U;
    const size_t count = sizeof runs / sizeof *runs;
    for (size_t index = 0U; index < count; ++index) {
        const struct run_case *c = runs + index;
        got = marked;
        const int rc = bd_spread_run(c->seed, c->tasks, c->steps, c->workers, got.w, WORDS);
        ok &= AS_BIT(rc == BD_SPREAD_OK) & marked_from(c->tasks);
        ok &= AS_BIT(*(got.w + c->task) == c->digest);
    }
    REQUIRE(ok);
}

/* out_len equal to tasks: the call writes no word past tasks. */
static void exact_length(void) {
    got = marked;
    const int rc = bd_spread_run(5U, 2U, 3U, 0U, got.w, 2U);
    unsigned int ok = AS_BIT(rc == BD_SPREAD_OK) & marked_from(2U);
    ok &= AS_BIT(*(got.w + 0) == UINT64_C(0x9c63959820af6c98));
    ok &= AS_BIT(*(got.w + 1) == UINT64_C(0x9986dca443f172b8));
    REQUIRE(ok);
}

int main(void) {
    refusal_table();
    run_table();
    exact_length();
    puts("PASS bd_spread");
    return 0;
}
