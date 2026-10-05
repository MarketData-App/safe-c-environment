#include "sc-foundation.h"
#include <string.h>

struct ScText {
    GString *value;
    gsize maximum;
};
struct ScBytesList {
    GPtrArray *values;
    gsize maximum;
    gsize payload_maximum;
    gsize payload;
};
struct ScBytesMap {
    GHashTable *values;
    gsize maximum;
    gsize key_maximum;
    gsize payload_maximum;
    gsize payload;
};

GQuark sc_error_quark(void) { return g_quark_from_static_string("sc-foundation-error"); }

static gboolean ready(GError **error) { return error == NULL || *error == NULL; }

static gboolean fail(GError **error, ScError code, const gchar *message) {
    if (error != NULL && *error == NULL) {
        g_set_error_literal(error, SC_ERROR, (gint)code, message);
    }
    return FALSE;
}

gboolean sc_size_add(gsize a, gsize b, gsize *out) {
    gsize result = 0;
    if (out == NULL || !g_size_checked_add(&result, a, b)) {
        return FALSE;
    }
    *out = result;
    return TRUE;
}

gboolean sc_size_mul(gsize a, gsize b, gsize *out) {
    gsize result = 0;
    if (out == NULL || !g_size_checked_mul(&result, a, b)) {
        return FALSE;
    }
    *out = result;
    return TRUE;
}

gboolean sc_length(gssize length, gsize maximum, gsize *out) {
    if (out == NULL || length < 0) {
        return FALSE;
    }
    gsize result = (gsize)length;
    if (result > maximum) {
        return FALSE;
    }
    *out = result;
    return TRUE;
}

gboolean sc_range(gsize offset, gsize length, gsize total) {
    return offset <= total && length <= total - offset;
}

static gboolean text_span(const gchar *data, gsize length, GError **error) {
    if (length > (gsize)G_MAXSSIZE || (data == NULL && length != 0)) {
        return fail(error, SC_ERROR_INVALID, "invalid text span");
    }
    if (length != 0 &&
        (memchr(data, 0, length) != NULL || !g_utf8_validate(data, (gssize)length, NULL))) {
        return fail(error, SC_ERROR_ENCODING, "text requires complete UTF-8 without NUL");
    }
    return TRUE;
}

ScText *sc_text_new(gsize maximum, GError **error) {
    if (!ready(error)) {
        return NULL;
    }
    if (maximum > SC_MAX_TEXT) {
        (void)fail(error, SC_ERROR_LIMIT, "unsupported text maximum");
        return NULL;
    }
    ScText *text = g_new0(ScText, 1);
    text->maximum = maximum;
    text->value = g_string_sized_new(MIN(maximum, (gsize)32));
    return text;
}

void sc_text_free(ScText *text) {
    if (text != NULL) {
        g_string_free(text->value, TRUE);
        g_free(text);
    }
}

gboolean sc_text_append(ScText *text, const gchar *data, gsize length, GError **error) {
    if (!ready(error)) {
        return FALSE;
    }
    if (text == NULL) {
        return fail(error, SC_ERROR_INVALID, "missing text");
    }
    gsize next = 0;
    gsize terminated = 0;
    if (!sc_size_add(text->value->len, length, &next) || !sc_size_add(next, 1, &terminated) ||
        next > text->maximum) {
        return fail(error, SC_ERROR_LIMIT, "text limit");
    }
    if (!text_span(data, length, error)) {
        return FALSE;
    }
    if (length != 0) {
        g_string_append_len(text->value, data, (gssize)length);
    }
    return TRUE;
}

gsize sc_text_length(const ScText *text) { return text == NULL ? 0 : text->value->len; }

gboolean sc_text_snapshot(const ScText *text, gchar **out, gsize *length, GError **error) {
    if (out != NULL) {
        *out = NULL;
    }
    if (length != NULL) {
        *length = 0;
    }
    if (!ready(error)) {
        return FALSE;
    }
    if (text == NULL || out == NULL || length == NULL) {
        return fail(error, SC_ERROR_INVALID, "missing snapshot output");
    }
    *out = g_strdup(text->value->str);
    *length = text->value->len;
    return TRUE;
}

gboolean sc_bytes_copy(const void *data, gsize length, gsize maximum, GBytes **out,
                       GError **error) {
    if (out != NULL) {
        *out = NULL;
    }
    if (!ready(error)) {
        return FALSE;
    }
    if (out == NULL || (data == NULL && length != 0)) {
        return fail(error, SC_ERROR_INVALID, "invalid byte span or output");
    }
    if (maximum > SC_MAX_BYTES || length > maximum) {
        return fail(error, SC_ERROR_LIMIT, "byte limit");
    }
    *out = g_bytes_new(data, length);
    return TRUE;
}

