#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static size_t fixture_partial_write(size_t n) { return n > 1 ? 1 : n; }
int main(int argc, char **argv) {
    (void)argc;
    (void)argv;
    size_t total = fixture_partial_write(4);
    if (total != 4) {
        fprintf(stderr, "CONTRACT short-io: expected 4 actual %zu\n", total);
        return 1;
    }
    return 0;
}
