#include "parser.h"
int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size);
int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    unsigned sum = 0;
    (void)demo_parse(data, size, &sum);
    return 0;
}
