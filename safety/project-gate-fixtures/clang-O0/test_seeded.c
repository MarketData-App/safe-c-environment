static volatile int seeded_input = 0;

int main(void) {
    int value = seeded_input;
    value = value;
    return value;
}
