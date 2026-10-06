#include <limits.h>

/* The asan profile also enables -fsanitize=undefined and runs first; the defect
 * is left out of that build so that the run reaches the ubsan gate. */
#if defined(__has_feature)
#if __has_feature(address_sanitizer)
#define SEEDED_ASAN_BUILD 1
#endif
#endif

#if !defined(SEEDED_ASAN_BUILD)
static volatile int seeded_value = INT_MAX;
static volatile int seeded_sink;
#endif

int main(void) {
#if !defined(SEEDED_ASAN_BUILD)
    seeded_sink = seeded_value + 1;
#endif
    return 0;
}
