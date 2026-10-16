/* Modified file. Origin: LLVM compiler-rt/test/asan/TestCases/use-after-free.cpp
 * at llvm-project revision cd708029e0b2869e80abe31ddb175f7c35361f90.
 * License: Apache-2.0 WITH LLVM-exception; see
 * third_party/originals/llvm/llvm-project/compiler-rt/LICENSE.TXT.
 * Changed by MarketData-App (C17 qualification fixture); the full change is
 * third_party/patches/C05.patch. */
#include "support.h"
#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(int argc, char **argv) {
    (void)argc;
    (void)argv;
    char *p = fixture_allocate();
    if (!p)
        return 2;
    fixture_release(p);
    return fixture_read(p);
}
