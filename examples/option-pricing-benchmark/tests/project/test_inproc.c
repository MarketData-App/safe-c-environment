#include "pl_test_inproc.h"

/* Test derived from specs/project/inproc.md (Amendment G ABI 2, Review Focus 4 and 6). Groups: abi,
 * same-bytes, arguments, echo, in-place, masks, reentrant and stats (threads 0, 1, 2 and 4). One
 * translation unit holds them all (see pl_test_inproc.h: the AST dump of every project unit uses
 * the fixed /work space of the project container). Each group is a function that main calls; a
 * repeated step is a loop over a table whose body calls library functions and ti_call (the fixed
 * GCC analyzer budget). The refusal of a mask outside PL_MASK_WIRED is in the arguments table. */

static const uint32_t ti_threads[4] = {0u, 1u, 2u, 4u};
static const uint32_t ti_masks[4] = {1u, 8u, 16u, 31u};

/* Group abi: the ABI version, the output length and the scratch length. */
static void group_abi(void) {
    REQUIRE(pl_inproc_abi_version() == 2u);
    REQUIRE(PL_INPROC_ABI == 2u);
    REQUIRE(pl_inproc_out_len(8u, 2u) == 2356u);
    REQUIRE(pl_inproc_out_len(8u, 0u) == 2324u);
    REQUIRE(pl_inproc_out_len(1u, 4u) == 290u + 4u + 16u);
    REQUIRE(pl_inproc_out_len(14336u, 4u) == 4157508u);
    REQUIRE(pl_inproc_scratch_len(8u) == 136u);
    REQUIRE(pl_inproc_scratch_len(14336u) == 129088u);
    REQUIRE(pl_inproc_out_len(8u, 2u) == pl_response_payload(8u, 2u));
    /* both lengths saturate: no wrap for n above (SIZE_MAX - 64) / 9 */
    REQUIRE(pl_inproc_scratch_len(SIZE_MAX) == SIZE_MAX);
    REQUIRE(pl_inproc_scratch_len((SIZE_MAX - 64u) / 9u) == 9u * ((SIZE_MAX - 64u) / 9u) + 64u);
    REQUIRE(pl_inproc_scratch_len((SIZE_MAX - 64u) / 9u + 1u) == SIZE_MAX);
    REQUIRE(pl_inproc_out_len(SIZE_MAX, 0xFFFFFFFFu) == pl_response_payload(UINT32_MAX, 65535u));
    puts("PASS abi");
}

/* Group same-bytes: eight rows in eight double columns give the pl_batch_run bytes (PL_INPUT_ROWS,
 * PL_OUTPUT_WIRE) and the trailer after the records (chunk count and chunk sizes; k chunks), for
 * threads 0, 1, 2 and 4, and the same record bytes for every threads value (ti_out2 keeps the
 * records of threads 0). Mask 7. The trailer is compared without the wall times: its count and
 * the 8 bytes of each of the four possible entries before the wall time (both buffers hold zero
 * bytes past their trailer). */
static void group_same(void) {
    struct ti_args a;
    struct pl_contract_result r;
    const size_t at = TI_N * PL_RESPONSE_RECORD_BYTES;
    ti_load8();
    ti_set_args(&a, TI_N, 0u, 7u);
    ti_out_s = ti_zero_out;
    CASE(99, ti_call(&a, NULL) == PL_INPROC_OK);
    ti_out2_s = ti_out_s;
    for (size_t j = ZERO; j < 4u; j++) {
        const uint32_t threads = *(ti_threads + j);
        struct pl_batch_stats ref_stats = {0};
        struct pl_batch_stats st = {0};
        ti_out_s = ti_zero_out;
        CASE(j, ti_reference(TI_N, threads, threads, 7u, &ref_stats) == PL_BATCH_OK);
        a.threads = threads;
        a.out_len = pl_inproc_out_len(TI_N, threads);
        CASE(j, ti_call(&a, &st) == PL_INPROC_OK);
        CASE(j, memcmp(ti_out, ti_ref, at) == 0);
        CASE(j, memcmp(ti_out + at, ti_ref + at, 4u) == 0);
        CASE(j, memcmp(ti_out + at + 4u, ti_ref + at + 4u, 8u) == 0);
        CASE(j, memcmp(ti_out + at + 20u, ti_ref + at + 20u, 8u) == 0);
        CASE(j, memcmp(ti_out + at + 36u, ti_ref + at + 36u, 8u) == 0);
        CASE(j, memcmp(ti_out + at + 52u, ti_ref + at + 52u, 8u) == 0);
        CASE(j, st.chunks == threads);
        CASE(j, ref_stats.chunks == threads);
        CASE(j, memcmp(ti_out, ti_out2, at) == 0);
        CASE(j, ti_decode(ti_out, 0u, 7u, &r) == PL_PROTO_OK);
        CASE(j, ti_decode(ti_out, TI_N - 1u, 7u, &r) == PL_PROTO_OK);
    }
    puts("PASS same-bytes");
}

