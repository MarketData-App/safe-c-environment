#include "pl_alo.h"
#include "pl_alo_equation.h"
#include "pl_ieee.h"
#include "pl_vec_alo_equation.h"
#include "pl_vec_alo_tables.h"
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

/* Bit-exact tests of the shared ALO equation choice and segment and of the ALO tables
 * (specs/project/models.md "ALO (Amendment I)") against the optionlab vectors: alo_equation with
 * every intermediate (I2.4), alo_segment for a call and a put (I2.6), the frozen Gauss-Legendre
 * table of record R5, the 14 Chebyshev nodes and barycentric weights, and the tanh-sinh rows of
 * tanh_sinh_detail<double> (rows 0-7 every entry, rows 8-14 the sampled entries, every row length
 * and first complement index, the FNV-1a digest of every entry of every row, t_crossover). Groups
 * print "PASS <group>" and counts; the first failed check prints "FAIL <group> <index>" and exits
 * 1 (REQUIRE-style, active under NDEBUG; no failure counter: one state per check for the fixed GCC
 * analyzer budget). */

/* The checks are macros, not functions, so that the GCC analyzer explores each check at its own
 * place (the fixed analyzer budget, as test_crr.c). same: equal bits, or both NaN. */
#define require(group, index, ok)                                                                  \
    ((ok) ? (void)0 : (void)(printf("FAIL %s %zu\n", group, (size_t)(index)), exit(1)))
#define same(group, index, got, want)                                                              \
    require(group, index,                                                                          \
            (pl_double_bits(got) == (want)) | (pl_is_nan(got) & pl_is_nan(pl_bits_double(want))))

static const char *verdict(int ok) { return ok ? "PASS" : "FAIL"; }

#define D(x) pl_bits_double(x)
/* An opaque zero (pl_double_bits of another translation unit): the table loops start from it, so
 * that the GCC analyzer widens them instead of unrolling them over constant data. */
#define OPAQUE_ZERO ((size_t)pl_double_bits(0.0))

/* The Auto bound 0.001 of alo_equation (qdfpamericanengine.cpp:457) as bits. */
#define PL_ALO_SWITCH_BITS UINT64_C(0x3f50624dd2f1a9fc)

/* I2.4: the shared alo_equation, every intermediate bit for bit. The table must hold an Auto tie
 * row of each sign (ruling R-10c, T10B-TIE-GUARD-01): abs_diff (intermediate 4) with the bits of
 * 0.001 and r_e > q_e, and one with r_e < q_e (cvectors.alo_switch_tie_rows). */
static void equation(void) {
    size_t fp_a = 0u, fp_b = 0u, compared = 0u, defects = 0u, tie_above = 0u, tie_below = 0u;
    const size_t fields = PL_VEC_ALO_EQUATION_FIELDS;
    require("equation-fields", 0u, fields == PL_ALO_RATES_FIELDS);
    require("equation-fields", 1u, fields <= PL_ALO_EQUATION_MAX_FIELDS);
    for (size_t i = OPAQUE_ZERO; i < PL_VEC_ALO_EQUATION_COUNT; i++) {
        const struct pl_vec_alo_equation *v = PL_VEC_ALO_EQUATION + i;
        struct pl_alo_rates a;
        pl_alo_equation(D(v->r1), D(v->q1), &a);
        const int head = (a.defect == v->defect) & (a.equation == v->equation);
        require("equation", i, head & (a.count == fields));
        for (size_t f = 0; f < fields; f++) {
            const size_t at = i * PL_ALO_EQUATION_MAX_FIELDS + f;
            same("equation-intermediate", at, *(a.values + f), *(v->values + f));
            compared++;
        }
        const int ok = v->defect == 0;
        fp_a += (ok && v->equation == PL_ALO_FP_A) ? 1u : 0u;
        fp_b += (ok && v->equation == PL_ALO_FP_B) ? 1u : 0u;
        defects += ok ? 0u : 1u;
        /* Branch-free counts (the fixed GCC analyzer budget). */
        const int tie = ok & (*(v->values + 4) == PL_ALO_SWITCH_BITS);
        const double r_e = D(*(v->values + 2));
        const double q_e = D(*(v->values + 3));
        tie_above += (size_t)(tie & (r_e > q_e));
        tie_below += (size_t)(tie & (r_e < q_e));
    }
    require("equation-tie", 0u, pl_double_bits(0.001) == PL_ALO_SWITCH_BITS);
    require("equation-tie", 1u, tie_above > 0u);
    require("equation-tie", 2u, tie_below > 0u);
    const int seen = fp_a > 0u && fp_b > 0u && defects > 0u;
    const int ok = seen && compared == PL_VEC_ALO_EQUATION_COUNT * fields;
    require("equation-coverage", 0u, ok);
    printf("%s equation fp-a %zu fp-b %zu defects %zu compared %zu ties %zu %zu\n", verdict(ok),
           fp_a, fp_b, defects, compared, tie_above, tie_below);
}

