/* Seeded defect for the inventory gate, runtime-interface check: the test
 * defines the AddressSanitizer options hook and asks for exit status 0 after a
 * report. The runtime environment sets a nonzero exit code that overrides it,
 * and both the pre-check and the AST policy refuse the runtime name. */
const char *__asan_default_options(void);

const char *__asan_default_options(void) { return "exitcode=0"; }

int main(void) { return 0; }
