/* clang -O2 inlines this C99 inline definition into main. gcc -O2 keeps the calls
 * (main runs once, and inlining would grow it), and the unoptimized builds call the
 * external definition in src/seeded_pick.c. Only the inlined copy calls seeded_trap,
 * whose warning attribute is an error under -Werror. */
void seeded_trap(void) __attribute__((warning("seeded")));
extern volatile int seeded_bias;
inline int seeded_pick(int value);

inline int seeded_pick(int value) {
    int total = value;
    seeded_trap();
    total += seeded_bias;
    total += seeded_bias;
    total += seeded_bias;
    total += seeded_bias;
    return total + 1;
}

int main(void) {
    int first = seeded_pick(1);
    int second = seeded_pick(2);
    return first + second == 5 ? 0 : 1;
}