/* One segment row: every member of pl_alo_segment equals the vector. */
static int segment_same(const struct pl_alo_segment *s, const struct pl_vec_alo_segment *v) {
    const int a = (s->defect == v->defect) & (s->equation == v->equation);
    const int b = (s->european_edge == v->european_edge);
    const int c = (s->double_boundary == v->double_boundary) & (s->xmax_case == v->xmax_case);
    return a & b & c & (s->r_over_q_below_one == v->r_over_q_below_one);
}

/* I2.6: alo_segment, every branch test, and pl_alo_segment_equal. */
static void segment(void) {
    size_t edge = 0u, boundary = 0u, first = 0u, below = 0u, defects = 0u;
    size_t cases[8] = {0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u};
    for (size_t i = OPAQUE_ZERO; i < PL_VEC_ALO_SEGMENT_COUNT; i++) {
        const struct pl_vec_alo_segment *v = PL_VEC_ALO_SEGMENT + i;
        struct pl_alo_segment s;
        pl_alo_segment(v->side, D(v->r1), D(v->q1), &s);
        require("segment", i, segment_same(&s, v));
        struct pl_alo_segment t = s;
        require("segment-equal", i, pl_alo_segment_equal(&s, &t));
        t.r_over_q_below_one = s.r_over_q_below_one + 1;
        require("segment-unequal", i, !pl_alo_segment_equal(&s, &t));
        edge += v->european_edge != 0 ? 1u : 0u;
        boundary += v->double_boundary != 0 ? 1u : 0u;
        first += v->xmax_case == 1 ? 1u : 0u;
        below += v->r_over_q_below_one == 1 ? 1u : 0u;
        defects += v->defect != 0 ? 1u : 0u;
        if (v->xmax_case >= 0 && v->xmax_case < 8) {
            *(cases + v->xmax_case) += 1u;
        }
    }
    struct pl_alo_segment bad;
    pl_alo_segment(2, 0.04, 0.012, &bad);
    require("segment-side", 0u, (bad.defect == 1) & (bad.equation == -1));
    int all_cases = 1;
    for (size_t k = 1; k < 8u; k++) {
        all_cases &= *(cases + k) > 0u;
    }
    const int seen = edge > 0u && boundary > 0u && first > 0u && below > 0u;
    const int ok = seen && defects > 0u && all_cases;
    require("segment-coverage", 0u, ok);
    printf("%s segment edge %zu double-boundary %zu xmax-first %zu below-one %zu\n", verdict(ok),
           edge, boundary, first, below);
}

