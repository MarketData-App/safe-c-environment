#pragma once
#include "pl_serve.h"
#include <stdio.h>

/* Program logic of pl-worker (specs/project/serve.md "Command line"): argv holds argc pointers;
 * any of them may be NULL. Returns the pl_serve result (0, 1, 3, 4) or 2 for a usage error. err
 * receives the usage line and the PLW1 line. Uses static buffers: one call at a time. */
int pl_worker_main(int argc, char **argv, FILE *err);

/* The parts of pl-worker in src/pl_worker_cli.c and src/pl_worker_opts.c. */

/* The parsed command line (paths borrowed from argv; NULL when absent). */
struct pl_worker_args {
    struct pl_serve_options o;
    int counters;
    const char *files_in;
    const char *files_out;
};

/* The options of pl-worker: bit 1 << option in *seen. */
enum pl_wopt {
    PL_WOPT_ECHO = 0,
    PL_WOPT_COUNTERS,
    PL_WOPT_SHM_IN,
    PL_WOPT_SHM_OUT,
    PL_WOPT_FILES,
    PL_WOPT_COUNT
};

/* One option at argv[*i] into *a; advances *i past its values and adds its bit to *seen. 0, or -1
 * for an unknown, repeated or NULL option, a missing value or a descriptor outside 3-1023. */
int pl_worker_option(int argc, char **argv, int *i, struct pl_worker_args *a, unsigned *seen);
