#include "dependency-identity.h"
#include "sc-foundation.h"
#include <stdio.h>
typedef struct {
    guint *count;
    guint8 value;
} Witness;
static void release(gpointer data) {
    Witness *value = data;
    *value->count += 1;
    g_free(value);
}
static GBytes *make(guint *count) {
    Witness *value = g_new0(Witness, 1);
    value->count = count;
    return g_bytes_new_with_free_func(&value->value, 1, release, value);
}
static void early(guint *count) {
#if FOUNDATION_NEGATIVE
    GBytes *first = make(count);
    (void)first;
#else
    g_autoptr(GBytes) first = make(count);
#endif
    g_autoptr(GBytes) second = make(count);
    return;
}
int main(void) {
    if (sc_dependency_identity() != 0)
        return 3;
    guint count = 0;
    early(&count);
    if (count != 2) {
        (void)puts("F01_MISSING_CLEANUP_ACCOUNTING");
        (void)fflush(stdout);
        return 1;
    }
    (void)puts("F01_CLEANUP_ACCOUNTING_PASS");
    return 0;
}
