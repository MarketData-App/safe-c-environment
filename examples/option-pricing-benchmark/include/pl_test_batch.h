#pragma once
#include "pl_batch_core.h"
#include "pl_crr.h"
#include "pl_evaluate.h"
#include "pl_ieee.h"
#include "pl_partition.h"
#include "pl_protocol.h"
#include "pl_types.h"
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* The shared helpers of the batch and pl-kernel tests (tests/project/test_batch*.c and
 * test_kernel_*.c; specs/project/batch.md). Test code only: no source file includes this header.
 * The helpers use standard C only; the batch test files define no _GNU_SOURCE (it enlarges the
 * system headers). Every helper is static inline. The shared buffers are static arrays at file
 * scope: each test file has its own copy, and each array is one region of its own (a struct of
 * arrays exceeds the GCC analyzer budget). Sections (a test file defines at most one of the two
 * macros before its first include, so that each file holds only the helpers it uses: the AST dump
 * size of the files that include the generated evaluate header): PL_TEST_KERNEL gives the pl-kernel
 * helpers; without it the batch helpers, plus the vector-row helpers with PL_TEST_VECTOR_ROWS or
 * the synthetic-row helpers without it. Two optional sections: PL_TEST_BATCH_MASKS gives the mask
 * check pl_tb_masks; PL_TEST_BATCH_ALO (with PL_TEST_VECTOR_ROWS) gives the ALO subset rows of
 * ruling R-10b-B1. */

/* REQUIRE stays active under NDEBUG. */
#define REQUIRE_FAIL(c) (fprintf(stderr, "%s:%d: REQUIRE %s\n", __FILE__, __LINE__, #c), exit(1))
#define REQUIRE(c) ((c) ? (void)0 : REQUIRE_FAIL(c))
#define FAIL(group, i) (printf("FAIL %s %zu\n", group, (size_t)(i)), exit(1))
#define CHECK(group, i, ok) ((ok) ? (void)0 : FAIL(group, i))
/* An opaque zero (pl_request_count(0) in another translation unit): the marked loops start from
 * it, so that the GCC analyzer widens them instead of unrolling them over constant data. */
#define ZERO pl_request_count(0u)

/* The 48 test rows. */
#define PL_TB_N 48u
#define PL_TB_NAN_BITS UINT64_C(0x7FF8000000000000)
/* The largest base of an output of 290-byte records. */
#define PL_TB_BASE_MAX (SIZE_MAX / PL_RESPONSE_RECORD_BYTES)
/* bsm, bjs and crr per row in PL_VEC_EVALUATE (five models per row after Task 10b). */
#define PL_VEC_EVALUATE_PER_ROW 3u
/* Controller ruling R-10b-B1 (the protected 10 s per-test budget): the batch tests evaluate every
 * wired model but ALO on the 48 rows (PL_TB_MASK_FULL; one ALO run of the 48 rows takes about 5 s
 * in the coverage build), and check the ALO part (PL_TB_ALO_BIT) on the representative subset of
 * PL_VEC_BATCH_ALO (section PL_TEST_BATCH_ALO). The full-domain ALO proof is test_alo*.c and the
 * alo-agreement checks. */
#define PL_TB_ALO_BIT (1u << PL_MODEL_ALO)
#define PL_TB_MASK_FULL (PL_MASK_WIRED & ~PL_TB_ALO_BIT)

#ifdef PL_TEST_KERNEL
#include "pl_kernel_cli.h"

/* The pl-kernel tests: the out and err files of pl_kernel_main, the out text and two file
 * buffers. */
#define PL_TK_FILE_CAP 6000000u
#define PL_TK_TEXT_CAP 8192u

static FILE *tk_out;
static FILE *tk_err;
static char tk_text[PL_TK_TEXT_CAP];
static uint8_t tk_a[PL_TK_FILE_CAP];
static uint8_t tk_b[PL_TK_FILE_CAP];

/* Runs a command array a (argc from its size). */
#define PL_TK_CMD(a) pl_tk_run((int)(sizeof(a) / sizeof *(a)) - 1, a)

/* Opens the shared out and err files (tmpfile). */
static inline void pl_tk_setup(void) {
    tk_out = tmpfile();
    tk_err = tmpfile();
    REQUIRE(tk_out != NULL && tk_err != NULL);
}

