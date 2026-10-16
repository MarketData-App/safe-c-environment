#ifndef SC_PARALLEL_CHECKS_H
#define SC_PARALLEL_CHECKS_H
/* Loop-based checks of the parallel contract test, in their own translation unit so that the
 * analyzer of contracts.c treats them as single calls rather than one loop per call site. */
#include "sc-parallel.h"

#include <sys/types.h>

#define CHECK_TASKS 512u

/* Zeroes the per-index hit counters and returns them (CHECK_TASKS entries). */
guint *checks_hits_reset(void);
/* The sum of all hit counters. */
guint checks_hits_total(void);
/* TRUE when every hit counter equals value. */
gboolean checks_hits_all(guint value);
/* TRUE when entries 0..used-1 are in index order, ran on a tag below workers, have ordered
 * non-negative times and CPU time, and neither started nor ended after returned. */
/* The largest number of entries 0..used-1 whose [start_ns, end_ns) interval contains the start
 * of one of them: the most tasks that ran at the same time. */
gsize checks_trace_max_overlap(const ScParallelTraceEntry *entries, gsize used);
gboolean checks_trace_entries(const ScParallelTraceEntry *entries, gsize used, guint workers,
                              gint64 returned);
/* TRUE when error is not NULL and its message is exactly the first length bytes of text. */
gboolean checks_message_is(const GError *error, const gchar *text, gsize length);
/* TRUE when error is not NULL and its message equals one of messages 0..count-1. */
gboolean checks_message_in(const GError *error, const gchar *const *messages, gsize count);

/* The standard error capture of a window (one at a time). checks_capture_begin sends standard
 * error to a pipe whose bytes go to the descriptor out; FALSE when a step fails. Call
 * checks_capture_end after every checks_capture_begin, also a failed one: it restores standard
 * error, sets *logged to TRUE when any byte arrived (or the capture could not tell) and returns
 * FALSE when standard error was not redirected and restored or a step of the capture failed. */
gboolean checks_capture_begin(int out);
gboolean checks_capture_end(gboolean *logged);

/* The text that checks_capture_end writes to the saved standard error when it cannot restore
 * standard error; later diagnostics of the process are lost (finding S2-04). */
#define CHECKS_RESTORE_MARKER "parallel checks: stderr restore failed; later output is lost\n"
/* Test-only faults of the next checks_capture_end (finding S2-04): with wait_eintr its first wait
 * for the drain child fails with EINTR; with restore_fails its restore of standard error fails.
 * Each fault applies once. */
void checks_capture_inject(gboolean wait_eintr, gboolean restore_fails);
/* waitpid(child, status, 0) for a child of the capture boundary, retried while it fails with
 * EINTR; after checks_capture_inject(TRUE, ...) its first attempt fails with EINTR. */
pid_t checks_wait(pid_t child, int *status);
#endif
