#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(int argc, char **argv) {
    (void)argc;
    (void)argv;
    unsigned input = 256U;
    uint8_t out = (uint8_t)input;
    if ((unsigned)out != input) {
        fprintf(stderr, "PROPERTY round-trip: 256 becomes %u\n", (unsigned)out);
        return 1;
    }
    return 0;
}
