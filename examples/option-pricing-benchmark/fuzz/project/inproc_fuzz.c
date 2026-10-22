#include "pl_evaluate.h"
#include "pl_inproc.h"
#include "pl_protocol.h"
#include "pl_types.h"
#include <stddef.h>
#include <stdint.h>
#include <string.h>

/* libFuzzer target `inproc` (specs/project/inproc.md "Fuzz target"). The input builds n of 0-4
 * rows, the threads value (a byte), the models value (a u16, so 0, 32 and above occur), the
 * request index and the placement of the eight columns, out and scratch in one static 8-byte
 * aligned arena: the offsets come from the input, a skew byte per pointer and a length within one
 * of the exact value, so that misaligned, overlapping and short buffers occur.
 * Layout: byte 0 n (modulo 5), 1 threads, 2-3 models, 4 request index, 5 out length delta, 6
 * scratch length delta, 7-8 reserved, 9-18 ten slot bytes (pointer i is at arena offset 64 x
 * slot, pointers 0-7 the columns, 8 out, 9 scratch), 19-28 ten skew bytes (bit 0 set: the
 * pointer is 4 bytes further, so not a multiple of 8), 29-284 the row values (column c at
 * 29 + 32 c: four doubles, written at the column pointer). An input shorter than 285 bytes is
 * ignored. A length delta byte d changes the exact length by -1 for d modulo 4 = 1, +1 for 3 and
 * not at all otherwise. A refused call leaves the arena unchanged; a valid call's records decode
 * under the call's mask. The code has no loop and no helper that is called many times (macros),
 * because of the fixed GCC analyzer budget of one translation unit; the AST policy refuses array
 * subscripts and memcpy/memset, so an element is read as *(p + i) and the arena is cleared and
 * copied by struct assignment. */

#define FZ_ARENA 18432u
#define FZ_HEAD 29u
#define FZ_VALUES 256u

/* The largest pointer offset 64 x 255 + 4 plus the largest buffer (4 x 290 + 4 + 16 x 4 + 1
 * bytes) stays inside the arena, so that no pointer range leaves it. */
_Static_assert(64u * 255u + 4u + 4u * 290u + 4u + 16u * 4u + 1u <= FZ_ARENA,
               "the arena holds every placement");

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size);

struct fz_bytes {
    _Alignas(8) uint8_t b[FZ_ARENA];
};

static struct fz_bytes fz_arena;
static struct fz_bytes fz_before;
static const struct fz_bytes fz_zero = {{0}};

/* The pointer i of the input in the arena. */
#define FZ_PTR(i)                                                                                  \
    (fz_arena.b + 64u * (size_t)(*(data + 9u + (i))) + 4u * (size_t)(*(data + 19u + (i)) & 1u))

/* The pointer i as a column address. */
#define FZ_COLUMN(i) ((const double *)(const void *)FZ_PTR(i))

/* The four row values of column c at its pointer (little-endian words, so any alignment). */
#define FZ_FILL(c)                                                                                 \
    do {                                                                                           \
        uint8_t *dst_ = FZ_PTR(c);                                                                 \
        const uint8_t *src_ = data + FZ_HEAD + 32u * (c);                                          \
        pl_store_u64(dst_, pl_load_u64(src_));                                                     \
        pl_store_u64(dst_ + 8, pl_load_u64(src_ + 8));                                             \
        pl_store_u64(dst_ + 16, pl_load_u64(src_ + 16));                                           \
        pl_store_u64(dst_ + 24, pl_load_u64(src_ + 24));                                           \
    } while (0)

/* v changed by the delta byte d: d modulo 4 = 1 minus one, 3 plus one, else no change. v >= 4. */
#define FZ_LENGTH(v, d) ((v) + (size_t)(((d) & 3u) == 3u) - (size_t)(((d) & 3u) == 1u))

/* 1 when the first min(n, 4) records of a valid call decode under the call's mask. */
static int fz_records_ok(const uint8_t *out, size_t n, uint16_t models) {
    struct pl_contract_result r;
    const uint8_t *rec1 = out + PL_RESPONSE_RECORD_BYTES;
    const uint8_t *rec2 = rec1 + PL_RESPONSE_RECORD_BYTES;
    const uint8_t *rec3 = rec2 + PL_RESPONSE_RECORD_BYTES;
    if (n > 0u && pl_response_decode(out, models, &r) != PL_PROTO_OK) {
        return 0;
    }
    if (n > 1u && pl_response_decode(rec1, models, &r) != PL_PROTO_OK) {
        return 0;
    }
    if (n > 2u && pl_response_decode(rec2, models, &r) != PL_PROTO_OK) {
        return 0;
    }
    return n < 4u || pl_response_decode(rec3, models, &r) == PL_PROTO_OK;
}

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    if (size < FZ_HEAD + FZ_VALUES) {
        return 0;
    }
    const size_t n = (size_t)(*(data + 0)) % 5u;
    const uint8_t threads = *(data + 1);
    const uint16_t models = (uint16_t)((unsigned)(*(data + 2)) | ((unsigned)(*(data + 3)) << 8));
    const uint32_t index = *(data + 4);
    fz_arena = fz_zero;
    FZ_FILL(0u);
    FZ_FILL(1u);
    FZ_FILL(2u);
    FZ_FILL(3u);
    FZ_FILL(4u);
    FZ_FILL(5u);
    FZ_FILL(6u);
    FZ_FILL(7u);
    fz_before = fz_arena;
    uint8_t *out = FZ_PTR(8u);
    uint8_t *scratch = FZ_PTR(9u);
    const size_t out_len = FZ_LENGTH(pl_inproc_out_len(n, threads), *(data + 5));
    const size_t scratch_len = FZ_LENGTH(pl_inproc_scratch_len(n), *(data + 6));
    const double *c0 = FZ_COLUMN(0u);
    const double *c1 = FZ_COLUMN(1u);
    const double *c2 = FZ_COLUMN(2u);
    const double *c3 = FZ_COLUMN(3u);
    const double *c4 = FZ_COLUMN(4u);
    const double *c5 = FZ_COLUMN(5u);
    const double *c6 = FZ_COLUMN(6u);
    const double *c7 = FZ_COLUMN(7u);
    const int rc = pl_inproc_price(c0, c1, c2, c3, c4, c5, c6, c7, n, threads, index, models, out,
                                   out_len, scratch, scratch_len);
    if (rc == PL_INPROC_ARGUMENT && memcmp(fz_arena.b, fz_before.b, FZ_ARENA) != 0) {
        __builtin_trap(); /* a refused call wrote */
    }
    const int must_refuse = n == 0u || threads > 4u || models == 0u || models > PL_MASK_WIRED;
    if (rc != PL_INPROC_ARGUMENT && must_refuse) {
        __builtin_trap(); /* a call outside the contract was not refused */
    }
    if (rc == PL_INPROC_OK && !fz_records_ok(out, n, models)) {
        __builtin_trap(); /* a record that its mask rejects */
    }
    return 0;
}
