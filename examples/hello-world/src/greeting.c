#include "greeting.h"

#include <stdint.h>
#include <stdio.h>

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

/* Decodes one UTF-8 sequence that starts at bytes and has at most remaining
 * readable bytes (remaining >= 1). Returns the sequence length (1 to 4), or 0
 * for a truncated, overlong, surrogate or above-U+10FFFF sequence. */
static size_t decode_utf8(const unsigned char *bytes, size_t remaining, uint32_t *code_point) {
    const unsigned char lead = *bytes;
    size_t length = 0U;
    uint32_t value = 0U;
    uint32_t minimum = 0U;
    if (lead < 0x80U) {
        *code_point = lead;
        return 1U;
    }
    if (lead >= 0xC2U && lead <= 0xDFU) {
        length = 2U;
        value = lead & 0x1FU;
        minimum = 0x80U;
    } else if (lead >= 0xE0U && lead <= 0xEFU) {
        length = 3U;
        value = lead & 0x0FU;
        minimum = 0x800U;
    } else if (lead >= 0xF0U && lead <= 0xF4U) {
        length = 4U;
        value = lead & 0x07U;
        minimum = 0x10000U;
    } else {
        return 0U;
    }
    if (length > remaining) {
        return 0U;
    }
    for (size_t offset = 1U; offset < length; ++offset) {
        const unsigned char next = *(bytes + offset);
        if ((next & 0xC0U) != 0x80U) {
            return 0U;
        }
        value = (value << 6U) | (uint32_t)(next & 0x3FU);
    }
    if (value < minimum || value > 0x10FFFFU) {
        return 0U;
    }
    if (value >= 0xD800U && value <= 0xDFFFU) {
        return 0U;
    }
    *code_point = value;
    return length;
}

/* Printable: no C0 control (U+0000..U+001F), no DEL (U+007F) and no C1
 * control (U+0080..U+009F). */
static int is_printable(uint32_t code_point) {
    if (code_point < 0x20U || code_point == 0x7FU) {
        return 0;
    }
    return code_point < 0x80U || code_point > 0x9FU;
}

/* Scans all length bytes. Invalid UTF-8 anywhere wins over a non-printable
 * code point, so the reported status follows the specified order. */
static enum greeting_status check_name(const unsigned char *bytes, size_t length) {
    int printable = 1;
    size_t offset = 0U;
    while (offset < length) {
        uint32_t code_point = 0U;
        const size_t step = decode_utf8(bytes + offset, length - offset, &code_point);
        if (step == 0U) {
            return GREETING_INVALID_UTF8;
        }
        if (!is_printable(code_point)) {
            printable = 0;
        }
        offset += step;
    }
    return printable ? GREETING_OK : GREETING_NOT_PRINTABLE;
}

static enum greeting_status validate(const char *name, size_t name_len, size_t capacity) {
    if (name_len == 0U) {
        return GREETING_EMPTY_NAME;
    }
    /* Reject before any name byte is read: name_len can exceed the buffer. */
    if (name_len > (size_t)GREETING_NAME_MAX) {
        return GREETING_NAME_TOO_LONG;
    }
    const enum greeting_status status = check_name((const unsigned char *)name, name_len);
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

/* Counts at most limit bytes of a NUL-terminated text. A NULL text counts as 0
 * bytes; greeting_format then reports GREETING_NULL_ARGUMENT. */
static size_t bounded_length(const char *text, size_t limit) {
    size_t length = 0U;
    if (text == NULL) {
        return 0U;
    }
    while (length < limit && *(text + length) != '\0') {
        ++length;
    }
    return length;
}

/* Writes line and a newline, then flushes. Returns 0 on success and 1 when any
 * step fails. All three steps always run, so the result has no branch. */
static int write_line(FILE *stream, const char *line) {
    const int text_failed = fputs(line, stream) == EOF;
    const int newline_failed = fputc('\n', stream) == EOF;
    const int flush_failed = fflush(stream) == EOF;
    return text_failed | newline_failed | flush_failed;
}

int greeting_main(int argc, char **argv, FILE *out, FILE *err) {
    if (argc != 2) {
        (void)fputs("usage: hello NAME\n", err);
        return 2;
    }
    const char *name = *(argv + 1);
    const size_t name_len = bounded_length(name, (size_t)GREETING_NAME_MAX + 1U);
    char line[GREETING_NAME_MAX + 9];
    size_t written = 0U;
    enum greeting_status status = greeting_format(name, name_len, line, sizeof line, &written);
    if (status != GREETING_OK) {
        (void)fprintf(err, "hello: %s\n", greeting_status_name(status));
        return 1;
    }
    return write_line(out, line);
}
