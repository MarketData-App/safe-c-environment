#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(int argc, char **argv) {
    (void)argc;
    (void)argv;
    volatile size_t n = SIZE_MAX;
    size_t count = (size_t)argc + 1;
    if (n > SIZE_MAX / count)
        return 0;
    char *p = malloc(n * count);
    if (!p)
        return 2;
    free(p);
    return 0;
}
