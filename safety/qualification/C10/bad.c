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
    for (int i = 0; i < 10; ++i)
        fixture_leak((size_t)argc + 16);
    return 0;
}
