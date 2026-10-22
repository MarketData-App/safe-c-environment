#include "bd_spread.h"

#include <sc-parallel.h>

/* The threaded coverage fixture and the traced pool run (specs/project/bd_spread.md). The job is
 * read-only for the tasks; each task writes only its own output word. No task sets a GError. */

struct bd_spread_job {
    uint64_t seed;
    uint32_t steps;
    uint64_t *out;
};

/* The product modulo 2^64: __builtin_mul_overflow stores the wrapped value, and its overflow
 * flag is not an error here. A plain multiplication would trap the integer gate's
 * unsigned-integer-overflow check. */
static uint64_t bd_spread_mul(uint64_t a, uint64_t b) {
    uint64_t product = 0U;
    (void)__builtin_mul_overflow(a, b, &product);
    return product;
}

static uint64_t bd_spread_digest(uint64_t seed, uint64_t task, uint32_t steps) {
    uint64_t state = seed ^ bd_spread_mul(task, UINT64_C(0x9e3779b97f4a7c15));
    if (state == 0U) {
        state = UINT64_C(0x9e3779b97f4a7c15);
    }
    uint64_t hash = UINT64_C(0xcbf29ce484222325);
    for (uint32_t step = 0U; step < steps; ++step) {
        state ^= state << 13U;
        state ^= state >> 7U;
        state ^= state << 17U;
        if (step + 1U != steps) {
            hash = bd_spread_mul(hash ^ state, UINT64_C(0x100000001b3));
        } else {
            hash = bd_spread_mul(hash ^ state ^ task, UINT64_C(0x100000001b3));
        }
    }
    return hash;
}

static gboolean bd_spread_task(gconstpointer shared, gsize task_index, GError **error) {
    (void)error; /* no GError from a pool thread */
    const struct bd_spread_job *job = shared;
    *(job->out + task_index) = bd_spread_digest(job->seed, (uint64_t)task_index, job->steps);
    return TRUE;
}

static int bd_spread_args_ok(uint32_t tasks, uint32_t steps, uint32_t workers, const uint64_t *out,
                             size_t out_len) {
    if (out == NULL) {
        return 0;
    }
    if (tasks == 0U || tasks > (uint32_t)BD_SPREAD_MAX_TASKS) {
        return 0;
    }
    if (steps == 0U || steps > (uint32_t)BD_SPREAD_MAX_STEPS) {
        return 0;
    }
    if (workers > (uint32_t)BD_SPREAD_MAX_WORKERS) {
        return 0;
    }
    return out_len >= (size_t)tasks;
}

int bd_spread_run(uint64_t seed, uint32_t tasks, uint32_t steps, uint32_t workers, uint64_t *out,
                  size_t out_len) {
    if (!bd_spread_args_ok(tasks, steps, workers, out, out_len)) {
        return BD_SPREAD_BAD_ARGUMENT;
    }
    if (workers == 0U) {
        for (uint32_t task = 0U; task < tasks; ++task) {
            *(out + task) = bd_spread_digest(seed, (uint64_t)task, steps);
        }
        return BD_SPREAD_OK;
    }
    const struct bd_spread_job job = {seed, steps, out};
    const ScParallelConfig config = {workers, 2U * workers};
    ScParallelReport report = {0U, 0U, 0U, 0U, 0U, NULL};
    const gsize count = (gsize)tasks;
    GError *error = NULL;
    const gboolean ok = sc_parallel_run(&config, count, bd_spread_task, &job, &report, &error);
    g_clear_error(&error);
    return ok ? BD_SPREAD_OK : BD_SPREAD_POOL;
}

/* 1 when every entry of the pool trace ran, has values in range and names each task index in
 * [0, tasks) exactly once. Conditions are combined without branches. */
