#define _GNU_SOURCE
#include "checks.h"
#include "sc-parallel.h"

#include <stdio.h>
#include <time.h>

/* Simulated sc_parallel lifecycle faults: the same sc-parallel.c source, linked against the
 * static GLib archive with --wrap of three pool calls (ordinary unsanitized test link only).
 * Errors are created through sc_parallel_set_task_error, so this file needs no GLib grant. The
 * hit counters of checks.c keep the loops out of this translation unit (gcc analyzer). */

GThreadPool *__real_g_thread_pool_new(GFunc func, gpointer data, gint max_threads,
                                      gboolean exclusive, GError **error);
gboolean __real_g_thread_pool_push(GThreadPool *pool, gpointer data, GError **error);
guint __real_g_thread_pool_get_num_threads(GThreadPool *pool);
GThreadPool *__wrap_g_thread_pool_new(GFunc func, gpointer data, gint max_threads,
                                      gboolean exclusive, GError **error);
gboolean __wrap_g_thread_pool_push(GThreadPool *pool, gpointer data, GError **error);
guint __wrap_g_thread_pool_get_num_threads(GThreadPool *pool);

#define FAULT_TASKS 64u
_Static_assert(FAULT_TASKS <= CHECK_TASKS, "the hit counters cover every task");

typedef enum { FAULT_NONE, FAULT_CREATE, FAULT_INCOMPLETE, FAULT_PUSH_AFTER_QUEUE } Fault;
/* Touched only by the submitting thread (pool creation and pushes run there). */
static Fault fault = FAULT_NONE;
static gsize pushes = 0u;

GThreadPool *__wrap_g_thread_pool_new(GFunc func, gpointer data, gint max_threads,
                                      gboolean exclusive, GError **error) {
    if (fault == FAULT_CREATE) {
        sc_parallel_set_task_error(error, "simulated creation failure");
        return NULL;
    }
    return __real_g_thread_pool_new(func, data, max_threads, exclusive, error);
}

guint __wrap_g_thread_pool_get_num_threads(GThreadPool *pool) {
    guint n = __real_g_thread_pool_get_num_threads(pool);
    return fault == FAULT_INCOMPLETE && n > 0u ? n - 1u : n;
}

gboolean __wrap_g_thread_pool_push(GThreadPool *pool, gpointer data, GError **error) {
    gboolean queued = __real_g_thread_pool_push(pool, data, error);
    pushes++;
    if (fault == FAULT_PUSH_AFTER_QUEUE && pushes == 5u) {
        sc_parallel_set_task_error(error, "simulated push error after queueing");
        return FALSE; /* the item is queued: the GLib push-error contract */
    }
    return queued;
}

/* Set by the submitting thread before each run; a task writes only its own index. */
static guint *executed_tasks = NULL;

static gboolean task(gconstpointer shared, gsize index, GError **error) {
    (void)shared;
    (void)error;
    struct timespec t = {0, 200000};
    (void)nanosleep(&t, NULL);
    *(executed_tasks + index) += 1u;
    return TRUE;
}

static gboolean scenario(Fault f, ScParallelError expected, gsize expected_submitted) {
    executed_tasks = checks_hits_reset();
    fault = f;
    pushes = 0u;
    ScParallelConfig config = {2u, 4u};
    ScParallelReport report = {0};
    GError *error = NULL;
    gboolean ran = sc_parallel_run(&config, FAULT_TASKS, task, NULL, &report, &error);
    fault = FAULT_NONE;
    gboolean matched = g_error_matches(error, SC_PARALLEL_ERROR, (gint)expected);
    g_clear_error(&error);
    guint after = checks_hits_total();
    struct timespec t = {0, 20000000};
    (void)nanosleep(&t, NULL);
    gboolean counted = report.submitted == expected_submitted &&
                       report.executed + report.skipped == report.submitted;
    /* No task ran after the return. */
    gboolean settled = report.executed == after && after == checks_hits_total();
    return !ran && matched && counted && settled;
}

int main(void) {
    gboolean create = scenario(FAULT_CREATE, SC_PARALLEL_ERROR_CREATE, 0u);
    gboolean incomplete = scenario(FAULT_INCOMPLETE, SC_PARALLEL_ERROR_CREATE, 0u);
    gboolean push = scenario(FAULT_PUSH_AFTER_QUEUE, SC_PARALLEL_ERROR_PUSH, 5u);
    printf("LABEL simulated\n");
    printf("%s create\n", create ? "PARALLEL_FAULT_PASS" : "PARALLEL_FAULT_FAIL");
    printf("%s incomplete\n", incomplete ? "PARALLEL_FAULT_PASS" : "PARALLEL_FAULT_FAIL");
    printf("%s push-after-queue\n", push ? "PARALLEL_FAULT_PASS" : "PARALLEL_FAULT_FAIL");
    return create && incomplete && push ? 0 : 1;
}
