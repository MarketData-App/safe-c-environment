#define _GNU_SOURCE

#include "bd_wire.h"

#include <errno.h>
#include <stdint.h>
#include <sys/types.h>
#include <unistd.h>

/* Descriptor I/O of the bench-demo peers (specs/project/bd_wire.md): exact
 * reads and complete writes with EINTR retried. No allocation, no global
 * mutable state. Every transfer is bounded by len. */

/* The largest positioned end: off_t is 64-bit on the qualified Linux x86-64
 * runner, and an end above INT64_MAX cannot be an off_t. */
#define BD_OFFSET_MAX UINT64_C(0x7fffffffffffffff)

enum bd_io bd_read_exact(int fd, unsigned char *buf, size_t len) {
    size_t done = 0U;
    while (done < len) {
        const ssize_t got = read(fd, buf + done, len - done);
        if (got < 0) {
            if (errno == EINTR) {
                continue;
            }
            return BD_IO_ERROR;
        }
        if (got == 0) {
            return done == 0U ? BD_IO_EOF : BD_IO_TRUNCATED;
        }
        done += (size_t)got;
    }
    return BD_IO_OK;
}

enum bd_io bd_write_all(int fd, const unsigned char *buf, size_t len) {
    size_t done = 0U;
    while (done < len) {
        const ssize_t put = write(fd, buf + done, len - done);
        if (put < 0) {
            if (errno == EINTR) {
                continue;
            }
            return BD_IO_ERROR;
        }
        if (put == 0) {
            return BD_IO_ERROR;
        }
        done += (size_t)put;
    }
    return BD_IO_OK;
}

/* 1 when offset + len stays at most BD_OFFSET_MAX. */
static int range_fits(size_t len, uint64_t offset) {
    uint64_t end = 0U;
    const int wraps = __builtin_add_overflow(offset, (uint64_t)len, &end);
    return (wraps == 0) & (end <= BD_OFFSET_MAX);
}

enum bd_io bd_pread_exact(int fd, unsigned char *buf, size_t len, uint64_t offset) {
    if (range_fits(len, offset) == 0) {
        return BD_IO_ERROR;
    }
    size_t done = 0U;
    while (done < len) {
        const ssize_t got = pread(fd, buf + done, len - done, (off_t)(offset + (uint64_t)done));
        if (got < 0) {
            if (errno == EINTR) {
                continue;
            }
            return BD_IO_ERROR;
        }
        if (got == 0) {
            return BD_IO_TRUNCATED;
        }
        done += (size_t)got;
    }
    return BD_IO_OK;
}

enum bd_io bd_pwrite_all(int fd, const unsigned char *buf, size_t len, uint64_t offset) {
    if (range_fits(len, offset) == 0) {
        return BD_IO_ERROR;
    }
    size_t done = 0U;
    while (done < len) {
        const ssize_t put = pwrite(fd, buf + done, len - done, (off_t)(offset + (uint64_t)done));
        if (put < 0) {
            if (errno == EINTR) {
                continue;
            }
            return BD_IO_ERROR;
        }
        if (put == 0) {
            return BD_IO_ERROR;
        }
        done += (size_t)put;
    }
    return BD_IO_OK;
}
