#include "pl_scan.h"
#include "pl_ieee.h"
#include "pl_protocol.h"
#include <math.h>
#include <stddef.h>
#include <stdint.h>

/* The record-scan kernel (specs/project/batch.md "Record-scan"): a transliteration of
 * benchlab.recordscan whole_days, _keep and scan_reference (recordscan.py:23-39). Pure. */

/* The int64 value of the bits of an i64 field (two's complement, no implementation-defined
 * conversion). */
static int64_t pl_i64_of(uint64_t u) {
    if (u <= (uint64_t)INT64_MAX) {
        return (int64_t)u;
    }
    return -(int64_t)(~u) - 1;
}

/* dte_min <= d <= dte_max for an integral finite double d, compared exactly: a d outside the
 * int64 range is outside every window. */
static int pl_in_window(double d, int64_t dte_min, int64_t dte_max) {
    if (d < -0x1p63 || d >= 0x1p63) {
        return 0;
    }
    const int64_t v = (int64_t)d;
    return dte_min <= v && v <= dte_max;
}

/* _keep (recordscan.py:29-32) with whole_days (recordscan.py:23-27). */
static int pl_keep(const uint8_t *rec, int64_t oi, int64_t dte_min, int64_t dte_max, double lo,
                   double hi) {
    const double S = pl_load_f64(rec + 1);
    if (oi < 0 || !(S > 0.0)) {
        return 0;
    }
    const double T = pl_load_f64(rec + 17);
    if (!pl_is_finite(T)) {
        return 0;
    }
    const double days = T * 365.0 + 0.5;
    if (!pl_is_finite(days) || !pl_in_window(floor(days), dte_min, dte_max)) {
        return 0;
    }
    const double m = pl_load_f64(rec + 9) / S;
    return lo <= m && m <= hi;
}

int pl_scan(const uint8_t *packed, size_t len, int64_t dte_min, int64_t dte_max, double lo,
            double hi, struct pl_scan_totals *out) {
    if (out == NULL || (packed == NULL && len > 0u) || len % PL_SCAN_RECORD_BYTES != 0u) {
        return -1;
    }
    struct pl_scan_totals t = {0u, 0, 0u};
    for (size_t off = 0; off < len; off += PL_SCAN_RECORD_BYTES) {
        const uint8_t *rec = packed + off;
        const int64_t oi = pl_i64_of(pl_load_u64(rec + 41));
        t.records++;
        if (pl_keep(rec, oi, dte_min, dte_max, lo, hi)) {
            t.count++;
            if (__builtin_add_overflow(t.open_interest, oi, &t.open_interest)) {
                return -2;
            }
        }
    }
    *out = t;
    return 0;
}
