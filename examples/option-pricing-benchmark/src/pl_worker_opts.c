#include "pl_worker_cli.h"
#include <stddef.h>
#include <string.h>

/* The option scanner of pl-worker (specs/project/serve.md "Command line"): a translation unit of
 * its own, so that the call inside the argument loop of src/pl_worker_cli.c is opaque to the GCC
 * analyzer (the fixed analyzer budget of the framework; the same reason as in batch.md). */

#define PL_FD_MIN 3
#define PL_FD_MAX 1023

/* The name of option k. */
static const char *pl_wopt_name(size_t k) {
    switch (k) {
    case PL_WOPT_ECHO:
        return "--echo";
    case PL_WOPT_COUNTERS:
        return "--counters";
    case PL_WOPT_SHM_IN:
        return "--shm-in";
    case PL_WOPT_SHM_OUT:
        return "--shm-out";
    default:
        return "--files";
    }
}

/* The number of value words of option k. */
static int pl_wopt_values(size_t k) {
    if (k == PL_WOPT_FILES) {
        return 2;
    }
    return k == PL_WOPT_SHM_IN || k == PL_WOPT_SHM_OUT ? 1 : 0;
}

/* The index of the option named arg (NULL gives PL_WOPT_COUNT), or PL_WOPT_COUNT. */
static size_t pl_wopt_find(const char *arg) {
    for (size_t k = 0; arg != NULL && k < PL_WOPT_COUNT; k++) {
        if (strcmp(arg, pl_wopt_name(k)) == 0) {
            return k;
        }
    }
    return PL_WOPT_COUNT;
}

/* Parses a decimal text of one to four digits with a value in [PL_FD_MIN, PL_FD_MAX]. Returns 1
 * and stores the value, or 0 (value 0). */
static int pl_parse_fd(const char *text, int *value) {
    int v = 0;
    size_t n = 0u;
    *value = 0;
    while (*(text + n) != '\0') {
        const char c = *(text + n);
        if (c < '0' || c > '9' || n >= 4u) {
            return 0;
        }
        v = v * 10 + (c - '0');
        n++;
    }
    if (n == 0u || v < PL_FD_MIN || v > PL_FD_MAX) {
        return 0;
    }
    *value = v;
    return 1;
}

/* 1 when count (0-2) value words follow argv[i] and none is NULL. */
static int pl_has_words(int argc, char **argv, int i, int count) {
    if (count == 0) {
        return 1;
    }
    if (i + count >= argc || *(argv + i + 1) == NULL) {
        return 0;
    }
    return count < 2 || *(argv + i + 2) != NULL;
}

/* Stores option k with its value words at argv[i + 1 ..] into *a: 1, or 0 for a bad descriptor. */
static int pl_wopt_store(size_t k, char **argv, int i, struct pl_worker_args *a) {
    switch (k) {
    case PL_WOPT_ECHO:
        a->o.echo = 1;
        return 1;
    case PL_WOPT_COUNTERS:
        a->counters = 1;
        return 1;
    case PL_WOPT_SHM_IN:
        return pl_parse_fd(*(argv + i + 1), &a->o.shm_in_fd);
    case PL_WOPT_SHM_OUT:
        return pl_parse_fd(*(argv + i + 1), &a->o.shm_out_fd);
    default:
        a->files_in = *(argv + i + 1);
        a->files_out = *(argv + i + 2);
        return 1;
    }
}

int pl_worker_option(int argc, char **argv, int *i, struct pl_worker_args *a, unsigned *seen) {
    const size_t k = pl_wopt_find(*(argv + *i));
    if (k == PL_WOPT_COUNT) {
        return -1;
    }
    const unsigned bit = 1u << k;
    const int values = pl_wopt_values(k);
    if ((*seen & bit) != 0u || !pl_has_words(argc, argv, *i, values)) {
        return -1;
    }
    *seen |= bit;
    const int ok = pl_wopt_store(k, argv, *i, a);
    *i += 1 + values;
    return ok ? 0 : -1;
}
