#include <stdio.h>

int main(void) {
    char buffer[1] = {0};
    fread(buffer, 1U, 0U, stdin);
    return buffer[0] == 0 ? 0 : 1;
}
