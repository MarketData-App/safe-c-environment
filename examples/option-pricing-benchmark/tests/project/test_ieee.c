#include "pl_ieee.h"
#include "pl_types.h"
#include "pl_vec_helpers.h"
#include <float.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

/* Boundary tests derived from specs/project/models.md "IEEE helpers".
 * REQUIRE stays active under NDEBUG. */
#define REQUIRE_FAIL(c) (fprintf(stderr, "%s:%d: REQUIRE %s\n", __FILE__, __LINE__, #c), exit(1))
#define REQUIRE(c) ((c) ? (void)0 : REQUIRE_FAIL(c))

static void bits(void) {
    REQUIRE(pl_double_bits(1.0) == UINT64_C(0x3ff0000000000000));
    REQUIRE(pl_double_bits(-0.0) == UINT64_C(0x8000000000000000));
    REQUIRE(pl_bits_double(UINT64_C(0x4014000000000000)) == 5.0);
    REQUIRE(pl_double_bits(pl_inf()) == UINT64_C(0x7ff0000000000000));
    REQUIRE(pl_double_bits(pl_nan()) == UINT64_C(0x7ff8000000000000));
    REQUIRE(pl_double_bits(pl_bits_double(UINT64_C(0x0000000000000001))) == UINT64_C(1));
    puts("PASS bits");
}

static void classify(void) {
    double inf = pl_inf();
    REQUIRE(pl_is_nan(pl_nan()) && !pl_is_nan(inf));
    REQUIRE(!pl_is_nan(0.0) && !pl_is_nan(-DBL_MAX));
    REQUIRE(pl_is_finite(0.0) && pl_is_finite(-0.0));
    REQUIRE(pl_is_finite(DBL_MAX) && pl_is_finite(-DBL_MAX));
    REQUIRE(pl_is_finite(DBL_MIN) && pl_is_finite(pl_bits_double(UINT64_C(1))));
    REQUIRE(!pl_is_finite(inf) && !pl_is_finite(-inf) && !pl_is_finite(pl_nan()));
    REQUIRE(pl_double_bits(pl_fabs(-0.0)) == UINT64_C(0));
    REQUIRE(pl_fabs(-2.5) == 2.5 && pl_fabs(-inf) == inf);
    const double negative_nan = pl_bits_double(UINT64_C(0xfff8000000000000));
    REQUIRE(pl_double_bits(pl_fabs(negative_nan)) == UINT64_C(0x7ff8000000000000));
    puts("PASS classify");
}

static void max_and_close(void) {
    REQUIRE(pl_max(1.0, 2.0) == 2.0 && pl_max(2.0, 1.0) == 2.0);
    /* A tie keeps a. */
    REQUIRE(pl_double_bits(pl_max(0.0, -0.0)) == UINT64_C(0));
    REQUIRE(pl_double_bits(pl_max(-0.0, 0.0)) == UINT64_C(0x8000000000000000));
    /* Python max(a, b) and std::max: a NaN on either side keeps a. */
    REQUIRE(pl_is_nan(pl_max(pl_nan(), 1.0)) && pl_max(1.0, pl_nan()) == 1.0);
    REQUIRE(pl_close(1.0, 1.0) && pl_close(0.0, 0.0));
    /* (42 eps)^2 = 8.69e-29; y == 0 takes the same branch as x == 0. */
    REQUIRE(pl_close(0.0, 1e-29) && !pl_close(0.0, 1e-28));
    REQUIRE(pl_close(1e-29, 0.0) && !pl_close(1e-28, 0.0));
    REQUIRE(pl_close(1.0, 1.0 + 4.0 * PL_QL_EPSILON));
    REQUIRE(!pl_close(1.0, 1.0 + 64.0 * PL_QL_EPSILON));
    /* The tolerance uses |x| and |y|: 84 eps from 2.0 is within 42 eps * |2.0| but not within
     * 42 eps * |2.0 - 84 eps|, in either argument order. */
    REQUIRE(!pl_close(2.0, 2.0 - 84.0 * PL_QL_EPSILON));
    REQUIRE(!pl_close(2.0 - 84.0 * PL_QL_EPSILON, 2.0));
    REQUIRE(pl_close(-1.0, -1.0 - 4.0 * PL_QL_EPSILON) && !pl_close(-1.0, 1.0));
    REQUIRE(!pl_close(pl_nan(), pl_nan()));
    puts("PASS max-close");
}

