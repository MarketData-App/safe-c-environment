#define _POSIX_C_SOURCE 200809L

#include <fcntl.h>

static int seeded_probe(void) {
    const int descriptor = open("/dev/null", O_RDONLY);
    return descriptor >= 0 ? 0 : 1;
}

int main(void) { return seeded_probe(); }
