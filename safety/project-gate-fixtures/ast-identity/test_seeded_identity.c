/* Seeded defect for the ast gate, build identity check: FIXTURE_VALUE depends
 * on a predefined macro that GCC and Clang define with different values and
 * that the inventory pre-check does not list. Every build and test passes, but
 * the GCC and Clang builds compile different code; only the identity check of
 * the ast gate compares the preprocessed project code of all builds. */
#ifdef __GXX_ABI_VERSION
#if __GXX_ABI_VERSION > 1010
#define FIXTURE_VALUE 1
#else
#define FIXTURE_VALUE 2
#endif
#else
#define FIXTURE_VALUE 2
#endif

int main(void) { return FIXTURE_VALUE > 0 ? 0 : 1; }