static inline void pl_tk_teardown(void) { REQUIRE(fclose(tk_out) == 0 && fclose(tk_err) == 0); }

/* Runs pl_kernel_main with the shared out and err files; text receives what the run wrote to
 * out (the stream is rewound before the run and the write position after it is the length;
 * truncated to PL_TK_TEXT_CAP - 1 bytes). External calls only: the GCC analyzer budget. */
static inline int pl_tk_run(int argc, char **argv) {
    (void)fseek(tk_out, 0L, SEEK_SET);
    const int code = pl_kernel_main(argc, argv, tk_out, tk_err);
    (void)fflush(tk_out);
    const long end = ftell(tk_out);
    size_t want = 0u;
    if (end > 0) {
        want = (unsigned long)end < PL_TK_TEXT_CAP ? (size_t)end : PL_TK_TEXT_CAP - 1u;
    }
    (void)fseek(tk_out, 0L, SEEK_SET);
    const size_t got = fread(tk_text, 1u, want, tk_out);
    *(tk_text + got) = '\0';
    return code;
}

/* 1 when the out text of the last run contains part. */
static inline int pl_tk_has(const char *part) { return strstr(tk_text, part) != NULL; }

/* The output stream accepts no byte: /dev/full reports ENOSPC on the flush. */
static inline int pl_tk_run_full(int argc, char **argv) {
    FILE *out = fopen("/dev/full", "w");
    int code = -1;
    if (out != NULL) {
        code = pl_kernel_main(argc, argv, out, tk_err);
        (void)fclose(out);
    }
    return code;
}

static inline void pl_tk_write_file(const char *path, const uint8_t *bytes, size_t n) {
    FILE *f = fopen(path, "wb");
    REQUIRE(f != NULL);
    const size_t written = fwrite(bytes, 1u, n, f);
    const int closed = fclose(f);
    REQUIRE(written == n && closed == 0);
}

/* Reads the whole file into bytes (PL_TK_FILE_CAP bytes); returns its length (0 when the file
 * cannot be read). */
static inline size_t pl_tk_read_file(const char *path, uint8_t *bytes) {
    FILE *f = fopen(path, "rb");
    if (f == NULL) {
        return 0u;
    }
    const size_t n = fread(bytes, 1u, PL_TK_FILE_CAP, f);
    (void)fclose(f);
    return n;
}

/* 1 when the two files hold the same bytes. */
static inline int pl_tk_same_files(const char *a, const char *b) {
    const size_t na = pl_tk_read_file(a, tk_a);
    const size_t nb = pl_tk_read_file(b, tk_b);
    return na == nb && memcmp(tk_a, tk_b, na) == 0;
}

/* 1 when the file starts with the text head. */
static inline int pl_tk_file_starts(const char *path, const char *head) {
    const size_t n = pl_tk_read_file(path, tk_a);
    const size_t h = strlen(head);
    return n > h && memcmp(tk_a, head, h) == 0;
}

/* Writes eight option rows (64-byte request records) to path. */
static inline void pl_tk_write_option_input(const char *path) {
    uint8_t buf[8u * PL_REQUEST_RECORD_BYTES];
    for (size_t i = 0; i < 8u; i++) {
        const double k = 80.0 + 5.0 * (double)i;
        const double mid = 100.0 - k > 0.0 ? 100.0 - k + 4.0 : 4.0;
        const struct pl_row r = {(int)(i & 1u), 100.0, k, 0.5, mid - 0.1, mid + 0.1, 0.04, 0.012};
        pl_request_encode(&r, buf + i * PL_REQUEST_RECORD_BYTES);
    }
    pl_tk_write_file(path, buf, sizeof buf);
}

#else

/* The 48 rows in the three input forms, two result arrays and the scratch of pl_batch_run. */
static struct pl_row tb_rows[PL_TB_N];
static uint8_t tb_wire_in[PL_TB_N * PL_REQUEST_RECORD_BYTES];
static double tb_cols[8][PL_TB_N];
static struct pl_contract_result tb_serial[PL_TB_N];
static struct pl_contract_result tb_pooled[PL_TB_N];
static uint32_t tb_perm[PL_TB_N];
static uint32_t tb_idx[PL_TB_N];
static uint8_t tb_mark[PL_TB_N];

