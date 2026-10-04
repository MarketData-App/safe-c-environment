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
    char p[10] = {0};
    size_t i = (size_t)argc * 10;
    fixture_write(p, i);
    return p[0];
}
