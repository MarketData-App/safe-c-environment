#define _GNU_SOURCE
#include "pl_kernel_run.h"
#include "pl_batch.h"
#include "pl_canonical.h"
#include "pl_crr.h"
#include "pl_evaluate.h"
#include "pl_ieee.h"
#include "pl_io.h"
#include "pl_kernel_cli.h"
#include "pl_partition.h"
#include "pl_protocol.h"
#include "pl_scan.h"
#include "pl_types.h"
#include <fcntl.h>
#include <inttypes.h>
#include <sc-parallel.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <unistd.h>

/* The runs of pl-kernel (specs/project/batch.md "pl-kernel command line"): the input, the timed
 * loops of the three cases, the output files, the trace and the PLK1 line. Static buffers: one
 * call at a time. */

#define PL_KERNEL_MAX_RECORDS 20000u
#define PL_WRITE_RECORDS 64u

static uint8_t pl_input[PL_KERNEL_MAX_RECORDS * PL_PROBE_IN_BYTES];
static struct pl_contract_result pl_results[PL_KERNEL_MAX_RECORDS];
static uint8_t pl_probe_out[PL_KERNEL_MAX_RECORDS * PL_PROBE_OUT_BYTES];
static uint32_t pl_perm[PL_REQUEST_LIMIT];
static uint32_t pl_indices[PL_REQUEST_LIMIT];
static uint8_t pl_mark[PL_REQUEST_LIMIT];
static ScParallelTraceEntry pl_trace[PL_MAX_CHUNKS];
static uint8_t pl_write_buf[PL_WRITE_RECORDS * PL_RESPONSE_RECORD_BYTES];

static size_t pl_record_bytes(int kase) {
    if (kase == PL_CASE_OPTION) {
        return PL_REQUEST_RECORD_BYTES;
    }
    return kase == PL_CASE_SCAN ? PL_SCAN_RECORD_BYTES : PL_PROBE_IN_BYTES;
}

/* Reads exactly bytes bytes from the start of the input file. */
static int pl_read_input(const char *path, size_t bytes) {
    const int fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0) {
        return PL_REASON_INPUT;
    }
    const enum pl_io r = pl_read_exact(fd, pl_input, bytes);
    const int closed = close(fd);
    return (r == PL_IO_OK && closed == 0) ? PL_REASON_OK : PL_REASON_INPUT;
}

/* Writes the byte send to fd 1 and reads one byte, which must be expect, from fd 0. */
static int pl_handshake(uint8_t send, uint8_t expect) {
    uint8_t got = 0u;
    if (pl_write_all(1, &send, 1u) != PL_IO_OK || pl_read_exact(0, &got, 1u) != PL_IO_OK) {
        return PL_REASON_IO;
    }
    return got == expect ? PL_REASON_OK : PL_REASON_IO;
}

/* The handshake, the clocks and the loops. */
static int pl_timed_loops(const struct pl_kernel_args *a, const struct pl_params *p,
                          struct pl_kernel_state *s, FILE *out) {
    if (a->handshake && (fflush(out) == EOF || pl_handshake('B', 'G') != PL_REASON_OK)) {
        return PL_REASON_IO;
    }
    uint64_t m0 = 0u, c0 = 0u, m1 = 0u, c1 = 0u;
    if (pl_clock_ns(&m0, &c0) != 0) {
        return PL_REASON_KERNEL;
    }
    struct pl_kernel_bufs b;
    b.input = pl_input;
    b.results = pl_results;
    b.probe_out = pl_probe_out;
    b.perm = pl_perm;
    b.mark = pl_mark;
    b.indices = pl_indices;
    b.trace = pl_trace;
    for (uint32_t loop = 0u; loop < a->loops; loop++) {
        const int rc = pl_kernel_loop(a, p, &b, s);
        if (rc != PL_REASON_OK) {
            return rc;
        }
    }
    if (pl_clock_ns(&m1, &c1) != 0) {
        return PL_REASON_KERNEL;
    }
    s->mono_ns = m1 >= m0 ? m1 - m0 : 0u;
    s->cpu_ns = c1 >= c0 ? c1 - c0 : 0u;
    if (a->handshake && pl_handshake('E', 'F') != PL_REASON_OK) {
        return PL_REASON_IO;
    }
    return PL_REASON_OK;
}

static int pl_open_out(const char *path) {
    return open(path, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0644);
}

/* The 290-byte records of the option case (n results). */
static enum pl_io pl_write_results(int fd, size_t n) {
    for (size_t i = 0; i < n; i += PL_WRITE_RECORDS) {
        const size_t k = n - i < PL_WRITE_RECORDS ? n - i : PL_WRITE_RECORDS;
        for (size_t j = 0; j < k; j++) {
            pl_response_encode(pl_results + i + j, pl_write_buf + j * PL_RESPONSE_RECORD_BYTES);
        }
        if (pl_write_all(fd, pl_write_buf, k * PL_RESPONSE_RECORD_BYTES) != PL_IO_OK) {
            return PL_IO_ERROR;
        }
    }
    return PL_IO_OK;
}

