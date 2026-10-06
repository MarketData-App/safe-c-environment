#define _POSIX_C_SOURCE 200809L

#include <pthread.h>
#include <stddef.h>

static int seeded_counter;

static void *seeded_worker(void *argument) {
    (void)argument;
    for (int round = 0; round < 1000; ++round) {
        seeded_counter = seeded_counter + 1;
    }
    return NULL;
}

int main(void) {
    pthread_t thread;
    if (pthread_create(&thread, NULL, seeded_worker, NULL) != 0) {
        return 1;
    }
    for (int round = 0; round < 1000; ++round) {
        seeded_counter = seeded_counter + 1;
    }
    if (pthread_join(thread, NULL) != 0) {
        return 1;
    }
    return 0;
}
