#include <limits.h>

static volatile unsigned int seeded_value = UINT_MAX;
static volatile unsigned int seeded_sink;

int main(void) {
    seeded_sink = seeded_value + 1U;
    return 0;
}
