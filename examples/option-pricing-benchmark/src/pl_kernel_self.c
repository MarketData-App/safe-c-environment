#include "pl_alo.h"
#include "pl_batch_core.h"
#include "pl_crr.h"
#include "pl_evaluate.h"
#include "pl_ieee.h"
#include "pl_kernel_cli.h"
#include "pl_partition.h"
#include "pl_protocol.h"
#include "pl_types.h"
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

/* pl-kernel --self-check and --print-params (specs/project/batch.md "pl-kernel command line"). */

/* The alo_scheme values of spec Amendment I item I2.2 are the C ALO constants of pl_alo.h (Task
 * 10b): --print-params prints the build's own values, and test_alo.c compares them with the
 * case manifest key alo_scheme (the c-vectors macros PL_VEC_ALO_SCHEME_*, case version 3). */

#define PL_SELF_ROWS 8u
#define PL_NAN_BITS UINT64_C(0x7ff8000000000000)

/* Row 0, model bsm (PL_VEC_EVALUATE entry 0): status ABOVE_MAX, flags rounding_band, two engine
 * evaluations, every value NaN. */
#define PL_SELF_BSM_STATUS 6u
#define PL_SELF_BSM_FLAGS 8u
#define PL_SELF_BSM_EVALS 2u

/* Row i (0-7) of PL_VEC_EVALUATE: S, K, T, bid, ask, r and q as binary64 bits. */
#define PL_D(x) pl_bits_double(UINT64_C(x))
static struct pl_row pl_self_row(size_t i) {
    struct pl_row r;
    r.side = 0;
    switch (i) {
    case 0u:
        r.side = 1;
        r.S = PL_D(0x4082c00000000000);
        r.K = PL_D(0x4076000000000000);
        r.T = PL_D(0x3f46719f3601671a);
        r.bid = PL_D(0x3f847ae147ae147b);
        r.ask = PL_D(0x3f847ae147ae147b);
        r.r = PL_D(0x3fa47ae147ae147b);
        r.q = PL_D(0x3f889374bc6a7efa);
        break;
    case 1u:
        r.side = 1;
        r.S = PL_D(0x4082c00000000000);
        r.K = PL_D(0x4081980000000000);
        r.T = PL_D(0x3f66719f3601671a);
        r.bid = PL_D(0x3f847ae147ae147b);
        r.ask = PL_D(0x3f847ae147ae147b);
        r.r = PL_D(0x3fa47ae147ae147b);
        r.q = PL_D(0x3f889374bc6a7efa);
        break;
    case 2u:
        r.side = 0;
        r.S = PL_D(0x4082c00000000000);
        r.K = PL_D(0x4088100000000000);
        r.T = PL_D(0x3f76719f3601671a);
        r.bid = PL_D(0x3f847ae147ae147b);
        r.ask = PL_D(0x3f847ae147ae147b);
        r.r = PL_D(0x3fa47ae147ae147b);
        r.q = PL_D(0x3f889374bc6a7efa);
        break;
    case 3u:
        r.side = 0;
        r.S = PL_D(0x4082c00000000000);
        r.K = PL_D(0x4089700000000000);
        r.T = PL_D(0x3f93a36b4f413a37);
        r.bid = PL_D(0x3f847ae147ae147b);
        r.ask = PL_D(0x3f847ae147ae147b);
        r.r = PL_D(0x3fa47ae147ae147b);
        r.q = PL_D(0x3f889374bc6a7efa);
        break;
    case 4u:
        r.side = 0;
        r.S = PL_D(0x4082c00000000000);
        r.K = PL_D(0x4073a00000000000);
        r.T = PL_D(0x3fa3a36b4f413a37);
        r.bid = PL_D(0x407188a3d70a3d71);
        r.ask = PL_D(0x40723fd70a3d70a4);
        r.r = PL_D(0x3fa47ae147ae147b);
        r.q = PL_D(0x3f889374bc6a7efa);
        break;
    case 5u:
        r.side = 1;
        r.S = PL_D(0x4082c00000000000);
        r.K = PL_D(0x407b600000000000);
        r.T = PL_D(0x3fb50a8542a150a8);
        r.bid = PL_D(0x3f847ae147ae147b);
        r.ask = PL_D(0x3f847ae147ae147b);
        r.r = PL_D(0x3fa47ae147ae147b);
        r.q = PL_D(0x3f889374bc6a7efa);
        break;
    case 6u:
        r.side = 0;
        r.S = PL_D(0x4082c00000000000);
        r.K = PL_D(0x4072f00000000000);
        r.T = PL_D(0x3fbf8fc7e3f1f8fc);
        r.bid = PL_D(0x40722c28f5c28f5c);
        r.ask = PL_D(0x4072eab851eb851f);
        r.r = PL_D(0x3fa47ae147ae147b);
        r.q = PL_D(0x3f889374bc6a7efa);
        break;
    default:
        r.side = 1;
        r.S = PL_D(0x4082c00000000000);
        r.K = PL_D(0x0000000000000000);
        r.T = PL_D(0x3fc50a8542a150a8);
        r.bid = PL_D(0x40714e3d70a3d70a);
        r.ask = PL_D(0x407202b851eb851f);
        r.r = PL_D(0x3fa47ae147ae147b);
        r.q = PL_D(0x3f889374bc6a7efa);
        break;
    }
    return r;
}

