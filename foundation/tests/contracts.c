#include "dependency-identity.h"
#include "sc-foundation.h"
#include <stdio.h>
#include <string.h>

#define REQUIRE(condition)                                                                         \
    do {                                                                                           \
        if (!(condition)) {                                                                        \
            (void)fprintf(stderr, "CONTRACT_FAILED %s:%d\n", __func__, __LINE__);                  \
            return FALSE;                                                                          \
        }                                                                                          \
    } while (0)

static gboolean sizes(void) {
    gsize result = 37;
    REQUIRE(!sc_size_add(G_MAXSIZE, 1, &result) && result == 37);
    REQUIRE(!sc_size_mul(G_MAXSIZE, 2, &result) && result == 37);
    REQUIRE(sc_size_add(G_MAXSIZE, 0, &result) && result == G_MAXSIZE);
    REQUIRE(sc_size_mul(G_MAXSIZE, 1, &result) && result == G_MAXSIZE);
    REQUIRE(sc_size_mul(0, G_MAXSIZE, &result) && result == 0);
    REQUIRE(!sc_size_add(1, 2, NULL));
    REQUIRE(!sc_size_mul(1, 2, NULL));
    REQUIRE(!sc_length(-1, G_MAXSIZE, &result) && result == 0);
    REQUIRE(!sc_length(2, 1, &result) && result == 0);
    REQUIRE(!sc_length(0, 1, NULL));
    REQUIRE(sc_length(0, 0, &result) && result == 0);
    REQUIRE(sc_length(255, 255, &result) && result == 255);
    REQUIRE(!sc_length(256, 255, &result) && result == 255);
    REQUIRE(sc_length(0, 0, &result) && result == 0);
    REQUIRE(sc_length(G_MAXSSIZE, G_MAXSIZE, &result) && result == (gsize)G_MAXSSIZE);
    REQUIRE(sc_range(0, 0, 0) && sc_range(3, 0, 3));
    REQUIRE(sc_range(0, 3, 3) && sc_range(1, 2, 3));
    REQUIRE(!sc_range(4, 0, 3) && !sc_range(1, 3, 3));
    REQUIRE(!sc_range(G_MAXSIZE, 1, G_MAXSIZE));
    return TRUE;
}

static gboolean text(void) {
    g_autoptr(GError) error = NULL;
    g_autoptr(ScText) value = sc_text_new(5, &error);
    REQUIRE(value != NULL && error == NULL);
    REQUIRE(sc_text_append(value, NULL, 0, &error));
    REQUIRE(sc_text_append(value, "ab", 2, &error));
    const gchar utf8[] = "\xe2\x82\xac";
    REQUIRE(sc_text_append(value, utf8, 3, &error));
    REQUIRE(sc_text_length(value) == 5);
    g_autofree gchar *snapshot = NULL;
    gsize length = 0;
    REQUIRE(sc_text_snapshot(value, &snapshot, &length, &error));
    REQUIRE(length == 5 && snapshot[length] == '\0');
    REQUIRE(memcmp(snapshot, "ab\xe2\x82\xac", 5) == 0);
    REQUIRE(!sc_text_append(value, "x", 1, &error));
    REQUIRE(error != NULL && error->code == SC_ERROR_LIMIT && sc_text_length(value) == 5);
    g_clear_error(&error);
    REQUIRE(!sc_text_append(value, "x", G_MAXSIZE, &error));
    g_clear_error(&error);
    g_autoptr(ScText) grow = sc_text_new(128, &error);
    REQUIRE(grow != NULL);
    REQUIRE(sc_text_append(grow, "old", 3, &error));
    g_autofree gchar *old = NULL;
    REQUIRE(sc_text_snapshot(grow, &old, &length, &error));
    REQUIRE(sc_text_append(grow, "abcdefghijklmnopqrstuvwxyz", 26, &error));
    REQUIRE(strcmp(old, "old") == 0 && sc_text_length(grow) == 29);
    const gchar invalid[] = "\xc0\xaf";
    REQUIRE(!sc_text_append(grow, invalid, 2, &error));
    REQUIRE(error != NULL && error->code == SC_ERROR_ENCODING && sc_text_length(grow) == 29);
    g_clear_error(&error);
    const gchar binary[] = {'a', '\0', 'b'};
    REQUIRE(!sc_text_append(grow, binary, sizeof(binary), &error));
    g_clear_error(&error);
    REQUIRE(!sc_text_append(grow, NULL, 1, &error));
    REQUIRE(error != NULL && error->code == SC_ERROR_INVALID);
    g_clear_error(&error);
    REQUIRE(!sc_text_append(NULL, "a", 1, &error));
    g_clear_error(&error);
    REQUIRE(sc_text_new(SC_MAX_TEXT + 1, &error) == NULL);
    g_clear_error(&error);
    g_autoptr(ScText) empty = sc_text_new(0, NULL);
    REQUIRE(empty != NULL && sc_text_append(empty, NULL, 0, NULL));
    REQUIRE(!sc_text_append(empty, "a", 1, NULL));
    REQUIRE(sc_text_length(NULL) == 0);
    sc_text_free(NULL);
    gchar *missing = NULL;
    REQUIRE(!sc_text_snapshot(NULL, &missing, &length, &error) && missing == NULL && length == 0);
    g_clear_error(&error);
    REQUIRE(!sc_text_snapshot(grow, NULL, &length, &error));
    g_clear_error(&error);
    REQUIRE(!sc_text_snapshot(grow, &missing, NULL, &error));
    g_clear_error(&error);
    return TRUE;
}

