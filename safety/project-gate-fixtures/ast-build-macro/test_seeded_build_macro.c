#include <stdlib.h>

/* Seeded defect for the ast gate, build-macros check: a C library macro that
 * expands to 0 under GCC and to 1 under Clang selects a code path in an
 * ordinary if. Conditional inclusion is the same in every build, so only the
 * check of macros with build-dependent definitions sees it. */
int main(void) {
    int status = EXIT_SUCCESS;
    if (__glibc_clang_prereq(3, 0)) {
        status = EXIT_SUCCESS;
    }
    return status;
}
