#include "bd_spread.h"

#include <sc-parallel.h>

/* The threaded coverage fixture (specs/project/bd_spread.md). The job is read-only for the tasks;
 * each task writes only its own output word. No task sets a GError. */

struct bd_spread_job {
    uint64_t seed;
    uint32_t steps;
    uint64_t *out;
};

/* The product modulo 2^64: __builtin_mul_overflow stores the wrapped value, and its overflow
 * flag is not an error here. A plain multiplication would trap the integer gate's
 * unsigned-integer-overflow check. */
static uint64_t bd_spread_mul(uint64_t a, uint64_t b) {
    uint64_t product = 0U;
    (void)__builtin_mul_overflow(a, b, &product);
    return product;
}

static uint64_t bd_spread_digest(uint64_t seed, uint64_t task, uint32_t steps) {
    uint64_t state = seed ^ bd_spread_mul(task, UINT64_C(0x9e3779b97f4a7c15));
    if (state == 0U) {
        state = UINT64_C(0x9e3779b97f4a7c15);
    }
    uint64_t hash = UINT64_C(0xcbf29ce484222325);
    for (uint32_t step = 0U; step < steps; ++step) {
        state ^= state << 13U;
        state ^= state >> 7U;
        state ^= state << 17U;
        if (step + 1U != steps) {
            hash = bd_spread_mul(hash ^ state, UINT64_C(0x100000001b3));
        } else {
            hash = bd_spread_mul(hash ^ state ^ task, UINT64_C(0x100000001b3));
        }
    }
    return hash;
}

static gboolean bd_spread_task(gconstpointer shared, gsize task_index, GError **error) {
    (void)error; /* no GError from a pool thread */
    const struct bd_spread_job *job = shared;
    *(job->out + task_index) = bd_spread_digest(job->seed, (uint64_t)task_index, job->steps);
    return TRUE;
}

static int bd_spread_args_ok(uint32_t tasks, uint32_t steps, uint32_t workers, const uint64_t *out,
                             size_t out_len) {
    if (out == NULL) {
        return 0;
    }
    if (tasks == 0U || tasks > (uint32_t)BD_SPREAD_MAX_TASKS) {
        return 0;
    }
    if (steps == 0U || steps > (uint32_t)BD_SPREAD_MAX_STEPS) {
        return 0;
    }
    if (workers > (uint32_t)BD_SPREAD_MAX_WORKERS) {
        return 0;
    }
    return out_len >= (size_t)tasks;
}

int bd_spread_run(uint64_t seed, uint32_t tasks, uint32_t steps, uint32_t workers, uint64_t *out,
                  size_t out_len) {
    if (!bd_spread_args_ok(tasks, steps, workers, out, out_len)) {
        return BD_SPREAD_BAD_ARGUMENT;
    }
    if (workers == 0U) {
        for (uint32_t task = 0U; task < tasks; ++task) {
            *(out + task) = bd_spread_digest(seed, (uint64_t)task, steps);
        }
        return BD_SPREAD_OK;
    }
    const struct bd_spread_job job = {seed, steps, out};
    const ScParallelConfig config = {workers, 2U * workers};
    ScParallelReport report = {0U, 0U, 0U, 0U, 0U, NULL};
    const gsize count = (gsize)tasks;
    GError *error = NULL;
    const gboolean ok = sc_parallel_run(&config, count, bd_spread_task, &job, &report, &error);
    g_clear_error(&error);
    return ok ? BD_SPREAD_OK : BD_SPREAD_POOL;
}