/* 1 when the part has the status, flags and seven value bit patterns of want. */
static int pl_same_part(const struct pl_model_result *a, const struct pl_model_result *want) {
    int same = (a->status == want->status) & (a->flags == want->flags);
    for (size_t j = 0; j < PL_FIELDS; j++) {
        same &= pl_double_bits(*(a->values + j)) == pl_double_bits(*(want->values + j));
    }
    return same;
}

/* Part 1: the Amendment E known answers. */
static int pl_self_partition(void) {
    static const uint32_t p0[10] = {0, 3, 1, 4, 8, 2, 7, 9, 5, 6};
    static const uint32_t chunked[10] = {0, 3, 1, 4, 8, 2, 7, 5, 6, 9};
    static const size_t sizes[4] = {2u, 3u, 2u, 3u};
    struct pl_random g;
    pl_random_init(&g, PL_PARTITION_SEED);
    int ok = pl_random_next(&g) == UINT64_C(0xae58eab7f35199e4);
    ok &= pl_random_next(&g) == UINT64_C(0xa16951b663213f43);
    ok &= pl_random_next(&g) == UINT64_C(0xcc4ea8b7bd8207bd);
    uint32_t perm[10], idx[10];
    uint8_t mark[10];
    ok &= pl_permutation(10u, 0u, perm, 10u) == 0;
    for (size_t i = 0; i < 10u; i++) {
        ok &= *(perm + i) == *(p0 + i);
    }
    struct pl_chunk chunks[PL_MAX_WORKERS];
    size_t count = 0u;
    ok &= pl_request_chunks(10u, 4u, 0u, perm, mark, idx, 10u, chunks, &count) == 0;
    ok &= count == 4u;
    for (size_t k = 0; k < 4u && k < count; k++) {
        ok &= (chunks + k)->count == *(sizes + k);
    }
    for (size_t i = 0; i < 10u; i++) {
        ok &= *(idx + i) == *(chunked + i);
    }
    return ok;
}

/* Part 2: row 0 through pl_evaluate (bsm) equals the constants of the vector. */
static int pl_self_row0(const struct pl_params *p) {
    const struct pl_row row = pl_self_row(0u);
    struct pl_model_result out;
    uint32_t evals = 0u;
    int ok = pl_evaluate(&row, PL_MODEL_BSM, p, &out, &evals) == PL_EVAL_OK;
    ok &= (out.status == PL_SELF_BSM_STATUS) & (out.flags == PL_SELF_BSM_FLAGS);
    ok &= evals == PL_SELF_BSM_EVALS;
    for (size_t j = 0; j < PL_FIELDS; j++) {
        ok &= pl_double_bits(*(out.values + j)) == PL_NAN_BITS;
    }
    return ok;
}

