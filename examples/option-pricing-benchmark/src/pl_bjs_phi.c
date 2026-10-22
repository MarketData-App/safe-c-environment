/* Transcribed from QuantLib 1.43 (QL_VERSION 1.43; retained source
 * benchmarks/project/third_party/sources/QuantLib-1.43.tar.gz, sha256
 * b41206ccc4ba39b5e86bdc940d51138222b352f79d2c6fc68649f9c9bbe58701), via optionlab/models.py lines
 * 204-244: ql/pricingengines/vanilla/bjerksundstenslandengine.cpp 37-110,
 * ql/pricingengines/vanilla/bjerksundstenslandengine.hpp 33. QuantLib license (BSD-3-Clause): the
 * copyright notices, conditions and disclaimer are in NOTICE-QuantLib.md of this example (LR-EX
 * 2026-10-18). */
#include "pl_bjs.h"
#include "pl_ieee.h"
#include "pl_normal.h"

/* The phi function of Bjerksund-Stensland 1993 and its analytic derivatives (specs/project/
 * models.md "Bjerksund-Stensland 1993"). Each function copies the cited optionlab function
 * statement by statement: the same operations in the same order and association (spec 3.4;
 * Amendment F item 8). A Python integer literal is the equal double literal. A named local holds
 * a Python subexpression that the Python text writes out (the same operations); a subexpression
 * that Python repeats is computed once (the functions are pure). math.erfc is pl_erfc (glibc
 * erfc). A Python sum of terms goes through pl_sum2, pl_sum3 or pl_sum4 (left to right, a - b as
 * a + (-b), which IEEE-754 defines as the same operation), so the GCC analyzer sees an opaque
 * value within its fixed symbolic-depth budget. Every division is IEEE C division (the engines
 * run through models._guard). A file of its own: the engine in pl_bjs.c sees opaque calls. */

/* models._phi (models.py:205-209). */
double pl_bjs_phi(double S, double gamma, double H, double I, double rT, double bT,
                  double variance) {
    const double lam = -rT + gamma * bT + 0.5 * gamma * (gamma - 1.0) * variance;
    const double d = -(pl_log(S / H) + (bT + (gamma - 0.5) * variance)) / pl_sqrt(variance);
    const double kappa = 2.0 * bT / variance + (2.0 * gamma - 1.0);
    const double n1 = pl_norm_cdf(d);
    const double p = pl_pow(I / S, kappa);
    const double n2 = pl_norm_cdf(d - 2.0 * pl_log(I / S) / pl_sqrt(variance));
    return pl_exp(lam) * (n1 - p * n2);
}

/* models._phi_S (models.py:211-213). */
double pl_bjs_phi_s(double S, double gamma, double H, double I, double rT, double bT, double v) {
    const double lsh = pl_log(S / H);
    const double lis = pl_log(I / S);
    const double sv = pl_sqrt(v);
    const double e = pl_exp(bT * gamma - rT + ((-1.0 + gamma) * gamma * v) / 2.0);
    const double p = pl_pow(I / S, 2.0 * (gamma + bT / v));
    const double z1 = 2.0 * bT - v + 2.0 * gamma * v + 4.0 * lis + 2.0 * lsh;
    const double z0 = 2.0 * bT - v + 2.0 * gamma * v + 2.0 * lsh;
    const double x1 = pl_exp(pl_sq(z1) / (8.0 * v));
    const double x0 = pl_exp(pl_sq(z0) / (8.0 * v));
    const double c = 2.0 * bT + (-1.0 + 2.0 * gamma) * v;
    const double t1 = (-(p / (x1 * I)) - 1.0 / (x0 * S)) / (PL_M_SQRT2 * PL_M_SQRTPI * sv);
    const double t2 = (p * c * pl_erfc(z1 / (2.0 * PL_M_SQRT2 * sv))) / (2.0 * I * v);
    return e * pl_sum2(t1, t2);
}

