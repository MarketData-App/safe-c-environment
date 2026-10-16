#define _GNU_SOURCE

#include "bd_wire.h"

#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

/* Program logic of bd-kernel (specs/project/bd_wire.md): --self-check, or a
 * timed run of one request file through the route entry bd_digest_request
 * with the framework kernel handshake (B, G before the loops; E, F after
 * them), so that no Python runs inside the timed loops. No allocation, no
 * global mutable state. */

static const char usage_text[] =
    "usage: bd-kernel --self-check | --input F --records N --loops L [--handshake] [--output F]\n";

enum { BD_KERNEL_USAGE = 2, BD_KERNEL_KERNEL = 3, BD_KERNEL_IO = 4 };

static int same(const char *text, const char *want) {
    return text != NULL && strcmp(text, want) == 0;
}

/* Writes the PLK1 failure line and returns rc. */
static int fail(FILE *out, const char *reason, int rc) {
    (void)fprintf(out, "PLK1 status=FAIL reason=%s\n", reason);
    (void)fflush(out);
    return rc;
}

/* Reads exactly length bytes from the file path and checks that it ends
 * there. Returns 1 on success. */
static int read_request(const char *path, unsigned char *request, size_t length) {
    FILE *file = fopen(path, "rb");
    if (file == NULL) {
        return 0;
    }
    int ok = fread(request, 1U, length, file) == length;
    /* Only after a complete read: the file must end exactly there. */
    if (ok != 0) {
        const int at_end = fgetc(file) == EOF;
        ok = at_end & (ferror(file) == 0);
    }
    (void)fclose(file);
    return ok;
}

static int write_output(const char *path, const unsigned char *output, size_t length) {
    FILE *file = fopen(path, "wb");
    if (file == NULL) {
        return 0;
    }
    const size_t put = fwrite(output, 1U, length, file);
    const int closed = fclose(file);
    return (put == length) & (closed == 0);
}

/* One handshake step: writes mark on out, flushes, and reads want from in. */
static int handshake(FILE *in, FILE *out, int mark, int want) {
    const int put = fputc(mark, out);
    const int flushed = fflush(out);
    if (put == EOF || flushed != 0) {
        return 0;
    }
    return fgetc(in) == want;
}

static int clock_ns(clockid_t id, uint64_t *ns) {
    struct timespec ts = {0, 0};
    *ns = 0U;
    if (clock_gettime(id, &ts) != 0 || ts.tv_sec < 0 || ts.tv_nsec < 0) {
        return 0;
    }
    uint64_t scaled = 0U;
    if (__builtin_mul_overflow((uint64_t)ts.tv_sec, UINT64_C(1000000000), &scaled) ||
        __builtin_add_overflow(scaled, (uint64_t)ts.tv_nsec, ns)) {
        *ns = 0U;
        return 0;
    }
    return 1;
}

/* FNV-1a 64 of length bytes (the summary digest of the output). */
static uint64_t output_digest(const unsigned char *bytes, size_t length) {
    uint64_t hash = BD_FNV_OFFSET;
    for (size_t index = 0U; index < length; ++index) {
        uint64_t product = 0U;
        (void)__builtin_mul_overflow(hash ^ (uint64_t)*(bytes + index), BD_FNV_PRIME, &product);
        hash = product;
    }
    return hash;
}

struct timing {
    uint64_t mono_ns;
    uint64_t cpu_ns;
};

/* The timed loops: o->loops calls of bd_digest_request between the clock
 * reads. Returns 1 when every call and clock read succeeds. */
static int timed_loops(const struct bd_kernel_options *o, const unsigned char *request,
                       size_t length, unsigned char *output, size_t *written, struct timing *t) {
    uint64_t mono0 = 0U;
    uint64_t cpu0 = 0U;
    uint64_t mono1 = 0U;
    uint64_t cpu1 = 0U;
    int ok = clock_ns(CLOCK_MONOTONIC, &mono0) & clock_ns(CLOCK_PROCESS_CPUTIME_ID, &cpu0);
    for (uint64_t loop = 0U; loop < o->loops; ++loop) {
        const size_t room = (size_t)BD_OUTPUT_MAX_BYTES;
        ok &= bd_digest_request(request, length, output, room, written) == BD_OK;
    }
    ok &= clock_ns(CLOCK_MONOTONIC, &mono1) & clock_ns(CLOCK_PROCESS_CPUTIME_ID, &cpu1);
    t->mono_ns = mono1 >= mono0 ? mono1 - mono0 : 0U;
    t->cpu_ns = cpu1 >= cpu0 ? cpu1 - cpu0 : 0U;
    return ok;
}

static int run(const struct bd_kernel_options *o, FILE *in, FILE *out) {
    unsigned char request[BD_REQUEST_MAX_BYTES] = {0};
    unsigned char output[BD_OUTPUT_MAX_BYTES] = {0};
    /* records <= BD_RECORDS_MAX, so the length cannot wrap. */
    const size_t length = (size_t)o->records * (size_t)BD_RECORD_IN_BYTES;
    size_t count = 0U;
    const int loaded = read_request(o->input, request, length);
    if (loaded == 0 || bd_check_request(request, length, &count) != BD_OK) {
        return fail(out, "input", BD_KERNEL_USAGE);
    }
    if (o->handshake != 0 && handshake(in, out, 'B', 'G') == 0) {
        return fail(out, "io", BD_KERNEL_IO);
    }
    size_t written = 0U;
    struct timing t = {0U, 0U};
    const int ok = timed_loops(o, request, length, output, &written, &t);
    if (o->handshake != 0 && handshake(in, out, 'E', 'F') == 0) {
        return fail(out, "io", BD_KERNEL_IO);
    }
    if (ok == 0) {
        return fail(out, "kernel", BD_KERNEL_KERNEL);
    }
    if (o->output != NULL && write_output(o->output, output, written) == 0) {
        return fail(out, "io", BD_KERNEL_IO);
    }
    const uint64_t digest = output_digest(output, written);
    const int head =
        fprintf(out, "PLK1 status=OK case=bd-digest records=%zu loops=%" PRIu64, count, o->loops);
    const int times =
        fprintf(out, " threads=0 mono_ns=%" PRIu64 " cpu_ns=%" PRIu64, t.mono_ns, t.cpu_ns);
    const int tail = fprintf(out, " chunks=0 chunk_sizes= chunk_wall_ns= copied_bytes=%zu", length);
    const int end = fprintf(out, " digest=%016" PRIx64 "\n", digest);
    const int text = (head < 0) | (times < 0) | (tail < 0) | (end < 0);
    const int flushed = fflush(out);
    return (text | (flushed != 0)) != 0 ? BD_KERNEL_IO : 0;
}

int bd_kernel_cli_main(int argc, char **argv, FILE *in, FILE *out, FILE *err) {
    if (argc == 2 && argv != NULL && same(*(argv + 1), "--self-check")) {
        return bd_kernel_main(argc, argv, out, err);
    }
    struct bd_kernel_options o = {NULL, NULL, 0U, 0U, 0};
    if (argv == NULL || argc < 2 || bd_kernel_parse(argc, argv, &o) == 0) {
        (void)fputs(usage_text, err);
        return fail(out, "usage", BD_KERNEL_USAGE);
    }
    return run(&o, in, out);
}
