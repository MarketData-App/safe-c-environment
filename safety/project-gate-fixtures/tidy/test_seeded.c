#include <stddef.h>

int main(void) {
    const size_t width = sizeof(sizeof(int));
    return width == 0U ? 1 : 0;
}
