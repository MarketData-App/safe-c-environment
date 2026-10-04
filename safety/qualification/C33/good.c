#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(int argc, char **argv) {
    (void)argc;
    (void)argv;
    size_t capacity = 4;
    for (size_t length = 0; length <= 5; ++length) {
        int allowed = length <= capacity;
        int expected = length < 5;
        if (allowed != expected)
            return 1;
    }
    return 0;
}