static gboolean bytes(void) {
    g_autoptr(GError) error = NULL;
    guint8 input[] = {0, 0x12, 0x34, 0xff};
    g_autoptr(GBytes) owner = NULL;
    REQUIRE(sc_bytes_copy(input, sizeof(input), 4, &owner, &error));
    input[1] = 0;
    guint16 number = 0;
    REQUIRE(sc_bytes_read_u16be(owner, 1, &number, &error) && number == 0x1234);
    g_autoptr(GBytes) slice = NULL;
    REQUIRE(sc_bytes_slice(owner, 1, 2, &slice, &error));
    g_clear_pointer(&owner, g_bytes_unref);
    REQUIRE(sc_bytes_read_u16be(slice, 0, &number, &error) && number == 0x1234);
    g_autoptr(GBytes) empty = NULL;
    REQUIRE(sc_bytes_copy(NULL, 0, 0, &empty, &error));
    REQUIRE(g_bytes_get_size(empty) == 0);
    g_autoptr(GBytes) end = NULL;
    REQUIRE(sc_bytes_slice(empty, 0, 0, &end, &error) && g_bytes_get_size(end) == 0);
    g_clear_pointer(&end, g_bytes_unref);
    REQUIRE(sc_bytes_slice(slice, 2, 0, &end, &error) && g_bytes_get_size(end) == 0);
    g_clear_pointer(&end, g_bytes_unref);
    REQUIRE(sc_bytes_slice(slice, 0, 2, &end, &error));
    g_clear_pointer(&end, g_bytes_unref);
    REQUIRE(!sc_bytes_slice(slice, 3, 0, &end, &error) && end == NULL);
    g_clear_error(&error);
    REQUIRE(!sc_bytes_slice(slice, 1, G_MAXSIZE, &end, &error) && end == NULL);
    g_clear_error(&error);
    REQUIRE(!sc_bytes_read_u16be(slice, 1, &number, &error) && number == 0);
    g_clear_error(&error);
    REQUIRE(!sc_bytes_read_u16be(empty, 0, &number, &error));
    g_clear_error(&error);
    REQUIRE(!sc_bytes_copy(NULL, 1, 4, &end, &error));
    g_clear_error(&error);
    REQUIRE(!sc_bytes_copy(input, sizeof(input), 3, &end, &error));
    g_clear_error(&error);
    REQUIRE(!sc_bytes_copy(NULL, 0, SC_MAX_BYTES + 1, &end, &error));
    g_clear_error(&error);
    REQUIRE(!sc_bytes_copy(input, 1, 4, NULL, &error));
    g_clear_error(&error);
    REQUIRE(!sc_bytes_slice(NULL, 0, 0, &end, &error));
    g_clear_error(&error);
    REQUIRE(!sc_bytes_slice(slice, 0, 0, NULL, &error));
    g_clear_error(&error);
    REQUIRE(!sc_bytes_read_u16be(NULL, 0, &number, &error));
    g_clear_error(&error);
    REQUIRE(!sc_bytes_read_u16be(slice, 0, NULL, &error));
    g_clear_error(&error);
    return TRUE;
}

