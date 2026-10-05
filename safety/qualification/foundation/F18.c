#define _POSIX_C_SOURCE 200809L
#include "dependency-identity.h"
#include "sc-foundation.h"
#include <pthread.h>
#include <stdlib.h>
static pthread_barrier_t iteration_gate;

typedef struct {
    pthread_mutex_t mutex;
    pthread_cond_t condition;
    GBytes *published;
    guint counter;
} State;
typedef struct {
    State *state;
    gboolean publisher;
} Worker;
static void lock(pthread_mutex_t *mutex) {
    if (pthread_mutex_lock(mutex) != 0)
        exit(70);
}
static void unlock(pthread_mutex_t *mutex) {
    if (pthread_mutex_unlock(mutex) != 0)
        exit(70);
}
static void *work(void *opaque) {
    Worker *worker = opaque;
    State *state = worker->state;
    GBytes *retained = NULL;
    if (worker->publisher) {
        const guint8 input[] = {0x12, 0x34};
        GBytes *value = NULL;
        if (!sc_bytes_copy(input, 2, 2, &value, NULL))
            exit(71);
        lock(&state->mutex);
        state->published = value;
        retained = g_bytes_ref(value);
        if (pthread_cond_signal(&state->condition) != 0)
            exit(70);
        unlock(&state->mutex);
    } else {
        lock(&state->mutex);
        while (state->published == NULL) {
            if (pthread_cond_wait(&state->condition, &state->mutex) != 0)
                exit(70);
        }
        retained = g_bytes_ref(state->published);
        unlock(&state->mutex);
    }
    for (guint i = 0; i < 1000; i += 1) {
        guint16 value = 0;
        if (!sc_bytes_read_u16be(retained, 0, &value, NULL) || value != 0x1234)
            exit(72);

        int arrived = pthread_barrier_wait(&iteration_gate);
        if (arrived != 0 && arrived != PTHREAD_BARRIER_SERIAL_THREAD) {
            return NULL;
        }
#if !FOUNDATION_NEGATIVE
        lock(&state->mutex);
#endif
        state->counter += 1;
#if !FOUNDATION_NEGATIVE
        unlock(&state->mutex);
#endif
    }
    g_bytes_unref(retained);
    return NULL;
}
int main(void) {
    if (pthread_barrier_init(&iteration_gate, NULL, 2) != 0) {
        return 2;
    }
    if (sc_dependency_identity() != 0)
        return 3;
    State state = {PTHREAD_MUTEX_INITIALIZER, PTHREAD_COND_INITIALIZER, NULL, 0};
    Worker workers[2] = {{&state, TRUE}, {&state, FALSE}};
    pthread_t threads[2];
    if (pthread_create(&threads[0], NULL, work, &workers[0]) != 0)
        return 70;
    if (pthread_create(&threads[1], NULL, work, &workers[1]) != 0)
        return 70;
    if (pthread_join(threads[0], NULL) != 0 || pthread_join(threads[1], NULL) != 0)
        return 70;
    gboolean correct = state.counter == 2000;
    g_bytes_unref(state.published);
    if (pthread_cond_destroy(&state.condition) != 0 || pthread_mutex_destroy(&state.mutex) != 0)
        return 70;
    (void)pthread_barrier_destroy(&iteration_gate);
    return correct ? 0 : 1;
}
