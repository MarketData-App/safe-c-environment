#include <stddef.h>

static volatile size_t seeded_index = 4U;
static volatile unsigned char seeded_sink;

int main(void) {
    const unsigned char bytes[4] = {1U, 2U, 3U, 4U};
    seeded_sink = *(bytes + seeded_index);
    return 0;
}
