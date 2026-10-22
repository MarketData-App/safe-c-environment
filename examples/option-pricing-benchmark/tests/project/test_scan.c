#include "pl_scan.h"
#include "pl_test_batch.h"

/* Tests of pl_scan.c (specs/project/batch.md "Record-scan"; benchlab.recordscan _keep and
 * scan_reference). Records are packed by hand with pl_store_*. REQUIRE stays active under
 * NDEBUG. */

#define R PL_SCAN_RECORD_BYTES

static uint8_t buf[8u * R];

/* Record i: side, S, K, T (years), bid, ask, open interest. */
static void pack(size_t i, double S, double K, double T, int64_t oi) {
    uint8_t *rec = buf + i * R;
    *rec = (uint8_t)(i & 1u);
    pl_store_f64(rec + 1, S);
    pl_store_f64(rec + 9, K);
    pl_store_f64(rec + 17, T);
    pl_store_f64(rec + 25, 1.0);
    pl_store_f64(rec + 33, 1.25);
    pl_store_u64(rec + 41, oi < 0 ? ~(uint64_t)(-(oi + 1)) : (uint64_t)oi);
}

static void scan(void) {
    pack(0u, 100.0, 90.0, 6.9 / 365.0, 10);   /* 7 days, K/S 0.9: kept */
    pack(1u, 100.0, 110.0, 60.5 / 365.0, 20); /* 61 days: dropped */
    pack(2u, 100.0, 110.0, 30.0 / 365.0, 40); /* K/S 1.1: kept */
    pack(3u, 100.0, 100.0, 30.0 / 365.0, -1); /* oi -1: skipped */
    pack(4u, 0.0, 100.0, 30.0 / 365.0, 80);   /* S = 0: skipped */
    pack(5u, 100.0, 100.0, pl_nan(), 160);    /* T NaN: skipped */
    struct pl_scan_totals t = {9u, 9, 9u};
    REQUIRE(pl_scan(buf, 6u * R, 7, 60, 0.9, 1.1, &t) == 0);
    REQUIRE(t.count == 2u && t.open_interest == 50 && t.records == 6u);
    REQUIRE(pl_scan(buf, 6u * R, 7, 61, 0.9, 1.1, &t) == 0); /* 61 days inside */
    REQUIRE(t.count == 3u && t.open_interest == 70);
    REQUIRE(pl_scan(buf, 6u * R, 8, 60, 0.9, 1.1, &t) == 0); /* 7 days outside */
    REQUIRE(t.count == 1u && t.open_interest == 40);
    REQUIRE(pl_scan(buf, 6u * R, INT64_MIN, INT64_MAX, 0.9, 1.0999999999999999, &t) == 0);
    REQUIRE(t.count == 1u && t.open_interest == 10); /* 1.1 above the band end */

    /* A huge day value is outside every int64 window. */
    pack(6u, 100.0, 100.0, 1e300, 1);
    pack(7u, 100.0, 100.0, -1e300, 1);
    REQUIRE(pl_scan(buf, 8u * R, INT64_MIN, INT64_MAX, 0.0, 2.0, &t) == 0);
    REQUIRE(t.count == 3u && t.records == 8u && t.open_interest == 70);
    pack(6u, 100.0, 100.0, -1.0 / 365.0, 1); /* -1 day */
    REQUIRE(pl_scan(buf, 7u * R, -1, -1, 0.0, 2.0, &t) == 0);
    REQUIRE(t.count == 1u && t.open_interest == 1);
    REQUIRE(pl_scan(buf, 7u * R, 7, 7, pl_nan(), 2.0, &t) == 0); /* a NaN band end fails */
    REQUIRE(t.count == 0u);
    /* The int64 range edges of the day value: 2^63 is outside, 2^63 - 1024 and -2^63 inside,
     * -2^63 - 2048 outside. */
    pack(0u, 100.0, 100.0, 0x1.6719f3601671ap+54, 1);
    pack(1u, 100.0, 100.0, 0x1.6719f36016719p+54, 2);
    pack(2u, 100.0, 100.0, -0x1.6719f3601671ap+54, 4);
    pack(3u, 100.0, 100.0, -0x1.6719f3601671cp+54, 8);
    REQUIRE(pl_scan(buf, 4u * R, INT64_MIN, INT64_MAX, 0.0, 2.0, &t) == 0);
    REQUIRE(t.count == 2u && t.open_interest == 6);
    REQUIRE(pl_scan(buf, 4u * R, INT64_MIN + 1, INT64_C(9223372036854774783), 0.0, 2.0, &t) == 0);
    REQUIRE(t.count == 0u);
    puts("PASS scan");
}

static void scan_errors(void) {
    struct pl_scan_totals t = {5u, 5, 5u};
    REQUIRE(pl_scan(buf, 48u, 0, 100, 0.0, 2.0, &t) == -1);
    REQUIRE(pl_scan(buf, R + 1u, 0, 100, 0.0, 2.0, &t) == -1);
    REQUIRE(t.count == 5u && t.open_interest == 5 && t.records == 5u);
    REQUIRE(pl_scan(buf, R, 0, 100, 0.0, 2.0, NULL) == -1);
    REQUIRE(pl_scan(NULL, R, 0, 100, 0.0, 2.0, &t) == -1);
    REQUIRE(pl_scan(NULL, 0u, 0, 100, 0.0, 2.0, &t) == 0);
    REQUIRE(t.count == 0u && t.open_interest == 0 && t.records == 0u);
    pack(0u, 100.0, 100.0, 30.0 / 365.0, INT64_MAX);
    pack(1u, 100.0, 100.0, 30.0 / 365.0, INT64_MAX);
    t.count = 5u;
    REQUIRE(pl_scan(buf, 2u * R, 0, 100, 0.0, 2.0, &t) == -2);
    REQUIRE(t.count == 5u);
    REQUIRE(pl_scan(buf, R, 0, 100, 0.0, 2.0, &t) == 0); /* INT64_MAX alone fits */
    REQUIRE(t.open_interest == INT64_MAX);
    pack(1u, 100.0, 100.0, 30.0 / 365.0, 0);
    REQUIRE(pl_scan(buf, 2u * R, 0, 100, 0.0, 2.0, &t) == 0);
    REQUIRE(t.count == 2u && t.open_interest == INT64_MAX);
    puts("PASS scan-errors");
}

int main(void) {
    scan();
    scan_errors();
    return 0;
}
