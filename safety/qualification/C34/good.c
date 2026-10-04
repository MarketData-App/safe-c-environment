#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(int argc, char **argv) {
    (void)argc;
    (void)argv;
    unsigned inputs[] = {0, 1, 255, 256};
    for (size_t i = 0; i < 4; ++i) {
        unsigned input = inputs[i];
        if (input > UINT8_MAX)
            continue;
        uint8_t out = (uint8_t)input;
        if ((unsigned)out != input)
            return 1;
    }
    return 0;
}
