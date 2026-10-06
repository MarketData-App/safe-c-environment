#ifndef GREETING_H
#define GREETING_H
#include <stddef.h>
enum greeting_status {
    GREETING_OK = 0,
    GREETING_NULL_ARGUMENT = 1,
    GREETING_EMPTY_NAME = 2,
    GREETING_NAME_TOO_LONG = 3,
    GREETING_INVALID_UTF8 = 4,
    GREETING_NOT_PRINTABLE = 5,
    GREETING_BUFFER_TOO_SMALL = 6
};
enum { GREETING_NAME_MAX = 64 };
/* Writes "Hello, <name>!" plus NUL into out[0..capacity).
 * name has name_len bytes (not NUL terminated).
 * On any status other than GREETING_OK, out[0] is NUL when capacity > 0
 * and *written is 0. See specs/project/greeting.md for the full contract. */
enum greeting_status greeting_format(const char *name, size_t name_len, char *out, size_t capacity,
                                     size_t *written);
#endif