/* No excess precision (the FLT_EVAL_METHOD == 0 property, checked at run time because the
 * source policy rejects a macro whose value differs between build configurations):
 * 1 + 2^-53 rounds to 1 in binary64. The operands come from another translation unit. */
static void precision(void) {
    const double one = pl_bits_double(UINT64_C(0x3ff0000000000000));
    const double half_ulp = pl_bits_double(UINT64_C(0x3ca0000000000000));
    REQUIRE((one + half_ulp) - one == 0.0);
    puts("PASS precision");
}

/* Python-semantics helpers (models.py:70-86): the IEEE result where Python raises. */
static void helpers(void) {
    double inf = pl_inf();
    const uint64_t qnan = UINT64_C(0x7ff8000000000000);
    REQUIRE(pl_exp(1000.0) == inf && pl_exp(-1000.0) == 0.0 && pl_exp(0.0) == 1.0);
    REQUIRE(pl_is_nan(pl_exp(pl_nan())));
    REQUIRE(pl_log(0.0) == -inf && pl_log(-0.0) == -inf && pl_double_bits(pl_log(-1.0)) == qnan);
    REQUIRE(pl_double_bits(pl_log(pl_nan())) == qnan && pl_double_bits(pl_log(-inf)) == qnan);
    REQUIRE(pl_log(inf) == inf && pl_log(1.0) == 0.0);
    REQUIRE(pl_sqrt(4.0) == 2.0 && pl_double_bits(pl_sqrt(-0.0)) == UINT64_C(0x8000000000000000));
    REQUIRE(pl_double_bits(pl_sqrt(-1.0)) == qnan && pl_double_bits(pl_sqrt(-inf)) == qnan);
    REQUIRE(pl_double_bits(pl_sqrt(pl_nan())) == qnan && pl_sqrt(inf) == inf);
    /* math.pow raises for a zero base and a negative exponent; _pow gives +inf for both zeros. */
    REQUIRE(pl_pow(0.0, -1.0) == inf && pl_pow(-0.0, -1.0) == inf && pl_pow(-0.0, -2.0) == inf);
    REQUIRE(pl_pow(0.0, -inf) == inf && pl_pow(0.0, 2.0) == 0.0 && pl_pow(2.0, -1.0) == 0.5);
    /* Overflow: the sign of the Python OverflowError branch. */
    REQUIRE(pl_pow(-2.0, 1025.0) == -inf && pl_pow(-2.0, 1024.0) == inf);
    REQUIRE(pl_pow(2.0, 1024.0) == inf);
    REQUIRE(pl_is_nan(pl_pow(-2.0, 0.5)) && pl_pow(pl_nan(), 0.0) == 1.0);
    REQUIRE(pl_pow(1.0, pl_nan()) == 1.0);
    REQUIRE(pl_erfc(0.0) == 1.0 && pl_erfc(inf) == 0.0 && pl_erfc(-inf) == 2.0);
    REQUIRE(pl_sq(-3.0) == 9.0 && pl_sq(1e200) == inf);
    puts("PASS helpers");
}

/* pl_py_div: the Python ZeroDivisionError point is exactly a zero divisor (both signs), for every
 * numerator; the smallest subnormal divisors (one past zero) do not raise. */
