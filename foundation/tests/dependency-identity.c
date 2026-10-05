#define _GNU_SOURCE
#include "dependency-identity.h"
#include <link.h>
#include <stdio.h>
#include <string.h>

typedef struct {
    unsigned int found;
    int failed;
} Identity;

static int observe(struct dl_phdr_info *info, size_t size, void *opaque) {
    (void)size;
    Identity *identity = opaque;
    if (strstr(info->dlpi_name, "/libglib-2.0.so") != NULL ||
        strstr(info->dlpi_name, "/libpcre2-8.so") != NULL) {
        char path[256] = {0};
        int length = snprintf(path, sizeof(path), "%s", info->dlpi_name);
        if (length < 0 || (size_t)length >= sizeof(path)) {
            identity->failed = 1;
            return 1;
        }
        if (printf("DEPENDENCY_LOADED %s\n", path) < 0) {
            identity->failed = 1;
            return 1;
        }
        identity->found += 1;
    }
    return 0;
}

int sc_dependency_identity(void) {
    Identity identity = {0, 0};
    int result = dl_iterate_phdr(observe, &identity);
    return result == 0 && identity.failed == 0 && identity.found == 2 ? 0 : 1;
}
