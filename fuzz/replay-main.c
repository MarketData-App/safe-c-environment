#include "parser.h"
#include <stdlib.h>
int main(void) {
    uint8_t *data = malloc(2);
    if (data == NULL)
        return 2;
    data[0] = 3;
    data[1] = 1;
    unsigned sum = 0;
    int result = demo_parse(data, 2, &sum);
    free(data);
    return result == -1 ? 0 : 1;
}