/* Group arguments: the table of wrong arguments, with the lengths written out (an independent
 * oracle: 8 rows with 2 threads need 8 x 290 + 4 + 16 x 2 = 2356 output bytes and 9 x 8 + 64 = 136
 * scratch bytes; 2 rows with 2 threads need 616 and 82). Each case returns PL_INPROC_ARGUMENT and
 * leaves the sentinel-filled out and scratch buffers unchanged. Rows 9-11 put a column or the
 * scratch inside ti_out or ti_scratch; rows 12 and 13 use ti_scratch as out and a column as the
 * scratch, so that a wrong write would still land in static memory. Cases 0-4 pointers
 * (null and misaligned columns), 5-8 null and misaligned out and scratch, 9-13 overlaps, 14-17
 * counts and threads (n = 0 needs 4 and 64 bytes, n = 14,337 needs 4,157,766 and 129,097, threads
 * 5 needs 2,404), 18-22 masks 0, 32, 33, 65535 and 65536, 23-26 lengths one short and one long,
 * 27-30 the masks 32, 64, 0x8000 and 0xFFFF on two rows with two threads (the masks group). A
 * constant table, so that the analyzer reads a case as an unknown row and not as 31 stores. */
#define TI_CASES 31u
#define TC0 TI_COL(0u)
#define TC1 TI_COL(1u)
#define TC2 TI_COL(2u)
#define TC3 TI_COL(3u)
#define TC4 TI_COL(4u)
#define TC5 TI_COL(5u)
#define TC6 TI_COL(6u)
#define TC7 TI_COL(7u)
#define TOUT ti_out
#define TSCR ti_scratch
#define TCOLS TC0, TC1, TC2, TC3, TC4, TC5, TC6, TC7
/* Column 3 and 5 four bytes past the column start (misaligned); column 3 inside ti_out; column 0
 * inside ti_scratch; ti_scratch where the scratch is the column 2. */
#define TM3 ((const double *)(const void *)((const char *)TC3 + 4))
#define TM5 ((const double *)(const void *)((const char *)TC5 + 4))
#define TO3 ((const double *)(const void *)(ti_out + 16))
#define TS0 ((const double *)(const void *)(ti_scratch + 8))
#define TSC2 ((uint8_t *)(void *)TC2)
static const struct ti_args ti_cases[TI_CASES] = {
    {{TC0, TC1, TC2, NULL, TC4, TC5, TC6, TC7}, 8u, 2u, 7u, 31u, TOUT, 2356u, TSCR, 136u},
    {{NULL, TC1, TC2, TC3, TC4, TC5, TC6, TC7}, 8u, 2u, 7u, 31u, TOUT, 2356u, TSCR, 136u},
    {{TC0, TC1, TC2, TC3, TC4, TC5, TC6, NULL}, 8u, 2u, 7u, 31u, TOUT, 2356u, TSCR, 136u},
    {{TC0, TC1, TC2, TM3, TC4, TC5, TC6, TC7}, 8u, 2u, 7u, 31u, TOUT, 2356u, TSCR, 136u},
    {{TC0, TC1, TC2, TC3, TC4, TM5, TC6, TC7}, 8u, 2u, 7u, 31u, TOUT, 2356u, TSCR, 136u},
    {{TCOLS}, 8u, 2u, 7u, 31u, NULL, 2356u, TSCR, 136u},
    {{TCOLS}, 8u, 2u, 7u, 31u, TOUT, 2356u, NULL, 136u},
    {{TCOLS}, 8u, 2u, 7u, 31u, TOUT + 4, 2356u, TSCR, 136u},
    {{TCOLS}, 8u, 2u, 7u, 31u, TOUT, 2356u, TSCR + 4, 136u},
    {{TC0, TC1, TC2, TO3, TC4, TC5, TC6, TC7}, 8u, 2u, 7u, 31u, TOUT, 2356u, TSCR, 136u},
    {{TS0, TC1, TC2, TC3, TC4, TC5, TC6, TC7}, 8u, 2u, 7u, 31u, TOUT, 2356u, TSCR, 136u},
    {{TCOLS}, 8u, 2u, 7u, 31u, TOUT, 2356u, TOUT + 8, 136u},
    {{TCOLS}, 8u, 2u, 7u, 31u, TSCR, 2356u, TSCR + 8, 136u},
    {{TCOLS}, 8u, 2u, 7u, 31u, TOUT, 2356u, TSC2, 136u},
    {{TCOLS}, 0u, 2u, 7u, 31u, TOUT, 4u, TSCR, 64u},
    {{TCOLS}, 14337u, 2u, 7u, 31u, TOUT, 4157766u, TSCR, 129097u},
    {{TCOLS}, 8u, 5u, 7u, 31u, TOUT, 2404u, TSCR, 136u},
    {{TCOLS}, 8u, 0xFFFFFFFFu, 7u, 31u, TOUT, 2452u, TSCR, 136u},
    {{TCOLS}, 8u, 2u, 7u, 0u, TOUT, 2356u, TSCR, 136u},
    {{TCOLS}, 8u, 2u, 7u, 32u, TOUT, 2356u, TSCR, 136u},
    {{TCOLS}, 8u, 2u, 7u, 33u, TOUT, 2356u, TSCR, 136u},
    {{TCOLS}, 8u, 2u, 7u, 65535u, TOUT, 2356u, TSCR, 136u},
    {{TCOLS}, 8u, 2u, 7u, 65536u, TOUT, 2356u, TSCR, 136u},
    {{TCOLS}, 8u, 2u, 7u, 31u, TOUT, 2355u, TSCR, 136u},
    {{TCOLS}, 8u, 2u, 7u, 31u, TOUT, 2357u, TSCR, 136u},
    {{TCOLS}, 8u, 2u, 7u, 31u, TOUT, 2356u, TSCR, 135u},
    {{TCOLS}, 8u, 2u, 7u, 31u, TOUT, 2356u, TSCR, 137u},
    {{TCOLS}, 2u, 2u, 7u, 32u, TOUT, 616u, TSCR, 82u},
    {{TCOLS}, 2u, 2u, 7u, 64u, TOUT, 616u, TSCR, 82u},
    {{TCOLS}, 2u, 2u, 7u, 32768u, TOUT, 616u, TSCR, 82u},
    {{TCOLS}, 2u, 2u, 7u, 65535u, TOUT, 616u, TSCR, 82u},
};

