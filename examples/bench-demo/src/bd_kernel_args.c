#include "bd_wire.h"

#include <stdint.h>
#include <stdlib.h>
#include <string.h>

/* The option parser of bd-kernel (specs/project/bd_wire.md). A separate
 * translation unit, so that each analyzer run stays within its fixed budget.
 * No allocation, no global mutable state. */

/* Parses a decimal text of 1 to 7 digits with a value in [1, limit]. Returns
 * 1 and stores the value, or 0 (value 0). Seven digits cannot overflow. */
static int parse_count(const char *text, uint64_t limit, uint64_t *value) {
    *value = 0U;
    if (text == NULL) {
        return 0;
    }
    const size_t length = strlen(text);
    if (length == 0U || length > 7U || strspn(text, "0123456789") != length) {
        return 0;
    }
    const unsigned long long parsed = strtoull(text, NULL, 10);
    if (parsed == 0U || parsed > limit) {
        return 0;
    }
    *value = (uint64_t)parsed;
    return 1;
}

static int same(const char *text, const char *want) {
    return text != NULL && strcmp(text, want) == 0;
}

int bd_kernel_parse(int argc, char **argv, struct bd_kernel_options *o) {
    const struct bd_kernel_options none = {NULL, NULL, 0U, 0U, 0};
    *o = none;
    if (argv == NULL || argc < 7 || argc > 10) {
        return 0;
    }
    /* The fixed order: --input PATH --records N --loops L, then optionally
     * --handshake, then optionally --output PATH. */
    const int input = same(*(argv + 1), "--input") & (*(argv + 2) != NULL);
    const int names = same(*(argv + 3), "--records") & same(*(argv + 5), "--loops");
    const int records = parse_count(*(argv + 4), (uint64_t)BD_RECORDS_MAX, &o->records);
    const int loops = parse_count(*(argv + 6), (uint64_t)BD_LOOPS_MAX, &o->loops);
    const int handshake = argc > 7 && same(*(argv + 7), "--handshake");
    const int at = 7 + handshake;
    const int output = at + 2 == argc && same(*(argv + at), "--output") && *(argv + at + 1) != NULL;
    const int ok = input & names & records & loops & ((at == argc) | output);
    if (ok == 0) {
        *o = none;
        return 0;
    }
    o->input = *(argv + 2);
    o->output = output != 0 ? *(argv + at + 1) : NULL;
    o->handshake = handshake;
    return 1;
}
