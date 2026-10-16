#ifndef BD_WIRE_H
#define BD_WIRE_H
#include "bd_digest.h"

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
/* The bench-demo native peers of the framework SCPL v2 transport: the frame
 * codec, the descriptor I/O helpers, the worker serve loop (routes stdio and
 * shm) and the kernel handshake program. The full contract is
 * specs/project/bd_wire.md. */
enum {
    BD_HEADER_BYTES = 28,
    BD_ERROR_PAYLOAD_BYTES = 4,
    BD_SHM_REQUEST_BYTES = 32,
    BD_SHM_RESPONSE_BYTES = 8,
    BD_PROTOCOL_VERSION = 2,
    BD_MAX_FRAME_BYTES = 4194304,
    BD_MAX_THREADS = 4,
    BD_SELECTOR_MAX = 31,
    /* The one selector value the bench-demo codec defines: the digest. */
    BD_SELECTOR_DIGEST = 1,
    /* Per codec region sizes (ruling FR6-R3 item 1): the largest request and
     * the largest response payload. */
    BD_SHM_INPUT_BYTES = BD_REQUEST_MAX_BYTES,
    BD_SHM_OUTPUT_BYTES = BD_OUTPUT_MAX_BYTES,
    BD_FD_MIN = 3,
    BD_FD_MAX = 1023,
    BD_LOOPS_MAX = 1000000
};
enum bd_frame_type {
    BD_FRAME_REQUEST = 1,
    BD_FRAME_RESPONSE = 2,
    BD_FRAME_ERROR = 3,
    BD_FRAME_SHUTDOWN = 4,
    BD_FRAME_SHM_REQUEST = 5,
    BD_FRAME_SHM_RESPONSE = 6
};
enum bd_proto {
    BD_PROTO_OK = 0,
    BD_PROTO_BAD_MAGIC = 1,
    BD_PROTO_BAD_VERSION = 2,
    BD_PROTO_BAD_TYPE = 3,
    BD_PROTO_RECORD_LIMIT = 4,
    BD_PROTO_FRAME_LIMIT = 5,
    BD_PROTO_LENGTH_MISMATCH = 6,
    BD_PROTO_TRUNCATED = 7,
    BD_PROTO_BAD_THREADS = 8,
    BD_PROTO_KERNEL_FAILURE = 9,
    BD_PROTO_IO_ERROR = 10,
    BD_PROTO_RESERVED_NONZERO = 11,
    BD_PROTO_BAD_SELECTOR = 12
};
/* Wire offsets: magic 0, version 4, type 6, request ID 8, record count 16,
 * threads 20, selector mask 22, payload length 24; all little-endian. */
struct bd_header {
    uint16_t version;
    uint16_t type;
    uint64_t request_id;
    uint32_t record_count;
    uint16_t threads;
    uint16_t selector_mask;
    uint32_t payload_length;
};
struct bd_shm_descriptor {
    uint64_t in_offset;
    uint64_t in_length;
    uint64_t out_offset;
    uint64_t out_capacity;
};
/* Little-endian load and store of count (1 to 8) bytes, byte by byte. */
uint64_t bd_load_le(const unsigned char *bytes, unsigned int count);
void bd_store_le(unsigned char *bytes, uint64_t value, unsigned int count);
/* Writes the 28 header bytes of h (magic SCPL). */
void bd_header_encode(const struct bd_header *h, unsigned char *out);
/* Decodes and checks the first 28 bytes of buf. The checks run in the order
 * magic, version, type, record count, threads, selector mask, frame size,
 * payload length, before any payload byte is read. *out holds the decoded
 * fields whenever len >= 28 (so an ERROR reply can repeat the request ID),
 * and is all zero for a shorter buffer. */
enum bd_proto bd_header_decode(const unsigned char *buf, size_t len, struct bd_header *out);
/* The 4-byte ERROR payload: the code as u32. */
void bd_error_encode(enum bd_proto code, unsigned char *out);
void bd_shm_descriptor_decode(const unsigned char *bytes, struct bd_shm_descriptor *d);
/* The Amendment F item 10 checks of a SHM_REQUEST descriptor against the
 * current region sizes, with overflow-checked additions. */