typedef struct {
    guint *destroyed;
    guint8 payload;
} Witness;

static void witness_free(gpointer opaque) {
    Witness *witness = opaque;
    *witness->destroyed += 1;
    g_free(witness);
}

/* Qualified test boundary only: initialized storage and a correctly typed
 * callback expose exact reference-release accounting. This is not public API. */
static GBytes *witness_new(guint *destroyed, guint8 payload) {
    Witness *witness = g_new0(Witness, 1);
    witness->destroyed = destroyed;
    witness->payload = payload;
    return g_bytes_new_with_free_func(&witness->payload, 1, witness_free, witness);
}

static gboolean lists(void) {
    g_autoptr(GError) error = NULL;
    guint destroyed = 0;
    g_autoptr(GBytes) first = witness_new(&destroyed, 1);
    g_autoptr(GBytes) last = witness_new(&destroyed, 2);
    g_autoptr(ScBytesList) list = sc_list_new(2, 2, &error);
    REQUIRE(list != NULL);
    GBytes *missing = NULL;
    REQUIRE(!sc_list_get_ref(list, 0, &missing, &error) && missing == NULL);
    g_clear_error(&error);
    REQUIRE(sc_list_append(list, first, &error));
    REQUIRE(sc_list_append(list, last, &error));
    REQUIRE(!sc_list_append(list, first, &error) && sc_list_length(list) == 2);
    g_clear_error(&error);
    REQUIRE(!sc_list_get_ref(list, 2, &missing, &error) && missing == NULL);
    g_clear_error(&error);
    REQUIRE(!sc_list_get_ref(list, G_MAXSIZE, &missing, &error));
    g_clear_error(&error);
    REQUIRE(sc_list_replace(list, 0, first, &error) && destroyed == 0);
    g_autoptr(GBytes) retained = NULL;
    REQUIRE(sc_list_get_ref(list, 1, &retained, &error) && g_bytes_equal(retained, last));
    REQUIRE(sc_list_remove(list, 0, &error) && sc_list_length(list) == 1 && destroyed == 0);
    g_autoptr(GBytes) shifted = NULL;
    REQUIRE(sc_list_get_ref(list, 0, &shifted, &error) && g_bytes_equal(shifted, last));
    REQUIRE(!sc_list_remove(list, 1, &error));
    g_clear_error(&error);
    REQUIRE(!sc_list_replace(list, 1, first, &error));
    g_clear_error(&error);
    g_clear_pointer(&list, sc_list_free);
    REQUIRE(destroyed == 0 && g_bytes_get_size(first) == 1);
    g_clear_pointer(&first, g_bytes_unref);
    REQUIRE(destroyed == 1);
    g_clear_pointer(&last, g_bytes_unref);
    g_clear_pointer(&retained, g_bytes_unref);
    REQUIRE(destroyed == 1);
    g_clear_pointer(&shifted, g_bytes_unref);
    REQUIRE(destroyed == 2);
    guint replacement_destroyed = 0;
    GBytes *replace_first = witness_new(&replacement_destroyed, 1);
    GBytes *replace_second = witness_new(&replacement_destroyed, 2);
    g_autoptr(ScBytesList) replacement = sc_list_new(1, 1, NULL);
    REQUIRE(replacement != NULL && sc_list_append(replacement, replace_first, NULL));
    g_bytes_unref(replace_first);
    REQUIRE(sc_list_replace(replacement, 0, replace_second, NULL));
    REQUIRE(replacement_destroyed == 1);
    g_bytes_unref(replace_second);
    g_clear_pointer(&replacement, sc_list_free);
    REQUIRE(replacement_destroyed == 2);
    g_autoptr(ScBytesList) limited = sc_list_new(2, 0, &error);
    g_autoptr(GBytes) data = NULL;
    REQUIRE(sc_bytes_copy("x", 1, 1, &data, &error));
    REQUIRE(!sc_list_append(limited, data, &error) && sc_list_length(limited) == 0);
    g_clear_error(&error);
    g_autoptr(GBytes) empty = NULL;
    REQUIRE(sc_bytes_copy(NULL, 0, 0, &empty, &error));
    REQUIRE(sc_list_append(limited, empty, &error));
    REQUIRE(!sc_list_replace(limited, 0, data, &error));
    g_clear_error(&error);
    REQUIRE(!sc_list_append(NULL, data, &error));
    g_clear_error(&error);
    REQUIRE(!sc_list_append(limited, NULL, &error));
    g_clear_error(&error);
    REQUIRE(!sc_list_replace(NULL, 0, data, &error));
    g_clear_error(&error);
    REQUIRE(!sc_list_replace(limited, 0, NULL, &error));
    g_clear_error(&error);
    REQUIRE(!sc_list_get_ref(NULL, 0, &missing, &error));
    g_clear_error(&error);
    REQUIRE(!sc_list_get_ref(limited, 0, NULL, &error));
    g_clear_error(&error);
    REQUIRE(!sc_list_remove(NULL, 0, &error));
    g_clear_error(&error);
    REQUIRE(sc_list_new(SC_MAX_ENTRIES + 1, 0, &error) == NULL);
    g_clear_error(&error);
    REQUIRE(sc_list_new(1, SC_MAX_BYTES + 1, &error) == NULL);
    g_clear_error(&error);
    REQUIRE(sc_list_length(NULL) == 0);
    sc_list_free(NULL);
    return TRUE;
}

