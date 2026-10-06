#include "greeting.h"

#include <stddef.h>
#include <stdint.h>

/* Seeded defect: the entry point has the wrong name, so the libFuzzer link fails. */
int LLVMFuzzerTestOneInputSeeded(const uint8_t *data, size_t size);

int LLVMFuzzerTestOneInputSeeded(const uint8_t *data, size_t size) {
    if (data == NULL || size == 0U) {
        return 0;
    }
    return greeting_status_name(GREETING_OK) == NULL ? 1 : 0;
}
