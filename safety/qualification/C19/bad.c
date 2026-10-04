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
    uint8_t y = x;
    return y == 0 ? 0 : 1;
}