static gboolean maps(void) {
    g_autoptr(GError) error = NULL;
    guint destroyed = 0;
    g_autoptr(GBytes) value = witness_new(&destroyed, 7);
    g_autoptr(ScBytesMap) map = sc_map_new(1, 3, 4, &error);
    REQUIRE(map != NULL);
    gchar key[] = "key";
    REQUIRE(sc_map_put(map, key, 3, value, &error));
    key[0] = 'X';
    g_autoptr(GBytes) retained = NULL;
    REQUIRE(sc_map_get_ref(map, "key", 3, &retained, &error) && g_bytes_equal(retained, value));
    REQUIRE(sc_map_put(map, "key", 3, value, &error) && sc_map_length(map) == 1 && destroyed == 0);
    REQUIRE(!sc_map_put(map, "two", 3, value, &error) && sc_map_length(map) == 1);
    g_clear_error(&error);
    REQUIRE(!sc_map_put(map, "long", 4, value, &error));
    g_clear_error(&error);
    GBytes *absent = NULL;
    REQUIRE(!sc_map_get_ref(map, "no", 2, &absent, &error) && absent == NULL);
    REQUIRE(error != NULL && error->code == SC_ERROR_NOT_FOUND);
    g_clear_error(&error);
    REQUIRE(!sc_map_remove(map, "no", 2, &error));
    g_clear_error(&error);
    REQUIRE(sc_map_remove(map, "key", 3, &error) && sc_map_length(map) == 0 && destroyed == 0);
    REQUIRE(sc_map_put(map, "key", 3, value, &error));
    g_clear_pointer(&map, sc_map_free);
    REQUIRE(destroyed == 0);
    g_clear_pointer(&value, g_bytes_unref);
    REQUIRE(destroyed == 0);
    g_clear_pointer(&retained, g_bytes_unref);
    REQUIRE(destroyed == 1);
    guint replacement_destroyed = 0;
    GBytes *replace_first = witness_new(&replacement_destroyed, 1);
    GBytes *replace_second = witness_new(&replacement_destroyed, 2);
    g_autoptr(ScBytesMap) replacement = sc_map_new(1, 1, 2, NULL);
    REQUIRE(replacement != NULL && sc_map_put(replacement, "a", 1, replace_first, NULL));
    g_bytes_unref(replace_first);
    REQUIRE(sc_map_put(replacement, "a", 1, replace_second, NULL));
    REQUIRE(replacement_destroyed == 1 && sc_map_length(replacement) == 1);
    g_bytes_unref(replace_second);
    g_clear_pointer(&replacement, sc_map_free);
    REQUIRE(replacement_destroyed == 2);
    g_autoptr(ScBytesMap) limited = sc_map_new(2, 3, 1, &error);
    g_autoptr(GBytes) empty = NULL;
    REQUIRE(sc_bytes_copy(NULL, 0, 0, &empty, &error));
    REQUIRE(sc_map_put(limited, "a", 1, empty, &error));
    REQUIRE(!sc_map_put(limited, "bb", 2, empty, &error));
    g_clear_error(&error);
    g_autoptr(GBytes) data = NULL;
    REQUIRE(sc_bytes_copy("x", 1, 1, &data, &error));
    REQUIRE(!sc_map_put(limited, "a", 1, data, &error));
    g_clear_error(&error);
    REQUIRE(!sc_map_put(limited, "", 0, empty, &error));
    g_clear_error(&error);
    REQUIRE(!sc_map_put(limited, NULL, 1, empty, &error));
    g_clear_error(&error);
    REQUIRE(!sc_map_put(NULL, "a", 1, empty, &error));
    g_clear_error(&error);
    REQUIRE(!sc_map_put(limited, "a", 1, NULL, &error));
    g_clear_error(&error);
    REQUIRE(!sc_map_put(limited, "\xff", 1, empty, &error));
    g_clear_error(&error);
    REQUIRE(!sc_map_get_ref(limited, "a", 1, NULL, &error));
    g_clear_error(&error);
    GBytes *missing = NULL;
    REQUIRE(!sc_map_get_ref(NULL, "a", 1, &missing, &error));
    g_clear_error(&error);
    REQUIRE(!sc_map_remove(NULL, "a", 1, &error));
    g_clear_error(&error);
    REQUIRE(!sc_map_remove(limited, "toolong", 7, &error));
    g_clear_error(&error);
    REQUIRE(sc_map_new(SC_MAX_ENTRIES + 1, 1, 1, &error) == NULL);
    g_clear_error(&error);
    REQUIRE(sc_map_new(1, SC_MAX_KEY + 1, 1, &error) == NULL);
    g_clear_error(&error);
    REQUIRE(sc_map_new(1, 1, SC_MAX_BYTES + 1, &error) == NULL);
    g_clear_error(&error);
    REQUIRE(sc_map_length(NULL) == 0);
    sc_map_free(NULL);
    return TRUE;
}

