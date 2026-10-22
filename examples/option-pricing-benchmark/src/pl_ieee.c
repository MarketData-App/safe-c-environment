/* Transcribed from QuantLib 1.43 (QL_VERSION 1.43; retained source
 * benchmarks/project/third_party/sources/QuantLib-1.43.tar.gz, sha256
 * b41206ccc4ba39b5e86bdc940d51138222b352f79d2c6fc68649f9c9bbe58701), via optionlab/models.py lines
 * 88-93: ql/math/comparison.hpp 59-76. The Python-semantics helpers mirror optionlab/models.py
 * lines 70-86 and pl_py_div the raise point of a Python float division (optionlab code; no
 * QuantLib source). QuantLib license (BSD-3-Clause): the copyright notices, conditions and
 * disclaimer are in NOTICE-QuantLib.md of this example (LR-EX 2026-10-18). */
#include "pl_ieee.h"
#include "pl_types.h"
#include <float.h>
#include <math.h>
#include <stdint.h>

/* IEEE-754 binary64 helpers (specs/project/models.md "IEEE helpers"). Bit access
 * reads the other member of a union, which C17 defines (6.5.2.3, footnote 97). */
union pl_bits {
    uint64_t u;
    double d;
};

uint64_t pl_double_bits(double x) {
    union pl_bits b;
    b.d = x;
    return b.u;
}

double pl_bits_double(uint64_t bits) {
    union pl_bits b;
    b.u = bits;
    return b.d;
}

double pl_inf(void) { return pl_bits_double(UINT64_C(0x7ff0000000000000)); }

double pl_nan(void) { return pl_bits_double(UINT64_C(0x7ff8000000000000)); }

int pl_is_nan(double x) { return x != x; }

int pl_is_finite(double x) { return x >= -DBL_MAX && x <= DBL_MAX; }

double pl_fabs(double x) {
    return pl_bits_double(pl_double_bits(x) & UINT64_C(0x7fffffffffffffff));
}

double pl_max(double a, double b) { return (a < b) ? b : a; }

/* models.close (models.py:88-93), QuantLib close(x, y) (math/comparison.hpp:59-76). */
int pl_close(double x, double y) {
    if (x == y) {
        return 1;
    }
    const double diff = pl_fabs(x - y);
    const double tolerance = 42.0 * PL_QL_EPSILON;
    if (x == 0.0 || y == 0.0) {
        return diff < tolerance * tolerance;
    }
    return diff <= tolerance * pl_fabs(x) && diff <= tolerance * pl_fabs(y);
}

/* Python-semantics helpers (specs/project/models.md "Python-semantics helpers"). Python raises
 * where these return the IEEE-754 result; models.py:70-86 return the same values. */
double pl_exp(double x) { return exp(x); }

double pl_log(double x) {
    if (x > 0.0) {
        return log(x);
    }
    if (x == 0.0) {
        return -pl_inf();
    }
    return pl_nan();
}

double pl_sqrt(double x) {
    if (x >= 0.0) {
        return sqrt(x);
    }
    return pl_nan();
}

/* math.pow raises ValueError for 0.0 or -0.0 to a negative power; _pow gives +inf (glibc pow
 * gives -inf for -0.0 to a negative odd integer). Every other case, including the overflow sign
 * and the NaN of a negative base with a non-integer exponent, is the value of glibc pow. */
double pl_pow(double a, double b) {
    if (a == 0.0 && b < 0.0) {
        return pl_inf();
    }
    return pow(a, b);
}

double pl_erfc(double x) { return erfc(x); }

double pl_sq(double x) { return x * x; }

/* The raise point of a Python float division: the divisor is +-0.0. The quotient is the IEEE
 * result; the caller does not use it once *defect is set (Python has raised). */
double pl_py_div(double a, double b, int *defect) {
    if (b == 0.0) {
        *defect = 1;
    }
    return a / b;
}

double pl_sum2(double a, double b) { return a + b; }

double pl_sum3(double a, double b, double c) { return a + b + c; }

double pl_sum4(double a, double b, double c, double d) { return a + b + c + d; }
