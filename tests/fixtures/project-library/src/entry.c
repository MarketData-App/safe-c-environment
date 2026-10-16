#include "entry.h"

#include <stddef.h>

int fixture_entry(const double *x, size_t n, double *out) {
    if (x == NULL || out == NULL || n < 1U || n > (size_t)FIXTURE_ENTRY_MAX) {
        return 1;
    }
    double sum = 0.0;
    for (size_t index = 0U; index < n; ++index) {
        sum += *(x + index);
    }
    *out = sum;
    return 0;
}

/* Returns 1 when arg is exactly "--self-check". The scan stops at the first
 * differing byte, so it never reads past the NUL of a shorter argument. */
static int is_self_check(const char *arg) {
    static const char want[] = "--self-check";
    if (arg == NULL) {
        return 0;
    }
    for (size_t index = 0U; index < sizeof want; ++index) {
        if (*(arg + index) != *(want + index)) {
            return 0;
        }
    }
    return 1;
}

int fixture_run(int argc, char **argv) {
    if (argc != 2 || argv == NULL || is_self_check(*(argv + 1)) == 0) {
        return 2;
    }
    const double values[3] = {1.0, 2.0, 3.5};
    double sum = 0.0;
    const int status = fixture_entry(values, 3U, &sum);
    /* Both checks always run, so the result has no branch. */
    return status | (int)(sum != 6.5);
}
