/* Transcribed from QuantLib 1.43 (QL_VERSION 1.43; retained source
 * benchmarks/project/third_party/sources/QuantLib-1.43.tar.gz, sha256
 * b41206ccc4ba39b5e86bdc940d51138222b352f79d2c6fc68649f9c9bbe58701), via optionlab/alo.py
 * lines 579-596 (merged G-ALO2 part B, commit 567f6c4): ql/pricingengines/vanilla/
 * qdfpamericanengine.cpp 429-516 (calculatePut: one Jacobi-Newton or naive sweep over the nodes,
 * then updateY) (spec Appendix I-ALO R2-R7). QuantLib license (BSD-3-Clause): the copyright
 * notices, conditions and disclaimer are in NOTICE-QuantLib.md of this example (LR-EX 2026-10-18).
 * */
#include "pl_alo.h"
#include "pl_alo_step.h"
#include "pl_types.h"
#include <stddef.h>

/* One sweep of alo.calculate_put (specs/project/models.md "ALO (Amendment I)"), copied statement
 * by statement. Its own translation unit: the five sweeps of src/pl_alo.c call it as an opaque
 * function, and it calls the node update of src/pl_alo_node.c as one (the fixed GCC analyzer
 * budget). The loop is bounded by the 13 nodes. */

int pl_alo_sweep(struct pl_alo_fp *eqn, struct pl_alo_cheb *interp, const double *x, double *y,
                 int jacobi) {
    struct pl_alo_run *run = eqn->run;
    for (int i = 1; i < PL_ALO_CHEB_NODES; i++) {
        pl_alo_fp_node(eqn, x, y, i, jacobi); /* y[i] */
        if (run->status != PL_ENGINE_OK) {
            return 1;
        }
    }
    pl_alo_cheb_update(interp, y); /* interp.update_y(y) */
    return pl_alo_check(run, PL_ALO_CHECK_POST_BOUNDARY, interp->y, (size_t)PL_ALO_CHEB_NODES);
}