static void py_div(void) {
    const double inf = pl_inf();
    const double tiny = pl_bits_double(UINT64_C(1));
    int defect = 0;
    REQUIRE(pl_py_div(1.0, 4.0, &defect) == 0.25 && defect == 0);
    REQUIRE(pl_py_div(1.0, tiny, &defect) == inf && defect == 0);
    REQUIRE(pl_py_div(-1.0, -tiny, &defect) == inf && defect == 0);
    REQUIRE(pl_py_div(0.0, inf, &defect) == 0.0 && defect == 0);
    REQUIRE(pl_is_nan(pl_py_div(pl_nan(), 2.0, &defect)) && defect == 0);
    REQUIRE(pl_is_nan(pl_py_div(1.0, pl_nan(), &defect)) && defect == 0);
    const double numerators[5] = {1.0, -1.0, 0.0, inf, pl_nan()};
    for (size_t i = 0; i < 5u; i++) {
        const double a = *(numerators + i);
        int plus = 0;
        int minus = 0;
        (void)pl_py_div(a, 0.0, &plus);
        (void)pl_py_div(a, -0.0, &minus);
        REQUIRE(plus == 1 && minus == 1);
    }
    /* The quotient is the IEEE result, and a set defect stays set. */
    defect = 0;
    REQUIRE(pl_py_div(1.0, 0.0, &defect) == inf && defect == 1);
    REQUIRE(pl_py_div(1.0, -0.0, &defect) == -inf && defect == 1);
    REQUIRE(pl_is_nan(pl_py_div(0.0, 0.0, &defect)) && defect == 1);
    REQUIRE(pl_py_div(3.0, 2.0, &defect) == 1.5 && defect == 1);
    puts("PASS py-div");
}

/* pl_sum2, pl_sum3, pl_sum4: left to right. With h = 2^-53, (1 + h) + h rounds to 1.0 at each
 * step (a tie to even), while 1 + (h + h) would be 1 + 2^-52. pl_sum2(a, -b) has the bits of
 * a - b, signed zeros included, except the sign of a NaN result (a NaN compares as any NaN). */
static void sums(void) {
    const double h = pl_bits_double(UINT64_C(0x3ca0000000000000));
    REQUIRE(pl_sum3(1.0, h, h) == 1.0 && pl_sum4(1.0, h, h, h) == 1.0);
    /* (h + h) + 1 is 1 + 2^-52; ((h + h) + h) + 1 is 1 + 1.5 * 2^-52, a tie to 1 + 2^-51. */
    REQUIRE(pl_sum3(h, h, 1.0) == 1.0 + 2.0 * h && pl_sum4(h, h, h, 1.0) == 1.0 + 4.0 * h);
    REQUIRE(pl_sum3(1.0, 2.0, 3.0) == 6.0 && pl_sum4(1.0, 2.0, 3.0, 4.0) == 10.0);
    REQUIRE(pl_is_nan(pl_sum3(pl_inf(), -pl_inf(), 1.0)) && pl_sum4(-0.0, -0.0, -0.0, -0.0) == 0.0);
    REQUIRE(pl_double_bits(pl_sum4(-0.0, -0.0, -0.0, -0.0)) == UINT64_C(0x8000000000000000));
    REQUIRE(pl_sum2(1.0, h) == 1.0 && pl_sum2(h, 1.0) == 1.0 && pl_sum2(1.0, 2.0 * h) > 1.0);
    REQUIRE(pl_double_bits(pl_sum2(-0.0, -0.0)) == UINT64_C(0x8000000000000000));
    REQUIRE(pl_double_bits(pl_sum2(0.0, -0.0)) == UINT64_C(0x0000000000000000));
    REQUIRE(pl_is_nan(pl_sum2(pl_inf(), -pl_inf())) && pl_sum2(pl_inf(), 1.0) == pl_inf());
    puts("PASS sums");
}

/* Equal bits, or both NaN (the vector comparison rule). */
static int same_bits(double got, uint64_t want) {
    return pl_double_bits(got) == want || (pl_is_nan(got) && pl_is_nan(pl_bits_double(want)));
}

/* pl_exp, pl_log and pl_sqrt against models._exp, _log and _sqrt (PL_VEC_HELPERS, generated by the
 * check c-vectors part helpers): subnormal inputs and subnormal or zero exp results included. */
static void helper_vectors(void) {
    for (size_t i = 0; i < PL_VEC_HELPERS_COUNT; i++) {
        const struct pl_vec_helpers *v = PL_VEC_HELPERS + i;
        const double x = pl_bits_double(v->x);
        REQUIRE(same_bits(pl_exp(x), v->exp));
        REQUIRE(same_bits(pl_log(x), v->log));
        REQUIRE(same_bits(pl_sqrt(x), v->sqrt));
    }
    puts("PASS helper-vectors");
}

int main(void) {
    _Static_assert(sizeof(double) == 8, "binary64 double");
    precision();
    bits();
    classify();
    max_and_close();
    helpers();
    py_div();
    sums();
    helper_vectors();
    return 0;
}
