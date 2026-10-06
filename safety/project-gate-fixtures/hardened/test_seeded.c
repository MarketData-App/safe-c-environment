#include <stdio.h>

int main(void) {
    char buffer[1] = {0};
#if defined(__clang__)
    fread(buffer, 1U, 0U, stdin);
#endif
    return buffer[0] == 0 ? 0 : 1;
}