static void group_arguments(void) {
    ti_load8();
    for (size_t k = ZERO; k < TI_CASES; k++) {
        const struct ti_args *a = ti_cases + k;
        ti_out_s = ti_sentinel_out;
        ti_scratch_s = ti_sentinel_scratch;
        const int rc = ti_call(a, NULL);
        CASE(k, rc == PL_INPROC_ARGUMENT);
        CASE(k, memcmp(ti_out, ti_sentinel_out.b, sizeof ti_out) == 0);
        CASE(k, memcmp(ti_scratch, ti_sentinel_scratch.b, sizeof ti_scratch) == 0);
    }
    puts("PASS arguments");
}

/* Group echo: after a successful call the last 64 bytes of the scratch hold the eight column
 * addresses (little-endian u64); after a refused call they are unchanged (the whole scratch and
 * out are unchanged). */
static void group_echo(void) {
    struct ti_args a;
    ti_load8();
    ti_out_s = ti_sentinel_out;
    ti_scratch_s = ti_sentinel_scratch;
    ti_set_args(&a, TI_N, 1u, 7u);
    CASE(100, ti_call(&a, NULL) == PL_INPROC_OK);
    const uint8_t *tail = ti_scratch + pl_inproc_scratch_len(TI_N) - 64u;
    for (size_t c = ZERO; c < 8u; c++) {
        CASE(c, pl_load_u64(tail + 8u * c) == (uint64_t)(uintptr_t)TI_COL(c));
    }
    ti_out_s = ti_sentinel_out;
    ti_scratch_s = ti_sentinel_scratch;
    a.models = 32u;
    CASE(101, ti_call(&a, NULL) == PL_INPROC_ARGUMENT);
    CASE(102, memcmp(ti_out, ti_sentinel_out.b, sizeof ti_out) == 0);
    CASE(103, memcmp(ti_scratch, ti_sentinel_scratch.b, sizeof ti_scratch) == 0);
    puts("PASS echo");
}

/* Group in-place: the columns are read in place: a value changed to NaN in the caller's array
 * reaches the next call, and row 0 becomes INVALID_INPUT in every model (the wired mask). */
static void group_in_place(void) {
    struct ti_args a;
    struct pl_contract_result r;
    ti_load2();
    ti_set_args(&a, 2u, 0u, PL_MASK_WIRED);
    CASE(100, ti_call(&a, NULL) == PL_INPROC_OK);
    CASE(101, ti_decode(ti_out, 0u, PL_MASK_WIRED, &r) == PL_PROTO_OK);
    CASE(102, (r.model + PL_MODEL_BSM)->status != PL_INVALID_INPUT);
    *(TI_COL(1u) + 0) = pl_bits_double(UINT64_C(0x7FF8000000000000));
    CASE(103, ti_call(&a, NULL) == PL_INPROC_OK);
    CASE(104, ti_decode(ti_out, 0u, PL_MASK_WIRED, &r) == PL_PROTO_OK);
    for (size_t m = ZERO; m < PL_MODELS; m++) {
        CASE(m, (r.model + m)->status == PL_INVALID_INPUT);
    }
    puts("PASS in-place");
}