/* Stores row k (k < PL_TB_N) as a row, a request record and the eight column values. */
static inline void pl_tb_store_row(size_t k, const struct pl_row *r) {
    *(tb_rows + k) = *r;
    pl_request_encode(r, tb_wire_in + k * PL_REQUEST_RECORD_BYTES);
    *(*(tb_cols + 0) + k) = (double)r->side;
    *(*(tb_cols + 1) + k) = r->S;
    *(*(tb_cols + 2) + k) = r->K;
    *(*(tb_cols + 3) + k) = r->T;
    *(*(tb_cols + 4) + k) = r->bid;
    *(*(tb_cols + 5) + k) = r->ask;
    *(*(tb_cols + 6) + k) = r->r;
    *(*(tb_cols + 7) + k) = r->q;
}

/* pl_batch_run with the 48-row scratch, request index 0 and no trace. */
static inline int pl_tb_run(const struct pl_input *in, const struct pl_params *p, int echo,
                            unsigned models, unsigned threads, const struct pl_output *out,
                            struct pl_batch_stats *st) {
    const struct pl_batch_scratch s = {tb_perm, tb_mark, tb_idx, PL_TB_N};
    return pl_batch_run_untraced(in, p, echo, (uint16_t)models, threads, 0u, &s, out, st);
}

/* Rows base .. base + n - 1 of the 48 rows as an input of kind PL_INPUT_ROWS. */
static inline struct pl_input pl_tb_rows_input(size_t base, size_t n) {
    struct pl_input in = {PL_INPUT_ROWS, base, n, tb_rows, NULL, {NULL}};
    return in;
}

/* The 48 pooled results as an output of kind PL_OUTPUT_RESULTS at base 0. */
static inline struct pl_output pl_tb_pooled_output(void) {
    struct pl_output out = {PL_OUTPUT_RESULTS, 0u, tb_pooled, NULL};
    return out;
}

/* The eight columns of the 48 rows. */
static inline void pl_tb_set_columns(struct pl_input *in) {
    for (size_t c = 0; c < 8u; c++) {
        *(in->columns + c) = *(tb_cols + c);
    }
}

/* The PL_TB_MASK_FULL serial results of the 48 rows; wired (nullable) receives their counters. */
static inline void pl_tb_baseline(struct pl_batch_stats *wired) {
    struct pl_params p;
    pl_case_params(&p);
    const struct pl_input in = pl_tb_rows_input(0u, PL_TB_N);
    const struct pl_output out = {PL_OUTPUT_RESULTS, 0u, tb_serial, NULL};
    struct pl_batch_stats st = {0};
    REQUIRE(pl_tb_run(&in, &p, 0, PL_TB_MASK_FULL, 0u, &out, &st) == PL_BATCH_OK);
    if (wired != NULL) {
        *wired = st;
    }
}

/* 1 when the n results a and b have equal 290-byte records. */
static inline int pl_tb_same_results(const struct pl_contract_result *a,
                                     const struct pl_contract_result *b, size_t n) {
    uint8_t ra[PL_RESPONSE_RECORD_BYTES], rb[PL_RESPONSE_RECORD_BYTES];
    int same = 1;
    for (size_t i = ZERO; i < n; i++) { /* ZERO: a long loop */
        pl_response_encode(a + i, ra);
        pl_response_encode(b + i, rb);
        same &= memcmp(ra, rb, sizeof ra) == 0;
    }
    return same;
}

/* 1 when the part has the status, the flags and the seven value bit patterns w (the bits are
 * compared with memcmp: the GCC analyzer budget). */
static inline int pl_tb_same_bits(const struct pl_model_result *a, unsigned status, unsigned flags,
                                  const uint64_t *w) {
    const double *g = a->values;
    uint64_t b[PL_FIELDS];
    *(b + 0) = pl_double_bits(*(g + 0));
    *(b + 1) = pl_double_bits(*(g + 1));
    *(b + 2) = pl_double_bits(*(g + 2));
    *(b + 3) = pl_double_bits(*(g + 3));
    *(b + 4) = pl_double_bits(*(g + 4));
    *(b + 5) = pl_double_bits(*(g + 5));
    *(b + 6) = pl_double_bits(*(g + 6));
    const int s = (a->status == status) & (a->flags == flags);
    const int m = memcmp(b, w, sizeof b) == 0;
    return s & m;
}

