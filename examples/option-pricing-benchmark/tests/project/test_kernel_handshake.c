#define _GNU_SOURCE
#define PL_TEST_KERNEL
#include "pl_io.h"
#include "pl_test_batch.h"
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

/* Tests derived from specs/project/batch.md "pl-kernel command line": the handshake on fds 1 and
 * 0 (B out, G in before the loops; E out, F in after them). A child process (fork) moves two
 * pipes onto its fds 0 and 1 and runs pl_kernel_main with --handshake; the parent writes the
 * bytes the child reads, reads the bytes the child writes and checks the exit status. No
 * production hook. The descriptors live in file-scope variables. REQUIRE stays active under
 * NDEBUG. */

#define INPUT "pl-kernel-handshake-test-input.bin"

static char nm[] = "pl-kernel";
static char ka[] = "--case";
static char kb[] = "option-chain-greeks";
static char kc[] = "--input";
static char kd[] = INPUT;
static char ke[] = "--records";
static char kf[] = "8";
static char kg[] = "--echo";
static char kh[] = "--handshake";
static char *c_handshake[] = {nm, ka, kb, kc, kd, ke, kf, kg, kh, NULL};

static uint8_t zeros[8u * PL_REQUEST_RECORD_BYTES];
static int to_child[2], from_child[2], child_fds[2];
static FILE *child_out, *child_err;

/* The child: the pipes become fds 0 and 1, then pl_kernel_main runs with --handshake; its exit
 * status is the exit code. */
static void child(void) {
    *child_fds = dup2(*to_child, 0);
    *(child_fds + 1) = dup2(*(from_child + 1), 1);
    child_out = tmpfile();
    child_err = tmpfile();
    const int argc = (int)(sizeof c_handshake / sizeof *c_handshake) - 1;
    int code = 9;
    if (*child_fds == 0 && *(child_fds + 1) == 1 && child_out != NULL && child_err != NULL) {
        code = pl_kernel_main(argc, c_handshake, child_out, child_err);
    }
    exit(code);
}

/* One handshake: the parent sends the two bytes reply (G and F), reads the child's bytes (*got:
 * the pl_read_exact result for two bytes into bytes) and returns the child's exit code (-1 when
 * it did not exit normally). */
static int handshake(const char *reply, uint8_t *bytes, enum pl_io *got) {
    REQUIRE(pipe(to_child) == 0 && pipe(from_child) == 0);
    REQUIRE(fflush(stdout) == 0 && fflush(stderr) == 0);
    const pid_t pid = fork();
    REQUIRE(pid >= 0);
    if (pid == 0) {
        child();
    }
    const int closed_in = close(*to_child) == 0;
    const int closed_out = close(*(from_child + 1)) == 0;
    const ssize_t sent = write(*(to_child + 1), reply, 2u);
    const int closed_write = close(*(to_child + 1)) == 0;
    *got = pl_read_exact(*from_child, bytes, 2u);
    const int closed_read = close(*from_child) == 0;
    int status = 0;
    const pid_t waited = waitpid(pid, &status, 0);
    REQUIRE(closed_in && closed_out && closed_write && closed_read);
    REQUIRE(sent == 2 && waited == pid);
    return WIFEXITED(status) ? WEXITSTATUS(status) : -1;
}

int main(void) {
    FILE *f = fopen(INPUT, "wb");
    REQUIRE(f != NULL);
    const size_t written = fwrite(zeros, 1u, sizeof zeros, f);
    REQUIRE(fclose(f) == 0 && written == sizeof zeros);
    uint8_t bytes[2] = {0u, 0u};
    enum pl_io got = PL_IO_ERROR;
    REQUIRE(handshake("GF", bytes, &got) == 0);
    REQUIRE(got == PL_IO_OK && *bytes == 'B' && *(bytes + 1) == 'E');
    /* A wrong first reply: the child wrote B, then fails with the I/O exit code 4. */
    REQUIRE(handshake("XF", bytes, &got) == 4);
    REQUIRE(got == PL_IO_TRUNCATED && *bytes == 'B');
    REQUIRE(remove(INPUT) == 0);
    puts("PASS handshake");
    return 0;
}
