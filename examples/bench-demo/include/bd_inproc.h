#ifndef BD_INPROC_H
#define BD_INPROC_H
#include <stddef.h>
#include <stdint.h>
/* The in-process entry of libbd_inproc.so for the framework's verified loader
 * (benchlab.native_inproc). The full contract is specs/project/bd_inproc.md. */
enum {
    BD_INPROC_ABI = 2,
    /* The entry writes these u64 values, little-endian, into the last
     * 8 * BD_INPROC_ECHO_WORDS bytes of scratch: n, length, threads,
     * request_index, selector_mask, capacity (the arguments it received). */
    BD_INPROC_ECHO_WORDS = 6,
    BD_INPROC_SCRATCH_MIN = 8 * BD_INPROC_ECHO_WORDS
};
/* Return values: 0 OK; 1 to 8 the bd_status of bd_digest_request
 * (BD_NULL_ARGUMENT, BD_STEPS_TOO_LARGE, BD_BUFFER_TOO_SMALL, BD_OVERLAP,
 * ...); and the refusals below. */
enum bd_inproc_rc {
    BD_INPROC_OK = 0,
    BD_INPROC_BAD_RECORDS = 20,
    BD_INPROC_BAD_LENGTH = 21,
    BD_INPROC_BAD_THREADS = 22,
    BD_INPROC_BAD_SELECTOR = 23,
    BD_INPROC_BAD_SCRATCH = 24
};
/* Returns BD_INPROC_ABI. */
uint32_t bd_inproc_abi_version(void);
/* Digests the n records of request (length bytes) into out (capacity bytes)
 * through bd_digest_request. threads must be 0 (no pool) and selector_mask
 * BD_SELECTOR_DIGEST (1); n must be in [1, 14,336] and length 12 * n. */
int bd_inproc_digest(const unsigned char *request, size_t length, size_t n, uint32_t threads,
                     uint32_t request_index, uint32_t selector_mask, unsigned char *out,
                     size_t capacity, unsigned char *scratch, size_t scratch_len);
#endif