static int pl_write_output(const struct pl_kernel_args *a) {
    const int fd = pl_open_out(a->output);
    if (fd < 0) {
        return PL_REASON_IO;
    }
    enum pl_io r = PL_IO_OK;
    if (a->kase == PL_CASE_PROBE) {
        r = pl_write_all(fd, pl_probe_out, a->records * PL_PROBE_OUT_BYTES);
    } else {
        r = pl_write_results(fd, a->records);
    }
    const int closed = close(fd);
    return (r == PL_IO_OK && closed == 0) ? PL_REASON_OK : PL_REASON_IO;
}

/* The canonical bytes (the parser refuses --echo with --canonical: the writer refuses status
 * 255). */
static int pl_write_canonical(const struct pl_kernel_args *a) {
    const int fd = pl_open_out(a->canonical);
    if (fd < 0) {
        return PL_REASON_IO;
    }
    struct pl_sink sink = {fd, pl_write_buf, sizeof pl_write_buf, 0u, 0, 0u, 0u};
    const int rc = pl_canonical_write(&sink, pl_results, a->records, a->models);
    int reason = rc == 0 ? PL_REASON_OK : (rc == -1 ? PL_REASON_KERNEL : PL_REASON_IO);
    if (close(fd) != 0 && reason == PL_REASON_OK) {
        reason = PL_REASON_IO;
    }
    return reason;
}

static int pl_write_trace(const struct pl_kernel_args *a, const struct pl_kernel_state *s) {
    FILE *f = fopen(a->trace, "w");
    if (f == NULL) {
        return PL_REASON_IO;
    }
    size_t executed = 0u;
    for (size_t k = 0; k < s->trace_used; k++) {
        executed += (size_t)((pl_trace + k)->start_ns >= 0);
    }
    const unsigned workers = s->stats.threads_observed;
    int bad = fprintf(f, "# workers=%u threads=%u", workers, a->threads) < 0;
    bad |= fprintf(f, " max_inflight=%zu", s->stats.max_inflight) < 0;
    bad |= fprintf(f, " submitted=%zu executed=%zu\n", s->trace_used, executed) < 0;
    for (size_t k = 0; k < s->trace_used; k++) {
        const ScParallelTraceEntry *e = pl_trace + k;
        const int64_t start = (int64_t)e->start_ns;
        const int64_t end = (int64_t)e->end_ns;
        const int64_t cpu = (int64_t)e->cpu_ns;
        bad |= fprintf(f, "%u %" PRId64 " %" PRId64, e->thread_tag, start, end) < 0;
        bad |= fprintf(f, " %zu %" PRId64 "\n", k, cpu) < 0;
    }
    bad |= fclose(f) != 0;
    return bad ? PL_REASON_IO : PL_REASON_OK;
}

static int pl_write_files(const struct pl_kernel_args *a, const struct pl_kernel_state *s) {
    int reason = PL_REASON_OK;
    if (a->output != NULL) {
        reason = pl_write_output(a);
    }
    if (reason == PL_REASON_OK && a->canonical != NULL) {
        reason = pl_write_canonical(a);
    }
    if (reason == PL_REASON_OK && a->trace != NULL) {
        reason = pl_write_trace(a, s);
    }
    return reason;
}

static const char *pl_case_name(int kase) {
    if (kase == PL_CASE_OPTION) {
        return "option-chain-greeks";
    }
    return kase == PL_CASE_SCAN ? "record-scan" : "probe";
}

static const char *pl_model_name(size_t m) {
    switch (m) {
    case PL_MODEL_BSM:
        return "bsm";
    case PL_MODEL_BJS:
        return "bjs";
    case PL_MODEL_CRR:
        return "crr";
    case PL_MODEL_BAW:
        return "baw";
    default:
        return "alo";
    }
}

/* The fields up to copied_bytes; returns 1 when a write failed. */
static int pl_print_common(const struct pl_kernel_args *a, const struct pl_kernel_state *s,
                           FILE *out) {
    int bad = fprintf(out, "PLK1 status=OK case=%s", pl_case_name(a->kase)) < 0;
    bad |= fprintf(out, " records=%zu loops=%" PRIu32, a->records, a->loops) < 0;
    bad |= fprintf(out, " threads=%u mono_ns=%" PRIu64, a->threads, s->mono_ns) < 0;
    bad |= fprintf(out, " cpu_ns=%" PRIu64 " chunks=%zu", s->cpu_ns, s->stats.chunks) < 0;
    bad |= fputs(" chunk_sizes=", out) == EOF;
    for (size_t k = 0; k < s->stats.chunks; k++) {
        bad |= fprintf(out, "%s%zu", k == 0u ? "" : ",", *(s->stats.chunk_sizes + k)) < 0;
    }
    bad |= fputs(" chunk_wall_ns=", out) == EOF;
    for (size_t k = 0; k < s->stats.chunks; k++) {
        const uint64_t w = *(s->stats.chunk_wall_ns + k);
        bad |= fprintf(out, "%s%" PRIu64, k == 0u ? "" : ",", w) < 0;
    }
    bad |= fprintf(out, " copied_bytes=%zu", s->copied) < 0;
    return bad;
}