gboolean sc_bytes_slice(GBytes *bytes, gsize offset, gsize length, GBytes **out, GError **error) {
    if (out != NULL) {
        *out = NULL;
    }
    if (!ready(error)) {
        return FALSE;
    }
    if (bytes == NULL || out == NULL) {
        return fail(error, SC_ERROR_INVALID, "missing byte owner or output");
    }
    if (!sc_range(offset, length, g_bytes_get_size(bytes))) {
        return fail(error, SC_ERROR_RANGE, "byte region");
    }
    *out = length == 0 ? g_bytes_new(NULL, 0) : g_bytes_new_from_bytes(bytes, offset, length);
    return TRUE;
}

gboolean sc_bytes_read_u16be(GBytes *bytes, gsize offset, guint16 *out, GError **error) {
    if (out != NULL) {
        *out = 0;
    }
    if (!ready(error)) {
        return FALSE;
    }
    if (bytes == NULL || out == NULL) {
        return fail(error, SC_ERROR_INVALID, "missing read owner or output");
    }
    if (!sc_range(offset, 2, g_bytes_get_size(bytes))) {
        return fail(error, SC_ERROR_RANGE, "two-byte region");
    }
    const guint8 *region = g_bytes_get_region(bytes, 1, offset, 2);
    if (region == NULL) {
        return fail(error, SC_ERROR_RANGE, "two-byte region unavailable");
    }
    *out = (guint16)(((guint16)region[0] << 8) | (guint16)region[1]);
    return TRUE;
}

static void release_bytes(gpointer value) { g_bytes_unref(value); }

ScBytesList *sc_list_new(gsize maximum, gsize payload_maximum, GError **error) {
    if (!ready(error)) {
        return NULL;
    }
    if (maximum > SC_MAX_ENTRIES || payload_maximum > SC_MAX_BYTES) {
        (void)fail(error, SC_ERROR_LIMIT, "unsupported list maximum");
        return NULL;
    }
    ScBytesList *list = g_new0(ScBytesList, 1);
    list->values = g_ptr_array_new_with_free_func(release_bytes);
    list->maximum = maximum;
    list->payload_maximum = payload_maximum;
    return list;
}

void sc_list_free(ScBytesList *list) {
    if (list != NULL) {
        g_ptr_array_unref(list->values);
        g_free(list);
    }
}

gsize sc_list_length(const ScBytesList *list) {
    return list == NULL ? 0 : (gsize)list->values->len;
}

gboolean sc_list_append(ScBytesList *list, GBytes *value, GError **error) {
    if (!ready(error)) {
        return FALSE;
    }
    if (list == NULL || value == NULL) {
        return fail(error, SC_ERROR_INVALID, "missing list or value");
    }
    gsize next = 0;
    if ((gsize)list->values->len >= list->maximum ||
        !sc_size_add(list->payload, g_bytes_get_size(value), &next) ||
        next > list->payload_maximum) {
        return fail(error, SC_ERROR_LIMIT, "list limit");
    }
    g_ptr_array_add(list->values, g_bytes_ref(value));
    list->payload = next;
    return TRUE;
}

gboolean sc_list_get_ref(const ScBytesList *list, gsize index, GBytes **out, GError **error) {
    if (out != NULL) {
        *out = NULL;
    }
    if (!ready(error)) {
        return FALSE;
    }
    if (list == NULL || out == NULL) {
        return fail(error, SC_ERROR_INVALID, "missing list or output");
    }
    if (index >= (gsize)list->values->len) {
        return fail(error, SC_ERROR_RANGE, "list index");
    }
    *out = g_bytes_ref(g_ptr_array_index(list->values, (guint)index));
    return TRUE;
}

gboolean sc_list_replace(ScBytesList *list, gsize index, GBytes *value, GError **error) {
    if (!ready(error)) {
        return FALSE;
    }
    if (list == NULL || value == NULL) {
        return fail(error, SC_ERROR_INVALID, "missing list or value");
    }
    if (index >= (gsize)list->values->len) {
        return fail(error, SC_ERROR_RANGE, "list index");
    }
    GBytes *old = g_ptr_array_index(list->values, (guint)index);
    gsize next = 0;
    if (!sc_size_add(list->payload - g_bytes_get_size(old), g_bytes_get_size(value), &next) ||
        next > list->payload_maximum) {
        return fail(error, SC_ERROR_LIMIT, "list limit");
    }
    GBytes *retained = g_bytes_ref(value);
    g_ptr_array_index(list->values, (guint)index) = retained;
    g_bytes_unref(old);
    list->payload = next;
    return TRUE;
}