/* models._phi_SS (models.py:215-219). */
double pl_bjs_phi_ss(double S, double gamma, double H, double I, double rT, double bT, double v) {
    const double lsh = pl_log(S / H);
    const double lis = pl_log(I / S);
    const double sv = pl_sqrt(v);
    const double z1 = 2.0 * bT - v + 2.0 * gamma * v + 4.0 * lis + 2.0 * lsh;
    const double c = 2.0 * bT + (-1.0 + 2.0 * gamma) * v;
    const double ex = pl_exp(pl_sq(z1) / (8.0 * v));
    const double ey = pl_exp(pl_sq(c + 2.0 * lsh) / (8.0 * v));
    const double e = pl_exp(bT * gamma - rT + ((-1.0 + gamma) * gamma * v) / 2.0);
    const double p = pl_pow(I / S, 2.0 * (gamma + bT / v));
    const double er = pl_erfc(z1 / (2.0 * PL_M_SQRT2 * sv));
    const double z2 = 2.0 * bT - 3.0 * v + 2.0 * gamma * v + 4.0 * lis + 2.0 * lsh;
    const double a1 = (PL_M_SQRT2 * I * v * sv) / ey;
    const double a2 = (2.0 * PL_M_SQRT2 * p * S * sv * c) / ex;
    const double a3 = 2.0 * pl_sqrt(PL_M_PI) * p * S * (bT + gamma * v) * c * er;
    const double a4 = (PL_M_SQRT2 * I * sv * (bT + (-0.5 + gamma) * v + lsh)) / ey;
    const double a5 = (p * S * sv * z2) / (PL_M_SQRT2 * ex);
    const double sum = pl_sum3(pl_sum3(a1, a2, -a3), a4, -a5);
    return (e * sum) / (2.0 * I * PL_M_SQRTPI * pl_sq(S * v));
}

/* models._phi_gamma (models.py:221-223). */
double pl_bjs_phi_gamma(double S, double gamma, double H, double I, double rT, double bT,
                        double v) {
    const double lsh = pl_log(S / H);
    const double lis = pl_log(I / S);
    const double sv = pl_sqrt(v);
    const double e = pl_exp(bT * gamma - rT + ((-1.0 + gamma) * gamma * v) / 2.0);
    const double z0 = 2.0 * bT - v + 2.0 * gamma * v + 2.0 * lsh;
    const double z1 = 2.0 * bT - v + 2.0 * gamma * v + 4.0 * lis + 2.0 * lsh;
    const double c = 2.0 * bT + (-1.0 + 2.0 * gamma) * v;
    const double p2 = pl_pow(I / S, -1.0 + 2.0 * gamma + (2.0 * bT) / v);
    const double e0 = pl_exp(-pl_sq(z0) / (8.0 * v));
    const double e1 = pl_exp(pl_sq(z1) / (8.0 * v));
    const double g1 = ((-e0 + p2 / e1) * sv) / (PL_M_SQRT2 * PL_M_SQRTPI);
    const double g2 = (c * pl_erfc((c + 2.0 * lsh) / (2.0 * PL_M_SQRT2 * sv))) / 4.0;
    const double g3 = (p2 * pl_erfc(z1 / (2.0 * PL_M_SQRT2 * sv)) * (c + 4.0 * lis)) / 4.0;
    return e * pl_sum3(g1, g2, -g3);
}

/* models._phi_H (models.py:225-227). */
double pl_bjs_phi_h(double S, double gamma, double H, double I, double rT, double bT, double v) {
    const double lsh = pl_log(S / H);
    const double lis = pl_log(I / S);
    const double e = pl_exp(bT * gamma - rT + ((-1.0 + gamma) * gamma * v) / 2.0);
    const double p = pl_pow(I / S, 2.0 * (gamma + bT / v));
    const double x0 = pl_exp(pl_sq(2.0 * bT - v + 2.0 * gamma * v + 2.0 * lsh) / (8.0 * v));
    const double z1 = 2.0 * bT - v + 2.0 * gamma * v + 4.0 * lis + 2.0 * lsh;
    const double x1 = pl_exp(pl_sq(z1) / (8.0 * v));
    return (e * (I / x0 - (p * S) / x1)) / (H * I * pl_sqrt(2.0 * PL_M_PI) * pl_sqrt(v));
}

/* models._phi_I (models.py:229-231). */
double pl_bjs_phi_i(double S, double gamma, double H, double I, double rT, double bT, double v) {
    const double lsh = pl_log(S / H);
    const double lis = pl_log(I / S);
    const double sv = pl_sqrt(v);
    const double e = pl_exp(bT * gamma - rT + ((-1.0 + gamma) * gamma * v) / 2.0);
    const double p = pl_pow(I / S, 2.0 * (gamma + bT / v));
    const double z1 = 2.0 * bT - v + 2.0 * gamma * v + 4.0 * lis + 2.0 * lsh;
    const double x1 = pl_exp(pl_sq(z1) / (8.0 * v));
    const double er = pl_erfc(z1 / (2.0 * PL_M_SQRT2 * sv));
    const double i1 = (2.0 * pl_sqrt(2.0 / PL_M_PI)) / (x1 * sv);
    const double i2 = (1.0 - 2.0 * gamma - (2.0 * bT) / v) * er;
    return (e * p * S * (i1 + i2)) / (2.0 * I * I);
}

