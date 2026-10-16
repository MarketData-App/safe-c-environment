#ifndef SC_PARALLEL_H
#define SC_PARALLEL_H

#include <glib.h>

G_BEGIN_DECLS

/* Narrow batch adapter over an exclusive GThreadPool (spec 6, Amendment F item 2). The shared input
 * is immutable; each task writes only its own output slots, which the caller owns until
 * sc_parallel_run returns. No work survives the return; no partial success, no nesting, no
 * cancellation. */
#define SC_PARALLEL_MAX_WORKERS 8u
#define SC_PARALLEL_POLICY_MAX_WORKERS 4u
#define SC_PARALLEL_MAX_INFLIGHT 256u
#define SC_PARALLEL_MAX_TASKS ((gsize)65536)
#define SC_PARALLEL_NO_TAG G_MAXUINT
#define SC_PARALLEL_ERROR (sc_parallel_error_quark())

typedef enum {
    SC_PARALLEL_ERROR_CONFIG,
    SC_PARALLEL_ERROR_CREATE,
    SC_PARALLEL_ERROR_PUSH,
    SC_PARALLEL_ERROR_TASK,
    SC_PARALLEL_ERROR_ACCOUNTING
} ScParallelError;

typedef gboolean (*ScParallelTaskFn)(gconstpointer shared, gsize task_index, GError **error);

typedef struct {
    guint worker_count; /* 1..SC_PARALLEL_MAX_WORKERS */
    guint max_inflight; /* 1..SC_PARALLEL_MAX_INFLIGHT: queued + executing + not yet completed */
} ScParallelConfig;

typedef struct {
    guint thread_tag; /* 0..worker_count-1, or SC_PARALLEL_NO_TAG when the index did not execute */
    gint64 start_ns;  /* CLOCK_MONOTONIC; -1 when the index did not execute */
    gint64 end_ns;
    gint64 cpu_ns; /* CLOCK_THREAD_CPUTIME_ID of the pool thread in the task; -1 if not run */
    gsize task_index;
} ScParallelTraceEntry;

typedef struct {
    ScParallelTraceEntry *entries; /* caller-owned, capacity entries */
    gsize capacity;
    gsize used; /* min(capacity, submitted) after the run */
} ScParallelTrace;

typedef struct {
    gsize submitted;
    gsize executed;
    gsize skipped;
    guint threads_observed;
    gsize max_inflight_observed;
    ScParallelTrace *trace; /* optional, set by the caller before the run */
} ScParallelReport;

GQuark sc_parallel_error_quark(void);
G_GNUC_WARN_UNUSED_RESULT gboolean sc_parallel_run(const ScParallelConfig *config, gsize task_count,
                                                   ScParallelTaskFn task, gconstpointer shared,
                                                   ScParallelReport *report, GError **error);
void sc_parallel_set_task_error(GError **error, const gchar *message);

G_END_DECLS

#endif
