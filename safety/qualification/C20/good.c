#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(int argc, char **argv) {
    (void)argc;
    (void)argv;
    volatile int x = -argc;
    if (x < 0)
        return 0;
    size_t n = (size_t)x;
    return n == 0 ? 0 : 1;
}