/* 1 when the part holds exactly the NOT_REQUESTED content (G4.5; straight-line code). */
static inline int pl_tb_not_requested(const struct pl_model_result *a) {
    const uint64_t n = PL_TB_NAN_BITS;
    const uint64_t w[PL_FIELDS] = {n, n, n, n, n, n, n};
    return pl_tb_same_bits(a, PL_NOT_REQUESTED, 0u, w);
}

#ifdef PL_TEST_BATCH_MASKS
#include "pl_canonical.h"

/* The mask check of the batch (specs/project/batch.md "Batch"; G1.6, G4.8; I13.3; moved from
 * test_batch_masks.c for ruling R-10b-B1 and the file splits of ruling (g)). */
#define PL_TB_CANON_CAP 65536u

static uint8_t tb_canon_a[PL_TB_CANON_CAP], tb_canon_b[PL_TB_CANON_CAP];

/* Every mask first .. last (each within PL_MASK_WIRED), serial and with two workers (run k: mask
 * first + k / 2 with 2 (k % 2) workers), on rows 0 .. n - 1 of tb_rows, whose serial results under
 * a mask that holds every checked mask are in tb_serial with the counters wired: each selected
 * part equals the serial part (equal canonical bytes, and equal raw record bytes bit for bit), the
 * reduction equals the reduction of the serial results under the mask, the counters are the wired
 * values for each selected model and 0 for each unselected model, and every unselected part holds
 * exactly the NOT_REQUESTED content (pl_response_decode with the mask). One loop over the runs with
 * external calls only (the fixed GCC analyzer budget). */
