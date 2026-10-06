#include <limits.h>
/* The project check runs the ubsan build before the asan build (whose profile
 * also enables -fsanitize=undefined), so this defect first fails ubsan. */

static volatile int seeded_value = INT_MAX;
static volatile int seeded_sink;

int main(void) {
    seeded_sink = seeded_value + 1;
    return 0;
}
