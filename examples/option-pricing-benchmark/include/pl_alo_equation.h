#pragma once
#include <stddef.h>

/* The shared Andersen-Lake-Offengenden equation choice and segment of a point (spec Amendment I
 * items I2.4 and I2.6; Appendix I-ALO R4) as optionlab.alo_equation computes them
 * (specs/project/models.md "ALO (Amendment I)"). One C function per Python function, with the
 * same operation order, association and constants (Amendment F item 8). Pure functions; the only
 * memory they touch is the caller's output objects. */

/* The fixed-point equations of QdFpAmericanEngine (alo_equation.FP_A and FP_B). */
enum pl_alo_equation { PL_ALO_FP_A = 0, PL_ALO_FP_B = 1 };

/* alo_equation.SWITCH (qdfpamericanengine.cpp:457): Auto chooses FP-A iff
 * std::abs(r - q) < 0.001. */
#define PL_ALO_AUTO_THRESHOLD 0.001

/* The capacity of struct pl_alo_rates values. */
#define PL_ALO_EQUATION_MAX_FIELDS 8u

/* The intermediates of pl_alo_equation in values (cvectors.ALO_EQUATION_FIELDS): D_r and D_q
 * (1.0 / exp(x * 1.0)), the read-back rates r_e and q_e (-log(D) / 1.0) and the operand
 * fabs(r_e - q_e) of the Auto test. */
enum pl_alo_rates_field {
    PL_ALO_R_DR = 0,
    PL_ALO_R_DQ = 1,
    PL_ALO_R_RE = 2,
    PL_ALO_R_QE = 3,
    PL_ALO_R_ABS_DIFF = 4
};
#define PL_ALO_RATES_FIELDS 5u

/* The result of pl_alo_equation. defect is 1 where Python raises: read_back divides 1.0 by an
 * exponential of 0.0 (ZeroDivisionError); equation is then -1 and every value pl_nan(). count is
 * PL_ALO_RATES_FIELDS. */
struct pl_alo_rates {
    int equation;
    int defect;
    size_t count;
    double values[PL_ALO_EQUATION_MAX_FIELDS];
};

/* The segment of a point (alo_equation.alo_segment): equation, the European edge test
 * r <= 0 && r <= q (qdplusamericanengine.cpp:207), the double-boundary test r < 0 && q < r
 * (qdfpamericanengine.cpp:432), the xMax case 1-7 of qdplusamericanengine.cpp:235-249 (0 for
 * its QL_FAIL "internal error") and, in case 1, the test r / q < 1.0 (qdplusamericanengine.cpp:236;
 * -1 for Python None in the other cases), all on the calculatePut rates (put: (r_e, q_e); call:
 * (q_e, r_e)). defect is 1 where Python raises (read_back: ZeroDivisionError; side_index: a side
 * other than 0 and 1, ValueError); every other member is then -1 or 0 as pl_alo_segment states. */
struct pl_alo_segment {
    int equation;
    int european_edge;
    int double_boundary;
    int xmax_case;
    int r_over_q_below_one;
    int defect;
};

/* alo_equation.read_back (alo_equation.py:33-40): D_r = 1.0 / exp(r1 * 1.0), D_q =
 * 1.0 / exp(q1 * 1.0), r_e = -log(D_r) / 1.0, q_e = -log(D_q) / 1.0, with models._exp and
 * models._log. *defect = 1 when an exponential is 0.0 (the Python division raises); the outputs
 * then hold the IEEE results. *defect is only set. */
void pl_alo_read_back(double r1, double q1, double *d_r, double *d_q, double *r_e, double *q_e,
                      int *defect);

/* The Auto test of alo_equation.alo_equation on read-back rates: PL_ALO_FP_A iff
 * fabs(r_e - q_e) < PL_ALO_AUTO_THRESHOLD, else PL_ALO_FP_B (a NaN difference is FP-B). */
int pl_alo_equation_of(double r_e, double q_e);

/* alo_equation.alo_equation (alo_equation.py:42-46) with every intermediate in out->values. */
void pl_alo_equation(double r1, double q1, struct pl_alo_rates *out);

/* alo_equation._xmax_case (alo_equation.py:48-59): the xMax case of the calculatePut rates. */
int pl_alo_xmax_case(double r, double q);

/* alo_equation.alo_segment (alo_equation.py:61-69) of a call (side 0) or a put (side 1). On a
 * defect: equation -1, the tests 0, xmax_case 0, r_over_q_below_one -1. */
void pl_alo_segment(int side, double r1, double q1, struct pl_alo_segment *out);

/* Python tuple equality of two alo_segment results: 1 when every member is equal. */
int pl_alo_segment_equal(const struct pl_alo_segment *a, const struct pl_alo_segment *b);
