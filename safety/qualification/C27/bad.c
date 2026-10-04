#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(int argc, char **argv) {
    (void)argc;
    (void)argv;
    int n = argc + 1;
    char a[n];
    memset(a, 0, (size_t)n);
    return a[0];
}
