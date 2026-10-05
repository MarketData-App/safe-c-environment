#ifndef SC_FOUNDATION_H
#define SC_FOUNDATION_H

#include <glib.h>

G_BEGIN_DECLS

typedef struct ScText ScText;
typedef struct ScBytesList ScBytesList;
typedef struct ScBytesMap ScBytesMap;
typedef enum {
    SC_ERROR_INVALID,
    SC_ERROR_RANGE,
    SC_ERROR_LIMIT,
    SC_ERROR_ENCODING,
    SC_ERROR_NOT_FOUND
} ScError;

#define SC_MAX_TEXT ((gsize)4096)
#define SC_MAX_BYTES ((gsize)8192)
#define SC_MAX_ENTRIES ((gsize)64)
#define SC_MAX_KEY ((gsize)64)
#define SC_ERROR (sc_error_quark())

GQuark sc_error_quark(void);
G_GNUC_WARN_UNUSED_RESULT gboolean sc_size_add(gsize a, gsize b, gsize *out);
G_GNUC_WARN_UNUSED_RESULT gboolean sc_size_mul(gsize a, gsize b, gsize *out);
G_GNUC_WARN_UNUSED_RESULT gboolean sc_length(gssize length, gsize maximum, gsize *out);
G_GNUC_WARN_UNUSED_RESULT gboolean sc_range(gsize offset, gsize length, gsize total);

/* Owners are initialized, thread-confined, and freed with the declared cleanup.
 * Recoverable errors preserve state and reset pointer/length outputs. See specs.
 * Raw spans require actual valid initialized storage; checks do not prove that. */
G_GNUC_WARN_UNUSED_RESULT ScText *sc_text_new(gsize maximum, GError **error);
void sc_text_free(ScText *text);
G_GNUC_WARN_UNUSED_RESULT gboolean sc_text_append(ScText *text, const gchar *data, gsize length,
                                                  GError **error);
gsize sc_text_length(const ScText *text);
G_GNUC_WARN_UNUSED_RESULT gboolean sc_text_snapshot(const ScText *text, gchar **out, gsize *length,
                                                    GError **error);

G_GNUC_WARN_UNUSED_RESULT gboolean sc_bytes_copy(const void *data, gsize length, gsize maximum,
                                                 GBytes **out, GError **error);
G_GNUC_WARN_UNUSED_RESULT gboolean sc_bytes_slice(GBytes *bytes, gsize offset, gsize length,
                                                  GBytes **out, GError **error);
G_GNUC_WARN_UNUSED_RESULT gboolean sc_bytes_read_u16be(GBytes *bytes, gsize offset, guint16 *out,
                                                       GError **error);

G_GNUC_WARN_UNUSED_RESULT ScBytesList *sc_list_new(gsize maximum, gsize payload_maximum,
                                                   GError **error);
void sc_list_free(ScBytesList *list);
gsize sc_list_length(const ScBytesList *list);
G_GNUC_WARN_UNUSED_RESULT gboolean sc_list_append(ScBytesList *list, GBytes *value, GError **error);
G_GNUC_WARN_UNUSED_RESULT gboolean sc_list_replace(ScBytesList *list, gsize index, GBytes *value,
                                                   GError **error);
G_GNUC_WARN_UNUSED_RESULT gboolean sc_list_get_ref(const ScBytesList *list, gsize index,
                                                   GBytes **out, GError **error);
G_GNUC_WARN_UNUSED_RESULT gboolean sc_list_remove(ScBytesList *list, gsize index, GError **error);

G_GNUC_WARN_UNUSED_RESULT ScBytesMap *sc_map_new(gsize maximum, gsize key_maximum,
                                                 gsize payload_maximum, GError **error);
void sc_map_free(ScBytesMap *map);
gsize sc_map_length(const ScBytesMap *map);
G_GNUC_WARN_UNUSED_RESULT gboolean sc_map_put(ScBytesMap *map, const gchar *key, gsize length,
                                              GBytes *value, GError **error);
G_GNUC_WARN_UNUSED_RESULT gboolean sc_map_get_ref(const ScBytesMap *map, const gchar *key,
                                                  gsize length, GBytes **out, GError **error);
G_GNUC_WARN_UNUSED_RESULT gboolean sc_map_remove(ScBytesMap *map, const gchar *key, gsize length,
                                                 GError **error);

G_DEFINE_AUTOPTR_CLEANUP_FUNC(ScText, sc_text_free)
G_DEFINE_AUTOPTR_CLEANUP_FUNC(ScBytesList, sc_list_free)
G_DEFINE_AUTOPTR_CLEANUP_FUNC(ScBytesMap, sc_map_free)
G_END_DECLS
#endif
