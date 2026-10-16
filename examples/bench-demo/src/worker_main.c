#include "bd_wire.h"

#include <stdio.h>

/* Usage: bd-worker --stdio | --shm-in FD --shm-out FD. All behaviour is in
 * bd_worker_main (specs/project/bd_wire.md). */

int main(int argc, char **argv) { return bd_worker_main(argc, argv, stderr); }
