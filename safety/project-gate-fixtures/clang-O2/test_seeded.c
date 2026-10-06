#include <stddef.h>
#include <string.h>

/* Only optimizing clang rewrites a memcmp whose result is compared with zero into
 * a call to bcmp. This redeclaration marks bcmp with a warning attribute, so only
 * the optimizing clang build reports that call (an error under -Werror). gcc never
 * emits bcmp calls, and the unoptimized builds keep the memcmp call. */
int bcmp(const void *first, const void *second, size_t count) __attribute__((warning("seeded")));

static volatile char seeded_source = 's';
static volatile size_t seeded_length = 8;

int main(void) {
    int (*volatile keep)(const void *, const void *, size_t) = bcmp;
    char left[8];
    char right[8];
    for (size_t index = 0; index < sizeof left; ++index) {
        left[index] = seeded_source;
        right[index] = seeded_source;
    }
    (void)keep;
    return memcmp(left, right, seeded_length) == 0 ? 0 : 1;
}
