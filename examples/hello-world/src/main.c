#include "greeting.h"

#include <stdio.h>

/* Usage: hello NAME. Exit 0 on success, 1 on a greeting error, 2 on a usage error. */

static const char *status_name(enum greeting_status status) {
    switch (status) {
    case GREETING_OK:
        return "GREETING_OK";
    case GREETING_NULL_ARGUMENT:
        return "GREETING_NULL_ARGUMENT";
    case GREETING_EMPTY_NAME:
        return "GREETING_EMPTY_NAME";
    case GREETING_NAME_TOO_LONG:
        return "GREETING_NAME_TOO_LONG";
    case GREETING_INVALID_UTF8:
        return "GREETING_INVALID_UTF8";
    case GREETING_NOT_PRINTABLE:
        return "GREETING_NOT_PRINTABLE";
    case GREETING_BUFFER_TOO_SMALL:
        return "GREETING_BUFFER_TOO_SMALL";
    }
    return "GREETING_UNKNOWN";
}

/* Counts at most limit bytes, so an argument of any size is read only up to
 * GREETING_NAME_MAX + 1 bytes; a longer name then reports GREETING_NAME_TOO_LONG. */
static size_t bounded_length(const char *text, size_t limit) {
    size_t length = 0U;
    while (length < limit && *(text + length) != '\0') {
        ++length;
    }
    return length;
}

int main(int argc, char **argv) {
    if (argc != 2 || argv == NULL || *(argv + 1) == NULL) {
        (void)fputs("usage: hello NAME\n", stderr);
        return 2;
    }
    const char *name = *(argv + 1);
    const size_t name_len = bounded_length(name, (size_t)GREETING_NAME_MAX + 1U);
    char line[GREETING_NAME_MAX + 9];
    size_t written = 0U;
    enum greeting_status status = greeting_format(name, name_len, line, sizeof line, &written);
    if (status != GREETING_OK) {
        (void)fputs("hello: ", stderr);
        (void)fputs(status_name(status), stderr);
        (void)fputs("\n", stderr);
        return 1;
    }
    if (fputs(line, stdout) == EOF || fputs("\n", stdout) == EOF || fflush(stdout) == EOF) {
        return 1;
    }
    return 0;
}
