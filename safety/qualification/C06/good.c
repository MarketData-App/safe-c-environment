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
    char *p = malloc((size_t)argc + 10);
    if (!p)
        return 2;
    p[0] = 0;
    int r = p[0];
    fixture_release(p);
    return r;
}
