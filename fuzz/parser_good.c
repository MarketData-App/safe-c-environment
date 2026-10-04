#include "parser.h"
int demo_parse(const uint8_t *data, size_t size, unsigned *sum) {
    if (size == 0 || data == NULL || sum == NULL)
        return -1;
    size_t count = data[0];
    if (count > size - 1)
        return -1;
    unsigned value = 0;
    for (size_t i = 0; i < count; ++i)
        value += data[i + 1];
    *sum = value;
    return 0;
}
