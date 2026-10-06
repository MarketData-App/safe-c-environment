static volatile int seeded_input = 5;

static int seeded_adjust(int start) {
    int value = 0;
    if (start > 3) {
        value = 1;
    }
    value = 2;
    return value + start;
}

int main(void) {
    const int result = seeded_adjust(seeded_input);
    return result == 7 ? 0 : 1;
}