static gboolean errors(void) {
    g_autoptr(GError) error = NULL;
    g_autoptr(ScText) text_owner = sc_text_new(2, NULL);
    g_autoptr(ScBytesList) list_owner = sc_list_new(1, 1, NULL);
    g_autoptr(ScBytesMap) map_owner = sc_map_new(1, 1, 1, NULL);
    g_autoptr(GBytes) bytes_owner = NULL;
    REQUIRE(sc_bytes_copy("x", 1, 1, &bytes_owner, NULL));
    REQUIRE(!sc_text_append(text_owner, NULL, 1, &error));
    GError *original = error;
    REQUIRE(!sc_text_append(text_owner, "x", 1, &error) && error == original);
    REQUIRE(sc_text_new(1, &error) == NULL && error == original);
    REQUIRE(sc_list_new(1, 1, &error) == NULL && error == original);
    REQUIRE(sc_map_new(1, 1, 1, &error) == NULL && error == original);
    REQUIRE(!sc_list_append(list_owner, bytes_owner, &error));
    REQUIRE(!sc_list_replace(list_owner, 0, bytes_owner, &error));
    REQUIRE(!sc_list_remove(list_owner, 0, &error));
    REQUIRE(!sc_map_put(map_owner, "x", 1, bytes_owner, &error));
    REQUIRE(!sc_map_remove(map_owner, "x", 1, &error));
    gchar *snapshot = NULL;
    gsize length = 99;
    REQUIRE(!sc_text_snapshot(text_owner, &snapshot, &length, &error) && snapshot == NULL &&
            length == 0);
    GBytes *output = NULL;
    REQUIRE(!sc_bytes_copy("x", 1, 1, &output, &error) && output == NULL);
    REQUIRE(!sc_bytes_slice(bytes_owner, 0, 1, &output, &error) && output == NULL);
    REQUIRE(!sc_list_get_ref(list_owner, 0, &output, &error) && output == NULL);
    REQUIRE(!sc_map_get_ref(map_owner, "x", 1, &output, &error) && output == NULL);
    guint16 word = 99;
    REQUIRE(!sc_bytes_read_u16be(bytes_owner, 0, &word, &error) && word == 0);
    REQUIRE(error == original);
    g_autoptr(GError) propagated = NULL;
    g_propagate_error(&propagated, g_steal_pointer(&error));
    REQUIRE(error == NULL && propagated == original);
    REQUIRE(sc_text_append(text_owner, "x", 1, NULL));
    return TRUE;
}

