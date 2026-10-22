#ifndef BD_SPREAD_H
#define BD_SPREAD_H
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
/* The threaded fixture of the framework coverage gate (finding P2-COV-ATOMIC-01) and the pool
 * trace program bd-spread (framework bench case B04). The full contract is
 * specs/project/bd_spread.md. */
enum { BD_SPREAD_MAX_TASKS = 64, BD_SPREAD_MAX_STEPS = 1000000, BD_SPREAD_MAX_WORKERS = 4 };
enum { BD_SPREAD_TRACE_STEPS = 100000 };
/* Return values of bd_spread_run and bd_spread_trace. */
enum bd_spread_rc { BD_SPREAD_OK = 0, BD_SPREAD_BAD_ARGUMENT = 1, BD_SPREAD_POOL = 2 };
/* Writes the task digest of each task t in [0, tasks) to out[t]. tasks must be in [1, 64], steps
 * in [1, 1,000,000], workers in [0, 4] (0: the caller thread) and out_len at least tasks. */
int bd_spread_run(uint64_t seed, uint32_t tasks, uint32_t steps, uint32_t workers, uint64_t *out,
                  size_t out_len);

/* One pool trace entry: the pool thread tag, the monotonic start and end of the task, the
 * thread CPU time of the task and the task index. */
struct bd_spread_span {
    uint64_t start_ns;
    uint64_t end_ns;
    uint64_t cpu_ns;
    uint32_t thread;
    uint32_t task;
};

/* The pool report of one bd_spread_trace call. */
struct bd_spread_report {
    uint64_t submitted;
    uint64_t executed;
    uint64_t max_inflight;
    uint32_t threads;
};

/* bd_spread_run through the pool (workers in [1, 4]) with the trace: spans[0, tasks) and *report
 * (span_len at least tasks). */
int bd_spread_trace(uint64_t seed, uint32_t tasks, uint32_t steps, uint32_t workers, uint64_t *out,
                    size_t out_len, struct bd_spread_span *spans, size_t span_len,
                    struct bd_spread_report *report);

/* The program logic of bd-spread: no argument; the serial run and the traced runs on 1, 2 and 4
 * workers on out. Returns 0, 2 (usage), 3 (a run failed) or 4 (a write failed). */
int bd_spread_cli_main(int argc, char **argv, FILE *out, FILE *err);
#endif
