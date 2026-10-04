#include <stdio.h>
#include <string.h>
__attribute__((noinline)) static int copy_checked(const char *input) {
    char buffer[128];
    size_t size = strlen(input);
    if (size >= sizeof buffer)
        return 1;
    if (snprintf(buffer, sizeof buffer, "%s", input) < 0)
        return 1;
    return puts(buffer) < 0 ? 1 : 0;
}
int main(int argc, char **argv) { return copy_checked(argc > 1 ? argv[1] : "hardening-control"); }
