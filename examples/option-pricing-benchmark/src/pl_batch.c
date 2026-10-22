#include "pl_batch.h"
#include "pl_io.h"
#include "pl_partition.h"
#include "pl_protocol.h"
#include <sc-parallel.h>
#include <stddef.h>
#include <stdint.h>

/* pl_batch_run (specs/project/batch.md "Batch"): the argument checks, the serial loop and the
 * pooled run with one sc_parallel task per Amendment E chunk. Each task writes only the output
 * positions of its chunk and its own per-chunk slots; pl_batch_run reads the slots after
 * sc_parallel_run returns, so no shared counter and no atomic operation exists. */

/* The immutable job of one pooled request, shared by its tasks. */
struct pl_job {
    const struct pl_input *in;
    const struct pl_params *params;
    int echo;
    uint16_t models; /* Amendment G: the request's mask */
    const struct pl_output *out;
    const uint32_t *indices;
    const struct pl_chunk *chunks;
    uint64_t *wall_ns;            /* one slot per chunk */
    int *defect;                  /* one slot per chunk */
    uint64_t (*calls)[PL_MODELS]; /* one row of counters per chunk */
    uint64_t (*evals)[PL_MODELS]; /* one row of counters per chunk */
};

/* Row i of the request through pl_batch_one (src/pl_batch_row.c, opaque to the analyzer). */
static enum pl_eval_error pl_job_row(const struct pl_job *job, size_t i, uint64_t *calls,
                                     uint64_t *evals) {
    const struct pl_params *p = job->params;
    return pl_batch_one(job->in, p, job->echo, job->models, job->out, i, calls, evals);
}

static gboolean pl_chunk_task(gconstpointer shared, gsize task_index, GError **error) {
    const struct pl_job *job = shared;
    (void)error; /* no GError from a pool thread: GLib's error-domain lock races under tsan */
    const struct pl_chunk *c = job->chunks + task_index;
    uint64_t t0 = 0u, t1 = 0u, cpu = 0u;
    uint64_t *calls = *(job->calls + task_index);
    uint64_t *evals = *(job->evals + task_index);
    (void)pl_clock_ns(&t0, &cpu);
    const uint32_t *indices = job->indices + c->offset;
    const struct pl_input *in = job->in;
    const struct pl_params *p = job->params;
    const struct pl_output *out = job->out;
    const int echo = job->echo;
    const uint16_t models = job->models;
    const size_t n = c->count;
    if (pl_batch_chunk(in, p, echo, models, out, indices, n, calls, evals) != PL_EVAL_OK) {
        *(job->defect + task_index) = 1;
        return FALSE; /* the adapter records the failure under its lock (P2-T14-TSAN-01) */
    }
    (void)pl_clock_ns(&t1, &cpu);
    *(job->wall_ns + task_index) = t1 >= t0 ? t1 - t0 : 0u;
    return TRUE;
}

/* 1 when the input kind is known and its data pointer is set. */
static int pl_input_ok(const struct pl_input *in) {
    if (in->kind == PL_INPUT_ROWS) {
        return in->rows != NULL;
    }
    if (in->kind == PL_INPUT_WIRE) {
        return in->wire != NULL;
    }
    if (in->kind != PL_INPUT_COLUMNS) {
        return 0;
    }
    for (size_t c = 0; c < 8u; c++) {
        if (*(in->columns + c) == NULL) {
            return 0;
        }
    }
    return 1;
}

/* 1 when the output kind is known and its data pointer is set. */
static int pl_output_ok(const struct pl_output *out) {
    if (out->kind == PL_OUTPUT_RESULTS) {
        return out->results != NULL;
    }
    return out->kind == PL_OUTPUT_WIRE && out->wire != NULL;
}

/* The argument checks of specs/project/batch.md "Batch", items 1-8. */
static int pl_batch_args_ok(const struct pl_input *in, const struct pl_params *p, uint16_t models,
                            unsigned threads, const struct pl_batch_scratch *scratch,
                            const struct pl_output *out, const struct pl_batch_stats *stats) {
    if (in == NULL || p == NULL || out == NULL || stats == NULL) {
        return 0;
    }
    if (models == 0u || models > PL_MASK_MODELS5 || in->n > PL_REQUEST_LIMIT) {
        return 0;
    }
    if (threads > PL_MAX_WORKERS || !pl_input_ok(in) || !pl_output_ok(out)) {
        return 0;
    }
    const size_t base_max = SIZE_MAX / PL_RESPONSE_RECORD_BYTES - in->n;
    if (in->base > base_max || out->base > base_max || stats->chunks > PL_MAX_CHUNKS) {
        return 0;
    }
    if (threads == 0u) {
        return 1;
    }
    if (scratch == NULL || scratch->perm == NULL || scratch->mark == NULL ||
        scratch->indices == NULL || scratch->cap < in->n) {
        return 0;
    }
    const size_t w = in->n < threads ? in->n : (size_t)threads;
    return stats->chunks + w <= PL_MAX_CHUNKS;
}

