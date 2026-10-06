/* Seeded defect for the ast gate, attribute check: FIXTURE_ENTRY expands to an
 * attribute that removes every instrumentation from a function. Neither the
 * macro name nor the attribute name is inventory pre-check text, and every
 * build accepts it; only the AST attribute scan of the ast gate refuses it. */
#define FIXTURE_ENTRY __attribute__((naked))

void fixture_entry(void);

FIXTURE_ENTRY void fixture_entry(void) {}

int main(void) { return 0; }
