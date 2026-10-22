#include "pl_kernel_cli.h"
#include <stdio.h>

/* Usage: specs/project/batch.md. All behaviour is in pl_kernel_main. */
int main(int argc, char **argv) { return pl_kernel_main(argc, argv, stdout, stderr); }
