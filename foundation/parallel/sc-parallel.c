#define _GNU_SOURCE
#include "sc-parallel.h"

#include <time.h>

/* Set only while a task runs on a pool thread: a nested sc_parallel_run is refused. */
static _Thread_local gboolean in_task = FALSE;

typedef struct {
    GMutex lock;
    GCond changed;
    gsize inflight;
    gsize max_inflight_seen;
    gsize submitted;
    gsize executed;
    gsize skipped;
    gint stop;
    GError *first_error;
    ScParallelTaskFn task;
    gconstpointer shared;
    ScParallelTrace *trace;
    GThread *threads[SC_PARALLEL_MAX_WORKERS];
    guint thread_count;
} RunState;

GQuark sc_parallel_error_quark(void) { return g_quark_from_static_string("sc-parallel-error"); }

/* Every GError that this adapter creates (task errors included) is created under this one
 * process-wide lock, so no two threads create one through the adapter at the same time: GLib
 * starts its error-domain lock lazily on first use (finding P2-T14-TSAN-01). A static GMutex needs
 * no initialization. record_failure takes it inside the run lock; nothing takes them the other
 * way round. */
static GMutex error_lock;

static gboolean fail(GError **error, ScParallelError code, const gchar *message) {
    if (error != NULL && *error == NULL) {
        g_mutex_lock(&error_lock);
        g_set_error_literal(error, SC_PARALLEL_ERROR, (gint)code, message);
        g_mutex_unlock(&error_lock);
    }
    return FALSE;
}

void sc_parallel_set_task_error(GError **error, const gchar *message) {
    (void)fail(error, SC_PARALLEL_ERROR_TASK, message);
}

/* Branch-free (here and for cpu_ns below) so that the analyzer can merge the worker states:
 * the value of the clock when it is read, else -1. */
static gint64 clock_ns(clockid_t id) {
    struct timespec t = {0, 0};
    gint64 known = clock_gettime(id, &t) == 0;
    return known * ((gint64)t.tv_sec * G_GINT64_CONSTANT(1000000000) + (gint64)t.tv_nsec) +
           (known - 1);
}

/* Caller holds s->lock. */
static guint thread_tag(RunState *s) {
    GThread *self = g_thread_self();
    for (guint i = 0; i < s->thread_count; i++) {
        if (*(s->threads + i) == self) {
            return i;
        }
    }
    /* An exclusive pool has at most worker_count threads; the limit only bounds the table. */
    guint tag = s->thread_count < SC_PARALLEL_MAX_WORKERS ? s->thread_count : SC_PARALLEL_NO_TAG;
    if (tag != SC_PARALLEL_NO_TAG) {
        *(s->threads + tag) = self;
        s->thread_count++;
    }
    return tag;
}

/* Caller holds s->lock. Takes ownership of failure; a NULL failure becomes code and message.
 * Sets the stop flag and keeps only the first failure. */
static void record_failure(RunState *s, GError *failure, ScParallelError code,
                           const gchar *message) {
    g_atomic_int_set(&s->stop, 1);
    if (failure == NULL) {
        (void)fail(&failure, code, message);
    }
    if (s->first_error == NULL) {
        s->first_error = failure;
    } else {
        g_error_free(failure);
    }
}

static void sc_parallel_worker(gpointer item, gpointer user_data) {
    RunState *s = user_data;
    gsize index = GPOINTER_TO_SIZE(item) - 1u; /* items are index + 1: no per-task allocation */
    gboolean run = g_atomic_int_get(&s->stop) == 0;
    gboolean ok = TRUE;
    GError *local = NULL;
    gint64 start = clock_ns(CLOCK_MONOTONIC);
    gint64 cpu_start = clock_ns(CLOCK_THREAD_CPUTIME_ID);
    if (run) {
        in_task = TRUE;
        ok = s->task(s->shared, index, &local);
        in_task = FALSE;
    }
    gint64 cpu_end = clock_ns(CLOCK_THREAD_CPUTIME_ID);
    gint64 end = clock_ns(CLOCK_MONOTONIC);
    g_mutex_lock(&s->lock);
    if (run) {
        s->executed++;
        guint tag = thread_tag(s);
        if (s->trace != NULL && index < s->trace->capacity) {
            ScParallelTraceEntry *e = s->trace->entries + index;
            e->thread_tag = tag;
            e->start_ns = start;
            e->end_ns = end;
            gint64 measured = (cpu_start >= 0) & (cpu_end >= cpu_start);
            e->cpu_ns = measured * (cpu_end - cpu_start) + (measured - 1);
        }
        if (!ok || local != NULL) {
            record_failure(s, local, SC_PARALLEL_ERROR_TASK, "task failed without an error");
        }
    } else {
        s->skipped++;
    }
    s->inflight--;
    g_cond_broadcast(&s->changed);
    g_mutex_unlock(&s->lock);
}

