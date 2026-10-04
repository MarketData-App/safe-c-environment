#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define COPY(d, s) strcpy(d, s)
int main(int argc, char **argv) {
    (void)argc;
    (void)argv;
    char a[8];
    memcpy(a, "x", 2);
    return strcmp(a, "x") == 0 ? 0 : 1;
}