/* Group masks (G4.4, G4.8, I13.3, ruling 46): masks 1, 8, 16 and 31 (all within PL_MASK_WIRED)
 * give the pl_batch_run bytes of that mask, with exactly NOT_REQUESTED unselected parts
 * (pl_response_decode under the mask checks them), for both rows. Two rows, threads 2. The
 * refusal of a mask outside PL_MASK_WIRED (32 and above) is in the arguments table. */
static void group_masks(void) {
    struct ti_args a;
    struct pl_contract_result r;
    const size_t at = 2u * PL_RESPONSE_RECORD_BYTES;
    ti_load2();
    ti_set_args(&a, 2u, 2u, 31u);
    for (size_t j = ZERO; j < 4u; j++) {
        const uint32_t models = *(ti_masks + j);
        struct pl_batch_stats ref_stats = {0};
        ti_out_s = ti_zero_out;
        CASE(j, ti_reference(2u, 2u, 2u, (uint16_t)models, &ref_stats) == PL_BATCH_OK);
        a.models = models;
        CASE(j, ti_call(&a, NULL) == PL_INPROC_OK);
        CASE(j, memcmp(ti_out, ti_ref, at) == 0);
        CASE(j, memcmp(ti_out + at, ti_ref + at, 4u) == 0);
        CASE(j, memcmp(ti_out + at + 4u, ti_ref + at + 4u, 8u) == 0);
        CASE(j, memcmp(ti_out + at + 20u, ti_ref + at + 20u, 8u) == 0);
        CASE(j, memcmp(ti_out + at + 36u, ti_ref + at + 36u, 8u) == 0);
        CASE(j, memcmp(ti_out + at + 52u, ti_ref + at + 52u, 8u) == 0);
        CASE(j, ti_decode(ti_out, 0u, (uint16_t)models, &r) == PL_PROTO_OK);
        CASE(j, ti_decode(ti_out, 1u, (uint16_t)models, &r) == PL_PROTO_OK);
    }
    puts("PASS masks");
}

/* Group reentrant: two calls with different scratch and output buffers, interleaved in one thread
 * (A, B, A), give the same bytes as separate calls: no state is shared between calls. */
static void group_reentrant(void) {
    struct ti_args a;
    struct ti_args b;
    const size_t at = TI_N * PL_RESPONSE_RECORD_BYTES;
    ti_load8();
    ti_set_args(&a, TI_N, 2u, 7u);
    ti_set_args(&b, TI_N, 1u, 7u);
    b.out = ti_out2;
    b.scratch = ti_scratch2;
    ti_out_s = ti_zero_out;
    CASE(100, ti_call(&a, NULL) == PL_INPROC_OK);
    ti_ref_s = ti_out_s;
    CASE(101, ti_call(&b, NULL) == PL_INPROC_OK);
    CASE(102, memcmp(ti_out2, ti_ref, at) == 0);
    ti_out_s = ti_zero_out;
    CASE(103, ti_call(&a, NULL) == PL_INPROC_OK);
    CASE(104, memcmp(ti_out, ti_ref, at) == 0);
    CASE(105, memcmp(ti_out + at, ti_ref + at, 4u) == 0);
    CASE(106, memcmp(ti_out + at + 4u, ti_ref + at + 4u, 8u) == 0);
    CASE(107, memcmp(ti_out + at + 20u, ti_ref + at + 20u, 8u) == 0);
    CASE(108, memcmp(ti_out + at + 36u, ti_ref + at + 36u, 8u) == 0);
    CASE(109, memcmp(ti_out + at + 52u, ti_ref + at + 52u, 8u) == 0);
    puts("PASS reentrant");
}

/* Group stats (G4.8, ruling 31), one function per threads value (the GCC analyzer budget counts a
 * function again at each call, so the four copies are written out): for every mask 1-31 within
 * PL_MASK_WIRED the calls and evals of pl_inproc_price_stats are 0 for an unselected model and
 * the wired value for a selected one; the wired values are above 0 for every wired model and equal
 * those of the serial run. A failed check ends the test with an exit status: 100 (serial call),
 * 101 (wired call), 102-105 (wired values), 110 (a mask call), 111-115 (calls of model 0-4) and
 * 116-120 (evals of model 0-4); the failed group is the first one without its PASS line. */
