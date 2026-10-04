#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
struct fields {
    int a;
    int b;
};
int main(int argc, char **argv) {
    (void)argc;
    (void)argv;
    struct fields *p = malloc(sizeof *p);
    if (!p)
        return 2;
    p->a = argc;
    int r = p->b == argc ? 0 : 1;
    free(p);
    return r;
}