/* The job fields that the serial loop and the pooled tasks share. */
static void pl_job_init(struct pl_job *job, const struct pl_input *in, const struct pl_params *p,
                        int echo, uint16_t models, const struct pl_output *out) {
    job->in = in;
    job->params = p;
    job->echo = echo;
    job->models = models;
    job->out = out;
    job->indices = NULL;
    job->chunks = NULL;
    job->wall_ns = NULL;
    job->defect = NULL;
    job->calls = NULL;
    job->evals = NULL;
}

static int pl_batch_serial(const struct pl_job *job, struct pl_batch_stats *stats) {
    for (size_t i = 0; i < job->in->n; i++) {
        if (pl_job_row(job, i, stats->calls, stats->evals) != PL_EVAL_OK) {
            return PL_BATCH_DEFECT;
        }
    }
    return PL_BATCH_OK;
}

/* The per-chunk slots of one pooled request. */
struct pl_slots {
    uint64_t wall_ns[PL_MAX_WORKERS];
    int defect[PL_MAX_WORKERS];
    uint64_t calls[PL_MAX_WORKERS][PL_MODELS];
    uint64_t evals[PL_MAX_WORKERS][PL_MODELS];
};

/* Appends the chunks of one pooled request and adds its counter rows to the stats. */
static void pl_batch_append(const struct pl_chunk *chunks, size_t count,
                            const struct pl_slots *slots, const ScParallelReport *report,
                            struct pl_batch_stats *stats) {
    for (size_t k = 0; k < count; k++) {
        *(stats->chunk_sizes + stats->chunks + k) = (chunks + k)->count;
        *(stats->chunk_wall_ns + stats->chunks + k) = *(slots->wall_ns + k);
        pl_add_counters(stats->calls, *(slots->calls + k));
        pl_add_counters(stats->evals, *(slots->evals + k));
    }
    stats->chunks += count;
    if (report->threads_observed > stats->threads_observed) {
        stats->threads_observed = report->threads_observed;
    }
    if (report->max_inflight_observed > stats->max_inflight) {
        stats->max_inflight = report->max_inflight_observed;
    }
}

static int pl_batch_pooled(struct pl_job *job, unsigned threads, uint64_t request_index,
                           const struct pl_batch_scratch *scratch, struct pl_batch_stats *stats,
                           ScParallelTrace *trace) {
    struct pl_chunk chunks[PL_MAX_WORKERS];
    size_t count = 0u;
    if (pl_request_chunks(job->in->n, threads, request_index, scratch->perm, scratch->mark,
                          scratch->indices, scratch->cap, chunks, &count) != 0) {
        return PL_BATCH_ARGUMENT;
    }
    if (count == 0u) {
        return PL_BATCH_OK;
    }
    struct pl_slots slots = {{0u}, {0}, {{0u}}, {{0u}}};
    job->indices = scratch->indices;
    job->chunks = chunks;
    job->wall_ns = slots.wall_ns;
    job->defect = slots.defect;
    job->calls = slots.calls;
    job->evals = slots.evals;
    const ScParallelConfig config = {threads, 2u * threads};
    ScParallelReport report = {0u, 0u, 0u, 0u, 0u, trace};
    GError *error = NULL;
    const gboolean ok = sc_parallel_run(&config, count, pl_chunk_task, job, &report, &error);
    g_clear_error(&error);
    pl_batch_append(chunks, count, &slots, &report, stats);
    if (ok) {
        return PL_BATCH_OK;
    }
    const int *d = slots.defect; /* the slots of chunks that do not exist stay 0 */
    const int defect = *(d + 0) | *(d + 1) | *(d + 2) | *(d + 3);
    return defect != 0 ? PL_BATCH_DEFECT : PL_BATCH_POOL;
}

int pl_batch_run(const struct pl_input *in, const struct pl_params *p, int echo, uint16_t models,
                 unsigned threads, uint64_t request_index, const struct pl_batch_scratch *scratch,
                 const struct pl_output *out, struct pl_batch_stats *stats,
                 ScParallelTrace *trace) {
    if (!pl_batch_args_ok(in, p, models, threads, scratch, out, stats)) {
        return PL_BATCH_ARGUMENT;
    }
    struct pl_job job;
    pl_job_init(&job, in, p, echo, models, out);
    if (threads == 0u) {
        return pl_batch_serial(&job, stats);
    }
    return pl_batch_pooled(&job, threads, request_index, scratch, stats, trace);
}

int pl_batch_run_untraced(const struct pl_input *in, const struct pl_params *p, int echo,
                          uint16_t models, unsigned threads, uint64_t request_index,
                          const struct pl_batch_scratch *scratch, const struct pl_output *out,
                          struct pl_batch_stats *stats) {
    return pl_batch_run(in, p, echo, models, threads, request_index, scratch, out, stats, NULL);
}
