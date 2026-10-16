#define _GNU_SOURCE

#include "bd_wire.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* bd-worker --files tests derived from specs/project/bd_wire.md: the stdio
 * route, a missing IN file, an unopenable OUT file, the shm route with two
 * temporary regions, and a protocol error. The usage forms are in
 * tests/project/test_bd_worker_usage.c. The frame files are written in the
 * current directory and removed at the end. REQUIRE stays active under
 * NDEBUG and has no side effects of its own. */

#define REQUIRE_FAIL(c) (fprintf(stderr, "%s:%d: REQUIRE %s\n", __FILE__, __LINE__, #c), exit(1))
#define REQUIRE(c) ((c) ? (void)0 : REQUIRE_FAIL(c))

enum { TEXT_SIZE = 160 };

static const char in_path[] = "bd-worker-test-in.bin";
static const char out_path[] = "bd-worker-test-out.bin";
/* An empty payload: fwrite gets a valid pointer and length 0. */
static const unsigned char none[1] = {0};

/* A comparison result (0 or 1) as unsigned int. */
#define AS_BIT(condition) ((unsigned int)(condition))

/* Runs bd_worker_main; 1 when its result is want and its err text is text. */
static unsigned int expect(int argc, char **argv, int want, const char *text) {
    FILE *err = tmpfile();
    REQUIRE(err != NULL);
    const int rc = bd_worker_main(argc, argv, err);
    char got[TEXT_SIZE] = {0};
    const int start = fseek(err, 0L, SEEK_SET);
    const size_t count = fread(got, 1U, sizeof got - 1U, err);
    const int closed = fclose(err);
    unsigned int ok = AS_BIT(rc == want) & AS_BIT(start == 0) & AS_BIT(closed == 0);
    return ok & AS_BIT(count == strlen(text)) & AS_BIT(strcmp(got, text) == 0);
}

static void write_frames(const struct bd_header *first, const struct bd_header *second,
                         const unsigned char *payload, size_t length) {
    unsigned char head[BD_HEADER_BYTES] = {0};
    unsigned char tail[BD_HEADER_BYTES] = {0};
    bd_header_encode(first, head);
    bd_header_encode(second, tail);
    FILE *file = fopen(in_path, "wb");
    REQUIRE(file != NULL);
    const size_t put_head = fwrite(head, 1U, sizeof head, file);
    const size_t put_payload = fwrite(payload, 1U, length, file);
    const size_t put_tail = fwrite(tail, 1U, sizeof tail, file);
    const int closed = fclose(file);
    REQUIRE(put_head == sizeof head && put_payload == length && put_tail == sizeof tail);
    REQUIRE(closed == 0);
}

static long out_size(void) {
    FILE *file = fopen(out_path, "rb");
    REQUIRE(file != NULL && fseek(file, 0L, SEEK_END) == 0);
    const long size = ftell(file);
    REQUIRE(fclose(file) == 0);
    return size;
}

static void files(void) {
    char prog[] = "bd-worker";
    char stdio_flag[] = "--stdio";
    char files_flag[] = "--files";
    char in_name[] = "bd-worker-test-in.bin";
    char out_name[] = "bd-worker-test-out.bin";
    char missing[] = "bd-worker-test-missing.bin";
    char no_dir[] = "bd-worker-test-no-dir/out.bin";
    const struct bd_header ping = {BD_PROTOCOL_VERSION, BD_FRAME_REQUEST, 1U, 0U, 0U, 1U, 0U};
    const struct bd_header stop = {BD_PROTOCOL_VERSION, BD_FRAME_SHUTDOWN, 0U, 0U, 0U, 0U, 0U};
    write_frames(&ping, &stop, none, 0U);
    char *stdio_files[] = {prog, stdio_flag, files_flag, in_name, out_name, NULL};
    REQUIRE(expect(5, stdio_files, 0, "BDW1 exit=0 requests=1\n"));
    REQUIRE(out_size() == 28L);
    char *missing_in[] = {prog, stdio_flag, files_flag, missing, out_name, NULL};
    REQUIRE(expect(5, missing_in, 4, "BDW1 exit=4 requests=0\n"));
    char *bad_out[] = {prog, stdio_flag, files_flag, in_name, no_dir, NULL};
    REQUIRE(expect(5, bad_out, 4, "BDW1 exit=4 requests=0\n"));
    /* The shm route with two temporary regions: a ping. */
    FILE *in_region = tmpfile();
    FILE *out_region = tmpfile();
    REQUIRE(in_region != NULL && out_region != NULL);
    char in_fd[8] = {0};
    char out_fd[8] = {0};
    REQUIRE(snprintf(in_fd, sizeof in_fd, "%d", fileno(in_region)) > 0);
    REQUIRE(snprintf(out_fd, sizeof out_fd, "%d", fileno(out_region)) > 0);
    char shm_in[] = "--shm-in";
    char shm_out[] = "--shm-out";
    const struct bd_header shm_ping = {2U, BD_FRAME_SHM_REQUEST, 2U, 0U, 0U, 1U, 32U};
    const unsigned char zero_descriptor[BD_SHM_REQUEST_BYTES] = {0};
    write_frames(&shm_ping, &stop, zero_descriptor, sizeof zero_descriptor);
    char *shm_files[] = {prog, shm_in, in_fd, shm_out, out_fd, files_flag, in_name, out_name, NULL};
    REQUIRE(expect(8, shm_files, 0, "BDW1 exit=0 requests=1\n"));
    REQUIRE(out_size() == 36L);
    /* A protocol error ends the run with 1. */
    const struct bd_header bad = {BD_PROTOCOL_VERSION, BD_FRAME_REQUEST, 3U, 0U, 0U, 2U, 0U};
    write_frames(&bad, &stop, none, 0U);
    REQUIRE(expect(5, stdio_files, 1, "BDW1 exit=1 requests=0\n"));
    REQUIRE(out_size() == 32L);
    REQUIRE(fclose(in_region) == 0 && fclose(out_region) == 0);
    REQUIRE(remove(in_path) == 0 && remove(out_path) == 0);
}

int main(void) {
    files();
    return 0;
}
