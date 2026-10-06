#include "greeting.h"

#include <stdio.h>

/* Usage: hello NAME. All behaviour is in greeting_main (specs/project/greeting.md). */

int main(int argc, char **argv) { return greeting_main(argc, argv, stdout, stderr); }
