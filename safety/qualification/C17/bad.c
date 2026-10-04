#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(int argc, char **argv) {
    (void)argc;
    (void)argv;
    char *p = malloc(16);
    if (!p)
        return 2;
    int *q = (int *)(p + argc);
    *q = 0;
    int r = *q;
    free(p);
    return r;
}
