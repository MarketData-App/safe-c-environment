#ifndef BD_SPREAD_H
#define BD_SPREAD_H
#include <stddef.h>
#include <stdint.h>
/* The threaded fixture of the framework coverage gate (finding P2-COV-ATOMIC-01). The full
 * contract is specs/project/bd_spread.md. */
enum { BD_SPREAD_MAX_TASKS = 64, BD_SPREAD_MAX_STEPS = 1000000, BD_SPREAD_MAX_WORKERS = 4 };
/* Return values of bd_spread_run. */
enum bd_spread_rc { BD_SPREAD_OK = 0, BD_SPREAD_BAD_ARGUMENT = 1, BD_SPREAD_POOL = 2 };
/* Writes the task digest of each task t in [0, tasks) to out[t]. tasks must be in [1, 64], steps
 * in [1, 1,000,000], workers in [0, 4] (0: the caller thread) and out_len at least tasks. */
int bd_spread_run(uint64_t seed, uint32_t tasks, uint32_t steps, uint32_t workers, uint64_t *out,
                  size_t out_len);
#endif
