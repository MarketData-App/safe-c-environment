#define _GNU_SOURCE
#include "checks.h"
#include "sc-parallel.h"

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#define TASKS CHECK_TASKS
#define TRACE_ENTRIES 64u

typedef struct {
    guint *hits;
    gsize fail_at;
    gboolean fail_silently;
    long sleep_ns;
    gboolean nest;
} Shared;

/* The shared input of a run larger than hits: each task only checks its index. */
typedef struct {
    gsize limit;
} Bound;

static void pause_ns(long ns) {
    struct timespec t = {0, ns};
    (void)nanosleep(&t, NULL);
}

static gint64 monotonic_ns(void) {
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC, &t) != 0) {
        return G_MAXINT64; /* makes the trace check fail rather than pass */
    }
    return (gint64)t.tv_sec * G_GINT64_CONSTANT(1000000000) + (gint64)t.tv_nsec;
}

static gboolean task(gconstpointer data, gsize index, GError **error) {
    const Shared *s = data;
    if (s->sleep_ns > 0) {
        pause_ns(s->sleep_ns);
    }
    if (s->nest) {
        ScParallelConfig inner = {1u, 1u};
        GError *nested = NULL;
        gboolean ran = sc_parallel_run(&inner, 1u, task, data, NULL, &nested);
        gboolean refused =
            !ran && g_error_matches(nested, SC_PARALLEL_ERROR, SC_PARALLEL_ERROR_CONFIG);
        g_clear_error(&nested);
        if (!refused) {
            sc_parallel_set_task_error(error, "nested submission accepted");
            return FALSE;
        }
    }
    *(s->hits + index) += 1u;
    if (index == s->fail_at) {
        if (!s->fail_silently) {
            sc_parallel_set_task_error(error, "seeded task failure");
        }
        return FALSE;
    }
    return TRUE;
}

static gboolean bounded_task(gconstpointer data, gsize index, GError **error) {
    const Bound *b = data;
    if (index >= b->limit) {
        sc_parallel_set_task_error(error, "index outside the submitted range");
        return FALSE;
    }
    return TRUE;
}

/* Reports success but sets an error: the run still fails. */
static gboolean error_but_true_task(gconstpointer data, gsize index, GError **error) {
    (void)data;
    if (index == 0u) {
        sc_parallel_set_task_error(error, "error with a true result");
        sc_parallel_set_task_error(error, "a second error never overwrites the first");
    }
    return TRUE;
}

/* Both tasks of a two-worker run start before either fails: two failures, one kept. */
static gboolean slow_failure_task(gconstpointer data, gsize index, GError **error) {
    (void)data;
    (void)index;
    pause_ns(50000000);
    sc_parallel_set_task_error(error, "concurrent seeded failure");
    return FALSE;
}

/* Race group: one run of RACE_TASKS tasks on RACE_TASKS workers (all items queued at once). The
 * failing index sleeps RACE_FAIL_NS and then fails. Each sibling index only passes its stop check,
 * then sleeps RACE_SIBLING_NS without a GLib call, a lock or an error, so it releases nothing
 * between its stop read and the failing write (the write comes first: its sleep is shorter). Its
 * stop read and that write therefore have no happens-before edge in either direction: only the
 * atomic stop flag keeps them race-free, which ThreadSanitizer checks on every run. */
#define RACE_TASKS 4u
#define RACE_FAIL_NS 20000000L
#define RACE_SIBLING_NS 80000000L

typedef struct {
    gsize fail_at;
} Race;

static gboolean race_task(gconstpointer data, gsize index, GError **error) {
    const Race *r = data;
    if (index == r->fail_at) {
        pause_ns(RACE_FAIL_NS);
        sc_parallel_set_task_error(error, "seeded failure while the siblings run");
        return FALSE;
    }
    pause_ns(RACE_SIBLING_NS);
    return TRUE;
}