static inline void pl_tb_masks(size_t n, unsigned first, unsigned last,
                               const struct pl_batch_stats *wired) {
    struct pl_params p;
    pl_case_params(&p);
    REQUIRE((n <= PL_TB_N) & (first >= 1u) & (first <= last));
    const struct pl_batch_scratch s = {tb_perm, tb_mark, tb_idx, PL_TB_N};
    const struct pl_input in = {PL_INPUT_ROWS, 0u, n, tb_rows, NULL, {NULL}};
    const struct pl_output out = {PL_OUTPUT_RESULTS, 0u, tb_pooled, NULL};
    const size_t runs = 2u * (size_t)(last - first + 1u);
    for (size_t k = ZERO; k < runs; k++) {
        const unsigned mask = first + (unsigned)(k / 2u);
        const uint16_t m16 = (uint16_t)mask;
        const unsigned t = 2u * (unsigned)(k % 2u);
        CHECK("masks-wired", k, (mask & ~PL_MASK_WIRED) == 0u);
        struct pl_batch_stats st = {0};
        pl_poison_results(tb_pooled, PL_TB_N);
        const int rc = pl_batch_run_untraced(&in, &p, 0, m16, t, 0u, &s, &out, &st);
        CHECK("masks-run", k, rc == PL_BATCH_OK);
        struct pl_sink a = {-1, tb_canon_a, PL_TB_CANON_CAP, 0u, 0, 0u, 0u};
        struct pl_sink c = {-1, tb_canon_b, PL_TB_CANON_CAP, 0u, 0, 0u, 0u};
        const int ra = pl_canonical_write(&a, tb_pooled, n, m16);
        const int rb = pl_canonical_write(&c, tb_serial, n, m16);
        const int len = (ra == 0) & (rb == 0) & (a.len == c.len);
        CHECK("masks-selected", k, len && memcmp(tb_canon_a, tb_canon_b, a.len) == 0);
        struct pl_reduction red, ref;
        pl_reduce(tb_pooled, n, m16, &red);
        pl_reduce(tb_serial, n, m16, &ref);
        const int counts = memcmp(red.counts, ref.counts, sizeof red.counts) == 0;
        const int index = memcmp(red.max_iv_index, ref.max_iv_index, sizeof red.max_iv_index) == 0;
        const int iv = memcmp(red.max_iv, ref.max_iv, sizeof red.max_iv) == 0;
        CHECK("masks-reduction", k, counts & index & iv);
        uint64_t want_calls[PL_MODELS], want_evals[PL_MODELS];
        *(want_calls + 0) = (mask & 1u) * *(wired->calls + 0);
        *(want_calls + 1) = ((mask >> 1u) & 1u) * *(wired->calls + 1);
        *(want_calls + 2) = ((mask >> 2u) & 1u) * *(wired->calls + 2);
        *(want_calls + 3) = ((mask >> 3u) & 1u) * *(wired->calls + 3);
        *(want_calls + 4) = ((mask >> 4u) & 1u) * *(wired->calls + 4);
        *(want_evals + 0) = (mask & 1u) * *(wired->evals + 0);
        *(want_evals + 1) = ((mask >> 1u) & 1u) * *(wired->evals + 1);
        *(want_evals + 2) = ((mask >> 2u) & 1u) * *(wired->evals + 2);
        *(want_evals + 3) = ((mask >> 3u) & 1u) * *(wired->evals + 3);
        *(want_evals + 4) = ((mask >> 4u) & 1u) * *(wired->evals + 4);
        const int calls = memcmp(st.calls, want_calls, sizeof want_calls) == 0;
        const int evals = memcmp(st.evals, want_evals, sizeof want_evals) == 0;
        CHECK("masks-counters", k, calls & evals);
        for (size_t i = ZERO; i < n; i++) {
            uint8_t rec[PL_RESPONSE_RECORD_BYTES], ser[PL_RESPONSE_RECORD_BYTES];
            uint8_t want[PL_RESPONSE_RECORD_BYTES];
            struct pl_contract_result decoded;
            struct pl_model_result part;
            pl_response_encode(tb_pooled + i, rec);
            pl_response_encode(tb_serial + i, ser);
            /* The expected raw record: each selected part from the serial record, each
             * unselected part from the batch record (bit for bit, -0.0 and NaN payloads
             * included). */
            const uint8_t *src[2] = {rec, ser};
            pl_load_part(*(src + (mask & 1u)), 0u, &part);
            pl_store_part(want, 0u, &part);
            pl_load_part(*(src + ((mask >> 1u) & 1u)), 1u, &part);
            pl_store_part(want, 1u, &part);
            pl_load_part(*(src + ((mask >> 2u) & 1u)), 2u, &part);
            pl_store_part(want, 2u, &part);
            pl_load_part(*(src + ((mask >> 3u) & 1u)), 3u, &part);
            pl_store_part(want, 3u, &part);
            pl_load_part(*(src + ((mask >> 4u) & 1u)), 4u, &part);
            pl_store_part(want, 4u, &part);
            const int raw = memcmp(want, rec, sizeof rec) == 0;
            const enum pl_proto_error e = pl_response_decode(rec, m16, &decoded);
            CHECK("masks-parts", 64u * k + i, raw & (e == PL_PROTO_OK));
        }
    }
}
#endif

#ifdef PL_TEST_VECTOR_ROWS

/* The row of a vector entry v (a struct pl_vec_evaluate or pl_vec_evaluate_baw). */
#define PL_TB_VEC_ROW(v)                                                                           \
    pl_tb_row_bits((v)->side, (v)->S, (v)->K, (v)->T, (v)->bid, (v)->ask, (v)->r, (v)->q)
/* 1 when the part a equals the vector entry v: status, flags, value bits or both NaN. */
#define PL_TB_SAME_AS_VECTOR(a, v)                                                                 \
    pl_tb_same_vector(a, (v)->status, (v)->flags, (v)->iv, (v)->price, (v)->delta, (v)->gamma,     \
                      (v)->theta, (v)->vega, (v)->rho)

/* The row with the side and the seven field bit patterns. */
static inline struct pl_row pl_tb_row_bits(int side, uint64_t S, uint64_t K, uint64_t T,
                                           uint64_t bid, uint64_t ask, uint64_t r, uint64_t q) {
    struct pl_row row;
    row.side = side;
    row.S = pl_bits_double(S);
    row.K = pl_bits_double(K);
    row.T = pl_bits_double(T);
    row.bid = pl_bits_double(bid);
    row.ask = pl_bits_double(ask);
    row.r = pl_bits_double(r);
    row.q = pl_bits_double(q);
    return row;
}

