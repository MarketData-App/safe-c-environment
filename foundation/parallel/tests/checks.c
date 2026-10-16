#define _GNU_SOURCE
#include "checks.h"

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

/* A struct so that the reset is one assignment. */
typedef struct {
    guint v[CHECK_TASKS];
} Hits;

static Hits hits;

guint *checks_hits_reset(void) {
    hits = (Hits){{0u}};
    return hits.v;
}

guint checks_hits_total(void) {
    guint sum = 0u;
    for (gsize i = 0; i < CHECK_TASKS; i++) {
        sum += *(hits.v + i);
    }
    return sum;
}

gboolean checks_hits_all(guint value) {
    gboolean ok = TRUE;
    for (gsize i = 0; i < CHECK_TASKS; i++) {
        ok &= *(hits.v + i) == value;
    }
    return ok;
}

gboolean checks_trace_entries(const ScParallelTraceEntry *entries, gsize used, guint workers,
                              gint64 returned) {
    gboolean ok = TRUE;
    for (gsize i = 0; i < used; i++) {
        const ScParallelTraceEntry *e = entries + i;
        /* No task starts or ends after the return. */
        ok &= (e->task_index == i) & (e->thread_tag < workers) & (e->start_ns >= 0) &
              (e->end_ns >= e->start_ns) & (e->cpu_ns >= 0) & (e->start_ns <= returned) &
              (e->end_ns <= returned);
    }
    return ok;
}

gsize checks_trace_max_overlap(const ScParallelTraceEntry *entries, gsize used) {
    gsize most = 0u;
    for (gsize i = 0; i < used; i++) {
        gint64 at = (entries + i)->start_ns;
        gsize running = 0u;
        for (gsize j = 0; j < used; j++) {
            const ScParallelTraceEntry *e = entries + j;
            running += (gsize)((e->start_ns <= at) & (at < e->end_ns));
        }
        most = MAX(most, running);
    }
    return most;
}

gboolean checks_message_is(const GError *error, const gchar *text, gsize length) {
    const gchar *message = error != NULL ? error->message : NULL;
    if (message == NULL) {
        return FALSE;
    }
    gboolean same = TRUE;
    for (gsize i = 0; i < length && same; i++) {
        same = (*(message + i) == *(text + i)) & (*(message + i) != '\0');
    }
    return same && *(message + length) == '\0';
}

gboolean checks_message_in(const GError *error, const gchar *const *messages, gsize count) {
    const gchar *message = error != NULL ? error->message : NULL;
    gboolean found = FALSE;
    for (gsize i = 0; i < count; i++) {
        found |= g_strcmp0(message, *(messages + i)) == 0;
    }
    return found & (message != NULL);
}

/* Writes length bytes to fd, retrying partial writes and interruptions; FALSE on a failure. Only
 * async-signal-safe calls. */
static gboolean write_all(int fd, const char *bytes, size_t length) {
    size_t done = 0;
    while (done < length) {
        ssize_t put = write(fd, bytes + done, length - done);
        if (put < 0 && errno == EINTR) {
            continue;
        }
        if (put <= 0) {
            return FALSE;
        }
        done += (size_t)put;
    }
    return TRUE;
}

/* Reviewed process boundary: standard error capture (batch S2, finding S2-02; completed by
 * finding S3-01). This section (drain, checks_capture_inject, checks_wait, checks_capture_begin,
 * checks_capture_end) and whole_with and faulted_with in contracts.c are the only users of the
 * process APIs pipe2, fork, dup2, fcntl, waitpid and _exit in the foundation tests;
 * checks_capture_inject calls none of them itself but sets the faults of the next
 * checks_capture_end. After a failed restore, checks_capture_end also opens /dev/null so that
 * descriptor 2 stays occupied (finding S3-06). They are test code, reviewed by the batch S2 and
 * S3 approvers; no other process API belongs in the foundation tests. */

/* The drain process of a capture: copies the pipe in to out as the bytes arrive, until end of
 * file, then exits 0 when nothing came, 1 when bytes came and 2 when a read or write failed. Only
 * async-signal-safe calls (it is a fork child); it never returns. */
static _Noreturn void drain(int in, int out) {
    char buffer[4096];
    int seen = 0;
    for (;;) {
        ssize_t got = read(in, buffer, sizeof buffer);
        if (got < 0 && errno == EINTR) {
            continue;
        }
        if (got <= 0) {
            _exit(got == 0 ? seen : 2);
        }
        seen = 1;
        if (!write_all(out, buffer, (size_t)got)) {
            _exit(2);
        }
    }
}

/* The saved standard error, the drain child and standard error as each dup2 returns it. They
 * are kept here, not in locals that go out of scope, because they stay open past the call that
 * makes them. */