/* Concurrent-failure group (finding P2-T14-TSAN-01): one run of n tasks on n workers (all items
 * queued at once). Every task waits for one common CLOCK_MONOTONIC deadline and then reports its
 * own failure, so the failures of the pool threads overlap. main runs this group first: these
 * failures create the first GError of the process (the GLib error-domain lock starts lazily, and
 * ThreadSanitizer sees that race only when two first creations overlap: a timing window, so this
 * is a chance detector). The contract check: after sc_parallel_set_task_error each task's own
 * error argument holds its own error (domain, code and message). */
#define CONCURRENT_MAX 8u
#define CONCURRENT_DELAY_NS 50000000L

typedef struct {
    struct timespec deadline;
    guint *own; /* per index: 1 when the error argument holds the task's own error */
} Concurrent;

static const gchar *const concurrent_messages[CONCURRENT_MAX] = {
    "concurrent failure 0", "concurrent failure 1", "concurrent failure 2", "concurrent failure 3",
    "concurrent failure 4", "concurrent failure 5", "concurrent failure 6", "concurrent failure 7",
};

static gboolean concurrent_task(gconstpointer data, gsize index, GError **error) {
    const Concurrent *c = data;
    (void)clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &c->deadline, NULL);
    sc_parallel_set_task_error(error, *(concurrent_messages + index));
    *(c->own + index) +=
        (guint)(g_error_matches(*error, SC_PARALLEL_ERROR, SC_PARALLEL_ERROR_TASK) &
                checks_message_in(*error, concurrent_messages + index, 1u));
    return FALSE;
}

/* Error group: the standard GError contract of sc_parallel_set_task_error in a task. */

/* Two reports with a true result: the first message is kept. */
static gboolean twice_task(gconstpointer data, gsize index, GError **error) {
    (void)data;
    (void)index;
    sc_parallel_set_task_error(error, "the first message");
    sc_parallel_set_task_error(error, "a second message");
    return TRUE;
}

/* A set error argument is never overwritten. */
static gboolean own_error_task(gconstpointer data, gsize index, GError **error) {
    (void)data;
    (void)index;
    GError *own = NULL;
    sc_parallel_set_task_error(&own, "the own error of the task");
    *error = own;
    sc_parallel_set_task_error(error, "a recorded message");
    return FALSE;
}

/* Any other receiver gets the error at once; an omitted receiver gets nothing. */
static gboolean private_error_task(gconstpointer data, gsize index, GError **error) {
    (void)data;
    (void)index;
    (void)error;
    GError *mine = NULL;
    sc_parallel_set_task_error(&mine, "a private error of the task");
    sc_parallel_set_task_error(NULL, "an omitted receiver");
    gboolean set = g_error_matches(mine, SC_PARALLEL_ERROR, SC_PARALLEL_ERROR_TASK);
    g_clear_error(&mine);
    return set;
}

static Shared fresh(void) {
    Shared s = {checks_hits_reset(), G_MAXSIZE, FALSE, 0, FALSE};
    return s;
}

static guint total(void) { return checks_hits_total(); }

/* The checks below combine results with the non-short-circuit & so that every check runs and
 * the analyzer explores one path per check rather than one per combination of outcomes. Each
 * run is its own statement: the operands of & are unsequenced. */
static gboolean refused(const ScParallelConfig *config, gsize count, gboolean with_task) {
    Shared s = fresh();
    GError *error = NULL;
    gboolean ran = sc_parallel_run(config, count, with_task ? task : NULL, &s, NULL, &error);
    gboolean ok = g_error_matches(error, SC_PARALLEL_ERROR, SC_PARALLEL_ERROR_CONFIG) &
                  (ran == FALSE) & (total() == 0u);
    g_clear_error(&error);
    return ok;
}

