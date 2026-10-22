/* Transcribed from QuantLib 1.43 (QL_VERSION 1.43; retained source
 * benchmarks/project/third_party/sources/QuantLib-1.43.tar.gz, sha256
 * b41206ccc4ba39b5e86bdc940d51138222b352f79d2c6fc68649f9c9bbe58701), via
 * optionlab/alo_equation.py lines 33-69 (merged G-ALO2 part A, commit 490dce1):
 * ql/termstructures/yield/flatforward.hpp 102-104, ql/interestrate.cpp 53-54,
 * ql/pricingengines/vanilla/qdplusamericanengine.cpp 182-183, 190-193, 207, 231-251 and
 * ql/pricingengines/vanilla/qdfpamericanengine.cpp 432, 455-463 (spec Appendix I-ALO R4).
 * QuantLib license (BSD-3-Clause): the copyright notices, conditions and disclaimer are in
 * NOTICE-QuantLib.md of this example (LR-EX 2026-10-18). */
#include "pl_alo_equation.h"
#include "pl_ieee.h"
#include <stddef.h>

/* The equation choice and the segment of a point (specs/project/models.md "ALO (Amendment I)").
 * Each function copies the cited optionlab statements in order; models._exp and models._log are
 * pl_exp and pl_log, math.fabs is pl_fabs, the Python division 1.0 / x is pl_py_div (a zero x
 * raises ZeroDivisionError: the defect output), -log(D) / 1.0 is an IEEE division by 1.0. */

void pl_alo_read_back(double r1, double q1, double *d_r, double *d_q, double *r_e, double *q_e,
                      int *defect) {
    *d_r = pl_py_div(1.0, pl_exp(r1 * 1.0), defect);
    *d_q = pl_py_div(1.0, pl_exp(q1 * 1.0), defect);
    *r_e = -pl_log(*d_r) / 1.0;
    *q_e = -pl_log(*d_q) / 1.0;
}

int pl_alo_equation_of(double r_e, double q_e) {
    return (pl_fabs(r_e - q_e) < PL_ALO_AUTO_THRESHOLD) ? PL_ALO_FP_A : PL_ALO_FP_B;
}

void pl_alo_equation(double r1, double q1, struct pl_alo_rates *out) {
    const double nan = pl_nan();
    /* every slot NaN (straight-line code: a loop here exceeds the fixed GCC analyzer budget) */
    *(out->values + 0) = nan;
    *(out->values + 1) = nan;
    *(out->values + 2) = nan;
    *(out->values + 3) = nan;
    *(out->values + 4) = nan;
    *(out->values + 5) = nan;
    *(out->values + 6) = nan;
    *(out->values + 7) = nan;
    out->count = PL_ALO_RATES_FIELDS;
    out->defect = 0;
    out->equation = -1;
    double d_r = nan;
    double d_q = nan;
    double r_e = nan;
    double q_e = nan;
    int defect = 0;
    pl_alo_read_back(r1, q1, &d_r, &d_q, &r_e, &q_e, &defect);
    if (defect != 0) {
        out->defect = 1; /* read_back raises; Python computes no intermediate */
        return;
    }
    *(out->values + PL_ALO_R_DR) = d_r;
    *(out->values + PL_ALO_R_DQ) = d_q;
    *(out->values + PL_ALO_R_RE) = r_e;
    *(out->values + PL_ALO_R_QE) = q_e;
    *(out->values + PL_ALO_R_ABS_DIFF) = pl_fabs(r_e - q_e);
    out->equation = pl_alo_equation_of(r_e, q_e);
}

int pl_alo_xmax_case(double r, double q) {
    if (r > 0.0 && q > 0.0) {
        return 1;
    }
    if (r > 0.0 && q <= 0.0) {
        return 2;
    }
    if (r == 0.0 && q < 0.0) {
        return 3;
    }
    if (r == 0.0 && q >= 0.0) {
        return 4;
    }
    if (r < 0.0 && q >= 0.0) {
        return 5;
    }
    if (r < 0.0 && q < r) {
        return 6;
    }
    if (r < 0.0 && r <= q && q < 0.0) {
        return 7;
    }
    return 0;
}

/* The defect result of alo_segment. */
static void segment_defect(struct pl_alo_segment *out) {
    out->equation = -1;
    out->european_edge = 0;
    out->double_boundary = 0;
    out->xmax_case = 0;
    out->r_over_q_below_one = -1;
    out->defect = 1;
}

void pl_alo_segment(int side, double r1, double q1, struct pl_alo_segment *out) {
    if (side != 0 && side != 1) {
        segment_defect(out); /* side_index raises ValueError */
        return;
    }
    double d_r = 0.0;
    double d_q = 0.0;
    double r_e = 0.0;
    double q_e = 0.0;
    int defect = 0;
    pl_alo_read_back(r1, q1, &d_r, &d_q, &r_e, &q_e, &defect);
    if (defect != 0) {
        segment_defect(out);
        return;
    }
    const double rr = (side == 1) ? r_e : q_e;
    const double qq = (side == 1) ? q_e : r_e;
    const int xcase = pl_alo_xmax_case(rr, qq);
    out->equation = pl_alo_equation_of(r_e, q_e);
    out->european_edge = rr <= 0.0 && rr <= qq;
    out->double_boundary = rr < 0.0 && qq < rr;
    out->xmax_case = xcase;
    out->r_over_q_below_one = (xcase == 1) ? (rr / qq < 1.0) : -1;
    out->defect = 0;
}

int pl_alo_segment_equal(const struct pl_alo_segment *a, const struct pl_alo_segment *b) {
    const int first = (a->equation == b->equation) & (a->european_edge == b->european_edge);
    const int second = (a->double_boundary == b->double_boundary) & (a->xmax_case == b->xmax_case);
    const int third = (a->r_over_q_below_one == b->r_over_q_below_one) & (a->defect == b->defect);
    return first & second & third;
}