static int capture_saved = -1;
static pid_t capture_drainer = -1;
static int redirected_stderr = -1;
static int restored_stderr = -1;
/* S3-06: /dev/null on descriptor 2 after a failed restore, as open returns it. */
static int reopened_stderr = -1;

/* The test-only faults of the next checks_capture_end (S2-04). The S2-04 evidence (the EINTR
 * retry and the restore marker) is GREEN-only: no valid failing-before run exists (finding
 * S3-02), so it is not behaviorally verified. */
static gboolean fault_wait_eintr = FALSE;
static gboolean fault_restore = FALSE;

void checks_capture_inject(gboolean wait_eintr, gboolean restore_fails) {
    fault_wait_eintr = wait_eintr;
    fault_restore = restore_fails;
}

pid_t checks_wait(pid_t child, int *status) {
    /* The injected fault stands for a first wait that failed with EINTR. */
    gboolean again = fault_wait_eintr;
    fault_wait_eintr = FALSE;
    pid_t got = -1;
    if (!again) {
        got = waitpid(child, status, 0);
        again = (got < 0) & (errno == EINTR);
    }
    /* S2-04: an interrupted wait is retried; any other result is the answer. Bitwise tests keep
     * the analyzer states at this loop few (analyzer-too-complex). */
    while (again) {
        got = waitpid(child, status, 0);
        again = (got < 0) & (errno == EINTR);
    }
    return got;
}

/* S1-02: a drain child process copies every captured byte to out as it arrives, so the whole
 * text reaches out also when this process ends inside the window (a halting sanitizer or a GLib
 * fatal path): the end closes the last write end, and the child copies the rest and exits. */
gboolean checks_capture_begin(int out) {
    int ends[2] = {-1, -1};
    redirected_stderr = -1;
    if (fflush(stderr) != 0 || pipe2(ends, O_CLOEXEC) != 0) {
        return FALSE;
    }
    capture_drainer = fork();
    if (capture_drainer == 0) {
        (void)close(*(ends + 1));
        drain(*ends, out);
    }
    (void)close(*ends);
    /* The saved standard error is close-on-exec, as both pipe ends (S1-03). The pipe has no
     * O_NONBLOCK: a file status flag of the pipe also applies to descriptor 2 inside the window,
     * so a write larger than the free pipe space would fail with EAGAIN and lose text. The child
     * keeps draining the pipe, so a writer waits instead of failing, and no byte is dropped. */
    capture_saved = capture_drainer > 0 ? fcntl(STDERR_FILENO, F_DUPFD_CLOEXEC, 0) : -1;
    redirected_stderr = capture_saved >= 0 ? dup2(*(ends + 1), STDERR_FILENO) : -1;
    (void)close(*(ends + 1));
    return redirected_stderr == STDERR_FILENO;
}

/* Few branches on purpose: the analyzer follows checks_wait inside this function, and each
 * branch before the wait multiplies the states at its retry loop (analyzer-too-complex). */
gboolean checks_capture_end(gboolean *logged) {
    (void)fflush(stderr);
    gboolean redirected = redirected_stderr == STDERR_FILENO;
    /* No branch before the restore: without a saved descriptor the source is -1, and the injected
     * fault turns a saved descriptor into G_MAXINT, which is not open; dup2 then fails (EBADF). */
    int source = capture_saved | (-(int)(fault_restore != FALSE) & G_MAXINT);
    fault_restore = FALSE;
    restored_stderr = dup2(source, STDERR_FILENO);
    gboolean restored = restored_stderr == STDERR_FILENO;
    if (redirected & !restored) {
        /* S2-04: first say on the saved standard error that later output of this process is lost
         * (one write below PIPE_BUF; best effort). Standard error still holds the last write end;
         * close it so that the drain child ends. */
        ssize_t put =
            write(capture_saved, CHECKS_RESTORE_MARKER, sizeof CHECKS_RESTORE_MARKER - 1u);
        (void)put;
        (void)close(STDERR_FILENO);
        /* S3-06: occupy descriptor 2 again, so that a later open, pipe or dup of this process
         * cannot take it and receive standard error text. open returns the lowest free
         * descriptor, which is 2 while descriptors 0 and 1 stay open. */
        reopened_stderr = open("/dev/null", O_WRONLY | O_CLOEXEC);
    }
    /* close(-1) fails with EBADF and changes nothing. */
    (void)close(capture_saved);
    capture_saved = -1;
    pid_t drainer = capture_drainer;
    capture_drainer = -1;
    int status = -1;
    gboolean reaped = drainer > 0 && checks_wait(drainer, &status) == drainer;
    gboolean drained = reaped & WIFEXITED(status) & (WEXITSTATUS(status) <= 1);
    *logged = !drained | (WEXITSTATUS(status) != 0);
    return redirected & restored & drained;
}
