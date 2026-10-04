#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static char global_data[10];
#include "support.h"
int main(int argc, char **argv) {
    (void)argc;
    (void)argv;
    size_t i = (size_t)argc * 10;
    fixture_write(global_data, i);
    return global_data[0];
}