gboolean sc_list_remove(ScBytesList *list, gsize index, GError **error) {
    if (!ready(error)) {
        return FALSE;
    }
    if (list == NULL) {
        return fail(error, SC_ERROR_INVALID, "missing list");
    }
    if (index >= (gsize)list->values->len) {
        return fail(error, SC_ERROR_RANGE, "list index");
    }
    GBytes *value = g_ptr_array_index(list->values, (guint)index);
    list->payload -= g_bytes_get_size(value);
    (void)g_ptr_array_remove_index(list->values, (guint)index);
    return TRUE;
}

ScBytesMap *sc_map_new(gsize maximum, gsize key_maximum, gsize payload_maximum, GError **error) {
    if (!ready(error)) {
        return NULL;
    }
    if (maximum > SC_MAX_ENTRIES || key_maximum > SC_MAX_KEY || payload_maximum > SC_MAX_BYTES) {
        (void)fail(error, SC_ERROR_LIMIT, "unsupported map maximum");
        return NULL;
    }
    ScBytesMap *map = g_new0(ScBytesMap, 1);
    map->values = g_hash_table_new_full(g_str_hash, g_str_equal, g_free, release_bytes);
    map->maximum = maximum;
    map->key_maximum = key_maximum;
    map->payload_maximum = payload_maximum;
    return map;
}

void sc_map_free(ScBytesMap *map) {
    if (map != NULL) {
        g_hash_table_unref(map->values);
        g_free(map);
    }
}

gsize sc_map_length(const ScBytesMap *map) {
    return map == NULL ? 0 : (gsize)g_hash_table_size(map->values);
}

static gboolean map_key(const ScBytesMap *map, const gchar *key, gsize length, GError **error) {
    if (map == NULL || key == NULL || length == 0) {
        return fail(error, SC_ERROR_INVALID, "missing map or nonempty key");
    }
    if (length > map->key_maximum) {
        return fail(error, SC_ERROR_LIMIT, "map key limit");
    }
    return text_span(key, length, error);
}

gboolean sc_map_put(ScBytesMap *map, const gchar *key, gsize length, GBytes *value,
                    GError **error) {
    if (!ready(error)) {
        return FALSE;
    }
    if (!map_key(map, key, length, error)) {
        return FALSE;
    }
    if (value == NULL) {
        return fail(error, SC_ERROR_INVALID, "missing map value");
    }
    gchar query[65] = {0};
    memcpy(query, key, length);
    GBytes *old = g_hash_table_lookup(map->values, query);
    gsize base = map->payload;
    if (old == NULL && sc_map_length(map) >= map->maximum) {
        return fail(error, SC_ERROR_LIMIT, "map count limit");
    }
    if (old != NULL) {
        base -= length + g_bytes_get_size(old);
    }
    gsize entry = 0;
    gsize next = 0;
    if (!sc_size_add(length, g_bytes_get_size(value), &entry) || !sc_size_add(base, entry, &next) ||
        next > map->payload_maximum) {
        return fail(error, SC_ERROR_LIMIT, "map payload limit");
    }
    gchar *owned_key = g_strndup(key, length);
    GBytes *retained = g_bytes_ref(value);
    g_hash_table_replace(map->values, owned_key, retained);
    map->payload = next;
    return TRUE;
}

gboolean sc_map_get_ref(const ScBytesMap *map, const gchar *key, gsize length, GBytes **out,
                        GError **error) {
    if (out != NULL) {
        *out = NULL;
    }
    if (!ready(error)) {
        return FALSE;
    }
    if (out == NULL) {
        return fail(error, SC_ERROR_INVALID, "missing map output");
    }
    if (!map_key(map, key, length, error)) {
        return FALSE;
    }
    gchar query[65] = {0};
    memcpy(query, key, length);
    GBytes *value = g_hash_table_lookup(map->values, query);
    if (value == NULL) {
        return fail(error, SC_ERROR_NOT_FOUND, "map key absent");
    }
    *out = g_bytes_ref(value);
    return TRUE;
}

gboolean sc_map_remove(ScBytesMap *map, const gchar *key, gsize length, GError **error) {
    if (!ready(error)) {
        return FALSE;
    }
    if (!map_key(map, key, length, error)) {
        return FALSE;
    }
    gchar query[65] = {0};
    memcpy(query, key, length);
    GBytes *value = g_hash_table_lookup(map->values, query);
    if (value == NULL) {
        return fail(error, SC_ERROR_NOT_FOUND, "map key absent");
    }
    map->payload -= length + g_bytes_get_size(value);
    (void)g_hash_table_remove(map->values, query);
    return TRUE;
}
