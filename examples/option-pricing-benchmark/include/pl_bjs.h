#pragma once
#include "pl_black.h"

/* QuantLib 1.43 BjerksundStenslandApproximationEngine (Bjerksund-Stensland 1993) as
 * optionlab.models computes it (specs/project/models.md "Bjerksund-Stensland 1993"). Pure
 * functions; the only memory they touch is the caller's output object. */

/* glibc math.h M_SQRT2, ql/mathconstants.hpp M_SQRTPI and glibc M_PI as models.py writes them. */
#define PL_M_SQRT2 0x1.6a09e667f3bcdp+0
#define PL_M_SQRTPI 0x1.c5bf891b4ef6bp+0
#define PL_M_PI 0x1.921fb54442d18p+1

/* models._phi (models.py:205-209), bjerksundstenslandengine.cpp:37-48. */
double pl_bjs_phi(double S, double gamma, double H, double I, double rT, double bT,
                  double variance);
/* The analytic derivatives of phi (models.py:211-244, bjerksundstenslandengine.cpp:50-110):
 * by S (211-213), twice by S (215-219), by gamma (221-223), H (225-227), I (229-231), rT
 * (233-235), bT (237-239) and the variance (241-244). */
double pl_bjs_phi_s(double S, double gamma, double H, double I, double rT, double bT, double v);
double pl_bjs_phi_ss(double S, double gamma, double H, double I, double rT, double bT, double v);
double pl_bjs_phi_gamma(double S, double gamma, double H, double I, double rT, double bT, double v);
double pl_bjs_phi_h(double S, double gamma, double H, double I, double rT, double bT, double v);
double pl_bjs_phi_i(double S, double gamma, double H, double I, double rT, double bT, double v);
double pl_bjs_phi_rt(double S, double gamma, double H, double I, double rT, double bT, double v);
double pl_bjs_phi_bt(double S, double gamma, double H, double I, double rT, double bT, double v);
double pl_bjs_phi_v(double S, double gamma, double H, double I, double rT, double bT, double v);

/* models._european_call (models.py:246-253): every member is set. */
void pl_bjs_european_call(double S, double X, double rf_d, double d_d, double variance,
                          struct pl_engine_result *out);
/* models._immediate (models.py:255-259): every member is set. */
void pl_bjs_immediate(double S, double X, struct pl_engine_result *out);
/* models._american_call (models.py:261-340). greeks == 0: in the formula branch only value is
 * computed and every other member is pl_nan(); the other branches set every member. */
void pl_bjs_american_call(double S, double X, double rf_d, double d_d, double variance, int greeks,
                          struct pl_engine_result *out);
/* models.bjs_engine (models.py:342-355). PL_ENGINE_QL_ERROR (every member pl_nan()) for the
 * double-boundary case (QL_FAIL "double-boundary case r<q<0 for a call given"), else
 * PL_ENGINE_OK. side 1 is a put; every other side is a call (models.py tests side == 1). */
enum pl_engine_status pl_bjs_engine(int side, double S, double K, double d_r, double d_q,
                                    double variance, int greeks, struct pl_engine_result *out);
/* models.bjs_result (models.py:449): PL_ENGINE_PY_DEFECT (every member pl_nan()) when
 * pl_mapped_inputs sets the defect (Python raises before models._guard), else the engine. */
enum pl_engine_status pl_bjs_result(int side, double S, double K, double T, double r, double q,
                                    double sigma, int greeks, struct pl_engine_result *out);