enum bd_proto bd_shm_descriptor_check(const struct bd_shm_descriptor *d, uint32_t count,
                                      uint64_t in_size, uint64_t out_size);
/* Returns a static name such as "BAD_MAGIC"; "UNKNOWN" for other values. */
const char *bd_proto_name(enum bd_proto code);
/* Answers one checked REQUEST header and its payload in memory: writes the
 * RESPONSE frame (header and 16n output bytes) into frame and its length
 * into *frame_length. BD_PROTO_KERNEL_FAILURE when bd_digest_request refuses
 * the records; *frame_length is 0 then. */
enum bd_proto bd_answer_request(const struct bd_header *h, const unsigned char *payload,
                                unsigned char *frame, size_t capacity, size_t *frame_length);

enum bd_io { BD_IO_OK = 0, BD_IO_EOF = 1, BD_IO_TRUNCATED = 2, BD_IO_ERROR = 3 };
/* Reads exactly len bytes; EINTR is retried. EOF before the first byte is
 * BD_IO_EOF, EOF after at least one byte is BD_IO_TRUNCATED. */
enum bd_io bd_read_exact(int fd, unsigned char *buf, size_t len);
enum bd_io bd_write_all(int fd, const unsigned char *buf, size_t len);
/* Positioned forms; an offset or an end above INT64_MAX is BD_IO_ERROR. A
 * short positioned read is BD_IO_TRUNCATED. */
enum bd_io bd_pread_exact(int fd, unsigned char *buf, size_t len, uint64_t offset);
enum bd_io bd_pwrite_all(int fd, const unsigned char *buf, size_t len, uint64_t offset);

enum bd_route { BD_ROUTE_STDIO = 0, BD_ROUTE_SHM = 1 };
struct bd_serve_options {
    int route;
    int shm_in_fd;
    int shm_out_fd;
};
/* Serves frames from in_fd to out_fd until SHUTDOWN or EOF. Returns 0
 * (SHUTDOWN, or EOF before a header), 1 (protocol error; an ERROR frame was
 * written before any payload or region byte was read), 2 (NULL argument or a
 * route outside the enum), 3 (kernel failure; ERROR KERNEL_FAILURE written),
 * 4 (I/O failure). *requests counts the answered requests. */
int bd_serve(int in_fd, int out_fd, const struct bd_serve_options *o, uint64_t *requests);
/* The SHM_REQUEST step of bd_serve: checks the descriptor against the
 * current sizes of both regions, copies the input range into input (a private
 * snapshot), runs bd_digest_request on the copy and writes the records at the
 * output offset. *written is the byte count written into the output region. */
enum bd_proto bd_shm_request(const struct bd_serve_options *o, const struct bd_header *h,
                             const unsigned char *payload, unsigned char *input,
                             unsigned char *output, size_t *written);
/* Program logic of bd-worker: --stdio | --shm-in FD --shm-out FD, and the
 * test option --files IN OUT. Exit codes as bd_serve, 2 for usage. */
int bd_worker_main(int argc, char **argv, FILE *err);
/* The run options of bd-kernel. */
struct bd_kernel_options {
    const char *input;
    const char *output;
    uint64_t records;
    uint64_t loops;
    int handshake;
};
/* Parses --input PATH --records N --loops L [--handshake] [--output PATH]
 * from argv[1, argc), in this fixed order. Returns 1, or 0 for a usage error
 * (another order or option, a missing or bad value); *o is all zero then.
 * argv must hold argc pointers. */
int bd_kernel_parse(int argc, char **argv, struct bd_kernel_options *o);
/* Program logic of bd-kernel: --self-check (bd_kernel_main), or
 * --input PATH --records N --loops L [--handshake] [--output PATH]. Exit 0
 * OK, 2 usage or input, 3 kernel failure, 4 I/O. The last line on out is the
 * PLK1 summary. With --handshake, the bytes B and E go to out and G and F
 * come from in. */
int bd_kernel_cli_main(int argc, char **argv, FILE *in, FILE *out, FILE *err);
#endif
