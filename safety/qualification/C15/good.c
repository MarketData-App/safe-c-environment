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
    if (n == 0)
        return 0;
    return 10 / n == 0 ? 0 : 1;
}
