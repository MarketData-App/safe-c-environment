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
    int x = 0;
    memcpy(p + argc, &x, sizeof x);
    int r = 1;
    memcpy(&r, p + argc, sizeof r);
    free(p);
    return r;
}
