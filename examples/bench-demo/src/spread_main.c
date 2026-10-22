#include "bd_spread.h"

#include <stdio.h>

/* Usage: bd-spread (no argument). All behaviour is in bd_spread_cli_main
 * (specs/project/bd_spread.md). */

int main(int argc, char **argv) { return bd_spread_cli_main(argc, argv, stdout, stderr); }