static void group_stats0(void) {
    struct pl_batch_stats serial = {0};
    struct pl_batch_stats wired = {0};
    struct ti_args a;
    ti_load2();
    ti_set_args(&a, 2u, 0u, PL_MASK_WIRED);
    if (ti_call(&a, &serial) != PL_INPROC_OK) {
        exit(100);
    }
    a.threads = 0u;
    a.out_len = pl_inproc_out_len(2u, 0u);
    if (ti_call(&a, &wired) != PL_INPROC_OK) {
        exit(101);
    }
    for (size_t m = ZERO; m < PL_MODELS; m++) {
        if (*(wired.calls + m) == 0u || *(wired.evals + m) == 0u) {
            exit(102);
        }
        if (*(wired.calls + m) != *(serial.calls + m)) {
            exit(103);
        }
        if (*(wired.evals + m) != *(serial.evals + m)) {
            exit(104);
        }
    }
    for (size_t k = ZERO; k < 31u; k++) {
        const uint32_t mask = (uint32_t)k + 1u;
        struct pl_batch_stats st = {0};
        a.models = mask;
        if (ti_call(&a, &st) != PL_INPROC_OK) {
            exit(110);
        }
        if (*(st.calls + 0) != (mask & 1u) * *(wired.calls + 0)) {
            exit(111);
        }
        if (*(st.calls + 1) != ((mask >> 1) & 1u) * *(wired.calls + 1)) {
            exit(112);
        }
        if (*(st.calls + 2) != ((mask >> 2) & 1u) * *(wired.calls + 2)) {
            exit(113);
        }
        if (*(st.calls + 3) != ((mask >> 3) & 1u) * *(wired.calls + 3)) {
            exit(114);
        }
        if (*(st.calls + 4) != ((mask >> 4) & 1u) * *(wired.calls + 4)) {
            exit(115);
        }
        if (*(st.evals + 0) != (mask & 1u) * *(wired.evals + 0)) {
            exit(116);
        }
        if (*(st.evals + 1) != ((mask >> 1) & 1u) * *(wired.evals + 1)) {
            exit(117);
        }
        if (*(st.evals + 2) != ((mask >> 2) & 1u) * *(wired.evals + 2)) {
            exit(118);
        }
        if (*(st.evals + 3) != ((mask >> 3) & 1u) * *(wired.evals + 3)) {
            exit(119);
        }
        if (*(st.evals + 4) != ((mask >> 4) & 1u) * *(wired.evals + 4)) {
            exit(120);
        }
    }
    puts("PASS stats threads=0");
}

static void group_stats1(void) {
    struct pl_batch_stats serial = {0};
    struct pl_batch_stats wired = {0};
    struct ti_args a;
    ti_load2();
    ti_set_args(&a, 2u, 0u, PL_MASK_WIRED);
    if (ti_call(&a, &serial) != PL_INPROC_OK) {
        exit(100);
    }
    a.threads = 1u;
    a.out_len = pl_inproc_out_len(2u, 1u);
    if (ti_call(&a, &wired) != PL_INPROC_OK) {
        exit(101);
    }
    for (size_t m = ZERO; m < PL_MODELS; m++) {
        if (*(wired.calls + m) == 0u || *(wired.evals + m) == 0u) {
            exit(102);
        }
        if (*(wired.calls + m) != *(serial.calls + m)) {
            exit(103);
        }
        if (*(wired.evals + m) != *(serial.evals + m)) {
            exit(104);
        }
    }
    for (size_t k = ZERO; k < 31u; k++) {
        const uint32_t mask = (uint32_t)k + 1u;
        struct pl_batch_stats st = {0};
        a.models = mask;
        if (ti_call(&a, &st) != PL_INPROC_OK) {
            exit(110);
        }
        if (*(st.calls + 0) != (mask & 1u) * *(wired.calls + 0)) {
            exit(111);
        }
        if (*(st.calls + 1) != ((mask >> 1) & 1u) * *(wired.calls + 1)) {
            exit(112);
        }
        if (*(st.calls + 2) != ((mask >> 2) & 1u) * *(wired.calls + 2)) {
            exit(113);
        }
        if (*(st.calls + 3) != ((mask >> 3) & 1u) * *(wired.calls + 3)) {
            exit(114);
        }
        if (*(st.calls + 4) != ((mask >> 4) & 1u) * *(wired.calls + 4)) {
            exit(115);
        }
        if (*(st.evals + 0) != (mask & 1u) * *(wired.evals + 0)) {
            exit(116);
        }
        if (*(st.evals + 1) != ((mask >> 1) & 1u) * *(wired.evals + 1)) {
            exit(117);
        }
        if (*(st.evals + 2) != ((mask >> 2) & 1u) * *(wired.evals + 2)) {
            exit(118);
        }
        if (*(st.evals + 3) != ((mask >> 3) & 1u) * *(wired.evals + 3)) {
            exit(119);
        }
        if (*(st.evals + 4) != ((mask >> 4) & 1u) * *(wired.evals + 4)) {
            exit(120);
        }
    }
    puts("PASS stats threads=1");
}

