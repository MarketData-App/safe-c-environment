#ifndef QUAL_SUPPORT_H
#define QUAL_SUPPORT_H
#include <stddef.h>
char *fixture_allocate(void);
void fixture_release(char *p);
void fixture_write(char *p, size_t i);
int fixture_read(const char *p);
void fixture_escape(int *p);
int *fixture_stack(void);
void fixture_leak(size_t n);
void *fixture_fail_realloc(void *p, size_t n);
int fixture_threads(int safe);
#endif
