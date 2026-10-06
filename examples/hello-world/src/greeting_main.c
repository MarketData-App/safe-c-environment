#include "greeting.h"

#include <stdio.h>

/* Program logic of hello (specs/project/greeting.md). This file is a separate
 * translation unit so that each analyzer run stays within its fixed budget. */

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
