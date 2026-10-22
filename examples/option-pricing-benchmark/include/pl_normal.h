#pragma once

/* QuantLib 1.43 normal functions as optionlab.normal computes them (specs/project/models.md
 * "Normal distribution"). Pure functions of one binary64 value; no failure path. */

/* QuantLib ErrorFunction::operator() (optionlab normal.erf, normal.py:40-69). */
double pl_erf(double x);
/* NormalDistribution(0, 1)::operator() (optionlab normal.norm_pdf, normal.py:72-76). */
double pl_norm_pdf(double x);
/* CumulativeNormalDistribution(0, 1)::operator() (optionlab normal.norm_cdf, normal.py:78-96). */
double pl_norm_cdf(double z);
