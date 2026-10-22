#pragma once
#include <stddef.h>
#include <stdint.h>

/* Exact-length descriptor I/O (specs/project/protocol.md "I/O"). Every buffer is caller-owned
 * and borrowed for the call only; no function keeps a pointer or closes a caller descriptor. */

enum pl_io { PL_IO_OK = 0, PL_IO_EOF = 1, PL_IO_TRUNCATED = 2, PL_IO_ERROR = 3 };

/* Reads exactly len bytes; EINTR is retried. EOF before any byte -> PL_IO_EOF; EOF after at
 * least one byte -> PL_IO_TRUNCATED; a read error -> PL_IO_ERROR. len 0 -> PL_IO_OK. */
enum pl_io pl_read_exact(int fd, uint8_t *buf, size_t len);
/* Writes exactly len bytes; EINTR is retried; an error or a zero-byte write -> PL_IO_ERROR. */
enum pl_io pl_write_all(int fd, const uint8_t *buf, size_t len);
/* Reads exactly len bytes at offset; a short read (EOF) -> PL_IO_TRUNCATED; an offset range
 * beyond the off_t range or a read error -> PL_IO_ERROR. */
enum pl_io pl_pread_exact(int fd, uint8_t *buf, size_t len, uint64_t offset);
/* Writes exactly len bytes at offset; errors as pl_pread_exact (a zero-byte write is an error). */
enum pl_io pl_pwrite_all(int fd, const uint8_t *buf, size_t len, uint64_t offset);
/* Reads the whole file at path (a NUL-terminated text) into buf; *len receives the byte count.
 * A file larger than cap, an open, read or close error -> PL_IO_ERROR (then *len is 0). */
enum pl_io pl_read_file(const char *path, uint8_t *buf, size_t cap, size_t *len);
/* Sets the SIGPIPE disposition to ignore, so a write to a closed pipe fails with EPIPE. */
void pl_ignore_sigpipe(void);
/* *mono: CLOCK_MONOTONIC, *cpu: CLOCK_PROCESS_CPUTIME_ID, in nanoseconds. 0 ok, -1 when a clock
 * fails (then both are 0). */
int pl_clock_ns(uint64_t *mono, uint64_t *cpu);
