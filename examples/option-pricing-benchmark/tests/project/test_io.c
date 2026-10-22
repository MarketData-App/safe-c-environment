#define _GNU_SOURCE
#include "pl_io.h"
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* Tests of pl_io.c (specs/project/protocol.md "I/O"): exact reads across partial writes, EOF
 * before and after the first byte, files larger than the capacity, positioned reads and writes,
 * closed descriptors, SIGPIPE, an EINTR read and a short write (group partial) and the clocks.
 * REQUIRE-style checks stay active under NDEBUG; the first failed check prints its line and
 * exits 1. */

#define REQUIRE_FAIL(c) (fprintf(stderr, "%s:%d: REQUIRE %s\n", __FILE__, __LINE__, #c), exit(1))
#define REQUIRE(c) ((c) ? (void)0 : REQUIRE_FAIL(c))

static const uint8_t data[8] = {1u, 2u, 3u, 4u, 5u, 6u, 7u, 8u};

static void pipes(void) {
    int p[2];
    uint8_t got[8] = {0u};
    REQUIRE(pipe(p) == 0);
    REQUIRE(pl_write_all(*(p + 1), data, 3u) == PL_IO_OK);
    REQUIRE(pl_write_all(*(p + 1), data + 3, 5u) == PL_IO_OK);
    REQUIRE(pl_read_exact(*p, got, 8u) == PL_IO_OK && memcmp(got, data, 8u) == 0);
    REQUIRE(pl_read_exact(*p, got, 0u) == PL_IO_OK);
    REQUIRE(pl_write_all(*(p + 1), data, 1u) == PL_IO_OK);
    REQUIRE(close(*(p + 1)) == 0);
    REQUIRE(pl_read_exact(*p, got, 2u) == PL_IO_TRUNCATED);
    REQUIRE(pl_read_exact(*p, got, 2u) == PL_IO_EOF);
    REQUIRE(close(*p) == 0);
    /* a write to a pipe without a reader fails (EPIPE) instead of killing the process */
    pl_ignore_sigpipe();
    REQUIRE(pipe(p) == 0);
    REQUIRE(close(*p) == 0);
    REQUIRE(pl_write_all(*(p + 1), data, 8u) == PL_IO_ERROR);
    REQUIRE(close(*(p + 1)) == 0);
    puts("PASS pipes");
}

static void closed(void) {
    uint8_t got[8] = {0u};
    const int fd = dup(1);
    REQUIRE(fd >= 0 && close(fd) == 0);
    REQUIRE(pl_read_exact(fd, got, 8u) == PL_IO_ERROR);
    REQUIRE(pl_write_all(fd, data, 8u) == PL_IO_ERROR);
    REQUIRE(pl_pread_exact(fd, got, 8u, 0u) == PL_IO_ERROR);
    REQUIRE(pl_pwrite_all(fd, data, 8u, 0u) == PL_IO_ERROR);
    REQUIRE(pl_write_all(fd, data, 0u) == PL_IO_OK);
    puts("PASS closed");
}

static void files(void) {
    uint8_t got[16] = {0u};
    FILE *f = tmpfile();
    REQUIRE(f != NULL);
    const int fd = fileno(f);
    char path[64];
    const int n = snprintf(path, sizeof path, "/proc/self/fd/%d", fd);
    const int named = n > 0 && (size_t)n < sizeof path;
    const enum pl_io w = pl_pwrite_all(fd, data, 8u, 0u);
    const enum pl_io r = pl_pread_exact(fd, got, 8u, 0u);
    const int same = memcmp(got, data, 8u) == 0;
    const enum pl_io beyond = pl_pread_exact(fd, got, 2u, 7u);
    const enum pl_io at_end = pl_pread_exact(fd, got, 1u, 8u);
    const enum pl_io huge = pl_pread_exact(fd, got, 1u, UINT64_MAX);
    const enum pl_io huge_w = pl_pwrite_all(fd, data, 1u, UINT64_MAX - 1u);
    size_t len = 99u;
    const enum pl_io whole = named ? pl_read_file(path, got, 8u, &len) : PL_IO_ERROR;
    const size_t whole_len = len;
    const enum pl_io larger = named ? pl_read_file(path, got, 7u, &len) : PL_IO_OK;
    const size_t larger_len = len;
    REQUIRE(fclose(f) == 0);
    REQUIRE(named && w == PL_IO_OK && r == PL_IO_OK && same);
    REQUIRE(beyond == PL_IO_TRUNCATED && at_end == PL_IO_TRUNCATED);
    REQUIRE(huge == PL_IO_ERROR && huge_w == PL_IO_ERROR);
    REQUIRE(whole == PL_IO_OK && whole_len == 8u && memcmp(got, data, 8u) == 0);
    REQUIRE(larger == PL_IO_ERROR && larger_len == 0u);
    REQUIRE(pl_read_file("/dev/null", got, 0u, &len) == PL_IO_OK && len == 0u);
    REQUIRE(pl_read_file("/nonexistent/pl-io", got, 8u, &len) == PL_IO_ERROR && len == 0u);
    puts("PASS files");
}

