#include <stddef.h>

static volatile size_t seeded_count = 16U;

int main(void) {
    unsigned int values[32] = {0U};
    const size_t count = seeded_count;
#if defined(__clang__)
#pragma clang loop vectorize(enable)
#endif
    for (size_t index = 1U; index < count; ++index) {
        values[index] = values[index - 1U] * 3U + 1U;
    }
    return values[1] == 1U ? 0 : 1;
}
