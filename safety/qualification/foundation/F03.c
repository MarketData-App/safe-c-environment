#include "dependency-identity.h"
#include "sc-foundation.h"
#include <stdio.h>
int main(void) {
    if (sc_dependency_identity() != 0)
        return 3;
    GBytes *owner = NULL;
    const guint8 input[] = {0x12, 0x34};
    if (!sc_bytes_copy(input, 2, 2, &owner, NULL))
        return 2;
#if FOUNDATION_NEGATIVE
    GBytes *alias = owner;
#else
    GBytes *alias = g_bytes_ref(owner);
#endif
    g_bytes_unref(owner);
    guint16 value = 0;
    gboolean ok = sc_bytes_read_u16be(alias, 0, &value, NULL);
    g_bytes_unref(alias);
    return ok && value == 0x1234 ? 0 : 1;
}
