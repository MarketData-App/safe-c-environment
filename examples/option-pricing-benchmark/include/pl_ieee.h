#pragma once
#include <stdint.h>

/* IEEE-754 binary64 helpers with the Python semantics of optionlab
 * (specs/project/models.md "IEEE helpers" and "Python-semantics helpers"). No helper uses a
 * compiler builtin; only the Python-semantics helpers call libm. */

/* The 64 bits of x (sign, exponent, fraction) as an unsigned integer. */
uint64_t pl_double_bits(double x);
/* The binary64 value whose bits are bits. */
double pl_bits_double(uint64_t bits);
/* +infinity (bits 0x7ff0000000000000). */
double pl_inf(void);
/* The quiet NaN of Python math.nan (bits 0x7ff8000000000000). */
double pl_nan(void);
/* 1 when x is a NaN (x != x), else 0. */
int pl_is_nan(double x);
/* 1 when -DBL_MAX <= x <= DBL_MAX, else 0 (0 for +-inf and NaN). */
int pl_is_finite(double x);
/* x with the sign bit cleared (also for -0.0 and a negative NaN). */
double pl_fabs(double x);
/* (a < b) ? b : a: Python max(a, b) and std::max (a tie and a NaN b keep a). */
double pl_max(double a, double b);
/* QuantLib close(x, y) as optionlab models.close (models.py:88-93). */
int pl_close(double x, double y);
/* Python-semantics helpers (specs/project/models.md "Python-semantics helpers"): each returns
 * the binary64 value of the cited optionlab helper, with IEEE inf and NaN where Python raises. */
/* models._exp (models.py:70-72): exp(x); +inf where math.exp raises OverflowError. */
double pl_exp(double x);
/* models._log (models.py:79-82): log(x) for x > 0.0, -inf for x == 0.0, else NaN. */
double pl_log(double x);
/* models._sqrt (models.py:83-85): sqrt(x) for x >= 0.0, else NaN. */
double pl_sqrt(double x);
/* models._pow (models.py:73-78): +inf for a == 0.0 and b < 0.0, else pow(a, b). */
double pl_pow(double a, double b);
/* math.erfc: glibc erfc(x) (spec 3.4). */
double pl_erfc(double x);
/* models._sq (models.py:86): x * x. */
double pl_sq(double x);
/* A Python float division a / b outside models._guard: returns the IEEE-754 a / b and sets
 * *defect = 1 when b == 0.0 (both zeros; Python raises ZeroDivisionError for every a, NaN
 * included). *defect is never cleared. */
double pl_py_div(double a, double b, int *defect);
/* The Python sums a + b, a + b + c and a + b + c + d, left to right: (a + b) + c and
 * ((a + b) + c) + d. A Python a - b is pl_sum2(a, -b): IEEE-754 defines a - b as a + (-b), so the
 * bits are equal, signed zeros included, except the sign of a NaN result (never read).
 * A function of another translation unit, so that the GCC analyzer sees an opaque result and
 * the BlackCalculator and Bjerksund-Stensland expressions stay within its fixed symbolic-depth
 * budget. */
double pl_sum2(double a, double b);
double pl_sum3(double a, double b, double c);
double pl_sum4(double a, double b, double c, double d);