static gboolean trace_storage(void) {
    ScParallelConfig ok = {1u, 1u};
    ScParallelTrace missing = {NULL, 4u, 7u};
    ScParallelReport report = {0};
    report.trace = &missing;
    Shared s = fresh();
    GError *error = NULL;
    gboolean ran = sc_parallel_run(&ok, 1u, task, &s, &report, &error);
    gboolean pass = g_error_matches(error, SC_PARALLEL_ERROR, SC_PARALLEL_ERROR_CONFIG) &
                    (ran == FALSE) & (total() == 0u) & (missing.used == 0u);
    g_clear_error(&error);
    ScParallelTrace empty = {NULL, 0u, 7u};
    report.trace = &empty;
    s = fresh();
    ran = sc_parallel_run(&ok, 2u, task, &s, &report, &error);
    pass &= ran & (error == NULL) & (empty.used == 0u) & (total() == 2u);
    g_clear_error(&error);
    return pass;
}

typedef struct {
    const ScParallelConfig *config;
    gsize count;
    gboolean with_task;
} Refusal;

static const ScParallelConfig zero = {0u, 1u}, nine = {9u, 1u}, no_window = {1u, 0u};
static const ScParallelConfig wide = {1u, 257u}, one = {1u, 1u};

/* Zero, one-past and missing arguments; one table so that one call site covers all rows. */
static const Refusal refusals[] = {
    {&zero, 1u, TRUE}, {&nine, 1u, TRUE},    {&no_window, 1u, TRUE}, {&wide, 1u, TRUE},
    {&one, 0u, TRUE},  {&one, 65537u, TRUE}, {&one, 1u, FALSE},      {NULL, 1u, TRUE},
};

static gboolean config_bounds(void) {
    ScParallelConfig ok = {1u, 1u}, max_ok = {8u, 256u};
    gboolean pass = TRUE;
    for (gsize i = 0; i < sizeof refusals / sizeof *refusals; i++) {
        const Refusal *r = refusals + i;
        pass &= refused(r->config, r->count, r->with_task);
    }
    /* The largest accepted run: its shared input is a bound, never the 512-entry hits. */
    Bound bound = {SC_PARALLEL_MAX_TASKS};
    ScParallelReport report = {0};
    GError *error = NULL;
    gboolean ran =
        sc_parallel_run(&max_ok, SC_PARALLEL_MAX_TASKS, bounded_task, &bound, &report, &error);
    pass &= ran & (error == NULL) & (report.submitted == SC_PARALLEL_MAX_TASKS) &
            (report.executed == SC_PARALLEL_MAX_TASKS) & (report.skipped == 0u) &
            (report.threads_observed >= 1u) & (report.threads_observed <= 8u) &
            (report.max_inflight_observed <= 256u);
    g_clear_error(&error);
    Shared s = fresh();
    GError *pending = NULL;
    sc_parallel_set_task_error(&pending, "pending");
    GError *kept = pending;
    ran = sc_parallel_run(&ok, 1u, task, &s, NULL, &pending);
    pass &= (total() == 0u) & (ran == FALSE) & (pending == kept);
    g_clear_error(&pending);
    /* An omitted error receiver does not change the status. */
    s = fresh();
    ran = sc_parallel_run(&zero, 1u, task, &s, NULL, NULL);
    pass &= (total() == 0u) & (ran == FALSE);
    s = fresh();
    ran = sc_parallel_run(&ok, 3u, task, &s, NULL, NULL);
    pass &= ran & (total() == 3u);
    return pass & trace_storage();
}

static gboolean execution_with(guint workers) {
    Shared s = fresh();
    ScParallelConfig config = {workers, 2u * workers};
    ScParallelReport report = {0};
    GError *error = NULL;
    gboolean ran = sc_parallel_run(&config, TASKS, task, &s, &report, &error);
    gboolean ok = ran & (error == NULL);
    g_clear_error(&error);
    ok &= checks_hits_all(1u);
    return ok & (report.submitted == TASKS) & (report.executed == TASKS) & (report.skipped == 0u) &
           (report.threads_observed >= 1u) & (report.threads_observed <= workers);
}

static gboolean execution(void) {
    gboolean ok = TRUE;
    for (guint workers = 1u; workers <= SC_PARALLEL_MAX_WORKERS; workers *= 2u) {
        ok &= execution_with(workers); /* 1, 2, 4 and 8 workers */
    }
    return ok;
}

