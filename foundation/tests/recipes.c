#include "dependency-identity.h"
#include "sc-foundation.h"
#include <stdio.h>

/* This compiled usage recipe has no raw-memory or mutable-GLib exemption. */
int main(void) {
    static const guint8 wire[] = {0x12, 0x34};
    g_autoptr(GError) error = NULL;
    g_autoptr(ScText) text = sc_text_new(16, &error);
    g_autoptr(GBytes) bytes = NULL;
    g_autoptr(GBytes) region = NULL;
    g_autoptr(GBytes) retrieved = NULL;
    g_autoptr(ScBytesList) list = sc_list_new(2, 4, &error);
    g_autoptr(ScBytesMap) map = sc_map_new(2, 8, 16, &error);
    g_autofree gchar *snapshot = NULL;
    gsize length = 0;
    guint16 value = 0;
    if (sc_dependency_identity() != 0 || text == NULL || list == NULL || map == NULL ||
        !sc_text_append(text, "hello", 5, &error) ||
        !sc_text_snapshot(text, &snapshot, &length, &error) || length != 5 ||
        g_strcmp0(snapshot, "hello") != 0 ||
        !sc_bytes_copy(wire, sizeof wire, SC_MAX_BYTES, &bytes, &error) ||
        !sc_bytes_slice(bytes, 0, 2, &region, &error) || !sc_list_append(list, region, &error) ||
        !sc_list_replace(list, 0, region, &error) || !sc_map_put(map, "value", 5, region, &error)) {
        return 1;
    }
    g_clear_pointer(&bytes, g_bytes_unref);
    g_clear_pointer(&region, g_bytes_unref);
    if (!sc_list_get_ref(list, 0, &retrieved, &error) ||
        !sc_bytes_read_u16be(retrieved, 0, &value, &error) || value != 0x1234) {
        return 1;
    }
    g_clear_pointer(&retrieved, g_bytes_unref);
    if (!sc_list_remove(list, 0, &error) || !sc_map_get_ref(map, "value", 5, &retrieved, &error) ||
        !sc_bytes_read_u16be(retrieved, 0, &value, &error) || value != 0x1234 ||
        !sc_map_remove(map, "value", 5, &error)) {
        return 1;
    }
    puts("FOUNDATION_RECIPE_PASS");
    return 0;
}
