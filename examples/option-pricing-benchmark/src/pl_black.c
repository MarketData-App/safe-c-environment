/* Transcribed from QuantLib 1.43 (QL_VERSION 1.43; retained source
 * benchmarks/project/third_party/sources/QuantLib-1.43.tar.gz, sha256
 * b41206ccc4ba39b5e86bdc940d51138222b352f79d2c6fc68649f9c9bbe58701), via optionlab/models.py lines
 * 95-190 and optionlab/mapping.py lines 9-14: ql/termstructures/yield/flatforward.hpp 102-104,
 * ql/interestrate.cpp 53-54, 91-92, ql/termstructures/yieldtermstructure.cpp 30, 118-127,
 * 154-171, ql/termstructures/volatility/equityfx/blackvoltermstructure.hpp 304-308,
 * ql/pricingengines/blackcalculator.cpp 65-428. QuantLib license (BSD-3-Clause): the copyright
 * notices, conditions and disclaimer are in NOTICE-QuantLib.md of this example (LR-EX 2026-10-18).
 * */
#include "pl_black.h"
#include "pl_ieee.h"
#include "pl_normal.h"
#include "pl_types.h"
#include <float.h>

/* Term structure, unit mapping and BlackCalculator (specs/project/models.md "Term structure,
 * mapping and BSM"; the engine is in pl_bsm.c). Each function copies the cited optionlab
 * function statement by statement (spec 3.4; Amendment F item 8). The divisions of discount,
 * zero_rate and forward_rate are Python divisions outside models._guard (pl_py_div: the raise
 * point is a zero divisor). Every division of Black is IEEE C division: models._guard runs the
 * engine again with IEEE division when the plain run raises ZeroDivisionError, and the other
 * operations give the same binary64 results in both runs. */

/* yieldtermstructure.cpp:30 dt = 0.0001 (models.RATE_DT). */
static const double PL_RATE_DT = 0x1.a36e2eb1c432dp-14;

/* models.discount (models.py:96). */
double pl_discount(double rate, double t, int *defect) {
    return pl_py_div(1.0, pl_exp(rate * t), defect);
}

/* models.implied_rate (models.py:97-99). */
double pl_implied_rate(double compound, double t) {
    if (compound == 1.0) {
        return 0.0;
    }
    return pl_log(compound) / t;
}

/* models.zero_rate (models.py:100-103). */
double pl_zero_rate(double rate, double t, int *defect) {
    if (t == 0.0) {
        t = PL_RATE_DT;
    }
    const double d = pl_discount(rate, t, defect);
    return pl_implied_rate(pl_py_div(1.0, d, defect), t);
}

/* models.forward_rate (models.py:104-105): both discounts, in this order, then the quotient.
 * Precondition: not (t2 == t1 and the rate is NaN). Python raises at models.py:99 in that
 * case and this function does not mirror the raise; no caller passes such arguments. */
double pl_forward_rate(double rate, double t1, double t2, int *defect) {
    const double d1 = pl_discount(rate, t1, defect);
    const double d2 = pl_discount(rate, t2, defect);
    return pl_implied_rate(pl_py_div(d1, d2, defect), t2 - t1);
}

/* mapping.unit (mapping.py:9-14). */
void pl_unit(double T, double r, double q, double sigma, double *r1, double *q1, double *s1) {
    *r1 = r * T;
    *q1 = q * T;
    *s1 = sigma * pl_sqrt(T);
}

/* models.mapped_inputs (models.py:187-190). Precondition: T >= 0. For T < 0 Python raises
 * ValueError in math.sqrt (mapping.unit); this function does not mirror it and returns values.
 * The row path cannot reach T < 0: reference.py returns EXPIRED or INVALID_INPUT first. */
void pl_mapped_inputs(double T, double r, double q, double sigma, double *d_r, double *d_q,
                      double *variance, int *defect) {
    double r1;
    double q1;
    double s1;
    pl_unit(T, r, q, sigma, &r1, &q1, &s1);
    *d_r = pl_discount(r1, 1.0, defect);
    *d_q = pl_discount(q1, 1.0, defect);
    *variance = s1 * s1 * 1.0;
}

