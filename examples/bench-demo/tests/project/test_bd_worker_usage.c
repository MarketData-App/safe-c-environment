#define _GNU_SOURCE

#include "bd_wire.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* bd-worker usage tests derived from specs/project/bd_wire.md: fifteen usage
 * forms (counts, descriptor bounds 2 and 1024, equal descriptors, five
 * digits, a bad digit, an empty text, the swapped order, a short --files, an
 * unknown or misspelled option, a NULL argument and a NULL argv) give 2 and
 * the usage line. The err stream is shared and checked once at the end.
 * REQUIRE stays active under NDEBUG and has no side effects of its own. */

#define REQUIRE_FAIL(c) (fprintf(stderr, "%s:%d: REQUIRE %s\n", __FILE__, __LINE__, #c), exit(1))
#define REQUIRE(c) ((c) ? (void)0 : REQUIRE_FAIL(c))

/* A comparison result (0 or 1) as unsigned int. */
#define AS_BIT(condition) ((unsigned int)(condition))

static const char usage_text[] =
    "usage: bd-worker --stdio | --shm-in FD --shm-out FD [--files IN OUT]\n";

static void usage(void) {
    char prog[] = "bd-worker";
    char stdio_flag[] = "--stdio";
    char shm_in[] = "--shm-in";
    char shm_out[] = "--shm-out";
    char files[] = "--files";
    char flies[] = "--flies";
    char fd2[] = "2";
    char fd3[] = "3";
    char fd4[] = "4";
    char fd1023[] = "1023";
    char fd1024[] = "1024";
    char fd_long[] = "00004";
    char fd_bad[] = "4x";
    char empty[] = "";
    char bogus[] = "--bogus";
    char a[] = "a";
    char b[] = "b";
    char *only[] = {prog, NULL};
    char *stdio_extra[] = {prog, stdio_flag, a, NULL};
    char *shm_short[] = {prog, shm_in, fd3, NULL};
    char *shm_low[] = {prog, shm_in, fd2, shm_out, fd4, NULL};
    char *shm_high[] = {prog, shm_in, fd1024, shm_out, fd4, NULL};
    char *shm_equal[] = {prog, shm_in, fd4, shm_out, fd4, NULL};
    char *shm_long[] = {prog, shm_in, fd_long, shm_out, fd3, NULL};
    char *shm_digit[] = {prog, shm_in, fd3, shm_out, fd_bad, NULL};
    char *shm_empty[] = {prog, shm_in, empty, shm_out, fd4, NULL};
    char *shm_swapped[] = {prog, shm_out, fd3, shm_in, fd4, NULL};
    char *shm_files_short[] = {prog, shm_in, fd3, shm_out, fd1023, files, a, NULL};
    char *unknown[] = {prog, bogus, NULL};
    char *misspelled[] = {prog, stdio_flag, flies, a, b, NULL};
    char *null_route[] = {prog, NULL, NULL};
    FILE *err = tmpfile();
    REQUIRE(err != NULL);
    REQUIRE(bd_worker_main(1, only, err) == 2);
    REQUIRE(bd_worker_main(3, stdio_extra, err) == 2);
    REQUIRE(bd_worker_main(3, shm_short, err) == 2);
    REQUIRE(bd_worker_main(5, shm_low, err) == 2);
    REQUIRE(bd_worker_main(5, shm_high, err) == 2);
    REQUIRE(bd_worker_main(5, shm_equal, err) == 2);
    REQUIRE(bd_worker_main(5, shm_long, err) == 2);
    REQUIRE(bd_worker_main(5, shm_digit, err) == 2);
    REQUIRE(bd_worker_main(5, shm_empty, err) == 2);
    REQUIRE(bd_worker_main(5, shm_swapped, err) == 2);
    REQUIRE(bd_worker_main(7, shm_files_short, err) == 2);
    REQUIRE(bd_worker_main(2, unknown, err) == 2);
    REQUIRE(bd_worker_main(5, misspelled, err) == 2);
    REQUIRE(bd_worker_main(2, null_route, err) == 2);
    REQUIRE(bd_worker_main(0, NULL, err) == 2);
    char got[4096] = {0};
    const size_t length = strlen(usage_text);
    const int start = fseek(err, 0L, SEEK_SET);
    const size_t count = fread(got, 1U, sizeof got - 1U, err);
    unsigned int ok = AS_BIT(start == 0) & AS_BIT(count == 15U * length);
    for (size_t index = 0U; index < 15U; ++index) {
        ok &= AS_BIT(memcmp(got + index * length, usage_text, length) == 0);
    }
    REQUIRE(ok && fclose(err) == 0);
}

int main(void) {
    usage();
    return 0;
}
