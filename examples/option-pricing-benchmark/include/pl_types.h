#pragma once
#include <stdint.h>

/* Shared types of the C pricer (specs/project/models.md "Shared types"). */

/* MODELS5 order (Amendment G1.7 and I1.3: mask bit 1 << model; the record has one block per
 * model). PL_MODEL_ALO is the slot of the fifth model: until Task 10b wires ALO, pl_evaluate
 * gives a run defect for it (PL_MASK_WIRED in pl_evaluate.h). */
enum pl_model {
    PL_MODEL_BSM = 0,
    PL_MODEL_BJS = 1,
    PL_MODEL_CRR = 2,
    PL_MODEL_BAW = 3,
    PL_MODEL_ALO = 4
};
#define PL_MODELS 5u

/* Model masks (Amendment G1.7, I1.3): the three-model ALL_MODELS, MODELS4 and MODELS5. */
#define PL_MASK_ALL3 7u
#define PL_MASK_MODELS4 15u
#define PL_MASK_MODELS5 31u

/* Row status in the order of spec 3.3; PL_ECHO marks an echo-kernel record and PL_NOT_REQUESTED
 * an unselected model part (both wire-only, G4.5). */
enum pl_status {
    PL_INVALID_INPUT = 0,
    PL_EXPIRED = 1,
    PL_NO_BID = 2,
    PL_CROSSED = 3,
    PL_MODEL_DOMAIN = 4,
    PL_BELOW_MIN = 5,
    PL_ABOVE_MAX = 6,
    PL_NOT_CONVERGED = 7,
    PL_OK = 8,
    PL_NOT_REQUESTED = 254,
    PL_ECHO = 255
};

#define PL_FLAG_BELOW_INTRINSIC 1u
#define PL_FLAG_BOUNDARY_AMBIGUOUS 2u
#define PL_FLAG_FLAT_VEGA 4u
#define PL_FLAG_ROUNDING_BAND 8u
/* BAW and ALO flags (G2.3, G4.5, I5.3): 16 and 32 in the baw and alo parts, 64 in the baw part
 * only. */
#define PL_FLAG_STENCIL_UNRESOLVED 16u
#define PL_FLAG_STENCIL_SWITCHED 32u
#define PL_FLAG_ADMIT_EXCLUDED 64u

enum pl_field { PL_IV = 0, PL_PRICE, PL_DELTA, PL_GAMMA, PL_THETA, PL_VEGA, PL_RHO };
#define PL_FIELDS 7

/* baw_newton_max: the protected case parameter of the BAW critical-price iteration (Appendix
 * G-BAW R3); baw_plant_nonfinite_sstar: test-only (G2.3 planted non-finite S*), 0 in every
 * production parameter set. Both follow h_sigma, so every earlier positional initializer keeps
 * its meaning. alo_plant_site and alo_force (Task 10b, Amendment I item I4.1; ruling 52): the
 * test-only planted-defect hooks of the ALO engine, appended after baw_plant_nonfinite_sstar and
 * 0 in every production parameter set. alo_plant_site k > 0 plants a NaN at site k of enum
 * pl_alo_site (the R7 value-mask sites of optionlab.alo, then the persistent QD+ evaluator NaN of
 * AI3-02); alo_force 1 forces the inner QD+ Brent bracket error, 1 + j the cap excess of loop j
 * of enum pl_alo_cap (pl_alo.h). */
struct pl_params {
    int crr_steps;
    double sigma_hi, kappa_cap, h_r, h_sigma;
    int baw_newton_max;
    int baw_plant_nonfinite_sstar;
    int alo_plant_site;
    int alo_force;
};

struct pl_row {
    int side;
    double S, K, T, bid, ask, r, q;
};

struct pl_model_result {
    uint8_t status;
    uint8_t flags;
    double values[PL_FIELDS];
};

/* Five model blocks in MODELS5 order (bsm, bjs, crr, baw, alo). */
struct pl_contract_result {
    struct pl_model_result model[PL_MODELS];
};

#define PL_CRR_MAX_STEPS 100

enum pl_eval_error { PL_EVAL_OK = 0, PL_EVAL_DEFECT = 1 };

/* QuantLib QL_EPSILON (std::numeric_limits<double>::epsilon()) = 2^-52. */
#define PL_QL_EPSILON 0x1p-52

/* mathconstants.hpp:85-87 M_SQRT_2 and 97-99 M_1_SQRTPI as models.py writes them (shared by
 * pl_normal.c and pl_black.c). */
#define PL_M_SQRT_2 0x1.6a09e667f3bcdp-1
#define PL_M_1_SQRTPI 0x1.20dd750429b6dp-1