static void group_stats2(void) {
    struct pl_batch_stats serial = {0};
    struct pl_batch_stats wired = {0};
    struct ti_args a;
    ti_load2();
    ti_set_args(&a, 2u, 0u, PL_MASK_WIRED);
    if (ti_call(&a, &serial) != PL_INPROC_OK) {
        exit(100);
    }
    a.threads = 2u;
    a.out_len = pl_inproc_out_len(2u, 2u);
    if (ti_call(&a, &wired) != PL_INPROC_OK) {
        exit(101);
    }
    for (size_t m = ZERO; m < PL_MODELS; m++) {
        if (*(wired.calls + m) == 0u || *(wired.evals + m) == 0u) {
            exit(102);
        }
        if (*(wired.calls + m) != *(serial.calls + m)) {
            exit(103);
        }
        if (*(wired.evals + m) != *(serial.evals + m)) {
            exit(104);
        }
    }
    for (size_t k = ZERO; k < 31u; k++) {
        const uint32_t mask = (uint32_t)k + 1u;
        struct pl_batch_stats st = {0};
        a.models = mask;
        if (ti_call(&a, &st) != PL_INPROC_OK) {
            exit(110);
        }
        if (*(st.calls + 0) != (mask & 1u) * *(wired.calls + 0)) {
            exit(111);
        }
        if (*(st.calls + 1) != ((mask >> 1) & 1u) * *(wired.calls + 1)) {
            exit(112);
        }
        if (*(st.calls + 2) != ((mask >> 2) & 1u) * *(wired.calls + 2)) {
            exit(113);
        }
        if (*(st.calls + 3) != ((mask >> 3) & 1u) * *(wired.calls + 3)) {
            exit(114);
        }
        if (*(st.calls + 4) != ((mask >> 4) & 1u) * *(wired.calls + 4)) {
            exit(115);
        }
        if (*(st.evals + 0) != (mask & 1u) * *(wired.evals + 0)) {
            exit(116);
        }
        if (*(st.evals + 1) != ((mask >> 1) & 1u) * *(wired.evals + 1)) {
            exit(117);
        }
        if (*(st.evals + 2) != ((mask >> 2) & 1u) * *(wired.evals + 2)) {
            exit(118);
        }
        if (*(st.evals + 3) != ((mask >> 3) & 1u) * *(wired.evals + 3)) {
            exit(119);
        }
        if (*(st.evals + 4) != ((mask >> 4) & 1u) * *(wired.evals + 4)) {
            exit(120);
        }
    }
    puts("PASS stats threads=2");
}

static void group_stats4(void) {
    struct pl_batch_stats serial = {0};
    struct pl_batch_stats wired = {0};
    struct ti_args a;
    ti_load2();
    ti_set_args(&a, 2u, 0u, PL_MASK_WIRED);
    if (ti_call(&a, &serial) != PL_INPROC_OK) {
        exit(100);
    }
    a.threads = 4u;
    a.out_len = pl_inproc_out_len(2u, 4u);
    if (ti_call(&a, &wired) != PL_INPROC_OK) {
        exit(101);
    }
    for (size_t m = ZERO; m < PL_MODELS; m++) {
        if (*(wired.calls + m) == 0u || *(wired.evals + m) == 0u) {
            exit(102);
        }
        if (*(wired.calls + m) != *(serial.calls + m)) {
            exit(103);
        }
        if (*(wired.evals + m) != *(serial.evals + m)) {
            exit(104);
        }
    }
    for (size_t k = ZERO; k < 31u; k++) {
        const uint32_t mask = (uint32_t)k + 1u;
        struct pl_batch_stats st = {0};
        a.models = mask;
        if (ti_call(&a, &st) != PL_INPROC_OK) {
            exit(110);
        }
        if (*(st.calls + 0) != (mask & 1u) * *(wired.calls + 0)) {
            exit(111);
        }
        if (*(st.calls + 1) != ((mask >> 1) & 1u) * *(wired.calls + 1)) {
            exit(112);
        }
        if (*(st.calls + 2) != ((mask >> 2) & 1u) * *(wired.calls + 2)) {
            exit(113);
        }
        if (*(st.calls + 3) != ((mask >> 3) & 1u) * *(wired.calls + 3)) {
            exit(114);
        }
        if (*(st.calls + 4) != ((mask >> 4) & 1u) * *(wired.calls + 4)) {
            exit(115);
        }
        if (*(st.evals + 0) != (mask & 1u) * *(wired.evals + 0)) {
            exit(116);
        }
        if (*(st.evals + 1) != ((mask >> 1) & 1u) * *(wired.evals + 1)) {
            exit(117);
        }
        if (*(st.evals + 2) != ((mask >> 2) & 1u) * *(wired.evals + 2)) {
            exit(118);
        }
        if (*(st.evals + 3) != ((mask >> 3) & 1u) * *(wired.evals + 3)) {
            exit(119);
        }
        if (*(st.evals + 4) != ((mask >> 4) & 1u) * *(wired.evals + 4)) {
            exit(120);
        }
    }
    puts("PASS stats threads=4");
}

