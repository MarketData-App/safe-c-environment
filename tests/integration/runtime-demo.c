/* Infrastructure packaging/health demonstration; no application service. */
#define _POSIX_C_SOURCE 200809L
#include "parser.h"
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

int main(int argc, char **argv) {
    const uint8_t input[] = {2, 4, 5};
    const struct timespec interval = {1, 0};
    const unsigned iterations = argc == 2 && strcmp(argv[1], "--hold") == 0 ? 8U : 1U;
    if (argc > 2 || (argc == 2 && strcmp(argv[1], "--hold") != 0))
        return 2;
    const char *const namespaces[] = {"pid", "net", "ipc", "mnt", "cgroup"};
    for (size_t i = 0; i < sizeof namespaces / sizeof namespaces[0]; ++i) {
        char path[64];
        char identity[128];
        int n = snprintf(path, sizeof path, "/proc/self/ns/%s", namespaces[i]);
        if (n < 0 || (size_t)n >= sizeof path)
            return 5;
        ssize_t length = readlink(path, identity, sizeof identity - 1U);
        if (length < 0 || (size_t)length >= sizeof identity)
            return 6;
        identity[(size_t)length] = '\0';
        if (printf("namespace %s=%s\n", namespaces[i], identity) < 0)
            return 7;
    }
    for (unsigned i = 0; i < iterations; ++i) {
        unsigned sum = 0;
        if (demo_parse(input, sizeof input, &sum) != 0 || sum != 9U)
            return 1;
        if (puts("runtime-demo healthy sum=9") < 0 || fflush(stdout) != 0)
            return 3;
        if (iterations > 1U && nanosleep(&interval, NULL) != 0)
            return 4;
    }
    return 0;
}
