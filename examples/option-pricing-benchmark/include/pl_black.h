#pragma once

/* QuantLib 1.43 term-structure arithmetic, the unit-maturity mapping, BlackCalculator and the
 * AnalyticEuropeanEngine as optionlab.models and optionlab.mapping compute them
 * (specs/project/models.md "Term structure, mapping and BSM"). Pure functions; the only
 * memory they touch is the caller's output objects. */

/* models.discount (models.py:96): 1.0 / exp(rate * t). Sets *defect = 1 where Python raises
 * ZeroDivisionError (the exponential is +-0.0). */
double pl_discount(double rate, double t, int *defect);
/* models.implied_rate (models.py:97-99): 0.0 when compound == 1.0, else log(compound) / t.
 * t is a nonzero constant at every call of the row path. */
double pl_implied_rate(double compound, double t);
/* models.zero_rate (models.py:100-103): t == 0.0 becomes 0.0001; implied_rate(1.0 / discount,
 * t). Sets *defect = 1 where Python raises (in discount, or a zero discount). */
double pl_zero_rate(double rate, double t, int *defect);
/* models.forward_rate (models.py:104-105): implied_rate(discount(t1) / discount(t2), t2 - t1).
 * Sets *defect = 1 where Python raises (in either discount, or a zero second discount). */
double pl_forward_rate(double rate, double t1, double t2, int *defect);

/* mapping.unit (mapping.py:9-14): r1 = r * T, q1 = q * T, s1 = sigma * sqrt(T). T >= 0.0 or
 * NaN (Python raises ValueError for T < 0.0; the row path never passes it). */
void pl_unit(double T, double r, double q, double sigma, double *r1, double *q1, double *s1);
/* models.mapped_inputs (models.py:187-190): D_r = discount(r1, 1.0), D_q = discount(q1, 1.0),
 * variance = s1 * s1 * 1.0. Sets *defect = 1 where Python raises ZeroDivisionError. */
void pl_mapped_inputs(double T, double r, double q, double sigma, double *d_r, double *d_q,
                      double *variance, int *defect);

/* models.Black (models.py:107-184), QuantLib BlackCalculator for a plain vanilla payoff. side 0
 * is a call, any other side a put (models.py tests side == 0). */
struct pl_black {
    int side;
    double strike, forward, std_dev, discount, variance, d1, d2, x, dx_dstrike, dx_ds, alpha,
        dalpha_dd1, beta, dbeta_dd2;
};

/* Black.__init__ (models.py:110-130). */
void pl_black_init(struct pl_black *b, int side, double strike, double forward, double std_dev,
                   double discount);
/* Black.value (models.py:131). */
double pl_black_value(const struct pl_black *b);
/* Black.delta (models.py:136-143). */
double pl_black_delta(const struct pl_black *b, double spot);
/* Black.deltaForward (models.py:144-149). */
double pl_black_delta_forward(const struct pl_black *b);
/* Black.gamma (models.py:150-157). */
double pl_black_gamma(const struct pl_black *b, double spot);
/* Black.theta (models.py:158-160). */
double pl_black_theta(const struct pl_black *b, double spot, double maturity);
/* Black.vega (models.py:161-166). */
double pl_black_vega(const struct pl_black *b, double maturity);
/* Black.rho (models.py:167-172). */
double pl_black_rho(const struct pl_black *b, double maturity);
/* Black.dividendRho (models.py:173-178). */
double pl_black_dividend_rho(const struct pl_black *b, double maturity);
/* Black.strikeSensitivity (models.py:179-184). */
double pl_black_strike_sensitivity(const struct pl_black *b);

/* Engine results; a member that the engine does not compute is pl_nan(). */
struct pl_engine_result {
    double value, delta, gamma, theta, vega, rho, dividend_rho, strike_sensitivity, strike_gamma;
};

/* PL_ENGINE_PY_DEFECT: a Python raise point outside models._guard was reached. */
enum pl_engine_status { PL_ENGINE_OK = 0, PL_ENGINE_QL_ERROR = 1, PL_ENGINE_PY_DEFECT = 2 };

/* models.bsm_engine (models.py:195-202), AnalyticEuropeanEngine::calculate at t = 1. greeks == 0:
 * only value is set. strike_sensitivity and strike_gamma are always pl_nan(). */
void pl_bsm_engine(int side, double S, double K, double d_r, double d_q, double variance,
                   int greeks, struct pl_engine_result *out);
/* models.bsm_result (models.py:448): PL_ENGINE_PY_DEFECT (every member pl_nan()) when
 * pl_mapped_inputs sets the defect, else PL_ENGINE_OK and the engine result. */
enum pl_engine_status pl_bsm_result(int side, double S, double K, double T, double r, double q,
                                    double sigma, int greeks, struct pl_engine_result *out);
