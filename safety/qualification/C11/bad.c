#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(int argc, char **argv) {
    (void)argc;
    (void)argv;
    int *p = malloc(sizeof *p);
    if (!p)
        return 2;
    int r = (*p == argc) ? 0 : 1;
    free(p);
    return r;
}
