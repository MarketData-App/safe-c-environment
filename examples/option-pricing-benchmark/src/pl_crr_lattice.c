/* Transcribed from QuantLib 1.43 (QL_VERSION 1.43; retained source
 * benchmarks/project/third_party/sources/QuantLib-1.43.tar.gz, sha256
 * b41206ccc4ba39b5e86bdc940d51138222b352f79d2c6fc68649f9c9bbe58701), via optionlab/models.py lines
 * 406-414: ql/methods/lattices/binomialtree.hpp 84-101, ql/methods/lattices/bsmlattice.hpp 71-87,
 * ql/pricingengines/vanilla/discretizedvanillaoption.cpp 47-77. QuantLib license (BSD-3-Clause):
 * the copyright notices, conditions and disclaimer are in NOTICE-QuantLib.md of this example (LR-EX
 * 2026-10-18). */
#include "pl_crr.h"
#include "pl_ieee.h"
#include "pl_types.h"

/* The CRR lattice of models.crr_engine (specs/project/models.md "CRR"): the underlying values, the
 * reset and one rollback step. A separate translation unit, so that these loops are opaque calls
 * in pl_crr.c (the fixed GCC analyzer budget of the framework). Each function checks steps and i
 * before it forms any position; every position is then in [0, 2 * steps] for growth and in
 * [0, steps] for values, inside the struct arrays. */

/* The payoff lambda of models.crr_engine (models.py:407): side 0 is a call, any other side a
 * put. */
static double payoff(int side, double K, double s) {
    if (side == 0) {
        return pl_max(s - K, 0.0);
    }
    return pl_max(K - s, 0.0);
}

/* models.crr_engine growth and values (models.py:406, 408). */
int pl_crr_lattice_reset(struct pl_crr_lattice *l) {
    const int steps = l->steps;
    if (steps < 2 || steps > PL_CRR_MAX_STEPS) {
        return 1;
    }
    for (int j = -steps; j <= steps; j++) {
        *(l->growth + (j + steps)) = l->S * pl_exp((double)j * l->dx);
    }
    for (int j = 0; j <= steps; j++) {
        *(l->values + j) = pl_max(0.0, payoff(l->side, l->K, *(l->growth + 2 * j)));
    }
    return 0;
}

/* One step i of the rollback loop of models.crr_engine (models.py:410-414). C writes values[j]
 * after it reads values[j] and values[j + 1] (j increasing), so the update in place equals the
 * Python list comprehension over the old list; the American maximum is applied to each new value
 * as the second Python comprehension does. */
int pl_crr_lattice_step(struct pl_crr_lattice *l, int i) {
    const int steps = l->steps;
    if (steps < 2 || steps > PL_CRR_MAX_STEPS || i < 0 || i >= steps) {
        return 1;
    }
    double *values = l->values;
    const double *growth = l->growth;
    const double pu = l->pu;
    const double pd = l->pd;
    const double disc = l->disc;
    if (l->american == 0) {
        for (int j = 0; j <= i; j++) {
            *(values + j) = (pd * *(values + j) + pu * *(values + (j + 1))) * disc;
        }
        return 0;
    }
    for (int j = 0; j <= i; j++) {
        const double next = (pd * *(values + j) + pu * *(values + (j + 1))) * disc;
        *(values + j) = pl_max(next, payoff(l->side, l->K, *(growth + (2 * j - i + steps))));
    }
    return 0;
}