/* Group checks (T17-R1, test-strength evidence: the code was right): pl_inproc_check over forged
 * addresses, which it never dereferences, so that n = 14,336 and the wrap branches need no large
 * buffers. The columns lie at 0x10000000 + c x 0x40000, out at 0x20000000, scratch at
 * 0x30000000. A table of scalar rows (representable maxima, truncation probes, the accepted
 * bounds), then a loop over the eight column indices (NULL, misaligned, a clash with out, a clash
 * with scratch, a wrap of the column end), then the pointer rows. */
#define TK_BASE UINT64_C(0x10000000)
#define TK_STRIDE UINT64_C(0x40000)
#define TK_OUT UINT64_C(0x20000000)
#define TK_SCR UINT64_C(0x30000000)
#define TK_P(a) ((const uint8_t *)(uintptr_t)(a))
#define TK_D(a) ((const double *)(uintptr_t)(a))

struct ti_scalar {
    const char *why;
    size_t n;
    uint32_t threads, models;
    size_t out_len, scratch_len;
    int want;
};

static const struct ti_scalar ti_scalars[] = {
    {"accepted: the upper bound, n 14,336, 4 threads", 14336u, 4u, 31u, 4157508u, 129088u, 0},
    {"accepted: n 1, no threads, mask 1 (294 and 73 bytes)", 1u, 0u, 1u, 294u, 73u, 0},
    {"accepted: n 1, 4 threads, mask 16 (310 and 73 bytes)", 1u, 4u, 16u, 310u, 73u, 0},
    {"refused: the mask 0xFFFFFFFF (the u32 maximum)", 8u, 2u, 0xFFFFFFFFu, 2356u, 136u, 1},
    {"refused: the mask 65537 (a u16 truncation gives 1)", 8u, 2u, 65537u, 2356u, 136u, 1},
    {"refused: the mask 65567 (a u16 truncation gives 31)", 8u, 2u, 65567u, 2356u, 136u, 1},
    {"refused: n, out_len and scratch_len all SIZE_MAX", SIZE_MAX, 4u, 31u, SIZE_MAX, SIZE_MAX, 1},
    {"refused: n SIZE_MAX with the lengths of 8 rows", SIZE_MAX, 4u, 31u, 2356u, 136u, 1},
    {"refused: n 4,294,967,297 (a u32 truncation gives 1)", 4294967297u, 0u, 1u, 294u, 73u, 1},
    {"refused: out_len SIZE_MAX for 8 rows", 8u, 2u, 31u, SIZE_MAX, 136u, 1},
    {"refused: scratch_len SIZE_MAX for 8 rows", 8u, 2u, 31u, 2356u, SIZE_MAX, 1},
    {"refused: out_len SIZE_MAX for n 14,336", 14336u, 4u, 31u, SIZE_MAX, 129088u, 1},
    {"refused: scratch_len SIZE_MAX for n 14,336", 14336u, 4u, 31u, 4157508u, SIZE_MAX, 1},
    {"refused: threads 0xFFFFFFFF, its exact length", 8u, 0xFFFFFFFFu, 31u, 2452u, 136u, 1},
    {"refused: threads 65536 (a u16 truncation gives 0)", 8u, 65536u, 31u, 2324u, 136u, 1},
    {"refused: the valid call but for one byte of out_len", 8u, 2u, 31u, 2357u, 136u, 1},
};
#define TI_SCALARS (sizeof ti_scalars / sizeof *ti_scalars)

