#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(int argc, char **argv) {
    (void)argc;
    (void)argv;
    volatile int x = INT_MAX;
    if (argc > 0 && x > INT_MAX - argc)
        return 0;
    return x + argc == 0 ? 0 : 1;
}
