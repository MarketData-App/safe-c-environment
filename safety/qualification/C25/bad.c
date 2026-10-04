#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(int argc, char **argv) {
    (void)argc;
    (void)argv;
    int a[4] = {0};
    size_t n = sizeof(sizeof(a));
    return n == sizeof(size_t) ? 0 : 1;
}
