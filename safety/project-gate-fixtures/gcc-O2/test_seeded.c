#include <stddef.h>

static volatile int seeded_sink;

static int seeded_at(const int *values, size_t index) { return values[index]; }

int main(void) {
    const int values[2] = {1, 2};
    seeded_sink = seeded_at(values, 2U);
    return 0;
}
