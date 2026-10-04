#ifndef DEMO_PARSER_H
#define DEMO_PARSER_H
#include <stddef.h>
#include <stdint.h>
int demo_parse(const uint8_t *data, size_t size, unsigned *sum);
#endif
