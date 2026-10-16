#include "entry.h"

#include <stddef.h>
#include <stdint.h>

/* libFuzzer target: the input length is n and each input byte b gives one value
 * b - 127.5. The target calls the library entry point fixture_entry and checks
 * the postconditions of specs/project/entry.md. A violated postcondition traps. */

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size);

#define CHECK(c) ((c) ? (void)0 : __builtin_trap())

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    double x[FIXTURE_ENTRY_MAX] = {0.0};
    const size_t used = size < (size_t)FIXTURE_ENTRY_MAX ? size : (size_t)FIXTURE_ENTRY_MAX;
    double want = 0.0;
    for (size_t index = 0U; index < used; ++index) {
        *(x + index) = (double)*(data + index) - 127.5;
        want += *(x + index);
    }
    double out = -1.0;
    /* For size above the maximum, x holds fewer than size values; the entry
     * point must refuse before it reads any element. */
    const int status = fixture_entry(x, size, &out);
    if (size >= 1U && size <= (size_t)FIXTURE_ENTRY_MAX) {
        CHECK(status == 0 && out == want);
    } else {
        CHECK(status == 1 && out == -1.0);
    }
    CHECK(fixture_entry(NULL, size, &out) == 1);
    CHECK(fixture_entry(x, size, NULL) == 1);
    return 0;
}
