#define _GNU_SOURCE

#include "bd_wire.h"

#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Program logic of bd-worker (specs/project/bd_wire.md). No allocation, no
 * global mutable state. */

static const char usage_text[] =
    "usage: bd-worker --stdio | --shm-in FD --shm-out FD [--files IN OUT]\n";

/* Parses a decimal text of 1 to 4 digits with a value in [BD_FD_MIN,
 * BD_FD_MAX]. Returns 1 and stores the value, or 0 (value 0). */
static int parse_fd(const char *text, int *value) {
    *value = 0;
    if (text == NULL) {
        return 0;
    }
    const size_t length = strlen(text);
    if (length == 0U || length > 4U || strspn(text, "0123456789") != length) {
        return 0;
    }
    const long parsed = strtol(text, NULL, 10);
    if (parsed < BD_FD_MIN || parsed > BD_FD_MAX) {
        return 0;
    }
    *value = (int)parsed;
    return 1;
}

static int same(const char *text, const char *want) {
    return text != NULL && strcmp(text, want) == 0;
}

/* Reads the route part of argv into *o; returns the number of arguments it
 * used (1 or 4), or 0 for a usage error. */
static int parse_route(int argc, char **argv, struct bd_serve_options *o) {
    if (argc >= 2 && same(*(argv + 1), "--stdio")) {
        o->route = BD_ROUTE_STDIO;
        return 1;
    }
    if (argc < 5 || !same(*(argv + 1), "--shm-in") || !same(*(argv + 3), "--shm-out")) {
        return 0;
    }
    const int in_ok = parse_fd(*(argv + 2), &o->shm_in_fd);
    const int out_ok = parse_fd(*(argv + 4), &o->shm_out_fd);
    if (in_ok == 0 || out_ok == 0 || o->shm_in_fd == o->shm_out_fd) {
        return 0;
    }
    o->route = BD_ROUTE_SHM;
    return 4;
}

/* --files IN OUT: serves frames from the file IN into the file OUT and
 * writes the BDW1 line on err. */
static int serve_files(const char *in_path, const char *out_path, const struct bd_serve_options *o,
                       FILE *err) {
    uint64_t requests = 0U;
    int rc = 4;
    FILE *in = fopen(in_path, "rb");
    FILE *out = in == NULL ? NULL : fopen(out_path, "wb");
    if (in != NULL && out != NULL) {
        rc = bd_serve(fileno(in), fileno(out), o, &requests);
    }
    if (out != NULL && fclose(out) != 0) {
        rc = 4;
    }
    if (in != NULL) {
        (void)fclose(in);
    }
    (void)fprintf(err, "BDW1 exit=%d requests=%" PRIu64 "\n", rc, requests);
    return rc;
}

int bd_worker_main(int argc, char **argv, FILE *err) {
    struct bd_serve_options o = {BD_ROUTE_STDIO, -1, -1};
    const int used = argv == NULL ? 0 : parse_route(argc, argv, &o);
    const int rest = argc - 1 - used;
    const int files = used != 0 && rest == 3 && same(*(argv + 1 + used), "--files");
    if (used == 0 || (rest != 0 && files == 0)) {
        (void)fputs(usage_text, err);
        return 2;
    }
    if (rest == 3) {
        return serve_files(*(argv + 2 + used), *(argv + 3 + used), &o, err);
    }
    uint64_t requests = 0U;
    return bd_serve(0, 1, &o, &requests);
}
