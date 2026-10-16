#define _GNU_SOURCE

#include "bd_wire.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* Descriptor I/O tests derived from specs/project/bd_wire.md: exact reads
 * with EOF before and after the first byte, complete writes, positioned reads
 * and writes with the INT64_MAX end bound and wrapping offsets, a pipe and an
 * invalid descriptor. Files are ISO C temporary files. REQUIRE stays active
 * under NDEBUG and has no side effects of its own. */

#define REQUIRE_FAIL(c) (fprintf(stderr, "%s:%d: REQUIRE %s\n", __FILE__, __LINE__, #c), exit(1))
#define REQUIRE(c) ((c) ? (void)0 : REQUIRE_FAIL(c))

#define OFFSET_MAX UINT64_C(0x7fffffffffffffff)

static const unsigned char ten[10] = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10};

static void sequential(void) {
    FILE *file = tmpfile();
    REQUIRE(file != NULL);
    const int fd = fileno(file);
    REQUIRE(bd_write_all(fd, ten, sizeof ten) == BD_IO_OK);
    REQUIRE(bd_write_all(fd, ten, 0U) == BD_IO_OK);
    REQUIRE(lseek(fd, 0, SEEK_SET) == 0);
    unsigned char got[12] = {0};
    REQUIRE(bd_read_exact(fd, got, 0U) == BD_IO_OK);
    REQUIRE(bd_read_exact(fd, got, 4U) == BD_IO_OK && memcmp(got, ten, 4U) == 0);
    REQUIRE(bd_read_exact(fd, got, 6U) == BD_IO_OK && memcmp(got, ten + 4, 6U) == 0);
    REQUIRE(bd_read_exact(fd, got, 1U) == BD_IO_EOF);
    REQUIRE(lseek(fd, 0, SEEK_SET) == 0);
    REQUIRE(bd_read_exact(fd, got, 11U) == BD_IO_TRUNCATED);
    REQUIRE(memcmp(got, ten, sizeof ten) == 0);
    REQUIRE(fclose(file) == 0);
}

static void positioned(void) {
    FILE *file = tmpfile();
    REQUIRE(file != NULL);
    const int fd = fileno(file);
    REQUIRE(bd_pwrite_all(fd, ten, sizeof ten, 5U) == BD_IO_OK);
    unsigned char got[16] = {0};
    REQUIRE(bd_pread_exact(fd, got, 10U, 5U) == BD_IO_OK && memcmp(got, ten, sizeof ten) == 0);
    REQUIRE(bd_pread_exact(fd, got, 15U, 0U) == BD_IO_OK && *got == 0U && *(got + 5) == 1U);
    REQUIRE(bd_pread_exact(fd, got, 1U, 15U) == BD_IO_TRUNCATED);
    REQUIRE(bd_pread_exact(fd, got, 2U, 14U) == BD_IO_TRUNCATED);
    REQUIRE(bd_pread_exact(fd, got, 0U, OFFSET_MAX) == BD_IO_OK);
    REQUIRE(bd_pread_exact(fd, got, 0U, OFFSET_MAX + 1U) == BD_IO_ERROR);
    REQUIRE(bd_pread_exact(fd, got, 1U, OFFSET_MAX) == BD_IO_ERROR);
    REQUIRE(bd_pread_exact(fd, got, 2U, UINT64_MAX) == BD_IO_ERROR);
    REQUIRE(bd_pwrite_all(fd, ten, 1U, OFFSET_MAX) == BD_IO_ERROR);
    REQUIRE(bd_pwrite_all(fd, ten, 2U, UINT64_MAX) == BD_IO_ERROR);
    REQUIRE(bd_pwrite_all(fd, ten, 0U, OFFSET_MAX) == BD_IO_OK);
    REQUIRE(fclose(file) == 0);
}

static void descriptors(void) {
    unsigned char got[4] = {0};
    REQUIRE(bd_read_exact(-1, got, 1U) == BD_IO_ERROR);
    REQUIRE(bd_write_all(-1, ten, 1U) == BD_IO_ERROR);
    REQUIRE(bd_pread_exact(-1, got, 1U, 0U) == BD_IO_ERROR);
    REQUIRE(bd_pwrite_all(-1, ten, 1U, 0U) == BD_IO_ERROR);
    int ends[2] = {-1, -1};
    REQUIRE(pipe(ends) == 0);
    REQUIRE(bd_write_all(*(ends + 1), ten, 3U) == BD_IO_OK);
    /* A pipe has no position. */
    REQUIRE(bd_pwrite_all(*(ends + 1), ten, 1U, 0U) == BD_IO_ERROR);
    REQUIRE(bd_pread_exact(*ends, got, 1U, 0U) == BD_IO_ERROR);
    REQUIRE(close(*(ends + 1)) == 0);
    REQUIRE(bd_read_exact(*ends, got, 4U) == BD_IO_TRUNCATED);
    REQUIRE(memcmp(got, ten, 3U) == 0);
    REQUIRE(bd_read_exact(*ends, got, 1U) == BD_IO_EOF);
    REQUIRE(close(*ends) == 0);
}

int main(void) {
    sequential();
    positioned();
    descriptors();
    return 0;
}
