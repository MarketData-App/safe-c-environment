#pragma once
#include "pl_protocol.h"
#include <stddef.h>
#include <stdint.h>

/* The serve loop of pl-worker (specs/project/serve.md): SCPL v2 frames over a descriptor pair,
 * route stdio (REQUEST) or shm (SHM_REQUEST with two regular-file regions, for example sealed
 * memfds). No allocation; the buffers are static, so one call at a time. */

enum pl_route { PL_ROUTE_STDIO = 0, PL_ROUTE_SHM = 1 };

/* shm_in_fd and shm_out_fd are the caller-owned region descriptors of the shm route (the worker
 * never closes them). calls and evals are nullable: PL_MODELS counters that each request adds
 * its batch totals to (the --counters test option). */
struct pl_serve_options {
    int route;
    int echo;
    int shm_in_fd;
    int shm_out_fd;
    uint64_t *calls;
    uint64_t *evals;
};

/* Serves frames from in_fd to out_fd until SHUTDOWN or EOF before a header. Returns 0 (that end),
 * 1 (protocol error; an ERROR frame was written before any payload or region byte was read), 3
 * (kernel failure; ERROR KERNEL_FAILURE written), 4 (I/O failure) or 2 (a NULL argument or an
 * unknown route). *requests counts the answered requests (0 for a NULL o). */
int pl_serve(int in_fd, int out_fd, const struct pl_serve_options *o, uint64_t *requests);

/* The batch of one request h (models, threads, record count, request ID) over count 64-byte wire
 * records in wire: count 290-byte records at out, then the trailer. *produced = bytes written
 * (count * 290 + 4 + 16 k). out holds PL_SHM_OUTPUT_BYTES bytes. PL_PROTO_KERNEL_FAILURE at a
 * batch failure, else PL_PROTO_OK. */
enum pl_proto_error pl_serve_compute(const struct pl_serve_options *o, const struct pl_header *h,
                                     const uint8_t *wire, uint8_t *out, size_t *produced);

/* The shm route of one SHM_REQUEST (src/pl_shm.c): descriptor check against the current region
 * sizes, snapshot of the input range into input (PL_SHM_INPUT_BYTES bytes), the batch into output
 * (PL_SHM_OUTPUT_BYTES bytes) and one positioned write at the output offset. payload holds the 32
 * descriptor bytes. *written = bytes written to the output region (0 on every failure, the
 * region untouched). */
enum pl_proto_error pl_shm_request(const struct pl_serve_options *o, const struct pl_header *h,
                                   const uint8_t *payload, uint8_t *input, uint8_t *output,
                                   size_t *written);