/* 1 when the three vector entries of a row are the synthetic prefix: no defect, models 0, 1, 2. */
static inline int pl_tb_prefix_entry(int d0, int d1, int d2, int m0, int m1, int m2) {
    const int prefix = (d0 == 0) & (d1 == 0) & (d2 == 0);
    return prefix & (m0 == 0) & (m1 == 1) & (m2 == 2);
}

/* Loads the 48 rows from PL_VEC_BATCH_ROWS, the rows of the synthetic prefix of PL_VEC_EVALUATE
 * (the first 144 entries, three per row; test_batch_trap.c checks that the rows are equal and that
 * the prefix entries are bsm, bjs and crr without a defect). Expands only in a file that includes
 * pl_vec_batch_rows.h (Task 10b: the large pl_vec_evaluate.h in every batch test exceeded the
 * memory of the source-policy step of the ast gate). */
#define PL_TB_LOAD_VECTOR_ROWS()                                                                   \
    do {                                                                                           \
        REQUIRE(PL_VEC_BATCH_ROWS_COUNT == PL_TB_N);                                               \
        for (size_t k_ = ZERO; k_ < PL_TB_N; k_++) {                                               \
            const struct pl_vec_batch_rows *v_ = PL_VEC_BATCH_ROWS + k_;                           \
            const struct pl_row r_ = PL_TB_VEC_ROW(v_);                                            \
            pl_tb_store_row(k_, &r_);                                                              \
        }                                                                                          \
    } while (0)

/* 1 when the double g has the bits w, or both are NaN (an expression, no call: the GCC analyzer
 * budget). */
#define PL_TB_SAME(g, w)                                                                           \
    ((pl_double_bits(g) == (w)) | (pl_is_nan(g) & pl_is_nan(pl_bits_double(w))))

/* 1 when the part has the status, the flags and the seven values (bits, or both NaN) of a vector
 * entry (straight-line code, as test_evaluate.c: the GCC analyzer budget). */
static inline int pl_tb_same_vector(const struct pl_model_result *a, int status, int flags,
                                    uint64_t iv, uint64_t price, uint64_t delta, uint64_t gamma,
                                    uint64_t theta, uint64_t vega, uint64_t rho) {
    const double *g = a->values;
    const int s = (a->status == status) & (a->flags == flags);
    const int x = PL_TB_SAME(*(g + 0), iv) & PL_TB_SAME(*(g + 1), price);
    const int y = PL_TB_SAME(*(g + 2), delta) & PL_TB_SAME(*(g + 3), gamma);
    const int z = PL_TB_SAME(*(g + 4), theta) & PL_TB_SAME(*(g + 5), vega);
    return s & x & y & z & PL_TB_SAME(*(g + 6), rho);
}

#ifdef PL_TEST_BATCH_ALO
#include "pl_vec_batch_alo.h"

/* Ruling R-10b-B1: the ALO part of the batch tests runs on the representative subset
 * PL_VEC_BATCH_ALO (cvectors.BATCH_ALO_ROWS, in this order: alo-invalid, alo-expired, alo-put-ok,
 * alo-call-ok (FP-B put and call), alo-put-switch-last-fp-a, alo-call-switch-last-fp-a (FP-A put
 * and call), alo-put-european-edge, alo-call-european-edge, alo-put-double-boundary,
 * alo-brent-fallback, alo-put-zero-rate-unresolved (stencil_unresolved), alo-put-forward-vega and
 * alo-put-below-sigma-lo (next to sigma_lo)): one or two rows per ALO branch class, because one
 * ALO run of the 48 rows takes about 5 s in the coverage build. The vector entries are
 * reference.evaluate of alo under the case parameters. */
#define PL_TB_ALO_N ((size_t)PL_VEC_BATCH_ALO_COUNT)

/* Rows 0 .. PL_TB_ALO_N - 1 of tb_rows from PL_VEC_BATCH_ALO. */
static inline void pl_tb_load_alo_rows(void) {
    REQUIRE((PL_TB_ALO_N > 0u) & (PL_TB_ALO_N <= PL_TB_N));
    for (size_t k = 0; k < PL_TB_ALO_N; k++) {
        const struct pl_vec_batch_alo *v = PL_VEC_BATCH_ALO + k;
        const struct pl_row r = PL_TB_VEC_ROW(v);
        pl_tb_store_row(k, &r);
    }
}

