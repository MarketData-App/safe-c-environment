/* Infrastructure packaging/health demonstration; no application service. */
#define _GNU_SOURCE
#include "dependency-identity.h"
#include "parser.h"
#include "sc-foundation.h"
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

static int foundation_input(const gchar *input) {
    gsize length = strnlen(input, 17);
    g_autoptr(GError) error = NULL;
    g_autoptr(ScText) text = sc_text_new(16, &error);
    if (text == NULL || !sc_text_append(text, input, length, &error)) {
        (void)puts("foundation input rejected");
        return 64;
    }
    g_autofree gchar *snapshot = NULL;
    gsize copied = 0;
    if (!sc_text_snapshot(text, &snapshot, &copied, &error) || copied != length) {
        return 9;
    }
    guint8 payload[] = {0, (guint8)length};
    g_autoptr(GBytes) bytes = NULL;
    g_autoptr(ScBytesList) list = sc_list_new(2, 4, &error);
    g_autoptr(ScBytesMap) map = sc_map_new(2, 6, 8, &error);
    if (!sc_bytes_copy(payload, sizeof(payload), 2, &bytes, &error) || list == NULL ||
        map == NULL || !sc_list_append(list, bytes, &error) ||
        !sc_map_put(map, "length", 6, bytes, &error)) {
        return 10;
    }
    g_autoptr(GBytes) retained = NULL;
    guint16 value = 0;
    if (!sc_map_get_ref(map, "length", 6, &retained, &error) ||
        !sc_bytes_read_u16be(retained, 0, &value, &error) || value != length ||
        sc_list_length(list) != 1 || sc_map_length(map) != 1) {
        return 11;
    }
    (void)puts("foundation input accepted");
    return 0;
}

int main(int argc, char **argv) {
    (void)g_log_set_always_fatal(G_LOG_FATAL_MASK | G_LOG_LEVEL_WARNING | G_LOG_LEVEL_CRITICAL);
    if (sc_dependency_identity() != 0) {
        return 12;
    }
    const uint8_t input[] = {2, 4, 5};
    const struct timespec interval = {1, 0};
    const unsigned iterations = argc == 2 && strcmp(argv[1], "--hold") == 0 ? 8U : 1U;
    const gchar *text_input = "ok";
    if (argc == 3 && strcmp(argv[1], "--input") == 0) {
        text_input = argv[2];
    } else if (argc > 2 || (argc == 2 && strcmp(argv[1], "--hold") != 0)) {
        return 64;
    }
    int checked = foundation_input(text_input);
    if (checked != 0) {
        return checked;
    }
    const char *const namespaces[] = {"pid", "net", "ipc", "mnt", "cgroup"};
    for (size_t i = 0; i < sizeof namespaces / sizeof namespaces[0]; ++i) {
        char path[64];
        char identity[128];
        int n = snprintf(path, sizeof path, "/proc/self/ns/%s", namespaces[i]);
        if (n < 0 || (size_t)n >= sizeof path)
            return 5;
        ssize_t length = readlink(path, identity, sizeof identity - 1U);
        if (length < 0 || (size_t)length >= sizeof identity)
            return 6;
        identity[(size_t)length] = '\0';
        if (printf("namespace %s=%s\n", namespaces[i], identity) < 0)
            return 7;
    }
    for (unsigned i = 0; i < iterations; ++i) {
        unsigned sum = 0;
        if (demo_parse(input, sizeof input, &sum) != 0 || sum != 9U)
            return 1;
        if (puts("runtime-demo healthy sum=9") < 0 || fflush(stdout) != 0)
            return 3;
        if (iterations > 1U && nanosleep(&interval, NULL) != 0)
            return 4;
    }
    return 0;
}
