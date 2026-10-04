#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(int argc, char **argv) {
    (void)argc;
    (void)argv;
    char *p = malloc(10);
    if (!p)
        return 2;
    memset(p, 0, 10);
    size_t i = (size_t)argc * 10;
    int r = i < 10 ? p[i] : 0;
    free(p);
    return r;
}
