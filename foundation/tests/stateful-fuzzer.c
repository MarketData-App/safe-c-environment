#include "sc-foundation.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Independent bounded oracle: fixed arrays/scalars model logical contents;
 * only the system under test uses the shipping adapters. Caller storage is
 * always initialized. Maximum input 256 bytes, 32 operations, four byte owners,
 * four list entries, two one-byte map keys, and sixteen text bytes. */
typedef struct {
    guint8 data[2];
    gsize length;
    gboolean live;
} Model;

static void require(gboolean condition) {
    if (!condition) {
        (void)fputs("FOUNDATION_ORACLE_FAILED\n", stderr);
        abort();
    }
}

static void equal_bytes(GBytes *actual, const Model *expected) {
    require(actual != NULL && expected->live);
    require(g_bytes_get_size(actual) == expected->length);
    if (expected->length != 0) {
        const guint8 *region = g_bytes_get_region(actual, 1, 0, expected->length);
        require(region != NULL && memcmp(region, expected->data, expected->length) == 0);
    }
    if (expected->length == 2) {
        guint16 value = 0;
        require(sc_bytes_read_u16be(actual, 0, &value, NULL));
        require(value == (guint16)(((guint16)expected->data[0] << 8) | expected->data[1]));
    }
}

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size);
int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    if (size > 256) {
        return 0;
    }
    GBytes *owners[4] = {NULL};
    Model model[4] = {0};
    Model list_model[4] = {0};
    Model map_model[2] = {0};
    gsize list_length = 0;
    gchar text_model[17] = {0};
    gsize text_length = 0;
    g_autoptr(ScText) text = sc_text_new(16, NULL);
    g_autoptr(ScBytesList) list = sc_list_new(4, 128, NULL);
    g_autoptr(ScBytesMap) map = sc_map_new(2, 1, 32, NULL);
    require(text != NULL && list != NULL && map != NULL);
    gsize operations = MIN(size / 4, (gsize)32);
    for (gsize step = 0; step < operations; step += 1) {
        gsize base = step * 4;
        guint operation = data[base] % 12U;
        guint slot = data[base + 1] % 4U;
        guint other = data[base + 2] % 4U;
        guint selector = data[base + 3];
        if (operation == 0) {
            g_clear_pointer(&owners[slot], g_bytes_unref);
            guint8 payload[2] = {data[base + 2], data[base + 3]};
            gsize length = selector % 3U;
            require(sc_bytes_copy(payload, length, 2, &owners[slot], NULL));
            model[slot] = (Model){{payload[0], payload[1]}, length, TRUE};
        } else if (operation == 1) {
            if (owners[other] != NULL) {
                GBytes *retained = g_bytes_ref(owners[other]);
                g_clear_pointer(&owners[slot], g_bytes_unref);
                owners[slot] = retained;
                model[slot] = model[other];
            }
        } else if (operation == 2) {
            if (owners[other] != NULL) {
                gsize offset = selector % 4U;
                gsize length = slot % 3U;
                GBytes *slice = NULL;
                gboolean expected =
                    offset <= model[other].length && length <= model[other].length - offset;
                require(sc_bytes_slice(owners[other], offset, length, &slice, NULL) == expected);
                if (expected) {
                    Model result = {{0}, length, TRUE};
                    for (gsize i = 0; i < length; i += 1) {
                        result.data[i] = model[other].data[offset + i];
                    }
                    g_clear_pointer(&owners[slot], g_bytes_unref);
                    owners[slot] = slice;
                    model[slot] = result;
                } else {
                    require(slice == NULL);
                }
            }
        } else if (operation == 3) {
            gboolean expected = owners[slot] != NULL && list_length < 4;
            require(sc_list_append(list, owners[slot], NULL) == expected);
            if (expected) {
                list_model[list_length] = model[slot];
                list_length += 1;
            }
        } else if (operation == 4) {
            gsize index = selector % 6U;
            gboolean expected = owners[slot] != NULL && index < list_length;
            require(sc_list_replace(list, index, owners[slot], NULL) == expected);
            if (expected) {
                list_model[index] = model[slot];
            }
        } else if (operation == 5) {
            gsize index = selector % 6U;
            gboolean expected = index < list_length;
            require(sc_list_remove(list, index, NULL) == expected);
            if (expected) {
                for (gsize i = index; i + 1 < list_length; i += 1) {
                    list_model[i] = list_model[i + 1];
                }
                list_length -= 1;
            }
        } else if (operation == 6) {
            gsize index = selector % 6U;
            GBytes *retained = NULL;
            require(sc_list_get_ref(list, index, &retained, NULL) == (index < list_length));
            if (index < list_length) {
                equal_bytes(retained, &list_model[index]);
                g_bytes_unref(retained);
            } else {
                require(retained == NULL);
            }
        } else if (operation == 7) {
            guint key_index = selector % 2U;
            gchar key = (gchar)('A' + key_index);
            gboolean expected = owners[slot] != NULL;
            require(sc_map_put(map, &key, 1, owners[slot], NULL) == expected);
            if (expected) {
                map_model[key_index] = model[slot];
            }
        } else if (operation == 8) {
            guint key_index = selector % 2U;
            gchar key = (gchar)('A' + key_index);
            GBytes *retained = NULL;
            require(sc_map_get_ref(map, &key, 1, &retained, NULL) == map_model[key_index].live);
            if (map_model[key_index].live) {
                equal_bytes(retained, &map_model[key_index]);
                g_bytes_unref(retained);
            } else {
                require(retained == NULL);
            }
        } else if (operation == 9) {
            guint key_index = selector % 2U;
            gchar key = (gchar)('A' + key_index);
            require(sc_map_remove(map, &key, 1, NULL) == map_model[key_index].live);
            map_model[key_index].live = FALSE;
        } else if (operation == 10) {
            gchar fragment[3] = {'x', 'y', 'z'};
            gsize length = selector % 4U;
            gboolean expected = length <= 16 - text_length;
            require(sc_text_append(text, fragment, length, NULL) == expected);
            if (expected) {
                memcpy(text_model + text_length, fragment, length);
                text_length += length;
            }
        } else {
            g_clear_pointer(&owners[slot], g_bytes_unref);
            model[slot].live = FALSE;
        }
        for (guint i = 0; i < 4; i += 1) {
            if (owners[i] != NULL) {
                equal_bytes(owners[i], &model[i]);
            }
        }
        require(sc_list_length(list) == list_length);
        require(sc_map_length(map) == (gsize)map_model[0].live + (gsize)map_model[1].live);
        g_autofree gchar *snapshot = NULL;
        gsize length = 0;
        require(sc_text_snapshot(text, &snapshot, &length, NULL));
        require(length == text_length && snapshot[length] == '\0');
        require(memcmp(snapshot, text_model, length) == 0);
    }
    for (guint i = 0; i < 4; i += 1) {
        g_clear_pointer(&owners[i], g_bytes_unref);
    }
    return 0;
}
