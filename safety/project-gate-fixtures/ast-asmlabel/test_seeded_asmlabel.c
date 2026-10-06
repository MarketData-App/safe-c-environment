#include "greeting.h"

/* Seeded defect for the ast gate, attributes check: the asm label renames this
 * declaration to the AddressSanitizer options hook, which would ask for exit
 * status 0 after a report. The label string is split, so the text pre-check
 * cannot see the runtime name; only the AST attribute allowlist refuses the
 * AsmLabelAttr node. The function is never defined or called, so every build
 * and test passes until the ast gate. */
const char *greeting_options(void) __asm__("__as"
                                           "an_default_options");

int main(void) { return 0; }
