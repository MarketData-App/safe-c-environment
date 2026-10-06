#include "greeting.h"

#include <string.h>

int main(void) {
    const char *name = greeting_status_name(GREETING_OK);
    /* Seeded defect: the expected status name is wrong. */
    return strcmp(name, "GREETING_WRONG") == 0 ? 0 : 1;
}
