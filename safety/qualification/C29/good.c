#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
__attribute__((warn_unused_result)) static int fixture_error(void) { return 0; }
int main(int argc, char **argv) {
    (void)argc;
    (void)argv;
    int r = fixture_error();
    return r;
}
