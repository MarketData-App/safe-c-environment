#include <stddef.h>

static volatile size_t seeded_index = 1U;
static volatile int seeded_sink;

int main(void) {
    unsigned char bytes[2];
    bytes[0] = 1U;
    if (bytes[seeded_index] == 7U) {
        seeded_sink = 1;
    }
    return 0;
}
