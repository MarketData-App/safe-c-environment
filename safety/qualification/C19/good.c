#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(int argc, char **argv) {
    (void)argc;
    (void)argv;
    volatile unsigned x = 256U * (unsigned)argc;
    if (x > UINT8_MAX)
        return 0;
    uint8_t y = (uint8_t)x;
    return (unsigned)y == x ? 0 : 1;
}