static gboolean admission_with(guint window) {
    Shared s = fresh();
    s.sleep_ns = 200000;
    ScParallelTraceEntry entries[TRACE_ENTRIES];
    ScParallelTrace t = {entries, TRACE_ENTRIES, 0u};
    ScParallelConfig config = {4u, window};
    ScParallelReport report = {0};
    report.trace = &t;
    GError *error = NULL;
    gboolean ok = sc_parallel_run(&config, TRACE_ENTRIES, task, &s, &report, &error);
    g_clear_error(&error);
    /* The trace, independent of the adapter's counter: at most window tasks overlap. */
    gsize overlap = checks_trace_max_overlap(entries, t.used);
    return ok & (t.used == TRACE_ENTRIES) & (overlap >= 1u) & (overlap <= window) &
           (report.max_inflight_observed >= 1u) & (report.max_inflight_observed <= window);
}

static gboolean admission(void) { return admission_with(1u) & admission_with(3u); }

static gboolean one_failure(gboolean silently) {
    Shared s = fresh();
    s.fail_at = 37u;
    s.fail_silently = silently;
    s.sleep_ns = 100000;
    /* One worker runs the items in order: while task 37 runs, at most 7 more are queued, and the
     * stop is set before its slot frees, so at most 37 + 8 items are submitted whatever the
     * timing. */
    ScParallelConfig config = {1u, 8u};
    ScParallelReport report = {0};
    GError *error = NULL;
    gboolean ran = sc_parallel_run(&config, TASKS, task, &s, &report, &error);
    gboolean ok =
        g_error_matches(error, SC_PARALLEL_ERROR, SC_PARALLEL_ERROR_TASK) & (ran == FALSE);
    g_clear_error(&error);
    guint after = total();
    ok &= (report.executed + report.skipped == report.submitted) & (report.executed == after) &
          (report.submitted <= 45u);
    pause_ns(20000000); /* no task runs after the return: the count stays */
    return ok & (after == total());
}

/* least..most executed: a run may skip an item that starts after the first failure. */
static gboolean failure_with(ScParallelTaskFn fn, guint workers, gsize count, gsize least,
                             gsize most) {
    ScParallelConfig config = {workers, workers};
    ScParallelReport report = {0};
    GError *error = NULL;
    gboolean ran = sc_parallel_run(&config, count, fn, NULL, &report, &error);
    gboolean ok =
        g_error_matches(error, SC_PARALLEL_ERROR, SC_PARALLEL_ERROR_TASK) & (ran == FALSE);
    g_clear_error(&error);
    return ok & (report.executed >= least) & (report.executed <= most) &
           (report.executed + report.skipped == report.submitted);
}

static gboolean errors(void) {
    gboolean ok = TRUE;
    for (gboolean silently = FALSE; silently <= TRUE; silently++) {
        ok &= one_failure(silently);
    }
    return ok & failure_with(error_but_true_task, 1u, 1u, 1u, 1u) &
           failure_with(slow_failure_task, 2u, 4u, 1u, 2u);
}

static gboolean trace_with(gsize capacity) {
    Shared s = fresh();
    s.sleep_ns = 100000;
    ScParallelTraceEntry entries[TRACE_ENTRIES];
    ScParallelTrace t = {entries, capacity, 0u};
    ScParallelConfig config = {2u, 4u};
    ScParallelReport report = {0};
    report.trace = &t;
    GError *error = NULL;
    gboolean ran = sc_parallel_run(&config, TRACE_ENTRIES, task, &s, &report, &error);
    gboolean ok = ran & (t.used == capacity) & (total() == TRACE_ENTRIES);
    gint64 returned = monotonic_ns(); /* the same clock as the trace (CLOCK_MONOTONIC) */
    g_clear_error(&error);
    ok &= checks_trace_entries(entries, t.used, 2u, returned);
    return ok;
}

static gboolean trace(void) {
    gboolean ok = TRUE;
    for (gsize capacity = 8u; capacity <= TRACE_ENTRIES; capacity *= 8u) {
        ok &= trace_with(capacity); /* a trace shorter than the run, then one entry per task */
    }
    return ok;
}

