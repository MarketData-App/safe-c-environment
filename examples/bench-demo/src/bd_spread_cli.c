#include "bd_spread.h"

#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>

/* Program logic of bd-spread (specs/project/bd_spread.md): no argument, no input. The serial run,
 * then the traced pool runs on 1, 2 and 4 workers of one fixed job, each as a header line and one
 * line per span. No allocation, no global mutable state. */

enum { BD_SPREAD_CLI_USAGE = 2, BD_SPREAD_CLI_RUN = 3, BD_SPREAD_CLI_IO = 4 };

static const uint64_t cli_seed = UINT64_C(20261015);
static const uint32_t cli_workers[] = {1U, 2U, 4U};

/* The output line formats (string literals, so the compiler checks every format). */
#define SPAN "%" PRIu32 " %" PRIu64 " %" PRIu64 " %" PRIu32 " %" PRIu64 "\n"
#define HEAD_A "# workers=%" PRIu32 " threads=%" PRIu32 " max_inflight=%" PRIu64
#define HEAD_B " submitted=%" PRIu64 " executed=%" PRIu64 " result=%016" PRIx64 "\n"

/* The fold of the output words (FNV-1a 64 over the words). */
static uint64_t cli_fold(const uint64_t *words, uint32_t count) {
    uint64_t hash = UINT64_C(0xcbf29ce484222325);
    for (uint32_t index = 0U; index < count; ++index) {
        uint64_t product = 0U;
        (void)__builtin_mul_overflow(hash ^ *(words + index), UINT64_C(0x100000001b3), &product);
        hash = product;
    }
    return hash;
}

/* Writes the spans of one traced run; 1 when every line is written. */
static unsigned int cli_spans(FILE *out, const struct bd_spread_span *spans, uint32_t count) {
    unsigned int ok = 1U;
    for (uint32_t index = 0U; index < count; ++index) {
        const struct bd_spread_span *s = spans + index;
        const int put = fprintf(out, SPAN, s->thread, s->start_ns, s->end_ns, s->task, s->cpu_ns);
        ok &= (unsigned int)(put > 0);
    }
    return ok;
}

/* One traced run on `workers` workers: its header and spans. Returns 0, BD_SPREAD_CLI_RUN or
 * BD_SPREAD_CLI_IO. */
static int cli_traced(FILE *out, uint32_t workers, uint64_t *words) {
    struct bd_spread_span spans[BD_SPREAD_MAX_TASKS] = {0};
    struct bd_spread_report rep = {0U, 0U, 0U, 0U};
    const uint32_t tasks = (uint32_t)BD_SPREAD_MAX_TASKS;
    const uint32_t steps = (uint32_t)BD_SPREAD_TRACE_STEPS;
    const size_t len = (size_t)tasks;
    const int rc = bd_spread_trace(cli_seed, tasks, steps, workers, words, len, spans, len, &rep);
    if (rc != BD_SPREAD_OK) {
        (void)fprintf(out, "# status=FAIL\n");
        return BD_SPREAD_CLI_RUN;
    }
    const uint64_t result = cli_fold(words, tasks);
    const int put_a = fprintf(out, HEAD_A, workers, rep.threads, rep.max_inflight);
    const int put_b = fprintf(out, HEAD_B, rep.submitted, rep.executed, result);
    const unsigned int head = (unsigned int)(put_a > 0) & (unsigned int)(put_b > 0);
    const unsigned int ok = head & cli_spans(out, spans, tasks);
    return ok != 0U ? 0 : BD_SPREAD_CLI_IO;
}

int bd_spread_cli_main(int argc, char **argv, FILE *out, FILE *err) {
    if (argc != 1 || argv == NULL) {
        (void)fputs("usage: bd-spread\n", err);
        return BD_SPREAD_CLI_USAGE;
    }
    uint64_t words[BD_SPREAD_MAX_TASKS] = {0};
    const uint32_t tasks = (uint32_t)BD_SPREAD_MAX_TASKS;
    const uint32_t steps = (uint32_t)BD_SPREAD_TRACE_STEPS;
    if (bd_spread_run(cli_seed, tasks, steps, 0U, words, (size_t)tasks) != BD_SPREAD_OK) {
        (void)fprintf(out, "# status=FAIL\n");
        return BD_SPREAD_CLI_RUN;
    }
    if (fprintf(out, "# workers=0 result=%016" PRIx64 "\n", cli_fold(words, tasks)) <= 0) {
        return BD_SPREAD_CLI_IO;
    }
    const size_t runs = sizeof cli_workers / sizeof *cli_workers;
    for (size_t index = 0U; index < runs; ++index) {
        const int rc = cli_traced(out, *(cli_workers + index), words);
        if (rc != 0) {
            return rc;
        }
    }
    return fflush(out) == 0 ? 0 : BD_SPREAD_CLI_IO;
}
