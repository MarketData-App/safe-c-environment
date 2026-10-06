#include "greeting.h"

#include <stddef.h>
#include <stdint.h>

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size);

/* Seeded defect: inputs that start with "QZ" trap. No corpus or regression input
 * starts with these bytes; only fuzz exploration can reach the trap. */
int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    if (size >= 2U && *data == 0x51U && *(data + 1) == 0x5AU) {
        __builtin_trap();
    }
    (void)greeting_status_name(GREETING_OK);
    return 0;
}
