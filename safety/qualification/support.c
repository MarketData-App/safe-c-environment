#include "support.h"
#include <pthread.h>
#include <sched.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
__attribute__((noinline)) char *fixture_allocate(void) {
    char *p = malloc(10);
    if (p)
        memset(p, 0, 10);
    return p;
}
__attribute__((noinline)) void fixture_write(char *p, size_t i) { p[i] = 7; }
__attribute__((noinline)) void fixture_release(char *p) { free(p); }
__attribute__((noinline)) int fixture_read(const char *p) { return p[5]; }
__attribute__((noinline)) void fixture_escape(int *p) { *p = 0; }
__attribute__((noinline)) int *fixture_stack(void) {
    int x = 0;
    fixture_escape(&x);
    return &x;
}
__attribute__((noinline)) void fixture_leak(size_t n) {
    char *p = malloc(n);
    if (!p)
        exit(2);
    memset(p, 0, n);
    printf("allocation %p\n", (void *)p);
    if (fixture_read(p) != 0)
        exit(3);
}
__attribute__((noinline)) void *fixture_fail_realloc(void *p, size_t n) {
    (void)p;
    (void)n;
    return NULL;
}
static volatile int shared;
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static atomic_int ready;
static int synchronized;
static int observed;
static void start_workers(void) {
    atomic_fetch_add_explicit(&ready, 1, memory_order_relaxed);
    while (atomic_load_explicit(&ready, memory_order_relaxed) < 2) {
    }
}
static void *writer_worker(void *unused) {
    (void)unused;
    start_workers();
    for (int i = 1; i <= 10000; ++i) {
        if (synchronized)
            pthread_mutex_lock(&lock);
        shared = i;
        if (synchronized)
            pthread_mutex_unlock(&lock);
        if ((i % 256) == 0)
            (void)sched_yield();
    }
    return NULL;
}
static void *reader_worker(void *unused) {
    (void)unused;
    start_workers();
    for (int i = 0; i < 10000; ++i) {
        if (synchronized)
            pthread_mutex_lock(&lock);
        observed = shared;
        if (synchronized)
            pthread_mutex_unlock(&lock);
        if ((i % 256) == 0)
            (void)sched_yield();
    }
    return NULL;
}
int fixture_threads(int safe) {
    pthread_t threads[2];
    shared = 0;
    observed = 0;
    synchronized = safe;
    atomic_store(&ready, 0);
    if (pthread_create(&threads[0], NULL, writer_worker, NULL) != 0)
        return 2;
    if (pthread_create(&threads[1], NULL, reader_worker, NULL) != 0)
        exit(2);
    if (pthread_join(threads[0], NULL) != 0)
        return 2;
    if (pthread_join(threads[1], NULL) != 0)
        return 2;
    return shared != 10000 || observed < 0 || observed > 10000 ? 1 : 0;
}
