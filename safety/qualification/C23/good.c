#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(int argc, char **argv) {
    (void)argc;
    (void)argv;
    FILE *p = fopen("/dev/null", "r");
    if (!p)
        return 2;
    return fclose(p) == 0 ? 0 : 1;
}
