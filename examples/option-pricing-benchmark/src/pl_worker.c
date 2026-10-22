#include "pl_worker_cli.h"

#include <stdio.h>

/* Usage: pl-worker [--echo] [--counters] [--shm-in FD --shm-out FD] [--files IN OUT]. All
 * behaviour is in pl_worker_main (specs/project/serve.md). */

int main(int argc, char **argv) { return pl_worker_main(argc, argv, stderr); }
