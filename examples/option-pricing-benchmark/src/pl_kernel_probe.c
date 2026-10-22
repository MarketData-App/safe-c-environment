#include "pl_evaluate.h"
#include "pl_kernel_cli.h"
#include "pl_protocol.h"
#include "pl_types.h"
#include <stddef.h>
#include <stdint.h>

/* The probe mode of pl-kernel (specs/project/batch.md "pl-kernel command line", Task 22 QuantLib
 * alignment): 72-byte input records (model, side, S, K, T, r, q, sigma, zero) and 64-byte output
 * records (u32 status, u32 rounding band, seven binary64). A translation unit of its own, so that
 * each call inside the record loops is opaque to the GCC analyzer. */

/* The model of a probe record (exactly 0.0 to 4.0), or -1. Branch-free but for the result. */
static int pl_probe_model(const uint8_t *rec) {
    const double v = pl_load_f64(rec);
    const int m = (v == 1.0) + 2 * (v == 2.0) + 3 * (v == 3.0) + 4 * (v == 4.0);
    const int known = (v == 0.0) | (v == 1.0) | (v == 2.0) | (v == 3.0) | (v == 4.0);
    return known ? m : -1;
}

int pl_probe_check(const uint8_t *input, size_t n) {
    int bad = 0;
    for (size_t i = 0; i < n; i++) {
        const uint8_t *rec = input + i * PL_PROBE_IN_BYTES;
        const int model = pl_probe_model(rec);
        const uint64_t zero = pl_load_u64(rec + 64);
        bad |= (model < 0) | (zero != 0u);
    }
    return bad ? PL_REASON_INPUT : PL_REASON_OK;
}

/* A side value decodes like the wire side (0.0 -> 0, 1.0 -> 1, any other value -> -1). */
static int pl_probe_side(double v) {
    if (v == 0.0) {
        return 0;
    }
    return v == 1.0 ? 1 : -1;
}

void pl_probe_record(const uint8_t *rec, const struct pl_params *p, uint8_t *out) {
    struct pl_row row;
    row.side = pl_probe_side(pl_load_f64(rec + 8));
    row.S = pl_load_f64(rec + 16);
    row.K = pl_load_f64(rec + 24);
    row.T = pl_load_f64(rec + 32);
    row.bid = 0.0;
    row.ask = 0.0;
    row.r = pl_load_f64(rec + 40);
    row.q = pl_load_f64(rec + 48);
    const double sigma = pl_load_f64(rec + 56);
    double values[PL_FIELDS];
    int band = 0;
    uint8_t flags = 0u;
    uint32_t evals = 0u;
    const int model = pl_probe_model(rec);
    const int st = pl_price_and_greeks(model, &row, sigma, p, values, &band, &flags, &evals);
    pl_store_u32(out, (uint32_t)st);
    pl_store_u32(out + 4, band != 0 ? 1u : 0u);
    pl_store_f64(out + 8, *(values + 0));
    pl_store_f64(out + 16, *(values + 1));
    pl_store_f64(out + 24, *(values + 2));
    pl_store_f64(out + 32, *(values + 3));
    pl_store_f64(out + 40, *(values + 4));
    pl_store_f64(out + 48, *(values + 5));
    pl_store_f64(out + 56, *(values + 6));
}
