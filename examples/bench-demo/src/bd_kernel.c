#include "bd_digest.h"

#include <stddef.h>
#include <stdio.h>
#include <string.h>

/* Program logic of bd-kernel (specs/project/bd_digest.md): the self-check of
 * the native C kernel. This file is a separate translation unit so that each
 * analyzer run stays within its fixed budget. No allocation, no global
 * mutable state. */

/* The 19 generated vectors of tests/project/test_bd_digest.c (benchdemo.vectors),
 * in the same order: seed, steps, FNV-1a checksum, final state. The project
 * unit test test_demo.py checks that these rows equal the generated rows. */
static const struct bd_check_vector bd_builtin_vectors[] = {
    {0x0000000000000000U, 0U, 0xcbf29ce484222325U, 0x9e3779b97f4a7c15U},
    {0x0000000000000000U, 1U, 0x9e44ffe67972dc6dU, 0xdc1b77ae0bf34dadU},
    {0x0000000000000000U, 2U, 0xd1beeb107f8ec798U, 0x64f0eeb9026e6076U},
    {0x0000000000000000U, 1000000U, 0xcc7c912f60df17abU, 0x3e746a84b0b86f03U},
    {0x9e3779b97f4a7c15U, 0U, 0xcbf29ce484222325U, 0x9e3779b97f4a7c15U},
    {0x9e3779b97f4a7c15U, 1U, 0x9e44ffe67972dc6dU, 0xdc1b77ae0bf34dadU},
    {0x0000000000000001U, 0U, 0xcbf29ce484222325U, 0x0000000000000001U},
    {0x0000000000000001U, 1U, 0x37e2fbafd55e2536U, 0x0000000040822041U},
    {0x0000000000000001U, 2U, 0xea443c57c075a843U, 0x100041060c011441U},
    {0x0000000000000001U, 3U, 0x6f423fe00d993980U, 0x9b1e842f6e862629U},
    {0x0000000000000002U, 64U, 0x298a07e8400f6f8cU, 0xaa83d55440673596U},
    {0x000000000135288fU, 64U, 0xc370523f1bfa3fe7U, 0x106c4bf21edae149U},
    {0x0123456789abcdefU, 4096U, 0xcb34fef79bb6833aU, 0x32744d2ca7ad39ddU},
    {0x8000000000000000U, 13U, 0x46ebb398af5cf94dU, 0x4d70a82913179aa9U},
    {0x7fffffffffffffffU, 7U, 0x4ccea6f64fe03e7dU, 0xe9443e112b5303f1U},
    {0xffffffffffffffffU, 0U, 0xcbf29ce484222325U, 0xffffffffffffffffU},
    {0xffffffffffffffffU, 1U, 0x6a1c4a26425994ddU, 0x000000003f801fc0U},
    {0xffffffffffffffffU, 999999U, 0xa9a7f838dff92ec8U, 0xe9c0d662fb69e645U},
    {0xdeadbeefcafef00dU, 1000000U, 0x1d7b49e45b2eebfeU, 0x36c853cbd9325819U},
};

enum { BD_BUILTIN_COUNT = sizeof bd_builtin_vectors / sizeof *bd_builtin_vectors };

enum bd_status bd_check_vectors(const struct bd_check_vector *vectors, size_t count,
                                size_t *mismatches) {
    if (mismatches != NULL) {
        *mismatches = 0U;
    }
    if (vectors == NULL || mismatches == NULL) {
        return BD_NULL_ARGUMENT;
    }
    if (count == 0U) {
        return BD_EMPTY_REQUEST;
    }
    /* Checked before any vector is read: count can exceed the array. */
    if (count > (size_t)BD_CHECK_VECTORS_MAX) {
        return BD_TOO_MANY_RECORDS;
    }
    unsigned char request[BD_CHECK_VECTORS_MAX * BD_RECORD_IN_BYTES] = {0};
    unsigned char output[BD_CHECK_VECTORS_MAX * BD_RECORD_OUT_BYTES] = {0};
    for (size_t index = 0U; index < count; ++index) {
        const struct bd_check_vector *vector = vectors + index;
        unsigned char *record = request + index * (size_t)BD_RECORD_IN_BYTES;
        /* record points into a local array, so the call cannot fail. */
        (void)bd_encode_record(record, vector->seed, vector->steps);
    }
    size_t written = 0U;
    /* count <= BD_CHECK_VECTORS_MAX, so the length cannot wrap. The steps
     * limit is enforced here, by the route entry. */
    const size_t length = count * (size_t)BD_RECORD_IN_BYTES;
    const enum bd_status st = bd_digest_request(request, length, output, sizeof output, &written);
    if (st != BD_OK) {
        return st;
    }
    size_t differ = 0U;
    for (size_t index = 0U; index < count; ++index) {
        const struct bd_check_vector *vector = vectors + index;
        const unsigned char *got = output + index * (size_t)BD_RECORD_OUT_BYTES;
        struct bd_result result = {.checksum = 0U, .state = 0U};
        /* got points into a local array, so the call cannot fail. */
        (void)bd_decode_output(got, &result);
        const int same = (result.checksum == vector->checksum) & (result.state == vector->state);
        differ += (size_t)(same == 0);
    }
    *mismatches = differ;
    return BD_OK;
}

int bd_kernel_report(const struct bd_check_vector *vectors, size_t count, FILE *out, FILE *err) {
    size_t bad = 0U;
    const enum bd_status status = bd_check_vectors(vectors, count, &bad);
    if (status != BD_OK) {
        (void)fprintf(err, "bd-kernel: %s\n", bd_status_name(status));
        return 1;
    }
    if (bad != 0U) {
        (void)fprintf(err, "bd-kernel: self-check FAIL %zu of %zu differ\n", bad, count);
        return 1;
    }
    /* Both steps always run. */
    const int text = fprintf(out, "bd-kernel: self-check PASS %zu vectors\n", count);
    const int flush = fflush(out);
    return (text < 0) | (flush == EOF);
}

int bd_kernel_main(int argc, char **argv, FILE *out, FILE *err) {
    const char *flag = argc == 2 ? *(argv + 1) : NULL;
    if (flag == NULL || strcmp(flag, "--self-check") != 0) {
        (void)fputs("usage: bd-kernel --self-check\n", err);
        return 2;
    }
    return bd_kernel_report(bd_builtin_vectors, BD_BUILTIN_COUNT, out, err);
}
