#define PL_TEST_ALO_GREEKS
#include "pl_test_alo.h"

/* Bit-exact test of the ALO greek step (pl_alo_price_and_greeks and the ALO branch of
 * pl_price_and_greeks; specs/project/models.md "ALO (Amendment I)") against the ALO branch of
 * reference.price_and_greeks with the counter of reference.evaluate (cvectors part alo_greeks):
 * status (0 OK, 1 order 5, 2 a Python raise), band, flags 16 and 32, the engine-evaluation count
 * (the stencil points, ruling 45) and the seven values as equal bits or both NaN, for the case,
 * planted and forced parameter sets: every row of the table (pl_test_alo.h, one slice). */

int main(void) { return pl_ta_greeks_slice(0u); }
