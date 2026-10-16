#include "bd_wire.h"

#include <stdio.h>

/* Usage: bd-kernel --self-check | --input PATH --records N --loops L
 * [--handshake] [--output PATH]. All behaviour is in bd_kernel_cli_main
 * (specs/project/bd_wire.md). */

int main(int argc, char **argv) { return bd_kernel_cli_main(argc, argv, stdin, stdout, stderr); }
