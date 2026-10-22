#include "pl_evaluate.h"
#include "pl_inproc.h"
#include "pl_partition.h"
#include "pl_protocol.h"
#include <stddef.h>
#include <stdint.h>

/* The argument contract of the in-process entry (specs/project/inproc.md "Argument contract"):
 * a translation unit of its own, so that the analyzer sees the checks apart from the batch call.
 * No pointer is read or written: only addresses are compared. The checks are one function of
 * early returns with expression macros and no helper function, no loop and no accumulated
 * condition: the fixed GCC analyzer budget of one translation unit counts a helper again at each
 * call site, and a long chain of combined conditions exceeds the symbol depth. */

/* 1 when the address a is not a multiple of 8 (a NULL address is checked before). */
#define PL_MISALIGNED(a) (((a) & 7u) != 0u)

/* 1 when the address interval [alo, ahi) and the interval [blo, bhi) share an address. */
#define PL_OVERLAP(alo, ahi, blo, bhi) (!(((ahi) <= (blo)) || ((bhi) <= (alo))))

/* 1 when the column at address c (a range of cl bytes) overlaps out [o, oe) or scratch [s, se). */
#define PL_COLUMN_CLASH(c, cl, o, oe, s, se)                                                       \
    (((c) > UINTPTR_MAX - (cl)) || PL_OVERLAP((c), (c) + (cl), (o), (oe)) ||                       \
     PL_OVERLAP((c), (c) + (cl), (s), (se)))

uint32_t pl_inproc_abi_version(void) { return PL_INPROC_ABI; }

size_t pl_inproc_out_len(size_t n, uint32_t threads) {
    /* Both arguments saturate (no wrap of the u32 and u16 parameters of pl_response_payload). */
    const uint32_t count = n > UINT32_MAX ? UINT32_MAX : (uint32_t)n;
    const uint16_t workers = threads > UINT16_MAX ? UINT16_MAX : (uint16_t)threads;
    return pl_response_payload(count, workers);
}

size_t pl_inproc_scratch_len(size_t n) {
    /* Saturates like pl_inproc_out_len: 9 n + 64 would wrap above (SIZE_MAX - 64) / 9. */
    return n > (SIZE_MAX - 64u) / 9u ? SIZE_MAX : 9u * n + 64u;
}

/* The pointer, count, mask and length checks of pl_inproc_check (nothing here reads memory). */
static int pl_scalars_ok(size_t n, uint32_t threads, uint32_t models, size_t out_len,
                         size_t scratch_len) {
    if (n < 1u || n > PL_MAX_REQUEST_RECORDS || threads > PL_MAX_THREADS) {
        return 0;
    }
    if (models < 1u || models > PL_MASK_WIRED) {
        return 0;
    }
    return out_len == pl_inproc_out_len(n, threads) && scratch_len == pl_inproc_scratch_len(n);
}

int pl_inproc_check(const double *const *columns, size_t n, uint32_t threads, uint32_t models,
                    const uint8_t *out, size_t out_len, const uint8_t *scratch,
                    size_t scratch_len) {
    if (columns == NULL || out == NULL || scratch == NULL) {
        return PL_INPROC_ARGUMENT;
    }
    const double *p0 = *(columns + 0);
    const double *p1 = *(columns + 1);
    const double *p2 = *(columns + 2);
    const double *p3 = *(columns + 3);
    const double *p4 = *(columns + 4);
    const double *p5 = *(columns + 5);
    const double *p6 = *(columns + 6);
    const double *p7 = *(columns + 7);
    if (p0 == NULL || p1 == NULL || p2 == NULL || p3 == NULL) {
        return PL_INPROC_ARGUMENT;
    }
    if (p4 == NULL || p5 == NULL || p6 == NULL || p7 == NULL) {
        return PL_INPROC_ARGUMENT;
    }
    const uintptr_t c0 = (uintptr_t)p0;
    const uintptr_t c1 = (uintptr_t)p1;
    const uintptr_t c2 = (uintptr_t)p2;
    const uintptr_t c3 = (uintptr_t)p3;
    const uintptr_t c4 = (uintptr_t)p4;
    const uintptr_t c5 = (uintptr_t)p5;
    const uintptr_t c6 = (uintptr_t)p6;
    const uintptr_t c7 = (uintptr_t)p7;
    const uintptr_t o = (uintptr_t)out;
    const uintptr_t s = (uintptr_t)scratch;
    if (PL_MISALIGNED(c0) || PL_MISALIGNED(c1) || PL_MISALIGNED(c2) || PL_MISALIGNED(c3)) {
        return PL_INPROC_ARGUMENT;
    }
    if (PL_MISALIGNED(c4) || PL_MISALIGNED(c5) || PL_MISALIGNED(c6) || PL_MISALIGNED(c7)) {
        return PL_INPROC_ARGUMENT;
    }
    if (PL_MISALIGNED(o) || PL_MISALIGNED(s)) {
        return PL_INPROC_ARGUMENT;
    }
    if (!pl_scalars_ok(n, threads, models, out_len, scratch_len)) {
        return PL_INPROC_ARGUMENT;
    }
    /* n is at most 14,336 here, so the column length 8 n cannot overflow. */
    const uintptr_t cl = (uintptr_t)n * 8u;
    if (out_len > UINTPTR_MAX - o || scratch_len > UINTPTR_MAX - s) {
        return PL_INPROC_ARGUMENT;
    }
    if (PL_OVERLAP(o, o + out_len, s, s + scratch_len)) {
        return PL_INPROC_ARGUMENT;
    }
    const uintptr_t oe = o + out_len;
    const uintptr_t se = s + scratch_len;
    if (PL_COLUMN_CLASH(c0, cl, o, oe, s, se) || PL_COLUMN_CLASH(c1, cl, o, oe, s, se) ||
        PL_COLUMN_CLASH(c2, cl, o, oe, s, se) || PL_COLUMN_CLASH(c3, cl, o, oe, s, se)) {
        return PL_INPROC_ARGUMENT;
    }
    if (PL_COLUMN_CLASH(c4, cl, o, oe, s, se) || PL_COLUMN_CLASH(c5, cl, o, oe, s, se) ||
        PL_COLUMN_CLASH(c6, cl, o, oe, s, se) || PL_COLUMN_CLASH(c7, cl, o, oe, s, se)) {
        return PL_INPROC_ARGUMENT;
    }
    return PL_INPROC_OK;
}
