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
    size_t bytes = n * ((size_t)argc + 1);
    char *p = malloc(bytes);
    free(p);
    return 0;
}
