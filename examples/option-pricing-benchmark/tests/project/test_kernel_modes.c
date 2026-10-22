#define _GNU_SOURCE
#define PL_TEST_KERNEL
#include "pl_scan.h"
#include "pl_test_batch.h"

/* Tests derived from specs/project/batch.md "pl-kernel command line": the probe mode and the
 * record-scan case (the handshake is in test_kernel_handshake.c). The input and output files are
 * written under the current directory and removed at the end. REQUIRE stays active under
 * NDEBUG. */

#define INPUT "pl-kernel-modes-test-input.bin"
#define OUT_A "pl-kernel-modes-test-a.bin"

static char nm[] = "pl-kernel";

/* The argument words of the commands (mutable arrays: argv is char **). */
static char ka[] = "--case";
static char kb[] = "probe";
static char kc[] = "--input";
static char kd[] = "pl-kernel-modes-test-input.bin";
static char ke[] = "--records";
static char kf[] = "2";
static char kg[] = "--output";
static char kh[] = "pl-kernel-modes-test-a.bin";
static char ki[] = "3";
static char kj[] = "--loops";
static char kk[] = "record-scan";
static char kl[] = "--dte-min";
static char km[] = "7";
static char kn[] = "--dte-max";
static char ko[] = "60";
static char kp[] = "--moneyness-lo";
static char kq[] = "0.9";
static char kr[] = "--moneyness-hi";
static char ks[] = "1.1";
static char kt[] = "-20";
static char ku[] = "20";

/* The commands (argv lists after the program name nm). */
static char *c_probe[] = {nm, ka, kb, kc, kd, ke, kf, kg, kh, NULL};
static char *c_probe3[] = {nm, ka, kb, kc, kd, ke, ki, kj, kf, NULL};
static char *c_scan[] = {nm, ka, kk, kc, kd, ke, ki, kl, km, kn, ko, kp, kq, kr, ks, NULL};
static char *c_scan_negative[] = {nm, ka, kk, kc, kd, ke, ki, kl, kt, kn, ku, kp, kq, kr, ks, NULL};

/* One 72-byte probe record. */
static void probe_record(uint8_t *rec, double model, double side, double sigma, uint64_t zero) {
    pl_store_f64(rec, model);
    pl_store_f64(rec + 8, side);
    pl_store_f64(rec + 16, 100.0);
    pl_store_f64(rec + 24, 100.0);
    pl_store_f64(rec + 32, 0.5);
    pl_store_f64(rec + 40, 0.04);
    pl_store_f64(rec + 48, 0.012);
    pl_store_f64(rec + 56, sigma);
    pl_store_u64(rec + 64, zero);
}

static void probe(void) {
    uint8_t buf[3u * 72u];
    probe_record(buf, 0.0, 0.0, 0.2, 0u);
    probe_record(buf + 72, 4.0, 1.0, 0.2, 0u);
    probe_record(buf + 144, 0.0, 1.0, 0.2, 0u);
    pl_tk_write_file(INPUT, buf, sizeof buf);
    REQUIRE(PL_TK_CMD(c_probe) == 0 && pl_tk_has(" probe_records=2"));
    REQUIRE(pl_tk_has(" copied_bytes=144 "));
    REQUIRE(pl_tk_read_file(OUT_A, tk_a) == 128u);
    REQUIRE(pl_load_u32(tk_a) == 0u && pl_load_u32(tk_a + 4) <= 1u);
    REQUIRE(pl_load_f64(tk_a + 8) == 0.2); /* the first value is sigma */
    const uint32_t alo = pl_load_u32(tk_a + 64);
    REQUIRE((PL_MASK_WIRED & 16u) != 0u ? alo <= 1u : alo == 2u);
    REQUIRE(PL_TK_CMD(c_probe3) == 0);
    probe_record(buf + 72, 0.5, 1.0, 0.2, 0u); /* model 0.5 */
    pl_tk_write_file(INPUT, buf, sizeof buf);
    REQUIRE(PL_TK_CMD(c_probe) == 2 && pl_tk_has("PLK1 status=FAIL reason=input\n"));
    probe_record(buf + 72, 5.0, 1.0, 0.2, 0u); /* model 5.0 */
    pl_tk_write_file(INPUT, buf, sizeof buf);
    REQUIRE(PL_TK_CMD(c_probe) == 2 && pl_tk_has("PLK1 status=FAIL reason=input\n"));
    probe_record(buf + 72, -1.0, 1.0, 0.2, 0u); /* model -1.0 */
    pl_tk_write_file(INPUT, buf, sizeof buf);
    REQUIRE(PL_TK_CMD(c_probe) == 2 && pl_tk_has("PLK1 status=FAIL reason=input\n"));
    probe_record(buf + 72, 1.0, 1.0, 0.2, 1u); /* a nonzero zero field */
    pl_tk_write_file(INPUT, buf, sizeof buf);
    REQUIRE(PL_TK_CMD(c_probe) == 2 && pl_tk_has("PLK1 status=FAIL reason=input\n"));
    puts("PASS probe");
}

/* One 49-byte record-scan record. */
static void scan_record(uint8_t *rec, double K, double T, uint64_t oi) {
    *rec = 0u;
    pl_store_f64(rec + 1, 100.0);
    pl_store_f64(rec + 9, K);
    pl_store_f64(rec + 17, T);
    pl_store_f64(rec + 25, 1.0);
    pl_store_f64(rec + 33, 1.5);
    pl_store_u64(rec + 41, oi);
}

static void record_scan(void) {
    uint8_t buf[3u * PL_SCAN_RECORD_BYTES];
    scan_record(buf, 95.0, 30.0 / 365.0, 100u);
    scan_record(buf + PL_SCAN_RECORD_BYTES, 120.0, 30.0 / 365.0, 200u);
    scan_record(buf + 2u * PL_SCAN_RECORD_BYTES, 105.0, 10.0 / 365.0, 400u);
    pl_tk_write_file(INPUT, buf, sizeof buf);
    REQUIRE(PL_TK_CMD(c_scan) == 0);
    REQUIRE(pl_tk_has("PLK1 status=OK case=record-scan records=3 loops=1 threads=0 "));
    REQUIRE(pl_tk_has(" chunks=0 chunk_sizes= chunk_wall_ns= copied_bytes=147 count=2 "));
    REQUIRE(pl_tk_has(" count=2 open_interest=500\n"));
    REQUIRE(PL_TK_CMD(c_scan_negative) == 0 && pl_tk_has(" count=1 open_interest=400"));
    scan_record(buf + PL_SCAN_RECORD_BYTES, 100.0, 30.0 / 365.0, (uint64_t)INT64_MAX);
    pl_tk_write_file(INPUT, buf, sizeof buf);
    REQUIRE(PL_TK_CMD(c_scan) == 3 && pl_tk_has("PLK1 status=FAIL reason=kernel\n"));
    puts("PASS record-scan");
}

int main(void) {
    pl_tk_setup();
    probe();
    record_scan();
    pl_tk_teardown();
    REQUIRE(remove(INPUT) == 0 && remove(OUT_A) == 0);
    return 0;
}
