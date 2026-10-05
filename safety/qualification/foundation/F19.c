#include <glib.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
void *__real_malloc(size_t size);
void *__wrap_malloc(size_t size);
static gboolean armed = FALSE;
static guint intercepted = 0;
void *__wrap_malloc(size_t size) {
    if (armed && size == 37) {
        static const char marker[] = "F19_BACKEND_NULL\n";
        armed = FALSE;
        intercepted += 1;
        if (write(2, marker, sizeof(marker) - 1) != (ssize_t)(sizeof(marker) - 1))
            _Exit(74);
        return NULL;
    }
    return __real_malloc(size);
}
int main(int argc, char **argv) {
    gboolean inject = argc == 2 && strcmp(argv[1], "--fail") == 0;
    if (argc > 2 || (argc == 2 && !inject && strcmp(argv[1], "--control") != 0))
        return 64;
    void *warmup = g_malloc(16);
    g_free(warmup);
    armed = inject;
    void *value = g_malloc(37);
    if (value == NULL)
        return 75;
    g_free(value);
    if (intercepted != 0)
        return 76;
    static const char marker[] = "F19_NO_INJECTION_PASS\n";
    return write(1, marker, sizeof(marker) - 1) == (ssize_t)(sizeof(marker) - 1) ? 0 : 74;
}