static gboolean nesting(void) {
    Shared s = fresh();
    s.nest = TRUE;
    ScParallelConfig config = {2u, 2u};
    GError *error = NULL;
    gboolean ran = sc_parallel_run(&config, 8u, task, &s, NULL, &error);
    gboolean ok = ran & (total() == 8u);
    g_clear_error(&error);
    return ok;
}

static gboolean race_once(gsize fail_at) {
    Race r = {fail_at};
    ScParallelConfig config = {RACE_TASKS, RACE_TASKS};
    ScParallelReport report = {0};
    GError *error = NULL;
    gboolean ran = sc_parallel_run(&config, RACE_TASKS, race_task, &r, &report, &error);
    gboolean ok =
        g_error_matches(error, SC_PARALLEL_ERROR, SC_PARALLEL_ERROR_TASK) & (ran == FALSE);
    g_clear_error(&error);
    return ok & (report.submitted >= 1u) & (report.submitted <= RACE_TASKS) &
           (report.executed >= 1u) & (report.executed + report.skipped == report.submitted);
}

/* The failing task at each index of the run: first, middle and last position in the queue. */
static gboolean race(void) {
    gboolean ok = race_once(0u);
    ok &= race_once(1u);
    ok &= race_once(2u);
    ok &= race_once(3u);
    return ok;
}

/* n failing tasks: the run fails with TASK, the kept error is one of the n task errors (domain,
 * code and message), every executed task saw its own error in its error argument, and the stop
 * accounting holds. */
static gboolean concurrent_once(guint n) {
    Concurrent c = {{0, 0}, checks_hits_reset()};
    gboolean timed = clock_gettime(CLOCK_MONOTONIC, &c.deadline) == 0;
    long nsec = c.deadline.tv_nsec + CONCURRENT_DELAY_NS;
    c.deadline.tv_sec += nsec / 1000000000L;
    c.deadline.tv_nsec = nsec % 1000000000L;
    ScParallelConfig config = {n, n};
    ScParallelReport report = {0};
    GError *error = NULL;
    gboolean ran = sc_parallel_run(&config, n, concurrent_task, &c, &report, &error);
    gboolean ok =
        timed & g_error_matches(error, SC_PARALLEL_ERROR, SC_PARALLEL_ERROR_TASK) & (ran == FALSE);
    ok &= checks_message_in(error, concurrent_messages, n);
    g_clear_error(&error);
    return ok & (checks_hits_total() == report.executed) & (report.submitted >= 1u) &
           (report.submitted <= n) & (report.executed >= 1u) &
           (report.executed + report.skipped == report.submitted);
}

/* N = 8 first (the most pool threads at the first GError), then 2. */
static gboolean concurrent_errors(void) {
    gboolean ok = concurrent_once(CONCURRENT_MAX);
    ok &= concurrent_once(2u);
    return ok;
}

/* A one-task run of fn fails with TASK, and the kept message is the first length bytes of
 * expected. */
static gboolean kept_with(ScParallelTaskFn fn, gconstpointer data, const gchar *expected,
                          gsize length) {
    ScParallelConfig config = {1u, 1u};
    GError *error = NULL;
    gboolean ran = sc_parallel_run(&config, 1u, fn, data, NULL, &error);
    gboolean ok =
        g_error_matches(error, SC_PARALLEL_ERROR, SC_PARALLEL_ERROR_TASK) & (ran == FALSE);
    ok &= checks_message_is(error, expected, length);
    g_clear_error(&error);
    return ok;
}

/* The first error of a task is kept (also with a true result); a set argument is never
 * overwritten; another receiver gets its own error and an omitted one nothing. */