static gboolean cleanup_early(guint stop, guint *destroyed) {
    g_autoptr(GBytes) first = NULL;
    g_autoptr(GBytes) second = NULL;
    g_autoptr(ScBytesList) list = NULL;
    if (stop == 0) {
        return TRUE;
    }
    first = witness_new(destroyed, 1);
    if (stop == 4) {
        g_autoptr(GError) error = NULL;
        g_autoptr(ScText) invalid = sc_text_new(SC_MAX_TEXT + 1, &error);
        REQUIRE(invalid == NULL && error != NULL && error->code == SC_ERROR_LIMIT);
        return FALSE;
    }
    if (stop == 1) {
        return TRUE;
    }
    second = witness_new(destroyed, 2);
    list = sc_list_new(2, 2, NULL);
    REQUIRE(list != NULL && sc_list_append(list, first, NULL));
    if (stop == 2) {
        return TRUE;
    }
    REQUIRE(sc_list_append(list, second, NULL));
    return TRUE;
}

static gboolean cleanup(void) {
    for (guint stop = 0; stop < 4; stop += 1) {
        guint destroyed = 0;
        REQUIRE(cleanup_early(stop, &destroyed));
        REQUIRE(destroyed == (stop == 0 ? 0U : stop == 1 ? 1U : 2U));
    }
    guint partial_destroyed = 0;
    REQUIRE(!cleanup_early(4, &partial_destroyed) && partial_destroyed == 1);
    guint destroyed = 0;
    GBytes *recipient = NULL;
    {
        g_autoptr(GBytes) owner = witness_new(&destroyed, 1);
        recipient = g_steal_pointer(&owner);
        REQUIRE(owner == NULL && destroyed == 0);
    }
    REQUIRE(recipient != NULL && g_bytes_get_size(recipient) == 1 && destroyed == 0);
    g_bytes_unref(recipient);
    REQUIRE(destroyed == 1);
    return TRUE;
}

int main(int argc, char **argv) {
    (void)g_log_set_always_fatal(G_LOG_FATAL_MASK | G_LOG_LEVEL_WARNING | G_LOG_LEVEL_CRITICAL);
    if (sc_dependency_identity() != 0) {
        return 3;
    }
    const struct {
        const gchar *name;
        gboolean (*test)(void);
    } cases[] = {{"sizes", sizes}, {"text", text},     {"bytes", bytes},    {"lists", lists},
                 {"maps", maps},   {"errors", errors}, {"cleanup", cleanup}};
    guint executed = 0;
    for (gsize i = 0; i < G_N_ELEMENTS(cases); i += 1) {
        if (argc == 1 || (argc == 2 && strcmp(argv[1], cases[i].name) == 0)) {
            if (!cases[i].test()) {
                return 1;
            }
            (void)printf("CONTRACT_PASS %s\n", cases[i].name);
            executed += 1;
        }
    }
    return executed == 0 ? 2 : 0;
}
