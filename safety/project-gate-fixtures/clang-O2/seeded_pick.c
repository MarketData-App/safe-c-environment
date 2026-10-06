/* The external definition of seeded_pick; the test file holds an inline definition. */
int seeded_pick(int value);

volatile int seeded_bias = 0;

int seeded_pick(int value) { return value + 1; }
