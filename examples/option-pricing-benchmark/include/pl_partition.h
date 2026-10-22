#pragma once
#include <stddef.h>
#include <stdint.h>

/* The Amendment E partition (specs/project/batch.md "Partition"): SplitMix64, the Lemire bounded
 * draw with rejection, the Durstenfeld permutation of one request and one chunk per worker with
 * sorted request-local indices. It must equal benchlab.pools (SplitMix64, permutation,
 * chunk_bounds, request_chunks) exactly. No allocation: the caller owns every array.
 *
 * Scratch layout (controller ruling A41, for Tasks 14 and 16): a caller that carves the partition
 * scratch of m rows from one byte buffer places perm (4 m bytes) first, then indices (4 m bytes),
 * then mark (m bytes). Each uint32_t array then starts 4-byte aligned for every m. */

#define PL_PARTITION_SEED UINT64_C(0x5AFEC0DE20261007)
#define PL_REQUEST_LIMIT ((size_t)14336)
#define PL_MAX_WORKERS 4u
#define PL_MAX_CHUNKS 8u

/* A SplitMix64 generator. script is NULL in production. A test sets script and script_len to
 * feed fixed outputs through the same bounded-draw loop; calls counts every pl_random_next. */
struct pl_random {
    uint64_t state;
    const uint64_t *script;
    size_t script_len;
    size_t script_pos;
    size_t calls;
    int script_overrun;
};

/* One chunk: its request-local indices are indices[offset] ... indices[offset + count - 1]. */
struct pl_chunk {
    size_t offset;
    size_t count;
};

/* Sets the state, no script, zero counters. A NULL g is ignored. */
void pl_random_init(struct pl_random *g, uint64_t state);

/* The next SplitMix64 output (all arithmetic modulo 2^64), or the next scripted value. With an
 * exhausted script: sets script_overrun = 1 and returns 0. A NULL g gives 0. */
uint64_t pl_random_next(struct pl_random *g);

/* The exact 128-bit product a * b as *hi * 2^64 + *lo, from 32-bit halves (strict C17). With a
 * NULL output it writes nothing. */
void pl_mul_64(uint64_t a, uint64_t b, uint64_t *hi, uint64_t *lo);

/* (a + b) mod 2^64 without an unsigned wrap in C. */
uint64_t pl_add_64(uint64_t a, uint64_t b);

/* Lemire's unbiased draw in [0, t) with rejection, threshold (2^64 - t) mod t. Returns 0 and
 * writes *out. Returns -1 and writes nothing for t outside [1, 2^32], a NULL argument or a
 * script that runs out during the draw. */
int pl_random_bounded(struct pl_random *g, uint64_t t, uint64_t *out);

/* perm[0 .. m-1] = the Durstenfeld permutation of request r (state PL_PARTITION_SEED + r mod
 * 2^64). Returns 0, or -1 (nothing written) when m > cap, m > PL_REQUEST_LIMIT or perm is NULL
 * with m > 0. */
int pl_permutation(size_t m, uint64_t r, uint32_t *perm, size_t cap);

/* The w = min(workers, m) chunks of request r with m rows. Writes perm[0 .. m-1], mark[0 .. m-1],
 * indices[0 .. m-1], chunks[0 .. w-1] (chunks holds PL_MAX_WORKERS elements) and *chunk_count.
 * Chunk k holds the ascending request-local indices perm[k m / w .. (k + 1) m / w - 1]. Zero rows:
 * *chunk_count = 0. Returns 0, or -1 (nothing written) for workers outside [1, PL_MAX_WORKERS],
 * m > cap, m > PL_REQUEST_LIMIT or a NULL argument. */
int pl_request_chunks(size_t m, unsigned workers, uint64_t r, uint32_t *perm, uint8_t *mark,
                      uint32_t *indices, size_t cap, struct pl_chunk *chunks, size_t *chunk_count);

/* The number of requests of n records: ceil(n / PL_REQUEST_LIMIT). */
size_t pl_request_count(size_t n);

/* FNV-1a 64 of h over the four little-endian bytes of v (prime 0x100000001b3; the offset basis
 * 0xcbf29ce484222325 is the caller's start value). */
uint64_t pl_fnv1a64_u32(uint64_t h, uint32_t v);
