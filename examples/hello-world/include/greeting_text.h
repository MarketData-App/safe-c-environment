#ifndef GREETING_TEXT_H
#define GREETING_TEXT_H
#include "greeting.h"
#include <stddef.h>
/* Internal to the greeting module. Checks length >= 1 readable bytes at bytes:
 * GREETING_INVALID_UTF8 for any ill-formed UTF-8, else GREETING_NOT_PRINTABLE
 * for any C0 control, DEL or C1 control, else GREETING_OK. */
enum greeting_status greeting_check_text(const unsigned char *bytes, size_t length);
#endif