static gboolean messages(void) {
    gboolean ok = kept_with(twice_task, NULL, "the first message", 17u);
    ok &= kept_with(own_error_task, NULL, "the own error of the task", 25u);
    ScParallelConfig config = {2u, 2u};
    ScParallelReport report = {0};
    GError *error = NULL;
    gboolean ran = sc_parallel_run(&config, 4u, private_error_task, NULL, &report, &error);
    ok &= ran & (error == NULL) & (report.executed == 4u);
    g_clear_error(&error);
    return ok;
}

/* The messages checks with standard error captured: FALSE when they fail or when anything is
 * logged meanwhile. GLib keeps a set error by itself and only warns, and the warning is not fatal
 * (G_DEBUG is a prohibited variable), so this check is what fails when the adapter passes a set
 * error argument to GLib (T14T-A02). The captured bytes go to standard error. */
static gboolean messages_quietly(void) {
    gboolean begun = checks_capture_begin(STDERR_FILENO);
    gboolean ok = messages();
    gboolean logged = TRUE;
    gboolean ended = checks_capture_end(&logged);
    return begun & ok & ended & !logged;
}

/* S1-02: a capture keeps the whole text. The logged text is four alphabets, written LOUD_TIMES
 * times (266,240 bytes, more than four default pipe capacities); byte p is 'a' + p % 26. The
 * check is here and the capture is in checks.c, so the analyzer of each translation unit treats
 * the other part as single calls. */
#define ALPHABET "abcdefghijklmnopqrstuvwxyz"
static const char loud_text[] = ALPHABET ALPHABET ALPHABET ALPHABET;
#define LOUD_TEXT (sizeof loud_text - 1u)
#define LOUD_TIMES 2560u
#define LOUD_BYTES (LOUD_TEXT * LOUD_TIMES)

/* Logs the LOUD_BYTES bytes of the text to standard error; FALSE when a write fails. The count
 * comes from the write results, so the analyzer needs no constant number of iterations. */
static gboolean loud(void) {
    size_t sent = 0;
    while (sent < LOUD_BYTES) {
        size_t at = sent % LOUD_TEXT;
        ssize_t put = write(STDERR_FILENO, loud_text + at, LOUD_TEXT - at);
        if (put < 0 && errno == EINTR) {
            continue;
        }
        if (put <= 0) {
            return FALSE;
        }
        sent += (size_t)put;
    }
    return TRUE;
}

/* Reads fd to its end; TRUE when it held exactly the LOUD_BYTES bytes of the text in order. */
static gboolean read_loud(int fd) {
    size_t received = 0;
    gboolean in_order = TRUE;
    char buffer[4096];
    for (;;) {
        ssize_t got = read(fd, buffer, sizeof buffer);
        if (got < 0 && errno == EINTR) {
            continue;
        }
        if (got <= 0) {
            return in_order & (got == 0) & (received == LOUD_BYTES);
        }
        for (size_t i = 0; i < (size_t)got; i++) {
            in_order &= *(buffer + i) == *(loud_text + (received + i) % LOUD_TEXT);
        }
        received += (size_t)got;
    }
}

/* Part of the reviewed process boundary "standard error capture" (checks.c, findings S2-02 and
 * S3-01; whole_with and faulted_with are its members in this file). A child process captures a
 * loud window into a pipe that this process reads to its end. With end_inside the child ends
 * inside the window (exit status 1), as a halting sanitizer or a GLib fatal path does; otherwise
 * it exits 0 when the capture worked and saw the bytes. */
static gboolean whole_with(gboolean end_inside) {
    int ends[2] = {-1, -1};
    if (fflush(stdout) != 0 || fflush(stderr) != 0 || pipe2(ends, O_CLOEXEC) != 0) {
        return FALSE;
    }
    pid_t child = fork();
    if (child == 0) {
        (void)close(*ends);
        gboolean begun = checks_capture_begin(*(ends + 1));
        gboolean wrote = loud();
        if (end_inside) {
            _exit(1);
        }
        gboolean logged = FALSE;
        gboolean ended = checks_capture_end(&logged);
        _exit((begun && wrote && ended && logged) ? 0 : 3);
    }
    (void)close(*(ends + 1));
    gboolean whole = child > 0 && read_loud(*ends);
    (void)close(*ends);
    int status = -1;
    gboolean reaped = child > 0 && checks_wait(child, &status) == child;
    return whole && reaped && WIFEXITED(status) && WEXITSTATUS(status) == (end_inside ? 1 : 0);
}