/* Black.__init__ (models.py:110-130), BlackCalculator setup (blackcalculator.cpp:65-195). */
void pl_black_init(struct pl_black *b, int side, double strike, double forward, double std_dev,
                   double discount) {
    double cum_d1;
    double cum_d2;
    double n_d1;
    double n_d2;
    b->side = side;
    b->strike = strike;
    b->forward = forward;
    b->std_dev = std_dev;
    b->discount = discount;
    b->variance = std_dev * std_dev;
    if (std_dev >= PL_QL_EPSILON) {
        if (pl_close(strike, 0.0)) {
            b->d1 = DBL_MAX;
            b->d2 = DBL_MAX;
            cum_d1 = 1.0;
            cum_d2 = 1.0;
            n_d1 = 0.0;
            n_d2 = 0.0;
        } else {
            b->d1 = pl_log(forward / strike) / std_dev + 0.5 * std_dev;
            b->d2 = b->d1 - std_dev;
            cum_d1 = pl_norm_cdf(b->d1);
            cum_d2 = pl_norm_cdf(b->d2);
            n_d1 = pl_norm_pdf(b->d1);
            n_d2 = pl_norm_pdf(b->d2);
        }
    } else {
        if (pl_close(forward, strike)) {
            b->d1 = 0.0;
            b->d2 = 0.0;
            cum_d1 = 0.5;
            cum_d2 = 0.5;
            n_d1 = PL_M_SQRT_2 * PL_M_1_SQRTPI;
            n_d2 = PL_M_SQRT_2 * PL_M_1_SQRTPI;
        } else if (forward > strike) {
            b->d1 = DBL_MAX;
            b->d2 = DBL_MAX;
            cum_d1 = 1.0;
            cum_d2 = 1.0;
            n_d1 = 0.0;
            n_d2 = 0.0;
        } else {
            b->d1 = -DBL_MAX;
            b->d2 = -DBL_MAX;
            cum_d1 = 0.0;
            cum_d2 = 0.0;
            n_d1 = 0.0;
            n_d2 = 0.0;
        }
    }
    b->x = strike;
    b->dx_dstrike = 1.0;
    b->dx_ds = 0.0;
    if (side == 0) {
        b->alpha = cum_d1;
        b->dalpha_dd1 = n_d1;
        b->beta = -cum_d2;
        b->dbeta_dd2 = -n_d2;
    } else {
        b->alpha = -1.0 + cum_d1;
        b->dalpha_dd1 = n_d1;
        b->beta = 1.0 - cum_d2;
        b->dbeta_dd2 = -n_d2;
    }
}

/* Black.value (models.py:131). */
double pl_black_value(const struct pl_black *b) {
    return b->discount * (b->forward * b->alpha + b->x * b->beta);
}

/* Black._flat (models.py:132-135): the zero-volatility results. Python evaluates all six
 * arguments before the call; they have no side effects. */
static double flat(const struct pl_black *b, double call_atm, double call_itm, double call_otm,
                   double put_atm, double put_itm_put, double put_otm) {
    if (pl_close(b->forward, b->strike)) {
        return b->alpha >= 0.0 ? call_atm : put_atm;
    }
    if (b->forward > b->strike) {
        return b->alpha >= 0.0 ? call_itm : put_itm_put;
    }
    return b->alpha >= 0.0 ? call_otm : put_otm;
}

/* Black.delta (models.py:136-143). */
double pl_black_delta(const struct pl_black *b, double spot) {
    if (b->std_dev <= PL_QL_EPSILON) {
        const double dforward_ds = b->forward / spot;
        const double d = b->discount;
        return flat(b, d * 0.5 * dforward_ds, d * 1.0 * dforward_ds, 0.0, d * (-0.5) * dforward_ds,
                    0.0, d * (-1.0) * dforward_ds);
    }
    const double dforward_ds = b->forward / spot;
    const double temp = b->std_dev * spot;
    const double dalpha_ds = b->dalpha_dd1 / temp;
    const double dbeta_ds = b->dbeta_dd2 / temp;
    const double temp2 =
        dalpha_ds * b->forward + b->alpha * dforward_ds + dbeta_ds * b->x + b->beta * b->dx_ds;
    return b->discount * temp2;
}

/* Black.deltaForward (models.py:144-149). */
double pl_black_delta_forward(const struct pl_black *b) {
    if (b->std_dev <= PL_QL_EPSILON) {
        const double d = b->discount;
        return flat(b, d * 0.5, d * 1.0, 0.0, d * (-0.5), 0.0, d * (-1.0));
    }
    const double temp = b->std_dev * b->forward;
    const double dalpha_dforward = b->dalpha_dd1 / temp;
    const double dbeta_dforward = b->dbeta_dd2 / temp;
    const double temp2 = dalpha_dforward * b->forward + b->alpha + dbeta_dforward * b->x;
    return b->discount * temp2;
}

