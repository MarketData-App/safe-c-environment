#include "greeting.h"
#include "greeting_text.h"

/* Contract: specs/project/greeting.md. No allocation, no global mutable state. */

static const char greeting_prefix[] = "Hello, ";
static const size_t greeting_prefix_length = sizeof greeting_prefix - 1U;

static void clear_output(char *out, size_t capacity, size_t *written) {
    if (out != NULL && capacity > 0U) {
        *out = '\0';
    }
    if (written != NULL) {
        *written = 0U;
    }
}

static enum greeting_status validate(const char *name, size_t name_len, size_t capacity) {
    if (name_len == 0U) {
        return GREETING_EMPTY_NAME;
    }
    /* Reject before any name byte is read: name_len can exceed the buffer. */
    if (name_len > (size_t)GREETING_NAME_MAX) {
        return GREETING_NAME_TOO_LONG;
    }
    const enum greeting_status status = greeting_check_text((const unsigned char *)name, name_len);
    if (status != GREETING_OK) {
        return status;
    }
    /* Prefix, name, '!' and NUL. name_len <= GREETING_NAME_MAX, so the sum cannot wrap. */
    if (capacity < greeting_prefix_length + name_len + 2U) {
        return GREETING_BUFFER_TOO_SMALL;
    }
    return GREETING_OK;
}

enum greeting_status greeting_format(const char *name, size_t name_len, char *out, size_t capacity,
                                     size_t *written) {
    if (name == NULL || out == NULL || written == NULL) {
        clear_output(out, capacity, written);
        return GREETING_NULL_ARGUMENT;
    }
    const enum greeting_status status = validate(name, name_len, capacity);
    if (status != GREETING_OK) {
        clear_output(out, capacity, written);
        return status;
    }
    char *cursor = out;
    for (size_t offset = 0U; offset < greeting_prefix_length; ++offset) {
        *cursor = *(greeting_prefix + offset);
        ++cursor;
    }
    for (size_t offset = 0U; offset < name_len; ++offset) {
        *cursor = *(name + offset);
        ++cursor;
    }
    *cursor = '!';
    ++cursor;
    *cursor = '\0';
    /* Prefix, name and '!'; the NUL is not counted. */
    *written = greeting_prefix_length + name_len + 1U;
    return GREETING_OK;
}

const char *greeting_status_name(enum greeting_status status) {
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
