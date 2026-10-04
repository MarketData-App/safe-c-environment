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
    char *p = fixture_allocate();
    if (!p)
        return 2;
    int r = fixture_read(p);
    fixture_release(p);
    return r;
}
