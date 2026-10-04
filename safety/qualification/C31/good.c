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
    size_t total = 0;
    while (total < 4) {
        size_t n = fixture_partial_write(4 - total);
        if (n == 0)
            return 2;
        total += n;
    }
    return total == 4 ? 0 : 1;
}
