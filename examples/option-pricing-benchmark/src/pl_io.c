#define _GNU_SOURCE
#include "pl_io.h"
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stddef.h>
#include <stdint.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

/* Exact-length descriptor I/O (specs/project/protocol.md "I/O"). Every loop ends: each pass
 * either moves at least one byte, retries an EINTR or returns. */

/* The largest byte count one read or write call is asked for (below SSIZE_MAX). */
#define PL_IO_CHUNK ((size_t)1 << 30)

/* The largest off_t value (off_t is 64 bits: _FILE_OFFSET_BITS is irrelevant on LP64). */
#define PL_OFF_MAX ((uint64_t)INT64_MAX)

static size_t pl_io_step(size_t left) { return left < PL_IO_CHUNK ? left : PL_IO_CHUNK; }

enum pl_io pl_read_exact(int fd, uint8_t *buf, size_t len) {
    size_t done = 0u;
    while (done < len) {
        const ssize_t n = read(fd, buf + done, pl_io_step(len - done));
        if (n > 0) {
            done += (size_t)n;
        } else if (n == 0) {
            return done == 0u ? PL_IO_EOF : PL_IO_TRUNCATED;
        } else if (errno != EINTR) {
            return PL_IO_ERROR;
        }
    }
    return PL_IO_OK;
}

enum pl_io pl_write_all(int fd, const uint8_t *buf, size_t len) {
    size_t done = 0u;
    while (done < len) {
        const ssize_t n = write(fd, buf + done, pl_io_step(len - done));
        if (n > 0) {
            done += (size_t)n;
        } else if (n == 0 || errno != EINTR) {
            return PL_IO_ERROR;
        }
    }
    return PL_IO_OK;
}

/* 1 when [offset, offset + len) lies inside the off_t range. */
static int pl_offset_ok(uint64_t offset, size_t len) {
    return offset <= PL_OFF_MAX && (uint64_t)len <= PL_OFF_MAX - offset;
}

enum pl_io pl_pread_exact(int fd, uint8_t *buf, size_t len, uint64_t offset) {
    if (!pl_offset_ok(offset, len)) {
        return PL_IO_ERROR;
    }
    size_t done = 0u;
    while (done < len) {
        const off_t at = (off_t)(offset + (uint64_t)done);
        const ssize_t n = pread(fd, buf + done, pl_io_step(len - done), at);
        if (n > 0) {
            done += (size_t)n;
        } else if (n == 0) {
            return PL_IO_TRUNCATED;
        } else if (errno != EINTR) {
            return PL_IO_ERROR;
        }
    }
    return PL_IO_OK;
}

enum pl_io pl_pwrite_all(int fd, const uint8_t *buf, size_t len, uint64_t offset) {
    if (!pl_offset_ok(offset, len)) {
        return PL_IO_ERROR;
    }
    size_t done = 0u;
    while (done < len) {
        const off_t at = (off_t)(offset + (uint64_t)done);
        const ssize_t n = pwrite(fd, buf + done, pl_io_step(len - done), at);
        if (n > 0) {
            done += (size_t)n;
        } else if (n == 0 || errno != EINTR) {
            return PL_IO_ERROR;
        }
    }
    return PL_IO_OK;
}

enum pl_io pl_read_file(const char *path, uint8_t *buf, size_t cap, size_t *len) {
    *len = 0u;
    const int fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0) {
        return PL_IO_ERROR;
    }
    size_t done = 0u;
    enum pl_io result = PL_IO_OK;
    for (;;) {
        uint8_t extra = 0u;
        uint8_t *at = done < cap ? buf + done : &extra;
        const size_t want = done < cap ? pl_io_step(cap - done) : 1u;
        const ssize_t n = read(fd, at, want);
        if (n > 0 && done < cap) {
            done += (size_t)n;
        } else if (n > 0) {
            result = PL_IO_ERROR;
            break;
        } else if (n == 0) {
            break;
        } else if (errno != EINTR) {
            result = PL_IO_ERROR;
            break;
        }
    }
    if (close(fd) != 0) {
        result = PL_IO_ERROR;
    }
    if (result == PL_IO_OK) {
        *len = done;
    }
    return result;
}

void pl_ignore_sigpipe(void) { (void)signal(SIGPIPE, SIG_IGN); }

/* The time of one clock in nanoseconds; 0 ok, -1 when the clock fails. */
static int pl_clock_read(clockid_t id, uint64_t *ns) {
    struct timespec t;
    if (clock_gettime(id, &t) != 0 || t.tv_sec < 0 || t.tv_nsec < 0) {
        return -1;
    }
    *ns = (uint64_t)t.tv_sec * UINT64_C(1000000000) + (uint64_t)t.tv_nsec;
    return 0;
}

int pl_clock_ns(uint64_t *mono, uint64_t *cpu) {
    *mono = 0u;
    *cpu = 0u;
    if (pl_clock_read(CLOCK_MONOTONIC, mono) != 0 ||
        pl_clock_read(CLOCK_PROCESS_CPUTIME_ID, cpu) != 0) {
        *mono = 0u;
        *cpu = 0u;
        return -1;
    }
    return 0;
}
