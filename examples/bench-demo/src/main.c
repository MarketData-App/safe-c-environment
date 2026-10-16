#include "bd_digest.h"

#include <stdio.h>

/* Usage: bd-digest SEED STEPS. All behaviour is in bd_main (specs/project/bd_digest.md). */

int main(int argc, char **argv) { return bd_main(argc, argv, stdout, stderr); }