static gboolean valid(const ScParallelConfig *config, gsize task_count, ScParallelTaskFn task,
                      const ScParallelTrace *trace, GError **error) {
    if (in_task) {
        return fail(error, SC_PARALLEL_ERROR_CONFIG, "nested submission");
    }
    if (config == NULL || task == NULL) {
        return fail(error, SC_PARALLEL_ERROR_CONFIG, "missing configuration or task");
    }
    if (config->worker_count == 0u || config->worker_count > SC_PARALLEL_MAX_WORKERS) {
        return fail(error, SC_PARALLEL_ERROR_CONFIG, "worker count outside 1-8");
    }
    if (config->max_inflight == 0u || config->max_inflight > SC_PARALLEL_MAX_INFLIGHT) {
        return fail(error, SC_PARALLEL_ERROR_CONFIG, "in-flight limit outside 1-256");
    }
    if (task_count == 0u || task_count > SC_PARALLEL_MAX_TASKS) {
        return fail(error, SC_PARALLEL_ERROR_CONFIG, "task count outside 1-65536");
    }
    if (trace != NULL && trace->capacity > 0u && trace->entries == NULL) {
        return fail(error, SC_PARALLEL_ERROR_CONFIG, "trace without storage");
    }
    return TRUE;
}

static void submit_all(RunState *s, GThreadPool *pool, const ScParallelConfig *config,
                       gsize task_count) {
    for (gsize i = 0; i < task_count; i++) {
        g_mutex_lock(&s->lock);
        while (s->inflight == config->max_inflight) {
            g_cond_wait(&s->changed, &s->lock);
        }
        gboolean stopped = g_atomic_int_get(&s->stop) != 0;
        if (!stopped) {
            s->inflight++;
            s->submitted++;
            /* inflight rose by one from at most max_inflight_seen: a branch-free maximum. */
            s->max_inflight_seen += (gsize)(s->inflight > s->max_inflight_seen);
        }
        g_mutex_unlock(&s->lock);
        if (stopped) {
            return;
        }
        GError *push_error = NULL;
        gboolean pushed = g_thread_pool_push(pool, GSIZE_TO_POINTER(i + 1u), &push_error);
        g_clear_error(&push_error);
        if (!pushed) {
            /* GLib may have queued the item although the push failed. The item owns nothing, so it
             * executes or is skipped and is counted either way; the run fails as a whole. */
            g_mutex_lock(&s->lock);
            record_failure(s, NULL, SC_PARALLEL_ERROR_PUSH, "thread pool push failed");
            g_mutex_unlock(&s->lock);
            return;
        }
    }
}

static gboolean run_pool(RunState *s, const ScParallelConfig *config, gsize task_count,
                         GError **error) {
    GError *create_error = NULL;
    GThreadPool *pool =
        g_thread_pool_new(sc_parallel_worker, s, (gint)config->worker_count, TRUE, &create_error);
    g_clear_error(&create_error);
    if (pool != NULL && g_thread_pool_get_num_threads(pool) != config->worker_count) {
        g_thread_pool_free(pool, FALSE, TRUE); /* safe drain: nothing was pushed */
        pool = NULL;
    }
    if (pool == NULL) {
        return fail(error, SC_PARALLEL_ERROR_CREATE, "thread pool creation failed or incomplete");
    }
    submit_all(s, pool, config, task_count);
    g_thread_pool_free(pool, FALSE, TRUE); /* waits for every queued item */
    g_mutex_lock(&s->lock);
    gboolean balanced = s->executed + s->skipped == s->submitted && s->inflight == 0u;
    g_mutex_unlock(&s->lock);
    if (!balanced) {
        g_clear_error(&s->first_error);
        return fail(error, SC_PARALLEL_ERROR_ACCOUNTING,
                    "executed plus skipped differs from submitted");
    }
    if (s->first_error != NULL) {
        g_propagate_error(error, s->first_error);
        s->first_error = NULL;
        return FALSE;
    }
    return TRUE;
}

/* Resets the caller-owned trace before the run: every entry reads as not executed. */
static void trace_reset(ScParallelTrace *trace) {
    if (trace != NULL) {
        trace->used = 0u;
        for (gsize i = 0; i < trace->capacity; i++) {
            ScParallelTraceEntry *e = trace->entries + i;
            e->thread_tag = SC_PARALLEL_NO_TAG;
            e->start_ns = -1;
            e->end_ns = -1;
            e->cpu_ns = -1;
            e->task_index = i;
        }
    }
}

/* Writes the accounting of s into the optional report and the used count of its trace. */
static void publish(ScParallelReport *report, const RunState *s) {
    if (report != NULL) {
        report->submitted = s->submitted;
        report->executed = s->executed;
        report->skipped = s->skipped;
        report->threads_observed = s->thread_count;
        report->max_inflight_observed = s->max_inflight_seen;
        if (s->trace != NULL) {
            s->trace->used = MIN(s->trace->capacity, s->submitted); /* the trace the run checked */
        }
    }
}

gboolean sc_parallel_run(const ScParallelConfig *config, gsize task_count, ScParallelTaskFn task,
                         gconstpointer shared, ScParallelReport *report, GError **error) {
    if (error != NULL && *error != NULL) {
        return FALSE; /* a pending error is never overwritten */
    }
    RunState s = {0};
    s.trace = report != NULL ? report->trace : NULL;
    if (!valid(config, task_count, task, s.trace, error)) {
        publish(report, &s); /* a refused run reports zero counts and an empty trace */
        return FALSE;
    }
    trace_reset(s.trace);
    g_mutex_init(&s.lock);
    g_cond_init(&s.changed);
    s.task = task;
    s.shared = shared;
    gboolean ok = run_pool(&s, config, task_count, error);
    publish(report, &s);
    g_cond_clear(&s.changed);
    g_mutex_clear(&s.lock);
    return ok;
}
