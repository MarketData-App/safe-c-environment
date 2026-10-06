#include "greeting_text.h"

/* UTF-8 and printable checks for greeting names (specs/project/greeting.md).
 * Validation follows the well-formed byte sequences of Unicode Table 3-7, which
 * exclude overlong forms, surrogates (U+D800..U+DFFF) and code points above
 * U+10FFFF. This file is a separate translation unit so that each analyzer run
 * stays within its fixed budget. */

/* Sequence length announced by a lead byte, or 0 for an invalid lead byte. */
static size_t utf8_length(unsigned char lead) {
    if (lead < 0x80U) {
        return 1U;
    }
    if (lead < 0xC2U) {
        return 0U;
    }
    if (lead < 0xE0U) {
        return 2U;
    }
    if (lead < 0xF0U) {
        return 3U;
    }
    if (lead < 0xF5U) {
        return 4U;
    }
    return 0U;
}

/* Lowest allowed second byte: E0 excludes overlong 3-byte forms and F0
 * excludes overlong 4-byte forms. */
static unsigned char utf8_second_low(unsigned char lead) {
    if (lead == 0xE0U) {
        return 0xA0U;
    }
    if (lead == 0xF0U) {
        return 0x90U;
    }
    return 0x80U;
}

/* Highest allowed second byte: ED excludes surrogates and F4 excludes code
 * points above U+10FFFF. */
static unsigned char utf8_second_high(unsigned char lead) {
    if (lead == 0xEDU) {
        return 0x9FU;
    }
    if (lead == 0xF4U) {
        return 0x8FU;
    }
    return 0xBFU;
}

/* Returns 1 when count bytes from bytes are all continuation bytes 0x80..0xBF. */
static int utf8_continuations(const unsigned char *bytes, size_t count) {
    for (size_t offset = 0U; offset < count; ++offset) {
        const unsigned char next = *(bytes + offset);
        if (next < 0x80U || next > 0xBFU) {
            return 0;
        }
    }
    return 1;
}

/* Returns the length (1 to 4) of the well-formed sequence that starts at bytes
 * and has remaining >= 1 readable bytes, or 0 for an ill-formed or truncated
 * sequence. */
static size_t utf8_sequence(const unsigned char *bytes, size_t remaining) {
    const unsigned char lead = *bytes;
    const size_t length = utf8_length(lead);
    if (length < 2U) {
        return length;
    }
    if (length > remaining) {
        return 0U;
    }
    const unsigned char second = *(bytes + 1);
    if (second < utf8_second_low(lead) || second > utf8_second_high(lead)) {
        return 0U;
    }
    return utf8_continuations(bytes + 2, length - 2U) ? length : 0U;
}

/* Returns 1 when all length bytes form complete, well-formed UTF-8. */
static int utf8_valid(const unsigned char *bytes, size_t length) {
    size_t offset = 0U;
    while (offset < length) {
        const size_t step = utf8_sequence(bytes + offset, length - offset);
        if (step == 0U) {
            return 0;
        }
        offset += step;
    }
    return 1;
}

/* In well-formed UTF-8, C0 controls (U+0000..U+001F) and DEL (U+007F) are the
 * single bytes 0x00..0x1F and 0x7F, and C1 controls (U+0080..U+009F) are 0xC2
 * followed by 0x80..0x9F. A continuation byte is never 0xC2, so each byte can
 * be checked on its own. The remaining > 1U guard is a defensive memory-safety
 * check that is always true after validation; keep it. */
static int control_at(const unsigned char *bytes, size_t remaining) {
    const unsigned char lead = *bytes;
    if (lead < 0x20U || lead == 0x7FU) {
        return 1;
    }
    return lead == 0xC2U && remaining > 1U && *(bytes + 1) < 0xA0U;
}

/* Returns 1 when well-formed UTF-8 of length bytes holds no control code point. */
static int utf8_printable(const unsigned char *bytes, size_t length) {
    for (size_t offset = 0U; offset < length; ++offset) {
        if (control_at(bytes + offset, length - offset)) {
            return 0;
        }
    }
    return 1;
}

/* Invalid UTF-8 anywhere wins over a control code point, so the reported status
 * follows the specified order. */
enum greeting_status greeting_check_text(const unsigned char *bytes, size_t length) {
    if (!utf8_valid(bytes, length)) {
        return GREETING_INVALID_UTF8;
    }
    return utf8_printable(bytes, length) ? GREETING_OK : GREETING_NOT_PRINTABLE;
}
