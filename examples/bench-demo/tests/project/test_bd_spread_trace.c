#include "bd_spread.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Tests of bd_spread_trace, derived from specs/project/bd_spread.md: every refused value at its
 * bound leaves out, the spans and the report unchanged; one and 64 tasks on 1, 2 and 4 workers give
 * the serial words, a complete trace and a complete report, and leave the extra word and span
 * unchanged. The program tests are in test_bd_spread_cli.c (the fixed GCC analyzer budget of one
 * translation unit). REQUIRE stays active under NDEBUG and has no side effects of its own. */

#define REQUIRE_FAIL(c) (fprintf(stderr, "%s:%d: REQUIRE %s\n", __FILE__, __LINE__, #c), exit(1))
#define REQUIRE(c) ((c) ? (void)0 : REQUIRE_FAIL(c))

/* A comparison result (0 or 1) as unsigned int: results are combined without branches, so GCC
 * -fanalyzer explores one path per loop. */
#define AS_BIT(condition) ((unsigned int)(condition))

enum { WORDS = BD_SPREAD_MAX_TASKS + 1 };

/* WORDS copies of the mark word and of the mark span: a struct copy marks the outputs and memcmp
 * checks them, without a loop in this translation unit (the GCC analyzer budget). */
#define MARK_WORD UINT64_C(0x5a5a5a5a5a5a5a5a)
#define MARK_4 MARK_WORD, MARK_WORD, MARK_WORD, MARK_WORD
#define MARK_16 MARK_4, MARK_4, MARK_4, MARK_4
#define SPAN_1 {MARK_WORD, MARK_WORD, MARK_WORD, UINT32_MAX, UINT32_MAX}
#define SPAN_4 SPAN_1, SPAN_1, SPAN_1, SPAN_1
#define SPAN_16 SPAN_4, SPAN_4, SPAN_4, SPAN_4

struct words {
    uint64_t w[WORDS];
};

struct spans {
    struct bd_spread_span s[WORDS];
};

static const struct words marked = {{MARK_16, MARK_16, MARK_16, MARK_16, MARK_WORD}};
static const struct spans marked_spans = {{SPAN_16, SPAN_16, SPAN_16, SPAN_16, SPAN_1}};
static struct words got;
static struct words serial;
static struct spans spans;
static struct bd_spread_report report;

static void mark_all(void) {
    got = marked;
    serial = marked;
    spans = marked_spans;
    report.submitted = MARK_WORD;
    report.executed = MARK_WORD;
    report.max_inflight = MARK_WORD;
    report.threads = UINT32_MAX;
}

static unsigned int report_marked(void) {
    unsigned int ok = AS_BIT(report.submitted == MARK_WORD) & AS_BIT(report.executed == MARK_WORD);
    ok &= AS_BIT(report.max_inflight == MARK_WORD) & AS_BIT(report.threads == UINT32_MAX);
    return ok;
}

/* 1 when every word and span from `from` (at most WORDS) on still holds its mark. */
static unsigned int marked_from(unsigned int from) {
    const size_t count = (size_t)((unsigned int)WORDS - from);
    const unsigned int words = AS_BIT(memcmp(got.w + from, marked.w + from, count * 8U) == 0);
    const size_t span_bytes = count * sizeof(struct bd_spread_span);
    const struct bd_spread_span *want = marked_spans.s + from;
    return words & AS_BIT(memcmp(spans.s + from, want, span_bytes) == 0);
}

struct refusal {
    uint64_t *out;
    struct bd_spread_span *spans;
    struct bd_spread_report *report;
    uint32_t tasks;
    uint32_t steps;
    uint32_t workers;
    size_t out_len;
    size_t span_len;
};

/* Every refused value at its bound (specs/project/bd_spread.md, bd_spread_trace). */
static const struct refusal refusals[] = {
    {got.w, spans.s, &report, 1U, 1U, 0U, WORDS, WORDS},
    {got.w, spans.s, &report, 1U, 1U, BD_SPREAD_MAX_WORKERS + 1U, WORDS, WORDS},
    {got.w, spans.s, &report, 1U, 1U, UINT32_MAX, WORDS, WORDS},
    {got.w, NULL, &report, 1U, 1U, 1U, WORDS, WORDS},
    {got.w, spans.s, &report, 2U, 1U, 1U, WORDS, 1U},
    {got.w, spans.s, &report, 1U, 1U, 1U, WORDS, 0U},
    {got.w, spans.s, NULL, 1U, 1U, 1U, WORDS, WORDS},
    {NULL, spans.s, &report, 1U, 1U, 1U, WORDS, WORDS},
    {got.w, spans.s, &report, 0U, 1U, 1U, WORDS, WORDS},
    {got.w, spans.s, &report, BD_SPREAD_MAX_TASKS + 1U, 1U, 1U, WORDS, WORDS},
    {got.w, spans.s, &report, 1U, 0U, 1U, WORDS, WORDS},
    {got.w, spans.s, &report, 1U, BD_SPREAD_MAX_STEPS + 1U, 1U, WORDS, WORDS},
    {got.w, spans.s, &report, 2U, 1U, 1U, 1U, WORDS},
};

