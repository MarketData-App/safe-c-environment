#include "greeting.h"

#include <stddef.h>
#include <stdint.h>

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size);

/* Seeded defect: one exact four-byte input traps; the regression input is that input. */
int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    if (size == 4U && *data == 0xDEU && *(data + 1) == 0xADU) {
        if (*(data + 2) == 0xBEU && *(data + 3) == 0xEFU) {
            __builtin_trap();
        }
    }
    (void)greeting_status_name(GREETING_OK);
    return 0;
}
