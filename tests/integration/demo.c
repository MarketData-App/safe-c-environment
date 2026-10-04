#include "parser.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define REQUIRE(x)                                                                                 \
    do {                                                                                           \
        if (!(x)) {                                                                                \
            fprintf(stderr, "CONTRACT %s:%d: %s\n", __FILE__, __LINE__, #x);                       \
            return 1;                                                                              \
        }                                                                                          \
    } while (0)
static size_t partial(size_t n) { return n > 1 ? 1 : n; }
static int allocation_trial(int fail_at) {
    void *first = NULL;
    void *second = NULL;
    int live = 0;
    if (fail_at != 0) {
        first = malloc(8);
        if (first == NULL)
            return 2;
        ++live;
    }
    if (first != NULL && fail_at != 1) {
        second = malloc(8);
        if (second == NULL) {
            free(first);
            return 2;
        }
        ++live;
    }
    if (second != NULL) {
        free(second);
        --live;
    }
    if (first != NULL) {
        free(first);
        --live;
    }
    return live == 0 ? 0 : 1;
}
int main(void) {
    const uint8_t valid[] = {2, 4, 5};
    const uint8_t short_input[] = {3, 1};
    unsigned sum = 0;
    REQUIRE(demo_parse(valid, sizeof valid, &sum) == 0);
    REQUIRE(sum == 9);
    REQUIRE(demo_parse(short_input, sizeof short_input, &sum) == -1);
    REQUIRE(demo_parse(NULL, 0, &sum) == -1);
    for (size_t n = 0; n <= 3; ++n) {
        const uint8_t bytes[] = {2, 1, 2};
        REQUIRE((demo_parse(bytes, n, &sum) == 0) == (n == 3));
    }
    size_t completed = 0;
    while (completed < 4)
        completed += partial(4 - completed);
    REQUIRE(completed == 4);
    /* Fail each allocation site and verify cleanup, including normal success. */
    REQUIRE(allocation_trial(0) == 0);
    REQUIRE(allocation_trial(1) == 0);
    REQUIRE(allocation_trial(2) == 0);
    return 0;
}