/* The PL_MASK_WIRED serial results of the subset rows in tb_serial: each ALO part equals its
 * vector entry and the ALO counters equal the vector counts (H17); every model counts one call per
 * row. wired (nullable) receives the counters. */
static inline void pl_tb_alo_baseline(struct pl_batch_stats *wired) {
    struct pl_params p;
    pl_case_params(&p);
    const struct pl_input in = pl_tb_rows_input(0u, PL_TB_ALO_N);
    const struct pl_output out = {PL_OUTPUT_RESULTS, 0u, tb_serial, NULL};
    struct pl_batch_stats st = {0};
    REQUIRE(pl_tb_run(&in, &p, 0, PL_MASK_WIRED, 0u, &out, &st) == PL_BATCH_OK);
    uint64_t evals = 0u;
    for (size_t k = 0; k < PL_TB_ALO_N; k++) {
        const struct pl_vec_batch_alo *v = PL_VEC_BATCH_ALO + k;
        CHECK("alo-baseline", k, PL_TB_SAME_AS_VECTOR((tb_serial + k)->model + PL_MODEL_ALO, v));
        evals += (uint64_t)v->engine_evals;
    }
    int ok = *(st.evals + PL_MODEL_ALO) == evals;
    for (size_t m = 0; m < PL_MODELS; m++) {
        ok &= *(st.calls + m) == (uint64_t)PL_TB_ALO_N;
    }
    REQUIRE(ok);
    if (wired != NULL) {
        *wired = st;
    }
}
#endif

#else

/* The 48 synthetic rows (calls and puts, strikes 76-123, maturities 1-48 weeks, quotes around a
 * plausible price): the limit tests need valid rows, not vector values, so their files do not
 * include the large generated evaluate header (the memory of the source-policy step of the ast
 * gate). */
static inline void pl_tb_load_synthetic(void) {
    for (size_t k = 0; k < PL_TB_N; k++) {
        const double x = (double)k;
        struct pl_row r;
        r.side = (int)(k % 2u);
        r.S = 100.0;
        r.K = 76.0 + x;
        r.T = (x + 1.0) / 52.0;
        r.bid = 2.0 + 0.25 * x;
        r.ask = 2.5 + 0.25 * x;
        r.r = 0.04;
        r.q = 0.012;
        pl_tb_store_row(k, &r);
    }
}

/* n = 0, 1 and 48 with w workers (no loop: the GCC analyzer budget). Needs the baseline. */
static inline void pl_tb_small_size(const struct pl_params *p, unsigned w) {
    struct pl_output out = pl_tb_pooled_output();
    struct pl_input zero = pl_tb_rows_input(0u, 0u);
    struct pl_batch_stats st = {0};
    REQUIRE(pl_tb_run(&zero, p, 0, 7u, w, &out, &st) == PL_BATCH_OK);
    REQUIRE(st.chunks == 0u && *(st.calls + 0) == 0u);
    struct pl_input one = pl_tb_rows_input(5u, 1u);
    struct pl_output o5 = {PL_OUTPUT_RESULTS, 5u, tb_pooled, NULL};
    struct pl_batch_stats s1 = {0};
    pl_poison_results(tb_pooled, PL_TB_N);
    REQUIRE(pl_tb_run(&one, p, 0, PL_TB_MASK_FULL, w, &o5, &s1) == PL_BATCH_OK);
    uint8_t a[PL_RESPONSE_RECORD_BYTES], b[PL_RESPONSE_RECORD_BYTES];
    pl_response_encode(tb_pooled + 5, a);
    pl_response_encode(tb_serial + 5, b);
    REQUIRE(s1.chunks == (w == 0u ? 0u : 1u) && memcmp(a, b, sizeof a) == 0);
    REQUIRE(pl_tb_not_requested((tb_pooled + 4)->model));
    REQUIRE(pl_tb_not_requested((tb_pooled + 6)->model));
    struct pl_input full = pl_tb_rows_input(0u, PL_TB_N);
    struct pl_batch_stats sf = {0};
    REQUIRE(pl_tb_run(&full, p, 1, 7u, w, &out, &sf) == PL_BATCH_OK && sf.chunks == w);
}

#endif
#endif