/* The frozen Gauss-Legendre table and the Chebyshev nodes and weights. */
static void nodes(void) {
    const uint64_t gl_x[PL_ALO_GL_ORDER] = PL_VEC_ALO_GL_X;
    const uint64_t gl_w[PL_ALO_GL_ORDER] = PL_VEC_ALO_GL_W;
    for (int i = 0; i < PL_ALO_GL_ORDER; i++) {
        same("gl-x", (size_t)i, pl_alo_gl_node(i), *(gl_x + i));
        same("gl-w", (size_t)i, pl_alo_gl_weight(i), *(gl_w + i));
    }
    require("gl-range", 0u, pl_is_nan(pl_alo_gl_node(-1)) & pl_is_nan(pl_alo_gl_node(25)));
    require("gl-range", 1u, pl_is_nan(pl_alo_gl_weight(-1)) & pl_is_nan(pl_alo_gl_weight(25)));
    const uint64_t cheb[PL_ALO_CHEB_NODES] = PL_VEC_ALO_CHEB;
    const uint64_t lambda[PL_ALO_CHEB_NODES] = PL_VEC_ALO_CHEB_LAMBDA;
    double x[PL_ALO_CHEB_NODES];
    double w[PL_ALO_CHEB_NODES];
    pl_alo_cheb_nodes(x, w);
    for (int i = 0; i < PL_ALO_CHEB_NODES; i++) {
        same("cheb", (size_t)i, *(x + i), *(cheb + i));
        same("cheb-lambda", (size_t)i, *(w + i), *(lambda + i));
    }
    same("t-crossover", 0u, pl_alo_ts_crossover(), PL_VEC_ALO_T_CROSSOVER);
}

/* (a b) mod 2^64 from 32-bit limbs: every product and sum stays below 2^64 (no unsigned wrap for
 * the integer sanitizer). */
static uint64_t mul_mod64(uint64_t a, uint64_t b) {
    const uint64_t m32 = UINT64_C(0xffffffff);
    const uint64_t a0 = a & m32;
    const uint64_t a1 = a >> 32u;
    const uint64_t b0 = b & m32;
    const uint64_t b1 = b >> 32u;
    const uint64_t lo = a0 * b0;
    const uint64_t cross = ((a0 * b1) & m32) + ((a1 * b0) & m32);
    const uint64_t high = ((lo >> 32u) + cross) & m32;
    return (high << 32u) | (lo & m32);
}

/* One FNV-1a 64 step: (h xor byte) times the prime 0x100000001b3, modulo 2^64. For the fixed GCC
 * analyzer budget the operand and the new state pass through pl_bits_double and pl_double_bits
 * (another translation unit; a union copy, so the bits are unchanged), which keeps the analyzer's
 * symbolic values small. */
static uint64_t fnv_byte(uint64_t h, uint64_t byte) {
    const uint64_t x = pl_double_bits(pl_bits_double(h ^ byte));
    return pl_double_bits(pl_bits_double(mul_mod64(x, UINT64_C(0x100000001b3))));
}

/* T10B-TS-SAMPLE-01 (ruling R-10c): every entry of every tanh-sinh row through the digest of
 * cvectors.alo_ts_digest, recomputed from pl_alo_ts_entry in entry order (abscissa bits, then
 * weight bits, for j = 0 ... length - 1). One loop over the 16 bytes of every entry of a row, t =
 * 16 j + k: byte k < 8 is byte k of the abscissa bits, byte k >= 8 byte k - 8 of the weight bits,
 * least significant byte first. For the fixed GCC analyzer budget the loop has no branch and one
 * call site of fnv_byte; it reads entry j again for each of its 16 bytes. Returns the number of
 * entries folded. */