/* Reads fd to its end (at most 255 bytes); TRUE when it held exactly the restore marker (marked)
 * or nothing (not marked). */
static gboolean read_marker(int fd, gboolean marked) {
    char buffer[256] = {0};
    size_t received = 0;
    for (;;) {
        ssize_t got = read(fd, buffer + received, sizeof buffer - 1u - received);
        if (got < 0 && errno == EINTR) {
            continue;
        }
        if (got <= 0) {
            break;
        }
        received += (size_t)got;
    }
    *(buffer + received) = '\0';
    return marked ? g_strcmp0(buffer, CHECKS_RESTORE_MARKER) == 0 : received == 0u;
}

/* Standard error of a faulted_with child, as dup2 returns it (a static, as in checks.c). */
static int faulted_stderr = -1;

/* Part of the reviewed process boundary "standard error capture" (checks.c, finding S3-01).
 * S2-04: a capture with one fault injected before the end (checks_capture_inject). The child
 * sends its standard error to a pipe that this process reads, so that the saved standard error of
 * the capture, and the drain's out, is that pipe; the window logs nothing. A first wait that fails
 * with EINTR must be retried: the end succeeds and the pipe stays empty. A failed restore must
 * make the end fail, write exactly the restore marker to the saved standard error and leave
 * descriptor 2 open (S3-06). The window whole_with checks the captured bytes; this check keeps
 * few branches for the analyzer. */
static gboolean faulted_with(gboolean restore_fails) {
    int errs[2] = {-1, -1};
    if (fflush(stdout) != 0 || fflush(stderr) != 0 || pipe2(errs, O_CLOEXEC) != 0) {
        return FALSE;
    }
    pid_t child = fork();
    if (child == 0) {
        (void)close(*errs);
        faulted_stderr = dup2(*(errs + 1), STDERR_FILENO);
        (void)close(*(errs + 1));
        gboolean begun = (faulted_stderr == STDERR_FILENO) & checks_capture_begin(STDERR_FILENO);
        checks_capture_inject(!restore_fails, restore_fails);
        gboolean logged = TRUE;
        gboolean ended = checks_capture_end(&logged);
        /* S3-06: descriptor 2 is open after every end, also after a failed restore, so that a
         * later open, pipe or dup cannot take it. */
        gboolean occupied = fcntl(STDERR_FILENO, F_GETFD) >= 0;
        _exit((begun & !logged & (ended != restore_fails) & occupied) ? 0 : 3);
    }
    (void)close(*(errs + 1));
    gboolean marked = child > 0 && read_marker(*errs, restore_fails);
    (void)close(*errs);
    int status = -1;
    gboolean reaped = child > 0 && checks_wait(child, &status) == child;
    return marked & reaped & WIFEXITED(status) & (WEXITSTATUS(status) == 0);
}

static int report_group(const char *name, gboolean ok) {
    printf("%s %s\n", ok ? "PARALLEL_PASS" : "PARALLEL_FAIL", name);
    return !ok;
}

int main(void) {
    int failed = 0;
    /* Before any thread exists, so that its child processes start from a single-threaded
     * process; it makes no GError. Reported with the errors group (S1-02). */
    gboolean whole =
        whole_with(FALSE) & whole_with(TRUE) & faulted_with(FALSE) & faulted_with(TRUE);
    /* First, before any other GError of the process; reported with the errors group. */
    gboolean concurrent = concurrent_errors();
    failed += report_group("config", config_bounds());
    failed += report_group("execution", execution());
    failed += report_group("admission", admission());
    gboolean messaged = messages_quietly();
    failed += report_group("errors", errors() & concurrent & messaged & whole);
    failed += report_group("trace", trace());
    failed += report_group("nesting", nesting());
    failed += report_group("race", race());
    return failed != 0;
}
