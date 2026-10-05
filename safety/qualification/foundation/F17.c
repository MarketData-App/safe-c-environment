#include "dependency-identity.h"
#include "sc-foundation.h"
#include <stdio.h>
int main(void) {
    if (sc_dependency_identity() != 0)
        return 3;
    guint8 input[2];
    input[0] = 0x12;
#if !FOUNDATION_NEGATIVE
    input[1] = 0x34;
#endif
    g_autoptr(GBytes) bytes = NULL;
    if (!sc_bytes_copy(input, 2, 2, &bytes, NULL))
        return 2;
    guint16 value = 0;
    if (!sc_bytes_read_u16be(bytes, 0, &value, NULL))
        return 2;
    return value == 0x1234 ? 0 : 1;
}
