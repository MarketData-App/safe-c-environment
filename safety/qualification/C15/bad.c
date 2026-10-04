#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(int argc, char **argv) {
    (void)argc;
    (void)argv;
    volatile int n = argc - 1;
    int r = 10 / n;
    return r == 0 ? 0 : 1;
}