static unsigned int bd_spread_trace_ok(const ScParallelTraceEntry *entries, uint32_t tasks,
                                       uint32_t workers) {
    unsigned int ok = 1U;
    uint64_t seen = 0U;
    for (uint32_t index = 0U; index < tasks; ++index) {
        const ScParallelTraceEntry *e = entries + index;
        const unsigned int in_range = (unsigned int)(e->task_index < (gsize)tasks);
        const uint64_t bit = in_range != 0U ? (UINT64_C(1) << e->task_index) : 0U;
        ok &= in_range & (unsigned int)((seen & bit) == 0U);
        ok &= (unsigned int)(e->thread_tag < workers);
        ok &= (unsigned int)(e->start_ns >= 0) & (unsigned int)(e->end_ns >= e->start_ns);
        ok &= (unsigned int)(e->cpu_ns >= 0);
        seen |= bit;
    }
    const uint64_t all = tasks == 64U ? UINT64_MAX : (UINT64_C(1) << tasks) - 1U;
    return ok & (unsigned int)(seen == all);
}

/* 1 when the pool report of a traced run of `tasks` tasks on `workers` workers is complete. */
static unsigned int bd_spread_report_ok(const ScParallelReport *r, const ScParallelTrace *trace,
                                        uint32_t tasks, uint32_t workers) {
    const gsize count = (gsize)tasks;
    const gsize window = (gsize)(2U * workers);
    unsigned int ok = (unsigned int)(r->submitted == count) & (unsigned int)(r->executed == count);
    ok &= (unsigned int)(r->skipped == 0U) & (unsigned int)(trace->used == count);
    ok &= (unsigned int)(r->threads_observed >= 1U);
    ok &= (unsigned int)(r->threads_observed <= workers);
    ok &= (unsigned int)(r->max_inflight_observed >= 1U);
    ok &= (unsigned int)(r->max_inflight_observed <= window);
    return ok;
}

int bd_spread_trace(uint64_t seed, uint32_t tasks, uint32_t steps, uint32_t workers, uint64_t *out,
                    size_t out_len, struct bd_spread_span *spans, size_t span_len,
                    struct bd_spread_report *report) {
    if (!bd_spread_args_ok(tasks, steps, workers, out, out_len)) {
        return BD_SPREAD_BAD_ARGUMENT;
    }
    if (workers == 0U || spans == NULL || span_len < (size_t)tasks || report == NULL) {
        return BD_SPREAD_BAD_ARGUMENT;
    }
    ScParallelTraceEntry entries[BD_SPREAD_MAX_TASKS] = {0};
    ScParallelTrace trace = {entries, (gsize)tasks, 0U};
    const struct bd_spread_job job = {seed, steps, out};
    const ScParallelConfig config = {workers, 2U * workers};
    ScParallelReport pool = {0U, 0U, 0U, 0U, 0U, &trace};
    GError *error = NULL;
    const gsize count = (gsize)tasks;
    const gboolean ran = sc_parallel_run(&config, count, bd_spread_task, &job, &pool, &error);
    g_clear_error(&error);
    const unsigned int report_ok = bd_spread_report_ok(&pool, &trace, tasks, workers);
    const unsigned int trace_ok = bd_spread_trace_ok(entries, tasks, workers);
    if (!ran || (report_ok & trace_ok) == 0U) {
        return BD_SPREAD_POOL;
    }
    for (uint32_t index = 0U; index < tasks; ++index) {
        const ScParallelTraceEntry *e = entries + index;
        struct bd_spread_span *s = spans + index;
        s->start_ns = (uint64_t)e->start_ns;
        s->end_ns = (uint64_t)e->end_ns;
        s->cpu_ns = (uint64_t)e->cpu_ns;
        s->thread = (uint32_t)e->thread_tag;
        s->task = (uint32_t)e->task_index;
    }
    report->submitted = (uint64_t)pool.submitted;
    report->executed = (uint64_t)pool.executed;
    report->max_inflight = (uint64_t)pool.max_inflight_observed;
    report->threads = (uint32_t)pool.threads_observed;
    return BD_SPREAD_OK;
}
