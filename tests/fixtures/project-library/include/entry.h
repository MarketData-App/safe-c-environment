#pragma once

#include <stddef.h>

/* Framework fixture for the project "libraries" field (specs/project/entry.md). */

enum { FIXTURE_ENTRY_MAX = 64 };

/* Writes the sum of x[0] .. x[n - 1], added in index order, to *out and returns 0.
 * Returns 1 and leaves *out unchanged when x or out is NULL or n is outside
 * [1, FIXTURE_ENTRY_MAX]; then it reads no element of x. The caller owns x and out. */
int fixture_entry(const double *x, size_t n, double *out);

/* Program logic of fixture-run. Returns 0 when argv is exactly {program,
 * "--self-check"} and fixture_entry sums {1.0, 2.0, 3.5} to 6.5; 1 when that
 * check fails; 2 for any other argument list, including a NULL argv or argument. */
int fixture_run(int argc, char **argv);
