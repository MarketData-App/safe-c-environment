#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(int argc, char **argv) {
    (void)argc;
    (void)argv;
    char a[8] = {0};
    int n = argc + 1;
    if (n > 8)
        return 0;
    return a[0];
}