/* models._phi_rt (models.py:233-235). */
double pl_bjs_phi_rt(double S, double gamma, double H, double I, double rT, double bT, double v) {
    const double lsh = pl_log(S / H);
    const double e = pl_exp(bT * gamma - rT + ((-1.0 + gamma) * gamma * v) / 2.0);
    const double p = pl_pow(I / S, 2.0 * (gamma + bT / v));
    const double z0 = 2.0 * bT - v + 2.0 * gamma * v + 2.0 * lsh;
    const double z1 = 2.0 * bT - v + 2.0 * gamma * v + 4.0 * pl_log(I / S) + 2.0 * lsh;
    const double r0 = pl_erfc(z0 / (2.0 * pl_sqrt(2.0 * v)));
    const double r1 = pl_erfc(z1 / (2.0 * pl_sqrt(2.0 * v)));
    return (e * (-(I * r0) + p * S * r1)) / (2.0 * I);
}

/* models._phi_bt (models.py:237-239). */
double pl_bjs_phi_bt(double S, double gamma, double H, double I, double rT, double bT, double v) {
    const double lsh = pl_log(S / H);
    const double lis = pl_log(I / S);
    const double sv = pl_sqrt(v);
    const double e = pl_exp(bT * gamma - rT + ((-1.0 + gamma) * gamma * v) / 2.0);
    const double p = pl_pow(I / S, 2.0 * (gamma + bT / v));
    const double z0 = 2.0 * bT - v + 2.0 * gamma * v + 2.0 * lsh;
    const double z1 = 2.0 * bT - v + 2.0 * gamma * v + 4.0 * lis + 2.0 * lsh;
    const double x0 = pl_exp(pl_sq(z0) / (8.0 * v));
    const double x1 = pl_exp(pl_sq(z1) / (8.0 * v));
    const double b1 = PL_M_SQRT2 * (-(I / x0) + (p * S) / x1) * sv;
    const double b2 = gamma * I * pl_sqrt(PL_M_PI) * v * pl_erfc(z0 / (2.0 * PL_M_SQRT2 * sv));
    const double r1 = pl_erfc(z1 / (2.0 * PL_M_SQRT2 * sv));
    const double b3 = PL_M_SQRTPI * p * S * r1 * (gamma * v + 2.0 * lis);
    return (e * pl_sum3(b1, b2, -b3)) / (2.0 * I * pl_sqrt(PL_M_PI) * v);
}

/* models._phi_v (models.py:241-244). */
double pl_bjs_phi_v(double S, double gamma, double H, double I, double rT, double bT, double v) {
    const double lsh = pl_log(S / H);
    const double lis = pl_log(I / S);
    const double sv = pl_sqrt(v);
    const double z0 = 2.0 * bT - v + 2.0 * gamma * v + 2.0 * lsh;
    const double z1 = 2.0 * bT - v + 2.0 * gamma * v + 4.0 * lis + 2.0 * lsh;
    const double er = pl_erfc(z1 / (2.0 * PL_M_SQRT2 * sv));
    const double e = pl_exp(bT * gamma - rT + ((-1.0 + gamma) * gamma * v) / 2.0);
    const double p = pl_pow(I / S, 2.0 * (gamma + bT / v));
    const double p2 = pl_pow(I / S, -1.0 + 2.0 * gamma + (2.0 * bT) / v);
    const double c = 2.0 * bT + (-1.0 + 2.0 * gamma) * v;
    const double r0 = pl_erfc(z0 / (2.0 * PL_M_SQRT2 * sv));
    const double v1 = ((-1.0 + gamma) * gamma * (I * r0 - p * S * er)) / (2.0 * I);
    const double v2 = (2.0 * bT * p2 * er * lis) / (v * v);
    const double y0 = pl_exp(pl_pow(c + 2.0 * lsh, 2.0) / (8.0 * v));
    const double n3 = 2.0 * bT + v - 2.0 * gamma * v + 2.0 * lsh;
    const double v3 = n3 / (2.0 * y0 * PL_M_SQRT2 * PL_M_SQRTPI * v * sv);
    const double y1 = pl_exp(pl_sq(z1) / (8.0 * v));
    const double n4 = p2 * (2.0 * bT + v - 2.0 * gamma * v + 4.0 * lis + 2.0 * lsh);
    const double v4 = n4 / (2.0 * y1 * PL_M_SQRT2 * PL_M_SQRTPI * v * sv);
    return (e * pl_sum4(v1, v2, v3, -v4)) / 2.0;
}