static size_t digests(void) {
    size_t entries = 0u;
    for (size_t i = OPAQUE_ZERO; i < PL_VEC_ALO_TS_DIGEST_COUNT; i++) {
        const struct pl_vec_alo_ts_digest *v = PL_VEC_ALO_TS_DIGEST + i;
        int length = -1;
        int fc = -1;
        const int rc = pl_alo_ts_row(v->level, &length, &fc);
        require("ts-digest-row", i, (rc == 0) & (length == v->length) & (v->level == (int)i));
        /* A failed entry sets bad (no branch). */
        int bad = 0;
        uint64_t h = UINT64_C(0xcbf29ce484222325);
        const unsigned bytes = 16u * (unsigned)length;
        for (unsigned t = (unsigned)OPAQUE_ZERO; t < bytes; t++) {
            double a = 0.0;
            double w = 0.0;
            bad |= pl_alo_ts_entry(v->level, (int)(t >> 4u), &a, &w) != 0;
            const uint64_t second = (uint64_t)((t >> 3u) & 1u); /* 0: abscissa, 1: weight */
            const uint64_t word = pl_double_bits(a) * (1u - second) + pl_double_bits(w) * second;
            h = fnv_byte(h, (word >> ((t & 7u) * 8u)) & UINT64_C(0xff));
        }
        require("ts-digest", i, (bad == 0) & (h == v->fnv1a));
        entries += (size_t)length;
    }
    require("ts-digest-rows", 0u, PL_VEC_ALO_TS_DIGEST_COUNT == PL_VEC_ALO_TS_ROWS_COUNT);
    return entries;
}

/* The tanh-sinh rows: every row length and first complement, the sampled entries, the digest of
 * every entry. */
static void tables(void) {
    for (size_t i = OPAQUE_ZERO; i < PL_VEC_ALO_TS_ROWS_COUNT; i++) {
        const struct pl_vec_alo_ts_rows *v = PL_VEC_ALO_TS_ROWS + i;
        int length = -1;
        int fc = -1;
        const int rc = pl_alo_ts_row(v->level, &length, &fc);
        require("ts-row", i, (rc == 0) & (length == v->length) & (fc == v->first_complement));
    }
    int length = 0;
    int fc = 0;
    require("ts-row-range", 0u, pl_alo_ts_row(-1, &length, &fc) == 1);
    require("ts-row-range", 1u, pl_alo_ts_row(PL_ALO_TS_ROWS, &length, &fc) == 1);
    require("ts-row-range", 2u, pl_alo_ts_row(PL_ALO_TS_ROWS - 1, &length, &fc) == 0);
    size_t computed = 0u;
    for (size_t i = OPAQUE_ZERO; i < PL_VEC_ALO_TS_COUNT; i++) {
        const struct pl_vec_alo_ts *v = PL_VEC_ALO_TS + i;
        double a = 0.0;
        double w = 0.0;
        require("ts-entry", i, pl_alo_ts_entry(v->level, v->index, &a, &w) == 0);
        same("ts-abscissa", i, a, v->abscissa);
        same("ts-weight", i, w, v->weight);
        computed += v->level >= PL_ALO_TS_TABLE_ROWS ? 1u : 0u;
    }
    double a = 0.0;
    double w = 0.0;
    require("ts-entry-range", 0u, pl_alo_ts_entry(0, 7, &a, &w) == 1);
    require("ts-entry-range", 1u, pl_alo_ts_entry(8, -1, &a, &w) == 1);
    require("ts-entry-range", 2u, pl_alo_ts_entry(8, 768, &a, &w) == 1);
    require("ts-entry-range", 3u, pl_alo_ts_entry(PL_ALO_TS_ROWS, 0, &a, &w) == 1);
    const size_t digested = digests();
    /* 98,305 entries: 769 in the tabulated rows 0-7, 97,536 in the computed rows 8-14. */
    const int ok = PL_VEC_ALO_TS_ROWS_COUNT == 15u && computed > 0u && digested == 98305u;
    require("tables-coverage", 0u, ok);
    printf("%s tables ts %zu computed %zu digested %zu\n", verdict(ok), PL_VEC_ALO_TS_COUNT,
           computed, digested);
}

int main(void) {
    equation();
    segment();
    nodes();
    tables();
    return 0;
}
