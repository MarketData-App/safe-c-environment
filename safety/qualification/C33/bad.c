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
    size_t length = 4;
    int allowed = length < capacity;
    if (!allowed) {
        fprintf(stderr, "PROPERTY exact-bound: length=4 capacity=4 at %s:%d main\n", __FILE__,
                __LINE__);
        return 1;
    }
    return 0;
}