/* One red= part: the status counts, the max IV bits or null, and its index (straight-line
 * count output: the GCC analyzer budget). */
static int pl_print_part(const struct pl_reduction *red, size_t m, FILE *out) {
    const uint64_t *c = *(red->counts + m);
    int bad = fprintf(out, "%s:", pl_model_name(m)) < 0;
    bad |= fprintf(out, "%" PRIu64 ",%" PRIu64 ",%" PRIu64 ",", *c, *(c + 1), *(c + 2)) < 0;
    bad |= fprintf(out, "%" PRIu64 ",%" PRIu64 ",%" PRIu64 ",", *(c + 3), *(c + 4), *(c + 5)) < 0;
    bad |= fprintf(out, "%" PRIu64 ",%" PRIu64 ",%" PRIu64, *(c + 6), *(c + 7), *(c + 8)) < 0;
    const int64_t index = *(red->max_iv_index + m);
    if (index < 0) {
        bad |= fputs(":null", out) == EOF;
    } else {
        bad |= fprintf(out, ":%016" PRIx64, pl_double_bits(*(red->max_iv + m))) < 0;
    }
    bad |= fprintf(out, ":%" PRId64, index) < 0;
    return bad;
}

/* digest= of the option case (batch.md "Kernel digest"): the FNV-1a 64 of the canonical bytes of
 * the last loop (pl_canonical_write into a digest sink), or none when the writer refuses the
 * results (the echo status 255). */
static int pl_print_digest(const struct pl_kernel_args *a, FILE *out) {
    struct pl_sink d = {-1, NULL, 0u, 0u, 0, 0u, 0u};
    if (pl_canonical_write(&d, pl_results, a->records, a->models) != 0) {
        return fputs(" digest=none", out) == EOF;
    }
    return fprintf(out, " digest=%016" PRIx64, pl_sink_fnv(&d)) < 0;
}

/* models=, evals=, red= and digest= of the option case. */
static int pl_print_option(const struct pl_kernel_args *a, const struct pl_kernel_state *s,
                           FILE *out) {
    struct pl_reduction red;
    pl_reduce(pl_results, a->records, a->models, &red);
    int bad = fprintf(out, " models=%u evals=", (unsigned)a->models) < 0;
    const char *sep = "";
    for (size_t m = 0; m < PL_MODELS; m++) {
        if (((unsigned)a->models >> m) & 1u) {
            const uint64_t e = *(s->stats.evals + m);
            bad |= fprintf(out, "%s%s:%" PRIu64, sep, pl_model_name(m), e) < 0;
            sep = ",";
        }
    }
    bad |= fputs(" red=", out) == EOF;
    sep = "";
    for (size_t m = 0; m < PL_MODELS; m++) {
        if (((unsigned)a->models >> m) & 1u) {
            bad |= fputs(sep, out) == EOF;
            bad |= pl_print_part(&red, m, out);
            sep = ";";
        }
    }
    bad |= pl_print_digest(a, out);
    return bad;
}

static int pl_print_summary(const struct pl_kernel_args *a, const struct pl_kernel_state *s,
                            FILE *out) {
    int bad = pl_print_common(a, s, out);
    if (a->kase == PL_CASE_OPTION) {
        bad |= pl_print_option(a, s, out);
    } else if (a->kase == PL_CASE_SCAN) {
        const int64_t oi = s->scan.open_interest;
        bad |= fprintf(out, " count=%" PRIu64 " open_interest=%" PRId64, s->scan.count, oi) < 0;
    } else {
        bad |= fprintf(out, " probe_records=%zu", a->records) < 0;
    }
    bad |= fputs("\n", out) == EOF;
    bad |= fflush(out) == EOF;
    return bad ? PL_REASON_IO : PL_REASON_OK;
}

int pl_kernel_run(const struct pl_kernel_args *a, FILE *out) {
    const size_t bytes = a->records * pl_record_bytes(a->kase);
    int reason = pl_read_input(a->input, bytes);
    if (reason == PL_REASON_OK && a->kase == PL_CASE_PROBE) {
        reason = pl_probe_check(pl_input, a->records);
    }
    if (reason != PL_REASON_OK) {
        return reason;
    }
    struct pl_params p;
    pl_case_params(&p);
    struct pl_kernel_state s = {0};
    s.copied = bytes;
    reason = pl_timed_loops(a, &p, &s, out);
    if (reason == PL_REASON_OK) {
        reason = pl_write_files(a, &s);
    }
    if (reason == PL_REASON_OK) {
        reason = pl_print_summary(a, &s, out);
    }
    return reason;
}
