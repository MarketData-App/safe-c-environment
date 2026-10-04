#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(int argc, char **argv) {
    (void)argc;
    (void)argv;
    volatile unsigned x = 1;
    unsigned n = (unsigned)argc + 31U;
    if (n >= 32U)
        return 0;
    return (x << n) == 0 ? 0 : 1;
}