/* Partial-I/O state shared with the SIGALRM handler (review M1). The handler uses only
 * async-signal-safe calls (read, write) and keeps errno. */
static volatile sig_atomic_t alarm_mode = 0;
static volatile sig_atomic_t alarm_fd = -1;
static volatile sig_atomic_t alarm_drained = 0;
static uint8_t drain[1u << 20];
static uint8_t big[1u << 20];

static void on_alarm(int sig) {
    (void)sig;
    const int saved = errno;
    if (alarm_mode == 1) {
        /* read test: the data arrives only after the blocked read was interrupted */
        (void)write(alarm_fd, data, sizeof data);
    } else if (alarm_mode == 2) {
        /* write test: drain one pipe capacity, so the interrupted writer can finish */
        const ssize_t n = read(alarm_fd, drain, (size_t)alarm_drained);
        alarm_drained = n > 0 ? (sig_atomic_t)n : 0;
    }
    errno = saved;
}

/* SIGALRM without SA_RESTART: a blocked read or write returns EINTR or a short count. */
static void arm_alarm(void) {
    struct sigaction sa = {0};
    sa.sa_handler = on_alarm;
    REQUIRE(sigemptyset(&sa.sa_mask) == 0 && sigaction(SIGALRM, &sa, NULL) == 0);
    (void)alarm(1u);
}

static void partial(void) {
    int p[2];
    uint8_t got[8] = {0u};
    /* EINTR on a blocked read: pl_read_exact retries and then reads the 8 bytes */
    REQUIRE(pipe(p) == 0);
    alarm_mode = 1;
    alarm_fd = *(p + 1);
    arm_alarm();
    REQUIRE(pl_read_exact(*p, got, 8u) == PL_IO_OK && memcmp(got, data, 8u) == 0);
    REQUIRE(close(*p) == 0 && close(*(p + 1)) == 0);
    /* a short write: more than one pipe capacity, with the handler as the reader of the
     * first capacity; pl_write_all continues after the short count */
    REQUIRE(pipe(p) == 0);
    const int cap = fcntl(*p, F_GETPIPE_SZ);
    REQUIRE(cap > 0 && (size_t)cap + 32768u <= sizeof big);
    const size_t total = (size_t)cap + 32768u;
    for (size_t i = 0; i < total; i++) {
        *(big + i) = (uint8_t)(i * 7u);
    }
    alarm_mode = 2;
    alarm_fd = *p;
    alarm_drained = (sig_atomic_t)cap;
    arm_alarm();
    REQUIRE(pl_write_all(*(p + 1), big, total) == PL_IO_OK);
    const size_t first = (size_t)alarm_drained;
    REQUIRE(first > 0u && first <= total && memcmp(drain, big, first) == 0);
    REQUIRE(pl_read_exact(*p, drain, total - first) == PL_IO_OK);
    REQUIRE(memcmp(drain, big + first, total - first) == 0);
    REQUIRE(close(*p) == 0 && close(*(p + 1)) == 0);
    /* EINTR on a blocked write: the pipe is full before the call, so the write blocks before
     * its first byte; the handler drains the pipe and pl_write_all retries */
    REQUIRE(pipe(p) == 0);
    REQUIRE(fcntl(*p, F_GETPIPE_SZ) == cap);
    REQUIRE(pl_write_all(*(p + 1), big, (size_t)cap) == PL_IO_OK);
    alarm_fd = *p;
    alarm_drained = (sig_atomic_t)cap;
    arm_alarm();
    REQUIRE(pl_write_all(*(p + 1), big + cap, 32768u) == PL_IO_OK);
    REQUIRE((size_t)alarm_drained == (size_t)cap && memcmp(drain, big, (size_t)cap) == 0);
    REQUIRE(pl_read_exact(*p, drain, 32768u) == PL_IO_OK && memcmp(drain, big + cap, 32768u) == 0);
    REQUIRE(close(*p) == 0 && close(*(p + 1)) == 0);
    alarm_mode = 0;
    puts("PASS partial");
}

static void clocks(void) {
    uint64_t mono = 0u, cpu = 0u;
    REQUIRE(pl_clock_ns(&mono, &cpu) == 0 && mono > 0u && cpu > 0u);
    uint64_t later = 0u, cpu2 = 0u;
    REQUIRE(pl_clock_ns(&later, &cpu2) == 0 && later >= mono && cpu2 >= cpu);
    puts("PASS clocks");
}

int main(void) {
    pipes();
    closed();
    files();
    partial();
    clocks();
    return 0;
}
