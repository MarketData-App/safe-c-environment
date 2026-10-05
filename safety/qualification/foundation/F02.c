#include "dependency-identity.h"
#include "sc-foundation.h"
#include <stdio.h>
static ScText *transfer(void) {
    g_autoptr(ScText) owner = sc_text_new(8, NULL);
    if (owner == NULL || !sc_text_append(owner, "ok", 2, NULL))
        return NULL;
#if FOUNDATION_NEGATIVE
    return owner;
#else
    return g_steal_pointer(&owner);
#endif
}
int main(void) {
    if (sc_dependency_identity() != 0)
        return 3;
    ScText *owner = transfer();
    if (owner == NULL)
        return 2;
    gsize length = sc_text_length(owner);
    sc_text_free(owner);
    return length == 2 ? 0 : 1;
}
