#include "bd_inproc.h"

#include "bd_digest.h"

/* The in-process entry (specs/project/bd_inproc.md). No allocation, no
 * global mutable state, no I/O. */

uint32_t bd_inproc_abi_version(void) { return (uint32_t)BD_INPROC_ABI; }

static void store_word(unsigned char *bytes, uint64_t value) {
    for (unsigned int index = 0U; index < 8U; ++index) {
        *(bytes + index) = (unsigned char)((value >> (8U * index)) & UINT64_C(0xff));
    }
}

int bd_inproc_digest(const unsigned char *request, size_t length, size_t n, uint32_t threads,
                     uint32_t request_index, uint32_t selector_mask, unsigned char *out,
                     size_t capacity, unsigned char *scratch, size_t scratch_len) {
    if (scratch == NULL || scratch_len < (size_t)BD_INPROC_SCRATCH_MIN) {
        return BD_INPROC_BAD_SCRATCH;
    }
    /* The echo: the arguments as received, before any other check. */
    unsigned char *echo = scratch + (scratch_len - (size_t)BD_INPROC_SCRATCH_MIN);
    store_word(echo, (uint64_t)n);
    store_word(echo + 8, (uint64_t)length);
    store_word(echo + 16, threads);
    store_word(echo + 24, request_index);
    store_word(echo + 32, selector_mask);
    store_word(echo + 40, (uint64_t)capacity);
    if (n == 0U || n > (size_t)BD_RECORDS_MAX) {
        return BD_INPROC_BAD_RECORDS;
    }
    /* n <= BD_RECORDS_MAX, so the product cannot wrap. */
    if (length != n * (size_t)BD_RECORD_IN_BYTES) {
        return BD_INPROC_BAD_LENGTH;
    }
    if (threads != 0U) {
        return BD_INPROC_BAD_THREADS;
    }
    if (selector_mask != 1U) {
        return BD_INPROC_BAD_SELECTOR;
    }
    size_t written = 0U;
    return (int)bd_digest_request(request, length, out, capacity, &written);
}