static void group_checks(void) {
    const double *col[8];
    const double *same[8];
    for (size_t i = ZERO; i < 8u; i++) {
        *(col + i) = TK_D(TK_BASE + i * TK_STRIDE);
        *(same + i) = TK_D(TK_BASE);
    }
    for (size_t k = ZERO; k < TI_SCALARS; k++) {
        const struct ti_scalar *s = ti_scalars + k;
        const int rc = pl_inproc_check(col, s->n, s->threads, s->models, TK_P(TK_OUT), s->out_len,
                                       TK_P(TK_SCR), s->scratch_len);
        CASE(k, rc == s->want);
    }
    /* two columns may overlap each other: all eight on one range are accepted */
    CASE(200, pl_inproc_check(same, 8u, 2u, 31u, TK_P(TK_OUT), 2356u, TK_P(TK_SCR), 136u) == 0);
    for (size_t c = ZERO; c < 8u; c++) {
        const double *keep = *(col + c);
        *(col + c) = NULL;
        CASE(c, pl_inproc_check(col, 8u, 2u, 31u, TK_P(TK_OUT), 2356u, TK_P(TK_SCR), 136u) == 1);
        *(col + c) = TK_D(TK_BASE + c * TK_STRIDE + 4u);
        CASE(c, pl_inproc_check(col, 8u, 2u, 31u, TK_P(TK_OUT), 2356u, TK_P(TK_SCR), 136u) == 1);
        *(col + c) = TK_D(TK_OUT + 16u);
        CASE(c, pl_inproc_check(col, 8u, 2u, 31u, TK_P(TK_OUT), 2356u, TK_P(TK_SCR), 136u) == 1);
        *(col + c) = TK_D(TK_SCR + 8u);
        CASE(c, pl_inproc_check(col, 8u, 2u, 31u, TK_P(TK_OUT), 2356u, TK_P(TK_SCR), 136u) == 1);
        *(col + c) = TK_D(UINTPTR_MAX - 7u);
        CASE(c, pl_inproc_check(col, 8u, 2u, 31u, TK_P(TK_OUT), 2356u, TK_P(TK_SCR), 136u) == 1);
        *(col + c) = keep;
    }
    CASE(201, pl_inproc_check(NULL, 8u, 2u, 31u, TK_P(TK_OUT), 2356u, TK_P(TK_SCR), 136u) == 1);
    CASE(202, pl_inproc_check(col, 8u, 2u, 31u, NULL, 2356u, TK_P(TK_SCR), 136u) == 1);
    CASE(203, pl_inproc_check(col, 8u, 2u, 31u, TK_P(TK_OUT), 2356u, NULL, 136u) == 1);
    CASE(204, pl_inproc_check(col, 8u, 2u, 31u, TK_P(TK_OUT), 2356u, TK_P(TK_OUT + 8u), 136u) == 1);
    CASE(205, pl_inproc_check(col, 8u, 2u, 31u, TK_P(UINTPTR_MAX - 1023u), 2356u, TK_P(TK_SCR),
                              136u) == 1);
    CASE(206, pl_inproc_check(col, 8u, 2u, 31u, TK_P(TK_OUT), 2356u, TK_P(UINTPTR_MAX - 127u),
                              136u) == 1);
    CASE(207, pl_inproc_check(col, 8u, 2u, 31u, TK_P(TK_OUT), 2356u, TK_P(TK_SCR), 136u) == 0);
    puts("PASS checks");
}

/* Group defect (T17-R1): a known run-defect row (RAISE_ROWS: a put with S 100, K 100, T 1, bid
 * 10, ask 11, r 709.77, q 709.79; the CRR entry raises in Python, so it is a run defect) with mask
 * 4 returns PL_INPROC_DEFECT, serially and through the pool; the echo (the last 64 bytes of the
 * scratch) and the trailer position of out stay unwritten. */
static void group_defect(void) {
    struct ti_args a;
    ti_load2();
    *(TI_COL(0u) + 0) = 0.0;
    *(TI_COL(1u) + 0) = 100.0;
    *(TI_COL(2u) + 0) = 100.0;
    *(TI_COL(3u) + 0) = 1.0;
    *(TI_COL(4u) + 0) = 10.0;
    *(TI_COL(5u) + 0) = 11.0;
    *(TI_COL(6u) + 0) = 709.77;
    *(TI_COL(7u) + 0) = 709.79;
    for (size_t j = ZERO; j < 2u; j++) {
        const uint32_t threads = j == 0u ? 0u : 2u;
        ti_out_s = ti_sentinel_out;
        ti_scratch_s = ti_sentinel_scratch;
        ti_set_args(&a, 2u, threads, 4u);
        CASE(j, ti_call(&a, NULL) == PL_INPROC_DEFECT);
        CASE(j, memcmp(ti_scratch + 9u * 2u, ti_sentinel_scratch.b + 9u * 2u, 64u) == 0);
        CASE(j, memcmp(ti_out + 2u * PL_RESPONSE_RECORD_BYTES,
                       ti_sentinel_out.b + 2u * PL_RESPONSE_RECORD_BYTES, 4u) == 0);
    }
    puts("PASS defect");
}

int main(void) {
    ti_init_sentinels();
    group_abi();
    group_same();
    group_arguments();
    group_checks();
    group_defect();
    group_echo();
    group_in_place();
    group_masks();
    group_reentrant();
    group_stats0();
    group_stats1();
    group_stats2();
    group_stats4();
    return 0;
}
