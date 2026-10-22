#define _GNU_SOURCE

#include "pl_worker_cli.h"
#include "pl_io.h"
#include "pl_serve.h"
#include "pl_types.h"
#include <inttypes.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

/* Program logic of pl-worker (specs/project/serve.md "Command line"). No allocation. */

static const char pl_usage[] =
    "usage: pl-worker [--echo] [--counters] [--shm-in FD --shm-out FD] [--files IN OUT] "
    "(specs/project/serve.md)\n";

static const char *const pl_model_names[PL_MODELS] = {"bsm", "bjs", "crr", "baw", "alo"};

/* The checked command line: 0 and *a, or -1. */
static int pl_parse(int argc, char **argv, struct pl_worker_args *a) {
    const struct pl_serve_options o = {PL_ROUTE_STDIO, 0, -1, -1, NULL, NULL};
    a->o = o;
    a->counters = 0;
    a->files_in = NULL;
    a->files_out = NULL;
    if (argv == NULL || argc < 1) {
        return -1;
    }
    unsigned seen = 0u;
    int i = 1;
    while (i < argc) {
        if (pl_worker_option(argc, argv, &i, a, &seen) != 0) {
            return -1;
        }
    }
    const int has_in = ((seen >> PL_WOPT_SHM_IN) & 1u) != 0u;
    const int has_out = ((seen >> PL_WOPT_SHM_OUT) & 1u) != 0u;
    if (has_in != has_out || (has_in && a->o.shm_in_fd == a->o.shm_out_fd)) {
        return -1;
    }
    if (has_in) {
        a->o.route = PL_ROUTE_SHM;
    }
    return 0;
}

/* --files IN OUT: serves frames from the file IN into the file OUT. */
static int pl_serve_files(const struct pl_worker_args *a, uint64_t *requests) {
    int rc = 4;
    FILE *in = fopen(a->files_in, "rb");
    FILE *out = in == NULL ? NULL : fopen(a->files_out, "wb");
    if (in != NULL && out != NULL) {
        rc = pl_serve(fileno(in), fileno(out), &a->o, requests);
    }
    if (out != NULL && fclose(out) != 0) {
        rc = 4;
    }
    if (in != NULL) {
        (void)fclose(in);
    }
    return rc;
}

/* " <label>=bsm:N,bjs:N,crr:N,baw:N,alo:N" on err. */
static void pl_print_totals(FILE *err, const char *label, const uint64_t totals[PL_MODELS]) {
    (void)fprintf(err, " %s=", label);
    for (size_t m = 0; m < PL_MODELS; m++) {
        (void)fprintf(err, "%s%s:%" PRIu64, m == 0u ? "" : ",", *(pl_model_names + m),
                      *(totals + m));
    }
}

int pl_worker_main(int argc, char **argv, FILE *err) {
    struct pl_worker_args a;
    if (pl_parse(argc, argv, &a) != 0) {
        (void)fputs(pl_usage, err);
        return 2;
    }
    pl_ignore_sigpipe();
    uint64_t calls[PL_MODELS] = {0u};
    uint64_t evals[PL_MODELS] = {0u};
    uint64_t requests = 0u;
    if (a.counters) {
        a.o.calls = calls;
        a.o.evals = evals;
    }
    const int files = a.files_in != NULL;
    const int rc = files ? pl_serve_files(&a, &requests) : pl_serve(0, 1, &a.o, &requests);
    if (files || a.counters) {
        (void)fprintf(err, "PLW1 exit=%d requests=%" PRIu64, rc, requests);
        if (a.counters) {
            pl_print_totals(err, "calls", calls);
            pl_print_totals(err, "evals", evals);
        }
        (void)fputc('\n', err);
    }
    return rc;
}