/* 1 when the refused call returns BD_SPREAD_BAD_ARGUMENT and leaves every output unchanged. */
static unsigned int refused(const struct refusal *r) {
    mark_all();
    const int rc = bd_spread_trace(1U, r->tasks, r->steps, r->workers, r->out, r->out_len, r->spans,
                                   r->span_len, r->report);
    return AS_BIT(rc == BD_SPREAD_BAD_ARGUMENT) & marked_from(0U) & report_marked();
}

static void refusal_table(void) {
    const size_t count = sizeof refusals / sizeof *refusals;
    for (size_t index = 0U; index < count; ++index) {
        REQUIRE(refused(refusals + index));
    }
}

struct trace_case {
    uint64_t seed;
    uint32_t tasks;
    uint32_t steps;
    uint32_t workers;
};

static const struct trace_case traces[] = {
    {7U, 1U, 1U, 1U},
    {7U, 1U, 1U, 2U},
    {7U, 1U, 1U, 4U},
    {3U, BD_SPREAD_MAX_TASKS, 2000U, 1U},
    {3U, BD_SPREAD_MAX_TASKS, 2000U, 2U},
    {UINT64_MAX, BD_SPREAD_MAX_TASKS, 2000U, BD_SPREAD_MAX_WORKERS},
};

/* 1 when spans [0, tasks) name each task once, with thread tags below workers and start <= end.
 * The task bit is masked without a branch. */
static unsigned int complete_spans(uint32_t tasks, uint32_t workers) {
    unsigned int ok = 1U;
    uint64_t seen = 0U;
    for (uint32_t index = 0U; index < tasks; ++index) {
        const struct bd_spread_span *s = spans.s + index;
        const unsigned int in_range = AS_BIT(s->task < tasks);
        const uint64_t bit = (UINT64_C(1) << (s->task & 63U)) * in_range;
        ok &= in_range & AS_BIT((seen & bit) == 0U);
        ok &= AS_BIT(s->thread < workers) & AS_BIT(s->start_ns <= s->end_ns);
        seen |= bit;
    }
    const uint64_t all = tasks >= 64U ? UINT64_MAX : (UINT64_C(1) << tasks) - 1U;
    return ok & AS_BIT(seen == all);
}

/* 1 when one traced run gives the serial words, a complete trace and a complete report. */
static unsigned int traced(const struct trace_case *c) {
    mark_all();
    const uint32_t w = c->workers;
    const uint32_t n = c->tasks;
    const int serial_rc = bd_spread_run(c->seed, n, c->steps, 0U, serial.w, WORDS);
    struct bd_spread_span *s = spans.s;
    const int rc = bd_spread_trace(c->seed, n, c->steps, w, got.w, WORDS, s, WORDS, &report);
    unsigned int ok = AS_BIT(serial_rc == BD_SPREAD_OK) & AS_BIT(rc == BD_SPREAD_OK);
    ok &= AS_BIT(memcmp(got.w, serial.w, sizeof got.w) == 0) & marked_from(n);
    return ok & complete_spans(n, w);
}

/* 1 when the report of the last traced run of `c` is complete. */
static unsigned int complete_report(const struct trace_case *c) {
    const uint32_t w = c->workers;
    const uint32_t n = c->tasks;
    unsigned int ok = AS_BIT(report.submitted == n) & AS_BIT(report.executed == n);
    ok &= AS_BIT(report.threads >= 1U) & AS_BIT(report.threads <= w);
    return ok & AS_BIT(report.max_inflight >= 1U) & AS_BIT(report.max_inflight <= 2U * w);
}

static void trace_table(void) {
    const size_t count = sizeof traces / sizeof *traces;
    for (size_t index = 0U; index < count; ++index) {
        REQUIRE(traced(traces + index));
        REQUIRE(complete_report(traces + index));
    }
}

int main(void) {
    refusal_table();
    trace_table();
    puts("PASS bd_spread trace");
    return 0;
}
