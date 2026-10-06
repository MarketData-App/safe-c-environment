#include <stdio.h>

/* The optimizing clang build rewrites the printf call below into a call to puts.
 * The clang-only redeclaration marks puts with a warning attribute, so only the
 * optimizing clang build reports that call (an error under -Werror). */
#if defined(__clang__)
int puts(const char *text) __attribute__((warning("seeded: puts must not be called")));
#endif

int main(void) {
    int (*volatile keep)(const char *) = puts;
    (void)keep;
    printf("seeded\n");
    return 0;
}