/* Black.gamma (models.py:150-157). */
double pl_black_gamma(const struct pl_black *b, double spot) {
    if (b->std_dev <= PL_QL_EPSILON) {
        return 0.0;
    }
    const double dforward_ds = b->forward / spot;
    const double temp = b->std_dev * spot;
    const double dalpha_ds = b->dalpha_dd1 / temp;
    const double dbeta_ds = b->dbeta_dd2 / temp;
    const double d2alpha_ds2 = -dalpha_ds / spot * (1.0 + b->d1 / b->std_dev);
    const double d2beta_ds2 = -dbeta_ds / spot * (1.0 + b->d2 / b->std_dev);
    /* temp2 = t1 + t2 + t3 + t4, left to right (pl_sum4). */
    const double temp2 = pl_sum4(d2alpha_ds2 * b->forward, 2.0 * dalpha_ds * dforward_ds,
                                 d2beta_ds2 * b->x, 2.0 * dbeta_ds * b->dx_ds);
    return b->discount * temp2;
}

/* Black.theta (models.py:158-160). */
double pl_black_theta(const struct pl_black *b, double spot, double maturity) {
    if (pl_close(maturity, 0.0)) {
        return 0.0;
    }
    /* -(sum) / maturity, with the sum of the three Python terms left to right (pl_sum3). */
    const double sum = pl_sum3(pl_log(b->discount) * pl_black_value(b),
                               pl_log(b->forward / spot) * spot * pl_black_delta(b, spot),
                               0.5 * b->variance * spot * spot * pl_black_gamma(b, spot));
    return -sum / maturity;
}

/* Black.vega (models.py:161-166). */
double pl_black_vega(const struct pl_black *b, double maturity) {
    if (b->std_dev <= PL_QL_EPSILON) {
        return 0.0;
    }
    const double temp = pl_log(b->strike / b->forward) / b->variance;
    const double dalpha_dsigma = b->dalpha_dd1 * (temp + 0.5);
    const double dbeta_dsigma = b->dbeta_dd2 * (temp - 0.5);
    const double temp2 = dalpha_dsigma * b->forward + dbeta_dsigma * b->x;
    return b->discount * pl_sqrt(maturity) * temp2;
}

/* Black.rho (models.py:167-172). */
double pl_black_rho(const struct pl_black *b, double maturity) {
    if (b->std_dev <= PL_QL_EPSILON) {
        const double delta_fwd = pl_black_delta_forward(b);
        return maturity * (delta_fwd * b->forward - pl_black_value(b));
    }
    const double dalpha_dr = b->dalpha_dd1 / b->std_dev;
    const double dbeta_dr = b->dbeta_dd2 / b->std_dev;
    const double temp = dalpha_dr * b->forward + b->alpha * b->forward + dbeta_dr * b->x;
    return maturity * (b->discount * temp - pl_black_value(b));
}

/* Black.dividendRho (models.py:173-178). */
double pl_black_dividend_rho(const struct pl_black *b, double maturity) {
    if (b->std_dev <= PL_QL_EPSILON) {
        const double delta_fwd = pl_black_delta_forward(b) / b->discount;
        return -maturity * b->discount * delta_fwd * b->forward;
    }
    const double dalpha_dq = -b->dalpha_dd1 / b->std_dev;
    const double dbeta_dq = -b->dbeta_dd2 / b->std_dev;
    const double temp = dalpha_dq * b->forward - b->alpha * b->forward + dbeta_dq * b->x;
    return maturity * b->discount * temp;
}

/* Black.strikeSensitivity (models.py:179-184). */
double pl_black_strike_sensitivity(const struct pl_black *b) {
    if (b->std_dev <= PL_QL_EPSILON) {
        const double d = b->discount;
        return flat(b, -d * 0.5, -d * 1.0, -d * 0.0, d * 0.5, d * 0.0, d * 1.0);
    }
    const double temp = b->std_dev * b->strike;
    const double dalpha_dstrike = -b->dalpha_dd1 / temp;
    const double dbeta_dstrike = -b->dbeta_dd2 / temp;
    const double temp2 =
        dalpha_dstrike * b->forward + dbeta_dstrike * b->x + b->beta * b->dx_dstrike;
    return b->discount * temp2;
}
