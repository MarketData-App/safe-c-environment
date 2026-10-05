#include "dependency-identity.h"
#include <glib.h>

int main(void) {
    if (sc_dependency_identity() != 0) {
        return 1;
    }
#if FOUNDATION_NEGATIVE
    g_critical("F14 unexpected diagnostic qualification");
#endif
    return 0;
}
