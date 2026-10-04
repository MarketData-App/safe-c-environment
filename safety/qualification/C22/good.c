#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int fixture_file_error(int argc);
int fixture_file_error(int argc) {

    (void)argc;

    FILE *p = fopen("/dev/null", "r");
    if (!p)
        return 2;
    (void)argc;
    return fclose(p) == 0 ? 0 : 1;
}
int main(int argc, char **argv) {
    (void)argv;
    return fixture_file_error(argc);
}