/* Part 3: the serial and the two-worker wire outputs of the eight rows are byte-identical. */
static int pl_self_pool(const struct pl_params *p) {
    struct pl_row rows[PL_SELF_ROWS];
    for (size_t i = 0; i < PL_SELF_ROWS; i++) {
        *(rows + i) = pl_self_row(i);
    }
    static uint8_t serial[PL_SELF_ROWS * PL_RESPONSE_RECORD_BYTES];
    static uint8_t pooled[PL_SELF_ROWS * PL_RESPONSE_RECORD_BYTES];
    uint32_t perm[PL_SELF_ROWS], idx[PL_SELF_ROWS];
    uint8_t mark[PL_SELF_ROWS];
    const struct pl_batch_scratch s = {perm, mark, idx, PL_SELF_ROWS};
    const struct pl_input in = {PL_INPUT_ROWS, 0u, PL_SELF_ROWS, rows, NULL, {NULL}};
    const struct pl_output so = {PL_OUTPUT_WIRE, 0u, NULL, serial};
    const struct pl_output po = {PL_OUTPUT_WIRE, 0u, NULL, pooled};
    struct pl_batch_stats ss = {0};
    struct pl_batch_stats ps = {0};
    int ok = pl_batch_run_untraced(&in, p, 0, PL_MASK_WIRED, 0u, 0u, &s, &so, &ss) == PL_BATCH_OK;
    ok &= pl_batch_run_untraced(&in, p, 0, PL_MASK_WIRED, 2u, 0u, &s, &po, &ps) == PL_BATCH_OK;
    ok &= ps.chunks == 2u;
    for (size_t j = 0; j < sizeof serial; j++) {
        ok &= *(serial + j) == *(pooled + j);
    }
    return ok;
}

/* Part 4: each one-model mask of PL_MASK_WIRED gives that model's part of the PL_MASK_WIRED
 * result bit for bit and the NOT_REQUESTED content in the other four parts. */
static int pl_self_models(const struct pl_params *p) {
    const struct pl_row row = pl_self_row(0u);
    uint64_t calls[PL_MODELS] = {0u, 0u, 0u, 0u, 0u};
    uint64_t evals[PL_MODELS] = {0u, 0u, 0u, 0u, 0u};
    struct pl_contract_result full;
    struct pl_model_result nr;
    pl_result_not_requested(&nr);
    int ok = pl_evaluate_contract(&row, p, PL_MASK_WIRED, &full, calls, evals) == PL_EVAL_OK;
    for (size_t m = 0; m < PL_MODELS; m++) {
        const uint16_t mask = (uint16_t)(1u << m);
        if ((PL_MASK_WIRED & mask) == 0u) {
            continue;
        }
        struct pl_contract_result one;
        ok &= pl_evaluate_contract(&row, p, mask, &one, calls, evals) == PL_EVAL_OK;
        for (size_t k = 0; k < PL_MODELS; k++) {
            const struct pl_model_result *want = k == m ? full.model + k : &nr;
            ok &= pl_same_part(one.model + k, want);
        }
    }
    return ok;
}

int pl_kernel_self_check(FILE *out) {
    struct pl_params p;
    pl_case_params(&p);
    const int a = pl_self_partition();
    const int b = pl_self_row0(&p);
    const int c = pl_self_pool(&p);
    const int d = pl_self_models(&p);
    if (!(a & b & c & d)) {
        return PL_REASON_KERNEL;
    }
    if (fputs("PLK1 status=OK self_check=4\n", out) == EOF || fflush(out) == EOF) {
        return PL_REASON_IO;
    }
    return PL_REASON_OK;
}

int pl_kernel_print_params(FILE *out) {
    struct pl_params p;
    pl_case_params(&p);
    const int a = fprintf(out, "PLPARAMS crr_steps=%d", p.crr_steps);
    const int b = fprintf(out, " alo_scheme=%s l=%d", PL_ALO_SCHEME_NAME, PL_ALO_GL_ORDER);
    const int c = fprintf(out, " m=%d n=%d", PL_ALO_FP_STEPS, PL_ALO_CHEB_N);
    const int d = fprintf(out, " eps=%a fp_equation=%s\n", PL_ALO_TS_EPS, PL_ALO_FP_EQUATION);
    const int n = ((a < 0) | (b < 0) | (c < 0) | (d < 0)) != 0 ? -1 : 0;
    if (n < 0 || fflush(out) == EOF) {
        return PL_REASON_IO;
    }
    return PL_REASON_OK;
}
