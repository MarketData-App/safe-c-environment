#pragma once
#include <stddef.h>
#include <stdint.h>

/* The record-scan kernel (specs/project/batch.md "Record-scan"): benchlab.recordscan whole_days,
 * _keep and scan_reference (recordscan.py:23-39) over packed 49-byte records <Bdddddq. */

#define PL_SCAN_RECORD_BYTES 49u

struct pl_scan_totals {
    uint64_t count;
    int64_t open_interest;
    uint64_t records;
};

/* Keeps a record when oi >= 0, S > 0.0, dte_min <= floor(T * 365.0 + 0.5) <= dte_max (T and the
 * day value finite) and lo <= K / S <= hi. Returns 0 and writes *out; -1 (no write) when len is
 * not a multiple of 49, out is NULL or packed is NULL with len > 0; -2 (no write) when the
 * open-interest sum overflows int64. */
int pl_scan(const uint8_t *packed, size_t len, int64_t dte_min, int64_t dte_max, double lo,
            double hi, struct pl_scan_totals *out);
