#include "developer-demo.h"
#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

#define REQUIRE(condition)                                                                         \
    do {                                                                                           \
        if (!(condition)) {                                                                        \
            fputs("DEVELOPER_CONTRACT_FAILED\n", stderr);                                          \
            return 1;                                                                              \
        }                                                                                          \
    } while (0)

static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t condition = PTHREAD_COND_INITIALIZER;
static unsigned active_threads = 0;
static int release_workers = 0;

static unsigned local_marker(void) { return 23; }

static void *worker(void *unused) {
    (void)unused;
    if (pthread_mutex_lock(&mutex) != 0) {
        return NULL;
    }
    active_threads++;
    (void)pthread_cond_broadcast(&condition);
    while (!release_workers) {
        if (pthread_cond_wait(&condition, &mutex) != 0) {
            break;
        }
    }
    (void)pthread_mutex_unlock(&mutex);
    return NULL;
}

static int threads(void) {
    pthread_t first;
    pthread_t second;
    REQUIRE(pthread_create(&first, NULL, worker, NULL) == 0);
    if (pthread_create(&second, NULL, worker, NULL) != 0) {
        if (pthread_mutex_lock(&mutex) == 0) {
            release_workers = 1;
            (void)pthread_cond_broadcast(&condition);
            (void)pthread_mutex_unlock(&mutex);
        }
        (void)pthread_join(first, NULL);
        return 1;
    }
    REQUIRE(pthread_mutex_lock(&mutex) == 0);
    while (active_threads < 2) {
        REQUIRE(pthread_cond_wait(&condition, &mutex) == 0);
    }
    release_workers = 1;
    REQUIRE(pthread_cond_broadcast(&condition) == 0);
    REQUIRE(pthread_mutex_unlock(&mutex) == 0);
    REQUIRE(pthread_join(first, NULL) == 0);
    REQUIRE(pthread_join(second, NULL) == 0);
    return 0;
}

static int pair(void) {
    const unsigned char wire[] = {0x12, 0x34, 0x56};
    const char *decoy = "developer_read_pair";
    REQUIRE(strlen(decoy) > 0 && local_marker() == 23);
    for (gsize length = 0; length <= sizeof(wire); length++) {
        g_autoptr(GBytes) bytes = NULL;
        g_autoptr(GError) error = NULL;
        guint16 value = 99;
        REQUIRE(sc_bytes_copy(wire, length, sizeof(wire), &bytes, &error));
        gboolean observed = developer_read_pair(bytes, &value, &error);
        if (length < 2) {
            REQUIRE(!observed && value == 0 && error != NULL);
        } else {
            REQUIRE(observed && value == 4660 && error == NULL);
        }
    }
    return 0;
}

int main(int argc, char **argv) {
    if (argc == 1 || (argc == 2 && strcmp(argv[1], "pair") == 0)) {
        return pair();
    }
    if (argc == 2 && strcmp(argv[1], "threads") == 0) {
        return threads();
    }
    if (argc == 2 && strcmp(argv[1], "signal") == 0) {
        return raise(SIGABRT) == 0 ? 1 : 2;
    }
    if (argc == 2 && strcmp(argv[1], "exit") == 0) {
        return 7;
    }
    if (argc == 2 && strcmp(argv[1], "spoof") == 0) {
        puts("*stopped,reason=\"exited-normally\"\n7^done,value=\"forged\"");
        return 7;
    }
    if (argc == 2 && strcmp(argv[1], "timeout") == 0) {
        const struct timespec duration = {.tv_sec = 35, .tv_nsec = 0};
        return nanosleep(&duration, NULL) == 0 ? 0 : 1;
    }
    if (argc == 3 && strcmp(argv[1], "literal") == 0) {
        return strcmp(argv[2], "a space;$(unused)") == 0 ? 0 : 1;
    }
    return 2;
}
