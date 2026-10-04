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
    int total = 0;
    for (int i = 0; i < 10; ++i) {
        char *p = malloc((size_t)argc + 16);
        if (!p)
            return 2;
        memset(p, 0, (size_t)argc + 16);
        int r = p[0];
        free(p);
        total += r;
    }
    return total;
}
