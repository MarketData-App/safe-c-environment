#include "support.h"
#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(int argc, char **argv) {
    (void)argc;
    (void)argv;
    char *p = malloc(32);
    if (!p)
        return 2;
    memset(p, 0, 32);
    char *next = fixture_fail_realloc(p, 64);
    if (!next) {
        int r = p[0];
        free(p);
        return r;
    }
    p = next;
    free(p);
    return 0;
}
